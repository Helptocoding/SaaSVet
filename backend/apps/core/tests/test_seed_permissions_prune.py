"""B6 (orden 6): `seed_permissions --prune` retira los códigos que salieron del catálogo.

Sin poda, un código retirado de PERMISSION_CODES seguía en la base y en cualquier rol
propio que lo tuviera. Los roles de sistema ya lo perdían en cada seed.
"""
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from apps.core.models import Permission, Role
from apps.core.permissions_codes import PERMISSION_CODES
from apps.organizations.models import Organization

ORPHAN = 'legacy_module.removed'


def run_seed(*args):
    out = StringIO()
    call_command('seed_permissions', *args, stdout=out)
    return out.getvalue()


def role_codes(role):
    return set(role.permissions.values_list('code', flat=True))


class SeedPermissionsPrune(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Crear la organización ya crea sus roles de sistema (_seed_roles_for_org).
        cls.org = Organization.objects.create(name='Clinica Poda', timezone='UTC')
        cls.orphan = Permission.objects.create(code=ORPHAN)
        listed, _ = Permission.objects.get_or_create(code='appointment.list')
        cls.custom = Role.objects.create(name='RECEPCION_EXTRA', organization=cls.org)
        cls.custom.permissions.set([cls.orphan, listed])
        cls.vet = Role.objects.get(organization=cls.org, name='VET')
        cls.vet.permissions.add(cls.orphan)

    def test_plain_seed_reports_the_orphan_and_keeps_it(self):
        out = run_seed()
        self.assertIn(ORPHAN, out)
        self.assertTrue(Permission.objects.filter(code=ORPHAN).exists())
        self.assertIn(ORPHAN, role_codes(self.custom))
        # El seed ya realinea los roles de sistema con el catálogo.
        self.assertNotIn(ORPHAN, role_codes(self.vet))

    def test_dry_run_prune_lists_without_writing(self):
        out = run_seed('--prune', '--dry-run')
        self.assertIn('Se eliminarían', out)
        self.assertIn(ORPHAN, out)
        self.assertTrue(Permission.objects.filter(code=ORPHAN).exists())
        self.assertIn(ORPHAN, role_codes(self.custom))
        self.assertIn(ORPHAN, role_codes(self.vet))

    def test_prune_deletes_the_orphan_and_its_grants(self):
        run_seed('--prune')
        self.assertFalse(Permission.objects.filter(code=ORPHAN).exists())
        self.assertEqual(role_codes(self.custom), {'appointment.list'})
        self.assertTrue(Role.objects.filter(pk=self.custom.pk).exists())
        missing = set(PERMISSION_CODES) - set(Permission.objects.values_list('code', flat=True))
        self.assertEqual(missing, set())

    def test_prune_is_idempotent(self):
        run_seed('--prune')
        self.assertIn('Permisos podados: 0', run_seed('--prune'))

    def test_prune_never_deletes_wildcards(self):
        Permission.objects.get_or_create(code='*.*')
        Permission.objects.get_or_create(code='invoice.*')
        run_seed('--prune')
        remaining = set(Permission.objects.filter(code__endswith='.*').values_list('code', flat=True))
        self.assertEqual(remaining, {'*.*', 'invoice.*'})

    def test_prune_logs_the_codes(self):
        with self.assertLogs('rbac.events', level='WARNING') as logs:
            run_seed('--prune')
        records = [r for r in logs.records if r.getMessage() == 'SEED_PERMISSIONS_PRUNED']
        self.assertEqual(len(records), 1)
        self.assertIn(ORPHAN, records[0].codes)
        self.assertEqual(records[0].count, len(records[0].codes))


class ReleaseNeverPrunes(SimpleTestCase):
    def test_release_script_does_not_prune(self):
        path = Path(__file__).resolve().parents[3] / 'scripts' / 'release.sh'
        body = [line for line in path.read_text(encoding='utf-8').splitlines()
                if line.strip() and not line.lstrip().startswith('#')]
        self.assertFalse(any('--prune' in line for line in body))
