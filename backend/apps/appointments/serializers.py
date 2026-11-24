import uuid

from rest_framework import serializers
from apps.core.tenant_validation import require_same_organization
from django.db.models import Q
from django.utils.timezone import now

from apps.core.datetime_utils import get_context_timezone, local_date_time_to_utc
from apps.core.sanitize import sanitize_text

from .models import Appointment, AppointmentStatusChange
from .services import (
    ACTIVE_STATUSES,
    EXPECTED_STATE_FIELD,
    MISSING,
    SlotTaken,
    enforce_expected_state,
    reject_if_veterinarian_absent,
    parse_expected_state,
)


class AppointmentSerializer(serializers.ModelSerializer):
    def update(self, instance, validated_data):
        # Validation and locks remain in the human endpoint. Share only the
        # schedule transformation with the restricted B8C command; one save.
        if 'start_datetime' in validated_data and any(
                key in validated_data for key in ('date', 'start_time', 'end_time', 'veterinarian')):
            from .mutations import set_schedule_fields
            set_schedule_fields(instance,
                day=validated_data.get('date', instance.date),
                start=validated_data.get('start_time', instance.start_time),
                end=validated_data.get('end_time', instance.end_time),
                veterinarian_id=getattr(validated_data.get('veterinarian', instance.veterinarian), 'pk', None),
                org=self.context['request'].user.organization)
        return super().update(instance, validated_data)

    def create(self, validated_data):
        # Same authority used by B8B, with reception's existing hours policy.
        # Technical provenance is not an API field and is never read from data.
        from .creation import AppointmentCommand, create_appointment
        data = validated_data
        return create_appointment(AppointmentCommand(
            organization_id=data['organization'].pk, pet_id=data['pet'].pk,
            veterinarian_id=getattr(data.get('veterinarian'), 'pk', None),
            date=data['date'], start_time=data['start_time'], end_time=data['end_time'],
            reason=data['reason'], category=data.get('category', 'general_consultation'),
            notes=data.get('notes', ''), status=data.get('status', 'scheduled'),
            cancellation_reason=data.get('cancellation_reason', ''),
            idempotency_key=data.get('idempotency_key')))

    # INV-A (ADR p57, §3.2 exigencia 1) — la precondición atómica de estado va
    # DECLARADA. DRF descarta en silencio las claves desconocidas: un
    # `expected_state` no declarado se perdería y el PATCH pasaría
    # INCONDICIONALMENTE. Es el fail-open invisible que P0-4 vigila; borrar
    # esta línea desactiva la garantía sin romper ningún test de forma obvia.
    #
    # `JSONField` y no un serializer anidado: la forma la valida
    # `parse_expected_state` (fuente única, compartida con las FBVs de
    # /status/, DELETE y assign-patient, que no pasan por este serializer).
    #
    # `allow_null=True` NO es permisividad: es lo que hace que un `null`
    # explícito LLEGUE a `validate()` en vez de morir con el mensaje genérico
    # en inglés de DRF. Ahí se rechaza con `400` y un mensaje que dice qué
    # hacer (omitir la clave). Con `allow_null=False` el desenlace también
    # sería 400, pero el dominio perdería el control del contrato.
    expected_state = serializers.JSONField(
        write_only=True, required=False, allow_null=True,
    )

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
            'expected_state',
            'pet', 'pet_name', 'pet_public_id', 'pet_is_generic',
            'owner_id', 'owner_public_id', 'owner_name',
            'veterinarian', 'veterinarian_name', 'veterinarian_public_id',
            'date', 'start_time', 'end_time', 'reason', 'category', 'notes',
            # Instantes UTC (anchors): el agente los usa para etiquetar en la
            # hora local de la org sin double-shift (ver executor.format_local_*).
            'start_datetime', 'end_datetime',
            'status', 'cancellation_reason', 'walk_in',
            'medical_record_ids', 'medical_record_public_ids',
            'invoice_id', 'invoice_public_id',
        ]
        read_only_fields = [
            'id', 'public_id', 'pet_public_id', 'owner_public_id', 'veterinarian_public_id',
            'pet_is_generic', 'owner_id', 'owner_name', 'walk_in',
            'start_datetime', 'end_datetime',
            'medical_record_ids', 'medical_record_public_ids',
            'invoice_id', 'invoice_public_id',
        ]

    def validate_pet(self, value):
        request = self.context.get('request')
        if request:
            require_same_organization(
                value, request, field='pet', serializer=type(self).__name__,
                message='Mascota fuera de tu organización')
        return value

    def validate_veterinarian(self, value):
        request = self.context.get('request')
        if request:
            require_same_organization(
                value, request, field='veterinarian', serializer=type(self).__name__,
                message='Veterinario fuera de tu organización')
        return value

    def validate(self, attrs):
        request = self.context.get('request')
        instance = getattr(self, 'instance', None)

        # INV-A: la precondición se saca de `attrs` SIEMPRE (no es un campo del
        # modelo). Se compara aquí porque el caller ya tomó el lock de la fila y
        # nos pasó la instancia bloqueada: la comparación queda dentro de la
        # misma transacción que escribe (§3.2 exigencia 2).
        #
        # El default del `pop` es `MISSING`, no `None`: con `required=False` la
        # clave ausente no llega a `attrs`, pero con `allow_null=True` un `null`
        # explícito SÍ llega como `None`. Usar `None` de default fusionaría los
        # dos casos y el `null` explícito pasaría como opt-in.
        expected_raw = attrs.pop(EXPECTED_STATE_FIELD, MISSING)
        if expected_raw is not MISSING and instance is None:
            # POST no tiene estado previo que comparar (matriz §3.3). Se rechaza
            # por PRESENCIA de la clave —igual que `create-with-patient` y
            # `walk-in`—, así que el mensaje es el mismo en las tres vías de
            # creación, valga lo que valga el campo (incluido `null`).
            raise serializers.ValidationError({
                EXPECTED_STATE_FIELD: [
                    'No aplica al crear una cita: no hay estado previo que comparar.'
                ]
            })
        expected = parse_expected_state(expected_raw)
        if instance is not None:
            # Fase 3 de INV-A: mutar una cita EXIGE la precondición. Su
            # ausencia ya no es opt-in, es `400 precondition_required` — el
            # propio `enforce_expected_state` lo decide, así que no hay una
            # segunda definición de «cuándo hace falta» viviendo aquí.
            enforce_expected_state(instance, expected)

        if not request or not request.user.is_authenticated:
            return attrs

        org = request.user.organization

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
            status__in=ACTIVE_STATUSES,
        )

        if instance:
            conflicts = conflicts.exclude(pk=instance.pk)

        conflicts = conflicts.filter(
            Q(start_datetime__lt=end_utc, end_datetime__gt=start_utc)
        )

        # INV-D — pre-chequeo. SE CONSERVA: es quien produce el mensaje legible
        # y el desenlace de negocio. La GARANTÍA es la restricción de exclusión
        # de PostgreSQL (§3.4); si este `exists()` pierde la carrera, la base
        # rechaza y el caller traduce al MISMO `400 slot_taken`.
        if target_status in ACTIVE_STATUSES and conflicts.exists():
            raise SlotTaken()

        # ADR p67: mover una cita a un día en que el veterinario está ausente
        # (o reasignarla a uno ausente) se bloquea. El alta lo comprueba en
        # `validate_creation`, ya con el veterinario bloqueado; aquí solo la
        # edición, que `AppointmentDetailView.update` valida bajo ese mismo lock.
        if instance and target_status in ACTIVE_STATUSES:
            moving = (
                date_or_time_changing
                or vet_pk != instance.veterinarian_id
                or target_status != instance.status
            )
            if moving:
                reject_if_veterinarian_absent(org.pk, vet_pk, local_date)

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


class ReassignAppointmentsSerializer(serializers.Serializer):
    """Cuerpo de `POST /api/appointments/reassign/` (ADR p67).

    Cada cita viaja con su `expected_state` (INV-A): omitirla es
    `400 precondition_required`, igual que en una edición individual.
    """
    source_public_id = serializers.UUIDField()
    target_public_id = serializers.UUIDField()
    appointments = serializers.ListField(child=serializers.DictField(), allow_empty=False)

    def validate(self, attrs):
        from .reassignment import MAX_REASSIGN
        from .services import MISSING, PreconditionRequired, parse_expected_state

        if attrs['source_public_id'] == attrs['target_public_id']:
            raise serializers.ValidationError(
                {'target_public_id': ['El veterinario destino debe ser otro.']})
        raw_items = attrs['appointments']
        if len(raw_items) > MAX_REASSIGN:
            raise serializers.ValidationError(
                {'appointments': [f'Como máximo {MAX_REASSIGN} citas por operación.']})
        items, seen = [], set()
        for raw in raw_items:
            try:
                public_id = uuid.UUID(str(raw.get('public_id')))
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    {'appointments': ['Cada cita necesita un public_id válido.']})
            if public_id in seen:
                raise serializers.ValidationError(
                    {'appointments': ['Hay citas repetidas.']})
            seen.add(public_id)
            expected = parse_expected_state(raw.get(EXPECTED_STATE_FIELD, MISSING))
            if expected is None:
                raise PreconditionRequired()
            items.append((public_id, expected))
        attrs['items'] = items
        return attrs
