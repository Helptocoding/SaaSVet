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

from .harness import legacy_write_component
from apps.agent import confirmations
from apps.agent import executor as executor_module
from apps.agent import tools
from apps.agent.executor import ToolExecutor
from apps.agent.tests.harness import set_schedule_day
from apps.agent.llm import LLMResult
from apps.agent.models import (
    AgentSettings, ContactIdentity, Conversation, HumanHandoff,
)
from apps.agent.tests.harness import (
    RealApiTransport,
    identity_commitment,
    run_turn,
)
from apps.appointments.models import Appointment
from apps.channels.models import ChannelAccount
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSIONS
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User
from apps.users.services import ensure_agent_user
from apps.agent.tests.agent_settings_fixtures import create_enabled_agent_settings


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
        self.settings = create_enabled_agent_settings(self.org, agent_user=self.agent_user,
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
            contact=self.contact,
            # La persona que escribe intenta identificarse contra un expediente
            # ya existente; no es una primera visita. La selección tipada es
            # precondición del contrato de `identify_client`.
            intake_path=Conversation.INTAKE_EXISTING_CLIENT)

    def _turn(self, text, scripted):
        return run_turn(self, self.conv, self.agent_user, text,
                        scripted_llm=scripted)

    def _executor(self):
        return ToolExecutor(self.conv, self.agent_user,
                            transport=RealApiTransport())


class FamilyChallengeFlowTests(FamilyLinkBase):
    """El reto triple, ahora conducido por el modelo (É-F5 Fase 2).

    La FSM que lo llevaba etapa por etapa se retiró junto con
    `link_family_member`. Lo que NO cambia es la garantía de seguridad: hacen
    falta los tres factores contra un mismo titular, y cualquier factor
    equivocado deja el contacto sin vincular.

    El caso feliz vive en `test_f5_fase1.IdentifyClientTests`; aquí se
    conservan los caminos de FALLO, que son los que protegen el expediente de
    un tercero.
    """

    def _identify(self, **args):
        return tools.run_tool('identify_client', args, conversation=self.conv,
                              executor=self._executor())

    def test_wrong_digits_no_link(self):
        """Un conocido casual sabe «Juan y Max»; los 4 dígitos no."""
        out = self._identify(owner_name="Juan Perez",
                             pet_name="Max", phone_digits="0000")
        self.assertFalse(out.data['verificado'])
        self.contact.refresh_from_db()
        self.assertIsNone(self.contact.owner_id)

    def test_wrong_pet_no_link(self):
        out = self._identify(owner_name="Juan Perez", pet_name="Firulais",
                             phone_digits="2244")
        self.assertFalse(out.data['verificado'])
        self.contact.refresh_from_db()
        self.assertIsNone(self.contact.owner_id)

    def test_e05_un_numero_que_ya_es_de_un_cliente_no_se_revincula(self):
        """E-05 · el número de un cliente no puede pasar a otro titular.

        Antes lo rechazaba `link_family_member` con `already_a_client`. Ahora
        es estructural: con `contact.owner_id` puesto, `identify_client` toma
        la rama de verificación del titular y **nunca** llega a vincular a un
        tercero — no hay error que devolver porque no hay camino.
        """
        otro = Owner.objects.create(organization=self.org, name="Otra Persona",
                                    phone="5599990000")
        Pet.objects.create(organization=self.org, owner=otro, name="Rex",
                           species="perro", birth_date="2020-01-01")
        self.contact.owner = self.titular
        self.contact.verification_level = "confirmed_in_chat"
        self.contact.save()

        self._identify(owner_name="Otra Persona", pet_name="Rex",
                       phone_digits="0000")

        self.contact.refresh_from_db()
        self.assertEqual(self.contact.owner_id, self.titular.id,
                         "el contacto se revinculó a otro titular")


@legacy_write_component
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
        # Agendar sí está permitido: la tool PROPUSO (dejó el pending staged).
        self.assertIsNotNone(confirmations.get_pending(self.conv))


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
