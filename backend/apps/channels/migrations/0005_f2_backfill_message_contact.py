"""F2 · `Message.contact` — paso 2 de 3: backfill POR LOTES.

`contact_id` se deriva de `conversation.contact_id`. Los mensajes sin
conversación (media huérfana, errores de parseo) quedan con ambos nulos: es el
contrato, no una fila a medias.

Por lotes y con `atomic = False` a propósito: en una clínica con años de
historial esto es la tabla más grande del subsistema, y un UPDATE único la
bloquearía durante todo el recorrido. Es **idempotente** —solo toca las filas que
aún tienen `contact_id IS NULL`— así que un fallo a medias se reintenta sin
duplicar trabajo.
"""
from django.db import migrations

BATCH = 2000


def backfill(apps, schema_editor):
    Message = apps.get_model('channels', 'Message')
    while True:
        batch = list(
            Message.objects.filter(contact__isnull=True,
                                   conversation__isnull=False)
            .values_list('pk', 'conversation__contact_id')[:BATCH]
        )
        if not batch:
            break
        for pk, contact_id in batch:
            Message.objects.filter(pk=pk).update(contact_id=contact_id)


def reverse_noop(apps, schema_editor):
    """No se revierte: dejar el campo poblado es inocuo y el código viejo no lo
    lee. Vaciarlo obligaría a repetir el recorrido para nada."""


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('channels', '0004_f2_message_contact_and_close_reason'),
    ]

    operations = [
        migrations.RunPython(backfill, reverse_noop),
    ]
