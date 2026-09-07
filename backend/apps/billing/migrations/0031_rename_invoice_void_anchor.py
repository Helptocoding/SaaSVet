from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0030_collection_case_public_id'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='invoice',
            name='invoice_cancelled_status_requires_cancelled_at',
        ),
        migrations.RemoveIndex(
            model_name='invoice',
            name='idx_inv_org_status_canc',
        ),
        migrations.RenameField(
            model_name='invoice',
            old_name='cancelled_at',
            new_name='voided_at',
        ),
        migrations.RenameField(
            model_name='invoice',
            old_name='cancelled_at_source',
            new_name='voided_at_source',
        ),
        migrations.AddIndex(
            model_name='invoice',
            index=models.Index(
                fields=['organization', 'status', 'voided_at'],
                name='idx_inv_org_status_void',
            ),
        ),
        migrations.AddConstraint(
            model_name='invoice',
            constraint=models.CheckConstraint(
                condition=(
                    ~models.Q(status='voided')
                    | models.Q(voided_at__isnull=False)
                ),
                name='invoice_voided_status_requires_voided_at',
            ),
        ),
    ]
