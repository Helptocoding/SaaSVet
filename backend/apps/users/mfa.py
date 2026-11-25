"""Verificación en dos pasos (ADR p68): activar, desactivar, códigos de respaldo
y el segundo paso del inicio de sesión.

Decisiones del PO (2026-11-24): opcional y solo para ADMIN; código de una app
autenticadora tecleando la clave (sin QR); 10 códigos de respaldo de un solo
uso; un restablecimiento de contraseña o una reactivación lo quitan.

Inicio de sesión con MFA activo: la contraseña correcta NO emite tokens; devuelve
un reto firmado (``mfa_token``, 5 minutos, ligado a la versión de sesión de la
persona). Los tokens salen solo de ``complete_login_challenge`` con un código
válido. Cinco códigos incorrectos invalidan el reto.
"""
from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from django.core import signing
from django.core.cache import caches
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import (
    APIException, AuthenticationFailed, PermissionDenied, ValidationError,
)

from apps.users import totp

logger = logging.getLogger('users.events')

LOGIN_CHALLENGE_SALT = 'users.mfa.login.v1'
LOGIN_CHALLENGE_MAX_AGE = 300
LOGIN_CHALLENGE_MAX_ATTEMPTS = 5
PENDING_SETUP_MAX_AGE = timedelta(minutes=30)


class MFANotAvailable(PermissionDenied):
    default_detail = 'La verificación en dos pasos está disponible para administradores.'
    default_code = 'mfa_not_available'


class MFAAlreadyEnabled(APIException):
    status_code = 409
    default_detail = 'La verificación en dos pasos ya está activa.'
    default_code = 'mfa_already_enabled'


class MFANotEnabled(APIException):
    status_code = 409
    default_detail = 'La verificación en dos pasos no está activa.'
    default_code = 'mfa_not_enabled'


class MFAChallengeInvalid(AuthenticationFailed):
    default_detail = 'La verificación expiró o ya no es válida. Inicia sesión de nuevo.'
    default_code = 'mfa_challenge_invalid'


class MFACodeInvalid(AuthenticationFailed):
    default_detail = 'El código no es válido. Revisa la hora del celular o usa un código de respaldo.'
    default_code = 'mfa_code_invalid'


def mfa_available(user) -> bool:
    """Se ofrece a ADMIN humanos de una clínica real (no demo)."""
    org = getattr(user, 'organization', None)
    return (getattr(user, 'role', None) == 'ADMIN'
            and not getattr(user, 'is_service_account', False)
            and org is not None and not getattr(org, 'is_demo', False))


def _row(user, *, lock=False):
    from apps.users.models import UserMFA
    qs = UserMFA.objects.filter(user_id=user.pk)
    if lock:
        qs = qs.select_for_update()
    return qs.first()


def is_mfa_enabled(user) -> bool:
    row = _row(user)
    return bool(row and row.is_enabled)


def mfa_status(user) -> dict:
    row = _row(user)
    enabled = bool(row and row.is_enabled)
    return {
        # Quien lo tiene activo puede verlo y quitarlo aunque ya no sea ADMIN.
        'available': mfa_available(user) or enabled,
        'enabled': enabled,
        'enabled_at': row.enabled_at if enabled else None,
        'recovery_codes_remaining': len(row.recovery_code_hashes) if enabled else 0,
    }


def _check_password(user, password):
    if not password or not user.check_password(password):
        raise ValidationError({'password': ['La contraseña no es correcta.']})


def _invalid_code():
    return ValidationError({'code': [
        'El código no coincide. Revisa que la hora del celular sea automática y vuelve a intentarlo.']})


def _consume_second_factor(row, code):
    """Valida y consume un código TOTP o de respaldo. ``row`` debe venir bloqueada.
    Devuelve ``'totp'``, ``'recovery'`` o ``None``. No guarda nada si falla."""
    secret = totp.decrypt_secret(row.secret_encrypted)
    digits = totp.normalize_code(code)
    if secret and len(digits) == totp.DIGITS and digits == str(code).strip().replace(' ', ''):
        step = totp.matching_step(secret, digits, after_step=row.last_used_step)
        if step is None:
            return None
        row.last_used_step = step
        row.save(update_fields=['last_used_step', 'updated_at'])
        return 'totp'
    hashed = totp.hash_recovery_code(code)
    if totp.normalize_recovery_code(code) and hashed in row.recovery_code_hashes:
        row.recovery_code_hashes = [h for h in row.recovery_code_hashes if h != hashed]
        row.save(update_fields=['recovery_code_hashes', 'updated_at'])
        return 'recovery'
    return None


def _event(user, kind, request_id, changes=None):
    from apps.users.services import record_staff_event
    if user.organization_id:
        record_staff_event(member=user, actor=user, kind=kind, changes=changes or {},
                           request_id=request_id or '')


@transaction.atomic
def start_setup(user, password):
    """Genera una clave nueva pendiente de confirmar. Repetirlo la reemplaza."""
    from apps.users.models import UserMFA

    if not mfa_available(user):
        raise MFANotAvailable()
    _check_password(user, password)
    row, _ = UserMFA.objects.select_for_update().get_or_create(user=user)
    if row.is_enabled:
        raise MFAAlreadyEnabled()
    secret = totp.new_secret()
    row.pending_secret_encrypted = totp.encrypt_secret(secret)
    row.pending_created_at = timezone.now()
    row.save(update_fields=['pending_secret_encrypted', 'pending_created_at', 'updated_at'])
    return {
        'secret': totp.group_secret(secret),
        'otpauth_uri': totp.provisioning_uri(secret, user.email or user.username),
    }


@transaction.atomic
def enable(user, code, *, request_id=''):
    """Activa con el primer código de la app y devuelve los códigos de respaldo,
    que solo se muestran esta vez."""
    from apps.users.models import StaffAccessEvent

    if not mfa_available(user):
        raise MFANotAvailable()
    row = _row(user, lock=True)
    if row is not None and row.is_enabled:
        raise MFAAlreadyEnabled()
    if row is None or not row.pending_secret_encrypted:
        raise ValidationError({'code': ['Primero genera la clave para tu app.']})
    if row.pending_created_at is None or timezone.now() - row.pending_created_at > PENDING_SETUP_MAX_AGE:
        raise ValidationError({'code': ['La clave expiró. Genera una nueva.']})
    secret = totp.decrypt_secret(row.pending_secret_encrypted)
    step = totp.matching_step(secret, code) if secret else None
    if step is None:
        raise _invalid_code()
    codes = totp.new_recovery_codes()
    row.secret_encrypted = row.pending_secret_encrypted
    row.pending_secret_encrypted = ''
    row.pending_created_at = None
    row.enabled_at = timezone.now()
    row.last_used_step = step
    row.recovery_code_hashes = [totp.hash_recovery_code(c) for c in codes]
    row.save()
    _event(user, StaffAccessEvent.KIND_MFA_ENABLED, request_id)
    transaction.on_commit(lambda: logger.info('MFA_ENABLED', extra={
        'event': 'MFA_ENABLED', 'user_id': user.pk,
        'organization_id': user.organization_id}), robust=True)
    return codes


@transaction.atomic
def disable(user, password, code, *, request_id=''):
    from apps.users.models import StaffAccessEvent

    _check_password(user, password)
    row = _row(user, lock=True)
    if row is None or not row.is_enabled:
        raise MFANotEnabled()
    if _consume_second_factor(row, code) is None:
        raise _invalid_code()
    row.delete()
    _event(user, StaffAccessEvent.KIND_MFA_DISABLED, request_id)
    transaction.on_commit(lambda: logger.info('MFA_DISABLED', extra={
        'event': 'MFA_DISABLED', 'user_id': user.pk,
        'organization_id': user.organization_id}), robust=True)


@transaction.atomic
def regenerate_recovery_codes(user, password, code):
    """Invalida los códigos anteriores y devuelve 10 nuevos."""
    _check_password(user, password)
    row = _row(user, lock=True)
    if row is None or not row.is_enabled:
        raise MFANotEnabled()
    if _consume_second_factor(row, code) is None:
        raise _invalid_code()
    codes = totp.new_recovery_codes()
    row.recovery_code_hashes = [totp.hash_recovery_code(c) for c in codes]
    row.save(update_fields=['recovery_code_hashes', 'updated_at'])
    transaction.on_commit(lambda: logger.info('MFA_RECOVERY_CODES_REGENERATED', extra={
        'event': 'MFA_RECOVERY_CODES_REGENERATED', 'user_id': user.pk}), robust=True)
    return codes


def remove_for_reset(user) -> bool:
    """Quita el MFA al restablecer la contraseña o reactivar (decisión del PO).
    Corre dentro de la transacción del llamador. ``True`` si había uno."""
    from apps.users.models import UserMFA
    deleted, _ = UserMFA.objects.filter(user_id=user.pk).delete()
    if deleted:
        transaction.on_commit(lambda: logger.info('MFA_REMOVED_BY_RESET', extra={
            'event': 'MFA_REMOVED_BY_RESET', 'user_id': user.pk}), robust=True)
    return bool(deleted)


# ── Segundo paso del inicio de sesión ───────────────────────────────────────

def issue_login_challenge(user) -> str:
    return signing.dumps(
        {'u': user.pk, 'sv': user.session_version, 'n': secrets.token_urlsafe(16)},
        salt=LOGIN_CHALLENGE_SALT, compress=True,
    )


def complete_login_challenge(token, code):
    """Devuelve ``(user, method, recovery_codes_remaining)`` si el código es
    válido. Un reto vale para un
    solo inicio de sesión, cinco intentos y 5 minutos, y muere si la persona
    cambió de contraseña o fue desactivada mientras tanto."""
    from django.contrib.auth import get_user_model

    try:
        payload = signing.loads(token or '', salt=LOGIN_CHALLENGE_SALT,
                                max_age=LOGIN_CHALLENGE_MAX_AGE)
        user_pk, session_version, nonce = payload['u'], payload['sv'], payload['n']
    except (signing.BadSignature, KeyError, TypeError):
        raise MFAChallengeInvalid()
    # Misma caché que los límites de login: si no responde, falla cerrado.
    cache = caches['throttle_login']
    attempts_key, used_key = f'mfa-login:{nonce}:attempts', f'mfa-login:{nonce}:used'
    if cache.get(used_key) or (cache.get(attempts_key) or 0) >= LOGIN_CHALLENGE_MAX_ATTEMPTS:
        raise MFAChallengeInvalid()
    user = (get_user_model().objects.select_related('organization')
            .filter(pk=user_pk, is_active=True).first())
    if user is None or user.session_version != session_version:
        raise MFAChallengeInvalid()
    with transaction.atomic():
        row = _row(user, lock=True)
        if row is None or not row.is_enabled:
            raise MFAChallengeInvalid()
        method = _consume_second_factor(row, code)
        remaining = len(row.recovery_code_hashes)
    if method is None:
        cache.add(attempts_key, 0, timeout=LOGIN_CHALLENGE_MAX_AGE)
        try:
            cache.incr(attempts_key)
        except ValueError:
            cache.set(attempts_key, 1, timeout=LOGIN_CHALLENGE_MAX_AGE)
        logger.warning('MFA_LOGIN_CODE_INVALID', extra={
            'event': 'MFA_LOGIN_CODE_INVALID', 'user_id': user.pk})
        raise MFACodeInvalid()
    cache.set(used_key, True, timeout=LOGIN_CHALLENGE_MAX_AGE)
    logger.info('MFA_LOGIN_VERIFIED', extra={
        'event': 'MFA_LOGIN_VERIFIED', 'user_id': user.pk, 'method': method,
        'recovery_codes_remaining': remaining})
    return user, method, remaining
