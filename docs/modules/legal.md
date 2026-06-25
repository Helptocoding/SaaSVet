# Modulo: Legal (aceptación de documentos legales)

**Fecha**: 2026-06-24

> **Ver también:** [`docs/system-operational-flow.md`](../system-operational-flow.md) — mapa operacional cross-módulo (acciones, precondiciones, efectos, invariantes).

## Objetivo

La app **NO duplica** el texto legal — vive en la landing pública
(`www.saaslyvet.com`). Este módulo **versiona** los documentos y **registra** qué
usuario aceptó qué versión, y un **gate** bloquea el uso de la app hasta aceptar.

Flujo de arranque de sesión:

```
Login → MustChangePasswordGate → LegalAcceptanceGate → Dashboard
```

## Modelos (`apps/legal/models.py`)

### `LegalDocument` (GLOBAL, no tenant-scoped)

Catálogo de versiones de cada documento legal. **No** pertenece a una organización
(es compartido por todo el SaaS).

| Campo | Tipo | Notas |
|---|---|---|
| `public_id` | UUID | identificador público |
| `doc_type` | `terms` \| `privacy` \| `cookies` | tipo de documento |
| `version` | str | espejo de la fecha "Última actualización" de la landing |
| `effective_date` | date | fecha de entrada en vigor |
| `landing_url` | str | URL del documento en la landing |
| `is_current` | bool | versión vigente |
| `created_at` | datetime | |

**Constraints:**
- Único `(doc_type, version)` — no se repite una versión por tipo.
- Único parcial sobre `is_current` por `doc_type` — **a lo sumo una** versión
  vigente por tipo.

### `LegalAcceptance` (OrganizationalModel, append-only)

Registro de aceptación de un usuario sobre una versión concreta.

| Campo | Tipo | Notas |
|---|---|---|
| `user` | FK PROTECT | quién aceptó |
| `document` | FK PROTECT | qué versión aceptó |
| `accepted_at` | datetime | **server-side** |
| `ip` | str | capturada server-side |
| `user_agent` | str | capturado server-side |
| `organization` | FK | **heredada** del `user` |

**Constraint:** único `(user, document)`. **Sin PATCH/DELETE** (append-only — es la
traza histórica del consentimiento).

## Requisito por rol (`apps/legal/services.py`)

| Rol | Documentos requeridos |
|---|---|
| **ADMIN** (OWNER de la clínica, representa la relación comercial) | Términos + Aviso de Privacidad |
| **VET / ASSISTANT** | solo Aviso de Privacidad |
| **ADMIN_SAAS** | ninguno (exento; el gate lo saltea por `is_superuser`) |
| **Cliente final** (`patients.Owner`) | NO usa la app; su consentimiento lo recaba la clínica (SaaslyVet = encargado) |

## El gate (`apps/core/permissions.py`)

`LegalAcceptanceGate` está embebido en `HybridPermission.has_permission` (después
del must-change, después de `is_superuser`) **+** como clase standalone en
`DEFAULT_PERMISSION_CLASSES`. Mismo patrón que `MustChangePasswordGate`.

- **Whitelist** `_LEGAL_WHITELIST`: `/api/legal/`, `/api/users/change-password/`,
  `/api/me/`, `/api/token/refresh/`, `/api/token/`.
- **Sin lockout**: el usuario gateado siempre puede aceptar (`/api/legal/accept/`),
  renderizar (`/api/me/`) o **cerrar sesión** — el logout es **client-side**
  (`authContext.logout` → `clearTokens`, sin endpoint backend), así que el gate no
  puede bloquearlo. No existe `/api/logout/` ni endpoint de blacklist; si se
  agregara, debe entrar a `_LEGAL_WHITELIST`.
- Helper `_legal_blocks(request)` cachea el resultado en el `user` para el request;
  import perezoso de `apps.legal` para evitar ciclo `core → legal`.
- **Propiedad clave**: si **NO** hay documentos `is_current`, el gate es **no-op**
  (no bloquea a nadie) → no rompe el resto de la suite ni instalaciones sin
  documentos sembrados.
- El bloqueo emite log `LEGAL_ACCEPTANCE_REQUIRED_BLOCKED` (WARNING).
- **Server-side autoritativo**: un cliente `curl` choca aquí (el gate no depende del
  frontend).

## Endpoints (`apps/legal/urls.py` + `views.py`)

### `GET /api/legal/current/`

Devuelve solo los documentos **vigentes requeridos** para el rol del user.
Permission `IsAuthenticated` (whitelisted).

```json
{
  "documents": [
    { "public_id": "...", "doc_type": "privacy", "version": "...",
      "effective_date": "...", "landing_url": "...", "accepted": false }
  ],
  "acceptance_required": true
}
```

### `POST /api/legal/accept/`

Registra la aceptación (`ip`/`user-agent` **server-side**). **Idempotente**; solo
acepta documentos vigentes y aplicables. Throttle `legal_accept` **30/hour**.

```json
// body
{ "document_public_ids": ["...", "..."] }
// respuesta
{ "acceptance_required": false }
```

### `/api/me/`

Ahora incluye `legal_acceptance_required` (bool) + `pending_legal_documents`
(lista).

## Versionado y sync con la landing (decisión P0)

**Repos INDEPENDIENTES**, sin dependencia en runtime:

- La **landing** mantiene el texto + la fecha "Última actualización".
- La **app** mantiene `LegalDocument.version`.

Promover una versión a `is_current` es la **decisión humana** que dispara el
re-consentimiento — **SOLO ante cambios materiales** (no correcciones menores).

**Herramienta**: `python manage.py seed_legal_documents`
- **sin args** → asegura las versiones por defecto (idempotente).
- **con** `--doc-type` / `--version` / `--effective-date` / `--url` → promueve una
  versión nueva.

Ver runbook [`docs/runbooks/legal-version-sync.md`](../runbooks/legal-version-sync.md).

## Demo

`seed_demo_clinic` **pre-acepta** los documentos vigentes para los usuarios demo
(espejo de `require_password_change=False`) para no romper el login compartido del
demo.

## Frontend

- `src/pages/acceptLegal.jsx` — ruta `/aceptar-terminos`, pantalla **dedicada**,
  bloquea **antes** del `Layout`.
- `src/api/legal.js` — funciones de API.
- `LegalAcceptanceGate` en `App.jsx` dentro de `wrap()` **tras**
  `MustChangePasswordGate`.
- Links a la landing en `/login`.

## Refs

- ADR p46 (`docs/decisions/2026-06-24-p46-legal-acceptance-gate.md`)
- ADR p21 (must-change)
- Auditoría `docs/auditoria-cumplimiento-privacidad-seguridad-2026-06-24.md`
