// Formateador único de montos (ADR p70 D4). Sustituye a los locales
// (`formatCurrency`, `fmtMXN`, `toFixed(2)` con "$" pegado) en las pantallas de
// precios. Solo da formato: nunca calcula impuestos (el backend entrega el
// precio con IVA; contrato del POS: sin matemática financiera en React).
const MONEY = new Intl.NumberFormat("es-MX", {
    style: "currency",
    currency: "MXN",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
});

export const formatMoney = (value) => MONEY.format(Number(value) || 0);

// "0.1600" → "16 %" para rotular el IVA vigente. null si no hay tasa.
export const formatTaxRate = (rate) => {
    if (rate === null || rate === undefined || rate === "") return null;
    const pct = Number(rate) * 100;
    if (!Number.isFinite(pct)) return null;
    return `${Number.isInteger(pct) ? pct : pct.toFixed(2)} %`;
};
