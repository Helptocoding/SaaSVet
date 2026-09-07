# Auditoría y plan — Centro de Notificaciones

> Solo investigación. **No se implementó código, migraciones, modelos, frontend ni dependencias.** Todo lo afirmado lleva evidencia `archivo:línea`.
> Fecha: 2026-09-06. Alcance: SaaSlyVet (VeterinariaSaaS).

## 1 Resumen ejecutivo

**Qué existe:**

- SaaS multi-tenant Django 6 + DRF + React 19 + Vite. 17 apps en `backend/apps/`. Aislamiento por `OrganizationalModel` + `TenantManager.for_organization(org)` + `HybridPermission` con `TENANT_MISMATCH_DETECTED`.
- Dominios con máquinas de estado reales y writers en `services.py`: `Appointment` 6 estados, `MedicalRecord` open/closed, `Invoice` posted/paid/voided + `Checkout` open/completed/abandoned, `CashSession` open/closed/force_closed, `Product.stock_quantity/min_stock` sin status + `StockLot` con status almacenado + `effective_status` derivado.
- Dashboard operativo live en `backend/apps/dashboard/views.py:572 dashboard_summary` (4 queries, cache Redis `dash:summary:{org}` TTL 30s, invalidación por `dashboard/signals.py`). Frontend lo consume con `useDashboardSummary.js:4 POLL_INTERVAL=30_000` + evento global `dashboard:refresh` + polling inbox 20s/10s. Sin React Query/SWR.
- Toasts con Sonner `frontend/package.json:31 "sonner":"^2.0.7"`, mount único `frontend/src/App.jsx:118 <Toaster richColors position="top-right" ... visibleToasts={3}/>`.
- Roles reales `backend/apps/users/models.py:10-19` `ADMIN_SAAS/ADMIN/VET/ASSISTANT/AGENT` + RBAC híbrido `backend/apps/core/permissions_codes.py:17-252` + `backend/apps/core/permissions.py:339-433`.

**Qué falta:**

- Cero infraestructura de notificaciones in-app: `grep notification` en `backend/apps` solo ruido; sin `tasks.py` en todo backend; sin Celery/Beat; sin Channels/WebSocket/SSE (`backend/config/asgi.py:16` solo `get_asgi_application()`); sin email (`settings.py` sin `EMAIL_*`); WhatsApp (`apps/channels/`, `apps/agent/`) es subsistema conversacional, no reutilizable como bus de eventos.
- Temporal solo vía cron externo (`backend/Procfile:15-27` + `docs/runbooks/cron-jobs.md`) y worker-loop de agente (`apps/agent/worker.py`, `run_agent_worker.py --poll 2.0`). No hay scheduler para "cita en 15 min / retraso / consulta envejecida / cobro envejecido".

**Arquitectura recomendada (Rev.2):** Híbrida — `Notification` (evento de la organización) + `NotificationReceipt` (`user + seen_at`, server-side) + builders temporales derivados en `GET /api/v1/notifications/feed/` (lazy, idempotente, sin Celery, sin localStorage como fuente semántica). Escritura explícita desde `services.py` + `transaction.on_commit()`, nunca `post_save` para crear notificaciones. Polling frontend 60s + `focus` + `dashboard:refresh`. Badge = `receipts unseen` (persistidas + derivadas). Sin WebSocket en beta. Ver §10-§12 Rev.2 y §24 Fases Rev.2.

**Complejidad/riesgo:** Medio. Riesgo principal no es técnico sino producto: duplicar Dashboard y fatiga. Mitigable con matriz §7 + dedup por `(org, type, entity, bucket)` + `CommandReceipt`-like.

## 2 Arquitectura actual relevante

**Backend:**

- `backend/requirements.txt:1-21`: Django, DRF, SimpleJWT, cors, redis, sin `celery/channels/daphne`. `backend/config/settings.py:182 AUTH_USER_MODEL=users.User`, `236-297 REST_FRAMEWORK TenantJWTAuthentication + IsAuthenticated+MustChangePasswordGate+LegalAcceptanceGate+DemoResetGate`, `299-315 SIMPLE_JWT ACCESS 15m/REFRESH 7d ROTATE+BLACKLIST`, `416-486 REDIS_URL django_redis` (`default` fail-open, `throttle_login` fail-closed), `510-516 TIME_ZONE='UTC' USE_TZ=True`.
- `backend/config/urls.py:204-209`: `api/dashboard/stats/`, `api/internal/analytics-health/`, `api/v1/dashboard/operations/series|financial/series|summary|activation/`. Sin `dashboard/urls.py`.
- `backend/apps/core/models.py:114-196`: `TenantManager.for_organization(org)` exige org, `OrganizationalModel` con `organization FK(PROTECT)` + `is_active` + auditoría thread-local. `TenantQuerySet.delete()` bloqueado. `backend/apps/core/middleware.py:57-81` solo `set_current_user`, org nunca en thread-local. `backend/apps/core/authentication.py:27,42 TenantJWTAuthentication`.
- `backend/apps/core/permissions.py:339-433 HybridPermission`: DB (`UserRole→Role→Permission`, cache `_cached_permissions`) con fallback estático `PERMISSIONS[user.role]`; `make_permission(code)`; `user_has_permission_strict` solo DB.
- `backend/apps/core/datetime_utils.py:26-81`: `org_today_local`, `local_day_bounds_utc`, `filter_by_local_range`. Regla dura `backend/CLAUDE.md`: prohibido `date.today()/datetime.now()` sin zona.
- `backend/apps/appointments/models.py:23-177`, `views.py:70-77 ALLOWED_TRANSITIONS`, `services.py:182-624` (INV-A compare-and-swap, locks vet→cita, idempotencia, `complete_appointment_on_record_close`).
- `backend/apps/medical_records/models.py:9-91`, `views.py:424 close_medical_record` (atomic + CommandReceipt + idempotente), `services.py:27-80`.
- `backend/apps/billing/models.py:33-1131` (`Invoice`, `Checkout:400-410`, `CheckoutEvent:662`, `CommandReceipt:840-867`, `Payment:1041`), `services.py:235 pay_invoice` (solo posted→paid, total exacto), `checkout_services.py:1506,1631,1680,1799`.
- `backend/apps/cash/models.py:18-143`, `services.py:1-80` (orden global `CashSession→MR→Invoice→...`).
- `backend/apps/inventory/models.py:7-470`, `services.py:17-60 apply_stock_movement` único writer, `signals.py:1-2` explícito sin signals.
- `backend/apps/analytics/models.py:44-177 DailyOrgMetrics/MetricAdjustment`, `services.py:60-529 compute_daily_metrics/apply_snapshot/is_bucket_frozen`.
- `backend/apps/organizations/models.py:15-166` (`timezone default America/Mexico_City`, `OrganizationSettings`, `Schedule`, `TimezoneAudit`), `signals.py:9 initialize_organization`.
- `backend/apps/dashboard/signals.py:23-66` invalida `dash:summary/series` en `post_save Appointment/MR/Presentation/StockMovement/MRP/Invoice` (`on_commit` para Invoice).

**Frontend:**

- `frontend/src/App.jsx:125-175` `createBrowserRouter`, `wrap(Layout)` salvo `/medical-records:135-148` (sin Layout) y `/login|/change-password|/aceptar-terminos`.
- `frontend/src/components/Layout.jsx:52-89` shell real (`Sidebar` + `topbar` sticky `AppShell.module.css:28-40`, `topbarActions:80-85` slot campana antes de `.avatar:79-81`). `Header.jsx:1-43` huérfano. `isDashboard:44` omite topbar en `/`.
- `frontend/src/components/Sidebar.jsx:6-34 NAV_ITEMS=[/,/pets,/appointments,/inbox,/medical-records,/prescriptions,/inventory,/pos,/billing,/cash]`, `ADMIN_ITEMS`, `CAPABILITY_ITEMS`, filtro `can():90-92`.
- `frontend/src/api/client.js:10-42` axios + `Authorization Bearer` + `X-Request-ID`, `401→/login`, `>=500→alert`. Sin React Query (`package.json:16-32` sin `@tanstack/swr`).
- `frontend/src/hooks/useDashboardSummary.js`, `useDayAppointments.js:42-43`, `activationContext.jsx:29-62`, inbox `LIST_POLL_MS=20000 THREAD_POLL_MS=10000 CLOCK_TICK 60000 (pages/inbox/index.jsx:37-39)`. Emisores `dashboard:refresh` en `pages/appointments.jsx:1097+`, `AppointmentQuickModal.jsx`, `medicalRecords/index.jsx:111`; oyentes en `useDashboardSummary:38`, `useDayAppointments:42`, `PendingFollowUp:54`, etc.
- `frontend/src/auth/authContext.jsx:20-265` `AuthProvider {token,user,permissions:Set}`, `can/canAny/canAll:252-265`, pero persisten `user.role===` en `Sidebar.jsx:49-50`, `appointments.jsx:1066,1738`, `inventory.jsx:231`, `dashboard/index.jsx:39-40`, etc.
- Popovers hand-rolled sin Radix: `SearchSelect.jsx:170-175 role=listbox`, `ConfirmDialog.jsx:7-72 + useConfirm.js`, modales `modal-overlay+modal` en `CajaBar.jsx:169,194,244`, `billing.jsx:1167+`. Sin `Bell/campana`.
- Responsive sidebar icon-only `AppShell.module.css:224-254 @media 900px/560px`; dashboard grids `dashboard.css:949+`, `KpiStrip.module.css:130`.

**Infraestructura:**

- Gunicorn sync `Procfile:13`, nightly jobs `nightly_snapshots|anchor_audit|flush_jwt:15-27` vía host crontab. `management/commands/` 30 comandos (`build_daily_metrics`, `prune_dashboard_snapshot_audit`, audits...).
- Redis solo cache+throttle, comentario `settings.py`: "Redis holds NOTHING authoritative... wipe pierde 30s dashboard". Sin Redis en prod → `RuntimeError` salvo break-glass.
- Agent worker `apps/agent/worker.py:1-80` polling con `FOR UPDATE SKIP LOCKED`, backoff `30s·2^n cap 1h`, `SESSION_WINDOW 24h`.

## 3 Mapa del flujo operativo

`Appointment(scheduled→confirmed→in_progress→done/canceled/no_show)` — `appointments/views.py:70-77`, `models.py:34-41`
→ `MedicalRecord(open→closed)` — `medical_records/models.py:10-12`, cierre `views.py:424-560` exige `diagnosis` (y `treatment` salvo vaccine), materializa `consultation_draft`, garantiza factura, llama `appointments.services.complete_appointment_on_record_close` (solo `in_progress→done`, idempotente)
→ `Checkout(open→completed/abandoned, completion no_charge/posted_paid/posted_unpaid/replacement_waived)` — `billing/models.py:400-410` + `CheckoutEvent:662`
→ `Invoice(posted→paid|voided)` — `billing/models.py:34-38`, `pay_invoice services.py:235` total exacto, sin parciales; `InvoiceItem:870` inmutable; `Payment:1041` append-only con `idempotency_key` único por org + `cash_session` string ref
→ `CashSession(open→closed/force_closed)` + `CashMovement(deposit/withdrawal/expense)` — `cash/models.py:36-143`, `close_cash_session services.py` calcula `expected/counted/difference` + `closed_snapshot v3`
→ `DailyOrgMetrics(provisional/frozen/rebuilt/corrupt)` — `analytics/models.py:31-52`, freeze T+2, today siempre live.

Inventario lateral: `Product.stock_quantity/min_stock` (`inventory/models.py:57-62`) mutado solo por `apply_stock_movement services.py:17-60` (FEFO multi-lote vía `StockLot:148-242`). `MedicalRecordProduct:327` consume/restock con `select_for_update`. `Dashboard` lee `Product min_stock>0 AND stock<=min_stock` (`dashboard/views.py:624-629`), nunca `Presentation.stock` (congelado migración 0018).

## 4 Dashboard actual

Endpoint `GET v1/dashboard/summary/` (`dashboard/views.py:572-731`, cache 30s):

- KPIs: `in_progress_now`, `pending_today (scheduled+confirmed hoy)`, `low_stock_count (top5)`, `patients_today`, `ar_outstanding` solo `ADMIN/ADMIN_SAAS:666` (`Invoice status=posted SUM total`).
- `waiting_room`, `backlog {open_total, needs_attention (>3h sin diagnosis), without_diagnosis, records[50]}`, `stock_alerts[5] {severity critical=agotado/warning=bajo}`.
- `timeline` slots 30min, `appointments hoy` con `pet/veterinarian/owner`.

Frontend `src/pages/dashboard/index.jsx:89-201`:

- `DashboardTopBar:53-119`, `KpiStrip:38-87`, `TodayAgendaList:42-61` (`GET appointments/?date=`), `PendingFollowUp.jsx:8-133` "Citas por resolver" (`RANGE_DAYS=30`, `MAX_VISIBLE=5`, `→/appointments`), `ClinicalBacklog.jsx:98-151` (`→/medical-records?record=${publicId}`), `StockAlerts.jsx:28-69` (`→/inventory`), `NowPanel`, `DashboardAnalytics`, `OperationalTimeline:56` tick 60s. `WaitingRoom.jsx` existe pero **no montado** en `dashboard/index.jsx:6-14`.
- Series: `operations/series + financial/series (views.py:511,535)` con envelope `Range+series+today+notes`, `financial` solo ADMIN.

## 5 Sistema actual de feedback

- **Toasts:** Sonner. `App.jsx:30 import {Toaster}`, `:118` mount. Patrón `toast.success/error/warning + apiError(err)`: `pages/billing.jsx:587,678,884`, `CajaBar.jsx:73,90`, `appointments.jsx:1820`, `inbox/index.jsx:387,458`, `SearchSelect.jsx:76`. `toast.promise` no resuelve a data en v2 (`billing.jsx:353,730`, `pos/index.jsx:157`).
- **Badges/cards Dashboard:** `TopBar badge-danger {criticos}`, `PendingFollowUp badge-warning {total}`, `KpiStrip danger/warning`. Son estado, no eventos.
- **Confirmaciones:** `ConfirmDialog + useConfirm`, usado en `inbox:653+`.
- **Sin campana/popover notificaciones:** verificado por grep + `Layout.jsx:70-82` solo avatar.

## 6 Mapa de eventos por dominio

**Appointments** (`models.py:34-67`, `views.py:70-77`, `services.py:182-624`): Estados `scheduled/confirmed/in_progress/done/canceled/no_show`; `walk_in bool`; `veterinarian nullable SET_NULL`; `start/end_datetime UTC + timezone_at_creation`; `AppointmentStatusChange` append-only. Eventos: create, `status PATCH` (con `expected_state` INV-A), `walk_in` (nace `in_progress`), `assign-patient`, auto `in_progress→done` al cerrar MR, `canceled/no_show→scheduled`.
**MedicalRecords** (`models.py:9-506`, `views.py:424-560`): `open→closed` terminal irreversible; `diagnosis/treatment/closed_at/closed_by`; `VitalSigns` append-only; `VaccineRecord.status` derivado. Eventos: create (open), `POST /<uuid>/close/` idempotente, `add_medical_record_product`.
**Billing** (`models.py:33-1387`): `Checkout open→completed/abandoned`, `Invoice posted→paid/voided`, `Payment` append-only, `CheckoutDispute open/resolved`, `CollectionCase open/resolved + review_due_at`, `CheckoutEvent`, `CommandReceipt`. "Cobro pendiente" real = `Checkout open` o `Invoice posted`. Sin parciales.
**Cash** (`models.py:18-143`): `open→closed/force_closed`, `Unique (org,opened_by)` parcial open, `expected/counted/difference/closed_snapshot v3`. Eventos: open, movement, close. Anomalía = `difference != 0`.
**Inventory** (`models.py:7-470`): Sin status en `Product/Presentation`; `stock_quantity/min_stock`; `StockLot effective_status recalled>quarantined>expired>consumed>active :194-205` derivado sin cron; `StockMovement in/out/adjustment`. Transición detectable solo comparando antes/después en `apply_stock_movement`.
**Analytics/Dashboard:** Solo lectura; `dashboard/signals.py` invalida cache (patrón reutilizable).

## 7 Matriz Dashboard vs Notification vs Toast

| Situación | Dashboard | Notification | Toast | Motivo |
|---|---|---|---|---|
| Pago registrado por mí | — | NO | SÍ | Feedback acción propia |
| Consulta guardada/cerrada por mí | Se actualiza `backlog` | NO a mí, SÍ a otros | SÍ a actor | Toast≠broadcast |
| Producto actualizado | Se actualiza `stock_alerts` | NO | SÍ | CRUD no notifica |
| 10 consultas sin diagnóstico (estado) | SÍ `ClinicalBacklog` | NO | NO | Estado agregado |
| Stock bajo (estado) | SÍ `StockAlerts` | NO (estado) | NO | Evitar duplicado |
| **Producto acaba de cruzar a bajo** | NO | SÍ P0 | NO | Novedad accionable |
| **Producto agotado** | SÍ (critical) sin evento | SÍ P0 | NO | Cambio crítico |
| Citas hoy (estado) | SÍ `pending_today` | NO | NO | Estado |
| **Cita próxima ≤15 min** | NO | SÍ P0 | NO | Temporal |
| **Cita retrasada >20 min** | NO | SÍ P0 | NO | Novedad |
| Cita cancelada/no-show | SÍ (conteos) | SÍ a asignado (P1) | SÍ a actor | Broadcast selectivo |
| **Consulta abierta >Xh** | SÍ `needs_attention>3h` | SÍ P0 (una vez) | NO | Envejecimiento |
| **Checkout/Invoice posted sin pagar >Xh** | SÍ `ar_outstanding` (ADMIN) | SÍ P1 | NO | Envejecimiento |
| **Diferencia de caja !=0** | NO | SÍ P0 solo ADMIN | SÍ a actor | Alerta admin |
| Cada movimiento stock/venta | NO | NO | NO | Activity log, prohibido |
| Autosave `consultation_draft` | NO | NO | NO | Nunca fuente verdad |
| Lote próximo a vencer | NO | SÍ P1 (si `tracks_lots`) | NO | Novedad |
| Disputa `CheckoutDispute open` | NO | SÍ P1 ADMIN | SÍ a actor | Excepción |

## 8 Catálogo candidato de notificaciones

CTA usa rutas reales `App.jsx:130-156`.

| ID | Trigger (origen real) | Destinatario | Pri. | Pers. | Clase | Dedup key (Rev.3-4 rearme) | CTA / Ruta |
|---|---|---|---|---|---|---|---|
| `appointment_upcoming` | `start_datetime-now<=15m AND status IN (scheduled,confirmed)` | `veterinarian` o ASSISTANT+ADMIN | attention | NO | CONDITION | `appt:{public_id}:upcoming:{start_iso}` | `→/appointments` |
| `appointment_delayed` | `now>start+20m AND status IN (scheduled,confirmed)` | mismo | important | NO | CONDITION | `appt:{public_id}:delayed:{start_iso}` (Rev.4-3: incluye slot; reprogramación 09:00→16:00 genera key nueva) | `→/appointments` |
| `appointment_status_changed` | `AppointmentStatusChange` a `canceled/no_show/done` | vet anterior + ASSISTANT | info | SÍ | EVENT | `statuschange:{id}` | Ver cita |
| `consult_open_aged` | `MR open AND now-created_at>4h AND sin diagnosis` | vet + ADMIN | attention | NO | CONDITION | `mr:{id}:aged:{day}` | `→/medical-records?record=UUID` |
| `checkout_unpaid_aged` | `Checkout open >4h` o `Invoice posted >24h` | ASSISTANT con `invoice.pay` + ADMIN | attention | NO | CONDITION | `checkout:{id}:unpaid:{day}` | `→/billing` |
| `stock_low_entered` | `stock>min → stock<=min` en `apply_stock_movement` (Rev.4-2 excluyente) | capacidad inventario (ADMIN+VET inicial, sin OR rol) | attention | SÍ | EVENT | `stock_low:{product_id}:{causing_movement_id}` — rearme tras reposición | `→/inventory` |
| `stock_out` | `stock>0 → 0` (prioridad sobre low) | capacidad `inventory.view` (Rev.4-6: sin `+ ASSISTANT` mezclado; que el permiso lo decida) | important | SÍ | EVENT | `stock_out:{product_id}:{causing_movement_id}` | `→/inventory` |
| `cash_difference` | `closed/force_closed AND abs(difference) >= 50 MXN` (Rev.4-8 congelado; `CASH_DIFFERENCE_NOTIFICATION_THRESHOLD=Decimal("50.00")` en `policies.py`) | capacidad `cashsession.close`/ADMIN | important | SÍ | EVENT (sin resolved; historial, solo SEEN lo archiva) | `cashsession:{public_id}` | `→/cash` |
| `lot_expiring` | `tracks_lots AND 0<expiry-hoy<=30d AND qty>0` | ADMIN | info | NO | CONDITION | `lot:{id}:exp:{expiry}` | `→/inventory` |
| `lot_expired/recalled` | `effective_status→expired/recalled/quarantined` | ADMIN + VET | important | SÍ | EVENT | `lot:{id}:{status}:{causing_event_id}` | `→/inventory` |
| `dispute_opened` | `CheckoutDispute status=open` | ADMIN | attention | SÍ | EVENT | `dispute:{id}` | `→/billing` |

## 9 Matriz de destinatarios

Roles `users/models.py:10-19` + `permissions_codes.py:17-252`.

| Evento | ADMIN | VET | ASSISTANT | AGENT | Regla |
|---|---|---|---|---|---|
| `upcoming/delayed` | SÍ | Solo suyas | SÍ si `appointment.list` | NO | Si vet NULL → ASSISTANT+ADMIN |
| `consult_open_aged` | SÍ | Solo suyas | NO | NO | Si NULL → ADMIN |
| `checkout_unpaid_aged` | SÍ | NO | SÍ si `invoice.pay` | NO | Por permiso |
| `stock_low/out` | SÍ | SÍ | `out` SÍ | NO | Por permiso inventario |
| `cash_difference` | Solo ADMIN/SAAS | NO | NO | NO | Espejo `dashboard/views.py:666` |
| `lot_*` | SÍ | expired/recalled SÍ | NO | NO | Solo `tracks_lots=True` |
| `dispute/collection` | SÍ | NO | open SÍ | NO | `checkout.dispute.*` |

Bordes: cambio de vet → notificar al nuevo; cambio de rol → recalcular por permiso vivo; baja/org removal → `for_organization` + `HybridPermission` deniegan; usar `can()` no `role===` (corregir `Sidebar.jsx:49-50`, `appointments.jsx:1066` en Fase 0).

## 10 Arquitecturas evaluadas (Rev.2)

**Decisión Rev.2-1 — lectura server-side, sin localStorage semántico:** se elimina `dismissed_keys` en localStorage como fuente de verdad. Incluso las alertas derivadas usan `NotificationReceipt(notification_key, seen_at)` server-side. `notification_key` = `dedup_key` calculada (`appt:{public_id}:slot{...}`) para derivadas, o PK de `Notification` para persistidas. Esto evita divergencias multi-dispositivo/navegador/storage-wipe y prepara móvil/PWA/push/WhatsApp/email + auditoría de lectura. localStorage solo como caché optimista, nunca autoridad.

**Decisión Rev.2-3 — writers explícitos, no signals para crear:** los `signals post_save` quedan reservados a invalidación de caché reconstruible (patrón existente `dashboard/signals.py`). Las notificaciones se registran explícitamente en el writer autorizado (`apply_stock_movement()`, `close_cash_session()`, `close_medical_record()`, `post_checkout()`), capturando `previous_*` antes de mutar y llamando a `NotificationService` dentro de `transaction.atomic()` + `on_commit()`. Motivo: idempotencia, `select_for_update`, `CommandReceipt` y compare-and-swap (INV-A) no pueden reconstruirse fiablemente desde un `post_save`.

**Decisión Rev.2-4 — Modelo B (evento + recipients) como base:** se compara explícitamente:

- Modelo A (fan-out `Notification` por usuario): simple con 5–10 clínicas, pero N filas por evento, lectura pegada al evento, coste semántico al agregar destinatarios tarde.
- Modelo B (elegido): `Notification` = evento/novedad de la organización (1 fila) + `NotificationReceipt` = (`notification` o `notification_key`, `user`, `seen_at`). 1 evento → N receipts. La lectura pertenece al destinatario, no al evento. Permite agregar ADMIN tarde sin duplicar evento, y unificar `seen` de persistidas y derivadas en una sola tabla.
Escala beta: B gana por semántica aunque A sea marginalmente más simple en SQL.

**Rev.5-1 — receipts dual (cierre Fase 0):** PERSISTIDA → crear `Receipt(user, seen_at=NULL)` por destinatario al generar el evento (materializa quién recibió). DERIVADA → feed nunca crea receipts; ausencia = unseen; `POST seen` crea receipt sparse. **Rev.5-2 — Fase 3 solo `upcoming`** (`delayed` pasa a Fase 5). **Rev.5-3 — tiempo:** aware UTC vs UTC, nunca naive; tz org solo presentación/calendario; `start_iso` canonicalizado UTC en keys. **Rev.5-4 — actor P0:** `upcoming/delayed N/A, stock_low NO, stock_out NO, cash_difference NO`. **Rev.5-5 — alcance MVP:** solo `GET feed/?limit=20`, `POST :key/seen`, `POST seen-all` (todo lo aplicable); sin lista paginada ni cursor. **Rev.5-6 — caja:** únicamente capacidad `cashsession.close`.

**A. Persistida:** historial, `Receipt.seen_at`, badge exacto, dedup DB. Contras: writers en dominios + pruning. Viable (precedente `CommandReceipt`/`CheckoutEvent`/`StatusChange`).
**B. Derivada:** cero migraciones de evento, sin drift. Contras históricas (sin historial) mitigadas por `Receipt` sobre `notification_key`. Perfecta para temporales.
**C. Híbrida (recomendada Rev.2):** persistidas (`stock`, `cash`, `status`, `dispute`) + derivadas (`upcoming/delayed/aged/unpaid/expiring`). `feed/` fusiona, ordena por `occurred_at`, pagina. Ver diagrama §11 Rev.2.

## 11 Arquitectura recomendada (Rev.2)

```
Domain Services (stock / cash / citas / billing)
 │ evento relevante (previous_* capturado en writer)
 ▼ (transaction.atomic + on_commit)
NotificationService
 │ persistidas solo si hay transición
 ▼
Notification (evento org: type, entity_type, entity_public_id, payload snapshot mínimo)
 │ 1 evento → N destinatarios
 ▼
NotificationReceipt (user, notification FK-nullable, notification_key, seen_at)
Tiempo ────────────────────────────────────►
GET /notifications/feed
 ├── eventos persistidos (con receipts)
 ├── builders temporales (upcoming/delayed/aged) → notification_key derivada + receipts
 └── merge por occurred_at → frontend (Bell/badge/popover)
```

**Rev.2-10 — thresholds centralizados:** `notifications/policies.py` (único lugar): `APPOINTMENT_UPCOMING_MINUTES=15`, `APPOINTMENT_DELAYED_MINUTES=20`, `CONSULTATION_AGED_HOURS=4 (solo 2ª iteración)`, `CHECKOUT_OPEN_AGED_H=4 / INVOICE_POSTED_AGED_H=24 (solo 2ª iteración)`. Evolución futura → `OrganizationSettings`, sin UI configurable ahora.
**Rev.2-11 — CTA no persistido:** se persiste `type + entity_type + entity_public_id + payload`; el frontend mapea `notificationActions = { appointment_upcoming: n => ({label:'Ver cita', to:'/appointments'}), ... }`. Nunca `href` en DB (evita rotura ante cambio de router).
**Rev.2-12 — payload vs copy:** híbrido pequeño: `type + payload snapshot mínimo (ej. {product_name_snapshot, stock_quantity})` + render en serializer/frontend. No copy de UI en cada writer de dominio; historial reproducible sin fosilizar rutas.
**Rev.2-13 — actor suppression:** todo `NotificationService.create_*` recibe `actor_user_id`. Regla: si `actor == recipient` y el evento solo confirma su propia acción → no crear receipt (toast ya cubrió). Excepción explícita: `cash_difference` sí notifica incluso al actor (anomalía persistente).

**Rev.4-2 — exclusividad stock (prioridad `out`):**
```
if prev > 0 and new == 0: stock_out
elif prev > min_stock and new <= min_stock and new > 0: stock_low_entered
else: ninguno
```
| Prev | New (min=5) | Resultado |
|---|---|---|
| 10 | 7 | ninguno |
| 10 | 4 | `stock_low_entered` |
| 10 | 0 | `stock_out` solamente |
| 4 | 2 | ninguno |
| 4 | 0 | `stock_out` |
| 0 | 20 | ninguno (reposición, sin evento) |
| 20 | 4 | nuevo `stock_low_entered` (rearme) |

**Rev.4-4 — `on_commit` best-effort (decisión ADR):** notificaciones P0 son side effect no autoritativo, entrega best-effort; NUNCA hacen fallar la operación de dominio tras el commit. `transaction.on_commit(callback robusto)` — wrapper que captura/loguea/Sentry y no propaga. Trade-off aceptado: crash entre commit y callback puede perder una notificación; sin Outbox/Celery en beta. El Dashboard conserva la fuente operacional, lo que hace seguro el trade-off.

## 12 Semántica read/unread/resolved (Rev.2 — ACTIVE/SEEN/RESOLVED)

- `SEEN` = existe `NotificationReceipt(user, key, seen_at NOT NULL)`. Vale para persistidas y derivadas. **Regla de existencia Rev.3-1 (derivadas): no receipt = nunca vista; receipt con `seen_at` = vista. El `GET feed/` NUNCA materializa receipts** (cada polling solo lee builders + receipts existentes). `unseen derivada = builder la produce AND NOT EXISTS receipt seen para esa key`. `seen-all` SÍ crea receipts para las derivadas actualmente visibles. Documentar textual en ADR.
- `INV-N1` **(Rev.3-2):** `Receipt.notification NOT NULL ⇒ receipt.notification_key == Notification.dedup_key`; `Receipt.notification NULL ⇒ notification_key == derived_key`. Persistida: `notification=<fk>, notification_key=<dedup_key copiado>` (duplicado intencional para unificar búsqueda/seen). Derivada: `notification=NULL, notification_key=<derived_key>`. Test obligatorio: crear receipt con `notification=A + key=otra-cosa` debe fallar (CHECK o validación en service).
- `ACTIVE` = la condición todavía existe. `RESOLVED` = `ACTIVE=no`. **Rev.3-3 — dos clases, no forzar stale artificial:**
  - `CONDITION` (tiene active/resolved, derivadas): `appointment_upcoming`, `appointment_delayed`. Existe mientras aplica; `Receipt` recuerda SEEN; Dashboard es el único que responde si la condición operacional sigue existiendo.
  - `EVENT` (histórico, sin resolved, persistidos): `stock_low_entered` ("acaba de cruzar a bajo"), `stock_out` ("acaba de agotarse"), `cash_difference`, `appointment_status_changed`, `dispute_opened`, `lot_expired/recalled`. Rev.4-1: inventario es EVENT — el Dashboard (`StockAlerts`) ya responde si sigue bajo/agotado; la notificación solo dice "entró hace X". Una vez vista pasa a Anteriores; no se calcula ACTIVE por `stock<=min` (evita que A y B parezcan activas a la vez tras reposición).
- `ACTIVE` = la condición que originó la alerta todavía existe (cita sigue `scheduled/confirmed` en ventana; `stock<=min`; `difference!=0`). Se calcula, no se persiste.
- `RESOLVED` = `ACTIVE=no` (cita pasó a `in_progress`, consulta cerró, checkout pagó, stock repuesto). No se persiste `resolved_at` en beta; la derivada deja de emitirse y la persistida muestra `stale=true` gris sin contar al badge. Ejemplo §12 original: 13:45 `ACTIVE=sí/SEEN=no` → abre campana `ACTIVE=sí/SEEN=sí` → 14:02 `in_progress` ⇒ `ACTIVE=no/SEEN=sí` ⇒ sale de activas.
- Badge = `COUNT receipts faltantes (persistidas + derivadas activas)`. Abrir popover **no** marca visto. **Rev.4-7 `seen-all` = todo lo actualmente aplicable del feed** (el backend recomputa el conjunto, independiente de cursor/página cargada); no "las 20 renderizadas".
- Retención: `prune_notifications` mensual (`>90d seen` o `>30d stale`) + `prune_receipts` huérfanas + paginación cursor 20/page. Sin segunda máquina de estados.

## 13 Estrategia temporal

Sin Celery/Beat (sin `tasks.py`, sin `CELERY_*`, `asgi.py` sin Channels). **Elegida:** lazy en `GET feed/` con `org_now_utc/org_today_local`, idempotente por `dedup_key`. Cero infra. Job periódico solo futuro (`prune_notifications` en cron `Procfile` existente). Polling frontend 60s (dashboard ya usa 30s, inbox 20s/10s).

## 14 Estrategia de actualización frontend

`useNotifications()` espejo `useDashboardSummary.js`: `setInterval(60s)+dashboard:refresh+focus+visibilitychange`. Sin WS/SSE (NO-GO Gunicorn sync). `medical-records` sin `Layout` (`App.jsx:135-148`) → montar `Bell` también en `ConsultationRail` en Fase 4.

## 15 UX funcional del popover

Ancla `Layout.topbarActions` + `DashboardTopBar`; `Bell` lucide, badge `9+`, `Esc`/outside (patrón `SearchSelect:44-51`), `↑↓/Enter`, `role=dialog`, `live-region`. Header `Notificaciones [Marcar todas]`. Secciones `Nuevas/Anteriores`. Item: icono/tipo, título, contexto, `hace X min` (org_tz), prioridad, CTA con `public_id`. Estados skeleton/error+reintentar/empty `Todo al día`/paginación. Responsive `min(360px,92vw)`, bottom-sheet `<560px`.

## 16 Priorización P0 P1 P2 NO IMPLEMENTAR (Rev.2 — vertical mínima)

**Primera vertical (3 familias, 5 comportamientos):**

1. Agenda — `appointment_upcoming + appointment_delayed` (prueba caso temporal derivado).
2. Inventario — `stock_low_entered + stock_out` (prueba transición persistible).
3. Caja — `cash_difference` (prueba evento puntual multi-destinatario).
Con esto se validan los tres problemas técnicos distintos antes de ampliar. UX, `Receipt`, `feed/merge`, badge y popover se prueban de punta a punta con el mínimo de productores.
**Segunda iteración:** `consult_open_aged` (solo al cruzar threshold, solo asignado — ver Rev.2-8), `checkout_unpaid_aged` desdoblada (ver Rev.2-9).
**P1:** `appointment_status_changed`, `lot_expiring/expired/recalled`, `dispute_opened`.
**P2:** `vaccine_overdue`, digest ADMIN, `collection_review_due`, push/WhatsApp futuro.
**NO:** CRUD, `consultation_draft` autosave, cada `StockMovement/Payment`, pago propio, `caja abierta`, duplicados de `pending_today/open_total/low_stock_count`.

**Rev.2-8 — `consult_open_aged` anti-duplicado:** Dashboard muestra agregado (`needs_attention>3h`, `without_diagnosis`). La notificación solo existe si `assigned_to == current_user AND age cruza threshold (único evento, no durante toda la condición) AND still open`. Sin asignación o sin cruce → no notificar.
**Rev.2-9 — `checkout_unpaid` desdoblada:** prohibido `Checkout open>4h OR Invoice posted>24h` en una sola notificación. Definir por separado `checkout_not_completed` (operativa, ASSISTANT, CTA completar) vs `invoice_unpaid` (deuda, ADMIN + cobrador con `invoice.pay`, CTA cobrar) con triggers/destinatarios/CTA propios tras aclarar dominio billing p62.

## 17 Cambios necesarios por archivo

| Archivo | Cambio futuro | Razón | Riesgo |
|---|---|---|---|
| `backend/apps/notifications/models.py` (nuevo) | `Notification(evento org) + NotificationReceipt(user, notification_key, seen_at)` Modelo B Rev.2 | Lectura server-side, 1 evento N destinatarios | Medio |
| `backend/apps/notifications/services.py` | `create_if_transition(previous,new,actor_id), mark_seen/all_seen(), prune()` explícito + `on_commit`, sin signals | Rev.2-3 + actor suppression | Medio |
| `backend/apps/notifications/policies.py` (nuevo) | `APPOINTMENT_UPCOMING_MINUTES=15` etc. centralizados | Rev.2-10 | Bajo |
| `backend/apps/notifications/views+urls+serializers` | `GET feed/, GET /, POST /:key/seen/, POST /seen-all/` + `notification.*` (CTA mapeado en frontend, Rev.2-11) | Contrato §19 Rev.2 | Medio |
| `backend/apps/inventory/services.py:17-60` | Hook transición stock en writer | Dedup transición | Bajo |
| `backend/apps/cash/services.py` | Hook `difference!=0` en writer | Alerta ADMIN | Bajo |
| `backend/apps/appointments + billing CheckoutEvent:662` | Emitir `status/dispute` desde writers (no signals) | Reutilizar append-only | Bajo |
| `backend/apps/core/permissions_codes.py` | `notification.list/retrieve/read/read_all` + seed | RBAC única fuente | Bajo |
| `backend/config/urls.py:204-209` | Montar `api/v1/notifications/` | Routing | Bajo |
| `frontend/src/components/Layout.jsx:70-82` | `Bell` en `topbarActions` | Ancla natural | Bajo |
| `frontend/src/components/notifications/*` | `BellButton, Popover, useNotifications, api/notifications.js + notificationActions.js` (Rev.2-11/12) | Integración nativa | Medio |
| `frontend/src/components/notifications/*` (alcance) | Solo `Bell/CTA` afectado por notificaciones; resto `role===` va a deuda aparte | Rev.2-6 alcance | Bajo |
| `frontend/src/pages/medicalRecords/*` | Montar `Bell` | `App.jsx:135` sin Layout | Bajo |

## 18 Migraciones previstas

- `notifications 0001_initial`: `notifications_notification (org, type, entity_type, entity_public_id, payload JSON, occurred_at, dedup_key Unique(org,dedup_key))` + `notifications_receipt (org, notification FK-nullable, notification_key, user FK, seen_at, Unique(org,notification_key,user))` + idx `(org,user,seen_at)`. Sin FK a entidades (por `public_id`).
- `core 00XX_seed_permissions`: `notification.*`.
- Cero migraciones en dominios.

## 19 Endpoints previstos

```
GET /api/v1/notifications/feed/?limit=20&cursor= → {items:[{key, source:persisted|derived, type, priority, title, body, occurred_at, age_min, seen, active, stale, entity:{type, public_id}, cta:{label}}], unseen_count, next}  # href NO persistido (Rev.2-11, mapeo frontend)
GET /api/v1/notifications/?unseen_only=&type=
POST /api/v1/notifications/:key/seen/ → {seen_at} (idempotente; 404 si org/recipient mismatch para no enumerar)
POST /api/v1/notifications/seen-all/ → {marked:N}
```
Auth `TenantJWTAuthentication`, `for_organization`, `public_id`, errores `{code,message}`. Derivadas con `id=dedup_key`.

## 20 Tests necesarios

Backend: tenant/recipient isolation (Notification + Receipt), permisos por capacidad, creación solo en transición con `previous_*` + `actor_id` + `causing_movement_id` (rearInterno: retry mismo movimiento no duplica, reposición + nuevo cruce sí crea), INV-N1 (receipt key == Notification.dedup_key si FK set), feed NO materializa receipts, `seen/seen-all` idempotentes, ventanas + timezone MX, `Unique(org,dedup_key)` + `Unique(org,key,user)`, `prune`, `stale` sin 500, vet NULL, multi-dispositivo (visto en PC no reaparece en laptop). Frontend (vitest): badge `unseen_count`, popover `Esc`/outside, `seen` optimista, CTA mapeado (`notificationActions`), empty/loading/error, polling + `dashboard:refresh`. Integración: `stock → Notification → Receipt → feed → Bell → CTA`; negativos: CRUD/draft no crean, doble `seen-all` ok, actor propio suprimido salvo `cash_difference`.

## 21 Documentación actualizar

`docs/modules/notifications.md` (nuevo), `docs/dashboard-metrics-contract.md §3`, `docs/modules/frontend.md`, `docs/system-flows.md` Flujo A, `docs/modules/billing.md` (archivar legacy), `docs/runbooks/cron-jobs.md` (`prune_notifications`), `docs/decisions/ADR-notificaciones-hibridas.md`, `docs/system-reference.md` (`INV-N`).

## 22 Divergencias encontradas

1. **Billing legacy vs código:** `docs/modules/billing.md` dice `draft→confirmed→paid`; código `billing/models.py:34-410` es `Checkout open→completed + Invoice posted→paid/voided` (p62). Usar p62.
2. **Timezone derivado:** `VaccineRecord.status (medical_records/models.py:175)` y `StockLot.effective_status (inventory/models.py:201)` usan `timezone.localdate()` (servidor), no `org_today_local`. `feed/` debe usar org.
3. **`Presentation.stock` congelado:** `dashboard/views.py:618-622` advierte falsos 0; usar `Product.stock_quantity`.
4. **Frontend `role===` vs `can()`:** `Sidebar.jsx:49-50`, `appointments.jsx:1066,1738`, `inventory.jsx:231`, `dashboard/index.jsx:39-40`. Rev.2-6: corregir en notificaciones **solo** lo que afecte a Bell/CTA/visibilidad (alcance bloqueador); el resto va a deuda aparte para no convertir el proyecto en refactor transversal de autorización.
5. **`/medical-records` sin `Layout`:** `App.jsx:135-148`. Campana invisible en consulta.
6. **`ChannelAccount.public_id` faltante (hallazgo paralelo, NO bloqueador):** `logs/django.log:15181+` `no existe la columna`. Rev.2-14: sacar de Fase 0; resolver como deuda de esquema independiente, salvo que `migrate` global esté roto e impida cualquier migración nueva (verificar con `showmigrations` en Fase 0 sin corregir aquí).
7. **`closed_at` en views no services:** violación p9 conocida (`views.py:424`). Hook explícito en writer/view `close_medical_record`, no signal.
8. **`WaitingRoom.jsx` huérfano:** no importado en `dashboard/index.jsx:6-14`.

## 23 Registro de riesgos

| Riesgo | Sev. | Mitigación |
|---|---|---|
| Duplicar Dashboard | ALTO | Matriz §7 como gate PR |
| Fatiga | ALTO | Dedup + bucket día + vertical mínima 3 familias + actor suppression |
| Duplicados retry | MEDIO | `idempotency_key` + `select_for_update` + writers explícitos (no signals) |
| Race stock | MEDIO | Hook en `apply_stock_movement atomic` con `previous_*` |
| Timezone drift | MEDIO | `org_today_local`, tests MX, thresholds en `policies.py` |
| Multi-tenancy leak | CRÍTICO | `for_organization` + 404 + tests cross-org (Notification + Receipt) |
| Permisos caja | ALTO | Capacidad `cashsession.close` / ADMIN + tests matriz por permiso |
| Polling N+1 | MEDIO | 4 queries, `select_related`, 60s, `Receipt` por `(org,key,user)` indexado |
| Infra innecesaria | MEDIO | Prohibido Celery/WS beta |
| Acoplar dominios | MEDIO | Writers explícitos + `on_commit`; signals solo caché |
| Link roto | MEDIO | Sin FK, `type+entity+payload`, CTA mapeado frontend, `stale`, `prune` |

## 24 Plan de implementación por fases (Rev.2)

**Fase 0 — Congelar contrato, sin código funcional:** resolver semántica SEEN/ACTIVE/RESOLVED, Modelo B, persistida/derivada, thresholds (`policies.py`), permisos por capacidad, actor suppression, y qué 3 familias P0 quedan. Verificar `showmigrations` (sin corregir ChannelAccount aquí). Aceptación: ADR firmada.
**Fase 1 — Núcleo Notification (sin productores):** `Notification + NotificationReceipt/Receipt + policies.py + permissions + API base (feed vacío, seen/seen-all)` + tests tenant/RBAC. Aceptación: `feed/` vacío sin 500, `seen-all` idempotente. Rollback `migrate notifications zero`.
**Fase 2 — Una persistida backend E2E (sin Bell):** `stock_low_entered/stock_out`. Aceptación API/tests: movimiento → transición (tabla Rev.4-2) → DB → receipts → `GET feed` → `unseen_count` → `POST seen` → disminuye. Sin badge/CTA todavía. Retry mismo `movement_id` no duplica; reposición + nuevo cruce crea 2º.
**Fase 3 — Una derivada backend E2E (sin Bell):** `appointment_upcoming` (keys con `start_iso`, Rev.4-3). Aceptación: appointment → builder → feed → seen → otro cliente ve `seen=true` → desaparece al salir de ventana/reprogramar.
**Fase 4 — Frontend popover:** Bell + badge (`unseen_count`) + popover nuevas/anteriores + `notificationActions` CTA + keyboard/mobile + polling/focus. Aceptación: badge decrementa al seen, CTA navega con `public_id`.
**Fase 5 — Ampliar catálogo:** `appointment_delayed`, `cash_difference`, luego evaluar `consult_open_aged` (Rev.2-8) y billing desdoblada (Rev.2-9).
**Fase 6 — Hardening/docs:** prune, índices, performance, docs §21, rollout tras `nightly_snapshots`.

## 25 Preguntas/decisiones pendientes (Rev.2)

1. Ventanas beta cerradas (Rev.3): `appointment_upcoming=15m`, `appointment_delayed=20m` como **defaults iniciales únicamente para pruebas — requieren mejor valoración posterior**. `consult aged / billing aged` quedan fuera de la primera vertical (2ª iteración). Defaults viven en `notifications/policies.py`, no dispersos.
2. ¿Umbral caja `!=0` o `>|50 MXN|`?
3. ¿Ruta `/notifications` full-page P1 o solo popover?
4. ¿`VET` ve `stock_low` o solo `out`? (definir por `inventory.view` vs responsabilidad).
5. ¿Flag por org o global beta?
6. Semántica payload: snapshot mínimo + render (elegido Rev.2-12) — confirmar inmutabilidad deseada del historial.
