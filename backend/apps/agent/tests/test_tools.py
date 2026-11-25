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
from apps.inventory.models import Presentation, Product
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
        from apps.agent.executor import TransportResponse
        return TransportResponse.from_http(response)


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
        # Hora FIJA del día: derivarla de `timezone.now()` hacía que la suite
        # fallara solo entre las 23:30 y las 00:00 UTC — la cita terminaba al
        # día siguiente y saltaba el CHECK `appointment_end_after_start`.
        start = (timezone.now() + timedelta(days=3)).replace(
            hour=10, minute=0, second=0, microsecond=0)
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
        cls.food_product = Product.objects.create(
            organization=cls.org, name="Alimento Premium Perro",
            internal_code="ALI-001", category="food", stock_quantity=5,
        )
        Presentation.objects.create(
            organization=cls.org, product=cls.food_product, name="Bolsa 1 kg",
            base_unit="kg", sale_price="250.00", stock=5,
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
            verified_at=timezone.now(),
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

    def test_get_appointments_lists_the_future_one(self):
        outcome = self._run("get_appointments")
        self.assertTrue(outcome.ok, outcome.client_error)
        appointment = next(a for a in outcome.data if a["mascota"] == "Luna")
        self.assertEqual(appointment["estado"], "programada")
        self.assertTrue(appointment["handle"].startswith("cita_"))
        self.assertTrue(appointment["cuando"])  # fecha absoluta legible (G5)
        self.assertFalse(appointment["ya_paso"])
        self.assertEqual(appointment["motivo"], "vacunación")

    def test_get_appointments_sees_the_one_the_client_missed(self):
        """Regresión de conv 21 (2026-08-17), el fallo más caro del piloto.

        El cliente abrió con «no pude acudir a mi cita». Su cita existía —ese
        mismo día, `scheduled`— y la API la devolvía en cada llamada. Pero
        `list_upcoming_appointments` hacía `if start_dt < now: continue` y
        `get_past_visits` hacía `if status != 'done': continue`, así que una cita
        perdida (pasada Y no atendida) no la veía NINGUNA de las 18 tools. El
        agente le dijo cuatro veces que no tenía citas mientras él respondía
        «estoy viendo el sistema y si hay».
        """
        missed = (timezone.now() - timedelta(hours=3)).replace(
            minute=0, second=0, microsecond=0)
        Appointment.objects.create(
            organization=self.org, pet=self.pet_luna, veterinarian=self.vet,
            date=missed.date(), start_time=missed.time(),
            end_time=(missed + timedelta(minutes=30)).time(),
            start_datetime=missed, end_datetime=missed + timedelta(minutes=30),
            reason="revisión", status="scheduled",
        )

        outcome = self._run("get_appointments")

        self.assertTrue(outcome.ok, outcome.client_error)
        perdida = [a for a in outcome.data if a["ya_paso"]]
        self.assertEqual(len(perdida), 1, outcome.data)
        self.assertEqual(perdida[0]["motivo"], "revisión")
        self.assertEqual(perdida[0]["estado"], "programada")
        # Y con handle: sin él, reagendarla o cancelarla es imposible por
        # construcción, que es la mitad del defecto que nadie vio.
        self.assertTrue(perdida[0]["handle"].startswith("cita_"))

    def test_get_appointments_labels_every_status(self):
        """El mapa de etiquetas solo cubría los 3 estados que el filtro dejaba
        pasar: una cita cancelada o no asistida ni tenía nombre que enseñar."""
        base = timezone.now() - timedelta(days=5)
        for offset, status in enumerate(("done", "canceled", "no_show")):
            start = (base + timedelta(hours=offset)).replace(
                minute=0, second=0, microsecond=0)
            Appointment.objects.create(
                organization=self.org, pet=self.pet_luna,
                veterinarian=self.vet, date=start.date(),
                start_time=start.time(),
                end_time=(start + timedelta(minutes=30)).time(),
                start_datetime=start,
                end_datetime=start + timedelta(minutes=30),
                reason="x", status=status,
            )

        outcome = self._run("get_appointments")

        etiquetas = {a["estado"] for a in outcome.data}
        self.assertTrue({"atendida", "cancelada", "no asistió"} <= etiquetas,
                        etiquetas)
        self.assertNotIn("done", etiquetas)  # nunca el enum crudo al modelo

    def test_get_service_catalog_exact_price(self):
        outcome = self._run("get_service_catalog", {"query": "consulta"})
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.data[0]["servicio"], "Consulta general")
        self.assertEqual(outcome.data[0]["precio"], "$350.00")

    def test_check_product_availability_category_query_includes_available_price_and_stock(self):
        outcome = self._run("check_product_availability",
                            {"query": "alimentos"})
        self.assertTrue(outcome.ok)
        product = outcome.data[0]
        self.assertTrue(product["disponible"])
        self.assertIn("stock", product)
        self.assertEqual(float(product["stock"]), 5.0)
        self.assertEqual(product["precio"], "250.00")

    def test_product_text_search_uses_description_and_excludes_inactive(self):
        Product.objects.create(
            organization=self.org, name="Nutrición canina",
            description="Croquetas para cachorro de raza mediana",
            internal_code="ALI-002", category="food", stock_quantity=2,
        )
        Product.objects.create(
            organization=self.org, name="Croquetas retiradas",
            description="Croquetas para cachorro",
            internal_code="ALI-003", category="food", stock_quantity=2,
            is_active=False,
        )

        outcome = self._run("check_product_availability",
                            {"query": "croquetas para cachorro"})

        self.assertTrue(outcome.ok)
        names = [item["producto"] for item in outcome.data]
        self.assertIn("Nutrición canina", names)
        self.assertNotIn("Croquetas retiradas", names)

    def test_out_of_stock_product_only_projects_its_exhausted_status(self):
        product = Product.objects.create(
            organization=self.org, name="Royal Canin Mini",
            internal_code="ALI-004", category="food", stock_quantity=0,
        )
        Presentation.objects.create(
            organization=self.org, product=product, name="Bolsa 2 kg",
            base_unit="kg", sale_price="620.00", stock=0,
        )

        outcome = self._run("check_product_availability",
                            {"query": "royal canin"})

        self.assertTrue(outcome.ok)
        product_data = next(item for item in outcome.data
                            if item["producto"] == "Royal Canin Mini")
        self.assertFalse(product_data["disponible"])
        self.assertTrue(product_data["agotado"])
        self.assertNotIn("precio", product_data)
        self.assertNotIn("stock", product_data)

    def test_specialty_is_offered_only_with_active_service_and_staff(self):
        self.vet.specialties = ["dermatology"]
        self.vet.save(update_fields=["specialties"])
        Service.objects.create(
            organization=self.org, name="Consulta de dermatología",
            base_price="500.00", specialty="dermatology",
        )

        outcome = self._run("get_offered_specialties", {"query": "dermatologia"})

        self.assertEqual(outcome.data, [{"especialidad": "Dermatología"}])
        Service.objects.filter(
            organization=self.org, name="Consulta de dermatología",
        ).update(is_active=False)
        self.assertEqual(
            self._run("get_offered_specialties", {"query": "dermatologia"}).data,
            [],
        )

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
