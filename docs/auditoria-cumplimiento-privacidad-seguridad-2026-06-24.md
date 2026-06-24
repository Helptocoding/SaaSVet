# Auditoría de cumplimiento — Privacidad y Seguridad (GAP Analysis)

**Fecha**: 2026-06-24
**Alcance**: SaaslyVet (backend Django/DRF + frontend React + infraestructura VPS Hetzner).
**Base normativa**: `Investigacion-de-cumplimiento-de-leyes.md` (LFPDPPP 2025 como obligación legal #1; PCI DSS vía Stripe a futuro; ISO 27001 / SOC 2 como marcos voluntarios; HIPAA NO aplica — datos veterinarios no son PHI).
**Método**: validación contra código real (modelos, vistas, serializers, permisos, middleware, settings, infra). No se asume cumplimiento por existir documentación.
**Leyenda**: ✅ Cumple · 🟡 Parcial / requiere mejora · 🔴 No existe.

> Este documento es un GAP analysis orientativo para priorizar trabajo de ingeniería. **No sustituye asesoría legal profesional** ni redacción legal final del aviso de privacidad.

---

## 1. Resumen ejecutivo

El SaaS tiene una **base de seguridad técnica sólida** para su etapa: aislamiento multi-tenant estricto y verificado a nivel de objeto, RBAC dinámico fail-closed, JWT de vida corta con rotación/blacklist, throttling anti fuerza-bruta con fallo cerrado en login, manejo de secretos por variables de entorno, backups cifrados offsite con drill de restauración, y scrubbing de PII en el monitoreo. **No se almacenan datos de tarjeta** en ninguna parte (no hay pasarela conectada todavía).

La brecha principal **no es técnica de seguridad, sino de cumplimiento LFPDPPP operativo**: no existe captura de **consentimiento**, no hay **enlace al aviso de privacidad dentro de la app**, no existen **mecanismos ARCO** (acceso/exportación, cancelación/borrado, oposición) ni siquiera como proceso manual documentado, no hay **procedimiento de notificación de brechas** (art. 19), y falta **MFA**. Estas son las piezas que deben resolverse —al menos a nivel proceso— **antes de que clínicas reales carguen datos de sus clientes**.

**Veredicto por bloque:**

| Bloque | Estado global |
|---|---|
| Seguridad técnica (acceso, tenant, cifrado en tránsito, secretos, backups) | ✅ Maduro para la etapa |
| LFPDPPP — aviso/consentimiento/ARCO/brechas | 🔴 Brecha principal |
| PCI DSS (Stripe sin implementar) | ⚪ N/A hoy — sin malas prácticas previas (✅ punto de partida limpio) |
| MFA / cifrado en reposo / IR plan | 🔴 Faltantes |
| ISO 27001 / SOC 2 (referencia) | 🟡 Controles técnicos sí, gobernanza/políticas no |

---

## 2. Tabla de controles — Estado / Evidencia / Archivo / Prioridad

### 2.1 LFPDPPP — Datos personales

| # | Control | Estado | Evidencia (archivo · clase/función) | Prioridad |
|---|---|---|---|---|
| L1 | Mapa de datos personales | ✅ | `apps/patients/models.py` (Owner: name, phone, legacy_id, extra_data — **sin email/dirección**; Pet: name, species, breed, birth_date, sex, color), `apps/users/models.py` (staff: username, email, names, role), `apps/medical_records/models.py` (diagnosis, treatment, notes, VitalSigns), `apps/billing/models.py` (ExternalPrescriptionAttestation.prescriber_name = PII de tercero) | — |
| L2 | Aviso de privacidad accesible en landing | ✅ | Landing `frontend/src/pages/aviso-de-privacidad.astro` (creado 2026-06-24) | — |
| L3 | Aviso de privacidad enlazado en la app (login/registro) | 🔴 | `frontend/src/auth/` (authContext.jsx, login.js) — sin enlace a aviso/términos | **P0** |
| L4 | Consentimiento (checkbox no premarcado + timestamp + versión aceptada) | 🔴 | No existe campo/modelo de consentimiento. `apps/platform/serializers.py::ProvisionOrgSerializer` no captura aceptación; `CreateEmployeeSerializer` tampoco | **P0** |
| L5 | ARCO — Acceso (exportar datos del usuario/organización) | 🔴 | No hay endpoint de exportación en `config/urls.py` ni en views | **P1** |
| L6 | ARCO — Rectificación | 🟡 | Datos de cliente/paciente: `PetViewSet`/`OwnerViewSet` (PATCH) por staff de la clínica ✅. Perfil propio del staff: **no hay** `PATCH /api/me/` (MeView es solo GET, `apps/users/views.py`) | **P1** |
| L7 | ARCO — Cancelación (borrado/erasure) | 🟡 | Staff: soft-deactivate `is_active=False` (`StaffDeactivateView`) — no es erasure. Owner/Pet: PROTECT bloquea borrado con dependencias. No hay anonimización ni borrado de datos de cliente | **P1** |
| L8 | ARCO — Oposición | 🔴 | Sin mecanismo | **P1** |
| L9 | Proceso ARCO documentado (≤20 días hábiles, art. 31) aunque sea manual | 🔴 | Sin runbook ni canal operativo definido | **P0** |
| L10 | Cifrado en tránsito (TLS/HTTPS) | ✅ | `config/settings.py` (`SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, `SECURE_PROXY_SSL_HEADER`), `.env.prod.example` (Caddy TLS, HSTS=31536000) | — |
| L11 | Cifrado en reposo (volumen DB) | 🟡 | No evidenciado. Postgres en contenedor sobre volumen Hetzner; sin LUKS/cifrado de disco documentado. **Backups sí cifrados** (age, ADR p40) | **P1** |
| L12 | Manejo de secretos | ✅ | `SECRET_KEY=config('SECRET_KEY')`, `.gitignore` + `.gitleaks.toml`, `.env` no trackeado (verificado `git ls-files`), `docs/security/secret-rotation-plan.md` | — |
| L13 | Backups + restauración probada | ✅ | ADR p40 (`docs/decisions/2026-06-12-p40-...`), `scripts/pg-backup.sh`, offsite B2 + age, deadman Healthchecks, `docs/runbooks/RUNBOOK-RESTORE.md` | — |
| L14 | Notificación de brechas (art. 19) | 🔴 | Sin runbook de respuesta a incidentes ni procedimiento de notificación al titular | **P0** |
| L15 | Designación de responsable de datos personales | 🟡 | Canal `privacidad@saaslyvet.com` definido en aviso (landing). Falta designación formal + monitoreo del buzón | **P0** |
| L16 | Contrato de encargado (DPA) con subprocesadores | 🔴 | Sin DPA firmado/archivado con Hetzner, Backblaze, Sentry | **P0** |
| L17 | Autoridad actualizada (INAI → Secretaría Anticorrupción y Buen Gobierno) | 🟡 | Aviso de la landing usa lenguaje genérico; verificar referencia a autoridad correcta en redacción legal final | **P1** |

### 2.2 Control de acceso y multi-tenant

| # | Control | Estado | Evidencia | Prioridad |
|---|---|---|---|---|
| A1 | RBAC con mínimo privilegio | ✅ | `apps/core/permissions.py::HybridPermission` (DB-backed + fallback estático, fail-closed: `required is None → deny`), `permissions_codes.py`, `make_permission()` | — |
| A2 | Aislamiento multi-tenant a nivel objeto | ✅ | `HybridPermission.has_object_permission` valida `obj.organization_id != user.organization_id` **primero** → `TENANT_MISMATCH_DETECTED` (ERROR). `core/models.py::TenantManager.for_organization` | — |
| A3 | Derivación de tenant server-side (no del body) | ✅ | `CreateEmployeeSerializer.organization_id` read_only; org derivada de `request.user.organization` | — |
| A4 | Enumeration cross-org bloqueado | ✅ | `public_id` UUID en URLs (`resolve_public_id`), `StaffDeactivateView` usa `<str:pk>` UUID (ADR p18) | — |
| A5 | RLS de base de datos (defensa en profundidad) | 🟡 | Preparado pero **no activo** (ADR p23, `docs/decisions/2026-05-26-p23-rls-tenant-isolation.md`) | P2 |
| A6 | MFA / 2FA | 🔴 | Inexistente. Sin TOTP/2FA para ADMIN, ADMIN_SAAS ni acceso a producción/admin Django | **P1** |
| A7 | Lockout / credential lifecycle | ✅ | JWT 15min + refresh 7d con rotación + blacklist (`SIMPLE_JWT`), `MustChangePasswordGate`, reset admin con temp-password 24h (ADR p21/p45) | — |
| A8 | Throttling login (anti fuerza-bruta) | ✅ | `DEFAULT_THROTTLE_RATES.login=5/15min`, Redis `throttle_login` **fail-closed** (`IGNORE_EXCEPTIONS=False`, ADR p41) | — |
| A9 | Ofuscación URL admin | ✅ | `DJANGO_ADMIN_URL` env (`config/urls.py`), ADR p45 | — |

### 2.3 Logging, auditoría e incidentes

| # | Control | Estado | Evidencia | Prioridad |
|---|---|---|---|---|
| O1 | Auditoría de acciones (mutaciones) | ✅ | Append-only: `InvoiceAuditLog`, `AppointmentStatusChange`, `Payment/RefundPayment/RefundReversal`, `VitalSigns`, `CashMovement`, `OrganizationTimezoneAudit`, `DashboardSnapshotAudit` | — |
| O2 | Logging estructurado + correlación | ✅ | `core/logging.py` (JSON RBAC), `RequestIDMiddleware` (X-Request-ID end-to-end), `core/observability.py` | — |
| O3 | Log de **acceso de lectura** a datos personales | 🟡 | Se auditan mutaciones y decisiones RBAC, no las lecturas de datos de un cliente concreto | **P1** |
| O4 | Monitoreo / alerting | 🟡 | Sentry (`send_default_pii=False` + `before_send` scrub), Healthchecks deadman, `docs/runbooks/observability.md` + `monitoring.md`. Sin SIEM ni alerting de seguridad | P2 |
| O5 | Plan de respuesta a incidentes | 🔴 | Sin runbook de IR ni clasificación de severidad/escalamiento | **P0** |

### 2.4 Infraestructura / configuración

| # | Control | Estado | Evidencia | Prioridad |
|---|---|---|---|---|
| I1 | DEBUG desactivado en producción | ✅ | `config/settings.py` `DEBUG=config('DEBUG', default=False)`; `.env.prod.example` `DEBUG=False` | — |
| I2 | CORS sin wildcard + fail-fast | ✅ | `CORS_ALLOWED_ORIGINS` parseado; `raise RuntimeError` si vacío en prod; `CORS_ALLOW_CREDENTIALS=False` | — |
| I3 | Cookies seguras / CSRF | ✅ | `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `CSRF_TRUSTED_ORIGINS` (env, True en `.env.prod.example`) | — |
| I4 | Headers de seguridad | ✅ | `X_FRAME_OPTIONS='DENY'`, `SECURE_CONTENT_TYPE_NOSNIFF=True`, HSTS env | — |
| I5 | Cache/throttle compartido multiworker | ✅ | Redis (ADR p41), refuse-to-boot sin REDIS_URL en prod | — |
| I6 | Hardening verificado en el VPS real | 🟡 | Settings correctos por env; **verificar** que `.env.prod` en Hetzner tiene todos los flags ON (`DEPLOY_VPS_STATUS.md`) | **P0** |

---

## 3. P0 — Antes de testers (clínicas reales cargando datos de sus clientes)

Mínimo legal-operativo para que terceros carguen datos personales de humanos:

1. **Enlace al aviso de privacidad dentro de la app** (login + footer de la app). (L3)
2. **Captura de consentimiento del administrador de la clínica**: al provisionar la organización o en el primer login, checkbox no premarcado de aceptación de Términos + Aviso, persistiendo **quién, cuándo y qué versión** aceptó. (L4)
3. **Proceso ARCO manual documentado** vía `privacidad@saaslyvet.com` con SLA ≤20 días hábiles (aunque aún no haya endpoints automáticos). (L9)
4. **Runbook de respuesta a incidentes + notificación de brechas** (art. 19): detección, contención, evaluación de impacto, plantilla de aviso al titular. (L14, O5)
5. **DPA con subprocesadores**: aceptar/archivar los Data Processing Agreements estándar de Hetzner, Backblaze y Sentry. (L16)
6. **Designar formalmente responsable de datos** y confirmar que el buzón `privacidad@` se monitorea. (L15)
7. **Verificar hardening real en Hetzner**: `.env.prod` con `DEBUG=False`, `SECURE_SSL_REDIRECT=True`, HSTS, cookies seguras, `DJANGO_ADMIN_URL` ofuscado, `ALLOW_LEGACY_ID_LOOKUP=False`. (I6)

> Nota: el aislamiento multi-tenant, RBAC, backups y TLS ya son aptos para testers (✅). El bloqueo es de privacidad/proceso, no de seguridad técnica.

---

## 4. P1 — Antes de cobrar con Stripe (suscripciones)

### 4.1 ARCO automatizado + consentimiento financiero
- **Endpoint de exportación** (acceso): JSON/CSV de los datos de la organización y del usuario. (L5)
- **Rectificación de perfil propio**: `PATCH /api/me/` para staff. (L6)
- **Cancelación/erasure** con anonimización donde el borrado físico esté bloqueado por registros inmutables (facturas/vitales). (L7, L8)
- **Modelo de consentimiento versionado** (`ConsentRecord`: user/org, document_type, version, accepted_at, ip). 
- **Consentimiento EXPRESO para datos financieros** (LFPDPPP art. 7) en el alta de suscripción.

### 4.2 Stripe / PCI DSS — Requisitos obligatorios antes de activar
Stripe **no está implementado** → no es un fallo actual. El punto de partida está limpio: **no existen campos `card_number`/`cvc`/`exp`/PAN en el backend** (verificado; los matches de `card`/`tarjeta` son el enum de método de pago `cash|card|transfer` y etiquetas de UI). Cuando se implemente, debe cumplir:

- **Usar Stripe Checkout o Elements (campos hospedados / iframe / redirect).** Objetivo: **SAQ A** (31 requisitos).
- **NO crear formularios propios de tarjeta**; **NO** postear datos de tarjeta al backend; **NO** almacenar PAN, CVV ni expiración cruda.
- **NO cargar scripts propios en la página de pago** (analytics/pixel) → evita caer en SAQ A-EP. (Relevante porque hoy la landing no tiene tracking — mantenerlo así en el flujo de pago.)
- **Modelo permitido** (lo único a guardar): `stripe_customer_id`, `stripe_subscription_id`, `plan`, `subscription_status`, `card_last4`, `card_brand`, `card_exp` (lo que Stripe devuelve, no sujeto a PCI).
- **Webhooks**: verificar **firma** (`Stripe-Signature` + `STRIPE_WEBHOOK_SECRET`), endpoint idempotente, manejar `customer.subscription.*` / `invoice.*` / `payment_intent.*`.
- **Operativo**: completar SAQ A vía wizard de Stripe, contratar **escaneos ASV trimestrales**, archivar el **AOC de Stripe**, mantener HTTPS forzado.

### 4.3 MFA
- **MFA/TOTP al menos para ADMIN y ADMIN_SAAS** (PCI req. 8 + art. 18 LFPDPPP). (A6)

### 4.4 Auditoría de lectura
- Log de acceso de lectura a datos personales de clientes. (O3)

---

## 5. P2 — Madurez futura (ISO 27001 / SOC 2 / enterprise)

Activar **solo cuando el mercado lo pida** (cliente B2B grande o levantamiento de capital). No antes.

- **ISO 27001 / SOC 2 Type I → II**: gap analysis formal, Statement of Applicability, ~20-25 políticas, gestión de riesgos documentada.
- **Gobernanza**: política de seguridad de la información, gestión de cambios formal (hoy hay CI + revisión, falta política escrita), gestión de proveedores (vendor management).
- **Cifrado de DB en reposo** (volumen Hetzner / LUKS o equivalente). (L11)
- **RLS de Postgres activado** como defensa en profundidad del multi-tenant. (A5)
- **Pentest externo** + escaneo de dependencias continuo.
- **Capacitación de seguridad** y simulacros de incidentes.
- **SIEM / alerting de seguridad** sobre los eventos ya estructurados (`TENANT_MISMATCH_DETECTED`, `RBAC_DENIED`, `LOGIN_FAILED`, `MUST_CHANGE_PASSWORD_BLOCKED`).

---

## 6. WhatsApp / automatización — Checklist previo a lanzamiento

En desarrollo → no es incumplimiento. Diseñar antes de enviar el primer mensaje:

- **Base de consentimiento de comunicación**: registrar opt-in del cliente final para recibir mensajes (la clínica como responsable lo recaba; SaaslyVet como encargado lo almacena).
- **Preferencias y opt-out**: mecanismo simple y gratuito para cancelar mensajes (palabra clave STOP / toggle por cliente).
- **Modelo sugerido**: `CommunicationConsent` (owner, channel, opted_in_at, opted_out_at, source) + `MessageLog` (owner, template, sent_at, status, provider_message_id).
- **Datos que necesitará**: teléfono del cliente (ya existe en `Owner.phone`), plantilla, estado de envío.
- **Proveedor externo**: WhatsApp Business API (Meta) o BSP → **DPA adicional** + declararlo como subprocesador en el aviso.
- **No almacenar** contenido sensible innecesario en logs de mensajes.

---

## 7. Roadmap

| Hito | Qué incluye |
|---|---|
| **Antes de testers** | P0 completo: aviso enlazado en app · consentimiento del admin (checkbox+timestamp+versión) · proceso ARCO manual · runbook de brechas · DPAs · responsable de datos · verificación de hardening en Hetzner. |
| **Antes de clientes pagos** | P1 completo: ARCO automatizado + consentimiento financiero expreso · Stripe hosted (SAQ A, webhooks firmados, modelo token-only, AOC, ASV) · MFA para ADMIN/ADMIN_SAAS · auditoría de lectura. |
| **Después de primeros clientes** | P2: ISO/SOC2 si el mercado lo exige · cifrado en reposo · RLS activo · pentest · gobernanza/políticas · SIEM. |

---

## 8. Notas de cierre

- **No se modificó código.** Este documento es solo el GAP analysis.
- Lo más urgente **no** es seguridad técnica (sólida) sino **proceso de privacidad LFPDPPP** (consentimiento, ARCO, brechas) — barato de implementar y bloqueante legal para recibir datos reales.
- Punto de partida PCI **limpio**: cero datos de tarjeta hoy. La decisión de arquitectura (Checkout/Elements hospedado) es lo que mantiene el alcance en SAQ A.
- Confirmar con abogado mexicano de datos la redacción final del aviso y la referencia a la autoridad vigente (Secretaría Anticorrupción y Buen Gobierno, no INAI).
