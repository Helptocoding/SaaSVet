import json
from datetime import date, timedelta
from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from rest_framework import serializers
from apps.core.sanitize import sanitize_text
from .models import ConsultationAssessment, MedicalRecord, MedicalRecordService, SurgeryRecord, VaccineRecord, VitalSigns
from .models import _get_last_weight
from .policies import can_close_medical_record, can_modify_medical_record_charges, medical_record_has_clinical_content


# Claves permitidas en MedicalRecord.consultation_draft (scratchpad de UI, no
# fuente de verdad). Se amplia 1 clave por protocolo clinico nuevo. Evita que el
# campo se vuelva un cajon de sastre donde cualquier componente escriba cualquier
# cosa. Ver docs/modules/medical_records.md (principio de protocolos).
ALLOWED_CONSULTATION_DRAFT_KEYS = {"vaccine", "general", "surgery"}


def _validate_weight_change(pet, new_weight, force=False):
    """
    Detecta cambio brusco de peso (>150%) buscando el último peso en VitalSigns
    y MedicalRecord via _get_last_weight. Compartida por ambos serializers.
    
    Usa el patrón de metadatos con '__' para señalizar force_weight_required.
    """
    last_weight = _get_last_weight(pet)
    if not last_weight:
        return
    ratio = float(new_weight) / float(last_weight)
    if ratio > 2.5 or ratio < 0.4:
        if not force:
            raise serializers.ValidationError({
                'weight': [
                    f'Cambio brusco de peso: último registro {last_weight} kg → '
                    f'nuevo {new_weight} kg. Confirme para continuar.'
                ],
                '__force_weight_required': True,
            })


class VitalSignsSerializer(serializers.ModelSerializer):
    recorded_by_name = serializers.SerializerMethodField(read_only=True)
    weight = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, allow_null=True,
        error_messages={"invalid": "El peso debe ser un número válido."},
    )
    temperature = serializers.DecimalField(
        max_digits=4, decimal_places=1, required=False, allow_null=True,
        error_messages={"invalid": "La temperatura debe ser un número válido."},
    )
    heart_rate = serializers.IntegerField(
        required=False, allow_null=True,
        error_messages={"invalid": "La frecuencia cardíaca debe ser un número entero."},
    )
    respiratory_rate = serializers.IntegerField(
        required=False, allow_null=True,
        error_messages={"invalid": "La frecuencia respiratoria debe ser un número entero."},
    )
    force_weight = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = VitalSigns
        fields = [
            'id', 'weight', 'temperature', 'heart_rate', 'respiratory_rate',
            'force_weight', 'recorded_by_name', 'recorded_at', 'created_at',
        ]
        read_only_fields = ['id', 'recorded_by_name', 'created_at']

    def get_recorded_by_name(self, obj):
        return obj.recorded_by.get_full_name() if obj.recorded_by else None

    def validate_recorded_at(self, value):
        now = timezone.now()
        if value > now:
            raise serializers.ValidationError("La fecha no puede estar en el futuro.")
        if value < now - timedelta(days=3650):
            raise serializers.ValidationError("La fecha no puede ser mayor a 10 años en el pasado.")
        return value

    def validate_weight(self, value):
        if value is not None:
            if not (Decimal('0.01') <= value <= Decimal('200.00')):
                raise serializers.ValidationError("El peso debe estar entre 0.01 y 200 kg.")
            pet = self.context.get('pet')
            if pet:
                force = bool(self.initial_data.get('force_weight', False))
                _validate_weight_change(pet, value, force=force)
        return value

    def validate_temperature(self, value):
        if value is not None and not (Decimal('30.0') <= value <= Decimal('45.0')):
            raise serializers.ValidationError("La temperatura debe estar entre 30.0 y 45.0 °C.")
        return value

    def validate_heart_rate(self, value):
        if value is not None and not (20 <= value <= 300):
            raise serializers.ValidationError("La frecuencia cardíaca debe estar entre 20 y 300 bpm.")
        return value

    def validate_respiratory_rate(self, value):
        if value is not None and not (5 <= value <= 120):
            raise serializers.ValidationError("La frecuencia respiratoria debe estar entre 5 y 120 rpm.")
        return value

    def validate(self, data):
        # force_weight es write_only y no es campo del modelo — eliminarlo antes de .create()
        data.pop('force_weight', None)

        if not any([
            data.get('weight') is not None,
            data.get('temperature') is not None,
            data.get('heart_rate') is not None,
            data.get('respiratory_rate') is not None,
        ]):
            raise serializers.ValidationError("Debe proporcionar al menos un signo vital.")
        temp = data.get('temperature')
        hr   = data.get('heart_rate')
        if temp is not None and hr is not None and temp >= Decimal('42.0') and hr < 40:
            raise serializers.ValidationError(
                "Temperatura y frecuencia cardíaca inconsistentes. Verifique los valores."
            )
        return data


class MedicalRecordSerializer(serializers.ModelSerializer):
    pet_name = serializers.CharField(source='pet.name', read_only=True)
    # Día 6 B1: pet_public_id expuesto para que frontend reciba UUID en lugar
    # de PK al embedder MR. Evita filtrado ?pet=<pk> en query params.
    pet_public_id = serializers.UUIDField(source='pet.public_id', read_only=True)
    veterinarian_name = serializers.SerializerMethodField()
    appointment_date = serializers.SerializerMethodField()
    appointment_public_id = serializers.UUIDField(source='appointment.public_id', read_only=True, allow_null=True)
    products_used = serializers.SerializerMethodField()
    prescription_id = serializers.ReadOnlyField()
    prescription_public_id = serializers.UUIDField(source='prescription.public_id', read_only=True, allow_null=True)
    prescription_summary = serializers.SerializerMethodField()
    invoice_id = serializers.ReadOnlyField()
    invoice_public_id = serializers.SerializerMethodField()
    invoice_status = serializers.SerializerMethodField()
    status = serializers.CharField(read_only=True)
    closed_at = serializers.DateTimeField(read_only=True)
    closed_by = serializers.PrimaryKeyRelatedField(read_only=True)
    can_modify_charges = serializers.SerializerMethodField()
    can_close = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    latest_vitals = serializers.SerializerMethodField()
    # Protocolo General: valoración estructurada (SOAP S/O). None si la consulta
    # no capturó SOAP estructurado (general "clásica" o aún sin materializar).
    consultation_assessment = serializers.SerializerMethodField()

    def get_invoice_public_id(self, obj):
        # invoice_id es ReadOnlyField sobre property o cached value; resolver
        # public_id requiere instance lookup. Evita N+1 si el caller hace
        # select_related('invoice').
        invoice = getattr(obj, 'invoice', None)
        return str(invoice.public_id) if invoice else None

    def get_invoice_status(self, obj):
        # Estado de la factura vinculada (draft/confirmed/paid/cancelled) para
        # que el Timeline muestre el badge "Cobro". None si la consulta aún no
        # tiene factura (clínica sin cargos antes de cerrar).
        invoice = getattr(obj, 'invoice', None)
        return invoice.status if invoice else None

    force_weight = serializers.BooleanField(write_only=True, required=False, default=False)

    # Scratchpad de UI (borrador de secciones en progreso). Writable pero NO es
    # fuente de verdad — ver comentario del modelo y validate_consultation_draft.
    consultation_draft = serializers.JSONField(required=False)

    weight = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        required=False,
        allow_null=True,
        validators=[
            MinValueValidator(Decimal('0.01'), message='El peso debe ser mayor a 0.'),
            # límite funcional (dominio clínico); el técnico de DB es 999.99 (max_digits=5)
            MaxValueValidator(Decimal('200.00'), message='El peso no puede superar 200 kg.'),
        ],
    )

    class Meta:
        model = MedicalRecord
        fields = [
            'id', 'public_id',
            'pet', 'pet_name', 'pet_public_id',
            'veterinarian', 'veterinarian_name',
            'appointment', 'appointment_public_id', 'appointment_date',
            'consultation_type',
            'diagnosis', 'treatment', 'notes', 'weight', 'force_weight', 'created_at', 'updated_at',
            'consultation_draft',
            'products_used',
            'prescription_id', 'prescription_public_id', 'prescription_summary',
            'invoice_id', 'invoice_public_id', 'invoice_status',
            'latest_vitals',
            'consultation_assessment',
            'status', 'closed_at', 'closed_by',
            'can_modify_charges', 'can_close', 'can_delete',
        ]
        read_only_fields = [
            'id', 'public_id', 'pet_public_id', 'appointment_public_id',
            'prescription_public_id', 'invoice_public_id', 'invoice_status',
            'created_at', 'updated_at', 'prescription_id', 'invoice_id',
            'status', 'closed_at', 'closed_by',
            'organization',
        ]

    def validate(self, data):
        data = super().validate(data)
        weight = data.get('weight')
        force_weight = data.pop('force_weight', False)

        # Validación explícita de longitud (PostgreSQL no respeta max_length en TextField).
        # Si el valor enviado es igual al existente en DB y supera el límite,
        # se omite la validación para no bloquear edición de otros campos
        # en registros históricos creados antes de que se estableció el límite.
        for field, limit in (('diagnosis', 400), ('treatment', 400), ('notes', 5000)):
            if field in data and data[field]:
                existing_value = getattr(self.instance, field, None) if self.instance else None
                if existing_value and existing_value == data[field] and len(data[field]) > limit:
                    continue
                if len(data[field]) > limit:
                    raise serializers.ValidationError({field: f'Máximo {limit} caracteres.'})
                data[field] = sanitize_text(data[field], max_length=limit)

        # El diagnóstico se valida al cerrar la consulta (close_medical_record),
        # no al crear. Esto permite pre-crear registros desde el flujo "Atender ahora"
        # y llenarlos progresivamente en el stepper.

        # Validación de cambio brusco de peso (solo en actualizaciones con peso informado)
        if weight and self.instance:
            try:
                _validate_weight_change(self.instance.pet, weight, force=force_weight)
            except serializers.ValidationError as exc:
                raise serializers.ValidationError({'weight': exc.detail})
        return data

    def update(self, instance, validated_data):
        if instance.status == MedicalRecord.Status.CLOSED:
            raise serializers.ValidationError({
                "non_field_errors": ["No se puede modificar una consulta cerrada."]
            })
        validated_data.pop('organization', None)
        return super().update(instance, validated_data)

    def validate_pet(self, pet):
        if pet and pet.organization != self.context['request'].user.organization:
            raise serializers.ValidationError('Acceso inválido.')
        return pet

    def validate_consultation_draft(self, value):
        # Valida ESTRUCTURA, no contenido. Solo claves whitelisteadas + tope de
        # tamaño (evita que el scratchpad se vuelva un cajon de sastre / payload
        # gigante). El contenido de cada slice lo valida su protocolo al finalizar
        # (p.ej. VaccineRecordSerializer en apply_consultation_draft_on_close).
        if not isinstance(value, dict):
            raise serializers.ValidationError("Formato inválido.")
        extra = set(value) - ALLOWED_CONSULTATION_DRAFT_KEYS
        if extra:
            raise serializers.ValidationError(
                f"Claves no permitidas en el borrador: {sorted(extra)}"
            )
        if len(json.dumps(value)) > 16_384:  # ~16 KB
            raise serializers.ValidationError("El borrador es demasiado grande.")
        return value

    def validate_appointment(self, appointment):
        if appointment and appointment.organization != self.context['request'].user.organization:
            raise serializers.ValidationError('Acceso inválido.')
        return appointment

    def validate_veterinarian(self, vet):
        if vet and vet.organization != self.context['request'].user.organization:
            raise serializers.ValidationError('Acceso inválido.')
        return vet

    def get_veterinarian_name(self, obj):
        if obj.veterinarian:
            return f"{obj.veterinarian.first_name} {obj.veterinarian.last_name}"
        return ""

    def get_appointment_date(self, obj):
        if obj.appointment:
            return obj.appointment.date
        return None

    def get_products_used(self, obj):
        from apps.inventory.serializers import MedicalRecordProductSerializer
        return MedicalRecordProductSerializer(obj.products_used.all(), many=True).data

    def get_prescription_summary(self, obj):
        prescription = getattr(obj, 'prescription', None)
        if not prescription:
            return None

        from apps.prescriptions.serializers import PrescriptionItemSerializer

        return {
            'id': prescription.id,
            'public_id': str(prescription.public_id),
            'notes': prescription.notes,
            'items': PrescriptionItemSerializer(
                prescription.items.select_related('product').prefetch_related('product__presentations').all(),
                many=True,
            ).data,
            'created_at': prescription.created_at,
        }

    def _request_user(self):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        return request.user

    def get_can_modify_charges(self, obj):
        user = self._request_user()
        if not user:
            return False
        return can_modify_medical_record_charges(user, obj)

    def get_can_close(self, obj):
        user = self._request_user()
        if not user:
            return False
        return can_close_medical_record(user, obj)

    def get_can_delete(self, obj):
        user = self._request_user()
        if not user:
            return False
        if not can_modify_medical_record_charges(user, obj):
            return False
        return not medical_record_has_clinical_content(obj)

    def get_latest_vitals(self, obj):
        vital = obj.vital_signs.order_by('-recorded_at', '-created_at').first()
        if not vital:
            return None
        return {
            'weight': vital.weight,
            'temperature': vital.temperature,
            'heart_rate': vital.heart_rate,
            'respiratory_rate': vital.respiratory_rate,
            'recorded_at': vital.recorded_at,
        }

    def get_consultation_assessment(self, obj):
        # Prefetched via 'consultation_assessments' en las views (anti N+1).
        # Ordering del modelo = -created_at → el primero es el más reciente.
        assessment = next(iter(obj.consultation_assessments.all()), None)
        return ConsultationAssessmentSerializer(assessment).data if assessment else None


class MedicalRecordDetailSerializer(MedicalRecordSerializer):
    services_used = serializers.SerializerMethodField()

    class Meta(MedicalRecordSerializer.Meta):
        fields = MedicalRecordSerializer.Meta.fields + ['organization', 'services_used']

    def get_services_used(self, obj):
        return MedicalRecordServiceSerializer(
            obj.services_used.all(), many=True,
            context=self.context,
        ).data


class MedicalRecordServiceSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source='service.name', read_only=True)
    unit_price = serializers.DecimalField(
        source='service.base_price', max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = MedicalRecordService
        fields = ['id', 'service', 'service_name', 'quantity', 'unit_price']


class VaccineRecordSerializer(serializers.ModelSerializer):
    status = serializers.CharField(read_only=True)
    applied_by_name = serializers.SerializerMethodField()
    # Día 6 Fase 5: VaccineRecord promovido a modelo público (anexo seguridad).
    # Expone public_id y FK embeds en formato UUID para deep links.
    pet_public_id = serializers.UUIDField(source='pet.public_id', read_only=True)
    applied_by_public_id = serializers.UUIDField(
        source='applied_by.public_id', read_only=True, allow_null=True
    )
    medical_record_public_id = serializers.UUIDField(
        source='medical_record.public_id', read_only=True, allow_null=True
    )
    # A2: trazabilidad por lote (snapshot denormalizado, solo lectura).
    product_public_id = serializers.UUIDField(
        source='product.public_id', read_only=True, allow_null=True
    )
    product_name = serializers.CharField(source='product.name', read_only=True, allow_null=True)

    class Meta:
        model = VaccineRecord
        fields = [
            'id', 'public_id',
            'pet', 'pet_public_id',
            'vaccine_name', 'application_date', 'next_due_date',
            'applied_by', 'applied_by_public_id', 'applied_by_name',
            'notes',
            'medical_record', 'medical_record_public_id',
            'product', 'product_public_id', 'product_name',
            'lot', 'lot_number', 'lot_expiry', 'manufacturer',
            'status', 'created_at',
        ]
        read_only_fields = [
            'id', 'public_id', 'pet_public_id', 'applied_by_public_id',
            'medical_record_public_id', 'product', 'product_public_id',
            'product_name', 'lot', 'lot_number', 'lot_expiry', 'manufacturer',
            'status', 'created_at',
        ]

    def get_applied_by_name(self, obj):
        if obj.applied_by:
            return f"{obj.applied_by.first_name} {obj.applied_by.last_name}".strip()
        return None

    def validate_vaccine_name(self, value):
        clean = sanitize_text(value or '', max_length=255)
        if not clean.strip():
            raise serializers.ValidationError("El nombre de la vacuna es requerido.")
        return clean

    def validate(self, attrs):
        # Defensa en profundidad (espeja vaccineProtocol.validate del frontend):
        # el refuerzo debe ser posterior a la aplicación.
        app = attrs.get('application_date')
        due = attrs.get('next_due_date')
        if app and due and due <= app:
            raise serializers.ValidationError(
                {"next_due_date": "El refuerzo debe ser posterior a la fecha de aplicación."}
            )
        return attrs

    def validate_application_date(self, value):
        if value > date.today():
            raise serializers.ValidationError("La fecha de aplicación no puede ser en el futuro.")
        return value

    def validate_pet(self, pet):
        if pet and pet.organization != self.context['request'].user.organization:
            raise serializers.ValidationError('Acceso inválido.')
        return pet


class SurgeryRecordSerializer(serializers.ModelSerializer):
    """Protocolo Cirugía (A3). Valida el mínimo obligatorio (PreOp+Proc+Recup)."""
    surgeon_name = serializers.SerializerMethodField()

    class Meta:
        model = SurgeryRecord
        fields = [
            'id', 'public_id', 'pet', 'medical_record', 'surgeon', 'surgeon_name',
            'preop_diagnosis', 'surgery_type', 'asa_class', 'asa_emergency',
            'anesthesia_type', 'procedure', 'wound_class', 'findings', 'complications',
            'postop_instructions', 'suture_removal_date', 'protocol_version', 'created_at',
        ]
        read_only_fields = [
            'id', 'public_id', 'pet', 'medical_record', 'surgeon', 'surgeon_name',
            'protocol_version', 'created_at',
        ]

    def get_surgeon_name(self, obj):
        if obj.surgeon:
            return f"{obj.surgeon.first_name} {obj.surgeon.last_name}".strip()
        return None

    def validate_procedure(self, value):
        clean = sanitize_text(value or '', max_length=2000)
        if not clean.strip():
            raise serializers.ValidationError("El procedimiento realizado es obligatorio.")
        return clean

    def validate_postop_instructions(self, value):
        clean = sanitize_text(value or '', max_length=2000)
        if not clean.strip():
            raise serializers.ValidationError("Las indicaciones postoperatorias son obligatorias.")
        return clean

    def validate_preop_diagnosis(self, value):
        return sanitize_text(value or '', max_length=500)

    def validate_findings(self, value):
        return sanitize_text(value or '', max_length=2000)

    def validate_complications(self, value):
        return sanitize_text(value or '', max_length=2000)

    def validate_medical_record(self, mr):
        if mr and mr.organization != self.context['request'].user.organization:
            raise serializers.ValidationError('Acceso inválido.')
        return mr

    def validate(self, data):
        if 'notes' in data:
            data['notes'] = sanitize_text(data['notes'], max_length=5000)

        next_due = data.get('next_due_date')
        app_date = data.get('application_date')
        if next_due and app_date and next_due <= app_date:
            raise serializers.ValidationError({
                'next_due_date': 'La fecha de próxima dosis debe ser posterior a la fecha de aplicación.'
            })
        return data


class ConsultationAssessmentSerializer(serializers.ModelSerializer):
    """
    Valida el contenido del protocolo General (familia diagnóstica) al
    materializar ConsultationAssessment en el cierre. `pet`/`medical_record`/
    `assessed_by`/`organization`/`protocol_version` los fija el service
    (server-side), no el cliente — por eso no están en `fields`.
    """
    class Meta:
        model = ConsultationAssessment
        fields = [
            'id', 'chief_complaint', 'history', 'exam',
            'differentials', 'recheck_date', 'protocol_version', 'created_at',
        ]
        read_only_fields = ['id', 'protocol_version', 'created_at']

    def validate_chief_complaint(self, value):
        return sanitize_text(value or '', max_length=255)

    def validate_history(self, value):
        return sanitize_text(value or '', max_length=5000)

    def validate_differentials(self, value):
        return sanitize_text(value or '', max_length=2000)

    def validate_exam(self, value):
        # Valida estructura + tope de tamaño; el contenido por sistema es libre.
        if value in (None, ''):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("Formato de exploración inválido.")
        if len(json.dumps(value)) > 16_384:  # ~16 KB
            raise serializers.ValidationError("La exploración es demasiado grande.")
        return value
