"""
Credential lifecycle services for the User app.

This module hosts the authoritative service used by the
``POST /api/users/change-password/`` endpoint. No other code path may
mutate a user's password — direct writes via serializers, admin forms,
or shell scripts bypass the auditing, JWT invalidation, and validator
stack documented in ADR p20.

Only acceptable bypasses today:
  - ``createsuperuser`` (CLI bootstrap).
  - ``StaffCreateView`` (initial password on user creation).
  - ``apps.platform.services.provision_organization`` (initial admin
    password on tenant provisioning).
  - Django admin password change form (operator escape hatch).
"""
from __future__ import annotations

import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken


logger = logging.getLogger('users.events')


@dataclass
class ChangePasswordResult:
    """Return shape of ``change_password``."""
    access: str
    refresh: str
    duration_ms: int
    request_id: str


@transaction.atomic
def change_password(
    *,
    actor,
    request,
    current_password: str,
    new_password: str,
    request_id: str | None = None,
    client_ip: str = '',
    user_agent: str = '',
) -> ChangePasswordResult:
    """
    Authoritative self-service credential change.

    Order of operations (ADR p20):

      1. Verify ``current_password`` (constant-time via ``check_password``).
         If wrong, emit ``USER_PASSWORD_CHANGE_FAILED`` and raise 400.
      2. Validate ``new_password`` through Django's full validator stack —
         ``UserAttributeSimilarityValidator``, ``MinimumLengthValidator``
         (8), ``CommonPasswordValidator``, ``NumericPasswordValidator``.
         The user is passed so similarity checks compare against username /
         email / first / last name.
      3. Reject if ``new_password`` equals the current password (idempotent
         self-change is not a credential rotation).
      4. **Snapshot** the IDs of all the user's currently-issued
         ``OutstandingToken`` rows *before* anything else mutates the
         token tables. This snapshot is the set of "old" refresh tokens
         we are going to blacklist; the new token we are about to mint
         will not be present in it.
      5. ``set_password`` and persist with ``update_fields=['password']``
         to avoid touching unrelated columns.
      6. Refresh Django's session auth hash so a parallel browser session
         (Django admin, ``SessionAuthentication``) does not get logged out
         from under the user.
      7. Mint a fresh ``RefreshToken`` for the user. This also creates a
         new ``OutstandingToken`` row — which is intentionally *not*
         in the snapshot from step 4.
      8. Blacklist every OutstandingToken whose PK is in the snapshot.
         The new refresh token is preserved because its PK was not
         captured.
      9. Emit a structured ``USER_PASSWORD_CHANGED`` log line.

    Everything above happens inside a single ``transaction.atomic`` block,
    so a failure at any step rolls back password + token mutations. The
    user's existing session is left intact in that case.
    """
    request_id = request_id or str(uuid.uuid4())
    started_at = time.monotonic()

    # --- 1. Verify current password --------------------------------------
    if not actor.check_password(current_password):
        logger.warning("USER_PASSWORD_CHANGE_FAILED", extra={
            "event": "USER_PASSWORD_CHANGE_FAILED",
            "reason": "wrong_current_password",
            "request_id": request_id,
            "actor_id": actor.pk,
            "actor_username": actor.username,
            "organization_id": actor.organization_id,
            "client_ip": client_ip,
            "user_agent": user_agent,
        })
        raise ValidationError({
            "current_password": ["Contraseña actual incorrecta."],
        })

    # --- 2. Validate new password ----------------------------------------
    try:
        validate_password(new_password, user=actor)
    except DjangoValidationError as exc:
        raise ValidationError({"new_password": list(exc.messages)})

    # --- 3. Reject same-as-current ---------------------------------------
    if actor.check_password(new_password):
        raise ValidationError({
            "new_password": ["Debe ser distinta a la contraseña actual."],
        })

    # --- 4. Snapshot existing outstanding token IDs (BEFORE any mutation) -
    # We capture PKs (cheap, indexed). The new token minted in step 7 will
    # receive a PK higher than every entry in this list and therefore will
    # NOT be blacklisted in step 8.
    old_outstanding_ids = list(
        OutstandingToken.objects
        .filter(user=actor)
        .values_list('pk', flat=True)
    )

    # --- 5. Persist new password -----------------------------------------
    # Also clear the temp-credential lifecycle fields (ADR p21). If the
    # user is here because of an admin reset, this is the moment when
    # `password_must_change` is lifted and the gate stops blocking them.
    actor.set_password(new_password)
    actor.password_must_change = False
    actor.password_temp_issued_at = None
    actor.save(update_fields=[
        'password',
        'password_must_change',
        'password_temp_issued_at',
    ])

    # --- 6. Keep parallel Django sessions alive --------------------------
    # No-op for pure-JWT clients, but matters when the user is also
    # logged into Django admin (SessionAuthentication coexists in
    # DEFAULT_AUTHENTICATION_CLASSES).
    update_session_auth_hash(request, actor)

    # --- 7. Mint new refresh + access pair -------------------------------
    new_refresh = RefreshToken.for_user(actor)
    new_access = str(new_refresh.access_token)

    # --- 8. Blacklist the snapshotted tokens -----------------------------
    # ``get_or_create`` is idempotent — safe if the row was already
    # blacklisted by a prior partial run or by ``BLACKLIST_AFTER_ROTATION``
    # firing during a refresh in flight.
    if old_outstanding_ids:
        old_tokens = OutstandingToken.objects.filter(pk__in=old_outstanding_ids)
        for ot in old_tokens:
            BlacklistedToken.objects.get_or_create(token=ot)

    # --- 9. Emit success log ---------------------------------------------
    duration_ms = int((time.monotonic() - started_at) * 1000)
    logger.info("USER_PASSWORD_CHANGED", extra={
        "event": "USER_PASSWORD_CHANGED",
        "request_id": request_id,
        "actor_id": actor.pk,
        "actor_username": actor.username,
        "actor_email": actor.email,
        "organization_id": actor.organization_id,
        "client_ip": client_ip,
        "user_agent": user_agent,
        "blacklisted_refresh_count": len(old_outstanding_ids),
        "duration_ms": duration_ms,
    })

    return ChangePasswordResult(
        access=new_access,
        refresh=str(new_refresh),
        duration_ms=duration_ms,
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# Admin reset (ADR p21)
# ---------------------------------------------------------------------------

# Temp passwords issued by the admin reset flow are valid for this long
# from issuance. After this window, the login view rejects them and the
# admin must issue a new reset.
TEMP_PASSWORD_VALIDITY = timedelta(hours=24)

# Length in *bytes* passed to ``secrets.token_urlsafe``. The resulting
# string is base64-urlsafe encoded, so the visible length is ~4/3 times
# this value (16 bytes → 22 chars). 16 bytes of entropy is the standard
# floor for password reset tokens (NIST SP 800-63B §5.1.1.2).
TEMP_PASSWORD_ENTROPY_BYTES = 16


@dataclass
class ResetPasswordResult:
    """Return shape of ``reset_password_for_staff``."""
    temp_password: str
    expires_in_seconds: int
    duration_ms: int
    request_id: str


@transaction.atomic
def reset_password_for_staff(
    *,
    admin,
    target_user,
    request_id: str | None = None,
    client_ip: str = '',
    user_agent: str = '',
) -> ResetPasswordResult:
    """
    Issue a temporary password on behalf of a staff member (ADR p21).

    Authorisation contract (defence in depth — the view also enforces):
      - ``admin.role == 'ADMIN'`` — VET/ASSISTANT cannot reset others.
      - ``target_user.organization == admin.organization`` — strict
        same-tenant rule. Cross-tenant resets cannot happen even by
        accident.
      - ``target_user != admin`` — admins use the self-service
        ``change_password`` flow for their own credentials.
      - ``target_user.role != 'ADMIN_SAAS'`` — clinic admins cannot
        affect platform operators.

    Side effects inside a single atomic block:
      1. Generate cryptographically random temp password.
      2. ``set_password`` on the target.
      3. Set ``password_must_change=True`` and stamp
         ``password_temp_issued_at=now()``.
      4. Blacklist EVERY ``OutstandingToken`` of the target — any
         existing session is immediately revoked.
      5. Emit a structured ``ADMIN_PASSWORD_RESET_ISSUED`` audit log.
      6. Return the temp password ONCE.

    The temp password is returned in plain to the caller (the admin)
    exactly once. It is NEVER written to logs.
    """
    request_id = request_id or str(uuid.uuid4())
    started_at = time.monotonic()

    # --- Authorisation gates -------------------------------------------------
    if getattr(admin, 'role', None) != 'ADMIN':
        raise PermissionDenied(
            "Solo administradores de la clínica pueden resetear contraseñas."
        )
    if target_user.pk == admin.pk:
        raise PermissionDenied(
            "Usa el cambio de contraseña personal para tu propia cuenta."
        )
    if getattr(target_user, 'role', None) == 'ADMIN_SAAS':
        raise PermissionDenied(
            "No puedes resetear la contraseña de operadores de plataforma."
        )
    if getattr(target_user, 'is_service_account', False):
        # ADR p51 — 404-as-403: un reset pondría password_must_change=True y
        # el gate embebido en HybridPermission inutilizaría al agente virtual.
        from django.http import Http404
        raise Http404("Usuario no encontrado.")
    if (
        target_user.organization_id is None
        or admin.organization_id is None
        or target_user.organization_id != admin.organization_id
    ):
        # Use the standard 404-as-403 convention — never confirm that
        # the target exists in another tenant.
        from django.http import Http404
        raise Http404("Usuario no encontrado.")

    # --- 1. Generate temp password ------------------------------------------
    temp_password = secrets.token_urlsafe(TEMP_PASSWORD_ENTROPY_BYTES)

    # --- 2-3. Persist credential change + lifecycle flags -------------------
    target_user.set_password(temp_password)
    target_user.password_must_change = True
    target_user.password_temp_issued_at = timezone.now()
    target_user.save(update_fields=[
        'password',
        'password_must_change',
        'password_temp_issued_at',
    ])

    # --- 4. Revoke every existing session of the target ---------------------
    # Unlike ``change_password`` (which preserves the caller's session),
    # an admin reset has no current session of the target to spare — the
    # target was not in the loop. Blacklist everything.
    old_outstanding = OutstandingToken.objects.filter(user=target_user)
    revoked_count = 0
    for ot in old_outstanding:
        _, created = BlacklistedToken.objects.get_or_create(token=ot)
        if created:
            revoked_count += 1

    # --- 5. Audit log -------------------------------------------------------
    duration_ms = int((time.monotonic() - started_at) * 1000)
    logger.info("ADMIN_PASSWORD_RESET_ISSUED", extra={
        "event": "ADMIN_PASSWORD_RESET_ISSUED",
        "request_id": request_id,
        "actor_id": admin.pk,
        "actor_username": admin.username,
        "actor_role": admin.role,
        "organization_id": admin.organization_id,
        "target_user_id": target_user.pk,
        "target_username": target_user.username,
        "target_public_id": str(target_user.public_id),
        "target_role": target_user.role,
        "revoked_refresh_count": revoked_count,
        "client_ip": client_ip,
        "user_agent": user_agent,
        "duration_ms": duration_ms,
        # Note — temp_password is NEVER logged.
    })

    return ResetPasswordResult(
        temp_password=temp_password,
        expires_in_seconds=int(TEMP_PASSWORD_VALIDITY.total_seconds()),
        duration_ms=duration_ms,
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# Staff deactivation (H-06)
# ---------------------------------------------------------------------------


@dataclass
class DeactivateStaffResult:
    """Return shape of ``deactivate_staff``."""
    revoked_refresh_count: int
    duration_ms: int
    request_id: str


@transaction.atomic
def deactivate_staff(
    *,
    admin,
    target_user,
    request_id: str | None = None,
    client_ip: str = '',
    user_agent: str = '',
) -> DeactivateStaffResult:
    """
    Deactivate a staff member AND revoke every session they hold (H-06).

    Before this service, ``StaffDeactivateView`` only flipped
    ``is_active=False``. Access tokens were already rejected by simplejwt
    (``CHECK_USER_IS_ACTIVE=True``), but the refresh token was never
    blacklisted: the target could keep hitting ``POST /api/token/refresh/``
    for up to ``REFRESH_TOKEN_LIFETIME`` (7 days) — minting tokens that,
    while useless against protected endpoints, kept the credential alive.
    A fired employee's refresh token must die the moment access is cut.

    Authorisation contract (defence in depth — the view also scopes the
    queryset to the caller's org + ``is_active=True`` before resolving the
    target):
      - ``target_user != admin`` — self-deactivation is a lockout; admins
        cannot remove their own only path back in. Raises ``ValidationError``
        (→ 400), preserving the prior endpoint contract.
      - ``target_user.role != 'ADMIN_SAAS'`` — clinic staff cannot touch
        platform operators (404-as-403, never confirm existence).
      - ``target_user.organization == admin.organization`` — strict
        same-tenant rule.

    Side effects inside a single atomic block:
      1. ``is_active=False`` (persisted with ``update_fields``).
      2. Blacklist EVERY ``OutstandingToken`` of the target — identical
         pattern to ``reset_password_for_staff`` step 4. The refresh
         endpoint will reject the revoked token on the next attempt.
      3. Emit a structured ``STAFF_DEACTIVATED`` audit log.
    """
    request_id = request_id or str(uuid.uuid4())
    started_at = time.monotonic()

    # --- Authorisation gates -------------------------------------------------
    if target_user.pk == admin.pk:
        raise ValidationError("No puedes desactivar tu propia cuenta.")
    if getattr(target_user, 'role', None) == 'ADMIN_SAAS':
        from django.http import Http404
        raise Http404("Usuario no encontrado.")
    if getattr(target_user, 'is_service_account', False):
        # ADR p51 — 404-as-403: el kill switch del agente virtual es
        # AgentSettings.enabled (É-F0) / ensure_agent_users, no esta API.
        from django.http import Http404
        raise Http404("Usuario no encontrado.")
    if (
        target_user.organization_id is None
        or admin.organization_id is None
        or target_user.organization_id != admin.organization_id
    ):
        from django.http import Http404
        raise Http404("Usuario no encontrado.")

    # --- 1. Deactivate -------------------------------------------------------
    target_user.is_active = False
    target_user.save(update_fields=['is_active'])

    # --- 2. Revoke every existing session ------------------------------------
    # Same blacklist-everything pattern as the admin password reset: the
    # deactivated user has no session worth sparing.
    old_outstanding = OutstandingToken.objects.filter(user=target_user)
    revoked_count = 0
    for ot in old_outstanding:
        _, created = BlacklistedToken.objects.get_or_create(token=ot)
        if created:
            revoked_count += 1

    # --- 3. Audit log --------------------------------------------------------
    duration_ms = int((time.monotonic() - started_at) * 1000)
    logger.info("STAFF_DEACTIVATED", extra={
        "event": "STAFF_DEACTIVATED",
        "request_id": request_id,
        "actor_id": admin.pk,
        "actor_username": admin.username,
        "actor_role": admin.role,
        "organization_id": admin.organization_id,
        "target_user_id": target_user.pk,
        "target_username": target_user.username,
        "target_public_id": str(target_user.public_id),
        "target_role": target_user.role,
        "revoked_refresh_count": revoked_count,
        "client_ip": client_ip,
        "user_agent": user_agent,
        "duration_ms": duration_ms,
    })

    return DeactivateStaffResult(
        revoked_refresh_count=revoked_count,
        duration_ms=duration_ms,
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# Service account del agente virtual (ADR p51)
# ---------------------------------------------------------------------------

AGENT_USERNAME_TEMPLATE = 'agent.whatsapp.{org_public_id}'


def update_staff_profile(*, admin, target_user, changes):
    """Edita especialidad y cédula de un miembro de Equipo (M01, orden 7).

    La view ya limita el target a la organización del ADMIN; aquí se repite como
    defensa en profundidad (404-as-403). El log lleva nombres de campo, no valores.
    """
    if (
        target_user.organization_id is None
        or target_user.organization_id != admin.organization_id
        or getattr(target_user, 'role', None) == 'ADMIN_SAAS'
        or getattr(target_user, 'is_service_account', False)
    ):
        from django.http import Http404
        raise Http404("Usuario no encontrado.")
    fields = sorted(changes)
    for field in fields:
        setattr(target_user, field, changes[field])
    target_user.save(update_fields=fields)
    logger.info(
        "STAFF_PROFILE_UPDATED",
        extra={
            'event': 'STAFF_PROFILE_UPDATED',
            'actor_id': admin.pk,
            'target_user_id': target_user.pk,
            'organization_id': admin.organization_id,
            'fields': fields,
        },
    )
    return target_user


def ensure_agent_user(organization):
    """
    Garantiza el user AGENT (service account) de una organización (ADR p51).

    Idempotente y auto-reparador — protege contra borrados/desactivaciones
    por shell: crea la cuenta si no existe, la reactiva si está inactiva y
    fuerza password inutilizable si alguien le puso una. Devuelve
    ``(user, status)`` con status ∈ {'created', 'repaired', 'ok'}.

    Reglas de la cuenta (ADR p51):
      - ``set_unusable_password()`` — jamás login interactivo; los tokens se
        acuñan server-side (Tool Executor, É-F1).
      - ``email=''`` — el constraint parcial de unicidad global (ADR p48)
        excluye email vacío para cuentas técnicas.
      - ``password_must_change`` siempre False (el gate bloquearía sus tools;
        la API de staff no puede resetearla — guard 404 arriba).
      - UserRole: lo asigna el signal ``assign_rbac_role_on_create`` al
        crear; aquí se re-garantiza por si el Role AGENT se sembró después
        (deploy con seed_permissions posterior a la creación del user).
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()

    user = (
        User.objects
        .filter(organization=organization, role='AGENT', is_service_account=True)
        .order_by('pk')
        .first()
    )
    status_ = 'ok'

    if user is None:
        user = User(
            username=AGENT_USERNAME_TEMPLATE.format(
                org_public_id=organization.public_id
            ),
            email='',
            organization=organization,
            role='AGENT',
            is_service_account=True,
            first_name='Asistente',
            last_name='Virtual',
        )
        user.set_unusable_password()
        user.save()
        status_ = 'created'
        logger.info("AGENT_USER_CREATED", extra={
            "event": "AGENT_USER_CREATED",
            "organization_id": organization.pk,
            "user_id": user.pk,
            "username": user.username,
        })
    else:
        repaired_fields = []
        if not user.is_active:
            user.is_active = True
            repaired_fields.append('is_active')
        if user.has_usable_password():
            user.set_unusable_password()
            repaired_fields.append('password')
        if user.password_must_change:
            user.password_must_change = False
            repaired_fields.append('password_must_change')
        if repaired_fields:
            user.save(update_fields=repaired_fields)
            status_ = 'repaired'
            logger.warning("AGENT_USER_REPAIRED", extra={
                "event": "AGENT_USER_REPAIRED",
                "organization_id": organization.pk,
                "user_id": user.pk,
                "repaired_fields": repaired_fields,
            })

    # Re-garantizar el UserRole (idempotente; cubre el orden inverso
    # user-antes-que-seed). Si el Role no existe aún, WARNING igual que el
    # signal — la señal de que falta correr seed_permissions.
    from apps.core.models import Role, UserRole
    try:
        role = Role.objects.get(
            name='AGENT', organization=organization, is_system_role=True
        )
        UserRole.objects.get_or_create(user=user, role=role)
    except Role.DoesNotExist:
        logger.warning(
            "ensure_agent_user: rol 'AGENT' no encontrado en org %s — "
            "ejecuta seed_permissions primero",
            organization.pk,
        )

    return user, status_


def is_temp_password_expired(user) -> bool:
    """
    Return True if ``user`` is currently in the ``must_change`` state and
    the temp password issued by an admin reset has aged past
    ``TEMP_PASSWORD_VALIDITY``.

    Used by the login view to reject expired temps. NOT used by the
    ``MustChangePasswordGate`` permission — the gate lets you in to
    change the password regardless of how stale the temp is, otherwise
    a user could be permanently locked out.
    """
    if not user.password_must_change:
        return False
    if user.password_temp_issued_at is None:
        return False
    return (timezone.now() - user.password_temp_issued_at) > TEMP_PASSWORD_VALIDITY
