# Investigación técnica — Legal Acceptance Gate (consentimiento) y cumplimiento

**Fecha**: 2026-06-24
**Tipo**: Investigación de arquitectura previa a diseño. **No se modificó código.**
**Regla**: la fuente de verdad es el código. Donde docs y código difieren, gana el código (discrepancias marcadas con ⚠️).
**Relación**: complementa `docs/auditoria-cumplimiento-privacidad-seguridad-2026-06-24.md` (GAP analysis). Aquí se profundiza en el flujo de onboarding y el punto de inserción del gate de aceptación legal.

---

## 1. Arquitectura actual encontrada

### 1.1 Autenticación y permisos (backend)
- **JWT** vía `rest_framework_simplejwt`. Login: `ThrottledTokenObtainPairView` (`config/urls.py:53`, ruta `api/token/` línea 154). Access 15 min + refresh 7 d con rotación + blacklist (`settings.py SIMPLE_JWT`).
- **Permisos**: `DEFAULT_PERMISSION_CLASSES = [IsAuthenticated, MustChangePasswordGate]` (`settings.py:163`). Pero **casi toda view declara su propio `permission_classes`**, lo que en DRF **anula** el default — por eso el gate de must-change está **embebido** dentro de `HybridPermission.has_permission` (`apps/core/permissions.py:329-343`) además de existir como clase suelta (`MustChangePasswordGate`, `permissions.py:453`).
- **RBAC**: `HybridPermission` (DB-backed + fallback estático, fail-closed `required is None → deny`, `permissions.py:348-371`). Aislamiento multi-tenant a nivel objeto: `has_object_permission` valida `obj.organization_id != user.organization_id` **primero** → `TENANT_MISMATCH_DETECTED` (`permissions.py:373-383`).
- **Middleware** (`config/settings.py:139`, orden): `RequestIDMiddleware` → SecurityMiddleware → WhiteNoise → CORS → Session → Common → CSRF → Auth → **`TenantMiddleware`** (después de Auth, setea `set_current_user` para audit) → Messages → XFrame. El tenant **no** se resuelve en middleware para queries — se deriva de `request.user.organization` en cada view/serializer.

### 1.2 Flujo del must-change gate (el patrón a imitar)
- **Backend**: `_MUST_CHANGE_WHITELIST` (`permissions.py:445`) = `{change-password, /me/, token/refresh/, token/}`. Si `user.password_must_change=True` y la ruta no está en la whitelist → 403 + log `MUST_CHANGE_PASSWORD_BLOCKED`.
- **Frontend**: `MustChangePasswordGate` (`App.jsx:41-50`) — mirror de UX; si `user?.must_change_password && path !== '/change-password'` → `<Navigate to="/change-password">`.
- **`/me/`** (`apps/users/views.py:29-51`) expone `must_change_password` (línea 50) → `authContext` lo lee y lo guarda en `user`.

### 1.3 Choke-point del frontend (clave para el gate legal)
`App.jsx:52` define `wrap(Component)`:
```
PrivateRoute > MustChangePasswordGate > Layout > ErrorBoundary > Component
```
**Todas** las rutas privadas usan `wrap()` (Dashboard, pets, staff, billing, pos, cash, config, etc.). Excepciones: `/change-password` usa `wrapNoGate` (sin el gate), y `/medical-records` inlinea el mismo `PrivateRoute > MustChangePasswordGate > ErrorBoundary` sin `Layout`. → **Existe un único punto de paso obligatorio** para inyectar un `LegalAcceptanceGate` con el mismo patrón.
- `PrivateRoute` (`routes/privateRoutes.jsx:4`): si `!isAuthenticated` → `/login`.
- `client.js:35`: interceptor 401 (no-login) → `clearTokens` + `window.location='/login'`; 500+ → alert. **No hay manejo especial de 403** (un gate que devuelva 403 en API se vería como error genérico; por eso el patrón redirige en el router ANTES de llamar la API).

---

## 2. Flujo real de onboarding (con archivos)

**Onboarding manual, sin self-service signup.** Secuencia verificada:

| Paso | Qué ocurre | Archivo · línea |
|---|---|---|
| 1 | Operador `ADMIN_SAAS` hace `POST /api/platform/organizations/` | `apps/platform/views.py:26,50` `PlatformOrgCreateView.post` |
| 2 | Valida payload (org + admin; password admin ≥12, `validate_password`) | `apps/platform/serializers.py:33` `ProvisionOrgSerializer` |
| 3 | `provision_organization()` atómico | `apps/platform/services/provision_organization.py:58` |
| 3a | `Organization.objects.create()` | `provision_organization.py:94` |
| 3b | **signal** `initialize_organization` (post_save) → `OrganizationSettings` + Owner/Pet genéricos + `_seed_roles_for_org` (ADMIN/VET/ASSISTANT con permisos) | `apps/organizations/signals.py:9,40` |
| 3c | `User.objects.create_user(role='ADMIN', password=<payload>, is_staff=False, is_superuser=False)` | `provision_organization.py:105-116` |
| 3d | **signal** `assign_rbac_role_on_create` → `UserRole(user, role)` | `apps/users/signals.py:9` |
| 3e | `UserRole.update_or_create(..., assigned_by=actor)` (backfill audit) + post-condición | `provision_organization.py:147,171` |
| 4 | Respuesta 201: `{organization{public_id,name,...}, admin{public_id,username,email}}`. **La contraseña NO se devuelve** | `platform/views.py:65-82` |
| 5 | Entrega de credenciales: el operador ya conoce la contraseña (la escribió en el payload) y la reenvía **out-of-band** (el endpoint no envía correo) | `platform/views.py:42-44` (docstring) |
| 6 | Primer login del admin de la clínica: `POST /api/token/` | `config/urls.py:154` |
| 7 | `→ dashboard` | `App.jsx:111` `wrap(Dashboard)` |

### ⚠️ Discrepancia código vs. expectativa (importante para el diseño)
**El admin provisionado se crea con `password_must_change=False`** (el campo NO se setea en `provision_organization.py:105-116`; el default del modelo es `False`, `apps/users/models.py:40`). → El admin de la clínica entra **directo al dashboard sin cambio de contraseña forzado y sin pasar por ningún gate**. El `MustChangePasswordGate` **solo** se activa en los flujos de *reset* (`reset_password_for_staff:286`, `platform_reset_password`), que sí setean `password_must_change=True`.

**Implicación de diseño**: **no existe hoy un choke-point de "primer login" reutilizable para el admin principal**. El gate legal NO puede colgarse del must-change (que es `False` para el admin provisionado); debe activarse por su propia condición ("¿aceptó la versión vigente de los documentos requeridos?").

---

## 3. Lugares candidatos para implementar el gate

| Capa | Punto de inserción | Evidencia | Por qué |
|---|---|---|---|
| Backend (enforcement) | Nueva clase `LegalAcceptanceGate` **embebida en `HybridPermission.has_permission`** (igual que must-change) + whitelist propia | `permissions.py:329-343,445` | Es el único punto que corre en (casi) toda view, ya resuelto `request.user`, post-auth. Replicar el patrón ya probado. |
| Backend (estado) | Campo derivado en `/me/`: `legal_acceptance_required: bool` (+ opcional `pending_documents: [...]`) | `apps/users/views.py:29-51` | El frontend ya consume `/me/`; añade un flag análogo a `must_change_password`. |
| Backend (acción) | Endpoint `POST /api/legal/accept/` (whitelisted en el gate) | nuevo, junto a `change-password` | Puerta de salida del gate, igual que `change-password` lo es para must-change. |
| Frontend (UX) | Nuevo `LegalAcceptanceGate` en `wrap()` **después** de `MustChangePasswordGate` | `App.jsx:52-62` | Choke-point existente; redirige a `/aceptar-terminos` antes de renderizar rutas privadas. |
| Frontend (estado) | `authContext` ya expone `user` con campos de `/me/` | `authContext.jsx:95-103` | Sin cambios estructurales; lee el nuevo flag. |
| UI (links) | Aviso/Términos en `pages/login.jsx` + footer de la app | `pages/login.jsx`, `components/Layout` | Riesgo bajo, cumple L3 del GAP. |

**Orden de gates en `wrap()` recomendado**: `PrivateRoute → MustChangePasswordGate → LegalAcceptanceGate → Layout → ...`. (Primero credencial válida, luego aceptación legal — un usuario con contraseña temporal debe cambiarla antes de aceptar nada.)

---

## 4. Versionado de documentos legales — propuesta (sin crear modelos aún)

### Modelos propuestos (descripción, no implementación)
- **`LegalDocument`**: `doc_type` (`privacy` | `terms` | `cookies`), `version` (str/int), `published_at`, `content` o `url`, `is_current` (bool, único por `doc_type`). Append-only de versiones; nunca se edita una versión publicada.
- **`LegalAcceptance`** (append-only): `user` (FK), `organization` (FK), `document` (FK a `LegalDocument`), `accepted_at`, `ip`, `user_agent`. Una fila por (usuario, documento-versión) aceptada.

### ¿Pertenece a User, Organization o ambos? — evaluación con evidencia
- `User` ↔ `Organization` = FK PROTECT (`apps/users/models.py:25`). Cada staff pertenece a una org; el admin provisionado es `role='ADMIN'`, primer usuario, `assigned_by=<operador>` (`provision_organization.py:147`).

| Opción | Pros | Contras | Veredicto |
|---|---|---|---|
| **Solo `User`** | Cada persona es titular de los datos de su propia cuenta; aceptación individual del Aviso de Privacidad es correcta. | No modela que los **Términos** del servicio los acepta la clínica como entidad. | Insuficiente solo. |
| **Solo `Organization`** | Una aceptación por clínica. | Un VET/ASSISTANT nuevo nunca acepta el Aviso como titular de sus propios datos; no hay traza individual. | Insuficiente solo. |
| **Ambos (recomendado)** | `LegalAcceptance` por **usuario** (con `organization` capturada). El **Aviso de Privacidad** lo acepta cada usuario; los **Términos** se consideran aceptados por la clínica cuando los acepta su **ADMIN** (representante legal de la org). | Un poco más de lógica de "qué docs requiere cada rol". | **Recomendado.** Granularidad por usuario + capturar org da trazabilidad y cubre ambos roles legales. |

**Quién representa legalmente a la organización**: el **ADMIN** provisionado (primer usuario, único con rol ADMIN al inicio). Su aceptación de Términos = aceptación de la clínica. VET/ASSISTANT aceptan al menos el Aviso de Privacidad (como usuarios/titulares).

**Usuarios ya existentes**: al publicar la v1 de cada documento, `legal_acceptance_required=True` para todos hasta que registren su `LegalAcceptance` de la versión vigente. El gate los intercepta en el siguiente request/navegación (no rompe sesión; los lleva a la pantalla de aceptación).

---

## 5. Mapa de datos para ARCO manual

Objetivo: poder responder solicitudes manuales (≤20 días hábiles) sabiendo dónde vive cada dato. **No se implementa export/delete todavía.**

| Dato personal | Modelo | App | Rol de SaaslyVet |
|---|---|---|---|
| Staff: username, email, nombre, rol, especialidad, contraseña (hash) | `User` | `users` | **Responsable** |
| Clínica: nombre, timezone, tax_rate, settings | `Organization`, `OrganizationSettings` | `organizations` | **Responsable** |
| Cliente final: nombre, teléfono, nº expediente anterior, historial migrado | `Owner` (name, phone, legacy_id, extra_data) | `patients` | **Encargado** (por cuenta de la clínica) |
| Paciente: nombre, especie, raza, fecha nac., sexo, color | `Pet` | `patients` | **Encargado** |
| Clínico: diagnóstico, tratamiento, notas, vitales, vacunas | `MedicalRecord`, `VitalSigns`, `VaccineRecord` | `medical_records` | **Encargado** |
| Recetas: dosis, duración, instrucciones | `Prescription`, `PrescriptionItem` | `prescriptions` | **Encargado** |
| Cobros: facturas, pagos (método, no tarjeta), prescriptor externo | `Invoice`, `Payment`, `ExternalPrescriptionAttestation` (`prescriber_name`=PII de tercero) | `billing` | **Encargado** |
| Citas | `Appointment` (refs a Pet/Vet) | `appointments` | **Encargado** |
| Caja | `CashSession`, `CashMovement` (refs a usuario) | `cash` | **Encargado** |
| Migración: filas crudas con PII de cliente/mascota staged | `ImportJob.rows` (JSON) | `imports` | **Encargado** |
| Inventario | `Product`, `Presentation` | `inventory` | (sin PII) |
| Métricas | `DailyOrgMetrics` (agregados) | `analytics` | (sin PII) |

**Proceso manual inicial**: solicitud a `privacidad@saaslyvet.com` → identificar si el titular es staff (Responsable directo) o cliente final (Encargado → derivar a la clínica responsable). Para acceso: query por `organization` + `Owner.public_id`/`User.public_id`. Borrado: bloqueado por PROTECT donde hay dependencias (facturas/expedientes) → anonimización, no borrado físico.

---

## 6. Incident Response y Vendors — realidad verificada

**No documentar capacidades inexistentes.** Lo que SÍ existe:
- **Logging estructurado** JSON a stdout: `core/logging.py`, eventos RBAC (`RBAC_DENIED`, `TENANT_MISMATCH_DETECTED`, `MUST_CHANGE_PASSWORD_BLOCKED`, `LOGIN_FAILED`), correlación `X-Request-ID` (`RequestIDMiddleware`).
- **Auditoría append-only** (DB): `InvoiceAuditLog`, `AppointmentStatusChange`, `Payment/RefundPayment/RefundReversal`, `VitalSigns`, `CashMovement`, `OrganizationTimezoneAudit`, `DashboardSnapshotAudit`. Eventos de plataforma: `PLATFORM_ORG_PROVISIONED`, `ADMIN_PASSWORD_RESET_ISSUED`, `USER_PASSWORD_CHANGED`.
- **Backups**: ADR p40 — `scripts/pg-backup.sh`, dump cifrado (age) offsite a Backblaze B2, deadman Healthchecks.io, restore drill (`RUNBOOK-RESTORE.md`).
- **Sentry**: `send_default_pii=False` + `before_send=scrubEvent` (`core/observability.py`), source maps ocultos.
- **Proveedores reales (subprocesadores)**: Hetzner (VPS), Backblaze B2 (backups cifrados), Sentry (errores), Healthchecks.io (deadman), Let's Encrypt/Caddy (TLS).

**Lo que NO existe** (no inventar): runbook de respuesta a incidentes/brechas (art. 19), procedimiento de notificación al titular, log de **lectura** de datos personales, DPAs firmados, SIEM/alerting de seguridad, MFA.

---

## 7. Riesgo de implementación

| Cambio | Riesgo | Pruebas afectadas / nuevas |
|---|---|---|
| `LegalAcceptanceGate` embebido en `HybridPermission` + whitelist | **ALTO** (toca capa de permisos; corre en cada request; riesgo de bypass o lockout si la whitelist está mal) | Afecta: tests de permisos/RBAC, tests de `/me/`, smoke de cada endpoint. Nuevas: gate permite/bloquea, whitelist (`/me/`, `token/`, `token/refresh/`, `legal/accept/`, logout), no rompe tenant. |
| `LegalAcceptanceGate` frontend en `wrap()` | **MEDIO** (router; riesgo de loop de redirección con must-change) | Nuevas: orden must-change→legal, no-loop, `/aceptar-terminos` accesible bajo el gate. |
| Modelos `LegalDocument` + `LegalAcceptance` + migraciones | **MEDIO** (aditivo, sin tocar modelos existentes; FKs a User/Organization PROTECT/SET_NULL a decidir) | Nuevas: unicidad `is_current` por `doc_type`, append-only de aceptaciones. |
| Campo `legal_acceptance_required` en `/me/` | **BAJO** | Test de contrato de `/me/`. |
| Endpoint `POST /api/legal/accept/` | **MEDIO** (escribe aceptación; idempotente; captura IP/UA server-side) | Nuevas: registra aceptación, idempotencia por versión, server-side IP. |
| Links UI (aviso/términos en login + footer) | **BAJO** | — |

**Regla de seguridad para el gate (no negociable)**: corre en `has_permission` sobre `request.user` únicamente (sin datos cross-tenant) → no introduce fuga multi-tenant. Debe ser **fail-closed pero no lockout**: whitelist obligatoria de `/me/`, `token/`, `token/refresh/`, el endpoint de aceptación y logout, exactamente como `_MUST_CHANGE_WHITELIST`.

---

## 8. Propuesta recomendada

1. **Modelos** `LegalDocument` (versionado, `is_current` por tipo) + `LegalAcceptance` (append-only, por **usuario**, capturando `organization`, `accepted_at`, `ip`, `user_agent`).
2. **Backend gate** `LegalAcceptanceGate` embebido en `HybridPermission` (espejo de must-change), con whitelist propia. Condición de bloqueo: existe ≥1 `LegalDocument.is_current` cuyo (user) no tenga `LegalAcceptance` de esa versión. **Términos** se exigen al ADMIN; **Aviso** a todos.
3. **`/me/`** expone `legal_acceptance_required` (+ `pending_documents`).
4. **Endpoint** `POST /api/legal/accept/` (whitelisted) que registra la aceptación con IP/UA server-side.
5. **Frontend**: `LegalAcceptanceGate` en `wrap()` tras must-change → pantalla `/aceptar-terminos` con checkboxes NO premarcados + links a los documentos. Links de aviso/términos también en `login.jsx` y footer.
6. **Seed**: publicar v1 de Aviso y Términos (los textos ya creados en la landing) como `LegalDocument`.

**Por qué este diseño**: reutiliza un patrón ya probado en producción (must-change), respeta el único choke-point existente, no toca el aislamiento multi-tenant, y resuelve la discrepancia del §2 (el admin provisionado no pasa por ningún gate hoy) sin depender de `password_must_change`.

---

## 9. Alternativas descartadas y por qué

| Alternativa | Por qué se descarta |
|---|---|
| **Capturar el consentimiento en el provisioning** (el operador ADMIN_SAAS acepta por la clínica) | El operador de plataforma **no** es el responsable legal de los datos de la clínica. El consentimiento debe darlo el responsable (admin de la clínica), no un tercero. No sería consentimiento válido. |
| **Checkbox solo en el login, sin persistencia/versionado** | Sin prueba (quién/cuándo/qué versión) y sin re-consentimiento al cambiar el documento. Incumple la trazabilidad que exige el art. 16/consentimiento. |
| **Aceptación solo a nivel Organization (una fila por org)** | Un VET/ASSISTANT nuevo nunca acepta el Aviso como titular de sus propios datos; sin traza individual. Se prefiere por-usuario capturando org. |
| **Gate como middleware Django (antes de DRF)** | Tendría que replicar la resolución de `request.user`/auth de DRF (JWT se valida en `TenantJWTAuthentication`, no en middleware). El layer de permisos ya corre post-auth con el user resuelto — es el lugar correcto, igual que must-change. |
| **Piggyback en `password_must_change`** | Es `False` para el admin provisionado (§2 ⚠️). Forzaría además un cambio de contraseña innecesario. El gate legal necesita su propia condición. |

---

## 10. Plan de implementación por fases

### P0 — Antes de testers (bloqueante legal para cargar datos reales)
- Modelos `LegalDocument` + `LegalAcceptance` (+ migraciones).
- `LegalAcceptanceGate` backend (permiso + whitelist) + `legal_acceptance_required` en `/me/` + `POST /api/legal/accept/`.
- `LegalAcceptanceGate` frontend en `wrap()` + pantalla de aceptación + links aviso/términos en login y footer.
- Seed v1 de Aviso y Términos. Documentar proceso ARCO manual (≤20 días) y runbook de brechas (art. 19).
- **Riesgo dominante**: ALTO (capa de permisos) → batería de tests de gate + whitelist + no-lockout + no-cross-tenant antes de merge.

### P1 — Antes de cobrar con Stripe
- Consentimiento **expreso** para datos financieros (art. 7) al contratar suscripción (nuevo `doc_type` o flujo de aceptación en checkout).
- Endpoints ARCO (export/rectify/cancel) — ver GAP analysis §4.
- MFA para ADMIN/ADMIN_SAAS.
- Stripe hosted (SAQ A) — fuera de este gate.

### P2 — Futuro
- RLS activo (ADR p23), cifrado en reposo, ISO/SOC2, SIEM/alerting sobre los eventos ya estructurados.

---

## 11. Discrepancias código vs. documentación (resumen)
1. ✅ **RESUELTO (2026-06-24)** — *Provisioning no forzaba cambio de contraseña*: `provision_organization` ahora setea `password_must_change=True` (param `require_password_change`, default True; seeds pasan False). Igual `CreateEmployeeSerializer.create` para el staff. El admin/staff entra **gateado** hasta cambiar la contraseña. Ver `docs/fix-provision-must-change-password-2026-06-24.md`. (Antes: el admin entraba directo al dashboard sin gate.)
2. El `MustChangePasswordGate` global de `DEFAULT_PERMISSION_CLASSES` (`settings.py:163`) es en la práctica **redundante** para las views que declaran sus propios `permission_classes`; el enforcement real viene del bloque embebido en `HybridPermission` (`permissions.py:329`). Mismo patrón a seguir para el gate legal.

**No se implementó nada. Esperando aprobación para diseñar el modelo de datos y los cambios concretos.**
