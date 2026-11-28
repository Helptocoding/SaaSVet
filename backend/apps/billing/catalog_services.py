"""Escrituras del catálogo de servicios (ADR p70 D9, plan F1.1).

Cada operación registra su `OrganizationConfigEvent` en la misma transacción y
solo si algo cambió. `billing` ya depende de `organizations`; al revés no.
"""
from django.db import transaction

from apps.organizations.models import OrganizationConfigEvent
from apps.organizations.services import config_diff, config_value, record_config_event

from .models import Service

SERVICE_FIELDS = ('name', 'description', 'base_price', 'specialty', 'is_active')


def _subject(service):
    return {'type': 'service', 'public_id': str(service.public_id), 'name': service.name}


def create_service(*, actor, organization, data):
    with transaction.atomic():
        service = Service.objects.create(organization=organization, **data)
        changes = {
            field: [None, config_value(getattr(service, field))]
            for field in SERVICE_FIELDS
        }
        record_config_event(
            organization=organization, actor=actor,
            kind=OrganizationConfigEvent.KIND_SERVICE_CREATED,
            changes=changes, subject=_subject(service),
        )
    return service


def update_service(*, actor, service, data):
    """Compara contra la fila bloqueada. Si cambia `is_active` el evento es
    `service_activated`/`service_deactivated` (con todo lo que cambió); si no,
    `service_updated`."""
    with transaction.atomic():
        locked = Service.all_objects.select_for_update().get(
            pk=service.pk, organization_id=service.organization_id,
        )
        changes = config_diff(locked, data)
        if changes:
            for field in changes:
                setattr(locked, field, data[field])
            locked.save(update_fields=list(changes) + ['updated_at', 'updated_by'])
            if 'is_active' in changes:
                kind = (OrganizationConfigEvent.KIND_SERVICE_ACTIVATED if locked.is_active
                        else OrganizationConfigEvent.KIND_SERVICE_DEACTIVATED)
            else:
                kind = OrganizationConfigEvent.KIND_SERVICE_UPDATED
            record_config_event(
                organization=locked.organization_id, actor=actor, kind=kind,
                changes=changes, subject=_subject(locked),
            )
    return locked


def delete_service(*, actor, service):
    """Borra el servicio. Con dependencias (`PROTECT`), la base lo rechaza y la
    transacción no deja evento; el manejador de errores responde 409."""
    with transaction.atomic():
        subject = _subject(service)
        organization_id = service.organization_id
        service.delete()
        record_config_event(
            organization=organization_id, actor=actor,
            kind=OrganizationConfigEvent.KIND_SERVICE_DELETED, subject=subject,
        )
