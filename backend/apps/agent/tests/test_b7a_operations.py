"""Persistent B7A acceptance on PostgreSQL, including real B0/B3/B6 boundaries."""
from .legacy_pending import seed_pending
import copy
import uuid
from datetime import timedelta
from unittest.mock import patch, Mock
from django.core.exceptions import ValidationError
from django.db import connection, transaction, DatabaseError
from django.test import TestCase
from django.utils import timezone
from apps.agent import operations, durable, matter_binding as binding, goals, confirmations, tools
from apps.agent.capabilities import OPERATIONS, EFFECTS, WRITE_BUSINESS
from apps.agent.models import ConversationOperation, ConversationGoal, Conversation, TurnWork
from apps.agent.operation_permission import actor_permission
from apps.agent.operation_schema import InvalidParameters
from apps.agent.turn_changes import TurnChanges
from apps.patients.models import Owner, Pet
from apps.appointments.models import Appointment
from apps.organizations.models import Organization, OrganizationSchedule
from apps.users.models import User
from . import test_b6_binding as b6


class OperationFixtures:
    inbound = b6.B6BindingTests.inbound
    claim = b6.B6BindingTests.claim

    def setUp(self):
        b6.B6BindingTests.setUp(self)
        self.vet = User.objects.create(organization=self.org, username='b7a-vet', role='VET')
        for weekday in range(1, 8):
            OrganizationSchedule.objects.update_or_create(organization=self.org, weekday=weekday,
                defaults=dict(opens_at='08:00', closes_at='20:00', is_closed=False))
        self.day = (timezone.now() + timedelta(days=3)).date().isoformat()
        self.inbound('Cita para Luna ' + self.day + ' 10:00 consulta')
        self.witness = self.claim()
        self.ctx = durable.context_for_work(self.witness)
        self.goal = ConversationGoal.objects.create(organization=self.org, conversation=self.conv,
                                                     name=goals.SCHEDULE)
        self.change({'owner': self.owner.pk, 'pet': self.luna.pk, 'date': self.day,
                     'time': '10:00', 'service': 'consulta', 'reason': 'consulta'})
        self.observe_slot()

    def change(self, updates):
        binding.change(self.goal, self.conv, updates, context=self.ctx,
            message_id=self.ctx.anchor.message_id, expected_revision=self.goal.binding_revision,
            correction=bool(self.goal.binding_revision))

    def observe_slot(self):
        values = binding.values(self.goal)
        start = values['time']
        binding.record_derived(self.goal, self.conv, 'selected_slot',
            {'date': values['date'], 'time': start, 'end_time': start[:3] + '30', 'available': True},
            context=self.ctx, message_id=self.ctx.anchor.message_id,
            expected_snapshot=binding.snapshot(self.goal), tool='check_appointment_slot',
            observed_at=timezone.now())

    def prepare(self, capability='create_appointment', **overrides):
        args = dict(witness=self.witness, goal_id=self.goal.pk, capability=capability,
            expected_binding_revision=self.goal.binding_revision,
            expected_identity_revision=self.conv.contact.authorization_revision)
        args.update(overrides)
        return operations.prepare_operation(**args)

    def next_turn(self, text='Mejor 11:00'):
        durable.finalize_turn(self.witness)
        self.inbound(text)
        self.witness = self.claim()
        self.ctx = durable.context_for_work(self.witness)

    def bind_appointment(self, *, name=goals.CANCEL, pet=None):
        self.goal.name = name
        self.goal.save(update_fields=['name'])
        self.change({'owner': self.owner.pk, 'pet': self.luna.pk, 'date': self.day,
                     'time': '10:00', 'reason': 'consulta'})
        appt = Appointment.objects.create(organization=self.org, pet=pet or self.luna,
            date=self.day, start_time='15:00', end_time='15:30', reason='Consulta')
        handle = tools._add_ref(self.conv, 'cita', appt.public_id)
        tools._save_refs(self.conv)
        binding.record_derived(self.goal, self.conv, 'appointment_candidates', [{'handle': handle}],
            context=self.ctx, message_id=self.ctx.anchor.message_id,
            expected_snapshot=binding.snapshot(self.goal), tool='get_appointments', observed_at=timezone.now())
        self.change({'appointment': appt.pk})
        return appt


class ConversationOperationTests(OperationFixtures, TestCase):
    def test_model_initial_contract(self):
        operation = self.prepare()
        self.assertIsInstance(operation.operation_key, uuid.UUID)
        self.assertEqual(operation.consent_state, 'PENDING')
        self.assertEqual(operation.execution_state, 'NOT_STARTED')
        self.assertIsNone(operation.proposal_message_id)
        self.assertEqual(operation.parameters_schema_version, 1)
        self.assertEqual(len(operation.parameters_digest), 64)
        self.assertEqual(operation.binding_revision, self.goal.binding_revision)
        self.assertEqual(operation.identity_revision, self.conv.contact.authorization_revision)
        self.assertEqual(operation.ownership_epoch, self.witness.ownership_epoch)
        self.assertEqual(operation.source_turn_id, self.witness.turn_work_id)
        self.assertEqual(operation.source_message_id, self.ctx.anchor.message_id)
        self.assertAlmostEqual((operation.expires_at-operation.created_at).total_seconds(), 1800, delta=3)

    def test_parameters_and_bindings_are_immutable_even_without_validation(self):
        operation = self.prepare()
        changes = dict(operation_key=uuid.uuid4(), operation_kind='CANCEL_APPOINTMENT',
            parameters={'appointment_id': 9}, parameters_digest='0'*64, pet_id=self.max.pk,
            appointment_id=1, binding_revision=99, identity_revision=99,
            ownership_epoch=99, expires_at=timezone.now(), preconditions={'schema': 2})
        for field, value in changes.items():
            with self.subTest(field=field):
                operation.refresh_from_db()
                setattr(operation, field, value)
                with self.assertRaises(ValidationError):
                    operation.save(validate=False)
        operation.refresh_from_db()
        operation.parameters = {**operation.parameters, 'start_time': '10:05'}
        operation.parameters_digest = operations.digest(operation.operation_kind, operation.parameters,
            bindings=operations.digest_bindings(operation))
        with self.assertRaisesMessage(ValidationError, 'immutable'):
            operation.save(validate=False)

    def test_queryset_and_bulk_mutation_are_rejected(self):
        op = self.prepare()
        for manager in (ConversationOperation.objects, ConversationOperation.all_objects):
            with self.assertRaises(ValidationError):
                manager.filter(pk=op.pk).update(parameters={})
            with self.assertRaises(ValidationError):
                manager.bulk_update([op], ['parameters'])
            with self.assertRaises(ValidationError):
                manager.bulk_create([op])

    def test_b7a_cannot_authorize_reject_or_execute(self):
        op = self.prepare()
        for field, value in [('consent_state', 'AUTHORIZED'), ('consent_state', 'REJECTED'),
                             ('execution_state', 'SUCCEEDED'), ('execution_state', 'FAILED'),
                             ('execution_state', 'UNCERTAIN'), ('authorized_at', timezone.now()),
                             ('proposal_message_id', self.ctx.anchor.message_id)]:
            op.refresh_from_db()
            setattr(op, field, value)
            with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                op.save(validate=False)
        with self.assertRaises(ValidationError):
            ConversationOperation.objects.all().retire_pending('AUTHORIZED', 'unsafe')

    def test_same_turn_retry_has_one_row(self):
        first, second = self.prepare(), self.prepare()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.operation_key, second.operation_key)
        self.assertEqual(ConversationOperation.objects.count(), 1)

    def test_same_turn_changed_payload_rejected(self):
        first = self.prepare()
        self.change({'time': '11:00'})
        self.observe_slot()
        with self.assertRaisesMessage(operations.PreparationDenied, 'causal_payload_conflict'):
            self.prepare()
        first.refresh_from_db()
        self.assertEqual(first.consent_state, 'INVALIDATED')
        self.assertEqual(ConversationOperation.objects.count(), 1)

    def test_replacement_chain_new_turn_and_immutable_history(self):
        a = self.prepare()
        self.next_turn()
        self.change({'time': '11:00'})
        self.observe_slot()
        b = self.prepare()
        self.next_turn('Mejor para Max')
        self.change({'pet': self.max.pk})
        self.observe_slot()
        c = self.prepare()
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual((a.consent_state, b.consent_state, c.consent_state), ('INVALIDATED', 'INVALIDATED', 'PENDING'))
        self.assertEqual((b.replaces_id, c.replaces_id), (a.pk, b.pk))
        self.assertEqual(len({x.operation_key for x in (a,b,c)}), 3)
        self.assertEqual(len({x.parameters_digest for x in (a,b,c)}), 3)
        self.assertEqual(a.parameters['start_time'], '10:00')
        self.assertEqual(c.pet_id, self.max.pk)
        a.replaces = c
        with self.assertRaises(ValidationError):
            a.save()

    def test_revision_race_old_operation_immediately_invalidated(self):
        op = self.prepare()
        old = self.goal.binding_revision
        self.next_turn('Mejor Max')
        self.change({'pet': self.max.pk})
        op.refresh_from_db()
        self.assertEqual(op.consent_state, 'INVALIDATED')
        with self.assertRaisesMessage(operations.PreparationDenied, 'binding_revision_stale'):
            self.prepare(expected_binding_revision=old)
        self.assertIsNone(confirmations.current_operation(self.conv))

    def test_abandoned_matter_retires_pending(self):
        op = self.prepare()
        goals.close(self.goal, ConversationGoal.STATUS_ABANDONED)
        op.refresh_from_db()
        self.assertEqual(op.consent_state, 'INVALIDATED')

    def test_expiry_is_distinct_and_does_not_mutate_business(self):
        op = self.prepare()
        with patch('apps.agent.operations.timezone.now', return_value=op.expires_at+timedelta(seconds=1)):
            op = operations.revalidate(op)
        self.assertEqual(op.consent_state, 'EXPIRED')
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(Pet.objects.filter(is_generic=False).count(), 2)
        with self.assertRaises(operations.PreparationDenied):
            self.prepare()

    def test_permission_01_own_entity_allowed(self):
        self.assertEqual(actor_permission(self.conv, self.goal, 'create_appointment').result, 'ALLOWED_TO_PROPOSE')
        self.assertEqual(self.prepare().owner_id, self.owner.pk)

    def test_permission_02_unidentified_denied(self):
        contact = self.conv.contact
        contact.verification_level = 'phone_match'
        contact.save()
        with self.assertRaisesMessage(operations.PreparationDenied, 'REQUIRES_IDENTITY'):
            self.prepare()
        self.assertFalse(ConversationOperation.objects.exists())

    def test_permission_03_other_owner_rejected(self):
        other = Owner.objects.create(organization=self.org, name='Other')
        ConversationGoal.objects.filter(pk=self.goal.pk).update(bound_owner=other)
        with self.assertRaisesMessage(operations.PreparationDenied, 'FORBIDDEN'):
            self.prepare()

    def test_permission_04_family_read_does_not_grant_cancel(self):
        self.bind_appointment()
        self.conv.contact.linked_via = 'family_challenge'
        self.conv.contact.save()
        self.assertTrue(tools._verification_ok(self.conv, 'confirmed_in_chat'))
        self.assertEqual(actor_permission(self.conv, self.goal, 'cancel_appointment').result, 'FORBIDDEN')
        with self.assertRaises(operations.PreparationDenied):
            self.prepare('cancel_appointment')

    def test_family_create_allowed_but_attendance_and_registration_not_inherited(self):
        self.conv.contact.linked_via = 'family_challenge'
        self.conv.contact.save()
        self.assertIsNotNone(self.prepare())
        for capability in ('confirm_appointment', 'register_pet_only', 'reschedule_appointment'):
            self.assertEqual(actor_permission(self.conv, self.goal, capability).result, 'FORBIDDEN')

    def test_permission_05_identity_revision_changes_invalidate(self):
        op = self.prepare()
        old = self.conv.contact.authorization_revision
        self.conv.contact.verified_at = timezone.now()
        self.conv.contact.save(update_fields=['verified_at'])
        op.refresh_from_db()
        self.assertEqual(op.consent_state, 'INVALIDATED')
        self.assertEqual(self.conv.contact.authorization_revision, old+1)
        with self.assertRaisesMessage(operations.PreparationDenied, 'identity_revision_stale'):
            self.prepare(expected_identity_revision=old)

    def test_identity_stale_writer_cannot_undo_revocation(self):
        from apps.agent.models import ContactIdentity
        stale = ContactIdentity.objects.get(pk=self.conv.contact_id)
        contact = self.conv.contact
        contact.auto_rematch_blocked = True
        contact.owner = None
        contact.save()
        stale.verified_at = timezone.now()
        with self.assertRaises(ValidationError):
            stale.save()

    def test_identity_ttl_ambiguous_and_revoked(self):
        for changes, result in [({'verified_at': timezone.now()-timedelta(days=183)}, 'REQUIRES_IDENTITY'),
                ({'verified_at': timezone.now(), 'is_ambiguous': True}, 'REQUIRES_STEP_UP'),
                ({'is_ambiguous': False, 'auto_rematch_blocked': True}, 'REQUIRES_STEP_UP')]:
            for key, value in changes.items():
                setattr(self.conv.contact, key, value)
            self.conv.contact.save()
            with self.assertRaisesMessage(operations.PreparationDenied, result):
                self.prepare()

    def test_permission_06_takeover_fences_preparation(self):
        op = self.prepare()
        with transaction.atomic():
            conv = Conversation.objects.select_for_update().get(pk=self.conv.pk)
            durable.invalidate_ownership(conv, reason='human_takeover')
            conv.state = Conversation.STATE_HUMAN_ACTIVE
            conv.save(update_fields=['state'])
        op.refresh_from_db()
        self.assertEqual(op.consent_state, 'INVALIDATED')
        with self.assertRaises(durable.OwnershipLost):
            self.prepare()
        self.assertIsNone(op.proposal_message_id)

    def test_safety_handoff_blocks_definition(self):
        from apps.agent.models import HumanHandoff
        HumanHandoff.objects.create(organization=self.org, conversation=self.conv, reason_code='emergency')
        with self.assertRaisesMessage(operations.PreparationDenied, 'human_handoff'):
            self.prepare()

    def test_pending_handoff_revalidation_invalidates_without_emission(self):
        from apps.agent.models import HumanHandoff
        op = self.prepare()
        HumanHandoff.objects.create(organization=self.org, conversation=self.conv, reason_code='emergency')
        op = operations.revalidate(op)
        self.assertEqual(op.consent_state, 'INVALIDATED')
        self.assertIsNone(op.proposal_message_id)
        self.assertEqual(op.execution_state, 'NOT_STARTED')

    def test_inactive_contact_cannot_prepare(self):
        self.conv.contact.is_active = False
        self.conv.contact.save(update_fields=['is_active'])
        with self.assertRaisesMessage(operations.PreparationDenied, 'FORBIDDEN'):
            self.prepare()

    def test_lease_expiry_after_insert_rolls_back_definition(self):
        def expire(witness):
            self.assertTrue(ConversationOperation.objects.exists())
            raise durable.OwnershipLost('expired')
        with patch('apps.agent.durable.check_turn_deadline', side_effect=expire):
            with self.assertRaises(durable.OwnershipLost):
                self.prepare()
        self.assertFalse(ConversationOperation.objects.exists())

    def test_cross_tenant_pet_rejected(self):
        org = Organization.objects.create(name='Other')
        owner = Owner.objects.create(organization=org, name='Other')
        pet = Pet.objects.create(organization=org, owner=owner, name='Other')
        ConversationGoal.objects.filter(pk=self.goal.pk).update(bound_pet=pet)
        with self.assertRaises(operations.PreparationDenied):
            self.prepare()
        self.assertFalse(ConversationOperation.objects.exists())

    def test_cross_tenant_appointment_rejected(self):
        org = Organization.objects.create(name='Other')
        owner = Owner.objects.create(organization=org, name='Other')
        pet = Pet.objects.create(organization=org, owner=owner, name='Other')
        appt = Appointment.objects.create(organization=org, pet=pet, date=self.day,
            start_time='12:00', end_time='12:30', reason='Other')
        ConversationGoal.objects.filter(pk=self.goal.pk).update(bound_appointment=appt)
        with self.assertRaises(operations.PreparationDenied):
            self.prepare()

    def test_new_inbound_during_preparation_requires_next_turn(self):
        self.inbound('Mejor Max')
        with self.assertRaisesMessage(operations.PreparationDenied, 'new_input'):
            self.prepare()

    def test_renderer_distinguishes_pet_and_time_and_is_deterministic(self):
        a = self.prepare()
        self.assertEqual(operations.render(a), operations.render(a))
        self.assertIn('Luna', operations.render(a))
        self.assertIn('10:00', operations.render(a))
        self.next_turn('Mejor Max 11:00')
        self.change({'pet': self.max.pk, 'time': '11:00'})
        self.observe_slot()
        b = self.prepare()
        self.assertIn('Max', operations.render(b))
        self.assertIn('11:00', operations.render(b))
        self.assertNotEqual(operations.render(a), operations.render(b))

    def test_cancel_reschedule_attendance_definitions(self):
        self.bind_appointment()
        cancel = self.prepare('cancel_appointment')
        self.assertIn('Cancelar', operations.render(cancel))
        self.next_turn('Reprogramar')
        self.bind_appointment(name=goals.RESCHEDULE)
        self.observe_slot()
        moved = self.prepare('reschedule_appointment')
        self.assertIn('Reprogramar', operations.render(moved))
        self.assertIn('15:00', operations.render(moved))
        self.assertNotEqual(cancel.parameters_digest, moved.parameters_digest)
        self.next_turn('Asistencia')
        self.bind_appointment(name='confirm_appointment')
        attendance = self.prepare('confirm_appointment')
        self.assertEqual(attendance.parameters['target_status'], 'confirmed')
        self.assertEqual(attendance.authorization_mode, 'CONTEXTUAL_DECLARATION')

    def test_appointment_domain_change_invalidates(self):
        appointment = self.bind_appointment()
        op = self.prepare('cancel_appointment')
        appointment.status = 'canceled'
        appointment.save(update_fields=['status'])
        self.assertEqual(operations.revalidate(op).consent_state, 'INVALIDATED')

    def test_appointment_correction_creates_new_exact_definition(self):
        first_appointment = self.bind_appointment()
        old = self.prepare('cancel_appointment')
        self.next_turn('No, la otra cita')
        second_appointment = self.bind_appointment()
        current = self.prepare('cancel_appointment')
        old.refresh_from_db()
        self.assertEqual(old.appointment_id, first_appointment.pk)
        self.assertEqual(old.consent_state, 'INVALIDATED')
        self.assertEqual(current.appointment_id, second_appointment.pk)
        self.assertEqual(current.replaces_id, old.pk)
        self.assertNotEqual(current.parameters_digest, old.parameters_digest)
        self.assertEqual(current.binding_revision, self.goal.binding_revision)
        self.assertEqual(current.consent_state, 'PENDING')

    def test_register_pet_from_validated_b6_fields(self):
        self.goal.name = goals.ADD_PET_ONLY
        self.goal.save()
        self.change({'owner': self.owner.pk, 'pet': None})
        for key, value in [('pet_name', 'Nala'), ('pet_species', 'felino'), ('pet_birth_date', '2020-01-02')]:
            binding.change(self.goal, self.conv, {key: value}, context=self.ctx,
                message_id=self.ctx.anchor.message_id, expected_revision=self.goal.binding_revision)
        op = self.prepare('register_pet_only')
        self.assertEqual(op.parameters, {'owner_id': self.owner.pk, 'name': 'Nala',
            'species': 'felino', 'birth_date': '2020-01-02'})
        self.assertIsNone(op.pet_id)
        self.assertIn('2020-01-02', operations.render(op))
        self.assertEqual(Pet.objects.filter(is_generic=False).count(), 2)

    def test_forged_provenance_cannot_prepare(self):
        data = copy.deepcopy(self.goal.working_state)
        data['binding']['sources']['pet']['source_message_id'] = 987654
        data['binding']['sources']['pet']['source_event_id'] = 987654
        self.goal.working_state = data
        self.goal.save()
        with self.assertRaisesMessage(operations.PreparationDenied, 'provenance_message_scope'):
            self.prepare()

    def test_slot_occupied_invalidates(self):
        op = self.prepare()
        Appointment.objects.create(organization=self.org, pet=self.max, veterinarian=self.vet,
            date=self.day, start_time='10:00', end_time='10:30', reason='Other')
        self.assertEqual(operations.revalidate(op).consent_state, 'INVALIDATED')

    def test_fi01_failure_before_persistence_recovery_no_duplicate(self):
        with patch.object(ConversationOperation, 'save', side_effect=RuntimeError('crash')):
            with self.assertRaises(RuntimeError):
                self.prepare()
        self.assertFalse(ConversationOperation.objects.exists())
        a = self.prepare()
        self.assertEqual(a.pk, self.prepare().pk)

    def test_fi02_after_persist_before_output_recovery_reuses(self):
        a = self.prepare()
        TurnWork.objects.filter(pk=self.witness.turn_work_id).update(
            lease_expires_at=timezone.now()-timedelta(seconds=1))
        self.witness = self.claim()
        self.assertEqual(a.pk, self.prepare().pk)
        self.assertIsNone(a.proposal_message_id)

    def test_fi03_postgresql_replacement_failure_is_atomic(self):
        a = self.prepare()
        self.next_turn('Preparar de nuevo')
        def fail(*args, **kwargs):
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1 / 0')
        with patch.object(ConversationOperation, 'save', fail), self.assertRaises(DatabaseError):
            self.prepare()
        a.refresh_from_db()
        self.assertEqual(a.consent_state, 'PENDING')
        self.assertEqual(ConversationOperation.objects.count(), 1)

    def test_b3_flush_prepares_without_emission(self):
        changes = TurnChanges(self.witness, self.conv)
        durable.finalize_turn(self.witness, changes=changes)
        op = ConversationOperation.objects.get()
        self.assertEqual(op.consent_state, 'PENDING')
        self.assertIsNone(op.proposal_message_id)
        self.assertFalse(self.conv.messages.filter(direction='out').exists())

    def test_b3_deferred_turn_does_not_prepare(self):
        changes = TurnChanges(self.witness, self.conv)
        self.inbound('Mejor Max')
        durable.finalize_turn(self.witness, changes=changes)
        self.assertFalse(ConversationOperation.objects.exists())

    def test_b3_identity_revision_race_cannot_republish_old_permission(self):
        changes = TurnChanges(self.witness, self.conv)
        self.conv.contact.auto_rematch_blocked = True
        self.conv.contact.save(update_fields=['auto_rematch_blocked'])
        with self.assertRaises(binding.BindingConflict):
            durable.finalize_turn(self.witness, changes=changes)
        self.assertFalse(ConversationOperation.objects.exists())

    def test_side_question_keeps_current_definition_without_new_preparation(self):
        op = self.prepare()
        self.next_turn('Cual es el horario')
        changes = TurnChanges(self.witness, self.conv)
        durable.finalize_turn(self.witness, changes=changes)
        self.assertEqual(ConversationOperation.objects.get().pk, op.pk)

    def test_new_legacy_writer_requires_causal_turn(self):
        with self.assertRaisesMessage(operations.PreparationDenied, 'source_turn_required'):
            confirmations.stage_pending(self.conv, tool='cancel_appointment', args={'id': 99}, paraphrase='LLM')
        self.assertNotIn('pending_action', self.conv.flow)

    def test_facade_ignores_llm_ids_and_paraphrase(self):
        op = confirmations.stage_pending(self.conv, tool='create_appointment',
            args={'pet_id': self.max.pk, 'consent_state': 'AUTHORIZED'}, paraphrase='Inventado',
            witness=self.witness)
        self.assertEqual(op.pet_id, self.luna.pk)
        self.assertEqual(op.consent_state, 'PENDING')
        self.assertNotIn('Inventado', operations.render(op))

    def test_identity_revision_changes_across_episodes(self):
        op = self.prepare()
        contact = self.conv.contact
        contact.is_blocked = True
        contact.save(update_fields=['is_blocked'])
        op.refresh_from_db()
        self.assertEqual(op.consent_state, 'INVALIDATED')
        self.assertNotEqual(op.identity_revision, contact.authorization_revision)

    def test_observability_events_do_not_contain_sensitive_labels(self):
        with self.assertLogs('agent.events', level='INFO') as logs, self.captureOnCommitCallbacks(execute=True):
            self.prepare()
            self.prepare()
        rows = [r for r in logs.records if r.msg.startswith('AGENT_B7A_')]
        self.assertTrue(any(r.event == 'AGENT_B7A_OPERATION_CREATED' for r in rows))
        self.assertTrue(any(r.event == 'AGENT_B7A_OPERATION_REUSED' for r in rows))
        for row in rows:
            for key in ('operation_key', 'conversation_id', 'pet_id', 'appointment_id', 'phone'):
                self.assertNotIn(key, row.__dict__)

    def test_admin_readonly_and_no_parameter_exposure(self):
        from apps.agent.admin import ConversationOperationAdmin
        from django.contrib.admin import site
        admin = ConversationOperationAdmin(ConversationOperation, site)
        self.assertNotIn('parameters', admin.fields)
        self.assertFalse(admin.has_add_permission(None))
        self.assertFalse(admin.has_change_permission(None))

    def test_new_row_with_manual_pk_cannot_bypass_service(self):
        op = self.prepare()
        op.pk += 1000000
        op.operation_key = uuid.uuid4()
        with self.assertRaises(ValidationError):
            op.save(validate=False)

    def test_legacy_pending_never_backfills_authorization_or_emission(self):
        seed_pending(self.conv, tool='create_appointment',
            args={'pet': self.luna.pk}, paraphrase='legacy')
        self.assertFalse(ConversationOperation.objects.exists())
        op = self.prepare()
        self.conv.refresh_from_db()
        self.assertIsNone(confirmations.get_pending(self.conv))
        self.assertEqual(op.consent_state, 'PENDING')
        self.assertIsNone(op.proposal_message_id)
        self.assertIsNone(op.authorization_message_id)

    def test_pending_does_not_open_any_write(self):
        self.prepare()
        from apps.agent.intake import write_is_contained
        from types import SimpleNamespace
        executor = SimpleNamespace(conversation=self.conv,
            agent_user=SimpleNamespace(organization_id=self.org.pk), record_local=Mock())
        for name, spec in OPERATIONS.items():
            self.assertEqual(EFFECTS[name], WRITE_BUSINESS)
            self.assertTrue(write_is_contained(name))
            with patch.dict(tools.TOOL_SPECS[name], handler=Mock(side_effect=AssertionError('WRITE'))):
                outcome = tools.run_tool(name, {}, conversation=self.conv, executor=executor)
            self.assertEqual(outcome.client_error, 'autonomous_writes_paused')

    def test_queries_are_scoped_and_efficient(self):
        op = self.prepare()
        self.assertEqual(operations.by_key(organization_id=self.org.pk, conversation_id=self.conv.pk,
            operation_key=op.operation_key).pk, op.pk)
        self.assertIsNone(operations.by_key(organization_id=99999, conversation_id=self.conv.pk,
            operation_key=op.operation_key))
        self.assertEqual(confirmations.current_operation(self.conv).pk, op.pk)
