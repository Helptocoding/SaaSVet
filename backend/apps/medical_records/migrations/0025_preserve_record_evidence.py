import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('medical_records', '0024_medicalrecord_originated_from')]
    operations = [
        migrations.AlterField(
            model_name='vitalsigns', name='medical_record',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                    related_name='vital_signs', to='medical_records.medicalrecord'),
        ),
        migrations.AlterField(
            model_name='medicalrecordservice', name='medical_record',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                    related_name='services_used', to='medical_records.medicalrecord'),
        ),
    ]
