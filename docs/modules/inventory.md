# Modulo: Inventario

> Orden 4 en curso: el orden de stock y valor en la tabla utiliza los mismos helpers que las columnas. Estado y límites de verificación en [expediente](../remediaciones/orden-4/README.md).

> Avance local: el alta manual positiva usa `apply_stock_movement` dentro de la transacción, y los serializers normalizan el alias de presentación. Migraciones y demás caminos siguen sujetos a los límites del expediente.

> Alta de presentación adicional: el stock positivo también entra mediante el writer en unidades base; para productos con lotes debe usarse recepción identificada. El PATCH de presentación rechaza asignaciones directas de stock.

> Recepción de lotes: la app registra una **intención durable en el servidor** antes de tocar stock y la ejecuta en otra petición, así que se puede recuperar o conciliar sin conservar nada en el navegador. Ver [Operaciones de recepción](#operaciones-de-recepción-intención-durable) y el [expediente](../remediaciones/orden-4/README.md).

> **Ver también:** [`docs/system-operational-flow.md`](../system-operational-flow.md) — mapa operacional cross-módulo.

## Objetivo

**Orden 2 (28-10-2026):** `StockMovement.product` y `.presentation` son PROTECT: ni borrar Product ni borrar Presentation puede eliminar filas del ledger. `MedicalRecordProduct.medical_record` es PROTECT; borrar expediente no devuelve stock ni borra consumo. El alias de archivo de Pet/Owner no crea movimientos.

El modulo gestiona el catalogo de productos, sus presentaciones (formatos comerciales), el stock en unidades base y los movimientos de inventario.

## Arquitectura de stock (ADR p31)

Stock se trackea en **unidades base** a nivel `Product`, no a nivel `Presentation`.

```
Product.stock_quantity  ← fuente autoritativa (en base_unit)
Product.base_unit       ← "piece", "ml", "kg", etc.
Product.min_stock       ← umbral de alerta (en base_unit)

Presentation.conversion_factor  ← cuántas base_unit contiene 1 unidad de esta presentación
Presentation.stock              ← copia display (backward compat); no autoritativa
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
- `manufacturer` — fabricante del **producto comercial** (Zoetis/MSD); no el principio activo (spec lotes 2026-07-10)
- `tracks_lots` — opt-in de trazabilidad por lote. `False` (default) = flujo idéntico al histórico
- `default_cost_behavior` — `charge`|`included` (default `charge`). Modo de cobro por defecto al
  auto-agregar el producto en consulta (p.ej. vacuna aplicada, A2). Editable luego en Cargos.
- `is_active` — soft delete
- `extra_data` — dato histórico del sistema anterior (importador; ADR p43/p61):
  `[{label, value, source_column, imported_at}]`. Read-only display; ninguna
  regla de negocio lo lee. No es EAV.

### Consulta de catálogo por el agente de WhatsApp

`check_product_availability` expone únicamente productos activos. Una consulta
que es una categoría aislada (por ejemplo, `alimentos`) se resuelve contra la
categoría cerrada; las demás se comparan, sin distinguir acentos ni plural,
contra nombre, fabricante y descripción. El resultado se limita a cinco y se
ordena por relevancia y después por nombre de forma estable.

Para productos con existencia positiva la proyección incluye disponibilidad,
precio, stock y si requiere receta. Cuando está agotado, solo indica ese estado;
costos de compra nunca se publican.

### Presentation

Cada producto puede tener una o más presentaciones (formatos comerciales de venta/compra).

- `product` — FK a Product (CASCADE)
- `name` — etiqueta de la presentación (ej: "Pieza", "Caja de 3")
- `base_unit` — misma unidad que `Product.base_unit` (se sincroniza al crear/editar)
- `conversion_factor` — cuántas unidades base contiene esta presentación (default 1)
- `sale_price` — precio de venta (> 0)
- `purchase_price` — costo de compra (opcional)
- `barcode` — código de barras (único parcial por organización, `blank=True`, `default=''` — columna NOT NULL, vacío = sin barcode)
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
- `lot` — FK nullable a `StockLot` (spec lotes 2026-07-10). Null en movimientos legacy y de productos sin `tracks_lots`
- `lot_number` — snapshot denormalizado del lote (el ledger conserva la identidad aunque el `StockLot` se borre)
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
  - `'charge'`: descuenta stock y registra un cargo clínico que se
    materializa como CheckoutItem al cierre
  - `'included'`: descuenta stock pero no genera cargo comercial
  - **inmutable** una vez guardado
  - Default en el wizard de consulta: `'charge'` (el usuario puede cambiarlo a `'included'` si es insumo clínico)
- `lot` — FK nullable a `StockLot` (B2a). **Obligatorio** si el producto tiene `tracks_lots`
  (validado en serializer); null en productos sin lote. Inmutable por línea (como `cost_behavior`).
  `save()/delete()` rutean por `consume_product`/`restock_product` sobre este lote → el
  consumo descuenta el lote elegido y el reverso vuelve al **mismo lote** (P4).
  Serializer expone `tracks_lots`, `lot_number`, `lot_expiry`, `lot_effective_status` (read).

### StockLot (trazabilidad por lote — spec 2026-07-10)

> Diseño congelado: [`docs/analisis-inventario-trazabilidad-lotes-2026-07-10.md`](../analisis-inventario-trazabilidad-lotes-2026-07-10.md).
> Plan: [`docs/plan-implementacion-inventario-lotes-2026-07-10.md`](../plan-implementacion-inventario-lotes-2026-07-10.md).
> **Implementado**: B0 (modelo + servicio de consumo), B1 (recepción multi-lote), **B2a**
> (consumo en consulta vía `MedicalRecordProduct`), **B2b** (billing/POS: `InvoiceItem.lot`;
> confirm/cancel/refund/dispensación ruteados por `consume_product`/`restock_product`; POS con
> picker FEFO, dispensación FEFO-auto), **B2c** (caducidad `lot_alerts`; `discard_lot` merma;
> `set_lot_status` cuarentena/retiro; frontend `LotManagerModal` + banner). **Trazabilidad por
> lote completa (B0–B2c).** Sigue: A2 (Vacuna consume StockLot).

Lote/batch físico de un `Product` con `tracks_lots=True`. Stock en **dos niveles**:
`Product.stock_quantity` = agregado autoritativo; `StockLot.quantity_on_hand` = saldo por lote
(base-units). Invariante: `Σ lotes == Product.stock_quantity`.

- `product` — FK PROTECT
- `lot_number` — número de lote
- `expiry_date` — caducidad (nullable)
- `received_at` — fecha de recepción (nullable)
- `quantity_on_hand` — saldo del lote en base-units (CHECK `>= 0`)
- `supplier_name` — snapshot del proveedor (la FK `supplier` se agregará al lado, futuro)
- `status` — **almacenado**: `active | quarantined | recalled`
- `effective_status` (property, derivado) — precedencia **BINDING**:
  `RECALLED → QUARANTINED → EXPIRED → CONSUMED → ACTIVE`. `EXPIRED` (fecha) y `CONSUMED`
  (saldo 0) se derivan → sin cron, sin drift.
- `PublicIdMixin` (expuesto en API en B1-B2). Unicidad `(product, lot_number, expiry_date)`.

## `consume_product()` — única entrada de consumo de inventario

Ubicación: `apps/inventory/services.py`. **Toda** baja de stock por consumo pasa por aquí
(MedicalRecordProduct, Billing, y futuros). Ningún caller llama `resolve_consumption_lots`
directamente → la política de lotes vive en un solo lugar (spec §10).

```python
consume_product(presentation, quantity_base, organization,
                reason='', created_by=None, medical_record=None, invoice=None,
                lot=None, force=False)
```

- Producto sin `tracks_lots` → `apply_stock_movement('out', lot=None)` (idéntico al histórico).
- Con `tracks_lots`: `lot` dado = override manual (P3; bloqueado si no es consumible salvo
  `force=True`); `lot=None` = **FEFO** vía `resolve_consumption_lots` (P1), reparte entre lotes.
- `resolve_consumption_lots(product, qty)` → asignación FEFO entre lotes elegibles
  (`effective_status=ACTIVE`), o `ValidationError` si no hay saldo (P2).
- `restock_product(...)` — inversa (movimiento `in`); con `lot` devuelve al **lote original** (P4).
- Debe correr en `transaction.atomic()` (assert).

### Recepción multi-lote — `receive_stock` (B1)

`receive_stock(presentation, lots, organization, supplier_name='', received_at=None, created_by=None)`.
Una recepción = una presentación + **N líneas de lote** (una compra suele traer varios lotes).
Cada línea `find-or-create` el `StockLot` `(product, lot_number, expiry_date)` y aplica un
movimiento `in` lot-scoped. `quantity` de la línea en unidades de **presentación** (convierte con
`conversion_factor`). Solo `tracks_lots` (los demás usan el ajuste histórico). Endpoint
`POST /presentations/<id>/receive/`; frontend en `StockEntryModal` (sección de lotes condicional).

### Operaciones de recepción: intención durable

`StockReceptionReceipt` es la identidad de una recepción, y existe **antes** de que esta toque stock:

| Estado | Significado | Stock |
|---|---|---|
| `pending` | Intención confirmada con la captura guardada. Puede haber una ejecución en curso | No aplicado |
| `confirmed` | Terminal. Publicado en la misma transacción que el stock y los movimientos | Aplicado una vez |
| `discarded` | Terminal. Cerrada por una persona, con motivo, autor y fecha | Nunca aplicado |

**Por qué son dos peticiones.** Si intención y efecto viajaran juntos, una petición aún en vuelo sería
invisible: la lista vacía no probaría nada y otra entrada podría sumarse a una que todavía va a ejecutarse.
Separadas, la ejecución solo sale tras conocer la respuesta de la intención. Una intención perdida o tardía
deja, como mucho, un `pending` inerte; una ejecución en vuelo ya es visible como `pending`, y completar o
descartar se serializan con ella por el lock de la fila.

- **Sin identidad local.** `GET /receptions/` lista lo que el usuario puede ver sin pedir ningún identificador.
- **Una entrada nueva exige resolver la anterior.** `UniqueConstraint` parcial: como máximo un `pending` por
  organización, actor y producto; otro → `409 reception_unresolved`. **No deduplica por contenido**: dos
  recepciones idénticas son válidas si la primera ya está resuelta.
- **Lo que aplicó sale del libro.** `StockMovement.reception_operation` se escribe en la misma transacción;
  `applied_lines` se lee de ahí, y `current_balance` se publica aparte porque acumula otras entradas y salidas.
- **Actor.** Solo quien capturó puede ejecutar. Sin facultad de supervisión, una operación ajena da 404.
  `staff.reset_password` (administración del equipo, ya existente) añade `scope=organization` en lectura y
  permite cerrar una operación ajena, nunca ejecutarla: así una persona que ya no está no deja nada sin salida.
- **Factor.** Se congela al preparar: si cambia, `409 reception_factor_changed` en vez de aplicar otra cantidad.

**Límites.** Las filas anteriores a `inventory.0031` no conservan captura ni cantidades: quedan `confirmed` con
`evidence_level=legacy_receipt` y solo se publica la identidad de sus lotes, porque los saldos de ese recibo no
son la cantidad recibida. Las entradas sin operación (llamadas directas, históricas, `adjust` de productos sin
lotes con motivo «Entrada de mercancía») aparecen en `/receptions/unattributed/`: son hechos del libro que nada
permite atribuir a un intento, y las concilia una persona. `POST /receive/` con clave conserva su contrato en una
sola petición, sin la visibilidad en vuelo; la app ya no lo usa para recepciones nuevas.

## `apply_stock_movement()` — contrato

**Único escritor autorizado de `Product.stock_quantity`.** Ubicación: `apps/inventory/services.py`.
**Single-lot**: mueve stock de un lote (o de ninguno con `lot=None`). El reparto multi-lote y
FEFO viven en `consume_product`, no aquí. Con `lot`: además de `Product.stock_quantity`, ajusta
`StockLot.quantity_on_hand` bajo el mismo lock de Product (orden de locks intacto), valida saldo
del lote en `out`, y denormaliza `lot_number` en el movimiento.

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

# billing.post_checkout
qty_base = item.quantity * item.conversion_factor_snapshot
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

### Orden de locks

Los servicios autoritativos de inventario y Billing deciden y adquieren sus
locks. Views y serializers no deben componer un orden parcial propio.

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
- Recorre el libro de cada producto: sin `adjustment` de producto parte de 0, un `adjustment` de producto fija el saldo y uno de lote mueve el agregado por su diferencia con ese lote
- Saldo sin movimientos que lo expliquen = drift. Todo stock entra por `apply_stock_movement`, incluido el inicial
- `no_baseline`: solo productos con movimientos legacy (sin producto o en unidades de presentación) y sin `adjustment` posterior; informativo, no drift
- Exit: 0 sin drift, 1 drift detectado, 2 error

## Barcode lookup (POS scanner)

`GET /api/inventory/presentations/barcode/?barcode=<codigo>`

Tenant-scoped. Retorna `PresentationSerializer` completo con `product.*`. 404 si no existe.
Diseñado para POS scanner — cuando el cajero escanea, se selecciona la presentación directamente.

## Importador de inventario (ADR p61)

`entity_type=inventory` del módulo imports: migra el catálogo desde Excel/CSV
creando Product + su Presentation única; el stock inicial entra **siempre** por
`apply_stock_movement(..., 'in', reason='Stock inicial (importación)')`
(ledger auditable, `quantity_unit='base'`). Dedup por `internal_code`; nombre
sin código ⇒ conflicto uncertain reportado (nunca dedup silenciosa). Sin código
⇒ auto `PROD-{org.id}-{pk:04d}`. Detalle: `modules/imports.md` § Importador de
inventario.

## Frontend: Wizard de alta de producto (ADR p33)

Al crear un producto ("Nuevo producto"), se muestra un **selector de modo** antes del formulario:

- **Producto normal** (`wizardMode = "simple"`): una sola presentación de venta. Shampoo, collar, alimento.
- **Varias formas de venta** (`wizardMode = "multi"`): el producto se divide en unidades (`divides = true`). Ej: caja de jeringas que también se vende por pieza.

El modo multi tiene auto-sync de `salesPres[1]` (nombre y conversion_factor desde `countUnit`/`dividesCount`) mientras el usuario no los edite manualmente (`presSecondAutoRef`). Ver `frontend/src/pages/inventory.jsx`, `MultiPresentationAnimation.jsx` (5 escenas Framer Motion, gate `localStorage`), `ProductCreationTour.jsx` (6 pasos con spotlight).

### Existencia inicial con `tracks_lots` — primer lote inline

El bloque de existencia inicial del wizard es **condicional al `tracks_lots`** del producto:

- **Sin lotes** (comportamiento previo): campo **Cantidad** + unidad → el producto se crea con
  ese stock inline (`presentation_input.stock`). 1 paso.
- **Con lotes**: el campo Cantidad se reemplaza por un editor de **Primer lote (opcional)**
  (proveedor + N filas lote/caducidad/cantidad, "+ Agregar lote") — reusa la UX de recepción de
  `StockEntryModal`. El producto se crea con `stock: 0` y, si hay lotes válidos, se registran
  con `receiveStock` sobre la **presentación base** (cf=1 → cantidad en unidad base) en el mismo
  guardado. También 1 paso; el usuario puede dejarlo vacío y registrar el stock luego en Entrada
  de stock. Los selectores estructurales (unidad base / "cada X contiene") se conservan.

**Motivo (correctitud, no solo UX):** el bloque de cantidad no captura lote/caducidad; si un
producto `tracks_lots` se creaba con stock inline quedaba stock base **sin lote**
(`Product.stock_quantity = N` pero `Σ lotes = 0`) y el primer consumo fallaba en FEFO
(`resolve_consumption_lots` → "No hay lotes elegibles"). Capturar el primer lote en el alta
cierra ese hueco manteniendo paridad (normal=1 paso, lote=1 paso).

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

- **Producto con `tracks_lots` (B1):** el modal muestra una sección de **lotes** (proveedor
  opcional + N filas lote/caducidad/cantidad, "+ Agregar lote") en vez del stepper simple, y
  confirma vía `receiveStock`, que prepara y ejecuta una operación con identidad propia. Reintentar la misma
  captura conserva la identidad; sin respuesta definitiva lleva al panel Recepciones. Producto sin lotes: el
  modal se comporta igual que antes (stepper + `adjustPresentationStock`), sin identidad de operación.

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
| `GET`    | `/api/inventory/products/<id>/lots/`                | Lotes del producto (orden FEFO; `?with_stock=true`) |
| `GET`    | `/api/inventory/lots/alerts/`                       | Caducidad: `expiring_soon` + `expired_with_stock` (`?days=30`, B2c) |
| `POST`   | `/api/inventory/lots/<id>/discard/`                 | Merma/write-off del lote (`{quantity?, reason?}`, B2c) |
| `POST`   | `/api/inventory/lots/<id>/status/`                  | Estado del lote: `active\|quarantined\|recalled` (B2c) |
| `GET`    | `/api/inventory/presentations/`                     | Listar presentaciones con filtros         |
| `GET`    | `/api/inventory/presentations/barcode/`             | Lookup por código de barras (POS)         |
| `PATCH`  | `/api/inventory/presentations/<id>/`                | Editar presentación                       |
| `DELETE` | `/api/inventory/presentations/<id>/`                | Eliminar (con checks)                     |
| `POST`   | `/api/inventory/presentations/<id>/adjust/`         | Ajustar stock de presentación específica  |
| `POST`   | `/api/inventory/presentations/<id>/receptions/`     | Registrar intención (`X-Idempotency-Key` UUID obligatorio). `201` nueva, `200` repetición; `409 reception_unresolved` · `reception_operation_conflict` |
| `GET`    | `/api/inventory/receptions/`                        | Descubrir operaciones (`?status=&product=&scope=own\|organization&cursor=&page_size=`, máx. 100). Requiere `inventory.update` |
| `GET`    | `/api/inventory/receptions/unattributed/`           | Entradas del libro sin identidad de operación (`?scope=&cursor=`) |
| `GET`    | `/api/inventory/receptions/<operation_id>/`         | Evidencia: lo capturado, lo aplicado, saldo actual aparte y entradas desde la intención |
| `POST`   | `/api/inventory/receptions/<operation_id>/complete/` | Ejecutar la captura guardada. Repetir devuelve lo confirmado sin movimientos; `409 reception_discarded` · `reception_factor_changed` · `reception_payload_unavailable` |
| `POST`   | `/api/inventory/receptions/<operation_id>/discard/` | Cerrar sin aplicar (`{reason: not_received\|already_registered\|entered_in_error, note?}`); `409 reception_already_confirmed` |
| `POST`   | `/api/inventory/presentations/<id>/receive/`        | Recepción multi-lote (B1, solo `tracks_lots`) |
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
