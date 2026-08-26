"""
imports/services.py — Núcleo del importador (validación dry-run + commit atómico).

Reglas de negocio (entity_type=owner_pet), ver docs/project_import_sprint.md §6:

- owner.name  requerido (NAME_REGEX, reusado de patients).
- owner.phone OPCIONAL. Con teléfono → dedup por (org, teléfono normalizado),
  resuelta por `patients.services` (INV-C, ADR p57): el importador NUNCA elige
  entre expedientes duplicados. Dos o más con el mismo teléfono normalizado →
  error de fila `owner_ambiguous`, y lo mismo en la vista previa (§4.8: el
  preview no puede mostrar una reutilización que el commit rechazaría). Sin
  teléfono → se importa igual (sin clave de deduplicación); dedup interna por
  nombre normalizado dentro del MISMO archivo (no se inventan errores por falta
  de teléfono).
- pet.name    requerido (NAME_REGEX).
- pet.species requerida → normalize_species; no resoluble → error de fila.
- pet dedup   por (owner, normalize(name), species) — normalizado, NO string exacto.
- dedup_strategy=skip (v1): duplicado → se salta y se reporta (nunca pisa datos).
- Una fila inválida NO aborta el import: se salta con savepoint y se reporta
  (evita "500 filas → 120 errores → nada se importa").
"""
from django.db import transaction
from django.utils import timezone

from apps.core.datetime_utils import org_today_local
from apps.core.validators import phone_digits
from apps.patients.models import Owner, Pet
from apps.patients.serializers import NAME_REGEX
from apps.patients.services import (
    OwnerIdentityConflict,
    lookup_owner_by_phone,
    resolve_owner_for_phone,
)

from .models import ImportJob
from .normalization import (
    extra_target_fields,
    normalize_species,
    normalize_sex,
    normalize_text,
    required_fields,
    valid_target_fields,
)

_LEGACY_MAX = 64
# Datos del sistema anterior (Fase D): tope por registro y por valor (ajuste PO).
_EXTRA_MAX_ENTRIES = 50
_EXTRA_VALUE_MAX = 500
_EXTRA_LABEL_MAX = 120
# Vista previa: cuántas filas SÍ importables y cuántas omitidas se muestran
# en el frontend (el total real va en preview_total / skipped_total).
_PREVIEW_MAX = 20
_SKIPPED_SAMPLE_MAX = 10


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


def _extra_entry(spec, header, value, imported_at):
    """Una entrada de dato del sistema anterior (Fase D, decisión final PO).

    Forma: {label, value, source_column, imported_at}.
      - label:         nombre visible elegido durante la importación (o el header).
      - value:         valor importado (truncado).
      - source_column: nombre ORIGINAL de la columna del Excel/CSV — NO se pierde
                       aunque el usuario renombre el label (permite saber de dónde
                       vino el dato si se decide promoverlo a feature oficial).
      - imported_at:   fecha del proceso de importación (ISO). Solo al persistir.
    """
    entry = {
        'label': _spec_label(spec, header),
        'value': value[:_EXTRA_VALUE_MAX],
        'source_column': header.strip()[:_EXTRA_LABEL_MAX],
    }
    if imported_at:
        entry['imported_at'] = imported_at
    return entry


# ---------------------------------------------------------------------------
# Proyección fila → dict por campo destino
# ---------------------------------------------------------------------------
def _project_row(columns, mapping, row, imported_at=None,
                 extra_targets=('owner.extra', 'pet.extra')):
    """Aplica el mapping a una fila.

    Devuelve (data, extras):
      - data: { campo_destino_del_sistema: valor }  (1:1)
      - extras: { target_extra: [ {label, value, source_column[, imported_at]}, … ] }
        para los targets `*.extra` (Fase D, datos del sistema anterior). Se itera en
        ORDEN DE COLUMNA para preservar el orden original; labels repetidos conviven
        (lista, no dict). Caps: máx 50 entradas/registro, value truncado a 500 chars.
        `imported_at` solo se incluye al persistir (commit), no en el dry-run.
    mapping = { header: campo_destino }. Columnas no mapeadas se ignoran.

    `extra_targets` parametriza qué targets son "extra" (owner_pet usa
    owner.extra/pet.extra; inventory usa product.extra). El comportamiento por
    defecto es idéntico al histórico.
    """
    data = {}
    extras = {target: [] for target in extra_targets}
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
        if target in extras:
            extras[target].append(_extra_entry(spec, header, value, imported_at))
        else:
            data[target] = value
    return data, {
        target: entries[:_EXTRA_MAX_ENTRIES]
        for target, entries in extras.items()
    }


def _parse_birth_date(raw, org):
    """Devuelve (iso_date|None, ok). Acepta YYYY-MM-DD y DD/MM/YYYY.

    Fecha inválida ⇒ (None, False) → el caller la trata como WARNING (campo
    opcional y relajado): se importa la mascota sin fecha en lugar de fallar.

    `org` es obligatorio: "no puede ser futura" se evalúa contra el día local
    de la CLÍNICA, no contra el del servidor (regla de calendario del
    proyecto). Con `date.today()`, una importación hecha de noche rechazaba —o
    aceptaba— fechas de un día distinto al que ve la clínica.
    """
    import datetime
    value = (raw or '').strip()
    if not value:
        return None, True
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d'):
        try:
            d = datetime.datetime.strptime(value, fmt).date()
            if d > org_today_local(org):
                return None, False
            return d.isoformat(), True
        except ValueError:
            continue
    return None, False


# ---------------------------------------------------------------------------
# Limpieza + validación pura de una fila (sin DB) — testeable aislada
# ---------------------------------------------------------------------------
def clean_owner_pet_row(data, org):
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
        # D3 del inventario: la normalización converge a la del dominio
        # (`core.validators.phone_digits`). El importador conserva SU excepción
        # —teléfono vacío permitido— pero no su propia definición de "dígitos".
        digits = phone_digits(raw_phone)
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
    iso_birth, ok = _parse_birth_date(raw_birth, org)
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
    """Shape canónico del resultado de validate/commit del importador.

    Counts are authoritative. Arrays are capped samples for UI only.

    Los contadores agregados (`*_total`, `created_*`, `skipped_*`,
    `conflicts_high`/`conflicts_uncertain`, `blocking_rows`) son la fuente de
    verdad de TODO número que muestre la UI. Los arrays `preview`/`skipped`/
    `conflicts` son MUESTRAS para render de ejemplos — nunca usar su `.length`
    como conteo (ese bug vuelve; ver P1-6C1 / docs/modules/imports.md).
    """
    return {
        'created_owners': 0,
        'reused_owners': 0,
        'created_pets': 0,
        # Contadores de inventario (aditivos; owner_pet los deja en 0).
        'created_products': 0,
        'created_presentations': 0,
        'initial_stock_movements': 0,
        'skipped_duplicates': 0,
        'skipped_conflicts': 0,
        # Split agregado de skipped_conflicts (fuente única de verdad para el
        # desglose del frontend). Invariante: conflicts_high + conflicts_uncertain
        # == skipped_conflicts. Se mantienen vía _append_conflict().
        'conflicts_high': 0,
        'conflicts_uncertain': 0,
        'blocking_rows': 0,
        'error_rows': 0,          # alias backward-compat = blocking_rows
        'blocking': [],           # datos faltantes / imposibles
        'conflicts': [],          # duplicados por legacy_id con contexto
        'errors': [],             # alias backward-compat = blocking
        'warnings': [],
        'preview': [],            # filas que SÍ se importarán (cleaned, capped)
        'skipped': [],            # filas omitidas por duplicado de nombre (cleaned)
        'preview_total': 0,       # total real (puede ser > len(preview))
        'skipped_total': 0,       # total real (puede ser > len(skipped))
    }


def _append_conflict(result, conflict):
    """Registra un conflicto y mantiene los contadores agregados en sync —
    fuente única de verdad para los conteos que muestra el frontend.

    `result['conflicts']` es la MUESTRA (ejemplos para la UI); los contadores
    `skipped_conflicts` / `conflicts_high` / `conflicts_uncertain` son exactos
    aunque la muestra se cape en el futuro. Invariante garantizado:
    conflicts_high + conflicts_uncertain == skipped_conflicts.
    """
    result['skipped_conflicts'] += 1
    if conflict.get('match_confidence') == 'high':
        result['conflicts_high'] += 1
    else:
        result['conflicts_uncertain'] += 1
    result['conflicts'].append(conflict)


# INV-C: el desenlace `owner_ambiguous` es el MISMO en las tres pasadas
# (preview, dry-run y commit). Un solo mensaje para que el usuario lea lo mismo
# antes y después de aprobar el import.
_AMBIGUOUS_OWNER_ERROR = {
    'field': 'owner.phone',
    'code': 'owner_ambiguous',
    'message': (
        'Hay más de un cliente con este teléfono. Revisa los expedientes '
        'duplicados antes de importar esta fila.'
    ),
}


def _append_row_error(result, row_num, error):
    """Marca la fila como no importable (política vigente: se salta y se reporta).

    Una fila problemática NUNCA aborta el import. Al contarla aquí, el
    «se importarán N filas» que ve el usuario ya la excluye — que es la
    condición para que el preview coincida con el resultado real del commit.
    """
    result['blocking_rows'] += 1
    result['error_rows'] += 1
    entry = {'row': row_num, **error}
    result['blocking'].append(entry)
    result['errors'].append(entry)


def _preview_row(row_num, clean):
    """Helper: devuelve dict de preview con los campos de la fila importable."""
    return {
        'row': row_num,
        'owner_name': clean.get('owner_name', ''),
        'owner_phone': clean.get('owner_phone', ''),
        'pet_name': clean.get('pet_name', ''),
        'pet_species': clean.get('pet_species', ''),
        'pet_breed': clean.get('pet_breed', ''),
        'pet_sex': clean.get('pet_sex', ''),
        'pet_birth_date': clean.get('pet_birth_date', ''),
        'pet_color': clean.get('pet_color', ''),
        'pet_legacy_id': clean.get('pet_legacy_id', ''),
    }


# ---------------------------------------------------------------------------
# Bulk fetch del contexto existente (evita N+1 en archivos grandes)
# ---------------------------------------------------------------------------
def _build_existing_index(org, rows, columns, mapping):
    """Recolecta todos los legacy_id del archivo y los busca en DB de una vez.

    Devuelve (pet_by_legacy, owner_by_legacy) donde cada dict mapea:
        legacy_id → {name/public_id fields}  (solo public_id, nunca PK).
    """
    pet_legacy_ids = set()
    owner_legacy_ids = set()
    for row in rows:
        data, _extras = _project_row(columns, mapping, row)
        ol = (data.get('owner.legacy_id') or '').strip()[:_LEGACY_MAX]
        pl = (data.get('pet.legacy_id') or '').strip()[:_LEGACY_MAX]
        if ol:
            owner_legacy_ids.add(ol)
        if pl:
            pet_legacy_ids.add(pl)

    pet_by_legacy = {}
    if pet_legacy_ids:
        qs = Pet.objects.for_organization(org).filter(
            legacy_id__in=pet_legacy_ids,
        ).select_related('owner').values('legacy_id', 'name', 'public_id', 'owner__name')
        for p in qs:
            pet_by_legacy[p['legacy_id']] = {
                'pet_name': p['name'],
                'owner_name': p['owner__name'],
                'public_id': str(p['public_id']),
            }

    owner_by_legacy = {}
    if owner_legacy_ids:
        qs = Owner.objects.for_organization(org).filter(
            legacy_id__in=owner_legacy_ids,
        ).values('legacy_id', 'name', 'public_id')
        for o in qs:
            owner_by_legacy[o['legacy_id']] = {
                'name': o['name'],
                'public_id': str(o['public_id']),
            }

    return pet_by_legacy, owner_by_legacy


def _compute_match_confidence(incoming, existing, scope='pet'):
    """Calcula match_confidence entre el incoming (fila) y el existing (DB).

    - 'high' → pet_name Y owner_name coinciden normalizados.
    - 'uncertain' → legacy_id coincide pero algún nombre difiere.
    """
    if scope == 'pet':
        pet_match = normalize_text(incoming.get('pet_name', '')) == normalize_text(existing.get('pet_name', ''))
        owner_match = normalize_text(incoming.get('owner_name', '')) == normalize_text(existing.get('owner_name', ''))
        return 'high' if (pet_match and owner_match) else 'uncertain'
    else:
        # owner scope: solo comparar owner_name
        owner_match = normalize_text(incoming.get('owner_name', '')) == normalize_text(existing.get('name', ''))
        return 'high' if owner_match else 'uncertain'


# ---------------------------------------------------------------------------
# VALIDATE (dry-run) — no escribe nada
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Dispatch por entity_type (owner_pet = histórico; inventory = services_inventory)
# ---------------------------------------------------------------------------
def validate_job(job):
    """Punto de entrada de validate: despacha por el entity_type del job."""
    if job.entity_type == ImportJob.ENTITY_INVENTORY:
        from .services_inventory import validate_inventory_job
        return validate_inventory_job(job)
    return _validate_owner_pet_job(job)


def commit_job(job, created_by=None):
    """Punto de entrada de commit: despacha por el entity_type del job.
    `created_by` se propaga al inventario para auditar StockMovement.created_by;
    owner_pet lo ignora (paridad con su comportamiento histórico)."""
    if job.entity_type == ImportJob.ENTITY_INVENTORY:
        from .services_inventory import commit_inventory_job
        return commit_inventory_job(job, created_by=created_by)
    return _commit_owner_pet_job(job)


def _validate_owner_pet_job(job):
    """Recorre las filas y predice el resultado SIN escribir. Idempotente.

    La fila del archivo es la unidad lógica:
    - Si la mascota entra → crear/reusar owner (predicción).
    - Si la mascota se omite (duplicado por nombre o conflicto legacy_id) → no
      contar owner. El preview es honesto: predice lo mismo que commit_job.
    """
    result = _base_result()
    problems = check_mapping(job)
    if problems:
        result['blocking'] = [{'row': 0, 'field': 'mapping', 'message': p} for p in problems]
        result['errors'] = result['blocking']
        result['blocking_rows'] = len(problems)
        result['error_rows'] = len(problems)
        return result

    org = job.organization
    columns = job.source_columns

    # Bulk fetch del contexto existente (evita N+1).
    pet_by_legacy, owner_by_legacy = _build_existing_index(
        org, job.rows, columns, job.mapping,
    )

    # Caches de predicción.
    owner_keys_new = set()
    owner_keys_existing = {}
    seen_pet_keys = set()
    seen_owner_legacy = set()
    seen_pet_legacy = set()

    for i, row in enumerate(job.rows, start=1):
        data, _extras = _project_row(columns, job.mapping, row)
        clean, errors, warnings = clean_owner_pet_row(data, org)
        for w in warnings:
            result['warnings'].append({'row': i, **w})
        if errors:
            result['blocking_rows'] += 1
            result['error_rows'] += 1
            for e in errors:
                result['blocking'].append({'row': i, **e})
                result['errors'].append({'row': i, **e})
            continue

        # --- 1. Resolver identidad del owner SOLO por lectura (sin contar) ---
        # E3 del inventario (INV-C, §4.8): el MISMO resolvedor que usa el
        # commit, en modo lectura. Antes esta pasada hacía `.first()` sobre los
        # duplicados: el preview decía "se reutilizará el cliente X" y el commit
        # rechazaba esa misma fila. El usuario aprobaba una cosa y obtenía otra.
        phone = clean['owner_phone']
        if phone:
            owner_key = ('phone', phone)
            if owner_key in owner_keys_existing or owner_key in owner_keys_new:
                owner_is_new = False
            else:
                lookup = lookup_owner_by_phone(org, phone)
                if lookup.is_ambiguous:
                    _append_row_error(result, i, _AMBIGUOUS_OWNER_ERROR)
                    continue
                if lookup.owner is not None:
                    owner_keys_existing[owner_key] = lookup.owner.pk
                    owner_is_new = False
                else:
                    owner_is_new = True
        else:
            owner_key = ('name', normalize_text(clean['owner_name']))
            owner_is_new = owner_key not in owner_keys_new and owner_key not in owner_keys_existing

        # --- 2. Conflicto de legacy_id de cliente ---
        owner_legacy = clean['owner_legacy_id']
        if owner_is_new and owner_legacy:
            if owner_legacy in seen_owner_legacy:
                _append_conflict(result, {
                    'row': i, 'type': 'duplicate_legacy_id',
                    'severity': 'conflict', 'scope': 'owner',
                    'match_confidence': 'high',
                    'message': 'Ya existe un cliente con este número en el archivo.',
                    'incoming': {'owner_name': clean['owner_name'], 'legacy_id': owner_legacy},
                    'existing': {},
                })
                continue
            if owner_legacy in owner_by_legacy:
                existing_owner = owner_by_legacy[owner_legacy]
                _append_conflict(result, {
                    'row': i, 'type': 'duplicate_legacy_id',
                    'severity': 'conflict', 'scope': 'owner',
                    'match_confidence': _compute_match_confidence(
                        {'owner_name': clean['owner_name']}, existing_owner, scope='owner',
                    ),
                    'message': 'Ya existe un cliente con este número.',
                    'incoming': {'owner_name': clean['owner_name'], 'legacy_id': owner_legacy},
                    'existing': {'owner_name': existing_owner.get('name', ''),
                                 'public_id': existing_owner.get('public_id', '')},
                })
                continue
            if Owner.objects.for_organization(org).filter(legacy_id=owner_legacy).exists():
                _append_conflict(result, {
                    'row': i, 'type': 'duplicate_legacy_id',
                    'severity': 'conflict', 'scope': 'owner',
                    'match_confidence': 'uncertain',
                    'message': 'Ya existe un cliente con este número.',
                    'incoming': {'owner_name': clean['owner_name'], 'legacy_id': owner_legacy},
                    'existing': {},
                })
                continue

        # --- 3. Decidir el pet ANTES de contar el owner ---
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
            if len(result['skipped']) < _SKIPPED_SAMPLE_MAX:
                result['skipped'].append({
                    **(_preview_row(i, clean)),
                    'reason': 'duplicate',
                    'message': 'Ya existe un paciente con el mismo nombre para este cliente.',
                })
            result['skipped_total'] += 1
            continue

        # Conflicto de legacy_id de mascota.
        pet_legacy = clean['pet_legacy_id']
        if pet_legacy:
            if pet_legacy in seen_pet_legacy:
                _append_conflict(result, {
                    'row': i, 'type': 'duplicate_legacy_id',
                    'severity': 'conflict', 'scope': 'pet',
                    'match_confidence': 'high',
                    'message': 'Ya existe una mascota con este expediente en el archivo.',
                    'incoming': {'pet_name': clean['pet_name'],
                                 'owner_name': clean['owner_name'],
                                 'legacy_id': pet_legacy},
                    'existing': {},
                })
                continue
            if pet_legacy in pet_by_legacy:
                existing_pet = pet_by_legacy[pet_legacy]
                _append_conflict(result, {
                    'row': i, 'type': 'duplicate_legacy_id',
                    'severity': 'conflict', 'scope': 'pet',
                    'match_confidence': _compute_match_confidence(
                        {'pet_name': clean['pet_name'],
                         'owner_name': clean['owner_name']},
                        existing_pet, scope='pet',
                    ),
                    'message': 'Ya existe una mascota con este expediente.',
                    'incoming': {'pet_name': clean['pet_name'],
                                 'owner_name': clean['owner_name'],
                                 'legacy_id': pet_legacy},
                    'existing': {'pet_name': existing_pet['pet_name'],
                                 'owner_name': existing_pet['owner_name'],
                                 'public_id': existing_pet['public_id']},
                })
                continue
            if Pet.objects.for_organization(org).filter(legacy_id=pet_legacy).exists():
                _append_conflict(result, {
                    'row': i, 'type': 'duplicate_legacy_id',
                    'severity': 'conflict', 'scope': 'pet',
                    'match_confidence': 'uncertain',
                    'message': 'Ya existe una mascota con este expediente.',
                    'incoming': {'pet_name': clean['pet_name'],
                                 'owner_name': clean['owner_name'],
                                 'legacy_id': pet_legacy},
                    'existing': {},
                })
                continue

        # --- 4. El pet ENTRA: ahora sí contar el owner y el pet ---
        if owner_is_new:
            owner_keys_new.add(owner_key)
            if owner_legacy:
                seen_owner_legacy.add(owner_legacy)
            result['created_owners'] += 1
        else:
            result['reused_owners'] += 1

        seen_pet_keys.add(pet_key)
        if pet_legacy:
            seen_pet_legacy.add(pet_legacy)
        result['created_pets'] += 1

        # Vista previa de lo que SÍ se importará (capped).
        if len(result['preview']) < _PREVIEW_MAX:
            result['preview'].append(_preview_row(i, clean))
        result['preview_total'] += 1

    return result


# ---------------------------------------------------------------------------
# COMMIT — escribe en transaction.atomic, savepoint por fila
# ---------------------------------------------------------------------------
def _commit_owner_pet_job(job):
    """Escribe los registros. Atómico a nivel job; savepoint por fila (una fila
    mala no tumba el resto). Devuelve result. NO marca el status (lo hace la view).

    La fila del archivo es la unidad lógica:
    - Si la mascota entra → crear/reusar owner (savepoint) + crear pet (savepoint).
    - Si la mascota se omite (duplicado por nombre o conflicto legacy_id) → no
      crear owner. Cero owners huérfanos.
    - Un owner compartido por varias filas se materializa con el primer pet que
      entra; las demás filas lo reúsan.
    """
    result = _base_result()
    problems = check_mapping(job)
    if problems:
        result['blocking'] = [{'row': 0, 'field': 'mapping', 'message': p} for p in problems]
        result['errors'] = result['blocking']
        result['blocking_rows'] = len(problems)
        result['error_rows'] = len(problems)
        return result

    org = job.organization
    columns = job.source_columns

    # Bulk fetch del contexto existente (evita N+1).
    pet_by_legacy, owner_by_legacy = _build_existing_index(
        org, job.rows, columns, job.mapping,
    )

    owners_by_phone = {}        # phone -> Owner (existente o creado)
    owners_by_name = {}         # norm_name -> Owner (phoneless, within-file)
    seen_pet_keys = set()       # (owner_key, norm_name, species) — virtual para nuevos
    seen_owner_legacy = set()   # legacy_id de owners creados en este job
    seen_pet_legacy = set()     # legacy_id de pets creados en este job
    # Una sola marca de tiempo para todo el job: identifica el proceso de
    # importación que originó cada dato del sistema anterior.
    imported_at = timezone.now().isoformat()

    with transaction.atomic():
        for i, row in enumerate(job.rows, start=1):
            data, extras = _project_row(columns, job.mapping, row, imported_at)
            owner_extra = extras.get('owner.extra', [])
            pet_extra = extras.get('pet.extra', [])
            clean, errors, warnings = clean_owner_pet_row(data, org)
            for w in warnings:
                result['warnings'].append({'row': i, **w})
            if errors:
                result['blocking_rows'] += 1
                result['error_rows'] += 1
                for e in errors:
                    result['blocking'].append({'row': i, **e})
                    result['errors'].append({'row': i, **e})
                continue

            # --- 1. Resolver identidad del owner SOLO por lectura (sin INSERT) ---
            # Modo lectura del resolvedor único (INV-C): el owner todavía no se
            # materializa aquí — solo se necesita saber si existe para decidir
            # el duplicado de mascota. La resolución REAL, con el lock de
            # deduplicación, ocurre en el paso 4 (`_resolve_owner`).
            phone = clean['owner_phone']
            if phone:
                if phone in owners_by_phone:
                    owner = owners_by_phone[phone]
                    owner_is_new = False
                else:
                    lookup = lookup_owner_by_phone(org, phone)
                    if lookup.is_ambiguous:
                        _append_row_error(result, i, _AMBIGUOUS_OWNER_ERROR)
                        continue
                    owner = lookup.owner
                    if owner is not None:
                        owners_by_phone[phone] = owner
                        owner_is_new = False
                    else:
                        owner_is_new = True
                owner_key = ('phone', phone)
            else:
                name_key = normalize_text(clean['owner_name'])
                owner = owners_by_name.get(name_key)
                owner_is_new = owner is None
                owner_key = ('name', name_key)

            # --- 2. Conflicto de legacy_id de cliente ---
            owner_legacy = clean['owner_legacy_id']
            if owner_is_new and owner_legacy:
                if owner_legacy in seen_owner_legacy:
                    _append_conflict(result, {
                        'row': i, 'type': 'duplicate_legacy_id',
                        'severity': 'conflict', 'scope': 'owner',
                        'match_confidence': 'high',
                        'message': 'Ya existe un cliente con este número en el archivo.',
                        'incoming': {'owner_name': clean['owner_name'], 'legacy_id': owner_legacy},
                        'existing': {},
                    })
                    continue
                if owner_legacy in owner_by_legacy:
                    existing_owner = owner_by_legacy[owner_legacy]
                    _append_conflict(result, {
                        'row': i, 'type': 'duplicate_legacy_id',
                        'severity': 'conflict', 'scope': 'owner',
                        'match_confidence': _compute_match_confidence(
                            {'owner_name': clean['owner_name']}, existing_owner, scope='owner',
                        ),
                        'message': 'Ya existe un cliente con este número.',
                        'incoming': {'owner_name': clean['owner_name'], 'legacy_id': owner_legacy},
                        'existing': {'owner_name': existing_owner.get('name', ''),
                                     'public_id': existing_owner.get('public_id', '')},
                    })
                    continue
                if Owner.objects.for_organization(org).filter(legacy_id=owner_legacy).exists():
                    _append_conflict(result, {
                        'row': i, 'type': 'duplicate_legacy_id',
                        'severity': 'conflict', 'scope': 'owner',
                        'match_confidence': 'uncertain',
                        'message': 'Ya existe un cliente con este número.',
                        'incoming': {'owner_name': clean['owner_name'], 'legacy_id': owner_legacy},
                        'existing': {},
                    })
                    continue

            # --- 3. Decidir el pet ANTES de materializar el owner ---
            # Dedup por nombre (within-file + DB para owners existentes).
            pet_key = (owner_key, normalize_text(clean['pet_name']), clean['pet_species'])
            if pet_key in seen_pet_keys:
                result['skipped_duplicates'] += 1
                continue
            if owner is not None and _pet_exists(org, owner, clean):
                result['skipped_duplicates'] += 1
                continue

            # Conflicto de legacy_id de mascota.
            pet_legacy = clean['pet_legacy_id']
            if pet_legacy:
                if pet_legacy in seen_pet_legacy:
                    _append_conflict(result, {
                        'row': i, 'type': 'duplicate_legacy_id',
                        'severity': 'conflict', 'scope': 'pet',
                        'match_confidence': 'high',
                        'message': 'Ya existe una mascota con este expediente en el archivo.',
                        'incoming': {'pet_name': clean['pet_name'],
                                     'owner_name': clean['owner_name'],
                                     'legacy_id': pet_legacy},
                        'existing': {},
                    })
                    continue
                if pet_legacy in pet_by_legacy:
                    existing_pet = pet_by_legacy[pet_legacy]
                    _append_conflict(result, {
                        'row': i, 'type': 'duplicate_legacy_id',
                        'severity': 'conflict', 'scope': 'pet',
                        'match_confidence': _compute_match_confidence(
                            {'pet_name': clean['pet_name'],
                             'owner_name': clean['owner_name']},
                            existing_pet, scope='pet',
                        ),
                        'message': 'Ya existe una mascota con este expediente.',
                        'incoming': {'pet_name': clean['pet_name'],
                                     'owner_name': clean['owner_name'],
                                     'legacy_id': pet_legacy},
                        'existing': {'pet_name': existing_pet['pet_name'],
                                     'owner_name': existing_pet['owner_name'],
                                     'public_id': existing_pet['public_id']},
                    })
                    continue
                if Pet.objects.for_organization(org).filter(legacy_id=pet_legacy).exists():
                    _append_conflict(result, {
                        'row': i, 'type': 'duplicate_legacy_id',
                        'severity': 'conflict', 'scope': 'pet',
                        'match_confidence': 'uncertain',
                        'message': 'Ya existe una mascota con este expediente.',
                        'incoming': {'pet_name': clean['pet_name'],
                                     'owner_name': clean['owner_name'],
                                     'legacy_id': pet_legacy},
                        'existing': {},
                    })
                    continue

            # --- 4. El pet ENTRA: ahora sí materializar/reusar el owner ---
            # Owner en SU PROPIO savepoint. owner_extra se aplica SOLO al crear
            # (la 1ª fila gana); un owner reusado conserva su extra_data de creación.
            try:
                with transaction.atomic():
                    owner, owner_status = _resolve_owner(
                        org, clean, owners_by_phone, owners_by_name,
                        owner_extra=owner_extra,
                    )
            except OwnerIdentityConflict as exc:
                # Desenlace de NEGOCIO (INV-C), no avería: el teléfono tiene más
                # de un expediente. Se reporta con el mismo mensaje que mostró
                # la vista previa y la fila se salta — política vigente del
                # importador para filas problemáticas.
                _append_row_error(result, i, {
                    'field': 'owner.phone',
                    'code': exc.default_code,
                    'message': str(exc.detail),
                })
                continue
            except Exception as exc:  # noqa: BLE001 — fila aislada por savepoint
                _append_row_error(result, i, {
                    'field': 'owner', 'message': _humanize_exc(exc),
                })
                continue
            if owner_status == 'created':
                result['created_owners'] += 1
                if owner_legacy:
                    seen_owner_legacy.add(owner_legacy)
            else:
                result['reused_owners'] += 1

            # --- Crear el pet en su propio savepoint ---
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
                if pet_legacy:
                    seen_pet_legacy.add(pet_legacy)
                result['created_pets'] += 1
            except Exception as exc:  # noqa: BLE001 — fila aislada por savepoint
                _append_row_error(result, i, {
                    'field': 'pet', 'message': _humanize_exc(exc),
                })

    return result


def _resolve_owner(org, clean, owners_by_phone, owners_by_name, owner_extra=None):
    """Devuelve (Owner, status) donde status ∈ {'created', 'reused'}.

    'created' la primera vez que se materializa un owner nuevo; 'reused' si ya
    existía en DB o si una fila previa de este mismo archivo ya lo resolvió.
    owner_extra solo se persiste al crear (no se mezcla en owners reusados).

    A4·B3 del inventario (INV-C, ADR p57): delega en el servicio único de
    `patients`, que toma el lock de deduplicación `(organización, teléfono
    normalizado)` y cuenta bajo él. El `.first()` que había aquí **elegía** una
    fila entre los duplicados históricos — exactamente lo que INV-C prohíbe.
    Ahora ese caso levanta `OwnerAmbiguous` y el commit lo convierte en error
    de fila.

    `match_name=False` a propósito: la regla documentada del importador es
    dedup **por teléfono**, no por `(nombre, teléfono)`. Endurecerla partiría
    archivos que hoy importan bien, y esa no es una decisión de F1.

    Nota de escala: el lock es a nivel de transacción y el commit del job es
    UNA transacción, así que los locks se acumulan hasta el final —uno por
    teléfono nuevo—. `parsers.MAX_ROWS = 2000` acota el máximo; subir ese tope
    obliga a revisar `max_locks_per_transaction`.
    """
    phone = clean['owner_phone']
    if phone and phone in owners_by_phone:
        return owners_by_phone[phone], 'reused'
    if not phone:
        # Sin teléfono no hay clave de deduplicación: dedup interna por nombre
        # normalizado dentro del MISMO archivo (regla vigente del importador).
        name_key = normalize_text(clean['owner_name'])
        if name_key in owners_by_name:
            return owners_by_name[name_key], 'reused'

    owner, status = resolve_owner_for_phone(
        org,
        phone=phone,
        name=clean['owner_name'],
        defaults={
            'legacy_id': clean['owner_legacy_id'],
            # `owner_extra` solo se persiste al CREAR; el servicio ignora los
            # defaults cuando reutiliza, así que un owner existente conserva su
            # extra_data de creación.
            'extra_data': owner_extra or [],
        },
    )
    if phone:
        owners_by_phone[phone] = owner
    else:
        owners_by_name[normalize_text(clean['owner_name'])] = owner
    return owner, status


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
