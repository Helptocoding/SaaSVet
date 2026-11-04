from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('billing', '0041_subject_snapshot_integrity')]
    operations = [
        migrations.AlterField('invoiceauditlog', 'invoice_public_id',
                              models.UUIDField(editable=False)),
    ]
