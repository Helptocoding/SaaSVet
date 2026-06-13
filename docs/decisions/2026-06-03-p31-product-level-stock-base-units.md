# ADR p31: Stock a nivel Product en unidades base (base_unit + conversion_factor)

**Fecha**: 2026-06-03  
**Estado**: Aceptado — implementado  
**Documentos relacionados**:
- ADR p32 (cost_behavior) — sprint paralelo
- `docs/modules/inventory.md` — contratos actualizados
- `backend/apps/inventory/migrations/0018_adr_p31_product_stock_and_presentation_format.py`
- `backend/apps/inventory/services.py::apply_stock_movement`

## Contexto

El sistema anterior tracked stock en `Presentation.stock` (unidades de presentación). Esto generaba:

1. **Ambigüedad de unidad**: "50 de stock" podía significar 50 piezas o 50 cajas de 100 piezas, dependiendo de la presentación.
2. **Imposibilidad de comparar presentaciones**: no había una unidad común para sumar stock de "Caja 100" + "Pieza suelta" del mismo producto.
3. **Stock bajo incorrecto**: `is_low_stock` comparaba presentation.stock contra presentation.min_stock en unidades de presentación. Un producto con varias presentaciones podía disparar alertas incoherentes.
4. **Consultas clínicas**: los insumos se consumen en unidades mínimas (1 jeringa), pero se compran en cajas. Sin una unidad base, no había forma de calcular correctamente cuántas unidades clínicas quedan.

## Decisión

Mover el inventario autoritativo a `Product.stock_quantity` en **unidades base**, con `Presentation.conversion_factor` indicando cuántas unidades base contiene una unidad de esa presentación.

### Nuevos campos

**Product:**
- `base_unit` — unidad mínima: `piece`, `ml`, `kg`, etc.
- `stock_quantity` — existencias en unidades base (Decimal, 14.4)
- `min_stock` — umbral de alerta en unidades base

**Presentation:**
- `conversion_factor` — cuántas `base_unit` contiene 1 unidad de esta presentación (ej: caja de 100 = `conversion_factor=100`)
- `purchase_price` — costo de compra por unidad de presentación
- `barcode` — código de barras (unique parcial por org, NULL permitido)

**StockMovement:**
- `product` — FK a Product (nullable para retrocompat)
- `quantity_unit` — `'base'` para nuevos movimientos, `'presentation'` para legacy

### `apply_stock_movement()` reescrito

- Acepta `quantity` ya en **unidades base** (responsabilidad del caller)
- Adquiere lock interno sobre `Product` via `select_for_update()`
- Actualiza `Product.stock_quantity` con `F()` expressions
- Dual-write a `Presentation.stock` para backward compat de código legacy
- Normaliza cantidad a 4 decimales (ROUND_HALF_UP) para evitar drift por multiplicación decimal

### Conversión en callers

```python
# MedicalRecordProduct.save() — consume en unidades base
cf = self.presentation.conversion_factor or 1
apply_stock_movement(quantity=self.quantity * cf, ...)

# adjust_stock view — user entra en unidades de presentación
quantity_base = quantity * (locked_pres.conversion_factor or 1)
apply_stock_movement(quantity=quantity_base, ...)
```

### Inicialización de datos (migración)

`populate_product_stock`: por cada producto, suma `Σ(p.stock * p.conversion_factor)` de todas sus presentaciones y lo escribe en `Product.stock_quantity`. Crea un `StockMovement(type='adjustment', quantity_unit='base')` como baseline para el comando de auditoría.

### `audit_stock_integrity` reescrito

- Fuente de verdad: `Product.stock_quantity` (no `Presentation.stock`)
- Baseline: último `StockMovement(quantity_unit='base', type='adjustment')` por producto
- Ignora movimientos legacy (`quantity_unit='presentation'`)

## Consecuencias

**Positivas:**
- Stock siempre en una unidad comparable entre presentaciones
- `is_low_stock` correcto: `product.stock_quantity <= product.min_stock`
- Consulta clínica puede usar fracción de unidad de presentación sin error
- El audit command detecta drift directamente en `stock_quantity`

**Negativas / deuda:**
- `Presentation.stock` es ahora un display de backward compat (derivado de `stock_quantity / conversion_factor`). Si diverge del ledger de movimientos, el audit lo detecta pero no corrije automáticamente.
- Lock order: `apply_stock_movement` adquiere lock sobre `Product`. El caller ya no necesita lockear `Presentation` antes. El orden canónico actualizado es: `CashSession → MedicalRecord → Invoice → Product → InvoiceItem`.

## Regla de implementación

Todo nuevo código que lea stock usa `product.stock_quantity`, no `presentation.stock`.  
`presentation.stock` solo se lee para backward compat en código ya existente que no fue migrado.
