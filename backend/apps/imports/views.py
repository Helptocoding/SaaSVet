"""
imports/views.py — Endpoints del importador (flujo de 3 fases).

    POST   /api/imports/                       upload + parse → pending
    GET    /api/imports/                       listado (auditoría)
    GET    /api/imports/<public_id>/           detalle
    PATCH  /api/imports/<public_id>/mapping/   set mapping + dedup_strategy
    POST   /api/imports/<public_id>/validate/  dry-run (no escribe) → validated
    POST   /api/imports/<public_id>/commit/    escribe (atómico) → committed

Multi-tenant: queryset siempre for_organization; el commit fuerza organization=org
en cada Owner/Pet (services). Cross-org = 404 vía PublicIdLookupMixin.
Permisos: import.* — v1 solo ADMIN (vía *.*). Upload/commit con throttle scoped.
"""
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.core.permissions import make_permission
from apps.core.views import PublicIdLookupMixin, TenantQueryMixin

from .models import ImportJob
from .parsers import ImportParseError, parse_file
from .serializers import ImportJobListSerializer, ImportJobSerializer
from .services import commit_job, validate_job

_ALLOWED_ENTITY_TYPES = {ImportJob.ENTITY_OWNER_PET}  # v1: solo owner_pet
# v1 solo implementa 'skip'. 'update'/'create_anyway' existen en el modelo para
# Fase B; aceptarlos ahora daría comportamiento skip silencioso → rechazarlos.
_VALID_DEDUP = {ImportJob.DEDUP_SKIP}

_PERMISSION_BY_ACTION = {
    'list': 'import.list',
    'retrieve': 'import.retrieve',
    'create': 'import.create',
    'mapping': 'import.create',
    'validate': 'import.create',
    'commit': 'import.commit',
}


class ImportJobViewSet(
    PublicIdLookupMixin,
    TenantQueryMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    lookup_field = 'public_id'

    def get_queryset(self):
        return ImportJob.objects.for_organization(self.request.user.organization)

    def get_serializer_class(self):
        if self.action == 'list':
            return ImportJobListSerializer
        return ImportJobSerializer

    def get_permissions(self):
        code = _PERMISSION_BY_ACTION.get(self.action, 'import.create')
        return [make_permission(code)()]

    def get_parsers(self):
        # Solo el upload acepta multipart; el resto es JSON.
        if getattr(self, 'action', None) == 'create':
            return [MultiPartParser(), FormParser()]
        return super().get_parsers()

    def get_throttles(self):
        if self.action in ('create', 'commit'):
            throttle = ScopedRateThrottle()
            self.throttle_scope = 'import_upload' if self.action == 'create' else 'import_commit'
            return [throttle]
        return super().get_throttles()

    # --- POST /api/imports/ : upload + parse ---
    def create(self, request, *args, **kwargs):
        entity_type = (request.data.get('entity_type') or '').strip()
        if entity_type not in _ALLOWED_ENTITY_TYPES:
            return Response(
                {'code': 'validation_error',
                 'errors': {'entity_type': ['Tipo de importación no soportado en esta versión.']}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        uploaded = request.FILES.get('file')
        if uploaded is None:
            return Response(
                {'code': 'validation_error', 'errors': {'file': ['Adjunta un archivo CSV o Excel.']}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            columns, rows = parse_file(uploaded)
        except ImportParseError as exc:
            return Response(
                {'code': 'import_parse_error', 'message': str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        job = ImportJob(
            organization=request.user.organization,
            entity_type=entity_type,
            status=ImportJob.STATUS_PENDING,
            original_filename=(getattr(uploaded, 'name', '') or '')[:255],
            source_columns=columns,
            rows=rows,
            mapping={},
            result={},
        )
        job.save()
        return Response(
            ImportJobSerializer(job).data, status=status.HTTP_201_CREATED,
        )

    # --- PATCH /api/imports/<public_id>/mapping/ ---
    @action(detail=True, methods=['patch'])
    def mapping(self, request, public_id=None):
        job = self.get_object()
        if job.status == ImportJob.STATUS_COMMITTED:
            return Response(
                {'code': 'import_already_committed',
                 'message': 'Esta importación ya fue confirmada; no se puede modificar.'},
                status=status.HTTP_409_CONFLICT,
            )
        new_mapping = request.data.get('mapping')
        if not isinstance(new_mapping, dict):
            return Response(
                {'code': 'validation_error', 'errors': {'mapping': ['Debe ser un objeto columna→campo.']}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        job.mapping = new_mapping
        dedup = request.data.get('dedup_strategy')
        if dedup is not None:
            if dedup not in _VALID_DEDUP:
                return Response(
                    {'code': 'validation_error', 'errors': {'dedup_strategy': ['Estrategia inválida.']}},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            job.dedup_strategy = dedup
        job.status = ImportJob.STATUS_PENDING
        job.save()
        return Response(ImportJobSerializer(job).data)

    # --- POST /api/imports/<public_id>/validate/ : dry-run ---
    @action(detail=True, methods=['post'])
    def validate(self, request, public_id=None):
        job = self.get_object()
        if job.status == ImportJob.STATUS_COMMITTED:
            return Response(
                {'code': 'import_already_committed',
                 'message': 'Esta importación ya fue confirmada.'},
                status=status.HTTP_409_CONFLICT,
            )
        result = validate_job(job)
        job.result = result
        job.status = ImportJob.STATUS_VALIDATED
        job.save()
        return Response(ImportJobSerializer(job).data)

    # --- POST /api/imports/<public_id>/commit/ ---
    @action(detail=True, methods=['post'])
    def commit(self, request, public_id=None):
        job = self.get_object()
        if job.status == ImportJob.STATUS_COMMITTED:
            return Response(
                {'code': 'import_already_committed',
                 'message': 'Esta importación ya fue confirmada.'},
                status=status.HTTP_409_CONFLICT,
            )
        result = commit_job(job)
        job.result = result
        job.status = ImportJob.STATUS_COMMITTED
        job.save()
        return Response(ImportJobSerializer(job).data)
