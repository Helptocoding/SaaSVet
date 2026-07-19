"""
agent/metrics.py — Métricas de NEGOCIO del piloto F2 (spec §8, epics §8).

F2 es una funcionalidad comercial: además de latencia/costo/errores, mide si
el agente cumple su objetivo real (agendar). Todo se deriva de tablas que YA
existen en el subsistema (`ToolExecution`, `Conversation`, `HumanHandoff`) —
NUNCA se escribe en `analytics` (contrato propio, boundary arquitectura §12.3).

v1 computa on-the-fly (volumen bajo del piloto). Materializar `AgentDailyUsage`
solo cuando la agregación duela o al cobrar el add-on (deferido, plan v1.1 §C8).
"""
from django.db.models import Count

from .models import Conversation, HumanHandoff, ToolExecution

# Ejecuciones que cuentan como "intención de agendar" (T9 ofertó horarios o
# hubo un intento de crear/registrar — la lectura de la mascota al proponer ya
# deja fila `create_appointment`).
_INTENT_TOOLS = (
    'find_available_slots', 'create_appointment', 'register_new_client_and_pet',
)
_CREATE_TOOLS = ('create_appointment', 'register_new_client_and_pet')


def compute_business_metrics(organization, date_from, date_to):
    """KPIs comerciales del periodo [date_from, date_to). Read-only, org-scoped.
    `citas_creadas`/`cancelaciones` = ejecuciones CONFIRMADAS (el commit tras el
    "sí"), no las propuestas — así el número coincide con las citas reales."""
    convs = Conversation.objects.filter(
        organization=organization,
        created_at__gte=date_from, created_at__lt=date_to,
    )
    conversaciones = convs.count()

    tx = ToolExecution.objects.filter(
        organization=organization,
        created_at__gte=date_from, created_at__lt=date_to,
    )

    intent_conv_ids = set(
        tx.filter(tool_name__in=_INTENT_TOOLS)
        .values_list('conversation_id', flat=True)
    )
    con_intencion = len(intent_conv_ids)

    created_tx = tx.filter(
        tool_name__in=_CREATE_TOOLS,
        policy_decision=ToolExecution.DECISION_CONFIRMED,
        http_status__lt=400,
    )
    citas_creadas = created_tx.count()
    created_conv_ids = set(created_tx.values_list('conversation_id', flat=True))

    slots_ofertados = (
        tx.filter(tool_name='find_available_slots', http_status__lt=400)
        .values('conversation_id').distinct().count()
    )

    cancelaciones = tx.filter(
        tool_name='cancel_appointment',
        policy_decision=ToolExecution.DECISION_CONFIRMED,
        http_status__lt=400,
    ).count()

    handoffs = HumanHandoff.objects.filter(
        organization=organization,
        created_at__gte=date_from, created_at__lt=date_to,
    )
    handoffs_total = handoffs.count()
    handoffs_por_motivo = {
        reason: n for reason, n in
        handoffs.values_list('reason_code').annotate(n=Count('id'))
    }

    # Abandono: conversaciones con intención que NO terminaron en cita creada.
    citas_abandonadas = len(intent_conv_ids - created_conv_ids)
    tasa_conversion = (
        round(citas_creadas / con_intencion, 4) if con_intencion else 0.0
    )

    return {
        'periodo': {'from': date_from.isoformat(), 'to': date_to.isoformat()},
        'conversaciones_iniciadas': conversaciones,
        'con_intencion_agendar': con_intencion,
        'citas_creadas': citas_creadas,
        'tasa_conversion': tasa_conversion,
        'citas_abandonadas': citas_abandonadas,
        'cancelaciones': cancelaciones,
        'handoffs': {'total': handoffs_total, 'por_motivo': handoffs_por_motivo},
        'embudo': {
            'conversaciones': conversaciones,
            'con_intencion': con_intencion,
            'slots_ofertados': slots_ofertados,
            'citas_creadas': citas_creadas,
        },
    }
