// Catálogo único de métodos de pago (espejo de PAYMENT_METHOD_CHOICES backend).
export const PAYMENT_METHODS = [
    { value: "cash", label: "Efectivo" },
    { value: "card", label: "Tarjeta" },
    { value: "transfer", label: "Transferencia" },
    { value: "other", label: "Otro" },
];

// Valida líneas de pago contra el total.
//  - allowPartial=true  → admite pagar menos (no se usa para cobros nuevos: ADR p30
//    rev exige total exacto siempre). Se conserva para casos futuros / refund parcial.
//  - allowChange=true   → admite efectivo recibido MAYOR al total; el excedente es
//    cambio, no se registra. Aplica a TODO cobro (ADR p30 rev).
//  - ambos false        → exige monto exacto (refund).
// Construye las payment_lines a enviar al backend (ADR p30 rev): si lo
// ingresado supera el total (cambio en efectivo, no se persiste), se registra
// SOLO el total con el método de la primera línea; si no, se envían las
// líneas > 0 normalizadas a 2 decimales. Única fuente — no copiar por módulo.
export const buildPaymentLines = (lines, total) => {
    const target = Number(Number(total).toFixed(2));
    const sum = Number(lines.reduce((a, l) => a + (Number(l.amount) || 0), 0).toFixed(2));
    if (sum > target) return [{ method: lines[0].method, amount: target.toFixed(2) }];
    return lines
        .filter(l => Number(l.amount) > 0)
        .map(l => ({ method: l.method, amount: Number(l.amount).toFixed(2) }));
};

export const paymentLinesValid = (lines, total, allowPartial, allowChange = false) => {
    if (lines.some(l => Number(l.amount) < 0)) return false;
    const positive = lines.map(l => Number(l.amount)).filter(n => n > 0);
    if (positive.length === 0) return false;
    const sum = Number(positive.reduce((a, n) => a + n, 0).toFixed(2));
    const t = Number(Number(total).toFixed(2));
    if (sum > t) return allowChange;          // sobrepago solo válido si se da cambio
    if (!allowPartial && sum !== t) return false;
    return true;
};
