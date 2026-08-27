"""F2 — el agente consume las garantías del dominio (ADR p57).

Item 2, fase F2. Lo que se ancla aquí es que las garantías de F0/F1 dejan de
ser teóricas para el agente:

  · **INV-A**: cancelar y reprogramar viajan con `expected_state` —la tupla que
    el cliente vio parafraseada—, y el `409` resultante se traduce a
    conversación en vez de a avería.
  · **INV-B**: el alta manda `require_new_owner=true` **siempre**, y un
    teléfono con expediente preserva la intención y escala, sin escribir nada.
  · **C1–C4**: si la identidad cambió entre la propuesta y el «sí», no se llama
    ni al dominio.
  · **§5.5.4**: la suspensión y el hand-off ocurren en una sola transición; la
    intención del cliente no se pierde por el camino.

Atraviesan la API real por el mismo camino que producción (`run_tool` →
`policy.evaluate` → `planner._commit_pending`), sin LLM.
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.agent import confirmations, executor as executor_module
from apps.agent import planner, policy, tools
from apps.agent.executor import ToolExecutor
from apps.agent.models import (
    AgentSettings, ContactIdentity, Conversation, HumanHandoff, ToolExecution,
)
from apps.agent.tests.harness import set_schedule_day
from apps.appointments.models import Appointment
from apps.channels.models import ChannelAccount, Message
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSIONS
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User
from apps.users.services import ensure_agent_user


def _seed_role(org, role_name):
    codes = PERMISSIONS[role_name]
    role, _ = Role.objects.get_or_create(
        name=role_name, organization=org, defaults={"is_system_role": True})
    if "*.*" in codes:
        w, _ = Permission.objects.get_or_create(code="*.*")
        role.permissions.set([w])
    else:
        role.permissions.set(
            [Permission.objects.get_or_create(code=c)[0] for c in codes])
    return role


class HeaderForwardingTransport:
    """Reenvía los headers al test client → el loopback se comporta como en
    producción (RBAC del rol AGENT, idempotencia, tenant validators)."""

    def __call__(self, method, path, *, headers, params=None, json=None):
        client = APIClient()
        extra = {}
        for key, value in (headers or {}).items():
            if key.lower() == "authorization":
                extra["HTTP_AUTHORIZATION"] = value
            else:
                extra["HTTP_" + key.upper().replace("-", "_")] = value
        if method.upper() == "GET":
            r = client.get(path, data=params or {}, **extra)
        else:
            r = getattr(client, method.lower())(
                path, data=json or {}, format="json", **extra)
        try:
            return r.status_code, (r.json() if r.content else {})
        except ValueError:
            return r.status_code, {}


class CommitPreconditionBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="F2 Org", timezone="UTC")
        _seed_role(cls.org, "AGENT")
        vet_role = _seed_role(cls.org, "VET")
        cls.vet = User.objects.create_user(
            username="f2_vet", password="p", organization=cls.org, role="VET")
        UserRole.objects.get_or_create(user=cls.vet, role=vet_role)
        cls.owner = Owner.objects.create(
            organization=cls.org, name="Ana", phone="5511110000")
        cls.pet = Pet.objects.create(
            organization=cls.org, owner=cls.owner, name="Luna",
            species="perro", birth_date="2021-01-01")

    def setUp(self):
        executor_module._token_cache.clear()
        self.agent_user, _ = ensure_agent_user(self.org)
        d = timezone.localdate() + timedelta(days=7)
        while d.weekday() > 4:
            d += timedelta(days=1)
        self.day = d
        self.settings = AgentSettings.objects.create(
            organization=self.org, enabled=True, agent_user=self.agent_user,
            default_veterinarian=self.vet)
        set_schedule_day(self.org, d.weekday(), "09:00", "13:00")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="770200770")
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215511110000",
            owner=self.owner, verification_level="confirmed_in_chat")
        self.conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact)
        self.executor = ToolExecutor(
            self.conv, self.agent_user, transport=HeaderForwardingTransport())

    # -- helpers -----------------------------------------------------------
    def _make_appt(self, hhmm="11:00", status="scheduled"):
        start = datetime.strptime(hhmm, "%H:%M").time()
        end = (datetime.strptime(hhmm, "%H:%M") + timedelta(minutes=30)).time()
        appt = Appointment.objects.create(
            organization=self.org, pet=self.pet, veterinarian=self.vet,
            date=self.day, start_time=start, end_time=end, reason="control",
            status=status,
            start_datetime=datetime.combine(self.day, start, tzinfo=dt_tz.utc),
            end_datetime=datetime.combine(self.day, end, tzinfo=dt_tz.utc))
        handle = tools._add_ref(self.conv, "cita", appt.public_id)
        tools._save_refs(self.conv)
        return appt, handle

    def _move_appt(self, appt, hhmm):
        """Mueve la cita como lo haría el equipo desde /appointments.

        Los cuatro campos van juntos: `end_time` y los anchors UTC no son
        redundancia, son lo que comprueban `appointment_end_after_start` y la
        restricción de no-solapamiento.
        """
        start = datetime.strptime(hhmm, "%H:%M").time()
        end = (datetime.strptime(hhmm, "%H:%M") + timedelta(minutes=30)).time()
        appt.start_time, appt.end_time = start, end
        appt.start_datetime = datetime.combine(self.day, start, tzinfo=dt_tz.utc)
        appt.end_datetime = datetime.combine(self.day, end, tzinfo=dt_tz.utc)
        appt.save()
        return appt

    def _run(self, name, args, conversation=None, executor=None):
        return tools.run_tool(name, args, conversation=conversation or self.conv,
                              executor=executor or self.executor)

    def _commit(self, conversation=None, executor=None):
        convo = conversation or self.conv
        pending = confirmations.get_pending(convo)
        # Las herramientas se prueban aquí sin pasar por el planner. En
        # producción el planner siempre emite y enlaza este Message antes del
        # “sí”; el helper reproduce esa frontera, no un estado imposible.
        if pending and not confirmations.is_confirmable(convo, pending):
            proposal = Message.objects.create(
                organization=convo.organization,
                channel_account=convo.channel_account,
                conversation=convo, contact=convo.contact,
                direction=Message.DIRECTION_OUT,
                author_type=Message.AUTHOR_SYSTEM,
                semantic_type=Message.SEMANTIC_CONFIRMATION,
                operation_key=pending['proposal_id'],
                body=pending['paraphrase'], status=Message.STATUS_SENT,
            )
            confirmations.bind_pending_message(convo, proposal.pk)
        policy.evaluate(convo, "sí", agent_settings=self.settings)
        return planner._commit_pending(convo, executor or self.executor)

    def _last_out(self, conversation=None):
        m = (Message.objects.filter(conversation=conversation or self.conv,
                                    direction=Message.DIRECTION_OUT)
             .order_by("-id").first())
        return m.body if m else ""

    def _staged(self, conversation=None):
        return confirmations.get_pending(conversation or self.conv) or {}


class StagedPreconditionTests(CommitPreconditionBase):
    """§6.1 — la precondición se captura al PROPONER, no al confirmar."""

    def test_cancel_stages_the_tuple_the_client_saw(self):
        appt, handle = self._make_appt("11:00")
        self._run("cancel_appointment", {"appointment_handle": handle})
        args = self._staged()["args"]
        self.assertEqual(args["expected_status"], "scheduled")
        self.assertEqual(args["expected_date"], appt.date.isoformat())
        self.assertEqual(args["expected_start_time"], "11:00")

    def test_reschedule_stages_the_origin_not_the_destination(self):
        _appt, handle = self._make_appt("11:00")
        self._run("reschedule_appointment", {
            "appointment_handle": handle,
            "new_date": self.day.isoformat(), "new_time": "12:00"})
        args = self._staged()["args"]
        self.assertEqual(args["expected_start_time"], "11:00")   # origen
        self.assertEqual(args["start_time"], "12:00")            # destino

    def test_create_stages_the_public_id_for_reading(self):
        """El PK sigue siendo el del body; el `public_id` es para leer (ADR p18)."""
        pet_handle = tools._add_ref(self.conv, "mascota", self.pet.public_id)
        tools._save_refs(self.conv)
        self._run("create_appointment", {
            "pet_handle": pet_handle, "date": self.day.isoformat(),
            "time": "10:00", "reason": "Consulta"})
        args = self._staged()["args"]
        self.assertEqual(args["pet_public_id"], str(self.pet.public_id))
        self.assertEqual(args["pet"], self.pet.id)


class AppointmentChangedTests(CommitPreconditionBase):
    """INV-A consumido: el 409 se traduce a conversación, no a avería."""

    def test_cancel_of_a_moved_appointment_tells_the_client_what_changed(self):
        appt, handle = self._make_appt("11:00")
        self._run("cancel_appointment", {"appointment_handle": handle})

        # Alguien del equipo la movió mientras el cliente leía el parafraseo.
        self._move_appt(appt, "12:00")

        res = self._commit()
        self.assertEqual(res["decision"], "commit_appointment_changed")
        # La cita NO se canceló: el humano gana.
        appt.refresh_from_db()
        self.assertEqual(appt.status, "scheduled")
        # Y el cliente se entera de QUÉ pasó, no de un "falló, reintenta".
        self.assertIn("cambió", self._last_out())
        # No escaló: es información para el cliente, que está escribiendo ahora.
        self.assertFalse(HumanHandoff.objects.filter(
            conversation=self.conv, resolved_at__isnull=True).exists())

    def test_reschedule_of_a_canceled_appointment_does_not_resurrect_it(self):
        """El caso que motivó el Item: no resucitar lo que alguien canceló."""
        appt, handle = self._make_appt("11:00")
        self._run("reschedule_appointment", {
            "appointment_handle": handle,
            "new_date": self.day.isoformat(), "new_time": "12:00"})

        appt.status = "canceled"
        appt.save(update_fields=["status"])

        res = self._commit()
        self.assertEqual(res["decision"], "replacement_confirmation")
        appt.refresh_from_db()
        self.assertEqual(appt.status, "canceled")
        replacement = confirmations.get_pending(self.conv)
        self.assertEqual(replacement["tool"], "create_appointment")
        self.assertTrue(confirmations.is_confirmable(self.conv, replacement))

        committed = self._commit()
        self.assertEqual(committed["decision"], "committed")
        replacement_appt = Appointment.objects.exclude(pk=appt.pk).get()
        self.assertEqual(replacement_appt.date, self.day)
        self.assertEqual(replacement_appt.start_time.strftime("%H:%M"), "12:00")
        self.assertEqual(replacement_appt.status, "scheduled")

    def test_no_automatic_retry_without_the_precondition(self):
        """R5/§5.3: reintentar sin `expected_state` ES la sobrescritura."""
        appt, handle = self._make_appt("11:00")
        self._run("cancel_appointment", {"appointment_handle": handle})
        self._move_appt(appt, "12:00")

        before = ToolExecution.objects.filter(conversation=self.conv).count()
        self._commit()
        after = ToolExecution.objects.filter(conversation=self.conv).count()
        # Exactamente UNA llamada de escritura: la que recibió el 409.
        self.assertEqual(after - before, 1)
        # Y la propuesta se descarta: no queda nada que un "sí" posterior
        # pudiera ejecutar sobre un mundo que ya cambió.
        self.assertIsNone(confirmations.get_pending(self.conv))

    def test_business_conflict_is_not_logged_as_an_integration_failure(self):
        """§5.4: un 409 declarado no puede contaminar las alertas de avería."""
        appt, handle = self._make_appt("11:00")
        self._run("cancel_appointment", {"appointment_handle": handle})
        appt.status = "canceled"
        appt.save(update_fields=["status"])

        with self.assertLogs("agent.events", level="INFO") as captured:
            self._commit()
        events = " ".join(captured.output)
        self.assertIn("AGENT_TOOL_BUSINESS_CONFLICT", events)
        self.assertNotIn("AGENT_TOOL_HTTP_ERROR", events)
        # La traza NO se pierde: la fila de auditoría sigue ahí con su código.
        self.assertTrue(ToolExecution.objects.filter(
            conversation=self.conv, error_code="appointment_changed").exists())


class AlreadyDoneTests(CommitPreconditionBase):
    """§3.2 exigencia 4: «ya estaba como querías» es éxito, no conflicto."""

    def test_canceling_an_already_canceled_appointment_closes_the_goal(self):
        appt, handle = self._make_appt("11:00")
        self._run("cancel_appointment", {"appointment_handle": handle})
        appt.status = "canceled"
        appt.save(update_fields=["status"])

        res = self._commit()
        self.assertEqual(res["decision"], "commit_already_done")
        self.assertIn("Ya estaba cancelada", self._last_out())
        # No escala: antes este caso rebotaba a una persona para nada.
        self.assertFalse(HumanHandoff.objects.filter(
            conversation=self.conv, resolved_at__isnull=True).exists())

    def test_rescheduling_to_where_it_already_is(self):
        appt, handle = self._make_appt("11:00")
        self._run("reschedule_appointment", {
            "appointment_handle": handle,
            "new_date": self.day.isoformat(), "new_time": "12:00"})
        # El equipo ya la movió justo a donde el cliente pedía.
        self._move_appt(appt, "12:00")

        res = self._commit()
        self.assertEqual(res["decision"], "commit_already_done")


class HappyPathUnchangedTests(CommitPreconditionBase):
    """Iron rule: con el mundo quieto, el comportamiento es el de siempre."""

    def test_cancel_still_works(self):
        appt, handle = self._make_appt("11:00")
        self._run("cancel_appointment", {"appointment_handle": handle})
        res = self._commit()
        self.assertEqual(res["decision"], "committed")
        appt.refresh_from_db()
        self.assertEqual(appt.status, "canceled")

    def test_reschedule_still_works(self):
        appt, handle = self._make_appt("11:00")
        self._run("reschedule_appointment", {
            "appointment_handle": handle,
            "new_date": self.day.isoformat(), "new_time": "12:00"})
        res = self._commit()
        self.assertEqual(res["decision"], "committed")
        appt.refresh_from_db()
        self.assertEqual(appt.start_time.strftime("%H:%M"), "12:00")
        self.assertEqual(appt.status, "scheduled")


class RegisterIdentityTests(CommitPreconditionBase):
    """INV-B consumido: el alta del agente exige expediente NUEVO (C5)."""

    def _unknown_conv(self, wa="5215512345678"):
        contact = ContactIdentity.objects.create(
            organization=self.org, external_id=wa,
            verification_level="unknown")
        conv = Conversation.objects.create(
            organization=self.org,
            channel_account=self.channel,
            contact=contact,
            # Estas pruebas parten después de que el modelo clasificó que el
            # contacto es nuevo; reflejan el hecho persistido, no una frase.
            intake_path=Conversation.INTAKE_NEW_CLIENT,
        )
        ex = ToolExecutor(conv, self.agent_user,
                          transport=HeaderForwardingTransport())
        return conv, ex

    def _propose_register(self, conv, ex):
        return self._run("register_new_client_and_pet", {
            "owner_name": "Carlos", "pet_name": "Rocky",
            "date": self.day.isoformat(), "time": "10:00", "reason": "Consulta"},
            conversation=conv, executor=ex)

    def test_zero_matches_registers_and_links(self):
        """Sin expediente previo, la premisa «cliente nuevo» es cierta."""
        conv, ex = self._unknown_conv()
        self._propose_register(conv, ex)
        res = self._commit(conv, ex)
        self.assertEqual(res["decision"], "committed")
        owner = Owner.objects.get(phone="5512345678")
        self.assertEqual(Appointment.objects.filter(pet__owner=owner).count(), 1)
        conv.contact.refresh_from_db()
        self.assertEqual(conv.contact.owner_id, owner.id)

    def test_existing_owner_preserves_the_intention_and_escalates(self):
        """§5.2: cero escrituras, caso de identidad abierto, intención viva."""
        existing = Owner.objects.create(
            organization=self.org, name="Cliente Previo", phone="5512345678")
        conv, ex = self._unknown_conv()
        self._propose_register(conv, ex)
        staged_before = confirmations.get_pending(conv)["args"]

        res = self._commit(conv, ex)
        self.assertEqual(res["decision"], "escalate")
        self.assertEqual(res["reason"], "owner_exists")

        # 1. Cero escrituras en el dominio.
        self.assertEqual(Owner.objects.filter(phone="5512345678").count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.name, "Cliente Previo")
        self.assertEqual(Appointment.objects.filter(pet__owner=existing).count(), 0)
        self.assertFalse(Pet.objects.filter(name="Rocky").exists())

        # 2. La intención NO se perdió: quedó suspendida ÍNTEGRA.
        conv.refresh_from_db()
        self.assertNotIn("pending_action", conv.flow)
        suspended = conv.flow["suspended"]
        self.assertEqual(suspended["state"]["args"], staged_before)
        self.assertEqual(suspended["handoff_reason"], HumanHandoff.REASON_IDENTITY)
        self.assertTrue(suspended["suspension_id"])

        # 3. El caso de identidad está abierto, con su discriminador.
        handoff = HumanHandoff.objects.get(
            conversation=conv, resolved_at__isnull=True)
        self.assertEqual(handoff.reason_code, HumanHandoff.REASON_IDENTITY)
        self.assertEqual(handoff.reason_detail, "owner_exists")
        self.assertEqual(conv.state, Conversation.STATE_HANDOFF_PENDING)

        # 4. El contacto sigue sin vincular: el teléfono localiza, no autoriza.
        conv.contact.refresh_from_db()
        self.assertIsNone(conv.contact.owner_id)

    def test_ambiguous_phone_opens_the_case_with_its_own_detail(self):
        """La diferencia le importa al staff, no al cliente (§5.2)."""
        Owner.objects.create(organization=self.org, name="Ana L", phone="55 1234 5678")
        Owner.objects.create(organization=self.org, name="Ana Lopez", phone="5512345678")
        conv, ex = self._unknown_conv()
        self._propose_register(conv, ex)

        res = self._commit(conv, ex)
        self.assertEqual(res["reason"], "owner_ambiguous")
        handoff = HumanHandoff.objects.get(
            conversation=conv, resolved_at__isnull=True)
        self.assertEqual(handoff.reason_detail, "owner_ambiguous")
        conv.refresh_from_db()
        self.assertIn("suspended", conv.flow)
        self.assertFalse(Pet.objects.filter(name="Rocky").exists())

    def test_the_client_gets_the_same_message_either_way(self):
        conv_a, ex_a = self._unknown_conv("5215512345678")
        Owner.objects.create(organization=self.org, name="Previo", phone="5512345678")
        self._propose_register(conv_a, ex_a)
        self._commit(conv_a, ex_a)

        conv_b, ex_b = self._unknown_conv("5215599998888")
        Owner.objects.create(organization=self.org, name="A", phone="55 9999 8888")
        Owner.objects.create(organization=self.org, name="B", phone="5599998888")
        self._propose_register(conv_b, ex_b)
        self._commit(conv_b, ex_b)

        self.assertEqual(self._last_out(conv_a), self._last_out(conv_b))

    def test_identity_resolved_during_handoff_does_not_call_the_domain(self):
        """C2 (§4.5): el humano ya lo registró — buena noticia, no error."""
        conv, ex = self._unknown_conv()
        self._propose_register(conv, ex)

        # Una persona resolvió la identidad mientras tanto.
        resolved = Owner.objects.create(
            organization=self.org, name="Carlos Real", phone="5512345678")
        conv.contact.owner = resolved
        conv.contact.verification_level = "staff_verified"
        conv.contact.save(update_fields=["owner", "verification_level"])

        before = ToolExecution.objects.filter(conversation=conv).count()
        res = self._commit(conv, ex)
        self.assertEqual(res["decision"], "commit_identity_changed")
        # Ni siquiera se llamó al dominio.
        self.assertEqual(
            ToolExecution.objects.filter(conversation=conv).count(), before)
        self.assertEqual(Appointment.objects.filter(pet__owner=resolved).count(), 0)
        # No escala: la conversación sigue por la vía de cliente conocido.
        self.assertFalse(HumanHandoff.objects.filter(
            conversation=conv, resolved_at__isnull=True).exists())
        self.assertIn("registrado", self._last_out(conv))

    def test_ambiguity_appearing_during_handoff_blocks_the_write(self):
        """C3: el teléfono se volvió ambiguo entre la propuesta y el «sí»."""
        conv, ex = self._unknown_conv()
        self._propose_register(conv, ex)
        conv.contact.is_ambiguous = True
        conv.contact.save(update_fields=["is_ambiguous"])

        res = self._commit(conv, ex)
        self.assertEqual(res["decision"], "commit_identity_changed")
        self.assertFalse(Pet.objects.filter(name="Rocky").exists())

    def test_a_different_number_cannot_confirm_someone_elses_proposal(self):
        """C4: el número que propuso es el que confirma."""
        conv, ex = self._unknown_conv()
        self._propose_register(conv, ex)
        conv.contact.external_id = "5215500000000"
        conv.contact.save(update_fields=["external_id"])

        res = self._commit(conv, ex)
        self.assertEqual(res["decision"], "commit_identity_changed")
        self.assertFalse(Owner.objects.filter(name="Carlos").exists())

    def test_the_alta_always_asks_for_a_new_record(self):
        """C5 no es «para contactos reseteados»: viaja SIEMPRE (§4.3).

        Se observa el body real que sale hacia el dominio: que el desenlace sea
        correcto en los casos de arriba no prueba que la bandera se envíe —
        podría estar acertando por otra razón.
        """
        conv, ex = self._unknown_conv()
        sent = {}
        real_call = ex.call

        def spy(method, path, **kwargs):
            if path.endswith('/create-with-patient/'):
                sent.update(kwargs.get('json') or {})
            return real_call(method, path, **kwargs)

        ex.call = spy
        self._propose_register(conv, ex)
        res = self._commit(conv, ex)

        self.assertEqual(res["decision"], "committed")   # cliente nuevo de verdad
        self.assertIs(sent.get('require_new_owner'), True)
