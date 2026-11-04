import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('organizations', '0013_preserve_timezone_audit'),
                    migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        # db_default: mantiene la migración ADITIVA para un escritor anclado a un
        # estado de esquema anterior, que omitiría la columna en su INSERT.
        migrations.AddField(model_name='organization', name='is_active',
                            field=models.BooleanField(default=True, db_default=True,
                                                      db_index=True)),
        migrations.AddField(model_name='organization', name='deactivated_at',
                            field=models.DateTimeField(blank=True, null=True, editable=False)),
        migrations.AddField(model_name='organization', name='deactivated_by',
                            field=models.ForeignKey(blank=True, null=True, editable=False,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name='+', to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name='organization', name='deactivation_reason',
                            field=models.CharField(blank=True, default='', db_default='',
                                                   max_length=255, editable=False)),
    ]
