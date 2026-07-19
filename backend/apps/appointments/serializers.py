from rest_framework import serializers
from django.db.models import Q
from django.utils.timezone import now

from apps.core.datetime_utils import get_context_timezone, local_date_time_to_utc
from apps.core.sanitize import sanitize_text

from .models import Appointment, AppointmentStatusChange


class AppointmentSerializer(serializers.ModelSerializer):
    pet_name = serializers.CharField(source='pet.name', read_only=True)
    pet_is_generic = serializers.BooleanField(source='pet.is_generic', read_only=True)
    # Día 6 B2: pet_public_id para deep links sin PK
    pet_public_id = serializers.UUIDField(source='pet.public_id', read_only=True)
    owner_id = serializers.IntegerField(source='pet.owner_id', read_only=True)
    owner_public_id = serializers.UUIDField(source='pet.owner.public_id', read_only=True)
    owner_name = serializers.CharField(source='pet.owner.name', read_only=True)
    veterinarian_name = serializers.CharField(source='veterinarian.get_full_name', read_only=True)
    veterinarian_public_id = serializers.UUIDField(source='veterinarian.public_id', read_only=True, allow_null=True)
    medical_record_ids = serializers.ReadOnlyField()
    medical_record_public_ids = serializers.SerializerMethodField()
    invoice_id = serializers.ReadOnlyField()
    invoice_public_id = serializers.SerializerMethodField()

    def get_medical_record_public_ids(self, obj):
        # obj.medical_record_ids es property; equivalente UUID list.
        from apps.medical_records.models import MedicalRecord
        ids = obj.medical_record_ids or []
        if not ids:
            return []
        return [
            str(uid) for uid in MedicalRecord.objects.filter(pk__in=ids).values_list('public_id', flat=True)
        ]

    def get_invoice_public_id(self, obj):
        invoice_id = obj.invoice_id
        if not invoice_id:
            return None
        from apps.billing.models import Invoice
        invoice = Invoice.objects.filter(pk=invoice_id).only('public_id').first()
        return str(invoice.public_id) if invoice else None

    class Meta:
        model = Appointment
        fields = [
            'id', 'public_id',
            'pet', 'pet_name', 'pet_public_id', 'pet_is_generic',
            'owner_id', 'owner_public_id', 'owner_name',
            'veterinarian', 'veterinarian_name', 'veterinarian_public_id',
            'date', 'start_time', 'end_time', 'reason', 'notes',
            'status', 'cancellation_reason', 'walk_in',
            'medical_record_ids', 'medical_record_public_ids',
            'invoice_id', 'invoice_public_id',
        ]
        read_only_fields = [
            'id', 'public_id', 'pet_public_id', 'owner_public_id', 'veterinarian_public_id',
            'pet_is_generic', 'owner_id', 'owner_name', 'walk_in',
            'medical_record_ids', 'medical_record_public_ids',
            'invoice_id', 'invoice_public_id',
        ]

    def validate_pet(self, value):
        request = self.context.get('request')
        if request and value.organization_id != request.user.organization_id:
            raise serializers.ValidationError('Mascota fuera de tu organización')
        return value

    def validate_veterinarian(self, value):
        request = self.context.get('request')
        if request and value.organization_id != request.user.organization_id:
            raise serializers.ValidationError('Veterinario fuera de tu organización')
        return value

    def validate(self, attrs):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return attrs

        org = request.user.organization
        instance = getattr(self, 'instance', None)

        local_date = attrs.get('date', instance.date if instance else None)
        start_time = attrs.get('start_time', instance.start_time if instance else None)
        end_time = attrs.get('end_time', instance.end_time if instance else None)
        veterinarian_id = attrs.get('veterinarian', instance.veterinarian if instance else None)
        target_status = attrs.get('status', instance.status if instance else 'scheduled')

        if not (local_date and start_time and end_time and veterinarian_id):
            return attrs

        if end_time <= start_time:
            raise serializers.ValidationError({'end_time': 'La hora fin debe ser mayor a la hora inicio'})

        start_utc = local_date_time_to_utc(org, local_date, start_time)
        end_utc = local_date_time_to_utc(org, local_date, end_time)

        # A2-1 (PR-14): el guard de fecha-pasada aplica en creación Y en
        # cualquier update que MUEVA la fecha/hora (reagendado). Antes solo
        # corría en creación → un PATCH podía mover una cita al pasado.
        date_or_time_changing = any(
            f in attrs for f in ('date', 'start_time', 'end_time')
        )
        if (not instance or date_or_time_changing) and start_utc < now():
            raise serializers.ValidationError(
                {"date": "No se pueden agendar citas en el pasado."}
            )

        vet_pk = veterinarian_id.pk if hasattr(veterinarian_id, 'pk') else veterinarian_id
        conflicts = Appointment.objects.filter(
            organization=org,
            veterinarian_id=vet_pk,
            status__in=['scheduled', 'confirmed', 'in_progress'],
        )

        if instance:
            conflicts = conflicts.exclude(pk=instance.pk)

        conflicts = conflicts.filter(
            Q(start_datetime__lt=end_utc, end_datetime__gt=start_utc)
        )

        if target_status in ('scheduled', 'confirmed', 'in_progress') and conflicts.exists():
            raise serializers.ValidationError(
                {'error': 'Ya existe una cita para este veterinario en ese horario'}
            )

        pet = attrs.get('pet', instance.pet if instance else None)
        raw_owner = self.context['request'].data.get('owner_id')
        if pet and raw_owner:
            if str(pet.owner_id) != str(raw_owner):
                raise serializers.ValidationError(
                    {'pet': 'La mascota no pertenece al propietario seleccionado'}
                )

        attrs['start_datetime'] = start_utc
        attrs['end_datetime'] = end_utc
        attrs['timezone_at_creation'] = str(get_context_timezone(org))

        # Sanitizar campos de texto libre
        for field, limit in (('reason', 255), ('notes', 5000), ('cancellation_reason', 500)):
            if field in attrs:
                attrs[field] = sanitize_text(attrs[field], max_length=limit)

        return attrs


class AppointmentStatusChangeSerializer(serializers.ModelSerializer):
    changed_by_name = serializers.SerializerMethodField()
    from_status_display = serializers.SerializerMethodField()
    to_status_display = serializers.SerializerMethodField()

    STATUS_LABELS = {
        'scheduled': 'Programada', 'confirmed': 'Confirmada',
        'in_progress': 'En consulta', 'done': 'Completada',
        'canceled': 'Cancelada', 'no_show': 'No se presentó',
    }

    class Meta:
        model = AppointmentStatusChange
        fields = [
            'id', 'from_status', 'from_status_display',
            'to_status', 'to_status_display',
            'changed_by', 'changed_by_name', 'reason', 'created_at',
        ]

    def get_changed_by_name(self, obj):
        if obj.changed_by:
            return f"{obj.changed_by.first_name} {obj.changed_by.last_name}".strip() or obj.changed_by.username
        return None

    def get_from_status_display(self, obj):
        return self.STATUS_LABELS.get(obj.from_status, obj.from_status)

    def get_to_status_display(self, obj):
        return self.STATUS_LABELS.get(obj.to_status, obj.to_status)
