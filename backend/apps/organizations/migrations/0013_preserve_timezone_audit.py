import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('organizations', '0012_remove_organizationsettings_auto_create_invoice_on_done_and_more')]
    operations = [
        migrations.AlterField(
            model_name='organizationtimezoneaudit', name='organization',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                    related_name='timezone_audits', to='organizations.organization'),
        ),
    ]
