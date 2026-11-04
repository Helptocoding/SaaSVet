import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [('organizations', '0014_organization_state'),
                    migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='OrganizationStateAudit', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False,
                                       verbose_name='ID')),
            ('active', models.BooleanField()),
            ('reason', models.CharField(max_length=255)),
            ('changed_at', models.DateTimeField(default=django.utils.timezone.now)),
            ('actor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                        to=settings.AUTH_USER_MODEL)),
            ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                related_name='state_audits', to='organizations.organization')),
        ]),
    ]
