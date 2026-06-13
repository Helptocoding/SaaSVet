# ADR p38: Punto de Venta — pantalla dedicada y checkout en 2 pasos server-driven

**Fecha**: 2026-06-12
**Estado**: Aceptado — implementado
**Documentos relacionados**:
- ADR p25 (cliente real en venta directa)
- ADR p26 (atestación de receta externa)
- ADR p27 (payment_lines + idempotencia)
- ADR p30 rev (total exacto, cambio no persistido)
- DD-010 en `docs/deferred-decisions.md` (resuelta por este ADR)
- `docs/modules/frontend.md` § Punto de Venta
- `docs/modules/billing.md` § Venta directa
- `frontend/src/pages/pos/`, `frontend/src/components/pos/`

## Contexto

La venta directa vivía en un modal ("Nuevo Cobro") dentro de `/billing` con tres
problemas detectados en la auditoría de 2026-06-12:

1. **Dos UX de pago para la misma operación contable.** El modal cobraba con un
   método único (`payment_method` legacy) sin recibido/cambio/split, mientras que
   el detalle de factura usaba `PaymentLinesEditor` (total exacto, cambio en
   efectivo, split). La queja operativa: "cliente paga $500, total $320, cambio
   $180" no existía en el flujo más frecuente de recepción.
2. **Barcode sin wiring.** `Presentation.barcode` + índice único parcial por org +
   endpoint `GET /inventory/presentations/barcode/` existían desde ADR p31 ("para
   POS scanner") pero ningún componente los consumía; la búsqueda del modal solo
   filtraba `product__name__icontains`.
3. **Modal no optimizado para mostrador**: SearchSelect→click→repetir, cantidad
   no editable en tabla, total poco prominente.

Además, DD-010 difería el split en la venta rápida porque exigía conocer el total
con IVA **antes** de crear la factura sin reintroducir drafts huérfanos (ADR p11),
y `tax_rate` de la organización no está expuesto al frontend.

## Decisión

### 1. Separación por pantallas, no por modelos

```
/pos      → venta rápida de mostrador (pantalla dedicada, reemplaza al modal)
/billing  → listado de documentos: facturas, dispensación, devoluciones, pagos
/cash     → turnos de caja + cierre Z (sin cambios)
```

La separación es **100% navegación/UI**: cero endpoints nuevos, cero modelos,
cero migraciones. `Invoice(invoice_type='direct_sale')` sigue siendo el modelo de
la venta de mostrador — **no** se crean entidades paralelas (`Sale`, `Ticket`,
`Order`): duplicarían el ledger y los anchors analíticos.

"+ Cobro" y F11 en `/billing` navegan a `/pos`.

### 2. Checkout en 2 pasos, server-driven

El frontend **no replica** `money.invoice_totals` (regla: cero matemática
financiera en React; `tax_rate` no está expuesto). En su lugar:

```
modo cart    → carrito en estado local; panel muestra "Total estimado" (subtotal)
   "Cobrar"  → createInvoice(direct_sale) + addInvoiceItem ×N + getInvoice
modo paying  → panel muestra subtotal/IVA/total REALES del backend
              + PaymentLinesEditor (split, total exacto, cambio — ADR p30 rev)
   "Confirmar cobro" → direct-pay atómico con X-Idempotency-Key
```

Esto resuelve el timing de DD-010: el total con IVA se conoce porque la factura
draft ya existe cuando se captura el pago — sin calcular impuestos client-side.

**Gestión del draft intermedio (no quedan huérfanos):**

- "Volver al carrito", error al preparar el cobro y desmontaje de la página en
  modo pago → `cancelInvoice` del draft (PATCH `cancel/`, auditable vía
  `InvoiceAuditLog`; `invoice.cancel` está en los 3 roles).
- Fallo del pago (caja cerrada, stock race) → se conservan draft + idempotency
  key para reintentar sin doble cobro.
- Editar la venta tras "Cobrar" = cancelar draft + crear uno nuevo al recobrar.
  Trade-off aceptado: filas `cancelled` en el listado (honesto y auditado) a
  cambio de no sincronizar ítems en vivo contra el backend.

### 3. Lógica de pago compartida (única fuente)

- `components/PaymentLinesEditor.jsx` — extraído de `billing.jsx`; lo usan
  Registrar Pago (consulta), devoluciones (ADR p29) y POS.
- `utils/payments.js` — `PAYMENT_METHODS`, `paymentLinesValid()`,
  `buildPaymentLines()` (regla de sobrepago→se registra solo el total, ADR p30
  rev). Prohibido copiar esta lógica por módulo.
- `utils/idempotency.js` — `newIdempotencyKey()`.

### 4. Escáner de código de barras

Un lector USB actúa como teclado (escribe el código + Enter). El input único del
POS (`ProductSearch`) intercepta Enter:

1. Lookup exacto `GET /inventory/presentations/barcode/?barcode=` → agrega qty 1
   (re-escaneo incrementa).
2. 404 → cae a la búsqueda por nombre (productos + servicios).

## Consecuencias

**Positivas**: flujo de pago unificado (recibido/cambio/split en toda venta);
escáner USB funcional sin hardware-specific code; totales siempre del backend;
DD-010 resuelta; `billing.jsx` −420 líneas (modal eliminado).

**Negativas / deuda aceptada**:
- Cerrar la pestaña del browser (no navegación in-app) en modo pago deja un draft
  sin cancelar — sin `beforeunload` en el scope básico.
- Secuencia `createInvoice + addItem ×N` no es atómica (igual que el modal
  legacy); un fallo a medias se cancela client-side. Candidato post-beta: endpoint
  de checkout batch atómico **solo si** el litter resulta un problema real.

**Excluido explícitamente de este sprint** (decisión de producto): tickets
imprimibles, `CashMovement` (retiros/gastos de caja — gap real: un retiro produce
diferencia falsa en el Z), atajos de teclado avanzados, refactor financiero.
