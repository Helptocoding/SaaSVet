import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('billing', '0029_external_attestation_corrections'),
    ]

    operations = [
        migrations.AddField(
            model_name='collectioncase',
            name='public_id',
            field=models.UUIDField(
                db_index=True, default=uuid.uuid4, editable=False, unique=True,
            ),
        ),
    ]
