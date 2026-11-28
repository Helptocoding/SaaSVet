"""ADR p70 D9: historial de cambios de Configuración.

Crea `OrganizationConfigEvent`, copia cada `OrganizationTimezoneAudit` como un
evento `timezone_changed` (mismo autor y fecha) y retira ese modelo: no quedan
dos formas de auditar lo mismo. Sin clínicas reales, la copia solo lleva lo de
las bases de desarrollo, CI y la demo.
"""
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def copy_timezone_audits(apps, schema_editor):
    Audit = apps.get_model('organizations', 'OrganizationTimezoneAudit')
    Event = apps.get_model('organizations', 'OrganizationConfigEvent')
    Event.objects.bulk_create([
        Event(
            organization_id=audit.organization_id,
            actor_id=audit.changed_by_id,
            occurred_at=audit.changed_at,
            kind='timezone_changed',
            changes={'timezone': [audit.old_timezone, audit.new_timezone]},
        )
        for audit in Audit.objects.order_by('changed_at', 'pk').iterator()
    ])


def copy_events_back(apps, schema_editor):
    Audit = apps.get_model('organizations', 'OrganizationTimezoneAudit')
    Event = apps.get_model('organizations', 'OrganizationConfigEvent')
    Audit.objects.bulk_create([
        Audit(
            organization_id=event.organization_id,
            changed_by_id=event.actor_id,
            changed_at=event.occurred_at,
            old_timezone=event.changes['timezone'][0],
            new_timezone=event.changes['timezone'][1],
        )
        for event in Event.objects.filter(kind='timezone_changed').iterator()
    ])


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0017_normalize_timezones_to_catalog'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='OrganizationConfigEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('occurred_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('kind', models.CharField(choices=[('clinic_updated', 'Datos de la clínica'), ('timezone_changed', 'Zona horaria'), ('rules_updated', 'Reglas de operación'), ('schedule_replaced', 'Horario'), ('closure_added', 'Cierre registrado'), ('closure_cancelled', 'Cierre cancelado'), ('service_created', 'Servicio creado'), ('service_updated', 'Servicio editado'), ('service_activated', 'Servicio activado'), ('service_deactivated', 'Servicio desactivado'), ('service_deleted', 'Servicio eliminado')], max_length=32)),
                ('subject', models.JSONField(blank=True, default=dict)),
                ('changes', models.JSONField(blank=True, default=dict)),
                ('request_id', models.CharField(blank=True, default='', max_length=64)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='config_events', to='organizations.organization')),
            ],
            options={
                'ordering': ['-occurred_at', '-pk'],
            },
        ),
        migrations.AddIndex(
            model_name='organizationconfigevent',
            index=models.Index(fields=['organization', '-occurred_at'], name='org_config_event_org_idx'),
        ),
        migrations.RunPython(copy_timezone_audits, copy_events_back),
        migrations.DeleteModel(
            name='OrganizationTimezoneAudit',
        ),
    ]
