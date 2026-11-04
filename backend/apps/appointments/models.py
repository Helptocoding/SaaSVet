from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Func, Q
from apps.patients.models import Pet
from apps.users.models import User
from apps.core.models import OrganizationalModel, PublicIdMixin


class TsTzRange(Func):
    """`tstzrange(start, end, '[)')` — el intervalo ocupado por una cita.

    Semiabierto por la derecha a propósito: una cita de 10:00–10:30 y otra de
    10:30–11:00 NO se solapan. Es exactamente el criterio del pre-chequeo del
    serializer (`start__lt=end AND end__gt=start`), para que la garantía de la
    base y el mensaje legible no puedan discrepar.
    """
    function = 'TSTZRANGE'
    output_field = DateTimeRangeField()


class Appointment(PublicIdMixin, OrganizationalModel):
    CATEGORY_CHOICES = (
        ('general_consultation', 'Consulta general'),
        ('preventive_vaccination', 'Vacunación / preventiva'),
        ('surgery_procedure', 'Cirugía o procedimiento'),
        ('grooming', 'Estética'),
        ('follow_up', 'Seguimiento'),
        ('emergency', 'Urgencia'),
        ('other', 'Otro'),
    )

    STATUS_CHOICES = (
        ('scheduled', 'Programada'),
        ('confirmed', 'Confirmada'),
        ('in_progress', 'En consulta'),
        ('done', 'Completada'),
        ('canceled', 'Cancelada'),
        ('no_show', 'No se presentó'),
    )

    pet = models.ForeignKey("patients.Pet", on_delete=models.PROTECT)
    veterinarian = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True)

    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    # Sin db_index lone (Capa 2): el composite (organization, start_datetime,
    # status) cubre listing/analytics org-scoped; la deteccion de conflictos se
    # apoya en el indice FK de veterinarian_id + filtro residual sobre pocas
    # filas/vet. Si conflict-detection profilea lento, usar un composite
    # (organization, veterinarian, start_datetime), no indices lone globales.
    start_datetime = models.DateTimeField(null=True, blank=True)
    end_datetime = models.DateTimeField(null=True, blank=True)
    timezone_at_creation = models.CharField(max_length=64, default='UTC')

    reason = models.CharField(max_length=255)
    category = models.CharField(
        max_length=32,
        choices=CATEGORY_CHOICES,
        default='general_consultation',
    )
    notes = models.TextField(blank=True)
    cancellation_reason = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="scheduled")

    # Authoritative walk-in flag. Hasta migración 0010 esto se inferia desde
    # AppointmentStatusChange history (frágil). Ahora se setea explícito en
    # walk_in() view. Ver docs/analytics-schema-audit.md §2.9.
    walk_in = models.BooleanField(default=False, editable=False, db_index=True)

    # A2-1 (ADR appointment-idempotency): deduplicación de creación. Opcional
    # (null); un reintento de red con la misma X-Idempotency-Key devuelve la
    # cita original en vez de crear otra. Patrón espejo de Payment
    # (billing, ADR p27). Beneficia también al doble-click del frontend.
    idempotency_key = models.CharField(
        max_length=64, null=True, blank=True, editable=False,
    )

    # B8B causal provenance, separate from human request idempotency. Clinical
    # rows survive retention mistakes: deleting the operation is PROTECTED.
    source_operation = models.OneToOneField(
        'agent.ConversationOperation', to_field='operation_key',
        on_delete=models.PROTECT, null=True, blank=True, editable=False,
        related_name='created_appointment',
    )
    source_parameters_digest = models.CharField(max_length=64, null=True, blank=True, default=None, editable=False)

    def clean(self):
        org = self.organization_id
        if org and self.pet_id and self.pet.organization_id != org:
            raise ValidationError("La mascota no pertenece a la misma organizacion que la cita.")
        if org and self.veterinarian_id and self.veterinarian.organization_id != org:
            raise ValidationError("El veterinario no pertenece a la misma organizacion que la cita.")
        if self.source_operation_id:
            operation = self.source_operation
            if (operation.organization_id != org or operation.pet_id != self.pet_id
                    or operation.operation_kind != 'CREATE_APPOINTMENT'
                    or operation.parameters_digest != self.source_parameters_digest):
                raise ValidationError('La procedencia de la cita no coincide con su operación.')
        elif self.source_parameters_digest:
            raise ValidationError('El digest exige una operación de origen.')

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).all_objects.filter(pk=self.pk).values_list(
                'source_operation_id', 'source_parameters_digest').first()
            if previous and previous != (self.source_operation_id, self.source_parameters_digest):
                raise ValidationError('La procedencia de una cita es inmutable.')
        return super().save(*args, **kwargs)

    @property
    def medical_record_ids(self):
        return list(self.medical_record.order_by('id').values_list('id', flat=True))

    @property
    def invoice_id(self):
        invoice = self.invoices.order_by('-posted_at', '-id').first()
        return invoice.id if invoice else None

    @property
    def invoice(self):
        return self.invoices.order_by('-posted_at', '-id').first()

    class Meta:
        ordering = ["date", "start_time"]
        indexes = [
            models.Index(fields=["organization", "date", "status"]),
            # Capa 3 — analytics. start_datetime es el anchor canónico de
            # bucketing diario operativo (ver dashboard contract §3.2.2).
            # El index existente sobre 'date' (DateField) cubre queries
            # legacy; este compuesto cubre rollups por start_datetime.
            models.Index(fields=["organization", "start_datetime", "status"],
                         name="idx_appt_org_start_status"),
        ]
        constraints = [
            models.UniqueConstraint(fields=['id', 'organization'], name='appointment_id_org_ref'),
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F('start_time')),
                name="appointment_end_after_start",
            ),
            # A2-1: unique por (org, key) SOLO cuando la key existe. Permite
            # múltiples NULL (creaciones sin idempotencia, comportamiento
            # actual). Igual que Payment.idempotency_key (ADR p27).
            models.UniqueConstraint(
                fields=['organization', 'idempotency_key'],
                condition=models.Q(idempotency_key__isnull=False),
                name='appointment_unique_idempotency_key_per_org',
            ),
            # INV-D (ADR p57, decisión §3.4) — un veterinario no tiene dos
            # citas ACTIVAS solapadas. La garantía vive en la tabla, no en un
            # endpoint: cubre creación, reprogramación, atención sin cita y
            # reactivación, y a cualquier actor presente o futuro (frontend,
            # importador, script de soporte, integración), sin rollout por
            # fases.
            #
            # Fuera del predicado, a propósito:
            #   - `done`/`canceled`/`no_show`: una cita cancelada NO bloquea el
            #     hueco — es la regla de negocio vigente.
            #   - citas sin veterinario (`veterinarian` es nullable): no hay
            #     recurso que reservar. Coherente con el pre-chequeo actual,
            #     que también exige veterinario.
            #   - filas sin instantes UTC (datos legacy pre-0003).
            #
            # Requiere la extensión `btree_gist` (los componentes de igualdad
            # no son indexables por GiST sin ella); la crea la migración 0014,
            # igual que `TrigramExtension` en patients/0012.
            ExclusionConstraint(
                name='appointment_no_overlap_per_vet',
                expressions=[
                    ('organization', RangeOperators.EQUAL),
                    ('veterinarian', RangeOperators.EQUAL),
                    (
                        TsTzRange('start_datetime', 'end_datetime', RangeBoundary()),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                condition=(
                    Q(status__in=['scheduled', 'confirmed', 'in_progress'])
                    & Q(veterinarian__isnull=False)
                    & Q(start_datetime__isnull=False)
                    & Q(end_datetime__isnull=False)
                ),
            ),
        ]


class AppointmentStatusChange(OrganizationalModel):
    appointment = models.ForeignKey(
        Appointment, on_delete=models.CASCADE, related_name='status_changes'
    )
    from_status = models.CharField(max_length=20)
    to_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='appointment_status_changes',
    )
    reason = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']


class AppointmentMutationEffect(models.Model):
    """B8C proof of one historical transition, independent of current appointment."""
    organization = models.ForeignKey('organizations.Organization', on_delete=models.PROTECT)
    operation = models.OneToOneField('agent.ConversationOperation', to_field='operation_key',
        on_delete=models.PROTECT, related_name='appointment_mutation_effect')
    appointment = models.ForeignKey(Appointment, on_delete=models.PROTECT, related_name='mutation_effects')
    kind = models.CharField(max_length=32, choices=[
        ('RESCHEDULE_APPOINTMENT', 'RESCHEDULE_APPOINTMENT'), ('CANCEL_APPOINTMENT', 'CANCEL_APPOINTMENT'),
        ('CONFIRM_ATTENDANCE', 'CONFIRM_ATTENDANCE')])
    status_change = models.OneToOneField(AppointmentStatusChange, on_delete=models.PROTECT,
        null=True, blank=True, related_name='mutation_effect')
    parameters_digest = models.CharField(max_length=64)
    before = models.JSONField()
    after = models.JSONField()
    committed_at = models.DateTimeField()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Appointment effect evidence is immutable.')
        operation = self.operation
        if (operation.organization_id != self.organization_id
                or self.appointment.organization_id != self.organization_id
                or operation.appointment_id != self.appointment_id
                or operation.parameters_digest != self.parameters_digest
                or operation.operation_kind != self.kind
                or operation.consent_state != 'AUTHORIZED'
                or operation.preconditions.get('appointment_snapshot') != self.before):
            raise ValidationError('Appointment effect scope does not match its operation.')
        self.full_clean()
        return super().save(*args, **kwargs)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=models.Q(kind__in=['RESCHEDULE_APPOINTMENT', 'CANCEL_APPOINTMENT', 'CONFIRM_ATTENDANCE']),
            name='appointment_mutation_kind_valid')]
