from rest_framework import status
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.core.pagination import StandardResultsPagination
from apps.core.permissions import HybridPermission
from apps.core.views import TenantQueryMixin, PublicIdLookupMixin, resolve_public_id

from .models import Pet, Owner
from .serializers import PetSerializer, OwnerSerializer


class PetViewSet(PublicIdLookupMixin, TenantQueryMixin, ModelViewSet):
    """
    Pacientes (mascotas). basename='patient' → permisos patient.*
    Soporta ?search=<nombre> y ?owner=<public_id> (combinables). Límite 20 cuando se filtra.
    """
    serializer_class = PetSerializer
    permission_classes = [HybridPermission]

    def get_queryset(self):
        org = self.request.user.organization
        qs = Pet.objects.for_organization(org)
        search = self.request.query_params.get("search", "").strip()
        owner_lookup = self.request.query_params.get("owner", "").strip()
        if search:
            qs = qs.filter(name__icontains=search)
        if owner_lookup:
            # Día 6 Fase 3: resolver Owner por public_id antes del filtro
            owner = resolve_public_id(Owner.objects.for_organization(org), owner_lookup)
            qs = qs.filter(owner=owner)
        if search or owner_lookup:
            qs = qs[:20]
        return qs

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_generic:
            # PR-4B: shape alineado al handler ProtectedError (code + message
            # en lugar del legacy `error`). Status 409 ya correcto.
            return Response(
                {
                    "code": "generic_resource_protected",
                    "message": "No se puede eliminar el paciente genérico del sistema.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        return super().destroy(request, *args, **kwargs)

    def get_serializer_context(self):
        return {'request': self.request}


class OwnerViewSet(PublicIdLookupMixin, TenantQueryMixin, ModelViewSet):
    """
    Propietarios. basename='owner' → permisos owner.*
    Soporta ?search=<nombre>. Límite 20 cuando se filtra.

    P1-2: paginación PageNumber(25) en el listado completo. El path `?search`
    (que alimenta SearchSelect con array plano [:20]) NO se pagina —
    `paginate_queryset` devuelve None para preservar el contrato de dropdown.
    """
    serializer_class = OwnerSerializer
    permission_classes = [HybridPermission]
    pagination_class = StandardResultsPagination

    def get_queryset(self):
        qs = Owner.objects.for_organization(self.request.user.organization)
        search = self.request.query_params.get("search", "").strip()
        is_generic = self.request.query_params.get("is_generic", "").strip()
        if is_generic == "true":
            qs = qs.filter(is_generic=True)
        elif is_generic == "false":
            qs = qs.filter(is_generic=False)
        if search:
            return qs.filter(name__icontains=search)[:20]
        # Owner no declara Meta.ordering → orden de heap. Orden estable para
        # paginación (name + id desempate).
        return qs.order_by("name", "id")

    def paginate_queryset(self, queryset):
        # El path de búsqueda devuelve un array plano [:20] para los dropdowns
        # (SearchSelect). No paginar ahí: un queryset ya sliced rompería el
        # paginador y los consumidores `.then(ps => ps.map(...))` esperan array.
        if self.request.query_params.get("search", "").strip():
            return None
        return super().paginate_queryset(queryset)

    def destroy(self, request, *args, **kwargs):
        # PR-4B D5: guard explícito antes de llegar al PROTECT-bound DB error.
        # El generic owner es el dummy walk-in usado por billing.services para
        # invoices sin cliente registrado. NUNCA debe borrarse. Sin este guard,
        # PROTECT lo bloquearía pero con un mensaje genérico de
        # `resource_has_dependencies` — esto da un mensaje específico y
        # accionable.
        instance = self.get_object()
        if instance.is_generic:
            return Response(
                {
                    "code": "generic_resource_protected",
                    "message": "No se puede eliminar el cliente genérico walk-in del sistema.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(
            organization=self.request.user.organization
        )
