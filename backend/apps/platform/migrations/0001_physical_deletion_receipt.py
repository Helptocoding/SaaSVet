from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [('billing', '0040_detachable_billed_subjects'),
                    ('organizations', '0015_state_audit')]
    operations = [migrations.CreateModel(name='PhysicalDeletionReceipt', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False,
                                   verbose_name='ID')),
        ('idempotency_key', models.UUIDField(unique=True)),
        ('confirmation_digest', models.CharField(max_length=64, unique=True)),
        ('actor_id', models.UUIDField()),
        ('actor_role', models.CharField(default='ADMIN_SAAS', max_length=16)),
        ('organization_id', models.UUIDField()),
        ('target_type', models.CharField(max_length=16)),
        ('target_id', models.UUIDField()),
        ('action', models.CharField(default='physical_delete', max_length=32)),
        ('reason', models.CharField(max_length=255)),
        ('payload_digest', models.CharField(max_length=64)),
        ('impact_digest', models.CharField(max_length=64)),
        ('impact', models.JSONField(default=dict)),
        ('outcome', models.CharField(default='deleted', max_length=16)),
        ('occurred_at', models.DateTimeField(auto_now_add=True)),
    ])]
