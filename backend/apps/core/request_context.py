"""
Request correlation id (P1-5 Fase A — observabilidad / debugging beta).

Un único `request_id` que viaja:

    Frontend → header X-Request-ID → RequestIDMiddleware → contextvar
             → logs (RequestIDLogFilter) → Sentry tag → exception handler
             → header X-Request-ID en la respuesta → reporte del usuario.

El valor vive en un `contextvars.ContextVar` para que el log filter y el
exception handler puedan leerlo SIN tener acceso al objeto `request` (los
filtros de logging no lo reciben). El middleware es el único que lo escribe y
SIEMPRE lo limpia en `finally` (reset del token) — en gunicorn gthread cada
request corre en un thread reusado, así que dejar el valor pegado filtraría el
id de un request al siguiente.

Pure stdlib (contextvars + uuid): seguro de importar desde settings/LOGGING en
tiempo de arranque, sin tocar Django ni modelos.
"""
import contextvars
import uuid

# default=None → "fuera de un request" (management commands, shell, arranque).
_request_id: contextvars.ContextVar = contextvars.ContextVar("request_id", default=None)


def new_request_id() -> str:
    """Genera un id nuevo (uuid4 canónico con guiones)."""
    return str(uuid.uuid4())


def coerce_request_id(incoming: str | None) -> str:
    """
    Normaliza un X-Request-ID entrante. El header es controlado por el cliente,
    así que NO se confía en su contenido crudo (log injection / payload):

      - UUID válido (cualquier formato) → se normaliza a su forma canónica.
      - Cualquier otra cosa (vacío, basura, demasiado largo) → id nuevo.

    Esto mantiene la correlación cuando el frontend manda un uuid legítimo y
    blinda los logs de strings arbitrarios inyectados por un atacante.
    """
    if incoming:
        try:
            return str(uuid.UUID(str(incoming)))
        except (ValueError, TypeError, AttributeError):
            pass
    return new_request_id()


def set_request_id(request_id: str):
    """Setea el id del request actual. Devuelve el token para `reset_request_id`."""
    return _request_id.set(request_id)


def reset_request_id(token) -> None:
    """Restaura el contextvar al valor previo (llamar en finally del middleware)."""
    try:
        _request_id.reset(token)
    except (ValueError, LookupError):
        # El token pertenece a otro contexto (no debería pasar en sync WSGI);
        # degradar limpiando a None en vez de propagar.
        _request_id.set(None)


def get_request_id() -> str | None:
    """Lee el id del request actual, o None fuera de un request."""
    return _request_id.get()
