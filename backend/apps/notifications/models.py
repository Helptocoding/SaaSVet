from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import OrganizationalModel


class Notification(OrganizationalModel):
    TYPE_CHOICES = (
        ('appointment_upcoming', 'Cita próxima'),
        ('appointment_delayed', 'Cita retrasada'),
        ('stock_low_entered', 'Entró en stock bajo'),
        ('stock_out', 'Agotado'),
        ('cash_difference', 'Diferencia de caja'),
    )

    type = models.CharField(max_length=40, choices=TYPE_CHOICES, db_index=True)
    entity_type = models.CharField(max_length=40, blank=True, default='')
    entity_public_id = models.UUIDField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(db_index=True)
    dedup_key = models.CharField(max_length=128, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'dedup_key'],
                name='notification_org_dedup_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['organization', 'type', 'occurred_at']),
        ]
        ordering = ['-occurred_at', '-id']

    def __str__(self):
        return f"{self.type} [{self.dedup_key}]"


class NotificationReceipt(OrganizationalModel):
    notification = models.ForeignKey(
        Notification, on_delete=models.PROTECT,
        null=True, blank=True, related_name='receipts',
    )
    notification_key = models.CharField(max_length=128, db_index=True)
    user = models.ForeignKey(
        'users.User', on_delete=models.CASCADE, related_name='notification_receipts',
    )
    seen_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'notification_key', 'user'],
                name='receipt_org_key_user_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['organization', 'user', 'seen_at']),
        ]
        ordering = ['-id']

    def clean(self):
        if self.notification_id is not None:
            if self.notification.organization_id != self.organization_id:
                raise ValidationError("La notificación no pertenece a la misma organización.")
            if self.notification_key != self.notification.dedup_key:
                raise ValidationError("INV-N1: notification_key debe ser igual al dedup_key de Notification.")
        if self.user_id is not None and self.organization_id is not None:
            if getattr(self.user, 'organization_id', None) != self.organization_id:
                raise ValidationError("El usuario no pertenece a la misma organización.")
        if not self.notification_key:
            raise ValidationError("notification_key es requerido.")
