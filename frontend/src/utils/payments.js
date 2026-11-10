// Catálogo único de métodos de pago (espejo de PAYMENT_METHOD_CHOICES backend).
export const PAYMENT_METHODS = [
    { value: "cash", label: "Efectivo" },
    { value: "card", label: "Tarjeta" },
    { value: "transfer", label: "Transferencia" },
    { value: "other", label: "Otro" },
];

const sumLineAmounts = (lines) =>
    Number(lines.reduce((a, l) => a + (Number(l.amount) || 0), 0).toFixed(2));

// Resumen visual de las líneas contra el total. Única fuente de sum/remaining/change.
// Suma todas las líneas, incluso negativas: la validez la decide paymentLinesValid.
export const paymentSummary = (lines, total) => {
    const sum = sumLineAmounts(lines);
    const remaining = Number((Number(total) - sum).toFixed(2));
    return { sum, remaining, change: remaining < 0 ? Math.abs(remaining) : 0 };
};

// Construye las payment_lines a enviar al backend (ADR p30 rev): si lo
// ingresado supera el total (cambio en efectivo, no se persiste), se registra
// SOLO el total con el método de la primera línea; si no, se envían las
// líneas > 0 normalizadas a 2 decimales. Única fuente — no copiar por módulo.
export const buildPaymentLines = (lines, total) => {
    const target = Number(Number(total).toFixed(2));
    const sum = sumLineAmounts(lines);
    if (sum > target) return [{ method: lines[0].method, amount: target.toFixed(2) }];
    return lines
        .filter(l => Number(l.amount) > 0)
        .map(l => ({ method: l.method, amount: Number(l.amount).toFixed(2) }));
};

// Valida líneas de pago contra el total. Toda factura exige total exacto (ADR p30 rev).
//  - allowChange=true  → admite recibir MÁS que el total; el excedente es cambio y no se registra.
//  - allowChange=false → exige monto exacto (devoluciones).
export const paymentLinesValid = (lines, total, allowChange = false) => {
    if (lines.some(l => Number(l.amount) < 0)) return false;
    const positive = lines.map(l => Number(l.amount)).filter(n => n > 0);
    if (positive.length === 0) return false;
    const sum = Number(positive.reduce((a, n) => a + n, 0).toFixed(2));
    const t = Number(Number(total).toFixed(2));
    if (sum > t) return allowChange;          // sobrepago solo válido si se da cambio
    return sum === t;
};
