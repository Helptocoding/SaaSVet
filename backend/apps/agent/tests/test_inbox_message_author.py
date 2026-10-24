"""WA-GRP-01: public author identity, without DB access or migrations."""
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase

from apps.agent.serializers import MessageSerializer
from apps.channels.models import Message


class InboxMessageAuthorTests(SimpleTestCase):
    def human_message(self, author):
        return Message(direction=Message.DIRECTION_OUT,
                       author_type=Message.AUTHOR_HUMAN, human_author=author)

    def test_homonymous_staff_have_distinct_public_identity(self):
        first = get_user_model()(id=101, public_id=uuid4(), first_name='Recepción')
        second = get_user_model()(id=102, public_id=uuid4(), first_name='Recepción')
        payloads = MessageSerializer([self.human_message(first), self.human_message(second)], many=True).data
        self.assertEqual(payloads[0]['human_author_name'], payloads[1]['human_author_name'])
        self.assertEqual(payloads[0]['human_author_public_id'], str(first.public_id))
        self.assertEqual(payloads[1]['human_author_public_id'], str(second.public_id))
        self.assertNotIn('human_author_id', payloads[0])

    def test_identity_is_stable_across_messages_and_status_changes(self):
        author = get_user_model()(id=101, public_id=uuid4(), username='reception')
        first, second = self.human_message(author), self.human_message(author)
        first.status, second.status = Message.STATUS_PENDING, Message.STATUS_READ
        self.assertEqual(MessageSerializer(first).data['human_author_public_id'],
                         MessageSerializer(second).data['human_author_public_id'])

    def test_nonhuman_or_missing_author_has_no_public_identity(self):
        author = get_user_model()(id=101, public_id=uuid4(), username='reception')
        for direction, author_type, staff in [
            (Message.DIRECTION_IN, Message.AUTHOR_HUMAN, author),
            (Message.DIRECTION_OUT, Message.AUTHOR_AGENT, author),
            (Message.DIRECTION_OUT, Message.AUTHOR_SYSTEM, author),
            (Message.DIRECTION_OUT, Message.AUTHOR_HUMAN, None),
        ]:
            with self.subTest(direction=direction, author_type=author_type, staff=bool(staff)):
                message = Message(direction=direction, author_type=author_type, human_author=staff)
                self.assertIsNone(MessageSerializer(message).data['human_author_public_id'])

    def test_public_identity_is_read_only(self):
        self.assertTrue(MessageSerializer().fields['human_author_public_id'].read_only)
