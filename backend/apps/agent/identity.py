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


def _token_eq(a, b):
    if a == b:
        return True
    return len(a) >= 4 and len(b) >= 4 and _levenshtein_le_1(a, b)


def _name_matches(candidate, registered):
    """Match tolerante (UX-03 + É-F3 W1-6).

    Tres vías, de la más estricta a la más laxa:
      1. Igualdad normalizada.
      2. Typo de distancia 1 en nombres de ≥4 letras (no colapsa 'Kim'/'Tim').
      3. **Subconjunto de tokens**: el lado corto está contenido en el largo
         ("Ana" contra "Ana Torres" registrado, "Luna" contra "Luna Bella").

    La vía 3 existe porque el reto preguntaba "¿a nombre de quién está el
    registro?" y rechazaba el **nombre de pila del propio cliente** — un
    cliente legítimo diciendo la verdad terminaba en handoff. Se exige que
    TODOS los tokens aportados coincidan y que al menos uno tenga ≥3 letras:
    no basta con acertar una partícula ("de", "la").
    """
    c, r = _norm(candidate), _norm(registered)
    if not c or not r:
        return False
    if c == r:
        return True
    if len(r) >= 4 and len(c) >= 4 and _levenshtein_le_1(c, r):
        return True

    short, long = c.split(), r.split()
    if len(short) > len(long):
        short, long = long, short
    if not short or not long:
        return False
    if max(len(t) for t in short) < 3:
        return False
    return all(any(_token_eq(a, b) for b in long) for a in short)


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
    contact.rematch_blocked = False
    contact.save(update_fields=[
        'verification_level', 'verified_at', 'rematch_blocked'])


# ---------------------------------------------------------------------------
# Vinculación familiar (UX-04, É-F2 PR-17b) — reto TRIPLE
# ---------------------------------------------------------------------------
# Un número no registrado que actúa por un cliente existente queda vinculado
# como contacto SECUNDARIO SOLO tras acertar los tres factores contra un mismo
# owner: nombre del titular + una mascota + últimos 4 dígitos del teléfono
# registrado. El contacto aporta; el sistema verifica (G4) — jamás se enumera.

def find_link_candidates(organization, titular_name):
    """Owners cuyo nombre matchea (tolerante) el aportado. Uso interno del reto
    — NUNCA se revela al cliente si existe o no."""
    from apps.patients.models import Owner
    if not _norm(titular_name):
        return []
    return [
        owner for owner in
        Owner.objects.for_organization(organization).filter(is_generic=False)
        if _name_matches(titular_name, owner.name)
    ]


def owner_has_pet(owner, answer):
    return any(_name_matches(answer, reg) for reg in _pet_names(owner))


def owner_digits_match(owner, answer):
    """True si los últimos 4 del teléfono registrado del owner == los aportados."""
    import re
    given = re.sub(r'\D', '', answer or '')
    phone = re.sub(r'\D', '', owner.phone or '')
    return bool(phone) and len(given) >= 4 and phone[-4:] == given[-4:]


def link_self_registered(contact, owner):
    """Vincula el contacto al owner que ACABA de crear con sus propios datos.

    Vivía dentro de `tools.commit_register_new_client_and_pet`, y ahí era el
    tercer sitio del subsistema capaz de elevar el nivel a `confirmed_in_chat`
    — el gate estático de ADR p56 (invariante 5) lo detectó. Se mueve aquí para
    que la regla sea cierta sin excepciones: **elevar a `confirmed_in_chat`
    ocurre únicamente en este módulo**, que es el único que cotea contra la
    base.

    Por qué es legítimo elevar aquí sin reto: el `Owner` se acaba de crear a
    partir de este mismo contacto (probó control del número al escribir y
    aportó sus datos). No hay expediente previo que suplantar — que es
    exactamente lo que el reto existe para impedir.
    """
    contact.owner = owner
    contact.verification_level = ContactIdentity.VERIFICATION_CONFIRMED
    contact.verified_at = timezone.now()
    contact.linked_via = ContactIdentity.LINKED_SELF_REGISTER
    contact.rematch_blocked = False
    contact.save(update_fields=[
        'owner', 'verification_level', 'verified_at', 'linked_via',
        'rematch_blocked'])


def link_family(contact, owner):
    """Vincula el contacto como secundario del owner (tras el reto triple)."""
    contact.owner = owner
    contact.verification_level = ContactIdentity.VERIFICATION_CONFIRMED
    contact.verified_at = timezone.now()
    contact.linked_via = ContactIdentity.LINKED_FAMILY
    contact.rematch_blocked = False
    contact.save(update_fields=[
        'owner', 'verification_level', 'verified_at', 'linked_via',
        'rematch_blocked'])
