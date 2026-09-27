"""
agent/metrics.py — Métricas de NEGOCIO del piloto F2 (spec §8, epics §8).

F2 es una funcionalidad comercial: además de latencia/costo/errores, mide si
el agente cumple su objetivo real (agendar). Todo se deriva de tablas que YA
existen en el subsistema (`ToolExecution`, `Conversation`, `HumanHandoff`) —
NUNCA se escribe en `analytics` (contrato propio, boundary arquitectura §12.3).

v1 computa on-the-fly (volumen bajo del piloto). Materializar `AgentDailyUsage`
solo cuando la agregación duela o al cobrar el add-on (deferido, plan v1.1 §C8).
"""
from collections import Counter

from django.db.models import Count

from .models import Conversation, ConversationGoal, HumanHandoff, ToolExecution

# Ejecuciones que cuentan como "intención de agendar" (T9 ofertó horarios o
# hubo un intento de crear/registrar — la lectura de la mascota al proponer ya
# deja fila `create_appointment`).
_INTENT_TOOLS = (
    'find_available_slots', 'create_appointment', 'register_new_client_and_pet',
)
_CREATE_TOOLS = ('create_appointment', 'register_new_client_and_pet')


def _percentile(values, pct):
    """Percentil sin numpy (muestras del piloto: decenas, no millones)."""
    if not values:
        return None
    ordered = sorted(values)
    index = min(int(round((pct / 100) * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[index]


def compute_quality_metrics(organization, date_from, date_to):
    """Calidad CONVERSACIONAL (É-F3 W3).

    Las métricas de negocio responden "¿agendó?". Estas responden la pregunta
    que de verdad decide el piloto: **"¿se siente como una buena
    recepcionista?"** — y la responden con datos, no con opinión.

    Todo se deriva de tablas existentes; cero campos nuevos.
    """
    from apps.channels.models import Message

    rows = list(
        Message.objects.for_organization(organization)
        .filter(created_at__gte=date_from, created_at__lt=date_to)
        .values('conversation_id', 'direction', 'author_type',
                'payload_type', 'status', 'created_at')
        .order_by('conversation_id', 'created_at', 'id')
    )

    entrantes = [r for r in rows if r['direction'] == 'in']
    tipos = Counter(r['payload_type'] for r in entrantes)
    total_in = sum(tipos.values())

    # Latencia de respuesta: desde el ÚLTIMO entrante del cliente hasta que el
    # agente encola su respuesta. Se mide desde el último a propósito: la
    # ventana silenciosa del debounce (W1-4) es espera deseada, no lentitud.
    #
    # Cuenta `agent` Y `system`: desde Fase 2 (§2.1) las plantillas tier-0 se
    # marcan como `system` para que el modelo no las lea como suyas — pero
    # para el CLIENTE siguen siendo la respuesta que recibió, y son las más
    # rápidas. Filtrar por `agent` a secas dejaría fuera justo esas y el p95
    # se vería peor de lo que es.
    latencias = []
    last_inbound = {}
    for row in rows:
        conv = row['conversation_id']
        if row['direction'] == 'in':
            if row['status'] != 'discarded':
                last_inbound[conv] = row['created_at']
        elif (row['author_type'] in ('agent', 'system')
                and row['status'] != 'discarded'
                and conv in last_inbound):
            delta = (row['created_at'] - last_inbound.pop(conv))
            latencias.append(int(delta.total_seconds() * 1000))

    # Turnos por resolución: mensajes del cliente en conversaciones cuyo
    # objetivo terminó completado. Menos turnos = menos fricción.
    completados = ConversationGoal.objects.filter(
        organization=organization,
        status=ConversationGoal.STATUS_COMPLETED,
        closed_at__gte=date_from, closed_at__lt=date_to,
    ).values_list('conversation_id', flat=True)
    por_conversacion = Counter(
        r['conversation_id'] for r in entrantes
        if r['conversation_id'] in set(completados)
    )
    turnos = list(por_conversacion.values())

    # Repregunta: objetivos donde hubo que pedir el MISMO dato ≥2 veces. Es el
    # tic más reconociblemente robótico que existe.
    abiertos = ConversationGoal.objects.filter(
        organization=organization,
        created_at__gte=date_from, created_at__lt=date_to,
    ).values_list('asked', flat=True)
    abiertos = list(abiertos)
    repreguntados = sum(
        1 for asked in abiertos
        if any(n >= 2 for n in (asked or {}).values())
    )

    conversaciones = Conversation.objects.filter(
        organization=organization,
        created_at__gte=date_from, created_at__lt=date_to,
    ).count()
    con_handoff = HumanHandoff.objects.filter(
        organization=organization,
        created_at__gte=date_from, created_at__lt=date_to,
    ).values('conversation_id').distinct().count()

    descartadas = sum(
        1 for r in rows
        if r['direction'] == 'out' and r['status'] == 'discarded'
    )

    return {
        'latencia_respuesta_ms': {
            'p50': _percentile(latencias, 50),
            'p95': _percentile(latencias, 95),
            'muestras': len(latencias),
        },
        'turnos_por_resolucion': {
            'promedio': (round(sum(turnos) / len(turnos), 2)
                         if turnos else None),
            'p95': _percentile(turnos, 95),
            'muestras': len(turnos),
        },
        'tasa_repregunta': (round(repreguntados / len(abiertos), 4)
                            if abiertos else 0.0),
        'tasa_handoff': (round(con_handoff / conversaciones, 4)
                         if conversaciones else 0.0),
        'entrantes_por_tipo': dict(tipos),
        # Gate de UX-14: >15 % de audio activa el requisito de transcripción.
        'pct_audio': (round(tipos.get('audio', 0) / total_in, 4)
                      if total_in else 0.0),
        'respuestas_descartadas': descartadas,
    }


def compute_conversation_metrics(organization, date_from, date_to):
    """Métrica de CONVERSACIÓN, no de software (É-F5 §9bis).

    Lo que se medía hasta aquí —handoffs, tools, costo, latencia— describe el
    motor. Ninguna de esas cifras se habría movido si el agente hubiera
    atendido bien la conversación del brief, y ninguna se mueve si la atiende
    mal con las mismas llamadas.

    Todo se deriva de tablas existentes; **cero campos nuevos**.

    Dos advertencias de método que cambian lo que significan estos números:

    - **`palabras_por_mensaje` mira SOLO `author_type='agent'`.** A medida que
      las fases retiran plantillas, un promedio sobre todos los salientes se
      movería por composición y no por deriva — la métrica cambiaría de
      significado a mitad del plan, que es justo el defecto de
      `tasa_repregunta`.
    - **`pct_redactado_por_agente` no puede llegar al 100 %** y no es un
      objetivo: hay clases de mensajes cuya literalidad *es* una garantía del
      sistema (urgencia, opt-out, handoff). El techo depende de la mezcla de
      tráfico — una semana con más urgencias lo baja, y eso es correcto.
    """
    from apps.channels.models import Message

    from .models import TurnDecision

    salientes = list(
        Message.objects.for_organization(organization)
        .filter(direction=Message.DIRECTION_OUT,
                created_at__gte=date_from, created_at__lt=date_to)
        .exclude(status=Message.STATUS_DISCARDED)
        .values('conversation_id', 'author_type', 'body', 'created_at', 'id')
        .order_by('conversation_id', 'created_at', 'id')
    )

    del_agente = [m for m in salientes if m['author_type'] == 'agent']
    automaticos = [m for m in salientes if m['author_type'] in ('agent', 'system')]

    palabras = [len((m['body'] or '').split()) for m in del_agente]

    # Salientes consecutivos IDÉNTICOS dentro de una misma conversación:
    # proxy exacto de «turno que no aportó nada» (§9bis.2). Hoy es 100 %
    # fiable porque los repetidos son plantillas literales.
    repetidos, previo_conv, previo_body = 0, None, None
    for message in automaticos:
        cuerpo = (message['body'] or '').strip()
        if message['conversation_id'] == previo_conv and cuerpo == previo_body:
            repetidos += 1
        previo_conv, previo_body = message['conversation_id'], cuerpo

    decisiones = TurnDecision.objects.filter(
        organization=organization,
        created_at__gte=date_from, created_at__lt=date_to,
    )
    turnos = decisiones.count()
    sin_modelo = decisiones.filter(planner_used=False).count()

    # Interrupciones recuperadas: un compromiso con dirección de retorno
    # (`return_to`, obligatorio al desviar desde p55) que además se completó.
    # `resume()` NO borra `return_to`, así que la evidencia sobrevive.
    from .models import ConversationGoal
    desviados = ConversationGoal.objects.filter(
        organization=organization,
        created_at__gte=date_from, created_at__lt=date_to,
    ).exclude(return_to='')
    desviados_total = desviados.count()
    desviados_ok = desviados.filter(
        status=ConversationGoal.STATUS_COMPLETED).count()

    return {
        # Métrica insignia de É-F5. NO es un objetivo a maximizar.
        'pct_redactado_por_agente': (
            round(len(del_agente) / len(automaticos), 4) if automaticos else 0.0),
        'palabras_por_mensaje_agente': {
            'p50': _percentile(palabras, 50),
            'p90': _percentile(palabras, 90),
            'muestras': len(palabras),
        },
        'pct_turnos_sin_modelo': (
            round(sin_modelo / turnos, 4) if turnos else 0.0),
        'salientes_repetidos': repetidos,
        'interrupciones_recuperadas': {
            'total': desviados_total,
            'recuperadas': desviados_ok,
            'tasa': (round(desviados_ok / desviados_total, 4)
                     if desviados_total else 0.0),
        },
        # Honestidad deliberada: «cambios de tema exitosos» NO es derivable
        # hoy. `goals.resume()` limpia `supplanted_by`, así que la evidencia de
        # que un compromiso fue suplantado desaparece al retomarlo. Antes que
        # inventar un proxy malo, se declara ausente — necesitaría un campo
        # nuevo y eso es otro sprint.
        'cambios_de_tema_exitosos': None,
    }


def compute_goal_metrics(organization, date_from, date_to):
    """Embudo por OBJETIVO y por SLOT (É-F3 W2).

    Hasta W2 el embudo se infería de nombres de herramienta porque no existía
    el objeto que representa la intención. Ahora se mide lo que de verdad
    pasó: cuántos objetivos se abrieron, cuántos se cerraron bien, y — lo más
    accionable — **en qué dato se atoran** los que no llegan.
    """
    goals = ConversationGoal.objects.filter(
        organization=organization,
        created_at__gte=date_from, created_at__lt=date_to,
    )
    por_estado = {
        status: n for status, n in
        goals.values_list('status').annotate(n=Count('id'))
    }
    por_objetivo = {
        name: n for name, n in
        goals.values_list('name').annotate(n=Count('id'))
    }
    total = sum(por_estado.values())
    completados = por_estado.get(ConversationGoal.STATUS_COMPLETED, 0)

    # Dónde se quedan los que no se completan: el slot que faltaba al cerrar.
    atorados = Counter()
    for missing in goals.exclude(
        status=ConversationGoal.STATUS_COMPLETED,
    ).values_list('missing', flat=True):
        for slot in (missing or []):
            atorados[slot] += 1

    return {
        'abiertos': total,
        'completados': completados,
        'tasa_completado': round(completados / total, 4) if total else 0.0,
        'por_estado': por_estado,
        'por_objetivo': por_objetivo,
        'slots_atorados': dict(atorados.most_common(5)),
    }


def compute_llm_usage(organization, *, turn_work_id=None):
    """B9 COST component evidence, tenant scoped; unknown totals stay unknown.

    No profile gate or economic estimate. Known subtotals never stand in for
    complete usage, and legacy rows do not masquerade as admitted B9 calls.
    """
    from .models import LLMCall
    calls = LLMCall.objects.filter(organization=organization)
    if turn_work_id is not None:
        calls = calls.filter(turn_work_id=turn_work_id)
    rows = list(calls.values('purpose', 'admission_id', 'recorded_at', 'input_tokens',
                            'output_tokens', 'retry_of_id', 'error'))
    unknown = sum(r['recorded_at'] is None or r['input_tokens'] is None or
                  r['output_tokens'] is None for r in rows)
    input_known = sum(r['input_tokens'] or 0 for r in rows if r['recorded_at'] is not None)
    output_known = sum(r['output_tokens'] or 0 for r in rows if r['recorded_at'] is not None)
    from .llm_budget import PURPOSES
    return {'calls': len(rows), 'admitted_calls': sum(r['admission_id'] is not None for r in rows),
        'roles': {role: sum(r['purpose'] == role for r in rows) for role in PURPOSES},
        'retries': sum(r['retry_of_id'] is not None for r in rows),
        'provider_failures': sum(bool(r['error']) for r in rows),
        'unknown_usage_calls': unknown, 'known_input_tokens': input_known,
        'known_output_tokens': output_known,
        'input_tokens': None if unknown else input_known,
        'output_tokens': None if unknown else output_known,
        'cost_estimate': None, 'profile_beta_1': 'PENDING'}


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
        'objetivos': compute_goal_metrics(organization, date_from, date_to),
        'calidad': compute_quality_metrics(organization, date_from, date_to),
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
