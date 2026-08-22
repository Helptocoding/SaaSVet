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


# Quiere pagar POR AQUÍ. Fuera de alcance: en la clínica se cobra en caja, y
# el agente no toca dinero. Vivía en `policy.py` como parte de una decisión;
# desde É-F5 Fase 5 es un HECHO que se le publica al modelo — la frase la
# redacta él, el límite lo sigue poniendo el sistema (no hay tool de cobro).
_PAYMENT_LEMMAS = (
    'te puedo pagar por aqui', 'te pago por aqui', 'pagar por whatsapp',
    'transferencia', 'tu clabe', 'numero de tarjeta', 'deposito', 'te deposito',
    'pago en linea', 'link de pago', 'me pasas tu cuenta',
)


def mentions_payment(text):
    return _has_any(normalize(text), _PAYMENT_LEMMAS)


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


def is_bare_affirmative(text):
    """Verdadero solo si el mensaje no contiene una instrucción adicional.

    Fuera de una propuesta persistida, un "sí" aislado no tiene una operación
    que confirmar y el router debe resolverlo sin delegarlo al modelo. Una
    frase como "sí, voy a asistir" sí comunica una intención nueva: puede
    recorrer el planner y, si corresponde, la herramienta inocua de confirmar
    asistencia. Esta separación evita la segunda confirmación sin convertir
    toda frase que contenga "sí" en una respuesta inválida.
    """
    if '👍' in (text or ''):
        return not normalize((text or '').replace('👍', ''))
    return normalize(text) in _AFFIRMATIVE


def _starts_with_phrase(n, phrases):
    return any(n == p or n.startswith(p + ' ') for p in phrases)


# `is_bare_greeting` y su lista `_GREETING` se retiraron con la rama de saludo
# (É-F5 Fase 5). Existían para que el router distinguiera "hola" de "hola
# quiero cita" y despachara el primero con una plantilla; ya no hay nada que
# despachar. Se van con sus tests: un matcher sin consumidor es código muerto,
# y uno CON tests es peor, porque los tests lo hacen parecer vivo.


_THANKS = {'gracias', 'muchas gracias', 'mil gracias', 'gracias', 'ok gracias',
           'perfecto gracias', 'excelente', 'muy amable'}


def is_thanks(text):
    return normalize(text).rstrip('.!') in _THANKS


# --- Tamiz de identidad (UX-05) --------------------------------------------
# Un número sin registro que pide algo PERSONAL (agendar, ver sus citas,
# cancelar) obliga a saber quién es. Preguntas de precio/horario NO: ésas se
# atienden en anónimo (tier 1) y meterles un tamiz sería fricción gratis.

# ---------------------------------------------------------------------------
# Tamiz de identidad y detección de acción personal — RETIRADOS (É-F5 Fase 2)
# ---------------------------------------------------------------------------
# Aquí vivían `wants_personal_action` (con sus cuatro listas de lemas) y las
# constantes `_TRIAGE_*` que alimentaban `classify_client_triage`. Servían al
# paso 12b de `policy.evaluate`, que interceptaba a todo número sin registro
# antes de que el modelo viera el mensaje.
#
# Su límite era estructural, no de cobertura: clasificaban "¿de qué tipo es
# este cliente?" y NUNCA podían devolver un dato. En la conversación que abrió
# É-F5 el cliente escribió "ya he ido, mi nombre es Ana"; el tamiz acertó la
# clasificación y perdió el nombre, porque no tenía dónde ponerlo.


# Lemas de pregunta. SOBREVIVEN a la Fase 2 aunque la FSM de identidad se haya
# retirado: `looks_like_question` tiene un consumidor nuevo desde la Fase 1 —
# `planner._settle_goal`, que impide que preguntar acerque al cliente a una
# escalada (C11/R10). Es un hecho de CONTROL, el mismo que alimentaba
# `TurnFacts.interrupts`.
_QUESTION_LEMMAS = (
    'para que', 'pa que', 'por que', 'pq', 'que necesitas',
    'para que lo quieres', 'para que sirve', 'no entiendo', 'como asi',
    'a que te refieres', 'que es eso', 'es seguro', 'es necesario',
    'tengo que darte', 'y eso', 'que dije', 'que te dije',
    'no te acuerdas', 'ya te dije', 'se te borro', 'que miras',
    'no acabamos de', 'no me acabas de',
)


def looks_like_question(text):
    """¿El mensaje interroga en vez de responder?

    Ojo: `normalize()` borra la puntuación, así que los signos se miran sobre
    el texto CRUDO antes de normalizar. Sin esto '¿para qué?' pierde el '?'.
    """
    raw = text or ''
    if '?' in raw or '¿' in raw:
        return True
    n = normalize(raw)
    return bool(n) and _has_any(n, _QUESTION_LEMMAS)


# Queja o meta-pregunta SOBRE la conversación (no sobre la clínica). Es el
# peor momento posible para anteponer un aviso automático: en la conv 13 el
# aviso de fuera de horario cayó justo aquí y provocó el mensaje siguiente
# ("no te pedí ningún horario"). Subconjunto deliberadamente ESTRECHO de
# `_QUESTION_LEMMAS`: "¿cuánto cuesta?" también es pregunta y ahí el aviso
# sí es pertinente — lo que se detecta es el reclamo, no la curiosidad.
_COMPLAINT_META_LEMMAS = (
    'que dije', 'que te dije', 'no te acuerdas', 'ya te dije',
    'se te borro', 'que miras', 'no acabamos de', 'no me acabas de',
    'no te entiendo', 'no me entiendes', 'no me estas entendiendo',
    'no te pedi', 'no pedi', 'no pregunte', 'no te pregunte',
    'ya te habia dicho', 'te lo dije', 'otra vez lo mismo',
    'me estas repitiendo', 'estas repitiendo', 'ya me lo preguntaste',
    'por que preguntas otra vez', 'perdiste el contexto',
    'se perdio el contexto', 'no me estas ayudando', 'no sirves',
    'que mal servicio', 'esto no funciona', 'no funciona esto',
)


def is_complaint_or_meta(text):
    """¿El cliente está reclamando o hablando DE la conversación?

    Señal de "mal momento para automatismos", no de intención. Su único
    consumidor hoy es el aviso de fuera de horario (`_after_hours_prefix`).
    """
    n = normalize(text)
    return bool(n) and _has_any(n, _COMPLAINT_META_LEMMAS)


# `_ANSWER_SHAPES` / `is_answer_shaped` y `classify_client_triage` vivían aquí
# (É-F5 Fase 2). El primero contestaba "¿este mensaje responde la etapa que yo
# esperaba?" para una FSM que ya no existe, y solo conocía UNA forma —cuatro
# dígitos—: en las otras cuatro etapas, cualquier mensaje con "?" contaba como
# interrupción. Era el falso dilema que C6 prohíbe: un mensaje puede ser
# respuesta Y pregunta a la vez.
