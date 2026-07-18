import re

from django.core.cache import caches
from rest_framework.throttling import (
    AnonRateThrottle,
    SimpleRateThrottle,
    UserRateThrottle,
)


class ServiceAwareUserRateThrottle(UserRateThrottle):
    """UserRateThrottle global con exención para service accounts (É-F1, R9).

    El user AGENT (ADR p51) consume la API vía loopback para TODAS las
    conversaciones de su organización: el rate global de 500/h lo agotaría
    en horas pico y fallaría en cascada sus tools. Su límite operativo real
    es el presupuesto del Policy Engine (turnos LLM + tools por turno,
    spec §2.6), no el throttle HTTP.

    Los usuarios humanos (is_service_account=False) conservan exactamente
    el comportamiento previo — test de no-regresión en
    apps/core/tests/test_service_account_throttle.py.
    """

    def allow_request(self, request, view):
        user = getattr(request, 'user', None)
        if (
            user is not None
            and user.is_authenticated
            and getattr(user, 'is_service_account', False)
        ):
            return True
        return super().allow_request(request, view)


class ExtendedRateThrottle(SimpleRateThrottle):
    """
    Extiende parse_rate para soportar ventanas explícitas como:
    - 5/15min
    - 5/15m
    - 10/2h

    Mantiene compatibilidad con formatos nativos DRF (5/min, 100/hour, etc.).
    """

    _WINDOW_RE = re.compile(r"^(?P<num>\d+)\s*/\s*(?P<dur>\d+)\s*(?P<unit>[a-zA-Z]+)$")

    @staticmethod
    def _unit_to_seconds(unit: str) -> int:
        unit = unit.strip().lower()
        if unit.startswith('s'):
            return 1
        if unit.startswith('m'):
            return 60
        if unit.startswith('h'):
            return 3600
        if unit.startswith('d'):
            return 86400
        raise ValueError(f"Unidad de throttle no soportada: {unit}")

    def parse_rate(self, rate):
        if rate is None:
            return (None, None)

        if isinstance(rate, str):
            m = self._WINDOW_RE.match(rate.strip())
            if m:
                num_requests = int(m.group('num'))
                duration = int(m.group('dur')) * self._unit_to_seconds(m.group('unit'))
                return (num_requests, duration)

        return super().parse_rate(rate)


class LoginRateThrottle(ExtendedRateThrottle, AnonRateThrottle):
    """Limita intentos de login por IP. Tasa en DEFAULT_THROTTLE_RATES['login'].

    Usa la cache `throttle_login` (IGNORE_EXCEPTIONS=False, P1-1/ADR p41): si
    Redis está caído el login FALLA CERRADO en vez de abrir una ventana de
    brute-force sin límite. El resto de la API usa la cache `default`
    (fail-open). Resuelto vía property para respetar @override_settings en tests.
    """
    scope = 'login'

    @property
    def cache(self):
        return caches['throttle_login']


class LoginUserRateThrottle(ExtendedRateThrottle):
    """
    Limita intentos de login por IP+username combinados.
    Si el body no tiene username, usa solo IP (no ignorar el request).
    Tasa en DEFAULT_THROTTLE_RATES['login_by_user'].

    Fail-closed sobre la cache `throttle_login` — ver LoginRateThrottle.
    """
    scope = 'login_by_user'

    @property
    def cache(self):
        return caches['throttle_login']

    def get_cache_key(self, request, view):
        ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
        ip = ip.split(',')[0].strip()
        username = (request.data or {}).get('username', '').strip().lower()

        if not username:
            # Sin username → throttle solo por IP (no ignorar el request)
            return self.cache_format % {'scope': self.scope, 'ident': f'ip_{ip}'}

        return self.cache_format % {'scope': self.scope, 'ident': f'{ip}_{username}'}
