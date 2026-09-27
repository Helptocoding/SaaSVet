"""
agent/llm.py — Adaptador LLM proveedor-agnóstico (É-F1 PR-9).

REGLA (feedback PO 2026-07-17): el proveedor NO está decidido y este módulo
JAMÁS asume una marca. Habla la API compatible con OpenAI
(``/chat/completions`` + tool calling), que cubre DeepSeek, OpenAI, Groq,
Together y despliegues self-hosted (vLLM/Ollama) con un solo cliente:
``AGENT_LLM_BASE_URL`` + ``AGENT_LLM_API_KEY`` + modelos, todo por env.

Sin SDKs: ``requests`` (ya en el lock). El planner consume la interfaz
``complete()``; los tests usan ``StubLLMClient`` (determinista — la suite
CI de la spec §9.1 corre sin red ni proveedor).

PII: este módulo no loguea prompts ni respuestas (regla R15); llm_budget
persiste admisión y observación en LLMCall para los tres call sites del agente.
"""
import json
import logging
import time
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

import requests
from django.conf import settings

logger = logging.getLogger('agent.events')

DEFAULT_TIMEOUT = 10
DEFAULT_MAX_TOKENS = 600
DEFAULT_TEMPERATURE = 0.3


class LLMError(Exception):
    """Fallo del proveedor. `retryable`: timeout/5xx/429 sí; 4xx no."""

    def __init__(self, message, retryable, usage=None):
        super().__init__(message)
        self.retryable = retryable
        self.usage = usage


@dataclass
class LLMResult:
    """Salida normalizada de una llamada.

    kind: 'text' (respuesta libre) | 'tool_call' (el modelo pide una tool).
    Los tokens vienen del campo `usage` del proveedor (None si no lo reporta).
    """

    kind: str
    text: str = ''
    tool_name: str = ''
    tool_args: dict = field(default_factory=dict)
    # Id que devuelve el proveedor para correlacionar la llamada con su
    # resultado (mensajes role='tool'). El stub no lo emite: el planner le
    # asigna uno sintético (W1-3).
    tool_call_id: str = ''
    finish_reason: str = ''
    input_tokens: int | None = None
    output_tokens: int | None = None
    model_id: str = ''
    latency_ms: int = 0


def estimate_cost(input_tokens, output_tokens):
    """Legacy estimate with explicit env pricing; unknown is None.

    AGENT_LLM_COST_PER_MTOK_INPUT/OUTPUT = USD por millón de tokens del
    proveedor elegido. Contabilidad (R11), no facturación.
    """
    price_in = getattr(settings, 'AGENT_LLM_COST_PER_MTOK_INPUT', 0.0)
    price_out = getattr(settings, 'AGENT_LLM_COST_PER_MTOK_OUTPUT', 0.0)
    if input_tokens is None or output_tokens is None or not price_in or not price_out:
        return None
    total = (Decimal(input_tokens) * Decimal(str(price_in))
             + Decimal(output_tokens) * Decimal(str(price_out))) / Decimal(1_000_000)
    # LLMCall.cost_estimate es DecimalField(max_digits=10, decimal_places=6):
    # el float trae ruido de precisión (0.0000747900...01) → cuantizar a 6
    # decimales antes de persistir, o Django lo rechaza. Cap defensivo a
    # 9999.999999 (el máximo del campo) por si el pricing se configura mal.
    quantized = Decimal(str(total)).quantize(
        Decimal('0.000001'), rounding=ROUND_HALF_UP,
    )
    return min(quantized, Decimal('9999.999999'))

class OpenAICompatibleClient:
    """Cliente mínimo de `/chat/completions` con tool calling."""

    # En producción toda respuesta llega como `respond_to_client`; así el
    # planner puede separar respuesta conversacional de propuesta tier-2.
    requires_response_tool = True

    def __init__(self, base_url=None, api_key=None, model=None):
        self.base_url = (
            base_url or getattr(settings, 'AGENT_LLM_BASE_URL', '')
        ).rstrip('/')
        self.api_key = api_key or getattr(settings, 'AGENT_LLM_API_KEY', '')
        self.model = model or getattr(settings, 'AGENT_LLM_MODEL_PLANNER', '')

    def complete(self, *, system, messages, tools=None,
                 max_tokens=DEFAULT_MAX_TOKENS,
                 temperature=DEFAULT_TEMPERATURE, tool_choice='auto'):
        """messages = [{'role': 'user'|'assistant'|'tool', 'content': ...}].

        Devuelve LLMResult; levanta LLMError. El caller decide reintentos;
        llm_budget hace admisión y registra cada intento antes del siguiente.
        """
        if not self.base_url or not self.api_key or not self.model:
            raise LLMError(
                "LLM no configurado (AGENT_LLM_BASE_URL/API_KEY/MODEL)",
                retryable=False,
            )

        payload = {
            'model': self.model,
            'messages': [{'role': 'system', 'content': system}] + list(messages),
            'max_tokens': max_tokens,
            'temperature': temperature,
        }
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = tool_choice

        started = time.monotonic()
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={'Authorization': f'Bearer {self.api_key}'},
                json=payload,
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise LLMError(f"red: {exc.__class__.__name__}", retryable=True)
        latency_ms = int((time.monotonic() - started) * 1000)

        if response.status_code >= 500 or response.status_code == 429:
            raise LLMError(f"proveedor {response.status_code}", retryable=True)
        if response.status_code >= 400:
            raise LLMError(f"proveedor {response.status_code}", retryable=False)

        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
        except (ValueError, TypeError):
            raise LLMError("respuesta no parseable", retryable=False)

        usage = data.get('usage')
        usage = usage if isinstance(usage, dict) else {}
        base = {
            'input_tokens': valid_token_count(usage.get('prompt_tokens')),
            'output_tokens': valid_token_count(usage.get('completion_tokens')),
            'model_id': data.get('model', self.model),
            'latency_ms': latency_ms,
        }
        try:
            choice = data['choices'][0]
            message = choice.get('message') or {}
            if not isinstance(message, dict):
                raise ValueError
        except (ValueError, TypeError, AttributeError, KeyError, IndexError):
            raise LLMError('respuesta no parseable', retryable=False, usage=base)
        base['finish_reason'] = choice.get('finish_reason', '')

        tool_calls = message.get('tool_calls') or []
        if tool_calls:
            function = (tool_calls[0].get('function') or {})
            raw_args = function.get('arguments') or '{}'
            try:
                tool_args = json.loads(raw_args)
                if not isinstance(tool_args, dict):
                    raise ValueError
            except ValueError:
                # Args malformados = el modelo alucinó JSON: NO retryable a
                # ciegas — el planner lo trata como turno fallido (fallback).
                raise LLMError("tool_args no parseables", retryable=False, usage=base)
            return LLMResult(
                kind='tool_call',
                tool_name=function.get('name', ''),
                tool_args=tool_args,
                tool_call_id=tool_calls[0].get('id', '') or '',
                **base,
            )

        return LLMResult(kind='text', text=message.get('content') or '', **base)


def valid_token_count(value):
    """Only provider integers in the storage range; absence is never zero."""
    return value if type(value) is int and 0 <= value <= 2147483647 else None


class StubLLMClient:
    """Determinista para tests (spec §9.1: la suite CI corre sin proveedor).

    `scripted` = lista de LLMResult (o LLMError para simular fallos) que se
    consumen en orden; registra cada invocación en `calls`.
    """

    requires_response_tool = False

    def __init__(self, scripted=None, model='stub-model'):
        self.scripted = list(scripted or [])
        self.model = model
        self.calls = []

    def complete(self, *, system, messages, tools=None, **kwargs):
        self.calls.append({
            'system': system, 'messages': messages, 'tools': tools,
        })
        if not self.scripted:
            return LLMResult(kind='text', text='(stub sin guion)',
                             model_id=self.model)
        item = self.scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def get_llm_client(role='planner'):
    """Factory por rol de conversación o autorización semántica.

    El autorizador y el verificador pueden usar modelos distintos. Mientras el
    operador los configura, ambos caen al router y éste al planner; sus
    contratos y llamadas siguen siendo separados.
    """
    model = getattr(settings, 'AGENT_LLM_MODEL_PLANNER', '')
    router_model = getattr(settings, 'AGENT_LLM_MODEL_ROUTER', '') or model
    if role == 'router':
        model = router_model
    elif role == 'operation_authorizer':
        model = (
            getattr(settings, 'AGENT_LLM_MODEL_OPERATION_AUTHORIZER', '')
            or router_model
        )
    elif role == 'operation_verifier':
        model = (
            getattr(settings, 'AGENT_LLM_MODEL_OPERATION_VERIFIER', '')
            or router_model
        )
    return OpenAICompatibleClient(model=model)
