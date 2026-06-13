// ADR p27: clave de idempotencia por intento de cobro (anti doble-cobro en
// reintento de red — header X-Idempotency-Key). Se reusa mientras el intento
// siga vivo (modal de pago abierto / cobro POS en curso) y se regenera tras
// cada cobro exitoso.
export const newIdempotencyKey = () =>
    (typeof crypto !== "undefined" && crypto.randomUUID)
        ? crypto.randomUUID()
        : `idem-${Date.now()}-${Math.random().toString(16).slice(2)}`;
