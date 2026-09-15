"""B2 minimal wire schemas for existing endpoints. No HTTP, ORM or authority.

DRF DecimalField emits decimal strings: parse explicitly, never search numbers.
Currency is supplied by the existing OrganizationSettings currency contract.
"""
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
import re
from uuid import UUID


class InvalidResponse(ValueError):
    """No response values in exceptions (they may be logged)."""


def require(condition):
    if not condition:
        raise InvalidResponse('endpoint_contract_mismatch')


def text(value, *, blank=False):
    return isinstance(value, str) and (blank or bool(value.strip()))


def public_id(value):
    try:
        return isinstance(value, str) and str(UUID(value)) == value.lower()
    except (ValueError, AttributeError):
        return False


def decimal_field(value, *, nullable=False):
    if value is None and nullable:
        return None
    require(type(value) in (str, int, float, Decimal))
    if isinstance(value, str):
        require(bool(re.fullmatch(r'-?\d+(?:\.\d+)?', value)))
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise InvalidResponse('invalid_decimal') from None
    require(result.is_finite() and result >= 0)
    return result


def iso_date(value, *, nullable=False):
    if value is None and nullable:
        return
    require(isinstance(value, str))
    try:
        require(date.fromisoformat(value).isoformat() == value)
    except ValueError:
        raise InvalidResponse('invalid_date') from None


def iso_time(value):
    require(isinstance(value, str))
    try:
        return time.fromisoformat(value)
    except ValueError:
        raise InvalidResponse('invalid_time') from None


def check_scope(row, scope):
    # Serializers usually omit org: authenticated JWT+TenantQueryMixin is the
    # source then. Explicit contradictory upstream scope must be rejected.
    for key in ('organization_id', 'contact_id'):
        if key in row:
            require(str(row[key]) == str(scope.get(key)))
    if 'organization' in row:
        require(str(row['organization']) == str(scope.get('organization_id')))


def validate_row(row, schema, scope):
    require(isinstance(row, dict))
    check_scope(row, scope)
    require(public_id(row.get('public_id')))
    if schema == 'pet':
        require(type(row.get('id')) is int)
        require(text(row.get('name')) and text(row.get('species'), blank=True))
        owner = row.get('owner')
        require(isinstance(owner, dict) and public_id(owner.get('public_id')))
        check_scope(owner, scope)
        if scope.get('owner'):
            require(owner['public_id'] == scope['owner'])
    elif schema == 'appointment':
        require(public_id(row.get('pet_public_id')) and public_id(row.get('owner_public_id')))
        require(type(row.get('pet')) is int and text(row.get('pet_name')))
        require(row.get('status') in ('scheduled', 'confirmed', 'in_progress',
                                      'done', 'canceled', 'no_show'))
        iso_date(row.get('date'))
        start, end = iso_time(row.get('start_time')), iso_time(row.get('end_time'))
        require(end > start)
        require(type(row.get('veterinarian')) is int or row.get('veterinarian') is None)
        for key in ('start_datetime', 'end_datetime'):
            require(text(row.get(key)))
            try:
                require(datetime.fromisoformat(row[key].replace('Z', '+00:00')).tzinfo is not None)
            except ValueError:
                raise InvalidResponse('invalid_datetime') from None
        for key, field in (('pet', 'pet_public_id'), ('owner', 'owner_public_id'),
                           ('appointment', 'public_id'), ('date', 'date')):
            if scope.get(key):
                require(str(row[field]) == str(scope[key]))
    elif schema == 'vaccine':
        require(public_id(row.get('pet_public_id')))
        require(row['pet_public_id'] == scope.get('pet'))
        require(text(row.get('vaccine_name')))
        iso_date(row.get('application_date'))
        require('next_due_date' in row)
        iso_date(row['next_due_date'], nullable=True)
        require(row.get('status') in ('current', 'overdue', 'no_scheduled'))
    elif schema == 'service':
        require(text(row.get('name')) and type(row.get('is_active')) is bool)
        require('base_price' in row)
        decimal_field(row['base_price'], nullable=True)
        if 'currency' in row:
            require(row['currency'] == scope.get('currency'))
    elif schema == 'product':
        require(text(row.get('name')) and type(row.get('is_active')) is bool)
        require(type(row.get('requires_prescription')) is bool)
        require(text(row.get('category')))
        if scope.get('category'):
            require(row['category'] == scope['category'])
        decimal_field(row.get('stock_quantity'))
        require(isinstance(row.get('presentations'), list))
        for entry in row['presentations']:
            require(isinstance(entry, dict) and text(entry.get('name')))
            check_scope(entry, scope)
            decimal_field(entry.get('stock'))
            require('sale_price' in entry)
            decimal_field(entry['sale_price'], nullable=True)
    else:
        raise InvalidResponse('unknown_schema')


def collection(data, schema, scope, *, flat_complete):
    """Validate all rows, including hidden rows, before any projection.

    Flat completeness is an endpoint contract, never an HTTP inference.
    An unrecognized pagination envelope stays unknown; no synthetic cursor.
    """
    has_more = cursor = None
    completeness = 'complete' if flat_complete else 'unknown'
    if isinstance(data, list):
        rows = data
    else:
        require(isinstance(data, dict) and isinstance(data.get('results'), list))
        rows, completeness = data['results'], 'unknown'
        if all(key in data for key in ('count', 'next', 'previous')):
            require(type(data['count']) is int and data['count'] >= len(rows))
            require(data['next'] is None or text(data['next']))
            require(data['previous'] is None or text(data['previous']))
            has_more = data['next'] is not None
            if has_more or data['previous'] is not None or data['count'] > len(rows):
                completeness = 'truncated'
            elif data['count'] == len(rows):
                completeness = 'complete'
        if data.get('truncated') is True:
            completeness = 'truncated'
    for row in rows:
        validate_row(row, schema, scope)
    # PetViewSet unpaginated owner filter is capped at 20.
    if schema == 'pet' and isinstance(data, list) and scope.get('owner'):
        completeness = 'unknown' if len(rows) >= 20 else 'complete'
    return rows, completeness, has_more, cursor
