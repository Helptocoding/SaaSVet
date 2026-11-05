"""
Tests del scratchpad `consultation_draft` (borrador de UI) y de la
materializacion atomica del protocolo Vacuna al cerrar la consulta
(apply_consultation_draft_on_close).
"""
from datetime import date, timedelta

from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.medical_records.models import ConsultationAssessment, MedicalRecord, VaccineRecord
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
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


class ConsultationDraftFieldTests(APITestCase):
    """Estructura (whitelist + tamaño) del scratchpad. No valida contenido."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Org Draft", timezone="UTC")
        cls.vet = _make_user("vet_draft", cls.org, "VET")

    def _make_record(self):
        owner = Owner.objects.create(name="O", phone="1", organization=self.org)
        pet = Pet.objects.create(name="P", species="canino", owner=owner, organization=self.org)
        return MedicalRecord.objects.create(
            pet=pet, veterinarian=self.vet, organization=self.org,
            diagnosis="d", treatment="t",
        )

    def _detail_url(self, pk):
        return f"/api/medical-records/{pk}/"

    def test_default_is_empty_dict(self):
        mr = self._make_record()
        self.client.force_authenticate(self.vet)
        r = self.client.get(self._detail_url(mr.public_id))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["consultation_draft"], {})

    def test_roundtrip_patch_and_get(self):
        mr = self._make_record()
        self.client.force_authenticate(self.vet)
        payload = {"consultation_draft": {"vaccine": {"vaccine_name": "Rabia"}}}
        r = self.client.patch(self._detail_url(mr.public_id), payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        r2 = self.client.get(self._detail_url(mr.public_id))
        self.assertEqual(r2.data["consultation_draft"], {"vaccine": {"vaccine_name": "Rabia"}})

    def test_general_key_accepted(self):
        mr = self._make_record()
        self.client.force_authenticate(self.vet)
        payload = {"consultation_draft": {"general": {"chief_complaint": "Vómito"}}}
        r = self.client.patch(self._detail_url(mr.public_id), payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["consultation_draft"], {"general": {"chief_complaint": "Vómito"}})

    def test_rejects_key_outside_whitelist(self):
        mr = self._make_record()
        self.client.force_authenticate(self.vet)
        r = self.client.patch(
            self._detail_url(mr.public_id),
            {"consultation_draft": {"hola": {}, "otra_cosa": {}}},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_non_dict(self):
        mr = self._make_record()
        self.client.force_authenticate(self.vet)
        r = self.client.patch(
            self._detail_url(mr.public_id),
            {"consultation_draft": ["not", "a", "dict"]},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_oversized_payload(self):
        mr = self._make_record()
        self.client.force_authenticate(self.vet)
        big = {"vaccine": {"notes": "x" * 20000}}  # > 16 KB
        r = self.client.patch(
            self._detail_url(mr.public_id),
            {"consultation_draft": big},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class VaccineMaterializationOnCloseTests(APITestCase):
    """apply_consultation_draft_on_close: crea VaccineRecord en el atomic del cierre."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Org Vacc", timezone="UTC")
        cls.vet = _make_user("vet_vacc", cls.org, "VET")

    def _make_record(self, consultation_type, draft):
        owner = Owner.objects.create(name="O", phone="2", organization=self.org)
        pet = Pet.objects.create(name="P", species="canino", owner=owner, organization=self.org)
        return MedicalRecord.objects.create(
            pet=pet, veterinarian=self.vet, organization=self.org,
            consultation_type=consultation_type,
            diagnosis="vacunación", treatment="",
            consultation_draft=draft,
        )

    def _close_url(self, pk):
        return f"/api/medical-records/{pk}/close/"

    def _vaccine_draft(self, **over):
        app = date.today() - timedelta(days=30)
        due = date.today() + timedelta(days=335)
        base = {
            "vaccine_name": "Rabia",
            "application_date": app.isoformat(),
            "scheduleBooster": True,
            "next_due_date": due.isoformat(),
            "notes": "lote ABC",
        }
        base.update(over)
        return {"vaccine": base}

    def test_vaccine_close_materializes_record(self):
        mr = self._make_record(MedicalRecord.ConsultationType.VACCINE, self._vaccine_draft())
        self.client.force_authenticate(self.vet)
        r = self.client.post(self._close_url(mr.public_id))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        qs = VaccineRecord.objects.filter(medical_record=mr)
        self.assertEqual(qs.count(), 1)
        vr = qs.first()
        self.assertEqual(vr.vaccine_name, "Rabia")
        self.assertEqual(vr.applied_by, self.vet)
        self.assertEqual(vr.pet_id, mr.pet_id)
        self.assertEqual(vr.organization_id, self.org.id)
        self.assertIsNotNone(vr.next_due_date)

    def test_general_type_does_not_materialize(self):
        # Draft de vacuna presente pero el tipo final es general → no se crea.
        mr = self._make_record(MedicalRecord.ConsultationType.GENERAL, self._vaccine_draft())
        mr.treatment = "reposo"  # general exige tratamiento
        mr.save(update_fields=["treatment"])
        self.client.force_authenticate(self.vet)
        r = self.client.post(self._close_url(mr.public_id))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(VaccineRecord.objects.filter(medical_record=mr).count(), 0)

    def test_no_vaccine_name_does_not_materialize(self):
        mr = self._make_record(
            MedicalRecord.ConsultationType.VACCINE, {"vaccine": {"vaccine_name": ""}}
        )
        self.client.force_authenticate(self.vet)
        r = self.client.post(self._close_url(mr.public_id))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(VaccineRecord.objects.filter(medical_record=mr).count(), 0)

    def test_invalid_draft_rolls_back_close(self):
        # next_due <= application → serializer 400 → rollback del cierre completo.
        app = date.today() - timedelta(days=1)
        bad = self._vaccine_draft(
            application_date=app.isoformat(),
            next_due_date=app.isoformat(),  # no posterior
        )
        mr = self._make_record(MedicalRecord.ConsultationType.VACCINE, bad)
        self.client.force_authenticate(self.vet)
        r = self.client.post(self._close_url(mr.public_id))
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        mr.refresh_from_db()
        self.assertEqual(mr.status, MedicalRecord.Status.OPEN)  # rollback
        self.assertEqual(VaccineRecord.objects.filter(medical_record=mr).count(), 0)

    def test_no_booster_sets_next_due_null(self):
        draft = self._vaccine_draft(scheduleBooster=False, next_due_date=None)
        mr = self._make_record(MedicalRecord.ConsultationType.VACCINE, draft)
        self.client.force_authenticate(self.vet)
        r = self.client.post(self._close_url(mr.public_id))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        vr = VaccineRecord.objects.get(medical_record=mr)
        self.assertIsNone(vr.next_due_date)

    def test_idempotent_close_does_not_duplicate(self):
        mr = self._make_record(MedicalRecord.ConsultationType.VACCINE, self._vaccine_draft())
        self.client.force_authenticate(self.vet)
        self.client.post(self._close_url(mr.public_id))
        self.client.post(self._close_url(mr.public_id))  # segunda vez: ya cerrada
        self.assertEqual(VaccineRecord.objects.filter(medical_record=mr).count(), 1)


class GeneralAssessmentMaterializationOnCloseTests(APITestCase):
    """_materialize_general: crea ConsultationAssessment en el atomic del cierre."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Org Gen", timezone="UTC")
        cls.vet = _make_user("vet_gen", cls.org, "VET")

    def _make_record(self, draft, diagnosis="dx", treatment="tx"):
        owner = Owner.objects.create(name="O", phone="3", organization=self.org)
        pet = Pet.objects.create(name="P", species="canino", owner=owner, organization=self.org)
        return MedicalRecord.objects.create(
            pet=pet, veterinarian=self.vet, organization=self.org,
            consultation_type=MedicalRecord.ConsultationType.GENERAL,
            diagnosis=diagnosis, treatment=treatment,
            consultation_draft=draft,
        )

    def _close_url(self, pk):
        return f"/api/medical-records/{pk}/close/"

    def test_general_with_content_materializes(self):
        mr = self._make_record({"general": {"chief_complaint": "Vómito", "history": "hace 2 días"}})
        self.client.force_authenticate(self.vet)
        r = self.client.post(self._close_url(mr.public_id))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        qs = ConsultationAssessment.objects.filter(medical_record=mr)
        self.assertEqual(qs.count(), 1)
        ca = qs.first()
        self.assertEqual(ca.chief_complaint, "Vómito")
        self.assertEqual(ca.pet_id, mr.pet_id)
        self.assertEqual(ca.organization_id, self.org.id)
        self.assertEqual(ca.assessed_by, self.vet)
        self.assertEqual(ca.protocol_version, 1)

    def test_general_empty_draft_does_not_materialize(self):
        # Consulta general "clásica" (sin SOAP estructurado) → no crea assessment.
        mr = self._make_record({})
        self.client.force_authenticate(self.vet)
        r = self.client.post(self._close_url(mr.public_id))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(ConsultationAssessment.objects.filter(medical_record=mr).count(), 0)

    def test_general_still_requires_diagnosis(self):
        # General mantiene las reglas de cierre actuales (dx obligatorio).
        mr = self._make_record({"general": {"chief_complaint": "x"}}, diagnosis="", treatment="tx")
        self.client.force_authenticate(self.vet)
        r = self.client.post(self._close_url(mr.public_id))
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ConsultationAssessment.objects.filter(medical_record=mr).count(), 0)

    def test_idempotent_close_does_not_duplicate(self):
        mr = self._make_record({"general": {"chief_complaint": "x"}})
        self.client.force_authenticate(self.vet)
        self.client.post(self._close_url(mr.public_id))
        self.client.post(self._close_url(mr.public_id))
        self.assertEqual(ConsultationAssessment.objects.filter(medical_record=mr).count(), 1)
