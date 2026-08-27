"""Persist the inbound message that authorized a post-receipt task goal."""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('agent', '0019_conversation_intake_path'),
        ('channels', '0009_message_idempotency_key'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversationgoal',
            name='authorization_message',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='authorized_goals',
                to='channels.message',
            ),
        ),
    ]
