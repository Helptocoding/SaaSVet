import django.db.models.deletion
from django.db import migrations, models


def backfill_invoice_uuid(apps, schema_editor):
    Audit = apps.get_model('billing', 'InvoiceAuditLog')
    for audit in Audit.objects.filter(invoice_public_id__isnull=True).select_related('invoice').iterator(chunk_size=500):
        Audit.objects.filter(pk=audit.pk, invoice_public_id__isnull=True).update(
            invoice_public_id=audit.invoice.public_id,
        )


class Migration(migrations.Migration):
    dependencies = [('billing', '0035_unit_snapshots_and_multilot_returns')]
    operations = [
        migrations.AddField(
            model_name='invoiceauditlog', name='invoice_public_id',
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.RunPython(backfill_invoice_uuid, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='invoiceauditlog', name='invoice',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                    related_name='audit_logs', to='billing.invoice'),
        ),
    ]
