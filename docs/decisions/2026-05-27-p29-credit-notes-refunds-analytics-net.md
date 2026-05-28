# ADR p29: Notas de crédito, refunds y `revenue_paid` net of refunds

**Fecha**: 2026-05-27
**Estado**: Aceptado (diseño) — implementación **Sprint B** (aislado de Sprint A), sin código aún
**Documentos relacionados**:
- `docs/financial-event-model-contract.md` (v1.0 frozen) — §6 (contra-asiento), §8 (net_settled)
- `docs/deferred-decisions.md` — `DD-007`, `DD-002`
- `docs/dashboard-metrics-contract.md` — §2.8 (dual-window), §3.1.1, §4.7, §8
- ADR `2026-05-27-p27` (Payment model — **prerequisito**), `2026-05-09-p9`, `2026-04-26` (receta no es factura)

## Contexto

No existen devoluciones. `cancel_invoice` solo aplica a `draft`/`confirmed` (pre-pago) y la
máquina de estados prohíbe cancelar `paid` — correcto. Pero una factura **pagada** cuyo
producto se devuelve necesita **regresar dinero**, y eso no es una cancelación.

El `dashboard-metrics-contract` §3.1.1 ya advierte: *"refunds not supported in v1; if added,
`revenue_paid` must be re-defined as net of refunds."* §2.8 ya tiene escrita la política de
reversos (dual-window con `MetricAdjustments`), pero la tabla **no está implementada**.

Este es el cambio más delicado del roadmap (toca pagos + caja + analytics + snapshots). Por
eso va en un **sprint aislado** (Sprint B), después de que pagos y caja (Sprint A) estén
estables en producción.

## Decisión

### 1. `cancelar` ≠ `devolver`

- **Cancel**: pre-pago (`draft`/`confirmed` → `cancelled`). No mueve dinero. Revierte stock.
- **Nota de crédito / refund**: post-pago. El dinero se cobró → se devuelve. Documento y
  lifecycle distintos. La factura `paid` **permanece `paid`** (terminal, contrato §8.2); no
  reabre, no muta `paid_at`.

### 2. Modelos (billing, append-only)

- `CreditNote` — **público** (`PublicIdMixin`, solo `public_id`, ADR p24). Documento legal.
  `original_invoice` (FK PROTECT), `status` (`issued` terminal), `created_by`, `issued_at`
  (anchor con provenance + CHECK, ADR p9), `total_refunded`, **`reason_code`**, `reason_notes`.
- `CreditNoteItem` — interno (PK). Referencia al `InvoiceItem` original (XOR service/presentation),
  `quantity` devuelta, `amount`, **`disposition`** (`restock | discard`).
- `RefundPayment` — evento financiero (contrato §2/§5, signo `−`). Pertenece a `CreditNote`.
- `RefundReversal` — **contra-asiento** (contrato §6). `reverses = RefundPayment`.

### 3. `reason_code` tipificado (no texto libre)

Choices: `customer_return | damaged_product | expired_product | duplicate_charge |
pricing_error | goodwill | clinical_cancellation | other` + `reason_notes` (sanitizado).
Constante app-level (estilo `SPECIES_CHOICES`, sin `choices=` en el campo → no migrar al
agregar un código), pero estable/queryable para conciliación, auditoría, fraude y reportes
fiscales. La causa vive en el **documento** (`CreditNote`), no en el `RefundPayment`
(contrato §2).

### 4. Productos abiertos/usados

`CreditNoteItem.disposition`:
- `restock` → `apply_stock_movement('in')` bajo lock de `presentation` (caller cumple
  contrato de lock, ADR p13).
- `discard` (vacuna abierta, medicamento parcial) → **sin** movimiento de stock, pero el
  dinero **sí** se reembolsa. Regla veterinaria real, explícita por línea.

### 5. Contra-asiento de refunds (contrato §6)

`RefundReversal` corrige un refund emitido por error **sin editar ni borrar**. Invariantes:
un `RefundPayment` admite **≤1** `RefundReversal`; un `RefundReversal` **no** es reversible
(la corrección de un reversal es un nuevo `RefundPayment`). Es el camino al ledger unificado
(`DD-007`). UX: "revertir devolución", nunca "deshacer" silencioso.

### 6. Analytics — `revenue_paid` net of refunds

- Implementar la tabla **`MetricAdjustments`** (`dashboard-metrics-contract` §2.8):
  `(org, date, metric_name, delta, reason, source_invoice_id, created_at)`.
- Refund/reversal → fila en `MetricAdjustments` en el **día del evento** (no en el día de la
  venta si está frozen). Read-time: `revenue_paid_net(day) = revenue_paid_gross(day) +
  Σ adjustments`. Charts grafican `_net`; `_gross` queryable para auditoría. Tax revertido
  proporcional → adjustment sobre `tax_collected`.
- **Cambio semántico de métrica financiera** → bump `METRICS_SCHEMA_VERSION` (1→2) +
  **dual-write 30 días** + **PO sign-off** (dashboard-contract §8, §4.7).
- **Snapshots frozen jamás se reescriben.** El reverso vive en la ventana abierta.
- **Kill-switch**: flag que hace fallback `_net → _gross` en prod si el net sale mal (la
  ventana dual produce ambos; el fallback es flippear el flag, no rollback de migración).
- **Test de divergencia**: `gross` y `net` solo difieren en exactamente `Σ adjustments` del
  día; cualquier otra diferencia = bug, falla CI.

### 7. Caja (contrato §6, §11; ADR p28)

Refund/reversal en efectivo afecta `expected_cash` de la **sesión abierta actual**
(`refund` resta, `reversal` suma). Si la venta original fue en sesión cerrada, esa sesión
**no** cambia (dual-window aplicado a caja).

### 8. RBAC y append-only

Permiso `billing.refund` (ADMIN / manager). Requiere `seed_permissions` en deploy. Todos los
modelos sin endpoint de edición ni borrado (append-only).

## Alternativas consideradas

1. **Refund reabre el balance de la factura** — descartada (contrato §8.2): forzaría
   `paid → unpaid`, rompiendo `paid_at` inmutable, lifecycle terminal y snapshots frozen.
2. **Restar del día original (frozen)** — descartada. Corrompe historia. Dual-window §2.8.
3. **Editar `Invoice.total`** — descartada. Append-only; el neto se computa en read-time.
4. **Reusar `cancel` para post-pago** — descartada. Mezcla dos lifecycles distintos.
5. **`void`/`delete` de refund** — descartada. El modelo es contra-asiento, no CRUD (§6).

## Consecuencias

Positivas:
- Auditoría legal completa: documento por devolución, factura original intacta.
- Analytics honesto (net) sin corromper snapshots frozen.
- Caja cuadra (refund en efectivo sale del cajón de hoy).
- Preparado para ledger unificado (`DD-007`).

Costos:
- Es el cambio de mayor blast radius → aislado en Sprint B.
- Bump de schema version + ventana dual de 30 días + sign-off (overhead deliberado).

## Relación con el contrato y otros ADRs

Toma campos/invariantes del contrato §6/§8.4; política analytics del dashboard-contract
§2.8/§3.1.1/§4.7/§8. **Depende de ADR p27** (Payment). Hooks futuros (`DD-007`, `DD-002`) en
`deferred-decisions.md` — no se re-explican aquí.
