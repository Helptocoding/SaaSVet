# Modulo: Platform (cross-tenant SaaS operations)

> **Ver también:** [`docs/system-operational-flow.md`](../system-operational-flow.md) — mapa operacional cross-módulo (acciones, precondiciones, efectos, invariantes).

## Objetivo

Aloja la infraestructura de operaciones de plataforma (SaaS-wide) que **no
pertenece al dominio de ninguna clínica individual**:

- Provisioning de nuevos tenants (Organization + admin inicial).
- Lifecycle de tenants: desactivar y reactivar organizaciones, archivar sujetos y borrado físico excepcional (orden 2, 28-10-2026). El estado de facturación del tenant sigue como futuro.
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

**Excepciones (orden 2, 28-10-2026):**

- El borrado físico y el historial de un tenant leen y borran modelos de
  `patients`, `billing`, `medical_records` y `prescriptions`
  (`services/physical_deletion.py`, `deletion_guards.py`, `views.py`). Es la
  única forma de borrar físicamente esos datos, así que no puede vivir en un
  dominio.
- `core/management/commands/seed_demo_clinic.py` importa
  `deletion_guards.demo_purge_authorized` y `provision_organization` para el
  reset de la demo (ADR p49).

Ningún módulo de dominio importa `platform`.

## Estructura

```
backend/apps/platform/
├── apps.py                 # PlatformConfig + docstring de dominio
├── permissions.py          # IsPlatformOperator
├── serializers.py          # ProvisionOrgSerializer
├── models.py               # PhysicalDeletionReceipt (orden 2)
├── deletion_guards.py      # bloquea borrados ORM fuera de la vía autorizada (orden 2)
├── views.py                # alta, reset, estado de org, archivo, historial y borrado físico (thin)
├── urls.py                 # Mount: /api/platform/
├── services/
│   ├── provision_organization.py
│   ├── platform_reset_password.py    # ADR p45
│   └── physical_deletion.py          # preview/execute (orden 2)
└── tests/
    ├── test_provision_service.py
    ├── test_view_auth.py
    ├── test_view_validation.py
    ├── test_view_integration.py
    └── test_platform_reset_password.py  # 21 tests ADR p45
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
(email seguro, secure share, etc.). Es una **contraseña temporal**: el admin se
crea con `password_must_change=True` y el sistema lo obliga a cambiarla en el
primer login (`MustChangePasswordGate`). No caduca (sin `password_temp_issued_at`,
a diferencia del reset admin de 24h).

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
├─ admin.password_must_change = True   # require_password_change=True (default);
│                                      # primer login forzado (MustChangePasswordGate);
│                                      # SIN password_temp_issued_at → no caduca; seeds: False.
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

Logger: `platform.events` (Docker stdout — ver con `docker compose logs backend`, agregable por Sentry).

### Eventos

| Evento | Nivel | Cuándo |
|---|---|---|
| `PLATFORM_ORG_PROVISIONED` | INFO | Provisioning exitoso |
| `PLATFORM_ORG_PROVISION_RACE` | WARNING | IntegrityError post-validación (race) |
| `PLATFORM_ORG_PROVISION_RBAC_MISSING` | CRITICAL | Role ADMIN ausente tras signal — bug en seed |
| `PLATFORM_ORG_PROVISION_POSTCOND_FAILED` | CRITICAL | Post-condition UserRole no satisfecha |
| `PLATFORM_PASSWORD_RESET_ISSUED` | INFO | Reset de contraseña cross-tenant exitoso (ADR p45) |
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

---

### `POST /api/platform/staff/<public_id>/reset-password/`

Reset de contraseña de cualquier usuario de clínica — cross-tenant. (ADR p45)

**Autenticación:** Bearer JWT de un usuario con `role='ADMIN_SAAS'`.

**Throttle:** `20/hour` por actor (scope `platform_password_reset`).

**Path param:** `public_id` (UUID) del usuario a resetear. Solo usuarios activos,
excluye `role='ADMIN_SAAS'` — si se pasa el UUID de un ADMIN_SAAS (incluido self)
retorna 404 ("404-as-403": no confirmar existencia).

**Request body:** vacío — el server genera la contraseña.

**Response 201:**

```json
{
  "detail": "Contraseña temporal generada.",
  "request_id": "...",
  "duration_ms": 34,
  "temp_password": "K9p_RxA2zVtwQ1f8hQwa3Q",
  "expires_in_seconds": 86400,
  "must_change_on_first_login": true
}
```

**Efectos:**
1. `set_password(temp_password)` en el target.
2. `password_must_change=True` → en el próximo login el `MustChangePasswordGate`
   bloquea todos los endpoints hasta que el usuario cambie la contraseña.
3. `password_temp_issued_at=now()`.
4. Todos los `OutstandingToken` del target quedan blacklisted — sesiones activas
   invalidadas de inmediato.

**Importante:** `temp_password` se devuelve UNA SOLA VEZ en el response 201 y
**jamás se loguea**. El ADMIN_SAAS debe transmitirlo out-of-band al usuario.

**Response 403** — actor no es ADMIN_SAAS.
**Response 404** — target no encontrado, inactivo, o es ADMIN_SAAS.
**Response 429** — throttle excedido.

**Audit log** (`platform.events`): evento `PLATFORM_PASSWORD_RESET_ISSUED` incluye
`target_organization_id` y `target_organization_name` — críticos para trazabilidad
cross-tenant (el actor tiene org de plataforma, no de clínica). Ver ADR p45.

**Caso de uso principal:** ADMIN de clínica olvida su contraseña y no existe
flujo "forgot-password por email" (diferido, requiere SMTP). ADMIN_SAAS resetea
via esta API y comparte la contraseña temporal por canal seguro.

---

### Ciclo de vida del tenant y de sus sujetos (orden 2, 28-10-2026)

Todas exigen `IsPlatformOperator` y usan el throttle `platform_lifecycle`,
salvo el borrado físico, que usa `platform_physical_deletion`.

| Ruta | Qué hace |
|---|---|
| `POST /api/platform/organizations/<uuid>/deactivate/` y `.../reactivate/` | Cambia el estado de la organización con `reason` obligatorio y deja un `OrganizationStateAudit`. Efectos sobre login, refresh, worker y sender en [organizations.md](organizations.md). |
| `GET /api/platform/organizations/<uuid>/history/?page=N` | Clientes y mascotas archivados, facturas y expedientes del tenant, con su `subject_snapshot`, en páginas de 100. Sirve también con la organización desactivada. |
| `POST /api/platform/organizations/<org_uuid>/owners/<uuid>/archive/` (también `restore`, y `pets` en lugar de `owners`) | Mismo servicio que usa la clínica, `patients/archive.py::change_archive_state` ([patients.md](patients.md)). |
| `POST /api/platform/physical-deletions/preview/` | Con `organization_id`, `target_type` (`owner`, `pet` u `organization`), `target_id` y `reason` (8–255 caracteres), devuelve `eligible`, `blockers`, `impact` y una `confirmation` firmada válida 300 s, solo si no hay bloqueos. |
| `POST /api/platform/physical-deletions/execute/` | Con el mismo payload, la `confirmation` y un `idempotency_key` UUID, borra y deja un `PhysicalDeletionReceipt`. Repetir la clave devuelve el mismo recibo. |

Reglas del borrado físico:

- Solo se borra un sujeto ya **archivado**. Bloquean: `target_not_archived`,
  `generic_resource`, `unsupported_import_provenance` (trae `legacy_id` o
  `extra_data` del importador), `unsupported_reference` (cualquier referencia que
  no se pueda separar), `identity_not_preserved` (un documento sin snapshot v1
  válido), `open_medical_record`, `open_checkout` y `pending_payment`.
- Solo se separan, quedando en `NULL`, `Invoice.owner/pet`, `Checkout.customer/pet`,
  `MedicalRecord.pet` y `Prescription.pet`. Cada documento conserva la identidad
  del sujeto en su `subject_snapshot`; eso no es anonimización.
- `execute` vuelve a inspeccionar bajo lock. Si el impacto difiere del firmado,
  si la confirmación venció, es de otro actor u objetivo o ya se usó, responde
  `409 physical_delete_conflict` y no borra nada.
- El recibo guarda UUIDs, no FKs al objetivo, así que sobrevive al borrado.
- `deletion_guards.py` hace fallar cualquier borrado ORM de esos modelos que no
  pase por esta vía o por la purga del reset de la demo.

Pruebas: `platform.tests.test_physical_deletion`,
`test_physical_deletion_hidden_refs` y `test_order2_migrations`. Expediente:
[orden 2](../remediaciones/orden-2/README.md).

---

## Throttling

```python
# config/settings.py
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['platform_org_create'] = '20/hour'
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['platform_password_reset'] = '20/hour'
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['platform_physical_deletion'] = '30/hour'   # orden 2
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['platform_lifecycle'] = '60/hour'           # orden 2
```

Scopes aplicados vía `ScopedRateThrottle`. Aplicados por actor (no por IP).

**Hardening fase 2 (POST-BETA):** agregar `IPRateThrottle` adicional + alerting
Sentry en bursts de `PLATFORM_ACCESS_DENIED` mismo IP.

## Tests

Ver `apps/platform/tests/`. 69 tests across 5 modules.

| Módulo | Tests | Qué cubre |
|---|---|---|
| `test_provision_service.py` | ~20 | Lógica atómica del service de provisioning |
| `test_view_auth.py` | ~8 | Matriz de permisos del endpoint de provisioning |
| `test_view_validation.py` | ~12 | Validación de payload (password floor, privilege-esc guards) |
| `test_view_integration.py` | ~8 | End-to-end: request → org creada → RBAC seedeado |
| `test_platform_reset_password.py` | 21 | ADR p45: auth matrix, lifecycle, audit, throttle |

**Workaround test runner Windows + Python 3.13:** stdlib `platform` colisiona
con `apps.platform` en unittest discovery. Listar test modules con full path:

```bash
python manage.py test \
  apps.platform.tests.test_provision_service \
  apps.platform.tests.test_view_auth \
  apps.platform.tests.test_view_validation \
  apps.platform.tests.test_view_integration \
  apps.platform.tests.test_platform_reset_password
```

NO usar `python manage.py test apps.platform` (TypeError en
`_path_normpath`). `python manage.py test apps` (discovery crudo) SÍ corre la
suite completa pero emite 2 `_FailedTest` espurios (`platform.tests`,
`platform.services`) por la misma colisión — **no son fallas de test**. Deuda de
rename diferida: `docs/deuda/fase4-prioridad-baja.md` C7.

## Refs

- ADR p19: `docs/decisions/2026-05-22-p19-platform-org-provisioning.md`
- ADR p45: `docs/decisions/2026-06-23-p45-platform-operator-password-reset.md`
- CLAUDE.md ADR-16
- Runbook: `docs/runbooks/platform-org-provisioning.md`
- Deuda diferida: `docs/day6/POST-BETA-DEBT.md` (POST-BETA-005)
