# ADR p27: Payment model — pagos split y parciales; `Invoice.status` como proyección del ledger

**Fecha**: 2026-05-27
**Estado**: Aceptado (diseño) — implementación Sprint A, sin código aún
**Documentos relacionados**:
- `docs/financial-event-model-contract.md` (v1.0 frozen) — **autoridad de vocabulario/semántica/invariantes**
- `docs/deferred-decisions.md` — `DD-001`, `DD-002`, `DD-006`, `DD-008`, `DD-009`
- `docs/dashboard-metrics-contract.md` — §3.1.1, §4.7
- ADR `2026-05-09-p9` (anchor authority), `2026-05-15-p11` (direct-pay), `2026-05-16-p12/p13` (locks, F())

## Contexto

`Invoice.payment_method` es un único valor (`cash|card|transfer|other`). Un POS real necesita:
- **Pagos mixtos**: efectivo + tarjeta, efectivo + transferencia en una misma operación.
- **Pagos parciales**: el cliente abona en varias entregas (consultation).
- **Idempotencia**: un reintento de red en caja no debe doble-cobrar.

Hoy `pay_invoice` / `pay_direct_sale` reciben un `payment_method` escalar. No hay registro
por movimiento, ni quién cobró cada parte, ni protección contra doble-registro.

Riesgo conceptual adicional: si el sistema crece, aparecerán paths que dejen
`status='paid'` sin que el dinero cuadre (`Σ pagos ≠ total`). Hay que fijar desde ya que el
estado es **derivado** del ledger, no un flag arbitrario.

## Decisión

### 1. Modelo `Payment` (billing, append-only)

Evento financiero según el **contrato** §1–§3. Campos canónicos (§2): `amount` (>0),
`method`, `occurred_at`, `actor`, `cash_session`, `reference`, `idempotency_key`,
`provenance`, `organization`. Una `Invoice` → muchos `Payment`. Modelo **interno** (PK-only,
sin `public_id` salvo trigger navegable — runbook `exposing-new-model.md`).

### 2. `Invoice.status` es proyección del ledger

Invariante financiero real (**contrato** §8.1):
```
remaining_balance(invoice) = invoice.total − Σ(Payment.amount aplicado)
Invoice.status='paid'  ⟺  remaining_balance == 0
```
- `remaining_balance` es **propiedad computada** en v1 (no columna — `DD-001`).
- Writer único en `billing/services.py` (extiende ADR p9 a eventos monetarios).
- `paid_at` (anchor ADR p9) = `occurred_at` del `Payment` que liquida; inmutable (§8.3).
- Refunds **no** entran en `remaining_balance` ni reabren la factura (§8.2; detallado en ADR p29).

### 3. `pay_invoice` / `pay_direct_sale` aceptan `payment_lines`

Firma nueva: `payment_lines = [{method, amount}, ...]` + `idempotency_key`. Validan:
- pago completo / `direct_sale`: `Σ amount == invoice.total`.
- pago parcial (consultation): `Σ amount ≤ remaining_balance`; si llega a 0 → `paid` +
  `paid_at`; si no → permanece `confirmed`.
- Todo en un `transaction.atomic()` bajo orden de locks `CashSession → Invoice` (contrato
  §11). Una línea fallida = rollback total, sin commit parcial.

### 4. Idempotencia (contrato §9)

`X-Idempotency-Key` por intento de cobro; `get_or_create` sobre `(organization,
idempotency_key)`; reintento devuelve el mismo resultado. **Agregar el header a
`CORS_ALLOW_HEADERS`** (regla CLAUDE frontend). Log `IDEMPOTENT_PAYMENT_DEDUPED`.

### 5. `payment_method` deprecado, no dropeado

Migración aditiva: crear tabla `Payment` → backfill 1 `Payment` por invoice `paid`
(`provenance='legacy'`, `actor=NULL`, contrato §10). `Invoice.payment_method` queda como
legacy/derivado. Drop = `DD-009` (post-beta).

### 6. `revenue_paid` no cambia en este ADR

Permanece anclado en `Invoice.paid_at` con semántica de **factura completa** (contrato
§8.4). NO se redefine a `Σ pagos/día` aquí (`DD-008`). Sin bump de `METRICS_SCHEMA_VERSION`,
sin romper comparabilidad histórica. El cambio a net of refunds es ADR p29 (Sprint B).

### 7. Enforcement

Comando `audit_payment_ledger_integrity` (exit 0/1/2, cron-wireable, contrato §8.5):
`paid ⇒ remaining_balance==0`, `confirmed ⇒ remaining_balance>0`. Ratchet anti-regresión.

## Alternativas consideradas

1. **`payment_method` multi-valor (CSV/JSON en la columna)** — descartada. No queryable,
   sin audit por movimiento, sin idempotencia por línea, sin vínculo a caja.
2. **`revenue_paid = Σ pagos/día` desde ya** — descartada. Redefine una métrica financiera y
   destruye comparabilidad histórica de dashboards/snapshots. Diferida con gobernanza
   (`DD-008` + dashboard-contract §4.7/§8).
3. **`remaining_balance` como columna almacenada** — descartada en v1. Reintroduce el
   lost-update cerrado en la auditoría (C2). Diferida (`DD-001`).
4. **Nombrar `InvoicePayment`** — descartada. Acopla el evento a Invoice y bloquea el
   allocation ledger futuro (`DD-006`). El contrato §4 lo prohíbe.

## Consecuencias

Positivas:
- Pagos mixtos y parciales sin bifurcar la máquina de estados (sigue ADR p11).
- Idempotencia real cierra el doble-cobro por reintento de red (gap de p11).
- `Payment` es la **fundación** de caja (p28) y refunds (p29).
- `status` derivado del ledger elimina la deuda conceptual del flag arbitrario.

Costos:
- `payment_method` vive como legacy hasta `DD-009`.
- Backfill de migración (un Payment por invoice paid).
- Costo de cómputo de `remaining_balance` (trivial: 1–3 pagos por factura).

## Relación con el contrato y otros ADRs

Este ADR **no redefine** campos ni invariantes — los toma del contrato §2/§3/§8/§9/§10. Los
hooks futuros (`DD-001/002/006/008/009`) viven en `deferred-decisions.md`; aquí solo se
referencian. ADR p9 (anchor `paid_at`), p11 (direct-pay un solo lock), p12/p13 (orden de
locks + F()). **p28 y p29 dependen de este ADR.**
