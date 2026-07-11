# Rediseño de Inventario — Trazabilidad por Lote (StockLot)

**Fecha**: 2026-07-10
**Estado**: 🧊 **CONGELADO** — especificación oficial del rediseño de inventario.
**Naturaleza**: análisis de arquitectura y dominio. **No** es implementación: no define
código, migraciones ni endpoints. Candidato a ADR formal al planear la implementación.
**Audiencia**: arquitectura, backend, producto, QA.

> **Ver también:** [`docs/modules/inventory.md`](modules/inventory.md) (contrato actual),
> [`docs/modules/medical_records.md`](modules/medical_records.md) (protocolos clínicos),
> ADR p31 (stock en base-units a nivel Product).

---

## 0. Contexto y problema

Los protocolos clínicos nuevos (primer consumidor: **Vacuna**) introducen un caso que el
modelo actual no cubre: una vacuna aplicada debería registrar **lote, caducidad y proveedor
del producto realmente utilizado**. Si una clínica compra dos lotes distintos de la misma
vacuna, el modelo actual no puede distinguir cuál se aplicó a cada paciente. Eso también
bloquea: retiros de producto por lote, trazabilidad clínica, control de caducidades,
consumo FEFO (First Expired First Out) y auditoría.

El rediseño **no rompe** la arquitectura de stock existente. Evoluciona aditivamente.

### Hallazgos del código actual (grounding)

- `Product.stock_quantity` = fuente autoritativa del stock, en **base-units** (ADR p31).
  `Presentation` es solo formato comercial (`conversion_factor`, `sale_price`);
  `Presentation.stock` es dual-write legacy.
- `apps/inventory/services.py::apply_stock_movement()` = **único escritor** de
  `Product.stock_quantity`. Lockea `Product` con `select_for_update()`, actualiza con
  `F()`, y crea el `StockMovement` append-only. **No existe concepto de lote.**
- `MedicalRecordProduct` consume vía `apply_stock_movement` (convierte a base-units con
  `conversion_factor`); `cost_behavior ∈ {charge, included}`; FK a Presentation con PROTECT.
- Billing liquida stock al confirmar vía `_items_settling_stock` (venta directa: todos los
  ítems con presentación; consulta: solo los `dispensed_from_prescription_item`).
- **Gap clínico crítico**: `VaccineRecord` es `pet + vaccine_name (texto libre) + fechas +
  notes`. **No tiene FK a Product, ni lote, ni caducidad, ni fabricante.** Aplicar una vacuna
  hoy **no** toca inventario y **no** traza el producto físico usado.

### Referencia de dominio (cómo lo resuelven los caducables)

ERPs farmacéuticos (SAP/Odoo), farmacia hospitalaria (Pyxis/Omnicell) y PIMS veterinarios
(ezyVet, Provet, Cornerstone) convergen: **el lote es un atributo del stock físico, no del
catálogo**. El producto es el concepto comercial; el lote/batch es una recepción concreta con
su propia caducidad y saldo. Los movimientos referencian el lote; el consumo elige lote (FEFO
por defecto, override permitido); los seriados (implantes) son lotes de cantidad 1. Se copia
el **modelo de dominio**, no la UI.

---

## 1. Modelo de dominio — ¿dónde vive el lote?

**Decisión: nueva entidad `StockLot`, subordinada a `Product`, opt-in por producto.**

Descartadas:
- *Lote como campo de `Product`*: un producto tiene N lotes simultáneos con caducidades
  distintas → un campo no lo representa.
- *Lote solo como campo de `StockMovement`* (sin entidad de saldo): reconstruir "cuánto queda
  del lote X" exigiría agregar el ledger append-only en cada consumo y bajo lock para FEFO →
  caro y frágil. El ledger es historia, no saldo consultable.

`StockLot` pertenece al **Product**, no a la Presentation: el stock ya es base-unit a nivel
Product (ADR p31); las presentaciones son reempaques del mismo bien base. Poner lote en
Presentation duplicaría el saldo por (lote × presentación) sin ganancia. **Una sola dimensión
de lote, en base-units.**

**Opt-in obligatorio: `Product.tracks_lots` (bool, default `false`).** Shampoo, collar,
alimento no cambian nada. Solo vacunas, inyectables, reactivos, implantes lo activan. Esto
mantiene retrocompatibilidad total y evita fricción en el 80% del catálogo.

> **Nota (observación final integrada):** el `manufacturer` **no** vive en el lote. El
> fabricante es identidad del producto (Rabia **Zoetis**) — no varía entre lotes; si variara,
> son dos productos distintos. Por eso: `Product.manufacturer`. El lote guarda solo lo que sí
> cambia: `lot_number`, `expiry_date`, `received_at`, saldo.
>
> **Precisión de dominio:** `Product.manufacturer` = **fabricante del producto comercial** (la
> empresa/marca que lo produce: Zoetis, MSD, Boehringer), **no** el origen del principio
> activo ni el laboratorio del ingrediente. Es el mismo eje que el `lot_number` y el retiro
> (`RECALLED`): quien fabrica y responde por ese producto comercial.

---

## 2. Stock — ¿dónde vive y cómo evitar inconsistencia?

**Dos niveles, un solo escritor:**
- `Product.stock_quantity` sigue siendo el **agregado autoritativo**. Invariante:
  `= Σ StockLot.quantity_on_hand` para productos con `tracks_lots=true`.
- `StockLot.quantity_on_hand` (base-units) es el saldo autoritativo **por lote**.

Consistencia **por construcción**: `apply_stock_movement()` sigue siendo el único escritor y
toca *ambos* niveles dentro de la misma sección ya serializada por el `select_for_update()`
sobre `Product`. El lote pertenece al producto lockeado → **cero riesgo nuevo de lock
ordering** (no se introduce un candado fuera del orden `CashSession → MR → Invoice → Product`).

- Producto sin lotes: no hay filas `StockLot`; `stock_quantity` opera **exactamente como hoy**.
- Validación de negativo: hoy compara `Product.stock_quantity`; con lotes debe comparar
  **también** el saldo del lote específico (no puedes sacar de un lote más de lo que tiene).
- Guardarraíl: extender `audit_stock_integrity` para verificar `Σ lotes == Product.stock_quantity`.
  CHECK `quantity_on_hand >= 0` en el lote.

---

## 3. Movimientos

`StockMovement` gana un FK **nullable** `lot` (retrocompatible: movimientos legacy y de
productos sin lote lo dejan `null`).

- **Compra/entrada**: encuentra-o-crea el `StockLot` por `(product, lot_number, expiry)`;
  movimiento `in` con lote → acredita lote + Product.
- **Consumo (consulta / confirmación de venta)**: `out` con lote; debita lote + Product. FEFO
  elige el lote (ver §4 y §Políticas operativas). Si un lote no alcanza, el consumo se
  **reparte** entre lotes → varios movimientos `out` (uno por lote). Estándar farmacéutico,
  encaja con el ledger append-only.
- **Ajuste**: hoy `adjustment` fija el agregado absoluto. Con lotes, el ajuste pasa a ser
  **por lote** (ver §6-bis Inventario físico).

---

## 4. Integración con protocolos clínicos (vacuna)

Primero cierra el gap: la vacuna debe poder ser un **Product de inventario**
(`tracks_lots=true`), no solo texto libre.

**Selección de lote: FEFO sugerido + override manual.** La política explícita está en
§Políticas operativas. Análisis de alternativas:
- *Auto puro (FEFO, sin elección)*: rápido, minimiza merma; pero el vial físico en la mano del
  vet puede no ser el que FEFO predijo → la trazabilidad regulatoria (NOM-007/046) exige
  registrar lo **realmente aplicado**. Inaceptable solo-auto.
- *Manual puro*: trazabilidad perfecta pero obliga a elegir lote en cada aplicación → fricción
  y errores.
- **Híbrido (elegido)**: el sistema pre-selecciona; el vet puede cambiar. Ver política.

Una dosis de vacuna = 1 vial = 1 lote → sin split. `VaccineRecord` guarda FK al lote **+
snapshot denormalizado** (`lot_number`, `expiry`, `manufacturer`) → registro legal inmutable
aunque el lote se corrija/borre después (append-only por cumplimiento).

---

## 5. Facturación — ¿el lote afecta el cobro?

> **PRINCIPIO DE DOMINIO (binding):** *`StockLot` nunca modifica el comportamiento de precio.
> Solo modifica la trazabilidad del consumo.* Esto es lo que explica —de un solo golpe— por
> qué `InvoiceItem` sigue igual, Billing sigue igual y `cost_behavior` sigue igual. Precio y
> lote son ejes ortogonales: el lote responde "¿de qué unidad física salió?", el precio
> responde "¿cuánto se cobra?". Nunca se cruzan.

**No. El lote es dimensión de stock/trazabilidad, ortogonal al precio.** Se mantiene intacto:
`cost_behavior` (charge/included), `InvoiceItem`, `dispensed_from_prescription_item`, el
predicado `_items_settling_stock`, y el precio desde `Presentation.sale_price`.

- El lote se adjunta al **movimiento de stock** (y como FK nullable de traza en
  `MedicalRecordProduct`/`InvoiceItem`), **nunca** al cálculo de totales.
- Un consumo repartido en 2 lotes sigue siendo **una** línea de `InvoiceItem` (un precio,
  cantidad agregada); el split de lote vive en el ledger (2 `StockMovement`). `InvoiceItem` no
  se fragmenta por lote.
- Reverso (cancel/refund) devuelve al **mismo lote** del movimiento original (leído del
  ledger), no a FEFO (ver política).

La integración de cobro existente no se toca; el lote viaja "por debajo".

---

## 6. Caducidades y estado del lote (`LotStatus`)

`expiry_date` vive en `StockLot`. Se introduce el concepto de estado del lote, **pero no se
almacenan los 5 estados** — dos son derivables y almacenarlos crearía drift (exigiría un cron
que "vence" lotes; si no corre, el estado miente).

- **Almacenados** (estados administrativos, no derivables): `ACTIVE`, `QUARANTINED`, `RECALLED`.
- **Derivados** (fuente de verdad = dato, no un flag):
  - `EXPIRED` = `expiry_date < hoy`
  - `CONSUMED` = `quantity_on_hand == 0`

`effective_status` (property). **Precedencia BINDING (orden fijo, no reordenar):**

```
RECALLED  →  QUARANTINED  →  EXPIRED  →  CONSUMED  →  ACTIVE
```

Se evalúa de arriba abajo; el primero que aplica gana. Expone los 5 hacia la UI, pero la fecha
sigue siendo la única verdad del vencimiento (mismo patrón que `VaccineRecord.status`, que ya
deriva de `next_due_date`). El orden está documentado **explícitamente** para que nadie lo
altere sin una decisión de dominio (un cambio de orden cambia qué se puede consumir).

Alertas: "lotes por vencer en N días" y "lotes vencidos con saldo" (mismo patrón que
`low-stock`) → panel de inventario + dashboard.

**Bloqueo de consumo**: `out` se bloquea si `effective_status ∈ {expired, quarantined,
recalled}`. FEFO solo elige `ACTIVE`. Override de un vencido solo con permiso explícito +
atestación auditable (caso raro: registrar una aplicación pasada). Descarte de stock vencido =
movimiento aparte (`discard`/write-off), no un consumo clínico.

**`RECALLED`** resuelve el retiro de laboratorio: lote no vencido que el fabricante retira →
se **bloquea** el consumo pero **se conserva el saldo** (para devolución/destrucción y
trazabilidad), no se descuenta.

### 6-bis. Inventario físico (conteo)

Caso: 20 en sistema, 17 reales.

- **Producto con `tracks_lots`**: el ajuste es **por lote** (se cuentan viales del lote A123 y
  del A124 por separado — el agregado no basta para saber cuál faltó). Movimiento `adjustment`
  lot-scoped que **fija absoluto** `lot.quantity_on_hand`; `Product.stock_quantity` se
  re-deriva de la suma. Reconciliación lote a lote.
- **Producto sin lotes**: ajuste a nivel Product, absoluto, **exactamente como hoy**.

Un mismo `movement_type='adjustment'` sirve ambos; lo que cambia es si lleva `lot` o no.

---

## 7. Recepción de mercancía (UX multi-lote)

Una compra suele llegar con **varios lotes**. La recepción lo contempla desde el diseño:

```
Entrada de mercancía
  Producto:      Rabia Zoetis
  Proveedor:     Distribuidora X        (→ supplier_name, snapshot)
  Recibido:      2026-07-10
  ── Lotes ──
  Lote A123   Caduca 2027-05   Cant. 10
  Lote A124   Caduca 2028-01   Cant. 10
  + Agregar lote
  ────────────────────────────
  Total: 20
```

Modelo: una recepción = 1 producto + N líneas de lote. Cada línea →
`find-or-create StockLot(product, lot_number, expiry)` + **un** movimiento `in` lot-scoped,
todos con el mismo `supplier_name`/`received_at`/`reason="Entrada de mercancía"`.

- Sin entidad "GoodsReceipt" todavía (el `purchase_order` FK que agruparía la compra va en
  Futuras extensiones — evita complejidad prematura).
- Producto sin `tracks_lots`: la misma pantalla colapsa a una sola cantidad, sin sección de
  lotes → la recepción actual (`StockEntryModal`) **no se rompe**.

> **`supplier_name`, no `supplier`** (observación final integrada): string congelado desde
> hoy. Cuando exista el módulo Compras, se agrega FK nullable `supplier` **al lado** (snapshot
> histórico + FK viva conviven) — sin renombrar, sin migración rara.

---

## 8. Impacto sobre la arquitectura actual

| Entidad | Impacto |
|---|---|
| **Product** | + `tracks_lots` (bool), + `manufacturer` (string). `stock_quantity` sigue siendo agregado autoritativo. Productos sin lote: **cero cambio de comportamiento**. |
| **Presentation** | Sin cambio conceptual. El lote NO cuelga de aquí (queda a nivel Product/base-unit). Precio/barcode intactos. |
| **StockMovement** | + FK nullable `lot`. Legacy y no-lote quedan `null`. |
| **apply_stock_movement()** | Sigue siendo escritor único. Se vuelve lot-aware: valida saldo del lote, debita/acredita lote + Product bajo el mismo lock. **Orden de locks sin cambio.** |
| **MedicalRecordProduct** | + FK nullable `lot` (traza). `save()/delete()` pasan el lote a `apply_stock_movement` y revierten al mismo lote. `cost_behavior` intacto. |
| **Billing** | `_items_settling_stock` sin cambio; la liquidación pasa el lote (FEFO o elegido). `InvoiceItem` + FK nullable `lot` (solo traza, sin impacto en totales). Reversos al lote original. |
| **Medical Records / VaccineRecord** | Cambio clínico mayor pero **aditivo**: FK opcional a Product + lote + snapshot denormalizado. Se conserva `vaccine_name` texto libre como fallback para productos fuera de inventario. |
| **Migración** | Aditiva. Habilitar `tracks_lots` en un producto con stock preexistente exige un **lote baseline "desconocido"** que absorba el saldo actual (seeding puntual). Sin reescritura de datos. |

---

## 9. Políticas operativas (decisiones explícitas)

Documentadas para evitar discusiones futuras frontend/backend. Son **contrato**.

### P1 — Selección automática del lote (FEFO + override)

**¿Quién decide el lote por defecto?** El backend propone; el usuario dispone.

| Situación | Comportamiento |
|---|---|
| **Un único lote elegible** | Se selecciona **automáticamente** (sin pedir input). |
| **Varios lotes elegibles** | Se **propone** el lote FEFO (caducidad más próxima entre `effective_status = ACTIVE`). El usuario **puede cambiarlo** manualmente. |
| **Ningún lote elegible** | El producto **no puede consumirse** (bloqueo con mensaje claro). |

"Elegible" = `effective_status = ACTIVE` y `quantity_on_hand > 0`. Vencidos, en cuarentena y
retirados **no** son elegibles.

### P2 — Sin lotes válidos

Consumo bloqueado (400 de negocio). No se consume "a ciegas" ni se descuenta del agregado sin
lote. Excepción única: override de vencido con permiso explícito + atestación (P4).

### P3 — Override manual del usuario

Si el usuario elige un lote distinto al FEFO propuesto, **se respeta y se registra el lote
elegido** (realidad física > sugerencia del sistema). La trazabilidad guarda lo realmente
usado.

### P4 — Reversión (devoluciones / cancelaciones)

Las reversiones (`in` de compensación por cancelación de factura, refund con restock,
eliminación de producto en consulta) regresan al **lote original** registrado en el movimiento
saliente — **nunca** a FEFO. El ledger es la fuente del lote a revertir.

### P5 — Productos con `tracks_lots = false`

El flujo permanece **exactamente igual que hoy**: sin `StockLot`, sin selección de lote, sin
caducidad, movimiento sin `lot`. La capa de lotes es invisible para ellos.

---

## 10. Escalabilidad — genérico, no específico de vacunas

**`StockLot` es una capacidad del inventario, no una característica de las vacunas.** La vacuna
es solo el **primer caso de uso**. El mismo modelo sirve inyectables, medicamentos con lote,
reactivos e implantes (seriados = lote de `quantity_on_hand = 1`). El driver es un flag por
producto (`tracks_lots`), no un tipo de producto nuevo. Construir un silo de "inventario de
vacunas" sería el error a evitar.

### Principio rector (binding)

> **`StockLot` es una capacidad del inventario, no una característica de las vacunas.**
> Cualquier módulo que consuma productos inventariables (hoy Vacuna; mañana medicamento
> inyectable vía receta → dispensación; después cirugía → anestésicos) **deberá usar la misma
> infraestructura de lotes** cuando el producto tenga `tracks_lots = true`. Ningún módulo
> reimplementa lotes ni salta `apply_stock_movement`.
>
> **Una sola entrada de consumo (`consume_product`).** La resolución FEFO vive **detrás** de un
> único servicio de consumo, **no repartida** entre callers. Ningún consumidor
> (`MedicalRecordProduct`, Billing, y mañana Hospitalización / transferencias / ajustes
> automáticos) llama a `resolve_consumption_lots` directamente: todos pasan por
> `consume_product` → (si `tracks_lots`) FEFO → `apply_stock_movement` → ledger. Así el 4º
> consumidor no puede olvidarse de aplicar la política de lotes.

Trayectoria prevista de consumidores:
```
Vacuna            → StockLot   (primer caso de uso)
Medicamento inyectable → Receta → Dispensación → StockLot
Cirugía → Anestésicos → StockLot
```

---

## 11. Forma resultante de las entidades

```
Product   + tracks_lots (bool), + manufacturer (string)      ← fabricante aquí
StockLot    product FK, lot_number, expiry_date, received_at,
            quantity_on_hand (base-units), supplier_name (snapshot),
            status ∈ {active, quarantined, recalled}          ← expired/consumed derivados
            effective_status (property: recalled|quarantined|expired|consumed|active)
StockMovement            + lot FK nullable
MedicalRecordProduct     + lot FK nullable (traza)
InvoiceItem              + lot FK nullable (traza, sin impacto en precio)
VaccineRecord            + product FK + lot FK + snapshot (lot_number/expiry/manufacturer)
```

**Qué se reutiliza:** escritor único `apply_stock_movement`, orden de locks, ledger
append-only, `cost_behavior`, predicado de dispensación, contrato de facturación.
**Qué se evita:** stock por (lote×presentación), lote obligatorio global, fragmentar
`InvoiceItem` por lote, y un módulo de proveedores prematuro (empezar con `supplier_name`).

---

## 12. Futuras extensiones (documentar, no implementar)

Prueba de que el modelo escala sin rediseño. Todos aditivos, nullable, opt-in:

```
StockLot  (futuro):
  serial_number     → seriados pieza a pieza (implantes) — hoy: lote qty 1
  storage_location  → ubicación física / refrigerador
  temperature_log   → cadena de frío (vacunas) — FK a lecturas
  supplier          → FK nullable (cuando exista módulo Compras) junto a supplier_name
  purchase_order    → FK nullable (agrupa la recepción a una orden de compra / GoodsReceipt)
```

Ninguno reescribe el núcleo (`apply_stock_movement`, orden de locks, ledger, `cost_behavior`).

---

**Principio rector final:** el lote es una dimensión de *stock físico y trazabilidad*,
ortogonal a *precio*; su identidad se **denormaliza** en los registros append-only
(`VaccineRecord`, `StockMovement`) para que ninguna corrección de lote reescriba historia. Y
`StockLot` es infraestructura del inventario que **todo** consumidor de productos reutiliza —
Vacuna es el primero, no el único.
