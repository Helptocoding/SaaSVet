"""B2: contracts, evidence and containment, without live providers."""
from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase

from apps.agent.executor import RequestsTransport


class B2TransportTests(SimpleTestCase):
    def test_valid_http_preserves_body_and_parse(self):
        response = Mock(status_code=200, content=b'[]')
        response.json.return_value = []
        with patch('apps.agent.executor.requests.request', return_value=response):
            result = RequestsTransport()('GET', '/api/pets/', headers={})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.body, b'[]')
        self.assertTrue(result.parse_valid)
        self.assertIsNone(result.error_kind)

    def test_invalid_json_and_empty_are_not_empty_data(self):
        for body in (b'{broken', b''):
            with self.subTest(body=body):
                response = Mock(status_code=200, content=body)
                response.json.side_effect = ValueError('private body')
                with patch('apps.agent.executor.requests.request', return_value=response):
                    result = RequestsTransport()('GET', '/api/pets/', headers={})
                self.assertFalse(result.parse_valid)
                self.assertIsNone(result.data)
                self.assertEqual(result.error_kind, 'malformed_response')
                self.assertEqual(result.status_code, 200)

    def test_http_errors_are_distinct(self):
        for status, kind in ((403, 'forbidden'), (404, 'not_found'),
                             (409, 'conflict'), (500, 'provider_error')):
            with self.subTest(status=status):
                response = Mock(status_code=status, content=b'{}')
                response.json.return_value = {}
                with patch('apps.agent.executor.requests.request', return_value=response):
                    result = RequestsTransport()('GET', '/api/pets/', headers={})
                self.assertEqual(result.error_kind, kind)

    def test_network_failure_and_write_uncertainty(self):
        for exc in (requests.Timeout('PII'), requests.ConnectionError('PII')):
            for method in ('GET', 'POST'):
                with self.subTest(exc=type(exc), method=method):
                    with patch('apps.agent.executor.requests.request', side_effect=exc):
                        result = RequestsTransport()(method, '/api/pets/', headers={})
                    self.assertEqual(result.error_kind, 'transport_error' if method == 'GET' else 'uncertain')
                    self.assertEqual(result.timeout, isinstance(exc, requests.Timeout))
                    self.assertIsNone(result.data)
                    self.assertNotIn('PII', repr(result))


from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from django.test import TestCase
from django.utils import timezone

from apps.agent import tools, planner, guards, result_renderers as renderers
from apps.agent.executor import ToolExecutor, TransportResponse
from apps.agent.llm import LLMResult, StubLLMClient
from apps.agent.models import AgentSettings, ToolExecution
from apps.agent.tests.agent_settings_fixtures import ensure_clinic_phone
from apps.agent.turn_context import build_turn_context
from apps.appointments.models import Appointment
from apps.channels.models import Message
from apps.billing.models import Service
from apps.patients.models import Pet, Owner
from apps.organizations.models import Organization, OrganizationSettings
from . import test_tools as tools_tests
from .harness import ControlledTransport, RealApiTransport, legacy_write_component


class B2ApiResultsTests(TestCase):
    # Reuse existing real API fixtures without inheriting their test methods.
    setUpTestData = classmethod(tools_tests.ToolsThroughRealApiTests.setUpTestData.__func__)
    setUp = tools_tests.ToolsThroughRealApiTests.setUp
    _run = tools_tests.ToolsThroughRealApiTests._run

    def _context(self, body='Consulta'):
        msg = Message.objects.create(
            organization=self.org, conversation=self.conversation,
            contact=self.contact, channel_account=self.conversation.channel_account,
            direction=Message.DIRECTION_IN, author_type=Message.AUTHOR_CLIENT,
            body=body, status=Message.STATUS_PENDING)
        return build_turn_context(self.conversation, [msg])

    def _fake(self, response):
        self.executor = ToolExecutor(self.conversation, self.agent_user,
                                     transport=ControlledTransport([response]))

    def test_read_shapes_and_http_errors_never_become_empty(self):
        cases = [(TransportResponse(200, value, parse_valid=True), 'malformed_response')
                 for value in ({}, {'pets': []}, [None], None, '[]')]
        cases += [(TransportResponse(code, {}, parse_valid=True), kind)
                  for code, kind in ((403, 'forbidden'), (404, 'not_found'),
                                     (409, 'conflict'), (500, 'provider_error'))]
        cases += [(TransportResponse(200, parse_valid=False), 'malformed_response'),
                  (TransportResponse(transport_error='Timeout', timeout=True), 'transport_error')]
        for response, kind in cases:
            with self.subTest(response=response):
                self._fake(response)
                outcome = self._run('list_my_pets')
                self.assertEqual(outcome.kind, 'ERROR')
                self.assertEqual(outcome.error_kind, kind)
                self.assertFalse(outcome.empty)
                self.assertNotIn('No encontré', renderers.render_read('list_my_pets', outcome, self._context()))

    def test_each_selected_endpoint_rejects_malformed_collection(self):
        handle = tools._add_ref(self.conversation, 'mascota', self.pet_luna.public_id)
        for name, args in (
                ('get_service_catalog', {}), ('check_product_availability', {'query': 'alimento'}),
                ('get_vaccine_status', {'pet_handle': handle}),
                ('get_appointments', {'pet_handle': handle})):
            for body in ({}, [None]):
                with self.subTest(tool=name, body=body):
                    self._fake(TransportResponse(200, body, parse_valid=True))
                    outcome = self._run(name, args)
                    self.assertEqual(outcome.error_kind, 'malformed_response')
                    self.assertFalse(outcome.empty)

    def test_complete_empty_is_explicit_and_scoped(self):
        # A genuinely empty owner scope, without deleting protected vaccines.
        empty_owner = Owner.objects.create(organization=self.org, name='Empty', phone='5544332211')
        self.contact.owner = empty_owner
        self.contact.save()
        outcome = self._run('list_my_pets')
        self.assertTrue(outcome.empty)
        self.assertEqual(outcome.completeness, 'complete')
        self.assertEqual(outcome.scope['owner'], str(empty_owner.public_id))
        self.assertIsNone(outcome.has_more)
        self.assertIsNone(outcome.cursor)

    def test_pet_projection_limit_is_truncated(self):
        for index in range(11):
            Pet.objects.create(organization=self.org, owner=self.owner,
                               name=f'Pet {index}', species='perro')
        outcome = self._run('list_my_pets')
        self.assertEqual(len(outcome.data), 10)
        self.assertEqual(outcome.completeness, 'truncated')
        self.assertIn(renderers.PARTIAL, renderers.render_read('list_my_pets', outcome, self._context()))

    def test_appointments_inherit_missing_pet_coverage(self):
        for index in range(11):
            Pet.objects.create(organization=self.org, owner=self.owner,
                               name=f'Pet {index}', species='perro')
        outcome = self._run('get_appointments')
        self.assertEqual(outcome.completeness, 'truncated')
        self.assertFalse(outcome.empty)

    def test_appointment_projection_limit_and_old_appointment(self):
        original = Appointment.objects.get(organization=self.org)
        for index in range(7):
            start = original.start_datetime - timedelta(days=10 + index)
            Appointment.objects.create(
                organization=self.org, pet=self.pet_luna, veterinarian=self.vet,
                date=start.date(), start_time=start.time(),
                end_time=(start + timedelta(minutes=30)).time(),
                start_datetime=start, end_datetime=start + timedelta(minutes=30),
                status='scheduled', reason='control')
        outcome = self._run('get_appointments')
        self.assertEqual(len(outcome.data), 5)
        self.assertEqual(outcome.completeness, 'truncated')
        self.assertTrue(any(row['ya_paso'] for row in outcome.data))

    def test_pagination_complete_truncated_unknown(self):
        for body, completeness, has_more in (
                ({'results': []}, 'unknown', None),
                ({'results': [], 'count': 0, 'next': None, 'previous': None}, 'complete', False),
                ({'results': [], 'count': 30, 'next': '/api/pets/?page=2', 'previous': None}, 'truncated', True),
                ({'results': [], 'truncated': True}, 'truncated', None)):
            with self.subTest(completeness=completeness, has_more=has_more):
                self._fake(TransportResponse(200, body, parse_valid=True))
                outcome = self._run('list_my_pets')
                self.assertEqual(outcome.completeness, completeness)
                self.assertEqual(outcome.has_more, has_more)
                self.assertIsNone(outcome.cursor)
                self.assertEqual(outcome.empty, completeness == 'complete')

    def test_public_reads_and_control_do_not_require_onboarding(self):
        self.contact.owner = None
        self.contact.verification_level = 'unknown'
        self.contact.verified_at = None
        self.contact.save()
        exposed = {item['function']['name'] for item in tools.as_openai_tools(self.conversation)}
        self.assertIn('get_service_catalog', exposed)
        self.assertIn('find_available_slots', exposed)
        self.assertNotIn('list_my_pets', exposed)
        self.assertEqual(self._run('get_service_catalog').kind, 'READ')
        # A completed operation cannot make a public READ require a new goal.
        with patch.object(tools, '_has_completed_operation', return_value=True):
            exposed_after_receipt = {
                item['function']['name']
                for item in tools.as_openai_tools(self.conversation)
            }
            self.assertIn('find_available_slots', exposed_after_receipt)
            self.assertEqual(self._run('get_service_catalog').kind, 'READ')
            self.assertNotIn('create_appointment', exposed_after_receipt)
        human = self._run('request_human')
        self.assertEqual(human.kind, 'EFFECT')
        text = renderers.render_effect('request_human', human, context=self._context())
        self.assertIn('solicitud', text)
        self.assertNotIn('avisé', text)
        self.assertNotIn('notifiqué', text)

    def test_personal_read_cannot_bypass_current_identity(self):
        self.contact.verified_at = timezone.now() - timedelta(days=300)
        self.contact.save()
        outcome = self._run('get_appointments')
        self.assertEqual(outcome.error_kind, 'forbidden')
        self.assertEqual(ToolExecution.objects.filter(conversation=self.conversation).count(), 0)

    def test_price_uses_field_not_coincident_id(self):
        service = Service.objects.get(organization=self.org)
        body = {'id': 329, 'public_id': str(service.public_id), 'name': 'Consulta general',
                'base_price': '500.00', 'price_with_tax': '500.00', 'is_active': True}
        for identifier, price in ((329, '500.00'), (500, '329.00')):
            with self.subTest(identifier=identifier):
                body.update(id=identifier, base_price=price, price_with_tax=price)
                self._fake(TransportResponse(200, [deepcopy(body)], parse_valid=True))
                outcome = self._run('get_service_catalog')
                text = renderers.render_read('get_service_catalog', outcome, self._context())
                self.assertIn(f'${Decimal(price):,.2f} MXN, IVA incluido', text)
                self.assertNotIn(f'${identifier}.00', text)

    def test_the_quoted_price_is_the_one_with_tax_never_the_base(self):
        """ADR p70 D4: se cita lo que el cliente paga; sin precio con IVA, lo
        confirma el equipo (nunca el precio sin IVA)."""
        base = {'public_id': str(uuid4()), 'name': 'Consulta', 'is_active': True,
                'base_price': '500.00'}
        cases = (('580.00', 'READ', '$580.00 MXN, IVA incluido'),
                 ('missing', 'READ', 'el equipo puede confirmar su precio'),
                 (None, 'READ', 'el equipo puede confirmar su precio'),
                 ('USD 1', 'ERROR', None))
        for with_tax, kind, expected in cases:
            with self.subTest(with_tax=with_tax):
                body = dict(base)
                if with_tax != 'missing':
                    body['price_with_tax'] = with_tax
                self._fake(TransportResponse(200, [body], parse_valid=True))
                outcome = self._run('get_service_catalog')
                self.assertEqual(outcome.kind, kind)
                if expected:
                    text = renderers.render_read('get_service_catalog', outcome, self._context())
                    self.assertIn(expected, text)
                    self.assertNotIn('$500.00', text)

    def test_real_api_quotes_the_tax_of_the_clinic(self):
        Organization.objects.filter(pk=self.org.pk).update(tax_rate=Decimal('0.1600'))
        self.conversation.organization = Organization.objects.get(pk=self.org.pk)
        Service.objects.create(organization=self.org, name='Revisión dental', base_price='500.00')
        outcome = self._run('get_service_catalog')
        text = renderers.render_read('get_service_catalog', outcome, self._context())
        self.assertIn('Revisión dental: $580.00 MXN, IVA incluido.', text)
        self.assertNotIn('$500.00', text)

    def test_missing_null_and_invalid_price(self):
        base = {'public_id': str(uuid4()), 'name': 'Consulta', 'is_active': True}
        for price in ('missing', None, {}, 'USD 329', True):
            with self.subTest(price=price):
                body = dict(base)
                if price != 'missing':
                    body['base_price'] = price
                self._fake(TransportResponse(200, [body], parse_valid=True))
                outcome = self._run('get_service_catalog')
                text = renderers.render_read('get_service_catalog', outcome, self._context())
                self.assertNotIn('$', text)
                self.assertEqual(outcome.kind, 'READ' if price is None else 'ERROR')

    def test_currency_and_multiple_services_stay_associated(self):
        OrganizationSettings.objects.update_or_create(organization=self.org, defaults={'currency_code': 'USD'})
        self.conversation.organization = Organization.objects.get(pk=self.org.pk)
        Service.objects.create(organization=self.org, name='Vacunación', base_price='329.00')
        outcome = self._run('get_service_catalog')
        text = renderers.render_read('get_service_catalog', outcome, self._context())
        self.assertIn('Consulta general: $350.00 USD', text)
        self.assertIn('Vacunación: $329.00 USD', text)
        self.assertNotIn('MXN', text)
        outcome.data[0]['currency'] = 'MXN'
        self.assertEqual(renderers.render_read('get_service_catalog', outcome, self._context()), renderers.UNKNOWN)

    def test_foreign_scope_and_coincident_price_rejected(self):
        other = Organization.objects.create(name='Other')
        Service.objects.create(organization=other, name='Foreign', base_price='329.00')
        outcome = self._run('get_service_catalog')
        self.assertNotIn('Foreign', str(outcome.data))
        context = self._context()
        outcome.scope['organization_id'] = other.pk
        self.assertEqual(renderers.render_read('get_service_catalog', outcome, context), renderers.UNKNOWN)
        self._fake(TransportResponse(200, [{'public_id': str(uuid4()), 'name': 'Foreign',
                   'base_price': '329.00', 'is_active': True, 'organization_id': other.pk}], parse_valid=True))
        self.assertEqual(self._run('get_service_catalog').error_kind, 'malformed_response')

    def test_foreign_owner_pet_reference_is_denied(self):
        other_owner = Owner.objects.create(organization=self.org, name='Other', phone='5588776655')
        pet = Pet.objects.create(organization=self.org, owner=other_owner, name='Foreign', species='perro')
        handle = tools._add_ref(self.conversation, 'mascota', pet.public_id)
        outcome = self._run('get_vaccine_status', {'pet_handle': handle})
        self.assertEqual(outcome.kind, 'ERROR')
        self.assertEqual(ToolExecution.objects.filter(conversation=self.conversation).count(), 0)

    def test_real_appointment_endpoint_enforces_pet_date_and_tenant(self):
        appt = Appointment.objects.get(organization=self.org)
        source = self.executor.call('GET', '/api/appointments/', tool_name='get_appointments',
                                    params={'pet': str(self.pet_michi.public_id), 'date': str(appt.date)})
        self.assertEqual(source.data, [])
        source = self.executor.call('GET', '/api/appointments/', tool_name='get_appointments',
                                    params={'pet': str(self.pet_luna.public_id), 'date': str(appt.date)})
        self.assertEqual([row['public_id'] for row in source.data], [str(appt.public_id)])
        foreign = Organization.objects.create(name='Foreign clinic')
        owner = Owner.objects.create(organization=foreign, name='Foreign', phone='5512349876')
        pet = Pet.objects.create(organization=foreign, owner=owner, name='Foreign', species='perro')
        denied = self.executor.call('GET', '/api/appointments/', tool_name='get_appointments',
                                    params={'pet': str(pet.public_id)})
        self.assertEqual(denied.error_kind, 'not_found')

    def test_diagnostics_are_versioned_without_personal_payload(self):
        self._run('list_my_pets')
        record = ToolExecution.objects.filter(conversation=self.conversation).latest('id')
        self.assertEqual(record.result_summary_redacted['_outcome_v1'], {
            'kind': 'READ', 'validated': True, 'completeness': 'complete', 'error_kind': None})
        self.assertNotIn(self.pet_luna.name, str(record.result_summary_redacted))

    def test_partial_occupancy_cannot_prove_available_slot(self):
        # Reach occupancy coverage on an open weekday regardless of run date.
        day = (timezone.now() + timedelta(days=3)).date()
        day = (day + timedelta(days=(0 - day.weekday()) % 7)).isoformat()
        self._fake(TransportResponse(200, {'results': []}, parse_valid=True))
        outcome = self._run('check_appointment_slot', {'date': day, 'time': '11:00'})
        self.assertEqual(outcome.kind, 'ERROR')
        self.assertEqual(outcome.error_kind, 'uncertain')
        self.assertEqual(renderers.render_read('check_appointment_slot', outcome, self._context()), renderers.UNKNOWN)

    def test_overlap_is_not_available_even_if_start_differs(self):
        appt = Appointment.objects.get(organization=self.org)
        appt.end_time = appt.start_time.replace(hour=11)
        appt.end_datetime = appt.start_datetime + timedelta(hours=1)
        appt.save()
        outcome = self._run('check_appointment_slot', {'date': str(appt.date), 'time': '10:30'})
        self.assertEqual(outcome.kind, 'READ')
        self.assertFalse(outcome.data['available'])

    def test_query_never_mutates_even_forced_wrong_tool(self):
        appt = Appointment.objects.get(organization=self.org)
        handle = tools._add_ref(self.conversation, 'cita', appt.public_id)
        settings = AgentSettings.objects.get(organization=self.org)
        ensure_clinic_phone(self.org)  # INV-L: encender exige teléfono válido.
        settings.enabled = True
        settings.agent_user = self.agent_user
        settings.save()
        for question in ('¿Mi cita está confirmada?', '¿sigue confirmada?',
                         'quiero saber si está confirmada', '¿confirmaste mi cita?'):
            with self.subTest(question=question):
                context = self._context(question)
                transport = ControlledTransport()
                executor = ToolExecutor(self.conversation, self.agent_user, transport=transport)
                stub = StubLLMClient(scripted=[LLMResult(kind='tool_call', tool_name='confirm_appointment',
                                                       tool_args={'appointment_handle': handle})])
                # Run the actual planner tool dispatch with the actual C1.
                planner._run_planner(self.conversation, settings, stub, executor,
                                     None, turn_context=context)
                self.assertEqual(transport.calls, [])
                appt.refresh_from_db()
                self.assertEqual(appt.status, 'scheduled')

    def test_read_cannot_emit_free_success_prose(self):
        context = self._context('¿Mi cita está confirmada?')
        settings = AgentSettings.objects.get(organization=self.org)
        stub = StubLLMClient(scripted=[
            LLMResult(kind='tool_call', tool_name='get_appointments', tool_args={}),
            LLMResult(kind='text', text='Ya agendé y confirmé tu cita, ya avisé al equipo.')])
        planner._run_planner(self.conversation, settings, stub, self.executor,
                             None, turn_context=context)
        message = Message.objects.filter(conversation=self.conversation, direction=Message.DIRECTION_OUT).latest('id')
        self.assertIn('programada', message.body)
        self.assertNotIn('confirmé', message.body)
        self.assertNotIn('avisé', message.body)

    def test_read_error_cannot_be_rewritten_as_absence(self):
        context = self._context('¿Hay horarios?')
        settings = AgentSettings.objects.get(organization=self.org)
        error = tools.ToolOutcome(kind='ERROR', error_kind='validation_error', client_error='no_vet')
        stub = StubLLMClient(scripted=[
            LLMResult(kind='tool_call', tool_name='find_available_slots', tool_args={'date': '2027-01-01'}),
            LLMResult(kind='text', text='No hay disponibilidad ni horarios.')])
        with patch('apps.agent.tools.run_tool', return_value=error):
            planner._run_planner(self.conversation, settings, stub, self.executor,
                                 None, turn_context=context)
        message = Message.objects.filter(conversation=self.conversation, direction=Message.DIRECTION_OUT).latest('id')
        self.assertEqual(message.body, renderers.UNKNOWN)

    def test_read_label_cannot_issue_http_mutation(self):
        transport = ControlledTransport()
        executor = ToolExecutor(self.conversation, self.agent_user, transport=transport)
        response = executor.call('PATCH', '/api/appointments/1/status/',
                                  tool_name='get_appointments', json={'status': 'confirmed'})
        self.assertEqual(response.error_kind, 'forbidden')
        self.assertEqual(transport.calls, [])

    def test_error_logs_never_include_provider_pii(self):
        secret = 'Owner Phone 5511224488 clinical transcript Bearer secret'
        self._fake(TransportResponse(500, {'detail': secret, 'code': secret}, body=secret, parse_valid=True))
        with self.assertLogs('agent.events', level='WARNING') as captured:
            self._run('list_my_pets')
        self.assertNotIn(secret, str([vars(record) for record in captured.records]))
        execution = ToolExecution.objects.filter(conversation=self.conversation).latest('id')
        self.assertNotIn(secret, str(execution.result_summary_redacted))
        self.assertEqual(execution.error_code, 'provider_error')


class B2OutcomeContractTests(SimpleTestCase):
    def test_ok_is_derived_and_legacy_does_not_prove_effect(self):
        outcome = tools.ToolOutcome(ok=True, data={'created': True})
        self.assertEqual(outcome.kind, 'READ')
        self.assertFalse(outcome.validated)
        self.assertEqual(planner._commit_success_text('create_appointment', outcome), renderers.UNKNOWN)
        with self.assertRaises(AttributeError):
            outcome.ok = True

    def test_numeric_strings_are_rejected_in_typed_price_projection(self):
        context = SimpleNamespace(organization_id=1, conversation_id=2, contact_id=3)
        outcome = tools.ToolOutcome(kind='READ', validated=True, completeness='complete',
                                    scope={**vars(context), 'currency': 'MXN'}, data=[{
                                        'service_id': str(uuid4()), 'servicio': 'Consulta',
                                        'amount': '329.00', 'currency': 'MXN'}])
        self.assertEqual(renderers.render_read('get_service_catalog', outcome, context), renderers.UNKNOWN)

    def test_numbers_do_not_ground_free_price_or_success(self):
        facts = [{'id': 329, 'duration': 30, 'phone': '329', 'price': 500}]
        self.assertTrue(any(v.kind == 'invented_price' for v in guards.check_output('Cuesta $329', tool_facts=facts)))
        self.assertTrue(any(v.kind == 'unbacked_success' for v in guards.check_behaviour('Ya agendé tu cita', tool_ran=True)))

    def test_no_tool_does_not_prove_absence_or_availability(self):
        self.assertTrue(guards.has_hard(guards.check_behaviour('No tienes citas', tool_ran=False)))
        self.assertTrue(guards.has_hard(guards.check_behaviour('Tengo lugar el martes', tool_ran=False)))

    def test_manifest_is_exhaustive_static_and_writes_contained(self):
        from apps.agent.capabilities import EFFECTS, WRITE_BUSINESS
        from apps.agent.intake import CONTAINED_WRITES
        self.assertEqual(set(EFFECTS), set(tools.TOOL_SPECS))
        self.assertEqual({name for name, effect in EFFECTS.items() if effect == WRITE_BUSINESS}, CONTAINED_WRITES)
        self.assertEqual(tools.TOOL_SPECS['request_human']['effect'], 'CONTROL')
        for spec in tools.TOOL_SPECS.values():
            self.assertIn('identity_policy', spec)
            self.assertIn('result_contract', spec)
        with self.assertRaises(TypeError):
            EFFECTS['confirm_appointment'] = 'READ_PUBLIC'


class B2EffectResultsTests(TestCase):
    setUpTestData = classmethod(tools_tests.ToolsThroughRealApiTests.setUpTestData.__func__)
    setUp = tools_tests.ToolsThroughRealApiTests.setUp

    def _appointment_row(self):
        appt = Appointment.objects.get(organization=self.org)
        response = self.executor.call('GET', f'/api/appointments/{appt.public_id}/',
                                      tool_name='get_appointments')
        return response.data

    def _confirm(self, responses):
        appt = Appointment.objects.get(organization=self.org)
        handle = tools._add_ref(self.conversation, 'cita', appt.public_id)
        transport = ControlledTransport(responses)
        executor = ToolExecutor(self.conversation, self.agent_user, transport=transport)
        outcome = tools.run_tool('confirm_appointment', {'appointment_handle': handle},
                                 conversation=self.conversation, executor=executor)
        return outcome, transport

    @legacy_write_component
    def test_confirm_malformed_conflict_and_timeout_never_claim_success(self):
        row = self._appointment_row()
        read = TransportResponse(200, row, parse_valid=True)
        cases = [(TransportResponse(200, {}, parse_valid=True), 'malformed_response'),
                 (TransportResponse(400, {}, parse_valid=True), 'validation_error'),
                 (TransportResponse(409, {'code': 'appointment_changed'}, parse_valid=True), 'conflict'),
                 (TransportResponse(transport_error='Timeout', timeout=True, uncertain=True), 'uncertain')]
        for response, kind in cases:
            with self.subTest(kind=kind):
                outcome, transport = self._confirm([read, response, read])
                self.assertEqual(outcome.kind, 'ERROR')
                self.assertEqual(outcome.error_kind, kind)
                self.assertFalse(outcome.ok)
                self.assertNotIn('quedó confirmada', renderers.render_effect('confirm_appointment', outcome))
                self.assertEqual(sum(method == 'PATCH' for method, _ in transport.calls), 1)

    @legacy_write_component
    def test_already_done_requires_matching_fresh_read(self):
        row = self._appointment_row()
        row['status'] = 'confirmed'
        outcome, transport = self._confirm([TransportResponse(200, row, parse_valid=True)])
        self.assertEqual(outcome.kind, 'EFFECT')
        self.assertEqual(outcome.effects[0]['result'], 'already_done')
        self.assertEqual([method for method, _ in transport.calls], ['GET'])
        self.assertIn('ya está confirmada', renderers.render_effect('confirm_appointment', outcome))

    @legacy_write_component
    def test_effect_response_must_match_entity_action_and_requested_state(self):
        row = self._appointment_row()
        wrong = deepcopy(row)
        wrong['status'] = 'canceled'
        outcome, _ = self._confirm([TransportResponse(200, row, parse_valid=True),
                                     TransportResponse(200, wrong, parse_valid=True)])
        self.assertEqual(outcome.error_kind, 'malformed_response')
        wrong['owner_public_id'] = str(uuid4())
        denied = tools._effect_response(self.conversation, TransportResponse(200, wrong, parse_valid=True),
                                       action='cancel_appointment',
                                       scope=tools._scope(self.conversation, owner=str(self.owner.public_id)))
        self.assertEqual(denied.error_kind, 'malformed_response')

    @legacy_write_component
    def test_valid_effect_can_render_only_its_own_action(self):
        row = self._appointment_row()
        confirmed = {**row, 'status': 'confirmed'}
        outcome, _ = self._confirm([TransportResponse(200, row, parse_valid=True),
                                     TransportResponse(200, confirmed, parse_valid=True)])
        self.assertEqual(outcome.kind, 'EFFECT')
        self.assertTrue(outcome.ok)
        self.assertIn('quedó confirmada', renderers.render_effect('confirm_appointment', outcome))
        self.assertEqual(renderers.render_effect('cancel_appointment', outcome), renderers.UNKNOWN)

    @legacy_write_component
    def test_compound_partial_only_proves_pet(self):
        pets = self.executor.call('GET', '/api/pets/', tool_name='list_my_pets',
                                  params={'owner': str(self.owner.public_id)}).data
        pet = pets[0]
        transport = ControlledTransport([
            TransportResponse(201, pet, parse_valid=True),
            TransportResponse(transport_error='Timeout', timeout=True, uncertain=True)])
        executor = ToolExecutor(self.conversation, self.agent_user, transport=transport)
        row = self._appointment_row()
        args = {k: row[k] for k in ('veterinarian', 'date', 'start_time', 'end_time', 'reason')}
        args.update(owner_public_id=str(self.owner.public_id), pet_name=pet['name'], notes='')
        outcome = tools.commit_register_pet_and_schedule(self.conversation, executor, args)
        self.assertEqual(outcome.kind, 'ERROR')
        self.assertEqual(outcome.error_kind, 'uncertain')
        self.assertEqual(len(outcome.partial_effects), 1)
        text = renderers.render_effect('register_pet_and_schedule', outcome)
        self.assertIn('quedó registrada', text)
        self.assertIn('No pude verificar', text)
        self.assertNotIn('no se agendó', text)

    @legacy_write_component
    def test_replay_requires_compatible_entity_and_existing_key(self):
        row = self._appointment_row()
        args = {k: row[k] for k in ('pet', 'veterinarian', 'date', 'start_time', 'end_time', 'reason')}
        args.update(notes='', idempotency_key=str(uuid4()))
        transport = ControlledTransport([TransportResponse(200, row, parse_valid=True)])
        executor = ToolExecutor(self.conversation, self.agent_user, transport=transport)
        outcome = tools.commit_create_appointment(self.conversation, executor, args)
        self.assertEqual(outcome.operation_key, args['idempotency_key'])
        self.assertEqual(outcome.effects[0]['result'], 'already_done')
        self.assertIn('ya está agendada', renderers.render_effect('create_appointment', outcome))

    def test_direct_commit_cannot_bypass_b0_at_executor(self):
        row = self._appointment_row()
        transport = ControlledTransport()
        executor = ToolExecutor(self.conversation, self.agent_user, transport=transport)
        args = {k: row[k] for k in ('pet', 'veterinarian', 'date', 'start_time', 'end_time', 'reason')}
        args['notes'] = ''
        outcome = tools.commit_create_appointment(self.conversation, executor, args)
        self.assertEqual(outcome.error_kind, 'forbidden')
        self.assertEqual(transport.calls, [])
