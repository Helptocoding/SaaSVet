"""B6 semantic boundary acceptance on real PostgreSQL."""
from .legacy_pending import seed_pending
from django.test import TestCase
from apps.agent import matter_binding as binding
from apps.agent import matter_resolution as resolution, goals, confirmations, tools, durable, policy, prompts
from apps.agent.models import ConversationGoal, Conversation, AgentSettings, TurnWork
from apps.agent.turn_context import build_turn_context
from apps.agent.turn_changes import TurnChanges
from apps.patients.models import Owner, Pet
from apps.appointments.models import Appointment
from apps.channels.models import Message
from django.db import connection, transaction, DatabaseError
from django.utils import timezone
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace
from . import test_b3_durable as b3_fixtures
from apps.agent.tests.agent_settings_fixtures import create_enabled_agent_settings


class B6ContractTests(TestCase):
    def test_dependency_map_is_explicit(self):
        self.assertIn('appointment', binding.DEPENDENCY_RULES['pet'])
        self.assertIn('selected_slot', binding.DEPENDENCY_RULES['date'])
        self.assertNotIn('date', binding.DEPENDENCY_RULES['pet'])


class B6BindingTests(TestCase):
    inbound = b3_fixtures.DurableTurnTests.inbound
    claim = b3_fixtures.DurableTurnTests.claim

    def setUp(self):
        b3_fixtures.DurableTurnTests.setUp(self)
        self.owner = Owner.objects.create(organization=self.org, name='Owner B6', phone='5512345678')
        self.luna = Pet.objects.create(organization=self.org, owner=self.owner, name='Luna')
        self.max = Pet.objects.create(organization=self.org, owner=self.owner, name='Max')
        contact = self.conv.contact
        contact.owner = self.owner
        contact.verification_level = 'staff_verified'
        contact.verified_at = timezone.now()
        contact.save()

    def context(self, text):
        return build_turn_context(self.conv, [self.inbound(text)])

    def turn(self, text):
        self.ctx = self.context(text)
        reply = resolution.process_turn(self.conv, self.ctx)
        self.goal = binding.current_goal(self.conv)
        return reply

    def start(self):
        self.turn('Quiero una cita para Luna el jueves consulta general')
        self.assertTrue(binding.trusted(self.goal, 'pet'))

    def derived(self, key, value=None, source_type='TOOL_RESULT', dependencies=None):
        binding.record_derived(self.goal, self.conv, key, value or {'old': True},
            context=self.ctx, message_id=self.ctx.anchor.message_id,
            expected_snapshot=binding.snapshot(self.goal), source_type=source_type,
            tool='fixture_read', dependencies=dependencies)

    def pending(self):
        seed_pending(self.conv, tool='create_appointment',
                                   args={'pet': str(self.luna.public_id)}, paraphrase='Propuesta')
        return confirmations.get_pending(self.conv)

    def appointment(self, pet=None):
        return Appointment.objects.create(organization=self.org, pet=pet or self.luna,
            date=timezone.now().date(), start_time='10:00', end_time='10:30', reason='Consulta')

    def test_bind_01_pet_correction_selective(self):
        self.start()
        old_revision = self.goal.binding_revision
        date = binding.values(self.goal)['date']
        for slot in ('availability', 'selected_slot', 'vaccine_facts', 'appointment_candidates'):
            self.derived(slot)
        self.pending()
        self.turn('Mejor para Max')
        self.assertEqual(self.goal.binding_revision, old_revision + 1)
        self.assertEqual(self.goal.bound_pet_id, self.max.pk)
        self.assertEqual(binding.values(self.goal)['date'], date)
        self.assertEqual(binding.values(self.goal)['service'], 'consulta general')
        for slot in ('availability', 'selected_slot', 'vaccine_facts', 'appointment_candidates'):
            self.assertNotIn(slot, binding.values(self.goal))
        self.assertIsNone(confirmations.get_pending(self.conv))

    def test_bind_02_date_correction(self):
        self.start()
        self.derived('availability')
        self.derived('selected_slot')
        rev = self.goal.binding_revision
        self.turn('Perdón viernes')
        self.assertEqual(self.goal.binding_revision, rev + 1)
        self.assertEqual(self.goal.bound_pet_id, self.luna.pk)
        self.assertEqual(binding.values(self.goal)['service'], 'consulta general')
        self.assertNotIn('availability', binding.values(self.goal))
        self.assertNotIn('selected_slot', binding.values(self.goal))

    def test_service_correction_preserves_pet_date(self):
        self.start()
        date = binding.values(self.goal)['date']
        self.derived('price')
        self.derived('availability')
        self.turn('Mejor vacunación')
        self.assertEqual(binding.values(self.goal)['date'], date)
        self.assertEqual(self.goal.bound_pet_id, self.luna.pk)
        self.assertNotIn('price', binding.values(self.goal))
        self.assertNotIn('availability', binding.values(self.goal))

    def test_bind_03_appointment_correction_and_pending(self):
        self.start()
        a, b = self.appointment(), self.appointment()
        handles = [tools._add_ref(self.conv, 'cita', appt.public_id) for appt in (a, b)]
        tools._save_refs(self.conv)
        binding.record_derived(self.goal, self.conv, 'appointment_candidates',
            [{'handle': h} for h in handles], context=self.ctx,
            message_id=self.ctx.anchor.message_id, expected_snapshot=binding.snapshot(self.goal),
            tool='get_appointments')
        binding.change(self.goal, self.conv, {'appointment': a.pk}, context=self.ctx,
            message_id=self.ctx.anchor.message_id, expected_revision=self.goal.binding_revision)
        self.derived('appointment_facts')
        self.derived('time', '10:00', source_type='DERIVED', dependencies=('appointment',))
        old = self.pending()
        ctx = self.context('no esa, la otra cita')
        binding.change(self.goal, self.conv, {'appointment': b.pk}, context=ctx,
            message_id=ctx.anchor.message_id, expected_revision=self.goal.binding_revision, correction=True)
        self.assertEqual(self.goal.bound_appointment_id, b.pk)
        self.assertNotIn('appointment_facts', binding.values(self.goal))
        self.assertNotIn('time', binding.values(self.goal))
        self.assertFalse(confirmations.is_confirmable(self.conv, old))
        self.assertIsNone(confirmations.get_pending(self.conv))

    def test_bind_04_negation_without_replacement(self):
        self.start()
        self.assertIn('mascota', self.turn('No es para Luna'))
        self.assertIsNone(self.goal.bound_pet_id)
        self.assertIn('pet', binding.metadata(self.goal)['unresolved'])

    def test_bind_05_late_outcome_cannot_revive(self):
        self.start()
        old = binding.snapshot(self.goal)
        self.turn('Mejor para Max')
        outcome = tools.ToolOutcome(kind='READ', data=[{'private': 'Luna'}], validated=True)
        consumed = binding.consume_outcome(self.conv, 'get_vaccine_status', outcome, old, context=self.ctx)
        self.assertEqual(consumed.kind, 'ERROR')
        self.assertEqual(consumed.client_error, 'stale_binding')
        self.assertNotIn('vaccine_facts', binding.values(self.goal))

    def test_incompatible_tool_scope_cannot_enter_current_slots(self):
        self.start()
        for scope in ({}, {**tools._scope(self.conv), 'pet': str(self.max.public_id)}):
            outcome = tools.ToolOutcome(kind='READ', data=[{'private': 'wrong scope'}],
                                        validated=True, scope=scope)
            result = binding.consume_outcome(self.conv, 'get_vaccine_status', outcome,
                binding.snapshot(self.goal), context=self.ctx)
            self.assertEqual(result.kind, 'ERROR')
        self.goal.refresh_from_db()
        self.assertNotIn('vaccine_facts', binding.values(self.goal))

    def test_current_tool_scope_records_exact_result_provenance(self):
        self.start()
        observed = timezone.now()
        outcome = tools.ToolOutcome(kind='READ', data=[], validated=True,
            scope={**tools._scope(self.conv), 'pet': str(self.luna.public_id)}, observed_at=observed)
        result = binding.consume_outcome(self.conv, 'get_vaccine_status', outcome,
            binding.snapshot(self.goal), context=self.ctx, tool_execution_id=123)
        self.assertEqual(result.kind, 'READ')
        self.goal.refresh_from_db()
        provenance = self.goal.slots['vaccine_facts']['provenance']
        self.assertEqual(provenance['tool_execution_id'], 123)
        self.assertEqual(provenance['observed_at'], observed.isoformat())

    def test_bind_06_cross_tenant_and_owner_rejected(self):
        from apps.organizations.models import Organization
        self.start()
        other = Organization.objects.create(name='Other B6')
        owner = Owner.objects.create(organization=other, name='Other Owner')
        pet = Pet.objects.create(organization=other, owner=owner, name='Max')
        with self.assertRaises(ValueError):
            binding.change(self.goal, self.conv, {'pet': pet.pk}, context=self.ctx,
                message_id=self.ctx.anchor.message_id, expected_revision=self.goal.binding_revision)
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.bound_pet_id, self.luna.pk)

    def test_matter_01_single_instance(self):
        self.start()
        self.turn('para el viernes')
        self.assertEqual(ConversationGoal.objects.count(), 1)

    def test_matter_02_compound_does_not_mix(self):
        reply = self.turn('reprograma la cita de Luna y cancela la de Max')
        self.assertIn('primero', reply)
        self.assertEqual(ConversationGoal.objects.count(), 0)
        events = [self.inbound('Cancela la cita de Luna'), self.inbound('Cancela la cita de Max')]
        reply = resolution.process_turn(self.conv, build_turn_context(self.conv, events))
        self.assertIn('primero', reply)
        self.assertEqual(ConversationGoal.objects.count(), 0)

    def test_compound_preserves_existing_without_applying_one_side(self):
        self.start()
        snapshot = binding.snapshot(self.goal)
        self.turn('reprograma Luna y cancela Max')
        self.assertEqual(snapshot, binding.snapshot(self.goal))

    def test_matter_03_public_side_question(self):
        self.start()
        pk, revision = self.goal.pk, self.goal.binding_revision
        self.assertIsNone(self.turn('¿Cuánto cuesta la consulta?'))
        self.assertEqual((self.goal.pk, self.goal.binding_revision), (pk, revision))
        self.turn('el viernes')
        self.assertEqual(self.goal.pk, pk)
        self.assertEqual(self.goal.bound_pet_id, self.luna.pk)

    def test_matter_04_replace_abandons_incompatible_slots(self):
        self.start()
        old = self.goal
        self.derived('selected_slot')
        self.turn('Olvida eso quiero cancelar la cita de Luna')
        old.refresh_from_db()
        self.assertEqual(old.status, 'abandoned')
        self.assertEqual(self.goal.name, goals.CANCEL)
        self.assertNotIn('selected_slot', binding.values(self.goal))
        self.assertNotIn('date', binding.values(self.goal))

    def test_matter_05_forget_is_not_business_cancel(self):
        self.start()
        appointment = self.appointment()
        self.assertIn('No se canceló', self.turn('Olvida eso'))
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, 'scheduled')
        self.assertIsNone(self.goal)

    def test_correction_negation_survives_legacy_arbiter(self):
        from apps.agent import planner
        self.start()
        self.turn('No es Luna')
        planner._settle_commitment(self.conv, {}, self.ctx)
        self.goal.refresh_from_db()
        self.assertNotEqual(self.goal.status, ConversationGoal.STATUS_ABANDONED)
        self.assertIsNone(self.goal.bound_pet_id)
        self.assertIn('pet', binding.metadata(self.goal)['unresolved'])

    def test_b3_real_planner_correction_and_side_question(self):
        from apps.agent import planner
        from apps.agent.llm import LLMResult, StubLLMClient
        settings = create_enabled_agent_settings(self.org)
        for text in ('Quiero una cita para Luna el viernes', '¿Cuánto cuesta?', 'No es Luna'):
            self.inbound(text)
            witness = self.claim()
            context = durable.context_for_work(witness)
            changes = TurnChanges(witness, self.conv)
            with changes.activate():
                planner.handle_inbound(self.conv, turn_context=context, agent_settings=settings,
                    llm_client=StubLLMClient(scripted=[LLMResult(kind='text', text='Puedo ayudarte.')]),
                    executor=self.executor_stub())
            durable.finalize_turn(witness, changes=changes, outputs=changes.outputs)
            self.conv.refresh_from_db()
        self.goal = binding.current_goal(self.conv)
        self.assertIsNotNone(self.goal)
        self.assertIsNone(self.goal.bound_pet_id)
        self.assertIn('pet', binding.metadata(self.goal)['unresolved'])
        self.assertIn('date', binding.values(self.goal))
        self.assertEqual(ConversationGoal.objects.count(), 1)
        self.assertEqual(TurnWork.objects.filter(status=TurnWork.COMPLETED).count(), 3)

    def test_legacy_proposal_without_matter_is_not_confirmable(self):
        pending = self.pending()
        message = Message.objects.create(organization=self.org, conversation=self.conv,
            channel_account=self.channel, direction='out', author_type='agent', status='sent',
            body='Propuesta', semantic_type=Message.SEMANTIC_CONFIRMATION,
            operation_key=pending['proposal_id'])
        confirmations.bind_pending_message(self.conv, message.pk)
        self.assertFalse(confirmations.is_confirmable(self.conv, confirmations.get_pending(self.conv)))

    def test_binding_proposal_receipt_then_correction_is_not_confirmable(self):
        self.start()
        pending = self.pending()
        message = Message.objects.create(organization=self.org, conversation=self.conv,
            channel_account=self.channel, direction='out', author_type='agent', status='sent',
            body='Propuesta', semantic_type=Message.SEMANTIC_CONFIRMATION,
            operation_key=pending['proposal_id'])
        confirmations.bind_pending_message(self.conv, message.pk)
        pending = confirmations.get_pending(self.conv)
        self.assertTrue(confirmations.binding_is_current(self.conv, pending))
        self.assertFalse(confirmations.is_confirmable(self.conv, pending))  # B7B excludes legacy consent
        self.turn('Mejor para Max')
        self.assertFalse(confirmations.is_confirmable(self.conv, pending))

    def test_amb_01_same_name_and_partial(self):
        Pet.objects.create(organization=self.org, owner=self.owner, name='Luna')
        self.assertTrue(self.turn('Quiero una cita para Luna'))
        self.assertIsNone(self.goal.bound_pet_id)
        self.assertTrue(self.turn('Mejor para Lu'))
        self.assertIsNone(self.goal.bound_pet_id)

    def test_amb_02_sol_not_solo(self):
        Pet.objects.create(organization=self.org, owner=self.owner, name='Sol')
        self.turn('Solo quiero saber el precio')
        self.assertIsNone(self.goal)

    def test_amb_03_plural_then_pronoun(self):
        self.assertTrue(self.turn('¿Qué vacunas tienen Luna y Max?'))
        self.assertIsNone(self.goal.bound_pet_id)
        self.assertTrue(self.turn('Agéndale una cita'))
        self.assertIsNone(self.goal.bound_pet_id)

    def test_amb_04_immediate_unique_pronoun(self):
        self.start()
        self.assertIsNone(self.turn('¿Tiene vacunas pendientes?'))
        args, _, error = binding.guard_arguments(self.conv, 'get_vaccine_status', {}, context=self.ctx)
        self.assertIsNone(error)
        self.assertEqual(tools.resolve_handle(self.conv, args['pet_handle']), str(self.luna.public_id))

    def test_prov_01_explicit_has_causal_source(self):
        self.start()
        prov = self.goal.slots['date']['provenance']
        self.assertEqual(prov['source_type'], 'USER_EXPLICIT')
        self.assertEqual(prov['source_message_id'], self.ctx.anchor.message_id)
        self.assertEqual(prov['source_event_id'], self.ctx.anchor.message_id)

    def test_prov_additional_data_is_explicit_not_a_correction(self):
        self.turn('Quiero una cita para Luna')
        self.turn('el viernes')
        self.assertEqual(self.goal.slots['date']['provenance']['source_type'], 'USER_EXPLICIT')

    def test_prov_02_tool_has_revision_dependencies_scope(self):
        self.start()
        self.derived('vaccine_facts')
        prov = self.goal.slots['vaccine_facts']['provenance']
        self.assertEqual(prov['source_type'], 'TOOL_RESULT')
        self.assertEqual(prov['binding_revision'], self.goal.binding_revision)
        self.assertEqual(prov['scope']['pet'], self.luna.pk)
        self.assertEqual(set(prov['dependencies']), {'owner', 'pet'})

    def test_prov_03_derived_invalidation(self):
        self.start()
        self.derived('selected_slot', source_type='DERIVED')
        self.turn('Quise decir el viernes')
        self.assertNotIn('selected_slot', binding.values(self.goal))

    def test_prov_04_legacy_not_trusted(self):
        goal = ConversationGoal.objects.create(organization=self.org, conversation=self.conv,
            name=goals.SCHEDULE, slots={'pet_handle': {'value': 'mascota_1', 'confidence': 1}})
        self.assertFalse(binding.trusted(goal, 'pet'))
        self.assertEqual(binding.values(goal), {})
        self.assertEqual(goals.context_block(self.conv)['ya_tengo'], {})
        _, _, error = binding.guard_arguments(self.conv, 'get_vaccine_status', {'pet_handle': 'mascota_1'})
        self.assertEqual(error, 'binding_required')

    def test_prov_05_latest_explicit_event_wins(self):
        a, b = self.inbound('Quiero cita para Luna'), self.inbound('Es para Max')
        resolution.process_turn(self.conv, build_turn_context(self.conv, [b, a]))
        goal = binding.current_goal(self.conv)
        self.assertEqual(goal.bound_pet_id, self.max.pk)
        self.assertEqual(binding.metadata(goal)['sources']['pet']['source_message_id'], b.pk)
        self.assertEqual(binding.metadata(goal)['sources']['pet']['source_type'], 'USER_CORRECTION')

    def test_causal_cursor_uses_created_at_before_id(self):
        from datetime import timedelta
        a = self.inbound('Es para Max')
        b = self.inbound('Quiero cita para Luna')
        Message.objects.filter(pk=b.pk).update(created_at=a.created_at - timedelta(seconds=1))
        b.refresh_from_db()
        resolution.process_turn(self.conv, build_turn_context(self.conv, [a, b]))
        goal = binding.current_goal(self.conv)
        self.assertEqual(goal.bound_pet_id, self.max.pk)
        self.assertEqual(binding.metadata(goal)['sources']['pet']['source_message_id'], a.pk)

    def test_llm_cannot_replace_trusted_slot_or_provenance(self):
        self.start()
        state = goals.capture(self.goal, {'date': '2099-01-01'}, self.conv)
        self.assertIn('date', state['rejected'])
        self.assertNotEqual(binding.values(self.goal)['date'], '2099-01-01')

    def test_old_pet_handle_cannot_construct_personal_arguments(self):
        self.start()
        handle = tools._add_ref(self.conv, 'mascota', self.luna.public_id)
        tools._save_refs(self.conv)
        self.turn('Mejor Max')
        _, _, error = binding.guard_arguments(self.conv, 'get_vaccine_status', {'pet_handle': handle})
        self.assertEqual(error, 'binding_required')

    def test_availability_cannot_invent_missing_date(self):
        self.turn('Quiero una cita para Luna')
        _, _, error = binding.guard_arguments(self.conv, 'find_available_slots', {'date': '2099-01-01'})
        self.assertEqual(error, 'binding_required')

    def test_planner_rejects_stale_outcome_before_next_model_call(self):
        from apps.agent import planner
        from apps.agent.llm import LLMResult, StubLLMClient
        self.start()
        old_context = self.ctx
        old = binding.snapshot(self.goal)
        settings = create_enabled_agent_settings(self.org)
        llm = StubLLMClient(scripted=[LLMResult(kind='tool_call', tool_name='get_vaccine_status', tool_args={})])
        def stale(*args, **kwargs):
            self.turn('Mejor Max')
            return tools.ToolOutcome(kind='READ', data=[{'private': 'Luna'}], validated=True,
                scope={**tools._scope(self.conv), 'binding': old})
        with patch('apps.agent.planner.tools.run_tool', side_effect=stale):
            result = planner.handle_inbound(self.conv, agent_settings=settings, llm_client=llm,
                executor=self.executor_stub(), turn_context=old_context)
        self.assertEqual(result['decision'], 'binding_stale')
        self.assertEqual(result['llm_calls'], 1)
        self.assertFalse(Message.objects.filter(direction='out', body__contains='Luna').exists())

    def test_prompt_does_not_reuse_private_history_after_correction(self):
        self.start()
        Message.objects.create(organization=self.org, conversation=self.conv, channel_account=self.channel,
            direction='out', author_type='agent', status='sent', body='Luna_PRIVATE_FACT')
        self.turn('Mejor para Max')
        assembled = prompts.assemble_messages(self.conv, turn_context=self.ctx)
        self.assertNotIn('Luna_PRIVATE_FACT', str(assembled))

    def test_race_01_new_inbound_defers_b3_output(self):
        self.start()
        witness = self.claim()
        changes = TurnChanges(witness, self.conv)
        with changes.activate():
            from apps.agent.planner import enqueue_outbound
            enqueue_outbound(self.conv, 'Propuesta para Luna')
        self.inbound('Mejor para Max')
        durable.finalize_turn(witness, changes=changes)
        self.assertFalse(Message.objects.filter(direction='out').exists())
        self.assertEqual(TurnWork.objects.get(pk=witness.turn_work_id).outcome_code, 'deferred_to_new_input')

    def test_race_02_cas_rejects_same_revision(self):
        self.start()
        old = self.goal.binding_revision
        self.turn('Mejor Max')
        with self.assertRaises(binding.BindingConflict):
            binding.change(self.goal, self.conv, {'pet': self.luna.pk}, context=self.ctx,
                message_id=self.ctx.anchor.message_id, expected_revision=old, correction=True)

    def test_b3_staged_revision_cas(self):
        self.start()
        witness = self.claim()
        changes = TurnChanges(witness, self.conv)
        self.turn('Mejor Max')
        with self.assertRaises(binding.BindingConflict):
            durable.finalize_turn(witness, changes=changes)

    def test_race_04_safety_precedes_correction(self):
        self.start()
        context = self.context('Mejor Max pero ahora no puede respirar')
        settings = create_enabled_agent_settings(self.org)
        with patch('apps.agent.matter_resolution.process_turn', side_effect=AssertionError('must not run')):
            result = policy.evaluate(self.conv, turn_context=context, agent_settings=settings)
        self.assertEqual(result.kind, policy.ESCALATE)

    def test_race_05_human_owner_does_not_progress(self):
        self.start()
        self.conv.state = Conversation.STATE_HUMAN_ACTIVE
        self.conv.save(update_fields=['state'])
        context = self.context('Mejor Max')
        settings = create_enabled_agent_settings(self.org)
        with patch('apps.agent.matter_resolution.process_turn', side_effect=AssertionError('must not run')):
            result = policy.evaluate(self.conv, turn_context=context, agent_settings=settings)
        self.assertEqual(result.kind, policy.SILENT)
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.bound_pet_id, self.luna.pk)

    def test_fi_01_and_05_db_failure_rolls_back_revision_and_pending(self):
        self.start()
        pending = self.pending()
        rev = self.goal.binding_revision
        def fail(*args, **kwargs):
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1/0')
        with patch('apps.agent.confirmations.supersede_pending', side_effect=fail):
            with self.assertRaises(DatabaseError):
                self.turn('Mejor Max')
        self.conv.refresh_from_db()
        self.goal = binding.current_goal(self.conv)
        self.assertEqual(self.goal.binding_revision, rev)
        self.assertEqual(self.goal.bound_pet_id, self.luna.pk)
        self.assertEqual(confirmations.get_pending(self.conv), pending)

    def test_fi_02_recovery_sees_complete_new_revision(self):
        self.start()
        self.derived('vaccine_facts')
        self.pending()
        self.turn('Mejor Max')
        recovered = ConversationGoal.objects.get(pk=self.goal.pk)
        self.conv.refresh_from_db()
        self.assertEqual(recovered.bound_pet_id, self.max.pk)
        self.assertNotIn('vaccine_facts', binding.values(recovered))
        self.assertIsNone(confirmations.get_pending(self.conv))

    def test_fi_03_tool_error_does_not_corrupt_provenance(self):
        import requests
        from apps.agent.executor import ToolExecutor
        self.start()
        before = self.goal.slots.copy()
        outcome = tools.ToolOutcome(kind='ERROR', error_kind='transport_error')
        result = binding.consume_outcome(self.conv, 'get_vaccine_status', outcome,
                                        binding.snapshot(self.goal), context=self.ctx)
        self.assertIs(result, outcome)
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.slots, before)
        executor = ToolExecutor(self.conv, SimpleNamespace(organization_id=self.org.pk))
        with patch('apps.agent.executor.mint_agent_token', return_value='synthetic-test-token'), patch(
                'apps.agent.executor.requests.request', side_effect=requests.Timeout):
            result = tools.run_tool('get_vaccine_status', {}, conversation=self.conv,
                                   executor=executor, turn_context=self.ctx)
        self.assertEqual(result.kind, 'ERROR')
        self.assertEqual(result.error_kind, 'transport_error')
        self.assertIsNotNone(executor.last_execution_id)
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.slots, before)

    def test_source_outside_c1_rejected(self):
        self.start()
        with self.assertRaises(ValueError):
            binding.change(self.goal, self.conv, {'pet': self.max.pk}, context=self.ctx,
                message_id=self.m1.pk, expected_revision=self.goal.binding_revision)

    def test_contact_change_invalidates_personal_dependencies(self):
        self.start()
        self.derived('vaccine_facts')
        other = Owner.objects.create(organization=self.org, name='New Owner')
        self.conv.contact.owner = other
        self.conv.contact.save()
        self.turn('Quise decir el viernes')
        self.assertEqual(self.goal.bound_owner_id, other.pk)
        self.assertIsNone(self.goal.bound_pet_id)
        self.assertNotIn('vaccine_facts', binding.values(self.goal))

    def executor_stub(self):
        return Mock(conversation=self.conv,
                    agent_user=SimpleNamespace(organization_id=self.org.pk), last_execution_id=None)

    def test_tool_boundary_rejects_old_handle_before_handler(self):
        self.start()
        old_handle = binding.values(self.goal)['pet_handle']
        self.turn('Mejor Max')
        handler = Mock()
        spec = {**tools.TOOL_SPECS['get_vaccine_status'], 'handler': handler}
        with patch.dict(tools.TOOL_SPECS, get_vaccine_status=spec):
            result = tools.run_tool('get_vaccine_status', {'pet_handle': old_handle},
                conversation=self.conv, executor=self.executor_stub(), turn_context=self.ctx)
        handler.assert_not_called()
        self.assertEqual(result.client_error, 'binding_required')

    def test_fi_04_actual_tool_boundary_discards_late_result(self):
        self.start()
        def late(*args, **kwargs):
            self.turn('Mejor Max')
            return tools.ToolOutcome(kind='READ', data=[{'private': 'old'}], validated=True)
        spec = {**tools.TOOL_SPECS['get_vaccine_status'], 'handler': late}
        with patch.dict(tools.TOOL_SPECS, get_vaccine_status=spec):
            result = tools.run_tool('get_vaccine_status', {}, conversation=self.conv,
                                   executor=self.executor_stub(), turn_context=self.ctx)
        self.assertEqual(result.client_error, 'stale_binding')
        self.assertNotIn('vaccine_facts', binding.values(binding.current_goal(self.conv)))

    def test_public_read_has_no_pet_requirement(self):
        self.turn('Quiero una cita')
        handler = Mock(return_value=tools.ToolOutcome(kind='READ', validated=True, data=[]))
        spec = {**tools.TOOL_SPECS['get_service_catalog'], 'handler': handler}
        with patch.dict(tools.TOOL_SPECS, get_service_catalog=spec):
            result = tools.run_tool('get_service_catalog', {}, conversation=self.conv,
                                   executor=self.executor_stub(), turn_context=self.ctx)
        self.assertEqual(result.kind, 'READ')
        handler.assert_called_once()

    def test_appointment_id_alone_is_not_binding_evidence(self):
        self.start()
        appointment = self.appointment()
        with self.assertRaises(ValueError):
            binding.change(self.goal, self.conv, {'appointment': appointment.pk},
                context=self.ctx, message_id=self.ctx.anchor.message_id,
                expected_revision=self.goal.binding_revision)

    def test_unknown_schema_and_llm_metadata_are_not_trusted(self):
        self.start()
        self.goal.working_state['binding']['schema'] = 999
        self.assertEqual(binding.values(self.goal), {})
        self.assertFalse(binding.trusted(self.goal, 'pet'))

    def test_amb_05_multiple_appointments_require_clarification(self):
        self.turn('Quiero reprogramar la cita de Luna')
        appointments = [self.appointment(), self.appointment()]
        data = [{'handle': tools._add_ref(self.conv, 'cita', a.public_id)} for a in appointments]
        tools._save_refs(self.conv)
        binding.record_derived(self.goal, self.conv, 'appointment_candidates', data,
            context=self.ctx, message_id=self.ctx.anchor.message_id,
            expected_snapshot=binding.snapshot(self.goal), tool='get_appointments')
        self.assertIn('cita', self.turn('Muévela'))
        self.assertIsNone(self.goal.bound_appointment_id)

    def test_immediate_appointment_selection_uses_tool_evidence(self):
        self.turn('Quiero reprogramar la cita de Luna')
        appointment = self.appointment()
        data = [{'handle': tools._add_ref(self.conv, 'cita', appointment.public_id)}]
        tools._save_refs(self.conv)
        binding.record_derived(self.goal, self.conv, 'appointment_candidates', data,
            context=self.ctx, message_id=self.ctx.anchor.message_id,
            expected_snapshot=binding.snapshot(self.goal), tool='get_appointments')
        self.turn('Esa')
        self.assertEqual(self.goal.bound_appointment_id, appointment.pk)
        prov = binding.metadata(self.goal)['sources']['appointment']
        self.assertEqual(prov['candidate_evidence']['tool'], 'get_appointments')

    def test_revoked_identity_filters_projection_even_on_public_question(self):
        self.start()
        self.derived('vaccine_facts')
        self.conv.contact.verification_level = 'unknown'
        self.conv.contact.save()
        self.assertEqual(binding.projection(self.conv)['slots'], {})
        self.assertEqual(goals.context_block(self.conv)['ya_tengo'], {})
        self.turn('¿Cuánto cuesta?')
        self.assertIsNone(self.goal.bound_owner_id)
        self.assertNotIn('vaccine_facts', binding.values(self.goal))
