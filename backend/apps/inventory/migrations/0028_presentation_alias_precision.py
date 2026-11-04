from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('inventory', '0027_preserve_stock_and_consumption')]

    operations = [
        migrations.AlterField(
            model_name='presentation',
            name='quantity',
            field=models.DecimalField(decimal_places=4, default=1, max_digits=12),
        ),
    ]
