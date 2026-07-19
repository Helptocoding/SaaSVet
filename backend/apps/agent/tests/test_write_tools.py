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
            default_veterinarian=self.vet,
            business_hours={wd: [["09:00", "13:00"]]})
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

    def _affirm(self, text="sí"):
        decision = policy.evaluate(self.conv, text, agent_settings=self.settings)
        return decision

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
        self.assertTrue(out.needs_confirmation)
        self.assertIn("Luna", out.confirmation_text)
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
        self.assertFalse(out.needs_confirmation)   # sin parafraseo
        appt.refresh_from_db()
        self.assertEqual(appt.status, "confirmed")

    # -- cancelar -----------------------------------------------------------
    def test_cancel_proposes_and_commits(self):
        appt, handle = self._make_appt(status="confirmed")
        out = self._run("cancel_appointment", {
            "appointment_handle": handle, "reason": "se enfermó"})
        self.assertTrue(out.needs_confirmation)
        self.assertIn("Luna", out.confirmation_text)

        self._affirm("sí")
        res = planner._commit_pending(self.conv, self.executor)
        self.assertEqual(res["decision"], "committed")
        appt.refresh_from_db()
        self.assertEqual(appt.status, "canceled")
        self.assertIn("asistente virtual", appt.cancellation_reason)

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
        self.assertTrue(out.needs_confirmation)

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
        self.assertTrue(out.needs_confirmation)
        self.assertIn("Carlos", out.confirmation_text)
        self.assertIn("Rocky", out.confirmation_text)
        pending = confirmations.get_pending(conv)
        self.assertEqual(pending["args"]["owner_phone"], "5512345678")  # 10 díg
        self.assertEqual(Owner.objects.filter(phone="5512345678").count(), 0)

    def test_register_commits_and_autolinks(self):
        conv, ex = self._unknown_conv()
        tools.run_tool("register_new_client_and_pet", {
            "owner_name": "Carlos", "pet_name": "Rocky",
            "date": self.day.isoformat(), "time": "10:00", "reason": "Consulta"},
            conversation=conv, executor=ex)
        policy.evaluate(conv, "sí", agent_settings=self.settings)
        res = planner._commit_pending(conv, ex)
        self.assertEqual(res["decision"], "committed")
        owner = Owner.objects.get(phone="5512345678")
        self.assertEqual(owner.name, "Carlos")
        self.assertEqual(Appointment.objects.filter(pet__owner=owner).count(), 1)
        conv.contact.refresh_from_db()
        self.assertEqual(conv.contact.owner_id, owner.id)           # auto-vínculo
        self.assertEqual(conv.contact.verification_level, "confirmed_in_chat")
        self.assertEqual(conv.contact.linked_via, "self_register")

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
        self.settings.business_hours = {
            d: [["09:00", "13:00"]] for d in
            ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
        self.settings.save(update_fields=["business_hours"])
        appt, handle = self._make_appt(status="confirmed")
        self._run("cancel_appointment", {"appointment_handle": handle})
        self._affirm("sí")
        planner._commit_pending(self.conv, self.executor)
        out = self._last_out()
        self.assertIn("cancelé tu cita", out)
        self.assertIn("te reagendo", out)            # UX-11 retención con horario

    # -- expiración del pending --------------------------------------------
    def test_expired_pending_reparaphrases_not_executes(self):
        self.conv.flow["pending_action"] = {
            "tool": "create_appointment",
            "args": {"pet": self.pet.pk, "veterinarian": self.vet.pk,
                     "date": self.day.isoformat(), "start_time": "10:00",
                     "end_time": "10:30", "reason": "x", "notes": "",
                     "idempotency_key": "k"},
            "paraphrase": "¿Es correcto?",
            "idempotency_key": "k",
            "expires_at": (timezone.now() - timedelta(minutes=1)).isoformat(),
        }
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
