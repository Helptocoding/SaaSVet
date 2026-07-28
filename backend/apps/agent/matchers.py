"""
agent/matchers.py — Clasificadores DETERMINISTAS es-MX (É-F1 PR-11).

El router de la spec §3 corre estos matchers ANTES que el LLM: resuelven el
40-60 % del tráfico sin costo y sin riesgo de generación libre (spec §11.5).
Cero LLM aquí — solo listas mantenidas + normalización.

Todo se evalúa sobre texto normalizado (minúsculas, sin acentos, sin signos
de puntuación de borde). La detección de urgencia (R16) y las falsas
afirmativas (UX-02) son las de mayor consecuencia — su recall imperfecto
peca del lado seguro (más escalado / menos ejecución), nunca al revés.
"""
import re
import unicodedata


def normalize(text):
    text = unicodedata.normalize('NFD', (text or '').lower().strip())
    text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')
    # Quita puntuación (comas/signos) — deja letras, dígitos y espacios. Sin
    # esto "no, mejor no" no matchea el negativo y "sí, dale" queda 'unclear'.
    text = re.sub(r'[^\w\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _has_any(text, needles):
    return any(n in text for n in needles)


# --- INT-01 Urgencia (router prioridad 1; R16) -----------------------------
# Lemas, no palabras exactas: "convuls" cubre convulsión/convulsiona/etc.
_EMERGENCY_LEMMAS = (
    'convuls', 'atropell', 'no respira', 'no puede respirar', 'se ahoga',
    'sangra', 'sangrado', 'hemorragia', 'envenen', 'intoxic', 'se comio',
    'se trago veneno', 'no se mueve', 'se esta muriendo', 'agoniz',
    'inconsciente', 'no reacciona', 'parto', 'esta pariendo', 'fractura',
    'hueso de fuera', 'quemadura grave', 'golpe fuerte', 'cayo de',
    'vomita sangre', 'convulsion',
)


def is_emergency(text):
    return _has_any(normalize(text), _EMERGENCY_LEMMAS)


# --- INT-02 Hablar con humano ----------------------------------------------
_HUMAN_LEMMAS = (
    'hablar con una persona', 'con una persona', 'con un humano', 'una persona real',
    'hablar con alguien', 'con alguien del equipo', 'con recepcion', 'con la clinica',
    'atienda una persona', 'me atienda alguien', 'un humano', 'persona real',
    'quiero hablar con', 'comunicarme con alguien', 'con un asesor',
)


def wants_human(text):
    return _has_any(normalize(text), _HUMAN_LEMMAS)


# --- INT-04 Opt-out --------------------------------------------------------
_OPTOUT_LEMMAS = (
    'no me escriban', 'no me escribas', 'no quiero mensajes', 'ya no me contacten',
    'dejen de escribirme', 'darme de baja', 'baja de la lista', 'stop', 'cancelar suscripcion',
    'no me manden', 'quitenme',
)


def wants_optout(text):
    n = normalize(text)
    if n == 'stop':
        return True
    return _has_any(n, _OPTOUT_LEMMAS)


# --- INT-06 "¿Eres una persona?" -------------------------------------------
_BOTQ_LEMMAS = (
    'eres un robot', 'eres un bot', 'eres una persona', 'eres humano',
    'eres real', 'eres una maquina', 'con quien hablo', 'con quien estoy hablando',
    'eres una ia', 'esto es un bot', 'hablo con un robot', 'eres automatico',
    'eres un contestador',
)


def is_bot_question(text):
    return _has_any(normalize(text), _BOTQ_LEMMAS)


# --- Confirmación en dos etapas (UX-02, spec §2.4) -------------------------
# Etapa 1: matcher. Etapa 2 (clasificación LLM) vive en el planner (PR-12).
_AFFIRMATIVE = {
    'si', 'sii', 'siii', 'sip', 'simon', 'sale', 'sale pues', 'va', 'vale',
    'claro', 'correcto', 'confirmo', 'confirmado', 'ok', 'okey', 'oki', 'okis',
    'dale', 'de una', 'esta bien', 'perfecto', 'andale', 'orale', 'asi es',
    'si por favor', 'porfa si', 'adelante', 'hagamoslo', 'me sirve',
}
_NEGATIVE = {
    'no', 'nel', 'nop', 'mejor no', 'cancela', 'cancelar', 'aun no', 'todavia no',
    'ya no', 'no gracias', 'nel pastel', 'mejor cancelalo',
}
# Falsas afirmativas: NUNCA ejecutan ni cierran el flujo (el peligro real).
_FALSE_AFFIRMATIVE = {
    'ahorita', 'al rato', 'dejame ver', 'dejame checar', 'luego te digo',
    'yo te aviso', 'yo te digo', 'lo checo', 'lo veo', 'deja veo', 'espera',
    'mas tarde', 'ahi te digo', 'lo pienso', 'dejame pensarlo',
}


def classify_confirmation(text):
    """'affirmative' | 'negative' | 'defer' | 'unclear'.

    'affirmative' ejecuta el pending_action tal cual fue parafraseado (jamás
    lo amplía — TC-SEC-03). 'defer' (falsa afirmativa) NO ejecuta y NO cierra
    el flujo. 'unclear' → el planner clasifica (etapa 2)."""
    # Anclado a INICIO de frase, no substring: "y más tarde no tienes?" NO es
    # 'defer' (contiene "mas tarde" pero es modificación → 'unclear').
    if '👍' in (text or ''):
        return 'affirmative'
    n = normalize(text)
    if not n:
        return 'unclear'
    tokens = n.split()
    first = tokens[0]

    if _starts_with_phrase(n, _FALSE_AFFIRMATIVE):
        return 'defer'
    if n in _NEGATIVE or first in {'no', 'nel', 'nop'} or _starts_with_phrase(n, _NEGATIVE):
        return 'negative'
    if n in _AFFIRMATIVE:
        return 'affirmative'
    if (
        len(tokens) <= 4
        and any(t in _AFFIRMATIVE for t in tokens)
        and not any(t in {'no', 'nel', 'nop'} for t in tokens)
    ):
        return 'affirmative'
    return 'unclear'


def _starts_with_phrase(n, phrases):
    return any(n == p or n.startswith(p + ' ') for p in phrases)


# --- Saludo / intent trivial (INT-00 / tier-0 sin LLM) ---------------------
_GREETING = {
    'hola', 'buenas', 'buenos dias', 'buenas tardes', 'buenas noches',
    'que tal', 'hey', 'holi', 'holaa', 'buenas!', 'saludos',
}


def is_bare_greeting(text):
    """Solo saludo, sin intención adjunta (para no tragarse "hola quiero cita")."""
    n = normalize(text).rstrip('.!¡¿?')
    return n in _GREETING


_THANKS = {'gracias', 'muchas gracias', 'mil gracias', 'gracias', 'ok gracias',
           'perfecto gracias', 'excelente', 'muy amable'}


def is_thanks(text):
    return normalize(text).rstrip('.!') in _THANKS


# --- Tamiz de identidad (UX-05) --------------------------------------------
# Un número sin registro que pide algo PERSONAL (agendar, ver sus citas,
# cancelar) obliga a saber quién es. Preguntas de precio/horario NO: ésas se
# atienden en anónimo (tier 1) y meterles un tamiz sería fricción gratis.

_PERSONAL_ACTION_STRONG = (
    'agendar', 'agendame', 'agendarme', 'agenda una', 'agendas una',
    'programar una cita', 'sacar cita', 'sacar una cita', 'hacer una cita',
    'apartar una cita', 'reservar una cita', 'quiero una cita', 'quiero cita',
    'quisiera una cita', 'necesito una cita', 'necesito cita',
    'dame una cita', 'me das una cita', 'me puedes dar una cita',
    'mis citas', 'mi cita', 'que citas tengo', 'cuando es mi cita',
    'tengo alguna cita', 'mi proxima cita',
    'cancelar mi cita', 'cancelar la cita', 'reagendar', 'mover mi cita',
    'cambiar mi cita', 'recorrer mi cita',
    'cuando le toca', 'sus vacunas', 'vacunas de mi',
    'quiero llevar a', 'puedo llevar a', 'quiero llevarlo', 'quiero llevarla',
)
_PERSONAL_ACTION_WEAK = (
    'una cita', 'la cita', 'cita para', 'consulta para',
)
# Pregunta sobre la POLÍTICA de citas ("¿hace falta cita?"), no una petición.
# Gana incluso a los lemas fuertes: "¿necesito cita o puedo llegar así?" es
# información pública, no un trámite personal.
_APPOINTMENT_POLICY_QUESTION = (
    'necesito cita o', 'necesito una cita o', 'se necesita cita',
    'hay que hacer cita', 'hay que agendar', 'es necesario agendar',
    'se puede sin cita', 'atienden sin cita', 'aceptan sin cita',
    'puedo llegar sin cita', 'sin cita previa',
)
_INFO_ONLY_LEMMAS = (
    'cuanto cuesta', 'cuanto sale', 'cuanto vale', 'cuanto cobran',
    'cuanto tarda', 'cuanto dura', 'cuanto tiempo',
    'que precio', 'precio de', 'tienen precio', 'costo de',
    'que incluye', 'que necesito', 'que se necesita', 'que requisitos',
    'necesito llevar', 'tengo que llevar', 'que debo llevar',
    'a que hora abren', 'a que hora cierran', 'que horario', 'horario de',
    'estan abiertos', 'donde estan', 'donde queda', 'como llego',
)


def wants_personal_action(text):
    """¿La petición EXIGE saber quién es el cliente?

    Orden deliberado: una pregunta sobre la política de citas gana a todo
    (es info pública); un lema fuerte gana a los informativos; los débiles
    ('una cita') ceden ante cualquier pregunta de precio/horario/requisitos.
    """
    n = normalize(text)
    if _has_any(n, _APPOINTMENT_POLICY_QUESTION):
        return False
    if _has_any(n, _PERSONAL_ACTION_STRONG):
        return True
    if _has_any(n, _INFO_ONLY_LEMMAS):
        return False
    return _has_any(n, _PERSONAL_ACTION_WEAK)


# Negaciones EXPLÍCITAS. Se evalúan antes que las listas positivas porque las
# contienen: "no soy cliente" contiene "soy cliente"; "no es la primera vez"
# contiene "primera vez". Sin este orden, ambas se clasificaban al revés.
_TRIAGE_NEGATED_NEW = (          # niega ser nuevo → ya es cliente
    'no es la primera', 'no es mi primera', 'no es primera vez',
    'no soy nuevo', 'no somos nuevos', 'no es nuevo', 'no es nueva',
    'no es la primera vez',
)
_TRIAGE_NEGATED_RETURNING = (    # niega ser cliente → es nuevo
    'no soy cliente', 'no somos clientes', 'no soy paciente',
    'no estoy registrado', 'no estoy registrada', 'no estamos registrados',
    'no tengo registro', 'no tengo expediente', 'no tenemos expediente',
    'no he ido', 'no hemos ido', 'no he venido', 'no hemos venido',
    'no me han atendido', 'no nos han atendido', 'no los conozco',
    'no me conocen', 'no nos conocen',
)
_TRIAGE_RETURNING = (
    'ya he ido', 'ya he venido', 'ya hemos ido', 'ya hemos venido',
    'ya vine', 'ya venimos', 'ya habia venido', 'ya habiamos venido',
    'ya fui', 'ya fuimos', 'ya iba', 'ya lleve', 'ya la lleve', 'ya lo lleve',
    'ya he llevado', 'ya hemos llevado',
    'ya me atendieron', 'ya nos atendieron', 'ya la atendieron',
    'ya lo atendieron', 'ya me han atendido', 'ya nos han atendido',
    'ya la han atendido', 'ya lo han atendido', 'ya me habian atendido',
    'ya soy cliente', 'ya somos clientes', 'soy cliente', 'somos clientes',
    'ya soy paciente', 'soy paciente',
    'ya estoy registrado', 'ya estoy registrada', 'ya estamos registrados',
    'ya tengo registro', 'ya tengo expediente', 'ya tenemos expediente',
    'ya me conocen', 'ya nos conocen', 'ya los conozco', 'ya te conozco',
    'si he ido', 'si he venido', 'si ya', 'si soy cliente',
    'siempre voy con', 'siempre los visito', 'somos de ahi',
    'cambie de numero', 'cambie mi numero', 'cambie el numero',
    'numero nuevo', 'nuevo numero', 'otro numero', 'con otro numero',
    'desde otro numero', 'este numero es nuevo',
)
_TRIAGE_NEW = (
    'primera vez', 'primera visita', 'primer vez', 'es la primera',
    'seria la primera', 'seria mi primera', 'la primera vez',
    'soy nuevo', 'soy nueva', 'somos nuevos', 'somos nuevas',
    'cliente nuevo', 'clienta nueva', 'nuevo cliente', 'es nuevo', 'es nueva',
    'nunca he ido', 'nunca hemos ido', 'nunca he venido', 'nunca hemos venido',
    'nunca los he', 'nunca la he llevado', 'nunca lo he llevado',
    'nunca la he traido', 'nunca lo he traido', 'nunca he traido',
    'apenas voy', 'apenas la voy', 'apenas lo voy', 'apenas me estoy',
    'es mi primera', 'es nuestra primera',
)


def classify_client_triage(text):
    """'new' | 'returning' | 'unclear' — respuesta al tamiz.

    NUNCA se adivina: 'unclear' vuelve a preguntar. Un falso 'new' abre un
    expediente duplicado sobre alguien que ya existe; un falso 'returning'
    manda a un cliente nuevo a un reto que no puede pasar. Por eso un "sí" o
    un "no" pelones se quedan en 'unclear': ante "¿primera vez o ya has
    venido?" son genuinamente ambiguos y el costo de errar es alto.
    """
    n = normalize(text)
    if not n:
        return 'unclear'
    if _has_any(n, _TRIAGE_NEGATED_NEW):
        return 'returning'
    if _has_any(n, _TRIAGE_NEGATED_RETURNING):
        return 'new'
    if _has_any(n, _TRIAGE_RETURNING):
        return 'returning'
    if _has_any(n, _TRIAGE_NEW):
        return 'new'
    return 'unclear'
