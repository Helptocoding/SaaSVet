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
from django.db import transaction
from django.db.models import Q
from django.core import signing
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.core.permissions import make_permission, NotDemoAccount
from apps.core.views import PublicIdLookupMixin, TenantQueryMixin

from .models import ImportJob, ImportConflict
from .conflict_reports import collect, convert_legacy
from .parsers import ImportParseError, parse_file
from .serializers import ImportJobListSerializer, ImportJobSerializer
from .services import ImportAlreadyCommitted, ImportHasBlockingErrors, commit_job, validate_job

_ALLOWED_ENTITY_TYPES = {
    ImportJob.ENTITY_OWNER_PET,
    ImportJob.ENTITY_INVENTORY,
}
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
    'conflicts': 'import.retrieve',
}


class ImportJobViewSet(
    PublicIdLookupMixin,
    TenantQueryMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    lookup_field = 'public_id'

    def handle_exception(self, exc):
        response = super().handle_exception(exc)
        # El handler compartido conserva el envelope y mensaje existentes. Solo
        # importación publica el código ya declarado por NotDemoAccount; otros
        # PermissionDenied y el cambio de contraseña conservan su contrato.
        if (isinstance(exc, PermissionDenied)
                and exc.get_codes() == NotDemoAccount.code
                and response.status_code == status.HTTP_403_FORBIDDEN):
            response.data['code'] = NotDemoAccount.code
        return response

    def get_queryset(self):
        return ImportJob.objects.for_organization(self.request.user.organization)

    def get_serializer_class(self):
        if self.action == 'list':
            return ImportJobListSerializer
        return ImportJobSerializer

    def get_permissions(self):
        # NotDemoAccount: el importador escribe Owners/Pets reales; en la org demo
        # debe ser inerte (ni el UI muestra la opción) para no contaminar la demo.
        code = _PERMISSION_BY_ACTION.get(self.action, 'import.create')
        return [make_permission(code)(), NotDemoAccount()]

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

    # --- Transición de estado del job: bajo lock, en la misma transacción ---
    #
    # Las tres acciones de abajo comparten un invariante: el estado del job
    # decide si la acción procede, y la acción lo reescribe. Hacer lo primero
    # ANTES de llamar al servicio y lo segundo DESPUÉS deja los dos separados
    # por toda la duración del trabajo, y con ello:
    #
    #   · dos `commit` solapados pasaban ambos el filtro y ejecutaban la
    #     importación entera dos veces — duplicando producto y stock inicial en
    #     las filas sin `internal_code`, que no tienen unicidad en BD que las
    #     atrape (auditoría run-1, reproducido: 2 productos y stock 20 para un
    #     archivo que declaraba 10);
    #   · un `validate` que terminase después de un `commit` devolvía el estado
    #     a VALIDATED y el job volvía a ser confirmable.
    #
    # `_locked_job` cierra ambos: relee la fila con `select_for_update()` y
    # vuelve a comprobar el estado DENTRO de la transacción que escribe. El
    # `atomic` que abre cada servicio queda anidado como savepoint, así que su
    # aislamiento por fila se conserva intacto.
    @staticmethod
    def _already_committed(message='Esta importación ya fue confirmada.'):
        # Se construye por llamada, nunca como atributo de clase: un Response
        # de DRF lleva estado (renderer, contenido renderizado) y compartir una
        # instancia entre peticiones lo corrompe.
        return Response(
            {'code': 'import_already_committed', 'message': message},
            status=status.HTTP_409_CONFLICT,
        )

    def _locked_job(self, job):
        """Relee el job bloqueando su fila. Devuelve None si ya está confirmado."""
        locked = ImportJob.objects.select_for_update().get(pk=job.pk)
        return None if locked.status == ImportJob.STATUS_COMMITTED else locked

    # --- PATCH /api/imports/<public_id>/mapping/ ---
    @action(detail=True, methods=['patch'])
    def mapping(self, request, public_id=None):
        new_mapping = request.data.get('mapping')
        if not isinstance(new_mapping, dict):
            return Response(
                {'code': 'validation_error', 'errors': {'mapping': ['Debe ser un objeto columna→campo.']}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        dedup = request.data.get('dedup_strategy')
        if dedup is not None and dedup not in _VALID_DEDUP:
            return Response(
                {'code': 'validation_error', 'errors': {'dedup_strategy': ['Estrategia inválida.']}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            job = self._locked_job(self.get_object())
            if job is None:
                return self._already_committed(
                    'Esta importación ya fue confirmada; no se puede modificar.'
                )
            job.mapping = new_mapping
            if dedup is not None:
                job.dedup_strategy = dedup
            job.status = ImportJob.STATUS_PENDING
            # El mapping sustituye la revisión; no se sirven páginas del cálculo anterior.
            if job.result:
                job.result = {**job.result, 'conflicts': [], 'conflict_report': {'invalidated': True}}
            ImportConflict.objects.filter(job=job).delete()
            job.save()
        return Response(ImportJobSerializer(job).data)

    # --- POST /api/imports/<public_id>/validate/ : dry-run ---
    @action(detail=True, methods=['post'])
    def validate(self, request, public_id=None):
        with transaction.atomic():
            job = self._locked_job(self.get_object())
            if job is None:
                return self._already_committed()
            job.result = collect(job, lambda: validate_job(job))
            job.status = ImportJob.STATUS_VALIDATED
            job.save()
        return Response(ImportJobSerializer(job).data)

    @action(detail=True, methods=['get'])
    def conflicts(self, request, public_id=None):
        if set(request.query_params) - {'page_size', 'version', 'cursor'}:
            return Response({'code': 'validation_error', 'message': 'Parámetro de paginación inválido.'}, status=400)
        raw_size = request.query_params.get('page_size', '50')
        if len(raw_size) > 3 or not raw_size.isascii() or not raw_size.isdecimal() or not 1 <= int(raw_size) <= 100:
            return Response({'code': 'validation_error', 'message': 'El tamaño de página debe estar entre 1 y 100.'}, status=400)
        size = int(raw_size)
        version = request.query_params.get('version')
        cursor = request.query_params.get('cursor')
        if cursor and not version:
            return Response({'code': 'validation_error', 'message': 'El cursor requiere versión.'}, status=400)
        initial = self.get_object()
        with transaction.atomic():
            job = ImportJob.objects.select_for_update().get(pk=initial.pk)
            result = job.result or {}
            if result.get('conflict_report', {}).get('invalidated'):
                return Response({'code': 'conflict_report_changed', 'message': 'El reporte cambió; actualiza la vista.'}, status=409)
            if not result.get('conflict_report'):
                if not result:
                    return Response({'code': 'conflict_report_unavailable', 'message': 'No hay reporte vigente.'}, status=409)
                result = convert_legacy(job)
                job.result = result
                job.save(update_fields=['result', 'updated_at'])
            meta = result['conflict_report']
            if version and version != meta['version']:
                return Response({'code': 'conflict_report_changed', 'message': 'El reporte cambió; actualiza la vista.'}, status=409)
            query = ImportConflict.objects.filter(job=job)
            if cursor:
                try:
                    data = signing.loads(cursor, salt='imports.conflicts.v1')
                    if (data['job'] != str(job.public_id) or data['version'] != meta['version']
                            or data['size'] != size or type(data['row']) is not int
                            or type(data['ordinal']) is not int or data['row'] < 0 or data['ordinal'] < 1):
                        raise ValueError
                except (signing.BadSignature, KeyError, TypeError, ValueError):
                    return Response({'code': 'invalid_conflict_cursor', 'message': 'Cursor inválido.'}, status=400)
                query = query.filter(Q(row__gt=data['row']) | Q(row=data['row'], ordinal__gt=data['ordinal']))
            entries = list(query.order_by('row', 'ordinal')[:size + 1])
            page = entries[:size]
            next_cursor = None
            if len(entries) > size:
                last = page[-1]
                next_cursor = signing.dumps({'job': str(job.public_id), 'version': meta['version'],
                                             'size': size, 'row': last.row, 'ordinal': last.ordinal},
                                            salt='imports.conflicts.v1')
            return Response({'version': meta['version'], 'total': meta['total'],
                             'available': meta['available'], 'complete': meta['complete'],
                             'next_cursor': next_cursor, 'results': [entry.payload for entry in page]})

    # --- POST /api/imports/<public_id>/commit/ ---
    @action(detail=True, methods=['post'])
    def commit(self, request, public_id=None):
        job = self.get_object()
        # Fase 0: impedir commit con errores bloqueantes pendientes.
        # Warnings y conflicts NO bloquean — solo blocking[].
        prev = job.result or {}
        if len(prev.get('blocking', [])) > 0:
            return Response(
                {'code': 'import_has_blocking_errors',
                 'message': 'Corrige los errores bloqueantes antes de confirmar la importación.',
                 'blocking_count': len(prev['blocking'])},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # El "una sola vez" lo garantiza el servicio bajo lock, no esta vista:
        # es un cambio de estado de dominio y la vista debe quedar delgada.
        # created_by: auditoría del StockMovement inicial (solo inventory lo
        # consume; owner_pet mantiene su comportamiento histórico).
        try:
            commit_job(job, created_by=request.user)
        except ImportAlreadyCommitted:
            return self._already_committed()
        except ImportHasBlockingErrors as exc:
            return Response(
                {'code': 'import_has_blocking_errors',
                 'message': 'Corrige los errores bloqueantes antes de confirmar la importación.',
                 'blocking_count': exc.count}, status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(ImportJobSerializer(job).data)
