from decimal import Decimal
from uuid import uuid4

from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from zoneinfo import available_timezones


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

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

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

    locale = models.CharField(max_length=16, default='es-MX')
    currency_code = models.CharField(max_length=3, default='MXN')
    default_appointment_duration_minutes = models.PositiveSmallIntegerField(default=30)
    appointment_buffer_minutes = models.PositiveSmallIntegerField(default=0)
    allow_emergency_walkin = models.BooleanField(default=False)
    week_starts_on = models.PositiveSmallIntegerField(default=1, validators=[_validate_weekday_range])

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


class OrganizationTimezoneAudit(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name='timezone_audits',
    )
    old_timezone = models.CharField(max_length=64)
    new_timezone = models.CharField(max_length=64)
    changed_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='organization_timezone_changes',
    )
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-changed_at']


class OrganizationStateAudit(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT,
                                     related_name='state_audits')
    actor = models.ForeignKey('users.User', on_delete=models.PROTECT)
    active = models.BooleanField()
    reason = models.CharField(max_length=255)
    changed_at = models.DateTimeField(default=timezone.now)

