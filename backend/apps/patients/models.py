from django.contrib.postgres.indexes import GinIndex, OpClass
from django.core.exceptions import ValidationError
from django.db import models
from apps.core.models import OrganizationalModel, PublicIdMixin

SPECIES_CHOICES = ['canino', 'felino', 'equino', 'ave', 'reptil', 'exótico', 'otro']


class Owner(PublicIdMixin, OrganizationalModel):
    name = models.CharField(max_length=255)
    # blank=True para soportar migración de clínicas: archivos viejos vienen sin
    # teléfono (Sprint import, Ajuste #1). El OwnerSerializer sigue exigiendo 10
    # dígitos en el alta manual (UI) — solo el importador, que crea vía .save()
    # directo, puede dejarlo vacío (dedup_key null, sin teléfono).
    phone = models.CharField(max_length=20, blank=True)
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

    class Meta:
        indexes = [
            # Búsqueda de owners por nombre/teléfono/expediente usa icontains
            # (patients/views.py + EntitySearch). GIN trigram acelera el substring
            # match; sin él = seq scan por org.
            GinIndex(OpClass('name', name='gin_trgm_ops'), name='owner_name_trgm'),
            GinIndex(OpClass('phone', name='gin_trgm_ops'), name='owner_phone_trgm'),
            GinIndex(OpClass('legacy_id', name='gin_trgm_ops'), name='owner_legacy_trgm'),
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


class Pet(PublicIdMixin, OrganizationalModel):
    SEX_CHOICES = (
        ('male', 'Macho'),
        ('female', 'Hembra'),
        ('unknown', 'Desconocido'),
    )

    name = models.CharField(max_length=255)
    # blank=True para migración de clínicas: expedientes viejos a veces no traen
    # especie (Sprint import). '' = especie pendiente. El alta MANUAL la sigue
    # exigiendo vía PetSerializer.validate_species — solo el importador admite ''.
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