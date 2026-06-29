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
        ]
