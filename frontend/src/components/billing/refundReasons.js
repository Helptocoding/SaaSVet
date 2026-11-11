// ADR p29: causas de devolución (deben coincidir con CREDIT_NOTE_REASON_CODES del backend).
export const REASON_CODES = [
    { value: "customer_return", label: "Devolución del cliente" },
    { value: "damaged_product", label: "Producto dañado" },
    { value: "expired_product", label: "Producto caducado" },
    { value: "duplicate_charge", label: "Cargo duplicado" },
    { value: "pricing_error", label: "Error de precio" },
    { value: "goodwill", label: "Cortesía" },
    { value: "clinical_cancellation", label: "Cancelación clínica" },
    { value: "other", label: "Otro" },
];
export const REASON_LABELS = Object.fromEntries(REASON_CODES.map(r => [r.value, r.label]));
