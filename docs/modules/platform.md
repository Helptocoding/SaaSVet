# Modulo: Platform (cross-tenant SaaS operations)

## Objetivo

Aloja la infraestructura de operaciones de plataforma (SaaS-wide) que **no
pertenece al dominio de ninguna clínica individual**:

- Provisioning de nuevos tenants (Organization + admin inicial).
- Lifecycle de tenants (futuro: suspend, reactivate, billing state).
- Herramientas de soporte / ops (futuro: impersonación controlada, health
  dashboard, métricas SaaS).

## Boundary regla

```
ALLOWED:     platform → organizations, users, core
PROHIBITED:  organizations → platform
             users → platform
             cualquier módulo de dominio → platform
```

`apps/platform/` puede leer modelos de `organizations`/`users`/`core`.
Los módulos de dominio (tenant-scoped) jamás importan de `platform`. Esto
mantiene `platform` como capa periférica y previene coupling fuerte.

Cualquier feature nueva que requiera importar desde `platform` hacia
`medical_records` / `billing` / `appointments` / `inventory` es una señal
de que la lógica está en el lado equivocado.

## Estructura

```
backend/apps/platform/
├── apps.py                 # PlatformConfig + docstring de dominio
├── permissions.py          # IsPlatformOperator
├── serializers.py          # ProvisionOrgSerializer
├── views.py                # PlatformOrgCreateView (thin)
├── urls.py                 # Mount: /api/platform/
├── services/
│   └── provision_organization.py
└── tests/
    ├── test_provision_service.py
    ├── test_view_auth.py
    ├── test_view_validation.py
    └── test_view_integration.py
```

## Endpoints

### `POST /api/platform/organizations/`

Provisión de tenant + admin inicial.

**Autenticación:** Bearer JWT de un usuario con `role='ADMIN_SAAS'`
(`is_superuser=True` + `is_staff=True`).

**Throttle:** `20/hour` por actor (`ScopedRateThrottle`, scope
`platform_org_create`).

**Headers opcionales:**
- `X-Request-ID: <uuid>` — correlation id propagado a logs + response.
  Si no se provee, el server genera `uuid4`.

  ⚠ **CORS:** `'x-request-id'` debe estar en `CORS_ALLOW_HEADERS`
  (`config/settings.py`). Sin esto, el browser hace OPTIONS preflight
  200 pero rechaza el POST silenciosamente. Detalle completo en
  `docs/runbooks/password-change.md` § "Infrastructure gotchas".

**Request body:**

```json
{
  "name": "Clinica Demo",
  "timezone": "America/Mexico_City",
  "tax_rate": "0.1600",
  "admin_username": "demo_admin",
  "admin_email": "demo@clinica.com",
  "admin_password": "DemoPass1234!",
  "admin_first_name": "Demo",
  "admin_last_name": "Admin"
}
```

**Reglas de validación:**

| Campo | Regla |
|---|---|
| `name` | Required, max 200, `sanitize_text`, unique case-insensitive |
| `timezone` | Default `America/Mexico_City`, `available_timezones()` enforced en `Organization.clean()` |
| `tax_rate` | Decimal entre 0 y 1 (ej. `0.1600` para 16%) |
| `admin_username` | Required, max 150, unique en `auth_user` |
| `admin_email` | Required, valid email, unique case-insensitive |
| `admin_password` | Required, **min_length=12**, Django `validate_password` (no numeric-only, no common-password) |
| `admin_first_name` | Required, max 150, `sanitize_text`, no vacío |
| `admin_last_name` | Required, max 150, `sanitize_text`, no vacío |

**Response 201:**

```json
{
  "request_id": "trace-from-client-001",
  "duration_ms": 142,
  "organization": {
    "public_id": "a3f1c2e4-8b9d-4a7e-9c1f-1234567890ab",
    "name": "Clinica Demo",
    "timezone": "America/Mexico_City",
    "tax_rate": "0.1600"
  },
  "admin": {
    "public_id": "b2e0d3a1-7c8f-4e9d-8a1b-fedcba098765",
    "username": "demo_admin",
    "email": "demo@clinica.com"
  }
}
```

**Importante:** el `admin_password` jamás se incluye en el response. El
operador SaaS debe transmitir la credencial al admin de la clínica out-of-band
(email seguro, secure share, etc.).

**Response 400** (validation):
```json
{
  "code": "validation_error",
  "errors": {
    "admin_password": ["Asegúrese de que este campo tenga al menos 12 caracteres."]
  }
}
```

**Response 401** (sin auth) / **403** (auth pero no ADMIN_SAAS).

**Response 429** (throttle excedido).

### Privilege escalation guards

El payload **NO puede** inyectar valores privilegiados — incluso si el body
los contiene, el server fuerza:

```python
role='ADMIN'           # nunca ADMIN_SAAS
is_staff=False         # nunca True
is_superuser=False     # nunca True
```

Tests `test_payload_cannot_inject_*` validan esto explícitamente.

## Side effects al crear una Organization

El service ejecuta dentro de `@transaction.atomic` la siguiente cadena:

```
Organization.create()
└─ post_save signal → organizations.signals.initialize_organization
   ├─ OrganizationSettings con defaults
   ├─ Owner('Público General', is_generic=True)
   ├─ Pet('Paciente Anónimo', is_generic=True)
   └─ Role(name in ['ADMIN','VET','ASSISTANT'], is_system_role=True)
      con permisos derivados de PERMISSION_CODES

User.create_user(role='ADMIN', organization=org)
└─ post_save signal → users.signals.assign_rbac_role_on_create
   └─ UserRole.get_or_create(user, role) [SIN assigned_by]

provision_organization service hace:
└─ UserRole.update_or_create(user, role, defaults={'assigned_by': actor})
   para backfill del audit field que el signal no captura.
```

Cualquier fallo en cualquier paso → rollback completo. Tests con
`Organization.objects.count()` antes/después validan el invariante.

## Permissions

### `IsPlatformOperator`

Predicado:
```python
user.is_authenticated
AND user.is_superuser is True
AND user.is_staff is True
AND user.role == 'ADMIN_SAAS'
```

**Semánticamente distinto** del predicado `_is_platform_superuser` en
`apps/users/apps.py` (bootstrap signal). El bootstrap valida identidad
env-driven (email match). El operator valida la sesión activa. Mantenerlos
separados permite que diverjan cuando se agregue impersonation, billing,
support tooling.

## Logging

Logger: `platform.events` (handler stdout en Railway, agregable por Sentry).

### Eventos

| Evento | Nivel | Cuándo |
|---|---|---|
| `PLATFORM_ORG_PROVISIONED` | INFO | Provisioning exitoso |
| `PLATFORM_ORG_PROVISION_RACE` | WARNING | IntegrityError post-validación (race) |
| `PLATFORM_ORG_PROVISION_RBAC_MISSING` | CRITICAL | Role ADMIN ausente tras signal — bug en seed |
| `PLATFORM_ORG_PROVISION_POSTCOND_FAILED` | CRITICAL | Post-condition UserRole no satisfecha |
| `PLATFORM_ACCESS_DENIED` | WARNING | IsPlatformOperator rechazó request |

### Fields estructurados

Todos los eventos incluyen:
- `event` (mismo string que `msg`)
- `request_id`
- `actor_id`, `actor_username`, `actor_email`, `actor_role`

Eventos de provisioning incluyen además:
- `org_id`, `org_public_id`, `org_name`
- `admin_user_id`, `admin_user_public_id`, `admin_username`
- `duration_ms`

Útiles para queries en agregador de logs:
```
event=PLATFORM_ORG_PROVISIONED AND duration_ms > 1000
event=PLATFORM_ACCESS_DENIED AND actor_role=ADMIN
event=PLATFORM_ORG_PROVISION_RACE
```

## Throttling

```python
# config/settings.py
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['platform_org_create'] = '20/hour'
```

Scope aplicado vía `ScopedRateThrottle` con `throttle_scope = 'platform_org_create'`
en la view. Aplicado por actor (no por IP) — un ADMIN_SAAS no puede provisionar
más de 20 orgs por hora.

**Hardening fase 2 (POST-BETA):** agregar `IPRateThrottle` adicional + alerting
Sentry en bursts de `PLATFORM_ACCESS_DENIED` mismo IP.

## Tests

Ver `apps/platform/tests/`. 48 tests across 4 modules.

**Workaround test runner Windows + Python 3.13:** stdlib `platform` colisiona
con `apps.platform` en unittest discovery. Listar test modules con full path:

```bash
python manage.py test \
  apps.platform.tests.test_provision_service \
  apps.platform.tests.test_view_auth \
  apps.platform.tests.test_view_validation \
  apps.platform.tests.test_view_integration
```

NO usar `python manage.py test apps.platform` (TypeError en
`_path_normpath`).

## Refs

- ADR p19: `docs/decisions/2026-05-22-p19-platform-org-provisioning.md`
- CLAUDE.md ADR-16
- Runbook: `docs/runbooks/platform-org-provisioning.md`
- Deuda diferida: `docs/day6/POST-BETA-DEBT.md` (POST-BETA-005)
