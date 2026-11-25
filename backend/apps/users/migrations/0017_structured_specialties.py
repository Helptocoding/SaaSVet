"""ADR p68: especialidad estructurada.

Pasa ``User.specialty`` (texto libre) a ``User.specialties`` (lista de códigos del
catálogo cerrado ``apps.users.specialties``): añade la columna, traduce lo que
reconoce del texto anterior y quita la columna vieja. Lo que no se reconoce se
descarta: no hay clínicas ni usuarios reales (CLAUDE.md § Datos y usuarios
reales). El reverso vuelve a crear la columna de texto con las etiquetas.
"""
import django.contrib.postgres.fields
from django.db import migrations, models


def free_text_to_codes(apps, schema_editor):
    from apps.users.specialties import specialties_from_free_text
    User = apps.get_model('users', 'User')
    for user in User.objects.exclude(specialty='').only('pk', 'specialty'):
        codes = specialties_from_free_text(user.specialty)
        if codes:
            User.objects.filter(pk=user.pk).update(specialties=codes)


def codes_to_free_text(apps, schema_editor):
    from apps.users.specialties import specialties_display
    User = apps.get_model('users', 'User')
    for user in User.objects.exclude(specialties=[]).only('pk', 'specialties'):
        User.objects.filter(pk=user.pk).update(
            specialty=specialties_display(user.specialties)[:100])


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0016_staff_absence'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='specialties',
            field=django.contrib.postgres.fields.ArrayField(base_field=models.CharField(choices=[('general_medicine', 'Medicina general'), ('internal_medicine', 'Medicina interna'), ('surgery', 'Cirugía'), ('dermatology', 'Dermatología'), ('ophthalmology', 'Oftalmología'), ('cardiology', 'Cardiología'), ('dentistry', 'Odontología'), ('orthopedics', 'Ortopedia y traumatología'), ('oncology', 'Oncología'), ('neurology', 'Neurología'), ('imaging', 'Imagenología'), ('anesthesiology', 'Anestesiología'), ('behavior', 'Etología (comportamiento)'), ('exotics', 'Animales exóticos'), ('rehabilitation', 'Rehabilitación y fisioterapia'), ('nutrition', 'Nutrición')], max_length=32), blank=True, default=list),
        ),
        migrations.RunPython(free_text_to_codes, codes_to_free_text),
        migrations.RemoveField(
            model_name='user',
            name='specialty',
        ),
    ]
