from django.db import transaction
from rest_framework import serializers

from apps.core.datetime_utils import serializer_today

from apps.core.validators import validate_mx_phone

from .models import Pet, Owner
from .services import change_owner_phone, resolve_owner_for_phone
from .creation import (NAME_REGEX, create_pet, validate_name as _validate_name,
    validate_species as creation_species, validate_birth_date as creation_birth_date,
    lock_organization, PetCreationRejected)

# `PHONE_REGEX` se retiró (D4 del inventario, decisión §4.7.4): era una TERCERA
# regla de formato de teléfono, más laxa que la del dominio (aceptaba rellenos
# como `0000000000` que `validate_mx_phone` rechaza). La forma la valida ahora
# `OwnerSerializer.validate_phone`, también en la escritura anidada de mascota.


class OwnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Owner
        fields = ['id', 'public_id', 'name', 'phone', 'is_generic', 'legacy_id', 'extra_data', 'is_active', 'archived_at']
        # extra_data = datos del sistema anterior (Fase D): read-only en la API
        # (lo escribe el importador, no la edición manual).
        read_only_fields = ['public_id', 'is_generic', 'extra_data', 'is_active', 'archived_at']
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

    def create(self, validated_data):
        """Alta manual de cliente — A2 del inventario (decisión §4.7.4).

        Pasa por el servicio único aunque hoy este endpoint «solo cree»: sin él,
        un alta de recepción concurrente fabrica el duplicado que el agente
        acaba de evitar, y nadie se entera hasta que el teléfono se vuelve
        ambiguo.

        `match_name=True`: si el número ya tiene expediente **con otro nombre**,
        el alta pregunta (`409 owner_exists` con el candidato) en vez de crear
        un segundo cliente con el mismo teléfono. Mismo nombre → devuelve el
        expediente existente, que es lo que recepción quería.
        """
        organization = validated_data.pop('organization')
        name = validated_data.pop('name')
        phone = validated_data.pop('phone', '')
        with transaction.atomic():
            owner, _outcome = resolve_owner_for_phone(
                organization,
                phone=phone,
                name=name,
                match_name=True,
                defaults=validated_data,
            )
        return owner

    def update(self, instance, validated_data):
        """Edición de cliente — C1 del inventario (decisión §4.10).

        El cambio de teléfono **mueve la clave de deduplicación**, así que va
        por el servicio: bloquea la clave anterior y la nueva en orden total,
        comprueba y guarda en el mismo bloque.

        La comprobación NO puede vivir en `validate()`: DRF valida y guarda en
        pasos separados, y esa es precisamente la ventana que el servicio
        elimina.
        """
        new_phone = validated_data.pop('phone', instance.phone)
        with transaction.atomic():
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            # `change_owner_phone` hace el único `save()`: los atributos de
            # arriba se persisten con él, así que un 409 no deja nada a medias.
            return change_owner_phone(instance, new_phone)


class PetSerializer(serializers.ModelSerializer):
    """Alta y edición de mascota.

    **El alta tiene dos modos explícitos** (decisión §4.9) y ninguno resuelve
    identidad por teléfono a espaldas del usuario:

      · **referencia** — `owner_public_id`: el cliente ya lo eligió una persona.
        Elegir es un acto del staff, no una inferencia del sistema; por eso es
        legítimo asociar la mascota a ESE expediente.
      · **alta** — `owner: {name, phone}`: pasa por el servicio único, bajo el
        lock de deduplicación.

    Antes había un tercer camino implícito: `get_or_create(name, phone, org)`,
    una segunda regla de deduplicación por `(nombre, teléfono)` que producía dos
    fallos reales. Colgaba una mascota de un expediente ajeno localizado solo
    por coincidencia de número (INV-B), y cuando el teléfono coincidía pero el
    nombre no ("Ana López" vs "Ana Lopez") **fabricaba** un segundo cliente con
    el mismo teléfono — el duplicado que INV-C obliga a tratar como ambiguo,
    creado por el propio sistema.
    """
    owner = OwnerSerializer(required=False)
    owner_id = serializers.IntegerField(source='owner.id', read_only=True)
    # Modo referencia. UUID, no PK: es un identificador que viaja desde el
    # cliente (ADR p18). Se resuelve SIEMPRE dentro de la organización del
    # usuario → un `public_id` de otra clínica no existe para este endpoint.
    owner_public_id = serializers.UUIDField(write_only=True, required=False)

    class Meta:
        model = Pet
        fields = ['id', 'public_id', 'name', 'species', 'breed', 'birth_date', 'sex', 'color', 'owner', 'owner_id', 'owner_public_id', 'legacy_id', 'extra_data', 'is_active', 'archived_at']
        # extra_data = datos del sistema anterior (Fase D): read-only en la API.
        read_only_fields = ['public_id', 'extra_data', 'is_active', 'archived_at']
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
        return creation_species(value)

    def validate_birth_date(self, value):
        # Fecha de nacimiento OPCIONAL (alineado con importador y registro rápido).
        # Si viene un valor, no puede ser futura.
        return creation_birth_date(value, serializer_today(self))

    def validate(self, attrs):
        request = self.context['request']
        if not request.user.organization:
            raise serializers.ValidationError({
                'organization': 'No tienes una organización asignada. Contacta al administrador del sistema.'
            })
        # La FORMA del teléfono la valida `OwnerSerializer.validate_phone`
        # (regla única del dominio). Aquí solo se decide el MODO.
        has_reference = 'owner_public_id' in attrs
        has_inline = 'owner' in attrs

        if self.instance is None:
            if has_reference and has_inline:
                raise serializers.ValidationError({
                    'owner': 'Envía el cliente ya elegido (owner_public_id) o los '
                             'datos para darlo de alta (owner), no ambos.'
                })
            if not has_reference and not has_inline:
                raise serializers.ValidationError({
                    'owner': 'El cliente es requerido.'
                })
        elif has_reference:
            # `PetSerializer.update` NO re-parenta (B4 del inventario): mover una
            # mascota de cliente es otra operación, con su propia decisión.
            raise serializers.ValidationError({
                'owner_public_id': 'No se puede cambiar el cliente de una mascota '
                                   'existente desde este endpoint.'
            })
        return attrs

    def create(self, validated_data):
        """Resolución del cliente y creación de la mascota en UNA transacción.

        El lock de deduplicación se toma **antes** de ambas, así que no existe
        el estado «cliente creado, mascota no» ni la ventana en la que otro
        actor crea el mismo expediente entre la comprobación y el insert.
        """
        request = self.context['request']
        organization = request.user.organization

        owner_public_id = validated_data.pop('owner_public_id', None)
        owner_data = validated_data.pop('owner', None)

        with transaction.atomic():
            organization = lock_organization(organization.pk)
            if owner_public_id is not None:
                owner = self._resolve_owner_reference(organization, owner_public_id)
            else:
                # `match_name=True`: teléfono conocido con otro nombre →
                # `409 owner_exists` con el candidato, para que la UI pregunte
                # «¿es este cliente?» y reenvíe en modo referencia. NUNCA un
                # segundo expediente con el mismo número.
                owner, _outcome = resolve_owner_for_phone(
                    organization,
                    phone=owner_data.get('phone', ''),
                    name=owner_data['name'],
                    match_name=True,
                )
            try:
                return create_pet(organization_id=organization.pk, owner_id=owner.pk,
                                  fields=validated_data)
            except PetCreationRejected as exc:
                raise serializers.ValidationError({
                    'owner_public_id': 'El cliente no está disponible para registrar esta mascota.'
                }) from exc

    def _resolve_owner_reference(self, organization, owner_public_id):
        """Modo referencia: el expediente que una persona ya eligió.

        Tenant-scoped por construcción — un `public_id` de otra organización
        simplemente no existe aquí (nunca se devuelve el objeto ajeno ni se
        confirma su existencia).
        """
        owner = Owner.objects.for_organization(organization).filter(
            public_id=owner_public_id
        ).first()
        if owner is None:
            raise serializers.ValidationError({
                'owner_public_id': 'El cliente indicado no existe en esta clínica.'
            })
        return owner

    def update(self, instance, validated_data):
        """Edición de mascota — C2 del inventario (decisión §4.10).

        La escritura anidada del teléfono del cliente es la vía **menos
        evidente y la más peligrosa** del inventario: mueve la identidad de un
        cliente desde una pantalla que parece de mascota. Va por el servicio,
        igual que la edición desde Clientes.

        Todo ocurre en una transacción: un `409` no deja ni el teléfono
        cambiado ni los campos de la mascota guardados. Antes eran dos `save()`
        sueltos.
        """
        owner_data = validated_data.pop('owner', None)

        with transaction.atomic():
            if owner_data is not None:
                owner = instance.owner
                owner.name = owner_data.get('name', owner.name)
                change_owner_phone(owner, owner_data.get('phone', owner.phone))

            for field in ('name', 'species', 'breed', 'birth_date', 'sex', 'color'):
                if field in validated_data:
                    setattr(instance, field, validated_data[field])
            instance.save()

        return instance
