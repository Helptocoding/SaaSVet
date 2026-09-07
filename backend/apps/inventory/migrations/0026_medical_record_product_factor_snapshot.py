from decimal import Decimal

from django.db import migrations, models


MAX_FACTOR = Decimal('999999.9999')


def backfill_clinical_factor_snapshot(apps, schema_editor):
    MedicalRecordProduct = apps.get_model('inventory', 'MedicalRecordProduct')
    pending = []
    queryset = (
        MedicalRecordProduct._base_manager
        .filter(conversion_factor_snapshot__isnull=True)
        .select_related('presentation')
        .order_by('pk')
    )
    for row in queryset.iterator(chunk_size=1000):
        factor = Decimal(row.presentation.conversion_factor)
        if not factor.is_finite() or factor <= 0 or factor > MAX_FACTOR:
            raise RuntimeError(
                f'MedicalRecordProduct {row.pk} references an invalid conversion factor.'
            )
        row.conversion_factor_snapshot = factor
        pending.append(row)
        if len(pending) == 1000:
            MedicalRecordProduct._base_manager.bulk_update(
                pending, ['conversion_factor_snapshot'], batch_size=1000,
            )
            pending = []
    if pending:
        MedicalRecordProduct._base_manager.bulk_update(
            pending, ['conversion_factor_snapshot'], batch_size=1000,
        )


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0025_presentation_conversion_factor_positive'),
    ]

    operations = [
        migrations.AddField(
            model_name='medicalrecordproduct',
            name='conversion_factor_snapshot',
            field=models.DecimalField(
                decimal_places=4, max_digits=10, null=True,
            ),
        ),
        migrations.RunPython(
            backfill_clinical_factor_snapshot,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='medicalrecordproduct',
            name='conversion_factor_snapshot',
            field=models.DecimalField(decimal_places=4, max_digits=10),
        ),
        migrations.AddConstraint(
            model_name='medicalrecordproduct',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(conversion_factor_snapshot__gt=0)
                    & models.Q(conversion_factor_snapshot__lte=MAX_FACTOR)
                ),
                name='medicalrecordproduct_factor_snapshot_valid',
            ),
        ),
    ]
