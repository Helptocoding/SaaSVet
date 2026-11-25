"""TOTP (RFC 6238) y códigos de respaldo para la verificación en dos pasos (ADR p68).

Solo biblioteca estándar: HMAC-SHA1, 6 dígitos, pasos de 30 s, que es lo que
usan Google Authenticator, Microsoft Authenticator, 1Password y Authy. Las
pruebas usan los vectores del RFC.

El secreto se guarda cifrado (Fernet, de ``cryptography``, ya en el lock) con una
clave derivada de ``MFA_ENCRYPTION_KEY`` o, si no se define, de ``SECRET_KEY``.
Cambiar esa clave invalida los secretos guardados: quien tenga MFA activo tendrá
que activarlo de nuevo tras un restablecimiento de contraseña.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

STEP_SECONDS = 30
DIGITS = 6
# Un paso antes y uno después: tolera ±30 s de desfase entre el celular y el
# servidor, que es lo habitual y lo que recomienda el RFC.
WINDOW = 1
RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789'  # sin 0/o, 1/l/i


def new_secret():
    """160 bits aleatorios en base32 sin relleno (lo que esperan las apps)."""
    return base64.b32encode(secrets.token_bytes(20)).decode('ascii').rstrip('=')


def _secret_bytes(secret):
    clean = secret.replace(' ', '').upper()
    return base64.b32decode(clean + '=' * (-len(clean) % 8))


def code_at(secret, step, digits=DIGITS):
    digest = hmac.new(_secret_bytes(secret), struct.pack('>Q', step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return f'{value:0{digits}d}'


def current_step(now=None):
    return int((time.time() if now is None else now) // STEP_SECONDS)


def normalize_code(code):
    return ''.join(ch for ch in str(code or '') if ch.isdigit())


def matching_step(secret, code, *, now=None, after_step=None):
    """El paso que valida ``code`` dentro de la ventana, o ``None``.

    ``after_step`` es el último paso ya usado: un código no se acepta dos veces
    (ni uno anterior), así que alguien que lo vea por encima del hombro no puede
    repetirlo."""
    code = normalize_code(code)
    if len(code) != DIGITS:
        return None
    base = current_step(now)
    for step in (base, base - WINDOW, base + WINDOW):
        if after_step is not None and step <= after_step:
            continue
        if hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def group_secret(secret):
    """«ABCD EFGH …» para teclearla a mano."""
    return ' '.join(secret[i:i + 4] for i in range(0, len(secret), 4))


def provisioning_uri(secret, account):
    issuer = settings.MFA_ISSUER
    label = quote(f'{issuer}:{account}')
    query = urlencode({'secret': secret, 'issuer': issuer, 'algorithm': 'SHA1',
                       'digits': DIGITS, 'period': STEP_SECONDS})
    return f'otpauth://totp/{label}?{query}'


# ── Códigos de respaldo ────────────────────────────────────────────────────

def new_recovery_codes(count=RECOVERY_CODE_COUNT):
    """«abcde-fghjk»: 10 caracteres de un alfabeto sin ambigüedades (~49 bits)."""
    codes = []
    for _ in range(count):
        raw = ''.join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        codes.append(f'{raw[:5]}-{raw[5:]}')
    return codes


def normalize_recovery_code(code):
    return ''.join(ch for ch in str(code or '').lower() if ch in _RECOVERY_ALPHABET)


def _derived_key(purpose):
    base = settings.MFA_ENCRYPTION_KEY or settings.SECRET_KEY
    return hashlib.sha256(f'users.mfa.{purpose}.v1|{base}'.encode()).digest()


def hash_recovery_code(code):
    return hmac.new(_derived_key('recovery'), normalize_recovery_code(code).encode(),
                    hashlib.sha256).hexdigest()


# ── Cifrado del secreto ────────────────────────────────────────────────────

def _fernet():
    return Fernet(base64.urlsafe_b64encode(_derived_key('secret')))


def encrypt_secret(secret):
    return _fernet().encrypt(secret.encode('ascii')).decode('ascii')


def decrypt_secret(token):
    """``None`` si no se puede descifrar (clave cambiada): se trata como sin MFA
    utilizable, nunca como «cualquier código vale»."""
    try:
        return _fernet().decrypt(token.encode('ascii')).decode('ascii')
    except (InvalidToken, ValueError):
        return None
