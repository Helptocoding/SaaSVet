"""Persist semantic intake path as a capability boundary."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agent', '0018_f5_drop_conversation_summary'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversation',
            name='intake_path',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', 'Pendiente de clasificar'),
                    ('new_client', 'Primera visita'),
                    ('existing_client', 'Cliente existente'),
                ],
                default='',
                max_length=20,
            ),
        ),
    ]
