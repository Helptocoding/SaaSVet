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
