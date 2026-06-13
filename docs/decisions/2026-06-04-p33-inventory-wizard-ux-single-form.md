# ADR p33: Wizard de inventario — selector de modo + dos flujos

**Fecha**: 2026-06-04 (revisado 2026-06-07)
**Estado**: Aceptado — implementado
**Documentos relacionados**:
- ADR p31 (Product-level stock + conversion_factor)
- ADR p32 (cost_behavior insumo vs cobrado)
- `docs/modules/frontend.md`
- `frontend/src/pages/inventory.jsx`
- `frontend/src/features/inventory/tutorial/`

## Contexto

El wizard anterior expuso conceptos técnicos internos al usuario:

- "Unidad de inventario" (base_unit como selector abstracto en paso 1)
- "Factor de conversión" / "CONTIENE (piezas)" como campos numéricos sin contexto
- "Presentación principal" como label que refleja la arquitectura interna
- Toggle "De una sola forma" / "De varias formas" que duplicaba la pregunta implícita en el modo

Feedback recolectado: perfiles técnicos y no técnicos se confundían porque el flujo describía la arquitectura del sistema en lugar de preguntar lo que el usuario ya sabe sobre su producto físico.

## Propuesta inicial (revisada durante implementación)

La propuesta original era un formulario único con chips visuales para `base_unit` y un accordion "+ También lo vendo en paquete". Tras implementar, se identificó que el problema de fondo era la mezcla de conceptos entre _configurar el inventario_ y _definir formas de venta_ — no la cantidad de pasos.

## Decisión final implementada

**Pantalla de selección de modo** al abrir "Nuevo producto", seguida de **dos flujos distintos** según el tipo de producto.

### Principio de diseño

El modo elegido comunica la intención del usuario; el sistema deriva los conceptos técnicos internamente. El usuario elige el _escenario_, no la arquitectura.

### Modo 1 — Producto normal (simple)

Para productos que se venden de una sola manera (shampoo, collar, alimento).

```
Nombre del producto *
Categoría  |  Código interno (opc.)
▸ Descripción y receta médica  ← accordion

¿Cuánto tienes actualmente?
  Stock inicial  |  Contado como [chips: Pieza / Tableta / ml / Frasco…]

¿Cómo lo vendes?
  Presentación 0:  Nombre | Precio de venta * | Costo | Barcode

Avisar cuando queden menos de ___ en inventario
```

- `divides = false` — solo 2 campos de stock (qty + countUnit)
- Una sola presentación en `salesPres`
- `base_unit` = valor de `countUnit`

### Modo 2 — Varias formas de venta (multi)

Para cuando el mismo inventario se vende en distintas cantidades (caja de jeringas → jeringa individual).

```
Nombre del producto *
Categoría  |  Código interno (opc.)

¿Cuánto tienes actualmente?
  Stock inicial  |  Contado como [chips]
  Cada [unidad] contiene ___  |  Unidad de la parte [chips]

¿Cómo lo vendes?
  Presentación 0 (unidad completa):  Nombre | Precio * | Costo | Barcode
  Presentación 1 (parte suelta):     Nombre | Precio * | Costo | Barcode
                                     ↑ auto-filled desde countUnit y dividesCount

+ Agregar otra forma de venta
```

- `divides = true` — 4 campos de stock (qty, countUnit, dividesCount, dividesUnit)
- Dos presentaciones auto-inicializadas al seleccionar este modo
- `salesPres[1].name` ← auto-sync desde label de `countUnit` (hasta que el usuario edita)
- `salesPres[1].conversion_factor` ← auto-sync desde `dividesCount` (hasta que el usuario edita)
- Tracking de edición manual con `presSecondAutoRef = { nameEdited, cfEdited }` para no pisarle encima al usuario

### Animación educativa (MultiPresentationAnimation)

Al seleccionar el modo multi, se muestra opcionalmente una animación de 5 escenas que explica el concepto "un mismo stock, múltiples formas de venta" usando el ejemplo de guantes de látex.

- `frontend/src/features/inventory/tutorial/MultiPresentationAnimation.jsx`
- Gate: `localStorage.getItem("multi_presentation_animation_seen")` — se muestra una vez
- Props: `config` (texto/números externalizables), `onDismiss`
- SVG assets: `frontend/src/assets/svgs/` (componentes inline en `AnimationSvgs.jsx`)
- Sin llamadas a API, sin lógica de negocio

### Tour interactivo (ProductCreationTour)

Tutorial activado por el botón "Ver ejemplo" en la pantalla de selección de modo.

- 6 pasos: modo-selector → nombre → sección-stock → venta-0 → venta-1 → final
- El popover del tour se posiciona **fuera del modal** (a la derecha, o izquierda si no hay espacio) para no tapar el formulario
- El auto-llenado usa `setWizardMode("multi")` → `useEffect` auto-inicializa `salesPres[1]` → tour llega al paso 4 con los campos ya presentes

### Mapa de estado del wizard (modo multi vs simple)

| Estado | simple | multi |
|---|---|---|
| `wizardMode` | `"simple"` | `"multi"` |
| `divides` | `false` | `true` |
| `salesPres.length` | 1 | ≥ 2 |
| campos stock | qty + countUnit | + dividesCount + dividesUnit |
| `presSecondAutoRef` | no aplica | activo |

### Flujo de guardado (sin cambios vs. ADR original)

1. `handleSubmit()` valida: nombre requerido, `sale_price > 0` en todas las presentaciones, `dividesCount ≥ 1` si `wizardMode === "multi"`
2. `handleWizardSave()` → `POST /inventory/products/` + `POST /inventory/products/<pk>/presentations/` para adicionales
3. Producto siempre se crea con `stock: 0` — stock inicial vía Ajuste de inventario

### Contrato de API sin cambios

- `ProductSerializer.create()` acepta `presentation_input` idéntico
- Rutas y serializers backend sin modificaciones

## Consecuencias

**Positivas:**
- Formulario completable en < 30 segundos para producto simple (modo simple: nombre + unidad + precio)
- El modo multi hace explícita la relación unidad-completa / parte-suelta con lenguaje natural
- Auto-sync de nombre y factor en `salesPres[1]` reduce error de entrada; el usuario puede override
- La animación educativa explica el concepto una sola vez (gate localStorage)
- El tour no tapa el formulario que está explicando

**Eliminados respecto al ADR original:**
- Chips de `base_unit` en paso 1 (reemplazado por campo "contado como" en sección de stock)
- Accordion "+ También lo vendo en paquete" (reemplazado por modo multi con 2 presentaciones)
- Modal de confirmación `showSummary` (no implementado — se consideró overhead para flujo rápido)
- `hasPackage` boolean (reemplazado por `wizardMode === "multi"`)

**Nuevos estados (vs. ADR original):**
- `wizardMode: null | "simple" | "multi"`
- `showMultiAnim: boolean`
- `presSecondAutoRef: { nameEdited, cfEdited }` (useRef, no state — no re-render)
- `divides`, `countQty`, `countUnit`, `dividesCount`, `dividesUnit` — campos del stock section
