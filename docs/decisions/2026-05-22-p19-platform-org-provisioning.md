# ADR p19 — Tenant provisioning vía API (apps/platform/)

**Fecha:** 2026-05-22
**Estado:** ✅ Aceptado e implementado
**Branch:** `develop`
**Issues cerrados:** N/A (feature greenfield)

## Contexto

Pre-p19, el único path para crear una nueva clínica era:
1. SSH/console al Railway deploy.
2. `python manage.py createsuperuser` (si no existe ADMIN_SAAS).
3. Login a `/admin/` (Django admin).
4. **Organizations → Add** manual.
5. **Users → Add** manual con `organization` + `role='ADMIN'`.
6. `python manage.py seed_permissions` (a veces redundante si el signal corrió).

Problemas:
- Django admin no es operacionalmente apto para onboarding SaaS frecuente.
- Sin audit trail estructurado de quién provisionó qué clínica.
- Sin tests automatizados del flujo (createsuperuser + admin UI no se cubren).
- Sin throttle — un ADMIN_SAAS comprometido podría crear cientos de orgs manualmente.
- Sin idempotency — clicks repetidos en admin UI pueden crear duplicados con nombres
  ligeramente distintos.
- Sin frontend dedicado para ops/support — Django admin expone toda la DB.

## Decisión

Endpoint API dedicado para provisioning, en una **app nueva separada** del dominio tenant.

### Estructura de app

`apps/platform/` es para cross-tenant SaaS operations. `apps/organizations/` queda como
tenant-scoped (settings de la clínica). **Boundary regla**: `platform` puede importar de
`organizations`/`users`/`core`; el inverso está prohibido. Esto previene que tenant logic
acople con platform logic en sprints futuros (impersonation, billing, support tooling).

### Componentes

| Componente | Path | Responsabilidad |
|---|---|---|
| Permission | `apps/platform/permissions.py:IsPlatformOperator` | Predicado `is_superuser + is_staff + role='ADMIN_SAAS'`. Distinto semánticamente de `_is_platform_superuser` (bootstrap) para evitar drift cuando agreguen impersonation/billing/support. |
| Serializer | `apps/platform/serializers.py:ProvisionOrgSerializer` | Input contract. Password `min_length=12`. `sanitize_text` en text fields. Pre-DB duplicate checks (username/email/org name case-insensitive). `validate_password` Django (common-password, numeric-only). |
| Service | `apps/platform/services/provision_organization.py:provision_organization` | Orquestación autoritativa. `@transaction.atomic`. Crea `Organization` → signals → `User(role='ADMIN', is_staff=False, is_superuser=False)` → signals → `UserRole.update_or_create(defaults={'assigned_by': actor})` para backfill audit. Post-condition assert. IntegrityError → ValidationError. |
| View | `apps/platform/views.py:PlatformOrgCreateView` | Thin transport. Extrae `X-Request-ID` o genera uuid4. Delega 100% al service. Response 201 con `public_id`s, JAMÁS password. |
| URL | `POST /api/platform/organizations/` | Namespace `/api/platform/` distinguido de `/api/` tenant-scoped. |
| Throttle | `platform_org_create` = `20/hour` (`ScopedRateThrottle`) | Operación cara + privilegiada. |

### Flujo runtime

```
1. POST /api/platform/organizations/  con Bearer JWT de ADMIN_SAAS
   ├─ IsPlatformOperator (403 si no ADMIN_SAAS)
   ├─ ScopedRateThrottle (429 si > 20/h)
   ├─ ProvisionOrgSerializer.is_valid (400 si duplicate / password weak / sanitize empty)
   ├─ provision_organization() dentro de @transaction.atomic:
   │   ├─ Organization.create()
   │   │   └─ post_save signal: initialize_organization
   │   │       ├─ OrganizationSettings con defaults
   │   │       ├─ Owner('Público General') + Pet('Paciente Anónimo') genéricos
   │   │       └─ _seed_roles_for_org → Role(ADMIN/VET/ASSISTANT, is_system_role=True)
   │   ├─ User.create_user(role='ADMIN', is_staff=False, is_superuser=False)
   │   │   └─ post_save signal: assign_rbac_role_on_create
   │   │       └─ UserRole.get_or_create(user, role) [SIN assigned_by]
   │   ├─ admin.password_must_change=True (si require_password_change, default True)
   │   │   └─ Onboarding forzado: primer login pasa por MustChangePasswordGate.
   │   │       SIN password_temp_issued_at → no caduca (cf. reset p21 = 24h). Seeds: False.
   │   ├─ Role.objects.filter(organization, name='ADMIN', is_system_role=True).get()
   │   │   └─ RuntimeError + rollback si DoesNotExist
   │   ├─ UserRole.update_or_create(user, role, defaults={'assigned_by': actor})
   │   │   └─ Backfill del audit field que el signal no captura
   │   ├─ Post-condition: assert UserRole(user, role, assigned_by=actor).exists()
   │   │   └─ RuntimeError + rollback si invariante falla
   │   └─ Log PLATFORM_ORG_PROVISIONED (request_id, actor_*, org_*, admin_*, duration_ms)
   └─ Response 201 {request_id, duration_ms, organization{public_id,...}, admin{public_id,...}}
```

### Invariantes obligatorios

1. **Password floor 12 chars** para admins iniciales SaaS. Justificado por privilegio +
   acceso clínico/financiero. Más estricto que el default `min_length=8` de
   Django's `MinimumLengthValidator`.
2. **Privilege escalation guards**: payload NO puede inyectar `role=ADMIN_SAAS`,
   `is_superuser`, `is_staff`. Server fuerza valores seguros independientemente
   del input.
3. **Password JAMÁS en response**. Caller debe registrarlo out-of-band (email,
   secure share). Validado por test `test_password_never_in_response` que escanea
   el body completo en busca del literal.
4. **Atomicity**: cualquier fallo dentro del service rollbackea TODO. Tests
   verifican `Organization.objects.count()`, `User.objects.count()` y
   `UserRole.objects.count()` no cambian post-fallo.
5. **Audit trail**: `UserRole.assigned_by` siempre apunta al actor que provisionó.
   El signal automático lo deja NULL — el service hace `update_or_create` con
   `defaults={'assigned_by': actor}` para backfill.
6. **Onboarding forzado (2026-06-24)**: el admin provisionado se crea con
   `password_must_change=True` (param `require_password_change`, default True) → el
   primer login es forzado por `MustChangePasswordGate` a cambiar la contraseña.
   Sin `password_temp_issued_at` → la temporal **no caduca** (a diferencia del
   reset admin de 24h, ADR p21 addendum). Seeds (demo) pasan
   `require_password_change=False`.

### Anti-patterns prohibidos

1. ❌ Provisionar Org sin User ADMIN en la misma transacción (org huérfana).
2. ❌ Crear el User ANTES de la Org (necesita FK).
3. ❌ Bypass del service desde otros call sites (views directas creando
   Organization+User). Cualquier path nuevo de provisioning debe pasar por
   `provision_organization()`.
4. ❌ Reusar `_is_platform_superuser` del bootstrap como permission class para
   endpoints platform. Conceptualmente distintos — el bootstrap valida identidad
   env-driven; el operator valida sesión actual.
5. ❌ Exponer este endpoint en `/api/` (tenant scope). Debe vivir en `/api/platform/`.

## Trade-offs aceptados

| Trade-off | Justificación |
|---|---|
| App separada (más código boilerplate) | Boundary explícito previene coupling tenant↔platform. Coupling fuerte aparece en sprints futuros si comparten app. |
| Password requerido en payload (no auto-generado) | Auto-generación requiere SMTP infra que no existe pre-beta. Admin SaaS provee password, lo envía out-of-band. |
| Sin idempotency key | Diferido a `POST-BETA-005`. Validaciones pre-DB de duplicados mitigan ~95% pre-beta. Throttle bajo limita blast radius. |
| Sin endpoint LIST de orgs | Out-of-scope para este PR. Separado para limitar blast radius. |
| Sin endpoint UPDATE/DELETE de orgs | DELETE bloqueado por ADR-15 (CASCADE → PROTECT). UPDATE requiere políticas de billing/SaaS no definidas pre-beta. |
| Test runner gotcha en Windows | Stdlib `platform` colisiona con `apps.platform`. Workaround: listar test modules con full path en lugar de `apps.platform`. Documentado en CLAUDE.md. |
| **CORS gotcha**: `X-Request-ID` debe estar en `CORS_ALLOW_HEADERS` | Sin esto, browser hace OPTIONS preflight 200 pero rechaza el POST silenciosamente. Ver runbook `password-change.md` § "Infrastructure gotchas". Aplica a TODOS los endpoints que reciben `X-Request-ID` (p19, p20, p21). |

## Componentes acoplados (mapa)

```
apps/platform/
├── services/provision_organization.py
│   ├── apps.organizations.models.Organization              (FK destination)
│   ├── apps.organizations.signals.initialize_organization  (implícito vía post_save)
│   ├── apps.users.models.User (get_user_model)             (FK destination)
│   ├── apps.users.signals.assign_rbac_role_on_create       (implícito vía post_save)
│   └── apps.core.models.Role, UserRole                     (RBAC primary)
└── (sin imports de billing, medical_records, appointments, inventory)
```

`platform → organizations/users/core` solamente. Cualquier import nuevo desde
`platform` hacia los módulos de dominio (`medical_records`, `billing`,
`appointments`) debe pasar por revisión arquitectónica — sugiere que la lógica
no pertenece a `platform`.

## Tests

48 tests across 4 modules:

- `apps/platform/tests/test_provision_service.py` (14): happy path, signals,
  RBAC backfill, atomicity, rollback con count invariants, IntegrityError race,
  RuntimeError post-condition, logs estructurados.
- `apps/platform/tests/test_view_auth.py` (8): permission matrix completa
  (ADMIN_SAAS / ADMIN / VET / ASSISTANT / unauth / degradados).
- `apps/platform/tests/test_view_validation.py` (19): privilege escalation
  guards, duplicates pre-DB, password floor 12, password validators Django,
  password no en response, tax_rate range, sanitize_text behaviors.
- `apps/platform/tests/test_view_integration.py` (7): E2E login del admin
  provisionado, RBAC permissions completos, `/me/` endpoint, `X-Request-ID`
  propagation, throttle scope (con `mock.patch.object(ScopedRateThrottle,
  'get_rate', ...)` por collision con DRF api_settings cache).

## Deuda diferida

- **POST-BETA-005** — `X-Idempotency-Key` support. Diseño tentativo + sprint
  estimado en `docs/day6/POST-BETA-DEBT.md`.
- **Frontend dedicado** — página `/platform/organizations/new` solo visible
  para `role === 'ADMIN_SAAS'`. PR separado, posterior al backend stable.
- **Endpoint LIST de orgs** — `GET /api/platform/organizations/` con filtros
  + paginación. PR separado.
- **Endpoint suspend/reactivate org** — políticas + billing state. ADR aparte
  cuando se diseñe billing SaaS.
- **Hardening throttle fase 2** — `IPRateThrottle` adicional + Sentry alerting
  en `PLATFORM_ACCESS_DENIED` repetidos por IP.

## Refs

- CLAUDE.md ADR-16
- `docs/modules/platform.md`
- `docs/runbooks/platform-org-provisioning.md`
- `docs/day6/POST-BETA-DEBT.md` (entrada POST-BETA-005)
