# ADR p37: Tope clínico de dispensación (dispensado ≤ recetado)

**Fecha**: 2026-06-11
**Estado**: Aceptado — implementado (commits `42836f3` + `93c4fd0`)
**Documentos relacionados**:
- ADR p30 (dispensación de receta interna) — esta decisión lo complementa
- ADR p31 (stock a nivel Product en unidades base) — define la unidad de comparación
- `docs/modules/billing.md` §"Sugerencias de receta y dispensación"
- `backend/apps/billing/services.py::_enforce_prescribed_quantity_cap`
- `backend/apps/billing/tests/test_prescription_dispense.py::PrescriptionDispenseCapTests`

## Contexto

ADR p30 introdujo la dispensación de receta interna: recepción agrega a la MISMA
factura de consulta los medicamentos que el cliente decide llevar. El diseño cubría
"llevar menos de lo recetado" (no incluir la línea = no-op), pero **no limitaba el
máximo**: se podía dispensar Amoxicilina ×50 con una receta de ×1, en una llamada o
acumulando llamadas mientras la factura siguiera en `draft`. Esto rompe la intención
médica y deja a la receta como amparo legal de una venta que no respalda.

Auditoría 2026-06-11 encontró además dos rutas laterales:

1. `PATCH /invoices/<id>/items/<pk>/` permitía editar la cantidad de una línea
   dispensada sin pasar por ningún tope (dispensar 1 → subir a 50).
2. `POST /invoices/<id>/items/` permitía crear ítems de presentación en una factura
   `consultation`. Esos ítems no tienen FK de dispensación, y `_items_settling_stock`
   (discriminador único de stock, ADR p30) los ignora al confirmar → **se cobraban
   sin descontar inventario** (stock fantasma).

### Semántica de unidades (decisión previa necesaria)

`PrescriptionItem.quantity` no tiene campo de unidad. El VET receta **por producto**
y el formulario muestra la `base_unit` del producto (ADR p31) → la cantidad recetada
está en **unidades base**. Cada línea dispensada elige una presentación comercial
(`conversion_factor` = unidades base por paquete). Comparar piezas-de-presentación
crudas sería incorrecto (1 "Caja ×10" contaría como 1, no como 10).

## Decisión

**Invariante**: por ítem de receta, lo dispensado acumulado en la factura de consulta
más lo solicitado no puede exceder `PrescriptionItem.quantity`, comparado en unidades
base:

```
Σ(InvoiceItem.quantity × presentation.conversion_factor)  ≤  PrescriptionItem.quantity
   (líneas activas con dispensed_from_prescription_item)
```

El cliente puede llevar menos de lo recetado; **nunca más**.

### Reglas

1. **Validación autoritativa en backend** (`_enforce_prescribed_quantity_cap`,
   `billing/services.py`), bajo el lock de la Invoice ya adquirido por el caller —
   sin carrera entre dispensaciones concurrentes. El frontend solo espeja (UX).
2. **Cubre las tres rutas de mutación**:
   - `dispense/`: lo solicitado se **suma** al acumulado. Agrega entre presentaciones
     del mismo ítem de receta dentro de una misma llamada y entre llamadas.
   - `PATCH items/<pk>/` de línea dispensada: la cantidad nueva **reemplaza** a la
     vieja → el acumulado excluye al propio ítem (`exclude_item_id`). Wrapper público
     `enforce_dispensed_item_quantity_cap(invoice, item, new_quantity)`.
   - `POST items/` en factura `consultation`: ítems de presentación **rechazados**
     (400). Los productos solo entran por sus rutas únicas — insumos
     (`MedicalRecordProduct`, ya descontaron al consumirse) o dispensación. Servicios
     sí se permiten manualmente.
3. **Borrar una línea dispensada libera el cupo** (hard delete del draft; el
   acumulado solo cuenta líneas activas de ESA factura).
4. **Error accionable**: 400 con amparado / ya dispensado / restante en el mensaje.
5. **Exposición para UX**: `prescription_suggestions` agrega `prescribed_quantity`,
   `dispensed_quantity`, `remaining_quantity` (unidades base, strings), `base_unit`
   (display) y `conversion_factor` por presentación. El panel de Cobros muestra
   "Recetado X · restante Y" y capea el input a `floor(remaining / conversion_factor)`
   por formato; filas agotadas quedan deshabilitadas.
6. **Fallback legacy**: una línea sin `prescription_item` se resuelve por producto
   (`rx_item_by_product`, primer ítem). Si la receta tuviera el mismo producto en dos
   ítems, todo se carga al primero — dirección conservadora (rechaza antes, nunca
   permite de más). El frontend siempre envía `prescription_item` explícito.

## Consecuencias

**Positivas:**
- La intención médica limita la venta: la receta deja de ser amparo de cantidades
  arbitrarias de productos `requires_prescription`.
- Muere el stock fantasma: en facturas de consulta ya no pueden existir ítems de
  presentación que se cobren sin liquidar inventario.
- El restante es visible para recepción (menos 400 por prueba y error).

**Negativas / trade-offs:**
- Si el VET subestimó la cantidad, recepción no puede "completar" desde Cobros: se
  requiere corregir la receta (consulta `open`) o una venta directa con atestación
  externa (ADR p26). Es el comportamiento deseado, pero agrega un paso operativo.
- El cap usa el `conversion_factor` vigente al validar; si el formato se reconfigura
  después, las líneas históricas no se reinterpretan (consistente con el resto del
  sistema: precios/factores se copian punto-en-tiempo).

## Regla de implementación

Toda ruta nueva que cree o mute `InvoiceItem` con `dispensed_from_prescription_item`
debe invocar el cap bajo el lock de la Invoice. No crear una segunda función de
validación: extender `_enforce_prescribed_quantity_cap`.
