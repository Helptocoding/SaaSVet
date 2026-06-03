from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0016_remove_presentation_inventory_p_product_3223d8_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='medicalrecordproduct',
            name='cost_behavior',
            field=models.CharField(
                choices=[
                    ('charge', 'Cobrar al cliente'),
                    ('included', 'Incluido en costo de servicio'),
                ],
                default='charge',
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name='medicalrecordproduct',
            constraint=models.CheckConstraint(
                condition=models.Q(cost_behavior__in=['charge', 'included']),
                name='medicalrecordproduct_cost_behavior_valid',
            ),
        ),
    ]
