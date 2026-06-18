import json
import logging

from apps.core.request_context import get_request_id

_BASE_RECORD_KEYS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)))


class RequestIDLogFilter(logging.Filter):
    """
    Inyecta `request_id` en cada LogRecord (P1-5 Fase A).

    Lo lee del contextvar que setea RequestIDMiddleware. Fuera de un request
    (management commands, arranque) queda en '-'. Se adjunta a TODOS los
    handlers para que ningún formatter que referencie {request_id} levante
    KeyError, y para que el id aparezca tanto en los logs de texto como en los
    JSON estructurados (RBAC).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id() or "-"
        return True


class RBACStructuredFormatter(logging.Formatter):
    """
    Formatter para eventos RBAC — emite una línea JSON por evento.
    Incluye los campos extra pasados via logger.warning("EVENT", extra={...}).
    Compatible con Datadog, ELK, y cualquier agregador que ingeste JSON por línea.
    """

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "event": record.getMessage(),
            "level": record.levelname,
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
        }
        for key, val in vars(record).items():
            if key not in _BASE_RECORD_KEYS and not key.startswith("_"):
                data[key] = val
        return json.dumps(data, default=str)
