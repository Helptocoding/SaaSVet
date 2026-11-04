import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('inventory', '0026_medical_record_product_factor_snapshot')]
    operations = [
        migrations.AlterField(
            model_name='stockmovement', name='product',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='stock_movements', to='inventory.product'),
        ),
        migrations.AlterField(
            model_name='stockmovement', name='presentation',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                    related_name='movements', to='inventory.presentation'),
        ),
        migrations.AlterField(
            model_name='medicalrecordproduct', name='medical_record',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                    related_name='products_used', to='medical_records.medicalrecord'),
        ),
    ]
