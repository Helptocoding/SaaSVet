"""
Sentry privacy scrubbing (P1-5 Fase A — A2).

`before_send` se ejecuta sobre CADA evento antes de salir hacia Sentry. Es la
última línea de defensa de privacidad de un SaaS clínico multi-tenant: nunca
debe filtrarse a un tercero información sensible.

NUNCA enviar:
  - historial clínico / notas médicas        → viajan en request bodies (POST/PATCH)
  - datos financieros (montos, pagos)         → request bodies
  - teléfonos, emails, direcciones de dueños  → request bodies + user PII
  - Authorization / Cookies / tokens          → headers

Estrategia: dropear el cuerpo del request por completo (no se puede saber qué
campo es clínico vs benigno) y filtrar headers sensibles por denylist. Se
conservan los datos NO sensibles que sirven para debuggear: `request_id` y
`organization_id` (tags, ids internos — no PII), método, url (las urls usan
`public_id` UUID, no PII), y el stacktrace.

`send_default_pii=False` ya excluye user PII e IP a nivel SDK; este hook agrega
defensa en profundidad y cubre el request body, que el SDK SÍ adjunta.

Módulo puro (sin imports de Django): seguro de importar desde settings al
inicializar Sentry en tiempo de arranque.
"""

# Headers que jamás deben salir (comparación case-insensitive).
SENSITIVE_HEADERS = frozenset({
    "authorization",
    "cookie",
    "set-cookie",
    "proxy-authorization",
    "x-csrftoken",
    "x-idempotency-key",
    "x-api-key",
})

# Claves de PII a remover del bloque `user` (defensa extra sobre send_default_pii).
SENSITIVE_USER_KEYS = ("email", "username", "ip_address", "name", "phone")

_FILTERED = "[Filtered]"


def _scrub_headers(headers):
    if isinstance(headers, dict):
        return {
            k: (_FILTERED if isinstance(k, str) and k.lower() in SENSITIVE_HEADERS else v)
            for k, v in headers.items()
        }
    return headers


def scrub_event(event):
    """Aplica el scrubbing in-place y devuelve el evento (None descartaría)."""
    if not isinstance(event, dict):
        return event

    request = event.get("request")
    if isinstance(request, dict):
        # Body completo: puede contener notas clínicas / montos / PII → fuera.
        request.pop("data", None)
        request.pop("cookies", None)
        if "headers" in request:
            request["headers"] = _scrub_headers(request["headers"])

    user = event.get("user")
    if isinstance(user, dict):
        for key in SENSITIVE_USER_KEYS:
            user.pop(key, None)

    return event


def before_send(event, hint):
    """Hook de sentry_sdk.init. Nunca debe lanzar — un fallo aquí tumbaría el
    reporte de errores que es justo lo que queremos preservar."""
    try:
        return scrub_event(event)
    except Exception:  # pragma: no cover - defensivo
        # Ante un evento con shape inesperado, preferimos no enviarlo a enviar
        # algo sin scrubbear (fail-closed por privacidad).
        return None
