import uuid as _uuid_module

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound, PermissionDenied


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
