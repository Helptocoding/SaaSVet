"""ADR p68: especialidad opcional del servicio, del catálogo único de
``apps.users.specialties``. Aditiva, sin backfill (vacía = sin especialidad)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0043_generic_subject_relink'),
    ]

    operations = [
        migrations.AddField(
            model_name='service',
            name='specialty',
            field=models.CharField(blank=True, choices=[('general_medicine', 'Medicina general'), ('internal_medicine', 'Medicina interna'), ('surgery', 'Cirugía'), ('dermatology', 'Dermatología'), ('ophthalmology', 'Oftalmología'), ('cardiology', 'Cardiología'), ('dentistry', 'Odontología'), ('orthopedics', 'Ortopedia y traumatología'), ('oncology', 'Oncología'), ('neurology', 'Neurología'), ('imaging', 'Imagenología'), ('anesthesiology', 'Anestesiología'), ('behavior', 'Etología (comportamiento)'), ('exotics', 'Animales exóticos'), ('rehabilitation', 'Rehabilitación y fisioterapia'), ('nutrition', 'Nutrición')], default='', max_length=32),
        ),
    ]
