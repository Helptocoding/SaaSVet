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
from apps.core.permissions import HybridPermission, make_permission
from apps.core.views import TenantQueryMixin, PublicIdLookupMixin, resolve_public_id

from .models import Service, Invoice, InvoiceItem
from .serializers import ServiceSerializer, InvoiceSerializer, InvoiceItemSerializer, CreditNoteSerializer
from .permissions import CanConfirmInvoice, CanPayInvoice, CanCancelInvoice

VALID_INVOICE_TYPES = {choice[0] for choice in Invoice.INVOICE_TYPE_CHOICES}
VALID_INVOICE_STATUSES = {choice[0] for choice in Invoice.STATUS_CHOICES}


class PrescriptionRequired(APIException):
    """ADR p26: falta atestación de receta para un producto requires_prescription.
    `default_code` propaga a `{code: 'prescription_required'}` vía el handler global."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = 'prescription_required'
    default_detail = 'Se requiere atestación de receta para este producto.'


class BillingOrganizationMixin(TenantQueryMixin):
    """Garantiza que ninguna vista de facturación retorne datos de otra organización."""


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


class InvoiceListCreateView(BillingOrganizationMixin, generics.ListCreateAPIView):
    serializer_class = InvoiceSerializer
    permission_classes = [HybridPermission]
    resource_name = "invoice"

    def get_queryset(self):
        org = self.request.user.organization
        queryset = Invoice.objects.for_organization(
            org
        ).select_related('owner', 'pet', 'appointment').annotate(
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
            # Día 6 Fase 3: resolver Owner por public_id antes del filtro
            from apps.patients.models import Owner
            owner = resolve_public_id(Owner.objects.for_organization(org), owner_lookup)
            queryset = queryset.filter(owner=owner)
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

        return queryset

    def perform_create(self, serializer):
        org = self.request.user.organization
        serializer.save(
            organization=org,
            created_by=self.request.user,
            tax_rate=org.tax_rate,
        )


class InvoiceDetailView(PublicIdLookupMixin, BillingOrganizationMixin, generics.RetrieveUpdateAPIView):
    serializer_class = InvoiceSerializer
    permission_classes = [HybridPermission]
    resource_name = "invoice"
    lookup_url_kwarg = 'pk'

    def get_queryset(self):
        return Invoice.objects.for_organization(self.request.user.organization)

    def update(self, request, *args, **kwargs):
        with transaction.atomic():
            invoice = resolve_public_id(
                Invoice.objects.for_organization(request.user.organization).select_for_update(),
                kwargs['pk'],
            )
            if invoice.status != 'draft':
                return Response(
                    {'error': 'Solo se pueden editar facturas en borrador.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            partial = kwargs.pop('partial', False)
            serializer = self.get_serializer(invoice, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)
            return Response(serializer.data)


@api_view(['PATCH'])
@permission_classes([CanConfirmInvoice])
def confirm_invoice(request, pk):
    from apps.billing.services import confirm_invoice as confirm_invoice_service

    invoice = resolve_public_id(
        Invoice.objects.for_organization(request.user.organization), pk
    )
    try:
        confirm_invoice_service(invoice, user=request.user)
    except DjValidationError as e:
        return Response({'detail': e.messages}, status=status.HTTP_400_BAD_REQUEST)

    invoice.refresh_from_db()
    return Response(InvoiceSerializer(invoice).data)


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


class InvoiceItemCreateView(BillingOrganizationMixin, generics.CreateAPIView):
    serializer_class = InvoiceItemSerializer
    permission_classes = [HybridPermission]
    resource_name = "invoice"

    def get_serializer_context(self):
        context = super().get_serializer_context()
        invoice = resolve_public_id(
            Invoice.objects.for_organization(self.request.user.organization),
            self.kwargs['invoice_pk']
        )
        context['invoice'] = invoice
        return context

    def perform_create(self, serializer):
        from apps.inventory.models import Presentation as InventoryPresentation

        data = serializer.validated_data
        service = data.get('service')
        presentation = data.get('presentation')

        with transaction.atomic():
            invoice = resolve_public_id(
                Invoice.objects.for_organization(self.request.user.organization).select_for_update(),
                self.kwargs['invoice_pk']
            )
            if invoice.status != 'draft':
                raise ValidationError('Solo se pueden agregar ítems a cobros en borrador')

            if service:
                unit_price = service.base_price
                description = service.name
                serializer.save(invoice=invoice, unit_price=unit_price, description=description)
            else:
                locked_pres = InventoryPresentation.objects.select_for_update().filter(
                    pk=presentation.pk,
                    organization=self.request.user.organization,
                ).first()
                if locked_pres is None:
                    raise ValidationError("Presentación no encontrada en la organización.")
                if locked_pres.stock < data.get('quantity', 1):
                    raise ValidationError(
                        f"Stock insuficiente para '{locked_pres.product.name}': "
                        f"disponible {locked_pres.stock}, solicitado {data.get('quantity', 1)}."
                    )
                # ADR p26: venta de producto con receta en venta directa exige
                # atestación de receta externa (registro legal append-only) +
                # permiso billing.rx_dispense. Creada en el mismo atomic, bajo
                # el lock de la Invoice.
                if locked_pres.product.requires_prescription and invoice.invoice_type == 'direct_sale':
                    self._attest_external_prescription(invoice, locked_pres, data.get('quantity', 1))
                unit_price = locked_pres.sale_price
                description = str(locked_pres)
                serializer.save(invoice=invoice, unit_price=unit_price, description=description)

    def _attest_external_prescription(self, invoice, locked_pres, quantity):
        """ADR p26: gate + registro de atestación de receta externa."""
        from apps.core.permissions import user_has_permission
        from apps.core.sanitize import sanitize_text
        from rest_framework.exceptions import PermissionDenied
        from .models import ExternalPrescriptionAttestation

        if not user_has_permission(self.request.user, 'billing.rx_dispense'):
            raise PermissionDenied('No tienes permiso para dispensar productos con receta.')

        attested = self.request.data.get('rx_attested')
        prescriber = sanitize_text(self.request.data.get('prescriber_name') or '', max_length=255)
        if not attested or not prescriber:
            raise PrescriptionRequired(detail=(
                f"'{locked_pres.product.name}' requiere receta. Confirma que el cliente "
                f"presentó una receta médica válida e indica el médico que la emitió."
            ))
        ExternalPrescriptionAttestation.objects.create(
            organization=invoice.organization,
            invoice=invoice,
            presentation=locked_pres,
            quantity=quantity,
            attested_by=self.request.user,
            prescriber_name=prescriber,
            prescription_folio=sanitize_text(self.request.data.get('prescription_folio') or '', max_length=100),
            notes=sanitize_text(self.request.data.get('rx_notes') or '', max_length=5000),
        )


class InvoiceItemDetailView(BillingOrganizationMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = InvoiceItemSerializer
    permission_classes = [HybridPermission]
    resource_name = "invoice"

    def initial(self, request, *args, **kwargs):
        # Día 6 audit F14: `invoice.update` no existe en PERMISSION_CODES
        # (decisión semántica: invoice no tiene estado "update" abstracto —
        # cambios son via state machine confirm/pay/cancel + edición de items
        # en draft). Sin esta declaración explícita, _method_to_action infiere
        # 'update' por PATCH y exige 'invoice.update' inexistente → 403 silente
        # para VET/ASSISTANT.
        #
        # Mapping declarado:
        #   GET    → invoice.retrieve   (lectura del ítem)
        #   PATCH  → invoice.create     (edición de ítems es parte del armado
        #                                del cobro en draft — VET ya tiene)
        #   DELETE → invoice.destroy    (eliminar ítems del draft)
        if request.method == 'GET':
            self.required_permission = 'invoice.retrieve'
        elif request.method in ('PUT', 'PATCH'):
            self.required_permission = 'invoice.create'
        elif request.method == 'DELETE':
            self.required_permission = 'invoice.destroy'
        return super().initial(request, *args, **kwargs)

    def _get_invoice(self):
        return resolve_public_id(
            Invoice.objects.for_organization(self.request.user.organization),
            self.kwargs['invoice_pk']
        )

    def get_object(self):
        return get_object_or_404(InvoiceItem, pk=self.kwargs['pk'], invoice=self._get_invoice())

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['invoice'] = self._get_invoice()
        return context

    def update(self, request, *args, **kwargs):
        with transaction.atomic():
            invoice = resolve_public_id(
                Invoice.objects.for_organization(request.user.organization).select_for_update(),
                self.kwargs['invoice_pk']
            )
            item = get_object_or_404(InvoiceItem.objects.select_for_update(), pk=self.kwargs['pk'], invoice=invoice)
            if invoice.status != 'draft':
                return Response(
                    {'error': 'Solo se pueden editar ítems de facturas en borrador'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            partial = kwargs.pop('partial', False)
            serializer = self.get_serializer(item, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)
            return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        with transaction.atomic():
            invoice = resolve_public_id(
                Invoice.objects.for_organization(request.user.organization).select_for_update(),
                self.kwargs['invoice_pk']
            )
            item = get_object_or_404(InvoiceItem.objects.select_for_update(), pk=self.kwargs['pk'], invoice=invoice)
            if invoice.status != 'draft':
                return Response(
                    {'error': 'Solo se pueden eliminar ítems de facturas en borrador'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            item.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([CanPayInvoice])
def direct_pay_invoice(request, pk):
    """Paga una venta directa: confirma + cobra atómicamente (draft → paid en un paso)."""
    from apps.billing.services import pay_direct_sale

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
        invoice = pay_direct_sale(
            invoice, user=request.user,
            payment_method=payment_method,
            payment_lines=payment_lines,
            idempotency_key=idempotency_key,
        )
    except DjValidationError as e:
        return Response({'detail': e.messages}, status=status.HTTP_400_BAD_REQUEST)
    return Response(InvoiceSerializer(invoice).data)


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


@api_view(['PATCH'])
@permission_classes([CanCancelInvoice])
def cancel_invoice(request, pk):
    invoice = resolve_public_id(
        Invoice.objects.for_organization(request.user.organization), pk
    )
    from apps.core.sanitize import sanitize_text
    notes = sanitize_text(request.data.get('notes') or '', max_length=255)
    try:
        from .services import cancel_invoice as cancel_invoice_service
        cancel_invoice_service(invoice, user=request.user, notes=notes)
    except DjValidationError as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    invoice.refresh_from_db()
    return Response(InvoiceSerializer(invoice).data)


_STATUS_LABEL = dict(Invoice.STATUS_CHOICES)
_TYPE_LABEL = dict(Invoice.INVOICE_TYPE_CHOICES)
_PAYMENT_LABEL = dict(Invoice.PAYMENT_METHOD_CHOICES)


def _fmt_money(value):
    try:
        return f"${value:,.2f}"
    except Exception:
        return "$0.00"


def _fmt_dt(value):
    if not value:
        return ""
    try:
        return value.strftime('%d/%m/%Y %H:%M')
    except Exception:
        return str(value)


@api_view(['GET'])
@permission_classes([make_permission("invoice.retrieve")])
def invoice_pdf(request, pk):
    """Genera el cobro como archivo PDF (todos los estados, incluido draft)."""
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, LongTable,
    )
    from django.http import HttpResponse
    from apps.core.pdf_utils import safe_pdf_text, safe_filename_segment

    invoice = resolve_public_id(
        Invoice.objects
            .for_organization(request.user.organization)
            .select_related('pet', 'owner', 'created_by', 'organization')
            .prefetch_related('items'),
        pk,
    )

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title=f"Cobro #{invoice.id}",
    )
    styles = getSampleStyleSheet()
    h_org = ParagraphStyle('h_org', parent=styles['Heading1'], fontSize=16, spaceAfter=4)
    h_title = ParagraphStyle('h_title', parent=styles['Heading2'], fontSize=13, spaceAfter=2)
    h_sub = ParagraphStyle('h_sub', parent=styles['Heading3'], fontSize=11, spaceBefore=10, spaceAfter=4)
    body = styles['BodyText']
    body_sm = ParagraphStyle('body_sm', parent=body, fontSize=9, leading=11)

    flow = []
    flow.append(Paragraph(safe_pdf_text(invoice.organization.name), h_org))
    flow.append(Paragraph(f"COBRO #{invoice.id}", h_title))
    flow.append(Paragraph(
        f"Estado: <b>{_STATUS_LABEL.get(invoice.status, invoice.status)}</b> &nbsp;·&nbsp; "
        f"Tipo: {_TYPE_LABEL.get(invoice.invoice_type, invoice.invoice_type)}",
        body_sm,
    ))
    flow.append(Paragraph(f"Creado: {_fmt_dt(invoice.created_at)}", body_sm))
    if invoice.confirmed_at:
        flow.append(Paragraph(f"Confirmado: {_fmt_dt(invoice.confirmed_at)}", body_sm))
    if invoice.paid_at:
        flow.append(Paragraph(f"Pagado: {_fmt_dt(invoice.paid_at)}", body_sm))
    if invoice.cancelled_at:
        flow.append(Paragraph(f"Cancelado: {_fmt_dt(invoice.cancelled_at)}", body_sm))

    flow.append(Paragraph("Cliente", h_sub))
    owner_name = safe_pdf_text(invoice.owner.name) if invoice.owner_id else ""
    owner_phone = safe_pdf_text(invoice.owner.phone) if invoice.owner_id else ""
    flow.append(Paragraph(f"<b>Dueño:</b> {owner_name} &nbsp; <b>Teléfono:</b> {owner_phone}", body))
    if invoice.pet_id:
        pet = invoice.pet
        flow.append(Paragraph(
            f"<b>Mascota:</b> {safe_pdf_text(pet.name)} "
            f"&nbsp; <b>Especie:</b> {safe_pdf_text(pet.species)} "
            f"&nbsp; <b>Raza:</b> {safe_pdf_text(pet.breed or '-')}",
            body,
        ))

    flow.append(Paragraph("Ítems", h_sub))
    items = list(invoice.items.all())
    header = ["Descripción", "Cant.", "P. unit.", "Subtotal"]
    rows = [header]
    if not items:
        rows.append([Paragraph("<i>Sin ítems</i>", body_sm), "", "", ""])
    else:
        for it in items:
            desc = safe_pdf_text(it.description)[:120]
            rows.append([
                Paragraph(desc, body_sm),
                f"{it.quantity:g}",
                _fmt_money(it.unit_price),
                _fmt_money(it.subtotal),
            ])
    items_table = LongTable(
        rows,
        colWidths=[9.5 * cm, 1.8 * cm, 2.5 * cm, 2.5 * cm],
        repeatRows=1,
    )
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eeeeee')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    flow.append(items_table)

    flow.append(Spacer(1, 0.4 * cm))
    tax_pct = float(invoice.tax_rate) * 100
    totals = [
        ["Subtotal", _fmt_money(invoice.subtotal)],
        [f"IVA ({tax_pct:.2f}%)", _fmt_money(invoice.tax_amount)],
        ["Total", _fmt_money(invoice.total)],
    ]
    totals_table = Table(totals, colWidths=[12 * cm, 4.3 * cm], hAlign='RIGHT')
    totals_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('LINEABOVE', (0, -1), (-1, -1), 0.5, colors.black),
        ('TOPPADDING', (0, -1), (-1, -1), 6),
    ]))
    flow.append(totals_table)

    if invoice.status == 'paid' and invoice.payment_method:
        flow.append(Spacer(1, 0.4 * cm))
        flow.append(Paragraph(
            f"<b>Método de pago:</b> {_PAYMENT_LABEL.get(invoice.payment_method, invoice.payment_method)}",
            body,
        ))

    if invoice.notes:
        flow.append(Paragraph("Notas", h_sub))
        flow.append(Paragraph(safe_pdf_text(invoice.notes).replace('\n', '<br/>'), body))

    doc.build(flow)
    buffer.seek(0)

    pet_segment = safe_filename_segment(invoice.pet.name) if invoice.pet_id else "sin-mascota"
    filename = f"factura_{invoice.id}_{pet_segment}.pdf"
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
