"""Fase 7 (audit run-1): endurecimiento operativo que un test debe sostener.

Los scripts se EJECUTAN contra un `docker` falso que registra sus argumentos:
leer el texto no probaría que un simulacro aborta sin postgres, ni que un dump
nace sin permisos para grupo y otros.
"""
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from unittest import skipUnless

from django.conf import settings
from django.test import SimpleTestCase
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.core.tests.test_day6_invariants import _make_admin
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet

REPO_ROOT = Path(__file__).resolve().parents[4]
BASH = shutil.which('bash')

FAKE_DOCKER = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$DOCKER_LOG"
case "$*" in
  *pg_isready*) exit "${PG_ISREADY_EXIT:-0}" ;;
  *pg_dump*) head -c 4096 /dev/zero ;;
  *'pg_restore --list'*) cat >/dev/null; echo '1; 0 0 TABLE public demo' ;;
  *pg_restore*) cat >/dev/null ;;
  *psql*) echo "${PSQL_VALUE:-0}" ;;
esac
exit 0
"""


class ScriptSandbox:
    """Directorio con env, compose y `docker` falsos. Nada toca Docker real."""

    def __init__(self, test):
        folder = tempfile.TemporaryDirectory(prefix='phase7-')
        test.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.log = self.root / 'docker.log'
        self.log.write_text('')
        self.backups = self.root / 'backups'
        (self.root / '.env.prod').write_text(
            'POSTGRES_USER=u\nPOSTGRES_DB=live\nPOSTGRES_PASSWORD=p\nENVIRONMENT=development\n')
        (self.root / 'docker-compose.prod.yml').write_text('services: {}\n')
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        fake = bin_dir / 'docker'
        fake.write_text(FAKE_DOCKER)
        fake.chmod(0o755)
        self.env = {
            **os.environ,
            'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}',
            'DOCKER_LOG': str(self.log),
            'BACKUP_DIR': str(self.backups),
            'COMPOSE_DIR': str(self.root),
            'ENV_FILE': str(self.root / '.env.prod'),
            'COMPOSE_FILE': str(self.root / 'docker-compose.prod.yml'),
        }

    def run(self, script, *args, umask='022', **env):
        command = f'umask {umask}; exec bash "$0" "$@"'
        return subprocess.run(
            [BASH, '-c', command, (REPO_ROOT / 'scripts' / script).as_posix(), *args],
            env={**self.env, **env}, capture_output=True, text=True, timeout=120)

    def calls(self):
        return self.log.read_text().splitlines()


@skipUnless(os.name == 'posix' and BASH, 'Requires POSIX bash and file modes')
class RestoreDrillDoesNotTouchServices(SimpleTestCase):
    def _dump(self, box):
        box.backups.mkdir(mode=0o700)
        dump = box.backups / 'vet-20260101T000000Z.dump'
        dump.write_bytes(b'x' * 2048)
        return dump

    def test_aborts_without_starting_anything_when_postgres_is_down(self):
        box = ScriptSandbox(self)
        self._dump(box)
        result = box.run('restore-drill.sh', PG_ISREADY_EXIT='1')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('postgres is not available', result.stderr)
        self.assertEqual(len(box.calls()), 1, 'Only the availability probe may run')
        self.assertIn('pg_isready', box.calls()[0])

    def test_audits_run_without_dependencies_when_postgres_is_up(self):
        box = ScriptSandbox(self)
        self._dump(box)
        result = box.run('restore-drill.sh')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        runs = [call for call in box.calls() if ' run ' in f' {call} ']
        self.assertEqual(len(runs), 2)
        for call in runs:
            self.assertIn('--no-deps', call)
        self.assertFalse([call for call in box.calls() if re.search(r'\b(up|start)\b', call)])
        self.assertIn('RESTORE VERIFIED', result.stdout)

    def test_failed_health_check_keeps_its_exit_code(self):
        box = ScriptSandbox(self)
        self._dump(box)
        result = box.run('restore-drill.sh', PSQL_VALUE='7')
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn('DROP DATABASE', '\n'.join(box.calls()))

    def test_plain_dump_restore_reports_success(self):
        """Regresión: el trap de limpieza convertía todo éxito en exit 1."""
        box = ScriptSandbox(self)
        dump = self._dump(box)
        result = box.run('pg-restore.sh', str(dump), 'vet_restore_test')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


@skipUnless(os.name == 'posix' and BASH, 'Requires POSIX bash and file modes')
class BackupFilesAreNotReadableByOthers(SimpleTestCase):
    def _assert_private(self, box):
        artifacts = list(box.backups.iterdir())
        self.assertTrue(artifacts)
        self.assertEqual(stat.S_IMODE(box.backups.stat().st_mode), 0o700)
        for artifact in artifacts:
            self.assertEqual(stat.S_IMODE(artifact.stat().st_mode), 0o600, artifact.name)

    def test_nightly_backup_under_a_permissive_umask(self):
        box = ScriptSandbox(self)
        result = box.run('pg-backup.sh', umask='000')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self._assert_private(box)

    def test_existing_open_directory_is_closed_before_writing(self):
        box = ScriptSandbox(self)
        box.backups.mkdir()
        box.backups.chmod(0o755)
        result = box.run('pg-backup.sh')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self._assert_private(box)


class OperationalContractGates(SimpleTestCase):
    def _text(self, relative):
        return (REPO_ROOT / relative).read_text(encoding='utf-8')

    def test_umask_precedes_any_file_creation(self):
        for script in ('pg-backup.sh', 'pre-deploy-backup.sh'):
            with self.subTest(script=script):
                body = self._text(f'scripts/{script}')
                self.assertLess(body.index('\numask 077'), body.index('mkdir -p'))
                self.assertNotIn('chmod 700 "$BACKUP_DIR" 2>/dev/null || true', body)

    def test_scheduled_jobs_never_start_dependencies(self):
        for relative in ('scripts/crontab.example', 'docs/runbooks/cron-jobs.md'):
            with self.subTest(file=relative):
                body = self._text(relative)
                self.assertNotIn('run --rm backend python', body)
                self.assertIn('run --rm --no-deps backend python', body)

    def test_restore_verification_never_starts_dependencies(self):
        body = self._text('docs/runbooks/RUNBOOK-RESTORE.md')
        self.assertNotIn('run --rm -e DATABASE_URL', body)
        self.assertIn('run --rm --no-deps -e DATABASE_URL', body)

    def test_cleanup_traps_cannot_overwrite_the_exit_status(self):
        for script in ('pg-restore.sh', 'restore-drill.sh'):
            with self.subTest(script=script):
                self.assertNotRegex(self._text(f'scripts/{script}'), r'cleanup\(\) \{ \[')

    def test_deploy_keeps_running_release_on_purpose(self):
        self.assertIn('compose run --rm release', self._text('scripts/deploy.sh'))

    def test_csp_allows_blob_only_where_a_consumer_needs_it(self):
        csp = re.search(r'Content-Security-Policy "([^"]+)"', self._text('infra/Caddyfile')).group(1)
        directives = {
            part.split()[0]: part.split()[1:]
            for part in (piece.strip() for piece in csp.split(';')) if part
        }
        self.assertEqual(directives['media-src'], ["'self'", 'blob:'])
        self.assertIn('blob:', directives['img-src'])
        for name, sources in directives.items():
            if name not in {'media-src', 'img-src'}:
                self.assertNotIn('blob:', sources, name)

    def test_inbox_media_is_what_justifies_media_src_blob(self):
        bubble = self._text('frontend/src/pages/inbox/MediaBubble.jsx')
        self.assertIn('<audio', bubble)
        self.assertIn('<video', bubble)


class CiSupplyChainGates(SimpleTestCase):
    def setUp(self):
        self.ci = (REPO_ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')

    def test_every_action_is_pinned_by_full_commit_sha(self):
        uses = re.findall(r'uses:\s*(\S+)', self.ci)
        self.assertTrue(uses)
        for reference in uses:
            with self.subTest(action=reference):
                self.assertRegex(reference, r'^[\w.-]+/[\w.-]+@[0-9a-f]{40}$')

    def test_gitleaks_is_verified_before_it_is_unpacked(self):
        self.assertRegex(self.ci, r'GITLEAKS_SHA256: [0-9a-f]{64}')
        self.assertLess(self.ci.index('sha256sum -c -'), self.ci.index('tar -xzf /tmp/gitleaks.tar.gz'))

    def test_pip_audit_version_is_pinned(self):
        self.assertRegex(self.ci, r'pip install pip-audit==\d+\.\d+\.\d+')


class LegacyIdLookupIsOffByDefault(APITestCase):
    """Sin `override_settings`: es el valor efectivo lo que se está probando."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Org A', timezone='UTC')
        cls.other = Organization.objects.create(name='Org B', timezone='UTC')
        cls.admin = _make_admin('admin_legacy', cls.org)
        cls.pet = cls._pet(cls.org, '5512345678')
        cls.foreign_pet = cls._pet(cls.other, '5598765432')

    @staticmethod
    def _pet(org, phone):
        owner = Owner.objects.create(organization=org, name='Cliente', phone=phone)
        return Pet.objects.create(organization=org, owner=owner, name='Luna',
                                  species='perro', birth_date='2020-01-01')

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_default_is_off_when_the_variable_is_absent(self):
        if 'ALLOW_LEGACY_ID_LOOKUP' in os.environ:
            self.skipTest('Environment overrides the default')
        self.assertIs(settings.ALLOW_LEGACY_ID_LOOKUP, False)

    def test_settings_source_declares_the_closed_default(self):
        source = (REPO_ROOT / 'backend/config/settings.py').read_text(encoding='utf-8')
        self.assertIn("config('ALLOW_LEGACY_ID_LOOKUP', default=False, cast=bool)", source)

    def test_uuid_of_own_record_resolves(self):
        response = self.client.get(f'/api/pets/{self.pet.public_id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_integer_pk_of_own_record_does_not_resolve(self):
        response = self.client.get(f'/api/pets/{self.pet.pk}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_integer_pk_of_other_tenant_does_not_resolve(self):
        response = self.client.get(f'/api/pets/{self.foreign_pet.pk}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_uuid_of_other_tenant_stays_404(self):
        response = self.client.get(f'/api/pets/{self.foreign_pet.public_id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_uuid_query_param_between_resources_still_filters(self):
        response = self.client.get('/api/medical-records/', {'pet': str(self.pet.public_id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class RetiredOrganizationPermissionCodes(SimpleTestCase):
    RETIRED = ('organization.create', 'organization.list')

    def test_absent_from_the_catalog_and_every_explicit_role(self):
        for code in self.RETIRED:
            with self.subTest(code=code):
                self.assertNotIn(code, PERMISSION_CODES)
                for role, codes in PERMISSIONS.items():
                    self.assertNotIn(code, codes, role)

    def test_no_view_service_or_screen_asks_for_them(self):
        this_file = Path(__file__).resolve()
        catalog = REPO_ROOT / 'backend/apps/core/permissions_codes.py'
        pattern = re.compile(r'organization\.(create|list)\b')
        roots = [(REPO_ROOT / 'backend/apps', '*.py'), (REPO_ROOT / 'frontend/src', '*.js'),
                 (REPO_ROOT / 'frontend/src', '*.jsx')]
        offenders = []
        for root, glob in roots:
            for path in root.rglob(glob):
                if path.resolve() in {this_file, catalog} or 'migrations' in path.parts:
                    continue
                if pattern.search(path.read_text(encoding='utf-8', errors='ignore')):
                    offenders.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(offenders, [])

    def test_explicit_role_fallback_does_not_grant_an_unknown_code(self):
        from apps.core.permissions import _is_allowed
        for role in ('VET', 'ASSISTANT'):
            for code in self.RETIRED:
                with self.subTest(role=role, code=code):
                    self.assertFalse(_is_allowed(code, PERMISSIONS[role]))
