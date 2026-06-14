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

    class Meta:
        indexes = [
            # Búsqueda de owners por nombre usa name__icontains (patients/views.py).
            # GIN trigram acelera substring match; sin él = seq scan por org.
            GinIndex(OpClass('name', name='gin_trgm_ops'), name='owner_name_trgm'),
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
    species = models.CharField(max_length=100)
    breed = models.CharField(max_length=100, blank=True, default='')
    birth_date = models.DateField(null=True, blank=True)
    sex = models.CharField(max_length=10, choices=SEX_CHOICES, default='unknown')
    color = models.CharField(max_length=100, blank=True, default='')

    is_generic = models.BooleanField(default=False)
    # Sprint import: nº de expediente del sistema viejo. Ver Owner.legacy_id.
    legacy_id = models.CharField(max_length=64, blank=True, default='')

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
            # Búsqueda de mascotas por nombre usa name__icontains (patients/views.py).
            GinIndex(OpClass('name', name='gin_trgm_ops'), name='pet_name_trgm'),
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