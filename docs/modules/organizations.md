# Módulo: Organizaciones y usuarios

**Última actualización**: 2026-09-07

> **Ver también:** [`docs/system-operational-flow.md`](../system-operational-flow.md) — mapa operacional cross-módulo (acciones, precondiciones, efectos, invariantes).

## Objetivo

**Orden 2 (28-10-2026):** Organization tiene `is_active`, fecha/actor/motivo de desactivación, y `OrganizationStateAudit` con FK PROTECT. Solo `ADMIN_SAAS` completo opera `POST /api/platform/organizations/<uuid>/deactivate|reactivate/` con `reason`; el tenant no puede editar estado en `/organizations/me/`. Login, refresh, JWT previo, sesiones Django y admisión del worker/sender se bloquean durante desactivación. Se conservan staff, sus flags individuales, trabajos pendientes y política de incertidumbre; reactivar no reactiva un usuario individualmente inactivo ni autonomía cerrada. `GET /api/platform/organizations/<uuid>/history/?page=N` permite a plataforma leer historial de tenant desactivado con scope. `OrganizationTimezoneAudit.organization` PROTECT; organización con configuración, roles, usuarios, genéricos, historia o auditoría no es target físico vacío.

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

O simplemente hacer redeploy — `scripts/release.sh` lo ejecuta antes de iniciar el servidor.

Si `seed_permissions` no se ejecuta, todos los endpoints de la org nueva retornan `403`. El endpoint `POST /api/platform/organizations/` NO depende de esto (corre el seed por org via signal).

**Poda de permisos retirados (deuda B6, orden 6).** Un código que sale de `PERMISSION_CODES` deja de concederse a los roles de sistema en el siguiente seed, pero su fila `Permission` sigue en la base y en cualquier rol propio que la tenga. Para retirarlo, en una ventana de mantenimiento y nunca desde `release.sh`:

```bash
python manage.py seed_permissions --prune --dry-run   # lista lo que se borraría
python manage.py seed_permissions --prune             # borra y registra SEED_PERMISSIONS_PRUNED
```

Nunca poda comodines (`*.*`, `recurso.*`): los gobierna el preflight de ADR p63.

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

**Último acceso (Fase 1 Equipo, 2026-11-23).** `User.last_login` se registra al
iniciar sesión y al renovar la sesión (`/api/token/refresh/`), con
`apps.users.services.record_user_access`: un `UPDATE` condicional de ese único campo,
como máximo una vez por hora (`ACCESS_RECORD_INTERVAL`), nunca para cuentas de
servicio. Solo cuenta un acceso que pasó todas las compuertas: un login rechazado por
contraseña incorrecta, contraseña temporal vencida, organización desactivada o sesión
revocada no lo actualiza. Un error de base se registra (`USER_ACCESS_RECORD_FAILED`) y
no rompe la autenticación. `SIMPLE_JWT['UPDATE_LAST_LOGIN']` sigue apagado a propósito:
escribiría dentro del serializer, antes de esas compuertas, y nunca en el refresh. Los
accesos anteriores a este cambio no se registraron.

### Crear staff

```
POST /api/staff/create/
Authorization: Bearer <token ADMIN>

{
  "username": "dra.garcia",
  "email": "garcia@clinica.com",
  "first_name": "Laura",
  "last_name": "Garcia",
  "role": "VET",
  "specialty": "Cirugia",
  "license_number": "1234567"
}
```

**La contraseña inicial la genera el sistema** (Fase 1 Equipo, 2026-11-23; ADR p21,
addendum 2026-11-23). Enviar `password` es `400` en ese campo: un cliente antiguo no
debe creer que fijó una contraseña. Respuesta `201` con `Cache-Control: no-store`:

```
{ "detail": "Integrante creado.", "request_id": "...",
  "temp_password": "<22 caracteres>", "expires_in_seconds": null,
  "must_change_on_first_login": true, "member": { ...integrante... } }
```

La contraseña tiene la misma fuerza que la temporal del restablecimiento
(`secrets.token_urlsafe(16)`), se devuelve una sola vez, después del commit, y nunca se
registra (`STAFF_CREATED` se emite con `on_commit(robust=True)` y no la lleva). Si la
respuesta se pierde, la vía es Restablecer contraseña.

`first_name` es **obligatorio** también en el backend (plan Equipo, D4). Nombre y apellido siguen la regla de nombres de abajo (§ Editar integrante). `username` es único **sin distinguir mayúsculas**, con el mensaje genérico «Este nombre de usuario no está disponible.» (antes un repetido terminaba en `500`). `specialty`, como máximo 100 caracteres.

`license_number` es la cédula profesional (M01, orden 7; ADR p64): solo dígitos, de 5 a 10, sin verificar contra la SEP. Es **obligatoria para `VET`** y opcional para los demás roles. Hay además un CHECK en base de datos (`user_license_number_digits`). Los errores de validación del serializer vuelven sin el sobre `{code, errors}`; los de una carrera con la restricción de base (usuario o correo tomado entre la validación y la escritura) vuelven con el sobre estándar, en el campo correspondiente y nunca como `500`.

La contraseña es **de un solo uso**: el usuario creado entra con `password_must_change=True` y el sistema lo obliga a cambiarla en el primer login (`MustChangePasswordGate`). Sin `password_temp_issued_at` → no caduca (a diferencia del reset admin de 24h). El flag se setea en `apps.users.services.create_staff_member` (ruta de alta por endpoint), nunca en `User.create_user` ni en signals. Ver ADR p21 (addenda 2026-06-24 y 2026-11-23).

El alta es una unidad: usuario y `UserRole` RBAC se crean en la misma transacción (requiere que `seed_permissions` haya corrido). `create_staff_member` es **durable**, como `reactivate_staff`: debe ser la transacción más externa (lo vigila un gate de llamador único) para que la contraseña no salga antes de un commit que pudiera fallar.

### Listar staff

```
GET /api/staff/                  # activos (lo consume Citas)
GET /api/staff/?archived=true    # inactivos (plan Equipo, D6)
Authorization: Bearer <token ADMIN>
```

Sin parámetros devuelve solo activos, como siempre. `?archived=true` devuelve solo los
inactivos de la clínica, sin `ADMIN_SAAS` ni cuentas de servicio, y exige además
`staff.reactivate` (sin él, `403`): son datos de ex empleados. Cada fila trae
`demo_protected` (ver § Demo); solo sirve a la interfaz y no autoriza nada.

**La forma de cada fila depende de quién pregunta** (Fase 1 Equipo):

| Quién | Recibe |
|---|---|
| Quien gestiona personal (algún permiso `staff.create`, `staff.update`, `staff.destroy`, `staff.reset_password` o `staff.reactivate`; `apps.users.access.can_manage_staff`) | El integrante completo (`UserSerializer`) con su bloque `access` |
| Quien solo tiene `staff.list` (VET y ASSISTANT, para elegir veterinario en Citas) | El directorio mínimo `{id, public_id, first_name, last_name, role}`: sin correo, usuario, cédula, organización ni datos de acceso |

Antes cualquier `staff.list` recibía correo, usuario y cédula de cada colega aunque la
interfaz no los mostrara. El directorio conserva `id` porque Citas envía el PK del
veterinario en el cuerpo de la cita (ADR p18).

**Estado de acceso** (`access`, solo para quien gestiona personal), derivado de campos
existentes sin migración (`apps/users/access.py`):

```
"access": { "status": "...", "last_login": "<ISO>|null", "temp_password_expires_at": "<ISO>|null" }
```

| `status` | Cuándo (gana la primera que se cumple) |
|---|---|
| `inactive` | `is_active=False` |
| `temp_password_expired` | Temporal de restablecimiento o reactivación vencida (misma regla que rechaza el login) |
| `temp_password_active` | Temporal vigente; `temp_password_expires_at` = emisión + 24 h |
| `pending_first_login` | Contraseña inicial del alta y ningún acceso registrado |
| `password_change_pending` | Contraseña inicial y algún acceso registrado: entró y no completó el cambio |
| `active` | Acceso normal |

No se exponen hashes, tokens, `session_version` ni las banderas de contraseña en crudo.
`last_login` vacío significa «sin accesos registrados», no «nunca entró».

### Desactivar usuario

```
DELETE /api/staff/<public_id>/
Authorization: Bearer <token ADMIN>
```

No elimina el usuario: marca `is_active = False`, revoca todos sus refresh tokens e
incrementa su versión de sesión (ADR p65), así que sus access tokens dejan de servir
aunque después se le reactive.

**Una clínica nunca queda sin un ADMIN activo** (plan Equipo, II.3.1). El servicio
bloquea en una sola consulta ordenada por `pk` al actor, al objetivo y, si el objetivo es
ADMIN, a todos los ADMIN activos de la clínica, y vuelve a comprobar con el bloqueo tomado:

| Respuesta | Cuándo |
|---|---|
| `400` | Desactivarse a sí mismo (sin cambios). |
| `403 actor_inactive` | El actor quedó desactivado mientras la operación esperaba (dos ADMIN que se desactivan entre sí: gana uno). |
| `409 last_active_admin` | El objetivo es el último ADMIN activo. Aplica aunque otro rol tenga `staff.destroy` concedido en la base. |
| `403 demo_seed_account` | Cuenta semilla de la demo. |

Recuperación si el único ADMIN olvida su contraseña: restablecimiento de plataforma
(ADR p45). El admin de Django y la shell quedan fuera de esta garantía (vía de operadores).

### Editar integrante (plan Equipo A1; especialidad y cédula desde M01, orden 7)

```
PATCH /api/staff/<public_id>/
Authorization: Bearer <token ADMIN>

{ "first_name": "Laura", "last_name": "de la Cruz", "email": "laura@clinica.com",
  "specialty": "Cirugia", "license_number": "1234567" }
```

Permiso `staff.update` (sensible, solo ADMIN; ADR p63 y p64). Acepta solo esas cinco claves:
cualquier otra (rol, username, contraseña, estado) es `400` con «Solo se pueden editar nombre,
apellido, correo, especialidad y cédula profesional.». Solo se guarda lo que cambia; un valor
igual al actual (el mismo correo con otras mayúsculas) no se guarda ni se registra. Un `VET`
no puede quedar sin cédula. Alcance: la misma organización, usuarios activos, sin `ADMIN_SAAS`
ni cuentas de servicio (fuera de eso, `404`). El ADMIN puede editar también los suyos.
Registra `STAFF_PROFILE_UPDATED` con los nombres de los campos, nunca sus valores.

- **Correo** (ADR p48): se guarda en minúsculas y es único global, incluidos inactivos. Si
  está ocupado, «Este correo no está disponible.» (no revela en qué clínica). Dos ADMIN que
  guardan el mismo correo a la vez: decide el índice `user_email_ci_unique` y quien pierde
  recibe `400` en el campo, nunca `500`. Cambiar el correo **no** cierra sesiones (D2): el
  correo anterior deja de servir para entrar y el username sigue funcionando.
- **Nombres** (D4): se normalizan a Unicode NFC y se recortan los extremos; nada más (sin
  mayúsculas forzadas ni colapso de espacios). Se aceptan letras latinas por rangos
  explícitos (`A-Z`, `À-Ö`, `Ø-ö`, `ø-ÿ`, `Ā-ž`), espacio, guion y los apóstrofos ' y ’. El
  nombre es obligatorio; el apellido puede quedar vacío. El backend es la autoridad; el
  frontend replica la regla solo para avisar. Tabla de ejemplos (contrato compartido por
  `apps/users/tests/test_staff_profile_edit.py` y `frontend/src/pages/staff.test.jsx`):

  | Entrada | Resultado |
  |---|---|
  | `María José`, `Argüelles`, `María-José`, `O'Brien`, `D’Angelo`, `de la Cruz`, `Zoë`, `Łukasz` | Se acepta tal cual |
  | `José` en NFD | Se guarda en NFC |
  | `  Ana  ` | Se guarda `Ana` |
  | `Ana  Luz` | Se guarda igual, sin colapsar |
  | `Juan2`, `Ana 😀`, `Аna` (A cirílica), `Ana_Luz`, `Ma. José` | Se rechaza |

- **Documentos clínicos:** las consultas y recetas cerradas conservan el nombre, la
  especialidad y la cédula congelados al cierre; las abiertas muestran los datos vivos.

La misma ruta con `DELETE` sigue desactivando (`staff.destroy`): `StaffDetailView` deriva el permiso del método.

### Reactivar integrante (plan Equipo A2)

```
POST /api/staff/<public_id>/reactivate/
Authorization: Bearer <token ADMIN>
```

Permiso `staff.reactivate` (sensible, solo ADMIN; D1). Throttle propio `staff_reactivate`,
10 por hora (D7). Reactiva **la misma cuenta** (mismo PK, `public_id`, rol, cédula,
`UserRole` y relaciones), emite una contraseña temporal de 24 h con cambio obligatorio y
revoca todas las sesiones anteriores (refresh tokens y versión de sesión, ADR p65). La
contraseña anterior deja de servir.

Responde `201` con la misma forma que el restablecimiento (`temp_password`,
`expires_in_seconds`, `must_change_on_first_login`, `request_id`, `duration_ms`) más
`member`, y `Cache-Control: no-store`. Si ya está activo, `409 already_active` (también tras
una respuesta perdida: usar Restablecer contraseña). Otra clínica, cuenta de servicio o
`ADMIN_SAAS`: `404`. Un VET sin cédula se puede reactivar; no podrá firmar hasta capturarla (D9).

**Restricción de `durable=True`:** `apps.users.services.reactivate_staff` debe ser la
transacción más externa. Llamado dentro de otra transacción lanza `RuntimeError` antes de
escribir nada, porque si no el commit ocurriría después de devolver la contraseña. Hoy solo lo
llama `StaffReactivateView` (lo vigila un gate de pruebas); una reactivación masiva, un comando
o una acción de admin futuros tendrán que llamarlo fuera de cualquier transacción. El evento
`STAFF_REACTIVATED` se emite con `on_commit(robust=True)`: no hay evento de una reactivación
revertida y un fallo del aviso no convierte en error una reactivación ya confirmada.

### Restablecer contraseña (ADR p21)

`POST /api/staff/<public_id>/reset-password/` responde con `Cache-Control: no-store` (plan
Equipo, D11): el cuerpo lleva una contraseña temporal. Además de revocar los refresh tokens,
incrementa la versión de sesión (ADR p65). Cuentas semilla de la demo: `403 demo_seed_account`.

## Endpoints de Organization (PR-4B / ADR p16, p18)

### Singleton — recomendado

```
GET   /api/organizations/me/
PATCH /api/organizations/me/
Authorization: Bearer <token ADMIN>
```

Devuelve/actualiza la organizacion del usuario autenticado sin exponer el PK en la URL. Forma canonica desde PR-4B.

**Día 6 (ADR p18):** `Organization` ahora tiene campo `public_id` (UUID v4). El response de `/me/` expone tanto `id` (PK, retrocompat pre-beta) como `public_id` (UUID). Frontend nuevo debe consumir `public_id` o `organization_public_id` desde `MeView`. Cleanup post-beta: ticket `POST-BETA-001`.

### Legacy — retirado

`GET/PATCH /api/organizations/<pk>/` se retiró en el orden 6 (deuda D2), tras su Sunset RFC 8594 del 17-08-2026. La ruta ya no existe y responde 404. Usar `/api/organizations/me/`.

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

### Teléfono de la clínica — validación real (regla compartida)

`Organization.phone` no es un campo cosmético: es el número que el agente de
WhatsApp pone en su **plantilla de urgencia** y la señal del hito
`has_clinic_contact` del onboarding (`GET /api/v1/dashboard/activation/`).

La regla vive en **`apps/core/validators.py`** (dueño único) y la consumen
`OrganizationSerializer.validate_phone` y `OwnerSerializer.validate_phone`:

| Capa | Regla |
|---|---|
| Formato | Normaliza a dígitos; exige exactamente **10** (México-only, misma decisión Q5 que `agent.services.normalize_wa_id`) |
| Relleno evidente | Rechaza todos los dígitos iguales (`1111111111`) y secuencias triviales (`1234567890`, `9876543210`) |
| Vacío | `Organization.phone` lo permite (`allow_blank=True` — la org nace sin él y el ADMIN debe poder guardar el resto de la sección). `Owner.phone` **no** (alta manual siempre exige teléfono) |

**Lo que NO pasa nunca**: un valor no vacío que no normaliza. Antes
`validate_phone` solo quitaba los no-dígitos, así que `"5"` se guardaba como `"5"`
y `"no sé"` se guardaba como `""` **en silencio** — el ADMIN creía haber capturado
el dato. Por eso arriba basta con `bool(phone)`: si el campo no puede contener
basura, *existir* equivale a *ser válido*.

**Límite honesto**: sube el piso de "cualquier cosa" a "plausible". Un número
válido pero equivocado pasa igual; la única prueba real sería un OTP (fuera de
alcance). Residual asumido.

**Deuda contenida** (no ampliar sin ADR): el registro rápido de citas
(`appointments/views.py`) y `PetSerializer.validate` conservan su propio chequeo
inline de 10 dígitos (sin rechazo de relleno) — escriben `Owner` por rutas que no
pasan por `OwnerSerializer`. `validate_whatsapp` sigue siendo el stripper viejo.

**Verificación antes de desplegar** (las orgs sin teléfono verán el overlay de
onboarding al siguiente login):

```python
Organization.objects.filter(phone='').values_list('name', flat=True)
```

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

Las 7 filas las siembra el signal `initialize_organization`
(`create_default_schedule`: L-V 9-18, sáb 9-14, dom cerrado) al crear la
organización, y `ensure_schedule_integrity` repara las que falten al leer o
escribir el horario. Una org creada **antes** de la migración `0011` puede no
tenerlas hasta que alguien abra Configuración.

> **⚠️ Consumidor externo: el agente de WhatsApp (ADR p54).**
> `OrganizationSchedule` es la **fuente única** del horario para el agente:
> los huecos que ofrece a los clientes, el "¿está abierta ahora?" y el aviso de
> fuera de horario salen de aquí (vía `agent/clinic_context.py`). Igual para
> `Organization.phone`, que es el número que aparece en su **plantilla de
> urgencia**.
>
> El campo espejo `AgentSettings.business_hours` **se eliminó** justamente para
> que no hubiera dos superficies escribiendo el mismo dato. Al cambiar este
> modelo o sus validaciones, el agente es un consumidor a considerar:
> `is_closed` en los 7 días significa "cerrada toda la semana" (el agente lo
> dice), mientras que **cero filas** significa "sin configurar" (el agente
> calla en vez de inventar un horario).

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
| `require_confirmation_before_start`| `false` | La cita debe confirmarse antes de iniciar                     |
| `allow_anonymous_walkin`           | `false` | Permite walk-in sin mascota registrada                        |
| `show_status_change_history`       | `true`  | Muestra historial de cambios de estado en citas               |
| `require_open_cash_session`        | `false` | Si `True`, `post_checkout(..., pay=True)` / `pay_invoice` exigen una caja abierta del actor. |
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

**Equipo en la demo (plan Equipo, D5):**

- Las tres cuentas semilla (`apps.core.demo_reset.DEMO_SEED_USERNAMES`) no se editan,
  restablecen ni desactivan por la API: `403 demo_seed_account`. Se identifican por
  `organization.is_demo` **y** el username semilla, la misma clave que usa el seed. El
  username no se puede cambiar por la API, y los semilla llevan `@`, que el alta no admite.
- Alta y edición en la demo solo aceptan correos de dominios reservados (`example.com`,
  `example.net`, `example.org`, `*.test`, `*.example`): «En la demo usa un correo de
  ejemplo, como nombre@example.com.». Así ningún visitante inutiliza un correo real.
- **Restricción operativa (riesgo R7):** las cuentas semilla **no** deben renombrarse ni
  modificarse manualmente desde el admin de Django. Renombrarlas les quita la protección y
  el reset de la demo deja de reconocerlas.

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
- `DEPRECATED_ENDPOINT_HIT` — uso de un endpoint deprecado vigente (logger `core.deprecation`; ver `logs.md`)

Corte del fallback (deuda B3): **aplazado** en el orden 6. El gate de 7 dias de logs no es alcanzable sin produccion. Cuando se retome, `User.role` se conserva como etiqueta y deja de autorizar (ver [plan del orden 6](../plan-remediacion-orden-6-2026-11-11.md), §1).

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

Para desactivar una organización: `POST /api/platform/organizations/<uuid>/deactivate/` con motivo (orden 2; ver el inicio de este documento). No marcar `is_active=False` a mano: el servicio `organizations/state.py` deja el `OrganizationStateAudit` y la fecha, el actor y el motivo. Borrar físicamente una organización solo es posible si está vacía, y solo por la vía de plataforma ([platform.md](platform.md)).
