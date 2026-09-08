"""
test_hybrid_permission_nested.py — ADR-09 / Día 6 audit F16

Verifica que List/Create views anidadas bajo URL con <str:pk> UUID parent
declaran `required_permission` por método HTTP en `initial()`.

Sin esta declaración, `_method_to_action` infiere 'retrieve' por presencia
de `pk` en kwargs y rompe RBAC silenciosamente (list/create deniega o
sobreautoriza por mapping equivocado).

Test estrategia: rol custom con SOLO un permiso específico, verifica que:
  - GET respeta el permiso de list (no de retrieve)
  - POST respeta el permiso de create/update (no de retrieve)
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import Permission, Role, UserRole
from apps.medical_records.models import MedicalRecord
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet

User = get_user_model()


def _make_user_with_perms(username, org, codes):
    """Crea user + role con SOLO los permission codes especificados.

    Nota: Organization.post_save signal (organizations/signals.py) auto-seedea
    los system roles VET/ADMIN/ASSISTANT con sus PERMISSIONS completas. Luego
    users/signals.py::assign_rbac_role_on_create asigna ese system role al
    user. Para aislar SOLO los `codes` de este test, eliminamos las UserRoles
    auto-asignadas antes de crear la custom.
    """
    u = User.objects.create_user(
        username=username, password="pass", organization=org, role="VET"
    )
    # Limpiar role auto-asignado por signal (VET system role con perms completas)
    UserRole.objects.filter(user=u).delete()
    role, _ = Role.objects.get_or_create(
        name=f"role-{username}", organization=org, defaults={"is_system_role": False}
    )
    perms = [Permission.objects.get_or_create(code=c)[0] for c in codes]
    role.permissions.set(perms)
    UserRole.objects.get_or_create(user=u, role=role)
    return u


class VitalsListPermissionTests(APITestCase):
    """ADR-09: GET /medical-records/<uuid>/vitals/ debe requerir
    'medicalrecord.vitals.list', NO 'medicalrecord.retrieve'."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Nested Org", timezone="UTC")
        cls.owner = Owner.objects.create(
            organization=cls.org, name="Dueño", phone="5511112222"
        )
        cls.pet = Pet.objects.create(
            organization=cls.org, owner=cls.owner, name="Pet",
            species="perro", birth_date="2020-01-01",
        )
        # Veterinarian autor de la consulta (necesario para vet field)
        cls.vet = User.objects.create_user(
            username="vet_author", password="pass",
            organization=cls.org, role="VET",
        )
        cls.mr = MedicalRecord.objects.create(
            organization=cls.org, pet=cls.pet, veterinarian=cls.vet,
            consultation_type="general", diagnosis="dx", treatment="tx",
        )

    def test_get_vitals_requires_list_not_retrieve(self):
        """User con SOLO 'medicalrecord.vitals.list' puede GET (no retrieve)."""
        u = _make_user_with_perms(
            "list_only", self.org, ["medicalrecord.vitals.list"]
        )
        self.client.force_authenticate(u)
        r = self.client.get(f"/api/medical-records/{self.mr.public_id}/vitals/")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)

    def test_get_vitals_denied_without_list_permission(self):
        """User con SOLO 'medicalrecord.retrieve' (sin vitals.list) recibe 403.
        Esto verifica que _method_to_action NO está inferiendo 'retrieve'
        silenciosamente (sino este test pasaría con 200)."""
        u = _make_user_with_perms(
            "retrieve_only", self.org, ["medicalrecord.retrieve"]
        )
        self.client.force_authenticate(u)
        r = self.client.get(f"/api/medical-records/{self.mr.public_id}/vitals/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN, r.content)

    def test_post_vitals_requires_create_not_list(self):
        """User con SOLO 'medicalrecord.vitals.list' NO puede POST."""
        u = _make_user_with_perms(
            "list_only_post", self.org, ["medicalrecord.vitals.list"]
        )
        self.client.force_authenticate(u)
        r = self.client.post(
            f"/api/medical-records/{self.mr.public_id}/vitals/",
            {"weight": "12.5"}, format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN, r.content)

    def test_post_vitals_allowed_with_create_permission(self):
        """User con vitals.create + vitals.list (necesario para que
        DRF pueda renderizar la response del POST) puede crear."""
        u = _make_user_with_perms(
            "create_user", self.org,
            ["medicalrecord.vitals.create", "medicalrecord.vitals.list"],
        )
        self.client.force_authenticate(u)
        r = self.client.post(
            f"/api/medical-records/{self.mr.public_id}/vitals/",
            {"weight": "12.5"}, format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)


class MedicalRecordServiceListPermissionTests(APITestCase):
    """ADR-09: GET /medical-records/<uuid>/services/ debe usar
    'medicalrecord.retrieve' (declarado), NO inferir mal por kwargs."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="MRService Org", timezone="UTC")
        cls.owner = Owner.objects.create(
            organization=cls.org, name="Dueño", phone="5500001111"
        )
        cls.pet = Pet.objects.create(
            organization=cls.org, owner=cls.owner, name="Pet2",
            species="gato", birth_date="2021-01-01",
        )
        cls.vet = User.objects.create_user(
            username="vet_srv", password="pass",
            organization=cls.org, role="VET",
        )
        cls.mr = MedicalRecord.objects.create(
            organization=cls.org, pet=cls.pet, veterinarian=cls.vet,
            consultation_type="general", diagnosis="dx", treatment="tx",
        )

    def test_get_services_requires_retrieve(self):
        u = _make_user_with_perms(
            "srv_retrieve", self.org, ["medicalrecord.retrieve"]
        )
        self.client.force_authenticate(u)
        r = self.client.get(
            f"/api/medical-records/{self.mr.public_id}/services/"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)

    def test_get_services_denied_without_retrieve(self):
        u = _make_user_with_perms(
            "srv_other", self.org, ["medicalrecord.list"]
        )
        self.client.force_authenticate(u)
        r = self.client.get(
            f"/api/medical-records/{self.mr.public_id}/services/"
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN, r.content)


class CheckoutItemDetailPermissionTests(APITestCase):
    """Los cambios del carrito financiero exigen invoice.create."""

    @classmethod
    def setUpTestData(cls):
        from apps.billing.checkout_services import add_checkout_item, create_direct_sale_checkout
        from apps.billing.models import Service
        cls.org = Organization.objects.create(name="II Org", timezone="UTC")
        cls.owner = Owner.objects.create(
            organization=cls.org, name="Dueño", phone="5500002222"
        )
        cls.pet = Pet.objects.create(
            organization=cls.org, owner=cls.owner, name="PetII",
            species="perro", birth_date="2020-01-01",
        )
        cls.service = Service.objects.create(
            organization=cls.org, name="Consulta", base_price=Decimal("100.00"),
        )
        cls.checkout = create_direct_sale_checkout(
            organization=cls.org, customer=cls.owner, pet=cls.pet,
            user=None,
        )
        cls.item = add_checkout_item(
            cls.checkout, None, service=cls.service, quantity=Decimal('1'),
        )

    def test_patch_item_with_invoice_create_permission(self):
        u = _make_user_with_perms(
            "item_patch", self.org, ["invoice.create", "invoice.retrieve"]
        )
        self.client.force_authenticate(u)
        self.checkout.refresh_from_db()
        r = self.client.patch(
            f"/api/billing/checkouts/{self.checkout.public_id}/items/{self.item.id}/",
            {"quantity": "2", "expected_version": self.checkout.version}, format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)

    def test_patch_item_denied_without_invoice_create(self):
        u = _make_user_with_perms(
            "item_no_create", self.org, ["invoice.retrieve"]
        )
        self.client.force_authenticate(u)
        r = self.client.patch(
            f"/api/billing/checkouts/{self.checkout.public_id}/items/{self.item.id}/",
            {"quantity": "2"}, format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN, r.content)

    def test_delete_item_with_invoice_create_permission(self):
        u = _make_user_with_perms(
            "item_destroy", self.org, ["invoice.create", "invoice.retrieve"]
        )
        self.client.force_authenticate(u)
        self.checkout.refresh_from_db()
        r = self.client.delete(
            f"/api/billing/checkouts/{self.checkout.public_id}/items/{self.item.id}/",
            {"expected_version": self.checkout.version}, format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT, r.content)
