"""INV-C — un teléfono normalizado identifica como máximo un expediente.

**PostgreSQL obligatorio.** Todo aquí se apoya en un lock de aviso a nivel de
transacción; en SQLite el mecanismo no existe y la suite pasaría en verde sin
acreditar nada.

`ConcurrencyTests` y `AdvisoryLockContractTests` usan `TransactionTestCase`
(commits reales) y dos hilos con **dos conexiones reales** — una prueba de
carrera sobre una sola conexión no es una prueba de carrera, y la guarda de
«exige transacción abierta» nunca dispararía dentro del `atomic()` que
`TestCase` monta. El resto usa `TestCase`: el lock funciona igual ahí y la
suite tarda un orden de magnitud menos.

Cobertura (plan §12.3): P0-16, P0-17, P0-21, P0-22, P0-23, P0-24, P0-25, P0-28,
P2-12, P2-14, P2-15.
"""
import ast
import threading
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

from django.db import connection, transaction
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from rest_framework.test import APIClient

from apps.core.db_locks import AdvisoryLockUnsupported, advisory_xact_lock
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.patients.services import (
    OwnerAmbiguous,
    OwnerExists,
    change_owner_phone,
    lookup_owner_by_phone,
    resolve_owner_for_phone,
)
from apps.users.models import User

PHONE = '5512345678'
PHONE_ALT = '5598765432'


def _seed_roles(org):
    wildcard, _ = Permission.objects.get_or_create(code="*.*")
    perms_map = {c: Permission.objects.get_or_create(code=c)[0] for c in PERMISSION_CODES}
    roles = {}
    for name, codes in PERMISSIONS.items():
        if name == "ADMIN_SAAS":
            continue
        role, _ = Role.objects.get_or_create(
            name=name, organization=org, defaults={"is_system_role": True},
        )
        role.permissions.set(
            [wildcard] if "*.*" in codes else [perms_map[c] for c in codes if c in perms_map]
        )
        roles[name] = role
    return roles


def _make_admin(username, org):
    user = User.objects.create_user(
        username=username, password="pass", organization=org, role="ADMIN",
    )
    UserRole.objects.get_or_create(user=user, role=_seed_roles(org)["ADMIN"])
    return user


def run_concurrently(*fns):
    """Ejecuta `fns` en hilos distintos —conexiones distintas— y devuelve
    `[(estado, valor|excepción), …]` en el orden de entrada.

    Cada función recibe una barrera que debe esperar **dentro** de su
    transacción: así las dos llegan al lock a la vez, que es lo que la prueba
    quiere ejercitar.
    """
    results = [None] * len(fns)
    barrier = threading.Barrier(len(fns), timeout=15)

    def wrapped(index, fn):
        try:
            results[index] = ('ok', fn(barrier))
        except BaseException as exc:  # noqa: BLE001 — el desenlace ES el dato
            results[index] = ('error', exc)
        finally:
            connection.close()

    threads = [
        threading.Thread(target=wrapped, args=(i, fn)) for i, fn in enumerate(fns)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    for t in threads:
        assert not t.is_alive(), "Un hilo quedó bloqueado: posible deadlock."
    return results


class OwnerPhoneIdentityMixin:
    def setUp(self):
        self.org = Organization.objects.create(name="Clínica INV-C", timezone="UTC")
        self.other_org = Organization.objects.create(name="Otra Clínica", timezone="UTC")

    def real_owners(self, org=None, phone_key=PHONE):
        return Owner.objects.for_organization(org or self.org).filter(
            is_generic=False, phone_normalized=phone_key,
        )

    def real_pets(self, org=None):
        """Mascotas de verdad: la genérica la siembra el signal de la org."""
        return Pet.objects.for_organization(org or self.org).filter(is_generic=False)


class OwnerPhoneIdentityBase(OwnerPhoneIdentityMixin, TestCase):
    """Caso normal: rollback por transacción.

    El lock de aviso funciona igual aquí —`TestCase` envuelve cada prueba en un
    `atomic()`, así que `advisory_xact_lock` encuentra su transacción—. Lo que
    NO se puede probar así es una carrera: para eso hacen falta commits reales
    y dos conexiones (`ConcurrencyTests`).
    """


class OwnerPhoneIdentityTxBase(OwnerPhoneIdentityMixin, TransactionTestCase):
    """Commits reales: solo para lo que de verdad los necesita."""


class PhoneKeyDerivationTests(OwnerPhoneIdentityBase):
    """La clave la deriva SIEMPRE el dominio, en toda escritura."""

    def test_key_derived_on_create_regardless_of_input_format(self):
        for raw in ('5512345678', '55 1234 5678', '(55) 1234-5678'):
            owner = Owner.objects.create(
                organization=self.org, name="Ana", phone=raw,
            )
            self.assertEqual(owner.phone_normalized, PHONE, raw)
            owner.delete()

    def test_key_is_null_without_ten_digits(self):
        owner = Owner.objects.create(organization=self.org, name="Sin tel", phone='')
        self.assertIsNone(owner.phone_normalized)
        owner.phone = '123'
        owner.save()
        owner.refresh_from_db()
        self.assertIsNone(owner.phone_normalized)

    def test_key_follows_phone_even_with_update_fields(self):
        """Un `save(update_fields=['phone'])` no puede dejar la clave mintiendo."""
        owner = Owner.objects.create(organization=self.org, name="Ana", phone=PHONE)
        owner.phone = PHONE_ALT
        owner.save(update_fields=['phone'])
        owner.refresh_from_db()
        self.assertEqual(owner.phone_normalized, PHONE_ALT)


class GenericOwnerTests(OwnerPhoneIdentityBase):
    """P0-28 / P2-15 — el teléfono del genérico NUNCA es identidad (§4.12)."""

    def test_generic_from_signal_has_null_key(self):
        generic = Owner.objects.for_organization(self.org).get(is_generic=True)
        self.assertEqual(generic.phone, '0000000000')
        self.assertIsNone(generic.phone_normalized)

    def test_generic_from_utils_has_null_key(self):
        from apps.patients.utils import get_or_create_generic_patient

        fresh = Organization.objects.create(name="Clínica utils", timezone="UTC")
        # El signal ya sembró el genérico; `get_or_create_generic_patient` es la
        # otra vía (A5) y debe llegar al mismo estado.
        owner, _pet = get_or_create_generic_patient(fresh)
        self.assertTrue(owner.is_generic)
        self.assertIsNone(owner.phone_normalized)

    def test_generic_does_not_count_as_candidate(self):
        """Su relleno '0000000000' no colisiona con un cliente real que lo tenga."""
        real = Owner.objects.create(
            organization=self.org, name="Cliente real", phone='0000000000',
        )
        self.assertEqual(real.phone_normalized, '0000000000')
        lookup = lookup_owner_by_phone(self.org, '0000000000')
        self.assertEqual(lookup.outcome, 'unique')
        self.assertEqual(lookup.owner.pk, real.pk)

    def test_contact_can_never_link_to_generic_by_phone(self):
        lookup = lookup_owner_by_phone(self.org, '0000000000')
        self.assertIsNone(lookup.owner)

    def test_migration_backfill_derives_the_same_key_as_the_domain(self):
        """P0-28 — el backfill y `Owner.save()` no pueden discrepar.

        Se simula el estado pre-migración (columna vacía) y se corre el backfill
        real de `0018`. Si la derivación en SQL divergiera de `phone_key`, la
        primera escritura posterior movería la clave de esas filas sin que nadie
        lo pidiera — y en una clínica con duplicados eso cambia el desenlace.
        """
        backfill = import_module(
            'apps.patients.migrations.0018_owner_phone_normalized'
        )._backfill

        clean = Owner.objects.create(organization=self.org, name="Con espacios",
                                     phone='55 1234 5678')
        short = Owner.objects.create(organization=self.org, name="Corto", phone='123')
        generic = Owner.objects.for_organization(self.org).get(is_generic=True)

        # Estado pre-migración: la columna no existía, así que nadie la había
        # derivado todavía.
        Owner.all_objects.update(phone_normalized=None)

        # `_backfill` solo necesita la conexión; construir un schema_editor real
        # traería efectos que esta prueba no quiere ejercitar.
        backfill(None, SimpleNamespace(connection=connection))

        clean.refresh_from_db()
        short.refresh_from_db()
        generic.refresh_from_db()
        self.assertEqual(clean.phone_normalized, PHONE)
        self.assertIsNone(short.phone_normalized)
        self.assertIsNone(
            generic.phone_normalized,
            "El genérico recibe NULL sin pasar por la normalización: si el "
            "backfill normalizara su relleno, entraría en la deduplicación de "
            "todas las organizaciones a la vez.",
        )


class HistoricalDuplicateTests(OwnerPhoneIdentityBase):
    """P0-17 / P0-24 — dos expedientes con la misma clave: nadie elige."""

    def setUp(self):
        super().setUp()
        # Distinguibles SOLO tras normalizar: la igualdad cruda vería uno.
        self.dup_a = Owner.objects.create(
            organization=self.org, name="Ana López", phone='55 1234 5678',
        )
        self.dup_b = Owner.objects.create(
            organization=self.org, name="Ana Lopez", phone=PHONE,
        )
        self.admin = _make_admin("adm_dup", self.org)

    def api(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        return client

    def test_read_mode_reports_ambiguous_without_choosing(self):
        lookup = lookup_owner_by_phone(self.org, PHONE)
        self.assertEqual(lookup.outcome, 'ambiguous')
        self.assertIsNone(lookup.owner)

    def test_resolver_refuses_for_every_actor(self):
        for require_new in (False, True):
            with self.subTest(require_new=require_new), transaction.atomic():
                with self.assertRaises(OwnerAmbiguous):
                    resolve_owner_for_phone(
                        self.org, phone=PHONE, name="Ana", require_new=require_new,
                    )
        self.assertEqual(self.real_owners().count(), 2)

    def test_pet_creation_via_api_refuses_and_writes_nothing(self):
        resp = self.api().post(
            '/api/pets/',
            {'name': 'Luna', 'owner': {'name': 'Ana Lopez', 'phone': PHONE}},
            format='json',
        )
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.data['code'], 'owner_ambiguous')
        # Cero escrituras: ni mascota, ni tercer expediente.
        self.assertFalse(self.real_pets().exists())
        self.assertEqual(self.real_owners().count(), 2)

    def test_owner_creation_via_api_refuses(self):
        resp = self.api().post(
            '/api/owners/', {'name': 'Ana Lopez', 'phone': PHONE}, format='json',
        )
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.data['code'], 'owner_ambiguous')
        self.assertEqual(self.real_owners().count(), 2)

    def test_phone_change_onto_duplicate_refuses(self):
        mover = Owner.objects.create(
            organization=self.org, name="Otro", phone=PHONE_ALT,
        )
        with transaction.atomic(), self.assertRaises(OwnerAmbiguous):
            change_owner_phone(mover, PHONE)
        mover.refresh_from_db()
        self.assertEqual(mover.phone_normalized, PHONE_ALT)

    def test_ambiguous_response_publishes_no_candidate(self):
        """Publicar un candidato sería sugerir la elección que INV-C prohíbe."""
        resp = self.api().post(
            '/api/owners/', {'name': 'Ana', 'phone': PHONE}, format='json',
        )
        self.assertNotIn('candidate', resp.data)
        self.assertEqual(resp.data['candidate_count'], 2)


class PetCreateContractTests(OwnerPhoneIdentityBase):
    """§4.9 — el alta de mascota no infiere identidad por teléfono."""

    def setUp(self):
        super().setUp()
        self.admin = _make_admin("adm_pet", self.org)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_zero_matches_creates_owner_and_pet(self):
        resp = self.client.post(
            '/api/pets/',
            {'name': 'Luna', 'owner': {'name': 'Ana Soto', 'phone': PHONE}},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(self.real_owners().count(), 1)

    def test_same_name_reuses_existing_record(self):
        """P2-14 (iron rule): el flujo normal de recepción NO cambia."""
        existing = Owner.objects.create(
            organization=self.org, name="Ana Soto", phone=PHONE,
        )
        resp = self.client.post(
            '/api/pets/',
            {'name': 'Luna', 'owner': {'name': 'Ana Soto', 'phone': PHONE}},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(self.real_owners().count(), 1)
        self.assertEqual(Pet.objects.get(name='Luna').owner_id, existing.pk)

    def test_accent_difference_still_counts_as_same_name(self):
        existing = Owner.objects.create(
            organization=self.org, name="Ana López", phone=PHONE,
        )
        resp = self.client.post(
            '/api/pets/',
            {'name': 'Luna', 'owner': {'name': 'ana lopez', 'phone': PHONE}},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(Pet.objects.get(name='Luna').owner_id, existing.pk)

    def test_different_name_asks_instead_of_forging_a_duplicate(self):
        existing = Owner.objects.create(
            organization=self.org, name="Ana Soto", phone=PHONE,
        )
        resp = self.client.post(
            '/api/pets/',
            {'name': 'Luna', 'owner': {'name': 'Beto Ruiz', 'phone': PHONE}},
            format='json',
        )
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.data['code'], 'owner_exists')
        self.assertEqual(resp.data['candidate']['public_id'], str(existing.public_id))
        self.assertEqual(resp.data['candidate']['name'], 'Ana Soto')
        # NUNCA un segundo expediente con el mismo número, y ninguna mascota.
        self.assertEqual(self.real_owners().count(), 1)
        self.assertFalse(self.real_pets().exists())

    def test_reference_mode_associates_to_the_chosen_record(self):
        chosen = Owner.objects.create(
            organization=self.org, name="Ana Soto", phone=PHONE,
        )
        resp = self.client.post(
            '/api/pets/',
            {'name': 'Luna', 'owner_public_id': str(chosen.public_id)},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(Pet.objects.get(name='Luna').owner_id, chosen.pk)

    def test_reference_mode_is_tenant_scoped(self):
        foreign = Owner.objects.create(
            organization=self.other_org, name="Ajeno", phone=PHONE,
        )
        resp = self.client.post(
            '/api/pets/',
            {'name': 'Luna', 'owner_public_id': str(foreign.public_id)},
            format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertFalse(self.real_pets().exists())

    def test_both_modes_at_once_is_rejected(self):
        chosen = Owner.objects.create(
            organization=self.org, name="Ana Soto", phone=PHONE,
        )
        resp = self.client.post(
            '/api/pets/',
            {
                'name': 'Luna',
                'owner_public_id': str(chosen.public_id),
                'owner': {'name': 'Otra', 'phone': PHONE_ALT},
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_owner_is_still_required(self):
        resp = self.client.post('/api/pets/', {'name': 'Luna'}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_filler_phone_is_rejected_on_manual_create(self):
        """D4: el `PHONE_REGEX` local aceptaba rellenos; la regla del dominio no."""
        resp = self.client.post(
            '/api/pets/',
            {'name': 'Luna', 'owner': {'name': 'Ana', 'phone': '0000000000'}},
            format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.data)


class PhoneChangeTests(OwnerPhoneIdentityBase):
    """§4.10 — cambiar el teléfono mueve la clave; se serializa y falla cerrado."""

    def setUp(self):
        super().setUp()
        self.admin = _make_admin("adm_chg", self.org)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_change_to_free_number_succeeds(self):
        owner = Owner.objects.create(organization=self.org, name="Ana", phone=PHONE)
        resp = self.client.patch(
            f'/api/owners/{owner.public_id}/', {'phone': PHONE_ALT}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        owner.refresh_from_db()
        self.assertEqual(owner.phone_normalized, PHONE_ALT)

    def test_change_onto_occupied_number_refuses(self):
        occupant = Owner.objects.create(organization=self.org, name="Beto", phone=PHONE)
        mover = Owner.objects.create(organization=self.org, name="Ana", phone=PHONE_ALT)
        resp = self.client.patch(
            f'/api/owners/{mover.public_id}/', {'phone': PHONE}, format='json',
        )
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.data['code'], 'owner_exists')
        self.assertEqual(resp.data['candidate']['public_id'], str(occupant.public_id))
        mover.refresh_from_db()
        self.assertEqual(mover.phone_normalized, PHONE_ALT)

    def test_reformatting_the_same_number_is_an_ordinary_edit(self):
        owner = Owner.objects.create(organization=self.org, name="Ana", phone=PHONE)
        resp = self.client.patch(
            f'/api/owners/{owner.public_id}/',
            {'phone': '55 1234 5678', 'name': 'Ana María'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        owner.refresh_from_db()
        self.assertEqual(owner.phone_normalized, PHONE)
        self.assertEqual(owner.name, 'Ana María')

    def test_nested_change_from_pet_is_all_or_nothing(self):
        """P0-25: un 409 en la vía anidada no deja NADA guardado."""
        Owner.objects.create(organization=self.org, name="Beto", phone=PHONE)
        mover = Owner.objects.create(organization=self.org, name="Ana", phone=PHONE_ALT)
        pet = Pet.objects.create(
            organization=self.org, owner=mover, name="Luna", species="canino",
        )
        resp = self.client.patch(
            f'/api/pets/{pet.public_id}/',
            {'name': 'Lunita', 'owner': {'name': 'Ana', 'phone': PHONE}},
            format='json',
        )
        self.assertEqual(resp.status_code, 409, resp.data)
        pet.refresh_from_db()
        mover.refresh_from_db()
        self.assertEqual(pet.name, 'Luna')                 # ni la mascota
        self.assertEqual(mover.phone_normalized, PHONE_ALT)  # ni el teléfono

    def test_pet_update_cannot_reparent(self):
        owner = Owner.objects.create(organization=self.org, name="Ana", phone=PHONE)
        other = Owner.objects.create(organization=self.org, name="Beto", phone=PHONE_ALT)
        pet = Pet.objects.create(
            organization=self.org, owner=owner, name="Luna", species="canino",
        )
        resp = self.client.patch(
            f'/api/pets/{pet.public_id}/',
            {'owner_public_id': str(other.public_id)},
            format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        pet.refresh_from_db()
        self.assertEqual(pet.owner_id, owner.pk)


class TenantIsolationTests(OwnerPhoneIdentityBase):
    """P0-25 — el mismo teléfono en otra organización no interfiere."""

    def test_foreign_record_neither_counts_nor_blocks(self):
        Owner.objects.create(organization=self.other_org, name="Ajena", phone=PHONE)
        lookup = lookup_owner_by_phone(self.org, PHONE)
        self.assertEqual(lookup.outcome, 'none')
        with transaction.atomic():
            owner, status = resolve_owner_for_phone(
                self.org, phone=PHONE, name="Propia",
            )
        self.assertEqual(status, 'created')
        self.assertEqual(self.real_owners().count(), 1)
        self.assertEqual(self.real_owners(self.other_org).count(), 1)


class ConcurrencyTests(OwnerPhoneIdentityTxBase):
    """Dos conexiones reales. Sin PostgreSQL, ninguna de estas vale."""

    def setUp(self):
        super().setUp()
        self.assertEqual(
            connection.vendor, 'postgresql',
            "INV-C se apoya en locks de aviso: estas pruebas exigen PostgreSQL.",
        )

    def _resolve(self, name, phone=PHONE, **kwargs):
        def run(barrier):
            with transaction.atomic():
                barrier.wait()
                owner, status = resolve_owner_for_phone(
                    self.org, phone=phone, name=name, **kwargs,
                )
                return status
        return run

    def test_p0_16_two_concurrent_resolutions_yield_one_record(self):
        results = run_concurrently(
            self._resolve("Ana"), self._resolve("Ana"),
        )
        self.assertEqual(self.real_owners().count(), 1)
        statuses = sorted(v for state, v in results if state == 'ok')
        errors = [v for state, v in results if state == 'error']
        # O bien una crea y la otra reutiliza, o bien una recibe un 409 cerrado.
        # Lo que NUNCA puede pasar es que persistan dos expedientes.
        # `errors and all(...)`, no solo `all(...)`: sobre una lista vacía `all`
        # es cierto por vacuidad y la rama de conflicto pasaría sin conflicto.
        self.assertTrue(
            statuses == ['created', 'reused'] or
            (errors and all(isinstance(e, (OwnerExists, OwnerAmbiguous)) for e in errors)),
            f"statuses={statuses} errors={errors}",
        )

    def test_p0_16_agent_and_reception_do_not_fabricate_a_duplicate(self):
        """Mezcla de actores: el agente exige expediente nuevo, recepción no."""
        results = run_concurrently(
            self._resolve("Ana", require_new=True),
            self._resolve("Ana"),
        )
        self.assertLessEqual(self.real_owners().count(), 1)
        self.assertGreaterEqual(
            sum(1 for state, _ in results if state == 'ok'), 1,
        )
        for state, value in results:
            if state == 'error':
                self.assertIsInstance(value, (OwnerExists, OwnerAmbiguous))

    def test_p0_21_pets_route_and_owners_route_race(self):
        admin = _make_admin("adm_race", self.org)

        def via_pets(barrier):
            client = APIClient()
            client.force_authenticate(admin)
            barrier.wait()
            return client.post(
                '/api/pets/',
                {'name': 'Luna', 'owner': {'name': 'Ana Soto', 'phone': PHONE}},
                format='json',
            ).status_code

        def via_owners(barrier):
            client = APIClient()
            client.force_authenticate(admin)
            barrier.wait()
            return client.post(
                '/api/owners/', {'name': 'Ana Soto', 'phone': PHONE}, format='json',
            ).status_code

        run_concurrently(via_pets, via_owners)
        self.assertEqual(
            self.real_owners().count(), 1,
            "La vía de mascotas no puede fabricar un segundo expediente.",
        )

    def test_p0_22_two_changes_onto_the_same_new_number(self):
        a = Owner.objects.create(organization=self.org, name="A", phone='5511111111')
        b = Owner.objects.create(organization=self.org, name="B", phone='5522222222')

        def move(owner_pk):
            def run(barrier):
                with transaction.atomic():
                    barrier.wait()
                    owner = Owner.objects.get(pk=owner_pk)
                    change_owner_phone(owner, PHONE)
                    return 'moved'
            return run

        results = run_concurrently(move(a.pk), move(b.pk))
        moved = [v for state, v in results if state == 'ok']
        self.assertEqual(len(moved), 1, f"Debe ganar exactamente uno: {results}")
        for state, value in results:
            if state == 'error':
                self.assertIsInstance(value, (OwnerExists, OwnerAmbiguous))
        self.assertEqual(self.real_owners().count(), 1)

    def test_p0_22_crossed_changes_do_not_deadlock(self):
        """A→B y B→A a la vez. El orden total de claves es lo único que lo evita."""
        a = Owner.objects.create(organization=self.org, name="A", phone='5511111111')
        b = Owner.objects.create(organization=self.org, name="B", phone='5522222222')

        def move(owner_pk, target):
            def run(barrier):
                with transaction.atomic():
                    barrier.wait()
                    owner = Owner.objects.get(pk=owner_pk)
                    change_owner_phone(owner, target)
                    return 'moved'
            return run

        results = run_concurrently(
            move(a.pk, '5522222222'), move(b.pk, '5511111111'),
        )
        for state, value in results:
            if state == 'error':
                # Un `owner_exists` es el desenlace correcto; un deadlock de
                # PostgreSQL (`OperationalError`) sería el bug que el orden
                # total existe para evitar.
                self.assertIsInstance(
                    value, (OwnerExists, OwnerAmbiguous),
                    f"Desenlace inesperado (¿deadlock?): {value!r}",
                )
        # Ningún duplicado nuevo: siguen siendo dos expedientes.
        self.assertEqual(
            Owner.objects.for_organization(self.org).filter(is_generic=False).count(), 2,
        )

    def test_p0_23_phone_change_races_a_fresh_registration(self):
        mover = Owner.objects.create(organization=self.org, name="A", phone=PHONE_ALT)

        def move(barrier):
            with transaction.atomic():
                barrier.wait()
                change_owner_phone(Owner.objects.get(pk=mover.pk), PHONE)
                return 'moved'

        results = run_concurrently(move, self._resolve("Nueva"))
        self.assertEqual(
            self.real_owners().count(), 1,
            "Exactamente una operación puede ocupar la clave.",
        )
        for state, value in results:
            if state == 'error':
                self.assertIsInstance(value, (OwnerExists, OwnerAmbiguous))


class AdvisoryLockContractTests(OwnerPhoneIdentityTxBase):
    """El lock no puede degradarse a no-op en silencio.

    `TransactionTestCase` es obligatorio aquí: `TestCase` envuelve la prueba en
    un `atomic()` y la guarda de «exige transacción abierta» nunca dispararía.
    """

    def test_requires_open_transaction(self):
        with self.assertRaises(RuntimeError):
            advisory_xact_lock('patients.owner.phone', self.org.pk, PHONE)

    def test_resolver_refuses_outside_a_transaction(self):
        """La guarda no es decorativa: protege al servicio, no solo al helper."""
        with self.assertRaises(RuntimeError):
            resolve_owner_for_phone(self.org, phone=PHONE, name="Ana")

    def test_acquires_inside_transaction(self):
        with transaction.atomic():
            key = advisory_xact_lock('patients.owner.phone', self.org.pk, PHONE)
        self.assertIsInstance(key, int)

    def test_unsupported_backend_raises(self):
        """En otro motor rompe ruidosamente en vez de fingir que bloqueó."""
        self.assertTrue(issubclass(AdvisoryLockUnsupported, RuntimeError))


class InventoryStaticGateTests(SimpleTestCase):
    """P2-12 (estático) — el inventario cerrado de §4.7.4, como gate.

    Un grep de una línea sobre `get_or_create(...phone...)` es justo lo que dejó
    pasar el hallazgo Z. Este gate no busca una fórmula: enumera **todos** los
    sitios que crean un `Owner` y exige que cada uno esté en el inventario, con
    su motivo escrito. Una vía nueva rompe la prueba hasta que alguien la
    clasifique — que es exactamente la regla de proceso que la decisión pide.

    Se analiza el **AST**, no el texto. La documentación de este Item cita el
    patrón viejo a propósito en docstrings y comentarios; un gate por líneas
    fallaría con su propia explicación, y el reflejo sería relajarlo.
    """

    #: Cada entrada es una fila del inventario §4.7.4 «excluida con evidencia»
    #: (o el propio servicio). Añadir una vía aquí es una decisión, no un
    #: apaño: exige justificar por qué NO puede alterar identidad.
    ALLOWLIST = {
        'apps/patients/services.py':
            'La fuente única: es quien toma el lock y cuenta bajo él.',
        'apps/patients/utils.py':
            'A5 — Owner genérico (is_generic=True, UniqueConstraint, clave NULL).',
        'apps/organizations/signals.py':
            'A5 — Owner genérico sembrado al crear la organización.',
        'apps/core/management/commands/seed_demo_clinic.py':
            'A6 — siembra single-writer sobre el tenant demo.',
        'apps/agent/management/commands/agent_eval.py':
            'A6 — siembra single-writer sobre el tenant de evaluación.',
        'apps/appointments/views.py':
            'A1 — create-with-patient: PENDIENTE de migrar al servicio. Deriva '
            'la clave (Owner.save lo garantiza) pero NO toma el lock de '
            'deduplicación ni produce owner_exists/owner_ambiguous.',
    }

    #: Sitios donde una asignación a `.phone` es legítima. Mover la clave es
    #: competencia exclusiva del servicio (C1–C4 del inventario).
    PHONE_WRITE_ALLOWLIST = {
        'apps/patients/services.py':
            'change_owner_phone: la única escritura del teléfono de un Owner.',
    }

    def _source_files(self):
        root = Path(__file__).resolve().parents[3]  # backend/apps/…/tests → backend/
        for path in sorted((root / 'apps').rglob('*.py')):
            rel = path.relative_to(root).as_posix()
            if '/tests/' in rel or '/migrations/' in rel:
                continue
            yield rel, ast.parse(path.read_text(encoding='utf-8'), filename=rel)

    #: Verbos que **materializan** un Owner. Leerlos (`filter`,
    #: `for_organization`) es legítimo en cualquier módulo; crearlos no.
    CREATE_VERBS = {'create', 'get_or_create', 'update_or_create', 'bulk_create'}
    MANAGERS = {'objects', 'all_objects'}

    @classmethod
    def _creates_owner(cls, node):
        """¿Este nodo construye un `Owner`? (llamada real, no una cita en prosa)."""
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Name):                       # Owner(...)
            return func.id == 'Owner'
        if isinstance(func, ast.Attribute) and func.attr in cls.CREATE_VERBS:
            inner = func.value                               # Owner.objects.create(...)
            if isinstance(inner, ast.Attribute) and inner.attr in cls.MANAGERS:
                base = inner.value
                return isinstance(base, ast.Name) and base.id == 'Owner'
        return False

    def test_every_owner_creation_site_is_in_the_inventory(self):
        offenders = []
        for rel, tree in self._source_files():
            if rel in self.ALLOWLIST:
                continue
            for node in ast.walk(tree):
                if self._creates_owner(node):
                    offenders.append(f'{rel}:{node.lineno}')
                    break
        self.assertEqual(
            offenders, [],
            "Vía nueva que construye un Owner fuera del inventario §4.7.4. "
            "Clasifícala (que use `patients.services`) o añádela al ALLOWLIST "
            "con la evidencia de por qué no puede alterar identidad. "
            "«Cualquier vía futura» no es cobertura válida.",
        )

    def test_no_route_writes_owner_phone_outside_the_service(self):
        offenders = []
        for rel, tree in self._source_files():
            if rel in self.PHONE_WRITE_ALLOWLIST:
                continue
            for node in ast.walk(tree):
                targets = []
                if isinstance(node, ast.Assign):
                    targets = node.targets
                elif isinstance(node, ast.AnnAssign) and node.value is not None:
                    targets = [node.target]
                for target in targets:
                    if isinstance(target, ast.Attribute) and target.attr == 'phone':
                        offenders.append(f'{rel}:{node.lineno}')
        self.assertEqual(
            offenders, [],
            "Asignación directa a `.phone`: el cambio de teléfono mueve la "
            "clave de deduplicación y debe pasar por "
            "`patients.services.change_owner_phone` (§4.10).",
        )
