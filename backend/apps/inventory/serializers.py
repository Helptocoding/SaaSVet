import re
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers
from .models import Product, Presentation, StockLot, StockMovement, MedicalRecordProduct

PRODUCT_NAME_REGEX = re.compile(r"^[A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\s\.\-\(\)\/\%\+]+$")


def _validate_price(value, field_name='sale_price'):
    if value is None:
        raise serializers.ValidationError({field_name: "El precio es obligatorio."})
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise serializers.ValidationError({field_name: "Valor inválido."})
    if d <= Decimal('0.00'):
        raise serializers.ValidationError({field_name: "El precio debe ser mayor a 0."})


def _validate_non_negative(value, field_name, label):
    if value is None:
        raise serializers.ValidationError({field_name: f"{label} es obligatorio."})
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise serializers.ValidationError({field_name: "Valor inválido."})
    if d < Decimal('0'):
        raise serializers.ValidationError({field_name: f"{label} no puede ser negativo."})


class PresentationSerializer(serializers.ModelSerializer):
    product = serializers.IntegerField(source='product_id', read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)
    base_unit_display = serializers.CharField(source='get_base_unit_display', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_public_id = serializers.UUIDField(source='product.public_id', read_only=True)
    requires_prescription = serializers.BooleanField(source='product.requires_prescription', read_only=True)
    tracks_lots = serializers.BooleanField(source='product.tracks_lots', read_only=True)
    # ADR p31: stock real en unidades base (desde Product)
    stock_quantity = serializers.DecimalField(
        source='product.stock_quantity', max_digits=14, decimal_places=4, read_only=True,
    )
    product_base_unit = serializers.CharField(source='product.base_unit', read_only=True)

    class Meta:
        model = Presentation
        fields = [
            'id', 'public_id', 'product', 'product_public_id', 'name', 'product_name',
            'base_unit', 'base_unit_display', 'quantity', 'conversion_factor',
            'sale_price', 'purchase_price', 'stock', 'min_stock', 'is_low_stock',
            'stock_quantity', 'product_base_unit',
            'barcode', 'requires_prescription', 'tracks_lots',
        ]
        read_only_fields = [
            'id', 'public_id', 'product', 'product_name', 'requires_prescription',
            'stock_quantity', 'product_base_unit',
        ]

    def validate_sale_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("El precio de venta debe ser mayor a 0.")
        return value

    def validate_conversion_factor(self, value):
        from .units import validated_conversion_factor
        try:
            return validated_conversion_factor(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)

    def validate_stock(self, value):
        if value < 0:
            raise serializers.ValidationError("El stock no puede ser negativo.")
        return value

    def validate_min_stock(self, value):
        if value < 0:
            raise serializers.ValidationError("El stock mínimo no puede ser negativo.")
        return value


class PresentationCreateSerializer(serializers.ModelSerializer):
    """Serializer for adding a new presentation variant to an existing product."""

    name = serializers.CharField(required=False, allow_blank=True, default='')
    stock = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=True, allow_null=False
    )
    sale_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=True, allow_null=False
    )

    class Meta:
        model = Presentation
        fields = [
            'id', 'name', 'base_unit', 'quantity', 'conversion_factor',
            'sale_price', 'purchase_price', 'stock', 'min_stock', 'barcode',
        ]
        read_only_fields = ['id']

    def validate_sale_price(self, value):
        _validate_price(value)
        return value

    def validate_conversion_factor(self, value):
        from .units import validated_conversion_factor
        try:
            return validated_conversion_factor(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)

    def validate_stock(self, value):
        _validate_non_negative(value, 'stock', 'El stock')
        return value

    def validate_min_stock(self, value):
        _validate_non_negative(value, 'min_stock', 'El stock mínimo')
        return value


class ProductSerializer(serializers.ModelSerializer):
    presentations = PresentationSerializer(many=True, read_only=True)
    # Backward-compat: first presentation for existing frontend code
    presentation = serializers.SerializerMethodField()
    # Write-only input for product creation
    presentation_input = PresentationCreateSerializer(
        write_only=True, required=True, allow_null=False
    )
    internal_code = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default='',
    )
    base_unit_display = serializers.CharField(source='get_base_unit_display', read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'public_id', 'name', 'internal_code', 'description',
            'category', 'requires_prescription', 'is_active',
            # ADR p31: stock real en unidades base
            'base_unit', 'base_unit_display', 'stock_quantity', 'min_stock',
            # Trazabilidad por lote (spec 2026-07-10) — opt-in por producto.
            'manufacturer', 'tracks_lots',
            'presentations', 'presentation', 'presentation_input',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'public_id', 'stock_quantity', 'created_at', 'updated_at']

    def get_presentation(self, obj):
        first = obj.presentations.first() if hasattr(obj, '_prefetched_objects_cache') else obj.presentations.first()
        if first is None:
            return None
        return PresentationSerializer(first).data

    def validate_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("El nombre del producto es requerido.")
        if not PRODUCT_NAME_REGEX.match(value.strip()):
            raise serializers.ValidationError(
                "El nombre del producto contiene caracteres no permitidos. "
                "Use letras, números, espacios y los símbolos: . - ( ) / % +"
            )
        return value.strip()

    def validate(self, data):
        pres = data.get('presentation_input')
        if not pres:
            raise serializers.ValidationError("Se requiere al menos una presentación.")
        return data

    def validate_internal_code(self, value):
        if not value:
            return value
        request = self.context.get('request')
        if request:
            qs = Product.objects.filter(
                organization=request.user.organization,
                internal_code=value,
            )
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    "Este código ya está en uso en tu organización."
                )
        return value

    @transaction.atomic
    def create(self, validated_data):
        pres_data = validated_data.pop('presentation_input', None)

        organization = self.context['request'].user.organization
        validated_data.pop('organization', None)

        internal_code = validated_data.pop('internal_code', '').strip()

        if not internal_code:
            product = Product.objects.create(
                **validated_data,
                organization=organization,
                internal_code=f'__tmp_{uuid4().hex}',
            )
            product.internal_code = f'PROD-{organization.id}-{product.pk:04d}'
            product.save()
        else:
            product = Product.objects.create(
                **validated_data,
                organization=organization,
                internal_code=internal_code,
            )

        if pres_data:
            pres_serializer = PresentationCreateSerializer(
                data=pres_data,
                context=self.context
            )
            pres_serializer.is_valid(raise_exception=True)

            data = dict(pres_serializer.validated_data)
            if not data.get('name'):
                data['name'] = product.name

            pres = Presentation(product=product, organization=organization, **data)
            pres.full_clean()
            Presentation.objects.bulk_create([pres])

            # ADR p31: poblar Product.stock_quantity desde el stock inicial.
            # bulk_create omite signals, por eso se hace aquí explícitamente.
            from decimal import Decimal as _D
            cf = _D(str(pres.conversion_factor))
            initial_stock = _D(str(data.get('stock') or 0)) * cf
            min_stock_base = _D(str(data.get('min_stock') or 0)) * cf
            Product.all_objects.filter(pk=product.pk).update(
                base_unit=data.get('base_unit', ''),
                stock_quantity=initial_stock,
                min_stock=min_stock_base,
            )
            product.refresh_from_db()

        return product

    @transaction.atomic
    def update(self, instance, validated_data):
        pres_data = validated_data.pop('presentation_input', None)
        validated_data.pop('organization', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if pres_data is not None:
            first_pres = instance.presentations.first()
            if first_pres is None:
                raise serializers.ValidationError({
                    'presentation': 'Este producto no tiene presentaciones. Agrega una primero.'
                })

            # pres_data viene como lista de dicts (many=True)
            if isinstance(pres_data, list):
                update_data = pres_data[0] if pres_data else {}
            else:
                update_data = pres_data

            if 'stock' in update_data and update_data['stock'] != first_pres.stock:
                raise serializers.ValidationError({
                    'presentation': {
                        'stock': 'Usa el endpoint de ajuste de stock para modificar existencias.'
                    }
                })
            update_data.pop('name', None)  # name is immutable via this endpoint
            for attr, value in update_data.items():
                setattr(first_pres, attr, value)
            first_pres.save()

            # ADR p31: sincronizar base_unit y min_stock en Product cuando cambia la presentación.
            # stock_quantity NO se toca aquí — lo gestiona apply_stock_movement.
            from decimal import Decimal as _D
            cf = _D(str(first_pres.conversion_factor))
            min_base = _D(str(first_pres.min_stock or 0)) * cf
            Product.all_objects.filter(pk=instance.pk).update(
                base_unit=first_pres.base_unit or '',
                min_stock=min_base,
            )
        return instance


class StockMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='presentation.product.name', read_only=True)
    presentation_name = serializers.CharField(source='presentation.name', read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = StockMovement
        fields = [
            'id', 'presentation', 'product_name', 'presentation_name',
            'movement_type', 'quantity', 'reason', 'medical_record',
            'created_by', 'created_by_name', 'created_at',
        ]
        read_only_fields = ['id', 'created_at', 'created_by']

    def get_created_by_name(self, obj):
        if obj.created_by:
            return f"{obj.created_by.first_name} {obj.created_by.last_name}".strip()
        return ''


class StockAdjustmentSerializer(serializers.Serializer):
    movement_type = serializers.ChoiceField(choices=['in', 'out', 'adjustment'])
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'))
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


class StockLotSerializer(serializers.ModelSerializer):
    """Lectura de lotes (spec 2026-07-10). effective_status derivado (no columna)."""
    effective_status = serializers.CharField(read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)

    class Meta:
        model = StockLot
        fields = [
            'id', 'public_id', 'product', 'product_name', 'lot_number',
            'expiry_date', 'received_at', 'quantity_on_hand', 'supplier_name',
            'status', 'effective_status', 'created_at',
        ]
        read_only_fields = fields


class StockReceptionLineSerializer(serializers.Serializer):
    # lot_number obligatorio: la recepción por lotes existe para trazar el lote.
    lot_number = serializers.CharField(max_length=100)
    expiry_date = serializers.DateField(required=False, allow_null=True)
    # En unidades de PRESENTACIÓN (el backend convierte con conversion_factor).
    quantity = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal('0.01'),
    )

    def validate_lot_number(self, value):
        value = (value or '').strip()
        if not value:
            raise serializers.ValidationError("El número de lote es obligatorio.")
        return value


class StockReceptionSerializer(serializers.Serializer):
    """Recepción de mercancía multi-lote (B1): una presentación + N líneas de lote."""
    supplier_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default='',
    )
    received_at = serializers.DateField(required=False, allow_null=True)
    lots = StockReceptionLineSerializer(many=True)

    def validate_lots(self, value):
        if not value:
            raise serializers.ValidationError("Agrega al menos un lote.")
        return value


class LotDiscardSerializer(serializers.Serializer):
    """Merma/write-off de un lote (B2c). quantity en base-units; default = saldo."""
    quantity = serializers.DecimalField(
        max_digits=14, decimal_places=4, required=False, allow_null=True,
        min_value=Decimal('0.0001'),
    )
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


class LotStatusSerializer(serializers.Serializer):
    """Cambio de estado administrativo del lote (B2c)."""
    status = serializers.ChoiceField(choices=['active', 'quarantined', 'recalled'])


class MedicalRecordProductSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='presentation.product.name', read_only=True)
    presentation_name = serializers.CharField(source='presentation.name', read_only=True)
    base_unit = serializers.CharField(source='presentation.base_unit', read_only=True)
    base_unit_display = serializers.CharField(
        source='presentation.get_base_unit_display', read_only=True
    )
    unit_price = serializers.DecimalField(
        source='presentation.sale_price', max_digits=10, decimal_places=2, read_only=True
    )
    # Trazabilidad por lote (B2a). `lot` write = PK (body FK, ADR p18). Metadata read.
    tracks_lots = serializers.BooleanField(source='presentation.product.tracks_lots', read_only=True)
    lot_number = serializers.CharField(source='lot.lot_number', read_only=True)
    lot_expiry = serializers.DateField(source='lot.expiry_date', read_only=True)
    lot_effective_status = serializers.CharField(source='lot.effective_status', read_only=True)

    class Meta:
        model = MedicalRecordProduct
        fields = [
            'id', 'presentation', 'product_name', 'presentation_name',
            'base_unit', 'base_unit_display', 'quantity', 'unit_price', 'cost_behavior',
            'lot', 'tracks_lots', 'lot_number', 'lot_expiry', 'lot_effective_status',
        ]
        validators = []

    def validate_presentation(self, presentation):
        if presentation and presentation.organization != self.context['request'].user.organization:
            raise serializers.ValidationError('Acceso inválido.')
        return presentation

    def validate_lot(self, lot):
        if lot is None:
            return lot
        request = self.context.get('request')
        if request and lot.organization_id != request.user.organization_id:
            raise serializers.ValidationError('Lote fuera de tu organización.')
        return lot

    def validate(self, attrs):
        presentation = attrs.get('presentation')
        if not presentation:
            return attrs
        product = presentation.product

        # Lote: obligatorio y consumible si el producto lo trackea (spec P1/P2).
        lot = attrs.get('lot')
        if product.tracks_lots:
            if lot is None:
                raise serializers.ValidationError({'lot': 'Selecciona el lote a consumir.'})
            if lot.product_id != product.id:
                raise serializers.ValidationError({'lot': 'El lote no corresponde a este producto.'})
            if not lot.is_consumable:
                raise serializers.ValidationError(
                    {'lot': f"El lote {lot.lot_number} no está disponible ({lot.effective_status})."}
                )
        elif lot is not None:
            raise serializers.ValidationError({'lot': 'Este producto no usa control de lotes.'})

        if not product.requires_prescription:
            return attrs
        medical_record = self.context.get('medical_record')
        if not medical_record:
            return attrs
        from apps.prescriptions.models import PrescriptionItem
        has_active_rx = PrescriptionItem.objects.filter(
            prescription__medical_record=medical_record,
            prescription__is_active=True,
            product=product,
        ).exists()
        if not has_active_rx:
            raise serializers.ValidationError(
                f"{product.name} requiere receta médica activa. "
                "Crea la receta antes de agregar este producto a la consulta."
            )
        return attrs
