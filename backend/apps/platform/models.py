from django.db import models


class PhysicalDeletionReceipt(models.Model):
    """Durable operation/audit. UUID identifiers are deliberately not target FKs."""
    idempotency_key = models.UUIDField(unique=True)
    confirmation_digest = models.CharField(max_length=64, unique=True)
    actor_id = models.UUIDField()
    actor_role = models.CharField(max_length=16, default='ADMIN_SAAS')
    organization_id = models.UUIDField()
    target_type = models.CharField(max_length=16)
    target_id = models.UUIDField()
    action = models.CharField(max_length=32, default='physical_delete')
    reason = models.CharField(max_length=255)
    payload_digest = models.CharField(max_length=64)
    impact_digest = models.CharField(max_length=64)
    impact = models.JSONField(default=dict)
    outcome = models.CharField(max_length=16, default='deleted')
    occurred_at = models.DateTimeField(auto_now_add=True)
