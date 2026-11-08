"""Classify receipts written by 0030 without inventing what they never recorded.

A 0030 receipt with a result committed together with its stock, so it is confirmed.
Its payload, per-line quantities and ledger link were never stored and are NOT
rebuilt: the result holds cumulative balances and the hash is one-way. Movements
keep reception_operation NULL for the same reason.

0030 writes the receipt and its result in one transaction, so a committed row
without a result should not exist. If one does, nothing proves it was applied: it
stays pending without a payload, which can only be discarded by a person.
"""
from django.db import migrations

BATCH_SIZE = 500


def classify_existing_receipts(apps, schema_editor):
    Receipt = apps.get_model('inventory', 'StockReceptionReceipt')
    batch = []
    queryset = Receipt.objects.select_related('presentation').order_by('pk')
    for receipt in queryset.iterator(chunk_size=BATCH_SIZE):
        receipt.product_id = receipt.presentation.product_id
        receipt.status = 'pending' if receipt.result is None else 'confirmed'
        batch.append(receipt)
        if len(batch) >= BATCH_SIZE:
            Receipt.objects.bulk_update(batch, ['product', 'status'])
            batch = []
    if batch:
        Receipt.objects.bulk_update(batch, ['product', 'status'])


def refuse_rollback_with_open_intents(apps, schema_editor):
    """Rolling back would drop the payload an open intent needs to be completed."""
    Receipt = apps.get_model('inventory', 'StockReceptionReceipt')
    pending = Receipt.objects.filter(status='pending', payload__isnull=False).count()
    if pending:
        raise RuntimeError(
            f'{pending} recepciones sin resolver: complétalas o descártalas antes de revertir.'
        )


class Migration(migrations.Migration):
    dependencies = [('inventory', '0031_reception_operation_state')]

    operations = [
        migrations.RunPython(classify_existing_receipts, refuse_rollback_with_open_intents),
    ]
