import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('prescriptions', '0008_subject_snapshot_schema'),
                    ('billing', '0039_subject_snapshot_backfill')]
    operations = [migrations.AlterField('prescription', 'pet',
        models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                          related_name='prescriptions', to='patients.pet'))]
