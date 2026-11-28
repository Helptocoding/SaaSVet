"""INV-L (ADR p70 D2): agente encendido ⇒ teléfono de la clínica válido.

Se prueba desde los dos lados que escriben:

- `Organization.save()`: un teléfono válido solo cambia por otro válido, y se
  compara contra el valor PERSISTIDO bajo bloqueo, no contra la instancia.
- `AgentSettings.save()`: encender exige un teléfono válido leído bajo el mismo
  bloqueo de la fila de la organización.

Las pruebas de concurrencia fuerzan los dos órdenes posibles (la primera
transacción se detiene dentro de su sección crítica, la segunda espera el
bloqueo en `pg_stat_activity`) y verifican el estado final en PostgreSQL. El gate
estático impide escrituras masivas que eviten `save()`.
"""
import ast
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase

from apps.agent.models import AgentSettings
from apps.core.models import set_current_user
from apps.core.validators import is_valid_mx_phone
from apps.organizations import models as org_models
from apps.organizations.models import Organization

VALID = '5512345678'
OTHER_VALID = '5587654321'


def invariant_violations():
    """Configuraciones encendidas cuya clínica no tiene teléfono válido."""
    return [
        settings.pk
        for settings in AgentSettings.objects.filter(enabled=True).select_related('organization')
        if not is_valid_mx_phone(settings.organization.phone or '')
    ]


class OrganizationSideTests(TestCase):
    def test_a_valid_phone_cannot_be_blanked(self):
        org = Organization.objects.create(name='INV-L A', timezone='UTC', phone=VALID)
        org.phone = ''
        with self.assertRaises(ValidationError) as raised:
            org.save()
        self.assertIn('phone', raised.exception.message_dict)
        self.assertEqual(Organization.objects.get(pk=org.pk).phone, VALID)

    def test_a_stale_instance_cannot_blank_a_phone_captured_meanwhile(self):
        org = Organization.objects.create(name='INV-L B', timezone='UTC')
        stale = Organization.objects.get(pk=org.pk)        # leyó phone=''
        fresh = Organization.objects.get(pk=org.pk)
        fresh.phone = VALID
        fresh.save()
        stale.display_name = 'Nombre nuevo'                # reescribiría phone=''
        with self.assertRaises(ValidationError):
            stale.save()
        self.assertEqual(Organization.objects.get(pk=org.pk).phone, VALID)

    def test_an_invalid_phone_is_rejected(self):
        org = Organization.objects.create(name='INV-L C', timezone='UTC')
        org.phone = '5'
        with self.assertRaises(ValidationError):
            org.save()
        with self.assertRaises(ValidationError):
            Organization.objects.create(name='INV-L C2', timezone='UTC', phone='1111111111')

    def test_valid_to_valid_and_blank_to_blank_are_allowed(self):
        org = Organization.objects.create(name='INV-L D', timezone='UTC')
        org.display_name = 'Sin teléfono todavía'
        org.save()
        org.phone = VALID
        org.save()
        org.phone = OTHER_VALID
        org.save()
        self.assertEqual(Organization.objects.get(pk=org.pk).phone, OTHER_VALID)

    def test_a_write_that_excludes_the_phone_does_not_touch_it(self):
        org = Organization.objects.create(name='INV-L E', timezone='UTC', phone=VALID)
        org.phone = ''                                      # solo en memoria
        org.display_name = 'Otro'
        org.save(update_fields=['display_name'])
        self.assertEqual(Organization.objects.get(pk=org.pk).phone, VALID)


class AgentSideTests(TestCase):
    def test_enabling_without_a_phone_is_rejected(self):
        org = Organization.objects.create(name='INV-L F', timezone='UTC')
        with self.assertRaises(ValidationError) as raised:
            AgentSettings.objects.create(organization=org, enabled=True)
        self.assertIn('enabled', raised.exception.message_dict)
        self.assertFalse(AgentSettings.objects.filter(organization=org).exists())

    def test_enabling_reads_the_persisted_phone_not_the_cached_one(self):
        org = Organization.objects.create(name='INV-L G', timezone='UTC')
        settings = AgentSettings.objects.create(organization=org)
        settings.organization.phone = VALID                 # solo en memoria
        settings.enabled = True
        with self.assertRaises(ValidationError):
            settings.save()
        self.assertFalse(AgentSettings.objects.get(pk=settings.pk).enabled)

    def test_enabling_with_a_legacy_invalid_phone_is_rejected(self):
        org = Organization.objects.create(name='INV-L H', timezone='UTC')
        Organization.objects.filter(pk=org.pk).update(phone='5')  # fila previa a 0016
        settings = AgentSettings.objects.create(organization=org)
        settings.enabled = True
        with self.assertRaises(ValidationError):
            settings.save(update_fields=['enabled'])

    def test_enabling_with_a_valid_phone_works_and_disabling_never_needs_one(self):
        org = Organization.objects.create(name='INV-L I', timezone='UTC', phone=VALID)
        settings = AgentSettings.objects.create(organization=org, enabled=True)
        settings.enabled = False
        settings.save()
        self.assertFalse(AgentSettings.objects.get(pk=settings.pk).enabled)
        self.assertEqual(invariant_violations(), [])

    def test_saving_other_fields_of_an_enabled_agent_skips_the_check(self):
        org = Organization.objects.create(name='INV-L J', timezone='UTC', phone=VALID)
        settings = AgentSettings.objects.create(organization=org, enabled=True)
        settings.nudge_enabled = False
        with mock.patch.object(org_models, 'lock_organization_phone') as lock:
            settings.save(update_fields=['nudge_enabled'])
        lock.assert_not_called()


@unittest.skipUnless(connection.vendor == 'postgresql', 'INV-L se prueba sobre PostgreSQL')
class LockWaitTests(TransactionTestCase):
    """Entrelazado forzado: la primera escritura se detiene con la fila de la
    organización ya bloqueada; la segunda tiene que esperar ese bloqueo."""

    def setUp(self):
        set_current_user(None)

    def _wait_for_a_lock_waiter(self, timeout=10):
        deadline = time.monotonic() + timeout
        with connection.cursor() as cursor:
            while time.monotonic() < deadline:
                cursor.execute(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
                )
                if cursor.fetchone()[0] >= 1:
                    return True
                time.sleep(0.05)
        return False

    def interleave(self, first, second):
        entered, release = threading.Event(), threading.Event()
        claimed = threading.Lock()
        real_lock = org_models.lock_organization_phone

        def held_lock(organization_id):
            phone = real_lock(organization_id)              # el bloqueo ya está tomado
            if claimed.acquire(blocking=False):             # solo se detiene el primero
                entered.set()
                release.wait(timeout=20)
            return phone

        outcomes = {}

        def worker(label, call):
            try:
                call()
                outcomes[label] = 'ok'
            except Exception as exc:  # se clasifica en cada prueba
                outcomes[label] = exc
            finally:
                connection.close()

        with mock.patch.object(org_models, 'lock_organization_phone', held_lock):
            t1 = threading.Thread(target=worker, args=('first', first))
            t2 = threading.Thread(target=worker, args=('second', second))
            try:
                t1.start()
                self.assertTrue(entered.wait(timeout=10), 'la primera no llegó al bloqueo')
                t2.start()
                waited = self._wait_for_a_lock_waiter()
                second_still_running = t2.is_alive()
            finally:
                release.set()
                t1.join(timeout=30)
                t2.join(timeout=30)

        self.assertTrue(waited, 'la segunda transacción no esperó ningún bloqueo')
        self.assertTrue(second_still_running, 'la segunda terminó sin esperar a la primera')
        return outcomes

    def _org(self, phone=''):
        return Organization.objects.create(name='INV-L conc', timezone='UTC', phone=phone)

    def _enable(self, org_id):
        return lambda: AgentSettings.objects.create(
            organization=Organization.objects.get(pk=org_id), enabled=True)

    def _blank_from_a_stale_read(self, stale):
        def call():
            stale.display_name = 'Edición vieja'
            stale.save()
        return call

    def _capture(self, org_id, phone):
        def call():
            org = Organization.objects.get(pk=org_id)
            org.phone = phone
            org.save()
        return call

    def test_enable_first_then_a_stale_blank_waits_and_is_rejected(self):
        org = self._org(VALID)
        stale = Organization.objects.get(pk=org.pk)
        stale.phone = ''
        outcomes = self.interleave(self._enable(org.pk), self._blank_from_a_stale_read(stale))
        self.assertEqual(outcomes['first'], 'ok')
        self.assertIsInstance(outcomes['second'], ValidationError)
        self.assertEqual(Organization.objects.get(pk=org.pk).phone, VALID)
        self.assertTrue(AgentSettings.objects.get(organization=org).enabled)
        self.assertEqual(invariant_violations(), [])

    def test_stale_blank_first_is_rejected_and_the_enable_proceeds(self):
        org = self._org(VALID)
        stale = Organization.objects.get(pk=org.pk)
        stale.phone = ''
        outcomes = self.interleave(self._blank_from_a_stale_read(stale), self._enable(org.pk))
        self.assertIsInstance(outcomes['first'], ValidationError)
        self.assertEqual(outcomes['second'], 'ok')
        self.assertEqual(Organization.objects.get(pk=org.pk).phone, VALID)
        self.assertEqual(invariant_violations(), [])

    def test_capturing_the_phone_first_lets_the_waiting_enable_succeed(self):
        org = self._org('')
        outcomes = self.interleave(self._capture(org.pk, VALID), self._enable(org.pk))
        self.assertEqual(outcomes, {'first': 'ok', 'second': 'ok'})
        self.assertTrue(AgentSettings.objects.get(organization=org).enabled)
        self.assertEqual(invariant_violations(), [])

    def test_enabling_first_without_a_phone_is_rejected_while_the_capture_waits(self):
        org = self._org('')
        outcomes = self.interleave(self._enable(org.pk), self._capture(org.pk, VALID))
        self.assertIsInstance(outcomes['first'], ValidationError)
        self.assertEqual(outcomes['second'], 'ok')
        self.assertFalse(AgentSettings.objects.filter(organization=org, enabled=True).exists())
        self.assertEqual(Organization.objects.get(pk=org.pk).phone, VALID)
        self.assertEqual(invariant_violations(), [])

    def test_the_lock_helper_requires_an_open_transaction(self):
        org = self._org(VALID)
        with self.assertRaises(RuntimeError):
            org_models.lock_organization_phone(org.pk)
        with transaction.atomic():
            self.assertEqual(org_models.lock_organization_phone(org.pk), VALID)


class NoBulkWritesGateTests(TestCase):
    """Ninguna escritura masiva de código productivo evita los `save()` de INV-L.

    Busca llamadas `.update(...)`/`.bulk_update(...)` cuya cadena empieza en
    `Organization` con el campo `phone`, o en `AgentSettings` con `enabled`. Las
    migraciones (normalizan con el modelo histórico) y las pruebas quedan fuera.
    """

    GUARDED = {'Organization': 'phone', 'AgentSettings': 'enabled'}

    def _root_name(self, node):
        while isinstance(node, (ast.Attribute, ast.Call, ast.Subscript)):
            node = node.func if isinstance(node, ast.Call) else node.value
        return node.id if isinstance(node, ast.Name) else None

    def _writes_field(self, call, field):
        if any(keyword.arg == field for keyword in call.keywords):
            return True
        if call.func.attr != 'bulk_update':
            return False
        field_lists = list(call.args[1:]) + [k.value for k in call.keywords if k.arg == 'fields']
        for argument in field_lists:
            if not isinstance(argument, (ast.List, ast.Tuple)):
                return True                                  # campos dinámicos: se revisa a mano
            if field in ast.literal_eval(argument):
                return True
        return False

    def test_no_bulk_write_bypasses_the_invariant(self):
        apps_root = Path(__file__).resolve().parents[2]
        offenders = []
        for path in apps_root.rglob('*.py'):
            parts = set(path.parts)
            if 'tests' in parts or 'migrations' in parts:
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in ('update', 'bulk_update')):
                    continue
                root = self._root_name(node.func.value)
                field = self.GUARDED.get(root)
                if field and self._writes_field(node, field):
                    offenders.append(f'{path.relative_to(apps_root)}:{node.lineno}')
        self.assertEqual(offenders, [], 'escrituras masivas que evitan INV-L')
