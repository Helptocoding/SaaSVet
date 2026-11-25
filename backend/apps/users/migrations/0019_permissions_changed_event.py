"""ADR p69: tipo de evento ``permissions_changed`` en el historial de Equipo.
Solo cambia las opciones del campo; no toca filas."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0018_user_mfa'),
    ]

    operations = [
        migrations.AlterField(
            model_name='staffaccessevent',
            name='kind',
            field=models.CharField(choices=[('created', 'Alta'), ('profile_updated', 'Edición de datos'), ('role_changed', 'Cambio de rol'), ('deactivated', 'Desactivación'), ('reactivated', 'Reactivación'), ('password_reset', 'Restablecimiento de contraseña'), ('absence_added', 'Ausencia registrada'), ('absence_cancelled', 'Ausencia cancelada'), ('appointments_reassigned', 'Citas reasignadas'), ('mfa_enabled', 'Verificación en dos pasos activada'), ('mfa_disabled', 'Verificación en dos pasos desactivada'), ('permissions_changed', 'Cambio de permisos')], max_length=32),
        ),
    ]
