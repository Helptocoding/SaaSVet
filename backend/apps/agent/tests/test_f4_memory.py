"""
test_f4_memory.py — Memoria estructurada (F4).

Un hilo continuo no es memoria: la ventana sigue siendo 12 turnos / 40 mensajes,
así que «el producto que te pregunté la otra vez» se pierde igual. Estas tools
dan el equivalente a subir a leer, pero sobre HECHOS, no sobre texto libre.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.agent import tools
from apps.agent.executor import ToolExecutor
from apps.agent.models import ContactIdentity, Conversation, ToolExecution
from apps.channels.models import ChannelAccount
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.services import ensure_agent_user


class MemoryTestCase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Mem Org", timezone="UTC")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="660100660")
        self.owner = Owner.objects.create(
            organization=self.org, name="Andrés Ruiz", phone="5511889900")
        Pet.objects.create(
            organization=self.org, owner=self.owner, name="Luna",
            species="perro", birth_date="2021-01-01")
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215511889900",
            owner=self.owner,
            verification_level=ContactIdentity.VERIFICATION_CONFIRMED,
            verified_at=timezone.now())
        self.conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact)
        self.agent_user, _ = ensure_agent_user(self.org)
        self.executor = ToolExecutor(self.conv, self.agent_user)

    def _record(self, tool_name, summary, *, conversation=None,
                error_code='', http_status=None, decision=None):
        return ToolExecution.objects.create(
            organization=self.org,
            conversation=conversation or self.conv,
            tool_name=tool_name,
            result_summary_redacted=summary,
            error_code=error_code,
            http_status=http_status,
            policy_decision=decision or ToolExecution.DECISION_AUTO,
        )


class ProductMemoryTests(MemoryTestCase):
    def test_remembers_a_previous_product_query(self):
        self._record('product_query_resolved',
                     {'producto': 'Bravecto', 'disponible': True})
        outcome = tools.get_recent_product_queries(
            self.conv, self.executor, {})
        self.assertEqual([e['producto'] for e in outcome.data], ['Bravecto'])

    def test_a_failed_execution_is_not_a_fact(self):
        """Una llamada fallida no se le cuenta al cliente como si hubiera
        pasado."""
        self._record('product_query_resolved', {'producto': 'Bravecto'},
                     error_code='tool_failure')
        outcome = tools.get_recent_product_queries(
            self.conv, self.executor, {})
        self.assertEqual(outcome.data, [])

    def test_a_denied_execution_is_not_a_fact(self):
        self._record('product_query_resolved', {'producto': 'Bravecto'},
                     decision=ToolExecution.DECISION_DENIED)
        self.assertEqual(
            tools.get_recent_product_queries(self.conv, self.executor, {}).data,
            [])

    def test_an_http_error_is_not_a_fact(self):
        self._record('product_query_resolved', {'producto': 'Bravecto'},
                     http_status=500)
        self.assertEqual(
            tools.get_recent_product_queries(self.conv, self.executor, {}).data,
            [])

    def test_memory_crosses_sessions_of_the_same_contact(self):
        """Es el punto entero: la sesión vieja está cerrada y el dato sigue."""
        old = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact, state=Conversation.STATE_CLOSED,
            closed_at=timezone.now() - timedelta(days=3))
        self._record('product_query_resolved', {'producto': 'Bravecto'},
                     conversation=old)
        outcome = tools.get_recent_product_queries(
            self.conv, self.executor, {})
        self.assertEqual([e['producto'] for e in outcome.data], ['Bravecto'])

    def test_another_contact_is_never_remembered(self):
        other_contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215500001111")
        other_conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=other_contact)
        self._record('product_query_resolved', {'producto': 'Secreto'},
                     conversation=other_conv)
        self.assertEqual(
            tools.get_recent_product_queries(self.conv, self.executor, {}).data,
            [])

    def test_another_channel_account_is_separate(self):
        other_channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="660100661")
        other_conv = Conversation.objects.create(
            organization=self.org, channel_account=other_channel,
            contact=self.contact)
        self._record('product_query_resolved', {'producto': 'Otro número'},
                     conversation=other_conv)
        self.assertEqual(
            tools.get_recent_product_queries(self.conv, self.executor, {}).data,
            [])

    def test_duplicates_are_collapsed(self):
        for _ in range(3):
            self._record('product_query_resolved', {'producto': 'Bravecto'})
        outcome = tools.get_recent_product_queries(
            self.conv, self.executor, {})
        self.assertEqual(len(outcome.data), 1)


class MemoryScopeTests(MemoryTestCase):
    def test_both_memory_tools_require_a_verified_contact(self):
        """El historial es lo que este cliente preguntó y cuándo vino: con solo
        `phone_match` devolverlo es una fuga."""
        for name in ('get_recent_product_queries', 'get_past_visits'):
            self.assertEqual(
                tools.TOOL_SPECS[name]['min_verification'],
                'confirmed_in_chat', name)

    def test_the_barrier_rejects_an_unverified_contact(self):
        self.contact.verification_level = (
            ContactIdentity.VERIFICATION_PHONE_MATCH)
        self.contact.save(update_fields=['verification_level'])
        self.conv.contact = self.contact
        outcome = tools.run_tool(
            'get_recent_product_queries', {}, conversation=self.conv,
            executor=self.executor)
        self.assertEqual(outcome.client_error, 'verification_required')

    def test_the_product_projection_has_its_own_tool_name(self):
        """Reusar `check_product_availability` contaría DOS ejecuciones por una
        sola búsqueda y falsearía las métricas por tool."""
        self.assertNotIn('product_query_resolved', tools.TOOL_SPECS)
