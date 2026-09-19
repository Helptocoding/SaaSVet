"""Closed B7A parameter schemas v1. No arbitrary LLM payloads or schema engine."""
import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, time
from .capabilities import operation_capability


class InvalidParameters(ValueError):
    pass


def _normalize(value, rule):
    if value is None or type(value) is bool:
        raise InvalidParameters('null/bool is not a parameter')
    if rule == 'id':
        if type(value) is int and value > 0:
            return value
        if isinstance(value, str) and re.fullmatch(r'[0-9]+', value) and int(value) > 0:
            return int(value)
    elif rule == 'date':
        if isinstance(value, date) and not isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            try:
                return date.fromisoformat(value).isoformat()
            except ValueError:
                pass
    elif rule == 'time':
        if isinstance(value, str) and re.fullmatch(r'\d{1,2}:\d{2}(:00)?', value):
            try:
                hour, minute, *_ = value.split(':')
                value = time(int(hour), int(minute))
            except ValueError:
                pass
        if isinstance(value, time) and not value.second and not value.microsecond and not value.tzinfo:
            return value.isoformat(timespec='minutes')
    elif rule.startswith('text') and isinstance(value, str):
        value = unicodedata.normalize('NFC', ' '.join(value.split()))
        if len(value) <= int(rule[4:]):
            return value
    elif rule == 'species' and isinstance(value, str):
        from apps.patients.models import SPECIES_CHOICES
        value = unicodedata.normalize('NFC', value.strip().lower())
        if value in SPECIES_CHOICES or value == '':
            return value
    elif rule == 'confirmed' and value == 'confirmed':
        return value
    raise InvalidParameters('invalid parameter type or value')


def canonicalize(kind, parameters, *, version=1):
    spec = operation_capability(kind)
    if not spec or version != spec.schema_version or type(parameters) is not dict:
        raise InvalidParameters('unknown operation/schema')
    fields = {field for field, _, _ in spec.schema}
    if set(parameters) - fields:
        raise InvalidParameters('unknown parameter')
    result = {}
    for field, rule, required in spec.schema:
        if field not in parameters:
            if required:
                raise InvalidParameters('missing parameter')
            continue
        value = _normalize(parameters[field], rule)
        if value == '':
            if required:
                raise InvalidParameters('empty parameter')
            continue  # blank optional strings mean omission in the domain
        result[field] = value
    if 'end_time' in result and result['end_time'] <= result['start_time']:
        raise InvalidParameters('invalid interval')
    return dict(sorted(result.items()))


def canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def digest(kind, parameters, *, version=1, bindings=None):
    payload = {'operation_kind': kind, 'parameters_schema_version': version,
               'parameters': canonicalize(kind, parameters, version=version),
               'bindings': bindings or {}}
    return hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()
