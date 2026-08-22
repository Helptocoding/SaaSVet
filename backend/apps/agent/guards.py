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


def check_output(text, *, tool_facts=None, protected_name=None,
                 grounded_names=()):
    """Devuelve la lista de violaciones del texto generado (vacía si limpio).

    `tool_facts` = lo que las herramientas devolvieron en ESTE turno. Un
    importe que no aparezca ahí es un precio inventado (G1): el caso más caro
    de todos, porque el cliente llega a la clínica con una cifra que nadie dijo.

    `protected_name` = el nombre del titular registrado, cuando el contacto **no
    está verificado**. Emitirlo es fuga: es exactamente lo que ocurrió en la
    conv 18 de producción («Claro, Andrés 😊» a alguien que no había probado ser
    Andrés), y de ahí salió el bypass — el modelo leyó el nombre del contexto y
    el sistema lo verificó contra sí mismo.

    `grounded_names` = lo que el cliente escribió **recientemente** (burst actual
    o entrantes posteriores a la última respuesta del agente). Repetir lo que
    acaba de decir no es fuga. La ventana es corta a propósito: «alguna vez en el
    historial» convertía la repetición de una fuga vieja en autorización
    permanente.
    """
    violations = []
    low = (text or '').lower()

    if protected_name:
        leaked = _protected_name_leak(text, protected_name, grounded_names)
        if leaked:
            violations.append(Violation('identity_leak', HARD, leaked))

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


# ---------------------------------------------------------------------------
# Guards de CONDUCTA (É-F4 Fase 4) — R10, R2, BUG-AGENT-001
# ---------------------------------------------------------------------------
# Los de arriba juzgan **lo que se dijo** (léxico). Estos juzgan **cómo se está
# comportando el sistema**, que es donde estaban los fallos más caros de la
# auditoría de rigidez: ninguno de ellos es una palabra prohibida, y por eso
# `check_output` no los veía.
#
# Nacen los tres en SOFT, en **modo observación** a propósito: un guard nuevo
# en HARD escala conversaciones sanas, y una escalada de más le cuesta al
# cliente mucho más que un log de más. Promover uno a HARD exige mirar antes
# los `AGENT_OUTPUT_GUARD` que deje — con datos, no con intuición.

# R10 · el sistema repitiendo la misma pregunta. Dos umbrales, no uno, porque
# describen respuestas distintas al mismo problema (auditoría de rigidez §P5):
#
#   2 preguntas → el sistema CAMBIA DE ESTRATEGIA. Deja de pedir igual y
#                 ofrece opciones concretas o reformula. Lo aplica
#                 `tools._goal_gate`, que a partir de aquí ya no incrementa
#                 `asked`: el contador cuenta PREGUNTAS, y esto ya no lo es.
#   3 preguntas → es un bucle. El guard lo marca sobre el texto ya generado.
#
# Hasta É-F5 Fase 3 solo existía el segundo: `asked` subía sin tope y el modelo
# volvía a preguntar lo mismo. En el piloto (conv 12) llegó a
# `asked={'date': 4, 'time': 4}` y el cliente se fue.
CHANGE_APPROACH_AFTER = 2
REPEATED_ASK_LIMIT = 3

# R2 · negar lo que el cliente SÍ dijo. Patrones que niegan el HISTORIAL, no
# que pidan un dato que falta: "¿me dices la hora?" es legítimo aunque haya
# hechos anclados; "no me lo dijiste" con el hecho en el estado, no.
DENIAL_PATTERNS = (
    'no me lo dijiste', 'no me lo has dicho', 'no me habías dicho',
    'no me habias dicho', 'no me has dicho nada', 'no me dijiste nada',
    'aún no me lo has dicho', 'aun no me lo has dicho',
    'todavía no me lo has dicho', 'todavia no me lo has dicho',
    'no me lo habías mencionado', 'no me lo habias mencionado',
    'es la primera vez que me lo mencionas',
    'no recuerdo que me lo hayas dicho', 'no me lo dijiste aún',
    'no me lo dijiste aun',
)

# F1b · negar el HILO, no un dato suelto. En producción (conv 20) el agente
# contestó «Esta es una conversación nueva para mí, no tengo contexto de lo
# anterior» a un cliente con 19 conversaciones previas. Entonces era verdad —el
# contexto moría con el hilo—; desde F2 ya no lo es, así que decirlo pasa de
# descripción honesta a contradicción de su propio estado.
HISTORY_DENIAL_PATTERNS = (
    'no tengo contexto', 'sin contexto de lo anterior',
    'es una conversación nueva para mí', 'es una conversacion nueva para mi',
    'no tengo registro de conversaciones', 'no recuerdo conversaciones',
    'no tengo historial', 'no guardo el historial',
    'es la primera vez que hablamos', 'no habíamos hablado antes',
    'no habiamos hablado antes',
)

# BUG-AGENT-001 · dar por hecho algo que nunca se ejecutó. El fallo más caro
# del piloto: el agente recolectó todo en texto, jamás llamó una herramienta y
# dio por agendada una cita inexistente — dos veces, incluida la respuesta a un
# "¿la cita se creó bien?" del cliente.
SUCCESS_CLAIM_PATTERNS = (
    'ya quedó agendada', 'ya quedo agendada', 'quedó agendada', 'quedo agendada',
    'ya está agendada', 'ya esta agendada', 'ya te agendé', 'ya te agende',
    'ya la agendé', 'ya la agende', 'ya quedó tu cita', 'ya quedo tu cita',
    'cita agendada', 'ya quedó confirmada', 'ya quedo confirmada',
    'ya la cancelé', 'ya la cancele', 'ya quedó cancelada', 'ya quedo cancelada',
    'ya la moví', 'ya la movi', 'ya quedó reagendada', 'ya quedo reagendada',
    'ya te registré', 'ya te registre', 'ya quedó registrado',
    'ya quedo registrado',
)



# NEGAR lo que el dominio SÍ devolvió — el guard simétrico (ADR p59 §6).
#
# `unbacked_success` impide afirmar lo que no pasó. Nada impedía lo contrario, y
# ése fue el fallo más caro del piloto: conv 21, el agente dijo CUATRO veces «no
# tengo ninguna cita agendada» mientras las tools devolvían una, y el cliente
# respondía «estoy viendo el sistema y si hay» · «deberías buscar bien».
#
# Toda la gobernanza vigilaba que el agente no prometiera de más. Nada vigilaba
# que no negara lo que el sistema le estaba enseñando.
#
# Determinista: el conteo lo trae el propio `ToolOutcome`, así que la señal de
# «había algo» no se interpreta.
#
# El TEXTO sí se compara contra una lista, y esa lista comparte la debilidad que
# p59 le reprocha a la gramática de identidad: no se pueden enumerar todas las
# formas de negar algo en español. La diferencia está en la DIRECCIÓN del fallo, y
# es la que hace aceptable el método aquí:
#
#   - un fraseo no cubierto ⇒ no hay corrección. Fail-OPEN: se pierde una
#     oportunidad de mejora, nadie queda bloqueado.
#   - la gramática de identidad fallaba al revés: un fraseo no cubierto dejaba a
#     un cliente legítimo sin poder identificarse nunca. Fail-CLOSED.
#
# Por eso esta lista crece con el tráfico real sin culpa, y aquella tenía que
# desaparecer. La primera persona («no TENGO ninguna cita») está aquí porque es
# la que usó el agente en conv 21 y mi primera versión de la lista no la tenía.
EXISTENCE_DENIAL_PATTERNS = (
    # segunda/tercera persona: sobre lo que el CLIENTE tiene
    'no tienes ninguna cita', 'no tiene ninguna cita', 'no tienes citas',
    'no tiene citas', 'no hay ninguna cita', 'no hay citas',
    'no tienes mascotas registradas', 'no tiene mascotas registradas',
    'no tienes ninguna mascota', 'no tienes registrada',
    # primera persona: sobre lo que el AGENTE ve. La de conv 21.
    'no tengo ninguna cita', 'no tengo citas', 'no tengo registrada',
    'no tengo registrado', 'no me aparece ninguna cita',
    'no aparece ninguna cita', 'no me aparece ninguna mascota',
    'no encuentro ninguna cita', 'no encuentro citas',
    'no encontré ninguna cita', 'no encontre ninguna cita',
    'no veo ninguna cita', 'no veo citas',
)


# Afirmar una VERIFICACIÓN que no ocurrió (É-F5, hallazgo del eval real).
#
# El prompt lo prohíbe explícitamente —«nunca digas ni des por hecho que
# alguien quedó verificado: eso lo dice la herramienta, no tú»— y el modelo lo
# hizo igual: con `verification_level` sin tocar respondió «¡Listo, ya quedó
# verificada la ficha de Ana!». Es la lección de p54 otra vez: una regla en el
# prompt es advisoria; en código es vinculante.
#
# No es una fuga —`_verification_ok` sigue bloqueando toda tool personal— pero
# le miente al cliente sobre su propio estado, y a los dos turnos discute con
# él («si ya me verificaste»).
VERIFICATION_CLAIM_PATTERNS = (
    'ya quedó verificada', 'ya quedo verificada',
    'ya quedó verificado', 'ya quedo verificado',
    'ya estás verificada', 'ya estas verificada',
    'ya estás verificado', 'ya estas verificado',
    'ya te verifiqué', 'ya te verifique',
    'ya quedó validada', 'ya quedo validada',
    'ya quedó validado', 'ya quedo validado',
    'identidad confirmada', 'ya confirmé tu identidad',
    'ya confirme tu identidad',
)


def _first_match(low, patterns):
    for pattern in patterns:
        if pattern in low:
            return pattern
    return None


def _protected_name_leak(text, protected_name, grounded_names):
    """¿El saliente dice el nombre registrado sin que el cliente lo haya dicho?

    Compara por **tokens completos**, no por substring: con un titular llamado
    «Sol», buscar la cadena dentro del texto marcaría «hay sol hoy» y, como esto
    es HARD, `has_hard` descartaría una respuesta legítima al cliente.
    """
    from . import identity

    tokens = set(identity._norm(text).split())
    if not tokens:
        return ''
    grounded = set()
    for said in grounded_names or ():
        grounded.update(identity._norm(said).split())
    for part in identity._norm(protected_name).split():
        if len(part) < 3:
            continue                      # partículas: «de», «la», iniciales
        if part in tokens and part not in grounded:
            return part
    return ''


def check_behaviour(text, *, asked=None, anchored_facts=None, tool_ran=True,
                    verified=True, has_history=False, rows_read=0):
    """Violaciones de CONDUCTA del turno (vacía si todo bien).

    - `asked`: `{slot: veces_preguntado}` del compromiso en curso (R10).
    - `verified`: si el contacto está REALMENTE verificado al cerrar el turno.
      Si no lo está y el texto lo afirma, el agente le miente al cliente sobre
      su propio estado (É-F5). Se pasa el hecho, no el objeto: el guard no
      consulta la base.
    - `anchored_facts`: los hechos que SÍ viajaron al modelo en este turno.
      Si el texto niega haber sido informado y aquí hay algo, se contradice a
      sí mismo (R2) — el "no me lo dijiste aún" de la conv 13.
    - `tool_ran`: si se ejecutó ALGUNA herramienta en el turno. Confirmar una
      cita tras una LECTURA es legítimo; afirmarla sin tocar nada, no.
    - `has_history`: si este contacto ya había hablado con la clínica (F1b).
      Negar el HILO —«no tengo contexto de lo anterior»— era una descripción
      honesta cuando el contexto moría con la conversación; desde F2 el modelo
      recibe el hilo del contacto, así que decirlo contradice su propio estado.
    - `rows_read`: cuántas filas devolvieron las LECTURAS del turno (p59 §6). Si
      devolvieron algo y el texto niega que exista, el modelo está negando lo que
      el sistema le acaba de enseñar. Es el simétrico de `unbacked_success`, y su
      ausencia costó la conversación 21 completa.
    """
    violations = []
    low = (text or '').lower()

    worn = sorted(slot for slot, n in (asked or {}).items()
                  if n >= REPEATED_ASK_LIMIT)
    if worn and ('?' in (text or '') or '¿' in (text or '')):
        violations.append(Violation('repeated_question', SOFT, worn[0]))

    if anchored_facts:
        denial = _first_match(low, DENIAL_PATTERNS)
        if denial:
            violations.append(Violation('contradicts_state', SOFT, denial))

    if has_history:
        denial = _first_match(low, HISTORY_DENIAL_PATTERNS)
        if denial:
            violations.append(Violation('denies_history', SOFT, denial))

    if not tool_ran:
        claim = _first_match(low, SUCCESS_CLAIM_PATTERNS)
        if claim:
            violations.append(Violation('unbacked_success', SOFT, claim))


    if rows_read:
        denial = _first_match(low, EXISTENCE_DENIAL_PATTERNS)
        if denial:
            violations.append(Violation('denies_domain_state', SOFT, denial))

    if not verified:
        claim = _first_match(low, VERIFICATION_CLAIM_PATTERNS)
        if claim:
            violations.append(Violation('unbacked_verification', SOFT, claim))

    return violations


def has_hard(violations):
    return any(v.severity == HARD for v in violations)


def summarize(violations):
    return ','.join(sorted({v.kind for v in violations}))


CORRECTION_HINT = {
    'unbacked_verification': (
        'Todavía NO está verificado quién te escribe: no digas ni des por '
        'hecho que quedó verificado o validado. Eso lo dice la herramienta, '
        'no tú. Dile con naturalidad qué falta para poder ayudarle.'
    ),
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
    'repeated_question': (
        'Ese dato ya se lo pediste varias veces. No lo vuelvas a preguntar '
        'igual: ofrécele opciones concretas para elegir, o dile que lo ves '
        'con una persona del equipo.'
    ),
    'contradicts_state': (
        'El cliente SÍ te lo dijo y lo tienes en los DATOS de contexto. No '
        'digas que no te lo ha dicho: úsalo.'
    ),
    'unbacked_success': (
        'No has ejecutado ninguna herramienta en este turno, así que no ha '
        'pasado nada todavía. No des por hecha una cita, una cancelación ni '
        'un registro: haz lo que falte o dilo con honestidad.'
    ),
}


def correction_message(violations):
    """Instrucción correctiva para el reintento (una sola, la más grave)."""
    ordered = sorted(violations, key=lambda v: 0 if v.severity == HARD else 1)
    kind = ordered[0].kind if ordered else ''
    return CORRECTION_HINT.get(kind, 'Reformula sin salirte de tus reglas.')
