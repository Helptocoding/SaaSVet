import json
import logging
import uuid as _uuid_module

import requests
from django.conf import settings
from django.db import connections
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_safe
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

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
# Reporte de soporte → Discord (webhook server-side).
# ---------------------------------------------------------------------------
_SUPPORT_HTTP_TIMEOUT = 10                    # s — cap del bloqueo síncrono del worker
_MAX_SUPPORT_IMAGE_BYTES = 5 * 1024 * 1024    # 5MB
_DISCORD_DESC_MAX = 4096                       # límite de embed.description de Discord
_DISCORD_FIELD_MAX = 1024                      # límite de embed field value de Discord


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
            return Response(
                {"code": "validation_error", "errors": {"message": ["Este campo es requerido."]}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        webhook_url = getattr(settings, 'DISCORD_WEBHOOK_URL', '')
        if not webhook_url:
            logger.error("SUPPORT_WEBHOOK_NOT_CONFIGURED")
            return Response(
                {"code": "service_unavailable", "message": "El soporte no está disponible en este momento."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if image:
            if image.size > _MAX_SUPPORT_IMAGE_BYTES:
                return Response(
                    {"code": "validation_error", "errors": {"image": ["La imagen no debe superar 5MB."]}},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not image.content_type or not image.content_type.startswith("image/"):
                return Response(
                    {"code": "validation_error", "errors": {"image": ["El archivo debe ser una imagen."]}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        user = request.user
        user_name = f"{user.first_name or ''} {user.last_name or ''} (@{user.username})".strip()
        org_name = getattr(user.organization, 'name', 'N/A') if user.organization else 'N/A'

        embed = {
            "title": "🚀 Nuevo reporte de problema",
            "description": message.strip()[:_DISCORD_DESC_MAX],
            "color": 16711680,
            "fields": [
                {"name": "👤 Usuario", "value": user_name[:_DISCORD_FIELD_MAX], "inline": True},
                {"name": "🏢 Organización", "value": org_name[:_DISCORD_FIELD_MAX], "inline": True},
                {"name": "📍 Página", "value": request.data.get("page_url", "N/A")[:_DISCORD_FIELD_MAX], "inline": False},
            ],
            "footer": {"text": "SaaSly — Intelligent Diagnostics"},
            "timestamp": request.data.get("timestamp", ""),
        }

        if image:
            embed["image"] = {"url": f"attachment://{image.name}"}

        payload = {"embeds": [embed]}

        # Llamada síncrona: bloquea el worker hasta _SUPPORT_HTTP_TIMEOUT s. Aceptable
        # al volumen de este endpoint (throttle 10/h por usuario). Si escala, mover a
        # una cola asíncrona — el proyecto no tiene task queue hoy (trade-off consciente).
        try:
            if image:
                image.seek(0)
                resp = requests.post(
                    webhook_url,
                    data={"payload_json": json.dumps(payload)},
                    files={"file": (image.name, image.read(), image.content_type)},
                    timeout=_SUPPORT_HTTP_TIMEOUT,
                )
            else:
                resp = requests.post(
                    webhook_url,
                    json=payload,
                    timeout=_SUPPORT_HTTP_TIMEOUT,
                )

            if resp.status_code == 204 or 200 <= resp.status_code < 300:
                logger.info(
                    "SUPPORT_MESSAGE_SENT",
                    extra={"user_id": user.pk, "org_id": user.organization_id},
                )
                return Response({"ok": True})
            else:
                logger.error(
                    "SUPPORT_WEBHOOK_FAILED",
                    extra={"status": resp.status_code, "body": resp.text[:500]},
                )
                return Response(
                    {"code": "service_error", "message": "No se pudo enviar el reporte. Intenta más tarde."},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
        except requests.Timeout:
            logger.error("SUPPORT_WEBHOOK_TIMEOUT")
            return Response(
                {"code": "service_error", "message": "No se pudo enviar el reporte. Intenta más tarde."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except requests.RequestException as e:
            logger.error("SUPPORT_WEBHOOK_ERROR", extra={"error": str(e)[:200]})
            return Response(
                {"code": "service_error", "message": "No se pudo enviar el reporte. Intenta más tarde."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
