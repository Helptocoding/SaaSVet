"""ADR p70 D1: lleva al catálogo de México las zonas que están fuera de él.

Desde p70 la zona se elige de un catálogo cerrado (`organizations.timezones`).
Las organizaciones creadas antes con otra zona (en desarrollo y CI, típicamente
`UTC`) pasan a `America/Mexico_City`. No hay datos reales (`CLAUDE.md`); las
citas de esas bases de prueba conservan sus instantes calculados con la zona
anterior, como cualquier cita creada antes de un cambio de zona.

El catálogo se copia aquí a propósito: una migración no debe depender de un
módulo que puede cambiar después. Solo datos, sin cambio de esquema. Revertirla
no restaura las zonas anteriores.
"""
from django.db import migrations


CATALOG = (
    'America/Mexico_City', 'America/Monterrey', 'America/Merida', 'America/Chihuahua',
    'America/Bahia_Banderas', 'America/Cancun', 'America/Mazatlan', 'America/Hermosillo',
    'America/Tijuana', 'America/Ciudad_Juarez', 'America/Ojinaga', 'America/Matamoros',
)
DEFAULT = 'America/Mexico_City'


def normalize_timezones(apps, schema_editor):
    Organization = apps.get_model('organizations', 'Organization')
    Organization.objects.exclude(timezone__in=CATALOG).update(timezone=DEFAULT)


class Migration(migrations.Migration):

    dependencies = [('organizations', '0016_normalize_invalid_phones')]

    operations = [
        migrations.RunPython(normalize_timezones, migrations.RunPython.noop),
    ]
