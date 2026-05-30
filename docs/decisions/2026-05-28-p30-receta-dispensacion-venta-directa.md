# ADR p30: Cierre garantiza factura + dispensación de receta en la misma factura de consulta

**Fecha**: 2026-05-28 (revisado 2026-05-29)
**Estado**: Aceptado — implementado
**Documentos relacionados**:
- ADR `2026-05-05-p7` (lazy invoice creation) — esta ADR la supera en el camino de cierre
- ADR `2026-05-27-p26` (attestation receta externa) — relación directa (rx interna vs externa)
- ADR `2026-05-16-p12` (orden global de locks), `2026-05-09-p9` (anchor authority)
- ADR `2026-04-26` "receta no es factura" — se mantiene: la receta sola no cobra ni mueve stock
- `docs/modules/billing.md`, `docs/modules/medical_records.md`, `docs/modules/inventory.md`

## Contexto

Tres síntomas reportados tras el refactor del stepper de consulta:

1. Consulta finalizada no aparecía en Cobros. Causa: `close_medical_record` solo cambiaba
   `status`; la factura se creaba *lazy* (ADR p7) solo al agregar insumos/servicios o al marcar
   la cita `done` (signal `create_draft_invoice_on_done`). Una consulta clínica sin cargos
   nunca generaba `Invoice` → nada en Cobros, pese a que el botón promete "enviar a Cobros".
2. Botón "Finalizar" persistía tras cerrar. Causa: `can_close_medical_record` no validaba
   `status == CLOSED` (su gemela `can_modify_medical_record_charges` sí). Fix aislado.
3. Receta hecha en consulta no llegaba a un cobro. La receta es registro clínico
   (`prescriptions.Prescription`, OneToOne a `MedicalRecord`); no descuenta stock ni cobra (ADR
   "receta no es factura"). Pero el negocio necesita que recepción **ofrezca** esos productos al
   cliente en caja: el cliente decide si los lleva.

Requisito de negocio:
- Finalizar **siempre** deja la consulta en Cobros.
- Insumos usados + servicios: descuentan stock (al consumirse en consulta) y se cobran. Sin cambio.
- Receta: NO descuenta stock automáticamente. Recepción decide por ítem **cobrar** o **quitar**.
  Lo que el cliente decide llevar se **agrega a la MISMA factura de consulta** (no se crea una
  factura aparte) y descuenta stock al cobrarse; lo no llevado no toca inventario.

## Decisión

### 1. Cierre garantiza la factura de consulta

`close_medical_record` llama a `get_or_create_invoice_for_medical_record(mr)` dentro de su
`atomic()` ya existente, tras escribir `status/closed_at`. El MR ya está lockeado
(`select_for_update`); el helper lockea la Invoice respetando el orden canónico
`MedicalRecord → Invoice`. Resultado: toda consulta cerrada tiene una `Invoice` draft (puede ser
$0). **Supera ADR p7** en el camino de cierre: la creación deja de ser puramente lazy. El resto
de caminos (sync de insumos/servicios, signal de cita `done`) siguen usando el mismo helper, sin
duplicación.

### 2. Dispensación de receta = líneas agregadas a la MISMA factura de consulta

Lo que el cliente decide llevar se inserta como `InvoiceItem`(s) en la **factura de consulta**
existente (resuelta vía `get_or_create_invoice_for_medical_record`), NO en una factura aparte.
Servicio `billing.services.dispense_prescription_into_invoice(prescription, lines, user)`:
- exige que la factura esté en `draft` (los ítems se agregan antes de confirmar);
- crea/agrega un `InvoiceItem` por presentación elegida con
  `dispensed_from_prescription_item` seteado (agrega cantidades por presentación:
  `unique_together(invoice, presentation)`);
- **no mueve stock**: el descuento ocurre al **confirmar** la factura de consulta;
- orden de locks `MedicalRecord → Invoice → Presentation → InvoiceItem` (CLAUDE.md).

Endpoint: `POST billing/prescriptions/<public_id>/dispense/`, body
`{ "lines": [{ "presentation": <pk>, "quantity": <num>, "prescription_item": <pk> }] }`.
Permiso base `invoice.create`. Devuelve la factura de consulta actualizada (200). "Quitar" en la
UI = no incluir la línea (no-op, sin persistencia ni auditoría — DD: declinación no se registra
en v1).

### 3. Ruta ÚNICA de descuento de stock (no se crea una segunda)

El descuento de stock por ítem corre por **una sola** función: `_confirm_locked_invoice` (al
confirmar) y su espejo en `cancel_invoice` (al revertir). Antes gateaba por
`invoice_type == 'direct_sale'`. Ahora el predicado se generaliza con el helper
`_items_settling_stock(invoice, items)`:

- **direct_sale**: todo ítem con presentación (venta directa pura, ej. POS walk-in).
- **consultation**: SOLO los ítems dispensados de receta (`dispensed_from_prescription_item`
  seteado). Los demás ítems con presentación (sincronizados desde `MedicalRecordProduct`) YA
  descontaron stock al consumirse en consulta; volver a moverlos sería doble descuento. Los
  servicios no tienen presentación → nunca mueven stock.

El loop de `apply_stock_movement` y el orden de locks no cambian: misma ruta, predicado más
amplio. **No hay una segunda función de descuento de stock.** Verificado por
`apps.billing.tests.test_invoice_concurrency` (sin reordenar locks) y por
`apps.billing.tests.test_prescription_dispense`.

### 4. Enlace a nivel de línea: `InvoiceItem.dispensed_from_prescription_item` (FK)

El enlace vive en el **ítem**, no en la factura. FK nullable a `PrescriptionItem`
(`related_name='dispensed_invoice_items'`, `on_delete=SET_NULL`). Doble función:
1. **Provenance**: qué línea de receta surtió esta línea de cobro.
2. **Discriminador de stock**: es la marca que `_items_settling_stock` usa para distinguir, en
   una consulta, el ítem dispensado (descuenta al confirmar) del insumo sincronizado (ya
   descontó). Migración `billing/0023`.

> Descartado (revisión 2026-05-29): la primera versión creaba una `Invoice` `direct_sale` aparte
> con `Invoice.dispensed_from_prescription`. Se rechazó: el cliente quería las líneas en la MISMA
> factura de consulta y reusar exactamente la ruta de descuento existente. El FK migró de
> `Invoice` a `InvoiceItem`.

### 5. Producto `requires_prescription`: la receta interna es el respaldo legal

Dispensar un producto `requires_prescription` contra la **receta interna** NO crea
`ExternalPrescriptionAttestation` (ADR p26, que cubre la venta SIN receta previa). La
`Prescription` interna + el FK `dispensed_from_prescription_item` son el rastro legal. Se exige el
mismo permiso `billing.rx_dispense` que la dispensación externa; el gate vive en la view
(`dispense_prescription`) antes de invocar el service. No se inventa bypass: mismo permiso,
distinto documento de respaldo.

### 6. Selección de presentación por recepción

`PrescriptionItem` apunta a `Product` (puede tener varias presentaciones/precios). Recepción
**elige** la presentación de venta por ítem. `InvoiceSerializer.prescription_suggestions`
(gateado a detalle vía `with_prescription_suggestions`, sin N+1 en lista) expone por ítem:
`prescription_item_id`, `product_name`, `dose`, `suggested_quantity` y `presentations[]` (`id`,
`name`, `sale_price`, `stock`). Se expone también `prescription_public_id` (receta de la
consulta). El front envía `prescription_item` por línea para fijar el FK de provenance; el ítem
dispensado se marca en `InvoiceItemSerializer.dispensed` (la UI lo etiqueta "para llevar").

### 7. Pago: total exacto SIEMPRE — sin parcial bajo ningún motivo (rev 2026-05-29)

Toda factura (consulta y venta directa) se cobra completa. Backend: `pay_invoice` corre
con `require_full=True` igual que `pay_direct_sale`; la suma de `payment_lines` debe
igualar el saldo exacto. **Supera la regla original de ADR p27** que admitía parcial en
consulta — decisión de producto: la factura se cobra completa en un solo evento de cobro
(split de métodos sigue válido: efectivo+tarjeta sumando el total).

`allowChange` aplica **universalmente** (no solo a venta directa): efectivo recibido >
total muestra el cambio (`recibido − total`) y registra **solo el total** (el cambio es
info de mostrador, **no se persiste**: no es `Payment`, no afecta `remaining_balance` ni
caja). Frontend: `payAllowPartial = false` siempre; `allowChange = true` siempre;
`submitPayment` capea al total en cualquier sobrepago.

Pagar menos del total devuelve `ValidationError` del backend
(`test_consultation_rejects_partial_payment`).

### 8. Errores de integración corregidos (mismo cambio)

- **Orden de Cobros**: `InvoiceListCreateView` ordena `-created_at` explícito. El
  `.annotate(Sum(...))` del ledger (ADR p27) descartaba el `Meta.ordering`
  (`query.order_by` vacío → orden de heap).
- **sonner v2**: `toast.promise(p)` no resuelve a la data de `p`. Usar
  `const x = await toast.promise(...)` dejaba `selectedInvoice` sin `items` (crash) y la respuesta
  sin `public_id`. Fix: await la promesa original. Ver `docs/modules/frontend.md` (Toaster).

## Consecuencias

- Una visita con receta produce **una sola** factura (la de consulta): insumos + servicios +
  lo dispensado conviven en ella. Contablemente es un único acto de cobro.
- Consultas clínicas sin cargos generan drafts $0 en Cobros (trade-off aceptado del punto 1).
- `unique_together(invoice, presentation)`: un producto usado como insumo Y dispensado en la
  misma presentación no puede tener dos líneas. Si ya existe como insumo (sin FK), la
  dispensación se rechaza y recepción ajusta la cantidad a mano. Si ya existe como dispensado, se
  agrega cantidad (vía `apply_invoice_item_quantity_delta`, F()).
- No hay tracking de dispensación parcial en v1: cada apertura del panel ofrece todos los ítems de
  la receta; recepción elige. Si se requiere "ya dispensado" se aborda en una ADR futura.
- `prescription_suggestions` y el panel de Cobros solo aplican mientras la factura está en
  `draft` (los ítems se agregan antes de confirmar).

## Cambios

- `medical_records/policies.py`: guard `status == CLOSED` en `can_close_medical_record`.
- `medical_records/views.py`: `close_medical_record` llama `get_or_create_invoice_for_medical_record`.
- `medical_records/serializers.py`: expone `invoice_status`.
- `billing/models.py` + `billing/migrations/0023`: FK `InvoiceItem.dispensed_from_prescription_item`.
- `billing/services.py`: helper `_items_settling_stock`; `_confirm_locked_invoice` y `cancel_invoice`
  generalizan el predicado (ruta única); `dispense_prescription_into_invoice` (reemplaza la versión
  `_as_direct_sale`).
- `billing/views.py`: view `dispense_prescription` (agrega a la consulta, acepta `prescription_item`,
  devuelve 200); flags de contexto en `InvoiceDetailView`; `InvoiceListCreateView` con
  `.order_by('-created_at')` explícito.
- `billing/serializers.py`: `prescription_suggestions` (presentaciones elegibles + `prescription_item_id`),
  `prescription_public_id`, `InvoiceItemSerializer.dispensed`.
- `billing/urls.py`: ruta `billing/prescriptions/<pk>/dispense/`.
- `billing/tests/test_prescription_dispense.py`: cubre dispensar→confirmar→cancelar + gate rx.
- Frontend: `ConsultationStepperV2` (header finaliza vía `handleSave`, `closed` derivado del status),
  `billing.jsx` (`PrescriptionDispensePanel` agrega a la misma factura y refresca el detalle; badge
  "para llevar"; `allowChange` solo en venta directa real), `api/billing.js` (`dispensePrescription`).

## Deploy

- `python manage.py migrate` (billing 0023).
- No hay nuevos `PERMISSION_CODES` (`billing.rx_dispense` ya existe desde p26) → no requiere
  `seed_permissions`.
