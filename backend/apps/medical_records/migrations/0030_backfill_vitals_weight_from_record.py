"""M03 (orden 7): VitalSigns pasa a ser la única fuente del peso.

Copia `MedicalRecord.weight` a un `VitalSigns` solo en las consultas que tienen
peso legacy y ningún signo vital con peso. `recorded_at` toma el alta de la
consulta y `recorded_by` queda vacío: nadie registró ese signo vital como tal, y
atribuírselo a alguien inventaría autoría.

Idempotente: una segunda pasada ya no encuentra consultas pendientes. La reversa
no hace nada, porque una fila copiada no se distingue de una capturada.
"""
from django.db import migrations


def backfill(apps, schema_editor):
    MedicalRecord = apps.get_model('medical_records', 'MedicalRecord')
    VitalSigns = apps.get_model('medical_records', 'VitalSigns')
    pending = (
        MedicalRecord._base_manager
        .filter(weight__isnull=False)
        .exclude(vital_signs__weight__isnull=False)
        .order_by('pk')
        .values_list('pk', 'organization_id', 'weight', 'created_at')
    )
    VitalSigns._base_manager.bulk_create(
        [
            VitalSigns(
                organization_id=organization_id,
                medical_record_id=record_id,
                weight=weight,
                recorded_at=created_at,
                recorded_by=None,
            )
            for record_id, organization_id, weight, created_at in pending.iterator(chunk_size=500)
        ],
        batch_size=500,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('medical_records', '0029_detachable_closed_patient'),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
