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
# Puntuación que vive DENTRO de un nombre y no lo parte ("O'Brien", "Ana-Sofía").
_KEEP_PUNCT = {"'", '-'}


def _norm(text):
    """Normaliza para comparar nombres: NFD, minúsculas, sin diacríticos, sin
    artículos, y con la PUNTUACIÓN como límite de token.

    Lo último se añadió con el servicio de evidencia (plan de continuidad,
    §2.3.1): sin ello «cita para Luna, por favor» dejaba el token `luna,`, que
    no es igual a `luna` — y el modo pasivo exige igualdad de token completo,
    nunca substring. Un cliente escribiendo con coma quedaba sin verificar.
    """
    text = unicodedata.normalize('NFD', (text or '').lower().strip())
    kept = []
    for ch in text:
        category = unicodedata.category(ch)
        if category == 'Mn':
            continue                                  # diacrítico
        if category.startswith('P') and ch not in _KEEP_PUNCT:
            ch = ' '        # LÍMITE, no borrado: borrarla pegaría dos palabras
        kept.append(ch)
    tokens = [t for t in ''.join(kept).split() if t not in _ARTICLES]
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


def matches_pet_name_tolerant(candidate, registered):
    """MATCHER PURO, tolerante (typo, subconjunto de tokens).

    Es el único desde p59: tolerar una letra evita mandar a handoff a quien dice
    la verdad, y la barrera real no es la ortografía sino la PROCEDENCIA —que el
    valor esté en un mensaje del cliente y no lo hayamos dicho nosotros primero.
    Lo usan la comprobación del aporte y la detección de eco.
    """
    return _name_matches(candidate, registered)


# `matches_pet_name_exact` se RETIRÓ (ADR p59): era el matcher del modo
# `passive_free_text`, y con la gramática cerrada fuera no queda quién lo
# llame. Dejarlo vivo —nombrado por un régimen que ya no existe— es una
# invitación a reintroducirlo.


# `try_verify_by_pet_name`, `try_verify_by_pet_answer` y
# `try_verify_by_owner_name` fueron RETIRADAS (plan de continuidad, D21/D28).
#
# Las dos primeras promovían por su cuenta desde dos sitios distintos, así que
# el anti-eco y la actualización del compromiso dependían de que cada caller se
# acordara. Ahora son matchers puros y `_promote` tiene **exactamente un
# llamador**: `identity_evidence.verify_pet_evidence`. Es un invariante que se
# verifica estáticamente (`test_identity_evidence.py`).
#
# La tercera se retiró porque `owner_name` dejó de ser factor de verificación
# (D4b): el sistema conoce ese nombre y se lo enseña al staff en la bandeja, así
# que no prueba nada sobre quien escribe. Sigue usándose como CLAVE DE BÚSQUEDA
# en el reto familiar (`find_link_candidates`), donde no hay owner que filtrar.


def _promote(contact):
    contact.verification_level = ContactIdentity.VERIFICATION_CONFIRMED
    contact.verified_at = timezone.now()
    contact.auto_rematch_blocked = False
    contact.save(update_fields=[
        'verification_level', 'verified_at', 'auto_rematch_blocked'])


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
    """Vincula el contacto al owner resuelto por su propia alta de cliente.

    Vivía dentro de `tools.commit_register_new_client_and_pet`, y ahí era el
    tercer sitio del subsistema capaz de elevar el nivel a `confirmed_in_chat`
    — el gate estático de ADR p56 (invariante 5) lo detectó. Se mueve aquí para
    que la regla sea cierta sin excepciones: **elevar a `confirmed_in_chat`
    ocurre únicamente en este módulo**, que es el único que cotea contra la
    base.

    CUIDADO — por qué NO es legítimo asumir "Owner recién creado, sin
    expediente previo que suplantar": `create-with-patient` hace
    `Owner.objects.get_or_create(phone=...)`, así que `owner` puede ser un
    registro EXISTENTE reutilizado por coincidencia de teléfono, no uno
    nuevo (auditoría OCR 2026-08-08, ver Item 1 del plan). Por eso este
    módulo YA NO decide por sí solo si es seguro vincular: el caller
    (`tools.commit_register_new_client_and_pet`) es responsable de no
    invocar esta función cuando `contact.auto_rematch_blocked` es `True`
    (contacto reseteado — el `Owner` reutilizado sí tiene expediente previo,
    exactamente el que un ADMIN acaba de desvincular).

    Precondición (no verificada aquí, la garantiza el único caller): al
    llegar a este punto, `contact.auto_rematch_blocked` ya vale `False` —
    o porque el contacto nunca fue reseteado, o porque el caller superó su
    propio guard. Bajarlo aquí es entonces una operación idempotente sobre
    un valor que ya era `False`, nunca la primera línea de defensa.
    """
    contact.owner = owner
    contact.verification_level = ContactIdentity.VERIFICATION_CONFIRMED
    contact.verified_at = timezone.now()
    contact.linked_via = ContactIdentity.LINKED_SELF_REGISTER
    contact.auto_rematch_blocked = False
    contact.save(update_fields=[
        'owner', 'verification_level', 'verified_at', 'linked_via',
        'auto_rematch_blocked'])


def link_staff_verified(contact, owner):
    """Vincula el contacto a un `Owner` EXISTENTE tras verificación humana.

    **Cuarta —y última— vía que eleva el nivel de verificación** (FLUJO-C, ADR
    p57 §5.5). Es la más fuerte de todas: una persona identificada, con permiso
    propio (`agentinbox.identity_verify`), respondió por el cliente y dejó
    registro append-only de qué comprobó.

    Es también la única forma legítima de deshacer un
    `reset_contact_identity`: por eso limpia `auto_rematch_blocked`. Ese flag
    apaga el auto-enlace precisamente porque nadie había verificado nada; aquí
    alguien lo hizo, con nombre y evidencia, así que la premisa del bloqueo
    dejó de valer. Ninguna otra ruta puede bajarlo.

    **No comprueba las precondiciones**: eso es del servicio
    (`services.authorize_identity_link`), que lo hace bajo `select_for_update()`
    del contacto y del hand-off, en la misma transacción que escribe. Llamar a
    esta función sin esas comprobaciones vincula a ciegas.
    """
    contact.owner = owner
    contact.verification_level = ContactIdentity.VERIFICATION_STAFF
    contact.verified_at = timezone.now()
    contact.linked_via = ContactIdentity.LINKED_STAFF
    contact.auto_rematch_blocked = False
    contact.save(update_fields=[
        'owner', 'verification_level', 'verified_at', 'linked_via',
        'auto_rematch_blocked'])


def link_family(contact, owner):
    """Vincula el contacto como secundario del owner (tras el reto triple)."""
    contact.owner = owner
    contact.verification_level = ContactIdentity.VERIFICATION_CONFIRMED
    contact.verified_at = timezone.now()
    contact.linked_via = ContactIdentity.LINKED_FAMILY
    contact.auto_rematch_blocked = False
    contact.save(update_fields=[
        'owner', 'verification_level', 'verified_at', 'linked_via',
        'auto_rematch_blocked'])
