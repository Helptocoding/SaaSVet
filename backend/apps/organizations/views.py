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
from django.db import transaction
from rest_framework import generics
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.core.permissions import HybridPermission
from apps.organizations.models import Organization, OrganizationSettings
from apps.organizations.serializers import (
    OrganizationSerializer,
    OrganizationSettingsSerializer,
    OrganizationScheduleItemSerializer,
    OrganizationScheduleBulkSerializer,
    ConfigurationAggregateSerializer,
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

        from .models import OrganizationSchedule as Schedule
        from django.db import transaction
        with transaction.atomic():
            current = list(
                Schedule.objects.filter(organization=org).select_for_update()
            )
            existing = {s.weekday: s for s in current}
            for item in serializer.validated_data:
                wd = item['weekday']
                if wd in existing:
                    for attr, value in item.items():
                        setattr(existing[wd], attr, value)
                    existing[wd].save()
                else:
                    Schedule.objects.create(organization=org, **item)

        fresh = Schedule.objects.filter(organization=org).order_by('weekday')
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
