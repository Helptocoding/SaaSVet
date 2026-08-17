"""`ContactIdentity.public_id` — la bandeja pasa a navegar por contacto.

Migración ESCALONADA (precedente: `patients/0009_add_public_id_to_exposed_models`):
campo nullable → un UUID DISTINTO por fila → unique. Añadirlo directamente como
unique con `default=uuid4` le daría a todas las filas existentes el MISMO valor
—el default se evalúa una vez en el ALTER— y la restricción fallaría.
"""
import uuid

from django.db import migrations, models


def populate_public_ids(apps, schema_editor):
    ContactIdentity = apps.get_model('agent', 'ContactIdentity')
    for row in ContactIdentity.objects.filter(public_id__isnull=True):
        row.public_id = uuid.uuid4()
        row.save(update_fields=['public_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('agent', '0016_f2_message_contact_and_close_reason'),
    ]

    operations = [
        migrations.AddField(
            model_name='contactidentity',
            name='public_id',
            field=models.UUIDField(db_index=True, null=True, editable=False),
        ),
        migrations.RunPython(populate_public_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='contactidentity',
            name='public_id',
            field=models.UUIDField(db_index=True, default=uuid.uuid4,
                                   editable=False, unique=True),
        ),
    ]
