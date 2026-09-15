"""
test_turn_decision.py — É-F4 Fase 1 §1.3/§1.4: rastro append-only del turno (R12).

`TurnDecision` es la pieza que convierte el tráfico real en suite de
regresión (plan de gobernanza §1.5): separa ORÁCULO (verdict/because,
determinista, testeable) de DIAGNÓSTICO (planner_used/tools_called/
duration_ms, variable, NUNCA se afirma aquí — harían la suite intermitente).
"""
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.agent import arbiter, planner
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
    (no manda mensaje, pero sí decide algo — nota del §9.2).

    **Reescrito en É-F5 Fase 4.** `verdict` guarda ahora el veredicto del
    ÁRBITRO (enum cerrado de cinco); el desenlace operativo del planner
    —`reply`, `silent`, `escalate`— bajó a `facts_produced['salida']`, que es
    diagnóstico. Era la deuda declarada en el docstring del modelo desde
    É-F4 Fase 1: «Fase 1 no tiene árbitro todavía; `verdict` guarda el
    `decision` de hoy tal cual».

    Lo que estos casos protegen NO cambia y es lo que importa: **todo turno
    deja exactamente una fila**, incluidos los que no mandan mensaje.
    """

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
        # El veredicto es del árbitro: sin compromiso en juego, `responder`.
        self.assertEqual(row.verdict, arbiter.ANSWER)
        # La salida del planner sigue registrada, como diagnóstico.
        self.assertEqual(row.facts_produced['salida'], 'silent')
        self.assertEqual(row.because, TurnDecision.Because.SAFEGUARD)
        self.assertEqual(row.triggered_by_message_id, msg.pk)

    def test_escalate_leaves_a_row_with_verification_required(self):
        msg = self._inbound("mi perro convulsiona!!")
        planner.handle_inbound(
            self.conv, agent_settings=self.settings, triggered_by=msg,
            burst=["mi perro convulsiona!!"],
        )
        row = TurnDecision.objects.get(conversation=self.conv)
        # El veredicto es del árbitro: sin compromiso en juego, `responder`.
        self.assertEqual(row.verdict, arbiter.ANSWER)
        # La salida del planner sigue registrada, como diagnóstico.
        self.assertEqual(row.facts_produced['salida'], 'escalate')
        self.assertEqual(row.because, TurnDecision.Because.SAFEGUARD)

    def test_reply_leaves_a_row(self):
        msg = self._inbound("¿eres una persona?")
        planner.handle_inbound(
            self.conv, agent_settings=self.settings, triggered_by=msg,
            burst=["¿eres una persona?"],
        )
        row = TurnDecision.objects.get(conversation=self.conv)
        # El veredicto es del árbitro: sin compromiso en juego, `responder`.
        self.assertEqual(row.verdict, arbiter.ANSWER)
        # La salida del planner sigue registrada, como diagnóstico.
        self.assertEqual(row.facts_produced['salida'], 'reply')
        # El disparador era "gracias" hasta É-F5 Fase 5, que lo pasó al modelo;
        # ahora es una de las plantillas que SÍ sobreviven, y ésa sí tiene
        # `because` propio.
        self.assertEqual(row.because, TurnDecision.Because.OUT_OF_SCOPE)


class NoPiiTests(TurnDecisionSetupMixin, TestCase):
    def test_no_field_contains_the_message_body(self):
        # Marcador LEGIBLE a propósito: una cadena de alta entropía asignada a
        # algo llamado `secret` hace que gitleaks la lea como una API key y
        # bloquee el pipeline. El test necesita un texto que no pueda aparecer
        # por azar, no uno que parezca una credencial.
        marker = "texto-del-cliente-que-no-debe-viajar"
        msg = self._inbound(f"hola {marker} quiero una cita")
        # Guion explícito: desde É-F5 Fase 2 este turno ya no lo intercepta el
        # router (el tamiz de identidad se retiró), así que llega al planner y
        # sin stub intentaría hablar con un proveedor real.
        from apps.agent.llm import LLMResult, StubLLMClient
        planner.handle_inbound(
            self.conv, agent_settings=self.settings, triggered_by=msg,
            burst=[f"hola {marker} quiero una cita"],
            llm_client=StubLLMClient(scripted=[
                LLMResult(kind="text", text="¡Claro! ¿Para qué día? 🙂")]),
        )
        row = TurnDecision.objects.get(conversation=self.conv)
        for field in (
            'verdict', 'because', 'active_commitment', 'return_to',
            'supplanted_by',
        ):
            self.assertNotIn(marker, getattr(row, field) or '')
        self.assertNotIn(marker, str(row.facts_consumed))
        self.assertNotIn(marker, str(row.facts_produced))


class ResilienceTests(TurnDecisionSetupMixin, TestCase):
    """El registro NUNCA puede tumbar el turno (mismo patrón que
    `_persist_llm_call`) — si escribir la fila revienta, el cliente igual
    recibe su respuesta."""

    def test_turn_responds_even_if_recording_blows_up(self):
        msg = self._inbound("¿eres una persona?")
        with patch(
            'apps.agent.planner.TurnDecision.objects.create',
            side_effect=RuntimeError("boom"),
        ):
            result = planner.handle_inbound(
                self.conv, agent_settings=self.settings, triggered_by=msg,
                burst=["¿eres una persona?"],
            )
        self.assertEqual(result['decision'], 'reply')
        self.assertEqual(TurnDecision.objects.filter(conversation=self.conv).count(), 0)


class B1TurnEvidenceTests(TurnDecisionSetupMixin, TestCase):
    """CTX-01: the wrapper observes the real burst even without legacy text args."""

    def test_real_burst_reaches_inner_policy_prompts_and_arbiter_in_the_same_order(self):
        from django.utils import timezone
        from apps.agent import policy, prompts
        from apps.agent.llm import LLMResult, StubLLMClient
        from apps.agent.turn_context import build_turn_context

        first = self._inbound('hola')
        last = self._inbound('¿qué horarios tienen?')
        stamp = timezone.now()
        Message.objects.filter(pk__in=[first.pk, last.pk]).update(created_at=stamp)
        first.refresh_from_db()
        last.refresh_from_db()
        captured = {}
        assemble = prompts.assemble_messages

        def capture_prompt(conversation, **kwargs):
            captured['context'] = kwargs['turn_context']
            captured['prompt'] = assemble(conversation, **kwargs)
            return captured['prompt']

        with (patch.object(planner, '_handle_inbound_inner', wraps=planner._handle_inbound_inner) as inner,
              patch.object(policy, 'evaluate', wraps=policy.evaluate) as evaluate,
              patch.object(prompts, 'assemble_messages', side_effect=capture_prompt),
              patch.object(planner, '_settle_commitment', wraps=planner._settle_commitment) as settle,
              patch.object(planner, '_observe_turn_facts', wraps=planner._observe_turn_facts) as observe):
            planner.handle_inbound(
                self.conv, agent_settings=self.settings,
                burst_messages=[last, first],
                # Conflicting obsolete arguments must not redefine the turn.
                burst=['no'], payload_types=['audio'], triggered_by=first,
                llm_client=StubLLMClient(scripted=[LLMResult(
                    kind='text', text='Puedo ayudarte con los horarios de la clínica.')]),
            )
        turn = inner.call_args.kwargs['turn_context']
        self.assertEqual(turn.inbound_ids, (first.pk, last.pk))
        self.assertEqual(turn.texts, ('hola', '¿qué horarios tienen?'))
        self.assertIs(evaluate.call_args.kwargs['turn_context'], turn)
        self.assertIs(captured['context'], turn)
        self.assertIs(settle.call_args.args[2], turn)
        self.assertEqual(observe.call_args.args[0], 'hola\n¿qué horarios tienen?')
        self.assertEqual([m['content'] for m in captured['prompt'] if m['role'] == 'user'],
                         list(turn.texts))
        row = TurnDecision.objects.get(conversation=self.conv)
        self.assertEqual(row.triggered_by_message_id, last.pk)
        self.assertTrue(row.facts_consumed['interrumpe'])
        self.assertEqual(turn, build_turn_context(self.conv, [first, last], now=turn.clinic_now))

    def test_explicit_context_wins_over_legacy_policy_arguments(self):
        from apps.agent import policy
        from apps.agent.turn_context import build_turn_context
        msg = self._inbound('mi perro convulsiona')
        turn = build_turn_context(self.conv, [msg])
        decision = policy.evaluate(
            self.conv, 'hola', burst=['hola'], payload_types=['text'],
            turn_context=turn, agent_settings=self.settings)
        self.assertEqual(decision.kind, policy.ESCALATE)
        self.assertEqual(decision.handoff_reason, 'emergency')

    def test_post_receipt_assessment_keeps_exact_context_members_without_new_semantics(self):
        from types import SimpleNamespace
        from apps.agent.llm import LLMResult, StubLLMClient
        first, last = self._inbound('quiero consultar'), self._inbound('los horarios')
        with (patch.object(planner.operation_authorization, 'requires_assessment', return_value=True),
              patch.object(planner.operation_authorization, 'assess_turn', return_value=SimpleNamespace(
                  assessment=SimpleNamespace(verdict='conversational'))) as assess):
            planner.handle_inbound(
                self.conv, agent_settings=self.settings, burst_messages=[last, first],
                llm_client=StubLLMClient(scripted=[LLMResult(
                    kind='text', text='Puedo ayudarte con los horarios de la clínica.')]))
        self.assertEqual([m.pk for m in assess.call_args.args[1]], [first.pk, last.pk])
        self.assertEqual([m.body for m in assess.call_args.args[1]], ['quiero consultar', 'los horarios'])

    def test_single_inbound_adapter_does_not_invent_an_action_id(self):
        from apps.agent.turn_context import context_from_inputs
        msg = self._inbound('Confirmar')
        msg.payload_type = 'button_reply'
        msg.save(update_fields=['payload_type'])
        turn = context_from_inputs(self.conv, triggered_by=msg, burst=['otra cosa'])
        self.assertEqual(turn.texts, ('Confirmar',))
        self.assertIsNone(turn.events[0].action_id)
        self.assertIsNone(turn.events[0].action_title)
