from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from apps.patients.models import Pet
from apps.users.models import User
from apps.core.models import OrganizationalModel, PublicIdMixin


class MedicalRecord(PublicIdMixin, OrganizationalModel):
    class Status(models.TextChoices):
        OPEN = 'open', 'Abierta'
        CLOSED = 'closed', 'Cerrada'

    class ConsultationType(models.TextChoices):
        GENERAL   = 'general',   'General'
        VACCINE   = 'vaccine',   'Vacuna'
        SURGERY   = 'surgery',   'Cirugía'
        EMERGENCY = 'emergency', 'Emergencia'

    pet = models.ForeignKey(Pet, on_delete=models.PROTECT, related_name='medical_records')
    veterinarian = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='medical_records', null=True, blank=True)
    appointment = models.ForeignKey("appointments.Appointment", on_delete=models.SET_NULL, null=True, blank=True, related_name='medical_record')
    # Cadena de episodio (A3): un encuentro puede originarse de otro
    # (urgencia → cirugía → hospitalización). Único campo estructural nuevo en el
    # central. SET_NULL: borrar el origen no rompe el derivado. Sin UI aún (solo el
    # enlace de datos); `discharge_status='hospitalizacion'` enlazará a Hospitalización futura.
    originated_from = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='derived_records',
    )

    diagnosis = models.TextField(max_length=400, blank=True)
    treatment = models.TextField(max_length=400, blank=True)
    notes = models.TextField(max_length=5000, blank=True)
    weight = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    consultation_type = models.CharField(
        max_length=20,
        choices=ConsultationType.choices,
        default=ConsultationType.GENERAL,
        db_index=True,
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)

    # Temporary UI scratchpad.
    # May be deleted or reshaped without migration.
    # Never use as business source of truth.
    #
    # Borrador de UI de secciones en progreso (vaccine, surgery, ...), solo para
    # que sobrevivan a una recarga antes de finalizar la consulta. NO es historial
    # clinico. NUNCA leer para analytics, reportes, historial ni registros legales.
    # Los registros autoritativos se crean al finalizar (p.ej. VaccineRecord, via
    # services.apply_consultation_draft_on_close). Claves acotadas por whitelist en
    # el serializer (ALLOWED_CONSULTATION_DRAFT_KEYS). Forma: {"vaccine": {...}}
    consultation_draft = models.JSONField(default=dict, blank=True)

    # Analytics anchor (editable=False, solo escrito por close_medical_record view).
    # Ver docs/dashboard-metrics-contract.md §2.7.
    closed_at = models.DateTimeField(null=True, blank=True, editable=False)
    CLOSED_AT_SOURCE_CHOICES = (
        ('service', 'View writer (close_medical_record)'),
        ('fallback', 'Backfilled from updated_at'),
        ('legacy', 'Existed before provenance tracking'),
    )
    closed_at_source = models.CharField(
        max_length=24, choices=CLOSED_AT_SOURCE_CHOICES,
        default='service', editable=False,
    )
    closed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='closed_medical_records')
    # created_at, updated_at heredados de OrganizationalModel

    def clean(self):
        org = self.organization_id
        if org and self.pet_id and self.pet.organization_id != org:
            raise ValidationError("La mascota no pertenece a la misma organizacion que el registro medico.")
        if org and self.veterinarian_id and self.veterinarian.organization_id != org:
            raise ValidationError("El veterinario no pertenece a la misma organizacion que el registro medico.")
        if org and self.appointment_id and self.appointment.organization_id != org:
            raise ValidationError("La cita no pertenece a la misma organizacion que el registro medico.")

    def save(self, *args, **kwargs):
        # Invariante de event-authority: si el registro queda en estado CLOSED,
        # closed_at NO puede ser NULL. Defensa en profundidad sobre el
        # CHECK constraint a nivel DB (migración 0014). Bloquea bypasses
        # tipo `mr.status='closed'; mr.save()` desde shell o código nuevo
        # que no use close_medical_record(). Ver docs/analytics-schema-audit.md §2.5.
        if self.status == self.Status.CLOSED and self.closed_at is None:
            raise ValidationError(
                "MedicalRecord no puede quedar 'closed' sin closed_at. "
                "Usa medical_records/views.py::close_medical_record."
            )
        super().save(*args, **kwargs)

    @property
    def prescription_id(self):
        try:
            return self.prescription.id
        except Exception:
            return None

    @property
    def invoice_id(self):
        invoice = self.invoices.order_by('-posted_at', '-id').first()
        return invoice.id if invoice else None

    @property
    def invoice(self):
        """Documento financiero más reciente; puede no existir mientras hay Checkout."""
        return self.invoices.order_by('-posted_at', '-id').first()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "pet", "-created_at"]),
            # Capa 3 — analytics. Soportan medical_records_closed,
            # appointments_done_without_medical_record (conversion join),
            # medical_records_open* (clinical backlog).
            models.Index(fields=["organization", "status", "-closed_at"],
                         name="idx_mr_org_status_closed_at"),
            models.Index(fields=["organization", "appointment"],
                         name="idx_mr_org_appointment"),
            models.Index(fields=["organization", "status", "-created_at"],
                         name="idx_mr_org_status_created"),
        ]
        constraints = [
            # Event-authority invariant (analytics): si status='closed',
            # closed_at NO puede ser NULL. Bloquea bypasses tipo
            # `mr.status='closed'; mr.save()` desde shell o queryset.update().
            # Ver docs/analytics-schema-audit.md §2.5.
            models.CheckConstraint(
                condition=~models.Q(status='closed') | models.Q(closed_at__isnull=False),
                name="medicalrecord_closed_status_requires_closed_at",
            ),
        ]


class VaccineRecord(PublicIdMixin, OrganizationalModel):
    STATUS_CURRENT = 'current'
    STATUS_OVERDUE = 'overdue'
    STATUS_NO_SCHEDULED = 'no_scheduled'

    pet = models.ForeignKey(Pet, on_delete=models.PROTECT, related_name='vaccine_records')
    vaccine_name = models.CharField(max_length=255)
    application_date = models.DateField()
    next_due_date = models.DateField(null=True, blank=True)
    applied_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='applied_vaccines'
    )
    notes = models.TextField(blank=True)
    medical_record = models.ForeignKey(
        MedicalRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name='vaccine_records'
    )

    # Trazabilidad por lote (A2, spec inventario 2026-07-10). Ligado a inventario:
    # product/lot (SET_NULL) + snapshot denormalizado (lot_number/lot_expiry/
    # manufacturer) para que el registro legal sea INMUTABLE aunque el lote se
    # corrija/borre (append-only NOM-007/046). Todos nullable: vacuna de texto
    # libre (sin inventario) los deja vacíos.
    product = models.ForeignKey(
        'inventory.Product', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vaccine_records',
    )
    lot = models.ForeignKey(
        'inventory.StockLot', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vaccine_records',
    )
    lot_number = models.CharField(max_length=100, blank=True, default='')
    lot_expiry = models.DateField(null=True, blank=True)
    manufacturer = models.CharField(max_length=255, blank=True, default='')

    @property
    def status(self):
        if not self.next_due_date:
            return self.STATUS_NO_SCHEDULED
        from django.utils import timezone
        return self.STATUS_CURRENT if self.next_due_date > timezone.localdate() else self.STATUS_OVERDUE

    class Meta:
        ordering = ['-application_date', '-id']
        indexes = [
            models.Index(fields=['pet', 'vaccine_name']),
            # Capa 3 — analytics. vaccines_applied + vaccines_due_window.
            models.Index(fields=['organization', 'application_date'],
                         name='idx_vacc_org_app_date'),
            models.Index(fields=['organization', 'next_due_date'],
                         name='idx_vacc_org_next_due'),
        ]


class ConsultationAssessment(OrganizationalModel):
    """
    Valoración estructurada de una consulta de la **familia diagnóstica**
    (general y futuros control/revisión/dermatología comparten este modelo;
    el nombre no se ata al examen físico).

    Guarda la S (motivo + historia) y la O (exploración por sistemas)
    estructuradas de SOAP; el diagnóstico (A) y el plan (P) siguen viviendo en
    MedicalRecord. NO es transversal: cada acto clínico tiene su propia
    valoración (ver docs/diseno-protocolos-clinicos-2026-07-09.md).

    Se materializa en el cierre de la consulta
    (services.apply_consultation_draft_on_close), dentro del mismo atomic. Un
    protocolo NUNCA muta MedicalRecord; solo crea su propio registro (principio
    binding, ADR p50). El scratchpad `MedicalRecord.consultation_draft['general']`
    es el borrador de UI; este modelo es la fuente de verdad.

    `protocol_version` congela el esquema con que se capturó el registro, para
    interpretar correctamente registros viejos cuando el protocolo evolucione.
    """
    PROTOCOL_VERSION = 1

    medical_record = models.ForeignKey(
        MedicalRecord, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='consultation_assessments',
    )
    pet = models.ForeignKey(Pet, on_delete=models.PROTECT, related_name='consultation_assessments')
    assessed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='consultation_assessments',
    )
    # S de SOAP
    chief_complaint = models.CharField(max_length=255, blank=True)  # motivo principal (1 línea, buscable)
    history = models.TextField(max_length=5000, blank=True)         # anamnesis / historia
    # O de SOAP — exploración por sistemas (estructura libre por sistema: normal/alterado + hallazgo)
    exam = models.JSONField(default=dict, blank=True)
    differentials = models.TextField(max_length=2000, blank=True)
    recheck_date = models.DateField(null=True, blank=True)          # seguimiento del acto (próxima revisión)
    protocol_version = models.PositiveSmallIntegerField(default=1, editable=False)

    def clean(self):
        org = self.organization_id
        if org and self.pet_id and self.pet.organization_id != org:
            raise ValidationError("La mascota no pertenece a la misma organizacion que la valoracion.")
        if org and self.medical_record_id and self.medical_record.organization_id != org:
            raise ValidationError("La consulta no pertenece a la misma organizacion que la valoracion.")

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'pet', '-created_at'],
                         name='idx_consult_assess_org_pet'),
            models.Index(fields=['organization', 'medical_record'],
                         name='idx_consult_assess_org_mr'),
        ]


class SurgeryRecord(PublicIdMixin, OrganizationalModel):
    """
    Registro quirúrgico (protocolo Cirugía, A3 — diseño 2026-07-09 §12). Una tabla
    con los grupos PreOp · Procedimiento · Recuperación. Se materializa en el cierre;
    un protocolo NUNCA muta MedicalRecord (ADR p50). `protocol_version` congela el
    esquema para interpretar cirugías viejas cuando el protocolo evolucione.
    """
    PROTOCOL_VERSION = 1

    class SurgeryType(models.TextChoices):
        ELECTIVA = 'electiva', 'Electiva'
        PROGRAMADA = 'programada', 'Programada'
        URGENCIA = 'urgencia', 'Urgencia'
        EMERGENCIA = 'emergencia', 'Emergencia'

    class AsaClass(models.TextChoices):
        I = 'I', 'ASA I'
        II = 'II', 'ASA II'
        III = 'III', 'ASA III'
        IV = 'IV', 'ASA IV'
        V = 'V', 'ASA V'

    class AnesthesiaType(models.TextChoices):
        GENERAL = 'general', 'General'
        LOCORREGIONAL = 'locorregional', 'Locorregional'
        SEDACION = 'sedacion', 'Sedación'
        LOCAL = 'local', 'Local'

    class WoundClass(models.TextChoices):
        LIMPIA = 'limpia', 'Limpia'
        LIMPIA_CONTAMINADA = 'limpia_contaminada', 'Limpia-contaminada'
        CONTAMINADA = 'contaminada', 'Contaminada'
        SUCIA = 'sucia', 'Sucia'

    medical_record = models.ForeignKey(
        MedicalRecord, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='surgery_records',
    )
    pet = models.ForeignKey(Pet, on_delete=models.PROTECT, related_name='surgery_records')
    surgeon = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='surgeries_performed',
    )

    # PreOp
    preop_diagnosis = models.CharField(max_length=500, blank=True)
    surgery_type = models.CharField(max_length=20, choices=SurgeryType.choices)
    asa_class = models.CharField(max_length=5, choices=AsaClass.choices)
    asa_emergency = models.BooleanField(default=False)   # sufijo "E" de ASA

    # Procedimiento
    anesthesia_type = models.CharField(max_length=20, choices=AnesthesiaType.choices)
    procedure = models.TextField(max_length=2000)
    wound_class = models.CharField(max_length=20, choices=WoundClass.choices, blank=True, default='')
    findings = models.TextField(max_length=2000, blank=True)
    complications = models.TextField(max_length=2000, blank=True)   # "ninguna" permitido

    # Recuperación
    postop_instructions = models.TextField(max_length=2000)
    suture_removal_date = models.DateField(null=True, blank=True)

    protocol_version = models.PositiveSmallIntegerField(default=1, editable=False)

    def clean(self):
        org = self.organization_id
        if org and self.pet_id and self.pet.organization_id != org:
            raise ValidationError("La mascota no pertenece a la misma organización que la cirugía.")
        if org and self.medical_record_id and self.medical_record.organization_id != org:
            raise ValidationError("La consulta no pertenece a la misma organización que la cirugía.")

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'pet', '-created_at'],
                         name='idx_surgery_org_pet'),
            models.Index(fields=['organization', 'created_at'],
                         name='idx_surgery_org_created'),
        ]


class EmergencyRecord(PublicIdMixin, OrganizationalModel):
    """
    Registro de urgencia (protocolo Urgencia, A3 — diseño 2026-07-09 §13). Gira
    alrededor del **tiempo** (puerta→triage→estabilización→egreso) y del outcome.
    La UI muestra "Evaluación rápida" (semáforos) y guarda por detrás A/B/C. Se
    materializa en el cierre; un protocolo NUNCA muta MedicalRecord (ADR p50).
    Anchor analítico: `arrived_at`. `protocol_version` congela el esquema.
    """
    PROTOCOL_VERSION = 1

    class TriageLevel(models.TextChoices):
        RED = 'red', 'Rojo — reanimación'
        ORANGE = 'orange', 'Naranja — emergencia'
        YELLOW = 'yellow', 'Amarillo — urgente'
        GREEN = 'green', 'Verde — menos urgente'
        BLUE = 'blue', 'Azul — no urgente'

    class AbcStatus(models.TextChoices):
        NORMAL = 'normal', 'Normal'
        COMPROMISED = 'compromised', 'Comprometido'
        CRITICAL = 'critical', 'Crítico'

    class DischargeStatus(models.TextChoices):
        DISCHARGED = 'alta', 'Alta'
        HOSPITALIZED = 'hospitalizacion', 'Hospitalización'
        REFERRED = 'referido', 'Referido'
        DECEASED = 'fallecido', 'Fallecido'

    medical_record = models.ForeignKey(
        MedicalRecord, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='emergency_records',
    )
    pet = models.ForeignKey(Pet, on_delete=models.PROTECT, related_name='emergency_records')
    attended_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='emergencies_attended',
    )

    # Tiempos (el motor del protocolo). arrived_at = anchor.
    arrived_at = models.DateTimeField()
    triage_at = models.DateTimeField()
    stabilized_at = models.DateTimeField(null=True, blank=True)
    discharged_at = models.DateTimeField(null=True, blank=True)

    triage_level = models.CharField(max_length=10, choices=TriageLevel.choices)

    # "Evaluación rápida" → A/B/C por detrás.
    airway_status = models.CharField(max_length=15, choices=AbcStatus.choices)
    breathing_status = models.CharField(max_length=15, choices=AbcStatus.choices)
    circulation_status = models.CharField(max_length=15, choices=AbcStatus.choices)

    chief_complaint = models.CharField(max_length=255)
    stabilization_actions = models.TextField(max_length=2000)   # checklist + texto
    response = models.TextField(max_length=1000, blank=True)
    discharge_status = models.CharField(max_length=20, choices=DischargeStatus.choices)
    reassessment_date = models.DateField(null=True, blank=True)

    protocol_version = models.PositiveSmallIntegerField(default=1, editable=False)

    def clean(self):
        org = self.organization_id
        if org and self.pet_id and self.pet.organization_id != org:
            raise ValidationError("La mascota no pertenece a la misma organización que la urgencia.")
        if org and self.medical_record_id and self.medical_record.organization_id != org:
            raise ValidationError("La consulta no pertenece a la misma organización que la urgencia.")

    class Meta:
        ordering = ['-arrived_at', '-id']
        indexes = [
            models.Index(fields=['organization', 'pet', '-arrived_at'],
                         name='idx_emerg_org_pet'),
            models.Index(fields=['organization', 'arrived_at'],
                         name='idx_emerg_org_arrived'),
        ]


class VitalSigns(OrganizationalModel):
    """
    Registro histórico de signos vitales por consulta. Append-only: sin PATCH/DELETE.
    recorded_at representa el momento clínico real, que puede diferir de created_at
    en importaciones o carga tardía de datos.
    """
    medical_record   = models.ForeignKey(
        MedicalRecord, on_delete=models.CASCADE, related_name='vital_signs'
    )
    weight           = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    temperature      = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    heart_rate       = models.PositiveSmallIntegerField(null=True, blank=True)
    respiratory_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    recorded_by      = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='recorded_vitals'
    )
    recorded_at      = models.DateTimeField(default=timezone.now, db_index=True)

    def save(self, *args, **kwargs):
        if not self.organization_id:
            self.organization = self.medical_record.organization
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-recorded_at', '-created_at']
        indexes = [
            models.Index(fields=['medical_record', '-recorded_at', '-created_at']),
            models.Index(fields=['-recorded_at', '-created_at']),
        ]


class MedicalRecordService(OrganizationalModel):
    """
    Servicio clínico aplicado durante una consulta (consulta, vacuna, cirugía, etc.).
    Sincroniza automáticamente con InvoiceItem vía la view — no en el modelo.
    """
    medical_record = models.ForeignKey(
        MedicalRecord,
        on_delete=models.CASCADE,
        related_name='services_used',
    )
    service = models.ForeignKey(
        'billing.Service',
        on_delete=models.PROTECT,
        related_name='medical_record_usages',
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)

    def save(self, *args, **kwargs):
        if self.medical_record_id and not self.organization_id:
            self.organization_id = self.medical_record.organization_id
        super().save(*args, **kwargs)

    class Meta:
        unique_together = [['medical_record', 'service']]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="medicalrecordservice_quantity_positive",
            ),
        ]


# ---------------------------------------------------------------------------
# Helpers de peso — fuente de verdad compartida entre serializers
# ---------------------------------------------------------------------------

def _get_last_weight(pet):
    """
    Historial global del paciente: último peso entre VitalSigns y MedicalRecord.
    Prioriza VitalSigns (más granular). Ordenado por recorded_at (momento clínico).

    Día 6 audit F15: defense-in-depth — for_organization(pet.organization)
    antes del filter. Caller debe pasar pet ya tenant-validated; el guard
    explícito previene drift si futuro caller reusa esta helper sin scoping.
    """
    org = pet.organization
    last_vital = (
        VitalSigns.objects
        .for_organization(org)
        .filter(medical_record__pet=pet, weight__isnull=False)
        .order_by('-recorded_at', '-created_at')
        .first()
    )
    if last_vital:
        return last_vital.weight
    last_mr = (
        MedicalRecord.objects
        .for_organization(org)
        .filter(pet=pet, weight__isnull=False)
        .order_by('-created_at')
        .first()
    )
    return last_mr.weight if last_mr else None


def get_current_weight(record):
    """
    Peso a mostrar para una consulta específica (panel lateral).
    Diferente a _get_last_weight, que busca en toda la historia del paciente.
    """
    last_vital = record.vital_signs.order_by('-recorded_at', '-created_at').first()
    if last_vital and last_vital.weight is not None:
        return last_vital.weight
    return record.weight
