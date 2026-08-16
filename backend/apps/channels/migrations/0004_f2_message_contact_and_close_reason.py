"""F2 · `Message.contact` — paso 1 de 3: solo el campo, nullable.

Expand-first (plan de continuidad, F2). Los tres pasos van SEPARADOS y el orden
no es intercambiable:

  0004  AddField nullable            ← esta
  0005  backfill POR LOTES
  0006  índice CONCURRENTLY

Hacer índice y backfill en la misma migración bloquea la tabla cuando crezca, y
el código viejo no lee el campo nuevo — así que entre 0004 y 0006 el sistema
sigue funcionando y el rollback es seguro.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agent', '0016_f2_message_contact_and_close_reason'),
        ('channels', '0003_message_process_attempts'),
    ]

    operations = [
        migrations.AddField(
            model_name='message',
            name='contact',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='messages', to='agent.contactidentity',
            ),
        ),
    ]
