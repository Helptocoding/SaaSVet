from uuid import uuid4

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower
from apps.organizations.models import Organization


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
    specialty = models.CharField(max_length=100, blank=True, default='')
    # M01 (orden 7, ADR p64): cédula profesional, solo dígitos (5 a 10), sin
    # verificar contra la SEP. Obligatoria para VET y para quien firma consultas y
    # recetas: lo exigen apps/users/professional.py y el dominio clínico. db_default
    # mantiene aditiva la migración (ver la nota de Organization.is_active).
    license_number = models.CharField(max_length=10, blank=True, default='', db_default='')
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
