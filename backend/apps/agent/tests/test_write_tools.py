"""
test_write_tools.py — É-F2 PR-16: escritura de agenda con confirmación tier-2.

Atraviesan la API REAL (RBAC del rol AGENT, tenant validators, idempotencia)
vía el Django test client — sin LLM: las tools se invocan por `run_tool` y la
afirmativa por `policy.evaluate` + `planner._commit_pending`, de modo que se
prueba el contrato determinista (propone → confirma → ejecuta lo STAGED).
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.agent import executor as executor_module
from apps.agent import confirmations, planner, policy, tools
from apps.agent.executor import ToolExecutor
from apps.agent.tests.harness import set_schedule_day
from apps.agent.models import AgentSettings, ContactIdentity, Conversation
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
    """Reenvía TODOS los headers (Authorization + X-Idempotency-Key +
    X-Request-ID) al test client → el loopback se comporta como en producción."""

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


class WriteToolsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Write Org", timezone="UTC")
        _seed_role(cls.org, "AGENT")
        vet_role = _seed_role(cls.org, "VET")
        cls.vet = User.objects.create_user(
            username="w_vet", password="p", organization=cls.org, role="VET")
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
        wd = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[d.weekday()]
        self.settings = AgentSettings.objects.create(
            organization=self.org, enabled=True, agent_user=self.agent_user,
            default_veterinarian=self.vet)
        set_schedule_day(self.org, d.weekday(), "09:00", "13:00")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="770100770")
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215511110000",
            owner=self.owner, verification_level="confirmed_in_chat")
        self.conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact)
        self.executor = ToolExecutor(
            self.conv, self.agent_user, transport=HeaderForwardingTransport())

    # -- helpers ------------------------------------------------------------
    def _pet_handle(self):
        h = tools._add_ref(self.conv, "mascota", self.pet.public_id)
        tools._save_refs(self.conv)
        return h

    def _make_appt(self, hhmm="11:00", status="scheduled"):
        start = datetime.strptime(hhmm, "%H:%M").time()
        end = (datetime.strptime(hhmm, "%H:%M") + timedelta(minutes=30)).time()
        appt = Appointment.objects.create(
            organization=self.org, pet=self.pet, veterinarian=self.vet,
            date=self.day, start_time=start, end_time=end, reason="control",
            status=status,
            start_datetime=datetime.combine(self.day, start, tzinfo=dt_tz.utc),
            end_datetime=datetime.combine(self.day, end, tzinfo=dt_tz.utc))
        h = tools._add_ref(self.conv, "cita", appt.public_id)
        tools._save_refs(self.conv)
        return appt, h

    def _run(self, name, args):
        return tools.run_tool(name, args, conversation=self.conv,
                              executor=self.executor)

    def _paraphrase(self, conversation=None):
        """El parafraseo tier-2 vive en el `pending_action` staged, no en el
        `ToolOutcome`: desde ADR p55 §4 una tool devuelve hechos, no copy."""
        pending = confirmations.get_pending(conversation or self.conv)
        return (pending or {}).get('paraphrase', '')

    def _ensure_confirmation_proposal(self, conversation=None):
        conversation = conversation or self.conv
        pending = confirmations.get_pending(conversation)
        if not pending or confirmations.is_confirmable(conversation, pending):
            return

        proposal = Message.objects.create(
            organization=conversation.organization,
            channel_account=conversation.channel_account,
            conversation=conversation,
            contact=conversation.contact,
            direction=Message.DIRECTION_OUT,
            author_type=Message.AUTHOR_SYSTEM,
            semantic_type=Message.SEMANTIC_CONFIRMATION,
            operation_key=pending['proposal_id'],
            body=pending['paraphrase'],
            status=Message.STATUS_SENT,
        )
        confirmations.bind_pending_message(conversation, proposal.pk)

    def _affirm(self, text="sí", *, conversation=None):
        conversation = conversation or self.conv
        self._ensure_confirmation_proposal(conversation)
        return policy.evaluate(conversation, text, agent_settings=self.settings)

    def _last_out(self):
        m = (Message.objects.filter(conversation=self.conv,
                                    direction=Message.DIRECTION_OUT)
             .order_by("-created_at", "-id").first())
        return m.body if m else ""

    # -- crear --------------------------------------------------------------
    def test_create_proposes_not_executes(self):
        out = self._run("create_appointment", {
            "pet_handle": self._pet_handle(), "date": self.day.isoformat(),
            "time": "10:00", "reason": "Vacunación"})
        self.assertTrue(out.ok, out.client_error)
        self.assertIn("Luna", self._paraphrase())
        pending = confirmations.get_pending(self.conv)
        self.assertIsNotNone(pending)
        self.assertEqual(pending["tool"], "create_appointment")
        self.assertEqual(pending["args"]["pet"], self.pet.pk)  # PK en el body
        self.assertTrue(pending["args"]["idempotency_key"])
        self.assertEqual(Appointment.objects.count(), 0)  # aún no crea

    def test_affirmative_commits_exact_staged(self):
        self._run("create_appointment", {
            "pet_handle": self._pet_handle(), "date": self.day.isoformat(),
            "time": "10:00", "reason": "Vacunación"})
        decision = self._affirm("sí, agéndala")
        self.assertEqual(decision.kind, policy.RUN_PLANNER)
        self.assertEqual(decision.meta.get("confirm"), "affirmative")

        res = planner._commit_pending(self.conv, self.executor)
        self.assertEqual(res["decision"], "committed")
        self.assertEqual(Appointment.objects.count(), 1)
        appt = Appointment.objects.get()
        self.assertEqual(appt.pet, self.pet)          # TC-SEC-03: pet staged
        self.assertEqual(appt.status, "scheduled")
        self.assertIn("asistente virtual", appt.notes)
        self.assertIsNone(confirmations.get_pending(self.conv))  # limpio
        self.assertIn("Listo", self._last_out())

    def test_create_past_date_rejected(self):
        past = (timezone.localdate() - timedelta(days=1)).isoformat()
        out = self._run("create_appointment", {
            "pet_handle": self._pet_handle(), "date": past, "time": "10:00",
            "reason": "x"})
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, "past_date")
        self.assertIsNone(confirmations.get_pending(self.conv))

    def test_create_requires_verification(self):
        self.contact.verification_level = "phone_match"
        self.contact.owner = None
        self.contact.save()
        out = self._run("create_appointment", {
            "pet_handle": "mascota_1", "date": self.day.isoformat(),
            "time": "10:00", "reason": "x"})
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, "verification_required")

    def test_create_unknown_pet_handle(self):
        out = self._run("create_appointment", {
            "pet_handle": "mascota_99", "date": self.day.isoformat(),
            "time": "10:00", "reason": "x"})
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, "unknown_handle")

    # -- confirmar (tier-1) -------------------------------------------------
    def test_confirm_is_immediate(self):
        appt, handle = self._make_appt(status="scheduled")
        out = self._run("confirm_appointment", {"appointment_handle": handle})
        self.assertTrue(out.ok, out.client_error)
        self.assertIsNone(confirmations.get_pending(self.conv))  # sin propuesta
        appt.refresh_from_db()
        self.assertEqual(appt.status, "confirmed")

    # -- cancelar -----------------------------------------------------------
    def test_cancel_proposes_and_commits(self):
        appt, handle = self._make_appt(status="confirmed")
        out = self._run("cancel_appointment", {
            "appointment_handle": handle, "reason": "se enfermó"})
        self.assertIn("Luna", self._paraphrase())

        self._affirm("sí")
        res = planner._commit_pending(self.conv, self.executor)
        self.assertEqual(res["decision"], "committed")
        appt.refresh_from_db()
        self.assertEqual(appt.status, "canceled")
        self.assertIn("asistente virtual", appt.cancellation_reason)

    def test_cancel_past_appointment_is_not_proposed(self):
        # Use a fixed daytime instant so this fixture remains valid at midnight.
        past = (timezone.now() - timedelta(days=1)).replace(
            hour=10, minute=0, second=0, microsecond=0)
        appt = Appointment.objects.create(
            organization=self.org, pet=self.pet, veterinarian=self.vet,
            date=past.date(),
            start_time=past.time().replace(second=0, microsecond=0),
            end_time=(past + timedelta(minutes=30)).time().replace(
                second=0, microsecond=0),
            reason="control", status="scheduled",
            start_datetime=past, end_datetime=past + timedelta(minutes=30),
        )
        handle = tools._add_ref(self.conv, "cita", appt.public_id)
        tools._save_refs(self.conv)

        out = self._run("cancel_appointment", {"appointment_handle": handle})

        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, "past_appointment")
        self.assertIsNone(confirmations.get_pending(self.conv))

    def test_negative_discards_pending(self):
        appt, handle = self._make_appt(status="confirmed")
        self._run("cancel_appointment", {"appointment_handle": handle})
        self.assertIsNotNone(confirmations.get_pending(self.conv))
        # "no" descarta el pending (policy §7 negative)
        decision = policy.evaluate(self.conv, "no, mejor no",
                                   agent_settings=self.settings)
        self.assertIsNone(confirmations.get_pending(self.conv))
        appt.refresh_from_db()
        self.assertEqual(appt.status, "confirmed")   # NO se canceló

    # -- reagendar ----------------------------------------------------------
    def test_reschedule_proposes_and_commits(self):
        appt, handle = self._make_appt(hhmm="09:00", status="scheduled")
        out = self._run("reschedule_appointment", {
            "appointment_handle": handle, "new_date": self.day.isoformat(),
            "new_time": "12:00"})
        self.assertIsNotNone(confirmations.get_pending(self.conv))

        self._affirm("sí")
        res = planner._commit_pending(self.conv, self.executor)
        self.assertEqual(res["decision"], "committed")
        appt.refresh_from_db()
        self.assertEqual(appt.start_time.strftime("%H:%M"), "12:00")

    def test_reschedule_past_date_rejected(self):
        appt, handle = self._make_appt(status="scheduled")
        past = (timezone.localdate() - timedelta(days=1)).isoformat()
        out = self._run("reschedule_appointment", {
            "appointment_handle": handle, "new_date": past, "new_time": "10:00"})
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, "past_date")

    # -- alta de cliente nuevo (T11, PR-17a) --------------------------------
    def _unknown_conv(self, wa="5215512345678"):
        contact = ContactIdentity.objects.create(
            organization=self.org, external_id=wa,
            verification_level="unknown")
        conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel, contact=contact)
        ex = ToolExecutor(conv, self.agent_user,
                          transport=HeaderForwardingTransport())
        return conv, ex

    def test_register_proposes_new_client(self):
        conv, ex = self._unknown_conv()
        out = tools.run_tool("register_new_client_and_pet", {
            "owner_name": "Carlos", "pet_name": "Rocky", "pet_species": "perro",
            "date": self.day.isoformat(), "time": "10:00", "reason": "Consulta"},
            conversation=conv, executor=ex)
        self.assertTrue(out.ok, out.client_error)
        self.assertIn("Carlos", self._paraphrase(conv))
        self.assertIn("Rocky", self._paraphrase(conv))
        pending = confirmations.get_pending(conv)
        self.assertEqual(pending["args"]["owner_phone"], "5512345678")  # 10 díg
        self.assertEqual(Owner.objects.filter(phone="5512345678").count(), 0)

    def test_register_commits_and_autolinks(self):
        conv, ex = self._unknown_conv()
        tools.run_tool("register_new_client_and_pet", {
            "owner_name": "Carlos", "pet_name": "Rocky",
            "date": self.day.isoformat(), "time": "10:00", "reason": "Consulta"},
            conversation=conv, executor=ex)
        self._affirm("sí", conversation=conv)
        res = planner._commit_pending(conv, ex)
        self.assertEqual(res["decision"], "committed")
        owner = Owner.objects.get(phone="5512345678")
        self.assertEqual(owner.name, "Carlos")
        self.assertEqual(Appointment.objects.filter(pet__owner=owner).count(), 1)
        conv.contact.refresh_from_db()
        self.assertEqual(conv.contact.owner_id, owner.id)           # auto-vínculo
        self.assertEqual(conv.contact.verification_level, "confirmed_in_chat")
        self.assertEqual(conv.contact.linked_via, "self_register")

    def test_register_after_reset_does_not_relink_existing_owner(self):
        """Item 1 (regla de seguridad ampliada, auditoría OCR 2026-08-08): un
        contacto reseteado (`reset_contact_identity`) que completa el alta de
        "cliente nuevo" en la MISMA conversación no debe re-vincularse al
        Owner existente que comparte su teléfono.

        **Con F2 la garantía se refuerza y el desenlace cambia** (INV-B): el
        alta del agente viaja con `require_new_owner=true`, así que el dominio
        rechaza con `409 owner_exists` ANTES de escribir nada. Ya no es que se
        reutilice el Owner y se suprima el vínculo: es que no se toca el
        expediente, no se crea la cita y la decisión pasa a una persona.

        El guard `auto_rematch_blocked` sigue en su sitio como segunda defensa
        (§4.4) y, sobre todo, **sigue levantado**: nada de este camino lo
        limpia."""
        existing_owner = Owner.objects.create(
            organization=self.org, name="Cliente Previo", phone="5512345678")
        conv, ex = self._unknown_conv()   # wa_id normaliza a phone 5512345678
        conv.contact.auto_rematch_blocked = True
        conv.contact.save(update_fields=["auto_rematch_blocked"])

        tools.run_tool("register_new_client_and_pet", {
            "owner_name": "Carlos", "pet_name": "Rocky",
            "date": self.day.isoformat(), "time": "10:00", "reason": "Consulta"},
            conversation=conv, executor=ex)
        self._affirm("sí", conversation=conv)
        res = planner._commit_pending(conv, ex)
        self.assertEqual(res["decision"], "escalate")
        self.assertEqual(res["reason"], "owner_exists")

        # CERO escrituras: ni un segundo Owner, ni el nombre real pisado, ni
        # una cita colgada de un expediente ajeno.
        self.assertEqual(Owner.objects.filter(phone="5512345678").count(), 1)
        untouched = Owner.objects.get(phone="5512345678")
        self.assertEqual(untouched.pk, existing_owner.pk)
        self.assertEqual(untouched.name, "Cliente Previo")
        self.assertEqual(Appointment.objects.filter(pet__owner=untouched).count(), 0)

        conv.contact.refresh_from_db()
        self.assertIsNone(conv.contact.owner_id)
        self.assertEqual(conv.contact.verification_level, "unknown")
        self.assertTrue(conv.contact.auto_rematch_blocked)   # el reset sigue en pie
        self.assertEqual(conv.contact.linked_via, "")
        self.assertTrue(conv.contact.auto_rematch_blocked)

    def test_register_refused_for_existing_client(self):
        out = self._run("register_new_client_and_pet", {
            "owner_name": "X", "pet_name": "Y", "date": self.day.isoformat(),
            "time": "10:00", "reason": "z"})
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, "already_client")
        self.assertIsNone(confirmations.get_pending(self.conv))

    # -- proactividad UX (PR-18) -------------------------------------------
    def test_post_scheduling_info_on_create(self):
        self.settings.faq_facts = {"direccion": "Av. Siempre Viva 123"}
        self.settings.save(update_fields=["faq_facts"])
        self._run("create_appointment", {
            "pet_handle": self._pet_handle(), "date": self.day.isoformat(),
            "time": "10:00", "reason": "Vacunación"})
        self._affirm("sí")
        planner._commit_pending(self.conv, self.executor)
        out = self._last_out()
        self.assertIn("Av. Siempre Viva 123", out)   # UX-09 dirección
        self.assertIn("📍", out)

    def test_retention_offer_on_cancel(self):
        for weekday in range(7):          # abierta toda la semana
            set_schedule_day(self.org, weekday, "09:00", "13:00")
        appt, handle = self._make_appt(status="confirmed")
        self._run("cancel_appointment", {"appointment_handle": handle})
        self._affirm("sí")
        planner._commit_pending(self.conv, self.executor)
        out = self._last_out()
        self.assertIn("cancelé tu cita", out)
        self.assertIn("te reagendo", out)            # UX-11 retención con horario

    # -- expiración del pending --------------------------------------------
    def test_expired_pending_reparaphrases_not_executes(self):
        confirmations.stage_pending(
            self.conv,
            tool="create_appointment",
            args={"pet": self.pet.pk, "veterinarian": self.vet.pk,
                  "date": self.day.isoformat(), "start_time": "10:00",
                  "end_time": "10:30", "reason": "x", "notes": "",
                  "idempotency_key": "k"},
            paraphrase="¿Es correcto?",
        )
        pending = confirmations.get_pending(self.conv)
        pending["expires_at"] = (
            timezone.now() - timedelta(minutes=1)).isoformat()
        self.conv.flow["pending_action"] = pending
        self.conv.save(update_fields=["flow"])

        decision = self._affirm("sí")
        self.assertEqual(decision.meta.get("confirm"), "affirmative")
        res = planner._commit_pending(self.conv, self.executor)
        self.assertEqual(res["decision"], "confirm_expired")
        self.assertEqual(Appointment.objects.count(), 0)          # NO ejecutó
        self.assertIn("de nuevo", self._last_out())
        # el pending se re-armó con nueva expiración futura
        pending = confirmations.get_pending(self.conv)
        self.assertFalse(confirmations.is_expired(pending))


class AddPetForExistingClientTests(WriteToolsTests):
    """Mascota nueva de un cliente YA identificado.

    El hueco que cierra: `register_new_client_and_pet` se niega con
    `already_client` y `create_appointment` exige un `pet_handle` que solo sale
    de `list_my_pets`. Un cliente conocido con OTRA mascota no tenía camino, y
    el modelo lo prometía igual: en el piloto acabó en hand-off por
    estancamiento tras cinco turnos (conv 17).
    """

    def test_proposes_without_asking_the_client_name_again(self):
        out = self._run("register_pet_and_schedule", {
            "pet_name": "Koler", "pet_species": "perro",
            "date": self.day.isoformat(), "time": "10:00", "reason": "baño"})
        self.assertTrue(out.ok, out.client_error)
        paraphrase = self._paraphrase()
        self.assertIn("Koler", paraphrase)
        # Ya es cliente: volver a decirle "te registro como cliente" es lo que
        # hace sentir que el sistema no lo reconoce.
        self.assertNotIn("te registro como cliente", paraphrase)
        self.assertEqual(Pet.objects.filter(name="Koler").count(), 0)

    def test_commit_creates_pet_and_appointment(self):
        self._run("register_pet_and_schedule", {
            "pet_name": "Koler", "pet_species": "perro",
            "date": self.day.isoformat(), "time": "10:00", "reason": "baño"})
        self._affirm("sí")
        res = planner._commit_pending(self.conv, self.executor)
        self.assertEqual(res["decision"], "committed", res)

        pet = Pet.objects.get(name="Koler")
        # INV-B: cuelga del expediente VINCULADO, no de uno resuelto ahora por
        # teléfono.
        self.assertEqual(pet.owner, self.owner)
        self.assertEqual(Appointment.objects.filter(pet=pet).count(), 1)

    def test_pet_only_registers_without_appointment(self):
        out = self._run("register_pet_only", {
            "pet_name": "Koler", "pet_species": "perro"})
        self.assertTrue(out.ok, out.client_error)
        self.assertIn("sin cita", self._paraphrase())
        self._affirm("sí")
        planner._commit_pending(self.conv, self.executor)

        self.assertEqual(Pet.objects.filter(name="Koler").count(), 1)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_duplicate_name_offers_the_existing_pet_instead(self):
        """No crea una segunda «Luna»; devuelve el handle de la que hay.

        Negarse sin alternativa sería otro callejón — el modelo necesita poder
        seguir por la vía normal de agendar.
        """
        out = self._run("register_pet_and_schedule", {
            "pet_name": "luna",  # sin mayúscula: la comparación normaliza
            "date": self.day.isoformat(), "time": "10:00", "reason": "baño"})
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, "pet_exists")
        self.assertTrue(out.data.get("mascota_handle"))
        self.assertEqual(Pet.objects.filter(owner=self.owner).count(), 1)
        self.assertIsNone(confirmations.get_pending(self.conv))

    def test_a_contact_without_record_never_reaches_the_tool(self):
        """Sin expediente no hay verificación posible, y el gate corta antes.

        `_verification_ok` devuelve False en cuanto `owner_id is None`, así que
        el `not_a_client` del handler no se alcanza por esta vía — queda como
        guarda defensiva para una llamada directa. Se afirma lo que de verdad
        pasa, no lo que uno esperaría leyendo solo el handler: un test que
        afirmara `not_a_client` estaría documentando una rama muerta.
        """
        self.contact.owner = None
        self.contact.save(update_fields=["owner"])
        out = self._run("register_pet_and_schedule", {
            "pet_name": "Koler", "date": self.day.isoformat(),
            "time": "10:00", "reason": "baño"})
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, "verification_required")
        self.assertEqual(Pet.objects.filter(name="Koler").count(), 0)

    def test_a_family_link_cannot_open_records_on_the_titular(self):
        """Un familiar consulta y mueve citas, pero no abre expedientes."""
        self.contact.linked_via = ContactIdentity.LINKED_FAMILY
        self.contact.save(update_fields=["linked_via"])
        out = self._run("register_pet_and_schedule", {
            "pet_name": "Koler", "date": self.day.isoformat(),
            "time": "10:00", "reason": "baño"})
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, "family_restricted")

    def test_phone_match_alone_is_not_enough(self):
        """INV-B: escribir en el expediente exige `confirmed_in_chat`."""
        self.contact.verification_level = "phone_match"
        self.contact.save(update_fields=["verification_level"])
        out = self._run("register_pet_and_schedule", {
            "pet_name": "Koler", "date": self.day.isoformat(),
            "time": "10:00", "reason": "baño"})
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, "verification_required")

    def test_when_the_slot_dies_the_pet_still_says_it_was_saved(self):
        """Callarlo dejaría al cliente creyendo que no pasó nada, y al
        siguiente intento chocando con `pet_exists`."""
        self._run("register_pet_and_schedule", {
            "pet_name": "Koler", "date": self.day.isoformat(),
            "time": "10:00", "reason": "baño"})
        # El hueco se ocupa entre la propuesta y el «sí».
        self._make_appt(hhmm="10:00")
        self._affirm("sí")
        planner._commit_pending(self.conv, self.executor)

        self.assertEqual(Pet.objects.filter(name="Koler").count(), 1)
        self.assertIn("Koler", self._last_out())


class ToolErrorCopyIsReachableTests(TestCase):
    """Todo `client_error` que una herramienta devuelve tiene texto para el
    modelo.

    Existía `already_a_client` en el diccionario y `already_client` en la
    herramienta: no casaban, así que el modelo recibía el genérico «no se
    completó» y no podía explicarle nada al cliente. Una errata en un dict de
    copy indexado por código no rompe nada — solo empobrece en silencio.
    """

    def test_no_client_error_falls_back_to_the_generic_text(self):
        import re
        from pathlib import Path
        from apps.agent import planner

        source = Path(tools.__file__).read_text(encoding="utf-8")
        emitted = set(re.findall(r"client_error='([a-z_]+)'", source))
        # Los que el planner maneja como flujo propio (suspender, escalar,
        # cerrar) en vez de contárselos al modelo, y los puramente internos
        # que ninguna conversación puede provocar.
        handled_elsewhere = {
            "identity_changed", "owner_exists", "owner_ambiguous",
            "appointment_changed", "already_done",
            "pet_saved_appointment_failed",   # el planner redacta el suyo
            "bad_phone",     # el wa_id lo pone WhatsApp, no el cliente
            "unknown_tool",  # el modelo pidió algo que no existe
        }
        generic = planner._error_fact("__inexistente__")
        for code in sorted(emitted - handled_elsewhere):
            with self.subTest(client_error=code):
                self.assertNotEqual(
                    planner._error_fact(code), generic,
                    f"`{code}` no tiene texto propio: el modelo recibirá el "
                    f"genérico y no podrá decirle al cliente qué pasó.")


class NeverLieAboutTheSlotTests(WriteToolsTests):
    """Nunca decirle «se ocupó» a quien ocupa el hueco.

    Conv 18 del piloto: el agente creó la cita, respondió «¡Listo! ✅» y, al
    recibir un «gracias», volvió a intentar agendar y anunció que las 11:00
    «se acababan de ocupar». Era **su propia cita**, de un minuto antes. La
    respuesta no solo era falsa: empujaba al cliente a agendar dos veces.
    """

    def test_the_clients_own_appointment_is_not_reported_as_taken(self):
        self._make_appt(hhmm="10:00")           # cita de Luna, 10:00
        out = self._run("create_appointment", {
            "pet_handle": self._pet_handle(), "date": self.day.isoformat(),
            "time": "10:00", "reason": "otra vez"})
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, "already_scheduled")
        self.assertIn("cuando", out.data)

    def test_someone_elses_appointment_is_still_slot_taken(self):
        """La verdad en el otro sentido: si el hueco es ajeno, se dice."""
        otro_owner = Owner.objects.create(
            organization=self.org, name="Otro", phone="5599990000")
        otro_pet = Pet.objects.create(
            organization=self.org, owner=otro_owner, name="Rex",
            species="perro", birth_date="2020-01-01")
        start = datetime.strptime("10:00", "%H:%M").time()
        end = datetime.strptime("10:30", "%H:%M").time()
        Appointment.objects.create(
            organization=self.org, pet=otro_pet, veterinarian=self.vet,
            date=self.day, start_time=start, end_time=end, reason="x",
            status="scheduled",
            start_datetime=datetime.combine(self.day, start, tzinfo=dt_tz.utc),
            end_datetime=datetime.combine(self.day, end, tzinfo=dt_tz.utc))

        out = self._run("create_appointment", {
            "pet_handle": self._pet_handle(), "date": self.day.isoformat(),
            "time": "10:00", "reason": "baño"})
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, "slot_taken")


class CommitSuccessTextIsSpecificTests(TestCase):
    """Toda herramienta que compromete dice QUÉ hizo.

    El genérico «¡Listo! ✅» es una red, no un destino: el modelo lee el hilo
    para saber en qué estado está la conversación, y un acuse mudo lo dejó
    reintentando una cita ya creada (conv 18). Una herramienta nueva sin frase
    propia reproduce el fallo, así que el gate la caza al añadirla.
    """

    def test_every_commit_handler_has_its_own_success_text(self):
        from apps.agent import planner
        from apps.agent.tools import COMMIT_HANDLERS, ToolOutcome

        outcome = ToolOutcome(ok=True, data={"cuando": "sábado 15, 11:00"})
        generic = planner._commit_success_text("__inexistente__", outcome)
        for tool in sorted(COMMIT_HANDLERS):
            with self.subTest(tool=tool):
                self.assertNotEqual(
                    planner._commit_success_text(tool, outcome), generic,
                    f"`{tool}` confirma con el acuse genérico: el cliente no "
                    f"sabe qué quedó hecho y el modelo tampoco.")
