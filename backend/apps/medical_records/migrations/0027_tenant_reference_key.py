from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('medical_records', '0026_vet_close_snapshot')]
    operations = [migrations.AddConstraint('medicalrecord', models.UniqueConstraint(
        fields=['id', 'organization'], name='medicalrecord_id_org_ref'))]
