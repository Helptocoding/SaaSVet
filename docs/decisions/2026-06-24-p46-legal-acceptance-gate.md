# ADR p46 — Legal Acceptance Gate (consentimiento de documentos legales)

**Fecha:** 2026-06-24
**Estado:** ✅ Aceptado e implementado
**Branch:** `develop`
**Origen:** P0 de la auditoría de cumplimiento (`docs/auditoria-cumplimiento-privacidad-seguridad-2026-06-24.md`, item L4) + investigación (`docs/investigacion-legal-acceptance-gate-2026-06-24.md`).

## Contexto

La auditoría LFPDPPP detectó que la app **no capturaba consentimiento** legal: no había aviso enlazado en la app, ni registro de aceptación de Términos/Aviso. El flujo de onboarding ya forzaba el cambio de contraseña (ADR p21 addendum); faltaba el segundo gate. Flujo esperado:

```
Login → MustChangePasswordGate → LegalAcceptanceGate → Dashboard
```

Restricción: **dos repos independientes**. El **texto** legal vive en la landing pública (`www.saaslyvet.com/{aviso-de-privacidad,terminos,cookies}`); la **app** no lo duplica. Sin dependencia en runtime entre proyectos.

## Decisión

App nueva `apps/legal/` con dos modelos + un gate (espejo del must-change) + endpoints + pantalla dedicada en frontend.

### Modelos

- **`LegalDocument`** (GLOBAL, no tenant-scoped): `public_id`, `doc_type` (`terms|privacy|cookies`), `version` (espejo de la fecha "Última actualización" de la landing), `effective_date`, `landing_url`, `is_current`, `created_at`. Constraints: único `(doc_type, version)`; único parcial `is_current` por `doc_type`.
- **`LegalAcceptance`** (OrganizationalModel, append-only): `user`, `document`, `accepted_at` (server-side), `ip`, `user_agent`; hereda `organization` del user. Único `(user, document)`.

### ¿Quién acepta? (por rol)

| Rol | Acepta | Razón |
|---|---|---|
| **ADMIN** (OWNER de la clínica) | Términos + Aviso | Representa la relación comercial → contrato + aviso |
| **VET / ASSISTANT** | Aviso | Titular de su propia cuenta |
| **ADMIN_SAAS** | — | Operador de plataforma (exento; el gate lo saltea por `is_superuser`) |
| **Cliente final** (`patients.Owner`) | — (en la app) | No usa la app; su consentimiento lo recaba la clínica (SaaslyVet = encargado) |

### El gate (`apps/core/permissions.py`)

- `LegalAcceptanceGate` **embebido** en `HybridPermission.has_permission` (después del must-change, después de `is_superuser`) **+** clase standalone en `DEFAULT_PERMISSION_CLASSES`. Mismo patrón doble que `MustChangePasswordGate`.
- Whitelist `_LEGAL_WHITELIST`: `/api/legal/`, `/api/users/change-password/`, `/api/me/`, `/api/token/refresh/`, `/api/token/`.
- **Salidas sin lockout**: el usuario gateado puede (a) aceptar (`/api/legal/accept/`), (b) renderizar (`/api/me/`), o (c) **cerrar sesión** — el logout es **client-side** (`authContext.logout` → `clearTokens`, sin endpoint backend), así que el gate no puede bloquearlo. No existe endpoint `/api/logout/` ni de blacklist que requiera whitelist; si se agregara uno, debe añadirse a `_LEGAL_WHITELIST`.
- `_legal_blocks(request)` cachea el resultado en el `user` por request; **import perezoso** de `apps.legal` (evita ciclo core→legal).
- Bloqueo → 403 + log `LEGAL_ACCEPTANCE_REQUIRED_BLOCKED`. Server-side autoritativo.

### Endpoints

- `GET /api/legal/current/` → documentos vigentes requeridos para el rol + flag `accepted`.
- `POST /api/legal/accept/` `{document_public_ids:[...]}` → registra aceptación (ip/ua server-side), idempotente, solo documentos vigentes/aplicables; throttle `legal_accept` 30/h.
- `/api/me/` → `legal_acceptance_required` + `pending_legal_documents[]`.

### Frontend

`src/pages/acceptLegal.jsx` (`/aceptar-terminos`, pantalla dedicada que **bloquea antes del Layout**, decisión 4), `src/api/legal.js`, gate `LegalAcceptanceGate` en `App.jsx` dentro de `wrap()` **tras** `MustChangePasswordGate`. Links a la landing en `/login`.

### Versionado / re-consentimiento (decisiones P0)

- **Sync manual** (decisión 2): repos independientes, sin runtime coupling. La landing mantiene texto + fecha; la app mantiene `LegalDocument.version`. Herramienta: `seed_legal_documents` (sin args = asegura defaults; con args = promueve versión nueva). Runbook `docs/runbooks/legal-version-sync.md`.
- **Re-consent solo en cambios materiales** (decisión 3): promover una versión a `is_current` es la decisión **humana** que dispara el re-consentimiento. Correcciones menores no se bumpean.

## Invariantes

1. **Gate no-op sin documentos `is_current`**: si no hay versión vigente de un tipo, no se exige nada → no rompe la suite ni instalaciones sin sembrar. (El gate se "enciende" al correr `seed_legal_documents`.)
2. **Append-only**: `LegalAcceptance` no se edita ni borra; corrección = nueva aceptación. Las aceptaciones viejas se conservan (traza de qué versión aceptó y cuándo).
3. **Server-side**: `accepted_at`, `ip`, `user_agent` los fija el server; nunca el cliente.
4. **ADMIN_SAAS exento** (operador de plataforma).
5. **Demo no se rompe**: `seed_demo_clinic` pre-acepta los documentos vigentes para los usuarios demo (espejo de `require_password_change=False`).
6. **Orden de gates**: credencial (must-change) **antes** de legal, en backend (HybridPermission) y frontend (`wrap()`).

## Anti-patterns

- ❌ Duplicar el texto legal en la app — vive en la landing; la app solo enlaza (`landing_url`).
- ❌ Crear dependencia en runtime app↔landing — el sync de versión es manual.
- ❌ Poner el flag legal en `User.create_user`/default/signal — el gate se basa en `LegalDocument.is_current` + aceptaciones, no en un flag por user.
- ❌ Confiar en el frontend para enforcement — el gate backend es autoritativo.
- ❌ Aceptar documentos no vigentes o no aplicables al rol — la view los rechaza (400).

## Componentes acoplados

```
apps/legal/
├── models.py (LegalDocument, LegalAcceptance)
├── services.py (required_doc_types, current_required_documents,
│                pending_documents, legal_acceptance_required, record_acceptances)
├── views.py (CurrentLegalView, AcceptLegalView) + urls.py
├── admin.py (LegalDocument editable; LegalAcceptance read-only)
└── management/commands/seed_legal_documents.py (sync manual)

apps/core/permissions.py  ← _LEGAL_WHITELIST, _legal_blocks, _log_legal_blocked,
                            LegalAcceptanceGate, embed en HybridPermission
apps/users/views.py:MeView ← legal_acceptance_required + pending_legal_documents
config/settings.py ← DEFAULT_PERMISSION_CLASSES += LegalAcceptanceGate; throttle legal_accept
config/urls.py ← include apps.legal.urls
apps/core/management/commands/seed_demo_clinic.py ← pre-acepta para usuarios demo

frontend/src/
├── pages/acceptLegal.jsx + api/legal.js
├── App.jsx (LegalAcceptanceGate + ruta /aceptar-terminos)
└── pages/login.jsx (links a la landing)
```

## Tests

`apps/legal/tests/test_legal.py` (16 tests): modelos (organización heredada, idempotencia), requisito por rol (ADMIN=terms+privacy, VET=privacy), gate (no-op sin docs, bloqueo, permitido tras aceptar, whitelist `/me/`+`/legal/`, ADMIN_SAAS exento, re-consent por bump de versión), endpoints (current/accept/validación/flip de `/me/`), **flujo E2E OWNER** (provisión → login → must-change → legal → dashboard, validando el orden de gates) y usuario existente gateado al publicar documentos.

## Trade-offs aceptados

| Trade-off | Justificación |
|---|---|
| +1 query (LegalDocument is_current) por request de user de clínica | Cacheado por request en el user; tabla pequeña. Optimizar (cache 30s) es P1 si profilea. |
| Sync de versión manual (operador corre un comando) | Desacopla los repos (sin runtime coupling). Cambios de documento legal son raros. |
| Pantalla `/aceptar-terminos` sin Layout | Decisión 4: bloquea antes del Layout/Dashboard. Paso forzado, no navegable. |

## Pendiente (P1+)

- Consentimiento **expreso** para datos financieros (art. 7 LFPDPPP) en el checkout de Stripe.
- Endpoints ARCO automatizados (export/rectify/cancel) — hoy proceso manual (`docs/compliance/arco.md`).
- Optimización de la query del gate (cache).

## Refs

- ADR p21 (must-change, dependencia de orden): `2026-05-22-p21-admin-password-reset.md`
- Auditoría: `docs/auditoria-cumplimiento-privacidad-seguridad-2026-06-24.md`
- Investigación: `docs/investigacion-legal-acceptance-gate-2026-06-24.md`
- Módulo: `docs/modules/legal.md` · Runbook: `docs/runbooks/legal-version-sync.md`
- ARCO/IR/vendors: `docs/compliance/arco.md`, `docs/security/incident-response.md`, `docs/compliance/vendors.md`
