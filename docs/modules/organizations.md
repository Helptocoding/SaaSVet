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
- Password floor de 12 caracteres + Django validators.
- Guards anti privilege-escalation (payload no puede inyectar `role=ADMIN_SAAS`, `is_superuser`, `is_staff`).

**Legacy (Django admin):** El flujo manual via `/admin/` sigue funcionando para casos excepcionales (recuperacion de incidentes, debugging). Pasos:

1. Ir a `https://tu-backend.example.com/admin/` con las credenciales del ADMIN_SAAS
2. **Organizations** → `+ Add` → completar `name`, `timezone`, `tax_rate`
3. **Users** → `+ Add` → completar `username`, `email`, `password`, `organization`, `role='ADMIN'`
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
{ "username": "...", "password": "..." }
→ { "access": "...", "refresh": "..." }
```

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
| `require_open_cash_session`        | `false` | Si `True`, `pay_invoice` / `pay_direct_sale` exigen una caja abierta del actor; el `Payment` se ata a esa sesion (ADR p28). |

Ver ADR `2026-04-28-organization-settings-toggles.md` para el racional de cada toggle.
Ver ADR `2026-05-27-p28-cash-session-cierre-z.md` para el toggle de caja.

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
