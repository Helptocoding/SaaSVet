"""INV-L (ADR p70 D2): vacía los teléfonos de clínica que no son válidos.

Desde p70, `Organization.save()` rechaza un teléfono no vacío que no sea un
número de 10 dígitos sin relleno. Las filas guardadas antes de que existiera esa
regla (por ejemplo `"5"`) harían fallar cualquier guardado posterior de su
organización. No hay datos reales (`CLAUDE.md`): se normalizan sin conservar el
valor. La migración del agente (0031) apaga después los agentes que queden sin
teléfono válido.

Solo datos, sin cambio de esquema. Revertirla no restaura los valores.
"""
from django.db import migrations


def clear_invalid_phones(apps, schema_editor):
    from apps.core.validators import is_valid_mx_phone

    Organization = apps.get_model('organizations', 'Organization')
    invalid = [
        pk for pk, phone in Organization.objects.exclude(phone='').values_list('pk', 'phone')
        if not is_valid_mx_phone(phone)
    ]
    if invalid:
        Organization.objects.filter(pk__in=invalid).update(phone='')


class Migration(migrations.Migration):

    dependencies = [('organizations', '0015_state_audit')]

    operations = [
        migrations.RunPython(clear_invalid_phones, migrations.RunPython.noop),
    ]
