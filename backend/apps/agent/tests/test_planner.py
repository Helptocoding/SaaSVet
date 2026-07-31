"""
test_planner.py — É-F1 PR-12: orquestación del turno (policy→LLM→tools).

LLM = StubLLMClient (determinista). Las tools atraviesan la API REAL vía el
Django test client con el JWT del AGENT (mismo patrón que test_tools).
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.agent import executor as executor_module
from apps.agent import planner
from apps.agent.executor import ToolExecutor
from apps.agent.llm import LLMError, LLMResult, StubLLMClient
from apps.agent.models import (
    AgentSettings,
    ContactIdentity,
    Conversation,
    HumanHandoff,
    LLMCall,
)
from apps.channels.models import ChannelAccount, Message
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSIONS
from apps.medical_records.models import VaccineRecord
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User
from apps.users.services import ensure_agent_user


def _seed_role(org, role_name):
    codes = PERMISSIONS[role_name]
    role, _ = Role.objects.get_or_create(
        name=role_name, organization=org, defaults={"is_system_role": True}
    )
    if "*.*" in codes:
        wildcard, _ = Permission.objects.get_or_create(code="*.*")
        role.permissions.set([wildcard])
    else:
        role.permissions.set(
            [Permission.objects.get_or_create(code=c)[0] for c in codes]
        )
    return role


def _next_open_day(min_offset):
    """Fecha ISO a >= `min_offset` días, saltando domingo (único día cerrado
    del horario default, `DEFAULT_ORGANIZATION_SCHEDULE`). Sin esto, pruebas
    con un offset fijo son intermitentes: si "hoy + N" cae en domingo,
    `find_available_slots` devuelve `closed=True` sin capturar ningún slot."""
    day = timezone.now().date() + timedelta(days=min_offset)
    while day.isoweekday() == 7:
        day += timedelta(days=1)
    return day.isoformat()


class TestClientTransport:
    def __call__(self, method, path, *, headers, params=None, json=None):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=headers.get("Authorization", ""))
        response = getattr(client, method.lower())(path, data=params or {})
        try:
            payload = response.json() if response.content else {}
        except ValueError:
            payload = {}
        return response.status_code, payload


class PlannerTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Plan Org", timezone="UTC")
        _seed_role(cls.org, "AGENT")
        vet_role = _seed_role(cls.org, "VET")
        cls.vet = User.objects.create_user(
            username="plan_vet", password="p", organization=cls.org, role="VET"
        )
        UserRole.objects.get_or_create(user=cls.vet, role=vet_role)
        cls.owner = Owner.objects.create(
            organization=cls.org, name="Ana Torres", phone="5511990088"
        )
        cls.pet = Pet.objects.create(
            organization=cls.org, owner=cls.owner, name="Luna",
            species="perro", birth_date="2021-01-01",
        )
        VaccineRecord.objects.create(
            organization=cls.org, pet=cls.pet, vaccine_name="Antirrábica",
            application_date="2026-01-15", next_due_date="2027-01-15",
        )

    def setUp(self):
        executor_module._token_cache.clear()
        self.agent_user, _ = ensure_agent_user(self.org)
        Organization.objects.filter(pk=self.org.pk).update(
            phone="55-1000-2000")
        self.org.refresh_from_db()
        self.settings = AgentSettings.objects.create(
            organization=self.org, enabled=True, agent_user=self.agent_user,
        )
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="900900900",
        )
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215511990088",
            owner=self.owner,
            verification_level=ContactIdentity.VERIFICATION_CONFIRMED,
            verified_at=timezone.now(),
        )
        self.conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact,
        )

    def _inbound(self, text):
        return Message.objects.create(
            organization=self.org, channel_account=self.channel,
            conversation=self.conv, direction=Message.DIRECTION_IN,
            author_type=Message.AUTHOR_CLIENT, body=text,
            status=Message.STATUS_PROCESSED,
        )

    def _handle(self, stub):
        executor = ToolExecutor(self.conv, self.agent_user,
                                transport=TestClientTransport())
        return planner.handle_inbound(
            self.conv, agent_settings=self.settings,
            llm_client=stub, executor=executor,
        )

    def _last_outbound(self):
        return Message.objects.filter(
            conversation=self.conv, direction=Message.DIRECTION_OUT,
        ).order_by("-id").first()


class PlannerHappyPathTests(PlannerTestCase):
    def test_plain_text_reply(self):
        self._inbound("¿a qué hora abren?")
        stub = StubLLMClient(scripted=[
            LLMResult(kind="text", text="Abrimos de 9 a 7 🙂",
                      input_tokens=100, output_tokens=20),
        ])
        result = self._handle(stub)
        self.assertEqual(result["decision"], "planner_reply")
        # `endswith`: fuera del horario de la clínica la respuesta lleva
        # antepuesto el aviso de fuera de horario (INT-03), y el alta de la
        # organización siembra un horario por defecto.
        self.assertTrue(
            self._last_outbound().body.endswith("Abrimos de 9 a 7 🙂"),
            self._last_outbound().body)
        self.assertEqual(self._last_outbound().author_type, Message.AUTHOR_AGENT)
        # LLMCall persistido + presupuesto incrementado.
        self.assertEqual(LLMCall.objects.filter(conversation=self.conv).count(), 1)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.total_llm_calls, 1)

    def test_tool_call_then_text(self):
        self._inbound("¿cuándo le toca la vacuna a Luna?")
        stub = StubLLMClient(scripted=[
            LLMResult(kind="tool_call", tool_name="get_vaccine_status",
                      tool_args={"pet_handle": "mascota_1"}),
            LLMResult(kind="text",
                      text="Luna tiene refuerzo el 15 de enero de 2027 ✅"),
        ])
        # Registrar el handle mascota_1 → Luna (lo haría list_my_pets; aquí
        # lo sembramos para probar get_vaccine_status en aislamiento).
        self.conv.flow["refs"] = {"mascota_1": str(self.pet.public_id)}
        self.conv.save()

        result = self._handle(stub)
        self.assertEqual(result["decision"], "planner_reply")
        self.assertEqual(result["tools"], 1)
        self.assertIn("15 de enero de 2027", self._last_outbound().body)
        # W1-3: el 2º prompt lleva el HILO del turno — la llamada del propio
        # modelo (role=assistant con tool_calls) y su resultado correlacionado
        # (role=tool). Antes solo viajaba el último resultado como bloque de
        # sistema y el modelo no veía que ya había llamado a la herramienta.
        second_call = stub.calls[1]
        roles = [m["role"] for m in second_call["messages"]]
        self.assertIn("assistant", roles)
        self.assertIn("tool", roles)
        tool_msg = next(m for m in second_call["messages"] if m["role"] == "tool")
        assistant_msg = next(
            m for m in second_call["messages"]
            if m["role"] == "assistant" and m.get("tool_calls")
        )
        self.assertEqual(
            tool_msg["tool_call_id"],
            assistant_msg["tool_calls"][0]["id"],
        )
        self.assertIn("2027", tool_msg["content"])


class PlannerPolicyShortCircuitTests(PlannerTestCase):
    def test_emergency_never_calls_llm(self):
        self._inbound("mi perro convulsiona!!")
        stub = StubLLMClient(scripted=[
            LLMResult(kind="text", text="NO DEBERÍA USARSE"),
        ])
        result = self._handle(stub)
        self.assertEqual(result["decision"], "escalate")
        self.assertEqual(result["handoff_reason"], HumanHandoff.REASON_EMERGENCY)
        self.assertEqual(len(stub.calls), 0)   # el LLM ni se tocó
        self.assertIn("55-1000-2000", self._last_outbound().body)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.state, Conversation.STATE_HANDOFF_PENDING)

    def test_human_active_is_silent(self):
        self.conv.state = Conversation.STATE_HUMAN_ACTIVE
        self.conv.save()
        self._inbound("hola?")
        result = self._handle(StubLLMClient())
        self.assertEqual(result["decision"], "silent")
        self.assertIsNone(self._last_outbound())


class PlannerVerificationTests(PlannerTestCase):
    def test_unverified_personal_tool_triggers_challenge(self):
        self.contact.verification_level = ContactIdentity.VERIFICATION_PHONE_MATCH
        self.contact.save()
        self._inbound("¿qué citas tengo?")
        stub = StubLLMClient(scripted=[
            LLMResult(kind="tool_call", tool_name="list_upcoming_appointments",
                      tool_args={}),
        ])
        result = self._handle(stub)
        self.assertEqual(result["decision"], "identity_challenge")
        from apps.agent.tests.harness import identity_commitment
        self.assertEqual(
            identity_commitment(self.conv).name, "identity_challenge")
        self.assertIn("mascota", self._last_outbound().body.lower())


class PlannerTriageAlreadyResolvedTests(PlannerTestCase):
    """Fase 0 §0.5 — conv 13 S6: `planner.py:274` sembraba SIEMPRE un tamiz
    nuevo aunque `identity_triage_done` ya tuviera veredicto, y dos
    meta-preguntas al tamiz nuevo pisaban un 'returning' correcto con
    'unclear'. Con el tamiz ya resuelto, se escala en vez de re-triar."""

    def setUp(self):
        super().setUp()
        self.contact.owner = None
        self.contact.verification_level = ContactIdentity.VERIFICATION_UNKNOWN
        self.contact.save()

    def test_does_not_re_triage_when_already_resolved(self):
        self.conv.flow = {"identity_triage_done": "returning"}
        self.conv.save(update_fields=["flow"])
        self._inbound("¿qué citas tengo?")
        stub = StubLLMClient(scripted=[
            LLMResult(kind="tool_call", tool_name="list_upcoming_appointments",
                      tool_args={}),
        ])
        result = self._handle(stub)
        self.assertEqual(result["decision"], "escalate")
        self.assertEqual(result["reason"], "triage_already_resolved")
        self.conv.refresh_from_db()
        self.assertNotIn("identity_triage", self.conv.flow)
        self.assertEqual(self.conv.state, Conversation.STATE_HANDOFF_PENDING)
        self.assertEqual(
            HumanHandoff.objects.filter(conversation=self.conv).count(), 1)


class PlannerFailureTests(PlannerTestCase):
    def test_llm_error_escalates(self):
        # Texto con intención (un "hola" pelón lo resuelve la plantilla de
        # bienvenida sin tocar el modelo desde W1-9).
        self._inbound("¿tienen cita para mañana?")
        stub = StubLLMClient(scripted=[LLMError("boom", retryable=False)])
        result = self._handle(stub)
        self.assertEqual(result["decision"], "escalate")
        self.assertEqual(result["reason"], "llm_error")
        self.assertTrue(
            LLMCall.objects.filter(conversation=self.conv).exclude(error="").exists()
        )

    def test_two_consecutive_tool_failures_escalate(self):
        self._inbound("¿tienen algo?")
        # Tool que siempre falla: check_product con la API caída se simula con
        # un handle inexistente en get_vaccine_status (unknown_handle NO es
        # tool_failure). Mejor: forzar 500 vía transport que devuelve error.
        stub = StubLLMClient(scripted=[
            LLMResult(kind="tool_call", tool_name="get_service_catalog",
                      tool_args={"query": "x"}),
            LLMResult(kind="tool_call", tool_name="get_service_catalog",
                      tool_args={"query": "y"}),
        ])

        class FailingTransport:
            def __call__(self, method, path, *, headers, params=None, json=None):
                return 503, {"code": "server_error"}

        executor = ToolExecutor(self.conv, self.agent_user,
                                transport=FailingTransport())
        result = planner.handle_inbound(
            self.conv, agent_settings=self.settings, llm_client=stub,
            executor=executor,
        )
        self.assertEqual(result["decision"], "escalate")
        self.assertEqual(result["reason"], "tool_failure")


class PlannerGoalStallTests(PlannerTestCase):
    """El detector de estancamiento debe medir PROGRESO, no "llamó la tool".

    Piloto conv 12 (2026-07-28): el modelo llamó `register_new_client_and_pet`
    cuatro veces con los mismos datos, sin fecha. Cada llamada marcaba el turno
    como productivo, así que `stall_turns` se quedó en 0 y el agente repreguntó
    el mismo dato indefinidamente (`asked = {'date': 4, 'time': 4}`).
    """

    def _reg_call(self, **extra):
        args = {"owner_name": "Ana Torres", "pet_name": "Luna",
                "reason": "consulta"}
        args.update(extra)
        return LLMResult(kind="tool_call",
                         tool_name="register_new_client_and_pet",
                         tool_args=args)

    def setUp(self):
        super().setUp()
        # Contacto SIN owner: el alta es la ruta válida.
        self.contact.owner = None
        self.contact.verification_level = ContactIdentity.VERIFICATION_UNKNOWN
        self.contact.save()
        # El tamiz ya se resolvió: aquí se prueba lo que pasa DESPUÉS.
        self.conv.flow = {"identity_triage_done": "new"}
        self.conv.save(update_fields=["flow"])

    def _goal(self):
        from apps.agent import goals
        return goals.get_open_goal(self.conv)

    def _stuck_turn(self):
        """Un turno en el que el modelo reenvía EXACTAMENTE lo que ya sabía."""
        self._inbound("regístrame")
        return self._handle(StubLLMClient(scripted=[
            self._reg_call(),
            LLMResult(kind="text", text="¿Qué día te gustaría?"),
        ]))

    def test_first_call_is_progress_repeats_are_not(self):
        self._stuck_turn()          # captura owner_name/pet_name/reason
        self.assertEqual(self._goal().stall_turns, 0)
        for turn in range(1, 3):    # reenviar lo mismo NO avanza
            self._stuck_turn()
            self.assertEqual(self._goal().stall_turns, turn, f"repetición {turn}")

    def test_stall_escalates_instead_of_asking_forever(self):
        result = None
        for _ in range(4):          # 1 productivo + 3 estancados
            result = self._stuck_turn()
        self.assertEqual(result["decision"], "goal_stalled")
        self.assertEqual(
            HumanHandoff.objects.filter(conversation=self.conv).count(), 1)

    def test_new_datum_resets_the_stall_counter(self):
        self._stuck_turn()
        self._stuck_turn()
        self.assertEqual(self._goal().stall_turns, 1)

        # Este turno SÍ aporta un dato nuevo → el contador vuelve a cero.
        self._inbound("el 4 de agosto")
        self._handle(StubLLMClient(scripted=[
            self._reg_call(date="2026-08-04"),
            LLMResult(kind="text", text="¿A qué hora?"),
        ]))
        goal = self._goal()
        self.assertEqual(goal.stall_turns, 0)
        self.assertEqual(goal.slots["date"]["value"], "2026-08-04")

    def test_partial_write_attempt_leaves_an_audit_row(self):
        """Una llamada de escritura incompleta debe verse en la telemetría.

        Antes salía temprano sin `record_local`, así que los 4 intentos del
        piloto eran invisibles y parecía que el modelo no llamaba herramientas.
        """
        from apps.agent.models import ToolExecution
        self._stuck_turn()
        rows = ToolExecution.objects.filter(
            conversation=self.conv, tool_name="register_new_client_and_pet")
        self.assertEqual(rows.count(), 1)
        row = rows.first()
        self.assertEqual(row.result_summary_redacted["resultado"], "need_data")
        self.assertIn("date", row.args_redacted["me_falta"])

    def test_correcting_a_value_counts_as_progress(self):
        """"mejor el jueves" mueve la conversación aunque el slot ya tuviera
        valor: es avance, no repetición."""
        self._inbound("regístrame")
        self._handle(StubLLMClient(scripted=[
            self._reg_call(date="2026-08-04"),
            LLMResult(kind="text", text="¿A qué hora?"),
        ]))
        self._inbound("mejor el 6")
        self._handle(StubLLMClient(scripted=[
            self._reg_call(date="2026-08-06"),
            LLMResult(kind="text", text="¿A qué hora?"),
        ]))
        goal = self._goal()
        self.assertEqual(goal.stall_turns, 0)
        self.assertEqual(goal.slots["date"]["value"], "2026-08-06")


class PlannerConcreteTimeCaptureTests(PlannerTestCase):
    """Fase 0 §0.6: `preferred_time` concreto (HH:MM) llena el slot `time`
    desde una lectura, igual que `date` (ADR de la auditoría — parcial: NO
    cierra conv 12, donde el modelo nunca mandó `preferred_time`; ver §0.6)."""

    def setUp(self):
        super().setUp()
        self.contact.owner = None
        self.contact.verification_level = ContactIdentity.VERIFICATION_UNKNOWN
        self.contact.save()
        self.conv.flow = {"identity_triage_done": "new"}
        self.conv.save(update_fields=["flow"])

    def test_hhmm_preferred_time_fills_the_missing_time_slot(self):
        from apps.agent import goals
        day = _next_open_day(3)
        self._inbound("regístrame, el jueves a las 9")
        self._handle(StubLLMClient(scripted=[
            LLMResult(kind="tool_call",
                      tool_name="register_new_client_and_pet",
                      tool_args={"owner_name": "Ana Torres",
                                 "pet_name": "Luna", "reason": "consulta"}),
            LLMResult(kind="tool_call", tool_name="find_available_slots",
                      tool_args={"date": day, "preferred_time": "09:00"}),
            LLMResult(kind="text", text="A las 9 tengo espacio 🙂"),
        ]))
        goal = goals.get_open_goal(self.conv)
        self.assertEqual(goal.slots["time"]["value"], "09:00")
        self.assertNotIn("time", goal.missing)

    def test_bucket_preferred_time_does_not_fill_the_slot(self):
        from apps.agent import goals
        day = _next_open_day(3)
        self._inbound("regístrame, el jueves en la mañana")
        self._handle(StubLLMClient(scripted=[
            LLMResult(kind="tool_call",
                      tool_name="register_new_client_and_pet",
                      tool_args={"owner_name": "Ana Torres",
                                 "pet_name": "Luna", "reason": "consulta"}),
            LLMResult(kind="tool_call", tool_name="find_available_slots",
                      tool_args={"date": day, "preferred_time": "mañana"}),
            LLMResult(kind="text", text="Tengo varios en la mañana 🙂"),
        ]))
        goal = goals.get_open_goal(self.conv)
        self.assertIn("time", goal.missing)


class PlannerSlotCaptureTests(PlannerTestCase):
    """Lo que el cliente ya dio no se vuelve a pedir — aunque el dato haya
    entrado por una tool de LECTURA (piloto conv 12: el agente resolvió
    "martes a las 9", consultó disponibilidad, lo dijo en voz alta… y siguió
    preguntando la fecha porque el slot nunca se llenó)."""

    def setUp(self):
        super().setUp()
        self.contact.owner = None
        self.contact.verification_level = ContactIdentity.VERIFICATION_UNKNOWN
        self.contact.save()
        self.conv.flow = {"identity_triage_done": "new"}
        self.conv.save(update_fields=["flow"])

    def test_availability_lookup_fills_the_missing_date(self):
        from apps.agent import goals
        day = _next_open_day(3)
        self._inbound("regístrame, quiero ir el jueves")
        self._handle(StubLLMClient(scripted=[
            LLMResult(kind="tool_call",
                      tool_name="register_new_client_and_pet",
                      tool_args={"owner_name": "Ana Torres",
                                 "pet_name": "Luna", "reason": "consulta"}),
            LLMResult(kind="tool_call", tool_name="find_available_slots",
                      tool_args={"date": day}),
            LLMResult(kind="text", text="Ese día tengo espacio 🙂"),
        ]))
        goal = goals.get_open_goal(self.conv)
        self.assertEqual(goal.slots["date"]["value"], day)
        self.assertNotIn("date", goal.missing)

    def test_lookup_does_not_overwrite_a_date_already_chosen(self):
        """El modelo consulta días alternativos; eso no borra lo elegido."""
        from apps.agent import goals
        chosen = (timezone.now() + timedelta(days=2)).date().isoformat()
        other = (timezone.now() + timedelta(days=9)).date().isoformat()
        self._inbound("regístrame")
        self._handle(StubLLMClient(scripted=[
            LLMResult(kind="tool_call",
                      tool_name="register_new_client_and_pet",
                      tool_args={"owner_name": "Ana Torres",
                                 "pet_name": "Luna", "reason": "consulta",
                                 "date": chosen}),
            LLMResult(kind="tool_call", tool_name="find_available_slots",
                      tool_args={"date": other}),
            LLMResult(kind="text", text="También tengo ese otro día."),
        ]))
        goal = goals.get_open_goal(self.conv)
        self.assertEqual(goal.slots["date"]["value"], chosen)

    def test_probed_date_not_updated_by_a_later_probe(self):
        """Deuda documentada (Fase 0 §0.7, introducida por el fix `103196e`):
        `_capture_slot_from_read` solo rellena si el slot está VACÍO. Si el
        modelo SONDEA el lunes (lo captura desde una lectura) y el cliente
        elige el martes, una segunda lectura NO corrige — 'date' ya no está
        en `missing`. Hoy lo salva que los args de ESCRITURA sí sobrescriben;
        este test ancla el comportamiento actual (bug conocido) antes de que
        Fase 3 lo reescriba (CR-7). NO es un cambio de código de Fase 0."""
        from apps.agent import goals
        monday = (timezone.now() + timedelta(days=1)).date().isoformat()
        tuesday = (timezone.now() + timedelta(days=2)).date().isoformat()
        self._inbound("regístrame, tal vez el lunes")
        self._handle(StubLLMClient(scripted=[
            LLMResult(kind="tool_call",
                      tool_name="register_new_client_and_pet",
                      tool_args={"owner_name": "Ana Torres",
                                 "pet_name": "Luna", "reason": "consulta"}),
            LLMResult(kind="tool_call", tool_name="find_available_slots",
                      tool_args={"date": monday}),
            LLMResult(kind="text", text="El lunes tengo espacio 🙂"),
        ]))
        goal = goals.get_open_goal(self.conv)
        self.assertEqual(goal.slots["date"]["value"], monday)

        self._inbound("mejor el martes")
        self._handle(StubLLMClient(scripted=[
            LLMResult(kind="tool_call", tool_name="find_available_slots",
                      tool_args={"date": tuesday}),
            LLMResult(kind="text", text="También tengo el martes 🙂"),
        ]))
        goal = goals.get_open_goal(self.conv)
        # BUG conocido: se queda en el lunes porque 'date' ya no estaba
        # `missing` cuando llegó el segundo sondeo.
        self.assertEqual(goal.slots["date"]["value"], monday)


class PlannerBudgetTests(PlannerTestCase):
    def test_budget_exhausted_escalates_before_llm(self):
        from django.conf import settings as dj_settings
        self.conv.total_llm_calls = (
            dj_settings.AGENT_MAX_LLM_TURNS_PER_CONVERSATION)
        self.conv.save()
        self._inbound("otra pregunta más")
        stub = StubLLMClient(scripted=[LLMResult(kind="text", text="x")])
        result = self._handle(stub)
        self.assertEqual(result["decision"], "escalate")
        self.assertEqual(len(stub.calls), 0)
