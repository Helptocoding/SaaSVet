# ADR p20 — Credential lifecycle: self-service password change

**Fecha:** 2026-05-22
**Estado:** ✅ Aceptado e implementado
**Branch:** `develop`
**Issues cerrados:** N/A (feature greenfield, gap post-ADR p19)

## Contexto

ADR p19 introdujo `POST /api/platform/organizations/` para provisión de
tenants + admin inicial. Quedó un gap operativo: el admin recién provisionado
recibe una contraseña temporal y NO tiene forma de cambiarla.

Estado pre-p20:
- ADMIN de clínica NO tiene `is_staff=True` → sin acceso a `/admin/`.
- VET / ASSISTANT mismo gap.
- No existe endpoint API para self-change.
- Único workaround: ADMIN_SAAS ejecuta `python manage.py changepassword
  <username>` desde shell. No escalable.

Esto bloqueaba el onboarding real de clientes — un admin que no puede
cambiar su contraseña temporal es un riesgo de credenciales compartidas.

## Decisión

Implementar **self-change credential lifecycle como operación explícita
auditada**, no como un campo update de usuario.

### Tres flujos distintos (separar, no mezclar)

| Flujo | Estado en p20 | Diferencias |
|---|---|---|
| **1. Self-change** (usuario autenticado cambia su propia contraseña) | ✅ Implementado | Requiere current_password, validate_password, blacklist tokens propios, re-mint tokens |
| **2. Admin reset** (ADMIN de org resetea password de staff) | ❌ Diferido | NO requiere current_password, requiere autorización del admin, debe forzar re-login, audit distinto |
| **3. Forgot password** (recovery por email, sin auth) | ❌ Diferido | NO autenticado, requiere SMTP + token de recovery + rate limiting agresivo + invalidation de recovery tokens |

Razón para separar: permisos, auditoría, riesgos, validaciones y throttling
son **distintos en cada uno**. Mezclarlos lleva a endpoints sobrecargados
con permisos confusos y vectores de privilege escalation.

### Endpoint p20

```
POST /api/users/change-password/
Authorization: Bearer <JWT>
X-Request-ID: <opcional, uuid v4>

{
  "current_password": "OldPass1234!",
  "new_password": "NewStrongPass4321!",
  "confirm_password": "NewStrongPass4321!"
}
```

Response 200:
```json
{
  "detail": "Contraseña actualizada.",
  "request_id": "...",
  "duration_ms": 87,
  "access": "<new JWT access token>",
  "refresh": "<new JWT refresh token>"
}
```

### Componentes implementados

| Componente | Path | Responsabilidad |
|---|---|---|
| Permission | `IsAuthenticated` (DRF default) | Cualquier user autenticado. RBAC NO aplica — todos los roles pueden cambiar SU propia contraseña. |
| Serializer | `apps/users/serializers.py:ChangePasswordSerializer` | Field validation: current/new/confirm presentes, `new_password.min_length=8`, confirm match. NO ejecuta `validate_password` (requiere user, se hace en service). |
| Service | `apps/users/services.py:change_password` | Orquestación autoritativa atomic. Orden estricto: verify current → validate new → reject same → snapshot OutstandingToken IDs → set_password → update_session_auth_hash → mint new pair → blacklist snapshotted → log. |
| View | `apps/users/views.py:ChangeMyPasswordView` | Thin transport. Extrae X-Request-ID, client_ip, user_agent. Delega al service. |
| URL | `POST /api/users/change-password/` | Action endpoint explícito, NO PATCH sobre /staff/<id>/. |
| Throttle | `change_password` scope = `10/hour` por user | Disuade brute-force del current_password. |

### JWT lifecycle (el corazón del flujo)

**Estado pre-p20 (riesgo):**
- `SIMPLE_JWT`: `ROTATE_REFRESH_TOKENS=False`, `BLACKLIST_AFTER_ROTATION=False`.
- `token_blacklist` app NO instalada.
- Cambiar password no invalidaba tokens → robo de credenciales NO mitigable
  sin esperar la expiración natural del refresh (7 días).

**Estado p20:**
- `rest_framework_simplejwt.token_blacklist` agregada a INSTALLED_APPS,
  migraciones aplicadas (13 archivos, 2 tablas: `outstandingtoken`,
  `blacklistedtoken` con índices en `user_id`, `jti`, `token_id`).
- `SIMPLE_JWT`:
  - `ROTATE_REFRESH_TOKENS = True` — cada `/token/refresh/` emite nuevo refresh.
  - `BLACKLIST_AFTER_ROTATION = True` — el refresh anterior queda blacklisteado.
  - `ACCESS_TOKEN_LIFETIME = timedelta(minutes=15)` (reducido de 30 → 15 min,
    ver "Trade-offs" abajo).

**Orden EXACTO en `change_password` service:**

```
@transaction.atomic
def change_password(*, actor, request, current_password, new_password, ...):
    # 1. Verify current (fail fast — log USER_PASSWORD_CHANGE_FAILED si falla)
    if not actor.check_password(current_password): raise ValidationError(...)

    # 2. validate_password(new, user=actor) — Django validators
    #    incl. UserAttributeSimilarityValidator (necesita user)
    #         MinimumLengthValidator (default 8)
    #         CommonPasswordValidator
    #         NumericPasswordValidator

    # 3. Reject new == current
    if actor.check_password(new_password): raise ValidationError(...)

    # 4. SNAPSHOT old OutstandingToken IDs ANTES de cualquier mutación de tokens
    old_outstanding_ids = list(
        OutstandingToken.objects.filter(user=actor).values_list('pk', flat=True)
    )

    # 5. set_password + save
    actor.set_password(new_password)
    actor.save(update_fields=['password'])

    # 6. update_session_auth_hash(request, actor)
    #    Mantiene viva la sesión Django (SessionAuthentication coexiste en
    #    DEFAULT_AUTHENTICATION_CLASSES — Django admin no se cae).

    # 7. Mint NEW refresh + access pair (crea nuevo OutstandingToken — NO está en snapshot)
    new_refresh = RefreshToken.for_user(actor)
    new_access = str(new_refresh.access_token)

    # 8. Blacklist solo los snapshotted (preserva el nuevo recién emitido)
    for ot in OutstandingToken.objects.filter(pk__in=old_outstanding_ids):
        BlacklistedToken.objects.get_or_create(token=ot)

    # 9. Log USER_PASSWORD_CHANGED estructurado

    return {access, refresh, duration_ms, request_id}
```

**Invariante crítica:** la captura del snapshot **antes** de mintear el
nuevo refresh garantiza que el nuevo token NO está en la lista a
blacklistear. Cualquier reorden rompe el flujo silenciosamente — un test
explícito (`test_new_refresh_token_is_valid` post-cambio) lo cubre.

### ⚠ Comportamiento del access token actual

**MUY IMPORTANTE para soporte / ops:** los **refresh tokens** se invalidan
al instante (entran a BlacklistedToken). Los **access tokens existentes
permanecen válidos hasta su expiración natural** (15 min con la nueva
config p20).

Esto NO es un bug — es el diseño stateless de JWT. SimpleJWT no soporta
nativamente blacklist de access tokens (sólo refresh). Mitigaciones aplicadas:

- TTL del access reducido 30 → 15 min → ventana máxima de exposición
  post-cambio es 15 min.
- AuthProvider del frontend hace refresh transparente 5 min antes de la
  expiración → tras el cambio, el próximo refresh con el viejo refresh
  token falla con 401 → frontend dispara `logout()` → el usuario vuelve
  a loguearse limpiamente.

Si en el futuro se requiere invalidación instantánea del access token,
hay tres caminos viables (ninguno implementado en p20):

1. JWT con `jti` + middleware que consulta blacklist en cada request.
   Convierte JWT en stateful — costo de latencia + DB hits por request.
2. Reemplazar JWT por sessions stateful (e.g. DRF token auth + Redis
   session store). Cambio arquitectónico mayor.
3. Forzar TTL aún más bajo (1-2 min) + refresh transparente más frecuente.
   Mejora la ventana pero no la elimina, aumenta carga de refresh.

p20 acepta la ventana de 15 min como trade-off proporcional al riesgo
real (self-change, no compromised-account recovery).

### Anti-patterns explícitamente bloqueados

❌ **NUNCA** permitir esto:

```
PATCH /api/staff/<id>/   {"password": "..."}
PATCH /api/me/           {"password": "..."}
```

Razones:
- Bypassa `validate_password` (validators Django no se ejecutan).
- Bypassa blacklist de refresh tokens → sesión robada sigue viva.
- Bypassa audit log estructurado.
- Rompe credential lifecycle controlado.

Verificación T26 del PR: ningún serializer expone `password` como writable
en update path. Solo paths permitidos:
- `CreateEmployeeSerializer` (initial password en create de staff).
- `ProvisionOrgSerializer` (initial password de admin SaaS provisionado).
- `change_password` service (esta operación).
- `_create_default_superuser` bootstrap signal.
- `createsuperuser` CLI.
- Django admin password change form (escape hatch operativo).

### Decisiones de diseño específicas

#### `min_length=8` en self-change, no 12

ADR p19 estableció `min_length=12` para passwords de admins iniciales SaaS
por su privilegio amplificado (operadores de plataforma). p20 baja a `8`
para self-change porque:

- Aplica a TODOS los roles (ADMIN, VET, ASSISTANT) — un floor de 12 es
  fricción excesiva para usuarios sin privilegio amplificado.
- Django's `MinimumLengthValidator` default es 8 — consistente con el
  resto del sistema.
- Validators adicionales (common-password, numeric-only, similarity)
  proveen defense-in-depth ortogonal al length.

#### Return new tokens vs forzar re-login

Devolver `{access, refresh}` nuevos en el response 200. Frontend reemplaza
los tokens via `useAuth().login(access, refresh)` (central token manager).

Razones contra forzar re-login:
- Self-change NO es compromised-account recovery — no hay razón para
  asumir el usuario lo está usando bajo coacción.
- Forzar re-login penaliza UX (extra click, retipear credenciales).
- No agrega seguridad real: el actor ya autenticó con current_password
  hace milisegundos.
- Complica el frontend (manejo de logout/login secuenciales en pantalla
  modal).

Razones a favor de devolver tokens nuevos:
- UX limpia (un toast, usuario sigue trabajando).
- Forzar uso del central token manager (`useAuth().login`) en lugar de
  `localStorage.setItem` disperso → menos drift, menos bugs.

#### `apps/core/network.py` para `get_client_ip` / `get_user_agent`

NO se metió en `apps/core/utils.py` deliberadamente. `utils.py` se vuelve
cementerio arquitectónico en proyectos que crecen. `network.py` tiene
nombre semántico claro y será el home futuro para:
- Forwarded headers trust-chain validation.
- Proxy chain parsing.
- IP geo enrichment.
- Audit-trail context extraction.

### Tests (22 tests, 100% pass)

`apps/users/tests/test_change_password.py`:

**Validation (8):**
- `test_wrong_current_password_rejected_400`
- `test_weak_new_password_below_min_length_rejected`
- `test_new_password_numeric_only_rejected`
- `test_new_password_too_similar_to_first_name_rejected`
- `test_new_password_common_dictionary_word_rejected`
- `test_confirm_password_mismatch_rejected_400`
- `test_new_equals_current_rejected_400`
- `test_unauthenticated_401`

**Success (5):**
- `test_password_changed_successfully_200`
- `test_response_includes_new_access_and_refresh_pair`
- `test_new_access_token_works_in_authenticated_request`
- `test_old_password_no_longer_works_for_login`
- `test_new_password_works_for_login`

**JWT lifecycle (5):**
- `test_old_refresh_token_blacklisted_after_change`
- `test_new_refresh_token_is_valid`
- `test_other_user_refresh_tokens_not_affected` (multi-user isolation)
- `test_multiple_old_refresh_tokens_all_blacklisted`
- `test_blacklist_count_in_log_matches_outstanding_snapshot`

**Logging (2):**
- `test_success_log_carries_actor_org_ip_useragent`
- `test_failed_attempt_logged_with_warning`

**Throttle (1):**
- `test_throttle_blocks_after_budget_exceeded`

**Atomicity (1):**
- `test_password_unchanged_when_token_blacklist_step_fails`

## Trade-offs aceptados

| Trade-off | Justificación |
|---|---|
| Access token sobrevive hasta 15 min post-cambio | Stateless JWT design. Ventana mitigable con TTL más bajo, no eliminable sin stateful auth. |
| `flushexpiredtokens` requiere cron | OutstandingToken + BlacklistedToken crecen lineal en refreshes. Documentado en runbook. |
| Single endpoint, no MFA | Pre-beta. MFA en sprint futuro. |
| Sin password history (rechazar últimos N) | Enterprise feature. v1 mantiene min necesario. |
| Sin email notification post-cambio | Requiere SMTP. Diferido. |
| **CORS gotcha**: `X-Request-ID` debe estar en `CORS_ALLOW_HEADERS` | Sin esto, browser hace OPTIONS preflight 200 pero rechaza el POST silenciosamente. Ver runbook `password-change.md` § "Infrastructure gotchas". |

## Lo que NO incluye p20

- **Admin reset** (`POST /api/staff/<public_id>/reset-password/`) — flujo
  distinto: NO requiere current_password, requiere autorización del admin,
  fuerza re-login. ADR separado.
- **Forgot password flow** (email + recovery token + reset link) — requiere
  SMTP infra + token storage + rate limiting agresivo. ADR separado.
- **MFA** — sprint futuro post-beta.
- **Password history** — enterprise feature, no v1.
- **Force password change post-provisioning** (flag `password_must_change`)
  — opcional fase 2 con su propio ADR.
- **Email verification del cambio** — no necesario si ya está autenticado.

## Componentes acoplados

```
apps/users/
├── services.py:change_password
│   ├── update_session_auth_hash (django.contrib.auth)
│   ├── validate_password (django.contrib.auth.password_validation)
│   ├── RefreshToken (rest_framework_simplejwt.tokens)
│   ├── OutstandingToken, BlacklistedToken (rest_framework_simplejwt.token_blacklist.models)
│   └── logger 'users.events'
├── views.py:ChangeMyPasswordView
│   ├── apps.core.network.get_client_ip, get_user_agent
│   └── apps.users.services.change_password
└── serializers.py:ChangePasswordSerializer
```

Sin imports nuevos hacia apps de dominio (`medical_records`, `billing`,
etc.) — el cambio queda contenido en `apps/users/` + `apps/core/`.

## Refs

- CLAUDE.md ADR-17
- `docs/runbooks/password-change.md`
- Endpoint: `POST /api/users/change-password/`
- ADR previo (provisioning): `2026-05-22-p19-platform-org-provisioning.md`
