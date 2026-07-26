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

# INT-01 · urgencia (R16): acudir de inmediato + teléfono + aviso al equipo.
# JAMÁS evalúa el cuadro (G2). {phone} = `Organization.phone` (ADR p53).
T0_EMERGENCY = (
    "Esto puede ser una emergencia 🚨 Acude de inmediato a la clínica o "
    "llámanos{phone}. Ya avisé al equipo para que te contacte lo antes "
    "posible."
)
T0_EMERGENCY_NO_PHONE = (
    "Esto puede ser una emergencia 🚨 Acude de inmediato a la clínica. Ya "
    "avisé al equipo para que te contacte lo antes posible."
)

# INT-02 · handoff explícito.
T0_HANDOFF = (
    "Claro, en un momento una persona del equipo continúa contigo por aquí 🙌"
)
T0_HANDOFF_AFTER_HOURS = (
    "Con gusto. Ahorita estamos fuera de horario; el equipo te responde por "
    "aquí en cuanto abramos 🙌"
)

# INT-06 · "¿eres una persona?".
T0_BOTQ = (
    "Soy el asistente virtual de la clínica 🙂 Puedo agendarte y resolver "
    "dudas al momento — y si prefieres, te comunico con una persona del equipo."
)

# UX-01 · aviso de privacidad just-in-time (antes de la 1ª recolección de datos).
T0_PRIVACY = (
    "Antes de continuar: tus datos se tratan conforme al aviso de privacidad "
    "de la clínica{link}."
)

# E-09 · presupuesto de conversación agotado.
T0_BUDGET = (
    "Para darte una mejor atención, dejo que una persona del equipo continúe "
    "contigo 🙌"
)

# W1-5 · el cliente escribe cuando ya hay una escalada en cola. Un acuse, una
# sola vez: ni seguir conversando como si nada (le prometimos una persona) ni
# silencio absoluto (parece que nadie lo leyó).
T0_HANDOFF_WAITING = (
    "Aquí sigo 🙌 Ya le pasé tu mensaje al equipo; en cuanto alguien se "
    "desocupe continúa contigo por aquí."
)

# W1-1 · el guard de salida bloqueó el texto generado. El cliente nunca ve el
# motivo técnico: ve a alguien que prefiere que lo atienda una persona.
T0_GUARD_BLOCKED = (
    "Mejor que esto te lo confirme una persona del equipo — no quiero darte "
    "un dato equivocado 🙏 Ya les avisé."
)

# Problema técnico real (LLM caído, tool en 5xx). Antes se reusaba T0_BUDGET,
# que habla de "mejor atención" para un fallo de infraestructura.
T0_TECH_PROBLEM = (
    "Uy, se me trabó el sistema tantito 😅 Ya le avisé al equipo para que te "
    "atiendan por aquí."
)

# W2 · el objetivo lleva 3 turnos sin avanzar un solo dato. No es un fallo
# técnico ni un límite contable: la conversación no está llegando a ningún
# lado y una persona la resuelve mejor.
T0_GOAL_STALLED = (
    "Creo que por aquí nos estamos enredando 🙈 Le paso tu caso a una persona "
    "del equipo para que lo resuelva contigo rapidito."
)

# GB-1 · media entrante sin transcripción. Se mide el volumen (`payload_type`)
# para decidir si toca transcribir (UX-14, umbral 15 %).
T0_MEDIA_AUDIO = (
    "Por ahora no puedo escuchar las notas de voz 🙈 ¿Me lo escribes? Así te "
    "ayudo de inmediato."
)
T0_MEDIA_OTHER = (
    "No alcanzo a ver lo que me mandaste 🙈 ¿Me lo cuentas por escrito? Así te "
    "ayudo de inmediato."
)


def render_media_reply(payload_types=None):
    """Plantilla según el tipo de adjunto (audio vs. lo demás)."""
    if payload_types and 'audio' in set(payload_types):
        return T0_MEDIA_AUDIO
    return T0_MEDIA_OTHER

# INT-05 · fuera de alcance.
T0_OUT_PAYMENT = (
    "Los pagos se realizan directamente en la clínica 🙂 Si tienes una duda "
    "de un cobro, con gusto te comunico con el equipo."
)
T0_OUT_MEDICAL = (
    "Eso mejor que lo valore el veterinario 🙏 ¿Te agendo una consulta? Y si "
    "es algo urgente, acude de inmediato a la clínica."
)

# UX-16 · falsa afirmativa a un pending_action (no ejecuta, no cierra).
T0_DEFER = "Va, aquí queda pendiente — me dices 🙌"

# Reto de identidad (G4: nunca enumera).
T0_CHALLENGE_PET = (
    "Para proteger tus datos, ¿me confirmas el nombre de tu mascota?"
)
T0_CHALLENGE_RETRY = (
    "Mmm, no me coincide. ¿Me lo repites tal como lo registraron?"
)
T0_CHALLENGE_OWNER = (
    "¿A nombre de quién está el registro?"
)
T0_CHALLENGE_FAILED = (
    "No logro validar tus datos por aquí 🙏 Te comunico con el equipo para "
    "que te apoyen."
)

# Número NO registrado que pide una acción personal (agendar / ver sus citas).
# En vez de retar por una mascota que no existe (→ rebote a humano), se ofrece
# el alta: primera vez → registro; ya visitó → puede haber usado otro número.
T0_NEW_CLIENT = (
    "¡Con gusto te ayudo! 🐾 Veo que este número aún no está registrado con "
    "nosotros. ¿Es tu primera vez en la clínica? Si es así, te doy de alta y "
    "agendamos en un momento — solo dime tu nombre y el de tu mascota."
)

T0_THANKS = "¡Con gusto! Aquí estoy si necesitas algo más 🐾"


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
    clinic = organization.name
    if agent_settings is None or not agent_settings.enabled:
        return T0_DISABLED.format(clinic=clinic)

    from . import clinic_context
    text = T0_GREET.format(clinic=clinic)
    open_now = is_open_now(
        clinic_context.effective_business_hours(organization, agent_settings),
        organization.timezone, now=now,
    )
    if open_now is False:
        text += T0_AFTER_HOURS_SUFFIX
    return text
