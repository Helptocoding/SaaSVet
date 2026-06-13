# Modulo: Inventario

> **Ver también:** [`docs/system-operational-flow.md`](../system-operational-flow.md) — mapa operacional cross-módulo.

## Objetivo

El modulo gestiona el catalogo de productos, sus presentaciones (formatos comerciales), el stock en unidades base y los movimientos de inventario.

## Arquitectura de stock (ADR p31)

Stock se trackea en **unidades base** a nivel `Product`, no a nivel `Presentation`.

```
Product.stock_quantity  ← fuente autoritativa (en base_unit)
Product.base_unit       ← "piece", "ml", "kg", etc.
Product.min_stock       ← umbral de alerta (en base_unit)

Presentation.conversion_factor  ← cuántas base_unit contiene 1 unidad de esta presentación
Presentation.stock              ← copia display (backward compat); no autoritative
```

**Ejemplo:** Jeringa 3ml
- `base_unit = "piece"`, `stock_quantity = 30`
- Presentación "Pieza": `conversion_factor = 1`, `sale_price = $15`
- Presentación "Caja de 3": `conversion_factor = 3`, `sale_price = $40`
- Vender "Caja de 3" descuenta `3` del `stock_quantity`

## Modelos

### Product

- `name` — nombre del producto
- `internal_code` — codigo interno unico por organizacion (auto-generado si no se envia)
- `description` — descripcion opcional
- `category` — choices: `medication`, `food`, `accessory`, `other`
- `requires_prescription` — si `True`, exige receta activa en consulta / atestación en venta directa (ADR p26)
- `base_unit` — unidad mínima de inventario
- `stock_quantity` — existencias en `base_unit` (Decimal 14.4) — **fuente autoritativa** (ADR p31)
- `min_stock` — umbral de alerta en `base_unit`
- `is_active` — soft delete

### Presentation

Cada producto puede tener una o más presentaciones (formatos comerciales de venta/compra).

- `product` — FK a Product (CASCADE)
- `name` — etiqueta de la presentación (ej: "Pieza", "Caja de 3")
- `base_unit` — misma unidad que `Product.base_unit` (se sincroniza al crear/editar)
- `conversion_factor` — cuántas unidades base contiene esta presentación (default 1)
- `sale_price` — precio de venta (> 0)
- `purchase_price` — costo de compra (opcional)
- `barcode` — código de barras (único parcial por organización, NULL permitido)
- `stock` — copia display para backward compat (no escribir directamente)
- `min_stock` — legacy (no usar para alerta; usar `Product.min_stock`)
- `quantity` — alias de `conversion_factor` (mantenido para compat)

**Unique constraint de barcode:**
```sql
CREATE UNIQUE INDEX presentation_barcode_org_uniq
ON inventory_presentation (organization_id, barcode)
WHERE barcode IS NOT NULL AND barcode <> '';
```
Permite múltiples presentaciones sin barcode; barcode de otra org no produce conflicto.

### StockMovement

Ledger append-only de cada cambio de stock.

- `product` — FK a Product (nuevo, nullable para legacy)
- `presentation` — FK a Presentation
- `movement_type` — `in`, `out`, `adjustment`
- `quantity` — en unidades base (ADR p31: `quantity_unit='base'`; legacy: `quantity_unit='presentation'`)
- `quantity_unit` — `'base'` o `'presentation'`
- FK opcionales a `MedicalRecord`, `Invoice`, `created_by`

El listado `GET /api/inventory/movements/` está **paginado por cursor** (ADR p42):
ledger append-only de alto volumen (50k+), donde el offset profundo degrada. Orden
estable `(-created_at, -id)`, servido por el índice `(organization, -created_at, -id)`.
Respuesta `{next, previous, results}` (cursor **no** expone `count`). El frontend
normaliza con `utils/toList.js`.

### MedicalRecordProduct (ADR p32)

Productos consumidos en consulta. Ver también `docs/modules/medical_records.md`.

- `presentation` — FK a Presentation
- `quantity` — cantidad consumida (en unidades de presentación)
- `cost_behavior` — `'charge'` | `'included'`
  - `'charge'`: descuenta stock Y genera InvoiceItem
  - `'included'`: descuenta stock pero NO genera InvoiceItem (insumo clínico)
  - **inmutable** una vez guardado
  - Default en el wizard de consulta: `'included'` (evita cobrar insumos accidentalmente)

## `apply_stock_movement()` — contrato

**Único escritor autorizado de `Product.stock_quantity`.** Ubicación: `apps/inventory/services.py`.

```python
apply_stock_movement(
    presentation,    # Presentation instance
    quantity,        # EN UNIDADES BASE (responsabilidad del caller)
    movement_type,   # 'in' | 'out' | 'adjustment'
    organization,
    reason='',
    created_by=None,
    medical_record=None,
    invoice=None,
)
```

- Adquiere `select_for_update()` sobre `Product` internamente
- Actualiza `Product.stock_quantity` con `F()` expressions (no race condition)
- Dual-write a `Presentation.stock` para backward compat
- Normaliza quantity a 4 decimales (ROUND_HALF_UP) antes de operar

**Callers que convierten a base_unit antes de llamar:**

```python
# MedicalRecordProduct.save()
cf = self.presentation.conversion_factor or 1
apply_stock_movement(quantity=self.quantity * cf, ...)

# adjust_stock view / adjust_presentation_stock
quantity_base = quantity * (locked_pres.conversion_factor or 1)
apply_stock_movement(quantity=quantity_base, ...)

# billing._confirm_locked_invoice / cancel_invoice
qty_base = item.quantity * (item.presentation.conversion_factor or 1)
```

## Validaciones de backend

### Nombre de producto

Regex: `^[A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s\.\-\(\)\/\%\+]+$`

### Precio y stock

- `sale_price > 0`
- `stock >= 0`
- `min_stock >= 0`

### Cost behavior

`CheckConstraint`: `cost_behavior IN ('charge', 'included')`

## Concurrencia (ADR p12/p13)

### Orden global de locks (actualizado ADR p31)

```
CashSession → MedicalRecord → Invoice → Product → InvoiceItem
```

`apply_stock_movement` adquiere lock sobre `Product` internamente. El caller **no** necesita lockear `Presentation` antes (cambio vs. pre-ADR p31, donde el caller debía lockear Presentation).

### MedicalRecordProduct.save() / .delete()

- Requieren `transaction.atomic()` externo (assert al inicio)
- Emiten `WARNING` si se invocan sin `locked_presentation` (fallback a lock interno)
- Ver deuda: cascada de MR no invoca el `.delete()` custom

## Alertas de stock bajo

`GET /api/inventory/products/low-stock/` — productos donde `stock_quantity <= min_stock`.

El frontend ordena: primero agotados (`stock_quantity = 0`), luego bajo mínimo.

## Reconciliación de stock

`python manage.py audit_stock_integrity [--org N] [--verbose] [--json]`

- Fuente de verdad: `Product.stock_quantity`
- Baseline: último `StockMovement(quantity_unit='base', movement_type='adjustment')` por producto
- Movimientos legacy (`quantity_unit='presentation'`) ignorados
- Exit: 0 sin drift, 1 drift detectado, 2 error

## Barcode lookup (POS scanner)

`GET /api/inventory/presentations/barcode/?barcode=<codigo>`

Tenant-scoped. Retorna `PresentationSerializer` completo con `product.*`. 404 si no existe.
Diseñado para POS scanner — cuando el cajero escanea, se selecciona la presentación directamente.

## Frontend: Entrada rápida de stock (recepción)

`frontend/src/components/StockEntryModal.jsx` — botón "+ Entrada de stock" junto a "Nuevo Producto".

Capa UX **solo de entrada** sobre el ajuste existente. NO crea productos ni edita datos del producto.

- Lookup **client-side** contra el array `products` ya cargado (sin red por escaneo):
  1. `presentation.barcode` exacto → formato bloqueado.
  2. `product.internal_code` exacto (case-insensitive).
  3. `name` contiene → si hay varios, lista para elegir.
- **Multi-presentación:** una sola presentación se autoselecciona; varias **obligan** selección (sin default a `presentations.first()`, evita entradas en formato incorrecto).
- Confirma vía `adjustPresentationStock(presentation.public_id, { movement_type: 'in', quantity, reason: 'Entrada de mercancía' })` → backend aplica `quantity × conversion_factor` del formato recibido.
- Preview muestra ambas unidades (base + equivalente de la presentación).
- Scanner UX: autofocus, Enter ejecuta lookup → Enter confirma → limpia y reenfoca para el siguiente. Modal queda abierto.
- `reason` fijo `"Entrada de mercancía"` para mantener movimientos filtrables.

No reemplaza el ajuste manual (`adjust_stock` / corrección, inventario físico) — ambos coexisten.

## Endpoints

| Metodo   | URL                                                 | Descripcion                               |
|----------|-----------------------------------------------------|-------------------------------------------|
| `GET`    | `/api/inventory/products/`                          | Listar productos (con `presentations[]`)  |
| `POST`   | `/api/inventory/products/`                          | Crear producto + primera presentación     |
| `GET`    | `/api/inventory/products/low-stock/`                | Productos con `stock_quantity <= min_stock` |
| `GET`    | `/api/inventory/products/<id>/`                     | Detalle de producto                       |
| `PATCH`  | `/api/inventory/products/<id>/`                     | Editar producto + primera presentación    |
| `DELETE` | `/api/inventory/products/<id>/`                     | Desactivar producto (soft delete)         |
| `POST`   | `/api/inventory/products/<id>/adjust/`              | Ajustar stock (primera presentación, compat) |
| `POST`   | `/api/inventory/products/<id>/presentations/`       | Agregar presentación adicional            |
| `GET`    | `/api/inventory/presentations/`                     | Listar presentaciones con filtros         |
| `GET`    | `/api/inventory/presentations/barcode/`             | Lookup por código de barras (POS)         |
| `PATCH`  | `/api/inventory/presentations/<id>/`                | Editar presentación                       |
| `DELETE` | `/api/inventory/presentations/<id>/`                | Eliminar (con checks)                     |
| `POST`   | `/api/inventory/presentations/<id>/adjust/`         | Ajustar stock de presentación específica  |
| `GET`    | `/api/inventory/movements/`                         | Historial de movimientos (paginado cursor, ADR p42) |
| `GET`    | `/api/inventory/units/`                             | Catálogo de unidades válidas              |

## `ProductSerializer` — notas

- `presentations` — array de todas las presentaciones (read-only)
- `presentation` — primera presentación (backward compat para frontend legacy)
- `presentation_input` — write-only para crear/editar primera presentación
- `stock_quantity` — read-only (se actualiza solo via `apply_stock_movement`)

**Al crear:** `presentation_input.stock` se interpreta en unidades de presentación. Backend calcula: `Product.stock_quantity = stock × conversion_factor`.

**Al editar:** cambiar `stock` via `presentation_input` está bloqueado (`raise ValidationError`). Usar endpoint de ajuste.

## Eliminación de una presentación

Solo posible si:
1. `stock == 0`
2. Sin `StockMovement` asociados
3. Sin `InvoiceItem` asociados
4. Sin `MedicalRecordProduct` asociados

Validación + delete dentro de `transaction.atomic()` + `select_for_update()`.

## Permisos RBAC

| Accion         | Codigo              |
|----------------|---------------------|
| Listar         | `inventory.list`    |
| Ver detalle    | `inventory.retrieve`|
| Crear          | `inventory.create`  |
| Editar         | `inventory.update`  |
| Ajustar stock  | `inventory.update`  |
