# E02 — C4 y C5: matemática de pagos y nombres accesibles

Primero lee y aplica `docs/remediaciones/orden-5/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Que `sum`, `remaining` y `change` existan en un solo sitio, y que los controles de pago tengan nombre accesible. Sin cambios de redondeo, de cambio en efectivo ni de apariencia.

## Archivos permitidos

- `frontend/src/utils/payments.js`
- `frontend/src/utils/payments.test.js`
- `frontend/src/components/PaymentLinesEditor.jsx`
- `frontend/src/components/PaymentLinesEditor.test.jsx`
- `docs/modules/frontend.md` (una nota)
- Expediente del orden 5

## Trampa

`paymentLinesValid` **no** usa la misma suma: rechaza negativos y luego suma solo positivos. El editor suma todas las líneas y un test ancla `Ingresado $-50.00`. **No toques `paymentLinesValid`.**

## Paso 1. Helper en `payments.js`

Añade justo después de `PAYMENT_METHODS`:

```js
const sumLineAmounts = (lines) =>
    Number(lines.reduce((a, l) => a + (Number(l.amount) || 0), 0).toFixed(2));

// Resumen visual de las líneas contra el total. Única fuente de sum/remaining/change.
// Suma todas las líneas, incluso negativas: la validez la decide paymentLinesValid.
export const paymentSummary = (lines, total) => {
    const sum = sumLineAmounts(lines);
    const remaining = Number((Number(total) - sum).toFixed(2));
    return { sum, remaining, change: remaining < 0 ? Math.abs(remaining) : 0 };
};
```

En `buildPaymentLines` cambia la línea `const sum = Number(lines.reduce(...` por `const sum = sumLineAmounts(lines);`.

## Paso 2. Consumir en `PaymentLinesEditor.jsx`

Importa `paymentSummary` junto a `PAYMENT_METHODS` y sustituye las tres primeras líneas del cuerpo (`const sum`, `const remaining`, `const change`) por:

```js
const { sum, remaining, change } = paymentSummary(lines, total);
```

## Paso 3. Nombres accesibles (C5)

En el mismo archivo, sin tocar estilos:

| Control | Añadir |
|---|---|
| `<select>` | ``aria-label={`Método de pago ${i + 1}`}`` |
| `<input type="number">` | ``aria-label={`Monto del método ${i + 1}`}`` |
| botón con `Icon.Trash` | ``aria-label={`Quitar método ${i + 1}`}`` |

## Paso 4. Pruebas

En `PaymentLinesEditor.test.jsx`:

1. Sustituye el helper `removeButtons` y su comentario por:

   ```js
   const removeButtons = () => screen.queryAllByRole("button", { name: /quitar método/i });
   ```

   Usa `queryAll` porque con una sola línea el botón está oculto y el test espera longitud 0. Ninguna aserción cambia.

2. Añade este bloque antes del `describe` de `disabled`:

   ```js
   describe("PaymentLinesEditor — nombres accesibles", () => {
     it("cada control de una línea tiene nombre accesible propio", async () => {
       const user = userEvent.setup();
       render(<Host total={500} />);
       await user.click(addButton());

       expect(screen.getByRole("combobox", { name: "Método de pago 1" })).toBeInTheDocument();
       expect(screen.getByRole("combobox", { name: "Método de pago 2" })).toBeInTheDocument();
       expect(screen.getByRole("spinbutton", { name: "Monto del método 2" })).toBeInTheDocument();
       expect(screen.getByRole("button", { name: "Quitar método 1" })).toBeEnabled();
     });
   });
   ```

En `payments.test.js` importa `paymentSummary` y añade:

```js
describe("paymentSummary — resumen visual de las líneas", () => {
  it("monto vacío cuenta como cero", () => {
    expect(paymentSummary([{ method: "cash", amount: "" }], 500)).toEqual({ sum: 0, remaining: 500, change: 0 });
  });

  it("normaliza la deriva de punto flotante", () => {
    const lines = [{ method: "cash", amount: "199.99" }, { method: "card", amount: "300.01" }];
    expect(paymentSummary(lines, 500)).toEqual({ sum: 500, remaining: 0, change: 0 });
  });

  it("calcula el cambio cuando se recibe de más", () => {
    expect(paymentSummary([{ method: "cash", amount: "600" }], 500)).toEqual({ sum: 600, remaining: -100, change: 100 });
  });

  it("una línea negativa entra en la suma: la validez no se decide aquí", () => {
    expect(paymentSummary([{ method: "cash", amount: "-50" }], 500)).toEqual({ sum: -50, remaining: 550, change: 0 });
  });

  it("acepta el total como texto", () => {
    expect(paymentSummary([{ method: "cash", amount: "100" }], "100.00").remaining).toBe(0);
  });
});
```

## Paso 5. Documentación

En `docs/modules/frontend.md`, sección de Gotchas, elimina el bullet que empieza con `` `PaymentLinesEditor` recalcula `sum`/`remaining`/`change` **inline** `` y su continuación.

## Verificación

```
rtk proxy node_modules/.bin/vitest run src/utils/payments.test.js src/components/PaymentLinesEditor.test.jsx --reporter=dot 2>&1 | tail -15
rtk proxy node_modules/.bin/eslint src/utils/payments.js src/components/PaymentLinesEditor.jsx
pnpm run build
```

Comprueba con `git diff` que en `PaymentLinesEditor.test.jsx` no cambió ninguna aserción existente. Recuento total: **61 errores**.

## Cierre

Commit: `refactor(frontend): centralize payment math and name payment controls (order 5, C4, C5)`.

Marca C5 como `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`. C4 queda `EN_CURSO` hasta E03.
