"""F2 · `Message.contact` — paso 3 de 3: el índice, CONCURRENTLY.

`AddIndexConcurrently` + `atomic = False`: PostgreSQL no admite CREATE INDEX
CONCURRENTLY dentro de una transacción, y es justo lo que permite crearlo sin
bloquear escrituras sobre la tabla más caliente del subsistema.

Va DESPUÉS del backfill (0005) a propósito: indexar una columna que todavía se
está poblando obliga a escribir el índice dos veces.
"""
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('channels', '0005_f2_backfill_message_contact'),
    ]

    operations = [
        AddIndexConcurrently(
            model_name='message',
            index=models.Index(
                fields=['organization', 'contact', 'channel_account',
                        'created_at'],
                name='channels_me_organiz_c00b67_idx',
            ),
        ),
    ]
