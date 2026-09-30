"""READY correction must not transfer old B7 permission into a B8 effect."""
from datetime import timedelta

from django.test import TestCase, override_settings

from apps.agent import durable, services, operation_execution as execution
from apps.agent.models import TurnWork
from apps.channels.models import Message
from .test_operation_execution import ExecutionFixtures
from .b8a_support import effect_count, enabled_test_adapter


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class MonotonicCausalTests(ExecutionFixtures, TestCase):
    def correction(self):
        return services.ingest_inbound_message(self.channel, wamid='mono-correction',
            wa_id='5215512345678', body='No, mejor el viernes')

    def test_preclaim_ready_consent_plus_correction_cannot_authorize_old_digest(self):
        self.proposal()
        digest = self.op.parameters_digest
        a = self.response()
        Message.objects.filter(pk=a.pk).update(available_at=durable.db_now()-timedelta(seconds=1))
        b = self.correction()
        self.assertNotEqual(self.evaluate().decision, 'ACCEPT')
        self.assertEqual(durable.context_for_work(self.witness).inbound_ids, (a.pk, b.pk))
        self.assertEqual(self.op.consent_state, 'INVALIDATED')
        self.assertEqual(self.op.parameters_digest, digest)
        self.context = execution.ExecutionContext(self.witness, self.conv.contact_id, 'create_appointment')
        with enabled_test_adapter():
            self.assertEqual(self.execute().status, 'DENIED')
        self.assertEqual(effect_count(), 0)

    def test_postclaim_correction_keeps_authorization_history_blocks_effect_and_defers(self):
        self.authorized()
        digest = self.op.parameters_digest
        before = durable.context_for_work(self.witness)
        b = self.correction()
        self.assertEqual(before, durable.context_for_work(self.witness))
        self.assertTrue(durable.has_new_input(TurnWork.objects.get(pk=self.witness.turn_work_id)))
        with enabled_test_adapter():
            self.assertEqual(self.execute().status, 'DENIED')
        self.assertEqual(effect_count(), 0)
        self.op.refresh_from_db()
        self.assertEqual(self.op.consent_state, 'AUTHORIZED')
        self.assertEqual(self.op.parameters_digest, digest)
        durable.finalize_turn(self.witness, outputs=[{'body': 'obsolete'}])
        Message.objects.filter(pk=b.pk).update(available_at=durable.db_now())
        second = self.claim()
        self.assertNotEqual(second.turn_work_id, self.witness.turn_work_id)
        self.assertEqual(durable.context_for_work(second).inbound_ids, (b.pk,))
