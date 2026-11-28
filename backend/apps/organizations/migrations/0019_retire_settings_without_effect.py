"""ADR p70 D5: se retiran cuatro ajustes que nada leía (`locale`,
`appointment_buffer_minutes`, `allow_emergency_walkin`, `week_starts_on`). Sin
clínicas reales no hay valores que conservar."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0018_config_event_absorbs_timezone_audit'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='organizationsettings',
            name='allow_emergency_walkin',
        ),
        migrations.RemoveField(
            model_name='organizationsettings',
            name='appointment_buffer_minutes',
        ),
        migrations.RemoveField(
            model_name='organizationsettings',
            name='locale',
        ),
        migrations.RemoveField(
            model_name='organizationsettings',
            name='week_starts_on',
        ),
    ]
