"""ADR p68: verificación en dos pasos.

Aditiva: tabla nueva ``users_usermfa`` (vacía) y dos tipos más en el historial
(``mfa_enabled``, ``mfa_disabled``). Sin backfill.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0017_structured_specialties'),
    ]

    operations = [
        migrations.AlterField(
            model_name='staffaccessevent',
            name='kind',
            field=models.CharField(choices=[('created', 'Alta'), ('profile_updated', 'Edición de datos'), ('role_changed', 'Cambio de rol'), ('deactivated', 'Desactivación'), ('reactivated', 'Reactivación'), ('password_reset', 'Restablecimiento de contraseña'), ('absence_added', 'Ausencia registrada'), ('absence_cancelled', 'Ausencia cancelada'), ('appointments_reassigned', 'Citas reasignadas'), ('mfa_enabled', 'Verificación en dos pasos activada'), ('mfa_disabled', 'Verificación en dos pasos desactivada')], max_length=32),
        ),
        migrations.CreateModel(
            name='UserMFA',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('secret_encrypted', models.TextField(blank=True, default='')),
                ('pending_secret_encrypted', models.TextField(blank=True, default='')),
                ('pending_created_at', models.DateTimeField(blank=True, null=True)),
                ('enabled_at', models.DateTimeField(blank=True, null=True)),
                ('last_used_step', models.BigIntegerField(blank=True, null=True)),
                ('recovery_code_hashes', models.JSONField(blank=True, default=list)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='mfa', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'constraints': [models.CheckConstraint(condition=models.Q(('enabled_at__isnull', True), models.Q(('secret_encrypted', ''), _negated=True), _connector='OR'), name='user_mfa_enabled_has_secret')],
            },
        ),
    ]
