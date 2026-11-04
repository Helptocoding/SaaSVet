from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('medical_records', '0027_tenant_reference_key')]
    operations = [migrations.AddField('medicalrecord', 'subject_snapshot',
                                      models.JSONField(blank=True, default=dict, editable=False))]
