"""
channels/crypto.py — Cifrado en reposo (Fernet) de secretos guardados en DB.

El access token de WhatsApp puede rotarse desde la UI; para no dejarlo en claro
en la base se cifra con Fernet (AES-128-CBC + HMAC). La clave sale de
``AGENT_TOKEN_ENC_KEY`` (env, clave Fernet urlsafe-b64 de 32 bytes) si existe;
si no, se deriva de ``SECRET_KEY`` (SHA-256 → 32 bytes b64) — suficiente para un
secreto efímero (el token de Meta caduca en 24 h y se re-pega).

Rotar ``SECRET_KEY``/``AGENT_TOKEN_ENC_KEY`` invalida los tokens ya guardados
(no se pueden descifrar) → simplemente se vuelven a pegar. El texto plano NUNCA
se persiste ni se loguea.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet():
    key = getattr(settings, 'AGENT_TOKEN_ENC_KEY', '') or ''
    if key:
        return Fernet(key.encode() if isinstance(key, str) else key)
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext):
    if not plaintext:
        return ''
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext):
    if not ciphertext:
        return ''
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        return ''
