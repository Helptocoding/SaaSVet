"""ADR p67: ausencias de integrantes y nuevos tipos del historial.

Aditiva: tabla nueva ``users_staffabsence`` (vacía) y ``StaffAccessEvent.kind``
pasa de 20 a 32 caracteres con tres valores más (ausencia registrada, ausencia
cancelada, citas reasignadas). Ampliar un ``varchar`` en PostgreSQL no reescribe
la tabla. Sin backfill.
"""

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0015_state_audit'),
        ('users', '0015_staffaccessevent'),
    ]

    operations = [
        migrations.AlterField(
            model_name='staffaccessevent',
            name='kind',
            field=models.CharField(choices=[('created', 'Alta'), ('profile_updated', 'Edición de datos'), ('role_changed', 'Cambio de rol'), ('deactivated', 'Desactivación'), ('reactivated', 'Reactivación'), ('password_reset', 'Restablecimiento de contraseña'), ('absence_added', 'Ausencia registrada'), ('absence_cancelled', 'Ausencia cancelada'), ('appointments_reassigned', 'Citas reasignadas')], max_length=32),
        ),
        migrations.CreateModel(
            name='StaffAbsence',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('start_date', models.DateField()),
                ('end_date', models.DateField()),
                ('kind', models.CharField(choices=[('vacation', 'Vacaciones'), ('training', 'Capacitación'), ('leave', 'Permiso'), ('other', 'Otro')], default='other', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('cancelled_at', models.DateTimeField(blank=True, null=True)),
                ('cancelled_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='absences_cancelled', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='absences_created', to=settings.AUTH_USER_MODEL)),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='absences', to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='staff_absences', to='organizations.organization')),
            ],
            options={
                'ordering': ['start_date', 'pk'],
                'indexes': [models.Index(fields=['organization', 'member', 'start_date'], name='staff_absence_member_idx'), models.Index(fields=['organization', 'start_date', 'end_date'], name='staff_absence_range_idx')],
                'constraints': [models.CheckConstraint(condition=models.Q(('end_date__gte', models.F('start_date'))), name='staff_absence_end_not_before_start'), models.CheckConstraint(condition=models.Q(models.Q(('cancelled_at__isnull', True), ('cancelled_by__isnull', True)), models.Q(('cancelled_at__isnull', False), ('cancelled_by__isnull', False)), _connector='OR'), name='staff_absence_cancel_pair')],
            },
        ),
    ]
