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


def _next_open_days(count, min_offset=1):
    """`count` fechas ISO ABIERTAS, distintas y crecientes, desde
    `hoy + min_offset`. Salta domingo (único día cerrado del horario default,
    `DEFAULT_ORGANIZATION_SCHEDULE`).

    Existe además de `_next_open_day` porque pedir dos días con offsets
    independientes NO garantiza que sean distintos: en sábado, `+1` salta el
    domingo y cae en lunes, y `+2` cae en lunes también. Un test que necesita
    "un día y OTRO día" tiene que pedirlos juntos.
    """
    days, day = [], timezone.now().date() + timedelta(days=min_offset)
    while len(days) < count:
        if day.isoweekday() != 7:
            days.append(day.isoformat())
        day += timedelta(days=1)
    return days


def _next_open_day(min_offset):
    """Fecha ISO a >= `min_offset` días, saltando domingo (único día cerrado
    del horario default, `DEFAULT_ORGANIZATION_SCHEDULE`). Sin esto, pruebas
    con un offset fijo son intermitentes: si "hoy + N" cae en domingo,
    `find_available_slots` devuelve `closed=True` sin capturar ningún slot."""
    return _next_open_days(1, min_offset)[0]


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


class PlannerPendingContextTests(PlannerTestCase):
    def test_question_does_not_restage_the_same_pending_action(self):
        """Una duda durante la espera conserva la propuesta y se contesta."""
        self.conv.flow['pending_action'] = {
            'tool': 'reschedule_appointment',
            'operation_family': 'reschedule',
            'args': {'appointment_handle': 'cita_1'},
            'paraphrase': 'Muevo la cita de Luna. ¿Confirmas?',
        }
        self.conv.save(update_fields=['flow'])
        self._inbound("¿qué día era?")
        stub = StubLLMClient(scripted=[
            LLMResult(kind='tool_call', tool_name='reschedule_appointment',
                      tool_args={'appointment_handle': 'cita_1'}),
            LLMResult(kind='text',
                      text='La propuesta es para el martes a las 11:30 🙂'),
        ])

        result = self._handle(stub)

        self.assertEqual(result['decision'], 'planner_reply')
        self.assertEqual(result['tools'], 0)
        self.assertTrue(self._last_outbound().body.endswith(
            'La propuesta es para el martes a las 11:30 🙂'))
        self.assertEqual(len(stub.calls), 2)
        self.conv.refresh_from_db()
        self.assertEqual(
            self.conv.flow['pending_action']['tool'],
            'reschedule_appointment',
        )

    def test_typed_response_protocol_has_no_confirmation_purpose(self):
        self._inbound('mueve la cita de Luna')
        stub = StubLLMClient(scripted=[
            LLMResult(
                kind='tool_call', tool_name='respond_to_client',
                tool_args={'purpose': 'confirmation', 'text': '¿Confirmas?'},
            ),
            LLMResult(
                kind='tool_call', tool_name='respond_to_client',
                tool_args={
                    'purpose': 'ask_for_data',
                    'text': '¿Qué horario prefieres para moverla?',
                },
            ),
        ])
        stub.requires_response_tool = True

        result = self._handle(stub)

        self.assertEqual(result['decision'], 'planner_reply')
        self.assertEqual(len(stub.calls), 2)
        self.assertNotIn('confirm', self._last_outbound().body.lower())
        self.assertTrue(self._last_outbound().body.endswith(
            '¿Qué horario prefieres para moverla?'))


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
    def test_unverified_personal_tool_executes_nothing(self):
        """La BARRERA, que es lo que de verdad protege los datos.

        Reescrito en É-F5 Fase 2: antes se afirmaba que el rebote arrancaba un
        reto conducido por el router (`decision == 'identity_challenge'`). Ese
        conductor se retiró y ahora el turno vuelve al modelo, que pregunta él.

        Lo que NO cambió —y es lo único que impide una fuga— es que la llamada
        rebota SIN ejecutarse: `_verification_ok` se evalúa dentro de
        `run_tool`, por debajo del modelo. Por eso es seguro dejarlo conversar
        sobre identidad.
        """
        self.contact.verification_level = ContactIdentity.VERIFICATION_PHONE_MATCH
        self.contact.save()
        self._inbound("¿qué citas tengo?")
        stub = StubLLMClient(scripted=[
            LLMResult(kind="tool_call", tool_name="get_appointments",
                      tool_args={}),
            LLMResult(kind="text",
                      text="Para verlas necesito confirmar quién eres 🙂"),
        ])
        result = self._handle(stub)

        self.assertEqual(result["decision"], "planner_reply")
        # La garantía: la tool NO se ejecutó con éxito. Se afirma así —y no
        # sobre la existencia de una fila— porque lo que protege los datos es
        # que la llamada rebote, no cómo se instrumente el rebote.
        from apps.agent.models import ToolExecution
        self.assertFalse(
            ToolExecution.objects.filter(
                conversation=self.conv,
                tool_name='get_appointments',
                error_code='').exists(),
            "una tool personal se ejecutó sin verificación")


# `PlannerTriageAlreadyResolvedTests` vivía aquí (É-F5 Fase 2). Protegía una
# guarda —"no re-triar un tamiz ya resuelto"— de una máquina de estados que ya
# no existe: sin tamiz no hay nada que re-triar. No se porta ninguna
# aserción; el defecto que la motivó (la conv 13 perdiendo un veredicto
# correcto) lo cubre ahora el corpus, sobre conducta observable.

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

    def test_retryable_llm_error_recovers_before_escalating(self):
        """Regression for transient ChunkedEncodingError-style failures."""
        self._inbound("¿tienen cita para mañana?")
        stub = StubLLMClient(scripted=[
            LLMError("red: ChunkedEncodingError", retryable=True),
            LLMResult(kind="text", text="Sí, reviso opciones para mañana 🙂"),
        ])

        result = self._handle(stub)

        self.assertEqual(result["decision"], "planner_reply")
        self.assertEqual(len(stub.calls), 2)
        self.assertEqual(
            LLMCall.objects.filter(conversation=self.conv).exclude(error="").count(),
            1,
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
        # Fecha RELATIVA: la hardcodeada (2026-08-04) caducó el día que pasó a
        # ser pasado — `_v_date` la rechazaba, el slot no se llenaba y el
        # contador nunca se reseteaba. Cuarto test dependiente del reloj de la
        # misma familia (ver `_next_open_days`).
        day = _next_open_day(2)
        self._inbound("ese día")
        self._handle(StubLLMClient(scripted=[
            self._reg_call(date=day),
            LLMResult(kind="text", text="¿A qué hora?"),
        ]))
        goal = self._goal()
        self.assertEqual(goal.stall_turns, 0)
        self.assertEqual(goal.slots["date"]["value"], day)

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
        primero, segundo = _next_open_days(2, min_offset=2)
        self._inbound("regístrame")
        self._handle(StubLLMClient(scripted=[
            self._reg_call(date=primero),
            LLMResult(kind="text", text="¿A qué hora?"),
        ]))
        self._inbound("mejor el otro día")
        self._handle(StubLLMClient(scripted=[
            self._reg_call(date=segundo),
            LLMResult(kind="text", text="¿A qué hora?"),
        ]))
        goal = self._goal()
        self.assertEqual(goal.stall_turns, 0)
        # La corrección PISA el valor anterior: es avance, no repetición.
        self.assertEqual(goal.slots["date"]["value"], segundo)


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
        modelo SONDEA un día (lo captura desde una lectura) y el cliente elige
        otro, una segunda lectura NO corrige — 'date' ya no está en `missing`.
        Hoy lo salva que los args de ESCRITURA sí sobrescriben; este test ancla
        el comportamiento actual (bug conocido) antes de que Fase 3 lo reescriba
        (CR-7). NO es un cambio de código de Fase 0."""
        from apps.agent import goals
        # Dos días ABIERTOS y distintos, pedidos juntos: con offsets fijos el
        # test era intermitente (el sábado, "hoy+1" cae en domingo y no se
        # captura nada) y con dos `_next_open_day` independientes los dos días
        # podían colapsar en el mismo.
        first_probe, second_probe = _next_open_days(2)
        self._inbound("regístrame, tal vez ese día")
        self._handle(StubLLMClient(scripted=[
            LLMResult(kind="tool_call",
                      tool_name="register_new_client_and_pet",
                      tool_args={"owner_name": "Ana Torres",
                                 "pet_name": "Luna", "reason": "consulta"}),
            LLMResult(kind="tool_call", tool_name="find_available_slots",
                      tool_args={"date": first_probe}),
            LLMResult(kind="text", text="Ese día tengo espacio 🙂"),
        ]))
        goal = goals.get_open_goal(self.conv)
        self.assertEqual(goal.slots["date"]["value"], first_probe)

        self._inbound("mejor el otro día")
        self._handle(StubLLMClient(scripted=[
            LLMResult(kind="tool_call", tool_name="find_available_slots",
                      tool_args={"date": second_probe}),
            LLMResult(kind="text", text="También tengo ese otro día 🙂"),
        ]))
        goal = goals.get_open_goal(self.conv)
        # BUG conocido: se queda en el PRIMER día porque 'date' ya no estaba
        # `missing` cuando llegó el segundo sondeo.
        self.assertEqual(goal.slots["date"]["value"], first_probe)


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
