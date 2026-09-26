"""Individual Pet creation shared by the human API and authorized B8E.

Owner is an exact reference; this service never resolves or creates clients.
Organization -> Owner shared row locks; no semantic Pet deduplication.
"""
import hashlib
import re
from datetime import date

from django.db import connection, transaction
from rest_framework import serializers

from apps.core.datetime_utils import org_today_local
from apps.organizations.models import Organization
from .models import Owner, Pet, SPECIES_CHOICES

NAME_REGEX = re.compile(r"^[A-Za-z0-9ÁÉÍÓÚáéíóúñÑ\' \-]+$")
CREATE_FIELDS = frozenset(('name', 'species', 'breed', 'birth_date', 'sex', 'color', 'legacy_id'))


class PetCreationRejected(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def validate_name(value, field_label='Nombre'):
    if not value or not value.strip():
        raise serializers.ValidationError(f'{field_label} es requerido.')
    if not NAME_REGEX.match(value.strip()):
        raise serializers.ValidationError(
            f'{field_label} solo puede contener letras, números, espacios, acentos, apóstrofes y guiones.')
    return value.strip()


def validate_species(value):
    if not value or not value.strip():
        return ''
    if value.strip().lower() not in SPECIES_CHOICES:
        raise serializers.ValidationError(f"Especie inválida. Opciones: {', '.join(SPECIES_CHOICES)}.")
    return value.strip().lower()


def validate_birth_date(value, today):
    if value is not None and value > today:
        raise serializers.ValidationError('La fecha de nacimiento no puede ser en el futuro.')
    return value


def _share(model, *, nowait=False, **scope):
    if not connection.in_atomic_block or connection.vendor != 'postgresql':
        raise RuntimeError('Pet creation requires atomic PostgreSQL')
    query = model._base_manager.filter(**scope).order_by('pk')
    sql, params = query.query.sql_with_params()
    with connection.cursor() as cursor:
        cursor.execute(sql + ' FOR SHARE' + (' NOWAIT' if nowait else ''), params)
        cursor.fetchall()
    return query.first()


def lock_organization(organization_id: int):
    org = _share(Organization, pk=organization_id)
    if org is None:
        raise PetCreationRejected('entity_scope')
    return org


def lock_creation_scope(organization_id: int, owner_id: int, *, owner_nowait=False):
    org = lock_organization(organization_id)
    owner = _share(Owner, pk=owner_id, organization_id=organization_id, nowait=owner_nowait)
    if owner is None:
        raise PetCreationRejected('entity_scope')
    if not owner.is_active:
        raise PetCreationRejected('entity_inactive')
    return org, owner


def owner_snapshot(owner):
    return {'schema': 1, 'id': owner.pk, 'public_id': str(owner.public_id),
        'organization_id': owner.organization_id, 'name': owner.name,
        'is_active': owner.is_active, 'is_generic': owner.is_generic,
        'phone_key_digest': hashlib.sha256((owner.phone_normalized or '').encode()).hexdigest()}


def validate_fields(fields: dict, org):
    if not isinstance(fields, dict) or set(fields) - CREATE_FIELDS or 'name' not in fields:
        raise PetCreationRejected('invalid_pet_data')
    values = dict(fields)
    values['name'] = validate_name(values['name'], 'Nombre de la mascota')
    if 'species' in values:
        values['species'] = validate_species(values['species'])
    if 'birth_date' in values:
        value = values['birth_date']
        if value is not None and type(value) is not date:
            raise PetCreationRejected('invalid_pet_data')
        values['birth_date'] = validate_birth_date(value, org_today_local(org))
    return values


@transaction.atomic
def create_pet(*, organization_id: int, owner_id: int, fields: dict) -> Pet:
    org, owner = lock_creation_scope(organization_id, owner_id)
    values = validate_fields(fields, org)
    return Pet.objects.create(organization=org, owner=owner, **values)
