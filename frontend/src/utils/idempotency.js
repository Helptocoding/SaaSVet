// ADR p27: clave de idempotencia por intento de cobro (anti doble-cobro en
// reintento de red — header X-Idempotency-Key). Se reusa mientras el intento
// siga vivo (modal de pago abierto / cobro POS en curso) y se regenera tras
// cada cobro exitoso.
export const newIdempotencyKey = () =>
    (typeof crypto !== "undefined" && crypto.randomUUID)
        ? crypto.randomUUID()
        : `idem-${Date.now()}-${Math.random().toString(16).slice(2)}`;

// Identidad de una operación que el servidor valida como UUID. getRandomValues existe
// también donde randomUUID no (contextos sin HTTPS, p. ej. una red local de la clínica).
export const newOperationUuid = () => {
    if (crypto.randomUUID) return crypto.randomUUID();
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
};
