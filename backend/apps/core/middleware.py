import logging
from django.http import HttpResponseForbidden

from apps.core.models import clear_tenant_context, set_current_user
from apps.core.request_context import (
    coerce_request_id,
    reset_request_id,
    set_request_id,
)

logger = logging.getLogger(__name__)


class RequestIDMiddleware:
    """
    Correlación end-to-end (P1-5 Fase A).

    Por cada request:
      1. Lee `X-Request-ID` entrante (lo inyecta el frontend, ver api/client.js).
      2. Si falta o es inválido, genera un uuid4 (coerce_request_id lo blinda
         contra log injection).
      3. Lo expone en `request.request_id`, en el contextvar (logs + exception
         handler) y como tag de Sentry.
      4. Lo devuelve en el header `X-Request-ID` de la respuesta para que el
         usuario/soporte pueda citarlo.

    Va PRIMERO en MIDDLEWARE (outermost) para que el id exista durante todo el
    ciclo, incluido el manejo de excepciones de las capas internas.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = coerce_request_id(request.META.get("HTTP_X_REQUEST_ID"))
        request.request_id = request_id
        token = set_request_id(request_id)
        self._tag_sentry(request_id)
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = request_id
            return response
        finally:
            reset_request_id(token)

    @staticmethod
    def _tag_sentry(request_id):
        # set_tag es no-op si Sentry no está inicializado (DSN vacío en dev).
        # Envuelto por defensa: la observabilidad nunca debe tumbar el request.
        try:
            import sentry_sdk

            sentry_sdk.set_tag("request_id", request_id)
        except Exception:  # pragma: no cover - defensivo
            pass


class TenantMiddleware:
    """
    Gestión del contexto de usuario para audit trail (created_by / updated_by).

    Para requests JWT (DRF): TenantJWTAuthentication setea set_current_user()
    después de validar el token. Este middleware lo hace como fallback para
    session auth (admin panel).

    Cleanup garantizado en finally.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            if request.user.is_authenticated:
                # Sesiones Django (incluido admin): mismo gate que JWT previo.
                # El operador de plataforma no tiene organization asignada.
                if (request.user.organization_id and not
                        request.user.organization.is_active):
                    return HttpResponseForbidden('Organización desactivada.')
                set_current_user(request.user)
            else:
                set_current_user(None)

            return self.get_response(request)

        finally:
            clear_tenant_context()
