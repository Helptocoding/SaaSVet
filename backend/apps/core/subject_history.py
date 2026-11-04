"""Minimum display identity persisted alongside a clinical or financial document."""
from django.utils import timezone


def snapshot(*, organization, owner=None, pet=None, source='captured'):
    if owner is not None and owner.organization_id != organization.pk:
        raise ValueError('Cliente de otra organización.')
    if pet is not None and pet.organization_id != organization.pk:
        raise ValueError('Paciente de otra organización.')
    if owner is None and pet is not None:
        owner = pet.owner
    return {
        'version': 1,
        'organization': str(organization.public_id),
        'source': source,
        'recorded_at': timezone.now().isoformat(),
        'owner': ({'uuid': str(owner.public_id), 'name': owner.name, 'phone': owner.phone}
                  if owner is not None else None),
        'pet': ({'uuid': str(pet.public_id), 'name': pet.name,
                 'species': pet.species, 'breed': pet.breed,
                 'sex': pet.sex, 'birth_date': pet.birth_date.isoformat() if pet.birth_date else None}
                if pet is not None else None),
    }


def identity(document, kind):
    return (document.subject_snapshot or {}).get(kind) or {}
