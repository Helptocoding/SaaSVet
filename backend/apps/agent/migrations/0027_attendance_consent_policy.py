from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('agent', '0026_b7b_consent_evidence')]

    operations = [
        migrations.RemoveConstraint(model_name='conversationoperation', name='operation_b7b_decision_evidence'),
        migrations.AddConstraint(model_name='conversationoperation', constraint=models.CheckConstraint(
            condition=~models.Q(consent_state__in=('AUTHORIZED', 'REJECTED')) |
                (models.Q(consent_decided_at__isnull=False) & models.Q(proposal_message__isnull=False)
                 & models.Q(authorization_message__isnull=False)
                 & (models.Q(authorization_policy_version=1) | models.Q(
                     authorization_policy_version=2, operation_kind='CONFIRM_ATTENDANCE',
                     authorization_mode='CONTEXTUAL_DECLARATION',
                     preconditions__contains={'schema': 3, 'attendance_contract': 1}))
                 & models.Q(authorization_policy_version__isnull=False)
                 & models.Q(authorization_channel='whatsapp')), name='operation_b7b_decision_evidence')),
    ]
