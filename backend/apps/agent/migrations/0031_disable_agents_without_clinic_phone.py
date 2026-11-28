"""INV-L (ADR p70 D2): apaga los agentes cuya clínica no tiene teléfono válido.

Después de esta migración se cumple en toda base que ningún `AgentSettings`
encendido pertenece a una organización sin teléfono válido. Desde aquí lo
mantienen `Organization.save()` y `AgentSettings.save()`. No hay datos reales
(`CLAUDE.md`): apagar es la normalización correcta, no una pérdida.

Solo datos, sin cambio de esquema. Revertirla no vuelve a encender nada.
"""
from django.db import migrations


def disable_agents_without_phone(apps, schema_editor):
    from apps.core.validators import is_valid_mx_phone

    AgentSettings = apps.get_model('agent', 'AgentSettings')
    offending = [
        pk for pk, phone in AgentSettings.objects.filter(enabled=True)
        .values_list('pk', 'organization__phone')
        if not is_valid_mx_phone(phone or '')
    ]
    if offending:
        AgentSettings.objects.filter(pk__in=offending).update(enabled=False)


class Migration(migrations.Migration):

    dependencies = [
        ('agent', '0030_turndecision_verdict_choices'),
        ('organizations', '0016_normalize_invalid_phones'),
    ]

    operations = [
        migrations.RunPython(disable_agents_without_phone, migrations.RunPython.noop),
    ]
