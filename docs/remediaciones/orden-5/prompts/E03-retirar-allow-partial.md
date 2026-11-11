# E03 — Retirar `allowPartial`

Primero lee y aplica `docs/remediaciones/orden-5/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Eliminar el pago parcial del frontend. Ningún caller lo activa, su texto menciona el estado «confirmada», ya retirado, y contradice la regla de total exacto (ADR p30 rev).

## Archivos permitidos

- `frontend/src/utils/payments.js` y `frontend/src/utils/payments.test.js`
- `frontend/src/components/PaymentLinesEditor.jsx` y `frontend/src/components/PaymentLinesEditor.test.jsx`
- `frontend/src/components/pos/PaymentPanel.jsx`
- `frontend/src/pages/billing.jsx`
- Expediente del orden 5

## Trampa crítica

`paymentLinesValid` usa parámetros **posicionales**. Al quitar el tercero, `allowChange` pasa a ser el tercero. Si un caller conserva `(lines, total, false, true)`, el cambio en efectivo se desactiva sin ningún error visible. Corrige todos los callers en esta misma entrega.

## Paso 1. `payments.js`

Sustituye el comentario que explica `allowPartial`, `allowChange` y «ambos false» por este, colocado justo encima de `paymentLinesValid`:

```js
// Valida líneas de pago contra el total. Toda factura exige total exacto (ADR p30 rev).
//  - allowChange=true  → admite recibir MÁS que el total; el excedente es cambio y no se registra.
//  - allowChange=false → exige monto exacto (devoluciones).
```

Deja el comentario de `buildPaymentLines` encima de esa función. Después cambia la función:

```js
export const paymentLinesValid = (lines, total, allowChange = false) => {
    if (lines.some(l => Number(l.amount) < 0)) return false;
    const positive = lines.map(l => Number(l.amount)).filter(n => n > 0);
    if (positive.length === 0) return false;
    const sum = Number(positive.reduce((a, n) => a + n, 0).toFixed(2));
    const t = Number(Number(total).toFixed(2));
    if (sum > t) return allowChange;          // sobrepago solo válido si se da cambio
    return sum === t;
};
```

## Paso 2. Callers

| Archivo | Antes | Después |
|---|---|---|
| `components/pos/PaymentPanel.jsx` | `paymentLinesValid(lines, Number(invoice.total), false, true)` | `paymentLinesValid(lines, Number(invoice.total), true)` |
| `components/pos/PaymentPanel.jsx` | prop `allowPartial={false}` | quitar la línea |
| `pages/billing.jsx` (`RefundModal`) | `paymentLinesValid(refundLines, refundTotal, false)` | `paymentLinesValid(refundLines, refundTotal)` |
| `pages/billing.jsx` (`RefundModal`) | prop `allowPartial={false}` | quitar la línea |
| `pages/billing.jsx` (`Billing`) | `const payAllowPartial = false;` | quitar la línea |
| `pages/billing.jsx` (`Billing`) | prop `allowPartial={payAllowPartial}` | quitar la línea |
| `pages/billing.jsx` (`Billing`) | `paymentLinesValid(payLines, payTarget, payAllowPartial, true)` | `paymentLinesValid(payLines, payTarget, true)` |

## Paso 3. `PaymentLinesEditor.jsx`

1. Quita `allowPartial` de las props.
2. Cambia `: (allowPartial ? "Pago completo" : "Exacto")}` por `: "Exacto"}`.
3. Elimina el bloque `{allowPartial && remaining > 0 && sum > 0 && (...)}` completo.

## Paso 4. Pruebas

En `PaymentLinesEditor.test.jsx`: quita `allowPartial` de los parámetros y props de `Host`, y cambia `<Host total={500} allowPartial={false} />` por `<Host total={500} />`.

En `payments.test.js`, dentro de `describe("paymentLinesValid...`:

| Test | Cambio |
|---|---|
| «total exacto sin parciales» | llamada `(…, 100)` |
| «pago insuficiente sin permitir parcial» | renómbralo a `"pago insuficiente → inválido (ADR p30: sin parciales)"`, llamada `(…, 100)` |
| «pago insuficiente permitiendo parcial» | **elimínalo** |
| «sobrepago sin permitir cambio» | llamada `(…, 100, false)` |
| «sobrepago permitiendo cambio» | llamada `(…, 100, true)` |
| «todas las líneas en cero» | llamada `(…, 100)` |
| «array de líneas vacío» | llamada `(…, 100)` |
| «cualquier monto negativo» | llamada `(…, 100)` |
| «monto negativo se bloquea ANTES» | llamada `(…, 100, true)` |
| «split de varios métodos» | llamada `(…, 100)` |
| «líneas positivas + ceros» | llamada `(…, 100)` |

Añade este test en el mismo `describe`:

```js
it("pago insuficiente nunca es válido, aunque se permita cambio", () => {
  expect(paymentLinesValid([{ method: "cash", amount: "50" }], 100, true)).toBe(false);
});
```

## Verificación

```
rtk proxy node_modules/.bin/vitest run src/utils/payments.test.js src/components/PaymentLinesEditor.test.jsx --reporter=dot 2>&1 | tail -15
rtk proxy node_modules/.bin/eslint src/utils/payments.js src/components/PaymentLinesEditor.jsx src/components/pos/PaymentPanel.jsx src/pages/billing.jsx
pnpm run build
```

Busca `allowPartial` y `payAllowPartial` en `frontend/src`: debe haber **0** resultados. Recuento total: **61 errores**.

## Cierre

Commit: `refactor(frontend): remove dead partial-payment path (order 5, C4)`.

Marca C4 como `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`. En «Para revisar», indica que es el único cambio de aserciones permitido del orden.
