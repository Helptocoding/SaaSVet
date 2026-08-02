import re

from rest_framework import serializers

from apps.core.datetime_utils import serializer_today

from apps.core.validators import validate_mx_phone

from .models import Pet, Owner, SPECIES_CHOICES

NAME_REGEX = re.compile(r"^[A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\' \-]+$")
PHONE_REGEX = re.compile(r"^\d{10}$")


def _validate_name(value, field_label="Nombre"):
    if not value or not value.strip():
        raise serializers.ValidationError(f"{field_label} es requerido.")
    if not NAME_REGEX.match(value.strip()):
        raise serializers.ValidationError(
            f"{field_label} solo puede contener letras, números, espacios, acentos, apóstrofes y guiones."
        )
    return value.strip()


class OwnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Owner
        fields = ['id', 'public_id', 'name', 'phone', 'is_generic', 'legacy_id', 'extra_data']
        # extra_data = datos del sistema anterior (Fase D): read-only en la API
        # (lo escribe el importador, no la edición manual).
        read_only_fields = ['public_id', 'is_generic', 'extra_data']
        extra_kwargs = {
            'legacy_id': {'required': False, 'allow_blank': True},
        }

    def validate_name(self, value):
        return _validate_name(value, "Nombre del dueño")

    def validate_phone(self, value):
        # skip validation for generic owners
        instance = getattr(self, 'instance', None)
        is_generic = getattr(instance, 'is_generic', False)
        if is_generic:
            return value
        # Alta/edición MANUAL: teléfono requerido (10 dígitos). El teléfono es
        # comercialmente crítico para datos nuevos (recordatorios, seguimiento,
        # campañas). La EXCEPCIÓN de teléfono opcional vive solo en el importador
        # (apps/imports/services.py), que escribe vía Owner.save() directo y NO
        # pasa por este serializer — Owner.phone es blank=True a nivel modelo para
        # permitirlo. NO relajar aquí: datos históricos sucios ≠ datos nuevos.
        #
        # La regla vive en `apps.core.validators` (dueño único, compartida con
        # `OrganizationSerializer.validate_phone`): 10 dígitos MX + rechazo de
        # relleno evidente. Aquí el teléfono es OBLIGATORIO → `allow_blank=False`.
        return validate_mx_phone(value)


class PetSerializer(serializers.ModelSerializer):
    owner = OwnerSerializer()
    owner_id = serializers.IntegerField(source='owner.id', read_only=True)

    class Meta:
        model = Pet
        fields = ['id', 'public_id', 'name', 'species', 'breed', 'birth_date', 'sex', 'color', 'owner', 'owner_id', 'legacy_id', 'extra_data']
        # extra_data = datos del sistema anterior (Fase D): read-only en la API.
        read_only_fields = ['public_id', 'extra_data']
        extra_kwargs = {
            'legacy_id': {'required': False, 'allow_blank': True},
            # Datos mínimos en alta manual (regla de producto piloto): la mascota
            # solo exige nombre + dueño (nombre/teléfono). Especie y fecha de
            # nacimiento son OPCIONALES y se completan después. El teléfono SIGUE
            # requerido (ver OwnerSerializer.validate_phone). Ver modules/patients.md.
            'species': {'required': False, 'allow_blank': True},
            'birth_date': {'required': False, 'allow_null': True},
        }

    def validate_name(self, value):
        return _validate_name(value, "Nombre de la mascota")

    def validate_species(self, value):
        # Especie OPCIONAL en captura manual: vacía => '' ("pendiente", se completa
        # después). Mismo criterio que el importador y el registro rápido de citas.
        # Si el usuario SÍ captura una especie, debe ser válida (SPECIES_CHOICES).
        if not value or not value.strip():
            return ''
        if value.strip().lower() not in SPECIES_CHOICES:
            raise serializers.ValidationError(
                f"Especie inválida. Opciones: {', '.join(SPECIES_CHOICES)}."
            )
        return value.strip().lower()

    def validate_birth_date(self, value):
        # Fecha de nacimiento OPCIONAL (alineado con importador y registro rápido).
        # Si viene un valor, no puede ser futura.
        if value is None:
            return None
        # Día local de la clínica, no del servidor (ver `serializer_today`).
        if value > serializer_today(self):
            raise serializers.ValidationError("La fecha de nacimiento no puede ser en el futuro.")
        return value

    def validate(self, attrs):
        request = self.context['request']
        if not request.user.organization:
            raise serializers.ValidationError({
                'organization': 'No tienes una organización asignada. Contacta al administrador del sistema.'
            })
        # phone validation: skip if owner is generic (create path doesn't have instance yet)
        owner_data = attrs.get('owner', {})
        phone = owner_data.get('phone', '')
        if phone and not PHONE_REGEX.match(phone):
            raise serializers.ValidationError({'owner': {'phone': 'El teléfono debe tener exactamente 10 dígitos.'}})
        return attrs

    def create(self, validated_data):
        request = self.context['request']
        organization = request.user.organization

        owner_data = validated_data.pop('owner')
        owner, _ = Owner.objects.get_or_create(
            name=owner_data['name'],
            phone=owner_data['phone'],
            organization=organization
        )

        pet = Pet.objects.create(
            owner=owner,
            organization=organization,
            **validated_data
        )

        return pet

    def update(self, instance, validated_data):
        owner_data = validated_data.pop('owner')
        owner = instance.owner
        owner.name = owner_data.get('name', owner.name)
        owner.phone = owner_data.get('phone', owner.phone)
        owner.save()

        instance.name = validated_data.get('name', instance.name)
        instance.species = validated_data.get('species', instance.species)
        instance.breed = validated_data.get('breed', instance.breed)
        instance.birth_date = validated_data.get('birth_date', instance.birth_date)
        instance.sex = validated_data.get('sex', instance.sex)
        instance.color = validated_data.get('color', instance.color)
        instance.save()

        return instance
