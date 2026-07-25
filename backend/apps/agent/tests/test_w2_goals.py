"""
test_w2_goals.py — É-F3 W2: conversación por objetivos.

El agente pasa de `mensaje → intent → tool → respuesta` a
`objetivo → qué me falta → lo obtengo → cierro`.

Lo que estos tests anclan:
- el sistema es dueño del checklist (el modelo solo redacta la pregunta);
- una llamada PARCIAL persiste lo válido en vez de tirarlo;
- la confianza baja NO llena el slot: se confirma con el cliente;
- una interrupción PAUSA el objetivo, no lo destruye (spec §2.7);
- el estancamiento (semántico) sustituye al presupuesto contable;
- el ciclo de vida queda medido (`completed/cancelled/handoff`).
"""
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.agent import confirmations, goals, policy, tools
from apps.agent.models import ConversationGoal, HumanHandoff
from apps.agent.tests.test_w0_hardening import AgentFixture
from apps.core.datetime_utils import org_today_local


class GoalFixture(AgentFixture):
    account_id = "900000201"

    def setUp(self):
        super().setUp()
        self.conv.flow["refs"] = {"mascota_1": str(self.pet.public_id)}
        self.conv.save(update_fields=["flow"])
        self.day = (org_today_local(self.org) + timedelta(days=3)).isoformat()

    def _create(self, **args):
        return tools.create_appointment(self.conv, self.executor(), args)

    def _goal(self):
        return goals.get_open_goal(self.conv)


# ---------------------------------------------------------------------------
# Captura incremental
# ---------------------------------------------------------------------------

class IncrementalSlotFillingTests(GoalFixture):
    def test_partial_call_opens_the_goal_and_keeps_what_is_valid(self):
        out = self._create(pet_handle="mascota_1", date=self.day)
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, 'need_data')

        goal = self._goal()
        self.assertIsNotNone(goal)
        self.assertEqual(goal.name, goals.SCHEDULE)
        self.assertEqual(goal.status, ConversationGoal.STATUS_ACTIVE)
        self.assertEqual(goals.values(goal)["date"], self.day)
        self.assertCountEqual(goal.missing, ["time", "reason"])

    def test_second_call_completes_and_proposes(self):
        self._create(pet_handle="mascota_1", date=self.day)
        out = self._create(time="10:00", reason="vacuna")
        self.assertTrue(out.ok, out.client_error)
        self.assertTrue(out.needs_confirmation)
        pending = confirmations.get_pending(self.conv)
        self.assertEqual(pending["tool"], "create_appointment")
        self.assertEqual(pending["args"]["date"], self.day)
        self.assertEqual(pending["args"]["start_time"], "10:00")

    def test_the_tool_no_longer_needs_everything_at_once(self):
        """Antes era todo-o-nada: faltaba un dato y el sistema tiraba el resto."""
        out = self._create(reason="vacuna")
        self.assertFalse(out.ok)
        self.assertEqual(goals.values(self._goal()), {"reason": "vacuna"})

    def test_missing_slots_are_counted_for_anti_repetition(self):
        self._create(pet_handle="mascota_1")
        self._create(pet_handle="mascota_1")
        goal = self._goal()
        self.assertGreaterEqual(goal.asked.get("date", 0), 2)
        block = goals.context_block(self.conv)
        self.assertIn("date", block["ya_preguntado_2_veces"])


# ---------------------------------------------------------------------------
# Confianza por slot
# ---------------------------------------------------------------------------

class SlotConfidenceTests(GoalFixture):
    def test_low_confidence_does_not_fill_the_slot(self):
        out = self._create(pet_handle="mascota_1", date=self.day,
                           date_confidence=0.4, time="10:00", reason="vacuna")
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, 'confirm_slot')
        goal = self._goal()
        self.assertNotIn("date", goals.values(goal))
        self.assertEqual(goal.low_confidence[0]["slot"], "date")

    def test_high_confidence_fills_normally(self):
        self._create(pet_handle="mascota_1", date=self.day,
                     date_confidence=0.95)
        self.assertEqual(goals.values(self._goal())["date"], self.day)

    def test_missing_confidence_is_trusted(self):
        """Compatibilidad: un modelo que no la emita se comporta como antes."""
        self._create(pet_handle="mascota_1", date=self.day)
        self.assertIn("date", goals.values(self._goal()))

    @override_settings(AGENT_SLOT_CONFIDENCE_THRESHOLD=0.9)
    def test_threshold_is_configurable(self):
        self._create(pet_handle="mascota_1", date=self.day,
                     date_confidence=0.8)
        self.assertNotIn("date", goals.values(self._goal()))

    def test_confidence_does_not_bypass_the_validator(self):
        """Dos filtros EN SERIE: seguro ≠ válido."""
        past = (org_today_local(self.org) - timedelta(days=1)).isoformat()
        out = self._create(pet_handle="mascota_1", date=past,
                           date_confidence=1.0, time="10:00", reason="x")
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, 'past_date')
        self.assertNotIn("date", goals.values(self._goal()))


class SlotValidatorTests(GoalFixture):
    def test_date_beyond_horizon_is_rejected(self):
        far = (org_today_local(self.org) + timedelta(days=90)).isoformat()
        out = self._create(pet_handle="mascota_1", date=far)
        self.assertEqual(out.client_error, 'out_of_horizon')

    def test_unknown_handle_is_rejected(self):
        out = self._create(pet_handle="mascota_9", date=self.day)
        self.assertEqual(out.client_error, 'unknown_handle')

    def test_malformed_time_is_rejected(self):
        out = self._create(pet_handle="mascota_1", date=self.day,
                           time="a las cuatro")
        self.assertEqual(out.client_error, 'invalid_slot')
        self.assertNotIn("time", goals.values(self._goal()))


# ---------------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------------

class GoalLifecycleTests(GoalFixture):
    def test_only_one_open_goal_per_conversation(self):
        self._create(pet_handle="mascota_1")
        tools.cancel_appointment(self.conv, self.executor(),
                                 {"appointment_handle": "cita_9"})
        abiertos = ConversationGoal.objects.filter(
            conversation=self.conv,
            status__in=ConversationGoal.OPEN_STATUSES)
        self.assertEqual(abiertos.count(), 1)
        self.assertEqual(abiertos.first().name, goals.CANCEL)
        # El anterior queda CANCELADO, no borrado: el embudo lo necesita.
        previo = ConversationGoal.objects.get(name=goals.SCHEDULE)
        self.assertEqual(previo.status, ConversationGoal.STATUS_CANCELLED)

    def test_escalation_closes_the_goal_as_handoff(self):
        self._create(pet_handle="mascota_1")
        policy.escalate_to_human(
            self.conv, reason_code=HumanHandoff.REASON_EXPLICIT)
        goal = ConversationGoal.objects.get(conversation=self.conv)
        self.assertEqual(goal.status, ConversationGoal.STATUS_HANDOFF)

    def test_pause_keeps_the_captured_slots(self):
        self._create(pet_handle="mascota_1", date=self.day)
        goals.pause(self._goal())
        goal = self._goal()
        self.assertEqual(goal.status, ConversationGoal.STATUS_PAUSED)
        self.assertEqual(goals.values(goal)["date"], self.day)

    def test_resume_reactivates_the_same_goal(self):
        self._create(pet_handle="mascota_1", date=self.day)
        goals.pause(self._goal())
        self._create(time="11:00")
        goal = self._goal()
        self.assertEqual(goal.status, ConversationGoal.STATUS_ACTIVE)
        self.assertEqual(goals.values(goal)["date"], self.day)
        self.assertEqual(
            ConversationGoal.objects.filter(conversation=self.conv).count(), 1)

    def test_stall_escalates_after_three_empty_turns(self):
        self._create(pet_handle="mascota_1")
        goal = self._goal()
        for _ in range(2):
            self.assertFalse(goals.bump_stall(goal))
        self.assertTrue(goals.bump_stall(goal))

    def test_progress_resets_the_stall_counter(self):
        self._create(pet_handle="mascota_1")
        goals.bump_stall(self._goal())
        self._create(date=self.day)
        self.assertEqual(self._goal().stall_turns, 0)


# ---------------------------------------------------------------------------
# Contexto y contrato de herramientas
# ---------------------------------------------------------------------------

class GoalContextTests(GoalFixture):
    def test_context_block_has_no_copy_only_data(self):
        self._create(pet_handle="mascota_1", date=self.day)
        block = goals.context_block(self.conv)
        self.assertEqual(block["objetivo"], goals.SCHEDULE)
        self.assertIn("date", block["ya_tengo"])
        self.assertCountEqual(block["me_falta"], ["time", "reason"])
        # Ni una pregunta redactada: el objetivo no sabe conversar.
        serialized = str(block).lower()
        for word in ("¿", "?", "por favor", "dime"):
            self.assertNotIn(word, serialized)

    def test_context_reaches_the_prompt(self):
        from apps.agent import prompts
        self._create(pet_handle="mascota_1", date=self.day)
        messages = prompts.assemble_messages(self.conv)
        self.assertIn("en_curso", messages[0]["content"])

    def test_no_goal_no_block(self):
        self.assertIsNone(goals.context_block(self.conv))


class GoalToolSchemaTests(TestCase):
    def test_goal_tools_accept_partial_calls_and_confidence(self):
        specs = {t["function"]["name"]: t["function"]
                 for t in tools.as_openai_tools()}
        for name in goals.TOOL_GOALS:
            fn = specs[name]
            self.assertEqual(fn["parameters"]["required"], [],
                             f"{name} debe aceptar llamadas parciales")
            props = fn["parameters"]["properties"]
            self.assertTrue(
                any(p.endswith("_confidence") for p in props), name)

    def test_read_tools_keep_their_required_fields(self):
        specs = {t["function"]["name"]: t["function"]
                 for t in tools.as_openai_tools()}
        self.assertEqual(
            specs["get_vaccine_status"]["parameters"]["required"],
            ["pet_handle"])

    def test_every_goal_has_a_spec(self):
        for name in goals.TOOL_GOALS.values():
            self.assertIsNotNone(goals.spec_for(name), name)


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------

class GoalMetricsTests(GoalFixture):
    def test_funnel_counts_goals_and_stuck_slots(self):
        from apps.agent.metrics import compute_goal_metrics
        self._create(pet_handle="mascota_1", date=self.day)
        since = timezone.now() - timedelta(days=1)
        until = timezone.now() + timedelta(days=1)
        data = compute_goal_metrics(self.org, since, until)
        self.assertEqual(data["abiertos"], 1)
        self.assertEqual(data["completados"], 0)
        self.assertEqual(data["por_objetivo"][goals.SCHEDULE], 1)
        self.assertIn("time", data["slots_atorados"])
