"""
agent/executor.py — Tool Executor: loopback HTTP con el JWT del AGENT (É-F1).

Decisión de arquitectura (plan v1.1 §6.7, NO reabrir): las tools consumen la
API DRF existente por HTTP — nunca ORM directo — para conservar serializers
(tenant validators ADR p14), RBAC, sanitización y el shape estándar de
errores sin duplicar nada. El precio (ms de hop local) es irrelevante frente
al costo del LLM.

Minting (diferido de A0-2 hasta tener consumidor — es este):
``AccessToken.for_user(agent_user)`` server-side — SIN pasar por
``/api/token/`` (el agente no tiene password utilizable) y SIN crear filas
``OutstandingToken`` (solo los refresh las crean). TTL corto del access
(15 min, ADR p20); cache en memoria por organización con margen de 60 s.
El token vive SOLO en la memoria del worker: jamás se persiste ni loguea.

Transporte inyectable: ``RequestsTransport`` (producción, hacia
``AGENT_INTERNAL_API_URL``) o un transport de tests que enruta por el
Django test client — así los tests de tools atraviesan la API REAL
(RBAC del rol AGENT incluido) sin servidor vivo.
"""

from .turn_changes import save_local, current_changes
import logging
import time
import uuid
from dataclasses import dataclass, field

import requests
from django.conf import settings
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from .models import ToolExecution

logger = logging.getLogger('agent.events')

HTTP_TIMEOUT = 10

# Cache de tokens por organización: {org_id: (token_str, expires_epoch)}.
# Memoria de proceso — cada réplica del worker acuña el suyo.
_token_cache = {}
_TOKEN_SLACK_SECONDS = 60


def mint_agent_token(agent_user):
    """Access token del user AGENT, cacheado hasta ~1 min antes de expirar."""
    now = time.time()
    cached = _token_cache.get(agent_user.organization_id)
    if cached and cached[1] - now > _TOKEN_SLACK_SECONDS:
        return cached[0]

    token = AccessToken.for_user(agent_user)
    expires_epoch = token.payload.get('exp', now + 300)
    token_str = str(token)
    _token_cache[agent_user.organization_id] = (token_str, expires_epoch)
    return token_str


@dataclass(frozen=True)
class TransportResponse:
    """HTTP evidence only. A parsed 2xx is NOT a business outcome.

    Body/data stay in memory and are deliberately excluded from repr/logs.
    Tuple iteration is temporary compatibility for unmigrated callers.
    """
    status_code: int | None = None
    data: object = field(default=None, repr=False)
    body: bytes | str | None = field(default=None, repr=False)
    parse_valid: bool = False
    transport_error: str | None = None
    timeout: bool = False
    uncertain: bool = False

    @classmethod
    def from_http(cls, response):
        body = response.content
        try:
            data = response.json() if body else None
            valid = bool(body)
        except (ValueError, TypeError):
            data, valid = None, False
        return cls(response.status_code, data, body, valid)

    @property
    def error_kind(self):
        if self.transport_error:
            return 'uncertain' if self.uncertain else 'transport_error'
        if self.status_code in (401, 403):
            return 'forbidden'
        if self.status_code == 404:
            return 'not_found'
        if self.status_code == 409:
            return 'conflict'
        if self.status_code in (400, 422):
            return 'validation_error'
        if self.status_code is None or self.status_code >= 500:
            return 'provider_error'
        if not 200 <= self.status_code < 300:
            return 'provider_error'
        if not self.parse_valid:
            return 'malformed_response'
        return None

    def __iter__(self):
        # Fail closed for legacy status checks without replacing the real
        # HTTP status or manufacturing an empty JSON body.
        yield (self.status_code if self.status_code is not None
               and (self.parse_valid or self.status_code >= 400) else 599)
        yield self.data


class RequestsTransport:
    """Transporte de producción: HTTP interno worker→backend."""

    def __call__(self, method, path, *, headers, params=None, json=None):
        base = getattr(settings, 'AGENT_INTERNAL_API_URL',
                       'http://backend:8000').rstrip('/')
        try:
            response = requests.request(
                method, f"{base}{path}", headers=headers,
                params=params, json=json, timeout=HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            return TransportResponse(
                transport_error=type(exc).__name__,
                timeout=isinstance(exc, requests.Timeout),
                uncertain=method.upper() not in ('GET', 'HEAD', 'OPTIONS'),
            )
        return TransportResponse.from_http(response)


class ToolExecutor:
    """Ejecuta llamadas de tools y persiste su auditoría (`ToolExecution`).

    Regla de redacción (R15): `args_redacted` y `result_summary_redacted`
    llegan YA proyectados por la tool — este módulo jamás vuelca payloads
    crudos ni el token a la auditoría o a los logs.
    """

    def __init__(self, conversation, agent_user, transport=None):
        self.conversation = conversation
        self.agent_user = agent_user
        self.transport = transport or RequestsTransport()
        self.last_execution_id = None

    def call(self, method, path, *, tool_name, params=None, json=None,
             args_redacted=None, policy_tier='', policy_decision='auto',
             triggered_by_message=None, result_summarizer=None,
             domain_object_public_id=None, extract_domain_id=None,
             idempotency_key=None, business_outcomes=()):
        """Un request autenticado + una fila de auditoría. Devuelve
        TransportResponse — transporte/parseo sin inferir éxito de negocio.
        La iteración como tuple es compatibilidad temporal para preparadores
        legacy; los consumidores B2 validan el resultado explícito.

        ``business_outcomes``: códigos que ESTA llamada declara como
        **desenlaces de negocio esperados** (§5.4, hallazgo X). Un
        ``owner_exists`` es negocio en el alta y sería una anomalía en
        cualquier otra tool, así que no hay lista global: la declara quien
        llama. Los declarados registran ``AGENT_TOOL_BUSINESS_CONFLICT``
        (INFO, redactado) en lugar de ``AGENT_TOOL_HTTP_ERROR`` (WARNING) y no
        cuentan como fallo de integración. **La fila de ``ToolExecution`` se
        sigue creando con su ``error_code``**: es la traza y no se pierde.

        Lo NO declarado conserva su comportamiento: el silencio por defecto
        sería el fail-open de la observabilidad.
        """
        from . import intake
        if current_changes() is not None:
            from .durable import check_turn_deadline
            check_turn_deadline(current_changes().witness)
        from .capabilities import EFFECTS, WRITE_BUSINESS
        # A READ can never hide a mutation, even through a wrong dispatch.
        # B0's legacy component test override is not a runtime setting.
        if method.upper() not in ('GET', 'HEAD', 'OPTIONS') and (
                EFFECTS.get(tool_name) != WRITE_BUSINESS or intake.write_is_contained(tool_name)):
            self.record_local(tool_name=tool_name, policy_decision='denied',
                              summary={'reason': 'autonomous_writes_paused'},
                              triggered_by_message=triggered_by_message)
            return TransportResponse(403, {'code': 'permission_denied'}, parse_valid=True)
        request_id = str(uuid.uuid4())
        headers = {
            'Authorization': f'Bearer {mint_agent_token(self.agent_user)}',
            'Accept': 'application/json',
            # Correlación end-to-end (P1-5 A1): el backend reusa este id en
            # sus logs → webhook→worker→tool→dominio trazable.
            'X-Request-ID': request_id,
            # El loopback es HTTP interno (worker→backend:8000); sin esto,
            # SECURE_SSL_REDIRECT responde 301→https y la tool falla. Con el
            # proto header (SECURE_PROXY_SSL_HEADER) Django lo trata como seguro,
            # igual que cuando Caddy lo reenvía desde afuera.
            'X-Forwarded-Proto': 'https',
        }
        # A2-1: idempotencia de escritura (una cita, no dos, ante reintento).
        if idempotency_key:
            headers['X-Idempotency-Key'] = idempotency_key

        started = time.monotonic()
        response = self.transport(
            method, path, headers=headers, params=params, json=json,
        )
        # Injected legacy test transports already provide decoded JSON.
        if not isinstance(response, TransportResponse):
            status, decoded = response
            response = TransportResponse(status, decoded, parse_valid=True)
        status_code, data = response.status_code, response.data
        duration_ms = int((time.monotonic() - started) * 1000)

        error_code = ''
        if response.error_kind:
            # Closed vocabulary: arbitrary server detail/code can contain PII.
            known_codes = {
                'permission_denied', 'not_found', 'appointment_changed',
                'owner_exists', 'owner_ambiguous', 'slot_taken',
                'past_appointment', 'precondition_required',
            }
            code = data.get('code') if isinstance(data, dict) else None
            error_code = code if isinstance(code, str) and code in known_codes else response.error_kind

        summary = {}
        if result_summarizer is not None and not response.error_kind:
            try:
                summary = result_summarizer(data) or {}
                # A summarizer must not turn an unvalidated provider string
                # into a persisted personal payload. Keep counts/known states.
                summary = {key: value for key, value in summary.items()
                           if key in ('pets', 'vaccines', 'appointments', 'occupied',
                                      'services', 'products', 'items', 'status')
                           and (type(value) in (int, bool)
                                or (key == 'status' and value in (
                                    'scheduled', 'confirmed', 'in_progress',
                                    'done', 'canceled', 'no_show')))}
            except Exception:  # la auditoría jamás tumba la ejecución
                summary = {'summary_error': True}

        # public_id del objeto de dominio creado/afectado (cadena ADR p51).
        if extract_domain_id is not None and not response.error_kind and domain_object_public_id is None:
            try:
                domain_object_public_id = extract_domain_id(data)
                if domain_object_public_id is not None:
                    domain_object_public_id = str(uuid.UUID(str(domain_object_public_id)))
            except Exception:
                domain_object_public_id = None

        execution = ToolExecution(
            organization=self.conversation.organization,
            conversation=self.conversation,
            tool_name=tool_name,
            args_redacted=args_redacted or {},
            policy_tier=str(policy_tier),
            policy_decision=policy_decision,
            http_status=status_code if status_code is not None and status_code <= 599 else None,
            result_summary_redacted=summary,
            error_code=error_code,
            duration_ms=duration_ms,
            request_id=request_id,
            domain_object_public_id=domain_object_public_id,
            triggered_by_message=triggered_by_message,
        )
        save_local(execution)
        self.last_execution_id = execution.pk

        if response.error_kind:
            is_business = error_code in business_outcomes
            event = ("AGENT_TOOL_BUSINESS_CONFLICT" if is_business
                     else "AGENT_TOOL_HTTP_ERROR")
            payload = {
                "event": event,
                "organization_id": self.conversation.organization_id,
                "conversation_id": self.conversation.pk,
                "tool_name": tool_name,
                "status_code": status_code,
                "error_code": error_code,
                "error_kind": response.error_kind,
                "request_id": request_id,
            }
            # Un conflicto de negocio frecuente no es un bug: es la señal de
            # que staff y agente operan sobre lo mismo a la vez, y produce
            # decisiones. Mezclarlo con las averías esconde las dos señales.
            if is_business:
                logger.info(event, extra=payload)
            else:
                logger.warning(event, extra=payload)
        return response

    def record_local(self, *, tool_name, args_redacted=None, policy_tier='',
                     policy_decision='auto', summary=None,
                     triggered_by_message=None, domain_object_public_id=None):
        """Auditoría de tools LOCALES (sin HTTP: T5 info clínica, T15 humano).

        Misma fila `ToolExecution` para que la cadena de auditoría no tenga
        huecos según el tipo de tool.
        """
        execution = ToolExecution(
            organization=self.conversation.organization,
            conversation=self.conversation,
            tool_name=tool_name,
            args_redacted=args_redacted or {},
            policy_tier=str(policy_tier),
            policy_decision=policy_decision,
            http_status=None,
            result_summary_redacted=summary or {},
            duration_ms=0,
            request_id=str(uuid.uuid4()),
            domain_object_public_id=domain_object_public_id,
            triggered_by_message=triggered_by_message,
        )
        save_local(execution)
        self.last_execution_id = execution.pk
        return execution

    def record_outcome(self, tool_name, outcome):
        """Versioned, non-authoritative C3 diagnostics in the existing row.

        No body, labels, prices, entity references or personal scope is copied.
        Older summaries remain diagnostics and are never upgraded/backfilled.
        """
        changes = current_changes()
        execution = (changes.executions.get(self.last_execution_id) if changes else
            ToolExecution.objects.filter(
                pk=self.last_execution_id, conversation=self.conversation,
                organization_id=self.conversation.organization_id, tool_name=tool_name).first())
        if execution is None:
            return
        summary = dict(execution.result_summary_redacted or {})
        summary['_outcome_v1'] = {
            'kind': outcome.kind, 'validated': outcome.validated,
            'completeness': outcome.completeness, 'error_kind': outcome.error_kind,
        }
        execution.result_summary_redacted = summary
        fields = ['result_summary_redacted']
        if outcome.kind == 'ERROR' and not execution.error_code:
            execution.error_code = outcome.error_kind
            fields.append('error_code')
            logger.warning('AGENT_TOOL_RESULT_ERROR', extra={
                'event': 'AGENT_TOOL_RESULT_ERROR',
                'organization_id': self.conversation.organization_id,
                'conversation_id': self.conversation.pk, 'tool_name': tool_name,
                'status_code': execution.http_status, 'error_kind': outcome.error_kind,
                'request_id': execution.request_id,
            })
        save_local(execution, update_fields=fields)


_ES_DAYS = ('lunes', 'martes', 'miércoles', 'jueves',
            'viernes', 'sábado', 'domingo')
_ES_MONTHS = ('enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
              'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre')


def _es_datetime_label(local):
    """'martes 21 de julio, 4:00 p. m.' desde un datetime ya en hora local."""
    hour12 = local.hour % 12 or 12
    ampm = 'a. m.' if local.hour < 12 else 'p. m.'
    return (
        f"{_ES_DAYS[local.weekday()]} {local.day} de {_ES_MONTHS[local.month - 1]}, "
        f"{hour12}:{local.minute:02d} {ampm}"
    )


def format_local_datetime(iso_or_dt, organization):
    """Etiqueta absoluta en la zona horaria de la ORG a partir de un instante
    UTC/aware (G5: fechas al cliente SIEMPRE absolutas y en su hora local).
    Para fecha+hora que YA vienen en hora local (wall-clock, p.ej. `date` +
    `start_time` del serializer o un slot ofertado) usar
    `format_local_wallclock` — NO esta función (double-shift de tz)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from datetime import timezone as dt_timezone

    value = iso_or_dt
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if timezone.is_naive(value):
        value = timezone.make_aware(value, dt_timezone.utc)
    try:
        local = value.astimezone(ZoneInfo(organization.timezone))
    except Exception:
        local = value
    return _es_datetime_label(local)


def format_local_wallclock(date_str, time_str):
    """Etiqueta absoluta desde fecha (YYYY-MM-DD) + hora (HH:MM) que YA están
    en la hora local de la org — SIN conversión de tz. El slot ofertado, la
    cita agendada y la cita a cancelar/mover se expresan en wall-clock local;
    convertirlos como si fueran UTC los desfasaría."""
    from datetime import datetime
    try:
        dt = datetime.strptime(
            f"{str(date_str)[:10]} {str(time_str)[:5]}", '%Y-%m-%d %H:%M')
    except (ValueError, TypeError):
        return f"{date_str} {time_str}".strip()
    return _es_datetime_label(dt)
