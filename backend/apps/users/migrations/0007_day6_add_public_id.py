"""
Día 6 Fase 5 — Add User.public_id

Mismo patrón aditivo 3 pasos que Organization (single-shot pre-beta):
1. AddField nullable + default=uuid4
2. Backfill por fila (asegura cada user con UUID único)
3. AlterField NOT NULL + UNIQUE + index
"""
from uuid import uuid4

from django.db import migrations, models


def _backfill_public_id(apps, schema_editor):
    User = apps.get_model('users', 'User')
    for user in User.objects.filter(public_id__isnull=True):
        user.public_id = uuid4()
        user.save(update_fields=['public_id'])


def _noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0006_alter_user_organization'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='public_id',
            field=models.UUIDField(
                null=True,
                editable=False,
                db_index=True,
            ),
        ),
        migrations.RunPython(_backfill_public_id, _noop_reverse),
        migrations.AlterField(
            model_name='user',
            name='public_id',
            field=models.UUIDField(
                default=uuid4,
                editable=False,
                unique=True,
                db_index=True,
            ),
        ),
    ]
