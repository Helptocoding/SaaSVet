from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('medical_records', '0030_backfill_vitals_weight_from_record'),
    ]

    operations = [
        migrations.AddField(
            model_name='medicalrecord',
            name='vet_license_at_close',
            field=models.CharField(blank=True, db_default='', default='', editable=False, max_length=10),
        ),
    ]
