"""
imports/models.py — Sesión de importación CSV/Excel (migración de clínicas).

ImportJob es la fuente de verdad de una sesión de import. Persiste las filas
parseadas (NO el archivo binario) + el mapping + el resultado, dando auditoría
y permitiendo el flujo de 3 fases sin reenviar miles de filas:

    upload  → status=pending    (parsea, guarda rows + columns + filename)
    mapping → (PATCH mapping)
    validate→ status=validated  (dry-run, NO escribe, guarda result preview)
    commit  → status=committed  (escribe en transaction.atomic, guarda result)

Ver docs/project_import_sprint.md.
"""
from django.db import models

from apps.core.models import OrganizationalModel, PublicIdMixin


class ImportJob(PublicIdMixin, OrganizationalModel):
    ENTITY_OWNER_PET = 'owner_pet'
    ENTITY_OWNER = 'owner'
    ENTITY_PRODUCT = 'product'
    ENTITY_INVENTORY = 'inventory'
    ENTITY_CHOICES = [
        (ENTITY_OWNER_PET, 'Clientes + Mascotas'),
        (ENTITY_OWNER, 'Clientes'),
        (ENTITY_PRODUCT, 'Productos'),
        (ENTITY_INVENTORY, 'Inventario'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_VALIDATED = 'validated'
    STATUS_COMMITTED = 'committed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pendiente'),
        (STATUS_VALIDATED, 'Validado'),
        (STATUS_COMMITTED, 'Importado'),
        (STATUS_FAILED, 'Fallido'),
    ]

    DEDUP_SKIP = 'skip'
    DEDUP_UPDATE = 'update'
    DEDUP_CREATE = 'create_anyway'
    DEDUP_CHOICES = [
        (DEDUP_SKIP, 'Saltar duplicados'),
        (DEDUP_UPDATE, 'Actualizar existentes'),
        (DEDUP_CREATE, 'Crear de todos modos'),
    ]

    entity_type = models.CharField(max_length=20, choices=ENTITY_CHOICES)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING,
    )
    # Solo el nombre, nunca el binario. Trazabilidad: "¿cuál archivo subieron?".
    original_filename = models.CharField(max_length=255, blank=True, default='')
    # Headers crudos del archivo (orden original).
    # blank=True: JSONField trata {}/[] como vacío y full_clean lo rechazaría;
    # estos campos arrancan vacíos antes del mapeo/validación.
    source_columns = models.JSONField(default=list, blank=True)
    # Filas parseadas (lista de listas, alineadas con source_columns). Cap 2000.
    rows = models.JSONField(default=list, blank=True)
    # { "<columna archivo>": "<campo destino>" } ej. {"Dueño": "owner.name"}.
    mapping = models.JSONField(default=dict, blank=True)
    dedup_strategy = models.CharField(
        max_length=20, choices=DEDUP_CHOICES, default=DEDUP_SKIP,
    )
    # Resultado de validate (preview) o commit:
    #   { created, skipped, errors:[{row, field, message}], warnings:[...] }
    result = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', '-created_at']),
        ]

    def __str__(self):
        return f"ImportJob<{self.entity_type} {self.status} {self.original_filename}>"


class ImportConflict(models.Model):
    """Detalles de la versión vigente; su ciclo de vida pertenece al job."""
    job = models.ForeignKey(ImportJob, on_delete=models.CASCADE, related_name='conflict_details')
    row = models.PositiveIntegerField()
    ordinal = models.PositiveIntegerField()
    payload = models.JSONField()

    class Meta:
        ordering = ['row', 'ordinal']
        constraints = [models.UniqueConstraint(fields=['job', 'ordinal'], name='import_conflict_job_ordinal_uniq')]
        indexes = [models.Index(fields=['job', 'row', 'ordinal'], name='import_conflict_order_idx')]
