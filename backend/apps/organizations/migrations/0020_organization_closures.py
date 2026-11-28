"""ADR p70 D6 (plan F2.1): cierres excepcionales por días completos. Tabla nueva, sin datos."""

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0019_retire_settings_without_effect'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='OrganizationClosure',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('start_date', models.DateField()),
                ('end_date', models.DateField()),
                ('reason', models.CharField(max_length=120)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('cancelled_at', models.DateTimeField(blank=True, null=True)),
                ('cancelled_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='closures_cancelled', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='closures_created', to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='closures', to='organizations.organization')),
            ],
            options={
                'ordering': ['start_date', 'pk'],
                'indexes': [models.Index(fields=['organization', 'start_date', 'end_date'], name='org_closure_range_idx')],
                'constraints': [models.CheckConstraint(condition=models.Q(('end_date__gte', models.F('start_date'))), name='org_closure_end_not_before_start'), models.CheckConstraint(condition=models.Q(models.Q(('cancelled_at__isnull', True), ('cancelled_by__isnull', True)), models.Q(('cancelled_at__isnull', False), ('cancelled_by__isnull', False)), _connector='OR'), name='org_closure_cancel_pair')],
            },
        ),
    ]
