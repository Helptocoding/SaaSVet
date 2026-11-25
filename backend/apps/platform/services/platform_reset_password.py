"""
Platform-operator password reset service (ADR p45).

Distinct from `apps.users.services.reset_password_for_staff` (clinic ADMIN
flow, same-org only). This service is called exclusively by ADMIN_SAAS via
`POST /api/platform/staff/<public_id>/reset-password/` — a cross-tenant
operation that bypasses the same-org restriction.

Authorization contract (defence in depth — IsPlatformOperator runs first):
  - actor.role == 'ADMIN_SAAS' AND is_superuser AND is_staff
  - target.role != 'ADMIN_SAAS'  — operators cannot reset peers
  - target != actor               — self-reset uses change-password
  - target is not a service account — 404, same as the clinic reset (ADR p51,
    D13 of ADR p65): the agent's tokens carry no session version

Side effects (inside transaction.atomic):
  1. Generate cryptographically random temp password.
  2. set_password on target.
  3. password_must_change=True, password_temp_issued_at=now().
  4. Blacklist ALL existing tokens of target and bump its session version
     (ADR p65): access tokens stop working too, not only refresh tokens.
  5. Emit PLATFORM_PASSWORD_RESET_ISSUED audit log (temp_password NEVER logged).
  6. Return temp_password ONCE.
"""
from __future__ import annotations

import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from apps.users.services import bump_session_version, record_staff_event

logger = logging.getLogger('platform.events')

TEMP_PASSWORD_VALIDITY = timedelta(hours=24)
TEMP_PASSWORD_ENTROPY_BYTES = 16


@dataclass
class PlatformResetResult:
    """Return shape of ``platform_reset_password``."""
    temp_password: str
    expires_in_seconds: int
    duration_ms: int
    request_id: str


@transaction.atomic
def platform_reset_password(
    *,
    actor,
    target_user,
    request_id: str | None = None,
    client_ip: str = '',
    user_agent: str = '',
) -> PlatformResetResult:
    """
    Issue a temporary password on behalf of any staff member, cross-tenant.

    Called only from PlatformStaffResetPasswordView after IsPlatformOperator
    has already verified the caller. The service re-checks as defence in depth.
    """
    request_id = request_id or str(uuid.uuid4())
    started_at = time.monotonic()

    # --- Authorization gates (defence in depth) --------------------------------
    if not (
        getattr(actor, 'is_superuser', False)
        and getattr(actor, 'is_staff', False)
        and getattr(actor, 'role', None) == 'ADMIN_SAAS'
    ):
        raise PermissionDenied("Solo operadores de plataforma pueden usar esta operación.")

    if target_user.pk == actor.pk:
        raise PermissionDenied("Usa el cambio de contraseña personal para tu propia cuenta.")

    if getattr(target_user, 'role', None) == 'ADMIN_SAAS':
        raise PermissionDenied("No puedes resetear la contraseña de otros operadores de plataforma.")

    if getattr(target_user, 'is_service_account', False):
        # ADR p51 / p65 (D13) — 404-as-403, igual que el reset de clínica: un
        # reset dejaría al agente bloqueado por el cambio obligatorio y con una
        # versión de sesión que sus tokens (sin claim) ya no cumplirían.
        from django.http import Http404
        raise Http404("Usuario no encontrado.")

    # --- 1. Generate temp password ---------------------------------------------
    temp_password = secrets.token_urlsafe(TEMP_PASSWORD_ENTROPY_BYTES)

    # --- 2-3. Persist credential change + lifecycle flags ----------------------
    target_user.set_password(temp_password)
    target_user.password_must_change = True
    target_user.password_temp_issued_at = timezone.now()
    target_user.save(update_fields=[
        'password',
        'password_must_change',
        'password_temp_issued_at',
    ])

    # --- 4. Revoke every existing session of the target ------------------------
    old_outstanding = OutstandingToken.objects.filter(user=target_user)
    revoked_count = 0
    for ot in old_outstanding:
        _, created = BlacklistedToken.objects.get_or_create(token=ot)
        if created:
            revoked_count += 1
    bump_session_version(target_user)
    # ADR p68 (PO): quita también la verificación en dos pasos. Es la salida de
    # un único ADMIN que perdió su celular y sus códigos de respaldo.
    from apps.users.mfa import remove_for_reset
    mfa_removed = remove_for_reset(target_user)
    # ADR p66: también queda en el historial de accesos de la clínica, con el
    # operador de plataforma como actor y el origen marcado.
    if target_user.organization_id is not None:
        changes = {'source': 'platform'}
        if mfa_removed:
            changes['mfa_removed'] = True
        record_staff_event(
            member=target_user, actor=actor, kind='password_reset',
            changes=changes, request_id=request_id or '',
        )

    # --- 5. Audit log ----------------------------------------------------------
    # NOTE: temp_password is NEVER logged — not even hashed.
    # target_organization_* fields are critical for cross-tenant traceability.
    duration_ms = int((time.monotonic() - started_at) * 1000)
    target_org = getattr(target_user, 'organization', None)
    logger.info("PLATFORM_PASSWORD_RESET_ISSUED", extra={
        "event": "PLATFORM_PASSWORD_RESET_ISSUED",
        "request_id": request_id,
        "actor_id": actor.pk,
        "actor_username": actor.username,
        "actor_role": actor.role,
        "target_user_id": target_user.pk,
        "target_username": target_user.username,
        "target_public_id": str(target_user.public_id),
        "target_role": target_user.role,
        "target_organization_id": getattr(target_user, 'organization_id', None),
        "target_organization_name": getattr(target_org, 'name', None),
        "revoked_refresh_count": revoked_count,
        "client_ip": client_ip,
        "user_agent": user_agent,
        "duration_ms": duration_ms,
    })

    return PlatformResetResult(
        temp_password=temp_password,
        expires_in_seconds=int(TEMP_PASSWORD_VALIDITY.total_seconds()),
        duration_ms=duration_ms,
        request_id=request_id,
    )
