# Modulo: Organizaciones y usuarios

> **Ver también:** [`docs/system-operational-flow.md`](../system-operational-flow.md) — mapa operacional cross-módulo (acciones, precondiciones, efectos, invariantes).

## Objetivo

Gestiona las clinicas (tenants), sus usuarios y la configuracion operativa de cada una.

## Roles del sistema

| Rol          | Alcance            | Descripcion                                    |
|--------------|--------------------|------------------------------------------------|
| `ADMIN_SAAS` | Plataforma entera  | Administrador de Vet Care. No pertenece a ninguna clinica. Opera via API platform (`/api/platform/`) o Django admin para casos de recuperacion. |
| `ADMIN`      | Una organizacion   | Administrador de la clinica. Gestiona staff, configuracion y tiene acceso completo a todos los modulos. |
| `VET`        | Una organizacion   | Veterinario. Puede crear y cerrar consultas propias. |
| `ASSISTANT`  | Una organizacion   | Asistente. Acceso limitado segun permisos RBAC configurados. |

## Como el ADMIN_SAAS crea una clinica nueva

No existe un endpoint de API para crear organizaciones desde fuera. El flujo es via Django admin.

### En VPS (produccion)

El ADMIN_SAAS se crea automaticamente en cada deploy si las siguientes variables de entorno estan seteadas:

```
DJANGO_SUPERUSER_USERNAME=admin_saas
DJANGO_SUPERUSER_PASSWORD=TuClave123!
DJANGO_SUPERUSER_EMAIL=admin@vetcare.example.com   # opcional pero recomendado
```

Esto ejecuta `_create_default_superuser` en el signal `post_migrate` de `apps/users/apps.py`.

**Guard anti-escalación (PR-4A / ADR p15):** El signal usa `filter().first()` + predicado `_is_platform_superuser` (requiere `is_superuser=True AND is_staff=True AND role='ADMIN_SAAS' AND email coincide case-insensitive cuando se provee`). Si una clinica registra un VET con el mismo username que `DJANGO_SUPERUSER_USERNAME`, el deploy ya NO escala al VET ni le resetea password — log CRITICAL `SUPERUSER_BOOTSTRAP_SKIPPED` y abort sin mutacion.

Eventos emitidos por el bootstrap:
- `SUPERUSER_BOOTSTRAP_CREATED` (INFO) — superuser nuevo creado
- `SUPERUSER_BOOTSTRAP_SKIPPED` (CRITICAL) — username collision con usuario non-platform
- `SUPERUSER_BOOTSTRAP_RACE_RESOLVED` (WARNING) — race multi-worker resuelto
- `SUPERUSER_BOOTSTRAP_INCOMPLETE_ENV` (WARNING) — solo `USERNAME` o solo `PASSWORD` seteado

### Flujo para crear una clinica nueva

**Recomendado (post ADR p19, 2026-05-22):** usar el endpoint API
`POST /api/platform/organizations/`. Detalles paso-a-paso en el runbook
[`docs/runbooks/platform-org-provisioning.md`](../runbooks/platform-org-provisioning.md)
y especificación técnica en [`docs/modules/platform.md`](platform.md).

Resumen del flujo API:

```bash
# 1. Login como ADMIN_SAAS
curl -X POST https://tu-backend.example.com/api/token/ \
  -d '{"username":"<ADMIN_SAAS>","password":"<pwd>"}' \
  -H "Content-Type: application/json"

# 2. Provisionar org + admin inicial (atomico en una sola llamada)
curl -X POST https://tu-backend.example.com/api/platform/organizations/ \
  -H "Authorization: Bearer <access token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Clinica X",
    "timezone": "America/Mexico_City",
    "tax_rate": "0.1600",
    "admin_username": "clinicax_admin",
    "admin_email": "admin@clinicax.mx",
    "admin_password": "TempPass-Strong-2026!",
    "admin_first_name": "Nombre",
    "admin_last_name": "Apellido"
  }'
```

Ventajas del flujo API vs Django admin manual:
- Atomico — Org + admin + RBAC en una sola transaccion.
- Audit log estructurado (`PLATFORM_ORG_PROVISIONED` con `actor_id`, `request_id`).
- Tests automatizados que cubren todo el ciclo.
- Throttle `20/hour` previene abuse.
- `seed_permissions` se ejecuta automaticamente vía signal (no requiere paso manual).
- Password floor de 12 caracteres + Django validators. El admin se crea con `password_must_change=True` → cambio forzado en el primer login (no caduca; ADR p21 addendum).
- Guards anti privilege-escalation (payload no puede inyectar `role=ADMIN_SAAS`, `is_superuser`, `is_staff`).

**Legacy (Django admin):** El flujo manual via `/admin/` sigue funcionando para casos excepcionales (recuperacion de incidentes, debugging). Pasos:

1. Ir a `https://tu-backend.example.com/admin/` con las credenciales del ADMIN_SAAS
2. **Organizations** → `+ Add` → completar `name`, `timezone`, `tax_rate`
3. **Users** → `+ Add` → completar `username`, `email`, `password`, `organization`, `role='ADMIN'` — **nota:** este alta manual por Django admin **no** setea `password_must_change` (el cambio forzado solo aplica al alta vía API/serializer, no al ORM directo). Setearlo a mano si se desea el gate.
4. Si el signal `_seed_roles_for_org` no corrio (raro), ejecutar `seed_permissions` manualmente

El signal `organizations.signals.initialize_organization` corre en post_save de Organization y crea automaticamente: `OrganizationSettings`, `Owner('Publico General')`, `Pet('Paciente Anonimo')`, y Roles RBAC (ADMIN/VET/ASSISTANT). El admin user es asignado a su UserRole RBAC por el signal `users.signals.assign_rbac_role_on_create`.

### Ejecutar seed_permissions en VPS

Desde SSH al servidor:

```bash
python manage.py seed_permissions
```

O simplemente hacer redeploy — el Procfile lo ejecuta automaticamente antes de iniciar el servidor.

Si `seed_permissions` no se ejecuta, todos los endpoints de la org nueva retornan `403`. El endpoint `POST /api/platform/organizations/` NO depende de esto (corre el seed por org via signal).

## Como el ADMIN_SAAS resetea credenciales de staff (ADR p45)

Cuando el ADMIN de una clínica olvida su contraseña (y no existe "forgot-password"
por email), el ADMIN_SAAS puede resetear la contraseña via API:

```bash
# Reset cross-tenant: no requiere estar en la misma organización
POST /api/platform/staff/<public_id>/reset-password/
Authorization: Bearer <JWT ADMIN_SAAS>
(body vacío)

→ 201 { "temp_password": "...", "expires_in_seconds": 86400, "must_change_on_first_login": true }
```

El `temp_password` se devuelve **una sola vez** y **nunca se loguea** — debe
transmitirse out-of-band (Slack DM, llamada, etc.).

En el próximo login con la contraseña temporal, `must_change_password: true` en
el JWT obliga al usuario a cambiar contraseña antes de poder usar cualquier
endpoint (`MustChangePasswordGate`).

**Restricciones:**
- Funciona para ADMIN, VET, ASSISTANT de cualquier clínica.
- NO funciona para otros ADMIN_SAAS (retorna 404).
- Throttle `20/hour` por actor.
- Revoca todos los tokens activos del target.

Ver detalles completos en [`docs/modules/platform.md`](platform.md) §
`POST /api/platform/staff/<public_id>/reset-password/` y ADR p45.

---

## Como el ADMIN de una clinica gestiona su equipo

Una vez que el ADMIN tiene credenciales, todo lo demas es via API.

### Login

```
POST /api/token/
{ "username": "<correo O username>", "password": "..." }
→ { "access": "...", "refresh": "..." }
```

**Identidad de login (ADR p48).** El campo `username` del request acepta **el
correo O el username**. Si contiene `@`, el backend lo resuelve por correo
(case-insensitive, solo usuarios activos) al username canónico antes de
autenticar; si no, autentica por username. Sin match → 401 genérico (sin oráculo
de enumeración). El SPA etiqueta el campo como "Correo o usuario".

Invariante de identidad:
- **El correo es identidad global única** (índice parcial `Lower(email)` único,
  `WHERE email <> ''`). **Un usuario = una clínica**; no existe identidad
  multi-clínica (una persona en dos clínicas usa dos cuentas con dos correos).
- **El correo es obligatorio, normalizado a minúsculas y único** en todo flujo
  de negocio (provisioning + alta de staff, vía serializers). Ningún flujo normal
  crea usuarios sin correo.
- Excepción: cuentas técnicas (superuser CLI, demo, seeds, fixtures) pueden tener
  correo vacío — el índice es parcial. No son usuarios de clínica.
- `username` se conserva como identidad interna estable (auditoría, throttle,
  logs); no es lo que el usuario necesita conocer para entrar.

### Crear staff

```
POST /api/staff/create/
Authorization: Bearer <token ADMIN>

{
  "username": "dra.garcia",
  "email": "garcia@clinica.com",
  "password": "Clave1234!",
  "first_name": "Laura",
  "last_name": "Garcia",
  "role": "VET",
  "specialty": "Cirugia"
}
```

Validaciones de password: minimo 8 caracteres, al menos una mayuscula, al menos un numero.

La contraseña es **temporal de un solo uso**: el usuario creado entra con `password_must_change=True` y el sistema lo obliga a cambiarla en el primer login (`MustChangePasswordGate`). Sin `password_temp_issued_at` → no caduca (a diferencia del reset admin de 24h). El flag se setea en `CreateEmployeeSerializer.create` (ruta de alta por endpoint), nunca en `User.create_user` ni en signals. Ver ADR p21 (addendum 2026-06-24).

La asignacion de `UserRole` RBAC ocurre automaticamente al crear el usuario (requiere que `seed_permissions` haya corrido).

### Listar staff

```
GET /api/staff/
Authorization: Bearer <token ADMIN>
```

### Desactivar usuario

```
DELETE /api/staff/<id>/
Authorization: Bearer <token ADMIN>
```

No elimina el usuario, marca `is_active = False`.

## Endpoints de Organization (PR-4B / ADR p16, p18)

### Singleton — recomendado

```
GET   /api/organizations/me/
PATCH /api/organizations/me/
Authorization: Bearer <token ADMIN>
```

Devuelve/actualiza la organizacion del usuario autenticado sin exponer el PK en la URL. Forma canonica desde PR-4B.

**Día 6 (ADR p18):** `Organization` ahora tiene campo `public_id` (UUID v4). El response de `/me/` expone tanto `id` (PK, retrocompat pre-beta) como `public_id` (UUID). Frontend nuevo debe consumir `public_id` o `organization_public_id` desde `MeView`. Cleanup post-beta: ticket `POST-BETA-001`.

### Legacy — deprecado

```
GET   /api/organizations/<pk>/
PATCH /api/organizations/<pk>/
```

Mantenido por retrocompat hasta **2026-08-17** (RFC 8594 Sunset). Reglas:
- `pk == request.user.organization_id` valida explicitamente — si no calza, **404** (no devuelve silenciosamente "tu org")
- Headers en TODO response: `Deprecation: true`, `Sunset: Mon, 17 Aug 2026 23:59:59 GMT`, `Link: </api/organizations/me/>; rel="successor-version"`
- Cada hit emite log `DEPRECATED_ENDPOINT_HIT` para tracking de adopcion
- **Post-Sunset (>2026-08-17): responde 410 Gone automaticamente** via `_EndpointSunsetException` raised en `initial()`

### Removidos

`list`, `create`, `destroy` ya no existen — router `DefaultRouter.register('organizations', ...)` removido. GET/POST a `/api/organizations/` → 404.

### Admin Django

`OrganizationAdmin.has_delete_permission = False` — la org se desactiva, no se borra (consistencia con `User.organization` PROTECT).

## Nuevos endpoints desde Fase 1 (ADR p53)

### Horario semanal

```
GET  /api/organizations/schedule/
PUT  /api/organizations/schedule/
Authorization: Bearer <token ADMIN>
```

`GET` devuelve las 7 filas del horario semanal (lunes=1 a domingo=7). `PUT` recibe
exactamente 7 objetos con los campos `weekday`, `is_closed`, `opens_at`, `closes_at`,
`has_break`, `break_start`, `break_end`. Solo `ADMIN` puede escribir.

Reglas del endpoint:
- exige exactamente 7 elementos con weekdays 1-7 sin duplicados
- persiste todo dentro de `transaction.atomic()`
- si cualquier fila falla validacion, no guarda nada
- el backend ordena por `weekday`

### Lectura agregada de configuracion

```
GET /api/settings/configuration/
```

Devuelve la configuracion completa de la clinica en una sola llamada: organizacion
(identidad, contacto, ubicacion), settings (reglas operativas) y schedule (horario
semanal). La respuesta incluye los campos nuevos de Fase 1.

### Horario por dia — modelo `OrganizationSchedule`

Cada fila representa un dia de la semana:

| Campo | Tipo | Descripcion |
|-------|------|-------------|
| `weekday` | PositiveSmallInteger (1-7) | Lunes=1 ... Domingo=7 |
| `is_closed` | Boolean | `True` = cerrado |
| `opens_at` | Time (nullable) | Hora de apertura |
| `closes_at` | Time (nullable) | Hora de cierre |
| `has_break` | Boolean | `True` = tiene descanso |
| `break_start` | Time (nullable) | Inicio del descanso |
| `break_end` | Time (nullable) | Fin del descanso |

Validaciones:
- si `is_closed=True`: todos los horarios deben ser `null`
- si `is_closed=False`: `opens_at` y `closes_at` obligatorios, `opens_at < closes_at`
- si `has_break=True`: `break_start` y `break_end` obligatorios, dentro del horario
- un solo bloque de apertura y un solo descanso por dia en Fase 1

## Configuracion de la clinica

```
GET  /api/organizations/settings/
PATCH /api/organizations/settings/
Authorization: Bearer <token ADMIN>
```

Toggles disponibles:

| Campo                              | Default | Descripcion                                                   |
|------------------------------------|---------|---------------------------------------------------------------|
| `auto_create_medical_record`       | `false` | Crea consulta automaticamente al completar una cita           |
| `auto_create_invoice_on_done`      | `false` | Crea factura draft al marcar cita como completada             |
| `require_confirmation_before_start`| `false` | La cita debe confirmarse antes de iniciar                     |
| `allow_anonymous_walkin`           | `false` | Permite walk-in sin mascota registrada                        |
| `show_status_change_history`       | `true`  | Muestra historial de cambios de estado en citas               |
| `require_open_cash_session`        | `false` | Si `True`, `pay_invoice` / `pay_direct_sale` exigen una caja abierta del actor (ADR p28). |
| `locale`                           | `es-MX` | Locale del sistema                                            |
| `currency_code`                    | `MXN`   | Codigo de moneda ISO-4217                                     |
| `default_appointment_duration_minutes` | `30` | Duracion sugerida al crear citas nuevas. No modifica citas existentes. |
| `appointment_buffer_minutes`       | `0`     | Intervalo entre citas                                         |
| `allow_emergency_walkin`           | `false` | Permite urgencias sin cita                                    |
| `week_starts_on`                   | `1`     | Primer dia de la semana (1=lunes, 7=domingo)                  |

Campos desde Fase 1 (ADR p53):
- `locale` (default `es-MX`)
- `currency_code` (default `MXN`)
- `default_appointment_duration_minutes` (default `30`)
- `appointment_buffer_minutes` (default `0`)
- `allow_emergency_walkin` (default `False`)
- `week_starts_on` (default `1`)

`default_appointment_duration_minutes` solo define el valor sugerido al crear nuevas
citas; no modifica citas existentes ni reorganiza la agenda automaticamente.

Ver ADR `2026-04-28-organization-settings-toggles.md` para el racional de cada toggle.
Ver ADR `2026-05-27-p28-cash-session-cierre-z.md` para el toggle de caja.
Ver ADR `2026-07-21-p53-clinic-configuration-aggregates.md` para la separacion de
agregados y la Fase 1 de configuracion de clinica.

## Tenant demo (`is_demo`) y su reset automático (ADR p49)

La demo pública del SaaS es **una `Organization` real marcada `is_demo=True`** (no
es otra base ni mocks: es un tenant más, aislado por multitenancy).
`Organization.is_demo` es la **única autoridad** para las operaciones destructivas
del demo — nunca se opera por nombre.

### Reset automático cada 30 min

Un cron (`scripts/crontab.example`, `10,40 * * * *`) corre
`seed_demo_clinic --reset --yes`, que deja la org demo en su estado inicial **sin
tocar ninguna otra clínica**:

- **Atómico**: purge + rebuild en una sola `transaction.atomic` (MVCC oculta el
  estado intermedio; un crash hace ROLLBACK total → la demo nunca queda a medio
  borrar).
- **Exclusión mutua**: `pg_try_advisory_xact_lock` no bloqueante — si otro reset
  corre, sale 0 sin tocar nada (no se encolan disparos).
- **Validación inline** pre-commit (conteos mínimos) + log de duración.
- **Cierre del P0**: el purge borra `analytics.MetricAdjustment` (FK PROTECT a
  `Invoice`) **antes** de `Invoice`, además de los snapshots de analytics e
  `ImportJob`. Sin esto, una devolución de un visitante bloqueaba el reset.
- Guards: aborta si hay 0 o >1 orgs `is_demo=True`; exige `--yes`.

Runbook: [`docs/runbooks/demo-seed.md`](../runbooks/demo-seed.md). Diseño completo
y recuperación ante fallo (§12): ADR p49 (`docs/decisions/2026-06-29-p49-demo-tenant-reset.md`).
Benchmark real en prod: purge ~0.4 s · rebuild ~13 s · total ~13 s.

### Ventana de mantenimiento (`DemoResetGate`)

Mientras un reset está en curso, un flag en cache (`demo_reset:in_progress`) hace
que las **escrituras** de usuarios de la org demo reciban **`503` con código
`demo_resetting` + header `Retry-After`**. Las **lecturas** pasan (MVCC sirve un
estado consistente) y los **tenants reales jamás se ven afectados**. El check vive
en `core.permissions._demo_reset_blocks`, embebido en `HybridPermission` (cubre los
endpoints RBAC, que pisan el `DEFAULT_PERMISSION_CLASSES`) y también registrado como
`DemoResetGate` en el default.

### Restricciones de la cuenta demo (`NotDemoAccount`)

Los usuarios demo (credenciales compartidas) **no** pueden cambiar contraseña ni
importar datos (`core.permissions.NotDemoAccount` → 403); el resto de la operación
es normal. `/api/me/` expone `is_demo` para que el frontend oculte esas opciones.

## RBAC — como funciona

El sistema usa `HybridPermission`: primero busca permisos en DB, si no encuentra usa fallback estatico.

```
POST /api/token/ → JWT
→ request llega a endpoint
→ HybridPermission.has_permission()
→ busca UserRole del usuario en DB
→ compara permisos del Role con el permiso requerido por el endpoint
→ permite o deniega
```

Eventos emitidos a stdout (Docker stdout — `docker compose logs backend`):
- `RBAC_ALLOWED_DB` — permiso concedido desde DB
- `RBAC_FALLBACK_ALLOWED` — permiso concedido por fallback (no deberia verse en produccion estable)
- `RBAC_DENIED` — acceso denegado
- `TENANT_MISMATCH_DETECTED` — intento de acceso a datos de otra organizacion
- `DEPRECATED_ENDPOINT_HIT` — uso del legacy `/api/organizations/<pk>/` (logger `core.deprecation`)

Gate para corte del fallback: `RBAC_FALLBACK_ALLOWED` ausente en logs por 7 dias consecutivos → se puede eliminar el campo `User.role`.

**Default DRF (PR-4A / ADR p15):** `REST_FRAMEWORK['DEFAULT_PERMISSION_CLASSES'] = ('rest_framework.permissions.IsAuthenticated',)`. Cualquier vista nueva que olvide declarar `permission_classes` queda cerrada por defecto. Las vistas publicas (`/api/token/`, `/api/token/refresh/`) declaran `AllowAny` explicito.

## Zona horaria por organizacion

Cada organizacion tiene su propia zona horaria. Actualmente solo se soporta Mexico.

Cambiar el timezone:

```
PATCH /api/organizations/me/
Authorization: Bearer <token ADMIN>
{ "timezone": "America/Monterrey" }
```

El cambio queda auditado en `OrganizationTimezoneAudit` con `changed_by` y timestamps del cambio.

Los filtros de fecha en facturas (`paid_on`, `created_on`) respetan la timezone de la organizacion.

## Cascade lockdown (PR-4B / ADR p16)

`User.organization` ahora es `on_delete=PROTECT` (antes CASCADE). Borrar una `Organization` con usuarios asociados lanza `django.db.models.ProtectedError` mapeado a 409 Conflict por el handler global. Justificacion: NOM-024 retencion de datos del prestador + audit trails (`InvoiceAuditLog.changed_by`, `MedicalRecord.closed_by`, etc.).

Para desactivar una organizacion: marcar `is_active=False` (soft-delete real es deuda Fase 2 A5).
