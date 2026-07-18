"""
test_tools.py — É-F1 PR-10: tools de lectura contra la API REAL.

El transporte de test enruta por el Django test client con el JWT REAL del
user AGENT: cada tool atraviesa TenantJWTAuthentication + HybridPermission
+ serializers de verdad — el RBAC del rol AGENT se prueba de punta a punta
(incluida la lista negativa: medical-records → 403).
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.agent import executor as executor_module
from apps.agent.executor import ToolExecutor
from apps.agent.models import (
    AgentSettings,
    ContactIdentity,
    Conversation,
    HumanHandoff,
)
from apps.agent.tools import resolve_handle, run_tool
from apps.appointments.models import Appointment
from apps.billing.models import Service
from apps.channels.models import ChannelAccount
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSIONS
from apps.inventory.models import Product
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
        perms = [Permission.objects.get_or_create(code=c)[0] for c in codes]
        role.permissions.set(perms)
    return role


class TestClientTransport:
    """Enruta el loopback por el Django test client (API real, sin red)."""

    def __call__(self, method, path, *, headers, params=None, json=None):
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=headers.get("Authorization", ""),
            HTTP_X_REQUEST_ID=headers.get("X-Request-ID", ""),
        )
        handler = getattr(client, method.lower())
        if method.upper() == "GET":
            response = handler(path, data=params or {})
        else:
            response = handler(path, data=json or {}, format="json")
        try:
            payload = response.json() if response.content else {}
        except ValueError:
            payload = {}
        return response.status_code, payload


class ToolsThroughRealApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(
            name="Tools Org", timezone="UTC",
        )
        _seed_role(cls.org, "AGENT")
        vet_role = _seed_role(cls.org, "VET")
        cls.vet = User.objects.create_user(
            username="tools_vet", password="pass",
            organization=cls.org, role="VET",
        )
        UserRole.objects.get_or_create(user=cls.vet, role=vet_role)

        cls.owner = Owner.objects.create(
            organization=cls.org, name="Ana Torres", phone="5511224488",
        )
        cls.pet_luna = Pet.objects.create(
            organization=cls.org, owner=cls.owner, name="Luna",
            species="perro", birth_date="2021-03-01",
        )
        cls.pet_michi = Pet.objects.create(
            organization=cls.org, owner=cls.owner, name="Michi",
            species="gato", birth_date="2022-06-01",
        )
        VaccineRecord.objects.create(
            organization=cls.org, pet=cls.pet_luna,
            vaccine_name="Antirrábica", application_date="2026-01-15",
            next_due_date="2027-01-15",
        )
        start = timezone.now() + timedelta(days=3)
        Appointment.objects.create(
            organization=cls.org, pet=cls.pet_luna, veterinarian=cls.vet,
            date=start.date(), start_time=start.time(),
            end_time=(start + timedelta(minutes=30)).time(),
            start_datetime=start, end_datetime=start + timedelta(minutes=30),
            reason="vacunación", status="scheduled",
        )
        Service.objects.create(
            organization=cls.org, name="Consulta general",
            base_price="350.00",
        )
        Product.objects.create(
            organization=cls.org, name="Alimento Premium Perro",
            internal_code="ALI-001", category="food", stock_quantity=5,
        )
        AgentSettings.objects.create(
            organization=cls.org,
            faq_facts={"dirección": "Av. Siempre Viva 123",
                       "estacionamiento": "Sí, gratuito"},
        )

    def setUp(self):
        executor_module._token_cache.clear()
        self.agent_user, _ = ensure_agent_user(self.org)
        channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="500200500",
        )
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215511224488",
            phone_normalized="5511224488", owner=self.owner,
            verification_level=ContactIdentity.VERIFICATION_CONFIRMED,
        )
        self.conversation = Conversation.objects.create(
            organization=self.org, channel_account=channel,
            contact=self.contact,
        )
        self.executor = ToolExecutor(
            self.conversation, self.agent_user,
            transport=TestClientTransport(),
        )

    def _run(self, name, args=None):
        return run_tool(name, args or {}, conversation=self.conversation,
                        executor=self.executor)

    def test_list_my_pets_projects_and_registers_handles(self):
        outcome = self._run("list_my_pets")
        self.assertTrue(outcome.ok, outcome.client_error)
        names = {p["nombre"] for p in outcome.data}
        self.assertEqual(names, {"Luna", "Michi"})
        for pet in outcome.data:
            self.assertIn("handle", pet)
            self.assertIsNotNone(
                resolve_handle(self.conversation, pet["handle"])
            )
            # Proyección mínima (R4): sin raza, sin fechas, sin owner.
            self.assertEqual(set(pet.keys()), {"handle", "nombre", "especie"})

    def test_get_vaccine_status_via_handle(self):
        pets = self._run("list_my_pets").data
        luna_handle = next(p["handle"] for p in pets if p["nombre"] == "Luna")
        outcome = self._run("get_vaccine_status", {"pet_handle": luna_handle})
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.data[0]["vacuna"], "Antirrábica")
        self.assertEqual(outcome.data[0]["estado"], "al día")
        self.assertIn("15 de enero de 2027", outcome.data[0]["proximo_refuerzo"])

    def test_unknown_handle_is_hard_denied(self):
        outcome = self._run(
            "get_vaccine_status",
            {"pet_handle": "3fa85f64-5717-4562-b3fc-2c963f66afa6"},
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.client_error, "unknown_handle")

    def test_list_upcoming_appointments(self):
        outcome = self._run("list_upcoming_appointments")
        self.assertTrue(outcome.ok, outcome.client_error)
        self.assertEqual(len(outcome.data), 1)
        appointment = outcome.data[0]
        self.assertEqual(appointment["mascota"], "Luna")
        self.assertEqual(appointment["estado"], "programada")
        self.assertTrue(appointment["handle"].startswith("cita_"))
        self.assertTrue(appointment["cuando"])  # fecha absoluta legible (G5)

    def test_get_service_catalog_exact_price(self):
        outcome = self._run("get_service_catalog", {"query": "consulta"})
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.data[0]["servicio"], "Consulta general")
        self.assertEqual(outcome.data[0]["precio"], "$350.00")

    def test_check_product_availability_yes_no_only(self):
        outcome = self._run("check_product_availability",
                            {"query": "alimento premium"})
        self.assertTrue(outcome.ok)
        product = outcome.data[0]
        self.assertTrue(product["disponible"])
        # G7: jamás cifras de stock en la proyección.
        self.assertNotIn("stock", str(outcome.data))
        self.assertNotIn("5", str(product.get("disponible")))

    def test_get_clinic_info_topic_and_honesty(self):
        outcome = self._run("get_clinic_info", {"topic": "dirección"})
        self.assertEqual(outcome.data, {"dirección": "Av. Siempre Viva 123"})
        missing = self._run("get_clinic_info", {"topic": "delivery"})
        self.assertEqual(missing.data, {"_sin_dato": True})  # G1: sin inventar

    def test_request_human_creates_handoff_and_silences(self):
        outcome = self._run("request_human", {"reason": "quiere factura"})
        self.assertTrue(outcome.ok)
        self.assertTrue(
            HumanHandoff.objects.filter(conversation=self.conversation).exists()
        )
        self.conversation.refresh_from_db()
        self.assertEqual(
            self.conversation.state, Conversation.STATE_HANDOFF_PENDING,
        )

    def test_verification_floor_blocks_personal_tools(self):
        self.contact.verification_level = ContactIdentity.VERIFICATION_PHONE_MATCH
        self.contact.save(update_fields=["verification_level"])
        outcome = self._run("list_my_pets")
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.client_error, "verification_required")

    def test_agent_rbac_denies_clinical_surface(self):
        """Lista negativa end-to-end: el rol AGENT contra medical-records
        recibe 403 REAL (RBAC de verdad, no mock) y queda auditado."""
        status, _ = self.executor.call(
            "GET", "/api/medical-records/", tool_name="negative_probe",
        )
        self.assertEqual(status, 403)
