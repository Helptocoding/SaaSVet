"""
Día 6 Fase 5 — VaccineRecord.public_id

Anexo de seguridad: VaccineRecord se promueve a modelo público porque tiene
endpoint detail `vaccines/<pk>/` editable. Hoy con <int:pk> permite enumeration
cross-org via probe 404 vs 200.

Mismo patrón aditivo 3 pasos.
"""
from uuid import uuid4

from django.db import migrations, models


def _backfill_public_id(apps, schema_editor):
    VaccineRecord = apps.get_model('medical_records', 'VaccineRecord')
    for vr in VaccineRecord.objects.filter(public_id__isnull=True):
        vr.public_id = uuid4()
        vr.save(update_fields=['public_id'])


def _noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('medical_records', '0017_alter_medicalrecord_pet_alter_vaccinerecord_pet'),
    ]

    operations = [
        migrations.AddField(
            model_name='vaccinerecord',
            name='public_id',
            field=models.UUIDField(
                null=True,
                editable=False,
                db_index=True,
            ),
        ),
        migrations.RunPython(_backfill_public_id, _noop_reverse),
        migrations.AlterField(
            model_name='vaccinerecord',
            name='public_id',
            field=models.UUIDField(
                default=uuid4,
                editable=False,
                unique=True,
                db_index=True,
            ),
        ),
    ]
