// P1-5 Fase A (A4): privacidad Sentry en el browser.
//
// `beforeSend` corre sobre cada evento antes de salir. Defensa de privacidad de
// un SaaS clínico: nunca enviar a un tercero historial clínico, notas médicas,
// teléfonos, emails, datos financieros ni tokens.
//
// Estrategia espejo del backend (apps/core/observability.py): dropear el body
// del request (puede traer notas/montos/PII) y filtrar headers sensibles. Las
// URLs usan public_id (UUID) → no son PII, se conservan para debuggear.

const SENSITIVE_HEADERS = [
    "authorization",
    "cookie",
    "x-csrftoken",
    "x-idempotency-key",
    "x-api-key",
];

const SENSITIVE_USER_KEYS = ["email", "username", "ip_address", "name", "phone"];

const FILTERED = "[Filtered]";

export function scrubEvent(event) {
    if (!event || typeof event !== "object") return event;

    if (event.request && typeof event.request === "object") {
        // Body completo fuera (puede contener PII clínica/financiera).
        delete event.request.data;
        delete event.request.cookies;
        const headers = event.request.headers;
        if (headers && typeof headers === "object") {
            for (const key of Object.keys(headers)) {
                if (SENSITIVE_HEADERS.includes(key.toLowerCase())) {
                    headers[key] = FILTERED;
                }
            }
        }
    }

    if (event.user && typeof event.user === "object") {
        for (const key of SENSITIVE_USER_KEYS) {
            delete event.user[key];
        }
    }

    return event;
}
