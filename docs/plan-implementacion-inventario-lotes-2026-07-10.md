# Plan de implementación — Inventario por lotes (Proyecto B) + secuenciación global

> [!NOTE]
> Plan histórico. Las referencias a `_confirm_locked_invoice` y
> `cancel_invoice` describen el Billing anterior. La integración vigente
> consume/asigna lotes al `post_checkout` y devuelve desde
> `StockAllocation`; consulte [Inventario](modules/inventory.md) y
> [Billing](modules/billing.md).

**Fecha**: 2026-07-10
**Estado**: plan de trabajo. Diseño de referencia (congelado):
[`docs/analisis-inventario-trazabilidad-lotes-2026-07-10.md`](analisis-inventario-trazabilidad-lotes-2026-07-10.md).
Este documento **solo secuencia**; no re-decide el dominio.

---

## Regla de oro — no mezclar proyectos

Dos proyectos distintos aunque relacionados. **Nunca** un cambio/PR que toque ambos dominios
sin justificación explícita.

- **Proyecto A — Protocolos clínicos**: General · Vacuna · Cirugía · Urgencias.
- **Proyecto B — Inventario por lotes**: StockLot · FEFO · Caducidades · Recepción · Discard.

Cada fase se cierra **completamente integrada** (backend + frontend + pruebas + docs) **antes**
de empezar la siguiente.

## Orden global

```
A1  General (protocolo)               ← YA IMPLEMENTADO (pendiente verificación UI/UX)
──────────────────────────────────────  cambio de proyecto
B   Inventario por lotes (StockLot)      ← SIGUIENTE. Bloquea a Vacuna.
──────────────────────────────────────  cambio de proyecto
A2  Vacuna usando StockLot
A3  Cirugía · Urgencias
```

Vacuna depende de StockLot; Cirugía y General no. Implementar `VaccineRecord` "completo" antes
de StockLot obligaría a re-modificarlo → se evita.

**Filosofía**: abstraer solo en la 2ª repetición. No motores genéricos ni infraestructura para
módulos inexistentes. Lo que se construye en B es infraestructura de un dominio **que ya
existe** (inventario/consumo), no especulación.

---

## Decisión arquitectónica clave — una sola entrada de consumo

La resolución FEFO **no** se reparte entre callers. Vive detrás de un único servicio:

```
consume_product(product, qty_base, context…)
        │
        ├── if product.tracks_lots ──►  resolve_consumption_lots()   (FEFO, política P1)
        │
        └──────────────────────────►  apply_stock_movement()  (por lote, o lot=None)
                                              │
                                              └──►  ledger (StockMovement)
```

- **Consumidores** (`MedicalRecordProduct`, Billing, y mañana Hospitalización / transferencias
  / ajustes automáticos) llaman **solo** a `consume_product`. **Ninguno** llama
  `resolve_consumption_lots` directamente.
- `apply_stock_movement` sigue siendo el **escritor único** de bajo nivel (single-lot). El
  split multi-lote y la política FEFO viven en el servicio de consumo, no en el escritor.
- La operación inversa vive en el mismo servicio: `revert_consumption` / restock lee los lotes
  del ledger y devuelve al **lote original** (política P4), nunca FEFO. Así el reverso tampoco
  se dispersa entre callers.

Por qué: mañana el 4º consumidor no puede "olvidarse" de aplicar la política de lotes. Una
entrada = una política. (Principio binding añadido al spec §10.)

---

## PROYECTO B — Inventario por lotes

### Fase B0 — Núcleo: modelo `StockLot` + servicio de consumo

**Backend**
- `Product` + `tracks_lots` (bool, default `false`) + `manufacturer` (string = **fabricante
  del producto comercial**: Zoetis/MSD/Boehringer; no el principio activo — spec §1).
- `StockLot`: `product` FK, `lot_number`, `expiry_date`, `received_at`, `quantity_on_hand`
  (base-units), `supplier_name` (snapshot), `status ∈ {active, quarantined, recalled}`.
  Property `effective_status` con **precedencia fija BINDING**:
  `RECALLED → QUARANTINED → EXPIRED → CONSUMED → ACTIVE` (primero que aplica gana; no
  reordenar — spec §6). CHECK `quantity_on_hand >= 0`. Unicidad `(product, lot_number, expiry_date)`.
- `StockMovement` + `lot` FK **nullable**.
- `apply_stock_movement(..., lot=None)` — escritor único de bajo nivel, ahora lot-aware:
  si `lot` presente, debita/acredita `StockLot` + `Product` bajo el **mismo** lock de Product;
  valida saldo del lote en `out`. `tracks_lots=false` → `lot=None` → **idéntico a hoy**.
- **`consume_product(product, qty_base, …)`** — única entrada pública de consumo (ver arriba).
  Interno: `resolve_consumption_lots(product, qty_base)` (FEFO entre `effective_status=ACTIVE`,
  política P1; `raise` si no hay elegibles, P2) + bucle sobre `apply_stock_movement` por lote.
  Para `tracks_lots=false` = un solo `apply_stock_movement(lot=None)`.
- `revert_consumption(...)` — inversa, restock al lote original leído del ledger (P4).
- Migración **aditiva** (todo nullable/nuevo/default). Baseline "lote desconocido" solo al
  activar `tracks_lots` sobre un producto con saldo previo (seeding puntual).
- `audit_stock_integrity` + invariante `Σ lotes == Product.stock_quantity` para `tracks_lots`.

**Frontend**
- Wizard de producto: toggle "¿Requiere control de lotes?" (`tracks_lots`) + campo
  `manufacturer`.

**Pruebas**: FEFO (1/varios/ninguno), débito/crédito por lote, negativo por lote, invariante,
`effective_status` (precedencia), `consume_product` con `tracks_lots=false` **sin cambio**
(regresión del path actual).
**Docs**: `docs/modules/inventory.md`.
**DoD**: producto lote-trackeado creado, su stock se mueve por `consume_product`, y los
productos sin lote se comportan exactamente igual (probado).

### Fase B1 — Recepción de mercancía multi-lote

**Backend**: servicio de recepción (producto + `supplier_name` + `received_at` + N líneas de
lote → find-or-create `StockLot` + un `in` por lote). `tracks_lots=false` → cantidad única
(path de ajuste actual, sin cambio).
**Frontend**: extender `StockEntryModal` — sección "Lotes" con `+ Agregar lote`
(lote/caducidad/cantidad) **solo** si `tracks_lots`; colapsa a cantidad única si no.
**Pruebas + Docs**.
**DoD**: una compra con 2 lotes distintos entra en una sola operación y queda trazada.

### Fase B2 — Consumo FEFO + caducidades + discard (integración con paths existentes)

**Backend**
- Rutear los consumidores **existentes** (`MedicalRecordProduct.save/delete`, Billing
  `_confirm_locked_invoice`, `cancel_invoice`, refund restock) a través de
  `consume_product` / `revert_consumption`. **No** llaman FEFO directo.
- Política P1 en `consume_product` (auto si 1, FEFO propuesto + override si varios, bloqueo si
  ninguno). Bloqueo de `expired/quarantined/recalled` (P2/§6).
- Reversos al lote original (P4) vía `revert_consumption`.
- `discard`/write-off para merma de vencidos (movimiento aparte, no consumo).
- Acciones administrativas: `quarantine` / `recall` sobre lote.
- Alertas: "lotes por vencer en N días" y "vencidos con saldo".

**Frontend**
- Selector de lote en puntos de consumo (`ChargesSection`, POS, dispensación) **solo** si
  `tracks_lots`: lote FEFO pre-seleccionado + dropdown override (ordenado por caducidad;
  muestra lote/caducidad/saldo).
- Alertas de caducidad en inventario + panel del dashboard (patrón `low-stock`).
- Acción Discard + admin cuarentena/retiro.

**Pruebas + Docs**.
**DoD**: activar `tracks_lots` en un medicamento cualquiera y consumirlo en consulta/POS
descuenta del lote correcto (FEFO), bloquea vencidos y revierte al lote original.

> **Decisión contenida en B2**: restock de refund **parcial** cuando un ítem se consumió
> repartido en varios lotes. Se resuelve al implementar, leyendo las salidas del ítem en el
> ledger vía `revert_consumption`. La vacuna no sufre esto (dosis = 1 lote).

**Exclusiones de todo el Proyecto B** (no abstraer hasta que exista el 2º caso real): módulo
`Supplier` (solo `supplier_name`), `purchase_order`/GoodsReceipt, `serial_number`,
`storage_location`, `temperature_log`. Documentados en §12 del spec; **no se implementan**.

---

## PROYECTO A (reanuda) — Vacuna usando StockLot

### Fase A2 — Vacuna consume StockLot (el puente)

Recién con B disponible:
- `VaccineRecord` + FK opcional `product` + FK `lot` + **snapshot** (`lot_number`, `expiry`,
  `manufacturer`) — registro legal inmutable. Se conserva `vaccine_name` texto libre como
  fallback (vacuna fuera de inventario).
- Al finalizar la consulta de vacuna: si el preset mapea a un `Product` con `tracks_lots`, se
  **consume del lote** vía `consume_product` (FEFO propuesto + override, reusando el selector
  de B2) y el `VaccineRecord` se materializa con `product`+`lot`+snapshot, todo en el **mismo
  atomic** del cierre (principio binding: el protocolo no muta MedicalRecord, solo crea su
  registro).
- Presets de vacuna (`vaccinePresets.js`) pueden ligarse a un `Product`.
- Pruebas (materialización con lote, bloqueo de vencido, override) + docs.
- **DoD**: aplicar una vacuna descuenta el vial del lote correcto vía `consume_product` y el
  `VaccineRecord` traza lote/caducidad reales.

### Fase A3 — Cirugía · Urgencias

Plan de protocolos (`docs/plan-implementacion-protocolos-clinicos-2026-07-09.md`),
**reordenado**: Vacuna pasó a A2 (post-StockLot). Cirugía/Urgencias no dependen de lotes; sus
anestésicos/insumos reusan `consume_product` **si** el producto tiene `tracks_lots`. La
abstracción del materializador backend (registry de protocolos) se extrae en la 2ª repetición
(Cirugía), como ya estaba planeado.

---

## Mapa de dependencias

```
General(A1, hecho) ─── independiente
StockLot B0 → B1 → B2 ─── bloquea →  Vacuna A2 → (Cirugía, Urgencias) A3
                                     Cirugía reusa consume_product si tracks_lots
consume_product (B0) = única entrada; MRP + Billing (+ futuros) la comparten
```

`consume_product` es la pieza compartida por MRP + Billing — abstracción justificada porque
**ambos son callers reales hoy**, no futuros. FEFO nunca vive en un caller.

## Principios que rigen el plan (del spec congelado)

1. **StockLot nunca modifica el precio; solo la trazabilidad del consumo** (§5). Por eso
   `InvoiceItem`, Billing y `cost_behavior` quedan intactos.
2. **Una sola entrada de consumo** (`consume_product`); FEFO detrás del servicio, no en callers.
3. **`effective_status`** con precedencia fija `RECALLED → QUARANTINED → EXPIRED → CONSUMED → ACTIVE`.
4. **`Product.manufacturer`** = fabricante del producto comercial, no del principio activo.
5. **Opt-in `tracks_lots`**: `false` = flujo idéntico a hoy.

## Riesgos / guardas
- **B0 toca el escritor único y crea la entrada de consumo**: `tracks_lots=false` debe recorrer
  el mismo camino de hoy → test de regresión obligatorio **antes** de re-rutear los callers.
- **Orden de locks intacto**: el lote pertenece al Product ya lockeado; prohibido lockear
  `StockLot` fuera de ese candado.
- **Migración aditiva**: sin reescritura; baseline "lote desconocido" solo al activar el flag
  con saldo previo.
- **No mezclar**: cada fase = sus propios PRs/commits dentro de un solo dominio.
