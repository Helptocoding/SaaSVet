# Modulo: Caja (turno / cierre Z)

> **Ver también:** [`docs/system-operational-flow.md`](../system-operational-flow.md) — mapa operacional cross-módulo (acciones, precondiciones, efectos, invariantes).

App: `apps/cash/`. ADRs `2026-05-27-p28-cash-session-cierre-z.md` y
`2026-06-12-p39-cash-movements-asociacion-pagos.md` (movimientos manuales del cajón +
asociación incondicional pago→caja).

## Objetivo

Reconciliacion del cajon fisico: un agregado **por encima** del ledger de pagos
(`billing.Payment`). Bounded context separado de billing — billing es el ciclo de
vida de la factura; caja es el cuadre del efectivo del turno.

`Payment.cash_session` es FK con string ref (`'cash.CashSession'`) → dependencia
unidireccional billing→cash, sin ciclo de import. El contrato de campos del evento
financiero vive en `docs/financial-event-model-contract.md`.

## Modelo: `CashSession`

Publico (`PublicIdMixin`, URLs por `public_id`; expone solo `public_id`, ADR p24).

Campos: `opened_by`, `opened_at`, `opening_float`, `status`, `closed_by`,
`closed_at`, `expected_cash`, `counted_cash`, `difference`, `notes`,
`closed_snapshot` (JSON), `report_schema_version`.

Lifecycle: `open → closed` (terminal). `force_closed` = cierre administrativo.

Invariantes (DB):
- **CHECK** `cashsession_closed_requires_closed_at`: status cerrado ⇒ `closed_at`
  NOT NULL (mismo patron de anchor que ADR p9). `closed_at` es `editable=False`.
- **UniqueConstraint parcial** `cashsession_one_open_per_user`: una sola caja
  abierta por `(organization, opened_by)`. Resuelve la doble-apertura.
- `opening_float >= 0`.

Inmutable tras cerrar: `expected/counted/difference/closed_snapshot`.

### Z legal congelado

Al cerrar, el service escribe `closed_snapshot` (JSON append-only) con
`{opening_float, totals_by_method, cash_refunds, cash_reversals, manual_in,
manual_out, movements_by_type, movements_count, cash_expected, cash_counted,
difference, operations, actor, generated_at, report_schema_version}`.
Las claves `manual_*` y `movements_*` existen desde **v3** (ADR p39);
`cash_refunds`/`cash_reversals` desde **v2** (ADR p29).

**El Z historico NO se reinterpreta** si cambia el codigo de reporting (mismo
principio que `DailyOrgMetrics` frozen + `metrics_schema_version`). `report_schema_version`
versiona el shape; bump al cambiar la semantica de un campo del reporte (DD-003).
Versiones: Sprint A = **v1**; refunds (ADR p29) → **v2**; movimientos manuales del
cajón (ADR p39) → **v3** (`REPORT_SCHEMA_VERSION = 3` en `cash/services.py`).

## Servicios (`cash/services.py`)

Writers autoritativos. **Solo importar de aqui** desde fuera del modulo.

- `get_open_session(user)` — sesion abierta del usuario, o None (lectura, sin lock).
- `open_cash_session(user, opening_float=0, notes='')` — abre turno; rechaza si ya
  hay uno abierto.
- `close_cash_session(session, user, counted_cash, notes='', force=False)` — computa
  el Z, congela snapshot, calcula `difference = counted − expected`.

### Calculo del Z

```
expected_cash = opening_float + Σ(Payment cash en S)
              − Σ(RefundPayment cash en S) + Σ(RefundReversal cash en S)   # ADR p29 (report_schema_version=2)
              + Σ(CashMovement deposit en S)                                # ADR p39 (report_schema_version=3)
              − Σ(CashMovement withdrawal + expense en S)                   # ADR p39
card_total / transfer_total = informativos (NO entran al conteo de efectivo)
difference = counted_cash − expected_cash
```

`card`/`transfer` cuentan en `revenue_paid` (analytics) pero **no** en el efectivo
del Z. **Caja-efectivo ≠ `revenue_paid`** — son magnitudes distintas.

## Orden de locks (extiende ADR p12)

```
CashSession → MedicalRecord → Invoice → Presentation → InvoiceItem → MedicalRecordProduct
```

- `CashSession` es la **cabeza**. El flujo de pago la lockea ANTES de Invoice
  cuando `require_open_cash_session` esta activo (`billing.services._resolve_cash_session_for_payment`).
- `close_cash_session` lockea **solo** `CashSession` (nunca Invoice) → no hay par
  {Invoice, CashSession} en orden inverso → sin ABBA.
- Invariante: una vez que `close` toma el lock, un pago en vuelo se serializa; al
  reanudar ve `status != 'open'` y es rechazado. **Ningun pago se cuela tras el
  conteo.** Verificado por `apps.cash.tests.test_cash_concurrency` (Postgres+threads).

## Integracion con el flujo de pago

Toggle `OrganizationSettings.require_open_cash_session` (**default `False`** →
comportamiento actual intacto, caja opcional).

Si `True`: `post_checkout(..., pay=True)` / `pay_invoice` exigen una caja abierta del usuario;
el `Payment` se ata a esa sesion (`cash_session`). Sin caja abierta (o cerrada) →
`ValidationError` → 400 ("No hay una caja abierta…").

**Asociación ≠ obligatoriedad (ADR p39):** si el actor tiene caja abierta, todo
`Payment` / `RefundPayment` / `RefundReversal` se ata a esa sesión **siempre**, con o
sin el toggle. El toggle solo decide si el cobro se **bloquea** cuando NO hay caja
abierta (ON → 400; OFF → pago sin sesión). Antes de p39, con el toggle apagado el pago
quedaba sin sesión aunque hubiera caja abierta → el Z reportaba $0 ventas (diferencia
falsa).

## Movimientos manuales del cajón (`CashMovement`, ADR p39)

Entradas/salidas de efectivo **no ligadas a una factura** (fondo, retiros, gastos
menores del cajón). Modelo público (`PublicIdMixin`) append-only — sin PATCH/DELETE;
corrección = contra-movimiento (invariante append-only del sistema).

Campos: `movement_type` (`deposit` | `withdrawal` | `expense`), `amount` (CHECK
`cashmovement_amount_positive`: `> 0`), `reason` (obligatorio, sanitizado ≤255),
`cash_session` (FK PROTECT), `actor` (SET_NULL), `occurred_at`. **Solo efectivo** (es el
cajón físico).

Writer único: `cash/services.register_cash_movement(user, movement_type, amount, reason)`.
Lockea la `CashSession` (cabeza del orden global) → serializado contra el cierre Z: si
el cierre gana el lock, la función ve `status != 'open'` y rechaza (ningún movimiento se
cuela tras el conteo).

Efecto en el Z: `deposit` **suma** a `expected_cash`; `withdrawal`/`expense` **restan**
(ver §Calculo del Z). El `closed_snapshot` v3 incluye `movements_by_type` y `movements_count`.

Bloquea: registrar sin caja abierta → 400; sobre caja cerrada (el lock lo garantiza);
`amount <= 0` o `reason` vacío → 400.

## Endpoints

| Metodo | URL | Permiso |
|--------|-----|---------|
| `POST` | `/api/cash/sessions/open/` | `cashsession.open` |
| `POST` | `/api/cash/sessions/<str:pk>/close/` | `cashsession.close` |
| `GET`  | `/api/cash/sessions/current/` | `cashsession.retrieve` |
| `GET`  | `/api/cash/sessions/` (`?status=`) | `cashsession.list` |
| `GET`  | `/api/cash/movements/` (`?session=<public_id>`) | `cashmovement.list` |
| `POST` | `/api/cash/movements/` | `cashmovement.create` |

Body de open: `{opening_float, notes?}`. Body de close: `{counted_cash, notes?, force?}`.
Body de `movements/` (POST): `{movement_type, amount, reason}`.
`current` devuelve la sesion abierta o `{"session": null}`.

## RBAC

Codigos `cashsession.{list,retrieve,open,close}` y `cashmovement.{list,create}`
(ADR p39) en `PERMISSION_CODES`. Asignados a ADMIN, VET y ASSISTANT (recepcion
opera caja). Requiere `seed_permissions` en el siguiente deploy.

## Analytics

Desacoplado de `revenue_paid` (que ancla en `Invoice.paid_at`, independiente de la
caja). El Z es reconciliacion operativa — **no** entra a `DailyOrgMetrics` en v1.
La sesion abierta (`current`) es live; nunca se snapshotea. Una metrica futura de
"diferencias de caja/dia" entraria por gobernanza `ANCHOR_REGISTRY` (ADR p17).

## Observabilidad

Logger `cash.events` (JSON stdout): `CASH_SESSION_OPENED`, `CASH_SESSION_CLOSED`
(con `difference`), `CASH_SESSION_FORCE_CLOSED`, `CASH_MOVEMENT_REGISTERED` (ADR p39,
con `movement_type` y `amount`).

## Diferido

- Caja por Register/Terminal (multi-recepcionista) — `DD-004`. Reportes ya se
  llavean por `CashSession.public_id`, no por user.
- Tabla `CashSessionSnapshot` materializada (grado fiscal/export) — `DD-003`.
