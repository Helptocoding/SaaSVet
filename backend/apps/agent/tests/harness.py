"""
harness.py — Motor de la suite de regresión conversacional (É-F1 PR-13).

Conduce un turno completo (entrante → policy/planner → salientes) con un
StubLLMClient determinista y aplica las ASERCIONES PROHIBIDAS GLOBALES de la
spec §9.2 a CADA saliente: ningún mensaje del agente puede contener UUIDs/
PKs, cifras de stock, consejo médico, jerga interna, ni datos de otro tenant.

Filosofía (spec §1.3/§9.1): plantillas tier-0 = igualdad literal; texto del
LLM = elementos obligatorios/prohibidos, jamás igualdad. Tools y efectos de
dominio = exactos. La suite CI corre contra el stub (bloqueante); el eval
con LLM real es nightly (comando agent_eval).
"""
from rest_framework.test import APIClient

from apps.agent import guards, planner
from apps.agent.executor import ToolExecutor
from apps.channels.models import Message

_UUID_RE = guards.UUID_RE

# Fuente única: las listas vinculantes viven en `guards.py` y corren en
# PRODUCCIÓN (É-F3 W1-1). Aquí solo se añade severidad extra de test —
# patrones demasiado ambiguos para bloquear en vivo pero útiles para detectar
# derivas de tono en la suite ('dale ' es un sí mexicano, no una posología).
FORBIDDEN_JARGON = guards.FORBIDDEN_JARGON + ('conversation',)
FORBIDDEN_MEDICAL = guards.MEDICAL_ADVICE_PATTERNS + ('dale ', 'administra ')


def set_schedule_day(organization, weekday_index, opens="09:00",
                     closes="13:00"):
    """Fija el horario de UN día (0=lunes) en la fuente única (ADR p53).

    El alta de organización siembra 7 filas por defecto; los tests que dependen
    de un horario concreto lo sobreescriben aquí. Sustituye al difunto
    `AgentSettings.business_hours`, que era una segunda fuente de verdad.
    """
    from apps.organizations.models import OrganizationSchedule
    OrganizationSchedule.objects.update_or_create(
        organization=organization, weekday=weekday_index + 1,
        defaults={'opens_at': opens, 'closes_at': closes, 'is_closed': False,
                  'has_break': False, 'break_start': None, 'break_end': None},
    )


def identity_commitment(conversation, *, parked=False):
    """El reto de identidad AL FRENTE (o el apartado, con `parked=True`).

    Desde É-F4 Fase 3 (R7) los retos son compromisos, no dicts en
    `Conversation.flow`. Los tests preguntan por su etapa a través de aquí
    para no volver a acoplarse al contenedor.
    """
    from apps.agent import goals
    from apps.agent.models import ConversationGoal
    statuses = ((ConversationGoal.STATUS_SUSPENDED,) if parked
                else ConversationGoal.FOREGROUND_STATUSES)
    return ConversationGoal.objects.filter(
        conversation=conversation, name__in=goals.IDENTITY_GOALS,
        status__in=statuses,
    ).first()


def close_all_days(organization):
    """Clínica cerrada toda la semana (para probar el aviso de fuera de horario)."""
    from apps.organizations.models import OrganizationSchedule
    OrganizationSchedule.objects.filter(
        organization=organization).update(is_closed=True)


class RealApiTransport:
    """Loopback por el Django test client con el JWT del AGENT (API+RBAC reales).

    Reenvía el body `json` en escrituras (POST/PATCH, F2) y `params` en lecturas
    (GET, F1). Los headers extra (X-Idempotency-Key, X-Request-ID) van como META
    para que el loopback se comporte como en producción."""

    def __call__(self, method, path, *, headers, params=None, json=None):
        client = APIClient()
        extra = {}
        for key, value in (headers or {}).items():
            if key.lower() == 'authorization':
                extra['HTTP_AUTHORIZATION'] = value
            else:
                extra['HTTP_' + key.upper().replace('-', '_')] = value
        if json is not None:
            response = getattr(client, method.lower())(
                path, data=json, format='json', **extra)
        else:
            response = getattr(client, method.lower())(
                path, data=params or {}, **extra)
        try:
            payload = response.json() if response.content else {}
        except ValueError:
            payload = {}
        return response.status_code, payload


def assert_no_forbidden(testcase, text, *, decoy_terms=()):
    """Aserciones prohibidas globales sobre UN saliente."""
    low = (text or '').lower()
    testcase.assertIsNone(_UUID_RE.search(text or ''),
                          f"UUID filtrado: {text}")
    for jargon in FORBIDDEN_JARGON:
        testcase.assertNotIn(jargon, low, f"jerga '{jargon}' en: {text}")
    for term in decoy_terms:
        testcase.assertNotIn(term.lower(), low,
                             f"FUGA CROSS-TENANT '{term}' en: {text}")


def run_turn(testcase, conversation, agent_user, text, *, scripted_llm,
             decoy_terms=(), assert_clean=True):
    """Persiste el entrante, corre el pipeline y devuelve la lista de cuerpos
    salientes producidos en el turno (en orden). Aplica las aserciones
    prohibidas a cada saliente si assert_clean."""
    from apps.agent.llm import StubLLMClient
    from apps.agent.models import AgentSettings, TurnDecision

    before_ids = set(
        Message.objects.filter(
            conversation=conversation, direction=Message.DIRECTION_OUT,
        ).values_list('id', flat=True)
    )
    turn_decisions_before = TurnDecision.objects.filter(
        conversation=conversation).count()

    Message.objects.create(
        organization=conversation.organization,
        channel_account=conversation.channel_account,
        conversation=conversation, direction=Message.DIRECTION_IN,
        author_type=Message.AUTHOR_CLIENT, body=text,
        status=Message.STATUS_PROCESSED,
    )

    agent_settings = AgentSettings.objects.filter(
        organization=conversation.organization,
    ).first()
    stub = StubLLMClient(scripted=scripted_llm)
    executor = ToolExecutor(conversation, agent_user,
                            transport=RealApiTransport())
    result = planner.handle_inbound(
        conversation, agent_settings=agent_settings,
        llm_client=stub, executor=executor,
    )

    # Exhaustividad de TurnDecision, Capa 2 (§9.2 del plan de gobernanza):
    # todo turno del harness compartido deja EXACTAMENTE una fila, incluidos
    # los que responden SILENT (no mandan mensaje pero sí deciden algo).
    testcase.assertEqual(
        TurnDecision.objects.filter(conversation=conversation).count(),
        turn_decisions_before + 1,
        "cada turno debe dejar exactamente 1 TurnDecision (R12)",
    )

    new_outbound = list(
        Message.objects.filter(
            conversation=conversation, direction=Message.DIRECTION_OUT,
        ).exclude(id__in=before_ids).order_by('id')
    )
    bodies = [m.body for m in new_outbound]
    if assert_clean:
        for body in bodies:
            assert_no_forbidden(testcase, body, decoy_terms=decoy_terms)
    return bodies, result, stub
