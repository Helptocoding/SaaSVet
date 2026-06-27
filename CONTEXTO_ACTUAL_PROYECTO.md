# Contexto actual del proyecto (VeterinariaSaaS)

Fecha de corte: 2026-06-27
Fuente: estado real del repositorio (backend + frontend) + docs/modules/* + landingsaas.

> **Notas de desfase (2026-06-27):**
> - **Deploy:** proyecto migrado de Railway/Vercel a **Docker/VPS** (branch `develop`). Secciones 2 y 9 describen la arquitectura objetivo Docker/VPS. Ver `DEPLOY_VPS_PLAN.md` y `DEPLOY_VPS_STATUS.md` para estado real.
> - **Changelog prosa:** llega hasta p33. Los sprints p34–p46 están en el índice de ADRs (§11); su prosa-changelog no se backfilleó en §10.
> - **Landing:** proyecto hermano `landingsaas` (Astro) en `C:\Users\LAP\Desktop\landingsaas` — landing page de marketing con Logo.astro y favicon compartido `iconosaaslyvet.ico`.

---

## 1) Punto actual

El proyecto está en fase de hardening avanzado. La base multitenant, autenticación JWT, módulos clínicos/administrativos y frontend están operativos. Los sprints recientes se centraron en:

- Completar la migración RBAC hacia roles dinámicos en DB.
- Sprint de seguridad completo (sanitización, concurrencia, UUIDs en URLs, throttling, exception handler).
- Rediseño historial clínico: `consultation_type`, modelo `VitalSigns`, endpoints `vitals` y `summary`.
- **Sprint 2026-05-05**: lazy invoice creation, separación create/close en stepper, PATCH estándar, captura de vitales con hash comparison.
- **Sprint 2026-05-06**: defaults toggles a `False`, modal post-done abierto con CTAs explícitos, `force_weight` por patrón `meta`.
- **Sprint 2026-05-07**: timeline editorial Framer Motion, `public_id` en URLs de historial, RBAC UI desde `can_modify_charges`/`can_close` backend.
- **Sprint analytics 2026-05-09 (ADR p9 + p10)**: contrato analítico, CHECK constraints anchors, Capas 1-5 (snapshots, read endpoints JSON-first, advisory lock per-org).
- **Sprint concurrencia 2026-05-16 (ADR p12 + p13)**: orden global de locks, helper `apply_invoice_item_quantity_delta` F(), asserts atómicos.
- **Sprint Día 3 hardening 2026-05-16 (ADR p14)**: tenant validators en `InvoiceSerializer` y `PrescriptionItemSerializer`, Fix 4 PATCH partial.
- **Sprints ADR p15 + p16 2026-05-17**: PR-4A (privilege escalation guard, `DEFAULT_PERMISSION_CLASSES`), PR-4B (Organization singleton `/me/`, 5 FKs CASCADE→PROTECT, `ProtectedError` handler bounded, `audit_orphan_fks`).
- **Sprints ADR p17–p22**: analytics correctness (registries estáticos, `now` policy, late-arrival observability), `public_id` en superficies externas, tenant provisioning (`apps/platform/`), credential lifecycle self-service, admin password reset, frontend token storage + "Recordarme".
- **Auditoría arquitectónica + remediación 2026-05-26 (ADR p23 + p24)**: C1/C2 descartados con tests reales; ratchets AST anti-leak + contención `id`/`public_id`; RLS diferido post-beta.
- **Sprint POS 2026-05-27 (ADR p25–p29)**: owner/pet real en venta directa (p25), atestación receta externa (p26), modelo `Payment` ledger append-only + split + idempotency (p27), módulo `apps/cash/` CashSession + cierre Z (p28), devoluciones/notas de crédito `CreditNote`/`RefundPayment`/`MetricAdjustment` + `revenue_paid_net` dual-expose (p29). Todos con tests verdes.
- **ADR p30 2026-05-28**: dispensación de receta en factura de consulta (`POST /api/billing/prescriptions/<uuid>/dispense/`); `close_medical_record` garantiza factura (incluso $0) al cerrar.
- **ADR p31 2026-06-04 (product-level stock)**: `Product.stock_quantity` como fuente autoritativa en base_units; `apply_stock_movement()` lockea `Product` internamente; callers convierten a base_units; dual-write a `Presentation.stock` para backward compat. Lock order actualizado: `CashSession → MedicalRecord → Invoice → Presentation → InvoiceItem → MedicalRecordProduct`.
- **ADR p32 2026-06-04 (cost_behavior)**: `MedicalRecordProduct.cost_behavior` (`'charge'`|`'included'`); `'included'` descuenta stock pero NO genera InvoiceItem (insumo clínico); default UI es `'included'`; inmutable tras creación.
- **ADR p33 2026-06-07 (wizard UX inventario)**: pantalla mode-selector antes del formulario (`"simple"` vs `"multi"`); `MultiPresentationAnimation` Framer Motion; `ProductCreationTour` 6 pasos; tutorial interactivo con `productTourSteps.js`/`useProductTour.js`/`ProductCreationTour.jsx`.

---

## 2) Arquitectura general

**Backend**: Django 6 + DRF + SimpleJWT — deploy objetivo Docker/VPS.
**Frontend**: React 19 + Vite (JavaScript, sin TypeScript) — deploy objetivo VPS via Nginx.
**DB**: PostgreSQL multitenant por `organization_id` en cada modelo.

Modelo base: `OrganizationalModel` con FK a `Organization`. Todas las queries de negocio van por `for_organization(org)` via `TenantManager`. Las vistas usan `TenantQueryMixin` que bloquea acceso si el usuario no tiene organización.

Autenticación: `TenantJWTAuthentication` recarga usuario con `select_related('organization')` en cada request.

---

## 3) Módulos backend

Apps activas: `organizations`, `users`, `patients`, `appointments`, `medical_records`, `inventory`, `billing`, `cash`, `prescriptions`, `dashboard`, `analytics`, `platform`, `core`.

| Módulo | Acoplamiento | Estado |
|--------|-------------|--------|
| `core` | Estable | Infraestructura pura: permisos, sanitización, throttling, exception handler con soporte `meta`. `LANGUAGE_CODE = 'es-mx'`. |
| `patients` | Estable | Owner + Pet con aislamiento por org. UniqueConstraint para paciente/propietario genérico por org. FKs PROTECT (PR-4B). GIN trigram en Owner/Pet.name. |
| `prescriptions` | Estable | Items de receta con exportación PDF. Sanitización en `dose/duration/instructions/notes`. Tenant validation en todos los FKs. Receta NO descuenta stock; dispensación via billing (ADR p30). |
| `users` | Estable | Roles estáticos + RBAC dinámico. Staff vía `/api/staff/create/`. Credential lifecycle self-service (p20/p21). |
| `platform` | Periférico | Operaciones SaaS cross-tenant. `POST /api/platform/organizations/` provisiona org+admin en un `atomic()`. Throttle 20/hour. Guard `IsPlatformOperator`. Eventos `PLATFORM_ORG_PROVISIONED` etc. |
| `dashboard` | Estable | Read endpoints v1 (`/api/v1/dashboard/operations/series/`, `/financial/series/`). Each datapoint tagged `source`+`lifecycle_state`. `revenue_paid_net = gross + ΣMetricAdjustment` dual-expose (ADR p29). `/api/internal/analytics-health/` para ADMIN_SAAS. |
| `organizations` | Bajo | Settings por org (timezone, tax_rate). `OrganizationSettings` auto-creado. Toggle `require_open_cash_session` (default `False`) integrado (ADR p28). `/api/organizations/me/` canónico; `/<pk>/` legacy deprecado (Sunset 2026-08-17, 410 Gone auto). |
| `appointments` | Moderado | Máquina de estados. Walk-in idempotente con `walk_in=True` persistido (ADR p9). CTAs post-done determinados por frontend desde `medical_record_ids`/`invoice_id` del backend. DELETE crea `AppointmentStatusChange` (solo desde `scheduled`/`confirmed`). ADR p34: cierre consulta completa cita automáticamente. |
| `inventory` | Moderado-alto | Productos, presentaciones, movimientos de stock. **ADR p31**: `Product.stock_quantity` = stock real en `base_unit` (autoritativo); `apply_stock_movement()` lockea `Product` internamente; callers convierten a base_units. Dual-write a `Presentation.stock` (backward compat, no autoritativo). **ADR p32**: `MedicalRecordProduct.cost_behavior` (`charge`\|`included`), inmutable, default `charge` en modelo y UI. **ADR p33**: wizard mode-selector (`simple`/`multi`), `MultiPresentationAnimation`, `ProductCreationTour`. Barcode lookup para POS (`GET /api/inventory/presentations/barcode/?barcode=<cod>`). `audit_stock_integrity` mgmt command. |
| `medical_records` | Alto | Consultas. `consultation_type`, `VitalSigns` append-only. Cierre: valida `diagnosis` siempre + `treatment` para todo tipo excepto VACCINE. **ADR p30**: `close_medical_record` garantiza factura (draft $0 mínimo) al cerrar. `closed_at` editable=False + CHECK constraint + `save()` guard. |
| `billing` | Alto | Máquina de estados `draft→confirmed→paid/cancelled`. **ADR p25**: owner/pet real en `direct_sale`. **ADR p26**: atestación de receta externa (`ExternalPrescriptionAttestation`, permiso `billing.rx_dispense`). **ADR p27**: modelo `Payment` ledger append-only; `remaining_balance = total − ΣPayment`; split `payment_lines`; idempotency `X-Idempotency-Key`; `audit_payment_ledger_integrity`. **ADR p28**: `CashSession` como cabeza del orden de locks; toggle `require_open_cash_session`. **ADR p29**: `CreditNote`/`CreditNoteItem`/`RefundPayment`/`RefundReversal` (devoluciones); `process_refund` + `reverse_credit_note` services; `MetricAdjustment` negativo en `revenue_paid` del día del reembolso. **ADR p30**: dispensación de receta vía `POST /api/billing/prescriptions/<uuid>/dispense/`; stock se descuenta al confirmar (no al dispensar). `pay_direct_sale()` = 1 lock atomic (confirm + pay interno). |
| `cash` | Moderado | ADR p28. `CashSession` (append-only, `open→closed` terminal, UniqueConstraint 1-abierta/user). Cierre Z: `expected_cash = opening_float + ΣPayment(cash) − ΣRefundPayment(cash) + ΣRefundReversal(cash) + manual_in − manual_out`. `closed_snapshot` JSON frozen (`REPORT_SCHEMA_VERSION = 3` con refunds + manual movements ADR p39). Endpoints `/api/cash/sessions/*`. |
| `analytics` | Lectura-derivada | ADR p10. `DailyOrgMetrics` (7 KPIs, `lifecycle_state`, `metrics_schema_version`, `provenance_mix`). `MetricAdjustment` (ADR p29, append-only, delta firmado para `revenue_paid`). Mgmt: `build_daily_metrics` (per-org PG advisory lock), `audit_anchor_integrity`. Today siempre live. |

### Modelos con `public_id` (UUID en URLs)

`Pet`, `Owner`, `Appointment`, `MedicalRecord`, `Invoice`, `Prescription`, `Product`, `Presentation`, `Service`, `VaccineRecord`, `User`, `Organization`, `CashSession`.

Modelos **sin** `public_id` (internos): `InvoiceItem`, `StockMovement`, `MedicalRecordProduct`, `MedicalRecordService`, `VitalSigns`, `InvoiceAuditLog`, `Permission`, `Role`, `UserRole`, `DailyOrgMetrics`, `DashboardSnapshotAudit`, `OrganizationTimezoneAudit`, `AppointmentStatusChange`, `Payment`, `CreditNote`, `CreditNoteItem`, `RefundPayment`, `RefundReversal`, `MetricAdjustment`.

URLs que referencian modelos con `public_id` usan `<str:pk>`. Resolución vía `resolve_public_id()`. `ALLOW_LEGACY_ID_LOOKUP` controla fallback.

---

## 4) RBAC — estado actual

| Fase | Estado |
|------|--------|
| Fase 1 — Observabilidad | ✅ Completa |
| Fase 2 — Seguridad base (tests) | ✅ Completa |
| Fase 3 — Migración vistas a HybridPermission | ✅ Completa |
| Fase 4 — Corte de `User.role` | ⏳ Pendiente (gate: 7 días sin `RBAC_FALLBACK_ALLOWED` en logs) |

**Permisos nuevos que requieren `seed_permissions` en deploy:**
- `cashsession.{list,retrieve,open,close}` (ADR p28)
- `billing.refund` (ADR p29, solo ADMIN)
- `billing.rx_dispense` (ADR p26, ADMIN+VET)
- `medicalrecord.vitals.{create,list}`, `medicalrecord.summary.retrieve`
- `dashboard.financial.view`

**Eventos de observabilidad** (logger `rbac.events` → stdout):
`RBAC_ALLOWED_DB` (INFO) | `RBAC_FALLBACK_ALLOWED` (WARNING) | `RBAC_DENIED` (WARNING) | `TENANT_MISMATCH_DETECTED` (ERROR)

---

## 5) Seguridad y hardening

### Sanitización de inputs

`apps/core/sanitize.py:sanitize_text()` en todos los campos de texto libre. Truncar → NFKC → bleach.clean → strip.

Límites: `diagnosis/treatment → 400`, `notes → 5000`, `vaccine_name/reason/dose/duration → 255`, `cancellation_reason → 100` (vista cancel) / `500` (serializer). Los límites `motivo`/`batch_number` solo existen como docstring en `core/sanitize.py`, sin enforcement en modelos/serializers.

### Orden global de locks (canónico, no negociable)

```
CashSession → MedicalRecord → Invoice → Presentation → InvoiceItem → MedicalRecordProduct
```

Reglas:
- `CashSession` es la **cabeza** (ADR p28): el flujo de pago la lockea ANTES de Invoice cuando `require_open_cash_session` está activo.
- `apply_stock_movement()` lockea `Product` internamente (ADR p31). El caller ya NO necesita lockear `Presentation` antes (cambio vs. pre-ADR p31).
- `close_cash_session` lockea SOLO `CashSession` (nunca Invoice) → sin ABBA.
- Dentro del mismo tipo, lockear por PK ascendente.
- Toda mutación de `InvoiceItem` debe correr con Invoice ya lockeada dentro del mismo `atomic()`.
- Verificado por `test_invoice_concurrency` + `test_cash_concurrency` (Postgres+threads).

### Mutación numérica de `InvoiceItem.quantity`

Toda mutación DEBE usar `F('quantity') ± delta` vía `update()`, incluso con `select_for_update()`.

Helper único: `apps.billing.services.apply_invoice_item_quantity_delta(item, delta)`.

### `MedicalRecordProduct.save()` / `.delete()`

Requieren `transaction.atomic()` externo (`assert connection.in_atomic_block`). Warning `INVOICEITEM_MUTATION_OUTSIDE_ATOMIC` si `InvoiceItem.save/delete` corre fuera de `atomic()`.

### Validaciones de FKs en serializers

Todo serializer con FK a modelo organizacional valida tenant:
```python
def validate_pet(self, pet):
    if pet and pet.organization != self.context['request'].user.organization:
        raise ValidationError('Acceso inválido.')
    return pet
```

### Throttling

`LoginRateThrottle` + `LoginUserRateThrottle` (por IP/IP+username). `vitals` scope 60/hour. `platform_org_create` 20/hour.

### Headers producción

`SECURE_SSL_REDIRECT=True`, `SECURE_HSTS_SECONDS=31536000`, `CORS_ALLOW_HEADERS` incluye `X-Idempotency-Key`, `X-Request-ID`. `ALLOW_LEGACY_ID_LOOKUP=False` cuando frontend migre completamente.

---

## 6) Máquinas de estado

### Appointment

```
scheduled → confirmed → in_progress → done (terminal)
    ↓            ↓            ↓
 canceled     canceled     canceled
    ↓            ↓
 no_show     no_show
```

### Invoice

```
              ┌─ direct_sale: pay_direct_sale() ──────────────────────┐
              │  (confirm_locked + pay_locked, un solo lock)           │
              │                                                         │
draft ────────┼── confirm_invoice() ──→ confirmed ── pay_invoice() ──→ paid
  │           │                                                         │
  └── cancel_invoice() ──────────────────────────→ cancelled           │
              (confirmed también puede cancelarse; paid NO)
```

**ADR p27 — Ledger de pagos:**
- `remaining_balance = total − ΣPayment.amount`
- `status='paid' ⟺ remaining_balance == 0`
- `pay_invoice` / `pay_direct_sale` aceptan `payment_lines=[{method, amount}]` o legacy `payment_method`.
- **Total exacto siempre** — sin pagos parciales. Split válido (efectivo+tarjeta sumando total).
- Cambio en efectivo: frontend lo calcula y muestra, backend registra solo el total.
- `cancel_invoice` rechaza facturas con pagos (dinero sin devolver → usar nota de crédito).

**ADR p29 — Devoluciones:**
- Factura `paid` → `CreditNote` + `RefundPayment` (nota de crédito; factura permanece `paid`).
- `process_refund` service + `reverse_credit_note` service.
- Endpoint `POST /api/billing/invoices/<uuid>/refund/` (permiso `billing.refund`).

### CashSession

```
open → closed (terminal) | force_closed (admin)
```

UniqueConstraint: 1 caja abierta por (org, user). `closed_snapshot` JSON frozen.

---

## 7) Design System

**Fuente única de verdad visual: `frontend/design-system.md`.**

Reglas:
- Cero hex crudo en `.css`/`.jsx`: usar tokens de `frontend/src/styles/tokens.css` (`var(--c-*)`, `var(--r-*)`, `var(--shadow-*)`).
- Reutilizar clases globales de `global.css`: `.btn`, `.card`, `.input`, `.table`, `.badge`, `.modal`.
- H1 de página: `.page-title` (20px/700). Un solo tamaño de título por módulo.
- Prohibido teal legacy `rgba(45,212,191,*)` / `#99f6e4`. Marca es verde bosque `--c-primary`.
- `style={{}}` solo para valores dinámicos (posición, ancho %, color de dato), nunca para color/spacing/radio/sombra fijos.
- Para desviarte de un contrato, editar primero `frontend/design-system.md`.

Paleta:
- Primario: forest-700 `#1a4434` → forest-800 `#16382a` → forest-900 `#0f2a1f`
- Acento: coral `#d67b5c`, sage-400 `#a8c4a2`, amber `#e8b87a`
- Fondos: cream-100 `#f5f1e8`, cream-50 `#fbf8f1`, cream-200 `#ede7d7`
- Fuentes: Plus Jakarta Sans (display/body) + IBM Plex Mono (datos clínicos) + Space Grotesk (login)

---

## 8) Tests

Suite mínima completa (incluye sprints p25–p33):

```bash
python manage.py test \
  apps.core.tests.test_security \
  apps.core.tests.test_sanitize \
  apps.core.tests.test_throttling \
  apps.core.tests.test_invoices \
  apps.core.tests.test_default_permissions \
  apps.core.tests.test_cascade_lockdown \
  apps.core.tests.test_exception_handler \
  apps.core.tests.test_audit_orphan_fks \
  apps.core.tests.test_public_id_dual_exposure_audit \
  apps.medical_records.tests.test_close \
  apps.medical_records.tests.test_vitals \
  apps.billing.tests.test_money \
  apps.billing.tests.test_invoice_state_machine \
  apps.billing.tests.test_invoice_multitenancy \
  apps.billing.tests.test_event_authority \
  apps.billing.tests.test_anchor_completeness \
  apps.billing.tests.test_invoice_concurrency \
  apps.appointments.tests.test_walkin \
  apps.dashboard.tests.test_analytics_health \
  apps.dashboard.tests.test_series_endpoints \
  apps.analytics.tests.test_snapshot_v1 \
  apps.analytics.tests.test_build_command \
  apps.analytics.tests.test_cron_safety \
  apps.prescriptions.tests.test_multitenancy \
  apps.users.tests.test_bootstrap \
  apps.organizations.tests.test_views \
  apps.patients.tests.test_pet_delete
```

**Suites específicas por sprint:**
- `test_invoice_concurrency` — lock order, serializacion paralela (Postgres+threads)
- `test_cash_concurrency` — CashSession lock order (Postgres+threads)
- `apps.dashboard.tests.test_revenue_net` — invariante `net == gross + ΣMetricAdjustment`
- `apps.inventory.tests.*` — ADR p31 stock (33 tests), ADR p32 cost_behavior (15 tests)

**Nota Windows + Python 3.13:**
```bash
# No usar: python manage.py test apps.platform
# Usar:
python manage.py test \
  apps.platform.tests.test_provision_service \
  apps.platform.tests.test_view_auth \
  apps.platform.tests.test_view_validation \
  apps.platform.tests.test_view_integration
```

---

## 9) Frontend

Stack: React 19 + Vite + React Router 7 + Axios + FullCalendar + Sonner + react-day-picker 9 + Framer Motion.

### Patrones clave

- JWT con refresh automático antes de expiración. `tokenStorage.js` módulo único para auth storage — NO `localStorage` raw.
- `AuthProvider` + rutas privadas. `can(permCode)` para permisos en UI (nunca inferir por `user.role`).
- Cliente Axios central: interceptor token + bypass redirect en login 401 + alert global 500.
- **Formularios**: `saving` state + `toast.promise` + validar ANTES de `setSaving(true)`.
- **ConfirmDialog**: `useConfirm` en todas las acciones destructivas y transiciones terminales.
- `apiError(err, fallback)` — helper centralizado, en todos los `catch`.
- `handleFormError(err, setFormErrors)` — centraliza errores DRF a `formErrors` + toasts globales.
- **`public_id`** en todas las URLs de API. `id` entero solo para FK payloads en body.
- **Refetch obligatorio** tras mutaciones.
- **`toast.promise` gotcha (sonner v2)**: NO devuelve la data. Patrón correcto:
  ```js
  const req = miApiCall();
  toast.promise(req, { loading, success, error });
  const data = await req; // await la promesa original, no el retorno de toast.promise
  ```

### Inventario — wizard (ADR p33)

`frontend/src/pages/inventory.jsx`:
- Mode-selector antes del formulario: `"simple"` (1 presentación) vs `"multi"` (2 presentaciones auto-sync).
- `wizardMode: null | "simple" | "multi"` reemplaza `hasPackage` boolean.
- Modo multi: `salesPres[1].name` auto-sync desde label de `countUnit`; `salesPres[1].conversion_factor` auto-sync desde `dividesCount`. `presSecondAutoRef = useRef({nameEdited, cfEdited})` previene pisar ediciones manuales.
- Tutorial interactivo: `features/inventory/tutorial/productTourSteps.js`, `useProductTour.js`, `ProductCreationTour.jsx`.
- `MultiPresentationAnimation.jsx` — 5 escenas Framer Motion. Gate `localStorage.getItem("multi_presentation_animation_seen")`.

### Rutas

| Ruta | Página | Acceso |
|------|--------|--------|
| `/` | Dashboard | Privada |
| `/login` | Login | Pública |
| `/pets` | Mascotas | Privada |
| `/pets/:id` | Ficha mascota | Privada |
| `/appointments` | Citas | Privada |
| `/medical-records` | Historial clínico | Privada |
| `/inventory` | Inventario | Privada |
| `/billing` | Facturación | Privada |
| `/prescriptions` | Recetas (visor) | Privada |
| `/cash` | Caja (turnos + Z) | Privada |
| `/staff` | Equipo | Solo ADMIN |
| `/config` | Configuración | Solo ADMIN |

---

## 10) Deuda técnica y pendientes

> Índice formal en `docs/deuda/`. Esta tabla mantiene items operativos que no encajan en hardening estructural.

| Item | Prioridad | Tracking |
|------|-----------|----------|
| **Fase 2 — Extracción `TenantScopedSerializerMixin`** | Alta | deuda A1 |
| **Fase 2 — `Invoice.clean()` → service + DB CHECK** | Alta | deuda A2 |
| **Fase 2 — `closed_at` writer fuera de service (ADR p9 violation)** | Alta | deuda A3 |
| **Fase 2 — `MRP.delete()` no se invoca en cascade** | Alta | deuda A4 |
| **Fase 2 — Soft-delete real Owner/Pet/Organization** | Alta | deuda A5 |
| **Fase 2 — `InvoiceAuditLog.invoice` CASCADE→SET_NULL** | Alta | deuda A6 |
| **Fase 2 — `MedicalRecord.vet_name_at_close` snapshot** | Alta | deuda A7 |
| **Fase 3 — `bootstrap_superuser` mgmt command** | Media | deuda B5 |
| **Fase 3 — `seed_permissions --prune`** | Media | deuda B6 |
| Gate Fase 4 RBAC: 7 días sin `RBAC_FALLBACK_ALLOWED` | Alta | deuda B3 |
| `seed_permissions` en próximo deploy: `cashsession.*`, `billing.refund`, `billing.rx_dispense` | Alta | — |
| Wire Cron `nightly_snapshots` + `nightly_anchor_audit` con alerting on non-zero exit | Alta | — |
| `ALLOW_LEGACY_ID_LOOKUP=False` en producción | Alta | — |
| Deprecated `/api/organizations/<pk>/` Sunset 2026-08-17 → 410 Gone auto | Alta | — |
| `Presentation.stock`, `Presentation.base_unit`, `Presentation.min_stock` deprecated (no eliminar pre-beta) | Media | ADR p31 |
| `cost_behavior` no tiene PATCH post-creación (by design, inmutable) | Media | ADR p32 |
| Flip de charts a `revenue_paid_net` + bump `METRICS_SCHEMA_VERSION` tras PO sign-off | Media | ADR p29 |
| `MedicalRecord.weight` → migrar a solo `VitalSigns` (data migration) | Media | — |
| Frontend dashboards consumiendo `/api/v1/dashboard/*/series/` — backend listo, UI pendiente | Media | — |
| RLS DB-side (ADR p23 propuesto) diferido post-beta | Media/Post-beta | ADR p23 |
| Inconsistencia ortográfica: `billing='cancelled'` vs `appointments='canceled'` | Baja | — |

### Changelog prosa (p25–p33 resumen)

**ADR p25 (2026-05-27)** — Owner/pet real en venta directa. `direct_sale` acepta `owner` registrado + `pet` opcional. Genérico sigue siendo default. Guard integridad pet.owner.

**ADR p26 (2026-05-27)** — Atestación receta externa en venta directa. `ExternalPrescriptionAttestation` (append-only, legal). Permiso `billing.rx_dispense`. Gate en `InvoiceItemCreateView.perform_create`. Panel de atestación en `NewInvoiceModal`.

**ADR p27 (2026-05-27)** — Modelo `Payment` ledger append-only. `remaining_balance = total − ΣPayment`. `payment_lines` con split por método. Total exacto siempre. Idempotency header `X-Idempotency-Key`. `audit_payment_ledger_integrity` mgmt command. Migración 0019 + backfill.

**ADR p28 (2026-05-27)** — Módulo `apps/cash/`. `CashSession` modelo público. Toggle `require_open_cash_session` (default `False`). Z congelado en `closed_snapshot`. Lock order: `CashSession` es la cabeza. Tests `test_cash_concurrency` (Postgres+threads). Frontend `/cash` + `CajaBar` banner en `/billing`.

**ADR p29 (2026-05-28)** — Devoluciones/notas de crédito. Modelos: `CreditNote`/`CreditNoteItem`/`RefundPayment`/`RefundReversal` (billing) + `MetricAdjustment` (analytics). Services: `process_refund` + `reverse_credit_note`. Analytics dual-expose: `revenue_paid` (gross, sin cambio) + `revenue_paid_net = gross + ΣMetricAdjustment`. Frontend: `RefundModal` en `pages/billing.jsx`. `refundInvoice`/`reverseCreditNote` en `api/billing.js`. `report_schema_version=2` en cierre Z.

**ADR p30 (2026-05-28)** — Dispensación de receta + garantía de factura. `POST /api/billing/prescriptions/<uuid>/dispense/` agrega ítems a factura de consulta (no factura aparte). Stock descuenta al confirmar (ruta única). `close_medical_record` garantiza `get_or_create_invoice_for_medical_record()` en mismo `atomic()`. `PrescriptionDispensePanel` en detalle del cobro.

**ADR p31 (2026-06-04)** — Product-level stock. `Product.stock_quantity` fuente autoritativa en `base_unit`. `apply_stock_movement()` lockea `Product` internamente. Dual-write a `Presentation.stock` backward compat. `audit_stock_integrity` mgmt command. 33/33 tests OK.

**ADR p32 (2026-06-04)** — cost_behavior en MedicalRecordProduct. `'charge'` → InvoiceItem + stock deduct. `'included'` → solo stock deduct. Inmutable tras creación. Default en wizard UI: `'included'`. 15/15 tests OK.

**ADR p33 (2026-06-07)** — Wizard UX inventario mode-selector. Pantalla de selección antes del formulario. `wizardMode: null|"simple"|"multi"`. Modo multi con auto-sync de `salesPres[1]`. `MultiPresentationAnimation` 5 escenas. `ProductCreationTour` 6 pasos con spotlight. Frontend.md sección inventario actualizada.

---

## 11) Índice de ADRs (decisiones de arquitectura)

| ADR | Fecha | Título | Estado |
|-----|-------|--------|--------|
| `2026-04-25-cierre-consulta-explicito.md` | 04-25 | Cierre de consulta explícito | Implementado |
| `2026-04-26-receta-no-es-factura.md` | 04-26 | Receta no es factura | Implementado |
| `2026-04-27-maquina-de-estados-citas.md` | 04-27 | Máquina de estados de citas | Implementado |
| `2026-04-28-organization-settings-toggles.md` | 04-28 | Toggles de flujo por organización | Implementado |
| `2026-04-28-generic-client-direct-sale.md` | 04-28 | Venta directa con cliente genérico | Implementado |
| `2026-04-28-registro-rapido-cita.md` | 04-28 | Registro rápido + cita | Implementado |
| `2026-05-01-p1-business-logic-hardening.md` | 05-01 | Hardening de lógica de negocio | Implementado |
| `2026-05-02-p2-frontend-ux-hardening.md` | 05-02 | Hardening UX frontend | Implementado |
| `2026-05-04-p3-historial-clinico-vitalsigns.md` | 05-04 | VitalSigns en historial clínico | Implementado |
| `2026-05-05-p4-create-close-separation.md` | 05-05 | Separación create/close en stepper | Implementado |
| `2026-05-05-p5-patch-vs-put.md` | 05-05 | PATCH en lugar de PUT | Implementado |
| `2026-05-05-p6-stepper-vitals-capture.md` | 05-05 | Captura de vitales en stepper | Implementado |
| `2026-05-05-p7-lazy-invoice-creation.md` | 05-05 | Creación lazy de facturas | Implementado |
| `2026-05-06-p8-post-done-manual-flow.md` | 05-06 | Flujo manual post-done con CTA explícito | Implementado |
| `2026-05-09-p9-analytics-anchor-authority.md` | 05-09 | Analytics anchor authority + provenance (Capa 1+2) | Implementado |
| `2026-05-09-p10-analytics-snapshots-and-read-endpoints.md` | 05-09 | Snapshots minimal v1 + read endpoints JSON-first (Capa 3+4+5) | Implementado |
| `2026-05-16-p12-concurrency-lock-order-hardening.md` | 05-16 | Orden global de locks + hardening concurrencia Día 1-2 | Implementado |
| `2026-05-16-p13-day12-concurrency-remediation.md` | 05-16 | Remediación post-review Día 1-2 (helper F() + asserts + tenant filter) | Implementado |
| `2026-05-16-p14-tenant-validators-day3.md` | 05-16 | Tenant validators P0 #8-9 + Fix 4 PATCH partial + plan Fase 2 mixin | Implementado |
| `2026-05-17-p15-day4-cascade-lockdown.md` | 05-17 | PR-4A: privilege escalation guard + default IsAuthenticated | Implementado |
| `2026-05-17-p16-pr4b-cascade-and-singleton.md` | 05-17 | PR-4B: Organization singleton + 5 FKs CASCADE→PROTECT + audit_orphan_fks | Implementado |
| `2026-05-17-p17-analytics-correctness-day5.md` | 05-17 | Analytics correctness (registries estáticos, `now` policy, late-arrival observability) | Implementado |
| `2026-05-20-p18-ids-en-superficies-externas.md` | 05-20 | `public_id` (UUID) en superficies externas | Implementado |
| `2026-05-22-p19-platform-org-provisioning.md` | 05-22 | Tenant provisioning vía API (`apps/platform/`) | Implementado |
| `2026-05-22-p20-credential-lifecycle-self-change.md` | 05-22 | Credential lifecycle: self-service password change | Implementado |
| `2026-05-22-p21-admin-password-reset.md` | 05-22 | Admin-initiated password reset + must-change gate | Implementado |
| `2026-05-22-p22-frontend-token-storage-remember-me.md` | 05-22 | Frontend token storage + "Recordarme" + logout/refresh race | Implementado |
| `2026-05-26-p23-rls-tenant-isolation.md` | 05-26 | RLS para aislamiento multitenant DB-side | **Propuesto** (diferido post-beta) |
| `2026-05-26-p24-id-public-id-dual-exposure-containment.md` | 05-26 | Contención de deuda `id`/`public_id` (ratchet, no remoción) | Aceptado |
| `2026-05-27-p25-direct-sale-real-client.md` | 05-27 | Owner/pet real en venta directa | Implementado |
| `2026-05-27-p26-rx-dispense-atestacion.md` | 05-27 | Atestación receta externa en venta directa | Implementado |
| `2026-05-27-p27-payment-ledger.md` | 05-27 | Modelo Payment ledger append-only + split + idempotency | Implementado |
| `2026-05-27-p28-cash-session-cierre-z.md` | 05-27 | Módulo CashSession + cierre Z + lock order cabeza | Implementado |
| `2026-05-28-p29-refunds-credit-notes.md` | 05-28 | Devoluciones/notas de crédito + MetricAdjustment + revenue_paid_net | Implementado |
| `2026-05-28-p30-receta-dispensacion-venta-directa.md` | 05-28 | Dispensación de receta en factura consulta + guaranteed invoice on close | Implementado |
| `2026-06-03-p31-product-level-stock-base-units.md` | 06-03 | Product-level stock en base_units (autoritativo) | Implementado |
| `2026-06-03-p32-cost-behavior-insumo-vs-cobrado.md` | 06-03 | cost_behavior en MedicalRecordProduct (charge / included) | Implementado |
| `2026-06-04-p33-inventory-wizard-ux-single-form.md` | 06-04 | Wizard UX inventario mode-selector simple/multi | Implementado |
| `2026-06-10-p34-cierre-consulta-completa-cita.md` | 06-10 | Cierre de consulta completa cita automáticamente (in_progress → done) | Implementado |
| `2026-06-10-p35-agenda-dia-dashboard.md` | 06-10 | Agenda del día en dashboard con navegación por fecha | Implementado |
| `2026-06-11-p36-pdf-theme-documentos.md` | 06-11 | PDF theme unificado (consulta, receta, cobro) | Implementado |
| `2026-06-11-p37-tope-clinico-dispensacion.md` | 06-11 | Tope clínico de dispensación (cap por cantidad recetada) | Implementado |
| `2026-06-12-p38-pos-pantalla-dedicada.md` | 06-12 | POS pantalla dedicada /pos (reemplaza modal Nuevo Cobro) | Implementado |
| `2026-06-12-p39-cash-movements-asociacion-pagos.md` | 06-12 | Movimientos manuales del cajón + asociación incondicional pago→caja | Implementado |
| `2026-06-12-p40-backup-offsite-disaster-recovery.md` | 06-12 | Backup offsite + disaster recovery | Implementado |
| `2026-06-13-p41-redis-cache-throttle-multiworker.md` | 06-13 | Redis cache + throttle multi-worker | Implementado |
| `2026-06-13-p42-pagination-opt-in-high-volume.md` | 06-13 | Paginación opt-in para endpoints de alto volumen | Implementado |
| `2026-06-16-p43-importador-csv-excel.md` | 06-16 | Importador CSV/Excel de pacientes | Implementado |
| `2026-06-16-p44-paginacion-busqueda-mascotas.md` | 06-16 | Paginación server-side + búsqueda relacional de mascotas | Implementado |
| `2026-06-16-p44b-busqueda-relacional-datos-incompletos.md` | 06-16 | Búsqueda relacional con datos incompletos (EntitySearch) | Implementado |
| `2026-06-23-p45-platform-operator-password-reset.md` | 06-23 | Platform operator password reset | Implementado |
| `2026-06-24-p46-legal-acceptance-gate.md` | 06-24 | Legal acceptance gate (aceptación de términos/privacidad) | Implementado |
