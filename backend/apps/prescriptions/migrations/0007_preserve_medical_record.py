import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('prescriptions', '0006_alter_prescription_pet')]
    operations = [
        migrations.AlterField(
            model_name='prescription', name='medical_record',
            field=models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                                       related_name='prescription', to='medical_records.medicalrecord'),
        ),
    ]
