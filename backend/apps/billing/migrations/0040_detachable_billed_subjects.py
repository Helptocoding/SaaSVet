import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('billing', '0039_subject_snapshot_backfill'),
                    ('medical_records', '0029_detachable_closed_patient'),
                    ('prescriptions', '0009_detachable_prescription_patient')]
    operations = [
        migrations.AlterField('invoice', 'owner', models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
            related_name='invoices', to='patients.owner')),
        migrations.AlterField('invoice', 'pet', models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
            related_name='invoices', to='patients.pet')),
        migrations.AlterField('checkout', 'customer', models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
            related_name='checkouts', to='patients.owner')),
        migrations.AlterField('checkout', 'pet', models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
            related_name='checkouts', to='patients.pet')),
    ]
