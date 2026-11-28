from decimal import Decimal
from uuid import uuid4

from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from zoneinfo import available_timezones

from apps.core.validators import is_valid_mx_phone


# INV-L (ADR p70 D2): «agente encendido ⇒ teléfono válido». Este lado garantiza
# que un teléfono válido solo cambia por otro válido; el lado del agente
# (`AgentSettings.save`) exige uno válido para encender. Ambos bloquean primero
# la fila de la organización.
PHONE_INVALID_MESSAGE = (
    'Escribe un teléfono de 10 dígitos (por ejemplo 5512345678).'
)
PHONE_REQUIRED_MESSAGE = (
    'La clínica necesita un teléfono: el asistente de WhatsApp lo da en urgencias. '
    'Puedes cambiarlo por otro, pero no dejarlo vacío.'
)


def lock_organization_phone(organization_id):
    """Bloquea la fila de la organización y devuelve su teléfono PERSISTIDO.

    Exige una transacción abierta: fuera de ella el bloqueo se soltaría en la
    misma sentencia. `FOR NO KEY UPDATE`, el modo que ya usa el worker del
    agente: excluye a las otras escrituras de la fila sin frenar a las
    inserciones que solo la referencian por clave foránea.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError('lock_organization_phone() requiere una transacción abierta.')
    return (
        Organization.objects.select_for_update(no_key=True)
        .filter(pk=organization_id).values_list('phone', flat=True).first()
    )


def _validate_weekday_range(value):
    if value < 1 or value > 7:
        raise ValidationError('El día de la semana debe estar entre 1 (lunes) y 7 (domingo).')


class Organization(models.Model):
    public_id = models.UUIDField(
        default=uuid4,
        editable=False,
        unique=True,
        db_index=True,
    )
    name = models.CharField(max_length=255)

    display_name = models.CharField(max_length=255, blank=True, default='')

    timezone = models.CharField(max_length=64, default='America/Mexico_City')
    timezone_updated_at = models.DateTimeField(null=True, blank=True)
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.0000'),
        help_text="Tasa de IVA aplicada automáticamente a nuevos cobros (ej: 0.16 = 16%)"
    )

    # Contacto
    phone = models.CharField(max_length=32, blank=True, default='')
    whatsapp = models.CharField(max_length=32, blank=True, default='')
    email = models.EmailField(blank=True, default='')
    website = models.URLField(blank=True, default='')

    # Ubicacion
    address_line1 = models.CharField(max_length=255, blank=True, default='')
    address_line2 = models.CharField(max_length=255, blank=True, default='')
    district = models.CharField(max_length=120, blank=True, default='')
    city = models.CharField(max_length=120, blank=True, default='')
    state = models.CharField(max_length=120, blank=True, default='')
    postal_code = models.CharField(max_length=16, blank=True, default='')
    country = models.CharField(max_length=80, blank=True, default='Mexico')
    google_maps_url = models.URLField(blank=True, default='')
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # Instrucciones
    arrival_instructions = models.TextField(blank=True, default='')

    is_demo = models.BooleanField(default=False, db_index=True)
    # `db_default` no es decorativo en estas dos: son columnas REQUERIDAS
    # añadidas a una tabla que ya existía. Sin default en base, un escritor
    # anclado a un estado de esquema anterior omite la columna en su INSERT y
    # recibe NotNullViolation — es decir, la migración deja de ser aditiva
    # aunque se llame `preserve_*`. Lo cazaron dos ensayos de migración que
    # existen justo para eso (`test_b4_migration`,
    # `test_replies_migration::..._legacy_writers`): rebobinan `channels` a un
    # estado viejo y crean una Organization con el modelo histórico, que no
    # conoce estos campos.
    #
    # Misma trampa, aún latente, en otras columnas requeridas que el mismo
    # trabajo añadió a tablas preexistentes: `Presentation.quantity`,
    # `MedicalRecord.vet_name_at_close` / `vet_specialty_at_close` y los cuatro
    # `subject_snapshot` (Invoice, Checkout, Prescription, MedicalRecord). No se
    # tocaron porque ninguna prueba las ejercita todavía y un `db_default` sobre
    # JSONField exige envolver el valor en `Value`; cuando se ejerciten, la
    # regla a aplicar es ésta.
    is_active = models.BooleanField(default=True, db_default=True, db_index=True)
    deactivated_at = models.DateTimeField(null=True, blank=True, editable=False)
    deactivated_by = models.ForeignKey('users.User', on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name='+', editable=False)
    deactivation_reason = models.CharField(max_length=255, blank=True, default='',
                                           db_default='', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.timezone not in available_timezones():
            raise ValidationError({'timezone': 'Zona horaria invalida'})
        if (self.latitude is None) != (self.longitude is None):
            raise ValidationError('Latitud y longitud deben enviarse juntas.')
        if self.phone and not is_valid_mx_phone(self.phone):
            raise ValidationError({'phone': PHONE_INVALID_MESSAGE})

    def save(self, *args, **kwargs):
        update_fields = kwargs.get('update_fields')
        writes_phone = update_fields is None or 'phone' in update_fields
        if self.pk is None or not writes_phone:
            self.full_clean()
            super().save(*args, **kwargs)
            return
        # INV-L: se compara contra el valor persistido y bloqueado, nunca contra
        # el de esta instancia, que puede venir de una lectura vieja.
        with transaction.atomic():
            persisted = lock_organization_phone(self.pk)
            if is_valid_mx_phone(persisted or '') and not is_valid_mx_phone(self.phone or ''):
                raise ValidationError({'phone': PHONE_REQUIRED_MESSAGE})
            self.full_clean()
            super().save(*args, **kwargs)

    @property
    def public_name(self):
        """Nombre ante los clientes (ADR p70 D5): el comercial o, si está vacío,
        el legal. Lo usan los PDFs, el agente y el encabezado del menú."""
        return (self.display_name or '').strip() or self.name

    def __str__(self):
        return self.name


class OrganizationSettings(models.Model):
    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name='settings'
    )
    auto_create_medical_record = models.BooleanField(default=False)
    require_confirmation_before_start = models.BooleanField(default=False)
    allow_anonymous_walkin = models.BooleanField(default=False)
    show_status_change_history = models.BooleanField(default=True)
    require_open_cash_session = models.BooleanField(default=False)
    allow_post_unpaid = models.BooleanField(default=False)
    credit_default_days = models.PositiveSmallIntegerField(default=30)

    # ADR p70 D5: moneda de solo lectura (MXN). `locale`, `appointment_buffer_minutes`,
    # `allow_emergency_walkin` y `week_starts_on` se retiraron (migración 0019):
    # nadie los leía y la pantalla prometía un efecto que no existía.
    currency_code = models.CharField(max_length=3, default='MXN')
    default_appointment_duration_minutes = models.PositiveSmallIntegerField(default=30)

    def __str__(self):
        return f"Settings — {self.organization.name}"


class OrganizationSchedule(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='schedules'
    )
    weekday = models.PositiveSmallIntegerField(validators=[_validate_weekday_range])
    is_closed = models.BooleanField(default=False)
    opens_at = models.TimeField(null=True, blank=True)
    closes_at = models.TimeField(null=True, blank=True)
    has_break = models.BooleanField(default=False)
    break_start = models.TimeField(null=True, blank=True)
    break_end = models.TimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'weekday'],
                name='org_schedule_unique_weekday',
            ),
        ]
        ordering = ['weekday']

    def clean(self):
        if self.is_closed:
            self.opens_at = None
            self.closes_at = None
            self.has_break = False
            self.break_start = None
            self.break_end = None
            return
        if self.opens_at is None or self.closes_at is None:
            raise ValidationError('opens_at y closes_at son obligatorios cuando is_closed=False.')
        if self.opens_at >= self.closes_at:
            raise ValidationError('La hora de apertura debe ser anterior a la de cierre.')
        if self.has_break:
            if self.break_start is None or self.break_end is None:
                raise ValidationError('break_start y break_end son obligatorios cuando has_break=True.')
            if not (self.opens_at < self.break_start < self.break_end < self.closes_at):
                raise ValidationError('El descanso debe estar dentro del horario de apertura.')
        else:
            self.break_start = None
            self.break_end = None

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        status = 'Cerrado' if self.is_closed else f'{self.opens_at}–{self.closes_at}'
        return f'Weekday {self.weekday}: {status}'


class OrganizationClosure(models.Model):
    """Cierre excepcional de la clínica por días completos (ADR p70 D6, plan F2.1).

    Días locales de la clínica, ambos extremos incluidos (la misma unidad que
    ``Appointment.date``). Mientras esté vigente (``cancelled_at`` nulo), el
    agente no ofrece ni agenda citas esos días y «¿abierto ahora?» responde que
    no; el personal solo recibe un aviso (D6 a). No se borra: se cancela, con
    quién y cuándo. Lo escriben `services.create_closure` / `cancel_closure`,
    que bloquean las filas del horario de esos días de la semana: la misma fila
    que el agente toma con `FOR SHARE` antes de agendar.
    """
    public_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name='closures',
    )
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.CharField(max_length=120)
    created_by = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, related_name='closures_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, related_name='closures_cancelled',
        null=True, blank=True,
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F('start_date')),
                name='org_closure_end_not_before_start',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(cancelled_at__isnull=True, cancelled_by__isnull=True)
                    | models.Q(cancelled_at__isnull=False, cancelled_by__isnull=False)
                ),
                name='org_closure_cancel_pair',
            ),
        ]
        indexes = [
            models.Index(fields=['organization', 'start_date', 'end_date'],
                         name='org_closure_range_idx'),
        ]
        ordering = ['start_date', 'pk']

    @property
    def is_active(self):
        return self.cancelled_at is None


class OrganizationConfigEvent(models.Model):
    """Historial de cambios de la configuración de la clínica (ADR p70 D9).

    De solo inserción: un evento no se corrige, se registra otro. Lo escriben
    los servicios de Configuración (`organizations.services`,
    `billing.catalog_services`) en la misma transacción que el cambio y solo si
    algo cambió; un rollback no deja evento. Absorbe al antiguo
    `OrganizationTimezoneAudit` (migración 0018).

    ``changes`` es ``{campo: [antes, después]}``. Son datos de la empresa, no
    de personas. ``subject`` identifica el objeto cuando no es la clínica misma
    (un servicio: ``{"type": "service", "public_id", "name"}``), para que el
    historial diga de cuál se trata aunque su nombre no haya cambiado.
    """
    KIND_CLINIC_UPDATED = 'clinic_updated'
    KIND_TIMEZONE_CHANGED = 'timezone_changed'
    KIND_RULES_UPDATED = 'rules_updated'
    KIND_SCHEDULE_REPLACED = 'schedule_replaced'
    KIND_CLOSURE_ADDED = 'closure_added'
    KIND_CLOSURE_CANCELLED = 'closure_cancelled'
    KIND_SERVICE_CREATED = 'service_created'
    KIND_SERVICE_UPDATED = 'service_updated'
    KIND_SERVICE_ACTIVATED = 'service_activated'
    KIND_SERVICE_DEACTIVATED = 'service_deactivated'
    KIND_SERVICE_DELETED = 'service_deleted'
    KIND_CHOICES = (
        (KIND_CLINIC_UPDATED, 'Datos de la clínica'),
        (KIND_TIMEZONE_CHANGED, 'Zona horaria'),
        (KIND_RULES_UPDATED, 'Reglas de operación'),
        (KIND_SCHEDULE_REPLACED, 'Horario'),
        (KIND_CLOSURE_ADDED, 'Cierre registrado'),
        (KIND_CLOSURE_CANCELLED, 'Cierre cancelado'),
        (KIND_SERVICE_CREATED, 'Servicio creado'),
        (KIND_SERVICE_UPDATED, 'Servicio editado'),
        (KIND_SERVICE_ACTIVATED, 'Servicio activado'),
        (KIND_SERVICE_DEACTIVATED, 'Servicio desactivado'),
        (KIND_SERVICE_DELETED, 'Servicio eliminado'),
    )

    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name='config_events',
    )
    actor = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    occurred_at = models.DateTimeField(default=timezone.now)
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    subject = models.JSONField(default=dict, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    request_id = models.CharField(max_length=64, blank=True, default='')

    class Meta:
        indexes = [
            models.Index(fields=['organization', '-occurred_at'],
                         name='org_config_event_org_idx'),
        ]
        ordering = ['-occurred_at', '-pk']

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError('OrganizationConfigEvent es de solo inserción.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('OrganizationConfigEvent es de solo inserción.')


class OrganizationStateAudit(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT,
                                     related_name='state_audits')
    actor = models.ForeignKey('users.User', on_delete=models.PROTECT)
    active = models.BooleanField()
    reason = models.CharField(max_length=255)
    changed_at = models.DateTimeField(default=timezone.now)

