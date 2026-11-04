"""Archivo/restauración de sujetos; nunca produce un borrado físico."""
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied

from apps.appointments.models import Appointment
from apps.medical_records.models import MedicalRecord
from apps.organizations.models import Organization
from .models import Owner, Pet


class ArchiveBlocked(APIException):
    status_code = 409
    default_code = 'archive_blocked'
    default_detail = 'Hay actividad abierta o el sujeto no está disponible.'


def _authorize(actor, org):
    platform = (actor.is_authenticated and actor.is_active and actor.is_superuser
                and actor.is_staff and actor.role == 'ADMIN_SAAS')
    if not platform and not (actor.is_authenticated and actor.is_active
                             and actor.role == 'ADMIN' and actor.organization_id == org.pk):
        raise PermissionDenied('Solo el administrador de la clínica o la plataforma.')
    return platform


def _check_open(org, pets):
    ids = [pet.pk for pet in pets]
    if not ids:
        return
    if Appointment.all_objects.filter(
        organization=org, pet_id__in=ids,
        status__in=('scheduled', 'confirmed', 'in_progress'),
    ).exists() or MedicalRecord.all_objects.filter(
        organization=org, pet_id__in=ids, status='open',
    ).exists():
        raise ArchiveBlocked('Resuelve citas pendientes y consultas abiertas antes de archivar.')


@transaction.atomic
def change_archive_state(*, actor, organization_id, kind, public_id, archive):
    # Orden global compatible con appointments.creation: Organization → Owner → Pet.
    org = Organization.objects.select_for_update().get(pk=organization_id)
    _authorize(actor, org)
    if not org.is_active:
        raise ArchiveBlocked('La organización está desactivada.')
    if kind == 'owner':
        owner = get_object_or_404(Owner.all_objects.select_for_update(),
            organization=org, public_id=public_id,
        )
        if owner.is_generic:
            raise ArchiveBlocked('No se puede archivar un cliente genérico.')
        pets = list(Pet.all_objects.filter(organization=org, owner=owner)
                    .select_for_update().order_by('pk'))
        if archive:
            _check_open(org, pets)
            now = timezone.now()
            for pet in pets:
                if pet.is_active:
                    Pet.all_objects.filter(pk=pet.pk).update(
                        is_active=False, archived_at=now, archived_by=actor,
                    )
            if owner.is_active:
                Owner.all_objects.filter(pk=owner.pk).update(
                    is_active=False, archived_at=now, archived_by=actor,
                )
        elif not owner.is_active:
            Owner.all_objects.filter(pk=owner.pk).update(
                is_active=True, archived_at=None, archived_by=None,
            )
        return Owner.all_objects.get(pk=owner.pk)
    if kind != 'pet':
        raise ValueError('Tipo no permitido.')
    # Leer dueño primero y bloquear ambos; revalidar bajo lock por si cambió FK.
    owner_id = get_object_or_404(Pet.all_objects.filter(organization=org),
                                public_id=public_id).owner_id
    owner = Owner.all_objects.select_for_update().get(pk=owner_id, organization=org)
    pet = get_object_or_404(Pet.all_objects.select_for_update(),
        organization=org, owner=owner, public_id=public_id,
    )
    if pet.is_generic or owner.is_generic:
        raise ArchiveBlocked('No se puede archivar una mascota genérica.')
    if archive:
        _check_open(org, [pet])
        if pet.is_active:
            Pet.all_objects.filter(pk=pet.pk).update(
                is_active=False, archived_at=timezone.now(), archived_by=actor,
            )
    else:
        if not owner.is_active:
            raise ArchiveBlocked('Restaura primero el cliente.')
        if not pet.is_active:
            Pet.all_objects.filter(pk=pet.pk).update(
                is_active=True, archived_at=None, archived_by=None,
            )
    return Pet.all_objects.get(pk=pet.pk)
