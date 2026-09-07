# Plan de implementación — Centro de Notificaciones (basado en auditoría Rev.3)

> Fuente: `docs/auditoria-centro-notificaciones-2026-09-06.md` (Rev.3). Este plan NO implementa código; congela contrato y fases.
> Fecha: 2026-09-06.

## 0. Objetivo y no-objetivos

Objetivo: vertical mínima que pruebe los 3 problemas técnicos (temporal derivada, transición persistible, evento multi-destinatario) con lectura server-side y sin duplicar Dashboard.
- Familias P0: Agenda (`appointment_upcoming`, `appointment_delayed`), Inventario (`stock_low_entered`, `stock_out`), Caja (`cash_difference`).
- Fuera: `consult_open_aged`, billing aged, lotes, disputas (2ª iteración); push/WhatsApp/email; realtime WS/SSE; refactor transversal `role===`.

## 1. Contrato congelado (Fase 0 debe firmarlo)

### 1.1 Tipos P0

| ID | Clase | Origen | Ventana / trigger | Destinatarios (capacidad) |
|---|---|---|---|---|
| `appointment_upcoming` | CONDITION (derivada) | `0 <= start-now <= 15m AND scheduled/confirmed` (prueba) | asignado o `appointment.list` |
| `appointment_delayed` | CONDITION (derivada) | `now-start >= 20m AND scheduled/confirmed` (prueba) | mismo |
| `stock_low_entered` | EVENT (persistida) | `prev>min AND new<=min AND new>0` (excluyente) | capacidad inventario |
| `stock_out` | EVENT (persistida) | `prev>0 AND new==0` (prioridad sobre low) | capacidad `inventory.view` |
| `cash_difference` | EVENT (persistida) | `closed/force_closed AND abs(difference) >= 50 MXN` | capacidad `cashsession.close`/ADMIN |

Exclusividad stock: `if prev>0 and new==0 → out; elif prev>min and new<=min and new>0 → low; else ninguno`. Tabla: `10→7 ∅; 10→4 low; 10→0 out solo; 4→2 ∅; 4→0 out; 0→20 ∅; 20→4 low (rearme)`.

### 1.2 Keys, receipts, invariantes

- Receipts dual explícito (Rev.5-1): PERSISTIDA → al crear `Notification` se crean `Receipt(user, seen_at=NULL)` por destinatario (`NULL`=unseen; `POST seen` completa `seen_at`). DERIVADA → sin `Notification`; el feed NUNCA crea receipts; ausencia = unseen; `POST seen` crea `Receipt(notification=NULL, key=derived_key, seen_at=now)`.
- Derivadas: `appt:{public_id}:upcoming:{start_iso_utc}`, `appt:{public_id}:delayed:{start_iso_utc}` (`start_iso` canonicalizado UTC).
- Tiempo (Rev.5-3): comparaciones sobre datetimes aware UTC vs UTC, nunca naive; tz de Organization solo presentación/calendario.
- Actor P0 (Rev.5-4): `upcoming N/A, delayed N/A, stock_low NO, stock_out NO, cash_difference NO` (toast ≠ campana; ejecutar ≠ conocer consecuencia).
- Escritura: writer explícito + `atomic + on_commit` best-effort robusto (nunca falla el dominio; pérdida ante crash aceptada, sin Outbox).
- Presentación: DB guarda `type + entity_type + entity_public_id + payload mínimo`; `href` y copy final en `notificationActions` frontend / serializer. Thresholds solo en `notifications/policies.py`.

### 1.3 Permisos

Nuevos `notification.list/retrieve/seen` (seed). Lectura filtra por `for_organization` + receipt propia + capacidad del tipo (caja: únicamente `cashsession.close` — si hoy solo ADMIN la tiene, pertenece al seed, no a la lógica).

## 2. Modelo de datos y migraciones

- `notifications_notification`: `organization FK PROTECT idx, type varchar40 idx, entity_type, entity_public_id UUID, payload JSON, occurred_at idx, dedup_key varchar128, Unique(org,dedup_key)`.
- `notifications_receipt`: `organization FK, notification FK nullable PROTECT, notification_key varchar128, user FK, seen_at, Unique(org,notification_key,user)`, idx `(org,user,seen_at)`.
- `notifications/policies.py`: constantes ventanas/umbrales.
- Migraciones: `notifications 0001_initial` + `core seed permissions`. Cero cambios en dominios. Rollback: `migrate notifications zero`.

## 3. API

```
GET /api/v1/notifications/feed/?limit=20
 → {items:[{key, source, type, priority, title, body, occurred_at, age_min, seen, active, entity:{type,public_id}}], unseen_count}  # Rev.5: sin cursor/next ni GET lista; 20 recientes suficientes para popover MVP
POST /api/v1/notifications/:key/seen/ → {seen_at} (idempotente; 404 ante mismatch)
POST /api/v1/notifications/seen-all/ → {marked:N} (todo lo aplicable del feed, no solo página)
```
Errores `{code,message}`; `public_id`/keys en URL, nunca PK.

## 4. Frontend

- `Bell` en `Layout.topbarActions` (+ `ConsultationRail` por `/medical-records` sin Layout).
- `useNotifications()`: polling 60s + `focus/visibilitychange` + `dashboard:refresh`; `notificationActions.js` mapea CTA.
- Popover: Nuevas/Anteriores, `Esc/outside`, `↑↓/Enter`, `role=dialog`, skeleton/error/empty, paginación cursor. Abrir NO marca visto.

## 5. Fases

### Fase 0 — Congelar contrato (sin código funcional)
Tareas: firmar §1 (tipos, keys, INV-N1, CONDITION/EVENT, ventanas prueba, permisos, actor suppression, CTA/payload); `showmigrations` (ChannelAccount queda como deuda paralela); archivar billing legacy en docs.
Aceptación: ADR firmada. Tests: ninguno funcional.

### Fase 1 — Núcleo (sin productores)
Archivos: `apps/notifications/{models,services(policies,seen),serializers,views,urls}`, `permissions_codes`, migraciones, `modules/notifications.md` + ADR.
Tests: tenant/RBAC cross-org, `seen/seen-all` idempotentes, INV-N1 rechaza mismatch, feed vacío 200, `unseen_count=0`.
Aceptación: feed vacío sin 500. Rollback: `migrate zero`.

### Fase 2 — Persistida backend E2E, sin Bell (stock)
Archivos: hook en `inventory/services.apply_stock_movement` (captura `prev/new + movement_id` → `NotificationService.handle_stock_transition` en `on_commit` best-effort; crea Receipts `seen_at=NULL` por destinatario).
Tests: tabla exclusividad (`10→7 ∅, 10→4 low, 10→0 out solo, 4→2 ∅, 4→0 out, 0→20 ∅, 20→4 low`); retry no duplica; receipts iniciales existen con `NULL`; actor NO suprimido (matriz P0).
Aceptación API: movimiento → Notification → recipients → `GET feed` → `unseen_count` → `POST seen` → disminuye.

### Fase 3 — Derivada backend E2E, sin Bell (solo upcoming)
Archivos: builder `upcoming` con datetimes aware UTC + keys `start_iso_utc` (Rev.5-2/5-3). `delayed` queda para Fase 5.
Tests: visible solo en ventana; reprogramación genera key nueva; visto en PC no reaparece en otro cliente (receipt sparse); `seen-all` marca todo lo aplicable; polling no materializa.
Aceptación API: appointment → builder → feed → seen → `seen=true` en otro cliente → desaparece al salir de ventana.

### Fase 4 — Popover frontend
Archivos: `BellButton, Popover, useNotifications, api/notifications.js, notificationActions.js`; alcance `role===` solo notificaciones.
Tests vitest: badge `unseen_count`, open/close, seen optimista + rollback, CTA mapping, empty/loading/error, 60s + refresh.
Aceptación: E2E `movimiento→DB→Notification→API→Bell→CTA→seen`.

### Fase 5 — Ampliar (delayed + cash_difference)
`delayed` (misma base Fase 3) + `cash_difference` EVENT (`abs>=50 MXN`, writer caja, ADMIN, incluso actor ve). Luego evaluar 2ª iteración (`consult_aged` con cruce único + asignado; billing desdoblada).
Aceptación: cash `-$12 → sin Notification; -$320 → cash_difference`.

### Fase 6 — Hardening/docs/rollout
`prune_notifications/receipts` cron mensual, índices, p95 feed <300ms, guías QA, `docs/dashboard-metrics-contract`, `frontend.md`, `system-flows`, runbook cron, flag rollout tras `nightly_snapshots`.

## 6. Riesgos y mitigaciones clave

Duplicar Dashboard → gate matriz §7 auditoría. Fatiga → 3 familias + actor suppression + bucket día. Drift TZ → `org_today_local`. Leak tenant → 404 + tests. Stale artificial → clases CONDITION/EVENT. Re-notificación infinita stock → `causing_movement_id`.

## 7. Criterio de listo global

Una persistida + una derivada E2E con receipts multi-dispositivo, badge `unseen_count`, CTA por `public_id`, INV-N1 verde, sin WS/Celery, docs y ADR al día.
