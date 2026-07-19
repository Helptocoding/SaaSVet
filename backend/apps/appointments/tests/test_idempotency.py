"""
test_idempotency.py — É-F2 PR-14 (ADR p52): idempotencia de creación + fix
del guard de fecha-pasada en update.
"""
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.appointments.models import Appointment
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSIONS
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User


def _seed_admin(org):
    wildcard, _ = Permission.objects.get_or_create(code="*.*")
    role, _ = Role.objects.get_or_create(
        name="ADMIN", organization=org, defaults={"is_system_role": True})
    role.permissions.set([wildcard])
    return role


class IdempotencyTestBase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Idem Org", timezone="UTC")
        role = _seed_admin(cls.org)
        cls.admin = User.objects.create_user(
            username="idem_admin", password="p", organization=cls.org, role="ADMIN")
        UserRole.objects.get_or_create(user=cls.admin, role=role)
        cls.vet = User.objects.create_user(
            username="idem_vet", password="p", organization=cls.org, role="VET")
        owner = Owner.objects.create(organization=cls.org, name="Ana", phone="5511110000")
        cls.pet = Pet.objects.create(
            organization=cls.org, owner=owner, name="Luna",
            species="perro", birth_date="2021-01-01")

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def _future(self, days=3):
        start = timezone.now() + timedelta(days=days)
        return {
            "pet": self.pet.id,
            "veterinarian": self.vet.id,
            "date": start.date().isoformat(),
            "start_time": start.strftime("%H:%M"),
            "end_time": (start + timedelta(minutes=30)).strftime("%H:%M"),
            "reason": "vacuna",
        }


class CreateIdempotencyTests(IdempotencyTestBase):
    def test_same_key_replays_not_duplicates(self):
        payload = self._future()
        r1 = self.client.post("/api/appointments/", payload,
                              HTTP_X_IDEMPOTENCY_KEY="abc-123")
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED, r1.content)

        # mismo key + mismo payload = reintento → 200 con la MISMA cita
        r2 = self.client.post("/api/appointments/", payload,
                              HTTP_X_IDEMPOTENCY_KEY="abc-123")
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertEqual(r1.json()["public_id"], r2.json()["public_id"])
        self.assertEqual(Appointment.objects.count(), 1)

    def test_no_key_creates_normally(self):
        self.client.post("/api/appointments/", self._future())
        self.client.post("/api/appointments/", self._future(days=4))
        self.assertEqual(Appointment.objects.count(), 2)  # sin key = como antes

    def test_different_keys_create_separate(self):
        self.client.post("/api/appointments/", self._future(),
                         HTTP_X_IDEMPOTENCY_KEY="k1")
        self.client.post("/api/appointments/", self._future(days=4),
                         HTTP_X_IDEMPOTENCY_KEY="k2")
        self.assertEqual(Appointment.objects.count(), 2)


class CreateWithPatientIdempotencyTests(IdempotencyTestBase):
    def _payload(self):
        start = timezone.now() + timedelta(days=3)
        return {
            "owner_name": "Nuevo Cliente",
            "owner_phone": "5599887766",
            "pet_name": "Michi",
            "pet_species": "felino",
            "veterinarian": self.vet.id,
            "date": start.date().isoformat(),
            "start_time": start.strftime("%H:%M"),
            "end_time": (start + timedelta(minutes=30)).strftime("%H:%M"),
            "reason": "revision",
        }

    def test_replay_does_not_duplicate_owner_pet_or_appt(self):
        payload = self._payload()
        before_owners = Owner.objects.count()
        before_pets = Pet.objects.count()

        r1 = self.client.post("/api/appointments/create-with-patient/", payload,
                              HTTP_X_IDEMPOTENCY_KEY="cwp-1")
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED, r1.content)

        r2 = self.client.post("/api/appointments/create-with-patient/", payload,
                              HTTP_X_IDEMPOTENCY_KEY="cwp-1")
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertEqual(r1.json()["public_id"], r2.json()["public_id"])
        # ni cita, ni owner, ni pet duplicados
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(Owner.objects.count(), before_owners + 1)
        self.assertEqual(Pet.objects.count(), before_pets + 1)


class PastDateGuardTests(IdempotencyTestBase):
    def test_reschedule_to_past_is_rejected(self):
        """Fix PR-14: antes el PATCH podía mover una cita al pasado."""
        r = self.client.post("/api/appointments/", self._future())
        public_id = r.json()["public_id"]

        past = timezone.now() - timedelta(days=2)
        patch = self.client.patch(
            f"/api/appointments/{public_id}/",
            {"date": past.date().isoformat(),
             "start_time": past.strftime("%H:%M"),
             "end_time": (past + timedelta(minutes=30)).strftime("%H:%M")},
        )
        self.assertEqual(patch.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reschedule_to_future_ok(self):
        r = self.client.post("/api/appointments/", self._future())
        public_id = r.json()["public_id"]

        future = timezone.now() + timedelta(days=5)
        patch = self.client.patch(
            f"/api/appointments/{public_id}/",
            {"date": future.date().isoformat(),
             "start_time": future.strftime("%H:%M"),
             "end_time": (future + timedelta(minutes=30)).strftime("%H:%M")},
        )
        self.assertEqual(patch.status_code, status.HTTP_200_OK, patch.content)

    def test_edit_reason_on_future_appt_not_blocked(self):
        """Un update que NO toca la fecha no dispara el guard."""
        r = self.client.post("/api/appointments/", self._future())
        public_id = r.json()["public_id"]
        patch = self.client.patch(
            f"/api/appointments/{public_id}/", {"reason": "otro motivo"})
        self.assertEqual(patch.status_code, status.HTTP_200_OK, patch.content)
