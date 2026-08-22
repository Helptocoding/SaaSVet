"""Semantic message roles for deterministic confirmation and receipts."""

from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ('channels', '0007_channelaccount_public_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='message',
            name='semantic_type',
            field=models.CharField(
                blank=True, choices=[('', 'Mensaje general'),
                                     ('confirmation', 'Confirmación de operación'),
                                     ('operation_receipt', 'Recibo de operación')],
                default='', max_length=24,
            ),
        ),
        migrations.AddField(
            model_name='message',
            name='operation_key',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddConstraint(
            model_name='message',
            constraint=models.UniqueConstraint(
                condition=Q(('direction', 'out'),
                            ('semantic_type', 'operation_receipt'))
                & ~Q(('operation_key', '')),
                fields=('conversation', 'operation_key'),
                name='message_unique_operation_receipt',
            ),
        ),
        migrations.AddIndex(
            model_name='message',
            index=models.Index(
                fields=['conversation', 'semantic_type', 'created_at'],
                name='channels_me_convers_c68da0_idx',
            ),
        ),
    ]
