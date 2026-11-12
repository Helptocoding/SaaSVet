# E04 — B6: `seed_permissions --prune`

Primero lee y aplica `docs/remediaciones/orden-6/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

`seed_permissions` solo añade. Cuando un código sale de `PERMISSION_CODES`, el siguiente seed ya lo quita de los roles de sistema (hace `role.permissions.set(...)`), pero la fila `Permission` sigue en la base y cualquier **rol propio** que la tenga la conserva. Se añade una poda explícita:

- `--prune` borra esas filas y, con ellas, sus concesiones en roles propios.
- `--prune --dry-run` solo las lista.
- Sin `--prune`, el seed solo informa de ellas.
- **Nunca** poda comodines (`*.*`, `recurso.*`). No están en el catálogo, pero los gobierna el preflight de ADR p63 y pueden ser una excepción documentada.
- **Nunca** en `release.sh`. Registra `SEED_PERMISSIONS_PRUNED` en `rbac.events`.

`--dry-run` ya existe (preflight de ADR p63) y no cambia de significado.

## Archivos permitidos

- `backend/apps/core/management/commands/seed_permissions.py`
- `backend/apps/core/tests/test_seed_permissions_prune.py` (nuevo)
- `docs/modules/organizations.md`, `docs/modules/logs.md`
- Expediente del orden 6

## Precondición

1. `grep -n "prune" backend/apps/core/management/commands/seed_permissions.py` no da resultados.
2. `grep -n "prune" backend/scripts/release.sh` no da resultados.
3. Desde `backend/`, `rtk proxy python scripts/orden6_isolated.py test apps.core.tests.test_admin_explicit_grants apps.users.tests.test_agent_identity --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED"` pasa. Anota el `Ran N`.

Si algo no coincide, `BLOQUEADA`.

## Paso 1. Docstring del comando

En `backend/apps/core/management/commands/seed_permissions.py`, sustituye:

```text
Se ejecuta automáticamente en cada deploy (ver Procfile).
```

por:

```text
Se ejecuta automáticamente en cada release (`scripts/release.sh`), sin `--prune`.
```

Y sustituye:

```text
comodín (ADR p63). `--dry-run` muestra esa revisión sin escribir nada.
"""
```

por:

```text
comodín (ADR p63). `--dry-run` muestra esa revisión sin escribir nada.

`--prune` (deuda B6, orden 6) borra los permisos de la base que ya no están en
`PERMISSION_CODES`, y con ellos sus concesiones en roles propios. Solo a mano, en una
ventana de mantenimiento; nunca en `release.sh`. Con `--dry-run` solo los lista. Nunca
poda comodines: los gobierna el preflight de ADR p63 y pueden ser una excepción
documentada.
"""
```

## Paso 2. Imports y logger

1. Debajo de `from django.db.models import F` añade `from django.db import transaction`.
2. Debajo de `logger = logging.getLogger(__name__)` añade `rbac_logger = logging.getLogger("rbac.events")`.

## Paso 3. Argumento

En `add_arguments`, después del `parser.add_argument("--dry-run", ...)` existente, añade:

```python
        parser.add_argument(
            "--prune", action="store_true",
            help="Borra los permisos de la base que ya no están en el catálogo. "
                 "Con --dry-run solo los lista. Nunca borra comodines.",
        )
```

## Paso 4. `handle`

Sustituye el método `handle` completo por:

```python
    def handle(self, *args, **options):
        blockers = self._preflight()
        if blockers:
            raise CommandError(
                "seed_permissions bloqueado, sin cambios:\n  " + "\n  ".join(blockers))
        orphans = self._report_orphans()
        if options["dry_run"]:
            if options["prune"]:
                self.stdout.write(f"  Se eliminarían {len(orphans)} permisos: {orphans}")
            self.stdout.write(self.style.SUCCESS("Preflight limpio. Sin cambios (--dry-run)."))
            return
        self._seed_permissions()
        self._seed_roles()
        if options["prune"]:
            self._prune()
        self.stdout.write(self.style.SUCCESS("seed_permissions completado"))
```

El preflight sigue yendo primero: un seed bloqueado no poda nada.

## Paso 5. Métodos nuevos

Al final de la clase `Command`, después de `_seed_roles`, añade:

```python
    def _orphan_permissions(self):
        # Los comodines (`*.*`, `recurso.*`) nunca están en el catálogo, pero los gobierna
        # el preflight de ADR p63 y pueden ser una excepción documentada: no se podan.
        return Permission.objects.exclude(code__in=PERMISSION_CODES).exclude(code__endswith=".*")

    def _report_orphans(self):
        orphans = sorted(self._orphan_permissions().values_list("code", flat=True))
        if orphans:
            self.stdout.write(f"Permisos fuera del catálogo: {len(orphans)} {orphans}")
        return orphans

    def _prune(self):
        with transaction.atomic():
            orphans = self._orphan_permissions()
            codes = sorted(orphans.values_list("code", flat=True))
            # Borrar el Permission retira también sus filas de Role.permissions.
            orphans.delete()
        rbac_logger.warning("SEED_PERMISSIONS_PRUNED", extra={
            "event": "SEED_PERMISSIONS_PRUNED", "count": len(codes), "codes": codes,
        })
        self.stdout.write(f"  Permisos podados: {len(codes)} {codes}")
```

Comprueba: `python -m py_compile apps/core/management/commands/seed_permissions.py && echo "py_compile OK"` desde `backend/`.

## Paso 6. Pruebas

Crea `backend/apps/core/tests/test_seed_permissions_prune.py`:

```python
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
```

## Paso 7. Documentación

**`docs/modules/organizations.md`.** Sustituye:

```markdown
O simplemente hacer redeploy — el Procfile lo ejecuta automaticamente antes de iniciar el servidor.
```

por:

```markdown
O simplemente hacer redeploy — `scripts/release.sh` lo ejecuta antes de iniciar el servidor.
```

Y justo después del párrafo que empieza por `` Si `seed_permissions` no se ejecuta, todos los endpoints `` añade una línea en blanco y:

~~~markdown
**Poda de permisos retirados (deuda B6, orden 6).** Un código que sale de `PERMISSION_CODES` deja de concederse a los roles de sistema en el siguiente seed, pero su fila `Permission` sigue en la base y en cualquier rol propio que la tenga. Para retirarlo, en una ventana de mantenimiento y nunca desde `release.sh`:

```bash
python manage.py seed_permissions --prune --dry-run   # lista lo que se borraría
python manage.py seed_permissions --prune             # borra y registra SEED_PERMISSIONS_PRUNED
```

Nunca poda comodines (`*.*`, `recurso.*`): los gobierna el preflight de ADR p63.
~~~

**`docs/modules/logs.md`.** Inmediatamente antes de la línea `` ## Eventos de validacion tenant en serializers (`apps.tenant_validation`) `` inserta:

```markdown
### `SEED_PERMISSIONS_PRUNED` · WARNING

`seed_permissions --prune` (deuda B6, orden 6) borro permisos de la base que ya no estan en `PERMISSION_CODES`. Con ellos desaparecen sus concesiones en roles propios; los roles de sistema ya las perdian en cada seed. Nunca borra comodines (`*.*`, `recurso.*`). Logger `rbac.events`.

Campos: `event`, `count`, `codes`

Accion requerida: ninguna si una persona lanzo la poda en una ventana de mantenimiento. Nunca deberia aparecer en un release: `release.sh` no usa `--prune`.

---

```

## Verificación

Desde `backend/`:

```bash
R="rtk proxy python scripts/orden6_isolated.py"
python -m py_compile apps/core/tests/test_seed_permissions_prune.py && echo "py_compile OK"
$R test apps.core.tests.test_seed_permissions_prune apps.core.tests.test_admin_explicit_grants apps.users.tests.test_agent_identity apps.agent.tests.test_identity_evidence.ReleaseScriptTests --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED|^FAIL:|^ERROR:" | head -20
```

Todo debe pasar. `test_admin_explicit_grants` y `test_agent_identity` no cambian su recuento: el seed sin `--prune` debe seguir comportándose igual.

## Cierre

Commit: `feat(rbac): add explicit seed_permissions --prune for retired codes (order 6, B6)`.

En `MATRIZ.md`, fila B6: `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`, `ver commit E04`, `EVIDENCIA.md §E04`; y la fila E04 del avance. En evidencia anota que la poda no se ejecutó contra ninguna base real.

En «Para revisar»: nada, salvo que quieras ejecutar `--prune --dry-run` en algún entorno propio.
