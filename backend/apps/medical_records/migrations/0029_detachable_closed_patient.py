import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('medical_records', '0028_subject_snapshot_schema'),
                    ('billing', '0039_subject_snapshot_backfill')]
    operations = [migrations.AlterField('medicalrecord', 'pet',
        models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                          related_name='medical_records', to='patients.pet'))]
