from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from decimal import Decimal

from django.core.exceptions import ValidationError as DjValidationError
from django.db import transaction
from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date

from apps.core.datetime_utils import filter_by_local_day, filter_by_local_range
from apps.core.filters import StableOrderingFilter
from apps.core.pagination import StandardResultsPagination
from apps.core.permissions import HybridPermission, make_permission
from apps.core.views import TenantQueryMixin, PublicIdLookupMixin, resolve_public_id

from .models import (
    Service, Invoice, Checkout, CheckoutDispute, CheckoutItem, CheckoutEstimate,
    ClinicalChargeEntry, CollectionCase,
)
from .serializers import (
    ServiceSerializer, InvoiceSerializer, CreditNoteSerializer,
    CheckoutSerializer, CheckoutDisputeSerializer, CheckoutItemSerializer,
    CheckoutEstimateSerializer, CheckoutPostCommandSerializer,
    PrescriptionDispenseCommandSerializer, CheckoutItemMutationSerializer,
)
from .permissions import CanPayInvoice

VALID_INVOICE_TYPES = {choice[0] for choice in Invoice.INVOICE_TYPE_CHOICES}
VALID_INVOICE_STATUSES = {choice[0] for choice in Invoice.STATUS_CHOICES}


def _internal_pk(value, field_name='id'):
    """Parsea IDs internos usados solo como hijos de un recurso público.

    Las rutas permanecen como ``<str:...>`` para no declarar PK enteros en la
    superficie pública; el modelo interno sigue usando su PK relacional.
    """
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValidationError({field_name: 'Identificador inválido.'})
    if parsed < 1:
        raise ValidationError({field_name: 'Identificador inválido.'})
    return parsed


class PrescriptionRequired(APIException):
    """ADR p26: falta atestación de receta para un producto requires_prescription.
    `default_code` propaga a `{code: 'prescription_required'}` vía el handler global."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = 'prescription_required'
    default_detail = 'Se requiere atestación de receta para este producto.'


class BillingOrganizationMixin(TenantQueryMixin):
    """Garantiza que ninguna vista de facturación retorne datos de otra organización."""


class CheckoutListView(BillingOrganizationMixin, generics.ListAPIView):
    serializer_class = CheckoutSerializer
    permission_classes = [HybridPermission]
    resource_name = 'invoice'

    def get_queryset(self):
        qs = Checkout.objects.for_organization(self.request.user.organization).select_related(
            'organization__settings', 'owner', 'customer', 'pet', 'medical_record',
        ).prefetch_related(
            'items__service', 'items__presentation__product', 'items__lot',
            'items__rx_attestations', 'items__clinical_charge_snapshot',
            'items__source_invoice_item', 'prescription_selections', 'disputes',
        )
        kind = self.request.query_params.get('kind')
        if kind:
            qs = qs.filter(kind=kind)
        lifecycle = self.request.query_params.get('lifecycle', 'open')
        if lifecycle:
            qs = qs.filter(lifecycle=lifecycle)
        return qs.order_by('-created_at')


class CheckoutDetailView(PublicIdLookupMixin, BillingOrganizationMixin, generics.RetrieveAPIView):
    serializer_class = CheckoutSerializer
    permission_classes = [HybridPermission]
    resource_name = 'invoice'
    lookup_url_kwarg = 'pk'

    def get_queryset(self):
        return Checkout.objects.for_organization(self.request.user.organization).select_related(
            'organization__settings', 'customer', 'pet', 'medical_record',
        ).prefetch_related(
            'items__service', 'items__presentation__product', 'items__lot',
            'items__rx_attestations', 'items__clinical_charge_snapshot',
            'items__source_invoice_item',
            'medical_record__prescription', 'prescription_selections', 'disputes',
        )


class CheckoutDisputeListView(BillingOrganizationMixin, generics.ListAPIView):
    serializer_class = CheckoutDisputeSerializer
    permission_classes = [make_permission('invoice.list')]

    def get_queryset(self):
        qs = CheckoutDispute.objects.for_organization(
            self.request.user.organization,
        ).select_related('checkout', 'owner', 'opened_by', 'resolved_by', 'invoice')
        dispute_status = self.request.query_params.get('status', 'open')
        if dispute_status:
            qs = qs.filter(status=dispute_status)
        return qs.order_by('review_due_at', 'pk')


@api_view(['POST'])
@permission_classes([make_permission('invoice.create')])
def create_direct_sale_checkout(request):
    from apps.patients.models import Owner, Pet
    from .checkout_services import create_direct_sale_checkout as command
    customer = resolve_public_id(
        Owner.objects.for_organization(request.user.organization),
        request.data.get('owner'),
    )
    pet = None
    if request.data.get('pet'):
        pet = resolve_public_id(
            Pet.objects.for_organization(request.user.organization), request.data['pet'],
        )
    checkout = command(
        organization=request.user.organization, customer=customer, pet=pet,
        user=request.user, notes=request.data.get('notes', ''),
    )
    return Response(CheckoutSerializer(checkout, context={'request': request}).data, status=201)


@api_view(['POST'])
@permission_classes([make_permission('invoice.create')])
def create_checkout_item(request, pk):
    from apps.inventory.models import Presentation, StockLot
    from apps.core.permissions import user_has_permission
    from .checkout_services import add_checkout_item
    checkout = resolve_public_id(Checkout.objects.for_organization(request.user.organization), pk)
    service = presentation = lot = None
    if request.data.get('service'):
        service = get_object_or_404(Service, pk=request.data['service'], organization=request.user.organization)
    if request.data.get('presentation'):
        presentation = get_object_or_404(
            Presentation.objects.select_related('product'),
            pk=request.data['presentation'], organization=request.user.organization,
        )
    if request.data.get('lot'):
        lot = get_object_or_404(StockLot, pk=request.data['lot'], organization=request.user.organization)
    if presentation and presentation.product.requires_prescription and not user_has_permission(request.user, 'billing.rx_dispense'):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied('No tienes permiso para dispensar productos con receta.')
    try:
        item = add_checkout_item(
            checkout, request.user, service=service, presentation=presentation,
            quantity=request.data.get('quantity', 1), lot=lot,
            discount_type=request.data.get('discount_type'),
            discount_value=request.data.get('discount_value', 0),
            rx_attested=request.data.get('rx_attested', False),
            prescriber_name=request.data.get('prescriber_name', ''),
            prescription_folio=request.data.get('prescription_folio', ''),
            expected_version=request.data.get('expected_version'),
        )
    except DjValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
    return Response(CheckoutItemSerializer(item, context={'request': request}).data, status=201)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([make_permission('invoice.create')])
def checkout_item_detail(request, pk, item_pk):
    from .checkout_services import delete_checkout_item, update_checkout_item
    checkout = resolve_public_id(Checkout.objects.for_organization(request.user.organization), pk)
    item = get_object_or_404(CheckoutItem, pk=_internal_pk(item_pk, 'item_pk'), checkout=checkout)
    if request.method == 'GET':
        return Response(CheckoutItemSerializer(item, context={'request': request}).data)
    command = CheckoutItemMutationSerializer(data=request.data)
    command.is_valid(raise_exception=True)
    try:
        if request.method == 'DELETE':
            delete_checkout_item(
                item, request.user,
                expected_version=command.validated_data['expected_version'],
            )
            return Response(status=204)
        item = update_checkout_item(
            item, request.user, quantity=command.validated_data.get('quantity'),
            expected_version=command.validated_data['expected_version'],
        )
    except DjValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
    return Response(CheckoutItemSerializer(item, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([make_permission('billing.rx_dispense')])
def attest_checkout_item_external_prescription(request, pk, item_pk):
    from .checkout_services import attest_external_prescription

    checkout = resolve_public_id(
        Checkout.objects.for_organization(request.user.organization), pk,
    )
    item = get_object_or_404(
        CheckoutItem.all_objects, pk=_internal_pk(item_pk, 'item_pk'), checkout=checkout, is_active=True,
    )
    key = request.headers.get('X-Idempotency-Key') or request.data.get('idempotency_key')
    try:
        attestation = attest_external_prescription(
            item, request.user,
            prescriber_name=request.data.get('prescriber_name', ''),
            prescription_folio=request.data.get('prescription_folio', ''),
            notes=request.data.get('notes', ''),
            correction_reason=request.data.get('correction_reason', ''),
            expected_version=request.data.get('expected_version'),
            idempotency_key=key,
        )
    except DjValidationError as exc:
        raise ValidationError(
            exc.message_dict if hasattr(exc, 'message_dict') else exc.messages,
        )
    return Response({
        'id': str(attestation.public_id),
        'checkout_item': attestation.checkout_item_id,
        'regulatory_revision': attestation.regulatory_revision,
        'attested_at': attestation.attested_at,
        'supersedes': (
            str(attestation.supersedes_attestation.public_id)
            if attestation.supersedes_attestation_id else None
        ),
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([make_permission('billing.rx_dispense')])
def create_prescription_supplement_view(request, pk):
    from apps.medical_records.models import MedicalRecord
    from .checkout_services import create_prescription_supplement

    medical_record = resolve_public_id(
        MedicalRecord.objects.for_organization(request.user.organization), pk,
    )
    key = request.headers.get('X-Idempotency-Key') or request.data.get('idempotency_key')
    try:
        checkout = create_prescription_supplement(
            medical_record, request.user, idempotency_key=key,
        )
    except DjValidationError as exc:
        raise ValidationError(
            exc.message_dict if hasattr(exc, 'message_dict') else exc.messages,
        )
    return Response(
        CheckoutSerializer(checkout, context={'request': request}).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
@permission_classes([make_permission('checkout.dispute.open')])
def open_checkout_dispute_view(request, pk):
    from apps.users.models import User
    from .checkout_services import open_checkout_dispute
    checkout = resolve_public_id(Checkout.objects.for_organization(request.user.organization), pk)
    owner = get_object_or_404(
        User, pk=request.data.get('owner'), organization=request.user.organization,
    )
    key = request.headers.get('X-Idempotency-Key') or request.data.get('idempotency_key')
    try:
        dispute = open_checkout_dispute(
            checkout, request.user, item_ids=request.data.get('item_ids') or [],
            statement=request.data.get('statement', ''), owner=owner,
            review_due_at=request.data.get('review_due_at'),
            evidence=request.data.get('evidence') or {},
            expected_version=request.data.get('expected_version'),
            idempotency_key=key,
        )
    except DjValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
    return Response(CheckoutDisputeSerializer(dispute).data, status=201)


@api_view(['POST'])
@permission_classes([make_permission('checkout.dispute.resolve')])
def resolve_checkout_dispute_view(request, pk):
    from .checkout_services import resolve_checkout_dispute
    dispute = resolve_public_id(
        CheckoutDispute.objects.for_organization(request.user.organization), pk,
    )
    key = request.headers.get('X-Idempotency-Key') or request.data.get('idempotency_key')
    try:
        dispute = resolve_checkout_dispute(
            dispute, request.user, resolution=request.data.get('resolution'),
            reason=request.data.get('reason', ''),
            resolution_evidence=request.data.get('resolution_evidence') or {},
            adjustments=request.data.get('adjustments') or [],
            due_at=request.data.get('due_at'),
            obligation_evidence=request.data.get('obligation_evidence') or {},
            expected_version=request.data.get('expected_version'),
            idempotency_key=key,
        )
    except DjValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
    return Response(CheckoutDisputeSerializer(dispute).data)


@api_view(['POST'])
@permission_classes([make_permission('collection.resolve')])
def resolve_collection_case_view(request, pk):
    from .checkout_services import resolve_collection_case

    case = resolve_public_id(
        CollectionCase.objects.for_organization(request.user.organization), pk,
    )
    key = request.headers.get('X-Idempotency-Key') or request.data.get('idempotency_key')
    try:
        case = resolve_collection_case(
            case, request.user, resolution=request.data.get('resolution'),
            reason=request.data.get('reason', ''),
            evidence=request.data.get('evidence') or {}, idempotency_key=key,
        )
    except DjValidationError as exc:
        raise ValidationError(
            exc.message_dict if hasattr(exc, 'message_dict') else exc.messages,
        )
    return Response({
        'id': str(case.public_id), 'invoice': str(case.invoice.public_id),
        'status': case.status, 'resolution': case.resolution,
        'resolved_at': case.resolved_at,
    })


@api_view(['POST'])
@permission_classes([make_permission('invoice.replace_adjust')])
def adjust_replacement_exposure_view(request, pk):
    from .checkout_services import adjust_replacement_exposure
    checkout = resolve_public_id(Checkout.objects.for_organization(request.user.organization), pk)
    key = request.headers.get('X-Idempotency-Key') or request.data.get('idempotency_key')
    try:
        checkout = adjust_replacement_exposure(
            checkout, request.user, item_id=request.data.get('item_id'),
            amount=request.data.get('amount'), reason_code=request.data.get('reason_code', ''),
            note=request.data.get('note', ''), evidence=request.data.get('evidence') or {},
            expected_version=request.data.get('expected_version'), idempotency_key=key,
        )
    except (DjValidationError, TypeError, ValueError) as exc:
        if isinstance(exc, DjValidationError):
            raise ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
        raise ValidationError(str(exc))
    return Response(CheckoutSerializer(checkout, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([make_permission('invoice.replace_manage')])
def assign_replacement_owner_view(request, pk):
    from apps.users.models import User
    from .checkout_services import assign_replacement_owner
    checkout = resolve_public_id(Checkout.objects.for_organization(request.user.organization), pk)
    owner = get_object_or_404(
        User, pk=request.data.get('owner'), organization=request.user.organization,
    )
    key = request.headers.get('X-Idempotency-Key') or request.data.get('idempotency_key')
    try:
        checkout = assign_replacement_owner(
            checkout, request.user, owner=owner,
            correction_due_at=request.data.get('correction_due_at'),
            reason_code=request.data.get('reason_code', ''),
            expected_version=request.data.get('expected_version'), idempotency_key=key,
        )
    except DjValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
    return Response(CheckoutSerializer(checkout, context={'request': request}).data)


def _post_checkout_response(request, pk, *, paying):
    from .checkout_services import CheckoutVersionConflict, post_checkout
    checkout = resolve_public_id(Checkout.objects.for_organization(request.user.organization), pk)
    key = request.headers.get('X-Idempotency-Key') or request.data.get('idempotency_key')
    command = CheckoutPostCommandSerializer(data={
        'expected_version': request.data.get('expected_version'),
        'idempotency_key': key,
        'payment_lines': request.data.get('payment_lines'),
        'payment_method': request.data.get('payment_method'),
        'due_at': request.data.get('due_at'),
        'credit_reason': request.data.get('credit_reason', ''),
        'obligation_evidence': request.data.get('obligation_evidence') or {},
    })
    command.is_valid(raise_exception=True)
    data = command.validated_data
    try:
        invoice = post_checkout(
            checkout, request.user,
            payment_lines=data.get('payment_lines'),
            payment_method=data.get('payment_method'),
            expected_version=data['expected_version'],
            idempotency_key=data['idempotency_key'],
            due_at=data.get('due_at'),
            credit_reason=data.get('credit_reason', ''),
            obligation_evidence=data.get('obligation_evidence') or {},
        )
    except CheckoutVersionConflict as exc:
        return Response(
            exc.message_dict if hasattr(exc, 'message_dict') else {'detail': exc.messages},
            status=status.HTTP_409_CONFLICT,
        )
    except DjValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
    return Response(InvoiceSerializer(invoice, context={'request': request}).data, status=201)


@api_view(['POST'])
@permission_classes([CanPayInvoice])
def pay_checkout_view(request, pk):
    if not (request.data.get('payment_lines') or request.data.get('payment_method')):
        raise ValidationError('Se requiere payment_lines o payment_method.')
    return _post_checkout_response(request, pk, paying=True)


@api_view(['POST'])
@permission_classes([make_permission('invoice.post_unpaid')])
def post_checkout_unpaid(request, pk):
    if request.data.get('payment_lines') or request.data.get('payment_method'):
        raise ValidationError('Usa /pay/ para cobrar ahora.')
    return _post_checkout_response(request, pk, paying=False)


@api_view(['POST'])
@permission_classes([make_permission('checkout.prescription_decide')])
def decide_checkout_prescription(request, pk, prescription_item_pk):
    from apps.prescriptions.models import PrescriptionItem
    from .checkout_services import decide_prescription_item
    checkout = resolve_public_id(Checkout.objects.for_organization(request.user.organization), pk)
    prescription_item = get_object_or_404(
        PrescriptionItem, pk=_internal_pk(prescription_item_pk, 'prescription_item_pk'),
        organization=request.user.organization,
    )
    try:
        decide_prescription_item(
            checkout, prescription_item, request.user,
            decision=request.data.get('decision', 'declined'),
            decline_reason=request.data.get('reason_code', ''),
            expected_version=request.data.get('expected_version'),
        )
    except DjValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
    checkout.refresh_from_db()
    return Response(CheckoutSerializer(checkout, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([make_permission('checkout.estimate.issue')])
def issue_checkout_estimate_view(request, pk):
    from .checkout_services import issue_checkout_estimate
    checkout = resolve_public_id(Checkout.objects.for_organization(request.user.organization), pk)
    key = request.headers.get('X-Idempotency-Key') or request.data.get('idempotency_key')
    try:
        estimate = issue_checkout_estimate(
            checkout, request.user, expected_version=request.data.get('expected_version'),
            idempotency_key=key,
        )
    except DjValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
    return Response(CheckoutEstimateSerializer(estimate).data, status=201)


@api_view(['GET'])
@permission_classes([make_permission('checkout.estimate.issue')])
def checkout_estimate_pdf(request, pk):
    """Renderiza el snapshot inmutable; nunca consulta precios actuales del Checkout."""
    from io import BytesIO
    from django.http import HttpResponse
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph
    from apps.core.pdf import (
        CONTENT_WIDTH, build_styles, data_table, get_theme_for_organization,
        pdf_filename, render_branded_pdf, safe_pdf_text, section, title_block,
        totals_table,
    )

    estimate = resolve_public_id(
        CheckoutEstimate.objects.for_organization(request.user.organization)
        .select_related('organization', 'checkout__pet'), pk,
    )
    snapshot = estimate.snapshot
    org = estimate.organization
    theme = get_theme_for_organization(org)
    st = build_styles(theme)
    flow = title_block(
        st, title='Estimado comercial',
        meta_lines=[
            f"Checkout: {safe_pdf_text(snapshot.get('checkout_public_id', ''))}",
            f"Versión: {snapshot.get('checkout_version', '')}",
        ],
    )
    flow += section(st, theme, 'Ítems')
    rows = [
        [
            Paragraph(safe_pdf_text(row.get('description', ''))[:120], st['cell']),
            row.get('quantity', ''), _fmt_money(Decimal(row.get('unit_price', '0'))),
            _fmt_money(Decimal(row.get('subtotal', '0'))),
        ]
        for row in snapshot.get('items', [])
    ] or [[Paragraph('<i>Sin ítems</i>', st['cell']), '', '', '']]
    flow += data_table(
        st, theme, ['Descripción', 'Cant.', 'P. unit.', 'Subtotal'], rows,
        col_widths=[CONTENT_WIDTH - 7.1 * cm, 2.0 * cm, 2.55 * cm, 2.55 * cm],
        align_right=(1, 2, 3),
    )
    flow += totals_table(st, theme, [
        ['Subtotal', _fmt_money(Decimal(snapshot.get('subtotal', '0')))],
        ['IVA', _fmt_money(Decimal(snapshot.get('tax_amount', '0')))],
        ['Total estimado', _fmt_money(Decimal(snapshot.get('total', '0')))],
    ])
    buffer = BytesIO()
    render_branded_pdf(
        buffer, flow, organization=org, doc_kicker='Estimado',
        pdf_title='Estimado comercial', watermark='NO ES FACTURA',
    )
    buffer.seek(0)
    filename = pdf_filename(
        'estimado', estimate.pk,
        estimate.checkout.pet.name if estimate.checkout.pet_id else 'sin-mascota',
        estimate.generated_at.date(),
    )
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@api_view(['POST'])
@permission_classes([make_permission('billing.clinical_charge.reprice')])
def reprice_clinical_charge_view(request, pk):
    from .checkout_services import reprice_clinical_charge
    entry = get_object_or_404(
        ClinicalChargeEntry.all_objects.select_related(
            'medical_record_service__service', 'medical_record_product__presentation',
        ),
        pk=_internal_pk(pk), organization=request.user.organization, lifecycle='active',
    )
    source = entry.medical_record_service or entry.medical_record_product
    if source is None:
        raise ValidationError('La fuente clínica ya no está disponible.')
    key = request.headers.get('X-Idempotency-Key') or request.data.get('idempotency_key')
    try:
        successor = reprice_clinical_charge(
            source, request.user,
            new_unit_price=request.data.get('new_unit_price'),
            reason=request.data.get('reason_code', 'authorized_correction'),
            expected_quantity=request.data.get('expected_quantity'),
            idempotency_key=key,
        )
    except DjValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
    return Response({
        'entry_id': successor.pk, 'cycle_number': successor.cycle_number,
        'unit_price': str(successor.unit_price),
        'quantity': str(successor.current_quantity),
    })


@api_view(['POST'])
@permission_classes([make_permission('invoice.create')])
def complete_checkout_no_charge(request, pk):
    from .checkout_services import complete_no_charge
    checkout = resolve_public_id(Checkout.objects.for_organization(request.user.organization), pk)
    key = request.headers.get('X-Idempotency-Key') or request.data.get('idempotency_key')
    try:
        checkout = complete_no_charge(
            checkout, request.user, reason=request.data.get('reason', 'no_billable_items'),
            expected_version=request.data.get('expected_version'), idempotency_key=key,
        )
    except DjValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
    return Response(CheckoutSerializer(checkout, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([make_permission('invoice.destroy')])
def abandon_checkout_view(request, pk):
    from .checkout_services import abandon_checkout
    checkout = resolve_public_id(Checkout.objects.for_organization(request.user.organization), pk)
    key = request.headers.get('X-Idempotency-Key') or request.data.get('idempotency_key')
    try:
        checkout = abandon_checkout(
            checkout, request.user, reason=request.data.get('reason', 'cancelled_by_user'),
            expected_version=request.data.get('expected_version'), idempotency_key=key,
        )
    except DjValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
    return Response(CheckoutSerializer(checkout, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([make_permission('invoice.replace_waive')])
def waive_replacement(request, pk):
    checkout = resolve_public_id(
        Checkout.objects.for_organization(request.user.organization), pk,
    )
    from .checkout_services import waive_replacement_exposure
    try:
        waiver = waive_replacement_exposure(
            checkout, request.user,
            reason_code=request.data.get('reason_code', ''),
            evidence=request.data.get('evidence') or {},
            expected_version=request.data.get('expected_version'),
            idempotency_key=(request.headers.get('X-Idempotency-Key') or request.data.get('idempotency_key')),
        )
    except DjValidationError as exc:
        return Response({'detail': exc.messages}, status=status.HTTP_409_CONFLICT)
    return Response(CheckoutSerializer(waiver.checkout, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([make_permission('invoice.replace')])
def void_and_prepare_replacement(request, pk):
    invoice = resolve_public_id(
        Invoice.objects.for_organization(request.user.organization), pk,
    )
    from .checkout_services import void_and_prepare_replacement as command
    try:
        checkout = command(
            invoice, request.user,
            reason=request.data.get('reason', 'correction'),
            correction_due_at=request.data.get('correction_due_at'),
            dispositions=request.data.get('dispositions') or [],
            idempotency_key=(request.headers.get('X-Idempotency-Key') or request.data.get('idempotency_key')),
        )
    except DjValidationError as exc:
        return Response({'detail': exc.messages}, status=status.HTTP_409_CONFLICT)
    return Response(CheckoutSerializer(checkout, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([make_permission('invoice.void_terminal')])
def void_invoice_terminal(request, pk):
    invoice = resolve_public_id(
        Invoice.objects.for_organization(request.user.organization), pk,
    )
    from .checkout_services import void_invoice_terminal as command
    try:
        invoice = command(
            invoice, request.user,
            reason_code=request.data.get('reason_code', ''),
            reason_notes=request.data.get('reason_notes', ''),
            dispositions=request.data.get('dispositions') or [],
            idempotency_key=(
                request.headers.get('X-Idempotency-Key')
                or request.data.get('idempotency_key')
            ),
        )
    except DjValidationError as exc:
        return Response({'detail': exc.messages}, status=status.HTTP_409_CONFLICT)
    return Response(InvoiceSerializer(invoice, context={'request': request}).data)


class ServiceListCreateView(BillingOrganizationMixin, generics.ListCreateAPIView):
    serializer_class = ServiceSerializer
    permission_classes = [HybridPermission]
    resource_name = "service"

    def get_queryset(self):
        queryset = Service.objects.for_organization(self.request.user.organization)
        active_only = self.request.query_params.get('active')
        if active_only == 'true':
            queryset = queryset.filter(is_active=True)
        search = self.request.query_params.get('search', '').strip()
        if search:
            queryset = queryset.filter(name__icontains=search)
        return queryset

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class ServiceDetailView(PublicIdLookupMixin, BillingOrganizationMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ServiceSerializer
    permission_classes = [HybridPermission]
    resource_name = "service"
    lookup_url_kwarg = 'pk'

    def get_queryset(self):
        return Service.objects.for_organization(self.request.user.organization)


class InvoiceListCreateView(BillingOrganizationMixin, generics.ListAPIView):
    serializer_class = InvoiceSerializer
    permission_classes = [HybridPermission]
    resource_name = "invoice"
    # P1-2: documento de alto volumen (6k-25k/año). PageNumber(25) + ordering
    # server-side. La tabla de Cobros movía el sort (Fecha/Total) en el cliente;
    # con paginación eso ordenaría solo la página actual → se expone `?ordering`.
    pagination_class = StandardResultsPagination
    # StableOrderingFilter agrega `-id` a cualquier `?ordering` que no lo lleve:
    # `total` empata entre muchas facturas → sin
    # desempate, PageNumber saltaría/duplicaría filas entre páginas.
    filter_backends = [StableOrderingFilter]
    ordering_fields = ['created_at', 'total']
    # Default ya estable (created_at puede colisionar en ventas de la misma tx).
    ordering = ['-created_at', '-id']

    def get_queryset(self):
        org = self.request.user.organization
        queryset = Invoice.objects.for_organization(
            org
        ).select_related(
            'owner', 'pet', 'appointment'
        ).annotate(
            # ADR p27: Σ pagos por factura para remaining_balance sin N+1.
            _paid_sum=Coalesce(
                Sum('payments__amount'),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )

        owner_lookup = self.request.query_params.get('owner')

        invoice_status = self.request.query_params.get('status', '').strip()
        invoice_type = self.request.query_params.get('invoice_type', '').strip()

        created_from = parse_date(self.request.query_params.get('created_from', ''))
        created_to = parse_date(self.request.query_params.get('created_to', ''))
        paid_from = parse_date(self.request.query_params.get('paid_from', ''))
        paid_to = parse_date(self.request.query_params.get('paid_to', ''))

        if owner_lookup:
            from uuid import UUID
            from apps.patients.models import Owner
            from django.db.models import Q
            try:
                owner_uuid = str(UUID(str(owner_lookup)))
            except (ValueError, TypeError):
                owner_uuid = str(resolve_public_id(
                    Owner.all_objects.filter(organization=org), owner_lookup).public_id)
            queryset = queryset.filter(Q(owner__public_id=owner_uuid) |
                                       Q(subject_snapshot__owner__uuid=owner_uuid))
        # pet_id removed — no longer exposed as standalone param
        if invoice_status:
            if invoice_status not in VALID_INVOICE_STATUSES:
                raise ValidationError({'status': ['Estado inválido.']})
            queryset = queryset.filter(status=invoice_status)
        if invoice_type:
            if invoice_type not in VALID_INVOICE_TYPES:
                raise ValidationError({'invoice_type': ['Tipo inválido.']})
            queryset = queryset.filter(invoice_type=invoice_type)

        if created_from and created_to and created_from > created_to:
            raise ValidationError({
                'created_to': ['La fecha final debe ser posterior a la inicial.']
            })
        if paid_from and paid_to and paid_from > paid_to:
            raise ValidationError({
                'paid_to': ['La fecha final debe ser posterior a la inicial.']
            })

        queryset = filter_by_local_range(queryset, 'created_at', org, created_from, created_to)
        queryset = filter_by_local_range(queryset, 'paid_at', org, paid_from, paid_to)

        # annotate(Sum(...)) descarta el Meta.ordering del modelo (queda
        # query.order_by=() → orden de heap del DB). Reimponer explícitamente
        # con tiebreaker `-id`. OrderingFilter lo sobrescribe cuando llega
        # `?ordering`; sin parámetro, este orden = el default de `ordering`.
        return queryset.order_by('-created_at', '-id')

class InvoiceDetailView(PublicIdLookupMixin, BillingOrganizationMixin, generics.RetrieveAPIView):
    serializer_class = InvoiceSerializer
    permission_classes = [HybridPermission]
    resource_name = "invoice"
    lookup_url_kwarg = 'pk'

    def get_queryset(self):
        # ADR p29: prefetch de notas de crédito + reembolsos + reversals para que
        # InvoiceSerializer.get_credit_notes (flag `with_credit_notes`) no haga N+1.
        # ADR p30: prefetch de la receta vinculada (suggestions de dispensación).
        return Invoice.objects.for_organization(
            self.request.user.organization
        ).prefetch_related(
            'credit_notes__refund_payments__reversals',
            'medical_record__prescription__items__product__presentations',
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['with_credit_notes'] = True
        context['with_prescription_suggestions'] = True
        return context

@api_view(['PATCH'])
@permission_classes([CanPayInvoice])
def pay_invoice(request, pk):
    from apps.billing.services import pay_invoice as pay_invoice_service

    payment_lines = request.data.get('payment_lines')
    payment_method = request.data.get('payment_method')
    if not payment_lines and not payment_method:
        return Response(
            {'error': 'Se requiere payment_lines o payment_method'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    idempotency_key = request.headers.get('X-Idempotency-Key') or request.data.get('idempotency_key')

    invoice = resolve_public_id(
        Invoice.objects.for_organization(request.user.organization), pk
    )
    try:
        invoice = pay_invoice_service(
            invoice, user=request.user,
            payment_method=payment_method,
            payment_lines=payment_lines,
            idempotency_key=idempotency_key,
        )
    except DjValidationError as e:
        return Response({'detail': e.messages}, status=status.HTTP_400_BAD_REQUEST)
    return Response(InvoiceSerializer(invoice).data)


@api_view(['POST'])
@permission_classes([make_permission('billing.rx_dispense')])
def dispense_prescription(request, pk):
    """
    Agrega al Checkout abierto los productos de la receta interna que el cliente
    decide llevar. Recepción elige presentación + cantidad por ítem; el stock se
    descuenta únicamente en el post autoritativo, no durante la selección.

    Body: { "expected_version": <int>, "idempotency_key": <str>,
            "lines": [ { "presentation": <pk>, "quantity": <entero>,
                         "prescription_item": <pk>, "lot": <pk|null> }, ... ] }
    """
    from apps.prescriptions.models import Prescription
    from apps.billing.checkout_services import (
        CheckoutVersionConflict,
        dispense_prescription_into_checkout,
    )

    prescription = resolve_public_id(
        Prescription.objects.for_organization(request.user.organization), pk
    )

    key = request.headers.get('X-Idempotency-Key') or request.data.get('idempotency_key')
    command = PrescriptionDispenseCommandSerializer(data={
        'lines': request.data.get('lines'),
        'expected_version': request.data.get('expected_version'),
        'idempotency_key': key,
    })
    command.is_valid(raise_exception=True)
    data = command.validated_data
    normalized = [
        {
            'presentation_id': line['presentation'],
            'quantity': line['quantity'],
            'prescription_item_id': line['prescription_item'],
            'lot_id': line.get('lot'),
        }
        for line in data['lines']
    ]

    try:
        checkout = dispense_prescription_into_checkout(
            prescription, normalized, request.user,
            expected_version=data['expected_version'],
            idempotency_key=data['idempotency_key'],
        )
    except CheckoutVersionConflict as exc:
        return Response(
            exc.message_dict if hasattr(exc, 'message_dict') else {'detail': exc.messages},
            status=status.HTTP_409_CONFLICT,
        )
    except DjValidationError as e:
        return Response({'detail': e.messages}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        CheckoutSerializer(checkout, context={'request': request}).data,
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([make_permission("billing.refund")])
def refund_invoice(request, pk):
    """ADR p29: emite nota de crédito + reembolso sobre una factura pagada."""
    from apps.billing.services import process_refund

    invoice = resolve_public_id(
        Invoice.objects.for_organization(request.user.organization), pk
    )
    idempotency_key = request.headers.get('X-Idempotency-Key') or request.data.get('idempotency_key')
    try:
        credit_note = process_refund(
            invoice, user=request.user,
            credit_lines=request.data.get('credit_lines') or [],
            refund_lines=request.data.get('refund_lines') or [],
            reason_code=request.data.get('reason_code', ''),
            reason_notes=request.data.get('reason_notes', ''),
            idempotency_key=idempotency_key,
        )
    except DjValidationError as e:
        return Response({'detail': e.messages}, status=status.HTTP_400_BAD_REQUEST)
    return Response(CreditNoteSerializer(credit_note).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([make_permission("billing.refund")])
def reverse_credit_note(request, pk):
    """ADR p29: contra-asiento de una nota de crédito (revertir devolución)."""
    from apps.billing.services import reverse_credit_note as reverse_service
    from .models import CreditNote

    credit_note = resolve_public_id(
        CreditNote.objects.for_organization(request.user.organization), pk
    )
    idempotency_key = request.headers.get('X-Idempotency-Key') or request.data.get('idempotency_key')
    try:
        credit_note = reverse_service(
            credit_note, user=request.user,
            reason_code=request.data.get('reason_code', ''),
            reason_notes=request.data.get('reason_notes', ''),
            idempotency_key=idempotency_key,
        )
    except DjValidationError as e:
        return Response({'detail': e.messages}, status=status.HTTP_400_BAD_REQUEST)
    return Response(CreditNoteSerializer(credit_note).data)


_STATUS_LABEL = dict(Invoice.STATUS_CHOICES)
_TYPE_LABEL = dict(Invoice.INVOICE_TYPE_CHOICES)
_PAYMENT_LABEL = dict(Invoice.PAYMENT_METHOD_CHOICES)


def _fmt_money(value):
    try:
        return f"${value:,.2f}"
    except Exception:
        return "$0.00"


@api_view(['GET'])
@permission_classes([make_permission("invoice.retrieve")])
def invoice_pdf(request, pk):
    """Genera el documento financiero emitido (posted, paid o voided)."""
    from io import BytesIO

    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, Spacer

    from django.http import HttpResponse

    from apps.core.datetime_utils import utc_to_local
    from apps.core.pdf import (
        CONTENT_WIDTH, build_styles, data_table, get_theme_for_organization,
        info_card, pdf_filename, render_branded_pdf, safe_pdf_text,
        section, title_block, totals_table,
    )

    invoice = resolve_public_id(
        Invoice.objects
            .for_organization(request.user.organization)
            .select_related('pet', 'owner', 'created_by', 'organization')
            .prefetch_related('items'),
        pk,
    )

    org = invoice.organization
    theme = get_theme_for_organization(org)
    st = build_styles(theme)

    def fmt_dt(value):
        local = utc_to_local(org, value)
        return local.strftime('%d/%m/%Y %H:%M') if local else ''

    meta_lines = [
        f"Estado: <b>{_STATUS_LABEL.get(invoice.status, invoice.status)}</b> &nbsp;·&nbsp; "
        f"Tipo: {_TYPE_LABEL.get(invoice.invoice_type, invoice.invoice_type)}",
        f"Creado: {fmt_dt(invoice.created_at)}",
    ]
    if invoice.posted_at:
        meta_lines.append(f"Emitido: {fmt_dt(invoice.posted_at)}")
    if invoice.paid_at:
        meta_lines.append(f"Pagado: {fmt_dt(invoice.paid_at)}")
    if invoice.voided_at:
        meta_lines.append(f"Anulada: {fmt_dt(invoice.voided_at)}")

    flow = []
    flow += title_block(st, title=f"Cobro #{invoice.id}", meta_lines=meta_lines)

    flow += section(st, theme, "Cliente")
    from apps.core.subject_history import identity
    old_owner = identity(invoice, 'owner')
    old_pet = identity(invoice, 'pet')
    client_pairs = [
        ("Dueño", safe_pdf_text(old_owner.get('name') or (invoice.owner.name if invoice.owner_id else 'Desconocido'))),
        ("Teléfono", safe_pdf_text(old_owner.get('phone') or (invoice.owner.phone if invoice.owner_id else ''))),
    ]
    if old_pet or invoice.pet_id:
        pet = invoice.pet if invoice.pet_id else None
        client_pairs += [
            ("Mascota", safe_pdf_text(old_pet.get('name') or (pet.name if pet else 'Desconocido'))),
            ("Especie", safe_pdf_text(old_pet.get('species') or (pet.species if pet else ''))),
            ("Raza", safe_pdf_text(old_pet.get('breed') or (pet.breed if pet else ''))),
        ]
    flow += info_card(st, theme, client_pairs, columns=3)

    flow += section(st, theme, "Ítems")
    items = list(invoice.items.all())
    rows = []
    if not items:
        rows.append([Paragraph("<i>Sin ítems</i>", st['cell']), "", "", ""])
    else:
        for it in items:
            rows.append([
                Paragraph(safe_pdf_text(it.description)[:120], st['cell']),
                f"{it.quantity:g}",
                _fmt_money(it.unit_price),
                _fmt_money(it.subtotal),
            ])
    flow += data_table(
        st, theme,
        ["Descripción", "Cant.", "P. unit.", "Subtotal"], rows,
        col_widths=[CONTENT_WIDTH - 7.1 * cm, 2.0 * cm, 2.55 * cm, 2.55 * cm],
        align_right=(1, 2, 3),
    )

    tax_pct = float(invoice.tax_rate) * 100
    flow += totals_table(st, theme, [
        ["Subtotal", _fmt_money(invoice.subtotal)],
        [f"IVA ({tax_pct:.2f}%)", _fmt_money(invoice.tax_amount)],
        ["Total", _fmt_money(invoice.total)],
    ])

    if invoice.status == 'paid' and invoice.payment_method:
        flow.append(Spacer(1, 0.4 * cm))
        flow.append(Paragraph(
            f"<b>Método de pago:</b> {_PAYMENT_LABEL.get(invoice.payment_method, invoice.payment_method)}",
            st['body'],
        ))

    if invoice.notes:
        flow += section(st, theme, "Notas")
        flow.append(Paragraph(safe_pdf_text(invoice.notes).replace('\n', '<br/>'), st['body']))

    # Una factura anulada debe distinguirse a simple vista.
    watermark = {'voided': 'ANULADO'}.get(invoice.status)

    buffer = BytesIO()
    render_branded_pdf(
        buffer, flow,
        organization=org,
        doc_kicker="Cobro",
        pdf_title=f"Cobro #{invoice.id}",
        watermark=watermark,
    )
    buffer.seek(0)

    created_local = utc_to_local(org, invoice.created_at)
    filename = pdf_filename(
        'factura', invoice.id,
        old_pet.get('name') or (invoice.pet.name if invoice.pet_id else 'sin-mascota'),
        created_local.date() if created_local else None,
    )
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
