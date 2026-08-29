"""
test_w2_goals.py — É-F3 W2: conversación por objetivos.

El agente pasa de `mensaje → intent → tool → respuesta` a
`objetivo → qué me falta → lo obtengo → cierro`.

Lo que estos tests anclan:
- el sistema es dueño del checklist (el modelo solo redacta la pregunta);
- una llamada PARCIAL persiste lo válido en vez de tirarlo;
- la confianza baja NO llena el slot: se confirma con el cliente;
- una interrupción DESVÍA el objetivo, no lo destruye (spec §2.7);
- el estancamiento (semántico) sustituye al presupuesto contable;
- el ciclo de vida queda medido (`completed/abandoned/blocked/handoff`);
- **É-F4 Fase 3 (ADR p55)**: todo factor lleva un `why` decible en voz alta
  (R9), y suplantar ≠ abortar (R4).
"""
from datetime import date, timedelta

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.agent import confirmations, goals, policy, tools
from apps.agent.models import ConversationGoal, HumanHandoff
from apps.agent.tests.harness import set_schedule_day
from apps.agent.tests.test_w0_hardening import AgentFixture
from apps.core.datetime_utils import org_today_local


class GoalFixture(AgentFixture):
    account_id = "900000201"

    def setUp(self):
        super().setUp()
        self.conv.flow["refs"] = {"mascota_1": str(self.pet.public_id)}
        self.conv.save(update_fields=["flow"])
        self.day = (org_today_local(self.org) + timedelta(days=3)).isoformat()
        set_schedule_day(self.org, date.fromisoformat(self.day).weekday(),
                         "09:00", "13:00")

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
        self.assertIsNotNone(confirmations.get_pending(self.conv))
        pending = confirmations.get_pending(self.conv)
        self.assertEqual(pending["tool"], "create_appointment")
        self.assertEqual(pending["args"]["date"], self.day)
        self.assertEqual(pending["args"]["start_time"], "10:00")

    def test_the_tool_no_longer_needs_everything_at_once(self):
        """Antes era todo-o-nada: faltaba un dato y el sistema tiraba el resto."""
        out = self._create(reason="vacuna")
        self.assertFalse(out.ok)
        self.assertEqual(goals.values(self._goal()), {"reason": "vacuna"})

    def test_a_la_tercera_el_sistema_deja_de_pedir_igual(self):
        """C7 · repetir es defecto del SISTEMA, no del cliente (R10).

        Reescrito en É-F5 Fase 3. Antes esto solo comprobaba que el contador
        subiera; ahora comprueba que la CONDUCTA cambie: a la tercera llamada
        con el mismo hueco, `asked` ya no sube —el sistema dejó de preguntar
        igual— y el bloque lo dice como instrucción, no como dato.
        """
        for _ in range(3):
            self._create(pet_handle="mascota_1")
        goal = self._goal()

        self.assertEqual(
            goal.asked.get("date", 0), 2,
            "el sistema siguió pidiendo el mismo dato una tercera vez")

        block = goals.context_block(self.conv)
        self.assertIn("el día de la cita",
                      block["ya_lo_pediste_dos_veces_no_lo_repitas"])


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
    def test_only_one_foreground_goal_per_conversation(self):
        self._create(pet_handle="mascota_1")
        tools.cancel_appointment(self.conv, self.executor(),
                                 {"appointment_handle": "cita_9"})
        al_frente = ConversationGoal.objects.filter(
            conversation=self.conv,
            status__in=ConversationGoal.FOREGROUND_STATUSES)
        self.assertEqual(al_frente.count(), 1)
        self.assertEqual(al_frente.first().name, goals.CANCEL)
        # ADR p55 §3 (R4): el anterior queda SUSPENDIDO, no cancelado — abrir
        # otro compromiso no es que el cliente abandonara el primero, y hay
        # que poder ofrecerlo de vuelta ("¿retomamos la cita de Luna?").
        previo = ConversationGoal.objects.get(name=goals.SCHEDULE)
        self.assertEqual(previo.status, ConversationGoal.STATUS_SUSPENDED)
        self.assertEqual(previo.supplanted_by, goals.CANCEL)

    def test_a_suspended_goal_can_be_resumed_with_its_slots(self):
        self._create(pet_handle="mascota_1", date=self.day)
        tools.cancel_appointment(self.conv, self.executor(),
                                 {"appointment_handle": "cita_9"})
        # El de agendar quedó suspendido; retomarlo conserva lo capturado.
        goals.close_open_goal(self.conv, ConversationGoal.STATUS_COMPLETED)
        retomado = goals.open_goal(self.conv, goals.SCHEDULE)
        self.assertEqual(retomado.status, ConversationGoal.STATUS_ACTIVE)
        self.assertEqual(goals.values(retomado)["date"], self.day)
        self.assertEqual(
            ConversationGoal.objects.filter(
                conversation=self.conv, name=goals.SCHEDULE).count(), 1)

    def test_escalation_closes_the_goal_as_handoff(self):
        self._create(pet_handle="mascota_1")
        policy.escalate_to_human(
            self.conv, reason_code=HumanHandoff.REASON_EXPLICIT)
        goal = ConversationGoal.objects.get(conversation=self.conv)
        self.assertEqual(goal.status, ConversationGoal.STATUS_HANDOFF)

    def test_deviating_keeps_the_captured_slots(self):
        self._create(pet_handle="mascota_1", date=self.day)
        goals.pause(self._goal())
        goal = self._goal()
        self.assertEqual(goal.status, ConversationGoal.STATUS_DEVIATED)
        self.assertEqual(goals.values(goal)["date"], self.day)

    def test_deviating_always_records_where_to_come_back(self):
        """R4 — una pausa sin dirección de retorno no es una pausa: es una
        interrupción sobrevivida por suerte. Si el caller no la da, se deriva
        del propio compromiso (el primer dato que falta), nunca de la ventana
        de mensajes."""
        self._create(pet_handle="mascota_1", date=self.day)
        goals.pause(self._goal())
        self.assertEqual(self._goal().return_to, "time")

    def test_deviate_refuses_an_empty_return_direction(self):
        self._create(pet_handle="mascota_1")
        with self.assertRaises(ValueError):
            goals.deviate(self._goal(), "")

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
    def test_context_block_publica_hechos_no_claves_ni_preguntas(self):
        """C3 · el estado se publica en lenguaje semántico, no en jerga.

        Reescrito en É-F5 Fase 3. Antes el bloque viajaba con las claves
        internas (`objetivo: schedule_appointment`, `me_falta: ['date']`) y el
        modelo aprendía a nombrar los datos como los nombra la base.

        Lo que NO cambia —y es la mitad importante del test original— es que
        el objetivo **sigue sin saber preguntar**: publica el dato y su
        motivo; la pregunta la redacta el modelo (contrato p54).
        """
        self._create(pet_handle="mascota_1", date=self.day)
        block = goals.context_block(self.conv)

        # Nada de claves internas.
        serialized = str(block)
        for internal in (goals.SCHEDULE, "'date'", "'time'", "pet_handle"):
            self.assertNotIn(internal, serialized)

        # Sí el dato y su porqué, en español.
        faltan = {f["dato"] for f in block["me_falta"]}
        self.assertIn("la hora de la cita", faltan)
        self.assertTrue(all(f["para"] for f in block["me_falta"]),
                        "un dato pedido sin motivo decible (R9)")

        # Ni una pregunta redactada: el objetivo no sabe conversar.
        low = serialized.lower()
        for word in ("¿", "?", "por favor", "dime"):
            self.assertNotIn(word, low)

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


# ---------------------------------------------------------------------------
# É-F4 Fase 3 · R9 estructural — todo factor lleva su `why`
# ---------------------------------------------------------------------------

class FactorWhyTests(SimpleTestCase):
    """Sin DB: el catálogo es una propiedad estática del módulo."""

    def test_a_factor_without_why_does_not_compile(self):
        with self.assertRaises(ValueError):
            goals.Factor('digits', '')
        with self.assertRaises(ValueError):
            goals.Factor('digits', '   ')

    def test_every_factor_of_every_goal_has_a_why(self):
        for name, spec in goals.GOAL_SPECS.items():
            for factor in spec.all_factors:
                with self.subTest(goal=name, factor=factor.name):
                    self.assertTrue(factor.why.strip())

    def test_required_slots_and_validators_still_derive_from_factors(self):
        """El contrato de slot (nombre + validador, ADR p54) no cambió: solo
        ganó el `why`. Si esto se rompe, `capture`/`missing_slots` mienten."""
        spec = goals.GOAL_SPECS[goals.REGISTER]
        self.assertEqual(
            spec.required_slots,
            ('owner_name', 'pet_name', 'date', 'time', 'reason'))
        self.assertEqual(spec.optional_slots, ('pet_species', 'pet_birth_date'))
        for slot in spec.required_slots:
            self.assertIn(slot, spec.validators)


class WhyVoiceTests(SimpleTestCase):
    """R6 — el cliente nunca debe satisfacer restricciones INTERNAS.

    Precedente exacto (conv 12): *"Entiendo, pero el sistema me pide al menos
    una fecha y hora para poder registrar a Luna"*. La restricción es legítima
    —el alta va con la primera cita, decisión de producto del 2026-07-30— pero
    enunciarla como schema es el defecto. Este gate no puede juzgar prosa; sí
    puede impedir que el vocabulario del sistema se cuele en el motivo.
    """

    _SYSTEM_VOICE = (
        'sistema', 'el campo', 'base de datos', 'schema', 'requisito',
        'obligatorio', 'formulario', 'registro interno', 'api', 'validac',
    )

    def test_no_why_speaks_like_a_system(self):
        for name, spec in goals.GOAL_SPECS.items():
            for factor in spec.all_factors:
                low = factor.why.lower()
                for word in self._SYSTEM_VOICE:
                    with self.subTest(goal=name, factor=factor.name, word=word):
                        self.assertNotIn(word, low)

    def test_the_alta_constraint_is_explained_as_clinic_policy(self):
        """El caso de la conv 12: pedir fecha en un ALTA tiene que sonar a
        cómo trabaja la clínica, no a lo que exige la tabla."""
        why = goals.GOAL_SPECS[goals.REGISTER].why('date')
        self.assertIn('primera cita', why)
        self.assertEqual(why, goals.GOAL_SPECS[goals.REGISTER].why('time'))

    def test_scheduling_and_registering_explain_the_same_slot_differently(self):
        """El `why` es por FACTOR, no global: la fecha de una cita normal y la
        de un alta se piden por motivos distintos."""
        self.assertNotEqual(
            goals.GOAL_SPECS[goals.SCHEDULE].why('date'),
            goals.GOAL_SPECS[goals.REGISTER].why('date'))
