"""ADR p65: versión de sesión.

Aditiva: agrega una columna NOT NULL con default de base de datos 0. En
PostgreSQL, una columna con default constante no reescribe la tabla. Sin
backfill: todas las filas quedan en 0, que es lo que vale un token sin claim
`sv`, así que nadie pierde la sesión al desplegar. `db_default` cubre a una
instancia con el código anterior que cree un usuario después de migrar.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0012_user_license_number'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='session_version',
            field=models.PositiveIntegerField(db_default=0, default=0, editable=False),
        ),
    ]
