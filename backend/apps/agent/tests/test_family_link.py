"""
test_family_link.py — É-F2 PR-17b: vinculación familiar (reto triple, UX-04).

Seguridad: 3 factores (titular + mascota + últimos 4 dígitos) contra un mismo
owner; jamás vínculo parcial; 2 fallos → handoff instrumentado; acceso
RESTRINGIDO (consulta/agenda sí, cancelar/mover no); revocable en bandeja.
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.agent import executor as executor_module
from apps.agent import tools
from apps.agent.executor import ToolExecutor
from apps.agent.tests.harness import set_schedule_day
from apps.agent.llm import LLMResult
from apps.agent.models import (
    AgentSettings, ContactIdentity, Conversation, HumanHandoff,
)
from apps.agent.tests.harness import RealApiTransport, run_turn
from apps.appointments.models import Appointment
from apps.channels.models import ChannelAccount
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


class FamilyLinkBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Fam Org", timezone="UTC")
        _seed_role(cls.org, "AGENT")
        vet_role = _seed_role(cls.org, "VET")
        cls.vet = User.objects.create_user(
            username="fam_vet", password="p", organization=cls.org, role="VET")
        UserRole.objects.get_or_create(user=cls.vet, role=vet_role)
        # Titular con teléfono conocido (últimos 4 = 2244) y una mascota "Max".
        cls.titular = Owner.objects.create(
            organization=cls.org, name="Juan Perez", phone="5511992244")
        cls.pet = Pet.objects.create(
            organization=cls.org, owner=cls.titular, name="Max",
            species="canino", birth_date="2021-01-01")

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
            organization=self.org, external_account_id="944944944")
        # El número de quien escribe (la esposa) — sin owner, sin verificar.
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215513330000",
            verification_level="unknown")
        self.conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact)

    def _turn(self, text, scripted):
        return run_turn(self, self.conv, self.agent_user, text,
                        scripted_llm=scripted)

    def _executor(self):
        return ToolExecutor(self.conv, self.agent_user,
                            transport=RealApiTransport())


class FamilyChallengeFlowTests(FamilyLinkBase):
    def test_full_triple_challenge_links(self):
        _, r1, _ = self._turn("soy la esposa de Juan Perez", [LLMResult(
            kind="tool_call", tool_name="link_family_member",
            tool_args={"titular_name": "Juan Perez"})])
        self.assertEqual(r1["decision"], "awaiting_reply")
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.flow["family_challenge"]["stage"], "pet")

        _, r2, _ = self._turn("Max", [])          # factor 2 (mascota) → dígitos
        self.assertEqual(r2["decision"], "reply")
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.flow["family_challenge"]["stage"], "digits")

        _, r3, _ = self._turn("2244", [LLMResult(   # factor 3 (4 dígitos) → link
            kind="text", text="¡Listo, validado! ¿En qué te ayudo? 🐾")])
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.owner_id, self.titular.id)
        self.assertEqual(self.contact.linked_via, "family_challenge")
        self.assertEqual(self.contact.verification_level, "confirmed_in_chat")

    def test_wrong_digits_twice_handoff_no_link(self):
        self._turn("familiar de Juan Perez", [LLMResult(
            kind="tool_call", tool_name="link_family_member",
            tool_args={"titular_name": "Juan Perez"})])
        self._turn("Max", [])
        self._turn("0000", [])                       # fallo 1 → reintento
        _, r, _ = self._turn("1111", [])             # fallo 2 → handoff
        self.assertEqual(r["decision"], "escalate")
        hh = HumanHandoff.objects.filter(conversation=self.conv).first()
        self.assertIsNotNone(hh)
        self.assertIn("failed_digits", hh.reason_detail)   # instrumentación P3
        self.contact.refresh_from_db()
        self.assertIsNone(self.contact.owner_id)           # cero vínculo

    def test_wrong_pet_never_reaches_digits(self):
        self._turn("familiar de Juan Perez", [LLMResult(
            kind="tool_call", tool_name="link_family_member",
            tool_args={"titular_name": "Juan Perez"})])
        self._turn("Firulais", [])                   # mascota que no es del titular
        self.conv.refresh_from_db()
        fam = self.conv.flow.get("family_challenge")
        # sigue en 'pet' (no avanzó) o escaló; nunca vinculó
        self.contact.refresh_from_db()
        self.assertIsNone(self.contact.owner_id)

    def test_e05_already_client_refuses_challenge(self):
        self.contact.owner = self.titular
        self.contact.verification_level = "confirmed_in_chat"
        self.contact.save()
        out = tools.link_family_member(
            self.conv, self._executor(), {"titular_name": "Juan Perez"})
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, "already_a_client")


class FamilyRestrictedAccessTests(FamilyLinkBase):
    def setUp(self):
        super().setUp()
        # Contacto YA vinculado como familiar (acceso restringido).
        self.contact.owner = self.titular
        self.contact.linked_via = ContactIdentity.LINKED_FAMILY
        self.contact.verification_level = "confirmed_in_chat"
        self.contact.verified_at = timezone.now()
        self.contact.save()
        self.conv.flow["refs"] = {"mascota_1": str(self.pet.public_id)}
        self.conv.save(update_fields=["flow"])

    def _appt_handle(self):
        start = datetime.strptime("11:00", "%H:%M").time()
        end = datetime.strptime("11:30", "%H:%M").time()
        appt = Appointment.objects.create(
            organization=self.org, pet=self.pet, veterinarian=self.vet,
            date=self.day, start_time=start, end_time=end, reason="x",
            status="scheduled",
            start_datetime=datetime.combine(self.day, start, tzinfo=dt_tz.utc),
            end_datetime=datetime.combine(self.day, end, tzinfo=dt_tz.utc))
        tools._add_ref(self.conv, "cita", appt.public_id)
        tools._save_refs(self.conv)
        return appt

    def test_family_cannot_cancel(self):
        self._appt_handle()
        out = tools.run_tool("cancel_appointment",
                             {"appointment_handle": "cita_1"},
                             conversation=self.conv, executor=self._executor())
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, "family_restricted")

    def test_family_cannot_reschedule(self):
        self._appt_handle()
        out = tools.run_tool("reschedule_appointment",
                             {"appointment_handle": "cita_1",
                              "new_date": self.day.isoformat(),
                              "new_time": "12:00"},
                             conversation=self.conv, executor=self._executor())
        self.assertFalse(out.ok)
        self.assertEqual(out.client_error, "family_restricted")

    def test_family_can_still_schedule(self):
        out = tools.run_tool("create_appointment", {
            "pet_handle": "mascota_1", "date": self.day.isoformat(),
            "time": "10:00", "reason": "Consulta"},
            conversation=self.conv, executor=self._executor())
        self.assertTrue(out.ok, out.client_error)
        self.assertTrue(out.needs_confirmation)   # agendar sí está permitido


class FamilyRevokeTests(FamilyLinkBase):
    def test_revoke_unlinks_family_contact(self):
        self.contact.owner = self.titular
        self.contact.linked_via = ContactIdentity.LINKED_FAMILY
        self.contact.verification_level = "confirmed_in_chat"
        self.contact.save()

        assistant_role = _seed_role(self.org, "ASSISTANT")
        recep = User.objects.create_user(
            username="fam_recep", password="p", organization=self.org,
            role="ASSISTANT")
        UserRole.objects.get_or_create(user=recep, role=assistant_role)
        client = APIClient()
        client.force_authenticate(recep)

        r = client.post(
            f"/api/inbox/conversations/{self.conv.public_id}/unlink-family/")
        self.assertEqual(r.status_code, 200, r.content)
        self.contact.refresh_from_db()
        self.assertIsNone(self.contact.owner_id)
        self.assertEqual(self.contact.linked_via, "")
        self.assertEqual(self.contact.verification_level, "unknown")

    def test_revoke_rejects_non_family_link(self):
        self.contact.owner = self.titular
        self.contact.linked_via = ContactIdentity.LINKED_SELF_REGISTER
        self.contact.save()
        assistant_role = _seed_role(self.org, "ASSISTANT")
        recep = User.objects.create_user(
            username="fam_recep2", password="p", organization=self.org,
            role="ASSISTANT")
        UserRole.objects.get_or_create(user=recep, role=assistant_role)
        client = APIClient()
        client.force_authenticate(recep)
        r = client.post(
            f"/api/inbox/conversations/{self.conv.public_id}/unlink-family/")
        self.assertEqual(r.status_code, 400, r.content)
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.owner_id, self.titular.id)  # intacto
