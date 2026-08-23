"""Idempotency key for outbound messages created from the Inbox API."""

from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ('channels', '0008_message_semantic_operation'),
    ]

    operations = [
        migrations.AddField(
            model_name='message',
            name='idempotency_key',
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddConstraint(
            model_name='message',
            constraint=models.UniqueConstraint(
                condition=Q(('direction', 'out'),
                            ('author_type', 'human_staff'),
                            ('idempotency_key__isnull', False)),
                fields=('organization', 'idempotency_key'),
                name='message_unique_idempotency_per_org',
            ),
        ),
    ]
