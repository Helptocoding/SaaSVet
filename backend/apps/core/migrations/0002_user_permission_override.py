"""ADR p69: permisos por integrante sobre su rol.

Aditiva: tabla nueva ``core_userpermissionoverride`` (vacía). Sin backfill: no hay
clínicas ni usuarios reales (CLAUDE.md § Datos y usuarios reales).
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_rbac_models'),
        ('organizations', '0015_state_audit'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='UserPermissionOverride',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('effect', models.CharField(choices=[('grant', 'Concedido'), ('revoke', 'Quitado')], max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('granted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='permission_overrides_granted', to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='permission_overrides', to='organizations.organization')),
                ('permission', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.permission')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='permission_overrides', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'UserPermissionOverride',
                'verbose_name_plural': 'UserPermissionOverrides',
                'constraints': [models.UniqueConstraint(fields=('user', 'permission'), name='user_permission_override_unique')],
            },
        ),
    ]
