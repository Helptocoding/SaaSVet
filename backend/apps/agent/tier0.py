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
    "\n\nAhorita estamos fuera de horario — deja tu mensaje y el equipo te "
    "responde al abrir 🙌"
)

# INT-00 borde · agente/buzón apagado (AgentSettings.enabled=False).
T0_DISABLED = (
    "¡Hola! Gracias por escribir a *{clinic}*. El equipo de recepción te "
    "responderá en cuanto esté disponible 🙌"
)

# Claves válidas del JSON business_hours (AgentSettings): lun..dom con
# listas de rangos [apertura, cierre] en HH:MM local de la org.
#   {"mon": [["09:00", "19:00"]], "sat": [["09:00", "14:00"]], "sun": []}
_WEEKDAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')


def is_open_now(business_hours, tz_name, now=None):
    """¿La clínica está abierta ahora, en SU zona horaria?

    Devuelve None si el horario no está configurado (dict vacío/ilegible):
    el caller trata "sin configurar" como "no anteponer aviso de cierre" —
    jamás se inventa un horario (regla G1).
    """
    if not business_hours or not isinstance(business_hours, dict):
        return None
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        return None
    local_now = (now or datetime.now(tz)).astimezone(tz)
    ranges = business_hours.get(_WEEKDAYS[local_now.weekday()], [])
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


def render_first_reply(agent_settings, organization, now=None):
    """Texto de la PRIMERA respuesta automática de una conversación (F0).

    - Buzón apagado (o sin provisionar) → T0-DISABLED.
    - Encendido → T0-GREET, con sufijo de fuera-de-horario si el horario
      está configurado y estamos cerrados.
    """
    clinic = organization.name
    if agent_settings is None or not agent_settings.enabled:
        return T0_DISABLED.format(clinic=clinic)

    text = T0_GREET.format(clinic=clinic)
    open_now = is_open_now(
        agent_settings.business_hours, organization.timezone, now=now,
    )
    if open_now is False:
        text += T0_AFTER_HOURS_SUFFIX
    return text
