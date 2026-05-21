"""
Día 6 Fase 4 — Add Organization.public_id

Single-shot migration (pre-beta, sin tráfico productivo):
1. AddField nullable + default=uuid4 (genera UUID por fila existente)
2. RunPython garantiza unicidad para filas pre-existentes
3. AlterField NOT NULL + UNIQUE + index

Reversible: campo nullable temporal, luego se vuelve NOT NULL. El
rollback recrea como nullable; el data loss no aplica porque public_id
es derivado.
"""
from uuid import uuid4

import django.db.models.deletion
from django.db import migrations, models


def _backfill_public_id(apps, schema_editor):
    Organization = apps.get_model('organizations', 'Organization')
    for org in Organization.objects.filter(public_id__isnull=True):
        org.public_id = uuid4()
        org.save(update_fields=['public_id'])


def _noop_reverse(apps, schema_editor):
    # Rollback: limpiar public_id no necesario — al revertir AlterField
    # el campo vuelve a ser nullable y queda intacto.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0007_sync_org_settings_data'),
    ]

    operations = [
        # Paso 1: agregar campo nullable
        migrations.AddField(
            model_name='organization',
            name='public_id',
            field=models.UUIDField(
                null=True,
                editable=False,
                db_index=True,
            ),
        ),
        # Paso 2: backfill para filas pre-existentes
        migrations.RunPython(_backfill_public_id, _noop_reverse),
        # Paso 3: NOT NULL + UNIQUE
        migrations.AlterField(
            model_name='organization',
            name='public_id',
            field=models.UUIDField(
                default=uuid4,
                editable=False,
                unique=True,
                db_index=True,
            ),
        ),
    ]
