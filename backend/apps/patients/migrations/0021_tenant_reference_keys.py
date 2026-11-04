from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('patients', '0020_archive_metadata')]
    operations = [
        migrations.AddConstraint('owner', models.UniqueConstraint(
            fields=['id', 'organization'], name='owner_id_org_ref')),
        migrations.AddConstraint('pet', models.UniqueConstraint(
            fields=['id', 'organization'], name='pet_id_org_ref')),
    ]
