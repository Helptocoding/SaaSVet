"""INV-C en el registro rápido — `POST /api/appointments/create-with-patient/`.

Cierra la familia A1·B2 del inventario (§4.7.4). Era la última vía viva que
resolvía un expediente con `Owner.objects.get_or_create(phone=…)`: sin lock, dos
altas concurrentes del mismo número creaban **dos** expedientes, y un teléfono
con duplicados históricos hacía que `get_or_create` reventara o eligiera uno.

Lo que se ancla aquí:

  · **0 coincidencias** → crea Owner + Pet + cita, como siempre.
  · **1 coincidencia** → reutiliza (recepción, flujo aprobado) o
    `409 owner_exists` si el llamador pidió expediente nuevo (INV-B).
  · **≥ 2** → `409 owner_ambiguous`, con o sin flag. INV-C no es opt-in.
  · **Cero escrituras** en los dos 409: ni Owner, ni Pet, ni Appointment.
  · **Carrera**: dos altas simultáneas con el mismo teléfono normalizado dejan
    **un** expediente.

**PostgreSQL obligatorio** en la prueba de carrera: el lock de deduplicación es
un lock de aviso, que en SQLite no existe. Dos conexiones reales.
"""
import threading
from datetime import timedelta

from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.appointments.models import Appointment
from apps.core.models import Permission, Role, UserRole
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User

PHONE = '5512345678'
URL = '/api/appointments/create-with-patient/'


def _seed(name, suffix):
    org = Organization.objects.create(name=name, timezone="UTC")
    wildcard, _ = Permission.objects.get_or_create(code="*.*")
    role, _ = Role.objects.get_or_create(
        name="ADMIN", organization=org, defaults={"is_system_role": True})
    role.permissions.set([wildcard])
    admin = User.objects.create_user(
        username=f"cwp_admin_{suffix}", password="p", organization=org, role="ADMIN")
    UserRole.objects.get_or_create(user=admin, role=role)
    vet = User.objects.create_user(
        username=f"cwp_vet_{suffix}", password="p", organization=org, role="VET")
    UserRole.objects.get_or_create(user=vet, role=role)
    return org, admin, vet


def _payload(vet, *, phone=PHONE, owner_name='Ana Soto', pet_name='Luna', hour=10,
             **extra):
    day = (timezone.now() + timedelta(days=3)).date()
    body = {
        'owner_name': owner_name,
        'owner_phone': phone,
        'pet_name': pet_name,
        'pet_species': 'canino',
        'veterinarian': vet.id,
        'date': day.isoformat(),
        'start_time': f'{hour:02d}:00',
        'end_time': f'{hour:02d}:30',
        'reason': 'consulta',
    }
    body.update(extra)
    return body


class CreateWithPatientIdentityBase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org, cls.admin, cls.vet = _seed("INV-C registro rápido", "id")

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def real_owners(self, key=PHONE):
        return Owner.objects.for_organization(self.org).filter(
            is_generic=False, phone_normalized=key)

    def real_pets(self):
        return Pet.objects.for_organization(self.org).filter(is_generic=False)

    def counts(self):
        return (
            self.real_owners().count(),
            self.real_pets().count(),
            Appointment.objects.for_organization(self.org).count(),
        )


class ZeroMatchesTests(CreateWithPatientIdentityBase):
    def test_creates_owner_pet_and_appointment(self):
        resp = self.client.post(URL, _payload(self.vet), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(self.counts(), (1, 1, 1))
        owner = self.real_owners().get()
        self.assertEqual(owner.name, 'Ana Soto')
        self.assertEqual(owner.phone_normalized, PHONE)

    def test_key_is_derived_even_from_a_formatted_number(self):
        """La clave la deriva el dominio, no el formato que llegó en el body."""
        resp = self.client.post(URL, _payload(self.vet, phone='5512345678'), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(self.real_owners().count(), 1)

    def test_require_new_owner_is_satisfied_when_nobody_has_the_number(self):
        resp = self.client.post(
            URL, _payload(self.vet, require_new_owner=True), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(self.counts(), (1, 1, 1))


class OneMatchTests(CreateWithPatientIdentityBase):
    def setUp(self):
        super().setUp()
        self.existing = Owner.objects.create(
            organization=self.org, name="Ana Soto", phone='55 1234 5678')

    def test_without_the_flag_reception_reuses_the_record(self):
        """P2-14 (iron rule): el cliente que vuelve con otra mascota NO cambia.

        Y ahora además lo encuentra aunque su teléfono se capturara con
        espacios: la igualdad cruda de `get_or_create` no lo veía y creaba un
        expediente duplicado.
        """
        resp = self.client.post(URL, _payload(self.vet, pet_name='Rocky'), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(self.real_owners().count(), 1)
        self.assertEqual(self.real_pets().get().owner_id, self.existing.pk)

    def test_with_the_flag_it_refuses_and_writes_nothing(self):
        before = self.counts()
        resp = self.client.post(
            URL, _payload(self.vet, require_new_owner=True), format='json')

        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT, resp.data)
        self.assertEqual(resp.data['code'], 'owner_exists')
        self.assertEqual(
            resp.data['candidate']['public_id'], str(self.existing.public_id))
        self.assertEqual(resp.data['candidate']['name'], 'Ana Soto')
        # Cero escrituras: ni expediente, ni mascota, ni cita.
        self.assertEqual(self.counts(), before)

    def test_the_existing_record_is_not_modified(self):
        self.client.post(URL, _payload(self.vet, owner_name='Otro Nombre',
                                       require_new_owner=True), format='json')
        self.existing.refresh_from_db()
        self.assertEqual(self.existing.name, 'Ana Soto')
        self.assertEqual(self.existing.phone, '55 1234 5678')


class AmbiguousTests(CreateWithPatientIdentityBase):
    def setUp(self):
        super().setUp()
        # Distinguibles SOLO tras normalizar: la igualdad cruda vería uno.
        Owner.objects.create(organization=self.org, name="Ana López", phone='55 1234 5678')
        Owner.objects.create(organization=self.org, name="Ana Lopez", phone=PHONE)

    def test_refuses_for_every_actor_and_writes_nothing(self):
        for flag in (None, True, False):
            with self.subTest(require_new_owner=flag):
                before = self.counts()
                extra = {} if flag is None else {'require_new_owner': flag}
                resp = self.client.post(URL, _payload(self.vet, **extra), format='json')

                self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT, resp.data)
                self.assertEqual(resp.data['code'], 'owner_ambiguous')
                self.assertEqual(self.counts(), before)

    def test_no_candidate_is_published(self):
        """Ofrecer uno sería sugerir la elección que INV-C prohíbe."""
        resp = self.client.post(URL, _payload(self.vet), format='json')
        self.assertNotIn('candidate', resp.data)
        self.assertEqual(resp.data['candidate_count'], 2)


class RequireNewOwnerParsingTests(CreateWithPatientIdentityBase):
    """Fail-closed: un valor irreconocible es 400, nunca un `False` silencioso."""

    def test_unrecognised_value_is_rejected(self):
        for raw in ('yes', 1, 'sí', ''):
            with self.subTest(raw=raw):
                resp = self.client.post(
                    URL, _payload(self.vet, require_new_owner=raw), format='json')
                self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(self.counts(), (0, 0, 0))

    def test_string_booleans_are_accepted(self):
        resp = self.client.post(
            URL, _payload(self.vet, require_new_owner='false'), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)


class ConcurrentRegistrationTests(TransactionTestCase):
    """Dos altas simultáneas con el mismo teléfono → UN expediente.

    Las citas van a horas distintas a propósito: así el único punto de
    contención es el teléfono. Con el mismo hueco, INV-D rechazaría una por
    cupo y la prueba ya no diría nada sobre INV-C.
    """

    def setUp(self):
        self.org, self.admin, self.vet = _seed("INV-C carrera", "race")
        self.assertEqual(
            connection.vendor, 'postgresql',
            "El lock de deduplicación es un lock de aviso: exige PostgreSQL.",
        )

    def _post(self, hour, pet_name):
        def run(barrier):
            client = APIClient()
            client.force_authenticate(self.admin)
            barrier.wait()
            try:
                resp = client.post(
                    URL, _payload(self.vet, hour=hour, pet_name=pet_name),
                    format='json')
                return resp.status_code
            finally:
                connection.close()
        return run

    def test_two_registrations_share_one_record(self):
        barrier = threading.Barrier(2, timeout=15)
        results = [None, None]

        def wrapped(i, fn):
            try:
                results[i] = ('ok', fn(barrier))
            except BaseException as exc:  # noqa: BLE001 — el desenlace ES el dato
                results[i] = ('error', exc)

        threads = [
            threading.Thread(target=wrapped, args=(0, self._post(10, 'Luna'))),
            threading.Thread(target=wrapped, args=(1, self._post(12, 'Rocky'))),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        for t in threads:
            self.assertFalse(t.is_alive(), "Hilo bloqueado: posible deadlock.")

        owners = Owner.objects.for_organization(self.org).filter(
            is_generic=False, phone_normalized=PHONE)
        self.assertEqual(
            owners.count(), 1,
            f"Dos altas concurrentes fabricaron expedientes duplicados: {results}",
        )
        # Las dos altas debían prosperar: horas distintas, sin choque de cupo.
        self.assertEqual([r[1] for r in results], [201, 201], results)
        self.assertEqual(
            Pet.objects.for_organization(self.org).filter(is_generic=False).count(), 2)
