from rest_framework import serializers
from django.utils import timezone
from zoneinfo import available_timezones

from apps.core.validators import validate_mx_phone

from .models import Organization, OrganizationTimezoneAudit, OrganizationSettings, OrganizationSchedule


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
        if value not in available_timezones():
            raise serializers.ValidationError('Zona horaria invalida')
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
        return validate_mx_phone(value, allow_blank=True)

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
        request = self.context.get('request')
        changed_by = request.user if request and request.user.is_authenticated else None

        old_timezone = instance.timezone
        updated = super().update(instance, validated_data)

        if 'timezone' in validated_data and validated_data['timezone'] != old_timezone:
            updated.timezone_updated_at = timezone.now()
            updated.save(update_fields=['timezone_updated_at'])
            OrganizationTimezoneAudit.objects.create(
                organization=updated,
                old_timezone=old_timezone,
                new_timezone=validated_data['timezone'],
                changed_by=changed_by,
            )

        return updated


class OrganizationSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationSettings
        fields = [
            'auto_create_medical_record',
            'auto_create_invoice_on_done',
            'require_confirmation_before_start',
            'allow_anonymous_walkin',
            'show_status_change_history',
            'require_open_cash_session',
            'locale',
            'currency_code',
            'default_appointment_duration_minutes',
            'appointment_buffer_minutes',
            'allow_emergency_walkin',
            'week_starts_on',
        ]

    def validate_currency_code(self, value):
        return value.upper()

    def validate_default_appointment_duration_minutes(self, value):
        if value < 5 or value > 240:
            raise serializers.ValidationError('La duracion debe estar entre 5 y 240 minutos.')
        return value

    def validate_appointment_buffer_minutes(self, value):
        if value < 0 or value > 120:
            raise serializers.ValidationError('El buffer debe estar entre 0 y 120 minutos.')
        return value

    def validate_week_starts_on(self, value):
        if value < 1 or value > 7:
            raise serializers.ValidationError('El dia de inicio de semana debe estar entre 1 (lunes) y 7 (domingo).')
        return value


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
                raise serializers.ValidationError(
                    'Si el dia esta cerrado, no debe enviar horarios.'
                )
            return data

        if opens_at is None or closes_at is None:
            raise serializers.ValidationError(
                'opens_at y closes_at son obligatorios cuando el dia no esta cerrado.'
            )
        if opens_at >= closes_at:
            raise serializers.ValidationError(
                'La hora de apertura debe ser anterior a la de cierre.'
            )
        if has_break:
            if break_start is None or break_end is None:
                raise serializers.ValidationError(
                    'break_start y break_end son obligatorios cuando has_break=True.'
                )
            if not (opens_at < break_start < break_end < closes_at):
                raise serializers.ValidationError(
                    'El descanso debe estar dentro del horario de apertura.'
                )
        else:
            if break_start or break_end:
                raise serializers.ValidationError(
                    'Si no hay descanso, no debe enviar break_start ni break_end.'
                )

        return data


class OrganizationScheduleBulkSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, list):
            raise serializers.ValidationError({'non_field_errors': 'Se espera una lista de 7 elementos.'})
        if len(data) != 7:
            raise serializers.ValidationError({'non_field_errors': 'Deben enviarse exactamente 7 dias de la semana.'})

        weekdays_seen = set()
        for item in data:
            wd = item.get('weekday')
            if wd is None or wd < 1 or wd > 7:
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
