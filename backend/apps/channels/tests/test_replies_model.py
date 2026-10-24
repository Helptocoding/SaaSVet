"""WA-RPL-01: nullable citations, protected history and application tenant scope."""
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError, PROTECT
from django.test import TestCase

from apps.agent.models import ContactIdentity, Conversation
from apps.channels.models import ChannelAccount, Message
from apps.channels.replies import resolve_reply_target
from apps.organizations.models import Organization


class MessageReplyModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Replies sintéticas')
        cls.foreign_org = Organization.objects.create(name='Otra clínica replies')
        cls.account = ChannelAccount.objects.create(organization=cls.org, external_account_id='replies-main')
        cls.other_account = ChannelAccount.objects.create(organization=cls.org, external_account_id='replies-second')
        cls.contact = ContactIdentity.objects.create(organization=cls.org, external_id='replies-person')
        cls.other_contact = ContactIdentity.objects.create(organization=cls.org, external_id='replies-other')
        cls.convo = Conversation.objects.create(organization=cls.org, channel_account=cls.account, contact=cls.contact)
        cls.target = cls.make_message()
        foreign_account = ChannelAccount.objects.create(organization=cls.foreign_org, external_account_id='replies-foreign')
        foreign_contact = ContactIdentity.objects.create(organization=cls.foreign_org, external_id='replies-foreign')
        cls.foreign_target = cls.make_message(organization=cls.foreign_org, channel_account=foreign_account,
            contact=foreign_contact, conversation=None)

    @classmethod
    def make_message(cls, **overrides):
        fields = dict(organization=cls.org, channel_account=cls.account, contact=cls.contact,
            conversation=cls.convo, direction='in', author_type='client', status='processed', body='Texto sintético')
        fields.update(overrides)
        return Message.objects.create(**fields)

    def resolve(self, target_id, **overrides):
        scope = dict(organization_id=self.org.pk, channel_account_id=self.account.pk, contact_id=self.contact.pk)
        scope.update(overrides)
        return resolve_reply_target(target_id=target_id, **scope)

    def test_nullable_default_preserves_unquoted_messages(self):
        self.assertIsNone(self.target.reply_to_id)
        self.assertIsNone(self.resolve(None))
        self.target.body = 'Texto sin cita actualizado'
        self.target.save(update_fields=['body'])
        self.target.refresh_from_db()
        self.assertIsNone(self.target.reply_to_id)

    def test_quote_accepts_both_directions_and_reverse_relation(self):
        reply = self.make_message(direction='out', author_type='human_staff', status='pending', reply_to=self.target)
        inbound = self.make_message(reply_to=reply)
        self.assertEqual(list(self.target.direct_replies.all()), [reply])
        self.assertEqual(inbound.reply_to_id, reply.pk)
        self.assertEqual(self.resolve(reply.pk), reply)

    def test_target_cannot_be_deleted_but_reply_can(self):
        reply = self.make_message(reply_to=self.target)
        with self.assertRaises(ProtectedError):
            self.target.delete()
        self.assertTrue(Message.objects.filter(pk=self.target.pk).exists())
        reply.delete()
        self.assertTrue(Message.objects.filter(pk=self.target.pk).exists())

    def test_same_thread_across_closed_and_current_episodes(self):
        historical = Conversation.objects.create(organization=self.org, channel_account=self.account,
            contact=self.contact, state='closed')
        old_target = self.make_message(conversation=historical, direction='out', author_type='system', status='sent')
        reply = self.make_message(reply_to=old_target)
        self.assertNotEqual(reply.conversation_id, old_target.conversation_id)
        self.assertEqual(reply.reply_to_id, old_target.pk)

    def test_hidden_and_discarded_target_remains_valid_history(self):
        reply = self.make_message(reply_to=self.target)
        self.target.status = 'discarded'
        self.target.is_active = False
        self.target.save(update_fields=['status', 'is_active'])
        self.assertEqual(self.resolve(self.target.pk).status, 'discarded')
        reply.body = 'La cita sigue siendo válida'
        reply.save(update_fields=['body'])
        reply.refresh_from_db()
        self.assertEqual(reply.reply_to_id, self.target.pk)

    def test_foreign_target_rejected_by_service_and_normal_save(self):
        with self.assertRaises(ValidationError) as error:
            self.resolve(self.foreign_target.pk)
        self.assertEqual(error.exception.error_dict['reply_to'][0].code, 'invalid_reply_target')
        with self.assertRaises(ValidationError):
            self.make_message(reply_to=self.foreign_target)

    def test_same_org_other_account_rejected(self):
        target = self.make_message(channel_account=self.other_account, conversation=None)
        with self.assertRaises(ValidationError):
            self.resolve(target.pk)
        with self.assertRaises(ValidationError):
            self.make_message(reply_to=target)

    def test_same_account_other_contact_rejected(self):
        target = self.make_message(contact=self.other_contact, conversation=None)
        with self.assertRaises(ValidationError):
            self.resolve(target.pk)
        with self.assertRaises(ValidationError):
            self.make_message(reply_to=target)

    def test_missing_or_malformed_target_rejected(self):
        for target_id in (999999999, 'invalid'):
            with self.subTest(target_id=target_id), self.assertRaises(ValidationError):
                self.resolve(target_id)

    def test_unknown_thread_scope_cannot_resolve_a_quote(self):
        for missing in ('organization_id', 'channel_account_id', 'contact_id'):
            with self.subTest(missing=missing), self.assertRaises(ValidationError):
                self.resolve(self.target.pk, **{missing: None})

    def test_self_fk_does_not_replace_application_tenant_validation(self):
        # A self-FK checks existence, not organization. Demonstrate only inside a
        # rolled-back test transaction; service/normal save reject the same link.
        with transaction.atomic():
            message = Message(organization=self.org, channel_account=self.account, contact=self.contact,
                conversation=self.convo, direction='in', author_type='client', status='processed',
                reply_to=self.foreign_target)
            message.save(validate=False)
            connection.check_constraints(table_names=['channels_message'])
            self.assertEqual(Message.objects.get(pk=message.pk).reply_to_id, self.foreign_target.pk)
            with self.assertRaises(ValidationError):
                self.resolve(message.reply_to_id)
            transaction.set_rollback(True)

    def test_database_still_rejects_a_dangling_reference(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            message = Message(organization=self.org, channel_account=self.account, contact=self.contact,
                conversation=self.convo, direction='in', author_type='client', status='processed', reply_to_id=999999999)
            message.save(validate=False)
            connection.check_constraints(table_names=['channels_message'])

    def test_schema_has_one_reply_index_and_nullable_protected_field(self):
        field = Message._meta.get_field('reply_to')
        self.assertTrue(field.null)
        self.assertTrue(field.blank)
        self.assertFalse(field.has_default())
        self.assertIs(field.remote_field.on_delete, PROTECT)
        self.assertEqual(field.remote_field.related_name, 'direct_replies')
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, Message._meta.db_table)
        indexes = {name for name, value in constraints.items()
            if value.get('index') and value['columns'] == ['reply_to_id']}
        self.assertEqual(indexes, {'message_reply_target'})
        self.assertTrue(any(value.get('foreign_key') == ('channels_message', 'id')
            and value['columns'] == ['reply_to_id'] for value in constraints.values()))
