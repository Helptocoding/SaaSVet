from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('billing', '0028_checkout_dispute'),
    ]

    operations = [
        migrations.AddField(
            model_name='externalprescriptionattestation',
            name='correction_reason',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='externalprescriptionattestation',
            name='supersedes_attestation',
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='superseded_by',
                to='billing.externalprescriptionattestation',
            ),
        ),
    ]
