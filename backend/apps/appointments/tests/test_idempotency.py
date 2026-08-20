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


# Hora FIJA para todos los huecos de prueba. Estos tests prueban idempotencia y
# el guard de fecha pasada; la hora del día es irrelevante para ambos.
#
# Con la hora ACTUAL sí importaba, y mal: el hueco se armaba como
# `now + N días` y `end_time = start + 30 min`, ambos formateados `%H:%M`. En
# los últimos 30 minutos del día UTC eso envuelve —23:50 produce end 00:20— y
# el serializer lo rechaza (`end_time <= start_time`, appointments/serializers
# §96). La suite fallaba en una ventana de 30 minutos cada noche.
SLOT_HOUR = 10


def _slot(days):
    """`(fecha_iso, inicio_hhmm, fin_hhmm)` a `days` días, a hora fija.

    `days` negativo da una fecha pasada (para el guard de reprogramación).
    """
    day = (timezone.now() + timedelta(days=days)).date()
    return day.isoformat(), f"{SLOT_HOUR:02d}:00", f"{SLOT_HOUR:02d}:30"


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
        date, start, end = _slot(days)
        return {
            "pet": self.pet.id,
            "veterinarian": self.vet.id,
            "date": date,
            "start_time": start,
            "end_time": end,
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
        date, start, end = _slot(3)
        return {
            "owner_name": "Nuevo Cliente",
            "owner_phone": "5599887766",
            "pet_name": "Michi",
            "pet_species": "felino",
            "veterinarian": self.vet.id,
            "date": date,
            "start_time": start,
            "end_time": end,
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
    @staticmethod
    def _precondition(created):
        """INV-A Fase 3: el PATCH exige declarar cómo se vio la cita.

        Se arma con el cuerpo de la creación, que es literalmente lo que el
        llamador tiene delante.
        """
        return {"expected_state": {
            "status": created["status"],
            "date": created["date"],
            "start_time": created["start_time"],
        }}

    def test_reschedule_to_past_is_rejected(self):
        """Fix PR-14: antes el PATCH podía mover una cita al pasado."""
        r = self.client.post("/api/appointments/", self._future())
        created = r.json()

        past_date, start, end = _slot(-2)
        patch = self.client.patch(
            f"/api/appointments/{created['public_id']}/",
            {"date": past_date, "start_time": start, "end_time": end,
             **self._precondition(created)},
            format="json",
        )
        self.assertEqual(patch.status_code, status.HTTP_400_BAD_REQUEST)
        # El 400 tiene que venir del guard de fecha, NO de la precondición: sin
        # esta comprobación el test seguiría verde aunque el guard se hubiera
        # caído, porque `precondition_required` también es 400.
        self.assertIn("date", patch.json().get("errors", {}))

    def test_reschedule_to_future_ok(self):
        r = self.client.post("/api/appointments/", self._future())
        created = r.json()

        future_date, start, end = _slot(5)
        patch = self.client.patch(
            f"/api/appointments/{created['public_id']}/",
            {"date": future_date, "start_time": start, "end_time": end,
             **self._precondition(created)},
            format="json",
        )
        self.assertEqual(patch.status_code, status.HTTP_200_OK, patch.content)

    def test_edit_reason_on_future_appt_not_blocked(self):
        """Un update que NO toca la fecha no dispara el guard."""
        r = self.client.post("/api/appointments/", self._future())
        created = r.json()
        patch = self.client.patch(
            f"/api/appointments/{created['public_id']}/",
            {"reason": "otro motivo", **self._precondition(created)},
            format="json",
        )
        self.assertEqual(patch.status_code, status.HTTP_200_OK, patch.content)

    def test_cancel_past_appointment_is_rejected_without_audit_write(self):
        """A scheduled legacy row in the past cannot be cancelled anymore."""
        r = self.client.post("/api/appointments/", self._future())
        created = r.json()
        appt = Appointment.objects.get(public_id=created["public_id"])
        past = timezone.now() - timedelta(hours=2)
        appt.date = past.date()
        appt.start_time = past.time().replace(second=0, microsecond=0)
        appt.end_time = (past + timedelta(minutes=30)).time().replace(
            second=0, microsecond=0)
        appt.start_datetime = past
        appt.end_datetime = past + timedelta(minutes=30)
        appt.save(update_fields=[
            "date", "start_time", "end_time", "start_datetime", "end_datetime",
        ])

        response = self.client.patch(
            f"/api/appointments/{appt.public_id}/status/",
            {"status": "canceled", "expected_state": {
                "status": "scheduled",
                "date": appt.date.isoformat(),
                "start_time": appt.start_time.strftime("%H:%M"),
            }},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("code"), "past_appointment")
        appt.refresh_from_db()
        self.assertEqual(appt.status, "scheduled")
        self.assertEqual(appt.status_changes.count(), 0)
