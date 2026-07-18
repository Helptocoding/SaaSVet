"""
agent/identity.py — Verificación de identidad del contacto (É-F1 PR-11).

Regla central (spec §2.3, G4): el cliente APORTA, el sistema VERIFICA —
jamás se enumera nada ("¿eres Juan?"/"¿tu mascota es Luna?" están
prohibidos). Dos vías:

- IMPLÍCITA: nombrar correctamente una mascota registrada = reto pasado.
  El slot-filling natural ("cita para Luna") sube phone_match →
  confirmed_in_chat sin fricción.
- EXPLÍCITA (tolerante, UX-03): normalización fuerte + artículos + typo de
  distancia 1 en nombres ≥4 letras; un no-match pide repetición SIN contar
  como fallo; 2º factor = nombre del titular; 2 fallos REALES → E-06.

`confirmed_in_chat` persiste; se re-reta si `verified_at` > 6 meses o el
Owner cambió.
"""
import unicodedata
from datetime import timedelta

from django.utils import timezone

from .models import ContactIdentity

VERIFICATION_TTL = timedelta(days=182)  # ~6 meses (spec §2.3)
_ARTICLES = {'la', 'el', 'mi', 'mis', 'los', 'las', 'un', 'una'}


def _norm(text):
    text = unicodedata.normalize('NFD', (text or '').lower().strip())
    text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')
    tokens = [t for t in text.split() if t not in _ARTICLES]
    return ' '.join(tokens)


def _levenshtein_le_1(a, b):
    """True si la distancia de edición entre a y b es ≤ 1 (rápido, sin matriz)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:  # una sustitución
        return sum(1 for x, y in zip(a, b) if x != y) == 1
    # una inserción/borrado: el más corto es subsecuencia por una brecha
    if la > lb:
        a, b = b, a
        la, lb = lb, la
    i = j = 0
    skipped = False
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1
            j += 1
        elif skipped:
            return False
        else:
            skipped = True
            j += 1
    return True


def _name_matches(candidate, registered):
    """Match tolerante (UX-03): normalizado exacto, o typo distancia 1 en
    nombres de ≥4 letras (evita colapsar nombres cortos tipo 'Kim'/'Tim')."""
    c, r = _norm(candidate), _norm(registered)
    if not c or not r:
        return False
    if c == r:
        return True
    if len(r) >= 4 and len(c) >= 4 and _levenshtein_le_1(c, r):
        return True
    return False


def is_verification_current(contact):
    if contact.verification_level not in (
        ContactIdentity.VERIFICATION_CONFIRMED,
        ContactIdentity.VERIFICATION_STAFF,
    ):
        return False
    if contact.owner_id is None:
        return False
    if contact.verified_at is None:
        return False
    return (timezone.now() - contact.verified_at) <= VERIFICATION_TTL


def _pet_names(owner):
    from apps.patients.models import Pet
    return list(
        Pet.objects.for_organization(owner.organization)
        .filter(owner=owner, is_generic=False)
        .values_list('name', flat=True)
    )


def try_verify_by_pet_name(contact, text):
    """Verificación IMPLÍCITA: ¿el texto nombra una mascota registrada?

    Sube a confirmed_in_chat si hay match Y el contacto tiene owner
    (phone_match). Devuelve True si verificó. No enumera nada."""
    if contact.owner_id is None:
        return False
    tokens = _norm(text).split()
    registered = _pet_names(contact.owner)
    for reg in registered:
        reg_norm = _norm(reg)
        # Match del nombre completo o de cualquier token del mensaje.
        if _name_matches(text, reg) or any(
            _name_matches(tok, reg) for tok in tokens
        ):
            _promote(contact)
            return True
    return False


def try_verify_by_pet_answer(contact, answer):
    """Reto EXPLÍCITO paso 1: el cliente responde con el nombre de su mascota."""
    if contact.owner_id is None:
        return False
    for reg in _pet_names(contact.owner):
        if _name_matches(answer, reg):
            _promote(contact)
            return True
    return False


def try_verify_by_owner_name(contact, answer):
    """Reto EXPLÍCITO 2º factor (UX-03): nombre del titular registrado."""
    if contact.owner_id is None:
        return False
    if _name_matches(answer, contact.owner.name):
        _promote(contact)
        return True
    return False


def _promote(contact):
    contact.verification_level = ContactIdentity.VERIFICATION_CONFIRMED
    contact.verified_at = timezone.now()
    contact.save(update_fields=['verification_level', 'verified_at'])
