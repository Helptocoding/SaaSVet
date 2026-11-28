"""Application E2E on PostgreSQL; external wire only is deterministic."""
from datetime import date, time, timedelta
import json
import os
from pathlib import Path
from unittest.mock import patch

import requests
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.agent import goals, matter_binding, operation_consent, operation_proposals
from apps.agent.models import (AgentSettings, ContactIdentity, Conversation,
    ConversationGoal, ConversationOperation, HumanHandoff, ToolExecution, TurnWork)
from apps.appointments.models import Appointment
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization, OrganizationSchedule
from apps.patients.models import Owner, Pet, PetRegistrationEffect
from apps.users.models import User
from apps.users.services import ensure_agent_user
from .b9a_harness import ApplicationHarness, answer, tool, response, write_gates
from apps.agent.tests.agent_settings_fixtures import create_enabled_agent_settings


@transaction.atomic
def seed_domain(label='A'):
    """Only domain/identity fixtures: no operation, consent or emission seed."""
    from apps.core.models import Role, Permission
    from apps.core.permissions_codes import PERMISSIONS
    org = Organization.objects.create(name='B9A TEST ' + label, timezone='UTC')
    role, _ = Role.objects.get_or_create(organization=org, name='AGENT', defaults={'is_system_role': True})
    role.permissions.set([Permission.objects.get_or_create(code=c)[0] for c in PERMISSIONS['AGENT']])
    agent, _ = ensure_agent_user(org)
    vet = User.objects.create(organization=org, username='b9a-vet-' + label, role='VET')
    create_enabled_agent_settings(org, agent_user=agent, default_veterinarian=vet)
    for day in range(1, 8):
        OrganizationSchedule.objects.update_or_create(organization=org, weekday=day,
            defaults={'opens_at': '00:00', 'closes_at': '23:59', 'is_closed': False})
    owner = Owner.objects.create(organization=org, name='Owner B9A ' + label, phone='5512345678')
    pet = Pet.objects.create(organization=org, owner=owner, name='Luna', species='perro')
    contact = ContactIdentity.objects.create(organization=org, external_id='5215512345678',
        owner=owner, verification_level='staff_verified', verified_at=timezone.now())
    channel = ChannelAccount.objects.create(organization=org, external_account_id='b9a-' + label,
        provider_credentials_ref='B9A_TOKEN')
    return org, channel, owner, pet, contact, vet


class B9AE2ETests(TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor, 'postgresql')
        self.org, self.channel, self.owner, self.pet, self.contact, self.vet = seed_domain()
        self.h = ApplicationHarness(self.channel)
        self.stack = self.h.running()
        self.stack.__enter__()
        self.addCleanup(self.stack.__exit__, None, None, None)
        self.day = (timezone.now() + timedelta(days=3)).date().isoformat()

    def tearDown(self):
        if os.environ.get('B8E_RESULTS_PATH'):
            # Test-only structured witness; never operational telemetry/PII.
            data = {'test_id': self.id(), 'http': self.h.http,
                'calls': self.h.calls,
                'wire': [{'boundary': e['boundary'], 'in_atomic': e['in_atomic']} for e in self.h.wire],
                'conversations': [self.h.snapshot(c) for c in Conversation.objects.all()],
                'operations': list(ConversationOperation.objects.values('operation_kind',
                    'consent_state', 'execution_state', 'result_code'))}
            path = Path(os.environ['B8E_RESULTS_PATH']).with_suffix('.b9a-pipeline.jsonl')
            with path.open('a', encoding='utf-8') as out:
                out.write(json.dumps(data) + '\n')
        super().tearDown()

    def public_read(self):
        self.h.llm.extend([tool('get_service_catalog'), answer()])
        inbound = self.h.inbound('¿Qué servicios ofrecen?')
        self.h.worker()
        return inbound.conversation

    def assert_pipeline(self, conv):
        work = TurnWork.objects.get(conversation=conv)
        self.assertEqual(work.status, TurnWork.COMPLETED)
        self.assertTrue(Message.objects.filter(turn_work=work, direction='in', status='processed').exists())
        for name in ('claim_turn', 'context_for_work', 'handle_inbound', 'finalize_turn'):
            self.assertTrue(any(c['function'] == name for c in self.h.calls), name)
        self.assertTrue(any(e['boundary'] == 'llm' for e in self.h.wire))
        self.assertTrue(any(e['boundary'] == 'domain' and e['status'] == 200 for e in self.h.http), self.h.http)

    def test_e2e_01_public_read_queued_accepted_delivered_read_are_distinct(self):
        conv = self.public_read()
        self.assert_pipeline(conv)
        before = self.h.snapshot(conv)
        self.assertEqual(before['outbound_queued'], 1)
        self.assertEqual(before['provider_accepted'], 0)
        self.assertEqual(before['delivered'], 0)
        self.h.sender()
        msg = Message.objects.get(conversation=conv, direction='out')
        self.assertEqual(msg.status, 'sent')
        self.assertIsNotNone(msg.send_admitted_at)
        self.assertIsNotNone(msg.provider_accepted_at)
        self.assertEqual(self.h.snapshot(conv)['delivered'], 0)
        self.h.status(msg, 'delivered')
        self.assertEqual(self.h.snapshot(conv)['delivered'], 1)
        self.h.status(msg, 'read')
        self.assertEqual(self.h.snapshot(conv)['read'], 1)

    def test_e2e_02_personal_read_uses_authenticated_domain_http(self):
        self.h.llm.extend([tool('list_my_pets'), answer()])
        msg = self.h.inbound('¿Cuáles son mis mascotas?')
        self.h.worker()
        self.h.sender()
        self.assert_pipeline(msg.conversation)
        self.assertIn('Luna', Message.objects.get(direction='out').body)
        self.assertTrue(any('/pets' in e['path'] and e['status'] == 200 for e in self.h.http))

    def test_e2e_03_duplicate_signed_http_is_one_message_and_work(self):
        self.h.llm.extend([answer()])
        first = self.h.inbound('Una pregunta sobre servicios', key='wamid.b9a.duplicate')
        second = self.h.inbound('Una pregunta sobre servicios', key='wamid.b9a.duplicate')
        self.assertEqual(first.pk, second.pk)
        self.h.worker()
        self.h.worker()
        self.assertEqual(TurnWork.objects.count(), 1)
        self.assertEqual(Message.objects.filter(direction='in').count(), 1)

    def test_e2e_04_burst_membership_then_next_turn(self):
        self.h.llm.extend([answer(), answer('El equipo puede darte más información.')])
        a = self.h.inbound('Una consulta sobre servicios')
        b = self.h.inbound('También sobre estacionamiento')
        self.h.worker()
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual(a.turn_work_id, b.turn_work_id)
        self.assertEqual(self.h.contexts[-1].inbound_ids, (a.pk, b.pk))
        self.h.sender()
        c = self.h.inbound('¿Dónde puedo consultar más detalles?')
        self.h.worker()
        c.refresh_from_db()
        self.assertNotEqual(c.turn_work_id, a.turn_work_id)
        self.assertEqual(TurnWork.objects.filter(status='COMPLETED').count(), 2)

    def test_http_signature_malformed_unknown_account_and_handshake(self):
        self.assertEqual(self.h.post({}, signature=False).status_code, 403)
        self.assertEqual(self.h.post(b'{invalid').status_code, 200)
        self.h.inbound('sin canal', account='unknown')
        self.assertEqual(Message.objects.count(), 0)
        reply = self.h.client.get('/hooks/whatsapp/', {'hub.mode': 'subscribe',
            'hub.verify_token': 'b9a-verify', 'hub.challenge': 'challenge'})
        self.assertEqual(reply.content, b'challenge')

    def test_e2e_05_caption_reply_and_action_projection(self):
        from apps.channels.events import event_from_message
        caption = self.h.inbound('', raw={'type': 'image', 'image': {'id': 'media-id',
            'caption': 'Pregunta por Luna'}, 'context': {'id': 'wamid.b9a.previous'}})
        projected = event_from_message(caption)
        self.assertEqual(projected.text, 'Pregunta por Luna')
        self.assertEqual(projected.reply_to_id, 'wamid.b9a.previous')
        action = self.h.inbound('', raw={'type': 'interactive', 'interactive': {
            'type': 'button_reply', 'button_reply': {'id': 'action-1', 'title': 'Consultar'}}})
        self.assertEqual(event_from_message(action).action_id, 'action-1')
        self.h.llm.append(answer())
        self.h.worker()
        events = {e.message_id: e for e in self.h.contexts[-1].events}
        self.assertEqual(events[caption.pk].text, 'Pregunta por Luna')
        self.assertEqual(events[caption.pk].reply_to_id, 'wamid.b9a.previous')
        self.assertEqual(events[action.pk].action_id, 'action-1')
        self.h.sender()

    def test_e2e_08_sender_known_failure(self):
        conv = self.public_read()
        self.h.meta.append(response({'error': {'code': 190}}, 401))
        self.h.sender()
        msg = Message.objects.get(conversation=conv, direction='out')
        self.assertEqual(msg.status, 'failed')
        self.assertIsNone(msg.provider_accepted_at)

    def test_e2e_09_uncertain_no_blind_retry_then_signed_reconciliation(self):
        conv = self.public_read()
        self.h.meta.append(requests.Timeout('controlled timeout'))
        self.h.sender()
        msg = Message.objects.get(conversation=conv, direction='out')
        self.assertEqual(msg.status, 'uncertain')
        count = len(self.h.wire)
        self.h.sender()
        self.assertEqual(len(self.h.wire), count)
        # No correlated provider ID: a guessed webhook must not invent a match.
        self.h.status(msg, 'delivered', provider_id='wamid.unknown')
        msg.refresh_from_db()
        self.assertEqual(msg.status, 'uncertain')

    def test_correlated_uncertain_fixture_reconciles_through_signed_status(self):
        self.public_read(); self.h.sender()
        msg = Message.objects.get(direction='out')
        self.assertIsNotNone(msg.provider_accepted_at)
        # Existing B4 recovery state with a genuinely observed provider ID;
        # unlike the lost-response case, correlation is available locally.
        Message.objects.filter(pk=msg.pk).update(status='uncertain', uncertain_at=timezone.now())
        self.h.status(msg, 'delivered')
        msg.refresh_from_db()
        self.assertEqual(msg.status, Message.STATUS_DELIVERED)
        self.assertIsNotNone(msg.delivered_at)
        self.assertEqual(sum(e['boundary'] == 'meta' for e in self.h.wire), 1)

    def test_e2e_10_human_request_keeps_case_and_honest_output(self):
        msg = self.h.inbound('Quiero hablar con una persona')
        self.h.worker()
        self.assertTrue(HumanHandoff.objects.filter(conversation=msg.conversation).exists())
        self.assertFalse(Appointment.objects.filter(source_operation__isnull=False).exists())

    def test_e2e_12_safety_precedes_llm_and_normal_write(self):
        with override_settings(AGENT_SAFETY_AUTOMATION_ENABLED=True):
            msg = self.h.inbound('Mi perro está convulsionando ahora')
            self.h.worker()
            self.h.sender()
        self.assertTrue(HumanHandoff.objects.filter(conversation=msg.conversation).exists())
        self.assertFalse(any(e['boundary'] == 'llm' for e in self.h.wire))
        self.assertEqual(ConversationOperation.objects.count(), 0)

    def test_e2e_19_duplicate_sender_does_not_repeat_acceptance(self):
        conv = self.public_read()
        self.h.sender(); self.h.sender()
        self.assertEqual(sum(e['boundary'] == 'meta' for e in self.h.wire), 1)
        self.assertEqual(self.h.snapshot(conv)['provider_accepted'], 1)

    def test_e2e_20_two_tenants_same_contact_and_provider_id_are_isolated(self):
        org, channel, *_ = seed_domain('B')
        self.h.llm.extend([answer(), answer()])
        a = self.h.inbound('Pregunta para la primera clínica', key='wamid.b9a.shared')
        other = ApplicationHarness(channel)
        b = other.inbound('Pregunta para la segunda clínica', key='wamid.b9a.shared')
        self.h.worker()
        other.worker()
        self.assertNotEqual(a.conversation_id, b.conversation_id)
        self.assertEqual(b.organization_id, org.pk)
        self.assertEqual(TurnWork.objects.count(), 2)
        self.assertTrue(all(m.organization_id == m.conversation.organization_id for m in Message.objects.all()))

    def proposal(self, kind='CREATE_APPOINTMENT'):
        if kind == 'CREATE_APPOINTMENT':
            self.h.llm.extend([tool('check_appointment_slot', date=self.day, time='10:00'), answer()])
            inbound = self.h.inbound(f'Quiero una cita para Luna {self.day} 10:00 consulta')
            self.h.worker()
        elif kind in ('CANCEL_APPOINTMENT', 'RESCHEDULE_APPOINTMENT', 'CONFIRM_ATTENDANCE'):
            from apps.appointments.creation import appointment_interval
            start, end = appointment_interval(self.org, date.fromisoformat(self.day), time(15), time(15, 30))
            self.appointment = Appointment.objects.create(organization=self.org, pet=self.pet,
                veterinarian=self.vet, date=self.day, start_time='15:00', end_time='15:30',
                start_datetime=start, end_datetime=end, timezone_at_creation='UTC', reason='consulta')
            verb = 'reprogramar' if kind == 'RESCHEDULE_APPOINTMENT' else 'cancelar'
            self.h.llm.extend([tool('get_appointments'), answer()])
            inbound = self.h.inbound(f'Quiero {verb} la cita de Luna')
            self.h.worker()
            self.h.sender()
            if kind == 'CONFIRM_ATTENDANCE':
                # Baseline has no B6 lexical opener for this goal. Fixture
                # selects the already-implemented matter; no operation or
                # consent is seeded. The next HTTP turn selects its candidate.
                goal = ConversationGoal.objects.get(conversation=inbound.conversation)
                goal.name = 'confirm_appointment'
                goal.save(update_fields=['name'])
                # A changed kind invalidates the old candidate provenance.
                # Re-observe through worker + authenticated READ, then select.
                self.h.llm.extend([tool('get_appointments'), answer()])
                self.h.inbound('Consulta la cita de Luna')
                self.h.worker()
                self.h.sender()
            if kind == 'RESCHEDULE_APPOINTMENT':
                self.h.llm.extend([tool('check_appointment_slot', date=self.day, time='10:00'), answer()])
                self.h.inbound(f'Mueve esa cita de Luna a {self.day} 10:00')
            else:
                self.h.llm.append(answer())
                self.h.inbound('Esa cita de Luna')
            self.h.worker()
        elif kind == 'REGISTER_PET':
            self.h.llm.append(answer('Necesito los datos para preparar la propuesta.'))
            inbound = self.h.inbound('Quiero registrar una mascota llamada Nala')
            self.h.worker()
            self.h.sender()
            goal = ConversationGoal.objects.get(conversation=inbound.conversation)
            # B8E intentionally did not implement a pet-data extractor. Seed
            # its explicit B6 field via the real writer with the real HTTP/C1
            # source, before the tested proposal/consent/effect sequence.
            context = self.h.contexts[-1]
            matter_binding.change(goal, inbound.conversation, {'pet_name': 'Nala'},
                context=context, message_id=inbound.pk, expected_revision=goal.binding_revision)
            self.h.llm.append(answer())
            self.h.inbound('Prepara la propuesta de registro')
            self.h.worker()
        else:
            raise ValueError(kind)
        self.assertTrue(ConversationOperation.objects.filter(conversation=inbound.conversation).exists(),
            {'goals': list(ConversationGoal.objects.filter(conversation=inbound.conversation).values()),
             'tools': list(ToolExecution.objects.filter(conversation=inbound.conversation).values()),
             'http': self.h.http})
        op = ConversationOperation.objects.get(conversation=inbound.conversation)
        self.assertEqual(op.operation_kind, kind)
        self.assertEqual(op.consent_state, 'PENDING')
        self.assertEqual(op.execution_state, 'NOT_STARTED')
        self.assertIsNotNone(op.proposal_message_id)
        if kind in ('CREATE_APPOINTMENT', 'RESCHEDULE_APPOINTMENT'):
            self.assertTrue(op.preconditions['slot_observation']['observed_at'])
        self.assertFalse(operation_proposals.is_proposal_emitted(op))
        return op

    def accept(self, op):
        self.h.sender()
        op.refresh_from_db()
        self.assertTrue(operation_proposals.is_proposal_emitted(op))
        declaration = ('SÍ CONFIRMO QUE ASISTIRÉ' if op.operation_kind == 'CONFIRM_ATTENDANCE'
            else 'CONFIRMAR ' + operation_proposals.proposal_token(op))
        self.h.client_reply(op, declaration)
        self.h.worker()
        op.refresh_from_db()
        self.assertEqual(op.consent_state, 'AUTHORIZED')
        evidence = operation_consent.authorization_evidence(op)
        self.assertEqual(evidence.operation_key, op.operation_key)
        self.assertEqual(op.execution_state, 'SUCCEEDED', op.result_code)
        self.assertTrue(ToolExecution.objects.filter(operation=op, policy_decision='confirmed').exists())
        receipt = Message.objects.get(conversation=op.conversation,
            semantic_type=Message.SEMANTIC_OPERATION_RECEIPT, operation_key=str(op.operation_key))
        self.assertEqual(receipt.status, 'pending')
        self.h.sender()
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, 'sent')
        # Passive Python call observation: the guard is called by runtime,
        # never by this test/harness or a replacement adapter.
        dispatches = [c for c in self.h.calls if c['function'] == 'execute_authorized_operation']
        self.assertEqual(len(dispatches), 1)
        self.assertEqual(dispatches[0]['caller'], 'apps.agent.operation_execution.consent_execution_output')
        self.assertTrue(any(c['function'] == 'execute' and not c['module'].startswith('apps.agent.tests')
                            for c in self.h.calls))

    def test_e2e_write_create_complete_pipeline(self):
        with write_gates():
            op = self.proposal()
            self.accept(op)
        self.assertEqual(Appointment.objects.filter(source_operation=op).count(), 1)

    def mutation_path(self, kind):
        from apps.appointments.models import AppointmentMutationEffect
        with write_gates():
            op = self.proposal(kind)
            self.accept(op)
        self.assertEqual(AppointmentMutationEffect.objects.filter(operation_id=op.operation_key).count(), 1)
        self.appointment.refresh_from_db()
        return self.appointment

    def test_e2e_write_reschedule_complete_pipeline(self):
        self.assertEqual(self.mutation_path('RESCHEDULE_APPOINTMENT').start_time, time(10))

    def test_e2e_write_cancel_complete_pipeline(self):
        self.assertEqual(self.mutation_path('CANCEL_APPOINTMENT').status, 'canceled')

    def test_e2e_write_attendance_complete_pipeline_with_existing_matter_fixture(self):
        self.assertEqual(self.mutation_path('CONFIRM_ATTENDANCE').status, 'confirmed')

    def test_e2e_write_register_complete_pipeline_with_explicit_b6_fixture(self):
        with write_gates():
            op = self.proposal('REGISTER_PET')
            self.accept(op)
        effect = PetRegistrationEffect.objects.get(operation_id=op.operation_key)
        self.assertEqual(effect.pet.name, 'Nala')
        self.assertEqual(effect.pet.owner_id, self.owner.pk)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_e2e_16_correction_retires_old_proposal_before_effect(self):
        with write_gates():
            op = self.proposal()
            self.h.sender()
            self.h.llm.extend([tool('check_appointment_slot', date=self.day, time='11:00'), answer()])
            self.h.inbound('Mejor 11:00 para Luna')
            self.h.worker()
            op.refresh_from_db()
            self.assertEqual(op.consent_state, 'INVALIDATED')
            self.h.inbound('CONFIRMAR ' + operation_proposals.proposal_token(op))
            self.h.worker()
            self.assertEqual(Appointment.objects.filter(source_operation__isnull=False).count(), 0)

    def test_e2e_17_duplicate_confirmation_and_worker_do_not_repeat_effect(self):
        with write_gates():
            op = self.proposal()
            self.accept(op)
            inbound = op.authorization_message
            original_works = TurnWork.objects.count()
            self.h.inbound(inbound.body, key=inbound.external_message_id)
            self.h.worker(); self.h.sender()
            self.assertEqual(TurnWork.objects.count(), original_works)
            self.assertEqual(Appointment.objects.filter(source_operation=op).count(), 1)
            self.assertEqual(Message.objects.filter(semantic_type='operation_receipt').count(), 1)

    def test_effect_and_consent_roll_back_with_receipt_sql_failure(self):
        with write_gates():
            op = self.proposal(); self.h.sender()
            inbound = self.h.client_reply(op, 'CONFIRMAR ' + operation_proposals.proposal_token(op))
            injected = []
            def fail(execute, sql, params, many, context):
                if not injected and sql.startswith('INSERT INTO "channels_message"'):
                    injected.append(True)
                    return execute('SELECT 1/0', (), False, context)
                return execute(sql, params, many, context)
            with connection.execute_wrapper(fail):
                self.h.worker()
            self.assertEqual(injected, [True])
            op.refresh_from_db()
            self.assertEqual(op.consent_state, 'PENDING')
            self.assertEqual(op.execution_state, 'NOT_STARTED')
            self.assertFalse(Appointment.objects.filter(source_operation=op).exists())
            self.assertFalse(ToolExecution.objects.filter(operation=op).exists())
            self.h.retry_due(inbound.conversation)
            self.h.worker(); self.h.sender()
            op.refresh_from_db()
            self.assertEqual(op.execution_state, 'SUCCEEDED', op.result_code)
            self.assertEqual(Appointment.objects.filter(source_operation=op).count(), 1)
            self.assertEqual(Message.objects.filter(semantic_type='operation_receipt', status='sent').count(), 1)

    def test_global_flags_and_b0_still_close_worker_execution(self):
        with override_settings(AGENT_B7B_CONSENT_ENABLED=True):
            op = self.proposal()
            self.h.sender()
            self.h.client_reply(op, 'CONFIRMAR ' + operation_proposals.proposal_token(op))
            self.h.worker()
            op.refresh_from_db()
            self.assertEqual(op.consent_state, 'AUTHORIZED')
            self.assertEqual(op.execution_state, 'NOT_STARTED')
            self.assertFalse(Appointment.objects.filter(source_operation=op).exists())
            self.assertFalse(any(c['function'] == 'execute_authorized_operation' for c in self.h.calls))

    def test_worker_reaches_b8a_and_denies_inactive_definition(self):
        with write_gates():
            op = self.proposal(); self.h.sender()
            # Failure injection: both ORM managers correctly prohibit editing
            # definitions. Corrupt only this lifecycle flag through SQL to
            # verify the final guard, with real consent and no direct guard call.
            with connection.cursor() as cursor:
                cursor.execute('UPDATE agent_conversationoperation SET is_active=false WHERE id=%s', [op.pk])
            self.h.client_reply(op, 'CONFIRMAR ' + operation_proposals.proposal_token(op))
            self.h.worker(); self.h.sender()
            op.refresh_from_db()
            self.assertEqual(op.consent_state, 'AUTHORIZED')
            self.assertNotEqual(op.execution_state, 'SUCCEEDED')
            self.assertEqual(op.result_code, 'scope_inactive')
            self.assertFalse(Appointment.objects.filter(source_operation=op).exists())
            self.assertTrue(any(c['function'] == 'execute_authorized_operation' for c in self.h.calls))
            self.assertFalse(any(c['function'] == 'execute' for c in self.h.calls))

    def test_llm_timeout_retry_uses_real_provider_abstraction(self):
        self.h.llm.extend([requests.Timeout('controlled'), answer()])
        self.h.inbound('Necesito información de servicios')
        self.h.worker(); self.h.sender()
        self.assertEqual(sum(e['boundary'] == 'llm' for e in self.h.wire), 2)
        self.assertEqual(TurnWork.objects.get().status, 'COMPLETED')

    def test_llm_invalid_wire_response_is_handoff_not_success(self):
        self.h.llm.append({'choices': []})
        self.h.inbound('Necesito información de servicios')
        self.h.worker(); self.h.sender()
        self.assertTrue(HumanHandoff.objects.exists())
        self.assertEqual(ConversationOperation.objects.count(), 0)

    def test_e2e_06_sql_failure_before_publication_rolls_back_then_worker_retries(self):
        self.h.llm.extend([answer(), answer()])
        inbound = self.h.inbound('Necesito información de servicios')
        injected = []
        def fail(execute, sql, params, many, context):
            if not injected and sql.startswith('INSERT INTO "channels_message"'):
                injected.append(True)
                return execute('SELECT 1/0', (), False, context)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(fail):
            self.h.worker()
        self.assertEqual(injected, [True])
        self.assertGreater(self.h.snapshot(inbound.conversation)['response_generated'], 0)
        self.assertEqual(Message.objects.filter(direction='out').count(), 0)
        self.assertEqual(TurnWork.objects.get().status, 'PENDING')
        self.h.retry_due(inbound.conversation)
        self.h.worker(); self.h.sender()
        self.assertEqual(TurnWork.objects.get().attempts, 2)
        self.assertEqual(Message.objects.filter(direction='out', status='sent').count(), 1)

    def human_client(self):
        from apps.core.models import UserRole
        from .test_inbox_api import _seed_role_from_catalog
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import RefreshToken
        user = User.objects.create(organization=self.org, username='b9a-human', role='ADMIN')
        UserRole.objects.get_or_create(user=user, role=_seed_role_from_catalog(self.org, 'ADMIN'))
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Bearer ' + str(RefreshToken.for_user(user).access_token))
        return client

    def test_e2e_11_takeover_during_llm_fences_publication(self):
        client = self.human_client()
        self.h.llm.append(answer())
        inbound = self.h.inbound('Necesito información de servicios')
        def takeover(boundary, event):
            if boundary == 'llm':
                self.assertEqual(client.post(
                    f'/api/inbox/conversations/{inbound.conversation.public_id}/claim/').status_code, 200)
        self.h.callback = takeover
        self.h.worker(); self.h.sender()
        self.assertEqual(Message.objects.filter(direction='out').count(), 0)
        self.assertEqual(TurnWork.objects.get().status, 'FAILED')

    def test_takeover_after_authorizable_proposal_blocks_write(self):
        client = self.human_client()
        with write_gates():
            op = self.proposal()
            self.h.sender()
            self.h.client_reply(op, 'CONFIRMAR ' + operation_proposals.proposal_token(op))
            self.assertEqual(client.post(f'/api/inbox/conversations/{op.conversation.public_id}/claim/').status_code, 200)
            self.h.worker(); self.h.sender()
            self.assertFalse(Appointment.objects.filter(source_operation=op).exists())

    def test_confirmation_cannot_cross_tenant_proposal_reference(self):
        with write_gates():
            a = self.proposal(); self.h.sender()
            org, channel, *_ = seed_domain('B')
            other = ApplicationHarness(channel)
            self.h.llm.extend([tool('check_appointment_slot', date=self.day, time='10:00'), answer()])
            inbound = other.inbound(f'Quiero una cita para Luna {self.day} 10:00 consulta')
            other.worker(); other.sender()
            b = ConversationOperation.objects.get(conversation=inbound.conversation)
            other.inbound('CONFIRMAR ' + operation_proposals.proposal_token(a),
                raw={'context': {'id': a.proposal_message.external_message_id}})
            other.worker()
            a.refresh_from_db(); b.refresh_from_db()
            self.assertEqual((a.consent_state, b.consent_state), ('PENDING', 'PENDING'))
            self.assertFalse(Appointment.objects.filter(source_operation__isnull=False).exists())

    def test_e2e_15_client_cannot_reply_to_pending_and_forged_early_reply_is_not_causal(self):
        with write_gates():
            op = self.proposal()
            token = 'CONFIRMAR ' + operation_proposals.proposal_token(op)
            with self.assertRaises(ValueError):
                self.h.client_reply(op, token)
            self.h.inbound(token)
            self.h.worker()
            self.h.sender()
            op.refresh_from_db()
            self.assertNotEqual(op.consent_state, 'AUTHORIZED')
            self.assertFalse(Appointment.objects.filter(source_operation=op).exists())
