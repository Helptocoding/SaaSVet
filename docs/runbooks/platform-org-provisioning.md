# Runbook: Provisionar una nueva clínica

**Audiencia:** ADMIN_SAAS (operadores de plataforma Vet Care).
**Frecuencia esperada:** ad-hoc, manual.
**Tiempo estimado:** 2 minutos.

## Pre-requisitos

- Cuenta `ADMIN_SAAS` activa (creada por el bootstrap signal con
  `DJANGO_SUPERUSER_*` env vars en el VPS).
- Backend `develop` deployed con el endpoint `/api/platform/organizations/`
  habilitado (commits posteriores a 2026-05-22 / ADR p19).
- Datos del cliente listos: nombre de la clínica, timezone, tax_rate,
  credenciales del admin inicial (username, email, nombre, apellido).

## Pasos

### 1. Login como ADMIN_SAAS

```bash
curl -X POST https://tu-backend.example.com/api/token/ \
  -H "Content-Type: application/json" \
  -d '{
    "username": "<tu ADMIN_SAAS username>",
    "password": "<tu ADMIN_SAAS password>"
  }'
```

Response:
```json
{
  "access": "eyJ0eXAi...",
  "refresh": "eyJ0eXAi..."
}
```

Copia el `access` token.

### 2. Acordar credenciales del nuevo admin

Antes de provisionar, ten listas:

| Campo | Reglas |
|---|---|
| `name` | Nombre de la clínica. Único case-insensitive. Sin HTML solo (se sanea). |
| `timezone` | Default `America/Mexico_City`. Lista válida: `zoneinfo.available_timezones()`. |
| `tax_rate` | `0.0000` sin IVA, `0.1600` para 16%, `0.0800` para 8%. |
| `admin_username` | Único. Será el login del admin de la clínica. |
| `admin_email` | Único. Recomendado: del cliente real. |
| `admin_password` | **Mínimo 12 caracteres**. No numeric-only. No common-password (Django validators). Es una **contraseña temporal de un solo uso**: el sistema obliga al admin a cambiarla en el primer login (`password_must_change=True`). No caduca, a diferencia del reset admin de 24h. |
| `admin_first_name`, `admin_last_name` | Nombre completo del admin del cliente. |

### 3. POST al endpoint

```bash
curl -X POST https://tu-backend.example.com/api/platform/organizations/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access token del paso 1>" \
  -H "X-Request-ID: prov-$(date +%s)" \
  -d '{
    "name": "Clinica San Lazaro",
    "timezone": "America/Mexico_City",
    "tax_rate": "0.1600",
    "admin_username": "sanlazaro_admin",
    "admin_email": "admin@sanlazaro.mx",
    "admin_password": "TempPass-2026-Set!",
    "admin_first_name": "Mariana",
    "admin_last_name": "Reyes"
  }'
```

`X-Request-ID` es opcional pero recomendado — permite correlacionar la
operación en logs si surge un incidente.

### 4. Validar response

Esperado: `201 Created` con shape:
```json
{
  "request_id": "prov-1747900000",
  "duration_ms": 187,
  "organization": {
    "public_id": "a3f1c2e4-8b9d-4a7e-9c1f-1234567890ab",
    "name": "Clinica San Lazaro",
    "timezone": "America/Mexico_City",
    "tax_rate": "0.1600"
  },
  "admin": {
    "public_id": "b2e0d3a1-7c8f-4e9d-8a1b-fedcba098765",
    "username": "sanlazaro_admin",
    "email": "admin@sanlazaro.mx"
  }
}
```

Guarda los `public_id` — son los identificadores estables para deep links,
soporte futuro y referencias cruzadas.

### 5. Comunicar credenciales al cliente

**El password JAMÁS aparece en el response.** Envía al cliente por canal
seguro:

- Email cifrado
- Secure share (1Password, Bitwarden)
- Mensaje directo en el sistema de tickets

**NO enviar por Slack/WhatsApp/SMS sin cifrado**.

Plantilla sugerida:
```
Hola Mariana,

Tu clínica "Clinica San Lazaro" ya está activa en Vet Care.

Login: https://tu-frontend.example.com/login
Usuario: sanlazaro_admin
Password temporal: TempPass-2026-Set!

Al iniciar sesión por primera vez, el sistema te pedirá cambiar la contraseña antes de continuar.

Para soporte: soporte@vetcare.example.com
```

### 6. Smoke check (opcional)

Verifica que el admin nuevo puede loguearse:

```bash
curl -X POST https://tu-backend.example.com/api/token/ \
  -H "Content-Type: application/json" \
  -d '{
    "username": "sanlazaro_admin",
    "password": "TempPass-2026-Set!"
  }'
```

Y que tiene permisos completos en su tenant:

```bash
curl https://tu-backend.example.com/api/me/ \
  -H "Authorization: Bearer <access token del paso anterior>"
```

Debe responder con `role: "ADMIN"`, `organization_name: "Clinica San Lazaro"`,
y `permissions` array con todos los códigos (wildcard `*.*`).

**Nota (must-change):** el login del paso anterior responde además con
`must_change_password: true`. El admin está **gateado** hasta cambiar la
contraseña: `/api/me/` y `/api/users/change-password/` responden 200, pero
cualquier otro endpoint devuelve **403** (`MUST_CHANGE_PASSWORD_BLOCKED`) hasta
que complete el cambio. Es el comportamiento esperado, no un error.

## Gotcha CORS — `X-Request-ID`

Si llamas el endpoint desde un browser (frontend dedicado, no curl) y
ves OPTIONS preflight 200 pero NINGÚN POST después en Network DevTools,
verifica que `x-request-id` esté en `CORS_ALLOW_HEADERS` en
`config/settings.py`. Sin esto, el browser permite el preflight pero
rechaza el POST silenciosamente al detectar que el header custom no
está en la lista de allowed headers.

Fix:
```python
CORS_ALLOW_HEADERS = [
    ...existing...,
    'x-request-id',
]
```

Documentado completo en `docs/runbooks/password-change.md` sección
"Infrastructure gotchas".

## Errores comunes

### `403 Forbidden`

```json
{"code": "permission_denied", "detail": "Solo operadores de plataforma."}
```

Causa: tu token NO es de un usuario `ADMIN_SAAS`. Verifica con `/api/me/`.

Log emitido: `PLATFORM_ACCESS_DENIED` con `actor_role`, `actor_id`.

### `400 Bad Request` — duplicate

```json
{
  "code": "validation_error",
  "errors": {
    "admin_username": ["Username ya en uso."]
  }
}
```

O `admin_email`, o `name` (case-insensitive). Resuelve usando otro valor.

### `400 Bad Request` — password weak

```json
{
  "code": "validation_error",
  "errors": {
    "admin_password": [
      "Asegúrese de que este campo tenga al menos 12 caracteres."
    ]
  }
}
```

O `["Esta contraseña es totalmente numérica."]`, o `["Esta contraseña es
demasiado común."]`. Usa un password más fuerte.

### `429 Too Many Requests`

Excediste 20 orgs/hora. Espera o coordina con el otro operador.

### `500 Internal Server Error`

Raro. Verifica logs del servidor con el `X-Request-ID` que enviaste:

```
request_id=<tu request id> AND level=CRITICAL
```

Buscar eventos:
- `PLATFORM_ORG_PROVISION_RBAC_MISSING` — bug en `_seed_roles_for_org`.
  Contactar backend lead.
- `PLATFORM_ORG_PROVISION_POSTCOND_FAILED` — bug en signal wiring de RBAC.
  Contactar backend lead. La transacción rolledback — re-intenta después
  del fix.

## Rollback

**No hay rollback API.** Si provisionas una clínica por error:

1. La transacción NO rollbackea después de retornar 201. Está creada.
2. DELETE de Organization está bloqueado por ADR-15 (`PROTECT` en 5 FKs).
3. Acción de mitigación: soft-delete del admin (`is_active=False` vía
   `DELETE /api/staff/<public_id>/`) + dejar la org huérfana hasta que se
   defina policy de suspend.
4. Documentar el incidente en el sistema de tickets con el `request_id`
   original.

POST-BETA habrá endpoint `PATCH /api/platform/organizations/<public_id>/
{status: 'suspended'}` para esto.

## Observability

Métricas a monitorear (Sentry / log aggregator):

- Total `PLATFORM_ORG_PROVISIONED` por día/semana.
- Latencia P95 de `duration_ms`.
- Tasa de `PLATFORM_ORG_PROVISION_RACE` — si > 0.1% sugiere
  contention y motiva implementar idempotency key (POST-BETA-005).
- Tasa de `PLATFORM_ACCESS_DENIED` — burst sugiere reconocimiento de
  endpoint por atacante (clinic ADMIN intentando escalar).

## Refs

- Endpoint: `POST /api/platform/organizations/`
- Implementación: `backend/apps/platform/`
- ADR formal: `docs/decisions/2026-05-22-p19-platform-org-provisioning.md`
- Módulo doc: `docs/modules/platform.md`
- CLAUDE.md ADR-16
