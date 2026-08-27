"""Make terminal-processing notices idempotent per conversation."""

from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ('channels', '0009_message_idempotency_key'),
    ]

    operations = [
        migrations.AlterField(
            model_name='message',
            name='semantic_type',
            field=models.CharField(
                blank=True,
                choices=[('', 'Mensaje general'),
                         ('confirmation', 'Confirmación de operación'),
                         ('operation_receipt', 'Recibo de operación'),
                         ('processing_failure', 'Fallo de procesamiento')],
                default='',
                max_length=24,
            ),
        ),
        migrations.AddConstraint(
            model_name='message',
            constraint=models.UniqueConstraint(
                condition=Q(('direction', 'out'),
                            ('semantic_type', 'processing_failure')),
                fields=('conversation', 'semantic_type'),
                name='message_unique_processing_failure_notice',
            ),
        ),
    ]
