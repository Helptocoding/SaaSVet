"""G07 (orden 8): `TurnDecision.verdict` admite solo los veredictos del árbitro.

Solo cambia `choices` y `blank`, que Django no traslada a la base de datos:
no genera SQL. La validación la aplica `full_clean()` al guardar filas nuevas;
las filas existentes no se reescriben porque la tabla es append-only.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agent', '0029_inbox_read_state'),
    ]

    operations = [
        migrations.AlterField(
            model_name='turndecision',
            name='verdict',
            field=models.CharField(
                blank=True,
                choices=[
                    ('continuar', 'Continuar'),
                    ('desviar', 'Desviar'),
                    ('suplantar', 'Suplantar'),
                    ('abortar', 'Abortar'),
                    ('responder', 'Responder'),
                ],
                max_length=40,
            ),
        ),
    ]
