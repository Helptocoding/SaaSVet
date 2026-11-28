"""
agent/tier0.py — Plantillas tier-0 y horario de atención (É-F0 PR-5).

Las plantillas tier-0 son LITERALES (contrato de la spec funcional §1.3:
test por igualdad; el LLM no participa). Copy aprobado 2026-07-15:
saludo institucional SIN nombre propio (decisión §2.1 de la spec) y sin
links (el aviso de privacidad es just-in-time, llega con F1).

WhatsApp renderiza *negritas* con asteriscos simples.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

# INT-00 · T0-GREET — elementos obligatorios: bienvenida + nombre de la
# clínica + oferta de ayuda + pregunta abierta. Sin menú, sin links.
T0_GREET = (
    "¡Hola! 🐾 Bienvenido a *{clinic}*. Estoy aquí para ayudarte con citas "
    "y cualquier duda. ¿En qué te puedo apoyar?"
)

# INT-03 · sufijo fuera de horario (modificador, una vez por conversación).
T0_AFTER_HOURS_SUFFIX = (
    "\n\nEstamos fuera de horario. Puedes dejar tu mensaje para revisión; "
    "no puedo confirmar cuándo estará disponible una persona."
)

# INT-00 borde · agente/buzón apagado (AgentSettings.enabled=False).
T0_DISABLED = (
    "¡Hola! Gracias por escribir a *{clinic}*. La atención automática está "
    "en pausa. Tu mensaje queda registrado para revisión."
)

# Forma del horario que produce `clinic_context.effective_business_hours`:
# lun..dom con listas de rangos [apertura, cierre] en HH:MM local de la org.
#   {"mon": [["09:00", "19:00"]], "sat": [["09:00", "14:00"]], "sun": []}
_WEEKDAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')


def is_open_now(hours, tz_name, now=None):
    """¿La clínica está abierta ahora, en SU zona horaria?

    `hours` viene de `clinic_context.effective_business_hours`. Devuelve None
    si el horario no está configurado (dict vacío/ilegible): el caller trata
    "sin configurar" como "no anteponer aviso de cierre" — jamás se inventa un
    horario (regla G1). Ojo: "configurado pero cerrado todos los días" NO es lo
    mismo — ahí devuelve False y el aviso sí se emite.
    """
    if not hours or not isinstance(hours, dict):
        return None
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        return None
    local_now = (now or datetime.now(tz)).astimezone(tz)
    ranges = hours.get(_WEEKDAYS[local_now.weekday()], [])
    if not isinstance(ranges, list):
        return None
    current = local_now.strftime('%H:%M')
    for item in ranges:
        try:
            start, end = item[0], item[1]
        except (TypeError, IndexError, KeyError):
            continue
        if start <= current < end:
            return True
    return False


# --- Plantillas F1 (LITERALES, spec §1.3; el LLM no participa) -------------

# INT-01 · contención B0: buscar atención; no afirmar aviso ni cobertura.
# JAMÁS evalúa el cuadro (G2). {phone} = `Organization.phone` (ADR p53).
T0_EMERGENCY = (
    "Esto puede ser una emergencia 🚨 Busca atención "
    "veterinaria presencial disponible y no esperes una respuesta por este "
    "chat. También puedes intentar llamar a la clínica{phone}; no puedo confirmar "
    "su disponibilidad ni que una persona haya recibido un aviso."
)
T0_EMERGENCY_NO_PHONE = (
    "Esto puede ser una emergencia 🚨 Busca atención "
    "veterinaria presencial disponible y no esperes una respuesta por este "
    "chat. No puedo confirmar que una persona haya recibido un aviso."
)

# INT-02 · handoff explícito.
T0_HANDOFF = (
    "Tu solicitud de atención humana queda registrada para revisión. "
    "Todavía no puedo confirmar que una persona haya tomado el caso."
)
T0_HANDOFF_AFTER_HOURS = (
    "Tu solicitud queda registrada. Estamos fuera de horario; no puedo "
    "confirmar cuándo estará disponible una persona."
)

# INT-06 · "¿eres una persona?".
T0_BOTQ = (
    "Soy el asistente virtual de la clínica. Puedo ayudarte con consultas "
    "administrativas y registrar una solicitud de atención humana. Los "
    "cambios de citas y registros requieren atención del equipo."
)

# UX-01 · aviso de privacidad just-in-time (antes de la 1ª recolección de datos).
T0_PRIVACY = (
    "Antes de continuar: tus datos se tratan conforme al aviso de privacidad "
    "de la clínica{link}."
)

# E-09 · presupuesto de conversación agotado.
T0_BUDGET = (
    "No puedo continuar esta consulta automáticamente. Queda pendiente de "
    "atención humana."
)

# W1-5 · el cliente escribe cuando ya hay una escalada en cola. Un acuse, una
# sola vez: ni seguir conversando como si nada (le prometimos una persona) ni
# silencio absoluto (parece que nadie lo leyó).
T0_HANDOFF_WAITING = (
    "Tu solicitud sigue pendiente de atención humana. No puedo confirmar "
    "que una persona haya tomado el caso."
)

# Anti-eco de identidad (plan de continuidad, D33): el nombre con el que el
# cliente intentó identificarse lo había dicho el sistema o el staff ANTES que
# él, así que no prueba que sea quien dice ser.
#
# GENÉRICO A PROPÓSITO: no repite el nombre ni insinúa que el cliente falló.
# Confirmarlo sería la misma fuga que este camino existe para cerrar. Y no se le
# pide otra vez: repetirlo seguiría siendo eco hasta que caduque la ventana, así
# que la salida es una persona, no otro intento.
T0_IDENTITY_ECHO = (
    "Por seguridad, prefiero que recepción continúe contigo con la "
    "verificación. La solicitud queda pendiente de atención humana."
)

# La pregunta del reto de identidad la pone el SISTEMA (D38), no el modelo. Sin
# esto, el modelo podía preguntar por los últimos 4 dígitos y ese saliente
# quedaba sellado como si fuera la pregunta por la mascota — y una respuesta
# «Luna» recibía el régimen tolerante sobre una pregunta que nunca se hizo.
# Mismo patrón que el aviso de privacidad: el modelo redacta, el sistema añade
# la parte que sostiene una garantía.
T0_IDENTITY_QUESTION = (
    "\n\nPara verificarte antes de consultar esos datos, ¿cómo se llama tu "
    "mascota?"
)

# W1-1 · el guard de salida bloqueó el texto generado. El cliente nunca ve el
# motivo técnico: ve a alguien que prefiere que lo atienda una persona.
T0_GUARD_BLOCKED = (
    "Mejor que esto te lo confirme una persona del equipo — no quiero darte "
    "un dato equivocado. La solicitud queda pendiente de atención humana."
)

# Problema técnico real (LLM caído, tool en 5xx). Antes se reusaba T0_BUDGET,
# que habla de "mejor atención" para un fallo de infraestructura.
T0_TECH_PROBLEM = (
    "No pude completar la consulta por un problema técnico. La solicitud "
    "queda pendiente de atención humana."
)

# W2 · el objetivo lleva 3 turnos sin avanzar un solo dato. No es un fallo
# técnico ni un límite contable: la conversación no está llegando a ningún
# lado y una persona la resuelve mejor.
T0_GOAL_STALLED = (
    "No he podido resolver tu solicitud por aquí. Queda pendiente de "
    "atención humana."
)

T0_WRITE_PAUSED = (
    "Los cambios de citas y registros requieren atención del equipo. "
    "No he realizado ningún cambio; tu solicitud queda pendiente de "
    "atención humana."
)

T0_CLINICAL_LIMIT = (
    "Por este chat no puedo diagnosticar, indicar tratamientos ni valorar "
    "la gravedad. Solicita una evaluación veterinaria. Tu consulta queda "
    "pendiente de atención humana; si necesitas atención urgente, busca "
    "atención presencial disponible sin esperar respuesta por aquí."
)

# ---------------------------------------------------------------------------
# Conveniencias — RETIRADAS (É-F5 Fase 5)
# ---------------------------------------------------------------------------
# Aquí vivían T0_MEDIA_AUDIO, T0_MEDIA_OTHER, render_media_reply, T0_OUT_PAYMENT
# y T0_OUT_MEDICAL. Ninguna protegía nada: contestaban con una constante y
# cerraban el turno sin que el modelo leyera el mensaje.
#
# El caso que mejor las retrata es el de media. "No alcanzo a ver lo que me
# mandaste" es correcto y es inútil: no sabe que veníamos hablando de la receta
# de Luna. El modelo, con el mismo hecho y el historial, puede decir algo que
# de verdad continúe la conversación. La plantilla no era una garantía; era una
# respuesta que no podía mejorar.
#
# Los pagos merecen su nota, porque el límite parecía vivir aquí y no vivía
# aquí: lo sostiene que NO EXISTA ninguna herramienta de cobro. Ninguna frase
# que el modelo escriba puede mover dinero.

# UX-16 · falsa afirmativa a un pending_action (no ejecuta, no cierra).
T0_DEFER = "Va, aquí queda pendiente — me dices 🙌"


# Una afirmativa solo puede ejecutar una propuesta que el cliente sí recibió.
# Evita convertir un “sí” a una promesa libre del modelo en una segunda ronda.
T0_CONFIRMATION_UNAVAILABLE = (
    "No tengo un resumen de cita listo para confirmar. Dime qué necesitas "
    "hacer y te muestro la propuesta real primero."
)

# ---------------------------------------------------------------------------
# Reto de identidad (G4: nunca enumera).
# Plantillas de identidad — RETIRADAS (É-F5 Fase 2, ADR p56)
# ---------------------------------------------------------------------------
# Aquí vivían las 13 plantillas que conducían los retos: T0_CHALLENGE_*,
# T0_TRIAGE_*, T0_FAMILY_LINK_START, render_triage… y `T0_WHY_THEN_REASK`.
#
# Esa última merece el epitafio, porque es el argumento entero de É-F5 en una
# línea de código:
#
#     T0_WHY_THEN_REASK = "Te lo pido para {why} 🙂" + salto + "{reask}"
#
# Con `why=''` producía literalmente «Te lo pido para  🙂» — dos espacios y un
# emoji— y salió así DOS VECES seguidas en producción. Ningún test lo vio:
# **una plantilla es un `format()` que no puede fallar visiblemente.** Un hecho
# ausente en un bloque de estado es diagnosticable; un hueco de formato vacío,
# no. Ahora el porqué de cada factor viaja como HECHO publicado y lo redacta
# quien está leyendo al cliente.


# `T0_THANKS` se retiró en la Fase 5 junto con el resto de conveniencias: un
# "gracias" es una de las mejores oportunidades de sonar humano y era
# exactamente donde el sistema contestaba con una constante.


def render_safety_guidance(assessment):
    """Finite B5 copy; pending veterinary review. No generated clinical text."""
    media = ('No puedo interpretar la imagen o el audio; me baso solo en el texto. '
             if assessment.media_uninterpreted else '')
    return (media + 'Por lo que describes, busca atención veterinaria inmediata en un '
            'servicio disponible. WhatsApp no sustituye la atención veterinaria; '
            'no esperes una respuesta de este chat para buscar ayuda. '
            'He marcado esta conversación para revisión del equipo en su bandeja. '
            'No puedo confirmar que una persona la haya visto o tomado.')


def render_emergency(agent_settings, organization):
    """Plantilla de urgencia con el teléfono de la clínica.

    El teléfono sale de la configuración de clínica (`Organization.phone`,
    ADR p53). Antes miraba únicamente `faq_facts`, así que una clínica con sus
    datos en Configuración recibía el mensaje de emergencia **sin número al que
    llamar** — en la plantilla de mayor riesgo del sistema.
    """
    from . import clinic_context
    phone = clinic_context.clinic_phone(organization, agent_settings)
    if phone:
        return T0_EMERGENCY.format(phone=f" al {phone}")
    return T0_EMERGENCY_NO_PHONE


def render_privacy(agent_settings):
    facts = (agent_settings.faq_facts or {}) if agent_settings else {}
    link = facts.get('aviso_privacidad') or facts.get('privacidad')
    return T0_PRIVACY.format(link=f" ({link})" if link else "")


def render_first_reply(agent_settings, organization, now=None):
    """Texto de la PRIMERA respuesta automática de una conversación (F0).

    - Buzón apagado (o sin provisionar) → T0-DISABLED.
    - Encendido → T0-GREET, con sufijo de fuera-de-horario si el horario
      está configurado y estamos cerrados.
    """
    clinic = organization.public_name   # ADR p70 D5: comercial o legal
    if agent_settings is None or not agent_settings.enabled:
        return T0_DISABLED.format(clinic=clinic)

    from . import clinic_context
    text = T0_GREET.format(clinic=clinic)
    # ADR p70 D6: un cierre excepcional hoy cuenta como cerrado.
    open_now = False if clinic_context.closed_today(organization) else is_open_now(
        clinic_context.effective_business_hours(organization, agent_settings),
        organization.timezone, now=now,
    )
    if open_now is False:
        text += T0_AFTER_HOURS_SUFFIX
    return text
