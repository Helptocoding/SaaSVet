from decimal import Decimal

from django.db import migrations, models
from django.db.models import Sum


MAX_FACTOR = Decimal('999999.9999')
QUANTUM = Decimal('0.0001')


def _factor_from_physical_or_catalog(row, allocation_totals):
    total = allocation_totals.get(row.pk)
    if total is not None:
        quantity = Decimal(row.quantity)
        if quantity <= 0:
            raise RuntimeError(f'Line {row.pk} has a non-positive quantity.')
        factor = (Decimal(total) / quantity).quantize(QUANTUM)
        if (quantity * factor).quantize(QUANTUM) != Decimal(total).quantize(QUANTUM):
            raise RuntimeError(
                f'Line {row.pk} allocations cannot be represented by one 4-decimal factor.'
            )
        return factor
    medical_record_product = getattr(row, 'medical_record_product', None)
    if medical_record_product is not None:
        return Decimal(medical_record_product.conversion_factor_snapshot)
    return Decimal(row.presentation.conversion_factor)


def _validate_factor(factor, label):
    if not factor.is_finite() or factor <= 0 or factor > MAX_FACTOR:
        raise RuntimeError(f'{label} has an invalid conversion factor snapshot.')
    return factor


def backfill_document_factor_snapshots(apps, schema_editor):
    CheckoutItem = apps.get_model('billing', 'CheckoutItem')
    InvoiceItem = apps.get_model('billing', 'InvoiceItem')
    StockAllocation = apps.get_model('billing', 'StockAllocation')

    checkout_totals = dict(
        StockAllocation._base_manager.values('checkout_item_id')
        .annotate(total=Sum('quantity_base'))
        .values_list('checkout_item_id', 'total')
    )
    invoice_totals = dict(
        StockAllocation._base_manager.values('invoice_item_id')
        .annotate(total=Sum('quantity_base'))
        .values_list('invoice_item_id', 'total')
    )

    checkout_rows = (
        CheckoutItem._base_manager
        .filter(presentation__isnull=False, conversion_factor_snapshot__isnull=True)
        .select_related('presentation', 'medical_record_product')
        .order_by('pk')
    )
    pending = []
    for row in checkout_rows.iterator(chunk_size=1000):
        row.conversion_factor_snapshot = _validate_factor(
            _factor_from_physical_or_catalog(row, checkout_totals),
            f'CheckoutItem {row.pk}',
        )
        pending.append(row)
        if len(pending) == 1000:
            CheckoutItem._base_manager.bulk_update(
                pending, ['conversion_factor_snapshot'], batch_size=1000,
            )
            pending = []
    if pending:
        CheckoutItem._base_manager.bulk_update(
            pending, ['conversion_factor_snapshot'], batch_size=1000,
        )

    invoice_rows = (
        InvoiceItem._base_manager
        .filter(presentation__isnull=False, conversion_factor_snapshot__isnull=True)
        .select_related('presentation')
        .order_by('pk')
    )
    pending = []
    for row in invoice_rows.iterator(chunk_size=1000):
        row.conversion_factor_snapshot = _validate_factor(
            _factor_from_physical_or_catalog(row, invoice_totals),
            f'InvoiceItem {row.pk}',
        )
        pending.append(row)
        if len(pending) == 1000:
            InvoiceItem._base_manager.bulk_update(
                pending, ['conversion_factor_snapshot'], batch_size=1000,
            )
            pending = []
    if pending:
        InvoiceItem._base_manager.bulk_update(
            pending, ['conversion_factor_snapshot'], batch_size=1000,
        )


def factor_snapshot_constraint(prefix):
    return models.CheckConstraint(
        condition=(
            models.Q(
                presentation__isnull=True,
                conversion_factor_snapshot__isnull=True,
            )
            | models.Q(
                presentation__isnull=False,
                conversion_factor_snapshot__gt=0,
                conversion_factor_snapshot__lte=MAX_FACTOR,
            )
        ),
        name=prefix,
    )


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0026_medical_record_product_factor_snapshot'),
        ('billing', '0034_contract_legacy_invoice_anchors'),
    ]

    operations = [
        migrations.AddField(
            model_name='checkoutitem',
            name='conversion_factor_snapshot',
            field=models.DecimalField(
                blank=True, decimal_places=4, max_digits=10, null=True,
            ),
        ),
        migrations.AddField(
            model_name='invoiceitem',
            name='conversion_factor_snapshot',
            field=models.DecimalField(
                blank=True, decimal_places=4, max_digits=10, null=True,
            ),
        ),
        migrations.RunPython(
            backfill_document_factor_snapshots,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name='checkoutitem',
            constraint=factor_snapshot_constraint(
                'billing_checkout_item_factor_snapshot_valid'
            ),
        ),
        migrations.AddConstraint(
            model_name='invoiceitem',
            constraint=factor_snapshot_constraint(
                'billing_invoice_item_factor_snapshot_valid'
            ),
        ),
        migrations.RemoveConstraint(
            model_name='stockdispositionevent',
            name='billing_stock_disposition_per_credit_line',
        ),
        migrations.AddConstraint(
            model_name='stockdispositionevent',
            constraint=models.UniqueConstraint(
                fields=('credit_note_item', 'allocation'),
                condition=models.Q(credit_note_item__isnull=False),
                name='billing_stock_disposition_credit_allocation_unique',
            ),
        ),
        migrations.RemoveConstraint(
            model_name='prescriptionfulfillmentevent',
            name='billing_rx_return_once_per_credit_line',
        ),
        migrations.AddConstraint(
            model_name='prescriptionfulfillmentevent',
            constraint=models.UniqueConstraint(
                fields=('credit_note_item', 'allocation'),
                condition=models.Q(credit_note_item__isnull=False),
                name='billing_rx_return_credit_allocation_unique',
            ),
        ),
    ]
