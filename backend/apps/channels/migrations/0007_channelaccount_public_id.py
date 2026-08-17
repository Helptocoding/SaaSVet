"""`ChannelAccount.public_id` — la ruta del hilo es COMPUESTA.

`ContactIdentity.public_id` no basta como identificador de la bandeja agrupada:
la fila es por `(contact, channel_account)` y una clínica con dos números tendría
dos filas del mismo contacto colisionando en un solo id. De ahí
`/inbox/threads/<contact_public_id>/<account_public_id>/`.

Y no se expone `external_account_id` en su lugar: es el `phone_number_id` del
proveedor, un identificador suyo que no tiene por qué viajar en nuestras URLs.

Escalonada por el mismo motivo que la de `ContactIdentity`: el `default=uuid4` de
un `AlterField` se evalúa UNA vez y le daría el mismo UUID a todas las filas.
"""
import uuid

from django.db import migrations, models


def populate_public_ids(apps, schema_editor):
    ChannelAccount = apps.get_model('channels', 'ChannelAccount')
    for row in ChannelAccount.objects.filter(public_id__isnull=True):
        row.public_id = uuid.uuid4()
        row.save(update_fields=['public_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('channels', '0006_f2_message_contact_index'),
    ]

    operations = [
        migrations.AddField(
            model_name='channelaccount',
            name='public_id',
            field=models.UUIDField(db_index=True, null=True, editable=False),
        ),
        migrations.RunPython(populate_public_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='channelaccount',
            name='public_id',
            field=models.UUIDField(db_index=True, default=uuid.uuid4,
                                   editable=False, unique=True),
        ),
    ]
