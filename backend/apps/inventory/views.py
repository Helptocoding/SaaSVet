import logging
from uuid import UUID
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from apps.core.pagination import StockMovementCursorPagination
from apps.core.permissions import HybridPermission, make_permission
from apps.core.views import TenantQueryMixin, PublicIdLookupMixin, resolve_public_id
from apps.medical_records.models import MedicalRecord
from apps.medical_records.policies import (
    assert_can_modify_charges,
    can_modify_medical_record_charges,
    log_closed_denied,
    log_ownership_denied,
)

from .models import (
    Product, Presentation, StockLot, StockMovement, StockReceptionReceipt, MedicalRecordProduct,
)
from .services import (
    build_reception_result,
    can_supervise_receptions,
    complete_reception,
    discard_reception,
    get_visible_reception,
    prepare_reception,
    reception_current_balance,
    reception_ledger_since_intent,
    receive_with_identity,
    receptions_visible_to,
    unattributed_reception_entries,
)
from .units import presentation_conversion_factor
from .serializers import (
    ProductSerializer,
    PresentationSerializer,
    PresentationCreateSerializer,
    StockMovementSerializer,
    StockAdjustmentSerializer,
    StockLotSerializer,
    StockReceptionSerializer,
    StockReceptionOperationSerializer,
    ReceptionLedgerEntrySerializer,
    ReceptionDiscardSerializer,
    LotDiscardSerializer,
    LotStatusSerializer,
    MedicalRecordProductSerializer,
)


events_logger = logging.getLogger("medical_records.events")


class ProductListCreateView(TenantQueryMixin, generics.ListCreateAPIView):
    serializer_class = ProductSerializer
    permission_classes = [HybridPermission]
    resource_name = "inventory"

    def get_queryset(self):
        queryset = (
            Product.objects
            .for_organization(self.request.user.organization)
            .prefetch_related('presentations')
        )
        if self.request.query_params.get('active') == 'true':
            queryset = queryset.filter(is_active=True)
        # Filter by category with stock > 0 (for prescription autocomplete)
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category=category)
        stock_gt = self.request.query_params.get('stock__gt')
        if stock_gt is not None:
            try:
                queryset = queryset.filter(
                    presentations__stock__gt=float(stock_gt)
                ).distinct()
            except ValueError:
                pass
        return queryset

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class ProductDetailView(PublicIdLookupMixin, TenantQueryMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ProductSerializer
    permission_classes = [HybridPermission]
    resource_name = "inventory"
    lookup_url_kwarg = 'pk'

    def get_queryset(self):
        return (
            Product.objects
            .for_organization(self.request.user.organization)
            .prefetch_related('presentations')
        )


@api_view(['GET'])
@permission_classes([make_permission("inventory.list")])
def low_stock_products(request):
    """Productos activos con stock_quantity <= min_stock (ADR p31: stock a nivel Product)."""
    products = (
        Product.objects
        .filter(
            organization=request.user.organization,
            is_active=True,
            stock_quantity__lte=F('min_stock'),
        )
        .prefetch_related('presentations')
        .distinct()
    )
    return Response(ProductSerializer(products, many=True).data)


@api_view(['POST'])
@permission_classes([make_permission("inventory.update")])
def adjust_stock(request, pk):
    """Ajuste de stock para la primera presentación de un producto (backward compat)."""
    from django.core.exceptions import ValidationError as DjValidationError
    from .services import apply_stock_movement

    product = resolve_public_id(
        Product.objects.for_organization(request.user.organization).prefetch_related('presentations'),
        pk,
    )

    presentation = product.presentations.first()
    if presentation is None:
        return Response(
            {'error': 'Este producto no tiene presentaciones configuradas.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    serializer = StockAdjustmentSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    movement_type = serializer.validated_data['movement_type']
    quantity = serializer.validated_data['quantity']
    reason = serializer.validated_data.get('reason', '')
    if movement_type == 'adjustment' and not reason:
        reason = f'Ajuste manual a {quantity}'

    try:
        with transaction.atomic():
            locked_pres = Presentation.objects.select_for_update().get(pk=presentation.pk)
            # ADR p31: convertir de unidades de presentación a base_units
            quantity_base = quantity * presentation_conversion_factor(locked_pres)
            apply_stock_movement(
                presentation=locked_pres,
                quantity=quantity_base,
                movement_type=movement_type,
                organization=request.user.organization,
                reason=reason,
                created_by=request.user,
            )
    except DjValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    product.refresh_from_db()
    return Response(ProductSerializer(product).data)


@api_view(['POST'])
@permission_classes([make_permission("inventory.update")])
def adjust_presentation_stock(request, pk):
    """Ajuste de stock para una presentación específica."""
    from django.core.exceptions import ValidationError as DjValidationError
    from .services import apply_stock_movement

    presentation = resolve_public_id(
        Presentation.objects.for_organization(request.user.organization).select_related('product'),
        pk,
    )

    serializer = StockAdjustmentSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    movement_type = serializer.validated_data['movement_type']
    quantity = serializer.validated_data['quantity']
    reason = serializer.validated_data.get('reason', '')
    if movement_type == 'adjustment' and not reason:
        reason = f'Ajuste manual a {quantity}'

    try:
        with transaction.atomic():
            locked_pres = Presentation.objects.select_for_update().get(pk=presentation.pk)
            # ADR p31: convertir de unidades de presentación a base_units
            quantity_base = quantity * presentation_conversion_factor(locked_pres)
            apply_stock_movement(
                presentation=locked_pres,
                quantity=quantity_base,
                movement_type=movement_type,
                organization=request.user.organization,
                reason=reason,
                created_by=request.user,
            )
    except DjValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(PresentationSerializer(presentation).data)


@api_view(['POST'])
@permission_classes([make_permission("inventory.update")])
def receive_presentation_stock(request, pk):
    """Recepción de mercancía multi-lote para una presentación (spec §7, B1).

    POST /api/inventory/presentations/<pk>/receive/
    Body: {supplier_name?, received_at?, lots: [{lot_number, expiry_date?, quantity}]}
    Solo para productos con tracks_lots. Cada lote → StockLot + movimiento 'in'.
    """
    from django.core.exceptions import ValidationError as DjValidationError
    from .services import receive_stock

    presentation = resolve_public_id(
        Presentation.objects.for_organization(request.user.organization).select_related('product'),
        pk,
    )
    if not presentation.product.tracks_lots:
        return Response(
            {'code': 'validation_error',
             'errors': {'product': ['Este producto no usa control de lotes.']}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    serializer = StockReceptionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    operation_id = _reception_operation_id(request)
    try:
        if operation_id is not None:
            operation = receive_with_identity(
                organization=request.user.organization,
                actor=request.user,
                presentation=presentation,
                validated_data=serializer.validated_data,
                operation_id=operation_id,
            )
            return Response(operation.result)
        with transaction.atomic():
            affected = receive_stock(
                presentation=presentation,
                lots=serializer.validated_data['lots'],
                organization=request.user.organization,
                supplier_name=serializer.validated_data.get('supplier_name', ''),
                received_at=serializer.validated_data.get('received_at'),
                created_by=request.user,
            )
            result = build_reception_result(presentation, affected)
    except DjValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(result)


def _reception_operation_id(request):
    raw_operation = request.headers.get('X-Idempotency-Key')
    if raw_operation is None:
        return None
    try:
        return UUID(raw_operation)
    except (ValueError, TypeError, AttributeError):
        raise ValidationError({'operation_id': 'Identificador de operación inválido.'})


def _reception_organization(request):
    organization = request.user.organization
    if organization is None:
        raise PermissionDenied('User has no organization assigned')
    return organization


def _include_other_actors(request):
    scope = request.query_params.get('scope', 'own')
    if scope not in ('own', 'organization'):
        raise ValidationError({'scope': 'Alcance inválido.'})
    if scope == 'organization' and not can_supervise_receptions(request.user):
        raise PermissionDenied()
    return scope == 'organization'


def _serialized_reception_detail(operation, request):
    data = dict(StockReceptionOperationSerializer(
        operation, context={'request': request, 'detail': True},
    ).data)
    data['current_balance'] = reception_current_balance(operation)
    if operation.status == StockReceptionReceipt.STATUS_PENDING:
        ledger = reception_ledger_since_intent(operation)
        data['ledger_since_intent'] = {
            'entries': ReceptionLedgerEntrySerializer(ledger['entries'], many=True).data,
            'truncated': ledger['truncated'],
        }
    return data


@api_view(['POST'])
@permission_classes([make_permission("inventory.update")])
def prepare_presentation_reception(request, pk):
    """Registra la intención de recepción ANTES de tocar stock.

    POST /api/inventory/presentations/<pk>/receptions/ + X-Idempotency-Key: <uuid>
    La ejecución es otra petición (receptions/<id>/complete/): como solo se envía tras
    conocer esta respuesta, una intención perdida o tardía nunca suma stock.
    """
    organization = _reception_organization(request)
    presentation = resolve_public_id(
        Presentation.objects.for_organization(organization).select_related('product'), pk,
    )
    if not presentation.product.tracks_lots:
        return Response(
            {'code': 'validation_error',
             'errors': {'product': ['Este producto no usa control de lotes.']}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    serializer = StockReceptionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    operation_id = _reception_operation_id(request)
    if operation_id is None:
        raise ValidationError({'operation_id': 'Falta el identificador de operación.'})
    _, created = prepare_reception(
        organization=organization,
        actor=request.user,
        presentation=presentation,
        validated_data=serializer.validated_data,
        operation_id=operation_id,
    )
    operation = get_visible_reception(organization, request.user, operation_id)
    return Response(
        _serialized_reception_detail(operation, request),
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@api_view(['GET'])
@permission_classes([make_permission("inventory.update")])
def reception_list(request):
    """Descubre operaciones sin conocer ningún identificador previo.

    GET /api/inventory/receptions/?status=&product=&scope=own|organization&cursor=
    Por defecto, las propias; `scope=organization` exige facultad de supervisión.
    """
    organization = _reception_organization(request)
    include_others = _include_other_actors(request)
    queryset = receptions_visible_to(organization, request.user, include_others=include_others)

    status_filter = request.query_params.get('status')
    if status_filter:
        if status_filter not in dict(StockReceptionReceipt.STATUS_CHOICES):
            raise ValidationError({'status': 'Estado inválido.'})
        queryset = queryset.filter(status=status_filter)
    product_lookup = request.query_params.get('product')
    if product_lookup:
        queryset = queryset.filter(product=resolve_public_id(
            Product.objects.for_organization(organization), product_lookup,
        ))

    queryset = queryset.select_related(
        'actor', 'resolved_by', 'product', 'presentation',
    ).prefetch_related('movements__lot')
    paginator = StockMovementCursorPagination()
    page = paginator.paginate_queryset(queryset, request)
    results = StockReceptionOperationSerializer(
        page, many=True, context={'request': request, 'detail': False},
    ).data
    response = paginator.get_paginated_response(results)
    response.data['can_supervise'] = can_supervise_receptions(request.user)
    return response


@api_view(['GET'])
@permission_classes([make_permission("inventory.update")])
def unattributed_reception_list(request):
    """GET /api/inventory/receptions/unattributed/ — entradas sin identidad de operación."""
    organization = _reception_organization(request)
    queryset = unattributed_reception_entries(
        organization, request.user, include_others=_include_other_actors(request),
    )
    paginator = StockMovementCursorPagination()
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response(ReceptionLedgerEntrySerializer(page, many=True).data)


@api_view(['GET'])
@permission_classes([make_permission("inventory.update")])
def reception_detail(request, operation_id):
    """Evidencia de una operación. Consultar nunca muta ni ejecuta."""
    organization = _reception_organization(request)
    operation = get_visible_reception(organization, request.user, operation_id)
    return Response(_serialized_reception_detail(operation, request))


@api_view(['POST'])
@permission_classes([make_permission("inventory.update")])
def complete_reception_view(request, operation_id):
    """Ejecuta la captura guardada de una intención propia, sin reenviarla."""
    from django.core.exceptions import ValidationError as DjValidationError

    organization = _reception_organization(request)
    try:
        complete_reception(
            organization=organization, actor=request.user, operation_id=operation_id,
        )
    except DjValidationError as e:
        return Response(
            {'code': 'validation_error', 'message': ' '.join(e.messages)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    operation = get_visible_reception(organization, request.user, operation_id)
    return Response(_serialized_reception_detail(operation, request))


@api_view(['POST'])
@permission_classes([make_permission("inventory.update")])
def discard_reception_view(request, operation_id):
    """Cierra una intención sin aplicarla; quedan motivo, autor y fecha."""
    organization = _reception_organization(request)
    serializer = ReceptionDiscardSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    discard_reception(
        organization=organization,
        actor=request.user,
        operation_id=operation_id,
        reason=serializer.validated_data['reason'],
        note=serializer.validated_data.get('note', ''),
    )
    operation = get_visible_reception(organization, request.user, operation_id)
    return Response(_serialized_reception_detail(operation, request))


class ProductLotsView(TenantQueryMixin, generics.ListAPIView):
    """Lotes de un producto (los activos con saldo primero, orden FEFO)."""
    serializer_class = StockLotSerializer
    permission_classes = [HybridPermission]
    resource_name = "inventory"

    def get_queryset(self):
        product = resolve_public_id(
            Product.objects.for_organization(self.request.user.organization),
            self.kwargs['product_pk'],
        )
        qs = StockLot.objects.for_organization(
            self.request.user.organization
        ).filter(product=product).select_related('product')
        if self.request.query_params.get('with_stock') == 'true':
            qs = qs.filter(quantity_on_hand__gt=0)
        return qs


@api_view(['GET'])
@permission_classes([make_permission("inventory.list")])
def lot_alerts(request):
    """Alertas de caducidad (B2c): lotes por vencer en N días + vencidos con saldo.

    GET /api/inventory/lots/alerts/?days=30
    Solo lotes con saldo y estado 'active' (cuarentena/retiro se gestionan aparte).
    """
    from datetime import timedelta
    try:
        days = int(request.query_params.get('days', 30))
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(days, 365))

    org = request.user.organization
    today = timezone.localdate()
    horizon = today + timedelta(days=days)
    base = (
        StockLot.objects.for_organization(org)
        .filter(quantity_on_hand__gt=0, status=StockLot.STATUS_ACTIVE)
        .select_related('product')
    )
    expiring = base.filter(
        expiry_date__isnull=False, expiry_date__gte=today, expiry_date__lte=horizon,
    ).order_by('expiry_date')
    expired = base.filter(expiry_date__lt=today).order_by('expiry_date')

    return Response({
        'days': days,
        'expiring_soon': StockLotSerializer(expiring, many=True).data,
        'expired_with_stock': StockLotSerializer(expired, many=True).data,
    })


@api_view(['POST'])
@permission_classes([make_permission("inventory.update")])
def discard_lot_view(request, pk):
    """Merma/write-off de un lote (B2c). POST /api/inventory/lots/<pk>/discard/"""
    from django.core.exceptions import ValidationError as DjValidationError
    from .services import discard_lot

    lot = resolve_public_id(
        StockLot.objects.for_organization(request.user.organization).select_related('product'),
        pk,
    )
    serializer = LotDiscardSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    reason = serializer.validated_data.get('reason') or 'Descarte de lote'
    try:
        with transaction.atomic():
            discard_lot(
                lot, request.user.organization,
                quantity=serializer.validated_data.get('quantity'),
                reason=reason, created_by=request.user,
            )
    except DjValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    lot.refresh_from_db()
    return Response(StockLotSerializer(lot).data)


@api_view(['POST'])
@permission_classes([make_permission("inventory.update")])
def set_lot_status_view(request, pk):
    """Cambia el estado del lote: active|quarantined|recalled (B2c).
    POST /api/inventory/lots/<pk>/status/"""
    from django.core.exceptions import ValidationError as DjValidationError
    from .services import set_lot_status

    lot = resolve_public_id(
        StockLot.objects.for_organization(request.user.organization).select_related('product'),
        pk,
    )
    serializer = LotStatusSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        with transaction.atomic():
            set_lot_status(
                lot, serializer.validated_data['status'],
                request.user.organization, created_by=request.user,
            )
    except DjValidationError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    lot.refresh_from_db()
    return Response(StockLotSerializer(lot).data)


class StockMovementListView(TenantQueryMixin, generics.ListAPIView):
    serializer_class = StockMovementSerializer
    permission_classes = [HybridPermission]
    # P1-2: ledger append-only de alto volumen (50k+). Cursor en lugar de
    # PageNumber → offset profundo no degrada y los inserts concurrentes no
    # desplazan filas entre páginas. El orden lo fija la paginación
    # (-created_at, -id), no el queryset.
    pagination_class = StockMovementCursorPagination
    resource_name = "inventory"

    def get_queryset(self):
        queryset = (
            StockMovement.objects
            .for_organization(self.request.user.organization)
            .select_related('presentation__product', 'created_by')
        )
        org = self.request.user.organization
        product_lookup = self.request.query_params.get('product')
        if product_lookup:
            # Día 6 Fase 3: resolver Product por public_id antes del filtro
            product = resolve_public_id(Product.objects.for_organization(org), product_lookup)
            queryset = queryset.filter(presentation__product=product)
        presentation_lookup = self.request.query_params.get('presentation')
        if presentation_lookup:
            presentation = resolve_public_id(
                Presentation.objects.for_organization(org), presentation_lookup
            )
            queryset = queryset.filter(presentation=presentation)
        return queryset


@api_view(['GET'])
@permission_classes([make_permission("inventory.list")])
def unit_choices(request):
    """Catálogo cerrado de unidades base válidas."""
    return Response([
        {'value': key, 'label': label}
        for key, label in Presentation.UNIT_CHOICES
    ])


@api_view(['GET'])
@permission_classes([make_permission("inventory.list")])
def presentation_by_barcode(request):
    """Lookup de presentación por código de barras (para POS scanner).

    GET /api/inventory/presentations/barcode/?barcode={code}
    Tenant-scoped. Cross-tenant → 404.
    """
    barcode = request.query_params.get('barcode', '').strip()
    if not barcode:
        return Response({'error': 'Parámetro barcode requerido.'}, status=status.HTTP_400_BAD_REQUEST)

    presentation = (
        Presentation.objects
        .for_organization(request.user.organization)
        .select_related('product')
        .filter(barcode=barcode)
        .first()
    )
    if presentation is None:
        return Response({'error': 'Presentación no encontrada.'}, status=status.HTTP_404_NOT_FOUND)

    return Response(PresentationSerializer(presentation).data)


class PresentationListView(TenantQueryMixin, generics.ListAPIView):
    serializer_class = PresentationSerializer
    permission_classes = [HybridPermission]
    resource_name = "inventory"

    def get_queryset(self):
        qs = Presentation.objects.for_organization(
            self.request.user.organization
        ).filter(product__is_active=True).select_related('product')
        category = self.request.query_params.get('product__category')
        if category:
            qs = qs.filter(product__category=category)
        stock_gt = self.request.query_params.get('stock__gt')
        if stock_gt is not None:
            try:
                qs = qs.filter(stock__gt=float(stock_gt))
            except ValueError:
                pass
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(product__name__icontains=search)
        return qs.order_by('product__name', 'name').select_related('product')


class PresentationCreateView(TenantQueryMixin, generics.CreateAPIView):
    """Add a new presentation variant to an existing product."""
    serializer_class = PresentationCreateSerializer
    permission_classes = [HybridPermission]
    resource_name = "inventory"

    def perform_create(self, serializer):
        from .services import apply_stock_movement
        with transaction.atomic():
            product = resolve_public_id(
                Product.objects.for_organization(self.request.user.organization),
                self.kwargs['product_pk'],
            )
            initial = serializer.validated_data['stock']
            factor = serializer.validated_data.get('conversion_factor', Decimal('1'))
            quantity = (initial * factor).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
            if initial > 0 and product.tracks_lots:
                raise ValidationError({'stock': 'Recibe el stock mediante lotes identificados.'})
            if initial > 0 and (quantity <= 0 or quantity >= Decimal('10000000000')):
                raise ValidationError({'stock': 'Stock fuera de rango en unidades base.'})
            pres = serializer.save(product=product, organization=self.request.user.organization, stock=0)
            if quantity > 0:
                apply_stock_movement(pres, quantity, 'in', self.request.user.organization,
                                     reason='Stock inicial (alta de presentación)', created_by=self.request.user)
                pres.refresh_from_db()


class PresentationDetailView(PublicIdLookupMixin, TenantQueryMixin, generics.RetrieveUpdateDestroyAPIView):
    """Update or delete a specific presentation variant."""
    serializer_class = PresentationCreateSerializer
    permission_classes = [HybridPermission]
    resource_name = "inventory"
    http_method_names = ['get', 'patch', 'delete']
    lookup_url_kwarg = 'pk'

    def get_queryset(self):
        return Presentation.objects.for_organization(
            self.request.user.organization
        ).select_related('product')

    def perform_destroy(self, instance):
        with transaction.atomic():
            pres = Presentation.objects.select_for_update().get(pk=instance.pk)
            if pres.stock > 0:
                raise ValidationError("No se puede eliminar una presentación con stock disponible.")
            if StockMovement.objects.filter(presentation=pres).exists():
                raise ValidationError(
                    "No se puede eliminar: esta presentación tiene movimientos de stock registrados."
                )
            from apps.billing.models import InvoiceItem
            if InvoiceItem.objects.filter(presentation=pres).exists():
                raise ValidationError(
                    "No se puede eliminar: esta presentación está referenciada en facturas."
                )
            if MedicalRecordProduct.objects.filter(presentation=pres).exists():
                raise ValidationError(
                    "No se puede eliminar: esta presentación fue usada en consultas médicas."
                )
            pres.delete()


class MedicalRecordProductListCreateView(TenantQueryMixin, generics.ListCreateAPIView):
    serializer_class = MedicalRecordProductSerializer
    permission_classes = [HybridPermission]
    resource_name = "medicalrecord"

    def initial(self, request, *args, **kwargs):
        if request.method == 'GET':
            self.required_permission = 'medicalrecord.retrieve'
        else:
            self.required_permission = 'medicalrecord.update'
        return super().initial(request, *args, **kwargs)

    def _get_medical_record(self):
        return resolve_public_id(
            MedicalRecord.objects.for_organization(self.request.user.organization),
            self.kwargs['medical_record_pk'],
        )

    def _assert_can_modify(self, medical_record):
        assert_can_modify_charges(self.request.user, medical_record, self.request)

    def get_queryset(self):
        medical_record = self._get_medical_record()
        if medical_record.organization_id != self.request.user.organization_id:
            raise PermissionDenied('No puedes acceder a consultas fuera de tu organización')
        return (
            MedicalRecordProduct.objects
            .filter(medical_record=medical_record)
            .select_related('presentation__product')
        )

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['medical_record'] = self._get_medical_record()
        return ctx

    def perform_create(self, serializer):
        # Fuente única del alta de producto en consulta (crea/incrementa MRP +
        # sincroniza InvoiceItem). Compartida con la materialización de Vacuna (A2).
        from apps.medical_records.services import add_medical_record_product

        with transaction.atomic():
            medical_record = resolve_public_id(
                MedicalRecord.objects.for_organization(self.request.user.organization).select_for_update(),
                self.kwargs['medical_record_pk'],
            )
            self._assert_can_modify(medical_record)
            presentation = serializer.validated_data['presentation']
            quantity = serializer.validated_data['quantity']
            cost_behavior = serializer.validated_data.get('cost_behavior', 'charge')
            lot = serializer.validated_data.get('lot')
            if presentation.organization_id != self.request.user.organization_id:
                raise ValidationError({'presentation': 'Presentación fuera de tu organización'})
            add_medical_record_product(
                medical_record, presentation, quantity, cost_behavior, lot, self.request.user,
            )


class MedicalRecordProductDeleteView(generics.DestroyAPIView):
    permission_classes = [HybridPermission]
    resource_name = "medicalrecord"
    required_permission = 'medicalrecord.update'

    def get_object(self):
        mr = resolve_public_id(
            MedicalRecord.objects.for_organization(self.request.user.organization),
            self.kwargs['medical_record_pk'],
        )
        return get_object_or_404(
            MedicalRecordProduct,
            pk=self.kwargs['pk'],
            medical_record=mr,
        )

    def perform_destroy(self, instance):
        import uuid
        from apps.billing.checkout_services import record_clinical_charge_delta

        with transaction.atomic():
            mr = resolve_public_id(
                MedicalRecord.objects.for_organization(self.request.user.organization).select_for_update(),
                self.kwargs['medical_record_pk'],
            )
            assert_can_modify_charges(self.request.user, mr, self.request)
            locked_pres = Presentation.objects.select_for_update().get(pk=instance.presentation_id)
            fresh_instance = MedicalRecordProduct.objects.select_for_update().get(
                pk=instance.pk,
                medical_record=mr,
            )
            if fresh_instance.cost_behavior == 'charge':
                record_clinical_charge_delta(
                    fresh_instance, delta=-fresh_instance.quantity,
                    user=self.request.user,
                    mutation_key=f'mrp-delete:{fresh_instance.pk}:{uuid.uuid4()}',
                    reason='product_removed',
                )
            fresh_instance.delete(locked_presentation=locked_pres)
