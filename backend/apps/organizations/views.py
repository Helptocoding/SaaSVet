"""
Views de Organization — PR-4B / ADR p16.

Cambios respecto al modelo anterior (`OrganizationViewSet ModelViewSet`):

1. **Singleton `/api/organizations/me/`** (`OrganizationMeView`): única forma
   semánticamente correcta de acceder/editar la org propia. Sin pk en URL,
   sin exposición del PK secuencial interno.

2. **Legacy `/api/organizations/<pk>/`**: retirado en el orden 6 (deuda D2), tras
   su Sunset RFC 8594 del 17-08-2026. La ruta ya no existe y responde 404.

3. **Router DELETE/POST/list removidos**: dos views explícitas reemplazan al
   ModelViewSet completo. No hay forma de listar/crear/borrar orgs vía API.

Rollback: revertir config/urls.py + este archivo. Sin schema migration.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import generics, serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.core.pagination import StandardResultsPagination
from apps.core.permissions import HybridPermission, make_permission
from apps.core.views import resolve_public_id
from apps.organizations.models import OrganizationClosure, OrganizationConfigEvent, OrganizationSettings
from apps.organizations.services import (
    active_closures, cancel_closure, create_closure, replace_schedule,
)
from apps.organizations.serializers import (
    OrganizationSerializer,
    OrganizationSettingsSerializer,
    OrganizationScheduleItemSerializer,
    OrganizationScheduleBulkSerializer,
    ConfigurationAggregateSerializer,
    OrganizationClosureCreateSerializer,
    OrganizationClosureSerializer,
    OrganizationConfigEventSerializer,
)


class OrganizationMeView(generics.RetrieveUpdateAPIView):
    """Singleton: GET/PATCH sobre la org propia. PK nunca aparece en URL."""
    serializer_class = OrganizationSerializer
    permission_classes = [HybridPermission]
    resource_name = "organization"
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_object(self):
        # request.user.organization viene cargado por TenantJWTAuthentication
        # con select_related — no genera query nueva.
        # Guard: TenantJWTAuthentication permite user.organization=None con
        # warning log. Sin esta guard, get_object() devuelve None y
        # RetrieveUpdateAPIView crash al serializar (TypeError).
        org = self.request.user.organization
        if org is None:
            raise NotFound("Organización no asignada al usuario.")
        return org


class OrganizationSettingsView(generics.RetrieveUpdateAPIView):
    serializer_class = OrganizationSettingsSerializer
    permission_classes = [HybridPermission]
    resource_name = "organization"
    http_method_names = ['get', 'patch']

    def get_object(self):
        org = self.request.user.organization
        if org is None:
            from django.http import Http404
            raise Http404("Usuario sin organizacion asignada.")
        settings, _ = OrganizationSettings.objects.get_or_create(organization=org)
        return settings


class OrganizationScheduleView(generics.GenericAPIView):
    permission_classes = [HybridPermission]
    resource_name = "organization"
    http_method_names = ['get', 'put', 'head', 'options']

    def get_serializer_class(self):
        if self.request.method == 'PUT':
            return OrganizationScheduleBulkSerializer
        return OrganizationScheduleItemSerializer

    def get_queryset(self):
        from .models import OrganizationSchedule as Schedule
        org = self.request.user.organization
        if org is None:
            return Schedule.objects.none()
        from .utils import ensure_schedule_integrity
        return ensure_schedule_integrity(org)

    def get(self, request, *args, **kwargs):
        qs = self.get_queryset()
        serializer = OrganizationScheduleItemSerializer(qs, many=True)
        return Response(serializer.data)

    def put(self, request, *args, **kwargs):
        org = request.user.organization
        if org is None:
            from django.http import Http404
            raise Http404("Usuario sin organizacion asignada.")

        serializer = OrganizationScheduleBulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            fresh = replace_schedule(
                actor=request.user, organization=org, days=serializer.validated_data,
            )
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, 'error_dict') else exc.messages
            raise serializers.ValidationError(detail) from exc
        out = OrganizationScheduleItemSerializer(fresh, many=True)
        return Response(out.data, status=200)


class OrganizationConfigurationView(generics.RetrieveAPIView):
    serializer_class = ConfigurationAggregateSerializer
    permission_classes = [HybridPermission]
    resource_name = "organization"
    http_method_names = ['get', 'head', 'options']

    def get_object(self):
        org = self.request.user.organization
        if org is None:
            from django.http import Http404
            raise Http404("Usuario sin organizacion asignada.")
        from .utils import ensure_schedule_integrity
        settings, _ = OrganizationSettings.objects.get_or_create(organization=org)
        schedule = ensure_schedule_integrity(org)
        return {
            'organization': org,
            'settings': settings,
            'schedule': schedule,
        }


class OrganizationConfigHistoryView(generics.ListAPIView):
    """GET /api/organizations/config-history/ — historial de cambios de la
    configuración (ADR p70 D9), del más reciente al más antiguo, paginado.

    Lo ve quien puede editar la clínica (`organization.update`), solo de su
    propia organización.
    """
    serializer_class = OrganizationConfigEventSerializer
    permission_classes = [make_permission('organization.update')]
    pagination_class = StandardResultsPagination

    def get_queryset(self):
        org = self.request.user.organization
        if org is None:
            raise NotFound("Organización no asignada al usuario.")
        return (
            OrganizationConfigEvent.objects.filter(organization=org)
            .select_related('actor').order_by('-occurred_at', '-pk')
        )


def _require_org(request):
    org = request.user.organization
    if org is None:
        raise NotFound("Organización no asignada al usuario.")
    return org


class OrganizationClosureListCreateView(generics.GenericAPIView):
    """GET/POST /api/organizations/closures/ — cierres excepcionales (ADR p70 D6).

    GET lista los vigentes que no han terminado (desde hoy, día local).
    POST registra uno: no mueve citas; la respuesta dice cuántas hay esos días
    (`affected_appointments`) para avisar al personal. `organization.update`.
    """
    permission_classes = [make_permission('organization.update')]
    serializer_class = OrganizationClosureSerializer

    def get(self, request):
        from apps.core.datetime_utils import org_today_local
        org = _require_org(request)
        closures = (active_closures(org.pk).filter(end_date__gte=org_today_local(org))
                    .select_related('created_by').order_by('start_date', 'pk'))
        return Response(OrganizationClosureSerializer(closures, many=True).data)

    def post(self, request):
        org = _require_org(request)
        data = OrganizationClosureCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        closure, affected = create_closure(
            actor=request.user, organization=org,
            start_date=data.validated_data['start_date'],
            end_date=data.validated_data['end_date'],
            reason=data.validated_data['reason'],
        )
        body = OrganizationClosureSerializer(closure).data
        body['affected_appointments'] = affected
        return Response(body, status=201)


class OrganizationClosureCancelView(generics.GenericAPIView):
    """POST /api/organizations/closures/<public_id>/cancel/ — reabre esos días."""
    permission_classes = [make_permission('organization.update')]
    serializer_class = OrganizationClosureSerializer

    def post(self, request, pk):
        org = _require_org(request)
        closure = resolve_public_id(OrganizationClosure.objects.filter(organization=org), pk)
        return Response(OrganizationClosureSerializer(
            cancel_closure(actor=request.user, closure=closure)).data)
