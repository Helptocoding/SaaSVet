"""
imports/services.py — Núcleo del importador (validación dry-run + commit atómico).

Reglas de negocio (entity_type=owner_pet), ver docs/project_import_sprint.md §6:

- owner.name  requerido (NAME_REGEX, reusado de patients).
- owner.phone OPCIONAL. Con teléfono → dedup por (org, phone). Sin teléfono →
  se importa igual (dedup_key=null); dedup interna por nombre normalizado dentro
  del MISMO archivo (no se inventan errores por falta de teléfono).
- pet.name    requerido (NAME_REGEX).
- pet.species requerida → normalize_species; no resoluble → error de fila.
- pet dedup   por (owner, normalize(name), species) — normalizado, NO string exacto.
- dedup_strategy=skip (v1): duplicado → se salta y se reporta (nunca pisa datos).
- Una fila inválida NO aborta el import: se salta con savepoint y se reporta
  (evita "500 filas → 120 errores → nada se importa").
"""
import re

from django.db import transaction

from apps.patients.models import Owner, Pet
from apps.patients.serializers import NAME_REGEX

from .models import ImportJob
from .normalization import (
    extra_target_fields,
    normalize_species,
    normalize_sex,
    normalize_text,
    required_fields,
    valid_target_fields,
)

_PHONE_DIGITS = re.compile(r'\D')
_LEGACY_MAX = 64
# Datos del sistema anterior (Fase D): tope por registro y por valor (ajuste PO).
_EXTRA_MAX_ENTRIES = 50
_EXTRA_VALUE_MAX = 500
_EXTRA_LABEL_MAX = 120


def _spec_target(spec):
    """Un valor de mapping puede ser str (campo del sistema / '' = no importar) o
    dict {target, label} (extra con label visible renombrado). Devuelve el target."""
    if isinstance(spec, dict):
        return spec.get('target') or ''
    return spec or ''


def _spec_label(spec, header):
    """Label visible para un dato extra. Si el usuario renombró la columna usa ese
    label; si no, el nombre original de la columna. La REFERENCIA a la columna
    original (header/índice) se mantiene aparte para leer la celda."""
    if isinstance(spec, dict):
        lbl = (spec.get('label') or '').strip()
        if lbl:
            return lbl[:_EXTRA_LABEL_MAX]
    return header.strip()[:_EXTRA_LABEL_MAX]


# ---------------------------------------------------------------------------
# Proyección fila → dict por campo destino
# ---------------------------------------------------------------------------
def _project_row(columns, mapping, row):
    """Aplica el mapping a una fila.

    Devuelve (data, owner_extra, pet_extra):
      - data: { campo_destino_del_sistema: valor }  (1:1)
      - owner_extra / pet_extra: [ {label, value}, ... ] para owner.extra/pet.extra
        (Fase D). Se itera en ORDEN DE COLUMNA para preservar el orden original;
        labels repetidos conviven (lista, no dict). Caps: máx 50 entradas/registro,
        value truncado a 500 chars.
    mapping = { header: campo_destino }. Columnas no mapeadas se ignoran.
    """
    data = {}
    owner_extra = []
    pet_extra = []
    # Iterar por ÍNDICE real (no por nombre): si hay headers duplicados
    # ("Comentario" ×2), cada columna lee SU celda → dos entradas distintas en la
    # lista extra. El mapping se comparte por nombre (ambas → el mismo target).
    for idx, header in enumerate(columns):  # orden original de columnas
        spec = mapping.get(header)
        target = _spec_target(spec)
        if not target:
            continue
        if idx >= len(row):
            continue
        value = (row[idx] or '').strip()
        if target == 'owner.extra':
            owner_extra.append({'label': _spec_label(spec, header), 'value': value[:_EXTRA_VALUE_MAX]})
        elif target == 'pet.extra':
            pet_extra.append({'label': _spec_label(spec, header), 'value': value[:_EXTRA_VALUE_MAX]})
        else:
            data[target] = value
    return data, owner_extra[:_EXTRA_MAX_ENTRIES], pet_extra[:_EXTRA_MAX_ENTRIES]


def _parse_birth_date(raw):
    """Devuelve (iso_date|None, ok). Acepta YYYY-MM-DD y DD/MM/YYYY.

    Fecha inválida ⇒ (None, False) → el caller la trata como WARNING (campo
    opcional y relajado): se importa la mascota sin fecha en lugar de fallar.
    """
    import datetime
    value = (raw or '').strip()
    if not value:
        return None, True
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d'):
        try:
            d = datetime.datetime.strptime(value, fmt).date()
            if d > datetime.date.today():
                return None, False
            return d.isoformat(), True
        except ValueError:
            continue
    return None, False


# ---------------------------------------------------------------------------
# Limpieza + validación pura de una fila (sin DB) — testeable aislada
# ---------------------------------------------------------------------------
def clean_owner_pet_row(data):
    """Valida y normaliza una fila owner_pet.

    Devuelve (clean: dict, errors: list[dict], warnings: list[dict]).
    `clean` solo se usa si errors está vacío.
    """
    errors = []
    warnings = []
    clean = {}

    # --- Owner ---
    owner_name = (data.get('owner.name') or '').strip()
    if not owner_name:
        errors.append({'field': 'owner.name', 'message': 'El nombre del cliente es requerido.'})
    elif not NAME_REGEX.match(owner_name):
        errors.append({'field': 'owner.name', 'message': 'El nombre del cliente tiene caracteres no permitidos.'})
    clean['owner_name'] = owner_name

    raw_phone = (data.get('owner.phone') or '').strip()
    phone = ''
    if raw_phone:
        digits = _PHONE_DIGITS.sub('', raw_phone)
        if len(digits) == 10:
            phone = digits
        else:
            errors.append({'field': 'owner.phone', 'message': 'El teléfono debe tener 10 dígitos (o dejarse vacío).'})
    else:
        # Datos históricos sucios: cliente sin teléfono se importa igual (mejor
        # tener a Juan + Max que perder el expediente), pero se avisa — el alta
        # MANUAL sí exige teléfono (OwnerSerializer.validate_phone).
        warnings.append({'field': 'owner.phone', 'message': 'Cliente sin teléfono — se importará igual.'})
    clean['owner_phone'] = phone  # '' = sin teléfono (permitido en import)

    owner_legacy = (data.get('owner.legacy_id') or '').strip()[:_LEGACY_MAX]
    clean['owner_legacy_id'] = owner_legacy

    # --- Pet ---
    pet_name = (data.get('pet.name') or '').strip()
    if not pet_name:
        errors.append({'field': 'pet.name', 'message': 'El nombre de la mascota es requerido.'})
    elif not NAME_REGEX.match(pet_name):
        errors.append({'field': 'pet.name', 'message': 'El nombre de la mascota tiene caracteres no permitidos.'})
    clean['pet_name'] = pet_name

    # Especie OPCIONAL en import (datos históricos): nunca bloquea. Si falta o no
    # se reconoce → se importa como pendiente ('') con warning. NO se asigna una
    # especie por defecto en masa. El alta manual sí la exige (PetSerializer).
    raw_species = (data.get('pet.species') or '').strip()
    species = normalize_species(raw_species)
    if not raw_species:
        warnings.append({'field': 'pet.species', 'message': 'Mascota sin especie — se importará como pendiente.'})
        species = ''
    elif species is None:
        warnings.append({'field': 'pet.species', 'message': f'Especie no reconocida ("{raw_species}") — se dejó pendiente.'})
        species = ''
    clean['pet_species'] = species

    clean['pet_breed'] = (data.get('pet.breed') or '').strip()[:100]
    clean['pet_color'] = (data.get('pet.color') or '').strip()[:100]
    clean['pet_sex'] = normalize_sex(data.get('pet.sex'))

    raw_birth = (data.get('pet.birth_date') or '').strip()
    iso_birth, ok = _parse_birth_date(raw_birth)
    if raw_birth and not ok:
        warnings.append({'field': 'pet.birth_date', 'message': f'Fecha de nacimiento ignorada (formato inválido): "{raw_birth}".'})
    clean['pet_birth_date'] = iso_birth

    clean['pet_legacy_id'] = (data.get('pet.legacy_id') or '').strip()[:_LEGACY_MAX]

    return clean, errors, warnings


# ---------------------------------------------------------------------------
# Pre-chequeo del mapping
# ---------------------------------------------------------------------------
def check_mapping(job):
    """Valida el mapping del job. Devuelve lista de mensajes de error (vacía = OK)."""
    targets = valid_target_fields(job.entity_type)
    problems = []
    # El valor del mapping puede ser str o {target, label} → normalizar a target.
    assigned = [t for t in (_spec_target(v) for v in job.mapping.values()) if t]
    unknown = sorted({t for t in assigned if t not in targets})
    if unknown:
        problems.append(f"Campos destino desconocidos: {', '.join(unknown)}.")
    # Dos columnas distintas al mismo campo del sistema → pérdida silenciosa de
    # datos (la última gana). Rechazar. Los targets *.extra están EXENTOS: muchas
    # columnas → una lista (Fase D, datos del sistema anterior).
    extras = extra_target_fields(job.entity_type)
    dupes = sorted({t for t in assigned if t not in extras and assigned.count(t) > 1})
    if dupes:
        problems.append(
            f"Hay columnas distintas asignadas al mismo campo: {', '.join(dupes)}. "
            "Cada campo del sistema debe recibir una sola columna."
        )
    mapped = set(assigned)
    missing = [f for f in required_fields(job.entity_type) if f not in mapped]
    if missing:
        problems.append(f"Faltan campos requeridos en el mapeo: {', '.join(missing)}.")
    return problems


def _base_result():
    return {
        'created_owners': 0,
        'reused_owners': 0,
        'created_pets': 0,
        'skipped_duplicates': 0,
        'error_rows': 0,
        'errors': [],
        'warnings': [],
    }


# ---------------------------------------------------------------------------
# VALIDATE (dry-run) — no escribe nada
# ---------------------------------------------------------------------------
def validate_job(job):
    """Recorre las filas y predice el resultado SIN escribir. Idempotente."""
    result = _base_result()
    problems = check_mapping(job)
    if problems:
        result['errors'] = [{'row': 0, 'field': 'mapping', 'message': p} for p in problems]
        result['error_rows'] = len(problems)
        return result

    org = job.organization
    columns = job.source_columns

    # Caches de predicción (claves virtuales para owners nuevos). Mantener el
    # MISMO orden de decisiones que commit_job para que el preview no mienta.
    owner_keys_new = set()        # owners que se crearían (phone o name)
    owner_keys_existing = {}      # owner_key -> Owner.pk existente
    seen_pet_keys = set()         # (owner_key, norm_name, species)
    seen_owner_legacy = set()     # legacy_id de owners nuevos (within-file)
    seen_pet_legacy = set()       # legacy_id de pets nuevos (within-file)

    for i, row in enumerate(job.rows, start=1):
        data, _owner_extra, _pet_extra = _project_row(columns, job.mapping, row)
        clean, errors, warnings = clean_owner_pet_row(data)
        for w in warnings:
            result['warnings'].append({'row': i, **w})
        if errors:
            result['error_rows'] += 1
            for e in errors:
                result['errors'].append({'row': i, **e})
            continue

        # --- predecir owner (sin contar todavía: puede haber conflicto legacy) ---
        phone = clean['owner_phone']
        if phone:
            owner_key = ('phone', phone)
            if owner_key in owner_keys_existing or owner_key in owner_keys_new:
                owner_is_new = False
            else:
                existing = Owner.objects.for_organization(org).filter(
                    phone=phone, is_generic=False,
                ).first()
                if existing:
                    owner_keys_existing[owner_key] = existing.pk
                    owner_is_new = False
                else:
                    owner_is_new = True
        else:
            owner_key = ('name', normalize_text(clean['owner_name']))
            owner_is_new = owner_key not in owner_keys_new

        # Conflicto de legacy_id de cliente (solo al crear uno nuevo).
        owner_legacy = clean['owner_legacy_id']
        if owner_is_new and owner_legacy:
            if owner_legacy in seen_owner_legacy or Owner.objects.for_organization(org).filter(
                legacy_id=owner_legacy,
            ).exists():
                result['error_rows'] += 1
                result['errors'].append({
                    'row': i, 'field': 'owner.legacy_id',
                    'message': f'El nº de cliente anterior "{owner_legacy}" ya existe.',
                })
                continue

        if owner_is_new:
            owner_keys_new.add(owner_key)
            if owner_legacy:
                seen_owner_legacy.add(owner_legacy)
            result['created_owners'] += 1
        else:
            result['reused_owners'] += 1

        # --- predecir pet ---
        pet_key = (owner_key, normalize_text(clean['pet_name']), clean['pet_species'])
        is_dup = pet_key in seen_pet_keys
        if not is_dup and owner_key in owner_keys_existing:
            owner_pk = owner_keys_existing[owner_key]
            for existing_pet in Pet.objects.for_organization(org).filter(
                owner_id=owner_pk, species=clean['pet_species'],
            ).values_list('name', flat=True):
                if normalize_text(existing_pet) == normalize_text(clean['pet_name']):
                    is_dup = True
                    break
        if is_dup:
            result['skipped_duplicates'] += 1
            continue

        # Conflicto de legacy_id de mascota.
        pet_legacy = clean['pet_legacy_id']
        if pet_legacy:
            if pet_legacy in seen_pet_legacy or Pet.objects.for_organization(org).filter(
                legacy_id=pet_legacy,
            ).exists():
                result['error_rows'] += 1
                result['errors'].append({
                    'row': i, 'field': 'pet.legacy_id',
                    'message': f'El nº de expediente anterior "{pet_legacy}" ya existe.',
                })
                continue
            seen_pet_legacy.add(pet_legacy)

        seen_pet_keys.add(pet_key)
        result['created_pets'] += 1

    return result


# ---------------------------------------------------------------------------
# COMMIT — escribe en transaction.atomic, savepoint por fila
# ---------------------------------------------------------------------------
def commit_job(job):
    """Escribe los registros. Atómico a nivel job; savepoint por fila (una fila
    mala no tumba el resto). Devuelve result. NO marca el status (lo hace la view).
    """
    result = _base_result()
    problems = check_mapping(job)
    if problems:
        result['errors'] = [{'row': 0, 'field': 'mapping', 'message': p} for p in problems]
        result['error_rows'] = len(problems)
        return result

    org = job.organization
    columns = job.source_columns

    owners_by_phone = {}        # phone -> Owner
    owners_by_name = {}         # norm_name -> Owner (phoneless, within-file)
    seen_pet_keys = set()       # (owner.pk, norm_name, species)

    with transaction.atomic():
        for i, row in enumerate(job.rows, start=1):
            data, owner_extra, pet_extra = _project_row(columns, job.mapping, row)
            clean, errors, warnings = clean_owner_pet_row(data)
            for w in warnings:
                result['warnings'].append({'row': i, **w})
            if errors:
                result['error_rows'] += 1
                for e in errors:
                    result['errors'].append({'row': i, **e})
                continue

            # --- Owner en SU PROPIO savepoint (persiste independiente del pet) ---
            # Si owner y pet compartieran savepoint, un fallo del pet revertiría
            # el INSERT del owner dejando un objeto huérfano en el cache → la
            # siguiente fila que lo reusa perdería su pet (BLOCKER del review).
            # _resolve_owner solo cachea tras un save() exitoso; si el save lanza,
            # el savepoint revierte y el except evita cachear.
            # owner_extra se aplica SOLO al crear (la 1ª fila gana); un owner
            # reusado conserva su extra_data de creación.
            try:
                with transaction.atomic():
                    owner, owner_status = _resolve_owner(
                        org, clean, owners_by_phone, owners_by_name,
                        owner_extra=owner_extra,
                    )
            except Exception as exc:  # noqa: BLE001 — fila aislada por savepoint
                result['error_rows'] += 1
                result['errors'].append({
                    'row': i, 'field': 'owner', 'message': _humanize_exc(exc),
                })
                continue
            if owner_status == 'created':
                result['created_owners'] += 1
            else:
                result['reused_owners'] += 1

            # --- Dedup de pet (sin escribir) ---
            pet_key = (owner.pk, normalize_text(clean['pet_name']), clean['pet_species'])
            if pet_key in seen_pet_keys or _pet_exists(org, owner, clean):
                result['skipped_duplicates'] += 1
                continue

            # --- Pet en su propio savepoint ---
            try:
                with transaction.atomic():
                    Pet.objects.create(
                        organization=org,
                        owner=owner,
                        name=clean['pet_name'],
                        species=clean['pet_species'],
                        breed=clean['pet_breed'],
                        color=clean['pet_color'],
                        sex=clean['pet_sex'],
                        birth_date=clean['pet_birth_date'] or None,
                        legacy_id=clean['pet_legacy_id'],
                        extra_data=pet_extra,
                    )
                seen_pet_keys.add(pet_key)
                result['created_pets'] += 1
            except Exception as exc:  # noqa: BLE001 — fila aislada por savepoint
                result['error_rows'] += 1
                result['errors'].append({
                    'row': i, 'field': 'pet', 'message': _humanize_exc(exc),
                })

    return result


def _resolve_owner(org, clean, owners_by_phone, owners_by_name, owner_extra=None):
    """Devuelve (Owner, status) donde status ∈ {'created', 'reused'}.

    'created' la primera vez que se materializa un owner nuevo; 'reused' si ya
    existía en DB o si una fila previa de este mismo archivo ya lo resolvió.
    owner_extra solo se persiste al crear (no se mezcla en owners reusados).
    """
    phone = clean['owner_phone']
    if phone:
        if phone in owners_by_phone:
            return owners_by_phone[phone], 'reused'
        existing = Owner.objects.for_organization(org).filter(
            phone=phone, is_generic=False,
        ).first()
        if existing:
            owners_by_phone[phone] = existing
            return existing, 'reused'
        owner = _create_owner(org, clean, phone=phone, owner_extra=owner_extra)
        owners_by_phone[phone] = owner
        return owner, 'created'

    # Sin teléfono: dedup interna por nombre normalizado dentro del archivo.
    name_key = normalize_text(clean['owner_name'])
    if name_key in owners_by_name:
        return owners_by_name[name_key], 'reused'
    owner = _create_owner(org, clean, phone='', owner_extra=owner_extra)
    owners_by_name[name_key] = owner
    return owner, 'created'


def _create_owner(org, clean, *, phone, owner_extra=None):
    owner = Owner(
        organization=org,
        name=clean['owner_name'],
        phone=phone,
        legacy_id=clean['owner_legacy_id'],
        extra_data=owner_extra or [],
    )
    owner.save()  # OrganizationalModel.save() → full_clean()
    return owner


def _pet_exists(org, owner, clean):
    for name in Pet.objects.for_organization(org).filter(
        owner=owner, species=clean['pet_species'],
    ).values_list('name', flat=True):
        if normalize_text(name) == normalize_text(clean['pet_name']):
            return True
    return False


# Constraints de DB → mensaje accionable para el usuario (NUNCA exponer el
# nombre crudo del constraint Postgres en la respuesta).
_CONSTRAINT_MESSAGES = {
    'pet_legacy_id_unique_per_org': 'El nº de expediente anterior ya existe en otra mascota.',
    'owner_legacy_id_unique_per_org': 'El nº de cliente anterior ya existe en otro cliente.',
}


def _humanize_exc(exc):
    from django.core.exceptions import ValidationError as DjangoValidationError
    text = str(exc)
    for constraint, friendly in _CONSTRAINT_MESSAGES.items():
        if constraint in text:
            return friendly
    if isinstance(exc, DjangoValidationError):
        try:
            parts = []
            for field, msgs in exc.message_dict.items():
                label = 'Datos' if field == '__all__' else field
                parts.append(f"{label}: {', '.join(str(m) for m in msgs)}")
            joined = '; '.join(parts)
            # Si algún mensaje aún arrastra el nombre del constraint, generizar.
            if any(c in joined for c in _CONSTRAINT_MESSAGES):
                return 'No se pudo importar la fila por un dato duplicado.'
            return joined or 'Datos inválidos.'
        except AttributeError:
            return '; '.join(str(m) for m in exc.messages)
    return 'No se pudo importar la fila.'
