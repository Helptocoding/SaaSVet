import logging
import uuid as _uuid_module

from django.conf import settings
from django.db import connections
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_safe
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.core.services import send_support_report

logger = logging.getLogger(__name__)


class TenantQueryMixin:
    """
    Mixin que garantiza que el usuario tiene organización antes de procesar la request.
    Agregar como primer mixin en todas las CBVs que accedan a datos de tenant.
    """

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not request.user.organization:
            raise PermissionDenied("User has no organization assigned")


def _resolve_or_404(queryset, lookup):
    """
    Día 6 ADR p18: helper privado compartido por PublicIdLookupMixin y
    resolve_public_id para evitar divergencia. Sin API pública nueva — esto
    es solo deduplicación interna.

    Lógica:
      - UUID válido → queryset.get(public_id=uuid)
      - String numérico + ALLOW_LEGACY_ID_LOOKUP=True → fallback PK entero
        (DEPRECATED: remove after 2026-06-19 — see Issue #18 / ADR p18)
      - Otro string → NotFound (404)
    """
    try:
        uuid_val = _uuid_module.UUID(str(lookup))
        return queryset.get(public_id=uuid_val)
    except (ValueError, TypeError):
        # DEPRECATED branch: remove after 2026-06-19 (Día 6 cleanup ticket)
        if str(lookup).isdigit() and getattr(settings, 'ALLOW_LEGACY_ID_LOOKUP', False):
            return get_object_or_404(queryset, pk=lookup)
        raise NotFound()
    except queryset.model.DoesNotExist:
        raise NotFound()


class PublicIdLookupMixin:
    """
    Mixin para ViewSets y CBVs que usan public_id (UUID) como lookup en URLs.

    Comportamiento:
      - UUID válido → busca por public_id dentro del queryset del tenant
      - String numérico + ALLOW_LEGACY_ID_LOOKUP=True → fallback a pk entero (transición)
        DEPRECATED: remove after 2026-06-19 — see Issue #18 / ADR p18
      - Cualquier otro string → 404 inmediato (sin fallback)

    Para ViewSets (router): set lookup_field = 'public_id', el router genera
      el kwarg `public_id` automáticamente.

    Para CBVs con <str:pk> en la URL: set lookup_url_kwarg = 'pk' en la view
      para que el mixin lea kwargs['pk'] en lugar de kwargs['public_id'].

    Desactivar el fallback en Railway cuando el frontend esté actualizado:
      ALLOW_LEGACY_ID_LOOKUP=False (sin deploy de código)
    """
    lookup_field = 'public_id'

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        url_kwarg = getattr(self, 'lookup_url_kwarg', None) or self.lookup_field
        lookup = self.kwargs.get(url_kwarg, '')
        obj = _resolve_or_404(queryset, lookup)
        self.check_object_permissions(self.request, obj)
        return obj


def resolve_public_id(queryset, lookup):
    """
    Helper para FBVs: resuelve un objeto por public_id (UUID) con fallback a pk entero.

    Uso en FBVs que reciben pk desde URL kwargs:
        obj = resolve_public_id(Model.objects.for_organization(org), pk)

    Comportamiento:
      - UUID válido → busca por public_id en el queryset
      - String numérico + ALLOW_LEGACY_ID_LOOKUP → fallback a pk entero
        DEPRECATED: remove after 2026-06-19 — see Issue #18 / ADR p18
      - Otro string → NotFound (404)
    """
    return _resolve_or_404(queryset, lookup)


# ---------------------------------------------------------------------------
# Health endpoints (Capa 0 — DEPLOY_VPS_PLAN.md)
#
# Plain Django views (no DRF) for two reasons:
#   1. Bypass DEFAULT_PERMISSION_CLASSES (IsAuthenticated + MustChangePasswordGate)
#      without per-view AllowAny boilerplate.
#   2. Lower overhead — docker healthcheck hits these every 30s.
#
# Both are exempted from CSRF (GET only; no state mutation). They DO honor
# ALLOWED_HOSTS — Docker compose healthcheck uses Host: localhost, so
# `localhost` MUST be present in ALLOWED_HOSTS in production .env.
# ---------------------------------------------------------------------------

@csrf_exempt
@require_safe
def healthz(request):
    """Liveness probe — process is up. Never touches DB."""
    return JsonResponse({"status": "ok"})


@csrf_exempt
@require_safe
def readyz(request):
    """Readiness probe — DB reachable. 503 if not."""
    try:
        connections['default'].cursor().execute('SELECT 1')
    except OperationalError:
        return JsonResponse({"status": "db_down"}, status=503)
    return JsonResponse({"status": "ready"})


@csrf_exempt
@require_safe
def version(request):
    """
    Build/version probe (P1-5 Fase A — A5).

    Responde qué está corriendo AHORA: commit y environment. Sirve para que,
    cuando una clínica reporte un error, sepamos exactamente qué versión estaba
    desplegada (correlaciona con el `release` tag de Sentry).

    Público (sin auth) y barato como healthz: solo lee settings, no toca DB.
    No expone secretos — solo el SHA del deploy y el environment.
    """
    return JsonResponse({
        "version": getattr(settings, "APP_VERSION", "dev"),
        "commit": getattr(settings, "GIT_SHA", "") or None,
        "environment": getattr(settings, "ENVIRONMENT", "dev"),
    })


# ---------------------------------------------------------------------------
# Reporte de soporte → Discord. El efecto externo (armado del embed + POST) vive
# en apps/core/services.send_support_report; la view solo valida input y delega
# (boundary: efectos en services, views delgadas). Los fallos del envío se
# levantan como excepciones DRF → custom_exception_handler arma {code,message}.
# ---------------------------------------------------------------------------
_MAX_SUPPORT_IMAGE_BYTES = 5 * 1024 * 1024    # 5MB — validación de input (400)


class SupportMessageThrottle(UserRateThrottle):
    scope = 'support_message'


class SupportMessageView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [SupportMessageThrottle]

    def post(self, request):
        message = request.data.get("message", "")
        image = request.FILES.get("image")

        if not message or not message.strip():
            raise ValidationError({"message": ["Este campo es requerido."]})

        if image:
            if image.size > _MAX_SUPPORT_IMAGE_BYTES:
                raise ValidationError({"image": ["La imagen no debe superar 5MB."]})
            if not image.content_type or not image.content_type.startswith("image/"):
                raise ValidationError({"image": ["El archivo debe ser una imagen."]})

        send_support_report(
            user=request.user,
            message=message,
            image=image,
            page_url=request.data.get("page_url", "N/A"),
            timestamp=request.data.get("timestamp", ""),
        )
        return Response({"ok": True})
