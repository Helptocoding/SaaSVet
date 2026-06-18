// P1-5 Fase A (A1): correlación end-to-end. El frontend acuña un request_id por
// request y lo manda en el header X-Request-ID; el backend lo reusa en logs,
// Sentry y en la respuesta. Mismo patrón que utils/idempotency.js.
export const genRequestId = () =>
    (typeof crypto !== "undefined" && crypto.randomUUID)
        ? crypto.randomUUID()
        : `req-${Date.now()}-${Math.random().toString(16).slice(2)}`;
