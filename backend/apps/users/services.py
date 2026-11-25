"""
Credential lifecycle services for the User app.

This module hosts the authoritative service used by the
``POST /api/users/change-password/`` endpoint. No other code path may
mutate a user's password — direct writes via serializers, admin forms,
or shell scripts bypass the auditing, JWT invalidation, and validator
stack documented in ADR p20.

Only acceptable bypasses today:
  - ``createsuperuser`` (CLI bootstrap).
  - ``create_staff_member`` (initial password generated on staff creation).
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
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken

from apps.users.professional import attends_for, license_required_message


logger = logging.getLogger('users.events')


def bump_session_version(user) -> int:
    """Invalida todos los tokens emitidos hasta ahora para ``user`` (ADR p65).

    Única escritura legítima de ``User.session_version``: un ``UPDATE`` con
    ``F()``, atómico en la base, dentro de la transacción del llamador. Si esa
    transacción se revierte, el incremento también. Después relee el valor en la
    instancia y lo devuelve.

    Rechaza las cuentas de servicio: sus tokens no llevan versión y ninguna vía
    debe incrementarla (todos los llamadores las excluyen antes). Llegar aquí con
    una es un error de programación.
    """
    if getattr(user, 'is_service_account', False):
        raise ValueError(
            'bump_session_version no aplica a cuentas de servicio (ADR p65).'
        )
    from django.contrib.auth import get_user_model
    from django.db.models import F
    User = get_user_model()

    # Filtra por la PK de un usuario que el llamador ya resolvió dentro de su
    # organización (o, en plataforma, por operador verificado).
    User.objects.filter(pk=user.pk).update(
        session_version=F('session_version') + 1,
    )
    user.refresh_from_db(fields=['session_version'])
    return user.session_version


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

    # --- 7. Invalidate every token issued so far, then mint the new pair --
    # ADR p65: other sessions (and the access token of this very request) stop
    # working at once; the new pair carries the new version.
    from apps.core.authentication import stamp_session_version

    bump_session_version(actor)
    new_refresh = stamp_session_version(RefreshToken.for_user(actor), actor)
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


# ---------------------------------------------------------------------------
# Shared building blocks of the staff credential/lifecycle services
# ---------------------------------------------------------------------------

class ActorInactive(PermissionDenied):
    """403: the acting ADMIN was deactivated while the operation waited for its
    locks (plan Equipo F1)."""
    default_detail = 'Tu cuenta ya no está activa.'
    default_code = 'actor_inactive'


class LastActiveAdmin(APIException):
    """409: the operation would leave the clinic without an active ADMIN."""
    status_code = 409
    default_detail = (
        'No puedes desactivar al último administrador activo de la clínica.'
    )
    default_code = 'last_active_admin'


class DemoSeedAccount(PermissionDenied):
    """403: shared demo seed accounts are not managed through Equipo (D5)."""
    default_detail = 'Las cuentas de demostración no se pueden modificar.'
    default_code = 'demo_seed_account'


class OpenCashSession(APIException):
    """409: the member has an open cash session (ADR p66, PO decision).

    Deactivating would leave a turn nobody can close from their side. Caja
    already offers the administrative close.
    """
    status_code = 409
    default_detail = (
        'Tiene una caja abierta. Ciérrala desde Caja antes de desactivar su acceso.'
    )
    default_code = 'open_cash_session'


def record_staff_event(*, member, actor, kind, changes=None, request_id=''):
    """Append a ``StaffAccessEvent`` inside the caller's transaction (ADR p66).

    ``changes`` carries field names and roles only — never passwords, emails or
    other personal values. A rolled-back operation leaves no event.
    """
    from apps.users.models import StaffAccessEvent

    return StaffAccessEvent.objects.create(
        organization_id=member.organization_id,
        member=member,
        actor=actor,
        kind=kind,
        changes=changes or {},
        request_id=(request_id or '')[:64],
    )


def is_demo_seed_account(user) -> bool:
    """True for the three shared seed accounts of the demo organization (D5).

    Identified by BOTH the demo organization and the seed username — the same
    key `seed_demo_clinic._ensure_users` uses. Usernames are immutable through
    the API and the seed ones contain '@', which `USERNAME_REGEX` rejects, so no
    visitor can create a look-alike. `UserSerializer.demo_protected` only mirrors
    this for the UI; the services enforce it.
    """
    from apps.core.demo_reset import DEMO_SEED_USERNAMES

    organization = getattr(user, 'organization', None)
    return bool(
        organization is not None
        and organization.is_demo
        and user.username in DEMO_SEED_USERNAMES
    )


def _assert_not_demo_seed_account(target_user):
    if is_demo_seed_account(target_user):
        raise DemoSeedAccount()


def _assert_manageable_target(admin, target_user):
    """The 404-as-403 gates every staff operation shares.

    Platform operators, service accounts (ADR p51) and users of another clinic
    are never confirmed to exist. Each operation keeps its own extra rules
    (acting on oneself, the reset's 403 for ``ADMIN_SAAS``) before calling this.
    """
    from django.http import Http404

    if (
        getattr(target_user, 'role', None) == 'ADMIN_SAAS'
        or getattr(target_user, 'is_service_account', False)
        or target_user.organization_id is None
        or admin.organization_id is None
        or target_user.organization_id != admin.organization_id
    ):
        raise Http404("Usuario no encontrado.")


def _revoke_all_sessions(user) -> int:
    """Revoke every session of ``user``: blacklist all its refresh tokens and
    bump its session version, so access tokens die too (ADR p65).

    Returns how many refresh tokens were newly blacklisted.
    """
    revoked = 0
    for ot in OutstandingToken.objects.filter(user=user):
        _, created = BlacklistedToken.objects.get_or_create(token=ot)
        if created:
            revoked += 1
    bump_session_version(user)
    return revoked


def _generate_password() -> str:
    """Random password for credentials the system hands out (ADR p21).

    ``TEMP_PASSWORD_ENTROPY_BYTES`` of entropy, base64-urlsafe. Shared by the
    reset/reactivation temporary password and the initial password of a new
    member, so every credential the system issues has the same strength.
    """
    return secrets.token_urlsafe(TEMP_PASSWORD_ENTROPY_BYTES)


def _issue_temporary_password(user) -> tuple[str, int]:
    """Replace the password with a temporary one (ADR p21) and revoke every
    session. Returns ``(temp_password, revoked_refresh_count)``.

    The temporary password is valid for ``TEMP_PASSWORD_VALIDITY`` and must be
    changed on first login. It is never logged.
    """
    temp_password = _generate_password()
    user.set_password(temp_password)
    user.password_must_change = True
    user.password_temp_issued_at = timezone.now()
    user.save(update_fields=[
        'password',
        'password_must_change',
        'password_temp_issued_at',
    ])
    return temp_password, _revoke_all_sessions(user)


def _lock_users(*, pks, active_admins_of=None):
    """Lock ``User`` rows in ONE query ordered by pk and return them by pk.

    PostgreSQL applies the lock after ordering, so two transactions always
    lock in the same order and cannot deadlock each other. With
    ``active_admins_of`` it also locks every active (human) ADMIN of that
    organization: the last-ADMIN rule reads that set under the lock.
    """
    from django.contrib.auth import get_user_model
    from django.db.models import Q
    User = get_user_model()

    condition = Q(pk__in=list(pks))
    if active_admins_of is not None:
        condition |= Q(
            organization_id=active_admins_of,
            role='ADMIN',
            is_active=True,
            is_service_account=False,
        )
    rows = User.objects.select_for_update().filter(condition).order_by('pk')
    return {row.pk: row for row in rows}


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
    # ADR p51 — 404-as-403 for service accounts (a reset would set
    # password_must_change=True and lock the agent out) and for other clinics.
    _assert_manageable_target(admin, target_user)
    _assert_not_demo_seed_account(target_user)

    # --- 1-4. Temp password + lifecycle flags + revoke every session --------
    # Unlike ``change_password`` (which preserves the caller's session),
    # an admin reset has no current session of the target to spare — the
    # target was not in the loop. Refresh AND access tokens die (ADR p65).
    temp_password, revoked_count = _issue_temporary_password(target_user)
    # ADR p68 (PO): el restablecimiento también quita la verificación en dos
    # pasos; es la salida para quien perdió el celular y sus códigos.
    from apps.users.mfa import remove_for_reset
    mfa_removed = remove_for_reset(target_user)
    record_staff_event(
        member=target_user, actor=admin, kind='password_reset', request_id=request_id,
        changes={'mfa_removed': True} if mfa_removed else None,
    )

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
    # ADR p51 — 404-as-403: platform operators, other clinics and service
    # accounts (the agent's kill switch is AgentSettings.enabled /
    # ensure_agent_users, not this API).
    _assert_manageable_target(admin, target_user)
    _assert_not_demo_seed_account(target_user)

    # --- Lock + re-check (last-ADMIN invariant) -----------------------------
    # One query ordered by pk: actor + target and, when the target is an
    # ADMIN, every active ADMIN of the clinic. Under READ COMMITTED,
    # PostgreSQL re-evaluates rows another transaction just committed, so two
    # ADMINs deactivating each other serialize and the second one finds its
    # own actor inactive.
    from django.http import Http404

    locked = _lock_users(
        pks=[admin.pk, target_user.pk],
        active_admins_of=(
            target_user.organization_id if target_user.role == 'ADMIN' else None
        ),
    )
    actor = locked.get(admin.pk)
    target = locked.get(target_user.pk)
    if actor is None or not actor.is_active:
        raise ActorInactive()
    if target is None or not target.is_active:
        raise Http404("Usuario no encontrado.")
    if target.role == 'ADMIN':
        others = [
            row for row in locked.values()
            if row.pk != target.pk
            and row.role == 'ADMIN'
            and row.is_active
            and not row.is_service_account
            and row.organization_id == target.organization_id
        ]
        if not others:
            raise LastActiveAdmin()
    # ADR p66 (PO): an open cash session blocks the deactivation. Upcoming
    # appointments and open records only warn (GET .../impact/).
    from apps.cash.services import get_open_session
    if get_open_session(target) is not None:
        raise OpenCashSession()

    # --- 1. Deactivate -------------------------------------------------------
    target.is_active = False
    target.save(update_fields=['is_active'])
    target_user.is_active = False

    # --- 2. Revoke every existing session (refresh + access, ADR p65) -------
    revoked_count = _revoke_all_sessions(target)
    record_staff_event(
        member=target, actor=admin, kind='deactivated', request_id=request_id,
    )

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
# Staff reactivation (plan Equipo, A2)
# ---------------------------------------------------------------------------


class AlreadyActive(APIException):
    """409: the member is already active (e.g. a retry after a lost response)."""
    status_code = 409
    default_detail = (
        'Ya está activo. Si no recibiste la contraseña temporal, usa '
        'Restablecer contraseña.'
    )
    default_code = 'already_active'


@dataclass
class ReactivateStaffResult:
    """Return shape of ``reactivate_staff``."""
    user: object
    temp_password: str
    expires_in_seconds: int
    duration_ms: int
    request_id: str


def _log_staff_reactivated(fields):
    logger.info("STAFF_REACTIVATED", extra=fields)


@transaction.atomic(durable=True)
def reactivate_staff(
    *,
    admin,
    target_user,
    request_id: str | None = None,
    client_ip: str = '',
    user_agent: str = '',
) -> ReactivateStaffResult:
    """Reactivate a deactivated member with a temporary password (A2).

    Same account — same PK, ``public_id``, role, cédula, ``UserRole`` and every
    relation (deactivation never removed them). The old password stops working
    and every session issued before is revoked (refresh tokens blacklisted and
    session version bumped, ADR p65).

    **Must be the outermost transaction** (``durable=True``): called inside
    another atomic block it raises ``RuntimeError`` before writing anything.
    Otherwise the commit would happen later, after the temporary password was
    already handed back. Only ``StaffReactivateView`` calls it; any future
    caller (bulk reactivation, command, admin action) must call it outside of a
    transaction.

    The temporary password is returned once, only after the commit, and never
    logged. ``STAFF_REACTIVATED`` is emitted with ``on_commit(robust=True)``:
    no event for a rolled-back reactivation, and a failing notification never
    turns a committed reactivation into an HTTP error.
    """
    request_id = request_id or str(uuid.uuid4())
    started_at = time.monotonic()

    _assert_manageable_target(admin, target_user)

    locked = _lock_users(pks=[admin.pk, target_user.pk])
    actor = locked.get(admin.pk)
    target = locked.get(target_user.pk)
    if actor is None or not actor.is_active:
        raise ActorInactive()
    if actor.role != 'ADMIN':
        raise PermissionDenied(
            "Solo administradores de la clínica pueden reactivar personal."
        )
    if actor.organization_id and not actor.organization.is_active:
        raise PermissionDenied("Organización desactivada.")
    if target is None:
        from django.http import Http404
        raise Http404("Usuario no encontrado.")
    if target.is_active:
        raise AlreadyActive()

    target.is_active = True
    target.save(update_fields=['is_active'])
    temp_password, revoked_count = _issue_temporary_password(target)
    from apps.users.mfa import remove_for_reset
    mfa_removed = remove_for_reset(target)
    record_staff_event(
        member=target, actor=admin, kind='reactivated', request_id=request_id,
        changes={'mfa_removed': True} if mfa_removed else None,
    )

    duration_ms = int((time.monotonic() - started_at) * 1000)
    event = {
        "event": "STAFF_REACTIVATED",
        "request_id": request_id,
        "actor_id": admin.pk,
        "actor_username": admin.username,
        "actor_role": admin.role,
        "organization_id": admin.organization_id,
        "target_user_id": target.pk,
        "target_username": target.username,
        "target_public_id": str(target.public_id),
        "target_role": target.role,
        "revoked_refresh_count": revoked_count,
        "client_ip": client_ip,
        "user_agent": user_agent,
        "duration_ms": duration_ms,
        # Note — temp_password is NEVER logged.
    }
    transaction.on_commit(lambda: _log_staff_reactivated(event), robust=True)

    return ReactivateStaffResult(
        user=target,
        temp_password=temp_password,
        expires_in_seconds=int(TEMP_PASSWORD_VALIDITY.total_seconds()),
        duration_ms=duration_ms,
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# Role change and clinical function (ADR p66)
# ---------------------------------------------------------------------------

ROLE_LABELS = {'ADMIN': 'Administrador', 'VET': 'Veterinario', 'ASSISTANT': 'Asistente'}


class SelfRoleChange(ValidationError):
    """400: an ADMIN cannot change their own role (lockout / self-escalation)."""
    default_detail = 'No puedes cambiar tu propio rol.'


def _swap_system_role(user):
    """Replace the system ``UserRole`` of ``user`` by the one of its current role.

    Only system roles of the clinic roles are touched; any custom role assigned
    in the database stays as it is.
    """
    from apps.core.models import UserRole

    UserRole.objects.filter(
        user=user,
        role__organization_id=user.organization_id,
        role__is_system_role=True,
        role__name__in=STAFF_ROLES,
    ).exclude(role__name=user.role).delete()
    _assign_system_role(user)


@transaction.atomic
def change_staff_role(*, admin, target_user, role, attends_patients=None,
                      request_id: str | None = None):
    """Change the role (and clinical function) of a clinic member (ADR p66).

    Rules:
      - Not on oneself (400) — no lockout, no self-escalation.
      - Same 404-as-403 scope as the other staff operations; demo seed accounts
        are protected (403); the target must be active.
      - INV-J: if the target stops being ADMIN, every active ADMIN of the clinic
        is locked (one query ordered by pk) and at least another one must remain
        (409 ``last_active_admin``). Two ADMINs demoting each other serialize and
        the second finds its actor inactive or not ADMIN.
      - The clinical function follows the role: VET always attends, ASSISTANT
        never; ADMIN keeps ``attends_patients`` (default: whether the member
        attended before the change). Whoever attends needs a cédula (400).
      - ``User.role`` and the system ``UserRole`` change in this transaction.
      - Same role and same function: no write, no event (idempotent).
      - Sessions are NOT revoked (PO decision): permissions are read from the
        database on every request, so the change applies on the next one.
    """
    from django.http import Http404

    request_id = request_id or str(uuid.uuid4())
    if role not in STAFF_ROLES:
        raise ValidationError({'role': ['Rol no válido.']})
    if target_user.pk == admin.pk:
        raise SelfRoleChange()
    _assert_manageable_target(admin, target_user)
    _assert_not_demo_seed_account(target_user)

    demoting_admin = target_user.role == 'ADMIN' and role != 'ADMIN'
    locked = _lock_users(
        pks=[admin.pk, target_user.pk],
        active_admins_of=target_user.organization_id if demoting_admin else None,
    )
    actor = locked.get(admin.pk)
    target = locked.get(target_user.pk)
    if actor is None or not actor.is_active:
        raise ActorInactive()
    # Another ADMIN may have changed the actor's own role while we waited.
    from apps.core.permissions import user_has_permission
    if not user_has_permission(actor, 'staff.change_role'):
        raise PermissionDenied('Ya no tienes permiso para cambiar roles.')
    if target is None or not target.is_active:
        raise Http404("Usuario no encontrado.")
    # Re-check with the row locked: the role may have changed meanwhile.
    if target.role == 'ADMIN' and role != 'ADMIN':
        others = [
            row for row in locked.values()
            if row.pk != target.pk and row.role == 'ADMIN' and row.is_active
            and not row.is_service_account and row.organization_id == target.organization_id
        ]
        if not others:
            raise LastActiveAdmin(
                detail='No puedes quitar el rol de administrador al último '
                       'administrador activo de la clínica.',
            )

    if role != 'ADMIN' and attends_patients is not None and bool(attends_patients) != attends_for(role):
        raise ValidationError({'attends_patients': [
            'Solo se ajusta en administradores: en veterinarios y asistentes lo define el rol.']})
    previous_attends = attends_for(target.role, target.attends_patients)
    wanted = previous_attends if attends_patients is None else attends_patients
    new_attends = attends_for(role, wanted)
    if new_attends and not target.license_number:
        raise ValidationError({'license_number': [license_required_message(role)]})

    old_role = target.role
    if old_role == role and target.attends_patients == new_attends:
        return target

    target.role = role
    target.attends_patients = new_attends
    target.save(update_fields=['role', 'attends_patients'])
    if old_role != role:
        _swap_system_role(target)

    changes = {'role': {'from': old_role, 'to': role}}
    if previous_attends != new_attends:
        changes['attends_patients'] = {'from': previous_attends, 'to': new_attends}
    record_staff_event(
        member=target, actor=admin, kind='role_changed', changes=changes,
        request_id=request_id,
    )
    log = {
        "event": "STAFF_ROLE_CHANGED",
        "request_id": request_id,
        "actor_id": admin.pk,
        "organization_id": admin.organization_id,
        "target_user_id": target.pk,
        "target_public_id": str(target.public_id),
        "from_role": old_role,
        "to_role": role,
        "attends_patients": new_attends,
    }
    transaction.on_commit(lambda: logger.info("STAFF_ROLE_CHANGED", extra=log), robust=True)
    return target


def staff_impact(member):
    """What a member has pending, for the warning before deactivating them or
    removing their clinical function (ADR p66). Read-only; each count comes from
    its own domain."""
    from apps.appointments.services import count_upcoming_for_veterinarian
    from apps.cash.services import get_open_session
    from apps.medical_records.services import count_open_for_veterinarian

    organization = member.organization
    return {
        'upcoming_appointments': count_upcoming_for_veterinarian(organization, member),
        'open_medical_records': count_open_for_veterinarian(organization, member),
        'open_cash_session': get_open_session(member) is not None,
    }


# ---------------------------------------------------------------------------
# Staff creation (Fase 1 Equipo): the system generates the initial password
# ---------------------------------------------------------------------------

STAFF_ROLES = ('ADMIN', 'VET', 'ASSISTANT')
EMAIL_UNAVAILABLE = 'Este correo no está disponible.'
USERNAME_UNAVAILABLE = 'Este nombre de usuario no está disponible.'


@dataclass
class CreateStaffResult:
    """Return shape of ``create_staff_member``."""
    user: object
    temp_password: str
    request_id: str


def _assign_system_role(user):
    """Link ``user`` to the system ``Role`` of its role name (RBAC).

    The ``post_save`` signal ``assign_rbac_role_on_create`` does the same on
    creation; both use ``get_or_create``, so running twice is harmless. Without
    the role seeded, it warns: ``seed_permissions`` has not run for the clinic.
    """
    from apps.core.models import Role, UserRole

    try:
        role = Role.objects.get(
            name=user.role, organization_id=user.organization_id, is_system_role=True,
        )
    except Role.DoesNotExist:
        logger.warning(
            "Rol '%s' no encontrado en org %s al crear usuario %s — "
            "ejecuta seed_permissions",
            user.role, user.organization_id, user.pk,
        )
        return
    UserRole.objects.get_or_create(user=user, role=role)


def _log_staff_created(fields):
    logger.info("STAFF_CREATED", extra=fields)


@transaction.atomic(durable=True)
def create_staff_member(*, admin, data, request_id: str | None = None) -> CreateStaffResult:
    """Create a member of the admin's clinic with a system-generated password.

    ``data`` is the validated input of ``CreateEmployeeSerializer`` (username,
    email, names, role, specialty, cédula). The organization always comes from
    ``admin``, never from the request body (ADR p18).

    The initial password follows ADR p21 (addendum 2026-06-24, amended
    2026-11-23): generated like the reset's temporary password, must be changed on
    first login (``password_must_change=True``) and, without
    ``password_temp_issued_at``, it does not expire. It is returned once, after
    the commit, and never logged.

    **Must be the outermost transaction** (``durable=True``), like
    ``reactivate_staff``: otherwise the password could be handed back before a
    commit that later fails. Creation and role assignment are one unit: a
    failure leaves no half-created member.

    A concurrent creation with the same email or username loses on the database
    constraint and gets a 400 on that field, never a 500.
    """
    from django.contrib.auth import get_user_model
    from django.db import IntegrityError

    User = get_user_model()
    request_id = request_id or str(uuid.uuid4())

    if admin.organization_id is None:
        raise PermissionDenied("Tu cuenta no pertenece a una clínica.")
    role = data.get('role')
    if role not in STAFF_ROLES:
        raise ValidationError({'role': ['Rol no válido.']})

    temp_password = _generate_password()
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=data['username'],
                email=data['email'],
                password=temp_password,
                first_name=data.get('first_name', ''),
                last_name=data.get('last_name', ''),
                specialties=data.get('specialties', []),
                license_number=data.get('license_number', ''),
                role=role,
                # ADR p66: VET siempre, ASSISTANT nunca, ADMIN según el alta.
                attends_patients=attends_for(role, data.get('attends_patients', False)),
                organization_id=admin.organization_id,
                # Contraseña de un solo uso (ADR p21): el gate obliga a cambiarla
                # en el primer acceso. Solo en esta ruta de alta, nunca en
                # create_user, un signal ni el default del modelo.
                password_must_change=True,
            )
    except IntegrityError as exc:
        if _is_email_unique_violation(exc):
            raise ValidationError({'email': [EMAIL_UNAVAILABLE]}) from exc
        if User.objects.filter(username__iexact=data['username']).exists():
            raise ValidationError({'username': [USERNAME_UNAVAILABLE]}) from exc
        raise

    _assign_system_role(user)
    record_staff_event(
        member=user, actor=admin, kind='created', request_id=request_id,
        changes={'role': user.role, 'attends_patients': user.attends_patients},
    )

    event = {
        "event": "STAFF_CREATED",
        "request_id": request_id,
        "actor_id": admin.pk,
        "actor_username": admin.username,
        "actor_role": admin.role,
        "organization_id": admin.organization_id,
        "target_user_id": user.pk,
        "target_username": user.username,
        "target_public_id": str(user.public_id),
        "target_role": user.role,
        # Note — the initial password is NEVER logged.
    }
    transaction.on_commit(lambda: _log_staff_created(event), robust=True)

    return CreateStaffResult(user=user, temp_password=temp_password, request_id=request_id)


# ---------------------------------------------------------------------------
# Service account del agente virtual (ADR p51)
# ---------------------------------------------------------------------------

AGENT_USERNAME_TEMPLATE = 'agent.whatsapp.{org_public_id}'


EMAIL_UNIQUE_CONSTRAINT = 'user_email_ci_unique'


def _is_email_unique_violation(exc):
    """True solo si la IntegrityError es del índice único del correo (ADR p48).

    Se compara el nombre de la restricción, nunca «cualquier IntegrityError»:
    convertir otro fallo en un error de correo ocultaría un bug (misma regla que
    `slot_taken`).
    """
    diag = getattr(getattr(exc, '__cause__', None), 'diag', None)
    constraint = getattr(diag, 'constraint_name', None)
    if constraint:
        return constraint == EMAIL_UNIQUE_CONSTRAINT
    return EMAIL_UNIQUE_CONSTRAINT in str(exc)


@transaction.atomic
def update_staff_profile(*, admin, target_user, changes):
    """Edita nombre, apellido, correo (A1, plan Equipo), especialidad y cédula
    (M01, orden 7) de un miembro de Equipo.

    La view ya limita el target a la organización del ADMIN; aquí se repite como
    defensa en profundidad (404-as-403). ``changes`` trae solo lo que cambia: sin
    cambios no se guarda ni se registra nada. Dos ADMIN que guardan el mismo
    correo a la vez: la restricción de base de datos decide y quien pierde
    recibe 400 en el campo. No toca los snapshots de documentos clínicos
    cerrados. El log lleva nombres de campo, no valores (el correo es dato
    personal).
    """
    from django.db import IntegrityError

    _assert_manageable_target(admin, target_user)
    _assert_not_demo_seed_account(target_user)
    fields = sorted(changes)
    if not fields:
        return target_user
    for field in fields:
        setattr(target_user, field, changes[field])
    try:
        with transaction.atomic():
            target_user.save(update_fields=fields)
    except IntegrityError as exc:
        if _is_email_unique_violation(exc):
            raise ValidationError({'email': [EMAIL_UNAVAILABLE]}) from exc
        raise
    record_staff_event(
        member=target_user, actor=admin, kind='profile_updated', changes={'fields': fields},
    )
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


# ---------------------------------------------------------------------------
# Last access (Fase 1 Equipo)
# ---------------------------------------------------------------------------

# Precisión del último acceso. Con sesiones que se renuevan solas (refresh cada
# ~10 min), escribir en cada renovación sería una escritura por usuario cada 10
# minutos para un dato que se lee en horas o días.
ACCESS_RECORD_INTERVAL = timedelta(hours=1)


def record_user_access(user, *, now=None) -> bool:
    """Record that ``user`` just obtained tokens (login or refresh).

    Called by the login and refresh views only after every rejection gate passed
    (inactive organization, expired temporary password, revoked session), so a
    refused attempt never counts as an access. ``SIMPLE_JWT['UPDATE_LAST_LOGIN']``
    stays off on purpose: it writes inside the serializer, before those gates,
    and never on refresh.

    One conditional ``UPDATE`` of ``last_login`` only: no ``save()``, no other
    field (``session_version`` and the rest stay untouched), and at most one
    write per ``ACCESS_RECORD_INTERVAL``. Service accounts are skipped.

    A database error is logged and swallowed: recording the access must never
    break an authentication that already succeeded. Returns True if it wrote.
    """
    from django.contrib.auth import get_user_model
    from django.db import DatabaseError
    from django.db.models import Q

    User = get_user_model()
    now = now or timezone.now()
    try:
        updated = (
            User.objects
            .filter(pk=user.pk, is_service_account=False)
            .filter(Q(last_login__isnull=True) | Q(last_login__lt=now - ACCESS_RECORD_INTERVAL))
            .update(last_login=now)
        )
    except DatabaseError:
        logger.warning("USER_ACCESS_RECORD_FAILED", extra={
            "event": "USER_ACCESS_RECORD_FAILED",
            "user_id": user.pk,
        })
        return False
    if updated:
        user.last_login = now
    return bool(updated)
