"""
test_contracts.py — G3 · Contract Freeze (plan de gobernanza §9.1, Fase 1).

Cuatro tipos son la API interna del sistema conversacional: `ToolOutcome`,
`PolicyDecision`, `TurnDecision` y el **compromiso** (`ConversationGoal`, que
la Fase 3 EXTIENDE en vez de reemplazar — ADR p55 §3). No pueden cambiar
"porque sí": la propiedad del contrato está declarada en
[ADR p55 §8](../../../../docs/decisions/2026-07-30-p55-turn-authority-and-commitments.md)
— todo cambio SEMÁNTICO del runtime conversacional entra por ese ADR.

Mecanismo: snapshot de la forma real (nombres de campo) versionado en este
archivo. Si el PR toca alguno de los cuatro, el diff de este test lo hace
VISIBLE — y debe venir acompañado de un ADR (cambio semántico: campo
eliminado/renombrado/re-tipado, o significado cambiado) o ser claramente
aditivo (campo opcional nuevo, valor de enum nuevo que pasa ortogonalidad y
cardinalidad → basta el bump del snapshot). Mismo patrón que
`requirements.lock`: fuente pinneada.

Coste declarado: cualquier campo nuevo, aunque sea trivial, obliga a tocar
este snapshot. Es el precio de que Fase 3 no pueda cambiar `ToolOutcome` en
silencio cuando le quitó `reply_text`/`needs_confirmation` (§9.1) — ese
cambio, el de mayor alcance de la Fase 3, tuvo que pasar por aquí.
"""
import dataclasses

from django.test import SimpleTestCase

from apps.agent.models import ConversationGoal, TurnDecision
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
            'client_error', 'data', 'detail', 'ok', 'summary',
        ])

    def test_a_tool_cannot_write_copy_nor_end_a_turn(self):
        """ADR p55 §4 — autoridad cero. Ordenar las tools al final de la
        jerarquía no bastaba: mientras `ToolOutcome` pudiera encolar texto al
        cliente o cerrar el turno, la jerarquía era decorativa."""
        names = {f.name for f in dataclasses.fields(ToolOutcome)}
        for removed in ('reply_text', 'needs_confirmation',
                        'confirmation_text'):
            with self.subTest(field=removed):
                self.assertNotIn(removed, names)


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


class TurnVerdictContractTests(SimpleTestCase):
    """La salida del árbitro (ADR p55 §2). Es control de flujo puro: si algún
    día aparece aquí un campo de texto para el cliente, el árbitro se
    convirtió en planner."""

    def test_fields_match_snapshot(self):
        from apps.agent.arbiter import TurnVerdict
        fields = sorted(f.name for f in dataclasses.fields(TurnVerdict))
        self.assertEqual(fields, ['commitment', 'return_to', 'verdict'])

    def test_facts_match_snapshot(self):
        from apps.agent.arbiter import TurnFacts
        fields = sorted(f.name for f in dataclasses.fields(TurnFacts))
        self.assertEqual(fields, [
            'client_declined', 'interrupts', 'proposes_other_commitment',
        ])


class CommitmentContractTests(SimpleTestCase):
    """El compromiso (`ConversationGoal` extendido, ADR p55 §3)."""

    def test_fields_match_snapshot(self):
        fields = sorted(f.name for f in ConversationGoal._meta.fields)
        self.assertEqual(fields, [
            'asked', 'attempts_failed', 'blocked_reason', 'closed_at',
            'closed_reason', 'conversation', 'created_at', 'created_by', 'id',
            'is_active', 'last_progress_at', 'low_confidence', 'missing',
            'name', 'organization', 'return_to', 'slots', 'stall_turns',
            'status', 'supplanted_by', 'updated_at', 'updated_by',
            'working_state',
        ])

    def test_lifecycle_states_match_the_adr(self):
        """Los seis estados del ciclo de vida de ADR p55 §3, más `handoff` y
        el `cancelled` deprecado que solo sostiene filas históricas."""
        self.assertEqual(
            sorted(s for s, _ in ConversationGoal.STATUS_CHOICES),
            ['abandoned', 'active', 'blocked', 'cancelled', 'completed',
             'deviated', 'handoff', 'suspended'],
        )

    def test_a_suspended_commitment_is_open_but_not_in_the_foreground(self):
        """Es lo que permite que la urgencia suplante a la cita y ambas
        coexistan — sin esto, `suplantar` y `abortar` vuelven a colapsar."""
        self.assertIn(ConversationGoal.STATUS_SUSPENDED,
                      ConversationGoal.OPEN_STATUSES)
        self.assertNotIn(ConversationGoal.STATUS_SUSPENDED,
                         ConversationGoal.FOREGROUND_STATUSES)
