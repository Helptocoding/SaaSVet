"""B9A: signed Django HTTP -> real worker -> real sender -> controlled wire.

No services/operations/adapters are invoked in place of the conversational path.
Only requests.Session.request is replaced: external LLM/Meta wire responses,
and loopback HTTP through Django's real URL/middleware/auth/view stack.
"""
import hashlib
import hmac
import io
import json
import sys
from collections import deque
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlsplit

import requests
from django.core.management import call_command
from django.db import connection
from django.test import Client, override_settings
from django.utils import timezone

from apps.agent import durable
from apps.agent.models import Conversation, TurnWork
from apps.channels.models import Message

SECRET = 'b9a-isolated-signature'
SETTINGS = dict(WHATSAPP_APP_SECRET=SECRET, WHATSAPP_VERIFY_TOKEN='b9a-verify',
    WHATSAPP_API_BASE_URL='https://meta.b9a.invalid', B9A_TOKEN='b9a-fake-token',
    AGENT_LLM_BASE_URL='https://llm.b9a.invalid', AGENT_LLM_API_KEY='b9a-fake-key',
    AGENT_LLM_MODEL_PLANNER='b9a-planner', AGENT_LLM_MODEL_ROUTER='b9a-router',
    AGENT_INTERNAL_API_URL='http://b9a.internal.test',
    HEALTHCHECK_AGENT_WORKER_URL='', HEALTHCHECK_AGENT_SENDER_URL='',
    AGENT_B7B_CONSENT_ENABLED=False, AGENT_OPERATION_EXECUTION_ENABLED={},
    AGENT_SAFETY_AUTOMATION_ENABLED=False,
    ALLOWED_HOSTS=['testserver', 'b9a.internal.test', 'localhost'])


def tool(name, **arguments):
    return {'choices': [{'message': {'tool_calls': [{'id': 'b9a-call',
        'type': 'function', 'function': {'name': name,
        'arguments': json.dumps(arguments)}}]}, 'finish_reason': 'tool_calls'}],
        'model': 'b9a-planner', 'usage': {'prompt_tokens': 20, 'completion_tokens': 10}}


def answer(text='Puedo ayudarte con esa solicitud.'):
    return tool('respond_to_client', purpose='answer', text=text)


def response(payload, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode()
    result.headers['Content-Type'] = 'application/json'
    return result


class ApplicationHarness:
    def __init__(self, channel, *, llm=(), meta=()):
        self.channel = channel
        self.llm = deque(llm)
        self.meta = deque(meta)
        self.http = []
        self.wire = []
        self.calls = []
        self.contexts = []
        self.generated = []
        self.serial = 0
        self.callback = None
        self.client = Client()

    def trace(self, frame, event, arg):
        module, name = frame.f_globals.get('__name__', ''), frame.f_code.co_name
        # Volatile generation witness, deliberately independent of committed
        # Message rows. A failed/fenced publication can have generated > queued.
        if event == 'call' and module == 'apps.agent.outbound' and name == 'enqueue_outbound':
            self.generated.append(frame.f_locals['conversation'].pk)
        if (event == 'return' and module == 'apps.agent.operation_proposals' and name == 'render_proposal'
                and frame.f_back.f_code.co_name == 'publish_proposal' and arg):
            self.generated.append(frame.f_locals['operation'].conversation_id)
        if (event == 'return' and module == 'apps.agent.operation_execution'
                and name == 'consent_execution_output' and arg):
            self.generated.append(frame.f_locals['witness'].conversation_id)
        if (event == 'return' and module == 'apps.agent.operation_consent' and name == 'reply_text'
                and frame.f_back.f_code.co_name == 'finalize_turn' and arg):
            self.generated.append(frame.f_back.f_locals['conv'].pk)
        if (event == 'return' and module == 'apps.agent.tier0' and name == 'render_safety_guidance'
                and frame.f_back.f_code.co_name == 'finalize_safety' and arg):
            self.generated.append(frame.f_back.f_locals['conv'].pk)
        if (event == 'return' and frame.f_globals.get('__name__') == 'apps.agent.durable'
                and frame.f_code.co_name == 'context_for_work' and arg is not None):
            self.contexts.append(arg)
        if event == 'call':
            module = frame.f_globals.get('__name__', '')
            name = frame.f_code.co_name
            if module.startswith('apps.agent.') and name in {
                    'claim_turn', 'context_for_work', 'handle_inbound', 'finalize_turn',
                    'publish_proposal', 'evaluate_turn', 'execute_authorized_operation',
                    'validate_preconditions', 'execute', 'dispatch_claim', 'admit_dispatch',
                    'admit', 'record'}:
                caller = frame.f_back
                self.calls.append({'module': module, 'function': name,
                    'caller': caller.f_globals.get('__name__', '') + '.' + caller.f_code.co_name})

    @contextmanager
    def running(self):
        if connection.vendor != 'postgresql' or not connection.settings_dict['NAME'].startswith('test_'):
            raise RuntimeError('B9A requires an isolated PostgreSQL test database')
        def wire_request(session, method, url, **kwargs):
            return self.request(method, url, **kwargs)
        previous = sys.getprofile()
        with override_settings(**SETTINGS), patch.object(requests.Session, 'request', wire_request):
            sys.setprofile(self.trace)
            try:
                yield self
            finally:
                sys.setprofile(previous)

    def request(self, method, url, **kwargs):
        target = urlsplit(url)
        if target.hostname == 'b9a.internal.test':
            headers = {'HTTP_' + k.upper().replace('-', '_'): v
                       for k, v in kwargs.get('headers', {}).items()}
            path = target.path + ('?' + target.query if target.query else '')
            client = Client()
            if kwargs.get('json') is not None:
                reply = client.generic(method.upper(), path, json.dumps(kwargs['json']),
                    content_type='application/json', **headers)
            else:
                reply = getattr(client, method.lower())(path, kwargs.get('params') or {}, **headers)
            self.http.append({'boundary': 'domain', 'method': method.upper(),
                              'path': target.path, 'status': reply.status_code})
            result = requests.Response()
            result.status_code, result._content = reply.status_code, reply.content
            result.headers.update(dict(reply.headers))
            return result
        if target.hostname not in ('llm.b9a.invalid', 'meta.b9a.invalid'):
            raise AssertionError('Network destination outside B9A controlled boundaries')
        boundary = 'llm' if target.hostname == 'llm.b9a.invalid' else 'meta'
        event = {'boundary': boundary, 'method': method.upper(), 'path': target.path,
                 'payload': kwargs.get('json'), 'in_atomic': connection.in_atomic_block}
        self.wire.append(event)
        if connection.in_atomic_block:
            raise AssertionError('External IO under transaction')
        if boundary == 'llm':
            from apps.agent.turn_changes import current_changes
            from apps.agent.models import LLMCall
            changes = current_changes()
            if changes is not None:
                witness = changes.witness
                call = LLMCall.objects.filter(organization_id=witness.organization_id,
                    turn_work_id=witness.turn_work_id, admission_lease_token=witness.lease_token,
                    admitted_at__isnull=False, recorded_at__isnull=True).order_by('-id').first()
                event['admission_observed'] = call is not None
                if call is None:
                    raise AssertionError('LLM wire without durable admission')
        if self.callback:
            self.callback(boundary, event)
        if boundary == 'llm':
            if not self.llm:
                raise AssertionError('Unscripted LLM call')
            item = self.llm.popleft()
        else:
            self.serial += 1
            item = self.meta.popleft() if self.meta else {
                'messages': [{'id': f'wamid.b9a.out.{self.channel.pk}.{self.serial}'}]}
        if isinstance(item, BaseException):
            raise item
        return item if isinstance(item, requests.Response) else response(item)

    def post(self, payload, *, signature=True):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        digest = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
        result = self.client.post('/hooks/whatsapp/', raw, content_type='application/json',
            HTTP_X_HUB_SIGNATURE_256='sha256=' + (digest if signature else 'invalid'))
        self.http.append({'boundary': 'webhook', 'method': 'POST',
                          'path': '/hooks/whatsapp/', 'status': result.status_code})
        return result

    def payload(self, *, messages=(), statuses=(), account=None):
        return {'object': 'whatsapp_business_account', 'entry': [{'changes': [{'value': {
            'metadata': {'phone_number_id': account or self.channel.external_account_id},
            'messages': list(messages), 'statuses': list(statuses)}}]}]}

    def inbound(self, text, *, key=None, wa_id='5215512345678', raw=None, account=None):
        self.serial += 1
        key = key or f'wamid.b9a.in.{self.channel.pk}.{self.serial}'
        event = {'id': key, 'from': wa_id, 'type': 'text', 'text': {'body': text}, **(raw or {})}
        reply = self.post(self.payload(messages=[event], account=account))
        if reply.status_code != 200:
            raise AssertionError(f'Webhook returned {reply.status_code}')
        return Message.objects.filter(channel_account=self.channel, direction='in',
                                      external_message_id=key).first()

    def client_reply(self, proposal, text, **kwargs):
        from apps.agent.operation_proposals import is_proposal_emitted
        proposal.refresh_from_db()
        if not is_proposal_emitted(proposal):
            raise ValueError('Simulated client cannot reply to an un-emitted proposal')
        return self.inbound(text, raw={'context': {'id': proposal.proposal_message.external_message_id}}, **kwargs)

    def status(self, message, status, *, account=None, provider_id=None):
        message.refresh_from_db()
        return self.post(self.payload(statuses=[{
            'id': provider_id or message.external_message_id, 'status': status}], account=account))

    def worker(self):
        # Explicit fixture clock: drain only debounce, never fabricate B7B
        # receipt timestamps, authorization, expiry or provider acceptance.
        Message.objects.filter(direction='in', status='pending', turn_work__isnull=True,
            organization_id=self.channel.organization_id).update(available_at=None)
        call_command('run_agent_worker', once=True, mode='planner', stdout=io.StringIO())

    def sender(self):
        call_command('run_agent_worker', once=True, mode='sender', stdout=io.StringIO())

    def snapshot(self, conversation):
        rows = Message.objects.filter(conversation=conversation, direction='out')
        return {'response_generated': self.generated.count(conversation.pk),
            'outbound_queued': rows.count(),
            'provider_accepted': rows.filter(provider_accepted_at__isnull=False).count(),
            'delivered': rows.filter(delivered_at__isnull=False).count(),
            'read': rows.filter(read_at__isnull=False).count(),
            'uncertain': rows.filter(status='uncertain').count(),
            'works_completed': TurnWork.objects.filter(conversation=conversation, status=TurnWork.COMPLETED).count()}

    def retry_due(self, conversation):
        # Scheduler fixture, not a new production retry policy.
        TurnWork.objects.filter(conversation=conversation, status=TurnWork.PENDING).update(next_attempt_at=None)
        TurnWork.objects.filter(conversation=conversation, status=TurnWork.PROCESSING).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1))


@contextmanager
def write_gates():
    """Test only. Never import this context manager from application runtime."""
    from apps.agent.operation_execution import REGISTRY
    with override_settings(AGENT_B7B_CONSENT_ENABLED=True,
            AGENT_OPERATION_EXECUTION_ENABLED={kind: True for kind in REGISTRY}), patch(
            'apps.agent.intake.CONTAINED_WRITES', frozenset()):
        yield
