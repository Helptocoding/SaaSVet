"""
Authoritative tenant provisioning service.

This is the *only* code path that creates a new Organization together
with its initial admin user. Direct callers (views, mgmt commands)
must use `provision_organization()` rather than orchestrating
Organization/User creation themselves — the side effects, audit trail,
and post-conditions live here.

Side effects guaranteed inside a single atomic block:
  1. `Organization` row created.
  2. `organizations.signals.initialize_organization` fires:
       - `OrganizationSettings` with defaults.
       - Generic `Owner` ("Público General") + generic `Pet`
         ("Paciente Anónimo") for walk-in flows.
       - System `Role`s seeded (ADMIN, VET, ASSISTANT) with permissions.
  3. `User` row created with `role='ADMIN'`, `is_staff=False`,
     `is_superuser=False`.
  4. `users.signals.assign_rbac_role_on_create` fires:
       - `UserRole(user, role)` get_or_created without `assigned_by`.
  5. This service runs `UserRole.objects.update_or_create(...,
     defaults={'assigned_by': actor})` to backfill the audit field that
     the signal cannot set.
  6. Post-condition assertion confirms the `UserRole` exists with
     `assigned_by` populated.

A failure in any of steps 1–6 rolls back the entire transaction. The
post-condition guarantees an invariant the rest of the platform depends
on: a freshly provisioned organization always has at least one usable
ADMIN account.
"""
import logging
import time
import uuid
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from apps.core.models import Role, UserRole
from apps.organizations.models import Organization


User = get_user_model()
logger = logging.getLogger('platform.events')


@dataclass
class ProvisionResult:
    """Return shape for `provision_organization`."""
    organization: Organization
    admin: User
    duration_ms: int
    request_id: str


@transaction.atomic
def provision_organization(*, actor, validated_data, request_id=None,
                           require_password_change=True):
    """
    Create a tenant Organization together with its initial admin user.

    Args:
        actor: The authenticated platform operator initiating the call
            (`request.user`). Used for audit (`UserRole.assigned_by`) and
            structured log context.
        validated_data: Dict from `ProvisionOrgSerializer.validated_data`.
            Required keys: name, timezone, tax_rate, admin_username,
            admin_email, admin_password, admin_first_name, admin_last_name.
        request_id: Correlation id for log/response tagging. Generated
            (uuid4) if not provided.
        require_password_change: When True (default), the provisioned admin is
            created with ``password_must_change=True`` so the first login is
            forced through the change-password flow (MustChangePasswordGate).
            ``password_temp_issued_at`` is left None → the temp does NOT expire
            (unlike admin resets, ADR p21). Seeds (demo) pass False for a
            direct-login admin.

    Returns:
        ProvisionResult with the persisted Organization, admin User,
        elapsed duration in ms, and the correlation id.

    Raises:
        ValidationError: A race between serializer validation and DB
            insert produced an IntegrityError on username/email/org name.
            Translated to a 400-friendly error.
        RuntimeError: The post-condition (UserRole present with
            `assigned_by=actor`) was not satisfied. Indicates a bug in
            signal wiring or RBAC seed — transaction is rolled back.
    """
    request_id = request_id or str(uuid.uuid4())
    started_at = time.monotonic()
    d = validated_data

    try:
        # 1. Organization. The post_save signal in
        #    `organizations.signals.initialize_organization` runs synchronously
        #    here and creates OrganizationSettings + generic Owner/Pet +
        #    system Roles (ADMIN, VET, ASSISTANT).
        org = Organization.objects.create(
            name=d['name'],
            timezone=d['timezone'],
            tax_rate=d['tax_rate'],
        )

        # 2. Initial admin user.
        #    role='ADMIN' is the legacy fallback channel; RBAC UserRole
        #    below is the authoritative grant.
        #    is_staff/is_superuser explicitly False — server controls
        #    privilege regardless of payload.
        admin = User.objects.create_user(
            username=d['admin_username'],
            email=d['admin_email'],
            password=d['admin_password'],
            first_name=d['admin_first_name'],
            last_name=d['admin_last_name'],
            role='ADMIN',
            organization=org,
            is_staff=False,
            is_superuser=False,
            is_active=True,
        )

        # Onboarding hardening: el admin provisionado entra con una contraseña de
        # un solo uso. password_must_change=True fuerza el cambio en el primer
        # login (MustChangePasswordGate). NO se setea password_temp_issued_at: la
        # temporal de provisioning NO caduca a 24h (el handoff operador→clínica
        # puede tardar más), a diferencia del reset admin (ADR p21). Los seeds
        # (demo) pasan require_password_change=False para un admin de login directo.
        if require_password_change:
            admin.password_must_change = True
            admin.save(update_fields=['password_must_change'])

        # 3. Resolve the seeded ADMIN role.
        #    Role is not an OrganizationalModel — use direct filter
        #    (`for_organization()` is not available on this manager).
        try:
            admin_role = Role.objects.filter(
                organization=org,
                name='ADMIN',
                is_system_role=True,
            ).get()
        except Role.DoesNotExist as exc:
            # Should be impossible: the post_save signal on Organization
            # seeded the system roles synchronously. If this branch fires,
            # there's a bug in `_seed_roles_for_org` — abort and rollback.
            logger.critical("PLATFORM_ORG_PROVISION_RBAC_MISSING", extra={
                "event": "PLATFORM_ORG_PROVISION_RBAC_MISSING",
                "request_id": request_id,
                "org_id": org.pk,
                "admin_user_id": admin.pk,
            })
            raise RuntimeError(
                f"RBAC role ADMIN missing for org {org.pk} after "
                f"initialize_organization signal — bug in role seeding."
            ) from exc

        # 4. Authoritative UserRole assignment with audit.
        #    `users.signals.assign_rbac_role_on_create` already ran on the
        #    User post_save and called get_or_create(user, role) WITHOUT
        #    setting `assigned_by`. update_or_create here overwrites
        #    `assigned_by` to record who provisioned this admin.
        UserRole.objects.update_or_create(
            user=admin,
            role=admin_role,
            defaults={'assigned_by': actor},
        )

    except IntegrityError as exc:
        # Validation passed but a parallel worker (or stale tx) inserted
        # the same username/email/org name in the meantime. Translate to
        # a 400 so the client can retry with a different value.
        logger.warning("PLATFORM_ORG_PROVISION_RACE", extra={
            "event": "PLATFORM_ORG_PROVISION_RACE",
            "request_id": request_id,
            "actor_id": getattr(actor, 'pk', None),
            "error_class": type(exc).__name__,
            "error": str(exc),
        })
        raise ValidationError(
            "Conflicto al crear: username, email u organización ya existen."
        )

    # 5. Post-condition. The rest of the platform assumes that a
    #    provisioned org has a usable ADMIN. Verify the invariant before
    #    returning success — if violated, rollback by raising.
    invariant_ok = UserRole.objects.filter(
        user=admin,
        role__organization=org,
        role__name='ADMIN',
        assigned_by=actor,
    ).exists()
    if not invariant_ok:
        logger.critical("PLATFORM_ORG_PROVISION_POSTCOND_FAILED", extra={
            "event": "PLATFORM_ORG_PROVISION_POSTCOND_FAILED",
            "request_id": request_id,
            "org_id": org.pk,
            "admin_user_id": admin.pk,
            "actor_id": getattr(actor, 'pk', None),
        })
        raise RuntimeError(
            "Post-condition failed: UserRole not present for "
            f"user={admin.pk}, org={org.pk}, role=ADMIN, "
            f"assigned_by={getattr(actor, 'pk', None)}."
        )

    duration_ms = int((time.monotonic() - started_at) * 1000)

    logger.info("PLATFORM_ORG_PROVISIONED", extra={
        "event": "PLATFORM_ORG_PROVISIONED",
        "request_id": request_id,
        "actor_id": getattr(actor, 'pk', None),
        "actor_username": getattr(actor, 'username', None),
        "actor_email": getattr(actor, 'email', None),
        "actor_role": getattr(actor, 'role', None),
        "org_id": org.pk,
        "org_public_id": str(org.public_id),
        "org_name": org.name,
        "admin_user_id": admin.pk,
        "admin_user_public_id": str(admin.public_id),
        "admin_username": admin.username,
        "duration_ms": duration_ms,
    })

    return ProvisionResult(
        organization=org,
        admin=admin,
        duration_ms=duration_ms,
        request_id=request_id,
    )
