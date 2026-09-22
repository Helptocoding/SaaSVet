from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('appointments', '0015_appointment_category'),
        ('agent', '0026_b7b_consent_evidence'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment', name='source_operation',
            field=models.OneToOneField(blank=True, editable=False, null=True,
                on_delete=django.db.models.deletion.PROTECT, related_name='created_appointment',
                to='agent.conversationoperation', to_field='operation_key'),
        ),
        migrations.AddField(
            model_name='appointment', name='source_parameters_digest',
            field=models.CharField(blank=True, null=True, default=None, editable=False, max_length=64),
        ),
    ]
