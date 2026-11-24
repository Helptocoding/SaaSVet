"""ADR p66: historial de accesos de Equipo (tabla nueva, de solo inserción).

Aditiva: crea una tabla vacía; no toca filas existentes. Los eventos anteriores
a esta migración no existen (solo quedaron en los logs).
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0015_state_audit'),
        ('users', '0014_user_attends_patients'),
    ]

    operations = [
        migrations.CreateModel(
            name='StaffAccessEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('created', 'Alta'), ('profile_updated', 'Edición de datos'), ('role_changed', 'Cambio de rol'), ('deactivated', 'Desactivación'), ('reactivated', 'Reactivación'), ('password_reset', 'Restablecimiento de contraseña')], max_length=20)),
                ('changes', models.JSONField(blank=True, default=dict)),
                ('request_id', models.CharField(blank=True, default='', max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='staff_actions', to=settings.AUTH_USER_MODEL)),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='access_events', to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='staff_access_events', to='organizations.organization')),
            ],
            options={
                'ordering': ['-created_at', '-pk'],
                'indexes': [models.Index(fields=['organization', 'member', '-created_at'], name='staff_event_org_member_idx')],
            },
        ),
    ]
