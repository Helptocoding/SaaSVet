from uuid import uuid4

from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models.functions import Lower
from apps.organizations.models import Organization
from apps.users.specialties import SPECIALTIES, specialties_display


class User(AbstractUser):
    ROLE_CHOICES = (
        ('ADMIN_SAAS', 'Admin SaaS'),
        ('ADMIN', 'Administrador'),
        ('VET', 'Veterinario'),
        ('ASSISTANT', 'Asistente'),
        # ADR p51: conjunto de permisos del agente virtual (service account).
        # La API de staff NO puede crear usuarios con este rol
        # (CreateEmployeeSerializer lo excluye); solo ensure_agent_users.
        ('AGENT', 'Agente virtual'),
    )

    # Día 6 Fase 5 (Issue #38): public_id para superficies externas.
    # /staff/<uuid>/deactivate/, /me response embedding, etc. PK secuencial
    # permitía enumeration cross-org de usuarios.
    public_id = models.UUIDField(
        default=uuid4,
        editable=False,
        unique=True,
        db_index=True,
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        null=True,
        blank=True
    )
    role = models.CharField(max_length=15, choices=ROLE_CHOICES, default='ASSISTANT')
    # ADR p68: catálogo cerrado, varias por integrante, en el orden del catálogo
    # (apps.users.specialties). Antes era texto libre (`specialty`).
    specialties = ArrayField(
        models.CharField(max_length=32, choices=SPECIALTIES),
        default=list, blank=True,
    )
    # M01 (orden 7, ADR p64): cédula profesional, solo dígitos (5 a 10), sin
    # verificar contra la SEP. Obligatoria para VET y para quien firma consultas y
    # recetas: lo exigen apps/users/professional.py y el dominio clínico. db_default
    # mantiene aditiva la migración (ver la nota de Organization.is_active).
    license_number = models.CharField(max_length=10, blank=True, default='', db_default='')
    # ADR p66: función clínica, separada del rol. Solo decide algo en ADMIN (el
    # dueño veterinario de una clínica pequeña): VET siempre atiende y ASSISTANT
    # nunca, y los servicios de Equipo fijan el campo así. Quién atiende se
    # pregunta SIEMPRE con apps.users.professional.is_clinician / clinician_q.
    attends_patients = models.BooleanField(default=False, db_default=False)
    is_active = models.BooleanField(default=True)

    # ADR p21: credential lifecycle — forced password change.
    # Multiple use cases (onboarding, admin reset, security policy
    # incidents, compromised credentials, first-login enforcement). The
    # `MustChangePasswordGate` permission blocks every endpoint except
    # the whitelist while this flag is True.
    password_must_change = models.BooleanField(default=False)

    # Set by `services.reset_password_for_staff` when an admin issues a
    # temporary password. Read by the login view to reject expired temps
    # (24h window). Cleared by `services.change_password` on success.
    password_temp_issued_at = models.DateTimeField(null=True, blank=True)

    # ADR p51: eje "clase de principal" (persona vs actor del sistema),
    # ortogonal a `role` (que nombra el conjunto de permisos). Las
    # superficies humanas (lista de Equipo, deactivate, reset-password)
    # excluyen service accounts por ESTE flag, nunca por nombre de rol —
    # así N agentes futuros no obligan a tocar esas superficies. El user
    # AGENT del subsistema conversacional es el primer service account.
    is_service_account = models.BooleanField(default=False)

    # ADR p65: versión de sesión. Viaja en cada token como claim `sv` y la
    # autenticación rechaza cualquier token con otra versión. Solo la escribe
    # `services.bump_session_version` (UPDATE con F(), atómico); `save()` nunca
    # la escribe en una fila existente, para que una instancia leída antes de un
    # incremento no la haga retroceder. Un gate estático lo vigila.
    session_version = models.PositiveIntegerField(
        default=0, db_default=0, editable=False,
    )

    class Meta(AbstractUser.Meta):
        indexes = [
            models.Index(fields=["organization", "role", "is_active"]),
        ]
        constraints = [
            # ADR p48: correo = identidad global única, case-insensitive.
            # PARCIAL (excluye email='') para que las cuentas técnicas
            # (superuser CLI, demo, seeds, fixtures de test) sin correo convivan.
            # La OBLIGATORIEDAD de correo en flujos de negocio (provisioning +
            # alta de staff) la enforzan los serializers, no el constraint:
            # ningún flujo normal de negocio crea usuarios sin correo.
            models.UniqueConstraint(
                Lower("email"),
                name="user_email_ci_unique",
                condition=~models.Q(email=""),
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(license_number='')
                    | models.Q(license_number__regex=r'^[0-9]{5,10}$')
                ),
                name='user_license_number_digits',
            ),
        ]

    @property
    def specialty_label(self):
        """«Cirugía, Dermatología» (ADR p68): lo que se muestra y se imprime."""
        return specialties_display(self.specialties)

    def save(self, *, force_insert=False, force_update=False, using=None, update_fields=None):
        """Guarda sin escribir nunca `session_version` en una fila existente (ADR p65).

        - `update_fields` con `session_version`: error de programación; la única
          escritura legítima es `services.bump_session_version`.
        - Guardado completo de una fila existente: los mismos campos que Django
          guardaría (concretos, sin la PK ni los diferidos) menos la versión.
        - Inserción: sin cambios; la versión nace en 0.
        """
        if update_fields is not None:
            if 'session_version' in update_fields:
                raise ValueError(
                    'session_version solo se modifica con '
                    'apps.users.services.bump_session_version (ADR p65).'
                )
        elif not self._state.adding and not force_insert and self.pk is not None:
            deferred = self.get_deferred_fields()
            update_fields = [
                field.attname
                for field in self._meta.concrete_fields
                if not field.primary_key
                and field.attname not in deferred
                and field.name != 'session_version'
            ]
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )


class StaffAccessEvent(models.Model):
    """Historial de accesos de un integrante de Equipo (ADR p66, decisión 7).

    De solo inserción: un evento no se corrige, se registra otro. Lo escriben los
    servicios de Equipo en la misma transacción que el cambio. ``changes`` guarda
    nombres de campo y roles, nunca contraseñas, correos ni otros valores
    personales (los logs siguen la misma regla).
    """
    KIND_CREATED = 'created'
    KIND_PROFILE_UPDATED = 'profile_updated'
    KIND_ROLE_CHANGED = 'role_changed'
    KIND_DEACTIVATED = 'deactivated'
    KIND_REACTIVATED = 'reactivated'
    KIND_PASSWORD_RESET = 'password_reset'
    # ADR p67: ausencias y reasignación de citas también quedan en la ficha.
    KIND_ABSENCE_ADDED = 'absence_added'
    KIND_ABSENCE_CANCELLED = 'absence_cancelled'
    KIND_APPOINTMENTS_REASSIGNED = 'appointments_reassigned'
    # ADR p68: verificación en dos pasos.
    KIND_MFA_ENABLED = 'mfa_enabled'
    KIND_MFA_DISABLED = 'mfa_disabled'
    KIND_CHOICES = (
        (KIND_CREATED, 'Alta'),
        (KIND_PROFILE_UPDATED, 'Edición de datos'),
        (KIND_ROLE_CHANGED, 'Cambio de rol'),
        (KIND_DEACTIVATED, 'Desactivación'),
        (KIND_REACTIVATED, 'Reactivación'),
        (KIND_PASSWORD_RESET, 'Restablecimiento de contraseña'),
        (KIND_ABSENCE_ADDED, 'Ausencia registrada'),
        (KIND_ABSENCE_CANCELLED, 'Ausencia cancelada'),
        (KIND_APPOINTMENTS_REASSIGNED, 'Citas reasignadas'),
        (KIND_MFA_ENABLED, 'Verificación en dos pasos activada'),
        (KIND_MFA_DISABLED, 'Verificación en dos pasos desactivada'),
    )

    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name='staff_access_events',
    )
    member = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, related_name='access_events',
    )
    actor = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, related_name='staff_actions',
    )
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    changes = models.JSONField(default=dict, blank=True)
    request_id = models.CharField(max_length=64, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['organization', 'member', '-created_at'],
                         name='staff_event_org_member_idx'),
        ]
        ordering = ['-created_at', '-pk']

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError('StaffAccessEvent es de solo inserción.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('StaffAccessEvent es de solo inserción.')


class StaffAbsence(models.Model):
    """Ausencia de un integrante por días completos (ADR p67).

    Fechas locales de la clínica, ambos extremos incluidos: es la misma unidad
    que ``Appointment.date``. Mientras una ausencia esté vigente
    (``cancelled_at`` nulo), nadie puede crear, mover ni reactivar citas de ese
    integrante en esos días, y el agente no ofrece sus huecos. No se borra: se
    cancela, y la cancelación queda con quién y cuándo.

    ``kind`` es una etiqueta operativa, no un diagnóstico: «Permiso» cubre una
    incapacidad sin registrar datos de salud.
    """
    KIND_VACATION = 'vacation'
    KIND_TRAINING = 'training'
    KIND_LEAVE = 'leave'
    KIND_OTHER = 'other'
    KIND_CHOICES = (
        (KIND_VACATION, 'Vacaciones'),
        (KIND_TRAINING, 'Capacitación'),
        (KIND_LEAVE, 'Permiso'),
        (KIND_OTHER, 'Otro'),
    )

    public_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name='staff_absences',
    )
    member = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, related_name='absences',
    )
    start_date = models.DateField()
    end_date = models.DateField()
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_OTHER)
    created_by = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, related_name='absences_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, related_name='absences_cancelled',
        null=True, blank=True,
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F('start_date')),
                name='staff_absence_end_not_before_start',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(cancelled_at__isnull=True, cancelled_by__isnull=True)
                    | models.Q(cancelled_at__isnull=False, cancelled_by__isnull=False)
                ),
                name='staff_absence_cancel_pair',
            ),
        ]
        indexes = [
            models.Index(fields=['organization', 'member', 'start_date'],
                         name='staff_absence_member_idx'),
            models.Index(fields=['organization', 'start_date', 'end_date'],
                         name='staff_absence_range_idx'),
        ]
        ordering = ['start_date', 'pk']

    @property
    def is_active(self):
        return self.cancelled_at is None


class UserMFA(models.Model):
    """Verificación en dos pasos de una persona (ADR p68): código de 6 dígitos de
    una app autenticadora (TOTP, ``apps.users.totp``).

    Opcional y solo para ADMIN. Mientras se configura, el secreto vive en
    ``pending_secret_encrypted``; pasa a ``secret_encrypted`` cuando la persona
    demuestra que su app genera códigos válidos. Los secretos se guardan
    cifrados y los códigos de respaldo, como HMAC: la base sola no permite
    generarlos ni leerlos.

    Un restablecimiento de contraseña (de clínica o de plataforma) y una
    reactivación borran esta fila: es la salida para quien perdió su celular y
    sus códigos de respaldo (decisión del PO).
    """
    user = models.OneToOneField('users.User', on_delete=models.CASCADE, related_name='mfa')
    secret_encrypted = models.TextField(blank=True, default='')
    pending_secret_encrypted = models.TextField(blank=True, default='')
    pending_created_at = models.DateTimeField(null=True, blank=True)
    enabled_at = models.DateTimeField(null=True, blank=True)
    # Último paso TOTP aceptado: un código no se acepta dos veces.
    last_used_step = models.BigIntegerField(null=True, blank=True)
    recovery_code_hashes = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(enabled_at__isnull=True)
                    | ~models.Q(secret_encrypted='')
                ),
                name='user_mfa_enabled_has_secret',
            ),
        ]

    @property
    def is_enabled(self):
        return self.enabled_at is not None and bool(self.secret_encrypted)
