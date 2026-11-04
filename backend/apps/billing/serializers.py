import logging
import re
from rest_framework import serializers
from decimal import Decimal
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from .models import (
    Service, Invoice, InvoiceItem, CreditNote, Checkout, CheckoutEstimate,
    CheckoutItem, ReplacementWaiver, CheckoutDispute,
)
from .money import discount_amount, money
from apps.core.sanitize import sanitize_text

SERVICE_NAME_REGEX = re.compile(r'^[A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s\-\(\)\/\%\+]+$')

# Logger dedicado para rechazos de tenant en serializers (ADR p14) — evento
# TENANT_VALIDATION_REJECTED a severidad WARNING. Separado de
# TENANT_MISMATCH_DETECTED (HybridPermission, ERROR) para no saturar la señal
# operacional con typos de UI / IDs stale del frontend.
tenant_logger = logging.getLogger('apps.tenant_validation')


class PaymentCommandLineSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=('cash', 'card', 'transfer', 'other'))
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    reference = serializers.CharField(required=False, allow_blank=True, max_length=100)


class CheckoutPostCommandSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(required=True, min_value=1)
    idempotency_key = serializers.CharField(required=True, max_length=100)
    payment_lines = PaymentCommandLineSerializer(
        many=True, required=False, allow_empty=False, allow_null=True,
    )
    payment_method = serializers.ChoiceField(
        choices=('cash', 'card', 'transfer', 'other'), required=False, allow_null=True,
    )
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    credit_reason = serializers.CharField(required=False, allow_blank=True, max_length=80)
    obligation_evidence = serializers.DictField(required=False)


class PrescriptionDispenseLineSerializer(serializers.Serializer):
    presentation = serializers.IntegerField(min_value=1)
    prescription_item = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('1'))
    lot = serializers.IntegerField(min_value=1, required=False, allow_null=True)

    def validate_quantity(self, value):
        from .prescription_availability import validated_presentation_quantity
        try:
            return validated_presentation_quantity(value)
        except DjangoValidationError as exc:
            if hasattr(exc, 'message_dict'):
                message = exc.message_dict.get('quantity', exc.messages)
            else:
                message = getattr(exc, 'messages', [str(exc)])
            raise serializers.ValidationError(message)


class PrescriptionDispenseCommandSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(required=True, min_value=1)
    idempotency_key = serializers.CharField(required=True, max_length=100)
    lines = PrescriptionDispenseLineSerializer(many=True, allow_empty=False, max_length=100)


class CheckoutItemMutationSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(required=True, min_value=1)
    quantity = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal('0.01'), required=False,
    )


def _validate_same_org(value, request, field_name, serializer_name):
    """
    Helper local: verifica que `value` pertenezca a la organización del
    request.user. Emite TENANT_VALIDATION_REJECTED en caso de violación.
    Retorna `value` si pasa (o si es None — FK opcional).

    NO se promueve a apps/core/ todavía (ADR p14 Fase 2). Battle-testing
    primero en los 2 sitios de Día 3, luego extracción a mixin centralizado.
    """
    if value is None:
        return value
    user_org_id = getattr(request.user, 'organization_id', None)
    obj_org_id = getattr(value, 'organization_id', None)
    if user_org_id is None or obj_org_id is None:
        return value
    if obj_org_id != user_org_id:
        tenant_logger.warning("TENANT_VALIDATION_REJECTED", extra={
            "source": "serializer",
            "serializer": serializer_name,
            "field": field_name,
            "user_id": getattr(request.user, 'pk', None),
            "user_org_id": user_org_id,
            "resource_org_id": obj_org_id,
            "resource_pk": getattr(value, 'pk', None),
            "endpoint": getattr(request, 'path', None),
            "method": getattr(request, 'method', None),
        })
        raise serializers.ValidationError('Acceso inválido.')
    return value


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ['id', 'public_id', 'name', 'description', 'base_price', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'public_id', 'created_at', 'updated_at']

    def validate_name(self, value):
        clean = sanitize_text(value or '', max_length=255)
        if not clean.strip():
            raise serializers.ValidationError("El nombre del servicio es obligatorio.")
        if not SERVICE_NAME_REGEX.match(clean):
            raise serializers.ValidationError(
                "El nombre contiene caracteres no permitidos."
            )
        return clean

    def validate_description(self, value):
        return sanitize_text(value or '', max_length=5000)

    def validate_base_price(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError("El precio debe ser mayor a 0.")
        return value


class InvoiceItemSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source='service.name', read_only=True)
    presentation_name = serializers.SerializerMethodField()
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    description = serializers.CharField(read_only=True)
    discount_amount = serializers.SerializerMethodField()
    # ADR p30: True si la línea es un producto dispensado de la receta interna
    # (agregado al cobro de la consulta). La UI lo usa para distinguir "para
    # llevar" de los insumos consumidos en la consulta.
    dispensed = serializers.SerializerMethodField()
    # Trazabilidad por lote (B2b). `lot` write = PK (body FK). Metadata read.
    tracks_lots = serializers.BooleanField(source='presentation.product.tracks_lots', read_only=True)
    lot_number = serializers.CharField(source='lot.lot_number', read_only=True)
    lot_effective_status = serializers.CharField(source='lot.effective_status', read_only=True)
    has_stock_allocation = serializers.SerializerMethodField()

    class Meta:
        model = InvoiceItem
        fields = [
            'id', 'invoice', 'service', 'service_name',
            'presentation', 'presentation_name', 'description',
            'quantity', 'conversion_factor_snapshot', 'unit_price',
            'discount_type', 'discount_value', 'discount_amount',
            'subtotal', 'dispensed',
            'lot', 'tracks_lots', 'lot_number', 'lot_effective_status',
            'has_stock_allocation',
        ]
        read_only_fields = ['id', 'subtotal', 'invoice', 'dispensed']

    def get_presentation_name(self, obj):
        if obj.presentation:
            return str(obj.presentation)   # "Producto — Presentación"
        return None

    def get_dispensed(self, obj):
        return obj.dispensed_from_prescription_item_id is not None

    def get_has_stock_allocation(self, obj):
        return obj.stock_allocations.exists()

    def get_discount_amount(self, obj):
        gross = money(obj.quantity * obj.unit_price)
        return str(discount_amount(gross, obj.discount_type, obj.discount_value))

    def validate(self, data):
        service = data.get('service')
        presentation = data.get('presentation')
        quantity = data.get('quantity')
        discount_type = data.get('discount_type')
        discount_value = data.get('discount_value', Decimal('0.00'))

        # Validar cantidad
        if quantity is not None and quantity <= 0:
            raise serializers.ValidationError("La cantidad debe ser mayor a cero.")

        # XOR: exactamente uno de los dos
        if service and presentation:
            raise serializers.ValidationError(
                "Un ítem es o un servicio o una presentación de inventario, no ambos."
            )
        # Día 6 audit: "must have one" solo aplica a CREATE (sin instance).
        # PATCH parcial (ej. `{"quantity": "2"}`) deja service/presentation en
        # None dentro de validated_data, pero self.instance ya los tiene
        # asignados. Sin este gate, todo PATCH parcial fallaba con 400.
        if not self.instance and not service and not presentation:
            raise serializers.ValidationError(
                "Debe especificar 'service' o 'presentation'."
            )

        # Día 6 audit F11: tenant validation canonical (ADR-13). Antes
        # comparaba contra invoice.organization_id (correcto pero sin log
        # estructurado). _validate_same_org valida contra request.user.org
        # y emite TENANT_VALIDATION_REJECTED uniforme con InvoiceSerializer.
        # Invariante: invoice.organization == request.user.organization
        # (garantizado por _get_invoice via for_organization()).
        invoice = self.context.get('invoice')
        if invoice is None:
            raise RuntimeError(
                "InvoiceItemSerializer requiere 'invoice' en su contexto."
            )
        request = self.context.get('request')
        assert request is not None, (
            "InvoiceItemSerializer requiere 'request' en su context. "
            "Si lo invocas fuera de una view DRF (shell, mgmt command), "
            "pasa context={'request': fake_request} con user.organization seteado."
        )

        if service:
            _validate_same_org(service, request, 'service', 'InvoiceItemSerializer')
            if not self.instance and InvoiceItem.objects.filter(invoice=invoice, service=service).exists():
                raise serializers.ValidationError(
                    "Este servicio ya está incluido en la factura."
                )

        if presentation:
            _validate_same_org(presentation, request, 'presentation', 'InvoiceItemSerializer')
            # Availability is never inferred from Presentation.stock (legacy).
            # Checkout posting settles Product/StockLot under locks; InvoiceItem
            # serialization must not introduce a competing stock authority.
            # Lote (B2b): obligatorio y consumible si el producto lo trackea (P1/P2).
            # Solo en CREATE (el lote es inmutable; PATCH parcial no lo re-valida).
            lot = data.get('lot')
            if presentation.product.tracks_lots:
                if not self.instance:
                    if lot is None:
                        raise serializers.ValidationError({'lot': 'Selecciona el lote a consumir.'})
                    if lot.organization_id != request.user.organization_id:
                        raise serializers.ValidationError({'lot': 'Lote fuera de tu organización.'})
                    if lot.product_id != presentation.product_id:
                        raise serializers.ValidationError({'lot': 'El lote no corresponde a este producto.'})
                    if not lot.is_consumable:
                        raise serializers.ValidationError(
                            {'lot': f"El lote {lot.lot_number} no está disponible ({lot.effective_status})."}
                        )
            elif lot is not None:
                raise serializers.ValidationError({'lot': 'Este producto no usa control de lotes.'})
            # ADR p26: la venta de un producto `requires_prescription` en una
            # venta directa YA NO se bloquea aquí. El gate autoritativo (atestación
            # de receta externa + permiso billing.rx_dispense) vive en
            # InvoiceItemCreateView.perform_create, que crea el registro legal
            # append-only en el mismo atomic bajo lock de la Invoice.

        # Validación de descuento (NUEVO)
        if discount_value is not None and discount_value < 0:
            raise serializers.ValidationError("El valor del descuento no puede ser negativo.")

        if discount_type == 'percentage' and discount_value > 100:
            raise serializers.ValidationError("El descuento porcentual no puede superar 100%.")

        if discount_type and (discount_value is None or discount_value <= 0):
            raise serializers.ValidationError(
                "Si se especifica tipo de descuento, el valor debe ser mayor a cero."
            )

        if discount_value and discount_value > 0 and not discount_type:
            raise serializers.ValidationError(
                "Debe especificar 'discount_type' si indica un valor de descuento."
            )

        return data


class InvoiceSerializer(serializers.ModelSerializer):
    items = InvoiceItemSerializer(many=True, read_only=True)
    pet_name = serializers.SerializerMethodField()
    # Día 6 B1: public_id de FKs embebidos para evitar PK en deep links
    pet_public_id = serializers.SerializerMethodField()
    owner_name = serializers.SerializerMethodField()
    owner_public_id = serializers.SerializerMethodField()
    historical_owner_public_id = serializers.SerializerMethodField()
    historical_pet_public_id = serializers.SerializerMethodField()
    subject_snapshot_source = serializers.SerializerMethodField()
    appointment_public_id = serializers.UUIDField(source='appointment.public_id', read_only=True, allow_null=True)
    medical_record_public_id = serializers.UUIDField(source='medical_record.public_id', read_only=True, allow_null=True)
    # ADR p30: receta de la consulta vinculada — recepción dispensa sus ítems
    # AGREGÁNDOLOS a esta misma factura de consulta (no se crea factura aparte).
    prescription_public_id = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    prescription_suggestions = serializers.SerializerMethodField()
    # ADR p27: ledger de pagos. amount_paid = Σ(Payment.amount); remaining_balance
    # = total − amount_paid (contrato §8.1). Decimals como string (sin float drift).
    amount_paid = serializers.SerializerMethodField()
    remaining_balance = serializers.SerializerMethodField()
    # ADR p29: notas de crédito de la factura. Solo en detalle (flag de context
    # `with_credit_notes`) para no incurrir N+1 en la lista. La UI las usa para
    # mostrar las devoluciones y ofrecer "revertir".
    credit_notes = serializers.SerializerMethodField()
    checkout_public_id = serializers.UUIDField(source='checkout.public_id', read_only=True, allow_null=True)
    supersedes_invoice_public_id = serializers.UUIDField(source='supersedes_invoice.public_id', read_only=True, allow_null=True)

    class Meta:
        model = Invoice
        fields = [
            'id', 'public_id', 'invoice_type', 'checkout_public_id',
            'supersedes_invoice_public_id',
            'appointment', 'appointment_public_id',
            'medical_record', 'medical_record_public_id',
            'prescription_public_id',
            'owner', 'owner_public_id', 'owner_name', 'historical_owner_public_id',
            'pet', 'pet_public_id', 'pet_name', 'historical_pet_public_id',
            'subject_snapshot_source',
            'status', 'payment_method', 'tax_rate',
            'subtotal', 'tax_amount', 'total',
            'due_at', 'credit_reason',
            'amount_paid', 'remaining_balance',
            'notes', 'created_by', 'created_by_name',
            'posted_at', 'paid_at', 'voided_at', 'created_at', 'updated_at',
            'items', 'prescription_suggestions', 'credit_notes',
        ]
        read_only_fields = [
            'id', 'public_id', 'pet_public_id', 'owner_public_id',
            'appointment_public_id', 'medical_record_public_id',
            'prescription_public_id',
            'subtotal', 'tax_amount', 'total',
            'amount_paid', 'remaining_balance', 'credit_notes',
            'created_by', 'posted_at', 'paid_at', 'voided_at',
            'created_at', 'updated_at',
            'tax_rate', 'due_at', 'credit_reason',
        ]

    def _paid_amount(self, obj):
        # Prefiere la anotación `_paid_sum` (list view) para evitar N+1; si no
        # está disponible (detail / post-save), cae a la propiedad (1 query).
        paid = getattr(obj, '_paid_sum', None)
        if paid is None:
            return obj.total - obj.remaining_balance
        return paid

    def get_amount_paid(self, obj):
        return str(self._paid_amount(obj))

    def get_remaining_balance(self, obj):
        return str(obj.total - self._paid_amount(obj))

    def get_created_by_name(self, obj):
        if obj.created_by:
            return f"{obj.created_by.first_name} {obj.created_by.last_name}".strip()
        return ''

    def get_owner_name(self, obj):
        from apps.core.subject_history import identity
        return identity(obj, 'owner').get('name') or (obj.owner.name if obj.owner_id else 'Desconocido')

    def get_pet_name(self, obj):
        from apps.core.subject_history import identity
        return identity(obj, 'pet').get('name') or (obj.pet.name if obj.pet_id else '')

    def get_owner_public_id(self, obj):
        return obj.owner.public_id if obj.owner_id and obj.owner.is_active else None

    def get_pet_public_id(self, obj):
        return obj.pet.public_id if obj.pet_id and obj.pet.is_active else None

    def get_historical_owner_public_id(self, obj):
        from apps.core.subject_history import identity
        return identity(obj, 'owner').get('uuid')

    def get_historical_pet_public_id(self, obj):
        from apps.core.subject_history import identity
        return identity(obj, 'pet').get('uuid')

    def get_subject_snapshot_source(self, obj):
        return (obj.subject_snapshot or {}).get('source', 'unknown')

    def get_credit_notes(self, obj):
        # Gateado por context: la lista NO lo pide → [] (sin N+1). El detalle
        # (InvoiceDetailView) setea `with_credit_notes` y prefetch.
        if not self.context.get('with_credit_notes'):
            return []
        out = []
        for cn in obj.credit_notes.all():
            rps = list(cn.refund_payments.all())
            # Una NC está revertida si todos sus reembolsos tienen contra-asiento
            # (reverse_credit_note revierte todos los pendientes de una vez).
            is_reversed = bool(rps) and all(list(rp.reversals.all()) for rp in rps)
            out.append({
                'public_id': str(cn.public_id),
                'total_refunded': str(cn.total_refunded),
                'reason_code': cn.reason_code,
                'reason_notes': cn.reason_notes,
                'issued_at': cn.issued_at,
                'reversed': is_reversed,
            })
        return out

    def validate_notes(self, value):
        from apps.core.sanitize import sanitize_text
        return sanitize_text(value or '', max_length=5000)

    def _get_request(self):
        """Acceso defensivo + assert. Loud failure si falta el context."""
        request = self.context.get('request')
        assert request is not None, (
            "InvoiceSerializer requiere 'request' en su context. "
            "Si lo invocas fuera de una view DRF (shell, admin, mgmt command), "
            "pasa context={'request': fake_request} con user.organization seteado."
        )
        return request

    def validate_owner(self, owner):
        return _validate_same_org(owner, self._get_request(), 'owner', 'InvoiceSerializer')

    def validate_pet(self, pet):
        return _validate_same_org(pet, self._get_request(), 'pet', 'InvoiceSerializer')

    def validate_appointment(self, appointment):
        return _validate_same_org(appointment, self._get_request(), 'appointment', 'InvoiceSerializer')

    def validate_medical_record(self, mr):
        return _validate_same_org(mr, self._get_request(), 'medical_record', 'InvoiceSerializer')

    def validate(self, data):
        # Resolver owner/pet/invoice_type considerando partial PATCH: los campos
        # ausentes heredan del instance actual. CREATE no tiene instance →
        # fallback None / default del modelo. Fix 4 (ADR p14): permite PATCH
        # minimalistas tipo {"notes": "x"} sin re-enviar pet/owner.
        owner = data.get('owner', getattr(self.instance, 'owner', None))
        pet = data.get('pet', getattr(self.instance, 'pet', None))
        invoice_type = data.get(
            'invoice_type',
            getattr(self.instance, 'invoice_type', None) or 'consultation',
        )

        # Owner genérico fuerza venta directa (ADR generic-client-direct-sale).
        if owner and getattr(owner, 'is_generic', False):
            data['invoice_type'] = 'direct_sale'
            invoice_type = 'direct_sale'

        # Requisito de pet por tipo (ADR p25):
        #   - consultation: pet obligatorio (el acto clínico requiere paciente).
        #   - direct_sale:  pet OPCIONAL, con o sin cliente registrado.
        # El mensaje conserva la subcadena "mascota es requerida" que asertan
        # los tests de regresión.
        if invoice_type == 'consultation' and pet is None:
            raise serializers.ValidationError(
                {'pet': 'La mascota es requerida para una factura de consulta.'}
            )

        # Guard de integridad (ADR p25): cuando el payload SETEA una mascota,
        # ésta debe pertenecer al propietario resuelto. NO es constraint de
        # modelo — mismo patrón que el owner_id guard de appointments. Acotado a
        # `'pet' in data` para no re-validar PATCH que solo tocan owner (no
        # rompe `test_patch_owner_same_org_preserves_existing_pet`).
        if 'pet' in data and pet is not None and owner is not None:
            if getattr(pet, 'is_generic', False) and not getattr(owner, 'is_generic', False):
                raise serializers.ValidationError(
                    {'pet': 'No se puede asignar el paciente genérico a un cliente registrado.'}
                )
            if pet.owner_id != owner.pk:
                raise serializers.ValidationError(
                    {'pet': 'La mascota no pertenece al propietario seleccionado.'}
                )

        return data

    def _linked_prescription(self, obj):
        """Receta de la consulta vinculada (OneToOne MedicalRecord.prescription)."""
        if not obj.medical_record_id:
            return None
        from apps.prescriptions.models import Prescription
        return Prescription.objects.for_organization(obj.organization).filter(
            medical_record_id=obj.medical_record_id,
        ).first()

    def get_prescription_public_id(self, obj):
        # Gateado a detalle: solo se usa para dispensar (panel de Cobros). En la
        # lista evita N+1 (obj.medical_record.prescription por cada factura).
        if not self.context.get('with_prescription_suggestions'):
            return None
        rx = self._linked_prescription(obj)
        return str(rx.public_id) if rx else None

    def get_prescription_suggestions(self, obj):
        """
        ADR p30: medicamentos de la receta para que recepción los dispense
        agregándolos a ESTA MISMA factura de consulta (no se crea factura
        aparte). Cada ítem trae las presentaciones disponibles para que
        recepción ELIJA formato y precio (Product puede tener varias). Gateado a
        detalle vía context para no incurrir N+1 en la lista.
        """
        if not self.context.get('with_prescription_suggestions'):
            return []
        if not obj.checkout_id:
            return []
        from .prescription_availability import build_checkout_prescription_suggestions
        return build_checkout_prescription_suggestions(
            obj.checkout,
            include_closed=True,
        )


class CreditNoteSerializer(serializers.ModelSerializer):
    """Solo lectura. Expone `public_id` (ADR p24) y la factura origen por public_id."""
    original_invoice_public_id = serializers.UUIDField(
        source='original_invoice.public_id', read_only=True,
    )
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CreditNote
        fields = [
            'public_id', 'status', 'original_invoice_public_id',
            'reason_code', 'reason_notes', 'total_refunded',
            'issued_at', 'created_by_name', 'created_at',
        ]
        read_only_fields = fields

    def get_created_by_name(self, obj):
        if obj.created_by:
            return f"{obj.created_by.first_name} {obj.created_by.last_name}".strip() or obj.created_by.username
        return ''


class CheckoutItemSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source='service.name', read_only=True)
    presentation_name = serializers.SerializerMethodField()
    product_requires_prescription = serializers.BooleanField(
        source='presentation.product.requires_prescription', read_only=True,
    )
    lot_number = serializers.CharField(source='lot.lot_number', read_only=True)

    class Meta:
        model = CheckoutItem
        fields = [
            'id', 'description', 'quantity', 'unit_price', 'subtotal',
            'discount_type', 'discount_value', 'source_kind', 'service',
            'service_name', 'presentation', 'presentation_name', 'lot',
            'conversion_factor_snapshot',
            'lot_number', 'prescription_item', 'product_requires_prescription',
            'source_invoice_item', 'baseline_kind',
            'required_replacement_baseline', 'fulfillment_source',
            'regulatory_revision',
        ]
        read_only_fields = fields

    def get_presentation_name(self, obj):
        return str(obj.presentation) if obj.presentation_id else None


class CheckoutSerializer(serializers.ModelSerializer):
    items = CheckoutItemSerializer(many=True, read_only=True)
    preparation_readiness = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()
    correction_status = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    customer_public_id = serializers.SerializerMethodField()
    pet_name = serializers.SerializerMethodField()
    pet_public_id = serializers.SerializerMethodField()
    historical_customer_public_id = serializers.SerializerMethodField()
    historical_pet_public_id = serializers.SerializerMethodField()
    medical_record_public_id = serializers.UUIDField(source='medical_record.public_id', read_only=True, allow_null=True)
    invoice_public_id = serializers.SerializerMethodField()
    prescription_public_id = serializers.SerializerMethodField()
    prescription_suggestions = serializers.SerializerMethodField()
    open_dispute = serializers.SerializerMethodField()

    class Meta:
        model = Checkout
        fields = [
            'public_id', 'origin', 'kind', 'medical_record',
            'medical_record_public_id', 'lifecycle', 'completion_kind', 'version',
            'owner', 'customer', 'customer_public_id', 'customer_name',
            'historical_customer_public_id', 'historical_pet_public_id', 'pet',
            'pet_public_id', 'pet_name', 'subtotal', 'tax_rate', 'tax_amount',
            'total', 'notes', 'correction_due_at', 'expires_at',
            'operational_hold', 'correction_status', 'invoice_public_id',
            'prescription_public_id', 'created_at', 'updated_at', 'items',
            'prescription_suggestions', 'preparation_readiness', 'actions',
            'open_dispute',
        ]
        read_only_fields = fields

    def _read_projection(self, obj):
        cached = getattr(obj, '_billing_read_projection', None)
        if cached is None:
            from .checkout_services import checkout_readiness_snapshot
            cached = checkout_readiness_snapshot(obj)
            obj._billing_read_projection = cached
        return cached

    def get_customer_name(self, obj):
        from apps.core.subject_history import identity
        return identity(obj, 'owner').get('name') or (obj.customer.name if obj.customer_id else 'Desconocido')

    def get_pet_name(self, obj):
        from apps.core.subject_history import identity
        return identity(obj, 'pet').get('name') or (obj.pet.name if obj.pet_id else '')

    def get_customer_public_id(self, obj):
        return obj.customer.public_id if obj.customer_id and obj.customer.is_active else None

    def get_pet_public_id(self, obj):
        return obj.pet.public_id if obj.pet_id and obj.pet.is_active else None

    def get_historical_customer_public_id(self, obj):
        from apps.core.subject_history import identity
        return identity(obj, 'owner').get('uuid')

    def get_historical_pet_public_id(self, obj):
        from apps.core.subject_history import identity
        return identity(obj, 'pet').get('uuid')

    def get_preparation_readiness(self, obj):
        return self._read_projection(obj)['preparation_readiness']

    def get_actions(self, obj):
        return self._read_projection(obj)['actions']

    def get_open_dispute(self, obj):
        dispute = next(
            (row for row in obj.disputes.all() if row.status == 'open'), None,
        )
        return CheckoutDisputeSerializer(dispute).data if dispute else None

    def get_correction_status(self, obj):
        if obj.kind != 'replacement' or obj.lifecycle != 'open':
            return None
        if obj.correction_due_at and obj.correction_due_at < timezone.now():
            return 'correction_overdue'
        return 'correction_pending'

    def get_invoice_public_id(self, obj):
        try:
            return str(obj.invoice.public_id)
        except Exception:
            return None

    def get_prescription_public_id(self, obj):
        if not obj.medical_record_id:
            return None
        from apps.prescriptions.models import Prescription
        prescription = Prescription.objects.for_organization(obj.organization).filter(
            medical_record_id=obj.medical_record_id,
        ).first()
        return str(prescription.public_id) if prescription else None

    def get_prescription_suggestions(self, obj):
        from .prescription_availability import build_checkout_prescription_suggestions
        return build_checkout_prescription_suggestions(obj)


class CheckoutDisputeSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source='owner.get_full_name', read_only=True)
    invoice_public_id = serializers.UUIDField(
        source='invoice.public_id', read_only=True, allow_null=True,
    )

    class Meta:
        model = CheckoutDispute
        fields = [
            'public_id', 'checkout', 'invoice_public_id', 'status',
            'disputed_item_ids', 'disputed_amount', 'statement', 'evidence',
            'owner', 'owner_name', 'opened_by', 'opened_at', 'review_due_at',
            'resolution', 'resolution_reason', 'resolution_evidence',
            'resolved_by', 'resolved_at', 'created_at', 'updated_at',
        ]
        read_only_fields = fields


class CheckoutEstimateSerializer(serializers.ModelSerializer):
    checkout_public_id = serializers.UUIDField(source='checkout.public_id', read_only=True)

    class Meta:
        model = CheckoutEstimate
        fields = [
            'public_id', 'checkout_public_id', 'checkout_version', 'snapshot',
            'content_hash', 'generated_at',
        ]
        read_only_fields = fields
