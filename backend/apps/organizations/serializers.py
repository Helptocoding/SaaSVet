from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.core.validators import is_valid_mx_phone, validate_mx_phone

from .models import (
    PHONE_REQUIRED_MESSAGE, Organization, OrganizationClosure, OrganizationConfigEvent,
    OrganizationSettings, OrganizationSchedule,
)
from .services import (
    TIMEZONE_NOT_SUPPORTED_MESSAGE, update_clinic_profile, update_operating_rules,
)
from .timezones import TIMEZONE_CODES


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = [
            'id', 'public_id', 'name', 'display_name',
            'timezone', 'timezone_updated_at', 'tax_rate',
            'phone', 'whatsapp', 'email', 'website',
            'address_line1', 'address_line2', 'district',
            'city', 'state', 'postal_code', 'country',
            'google_maps_url', 'latitude', 'longitude',
            'arrival_instructions', 'is_demo', 'created_at',
        ]
        read_only_fields = [
            'id', 'public_id', 'timezone_updated_at',
            'is_demo', 'created_at', 'tax_rate',
        ]

    def validate_timezone(self, value):
        # ADR p70 D1: catálogo cerrado de México. Reenviar la zona vigente se
        # admite aunque esté fuera de él: no es un cambio.
        if self.instance is not None and value == self.instance.timezone:
            return value
        if value not in TIMEZONE_CODES:
            raise serializers.ValidationError(TIMEZONE_NOT_SUPPORTED_MESSAGE)
        return value

    def validate_phone(self, value):
        # Teléfono público de la clínica. Es lo que el agente de WhatsApp pone en
        # su plantilla de URGENCIA (`agent/clinic_context.clinic_phone`), así que
        # el campo no puede aceptar basura: `bool(phone)` es la señal del hito
        # `has_clinic_contact` del onboarding, y solo vale si existir == ser válido.
        #
        # `allow_blank=True`: la org NACE con phone='' y el ADMIN debe poder
        # guardar el resto de la sección antes de capturarlo. Lo que sí se rechaza
        # es un valor NO vacío que no normaliza ("no sé" → antes se guardaba ''
        # en silencio y el onboarding reaparecía sin explicación).
        #
        # INV-L (ADR p70 D2): una vez válido, no se vacía. Esta comprobación solo
        # adelanta el mensaje; la garantía es `Organization.save`, que compara
        # contra el valor persistido bajo bloqueo.
        cleaned = validate_mx_phone(value, allow_blank=True)
        if not cleaned and self.instance is not None and is_valid_mx_phone(self.instance.phone or ''):
            raise serializers.ValidationError(PHONE_REQUIRED_MESSAGE)
        return cleaned

    def validate_whatsapp(self, value):
        if value:
            cleaned = ''.join(c for c in value if c.isdigit())
            return cleaned
        return value

    def validate(self, data):
        lat = data.get('latitude', getattr(self.instance, 'latitude', None))
        lng = data.get('longitude', getattr(self.instance, 'longitude', None))
        if (lat is None) != (lng is None):
            raise serializers.ValidationError(
                'Latitud y longitud deben enviarse juntas.'
            )
        return data

    def update(self, instance, validated_data):
        """Delega en `services.update_clinic_profile` (ADR p70 D9): guarda solo
        lo que cambió, la zona por su servicio y deja el evento del historial."""
        request = self.context.get('request')
        actor = request.user if request is not None else None
        try:
            return update_clinic_profile(
                actor=actor, organization=instance, data=validated_data,
            )
        except DjangoValidationError as exc:
            # El modelo es la garantía (INV-L); sin esto DRF respondería 500.
            detail = exc.message_dict if hasattr(exc, 'error_dict') else exc.messages
            raise serializers.ValidationError(detail) from exc


RETIRED_SETTINGS = frozenset({
    'locale', 'appointment_buffer_minutes', 'allow_emergency_walkin', 'week_starts_on',
})
RETIRED_SETTING_MESSAGE = 'Este ajuste se retiró: no tenía efecto en el sistema.'


class OrganizationSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationSettings
        fields = [
            'auto_create_medical_record',
            'require_confirmation_before_start',
            'allow_anonymous_walkin',
            'show_status_change_history',
            'require_open_cash_session',
            'allow_post_unpaid',
            'credit_default_days',
            'currency_code',
            'default_appointment_duration_minutes',
        ]
        # ADR p70 D5: la moneda es MXN y no se cambia desde Configuración.
        read_only_fields = ['currency_code']

    def to_internal_value(self, data):
        # D5: un ajuste retirado no se ignora en silencio: se dice que ya no existe.
        if hasattr(data, 'keys'):
            retired = sorted(set(data.keys()) & RETIRED_SETTINGS)
            if retired:
                raise serializers.ValidationError({
                    field: [RETIRED_SETTING_MESSAGE] for field in retired
                })
        return super().to_internal_value(data)

    def validate_default_appointment_duration_minutes(self, value):
        if value < 5 or value > 240:
            raise serializers.ValidationError('La duración debe estar entre 5 y 240 minutos.')
        return value

    def validate_credit_default_days(self, value):
        if value < 1 or value > 365:
            raise serializers.ValidationError('El plazo de crédito debe estar entre 1 y 365 días.')
        return value

    def update(self, instance, validated_data):
        """Delega en `services.update_operating_rules` (ADR p70 D9)."""
        request = self.context.get('request')
        return update_operating_rules(
            actor=request.user if request is not None else None,
            organization=instance.organization, data=validated_data,
        )


# Plan F1.3: mensajes para personas. El frontend los repite tal cual en su
# validación previa (`features/config/schedule.js`).
SCHEDULE_CLOSED_WITH_HOURS = 'Si el día está cerrado, no envíes horarios.'
SCHEDULE_HOURS_REQUIRED = 'Indica la hora de apertura y la de cierre.'
SCHEDULE_HOURS_ORDER = 'La hora de apertura debe ser anterior a la de cierre.'
SCHEDULE_BREAK_REQUIRED = 'Indica el inicio y el fin del descanso.'
SCHEDULE_BREAK_INSIDE = 'El descanso debe quedar dentro del horario de apertura.'
SCHEDULE_BREAK_WITHOUT_FLAG = 'Si no hay descanso, no envíes sus horas.'


class OrganizationScheduleItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationSchedule
        fields = [
            'weekday', 'is_closed', 'opens_at', 'closes_at',
            'has_break', 'break_start', 'break_end',
        ]

    def validate(self, data):
        is_closed = data.get('is_closed', False)
        opens_at = data.get('opens_at', None)
        closes_at = data.get('closes_at', None)
        has_break = data.get('has_break', False)
        break_start = data.get('break_start', None)
        break_end = data.get('break_end', None)

        if is_closed:
            if opens_at or closes_at or break_start or break_end:
                raise serializers.ValidationError(SCHEDULE_CLOSED_WITH_HOURS)
            return data

        if opens_at is None or closes_at is None:
            raise serializers.ValidationError(SCHEDULE_HOURS_REQUIRED)
        if opens_at >= closes_at:
            raise serializers.ValidationError(SCHEDULE_HOURS_ORDER)
        if has_break:
            if break_start is None or break_end is None:
                raise serializers.ValidationError(SCHEDULE_BREAK_REQUIRED)
            if not (opens_at < break_start < break_end < closes_at):
                raise serializers.ValidationError(SCHEDULE_BREAK_INSIDE)
        else:
            if break_start or break_end:
                raise serializers.ValidationError(SCHEDULE_BREAK_WITHOUT_FLAG)

        return data


class OrganizationScheduleBulkSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, list):
            raise serializers.ValidationError({'non_field_errors': 'Se espera una lista de 7 elementos.'})
        if len(data) != 7:
            raise serializers.ValidationError({'non_field_errors': 'Deben enviarse exactamente 7 dias de la semana.'})

        weekdays_seen = set()
        for item in data:
            # F1.4 (C19): un elemento que no es objeto o un `weekday` que no es
            # entero daban 500 al compararlos; ahora son 400.
            if not isinstance(item, dict):
                raise serializers.ValidationError(
                    {'non_field_errors': 'Cada día debe ser un objeto con sus horarios.'})
            wd = item.get('weekday')
            if isinstance(wd, bool) or not isinstance(wd, int):
                raise serializers.ValidationError(
                    {'non_field_errors': f'weekday invalido: {wd}. Debe ser un entero entre 1 y 7.'})
            if wd < 1 or wd > 7:
                raise serializers.ValidationError({'non_field_errors': f'weekday invalido: {wd}. Debe estar entre 1 y 7.'})
            if wd in weekdays_seen:
                raise serializers.ValidationError({'non_field_errors': f'weekday duplicado: {wd}.'})
            weekdays_seen.add(wd)

        if weekdays_seen != {1, 2, 3, 4, 5, 6, 7}:
            raise serializers.ValidationError('Deben incluirse todos los dias de la semana (1-7).')

        validated = []
        errors = {}
        for i, item in enumerate(data):
            s = OrganizationScheduleItemSerializer(data=item)
            if s.is_valid():
                validated.append(s.validated_data)
            else:
                wd = item.get('weekday', '?')
                errors[f'day_{wd}'] = s.errors

        if errors:
            raise serializers.ValidationError(errors)

        return validated

    def to_representation(self, instance):
        return OrganizationScheduleItemSerializer(instance, many=True).data


class ConfigurationAggregateSerializer(serializers.Serializer):
    organization = OrganizationSerializer()
    settings = OrganizationSettingsSerializer()
    schedule = OrganizationScheduleItemSerializer(many=True)


class OrganizationConfigEventSerializer(serializers.ModelSerializer):
    """Evento del historial de Configuración (ADR p70 D9). Sin PK internos:
    tipo, cuándo, quién, sobre qué y qué cambió."""
    kind_label = serializers.CharField(source='get_kind_display')
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = OrganizationConfigEvent
        fields = ['kind', 'kind_label', 'occurred_at', 'actor_name', 'subject', 'changes']

    def get_actor_name(self, obj):
        actor = obj.actor
        if actor is None:
            return None
        return f'{actor.first_name} {actor.last_name}'.strip() or actor.username


def _person_name(user):
    if user is None:
        return None
    return f'{user.first_name} {user.last_name}'.strip() or user.username


class OrganizationClosureSerializer(serializers.ModelSerializer):
    """Cierre excepcional (ADR p70 D6). Sin PK internos."""
    is_active = serializers.BooleanField(read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = OrganizationClosure
        fields = ['public_id', 'start_date', 'end_date', 'reason', 'is_active',
                  'created_by_name', 'created_at', 'cancelled_at']
        read_only_fields = fields

    def get_created_by_name(self, obj):
        return _person_name(obj.created_by)


class OrganizationClosureCreateSerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    reason = serializers.CharField(max_length=120, allow_blank=True)


class AgendaClosureSerializer(serializers.ModelSerializer):
    """Cierre tal como lo ve la agenda del personal (plan F2.2): sin autor."""

    class Meta:
        model = OrganizationClosure
        fields = ['public_id', 'start_date', 'end_date', 'reason']
        read_only_fields = fields
