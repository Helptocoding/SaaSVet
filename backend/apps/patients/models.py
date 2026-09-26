from django.contrib.postgres.indexes import GinIndex, OpClass
from django.core.exceptions import ValidationError
from django.db import models
from apps.core.models import OrganizationalModel, PublicIdMixin
from apps.core.validators import phone_key

SPECIES_CHOICES = ['canino', 'felino', 'equino', 'ave', 'reptil', 'exótico', 'otro']


class Owner(PublicIdMixin, OrganizationalModel):
    name = models.CharField(max_length=255)
    # blank=True para soportar migración de clínicas: archivos viejos vienen sin
    # teléfono (Sprint import, Ajuste #1). El OwnerSerializer sigue exigiendo 10
    # dígitos en el alta manual (UI) — solo el importador, que crea vía .save()
    # directo, puede dejarlo vacío (dedup_key null, sin teléfono).
    phone = models.CharField(max_length=20, blank=True)
    # INV-C (ADR p57 / decisión §4.7.2): clave de deduplicación e IDENTIDAD del
    # expediente. `phone` es texto libre y se guarda como lo tecleó cada quien
    # ("55 1234 5678" vs "5512345678"); esta columna es el valor comparable.
    #
    # NULL = "no tiene clave de cliente" (sin teléfono, menos de 10 dígitos, o
    # `is_generic=True` — §4.12: el teléfono de relleno del genérico NUNCA es
    # identidad de nadie). NULL queda fuera de todo conteo, lock y comparación
    # de igualdad sin que haya que recordarlo en cada consulta.
    #
    # La deriva SIEMPRE el dominio en `save()`, nunca el cliente (`editable=False`
    # + fuera de los serializers). NO lleva restricción única: INV-C admite
    # duplicados históricos y obliga a tratarlos como `owner_ambiguous`, no a
    # fusionarlos (§4.7.1).
    phone_normalized = models.CharField(
        max_length=10, null=True, blank=True, editable=False,
    )
    is_generic = models.BooleanField(default=False)
    # Sprint import: identificador del sistema/clínica de origen (nº de cliente
    # del software viejo). NO es PK ni reemplaza public_id — solo referencia.
    # UI lo muestra como "Número de expediente anterior", nunca "legacy_id".
    # default='' (NO null): muchos owners sin legacy conviven; el unique parcial
    # solo aplica cuando hay valor.
    legacy_id = models.CharField(max_length=64, blank=True, default='')
    # Datos históricos importados del sistema viejo de la clínica (Sprint import
    # Fase D). SOLO LECTURA / display — NO es el campo de notas operativas vivas
    # (eso será otro campo en otra fase). Lista de {label, value} para preservar
    # orden original y labels repetidos. Ver docs/project_import_sprint.md §Fase D.
    extra_data = models.JSONField(default=list, blank=True)

    def save(self, *args, update_fields=None, **kwargs):
        """Deriva `phone_normalized` en TODA escritura, sin excepción.

        Vive aquí y no en el servicio a propósito: el servicio garantiza la
        *deduplicación* (lock + conteo), pero la *consistencia* del campo no
        puede depender de que cada vía lo recuerde. Un `Owner` creado por una
        siembra, un comando o una vía nueva sigue teniendo su clave correcta;
        lo que esa vía se pierde es el lock, no la verdad del dato.
        """
        derived = None if self.is_generic else phone_key(self.phone)
        if derived != self.phone_normalized:
            self.phone_normalized = derived
            if update_fields is not None:
                # Un `save(update_fields=['phone'])` dejaría la clave sin
                # persistir: el dato quedaría mintiendo respecto al teléfono.
                update_fields = set(update_fields) | {'phone_normalized'}
        if update_fields is not None:
            kwargs['update_fields'] = update_fields
        return super().save(*args, **kwargs)

    class Meta:
        indexes = [
            # Búsqueda de owners por nombre/teléfono/expediente usa icontains
            # (patients/views.py + EntitySearch). GIN trigram acelera el substring
            # match; sin él = seq scan por org.
            GinIndex(OpClass('name', name='gin_trgm_ops'), name='owner_name_trgm'),
            GinIndex(OpClass('phone', name='gin_trgm_ops'), name='owner_phone_trgm'),
            GinIndex(OpClass('legacy_id', name='gin_trgm_ops'), name='owner_legacy_trgm'),
            # INV-C: el conteo de deduplicación es una igualdad por
            # (organización, clave), no un icontains sobre el GIN de trigramas.
            models.Index(
                fields=['organization', 'phone_normalized'],
                name='owner_phone_key_idx',
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['organization'],
                condition=models.Q(is_generic=True),
                name='unique_generic_owner_per_organization',
            ),
            # legacy_id único por organización SOLO cuando está presente.
            # Excluir '' permite N owners sin legacy; bloquea dos "00231" en la
            # misma org. Mismo legacy_id en otra org = OK (scope tenant).
            models.UniqueConstraint(
                fields=['organization', 'legacy_id'],
                condition=~models.Q(legacy_id=''),
                name='owner_legacy_id_unique_per_org',
            ),
        ]


class PetRegistrationEffect(models.Model):
    """Immutable historical creation, independent from mutable Pet fields.

    PostgreSQL verifies INSERT scope/definition and rejects UPDATE/DELETE.
    Human and legacy pets have no row. Never backfill provenance.
    """
    operation = models.OneToOneField('agent.ConversationOperation', to_field='operation_key',
        on_delete=models.PROTECT, related_name='pet_registration_effect')
    organization = models.ForeignKey('organizations.Organization', on_delete=models.PROTECT)
    owner = models.ForeignKey(Owner, on_delete=models.PROTECT)
    pet = models.OneToOneField('Pet', on_delete=models.PROTECT, related_name='registration_effect')
    parameters_digest = models.CharField(max_length=64)
    definition = models.JSONField()
    committed_at = models.DateTimeField()


class Pet(PublicIdMixin, OrganizationalModel):
    SEX_CHOICES = (
        ('male', 'Macho'),
        ('female', 'Hembra'),
        ('unknown', 'Desconocido'),
    )

    name = models.CharField(max_length=255)
    # blank=True para migración de clínicas: expedientes viejos a veces no traen
    # especie (Sprint import). '' = especie pendiente también en alta manual.
    species = models.CharField(max_length=100, blank=True, default='')
    breed = models.CharField(max_length=100, blank=True, default='')
    birth_date = models.DateField(null=True, blank=True)
    sex = models.CharField(max_length=10, choices=SEX_CHOICES, default='unknown')
    color = models.CharField(max_length=100, blank=True, default='')

    is_generic = models.BooleanField(default=False)
    # Sprint import: nº de expediente del sistema viejo. Ver Owner.legacy_id.
    legacy_id = models.CharField(max_length=64, blank=True, default='')
    # Datos históricos importados (Sprint import Fase D). SOLO LECTURA / display.
    # NO confundir con futuras notas operativas vivas del paciente (Pet.notes en
    # otra fase). Lista de {label, value}. Ver docs/project_import_sprint.md §Fase D.
    extra_data = models.JSONField(default=list, blank=True)

    owner = models.ForeignKey(
        Owner,
        on_delete=models.PROTECT,
        related_name="pets"
    )

    def clean(self):
        if self.owner_id and self.organization_id:
            if self.owner.organization_id != self.organization_id:
                raise ValidationError("El propietario no pertenece a la misma organizacion que la mascota.")

    class Meta:
        indexes = [
            models.Index(fields=["organization", "owner"]),
            # Búsqueda de mascotas por nombre/expediente usa icontains
            # (patients/views.py + EntitySearch). GIN trigram para el substring match.
            GinIndex(OpClass('name', name='gin_trgm_ops'), name='pet_name_trgm'),
            GinIndex(OpClass('legacy_id', name='gin_trgm_ops'), name='pet_legacy_trgm'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['organization'],
                condition=models.Q(is_generic=True),
                name='unique_generic_pet_per_organization',
            ),
            models.UniqueConstraint(
                fields=['organization', 'legacy_id'],
                condition=~models.Q(legacy_id=''),
                name='pet_legacy_id_unique_per_org',
            ),
        ]
