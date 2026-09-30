"""Candidate READ capabilities through signed HTTP, worker and sender."""
from datetime import timedelta

from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

from apps.agent.models import ToolExecution, TurnWork
from apps.channels.models import Message
from .b9a_harness import answer, tool
from .test_b9a_e2e import B9AE2ETests


class B9EReadScopeTests(TransactionTestCase):
    setUp = B9AE2ETests.setUp

    def read(self, name, text, *, local=False, **arguments):
        self.h.llm.extend([tool(name, **arguments), answer()])
        inbound = self.h.inbound(text)
        self.h.worker()
        self.h.sender()
        inbound.refresh_from_db()
        self.assertEqual(TurnWork.objects.get(pk=inbound.turn_work_id).status, TurnWork.COMPLETED)
        execution = ToolExecution.objects.filter(
            organization=self.org, conversation=inbound.conversation,
            tool_name=name, http_status=None if local else 200,
            error_code='').order_by('-pk').first()
        self.assertIsNotNone(execution)
        self.assertTrue(Message.objects.filter(
            conversation=inbound.conversation, direction='out', status='sent',
            provider_accepted_at__isnull=False).exists())
        return inbound, execution

    def test_public_clinic_info_with_productive_write_defaults_closed(self):
        self.assertEqual(connection.vendor, 'postgresql')
        inbound, execution = self.read('get_clinic_info', '¿Cuál es el horario de la clínica?',
                                       local=True)
        self.assertEqual(execution.organization_id, inbound.organization_id)
        self.assertTrue(self.h.contexts[-1].inbound_ids)

    def test_public_slot_check_is_read_not_reservation(self):
        day = (timezone.now() + timedelta(days=3)).date().isoformat()
        self.read('check_appointment_slot', '¿Hay un horario para Luna?', date=day, time='10:00')
        from apps.appointments.models import Appointment
        self.assertEqual(Appointment.objects.filter(organization=self.org).count(), 0)

    def test_personal_appointments_scoped_to_verified_owner(self):
        inbound, execution = self.read('get_appointments', '¿Cuáles son mis citas?')
        self.assertEqual(execution.organization_id, self.owner.organization_id)
        self.assertEqual(inbound.conversation.contact.owner_id, self.owner.pk)
        self.assertTrue(any('/api/appointments/' in event['path'] and event['status'] == 200
                            for event in self.h.http))

    def test_personal_vaccine_status_requires_conversation_pet_handle(self):
        self.read('list_my_pets', '¿Cuáles son mis mascotas?')
        inbound, execution = self.read('get_vaccine_status', '¿Qué vacunas tiene Luna?',
                                       pet_handle='mascota_1')
        self.assertEqual(execution.organization_id, self.org.pk)
        self.assertEqual(inbound.conversation.contact.owner_id, self.owner.pk)
        self.assertTrue(any('/api/vaccines/' in event['path'] and event['status'] == 200
                            for event in self.h.http))
