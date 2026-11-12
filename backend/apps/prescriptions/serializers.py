from rest_framework import serializers
from .models import Prescription, PrescriptionItem
from apps.core.tenant_validation import require_same_organization
from apps.core.sanitize import sanitize_text


class _PrescriptionItemBase(serializers.ModelSerializer):
    """Validación común de un medicamento recetado (deuda B2, orden 6).

    La comparten el anidado de `PrescriptionSerializer.items` y el endpoint
    `/prescriptions/<id>/items/`. Cada subclase declara solo su diferencia. Una regla
    nueva va aquí: si se pone en una sola subclase, las dos vías vuelven a divergir,
    como pasó con `validate_quantity`, que faltaba en el endpoint y dejaba un 500.
    """

    class Meta:
        model = PrescriptionItem
        fields = ['id', 'product', 'dose', 'duration', 'quantity', 'instructions']

    def validate_dose(self, value):
        clean = sanitize_text(value or '', max_length=255)
        if not clean.strip():
            raise serializers.ValidationError("La dosis es obligatoria.")
        return clean

    def validate_duration(self, value):
        return sanitize_text(value or '', max_length=255)

    def validate_instructions(self, value):
        return sanitize_text(value or '', max_length=5000)

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("La cantidad debe ser mayor a 0.")
        return value

    def validate_product(self, product):
        # Tenant isolation (ADR p14 — P0 #9). En el anidado, DRF propaga al hijo el
        # context del padre.
        request = self.context.get('request')
        assert request is not None, (
            f"{type(self).__name__} requiere 'request' en su context."
        )
        return require_same_organization(
            product, request, field='product', serializer=type(self).__name__)


class PrescriptionItemSerializer(_PrescriptionItemBase):
    """Anidado en `PrescriptionSerializer.items`: no exige `requires_prescription`."""

    product_name = serializers.CharField(source='product.name', read_only=True)
    product_unit = serializers.SerializerMethodField()

    def get_product_unit(self, obj):
        pres = obj.product.presentations.first()
        return pres.base_unit if pres else None

    class Meta(_PrescriptionItemBase.Meta):
        fields = [
            'id', 'product', 'product_name', 'product_unit',
            'dose', 'duration', 'quantity', 'instructions',
        ]


class PrescriptionSerializer(serializers.ModelSerializer):
    items = PrescriptionItemSerializer(many=True)
    pet_name = serializers.SerializerMethodField()
    # Día 6 B1: pet_public_id para frontend evitar PK en query params
    pet_public_id = serializers.SerializerMethodField()
    historical_pet_public_id = serializers.SerializerMethodField()
    # Metadatos de la mascota embebidos (read-only) para que la página de Recetas
    # filtre por especie/sexo/edad SIN cargar la lista completa de mascotas
    # (clínicas importadas de miles de pacientes). El pet ya viene select_related
    # en el queryset → costo cero. Pueden ser '' / null para datos importados.
    pet_species = serializers.SerializerMethodField()
    pet_sex = serializers.SerializerMethodField()
    pet_birth_date = serializers.SerializerMethodField()
    medical_record_public_id = serializers.UUIDField(
        source='medical_record.public_id', read_only=True, allow_null=True
    )
    veterinarian_name = serializers.SerializerMethodField()

    class Meta:
        model = Prescription
        fields = [
            'id', 'public_id', 'medical_record', 'medical_record_public_id',
            'veterinarian', 'veterinarian_name',
            'pet', 'pet_name', 'pet_public_id', 'historical_pet_public_id',
            'pet_species', 'pet_sex', 'pet_birth_date',
            'notes', 'items',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'public_id', 'pet_public_id', 'historical_pet_public_id',
            'pet_species', 'pet_sex', 'pet_birth_date',
            'medical_record_public_id',
            'veterinarian', 'created_at', 'updated_at',
        ]

    def get_veterinarian_name(self, obj):
        if obj.medical_record.status == 'closed':
            return obj.medical_record.vet_name_at_close or 'Desconocido'
        if obj.veterinarian:
            return f"{obj.veterinarian.first_name} {obj.veterinarian.last_name}".strip()
        return 'Desconocido'

    def get_pet_name(self, obj):
        from apps.core.subject_history import identity
        return identity(obj, 'pet').get('name') or (obj.pet.name if obj.pet_id else 'Desconocido')

    def get_pet_public_id(self, obj):
        return obj.pet.public_id if obj.pet_id and obj.pet.is_active else None

    def get_historical_pet_public_id(self, obj):
        from apps.core.subject_history import identity
        return identity(obj, 'pet').get('uuid')

    def get_pet_species(self, obj):
        from apps.core.subject_history import identity
        return identity(obj, 'pet').get('species') or (obj.pet.species if obj.pet_id else '')

    def get_pet_sex(self, obj):
        from apps.core.subject_history import identity
        return identity(obj, 'pet').get('sex') or (obj.pet.sex if obj.pet_id else None)

    def get_pet_birth_date(self, obj):
        from apps.core.subject_history import identity
        if identity(obj, 'pet').get('birth_date'):
            return identity(obj, 'pet')['birth_date']
        value = obj.pet.birth_date if obj.pet_id else None
        return value.isoformat() if value else None

    def validate_notes(self, value):
        return sanitize_text(value or '', max_length=5000)

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError(
                "La receta debe tener al menos un medicamento."
            )
        return items

    def validate_medical_record(self, mr):
        return require_same_organization(
            mr, self.context.get('request'), field='medical_record', serializer=type(self).__name__)

    def validate_pet(self, pet):
        return require_same_organization(
            pet, self.context.get('request'), field='pet', serializer=type(self).__name__)

    def validate(self, attrs):
        medical_record = attrs.get('medical_record')
        if medical_record and not self.instance:
            if hasattr(medical_record, 'prescription'):
                raise serializers.ValidationError(
                    "Esta consulta ya tiene una receta. Editá la existente."
                )

        # Inmutabilidad post-cierre. La receta es documento legal entregado al
        # paciente y su cantidad acota cuánto se puede dispensar, así que tras
        # cerrar la consulta solo se anota. Cubre también `items`, que `update`
        # reemplaza: sin esto, un PATCH posterior al cierre podía reescribir lo
        # prescrito —y con ello ensanchar el tope de dispensación— sin rastro.
        # Se evalúa contra la consulta YA GUARDADA, no contra la del payload.
        if self.instance is not None:
            from apps.medical_records.policies import assert_post_close_edit_allowed
            request = self.context.get('request')
            assert request is not None, (
                "PrescriptionSerializer requiere 'request' en el context para "
                "resolver el actor de la inmutabilidad post-cierre."
            )
            assert_post_close_edit_allowed(
                request.user,
                self.instance.medical_record,
                changed_fields=attrs.keys(),
                request=request,
            )
        return attrs

    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        prescription = Prescription.objects.create(**validated_data)
        for item_data in items_data:
            PrescriptionItem.objects.create(prescription=prescription, **item_data)
        return prescription

    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if items_data is not None:
            PrescriptionItem.all_objects.filter(prescription=instance).delete()
            for item_data in items_data:
                PrescriptionItem.objects.create(prescription=instance, **item_data)

        return instance


class PrescriptionItemWriteSerializer(_PrescriptionItemBase):
    """Endpoint `/prescriptions/<id>/items/`: además exige un producto con receta."""

    def validate_product(self, product):
        # El chequeo de organización va primero: no revelar `requires_prescription`
        # de productos de otra clínica (ADR p14 — P0 #9).
        product = super().validate_product(product)
        if not product.requires_prescription:
            raise serializers.ValidationError(
                "Este producto no requiere receta. Puede dispensarse directamente desde inventario."
            )
        return product
