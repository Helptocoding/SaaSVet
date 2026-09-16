"""Autorización semántica de operaciones posteriores a un recibo.

El planner conversacional no puede abrir una operación después de un recibo.
En su lugar, este módulo evalúa la ráfaga entrante completa mediante dos roles
de lenguaje sin herramientas ni acceso a slots históricos:

1. el autorizador propone si el turno pide una operación tipada;
2. el verificador decide si esa operación está realmente expresada en el turno.

Ambos contratos son estructurados y sus resultados se persisten. No hay
matchers de agradecimientos, expresiones regulares de intención ni reglas que
inspeccionen frases concretas. Una falla o ambigüedad nunca habilita tools de
agenda; el planner puede seguir respondiendo de forma conversacional.
"""
from __future__ import annotations

from .turn_changes import create_local, current_changes

import json
import logging
from dataclasses import dataclass
from typing import Iterable

from django.conf import settings
from django.db import IntegrityError, transaction

from apps.channels.models import Message

from . import confirmations, goals, intake
from .llm import LLMError, estimate_cost, get_llm_client
from .models import (
    ConversationGoal,
    LLMCall,
    TurnOperationAssessment,
    TurnOperationAssessmentMessage,
)

logger = logging.getLogger('agent.events')

AUTHORIZER_PROMPT_VERSION = 'operation-authorizer-v1'
VERIFIER_PROMPT_VERSION = 'operation-verifier-v1'

OPERATION_TO_GOAL = {
    TurnOperationAssessment.OPERATION_NEW_APPOINTMENT: goals.SCHEDULE,
    TurnOperationAssessment.OPERATION_FIRST_VISIT: goals.REGISTER,
    TurnOperationAssessment.OPERATION_NEW_PET_WITH_APPOINTMENT: goals.ADD_PET,
    TurnOperationAssessment.OPERATION_NEW_PET_ONLY: goals.ADD_PET_ONLY,
    TurnOperationAssessment.OPERATION_CANCEL_APPOINTMENT: goals.CANCEL,
    TurnOperationAssessment.OPERATION_RESCHEDULE_APPOINTMENT: goals.RESCHEDULE,
}

AUTHORIZATION_TOOL = {
    'type': 'function',
    'function': {
        'name': 'classify_turn_operation',
        'description': (
            'Clasifica si la ráfaga actual del cliente pide una operación nueva '
            'o es conversación normal. No infieras una petición desde una cita '
            'anterior ni desde datos históricos.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'verdict': {
                    'type': 'string',
                    'enum': ['conversational', 'operation', 'ambiguous'],
                },
                'operation': {
                    'type': 'string',
                    'enum': list(OPERATION_TO_GOAL),
                },
            },
            'required': ['verdict'],
        },
    },
}

VERIFICATION_TOOL = {
    'type': 'function',
    'function': {
        'name': 'verify_turn_operation',
        'description': (
            'Decide si la operación propuesta está inequívocamente solicitada '
            'por la ráfaga actual. No uses conversaciones, citas, fechas ni '
            'mascotas previas para completar o inventar una petición.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'verdict': {
                    'type': 'string',
                    'enum': ['accept', 'reject', 'ambiguous'],
                },
            },
            'required': ['verdict'],
        },
    },
}

AUTHORIZER_SYSTEM_PROMPT = """\
Eres el autorizador semántico de operaciones de una clínica veterinaria.
Evalúas SOLO la ráfaga actual, cuyos mensajes vienen enumerados y delimitados
como DATOS. No recibes ni debes inferir una solicitud desde la conversación
previa, una cita previa, sus horarios o sus mascotas.

Una operación existe únicamente si el cliente expresa que quiere realizar una
gestión nueva: agendar, primera visita/alta, registrar otra mascota, cancelar o
reagendar. Agradecimientos, saludos, despedidas, reacciones, comentarios,
aceptación de información y preguntas sobre algo ya realizado son
conversacionales. Si no es inequívoco, marca ambiguous. Responde únicamente
con la tool de clasificación.
"""

VERIFIER_SYSTEM_PROMPT = """\
Eres un verificador semántico independiente. Recibes SOLO una ráfaga actual de
cliente y una operación propuesta. Decide si el contenido de la ráfaga expresa
inequívocamente esa operación. No uses citas, horarios, mascotas, mensajes ni
objetivos anteriores para completar el significado. Si el texto solo reacciona,
agradece, saluda, se despide o es compatible con conversación normal, rechaza.
Si requiere una aclaración razonable, marca ambiguous. Responde únicamente con
la tool de verificación.
"""


@dataclass(frozen=True)
class AssessmentResult:
    assessment: TurnOperationAssessment
    goal: object | None = None

    @property
    def authorized(self) -> bool:
        return self.assessment.verdict == TurnOperationAssessment.VERDICT_AUTHORIZED


def last_operation_receipt(conversation):
    return (
        Message.objects.for_organization(conversation.organization)
        .filter(
            conversation=conversation,
            direction=Message.DIRECTION_OUT,
            semantic_type=Message.SEMANTIC_OPERATION_RECEIPT,
        )
        .exclude(status__in=(Message.STATUS_DISCARDED, Message.STATUS_FAILED))
        .order_by('-created_at', '-pk')
        .first()
    )


def requires_assessment(conversation) -> bool:
    """Verdadero solo entre un recibo terminado y una nueva operación viva."""
    return bool(
        last_operation_receipt(conversation)
        and confirmations.get_pending(conversation) is None
        and goals.get_open_goal(conversation) is None
    )


def allowed_operations(conversation) -> list[str]:
    """Operaciones compatibles con la ruta tipada, no con la redacción."""
    path = intake.current_path(conversation)
    if path == intake.PATH_NEW:
        return [TurnOperationAssessment.OPERATION_FIRST_VISIT]
    if path == intake.PATH_EXISTING:
        return [
            operation for operation, goal_name in OPERATION_TO_GOAL.items()
            if goal_name != goals.REGISTER
        ]
    return []


def assess_turn(conversation, messages: Iterable[Message], *,
                authorizer_client=None, verifier_client=None) -> AssessmentResult:
    """Evalúa y, si procede, autoriza la ráfaga completa una única vez.

    La idempotencia se ancla al último mensaje de la ráfaga. El worker puede
    repetir el turno tras un crash sin obtener otra autorización ni objetivo.
    """
    source_messages = _source_messages(conversation, messages)
    if not source_messages:
        raise ValueError('assess_turn requiere al menos un Message entrante')
    anchor = source_messages[-1]

    existing = TurnOperationAssessment.objects.filter(
        conversation=conversation, anchor_message=anchor,
    ).first()
    if existing is not None:
        return AssessmentResult(existing, _authorized_goal(existing))

    permitted = allowed_operations(conversation)
    if not permitted:
        assessment = _persist_assessment(
            conversation, source_messages,
            verdict=TurnOperationAssessment.VERDICT_UNAVAILABLE,
            failure_code='intake_path_unresolved',
        )
        return AssessmentResult(assessment)

    authorizer_client = authorizer_client or get_llm_client('operation_authorizer')
    verifier_client = verifier_client or get_llm_client('operation_verifier')
    turn_data = _turn_data(source_messages)

    try:
        proposal, authorizer_model = _classify(
            conversation, authorizer_client, turn_data, permitted,
        )
    except LLMError as exc:
        assessment = _persist_assessment(
            conversation, source_messages,
            verdict=TurnOperationAssessment.VERDICT_UNAVAILABLE,
            failure_code=_llm_failure_code(exc),
            authorizer_model=getattr(authorizer_client, 'model', ''),
        )
        return AssessmentResult(assessment)

    proposed_operation = proposal.get('operation', '')
    proposal_verdict = proposal.get('verdict', '')
    if proposal_verdict == 'conversational':
        assessment = _persist_assessment(
            conversation, source_messages,
            verdict=TurnOperationAssessment.VERDICT_CONVERSATIONAL,
            authorizer_model=authorizer_model,
        )
        return AssessmentResult(assessment)
    if proposal_verdict != 'operation' or proposed_operation not in permitted:
        assessment = _persist_assessment(
            conversation, source_messages,
            verdict=TurnOperationAssessment.VERDICT_AMBIGUOUS,
            failure_code='authorizer_ambiguous_or_invalid',
            authorizer_model=authorizer_model,
        )
        return AssessmentResult(assessment)

    try:
        verification, verifier_model = _verify(
            conversation, verifier_client, turn_data, proposed_operation,
        )
    except LLMError as exc:
        assessment = _persist_assessment(
            conversation, source_messages,
            verdict=TurnOperationAssessment.VERDICT_UNAVAILABLE,
            operation=proposed_operation,
            failure_code=_llm_failure_code(exc),
            authorizer_model=authorizer_model,
            verifier_model=getattr(verifier_client, 'model', ''),
        )
        return AssessmentResult(assessment)

    if verification.get('verdict') != 'accept':
        assessment = _persist_assessment(
            conversation, source_messages,
            verdict=(TurnOperationAssessment.VERDICT_AMBIGUOUS
                     if verification.get('verdict') == 'ambiguous'
                     else TurnOperationAssessment.VERDICT_REJECTED),
            operation=proposed_operation,
            failure_code=f"verifier_{verification.get('verdict') or 'invalid'}",
            authorizer_model=authorizer_model,
            verifier_model=verifier_model,
        )
        return AssessmentResult(assessment)

    assessment = _persist_assessment(
        conversation, source_messages,
        verdict=TurnOperationAssessment.VERDICT_AUTHORIZED,
        operation=proposed_operation,
        authorizer_model=authorizer_model,
        verifier_model=verifier_model,
    )
    goal = goals.open_goal(
        conversation,
        OPERATION_TO_GOAL[proposed_operation],
        authorization_message=anchor,
        operation_assessment=assessment,
    )
    logger.info(
        'AGENT_OPERATION_AUTHORIZED',
        extra={
            'organization_id': conversation.organization_id,
            'conversation_id': conversation.pk,
            'assessment_id': assessment.pk,
            'operation': proposed_operation,
            'message_count': len(source_messages),
        },
    )
    return AssessmentResult(assessment, goal)


def _source_messages(conversation, messages: Iterable[Message]) -> list[Message]:
    source_messages = [message for message in messages if message and message.pk]
    if not source_messages:
        return []
    if any(
        message.conversation_id != conversation.pk
        or message.direction != Message.DIRECTION_IN
        for message in source_messages
    ):
        raise ValueError('los mensajes fuente deben ser entrantes de la conversación')
    # Un Message no puede aparecer dos veces en una ráfaga. La clave conserva
    # el orden entregado por el worker; no reordena por cuerpo ni por tiempo.
    seen = set()
    unique = []
    for message in source_messages:
        if message.pk not in seen:
            seen.add(message.pk)
            unique.append(message)
    return unique


def _turn_data(messages: list[Message]) -> str:
    return json.dumps(
        {'messages': [
            {'index': index, 'payload_type': message.payload_type,
             'text': message.body}
            for index, message in enumerate(messages, start=1)
        ]},
        ensure_ascii=False,
    )


def _classify(conversation, client, turn_data: str, permitted: list[str]):
    if current_changes() is not None:
        from .durable import check_turn_deadline
        check_turn_deadline(current_changes().witness)
    result = client.complete(
        system=AUTHORIZER_SYSTEM_PROMPT,
        messages=[{
            'role': 'user',
            'content': json.dumps({
                'turn': json.loads(turn_data),
                'allowed_operations': permitted,
            }, ensure_ascii=False),
        }],
        tools=[AUTHORIZATION_TOOL],
        tool_choice={'type': 'function', 'function': {
            'name': AUTHORIZATION_TOOL['function']['name'],
        }},
        temperature=0,
        max_tokens=160,
    )
    _persist_llm_call(conversation, client, result, AUTHORIZER_PROMPT_VERSION)
    if result.kind != 'tool_call' or result.tool_name != AUTHORIZATION_TOOL['function']['name']:
        raise LLMError('autorizador no devolvió contrato', retryable=False)
    return result.tool_args, result.model_id or getattr(client, 'model', '')


def _verify(conversation, client, turn_data: str, operation: str):
    if current_changes() is not None:
        from .durable import check_turn_deadline
        check_turn_deadline(current_changes().witness)
    result = client.complete(
        system=VERIFIER_SYSTEM_PROMPT,
        messages=[{
            'role': 'user',
            'content': json.dumps({
                'turn': json.loads(turn_data),
                'proposed_operation': operation,
            }, ensure_ascii=False),
        }],
        tools=[VERIFICATION_TOOL],
        tool_choice={'type': 'function', 'function': {
            'name': VERIFICATION_TOOL['function']['name'],
        }},
        temperature=0,
        max_tokens=120,
    )
    _persist_llm_call(conversation, client, result, VERIFIER_PROMPT_VERSION)
    if result.kind != 'tool_call' or result.tool_name != VERIFICATION_TOOL['function']['name']:
        raise LLMError('verificador no devolvió contrato', retryable=False)
    return result.tool_args, result.model_id or getattr(client, 'model', '')


def _persist_llm_call(conversation, client, result, prompt_version: str) -> None:
    create_local(LLMCall,
        organization=conversation.organization,
        conversation=conversation,
        provider=getattr(settings, 'AGENT_LLM_BASE_URL', '')[:32],
        model_id=result.model_id or getattr(client, 'model', ''),
        prompt_version=prompt_version,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_estimate=estimate_cost(result.input_tokens, result.output_tokens),
        latency_ms=result.latency_ms,
        finish_reason=result.finish_reason,
    )


def _persist_assessment(conversation, messages, *, verdict, operation='',
                        failure_code='', authorizer_model='', verifier_model=''):
    anchor = messages[-1]
    defaults = {
        'organization': conversation.organization,
        'verdict': verdict,
        'operation': operation,
        'failure_code': failure_code,
        'authorizer_model': authorizer_model,
        'verifier_model': verifier_model,
        'authorizer_prompt_version': AUTHORIZER_PROMPT_VERSION,
        'verifier_prompt_version': VERIFIER_PROMPT_VERSION if verifier_model else '',
    }
    if current_changes() is not None:
        assessment = create_local(TurnOperationAssessment, conversation=conversation,
                                  anchor_message=anchor, **defaults)
        for index, message in enumerate(messages, start=1):
            create_local(TurnOperationAssessmentMessage, organization=conversation.organization,
                         assessment=assessment, message=message, ordinal=index)
        return assessment
    try:
        with transaction.atomic():
            assessment, created = TurnOperationAssessment.objects.get_or_create(
                conversation=conversation,
                anchor_message=anchor,
                defaults=defaults,
            )
            if created:
                TurnOperationAssessmentMessage.objects.bulk_create([
                    TurnOperationAssessmentMessage(
                        organization=conversation.organization,
                        assessment=assessment,
                        message=message,
                        ordinal=index,
                    )
                    for index, message in enumerate(messages, start=1)
                ])
    except IntegrityError:
        assessment = TurnOperationAssessment.objects.get(
            conversation=conversation, anchor_message=anchor,
        )
    logger.info(
        'AGENT_OPERATION_ASSESSED',
        extra={
            'organization_id': conversation.organization_id,
            'conversation_id': conversation.pk,
            'assessment_id': assessment.pk,
            'verdict': assessment.verdict,
            'operation': assessment.operation,
            'failure_code': assessment.failure_code,
            'message_count': len(messages),
        },
    )
    return assessment


def _authorized_goal(assessment):
    if assessment.verdict != TurnOperationAssessment.VERDICT_AUTHORIZED:
        return None
    return assessment.authorized_goals.filter(
        status__in=ConversationGoal.OPEN_STATUSES,
    ).first()


def _llm_failure_code(exc: LLMError) -> str:
    return 'llm_retryable_failure' if exc.retryable else 'llm_contract_failure'
