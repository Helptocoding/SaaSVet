"""
agent/guards.py — Filtro determinista sobre el texto YA generado (É-F3 W1-1).

Principio (enmienda E2 del PO): **una regla en el prompt es advisoria; una
regla en código es vinculante**. El modelo puede desobedecer una instrucción y
nadie se entera. Este módulo convierte cuatro reglas duras de la spec §2.2 en
comprobaciones que corren ANTES de encolar el saliente:

    G1  no inventar precios      → todo importe debe venir de una tool del turno
    G2  cero consejo médico      → patrones de dosis/diagnóstico/minimización
    G3  no prometer              → reembolsos, garantías, gratuidad
    G7  sin datos internos       → UUIDs y jerga del sistema

El prompt se acortó; el sistema quedó MÁS estricto, no menos.

Las listas viven aquí como fuente única: la suite de regresión las importa
(`tests/harness.py`) y añade encima su propia severidad de test.
"""
import re

# --- G7: jerga interna e identificadores -----------------------------------
UUID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
    re.IGNORECASE,
)

FORBIDDEN_JARGON = (
    'public_id', 'medical_record', 'invoice', 'draft', 'walk-in', 'walk_in',
    'vaccinerecord', 'medicalrecord', 'stock_quantity', 'tool_call',
    'agentinbox', 'idempotency',
)

# --- G2: consejo médico ----------------------------------------------------
# Patrones PRECISOS: esta lista corre en producción y un falso positivo manda
# al cliente con un humano sin motivo. Por eso NO incluye trozos ambiguos como
# "dale " (en México "dale" es un sí) — la severidad extra vive en los tests.
MEDICAL_ADVICE_PATTERNS = (
    'la dosis', 'la dósis', 'dosis recomendada', 'debes darle', 'puedes darle',
    'dale una pastilla', 'dale media pastilla', 'dale medio comprimido',
    'adminístrale', 'administrale', 'suminístrale', 'suministrale',
    'mg cada', 'ml cada', 'gotas cada', 'cada 8 horas', 'cada 12 horas',
    'seguramente no es', 'no es grave', 'no es nada grave', 'es normal que',
    'no te preocupes, es', 'probablemente sea', 'seguro es solo',
    'te recomiendo darle', 'puedes aplicarle', 'dale paracetamol',
    'dale ibuprofeno', 'dale aspirina',
)

# --- G3: promesas en nombre de la clínica ----------------------------------
PROMISE_PATTERNS = (
    'te devolvemos el dinero', 'te reembolsamos', 'te garantizamos',
    'garantizamos que', 'te lo dejamos gratis', 'sin ningún costo',
    'no te vamos a cobrar', 'te hacemos un descuento', 'te lo descontamos',
    'seguro te atienden sin cita',
)

# --- G1: importes -----------------------------------------------------------
MONEY_RE = re.compile(r'\$\s?\d[\d,]*(?:\.\d{1,2})?')

# Severidades. `hard` = no puede salir al cliente bajo ninguna circunstancia.
HARD = 'hard'
SOFT = 'soft'


class Violation:
    __slots__ = ('kind', 'severity', 'detail')

    def __init__(self, kind, severity, detail=''):
        self.kind = kind
        self.severity = severity
        self.detail = detail

    def __repr__(self):  # pragma: no cover - diagnóstico
        return f"Violation<{self.kind} {self.severity} {self.detail}>"


_NUMBER_RE = re.compile(r'\d[\d,]*(?:\.\d{1,2})?')


def _as_amount(raw):
    """'$1,200.00' → 1200.0. None si no es un número interpretable."""
    try:
        return round(float(raw.replace('$', '').replace(',', '').strip()), 2)
    except (ValueError, AttributeError):
        return None


def _money_values(text):
    """Importes citados en el texto (los que llevan signo de pesos)."""
    values = {_as_amount(raw) for raw in MONEY_RE.findall(text or '')}
    return {v for v in values if v is not None}


def _facts_numbers(tool_facts):
    """CUALQUIER número presente en los resultados de tools del turno.

    Deliberadamente permisivo: el objetivo es atrapar la cifra inventada de
    raíz, no auditar el formateo. Un falso positivo aquí escala una
    conversación sana, y eso cuesta más que un falso negativo cosmético.
    """
    blob = str(tool_facts or '')
    values = {_as_amount(raw) for raw in _NUMBER_RE.findall(blob)}
    return {v for v in values if v is not None}


def check_output(text, *, tool_facts=None):
    """Devuelve la lista de violaciones del texto generado (vacía si limpio).

    `tool_facts` = lo que las herramientas devolvieron en ESTE turno. Un
    importe que no aparezca ahí es un precio inventado (G1): el caso más caro
    de todos, porque el cliente llega a la clínica con una cifra que nadie dijo.
    """
    violations = []
    low = (text or '').lower()

    if UUID_RE.search(text or ''):
        violations.append(Violation('uuid', HARD))

    for jargon in FORBIDDEN_JARGON:
        if jargon in low:
            violations.append(Violation('jargon', SOFT, jargon))
            break

    for pattern in MEDICAL_ADVICE_PATTERNS:
        if pattern in low:
            violations.append(Violation('medical_advice', HARD, pattern))
            break

    for pattern in PROMISE_PATTERNS:
        if pattern in low:
            violations.append(Violation('promise', HARD, pattern))
            break

    quoted = _money_values(text)
    if quoted:
        known = _facts_numbers(tool_facts)
        invented = quoted - known
        if invented:
            violations.append(
                Violation('invented_price', HARD, str(sorted(invented)[0])))

    return violations


def has_hard(violations):
    return any(v.severity == HARD for v in violations)


def summarize(violations):
    return ','.join(sorted({v.kind for v in violations}))


CORRECTION_HINT = {
    'invented_price': (
        'No menciones ningún precio que no venga de una herramienta. Si no lo '
        'consultaste, dilo y ofrece consultarlo.'
    ),
    'medical_advice': (
        'No des indicaciones médicas de ningún tipo (dosis, diagnósticos, '
        'tranquilizar sobre síntomas). Ofrece una cita.'
    ),
    'promise': (
        'No prometas nada en nombre de la clínica (devoluciones, descuentos, '
        'gratuidad). Ofrece pasar con una persona.'
    ),
    'uuid': 'No incluyas identificadores técnicos.',
    'jargon': 'No uses términos internos del sistema; habla como recepción.',
}


def correction_message(violations):
    """Instrucción correctiva para el reintento (una sola, la más grave)."""
    ordered = sorted(violations, key=lambda v: 0 if v.severity == HARD else 1)
    kind = ordered[0].kind if ordered else ''
    return CORRECTION_HINT.get(kind, 'Reformula sin salirte de tus reglas.')
