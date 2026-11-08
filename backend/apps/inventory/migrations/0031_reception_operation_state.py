"""Reception operations: durable intent columns (schema only, nullable-first)."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0030_stock_reception_receipt'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='stockreceptionreceipt',
            name='product',
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='+', to='inventory.product',
            ),
        ),
        migrations.AddField(
            model_name='stockreceptionreceipt',
            name='payload',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='stockreceptionreceipt',
            name='conversion_factor_snapshot',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='stockreceptionreceipt',
            name='status',
            field=models.CharField(
                choices=[('pending', 'Sin confirmar'), ('confirmed', 'Confirmada'), ('discarded', 'Descartada')],
                default='pending', max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='stockreceptionreceipt',
            name='resolved_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='stockreceptionreceipt',
            name='resolved_by',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='+', to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='stockreceptionreceipt',
            name='discard_reason',
            field=models.CharField(
                blank=True,
                choices=[
                    ('not_received', 'La mercancía no se recibió'),
                    ('already_registered', 'Ya se registró por otra vía'),
                    ('entered_in_error', 'Captura equivocada'),
                ],
                default='', max_length=32,
            ),
        ),
        migrations.AddField(
            model_name='stockreceptionreceipt',
            name='discard_note',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='stockmovement',
            name='reception_operation',
            field=models.ForeignKey(
                blank=True, db_index=False, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='movements', to='inventory.stockreceptionreceipt',
            ),
        ),
    ]
