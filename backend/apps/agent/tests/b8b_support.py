"""Controlled gates around the REAL runtime registry. No fake domain adapter."""
from contextlib import contextmanager
from unittest.mock import patch
from django.test import override_settings
from .test_operation_consent import ConsentFixtures
from .test_operation_execution import ExecutionFixtures
from apps.agent import operation_execution as execution
from apps.appointments.models import Appointment
from apps.agent import durable, sender
from apps.agent import operation_consent as consent
from apps.agent.services import ingest_inbound_message
from apps.channels.models import Message
from apps.channels.events import normalize_whatsapp_event, EVENT_METADATA_KEY
from apps.channels.providers import SendResult
from uuid import uuid4


@contextmanager
def enabled_create():
    with patch('apps.agent.intake.write_is_contained', return_value=False), override_settings(
            AGENT_B7B_CONSENT_ENABLED=True,
            AGENT_OPERATION_EXECUTION_ENABLED={'CREATE_APPOINTMENT': True}):
        yield execution.REGISTRY['CREATE_APPOINTMENT'].adapter


class AppointmentExecutionFixtures(ConsentFixtures):
    authorized = ExecutionFixtures.authorized
    execute = ExecutionFixtures.execute
    tamper = ExecutionFixtures.tamper
    takeover = ExecutionFixtures.takeover
    correct = ExecutionFixtures.correct

    def inbound(self, text):
        message = ingest_inbound_message(self.channel, wamid='wamid.' + uuid4().hex,
            wa_id=getattr(self, 'wa_id', '5215512345678'), body=text)
        Message.objects.filter(pk=message.pk).update(available_at=None)
        return message

    def response(self, text=None, reply_to=None, **extra):
        text = text if text is not None else 'CONFIRMAR ' + consent.proposal_token(self.op)
        raw = {'type': 'text', 'text': {'body': text}}
        if reply_to:
            raw['context'] = {'id': reply_to}
        event = normalize_whatsapp_event(raw)
        message = ingest_inbound_message(self.channel, wamid='wamid.' + uuid4().hex,
            wa_id=self.conv.contact.external_id, body=text,
            raw={EVENT_METADATA_KEY: event.projection(), **extra})
        Message.objects.filter(conversation=message.conversation, direction='in',
            status='pending', turn_work__isnull=True).update(available_at=None)
        return message

    def emit(self):
        claim = sender.claim_message(self.msg.pk, organization_id=self.org.pk,
                                     channel_account_id=self.channel.pk)
        self.assertIsNotNone(claim)
        self.assertIsNotNone(sender.admit_dispatch(claim))
        sender.finalize_dispatch(claim, SendResult('accepted', provider_id='wamid.b8b.' + uuid4().hex))
        self.msg.refresh_from_db()

    def denied(self, reason=None):
        with enabled_create():
            result = self.execute()
        self.assertEqual(result.status, 'DENIED', result)
        if reason:
            self.assertEqual(result.reason, reason)
        self.assertEqual(Appointment.all_objects.filter(source_operation__isnull=False).count(), 0)
        return result
