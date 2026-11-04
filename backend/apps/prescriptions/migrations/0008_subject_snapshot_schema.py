from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('prescriptions', '0007_preserve_medical_record')]
    operations = [migrations.AddField('prescription', 'subject_snapshot',
                                      models.JSONField(blank=True, default=dict, editable=False))]
