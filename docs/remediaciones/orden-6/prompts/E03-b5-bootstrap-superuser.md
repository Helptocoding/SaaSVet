# E03 — B5: comando `bootstrap_superuser`

Primero lee y aplica `docs/remediaciones/orden-6/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Hoy el superusuario de plataforma se crea en un receptor de `post_migrate` (`apps/users/apps.py::_create_default_superuser`). Pasa a un comando explícito y con código de salida, sin cambiar el guard anti-escalación de ADR p15.

Hechos que fijan el diseño (comprobados el 11-11):

- El pre-launch prohíbe `DJANGO_SUPERUSER_*` en `.env.prod` (check 7). Por eso el comando **no va en `release.sh`**: las variables se pasan solo a su proceso.
- Los runbooks dicen usar `createsuperuser`, pero `User` no tiene manager propio: eso crea `role='ASSISTANT'` sin organización, y `apps/platform/permissions.py` exige `role == 'ADMIN_SAAS'`. El comando sustituye a `createsuperuser` en la documentación.
- Hoy `post_migrate` con esas variables crea el usuario. La prueba nueva lo fija en sentido contrario.

Códigos de salida: `0` si lo crea o ya existía; `1` si faltan variables, están incompletas o hay colisión.

## Archivos permitidos

- `backend/apps/users/bootstrap.py` (nuevo)
- `backend/apps/users/apps.py`
- `backend/apps/users/management/commands/bootstrap_superuser.py` (nuevo)
- `backend/apps/users/tests/test_bootstrap.py`
- `docs/modules/organizations.md`, `docs/modules/logs.md`, `docs/production-runbook.md`
- `docs/runbooks/platform-org-provisioning.md`, `docs/security/secret-rotation-plan.md`
- `docs/decisions/2026-05-17-p15-day4-cascade-lockdown.md`
- `.env.prod.example`, `scripts/pre-launch-security-check.sh` (solo el texto indicado)
- Expediente del orden 6

## Precondición

1. `grep -rn "_create_default_superuser" backend --include=*.py` solo muestra `apps/users/apps.py` y `apps/users/tests/test_bootstrap.py`.
2. `ls backend/apps/users/management/commands/bootstrap_superuser.py` no existe.
3. Desde `backend/`, `rtk proxy python scripts/orden6_isolated.py test apps.users.tests.test_bootstrap --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED"` pasa. Anota el `Ran N` (hoy 11).

Si algo no coincide, `BLOQUEADA`.

## Paso 1. `backend/apps/users/bootstrap.py` (nuevo)

Crea el archivo con exactamente este contenido. Es la función actual con tres cambios: devuelve un resultado, el aviso de entorno incompleto devuelve `INCOMPLETE_ENV` y los comentarios hablan de un comando en vez de un signal.

```python
"""Alta idempotente del superusuario de plataforma (ADMIN_SAAS).

Deuda B5, orden 6: antes corría como receptor de `post_migrate`. Ahora solo la invoca
el comando `bootstrap_superuser`, de forma explícita y con código de salida. El guard
anti-escalación es el de ADR p15 y no cambia.
"""
import logging
import os

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

logger = logging.getLogger('rbac.events')

# Resultados. El comando traduce cada uno a su código de salida.
CREATED = 'created'
EXISTING = 'existing'
BLOCKED = 'blocked'
MISSING_ENV = 'missing_env'
INCOMPLETE_ENV = 'incomplete_env'


def bootstrap_platform_superuser():
    """Crea o comprueba el superusuario de plataforma desde DJANGO_SUPERUSER_*.

    Guard anti-escalación (Issue #12 / ADR p15):
    - Si el username NO existe en DB → crea un superuser nuevo con role='ADMIN_SAAS'
      dentro de un atomic block; ante IntegrityError por dos ejecuciones simultáneas,
      re-fetch y reclasifica.
    - Si el username YA existe Y es el superuser de plataforma legítimo
      (is_superuser=True + is_staff=True + role='ADMIN_SAAS' + email coincide
      case-insensitive cuando se provee) → solo refresca is_active. NO resetea
      password (idempotencia de credenciales).
    - Si el username YA existe pero NO es el superuser de plataforma esperado
      (ej. una clínica registró un VET con ese username) → log CRITICAL y abort
      sin tocar al usuario. Sin esta guard, el antiguo signal escalaba cualquier
      usuario existente a superuser platform-wide y le reseteaba el password
      (CVSS 9.9).

    Devuelve CREATED, EXISTING, BLOCKED, MISSING_ENV o INCOMPLETE_ENV.
    """
    from apps.organizations.models import Organization

    username = os.environ.get('DJANGO_SUPERUSER_USERNAME')
    password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
    email = os.environ.get('DJANGO_SUPERUSER_EMAIL', '')

    if not username or not password:
        if username or password:
            # Solo uno de los dos seteado — config probablemente errónea.
            logger.warning("SUPERUSER_BOOTSTRAP_INCOMPLETE_ENV", extra={
                "event": "SUPERUSER_BOOTSTRAP_INCOMPLETE_ENV",
                "has_username": bool(username),
                "has_password": bool(password),
            })
            return INCOMPLETE_ENV
        return MISSING_ENV

    User = get_user_model()

    def _is_platform_superuser(user):
        """Predicado canónico — usado tanto en el path de fetch como en el
        post-race re-fetch. Mantener en un único lugar para evitar drift."""
        if not (user.is_superuser and user.is_staff):
            return False
        if getattr(user, 'role', None) != 'ADMIN_SAAS':
            return False
        if email and (user.email or '').lower() != email.lower():
            return False
        return True

    def _handle_existing(user, *, reason_if_blocked):
        if not _is_platform_superuser(user):
            logger.critical("SUPERUSER_BOOTSTRAP_SKIPPED", extra={
                "event": "SUPERUSER_BOOTSTRAP_SKIPPED",
                "reason": reason_if_blocked,
                "username": username,
                "existing_user_id": user.pk,
                "existing_role": getattr(user, 'role', None),
                "existing_org_id": user.organization_id,
                "existing_is_superuser": user.is_superuser,
                "existing_is_staff": user.is_staff,
            })
            return BLOCKED
        # Superuser plataforma legítimo: solo refrescar is_active si está inactivo.
        # NO resetear password.
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=['is_active'])
        return EXISTING

    existing = User.objects.filter(username=username).first()
    if existing is not None:
        return _handle_existing(existing, reason_if_blocked='username_collision_non_platform_user')

    # Usuario no existe → crear dentro de atomic. Si otra ejecución simultánea lo
    # creó en paralelo, IntegrityError dispara re-fetch y reclasifica.
    try:
        with transaction.atomic():
            org, _ = Organization.objects.get_or_create(name='Vet Care Internal')
            user = User.objects.create_superuser(
                username=username,
                email=email,
                password=password,
                role='ADMIN_SAAS',
                organization=org,
            )
        logger.info("SUPERUSER_BOOTSTRAP_CREATED", extra={
            "event": "SUPERUSER_BOOTSTRAP_CREATED",
            "username": username,
            "user_id": user.pk,
            "org_id": org.pk,
        })
        return CREATED
    except IntegrityError:
        # Otra ejecución creó el user entre filter().first() y create_superuser().
        # Re-fetch y aplicar el mismo predicado: si no calza con
        # is_platform_superuser, abort + log CRITICAL.
        raced = User.objects.filter(username=username).first()
        if raced is None:
            # IntegrityError por causa distinta a UNIQUE de username — re-raise.
            raise
        logger.warning("SUPERUSER_BOOTSTRAP_RACE_RESOLVED", extra={
            "event": "SUPERUSER_BOOTSTRAP_RACE_RESOLVED",
            "username": username,
            "user_id": raced.pk,
        })
        return _handle_existing(raced, reason_if_blocked='race_condition_created_unexpected_user')
```

## Paso 2. `backend/apps/users/apps.py`

Sustituye **todo** el archivo por exactamente:

```python
from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.users'

    def ready(self):
        # El superusuario de plataforma ya no se crea en `post_migrate`: lo hace el
        # comando explícito `bootstrap_superuser` (deuda B5, orden 6).
        import apps.users.signals  # noqa: registra post_save en User
```

## Paso 3. El comando

Crea `backend/apps/users/management/commands/bootstrap_superuser.py`. El directorio ya existe (contiene `ensure_agent_users.py`):

```python
"""bootstrap_superuser — crea o comprueba el superusuario de plataforma (ADMIN_SAAS).

Lee DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_PASSWORD y, opcional,
DJANGO_SUPERUSER_EMAIL del entorno de ESTE proceso. En producción esas variables no
van en .env.prod (pre-launch, check 7): se pasan solo a este comando. Procedimiento en
docs/modules/organizations.md, sección «En VPS (produccion)».

Idempotente: si el superusuario legítimo ya existe, no cambia su contraseña.
Salida 0: creado o ya existente. Salida 1: variables ausentes o incompletas, o
colisión con un usuario que no es el superusuario de plataforma.
No forma parte de release.sh.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.users.bootstrap import (
    BLOCKED, CREATED, EXISTING, INCOMPLETE_ENV, MISSING_ENV, bootstrap_platform_superuser,
)

_ERRORS = {
    MISSING_ENV: 'Define DJANGO_SUPERUSER_USERNAME y DJANGO_SUPERUSER_PASSWORD para este comando.',
    INCOMPLETE_ENV: 'Falta DJANGO_SUPERUSER_USERNAME o DJANGO_SUPERUSER_PASSWORD: define ambos.',
    BLOCKED: (
        'El usuario indicado ya existe y no es el superusuario de plataforma. No se modificó. '
        'Revisa el evento SUPERUSER_BOOTSTRAP_SKIPPED.'
    ),
}
_SUCCESS = {
    CREATED: 'Superusuario de plataforma creado.',
    EXISTING: 'El superusuario de plataforma ya existía. Su contraseña no cambió.',
}


class Command(BaseCommand):
    help = 'Crea o comprueba el superusuario de plataforma desde DJANGO_SUPERUSER_*. Idempotente.'

    def handle(self, *args, **options):
        result = bootstrap_platform_superuser()
        if result in _ERRORS:
            raise CommandError(_ERRORS[result])
        self.stdout.write(self.style.SUCCESS(_SUCCESS[result]))
```

Comprueba:

```bash
cd backend
python -m py_compile apps/users/bootstrap.py apps/users/apps.py apps/users/management/commands/bootstrap_superuser.py && echo "py_compile OK"
grep -rn "_create_default_superuser\|post_migrate.connect" apps --include=*.py | grep -v "/tests/"
```

El `grep` no debe imprimir nada. Los comentarios nuevos que mencionan `post_migrate` sin `.connect` no cuentan.

## Paso 4. `backend/apps/users/tests/test_bootstrap.py`

1. Sustituye la primera línea del archivo, que hoy es:

   ```python
   """Tests del bootstrap signal `_create_default_superuser` (Issue #12, ADR p15).
   ```

   por:

   ```python
   """Tests del bootstrap del superusuario de plataforma (Issue #12, ADR p15; comando desde el orden 6, B5).
   ```
2. Sustituye `from apps.users.apps import _create_default_superuser` por:

   ```python
   from apps.users.bootstrap import CREATED, MISSING_ENV, bootstrap_platform_superuser
   ```

3. Añade estos imports. Los dos primeros van debajo de `import os`, y los otros tres debajo de `from django.contrib.auth import get_user_model`:

   ```python
   from io import StringIO
   from pathlib import Path
   ```

   ```python
   from django.core.management import call_command
   from django.core.management.base import CommandError
   from django.core.management.sql import emit_post_migrate_signal
   ```

4. Sustituye el helper completo:

   ```python
       def _run_signal(self, username='superadmin', password='SuperPass123!', email=''):
           with mock.patch.dict(os.environ, {
               'DJANGO_SUPERUSER_USERNAME': username,
               'DJANGO_SUPERUSER_PASSWORD': password,
               'DJANGO_SUPERUSER_EMAIL': email,
           }):
               _create_default_superuser(sender=None)
   ```

   por:

   ```python
       def _run_bootstrap(self, username='superadmin', password='SuperPass123!', email=''):
           with mock.patch.dict(os.environ, {
               'DJANGO_SUPERUSER_USERNAME': username,
               'DJANGO_SUPERUSER_PASSWORD': password,
               'DJANGO_SUPERUSER_EMAIL': email,
           }):
               return bootstrap_platform_superuser()
   ```

5. Reemplaza en todo el archivo `self._run_signal(` por `self._run_bootstrap(`. Después, `grep -c "_run_signal" apps/users/tests/test_bootstrap.py` debe dar `0`.
6. En `test_creates_superuser_when_absent`, sustituye la línea `        self._run_bootstrap()` por `        self.assertEqual(self._run_bootstrap(), CREATED)`.
7. Sustituye el cuerpo de `test_noop_when_env_vars_absent`:

   ```python
           with mock.patch.dict(os.environ, {}, clear=True):
               _create_default_superuser(sender=None)
           self.assertFalse(User.objects.filter(username='superadmin').exists())
   ```

   por:

   ```python
           with mock.patch.dict(os.environ, {}, clear=True):
               result = bootstrap_platform_superuser()
           self.assertEqual(result, MISSING_ENV)
           self.assertFalse(User.objects.filter(username='superadmin').exists())
   ```

8. Al final del archivo añade:

   ```python
   ENV = {
       'DJANGO_SUPERUSER_USERNAME': 'superadmin',
       'DJANGO_SUPERUSER_PASSWORD': 'SuperPass123!',
       'DJANGO_SUPERUSER_EMAIL': '',
   }


   class BootstrapCommandTests(TestCase):
       """B5 (orden 6): comando explícito con código de salida, sin signal."""

       def _call(self, env):
           out = StringIO()
           with mock.patch.dict(os.environ, env, clear=True):
               call_command('bootstrap_superuser', stdout=out)
           return out.getvalue()

       def test_creates_and_then_is_idempotent(self):
           self.assertIn('creado', self._call(ENV))
           self.assertIn('ya existía', self._call(ENV))
           self.assertEqual(User.objects.filter(username='superadmin').count(), 1)

       def test_missing_env_fails(self):
           with self.assertRaisesMessage(CommandError, 'DJANGO_SUPERUSER_USERNAME'):
               self._call({})

       def test_incomplete_env_fails_without_creating(self):
           with self.assertLogs('rbac.events', level='WARNING'):
               with self.assertRaisesMessage(CommandError, 'define ambos'):
                   self._call({'DJANGO_SUPERUSER_USERNAME': 'superadmin'})
           self.assertFalse(User.objects.filter(username='superadmin').exists())

       def test_collision_fails_without_touching_the_user(self):
           org = Organization.objects.create(name='Clinica X')
           vet = User.objects.create_user(
               username='superadmin', password='VetPass123!', organization=org, role='VET',
           )
           with self.assertLogs('rbac.events', level='CRITICAL'):
               with self.assertRaisesMessage(CommandError, 'no es el superusuario de plataforma'):
                   self._call(ENV)
           vet.refresh_from_db()
           self.assertFalse(vet.is_superuser)
           self.assertTrue(vet.check_password('VetPass123!'))

       def test_migrate_no_longer_bootstraps(self):
           with mock.patch.dict(os.environ, ENV):
               emit_post_migrate_signal(verbosity=0, interactive=False, db='default')
           self.assertFalse(User.objects.filter(username='superadmin').exists())

       def test_release_does_not_bootstrap(self):
           path = Path(__file__).resolve().parents[3] / 'scripts' / 'release.sh'
           body = [line for line in path.read_text(encoding='utf-8').splitlines()
                   if line.strip() and not line.lstrip().startswith('#')]
           self.assertFalse(any('bootstrap_superuser' in line for line in body))
   ```

No cambies ninguna otra prueba.

## Paso 5. Documentación

Haz cada sustitución tal cual. Si un texto «antes» no aparece exactamente, `BLOQUEADA`.

**`docs/modules/organizations.md`.** Sustituye desde la línea `### En VPS (produccion)` hasta la línea `` - `SUPERUSER_BOOTSTRAP_INCOMPLETE_ENV` (WARNING) — solo `USERNAME` o solo `PASSWORD` seteado `` (ambas incluidas) por:

~~~markdown
### En VPS (produccion)

El ADMIN_SAAS se crea **una vez** con el comando explícito `bootstrap_superuser` (deuda B5, orden 6). Ya no hay signal `post_migrate` ni paso de `release.sh` que lo haga.

Las credenciales **no** van en `.env.prod`: el pre-launch lo bloquea, porque quedarían legibles en `/proc/<pid>/environ` de procesos que viven días. Se pasan solo al proceso del comando:

```bash
read -r -p "Usuario plataforma: " DJANGO_SUPERUSER_USERNAME
read -r -s -p "Contraseña: " DJANGO_SUPERUSER_PASSWORD; echo
read -r -p "Correo (opcional): " DJANGO_SUPERUSER_EMAIL
export DJANGO_SUPERUSER_USERNAME DJANGO_SUPERUSER_PASSWORD DJANGO_SUPERUSER_EMAIL
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm \
  -e DJANGO_SUPERUSER_USERNAME -e DJANGO_SUPERUSER_PASSWORD -e DJANGO_SUPERUSER_EMAIL \
  backend python manage.py bootstrap_superuser
unset DJANGO_SUPERUSER_USERNAME DJANGO_SUPERUSER_PASSWORD DJANGO_SUPERUSER_EMAIL
```

En local basta `python manage.py bootstrap_superuser` con esas variables en el entorno.

No usar `createsuperuser`: `User` no tiene manager propio y crea un superusuario con `role='ASSISTANT'` y sin organización, que no pasa el permiso de plataforma (`role == 'ADMIN_SAAS'`).

Salida `0`: creado o ya existente (idempotente; nunca cambia la contraseña de un superusuario legítimo). Salida `1`: variables ausentes o incompletas, o colisión con un usuario que no es el superusuario de plataforma.

**Guard anti-escalación (PR-4A / ADR p15):** el comando usa `filter().first()` + predicado `_is_platform_superuser` (requiere `is_superuser=True AND is_staff=True AND role='ADMIN_SAAS' AND email coincide case-insensitive cuando se provee`). Si una clinica registra un VET con el mismo username que `DJANGO_SUPERUSER_USERNAME`, el comando NO escala al VET ni le resetea password: log CRITICAL `SUPERUSER_BOOTSTRAP_SKIPPED`, sin mutacion y salida 1.

Eventos emitidos por el bootstrap:
- `SUPERUSER_BOOTSTRAP_CREATED` (INFO) — superuser nuevo creado
- `SUPERUSER_BOOTSTRAP_SKIPPED` (CRITICAL) — username collision con usuario non-platform
- `SUPERUSER_BOOTSTRAP_RACE_RESOLVED` (WARNING) — dos ejecuciones simultaneas del comando
- `SUPERUSER_BOOTSTRAP_INCOMPLETE_ENV` (WARNING) — solo `USERNAME` o solo `PASSWORD` seteado
~~~

**`docs/modules/logs.md`**, ocho sustituciones:

1. `` El signal `_create_default_superuser` (PR-4A / ADR p15) creo exitosamente `` → `` El comando `bootstrap_superuser` (deuda B5, orden 6; guard de PR-4A / ADR p15) creo exitosamente ``
2. `Accion requerida: ninguna en deploy nuevo. Si aparece en deploys subsecuentes (despues del primero), investigar — el signal deberia ser idempotente.` → `Accion requerida: ninguna si alguien ejecuto el comando a proposito. Si aparece sin esa ejecucion, investigar.`
3. `El signal detecto que ese usuario NO es` → `El comando detecto que ese usuario NO es`
4. `que permitia que el signal escalara cualquier usuario` → `que permitia que el antiguo signal escalara cualquier usuario`
5. `` Accion requerida: investigar de inmediato. Cambiar `DJANGO_SUPERUSER_USERNAME` a un valor que NO colisione con usuarios de clinicas, o bien crear el platform-superuser manualmente y remover las env vars. `` → `` Accion requerida: investigar de inmediato. El comando termina con codigo 1 sin tocar al usuario. Usar un `DJANGO_SUPERUSER_USERNAME` que NO colisione con usuarios de clinicas. ``
6. `` Race condition multi-worker: dos workers de `post_migrate` ejecutaron el signal en paralelo, uno gano la creacion y el otro recibio `IntegrityError`. El que perdio re-fetch el usuario creado y aplica el mismo predicado de validacion. Comportamiento esperado en deploys multi-worker. `` → `` Race condition: dos ejecuciones simultaneas del comando, una gano la creacion y la otra recibio `IntegrityError`. La que perdio re-fetch el usuario creado y aplica el mismo predicado de validacion. Solo ocurre si alguien lanza el comando dos veces a la vez. ``
7. `Config del entorno probablemente errónea — el signal aborta sin crear nada.` → `Config del entorno probablemente errónea — el comando aborta sin crear nada y termina con codigo 1.`
8. `` Accion requerida: revisar `.env.prod` en el VPS. Setear ambas o ninguna. `` → `` Accion requerida: pasar al comando ambas variables. Nunca van en `.env.prod`. ``

Y en la tabla de frecuencias: `` | `SUPERUSER_BOOTSTRAP_SKIPPED` | Nunca despues del deploy inicial | `` → `` | `SUPERUSER_BOOTSTRAP_SKIPPED` | Nunca | ``

**`docs/production-runbook.md`.** Sustituye estas dos líneas:

```bash
# bootstrap del admin de plataforma (UNA vez, NO en el env):
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend python manage.py createsuperuser
```

por:

```bash
# bootstrap del admin de plataforma (UNA vez; credenciales solo para este proceso,
# nunca en .env.prod). Ver docs/modules/organizations.md § En VPS (produccion).
read -r -p "Usuario plataforma: " DJANGO_SUPERUSER_USERNAME
read -r -s -p "Contraseña: " DJANGO_SUPERUSER_PASSWORD; echo
export DJANGO_SUPERUSER_USERNAME DJANGO_SUPERUSER_PASSWORD
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm \
  -e DJANGO_SUPERUSER_USERNAME -e DJANGO_SUPERUSER_PASSWORD \
  backend python manage.py bootstrap_superuser
unset DJANGO_SUPERUSER_USERNAME DJANGO_SUPERUSER_PASSWORD
```

**`.env.prod.example`.** Sustituye:

```text
#     Bootstrap the platform admin manually via `createsuperuser` one time.
```

por:

```text
#     Bootstrap the platform admin once with `manage.py bootstrap_superuser`,
#     passing these vars only to that process (docs/modules/organizations.md).
#     Do not use `createsuperuser`: it creates role=ASSISTANT with no organization.
```

**`scripts/pre-launch-security-check.sh`.** En el mensaje del bloqueante, sustituye `Bootstrap manually via createsuperuser once.` por `Bootstrap once via manage.py bootstrap_superuser, passing the vars only to that process.` No cambies nada más del script.

**`docs/runbooks/platform-org-provisioning.md`.** Sustituye:

```markdown
- Cuenta `ADMIN_SAAS` activa (creada por el bootstrap signal con
  `DJANGO_SUPERUSER_*` env vars en el VPS).
```

por:

```markdown
- Cuenta `ADMIN_SAAS` activa (creada una vez con `manage.py bootstrap_superuser`;
  ver [organizations, En VPS](../modules/organizations.md)).
```

**`docs/security/secret-rotation-plan.md`**, cuatro sustituciones:

1. El bloque de §5.3 que empieza en `- Bootstrap una sola vez en el VPS:` y termina en `  con password fresca, fuerte, no reusada.` (incluye el bloque `bash` con `createsuperuser`) → 

   ```markdown
   - Bootstrap una sola vez en el VPS con `python manage.py bootstrap_superuser`, pasando
     `DJANGO_SUPERUSER_*` solo a ese proceso (procedimiento en
     [organizations, En VPS](../modules/organizations.md)), con password fresca, fuerte,
     no reusada. `createsuperuser` no sirve: crea `role='ASSISTANT'` sin organización.
   ```

2. `` | `DJANGO_SUPERUSER_PASSWORD` | `createsuperuser` con password fresca; no portar | Sí | `` → `` | `DJANGO_SUPERUSER_PASSWORD` | `bootstrap_superuser` con password fresca; no portar | Sí | ``
3. `` "por comodidad" del primer boot — usar `createsuperuser` interactivo. `` → `` "por comodidad" del primer boot — usar `bootstrap_superuser` con las variables solo en ese proceso. ``
4. `` `DJANGO_SUPERUSER_PASSWORD` (vía `createsuperuser`, no portar). `` → `` `DJANGO_SUPERUSER_PASSWORD` (vía `bootstrap_superuser`, no portar). ``

**`docs/decisions/2026-05-17-p15-day4-cascade-lockdown.md`.** Al final del archivo añade:

```markdown

---

## Addendum 2026-11-11: el signal pasa a comando (deuda B5, orden 6)

`_create_default_superuser` dejó de recibir `post_migrate`. Su lógica vive en `apps/users/bootstrap.py` y solo la invoca `python manage.py bootstrap_superuser`, que termina con código 1 ante variables ausentes o incompletas o ante colisión. El guard anti-escalación no cambia. El comando no está en `release.sh`, porque el pre-launch prohíbe `DJANGO_SUPERUSER_*` en `.env.prod`: las credenciales se pasan solo a ese proceso. Sustituye a `createsuperuser` en los runbooks, que creaba `role='ASSISTANT'` sin organización.
```

Comprobación final: `git grep -n "createsuperuser" -- docs/production-runbook.md docs/runbooks docs/security .env.prod.example scripts/pre-launch-security-check.sh` solo puede mostrar líneas que digan que **no** se use (`no sirve`, `Do not use`).

## Verificación

Desde `backend/`:

```bash
R="rtk proxy python scripts/orden6_isolated.py"
python -m py_compile apps/users/tests/test_bootstrap.py && echo "py_compile OK"
$R test apps.users apps.organizations --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED|^FAIL:|^ERROR:" | head -20
$R test apps.users.tests.test_bootstrap --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED"
```

Todo debe pasar. El último debe dar el `Ran` de la precondición más 6.

## Cierre

Commit: `refactor(users): replace post_migrate superuser bootstrap with an explicit command (order 6, B5)`.

En `MATRIZ.md`, fila B5: `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`, `ver commit E03`, `EVIDENCIA.md §E03`; y la fila E03 del avance. En evidencia anota que el comando no se ejecutó contra ningún despliegue.

En «Para revisar»: el procedimiento nuevo de `docs/modules/organizations.md` antes del próximo despliegue, y que `createsuperuser` deja de recomendarse.
