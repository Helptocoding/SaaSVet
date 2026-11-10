# E11 — F02: dividir `billing.jsx`

Primero lee y aplica `docs/remediaciones/orden-5/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Sacar tres subcomponentes de `billing.jsx` a archivos propios **sin cambiar ni una línea de su lógica**, y después fijar su comportamiento con pruebas. Es código de dinero y hoy no tiene ninguna prueba.

## Archivos permitidos

- `frontend/src/pages/billing.jsx`
- `frontend/src/components/billing/` (nuevos: `RefundModal.jsx`, `DispenseLotSelect.jsx`, `PrescriptionDispensePanel.jsx`, `refundReasons.js` y sus pruebas)
- `docs/modules/frontend.md` (una nota)
- Expediente del orden 5

## Regla central

Copia y pega. No renombres variables, no reformatees, no corrijas nada, aunque veas algo mejorable. En particular:

- La línea `const updated = await toast.promise(` de `decline` usa un patrón desaconsejado. `handleDispensed` ignora su argumento, así que hoy no causa daño. **Déjala igual** y anótala en evidencia.
- Dentro de `PrescriptionDispensePanel`, `suggestions.map(s => ...)` usa `s` como parámetro y tapa al import del CSS. Es correcto; no lo renombres.

## Paso 1. `refundReasons.js`

Crea `frontend/src/components/billing/refundReasons.js` moviendo tal cual el comentario ADR p29, `REASON_CODES` y `REASON_LABELS`. Añade `export` a ambas constantes.

## Paso 2. Extraer

Cada archivo contiene el bloque movido sin cambios, y al final `export default <Nombre>;`.

| Archivo | Bloque a mover | Imports exactos |
|---|---|---|
| `RefundModal.jsx` | desde `/* ── RefundModal` hasta el `};` de cierre del componente | `useState` de react; `apiError` de `../../utils/apiError`; `refundInvoice` de `../../api/billing`; `Icon` de `../icons`; `toast` de `sonner`; `PaymentLinesEditor` de `../PaymentLinesEditor`; `paymentLinesValid` de `../../utils/payments`; `newIdempotencyKey` de `../../utils/idempotency`; `REASON_CODES` de `./refundReasons`; `s` de `../../pages/billing.module.css` |
| `DispenseLotSelect.jsx` | desde `/* Override opcional de lote` hasta su `};` | ninguno |
| `PrescriptionDispensePanel.jsx` | desde `/* ── PrescriptionDispensePanel` hasta su `};`, incluye `PRESCRIPTION_BLOCK_REASON` | `useState` de react; `apiError`; `dispensePrescription` y `decidePrescriptionItem` de `../../api/billing`; `Icon`; `toast`; `newIdempotencyKey`; `authoritativePresentationMax` de `../../utils/prescriptionAvailability`; `DispenseLotSelect` de `./DispenseLotSelect`; `s` de `../../pages/billing.module.css` |

## Paso 3. `billing.jsx`

1. Elimina los bloques movidos y las constantes `REASON_CODES` y `REASON_LABELS`.
2. Añade:

   ```js
   import RefundModal from "../components/billing/RefundModal";
   import PrescriptionDispensePanel from "../components/billing/PrescriptionDispensePanel";
   import { REASON_LABELS } from "../components/billing/refundReasons";
   ```

3. Quita de los imports `refundInvoice`, `dispensePrescription`, `decidePrescriptionItem` y `authoritativePresentationMax`. **Lint no detecta sobrantes con mayúscula inicial.** Los demás imports siguen en uso según el análisis previo: no quites otros.

## Paso 4. Demostrar que no cambió nada

Antes de hacer commit, crea en tu scratchpad un script que no se versiona:

```js
// verbatim.cjs — ejecutar desde la raíz del repositorio
const { execSync } = require("child_process");
const fs = require("fs");
const norm = (t) => t.replace(/\r\n/g, "\n");
const old = norm(execSync("git show HEAD:frontend/src/pages/billing.jsx", { maxBuffer: 1 << 24 }).toString());
const between = (a, b) => old.slice(old.indexOf(a), old.indexOf(b));
const blocks = {
  "RefundModal.jsx": between("/* ── RefundModal", "/* Override opcional de lote"),
  "DispenseLotSelect.jsx": between("/* Override opcional de lote", "/* ── PrescriptionDispensePanel"),
  "PrescriptionDispensePanel.jsx": between("/* ── PrescriptionDispensePanel", "const Billing = () => {"),
};
for (const [file, block] of Object.entries(blocks)) {
  const text = norm(fs.readFileSync(`frontend/src/components/billing/${file}`, "utf8"));
  console.log(file, text.includes(block.trim()) ? "IDENTICO" : "DIFIERE");
}
```

Las tres líneas deben decir `IDENTICO`. Si alguna dice `DIFIERE`, corrige la copia.

## Paso 5. Pruebas de caracterización

En `src/components/billing/`. Simula solo `../../api/billing` y `sonner`:

```js
vi.mock("sonner", () => ({ toast: { promise: vi.fn((p) => p), error: vi.fn(), success: vi.fn() } }));
```

No simules `payments`, `PaymentLinesEditor` ni `prescriptionAvailability`.

**`RefundModal.test.jsx`**. Datos:

```js
const invoice = { public_id: "inv-1", id: 7, total: "300.00", items: [
  { id: 1, description: "Consulta", quantity: "1.00", subtotal: "100.00", presentation: null },
  { id: 2, description: "Shampoo", quantity: "2.00", subtotal: "200.00", presentation: 55 },
]};
```

Casos:

1. Por defecto, «Emitir devolución» llama a `refundInvoice("inv-1", ...)` con `creditLines` de ambas filas (`quantity` y `amount` a 2 decimales, `disposition: "restock"`), `refundLines: [{ method: "cash", amount: "300.00" }]`, `reasonCode: "customer_return"`, `reasonNotes: ""` y `idempotencyKey` de tipo texto. `onDone` se llama una vez.
2. Al desmarcar la primera fila, el botón se deshabilita porque el reembolso ya no iguala. Tras «Igualar al total» se habilita y envía `amount: "200.00"`.
3. Una cantidad mayor que la máxima deshabilita el botón.
4. Si `refundInvoice` rechaza, el modal sigue abierto y `onDone` no se llama. Al reintentar se usa **la misma** `idempotencyKey`.
5. Una línea sin presentación envía siempre `disposition: "restock"`.

**`DispenseLotSelect.test.jsx`**: incluye la opción «FEFO automático» y los lotes de la presentación elegida. Al cambiar la selección llama a `setRow(row.key, { lot })`.

**`PrescriptionDispensePanel.test.jsx`**. Datos:

```js
const invoice = { public_id: "chk-1", prescription_public_id: "rx-1", lifecycle: "open", version: 3, prescription_suggestions: [{
  prescription_item_id: 11, product_name: "Amoxicilina", dose: "1 tableta", base_unit: "tableta",
  prescribed_quantity_base: "10", fulfilled_quantity_base: "0", selected_quantity_base: "0", legal_remaining_quantity_base: "10",
  decision: "pending", tracks_lots: false,
  presentations: [{ id: 5, name: "Caja 10", sale_price: "100", max_selectable_quantity: 2, available_stock_quantity_presentations: 4, lots: [], blocking_reasons: [] }],
}]};
```

Casos:

1. No renderiza nada si `lifecycle` no es `open`, si no hay sugerencias o si falta `prescription_public_id`.
2. Nada viene preseleccionado: «Agregar al cobro» está deshabilitado.
3. Al marcar la fila y agregar, llama a `dispensePrescription("rx-1", { lines: [{ presentation: 5, quantity: 1, prescription_item: 11 }], expectedVersion: 3, idempotencyKey: expect.any(String) })` y luego a `onDispensed`.
4. Una cantidad por encima de `max_selectable_quantity` deshabilita el botón.
5. Con `tracks_lots: true`, sin elegir lote la línea no incluye `lot`; al elegirlo, sí.
6. «No lo llevará» llama a `decidePrescriptionItem("chk-1", 11, { decision: "declined", reasonCode: "not_now", expectedVersion: 3 })` y a `onDispensed`. **No afirmes el argumento de `onDispensed` en este caso.**

Prueba comportamiento observable: roles y texto, no estado interno. Sin snapshots.

## Paso 6. Documentación

En `docs/modules/frontend.md`, sección «Pendiente (siguientes fases)», cambia la línea que empieza con `C: extraer la lógica pura restante` para indicar que los subcomponentes de billing ya están en `components/billing/`.

## Verificación

```
rtk proxy node_modules/.bin/vitest run src/components/billing --reporter=dot 2>&1 | tail -15
rtk proxy node_modules/.bin/eslint src/pages/billing.jsx src/components/billing
pnpm run build
```

Recuento total: **0 errores**.

## Cierre

Commit: `refactor(frontend): extract billing subcomponents and cover them with tests (order 5, F02)`.

Marca F02 como `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`. Registra la salida de `verbatim.cjs` en evidencia.
