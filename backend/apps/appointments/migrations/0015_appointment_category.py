from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('appointments', '0014_appointment_no_overlap_per_vet')]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='category',
            field=models.CharField(
                choices=[
                    ('general_consultation', 'Consulta general'),
                    ('preventive_vaccination', 'Vacunación / preventiva'),
                    ('surgery_procedure', 'Cirugía o procedimiento'),
                    ('grooming', 'Estética'),
                    ('follow_up', 'Seguimiento'),
                    ('emergency', 'Urgencia'),
                    ('other', 'Otro'),
                ],
                default='general_consultation',
                max_length=32,
            ),
        ),
    ]
