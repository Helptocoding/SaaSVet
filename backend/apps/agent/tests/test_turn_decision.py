"""
test_turn_decision.py — É-F4 Fase 1 §1.3/§1.4: rastro append-only del turno (R12).

`TurnDecision` es la pieza que convierte el tráfico real en suite de
regresión (plan de gobernanza §1.5): separa ORÁCULO (verdict/because,
determinista, testeable) de DIAGNÓSTICO (planner_used/tools_called/
duration_ms, variable, NUNCA se afirma aquí — harían la suite intermitente).
"""
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.agent import planner
from apps.agent.models import (
    AgentSettings,
    ContactIdentity,
    Conversation,
    TurnDecision,
)
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization


# Nombres de compromiso/etapa que `Because` NUNCA puede contener como
# substring (G1: ortogonalidad al contexto — un enum que absorbe el
# contexto es peor que la prosa libre, solo mueve el problema de sitio).
COMMITMENT_NAMES = {
    'identity_challenge', 'family_challenge', 'identity_triage',
    'pending_action',
}
STAGE_NAMES = {'pet', 'owner', 'titular', 'digits', 'ask'}


class BecauseGovernanceTests(SimpleTestCase):
    """G1/G2 — presupuesto de nacimiento (Fase 1 §1.4). Se prueban SIN DB:
    el enum es una propiedad estática de la clase."""

    def test_because_is_orthogonal_to_context(self):
        for value in TurnDecision.Because.values:
            for name in COMMITMENT_NAMES | STAGE_NAMES:
                with self.subTest(value=value, name=name):
                    self.assertNotIn(name, value)

    def test_because_cardinality_budget(self):
        self.assertLessEqual(len(TurnDecision.Because.values), 12)


class TurnDecisionSetupMixin:
    def setUp(self):
        self.org = Organization.objects.create(name="TD Org", timezone="UTC")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="800200800",
        )
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215500002222",
            phone_normalized="5500002222",
        )
        self.conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact,
        )
        self.settings = AgentSettings.objects.create(
            organization=self.org, enabled=True,
        )

    def _inbound(self, text):
        return Message.objects.create(
            organization=self.org, channel_account=self.channel,
            conversation=self.conv, direction=Message.DIRECTION_IN,
            author_type=Message.AUTHOR_CLIENT, body=text,
            status=Message.STATUS_PROCESSED,
        )


class ExhaustivenessTests(TurnDecisionSetupMixin, TestCase):
    """Capa 2 (parcial, directa): decisiones tomadas ANTES de tocar al LLM
    —incluida SILENT, la rama que un chequeo anclado al saliente se saltaría
    (no manda mensaje, pero sí decide algo — nota del §9.2)."""

    def test_silent_leaves_a_row(self):
        self.conv.state = Conversation.STATE_HUMAN_ACTIVE
        self.conv.save(update_fields=['state'])
        msg = self._inbound("hola")
        result = planner.handle_inbound(
            self.conv, agent_settings=self.settings, triggered_by=msg,
            burst=["hola"],
        )
        self.assertEqual(result['decision'], 'silent')
        row = TurnDecision.objects.get(conversation=self.conv)
        self.assertEqual(row.verdict, 'silent')
        self.assertEqual(row.because, TurnDecision.Because.SAFEGUARD)
        self.assertEqual(row.triggered_by_message_id, msg.pk)

    def test_escalate_leaves_a_row_with_verification_required(self):
        msg = self._inbound("mi perro convulsiona!!")
        planner.handle_inbound(
            self.conv, agent_settings=self.settings, triggered_by=msg,
            burst=["mi perro convulsiona!!"],
        )
        row = TurnDecision.objects.get(conversation=self.conv)
        self.assertEqual(row.verdict, 'escalate')
        self.assertEqual(row.because, TurnDecision.Because.SAFEGUARD)

    def test_reply_leaves_a_row(self):
        msg = self._inbound("gracias")
        planner.handle_inbound(
            self.conv, agent_settings=self.settings, triggered_by=msg,
            burst=["gracias"],
        )
        row = TurnDecision.objects.get(conversation=self.conv)
        self.assertEqual(row.verdict, 'reply')
        self.assertEqual(row.because, TurnDecision.Because.PLANNER_HANDLED)


class NoPiiTests(TurnDecisionSetupMixin, TestCase):
    def test_no_field_contains_the_message_body(self):
        secret = "ZZQXPLONK9284"  # marcador único, imposible de colar por azar
        msg = self._inbound(f"hola {secret} quiero una cita")
        planner.handle_inbound(
            self.conv, agent_settings=self.settings, triggered_by=msg,
            burst=[f"hola {secret} quiero una cita"],
        )
        row = TurnDecision.objects.get(conversation=self.conv)
        for field in (
            'verdict', 'because', 'active_commitment', 'return_to',
            'supplanted_by',
        ):
            self.assertNotIn(secret, getattr(row, field) or '')
        self.assertNotIn(secret, str(row.facts_consumed))
        self.assertNotIn(secret, str(row.facts_produced))


class ResilienceTests(TurnDecisionSetupMixin, TestCase):
    """El registro NUNCA puede tumbar el turno (mismo patrón que
    `_persist_llm_call`) — si escribir la fila revienta, el cliente igual
    recibe su respuesta."""

    def test_turn_responds_even_if_recording_blows_up(self):
        msg = self._inbound("gracias")
        with patch(
            'apps.agent.planner.TurnDecision.objects.create',
            side_effect=RuntimeError("boom"),
        ):
            result = planner.handle_inbound(
                self.conv, agent_settings=self.settings, triggered_by=msg,
                burst=["gracias"],
            )
        self.assertEqual(result['decision'], 'reply')
        self.assertEqual(TurnDecision.objects.filter(conversation=self.conv).count(), 0)
