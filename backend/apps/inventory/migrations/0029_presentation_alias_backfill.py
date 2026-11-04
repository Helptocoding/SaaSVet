from decimal import Decimal

from django.db import migrations
from django.db.models import F, Q


def backfill_alias(apps, schema_editor):
    Presentation = apps.get_model('inventory', 'Presentation')
    rows = Presentation._base_manager.using(schema_editor.connection.alias)
    valid = Q(conversion_factor__gt=Decimal('0')) & Q(conversion_factor__lte=Decimal('999999.9999'))
    invalid = rows.exclude(valid).count()
    if invalid:
        raise RuntimeError(f'Alias backfill detenido: {invalid} factores inválidos.')
    rows.exclude(quantity=F('conversion_factor')).update(quantity=F('conversion_factor'))


class Migration(migrations.Migration):
    dependencies = [('inventory', '0028_presentation_alias_precision')]

    operations = [migrations.RunPython(backfill_alias, migrations.RunPython.noop)]
