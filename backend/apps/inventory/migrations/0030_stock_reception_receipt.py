from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0029_presentation_alias_backfill'),
        ('organizations', '0015_state_audit'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [migrations.CreateModel(
        name='StockReceptionReceipt',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('operation_id', models.UUIDField()),
            ('payload_hash', models.CharField(max_length=64)),
            ('result', models.JSONField(null=True)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('actor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='organizations.organization')),
            ('presentation', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='inventory.presentation')),
        ],
        options={'constraints': [models.UniqueConstraint(fields=('organization', 'operation_id'), name='stock_reception_operation_unique')]},
    )]
