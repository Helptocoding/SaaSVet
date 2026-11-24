"""ADR p66: función clínica separada del rol.

Aditiva: columna booleana NOT NULL con default de base de datos False (en
PostgreSQL no reescribe la tabla) y un backfill acotado, decidido por el PO:

- VET → True (siempre atiende; el servicio lo mantiene así).
- ADMIN con cédula → True (quien ya puede firmar probablemente atiende).
- El resto queda en False.

`db_default` cubre a una instancia con el código anterior que cree un usuario
después de migrar. El reverso no deshace el backfill: al revertir, la columna
desaparece y con ella el dato.
"""
from django.db import migrations, models


def backfill(apps, schema_editor):
    User = apps.get_model('users', 'User')
    User.objects.filter(role='VET').update(attends_patients=True)
    User.objects.filter(role='ADMIN').exclude(license_number='').update(attends_patients=True)


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0013_user_session_version'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='attends_patients',
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
