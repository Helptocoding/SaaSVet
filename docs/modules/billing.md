# Módulo: Checkout, Cobros y Dispensación

**Contrato vigente desde:** 2026-09-06

**Autoridad arquitectónica:** [ADR p62](../decisions/2026-08-30-p62-billing-checkout-lifecycle.md)

**Auditoría de regresión:** [Checkout/Billing/Dispensación](../audits/2026-09-05-checkout-billing-regression-audit.md)
**Operación de schema:** [Runbook de reconciliación](../runbooks/billing-schema-reconciliation.md)

Este documento describe exclusivamente el runtime actual. Los documentos fechados
que describen `Invoice draft → confirmed → paid/cancelled` son evidencia histórica,
no contratos ejecutables.

**Orden 2 (28-10-2026):** Invoice nunca es objetivo físico: `InvoiceAuditLog.invoice` PROTECT y UUID de documento estable. `Invoice.owner/.pet` y `Checkout.customer/.pet` permiten separación **solo** por la API física de plataforma si se conserva `subject_snapshot` v1, documento settled y sin deuda; el PDF, detalle y filtros leen nombre/UUID históricos sin ofrecer un selector vivo. `Invoice.clean()` sigue exigiendo Checkout y cliente al crear; claves compuestas `(id, organization_id)` más FKs relacionales y triggers PostgreSQL de `billing.0038/.0041` cubren INSERT, UPDATE y cambio de padres aun con bulk/raw SQL. El Checkout previo a archivo mantiene su obligación y la Invoice posted existente se puede pagar después de archivar. El borrado normal de Invoice continúa bloqueado.

## 1. Responsabilidad y límites

Billing separa cuatro hechos con ciclos de vida distintos:

```text
MedicalRecord closed
        ↓
Checkout open (preparación mutable)
        ↓ post/pay atómico
Invoice posted (documento inmutable)
        ↓ pago total
Payment ledger / Invoice paid
```

- `Checkout` conserva intención comercial editable, decisiones de receta,
  readiness, versión y evidencia previa a emitir.
- `Invoice` nace sólo al postear. No funciona como carrito ni tiene estados
  `draft` o `confirmed`.
- `Payment`, `RefundPayment` y `RefundReversal` son eventos financieros
  append-only; no se simulan cambiando el estado de Invoice.
- Stock y fulfillment Rx se materializan al post exitoso, no al seleccionar.
- Una consulta sin cargos termina `Checkout.completed/no_charge` sin crear Invoice.

## 2. Modelos autoritativos

### Checkout

- `origin`: `consultation` o `direct_sale`.
- `kind`: `primary_consultation`, `prescription_supplement`, `direct_sale` o
  `replacement`.
- `lifecycle`: `open → completed|abandoned`.
- `completion_kind`: distingue `posted_paid`, `posted_unpaid`, `no_charge` y demás
  resultados terminales.
- `version`: optimistic concurrency. Todo comando mutante debe declarar la versión
  observada; una versión stale produce `409` sin efectos parciales.
- Readiness y acciones disponibles son proyecciones derivadas. No existe un estado
  persistido `ready`.

### CheckoutItem

- Servicio y Presentation son XOR.
- Una línea con Presentation guarda `quantity` en unidades comerciales enteras y
  `conversion_factor_snapshot` en unidades base por presentación.
- Una línea de servicio tiene `conversion_factor_snapshot = NULL`; una línea con
  Presentation debe tener snapshot positivo. El CHECK de base impone ambas ramas.
- El snapshot captura el factor aceptado al crear la línea. Editar después el
  catálogo no reinterpreta un Checkout ya preparado.
- `lot` expresa una selección/override de intención. Las allocations físicas se
  deciden y persisten al post bajo locks.

### Invoice

- Tipos: `consultation` y `direct_sale`.
- Estados: `posted → paid` o `posted → voided`.
- Anchors: `posted_at`, `paid_at`, `voided_at`, cada uno con provenance.
- No existen `confirmed_at`, `confirmed_at_source`, `cancelled_at`, `draft`,
  `confirmed` ni `cancelled` en el contrato vigente.
- Una Invoice y sus InvoiceItems son snapshots financieros inmutables. La colección
  `/api/billing/invoices/` es de lectura; la creación genérica está deshabilitada.
  `InvoiceSerializer` e `InvoiceItemSerializer` son de solo lectura y no validan
  escrituras. El tipo de la Invoice lo fija `Checkout.origin` (orden 6, C2).

### InvoiceItem y ledgers físicos

- `InvoiceItem.quantity` retail/Rx permanece en unidades de presentación.
- `conversion_factor_snapshot` se copia desde CheckoutItem.
- `StockAllocation.quantity_base` registra la cantidad base realmente comprometida
  por Product/lote/movimiento. Una línea puede tener 1..N allocations.
- `StockDispositionEvent` registra entrega, devolución o descarte en unidades base.
- Las devoluciones son únicas por `(credit_note_item, allocation)`, no sólo por
  línea financiera; esto permite revertir exactamente cada lote original.

### Receta y fulfillment

- `CheckoutPrescriptionSelection` guarda la decisión `pending|accepted|declined` y
  el remanente elegible observado al abrir; no guarda una cantidad seleccionada.
- La selección actual se deriva de CheckoutItems activos ligados al
  PrescriptionItem.
- `PrescriptionFulfillmentEvent` es append-only y nace únicamente en el post
  exitoso. Seleccionar o pagar una Invoice ya posteada no crea un segundo event.
- `quantity_delta` consume el cap legal; `physical_quantity` registra la cantidad
  físicamente entregada o devuelta. Redelivery puede mover stock con delta legal
  cero.

## 3. Contrato inequívoco de unidades

| Magnitud | Unidad |
|---|---|
| `PrescriptionItem.quantity` | unidades base de `Product.base_unit` |
| fulfillment `quantity_delta` / `physical_quantity` | unidades base |
| CheckoutItem/InvoiceItem retail `quantity` | unidades enteras de Presentation |
| `conversion_factor_snapshot` | unidades base por Presentation |
| `Product.stock_quantity` | unidades base agregadas; autoridad física |
| `StockLot.quantity_on_hand` | unidades base del lote; autoridad si usa lotes |
| `StockAllocation.quantity_base` | unidades base committed |
| `Presentation.stock` | proyección legacy/display; no autoridad de Billing |
| `Presentation.quantity` | alias legacy de formato; no autoridad de Billing |

Conversión canónica:

```text
quantity_base = quantity_presentation × conversion_factor_snapshot
whole_presentations = floor(quantity_base / conversion_factor)
```

Presentaciones retail/Rx son indivisibles. Si una receta tiene 2 tabletas base y el
único formato es una caja de 100, el máximo correcto es 0 cajas; el catálogo necesita
un formato compatible. Nunca se fuerza artificialmente un máximo de 1.

## 4. Disponibilidad Rx: autoridad única

`billing/prescription_availability.py` calcula la proyección que consumen API,
writers y frontend. El navegador no reconstruye cap, conversión ni stock.

Por PrescriptionItem se exponen, como strings decimales cuando están en base:

| Campo | Significado |
|---|---|
| `prescribed_quantity_base` | cap prescrito original |
| `fulfilled_quantity_base` | suma histórica de `quantity_delta` |
| `selected_quantity_base` | demanda Rx activa del Checkout actual |
| `selected_cap_consuming_quantity_base` | parte seleccionada que consume cap legal |
| `legal_remaining_quantity_base` | `max(prescribed - fulfilled - selected_cap, 0)` |
| `neutral_redelivery_remaining_quantity_base` | allowance física que no reconsume cap |
| `eligible_remaining_at_open_base` | snapshot de auditoría al abrir la selección |
| `base_unit` | unidad base canónica del Product |

Por Presentation:

| Campo | Significado |
|---|---|
| `conversion_factor_base_per_presentation` | base por presentación vigente para una selección nueva |
| `available_stock_quantity_base` | stock físico autoritativo observado |
| `checkout_stock_demand_quantity_base` | demanda activa de todo el Product en este Checkout |
| `available_stock_after_checkout_quantity_base` | headroom físico incremental |
| `clinical_max_additional_quantity` | presentaciones enteras permitidas clínicamente |
| `stock_max_additional_quantity` | presentaciones enteras disponibles físicamente |
| `max_selectable_quantity` | `min(clinical, stock)`; siempre cantidad adicional |
| `max_selectable_semantics` | `additional_presentation_units` |
| `blocking_reasons` | explicación estructurada del cero/límite |
| `lots` | desglose informativo FEFO en unidades base y presentaciones |

Reason codes actuales:

- `checkout_not_open`
- `prescription_fulfilled`
- `below_presentation_size`
- `out_of_stock`
- `no_consumable_lot`
- `stock_below_presentation_size`

Los aliases `prescribed_quantity`, `dispensed_quantity`, `remaining_quantity` y
`conversion_factor` sólo existen por compatibilidad y se derivan de esta proyección.
No se permite otra implementación del cálculo.

## 5. Stock y lotes

- `Product.stock_quantity` es la autoridad agregada.
- Para Products lot-tracked, la disponibilidad usa también la suma de StockLots
  activos, no vencidos y con saldo; ante drift se usa el menor saldo observable y
  `audit_stock_integrity` debe reconciliar.
- Billing nunca decide disponibilidad desde `Presentation.stock`.
- El post replantea FEFO bajo locks deterministas Product → Lot, revalida tenant,
  estado, expiración y saldo, y puede comprometer 1..N lotes.
- Availability es observación, no reserva. El post bajo lock sigue siendo árbitro
  ante concurrencia.
- Refund y void revierten slices contra sus StockAllocations originales. Una línea
  sin allocation física no puede fabricar una reposición.

## 6. Flujo de consulta y dispensación

1. Mientras MedicalRecord está abierto, servicios/productos generan evidencia
   clínica y ClinicalChargeEntry/QuantityEvent; no crean Invoice.
2. Cerrar la consulta crea o adopta un único Checkout `primary_consultation`, copia
   snapshots clínicos y abre decisiones Rx.
3. `accepted` agrega CheckoutItems ligados a PrescriptionItem; `declined` conserva
   la receta sin demanda física.
4. Seleccionar no mueve stock ni escribe fulfillment.
5. `post`/`pay` vuelve a validar readiness, cap, snapshots y stock bajo locks.
6. En un único commit crea Invoice/InvoiceItems, StockMovements/Allocations,
   FulfillmentEvents, evidencia y, para pay, Payments.

Un `prescription_supplement` permite dispensar posteriormente una decisión declinada
sin reabrir la consulta ni mutar la Invoice anterior.

## 7. Comandos, idempotencia y permisos

Comandos terminales y dispensación reclaman `CommandReceipt` mediante
`(organization, command_kind, idempotency_key)` y hash de payload canónico:

- mismo key + mismo payload: replay del resultado committed;
- mismo key + payload distinto: conflicto sin nuevos efectos;
- mismo Checkout + keys concurrentes: el lock/versionado permite una sola transición.

`expected_version` es obligatorio en pay/post/dispense y mutaciones de líneas. Los
payloads críticos se validan con serializers; cantidades no finitas, fracciones de
Presentation y estructuras inválidas se rechazan antes del dominio.

| Operación | Permiso principal | Resultado |
|---|---|---|
| crear venta directa | `invoice.create` | Checkout open |
| agregar/editar línea | `invoice.create` / permiso Rx si aplica | nueva versión |
| aceptar/declinar Rx | `checkout.prescription_decide` | decisión auditable |
| dispensar Rx | `billing.rx_dispense` también en service | líneas incrementales idempotentes |
| cobrar Checkout | `invoice.pay` | Invoice paid + Payment + stock |
| postear crédito | `invoice.post_unpaid` | Invoice posted/unpaid + evidencia |
| pagar Invoice posted | `invoice.pay` | Invoice paid |
| void terminal | `invoice.void_terminal` | Invoice voided + disposition |
| void + replacement | `invoice.replace` | Invoice voided + Checkout replacement |
| refund/reverse | `billing.refund` | CreditNote y contra-eventos |

## 8. Endpoints principales

| Método | Ruta | Contrato |
|---|---|---|
| GET | `/api/billing/checkouts/` | lista preparación comercial |
| POST | `/api/billing/checkouts/direct-sale/` | crea Checkout POS |
| GET | `/api/billing/checkouts/{id}/` | readiness, acciones, Rx y versión |
| POST | `/api/billing/checkouts/{id}/items/` | agrega línea |
| PATCH/DELETE | `/api/billing/checkouts/{id}/items/{item}/` | muta intención con versión |
| POST | `/api/billing/checkouts/{id}/prescriptions/{item}/decision/` | acepta/declina |
| POST | `/api/billing/prescriptions/{rx}/dispense/` | dispensación incremental |
| POST | `/api/billing/checkouts/{id}/pay/` | post + pago atómico |
| POST | `/api/billing/checkouts/{id}/post/` | post unpaid con evidencia |
| POST | `/api/billing/checkouts/{id}/complete-no-charge/` | completa sin Invoice |
| POST | `/api/billing/checkouts/{id}/estimate/` | snapshot no financiero |
| GET | `/api/billing/invoices/` | lista documentos emitidos; POST deshabilitado |
| GET | `/api/billing/invoices/{id}/` | documento inmutable |
| POST | `/api/billing/invoices/{id}/pay/` | paga saldo total posted |
| POST | `/api/billing/invoices/{id}/void/` | void terminal |
| POST | `/api/billing/invoices/{id}/void-and-prepare-replacement/` | corrección atómica |
| POST | `/api/billing/invoices/{id}/refund/` | CreditNote + refund/disposition |

El idempotency key puede viajar en el body tipado y, en comandos que lo soportan,
en `X-Idempotency-Key`. El frontend debe conservarlo durante retries.

## 9. Analytics y dinero

- `posted_at` alimenta revenue accrual.
- `paid_at` alimenta cash-basis e invoices paid.
- `voided_at` registra anulación/provenance; no reemplaza CreditNote.
- `Invoice.status='paid'` implica balance pendiente cero.
- `Invoice.status='posted'` implica balance pendiente positivo.
- Payments parciales y sobrepagos están prohibidos en el writer actual.
- Refund no reabre Invoice ni cambia `paid_at`; el neto se obtiene de Payments menos
  RefundPayments más RefundReversals.

## 10. Schema contract y despliegue

Migrations relevantes:

- `billing.0026`: replacement declarado del historial huérfano.
- `billing.0027`: puente ejecutable para old-only schema.
- `billing.0033`: repair/verify idempotente de anchors, constraints e índices.
- `billing.0034`: contract forward-only que elimina columnas/índice confirmed.
- `inventory.0025`: factor positivo/representable.
- `billing.0035` e `inventory.0026`: snapshots y devoluciones multilote.

Después de `migrate` debe ejecutarse:

```bash
python manage.py audit_billing_schema --json
python manage.py audit_anchor_integrity --json
python manage.py audit_payment_ledger_integrity --json
python manage.py audit_stock_integrity --json
```

`audit_billing_schema` debe devolver `ok=true` y cero violaciones. Está integrado en
CI. No se permite usar `--fake` para silenciar una diferencia física; seguir el
runbook y demostrar DDL equivalente.

## 11. Invariantes mínimas de prueba

- DB limpia y upgrade desde la `0026` histórica terminan en el mismo schema.
- No existen columnas/indexes confirmed legacy.
- factor 1 y factor >1; remanente menor al paquete produce máximo cero explicado.
- fulfillment parcial/total, selección actual y declined → supplement.
- stock insuficiente, `Presentation.stock` stale y cero lotes consumibles.
- una demanda FEFO puede crear varias allocations y refund/void las revierte todas.
- cambio posterior de factor no reinterpreta Checkout/Invoice/consumo clínico.
- doble pay, retry idéntico, key conflict, version conflict y carreras reales no
  duplican Invoice, Payment, stock ni fulfillment.
