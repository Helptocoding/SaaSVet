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
import logging
import time
import uuid

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
            return 599, {'code': 'transport_error',
                         'message': exc.__class__.__name__}
        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {}
        return response.status_code, data


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

    def call(self, method, path, *, tool_name, params=None, json=None,
             args_redacted=None, policy_tier='', policy_decision='auto',
             triggered_by_message=None, result_summarizer=None,
             domain_object_public_id=None, extract_domain_id=None,
             idempotency_key=None):
        """Un request autenticado + una fila de auditoría. Devuelve
        ``(status_code, data)`` — el mapeo a comportamiento conversacional
        (spec §2.5) es del caller (planner/policy), no de aquí.
        """
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
        status_code, data = self.transport(
            method, path, headers=headers, params=params, json=json,
        )
        duration_ms = int((time.monotonic() - started) * 1000)

        error_code = ''
        if status_code >= 400:
            error_code = str(
                (data or {}).get('code')
                or (data or {}).get('detail')
                or status_code
            )[:64]

        summary = {}
        if result_summarizer is not None and status_code < 400:
            try:
                summary = result_summarizer(data) or {}
            except Exception:  # la auditoría jamás tumba la ejecución
                summary = {'summary_error': True}

        # public_id del objeto de dominio creado/afectado (cadena ADR p51).
        if extract_domain_id is not None and status_code < 400 and domain_object_public_id is None:
            try:
                domain_object_public_id = extract_domain_id(data)
            except Exception:
                domain_object_public_id = None

        ToolExecution(
            organization=self.conversation.organization,
            conversation=self.conversation,
            tool_name=tool_name,
            args_redacted=args_redacted or {},
            policy_tier=str(policy_tier),
            policy_decision=policy_decision,
            http_status=status_code if status_code <= 599 else None,
            result_summary_redacted=summary,
            error_code=error_code,
            duration_ms=duration_ms,
            request_id=request_id,
            domain_object_public_id=domain_object_public_id,
            triggered_by_message=triggered_by_message,
        ).save()

        if status_code >= 400:
            logger.warning("AGENT_TOOL_HTTP_ERROR", extra={
                "event": "AGENT_TOOL_HTTP_ERROR",
                "organization_id": self.conversation.organization_id,
                "conversation_id": self.conversation.pk,
                "tool_name": tool_name,
                "status_code": status_code,
                "error_code": error_code,
                "request_id": request_id,
            })
        return status_code, data

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
        execution.save()
        return execution


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
