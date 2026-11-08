"""Reception operations: enforce the state machine once existing rows are classified."""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('inventory', '0032_reception_operation_backfill')]

    operations = [
        migrations.AlterField(
            model_name='stockreceptionreceipt',
            name='product',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name='+', to='inventory.product',
            ),
        ),
        migrations.AddConstraint(
            model_name='stockreceptionreceipt',
            constraint=models.UniqueConstraint(
                condition=models.Q(status='pending'),
                fields=('organization', 'actor', 'product'),
                name='stock_reception_one_pending',
            ),
        ),
        migrations.AddConstraint(
            model_name='stockreceptionreceipt',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(status='pending', result__isnull=True, resolved_at__isnull=True)
                    | models.Q(status='confirmed', result__isnull=False)
                    | (
                        models.Q(status='discarded', result__isnull=True, resolved_at__isnull=False)
                        & ~models.Q(discard_reason='')
                    )
                ),
                name='stock_reception_state_consistent',
            ),
        ),
        migrations.AddIndex(
            model_name='stockreceptionreceipt',
            index=models.Index(
                fields=['organization', 'actor', '-created_at', '-id'],
                name='idx_reception_org_actor',
            ),
        ),
        migrations.AddIndex(
            model_name='stockreceptionreceipt',
            index=models.Index(
                fields=['organization', '-created_at', '-id'],
                name='idx_reception_org_created',
            ),
        ),
        migrations.AddIndex(
            model_name='stockmovement',
            index=models.Index(
                condition=models.Q(reception_operation__isnull=False),
                fields=['reception_operation'],
                name='idx_stockmov_reception_op',
            ),
        ),
    ]
