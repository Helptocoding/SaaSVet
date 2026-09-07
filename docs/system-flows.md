# Flujos completos del sistema

**Fecha**: 2026-09-07

**Estado**: vigente; incluye ADR p62
**Audiencia**: desarrollo, QA, soporte y operaciones.

Este documento resume los recorridos operativos de extremo a extremo. Los
contratos detallados viven en [operaciones por módulo](system-module-operations.md),
[referencia operacional](system-reference.md) y [Billing](modules/billing.md).

## 1. Consulta agendada, atendida y cobrada

```text
Appointment scheduled
  → confirmed (opcional)
  → in_progress
  → MedicalRecord open
  → vitales / servicios / consumos / receta
  → MedicalRecord closed
  → Checkout primary_consultation open
  → decisión de receta: accepted | declined
  → post_checkout
  → Invoice posted
  → Payment(s)
  → Invoice paid
```

Reglas:

- Los servicios y cargos clínicos se registran como evidencia clínica; no crean
  una Invoice mutable.
- Los productos consumidos durante la consulta descuentan stock cuando se
  consumen.
- Cerrar la consulta materializa o adopta exactamente un Checkout y congela los
  snapshots de cargos.
- La receta por sí sola no cobra ni descuenta stock.
- Aceptar una presentación crea una selección/línea comercial; el stock y el
  fulfillment se comprometen juntos al post.
- Una consulta sin cargos termina mediante `complete_no_charge`, sin Invoice.
- El post puede cobrar en la misma transacción o dejar una Invoice `posted`
  sólo cuando el crédito está autorizado.

## 2. Venta directa / POS

```text
Recepción abre POS
  → crea Checkout direct_sale
  → agrega CheckoutItems
  → attestation externa si un producto Rx la requiere
  → backend calcula subtotal / impuesto / total / readiness
  → captura payment lines por total exacto
  → POST /checkouts/{id}/pay/
  → revalidación bajo locks
  → Invoice + InvoiceItems + StockAllocations + StockMovements + Payments
  → Checkout completed / Invoice paid
```

El cliente envía `expected_version` e `idempotency_key`. Repetir la misma
operación devuelve el resultado ya confirmado; una versión obsoleta produce un
conflicto y cero escrituras parciales. Volver al carrito conserva el Checkout
mutable; abandonarlo usa el comando explícito y no crea una Invoice a cancelar.

## 3. Dispensación de receta

```text
PrescriptionItem.quantity (base)
  − PrescriptionFulfillmentEvent.quantity (base)
  − selecciones cap-consuming del Checkout (base)
  = remaining_quantity_base

Product.stock_quantity / StockLot.quantity_on_hand (base)
  ÷ Presentation.conversion_factor (base por presentación)
  = stock_max_presentation_units

max_selectable_quantity
  = min(clinical_max_presentation_units, stock_max_presentation_units)
```

El backend devuelve las tres magnitudes y sus unidades en
`prescription_suggestions`. El frontend sólo las presenta.

Casos relevantes:

- `conversion_factor > remaining_quantity_base` puede producir
  `max_selectable_quantity = 0` de forma válida;
- stock de producto positivo con cero lotes consumibles produce máximo cero;
- `Presentation.stock` desincronizado no cambia el resultado;
- `declined` no consume cap, no crea fulfillment y no mueve stock;
- un reintento no duplica `PrescriptionFulfillmentEvent`.

## 4. Pago posterior de crédito

```text
Checkout autorizado sin pago
  → post_checkout
  → Invoice posted + due_date + evidencia de aceptación
  → pay_invoice con total exacto
  → Payment(s)
  → Invoice paid
```

No se admiten pagos parciales ni sobrepagos. Si la configuración exige caja
abierta, los métodos que afectan efectivo deben vincularse a la sesión del actor.

## 5. Corrección de una Invoice posteada

```text
Invoice posted
  → void_and_prepare_replacement
  → Invoice voided
  → Checkout replacement open con baseline protegido
  → corrección explícita
  → nuevo post
```

Una Invoice emitida no vuelve a ser editable. El replacement conserva la
trazabilidad del documento sustituido y no puede reducir silenciosamente a cero
el baseline entregado sin waiver autorizado y auditado. Una anulación terminal
usa `void_invoice_terminal` con motivo y evidencia.

## 6. Devolución post-pago

```text
Invoice paid
  → CreditNote + CreditNoteItems
  → RefundPayment(s)
  → disposition restock | discard por línea
  → MetricAdjustment
```

La Invoice permanece `paid`. Una devolución no reescribe `paid_at`. El
restock se apoya en las `StockAllocation` comprometidas al post para devolver
cantidades exactas por lote. Un refund emitido por error se corrige con
`RefundReversal`, nunca editando o borrando el evento original.

## 7. Walk-in anónimo

```text
Walk-in in_progress con Pet genérica
  → assign-patient antes de done
  → MedicalRecord
  → mismo flujo clínico y comercial
```

La vinculación a paciente real ocurre antes de cerrar la atención. El
multitenancy y las precondiciones de Appointment continúan aplicando.

## 8. Analytics

```text
Invoice.posted_at → revenue_accrual
Invoice.paid_at → revenue_paid / invoices_paid_count
MedicalRecord.closed_at → medical_records_closed
Appointment.start_datetime → métricas operativas
```

`build_daily_metrics` genera snapshots idempotentes por organización y fecha
local. El día actual es live. Los anchors ausentes no reciben fallbacks
silenciosos y los snapshots congelados sólo cambian mediante el flujo de
adjustment/rebuild.

## 9. Flujos válidos

1. Appointment: `scheduled → confirmed? → in_progress → done`.
2. MedicalRecord: `open → closed`; el cierre crea Checkout, no Invoice.
3. Checkout: `open → completed|abandoned`.
4. Invoice: nace `posted` y pasa a `paid` o `voided`.
5. Venta directa: Checkout abierto → post/pago atómico.
6. Crédito: Checkout abierto → Invoice posted → pago total posterior.
7. Sin cargos: Checkout abierto → completed/no_charge, sin Invoice.
8. Refund: Invoice paid → CreditNote/RefundPayment; Invoice sigue paid.
9. Reversal: RefundPayment → RefundReversal append-only.
10. Dispensación: selección en Checkout → fulfillment y stock al post.

## 10. Flujos inválidos

- Crear una Invoice `draft` para editarla.
- Confirmar o cancelar una Invoice con el lifecycle retirado.
- Editar Invoice o InvoiceItem después del post.
- Pagar menos o más que el saldo total.
- Pagar dos veces o duplicar fulfillment/stock al reintentar.
- Postear con `expected_version` obsoleta.
- Dispensar más unidades base que el remanente clínico.
- Usar `Presentation.stock` como autoridad.
- Postear un producto con lotes sin allocations consumibles suficientes.
- Vender un producto Rx sin receta interna o attestation externa válida.
- Mutar eventos financieros en vez de emitir un contra-asiento.
- Acceder a recursos de otra organización.
- Omitir los gates de schema en un despliegue de Billing.

Antes de release ejecutar `audit_billing_schema --json` y
`audit_anchor_integrity --json`; para schema drift seguir el
[runbook de reconciliación](runbooks/billing-schema-reconciliation.md).
