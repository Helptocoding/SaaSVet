"""
test_contracts.py — G3 · Contract Freeze (plan de gobernanza §9.1, Fase 1).

Tres tipos son la API interna del sistema conversacional: `ToolOutcome`,
`PolicyDecision`, `TurnDecision`. (El cuarto, `Commitment`, llega en Fase 3 —
no existe todavía.) No pueden cambiar "porque sí".

Mecanismo: snapshot de la forma real (nombres de campo) versionado en este
archivo. Si el PR toca alguno de los tres, el diff de este test lo hace
VISIBLE — y debe venir acompañado de un ADR (cambio semántico: campo
eliminado/renombrado/re-tipado) o ser claramente aditivo (campo opcional
nuevo, sin ADR). Mismo patrón que `requirements.lock`: fuente pinneada.

Coste declarado: cualquier campo nuevo, aunque sea trivial, obliga a tocar
este snapshot. Es el precio de que Fase 3 no pueda cambiar `ToolOutcome` en
silencio cuando le quite `reply_text`/`needs_confirmation` (§9.1).
"""
import dataclasses

from django.test import SimpleTestCase

from apps.agent.models import TurnDecision
from apps.agent.policy import PolicyDecision
from apps.agent.tools import ToolOutcome


class PolicyDecisionContractTests(SimpleTestCase):
    def test_fields_match_snapshot(self):
        fields = sorted(f.name for f in dataclasses.fields(PolicyDecision))
        self.assertEqual(fields, [
            'handoff_priority', 'handoff_reason', 'kind', 'meta', 'text',
        ])


class ToolOutcomeContractTests(SimpleTestCase):
    def test_fields_match_snapshot(self):
        fields = sorted(f.name for f in dataclasses.fields(ToolOutcome))
        self.assertEqual(fields, [
            'client_error', 'confirmation_text', 'data', 'detail',
            'needs_confirmation', 'ok', 'reply_text', 'summary',
        ])


class TurnDecisionContractTests(SimpleTestCase):
    def test_fields_match_snapshot(self):
        fields = sorted(f.name for f in TurnDecision._meta.fields)
        self.assertEqual(fields, [
            'active_commitment', 'because', 'conversation', 'created_at',
            'created_by', 'duration_ms', 'facts_consumed', 'facts_produced',
            'id', 'is_active', 'organization', 'planner_used', 'return_to',
            'supplanted_by', 'tools_called', 'triggered_by_message',
            'updated_at', 'updated_by', 'verdict',
        ])
