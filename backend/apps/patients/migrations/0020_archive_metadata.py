import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('patients', '0019_pet_registration_effect'),
                    migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name='owner', name='archived_at',
                            field=models.DateTimeField(blank=True, null=True, editable=False)),
        migrations.AddField(model_name='owner', name='archived_by',
                            field=models.ForeignKey(blank=True, null=True, editable=False,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name='+', to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name='pet', name='archived_at',
                            field=models.DateTimeField(blank=True, null=True, editable=False)),
        migrations.AddField(model_name='pet', name='archived_by',
                            field=models.ForeignKey(blank=True, null=True, editable=False,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name='+', to=settings.AUTH_USER_MODEL)),
    ]
