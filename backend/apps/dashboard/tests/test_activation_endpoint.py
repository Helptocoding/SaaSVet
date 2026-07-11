"""
Estado de activación de la clínica — GET /api/v1/dashboard/activation/.

Read-only, multi-tenant, basado en existencia REAL (sin flags persistidos):
- org recién creada (solo genéricos sembrados) => los 4 hitos en False.
- la mascota GENÉRICA no cuenta como "tiene pacientes".
- cada hito flipea a True al crear el recurso real de SU dominio.
- `completed` = READINESS = has_patients AND has_services (clínica lista para operar).
  NO depende de has_appointments/has_consultations (eventos que requieren un cliente
  real; mantendrían el onboarding activo días). Se completa en la 1ª sesión.
- datos de OTRA org nunca cuentan (aislamiento).
"""
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from apps.appointments.models import Appointment
from apps.billing.models import Service
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.medical_records.models import MedicalRecord
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User

ACTIVATION_URL = '/api/v1/dashboard/activation/'


def _seed_roles(org):
    wildcard, _ = Permission.objects.get_or_create(code="*.*")
    perms_map = {c: Permission.objects.get_or_create(code=c)[0] for c in PERMISSION_CODES}
    out = {}
    for name, codes in PERMISSIONS.items():
        if name == "ADMIN_SAAS":
            continue
        role, _ = Role.objects.get_or_create(name=name, organization=org, defaults={"is_system_role": True})
        role.permissions.set([wildcard] if "*.*" in codes else [perms_map[c] for c in codes if c in perms_map])
        out[name] = role
    return out


def _make_user(username, org, role_name):
    u = User.objects.create_user(username=username, password="x", organization=org, role=role_name)
    roles = _seed_roles(org)
    UserRole.objects.get_or_create(user=u, role=roles[role_name])
    return u


class DashboardActivationTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        # El post_save de Organization siembra 1 Owner + 1 Pet GENÉRICOS.
        cls.org = Organization.objects.create(name="Activación Org", timezone="UTC")
        cls.admin = _make_user("act_admin", cls.org, "ADMIN")
        cls.vet = _make_user("act_vet", cls.org, "VET")

        # Ruido en otra org — nunca debe flipear los hitos de cls.org.
        cls.other = Organization.objects.create(name="Otra Org", timezone="UTC")
        other_owner = Owner.objects.create(name="Ajeno", phone="5550000000", organization=cls.other)
        Pet.objects.create(name="PerroAjeno", species="canino", owner=other_owner, organization=cls.other)
        Service.objects.create(name="ServicioAjeno", base_price=Decimal("100.00"), organization=cls.other)

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_empty_org_all_false(self):
        resp = self.client.get(ACTIVATION_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data, {
            'has_patients': False,
            'has_services': False,
            'has_appointments': False,
            'has_consultations': False,
            'completed': False,
        })

    def test_generic_pet_does_not_count_as_patients(self):
        # La org tiene la mascota genérica sembrada, pero has_patients debe ser False.
        self.assertTrue(Pet.objects.for_organization(self.org).filter(is_generic=True).exists())
        resp = self.client.get(ACTIVATION_URL)
        self.assertFalse(resp.data['has_patients'])

    def test_each_milestone_flips_independently(self):
        owner = Owner.objects.create(name="Dueño Real", phone="5551112222", organization=self.org)
        pet = Pet.objects.create(name="Lola", species="canino", owner=owner, organization=self.org)
        resp = self.client.get(ACTIVATION_URL)
        self.assertTrue(resp.data['has_patients'])
        self.assertFalse(resp.data['completed'])  # falta el servicio

        Service.objects.create(name="Consulta", base_price=Decimal("250.00"), organization=self.org)
        self.assertTrue(self.client.get(ACTIVATION_URL).data['has_services'])

        Appointment.objects.create(
            pet=pet, veterinarian=self.vet, date='2035-01-01',
            start_time='10:00', end_time='10:30',
            status='scheduled', reason='Chequeo', organization=self.org,
        )
        self.assertTrue(self.client.get(ACTIVATION_URL).data['has_appointments'])

        MedicalRecord.objects.create(
            pet=pet, veterinarian=self.vet, consultation_type='general',
            diagnosis='Dx', status='open', organization=self.org,
        )
        final = self.client.get(ACTIVATION_URL).data
        self.assertTrue(final['has_consultations'])
        self.assertTrue(final['completed'])

    def test_completed_is_readiness_patients_and_services_only(self):
        """`completed` = has_patients AND has_services, sin depender de cita/consulta.

        La clínica queda "lista para operar" al configurarse (1ª sesión); no debe
        esperar a que llegue un cliente real (cita/consulta = eventos externos).
        """
        owner = Owner.objects.create(name="Dueño", phone="5553334444", organization=self.org)
        Pet.objects.create(name="Fido", species="canino", owner=owner, organization=self.org)

        # Solo paciente → aún NO listo (falta servicio).
        self.assertFalse(self.client.get(ACTIVATION_URL).data['completed'])

        Service.objects.create(name="Baño", base_price=Decimal("150.00"), organization=self.org)

        # Paciente + servicio → LISTO, aunque NO haya cita ni consulta.
        data = self.client.get(ACTIVATION_URL).data
        self.assertTrue(data['completed'])
        self.assertFalse(data['has_appointments'])
        self.assertFalse(data['has_consultations'])

    def test_only_services_without_patients_not_completed(self):
        """Servicio sin paciente NO completa (readiness exige ambos)."""
        Service.objects.create(name="Vacuna", base_price=Decimal("200.00"), organization=self.org)
        data = self.client.get(ACTIVATION_URL).data
        self.assertTrue(data['has_services'])
        self.assertFalse(data['has_patients'])
        self.assertFalse(data['completed'])

    def test_multitenant_other_org_data_does_not_count(self):
        # cls.other tiene pet + service; cls.org sigue vacía.
        resp = self.client.get(ACTIVATION_URL)
        self.assertFalse(resp.data['has_patients'])
        self.assertFalse(resp.data['has_services'])
