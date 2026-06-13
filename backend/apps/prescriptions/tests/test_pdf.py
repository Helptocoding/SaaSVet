"""
Tests del endpoint prescription_pdf (Fase 1 rediseño documentos).

Cubre el bug histórico del canvas crudo: una receta con muchos ítems dibujaba
fuera de página (contenido perdido). El rewrite a platypus debe paginar.
"""
from decimal import Decimal
from io import BytesIO

from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.inventory.models import Presentation, Product
from apps.medical_records.models import MedicalRecord
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.prescriptions.models import Prescription, PrescriptionItem
from apps.users.models import User


def _seed_roles(org):
    wildcard, _ = Permission.objects.get_or_create(code="*.*")
    perms_map = {c: Permission.objects.get_or_create(code=c)[0] for c in PERMISSION_CODES}
    roles = {}
    for name, codes in PERMISSIONS.items():
        if name == "ADMIN_SAAS":
            continue
        role, _ = Role.objects.get_or_create(name=name, organization=org, defaults={"is_system_role": True})
        role.permissions.set([wildcard] if "*.*" in codes else [perms_map[c] for c in codes if c in perms_map])
        roles[name] = role
    return roles


def _make_user(username, org, role_name):
    u = User.objects.create_user(username=username, password="pass", organization=org, role=role_name)
    roles = _seed_roles(org)
    UserRole.objects.get_or_create(user=u, role=roles[role_name])
    return u


def _extract_pdf_text(content):
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    reader = PdfReader(BytesIO(content))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _page_count(content):
    from pypdf import PdfReader
    return len(PdfReader(BytesIO(content)).pages)


class PrescriptionPdfTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Clinica RX PDF", timezone="UTC")
        cls.org_other = Organization.objects.create(name="Otra Clinica RX", timezone="UTC")

        cls.admin = _make_user("adm_rx_pdf", cls.org, "ADMIN")
        cls.vet = _make_user("vet_rx_pdf", cls.org, "VET")
        cls.vet.first_name = "Ana"
        cls.vet.last_name = "Galeno"
        cls.vet.specialty = "Dermatología"
        cls.vet.save(update_fields=["first_name", "last_name", "specialty"])

        cls.owner = Owner.objects.create(name="Pedro Ramirez", phone="5550001111",
                                         organization=cls.org)
        cls.pet = Pet.objects.create(name="Rocky", species="dog", breed="Boxer",
                                     owner=cls.owner, organization=cls.org)

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def _make_prescription(self, item_count=1, name_prefix="Amoxivet"):
        record = MedicalRecord.objects.create(
            organization=self.org, pet=self.pet, veterinarian=self.vet,
            diagnosis="dx", treatment="tx",
        )
        rx = Prescription.objects.create(
            organization=self.org, pet=self.pet, veterinarian=self.vet,
            medical_record=record, notes="Agitar antes de usar",
        )
        for i in range(item_count):
            product = Product.objects.create(
                name=f"{name_prefix}{i:02d}", internal_code=f"RXP{record.pk}_{i:02d}",
                requires_prescription=True, organization=self.org,
            )
            Presentation.objects.create(
                product=product, name=f"Frasco {i:02d}", base_unit="ml",
                sale_price=Decimal("120"), stock=Decimal("50"), organization=self.org,
            )
            PrescriptionItem.objects.create(
                prescription=rx, product=product, organization=self.org,
                dose="5ml cada 12h", quantity=Decimal("1"),
                duration="7 días", instructions="Con alimento",
            )
        return rx

    def _url(self, rx):
        return f'/api/prescriptions/{rx.public_id}/pdf/'

    def test_returns_pdf(self):
        rx = self._make_prescription()
        r = self.client.get(self._url(rx))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertIn('attachment', r['Content-Disposition'])
        self.assertIn(f'receta_{rx.id}', r['Content-Disposition'])
        # Nombre identificable: receta_<id>_<mascota>_<fecha local>.pdf
        self.assertRegex(
            r['Content-Disposition'],
            rf'receta_{rx.id}_Rocky_\d{{4}}-\d{{2}}-\d{{2}}\.pdf',
        )
        self.assertTrue(r.content.startswith(b'%PDF'))

    def test_pdf_text_contains_markers(self):
        rx = self._make_prescription()
        r = self.client.get(self._url(rx))
        text = _extract_pdf_text(r.content)
        self.assertIn("Rocky", text)                  # paciente
        self.assertIn("Pedro Ramirez", text)          # propietario
        self.assertIn("Amoxivet00", text)             # medicamento
        self.assertIn("Ana Galeno", text)             # veterinario (y firma)
        self.assertIn("Dermatología", text)           # especialidad
        self.assertIn("Agitar antes de usar", text)   # notas

    def test_many_items_paginate_without_losing_content(self):
        """
        Regresión del bug de overflow: el canvas crudo dibujaba con cursor `y`
        manual sin salto de página — recetas largas perdían contenido. Con
        platypus el documento debe tener 2+ páginas y el último medicamento
        debe seguir presente.
        """
        rx = self._make_prescription(item_count=40, name_prefix="MedPag")
        r = self.client.get(self._url(rx))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(_page_count(r.content), 2)
        text = _extract_pdf_text(r.content)
        self.assertIn("MedPag39", text)

    def test_cross_tenant_404(self):
        other_owner = Owner.objects.create(name="X", phone="5550002222",
                                           organization=self.org_other)
        other_pet = Pet.objects.create(name="OtherPet", species="cat",
                                       owner=other_owner, organization=self.org_other)
        other_vet = _make_user("vet_rx_pdf_b", self.org_other, "VET")
        other_record = MedicalRecord.objects.create(
            organization=self.org_other, pet=other_pet, veterinarian=other_vet,
        )
        rx_other = Prescription.objects.create(
            organization=self.org_other, pet=other_pet, veterinarian=other_vet,
            medical_record=other_record,
        )
        r = self.client.get(self._url(rx_other))
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)
