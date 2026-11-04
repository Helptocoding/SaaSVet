from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('billing', '0036_preserve_invoice_audit')]
    operations = [migrations.AddConstraint('checkout', models.UniqueConstraint(
        fields=['id', 'organization'], name='checkout_id_org_ref'))]
