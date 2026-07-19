"""
test_agent_identity.py — É0-PR2: identidad del agente virtual (ADR p51).

Cubre las dos mitades de la decisión:
  - `is_service_account` (eje "clase de principal"): superficies humanas lo
    excluyen por FLAG; gates de sesión no lo bloquean.
  - `role='AGENT'` (eje "conjunto de permisos"): en F2 gana un WHITELIST
    acotado de escritura de agenda (create/update de cita, alta de
    cliente/mascota); sigue SIN destroy, billing, clínico, staff → 403. Los
    roles se siembran DESDE el catálogo real (PERMISSIONS) para que el test
    falle si el catálogo cambia.

Plan aprobado: docs/whatsapp-agent-epics.md (É0 v2).
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.legal.models import LegalDocument
from apps.medical_records.models import VaccineRecord
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.services import ensure_agent_user

User = get_user_model()


def _seed_role_from_catalog(org, role_name):
    """Rol en DB con EXACTAMENTE los códigos del catálogo (como seed_permissions)."""
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


def _make_user(username, org, role_name):
    u = User.objects.create_user(
        username=username, password="pass", organization=org, role=role_name
    )
    UserRole.objects.get_or_create(user=u, role=_seed_role_from_catalog(org, role_name))
    return u


# ---------------------------------------------------------------------------
# Service ensure_agent_user
# ---------------------------------------------------------------------------

class EnsureAgentUserTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Agent Org", timezone="UTC")
        _seed_role_from_catalog(self.org, "AGENT")

    def test_creates_agent_with_correct_shape(self):
        user, status_ = ensure_agent_user(self.org)
        self.assertEqual(status_, "created")
        self.assertEqual(user.role, "AGENT")
        self.assertTrue(user.is_service_account)
        self.assertEqual(user.email, "")
        self.assertEqual(user.organization, self.org)
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.password_must_change)
        self.assertTrue(user.username.startswith("agent.whatsapp."))
        self.assertTrue(
            UserRole.objects.filter(user=user, role__name="AGENT").exists()
        )

    def test_is_idempotent(self):
        first, _ = ensure_agent_user(self.org)
        second, status_ = ensure_agent_user(self.org)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(status_, "ok")
        self.assertEqual(
            User.objects.filter(organization=self.org, role="AGENT").count(), 1
        )

    def test_repairs_deactivated_agent(self):
        user, _ = ensure_agent_user(self.org)
        user.is_active = False
        user.save(update_fields=["is_active"])

        repaired, status_ = ensure_agent_user(self.org)
        self.assertEqual(status_, "repaired")
        self.assertEqual(repaired.pk, user.pk)
        self.assertTrue(repaired.is_active)

    def test_repairs_usable_password_and_must_change(self):
        user, _ = ensure_agent_user(self.org)
        user.set_password("hacked-by-shell")
        user.password_must_change = True
        user.save()

        repaired, status_ = ensure_agent_user(self.org)
        self.assertEqual(status_, "repaired")
        self.assertFalse(repaired.has_usable_password())
        self.assertFalse(repaired.password_must_change)

    def test_management_command_runs_for_all_orgs(self):
        org_b = Organization.objects.create(name="Agent Org B", timezone="UTC")
        _seed_role_from_catalog(org_b, "AGENT")
        call_command("ensure_agent_users", verbosity=0)
        for org in (self.org, org_b):
            self.assertTrue(
                User.objects.filter(
                    organization=org, role="AGENT", is_service_account=True
                ).exists()
            )


# ---------------------------------------------------------------------------
# Catálogo del rol AGENT (unit, sin DB)
# ---------------------------------------------------------------------------

class AgentCatalogTests(SimpleTestCase):
    FORBIDDEN_PREFIXES = {
        "invoice", "billing", "cashsession", "cashmovement",
        "medicalrecord", "prescription", "staff", "import",
        "organization", "dashboard",
    }

    def test_agent_has_no_forbidden_resources(self):
        prefixes = {c.split(".")[0] for c in PERMISSIONS["AGENT"]}
        overlap = prefixes & self.FORBIDDEN_PREFIXES
        self.assertFalse(overlap, f"AGENT tiene recursos prohibidos: {overlap}")

    # F2: el read-only de F1 se relaja a un WHITELIST cerrado. Cualquier
    # permiso que no sea .list/.retrieve DEBE estar aquí — ni uno más
    # (defensa contra scope creep silencioso; ampliar exige tocar este set).
    F2_WRITE_WHITELIST = {
        "appointment.create", "appointment.update",
        "patient.create", "owner.create",
    }

    def test_agent_writes_are_whitelisted_in_f2(self):
        non_read = {
            c for c in PERMISSIONS["AGENT"]
            if not c.endswith(".list") and not c.endswith(".retrieve")
        }
        extra = non_read - self.F2_WRITE_WHITELIST
        self.assertFalse(extra, f"AGENT con escrituras fuera del whitelist F2: {extra}")
        # y NO gana destroy de cita (cancela vía /status/, no DELETE).
        self.assertNotIn("appointment.destroy", PERMISSIONS["AGENT"])

    def test_agent_codes_exist_in_catalog(self):
        catalog = set(PERMISSION_CODES)
        unknown = [c for c in PERMISSIONS["AGENT"] if c not in catalog]
        self.assertFalse(unknown)


# ---------------------------------------------------------------------------
# Permisos efectivos vía API (integración)
# ---------------------------------------------------------------------------

class AgentApiPermissionsTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Agent API Org", timezone="UTC")
        _seed_role_from_catalog(cls.org, "AGENT")
        cls.agent, _ = ensure_agent_user(cls.org)
        owner = Owner.objects.create(
            organization=cls.org, name="Cliente Uno", phone="5510203040"
        )
        cls.pet = Pet.objects.create(
            organization=cls.org, owner=owner, name="Luna",
            species="perro", birth_date="2021-05-01",
        )
        cls.vac = VaccineRecord.objects.create(
            organization=cls.org, pet=cls.pet,
            vaccine_name="Antirrábica", application_date="2026-06-01",
        )

    def setUp(self):
        self.client.force_authenticate(self.agent)

    def test_agent_can_read_f1_surfaces(self):
        for url in ("/api/appointments/", "/api/pets/", "/api/owners/",
                    "/api/vaccines/", "/api/billing/services/",
                    "/api/inventory/products/"):
            r = self.client.get(url)
            self.assertEqual(
                r.status_code, status.HTTP_200_OK, f"{url}: {r.status_code}"
            )

    def test_agent_can_reach_appointment_create_in_f2(self):
        """F2: ya NO es 403 (tiene appointment.create). Body vacío → cae en la
        validación del serializer (400), prueba de que el permiso pasó."""
        r = self.client.post("/api/appointments/", {})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)

    def test_agent_cannot_destroy_appointments_in_f2(self):
        """El agente cancela vía PATCH /status/ (deja lineage de auditoría);
        el DELETE (destroy) es de staff → 403 antes de tocar el objeto."""
        import uuid
        r = self.client.delete(f"/api/appointments/{uuid.uuid4()}/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN, r.content)

    def test_agent_cannot_create_vaccines(self):
        r = self.client.post("/api/vaccines/", {
            "pet": self.pet.pk, "vaccine_name": "X",
            "application_date": "2026-07-01",
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_agent_cannot_touch_billing_or_clinic(self):
        self.assertEqual(
            self.client.get("/api/billing/invoices/").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.get("/api/medical-records/").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.get("/api/staff/").status_code,
            status.HTTP_403_FORBIDDEN,
        )


# ---------------------------------------------------------------------------
# Gates de sesión (ADR p46/p21) — el agente NO se bloquea; humanos SÍ
# ---------------------------------------------------------------------------

class AgentGatesTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Agent Gate Org", timezone="UTC")
        _seed_role_from_catalog(cls.org, "AGENT")
        cls.agent, _ = ensure_agent_user(cls.org)
        cls.assistant = _make_user("gate_asst", cls.org, "ASSISTANT")
        LegalDocument.objects.create(
            doc_type=LegalDocument.DOC_PRIVACY, version="1.0",
            effective_date="2026-01-01", landing_url="https://example.com/priv",
            is_current=True,
        )

    def test_legal_gate_does_not_block_agent(self):
        """AGENT no está en REQUIRED_DOC_TYPES_BY_ROLE → exento por diseño
        del mapping (cero cambios en core/permissions.py — hallazgo É0)."""
        self.client.force_authenticate(self.agent)
        r = self.client.get("/api/pets/")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)

    def test_legal_gate_still_blocks_pending_human(self):
        """No-regresión: el gate p46 sigue bloqueando a un humano sin aceptar."""
        self.client.force_authenticate(self.assistant)
        r = self.client.get("/api/pets/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN, r.content)


# ---------------------------------------------------------------------------
# Superficies de staff — el agente es invisible e intocable
# ---------------------------------------------------------------------------

class AgentStaffSurfacesTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Agent Staff Org", timezone="UTC")
        _seed_role_from_catalog(cls.org, "AGENT")
        cls.agent, _ = ensure_agent_user(cls.org)
        cls.admin = _make_user("staff_admin", cls.org, "ADMIN")

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_staff_list_excludes_service_accounts(self):
        r = self.client.get("/api/staff/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        usernames = {u["username"] for u in r.json()}
        self.assertNotIn(self.agent.username, usernames)

    def test_staff_create_rejects_agent_role(self):
        r = self.client.post("/api/staff/create/", {
            "username": "sneaky_agent", "email": "sneaky@example.com",
            "password": "Password123", "role": "AGENT",
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)

    def test_deactivate_agent_returns_404(self):
        r = self.client.delete(f"/api/staff/{self.agent.public_id}/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND, r.content)
        self.agent.refresh_from_db()
        self.assertTrue(self.agent.is_active)

    def test_reset_password_agent_returns_404(self):
        r = self.client.post(f"/api/staff/{self.agent.public_id}/reset-password/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND, r.content)
        self.agent.refresh_from_db()
        self.assertFalse(self.agent.password_must_change)


# ---------------------------------------------------------------------------
# Evolución de permisos (punto 4 de la revisión del PO) + seed de org nueva
# ---------------------------------------------------------------------------

class AgentEvolutionTests(TestCase):
    def test_seed_propagates_new_agent_permission(self):
        """F2 añadirá appointment.create editando PERMISSIONS — este test
        ancla que el mecanismo (re-seed sobreescribe el Role) funciona."""
        org = Organization.objects.create(name="Agent Evo Org", timezone="UTC")
        evolved = dict(PERMISSIONS)
        evolved["AGENT"] = PERMISSIONS["AGENT"] + ["appointment.create"]
        with mock.patch(
            "apps.core.management.commands.seed_permissions.PERMISSIONS", evolved
        ):
            call_command("seed_permissions", verbosity=0)
        role = Role.objects.get(name="AGENT", organization=org, is_system_role=True)
        codes = set(role.permissions.values_list("code", flat=True))
        self.assertIn("appointment.create", codes)
        self.assertIn("vaccinerecord.list", codes)

    def test_new_org_signal_seeds_agent_role(self):
        org = Organization.objects.create(name="Agent Signal Org", timezone="UTC")
        self.assertTrue(
            Role.objects.filter(
                name="AGENT", organization=org, is_system_role=True
            ).exists()
        )
