from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import Organization, OrganizationStateAudit


@transaction.atomic
def change_organization_state(*, actor, public_id, active, reason):
    # La vista exige IsPlatformOperator; también se protege el caller directo.
    if not (actor.is_authenticated and actor.is_active and actor.is_superuser
            and actor.is_staff and actor.role == 'ADMIN_SAAS'):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied('Solo operadores de plataforma.')
    reason = reason.strip() if isinstance(reason, str) else ''
    if not reason or len(reason) > 255:
        raise ValidationError({'reason': 'Indica un motivo de hasta 255 caracteres.'})
    org = Organization.objects.select_for_update().get(public_id=public_id)
    if org.is_active == active:
        return org
    now = timezone.now()
    org.is_active = active
    org.deactivated_at = None if active else now
    org.deactivated_by = None if active else actor
    org.deactivation_reason = '' if active else reason
    org.save(update_fields=['is_active', 'deactivated_at', 'deactivated_by',
                            'deactivation_reason'])
    OrganizationStateAudit.objects.create(
        organization=org, actor=actor, active=active, reason=reason, changed_at=now,
    )
    return org
