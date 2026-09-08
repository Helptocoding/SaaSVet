"""
test_audit_overlaps.py — `audit_appointment_overlaps` (INV-D, F0·b).

El comando es el gate de la migración 0014: si miente (reporta limpio con
solapes históricos vivos), la migración falla en producción a mitad de la
ventana de deploy. Por eso se prueba que DETECTA, que no corrige nada y que
respeta el criterio exacto de la restricción.

Para poder crear los solapes que el comando debe encontrar hay que reproducir
el mundo PRE-migración: se hace `DROP CONSTRAINT` dentro de la transacción del
test (el DDL de PostgreSQL es transaccional, así que el rollback del test lo
restaura) y se insertan las filas con SQL crudo. Cualquier otra forma probaría
un escenario que ya no puede existir, que es lo contrario de lo que hace falta.
"""
from datetime import timedelta

from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User


def _drop_no_overlap_constraint():
    """Simula el mundo pre-migración 0014. Revertido por el rollback del test."""
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE appointments_appointment "
            "DROP CONSTRAINT IF EXISTS appointment_no_overlap_per_vet"
        )


def _insert_raw_appointment(org, pet, vet, start, end, status='scheduled'):
    """INSERT directo — salta el ORM, la restricción y `full_clean()`."""
    import uuid
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO appointments_appointment
                (public_id, organization_id, pet_id, veterinarian_id,
                date, start_time, end_time, start_datetime, end_datetime,
                 timezone_at_creation, reason, category, notes, cancellation_reason,
                 status, walk_in, created_at, updated_at, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'UTC', 'historico', 'general_consultation', '', '', %s, false, now(), now(), true)
            RETURNING id
            """,
            [
                str(uuid.uuid4()), org.pk, pet.pk, vet.pk,
                start.date(), start.time(), end.time(), start, end, status,
            ],
        )
        return cursor.fetchone()[0]


class AuditAppointmentOverlapsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Audit Org", timezone="UTC")
        cls.vet = User.objects.create_user(
            username="audit_vet", password="p", organization=cls.org, role="VET")
        owner = Owner.objects.create(
            organization=cls.org, name="Ana", phone="5511110003")
        cls.pet_a = Pet.objects.create(
            organization=cls.org, owner=owner, name="Luna",
            species="perro", birth_date="2021-01-01")
        cls.pet_b = Pet.objects.create(
            organization=cls.org, owner=owner, name="Rocky",
            species="perro", birth_date="2021-01-01")
        cls.base = timezone.now() + timedelta(days=30)

    def setUp(self):
        _drop_no_overlap_constraint()

    def _run(self):
        """Devuelve el exit code del comando (siempre llama a sys.exit)."""
        with self.assertRaises(SystemExit) as raised:
            call_command('audit_appointment_overlaps', org=self.org.pk)
        return raised.exception.code

    def test_clean_database_exits_zero(self):
        _insert_raw_appointment(
            self.org, self.pet_a, self.vet, self.base, self.base + timedelta(minutes=30))
        self.assertEqual(self._run(), 0)

    def test_overlapping_active_pair_exits_one(self):
        _insert_raw_appointment(
            self.org, self.pet_a, self.vet, self.base, self.base + timedelta(minutes=30))
        _insert_raw_appointment(
            self.org, self.pet_b, self.vet,
            self.base + timedelta(minutes=10), self.base + timedelta(minutes=40))

        self.assertEqual(self._run(), 1)
        # Diagnóstico, no remediación: las dos citas siguen ahí, sin tocar.
        self.assertEqual(Appointment.objects.filter(organization=self.org).count(), 2)
        self.assertEqual(
            Appointment.objects.filter(organization=self.org, status='scheduled').count(),
            2)

    def test_canceled_appointment_is_not_an_overlap(self):
        _insert_raw_appointment(
            self.org, self.pet_a, self.vet, self.base, self.base + timedelta(minutes=30))
        _insert_raw_appointment(
            self.org, self.pet_b, self.vet,
            self.base + timedelta(minutes=10), self.base + timedelta(minutes=40),
            status='canceled')
        self.assertEqual(self._run(), 0)

    def test_adjacent_appointments_are_not_an_overlap(self):
        _insert_raw_appointment(
            self.org, self.pet_a, self.vet, self.base, self.base + timedelta(minutes=30))
        _insert_raw_appointment(
            self.org, self.pet_b, self.vet,
            self.base + timedelta(minutes=30), self.base + timedelta(minutes=60))
        self.assertEqual(self._run(), 0)

    def test_different_veterinarians_do_not_overlap(self):
        other_vet = User.objects.create_user(
            username="audit_vet_2", password="p", organization=self.org, role="VET")
        _insert_raw_appointment(
            self.org, self.pet_a, self.vet, self.base, self.base + timedelta(minutes=30))
        _insert_raw_appointment(
            self.org, self.pet_b, other_vet,
            self.base + timedelta(minutes=10), self.base + timedelta(minutes=40))
        self.assertEqual(self._run(), 0)

    def test_other_organization_is_not_reported_under_org_filter(self):
        other_org = Organization.objects.create(name="Audit Org B", timezone="UTC")
        other_vet = User.objects.create_user(
            username="audit_vet_b", password="p", organization=other_org, role="VET")
        other_owner = Owner.objects.create(
            organization=other_org, name="Beto", phone="5511110004")
        other_pet = Pet.objects.create(
            organization=other_org, owner=other_owner, name="Kira",
            species="perro", birth_date="2021-01-01")
        other_pet2 = Pet.objects.create(
            organization=other_org, owner=other_owner, name="Nube",
            species="perro", birth_date="2021-01-01")
        _insert_raw_appointment(
            other_org, other_pet, other_vet, self.base,
            self.base + timedelta(minutes=30))
        _insert_raw_appointment(
            other_org, other_pet2, other_vet, self.base + timedelta(minutes=10),
            self.base + timedelta(minutes=40))

        # Filtrado a self.org: el solape de la otra organización no cuenta.
        self.assertEqual(self._run(), 0)

        # Sin filtro sí aparece.
        with self.assertRaises(SystemExit) as raised:
            call_command('audit_appointment_overlaps')
        self.assertEqual(raised.exception.code, 1)
