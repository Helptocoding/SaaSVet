"""
imports/services_inventory.py — Reglas de negocio del importador de inventario
(entity_type='inventory'). Plan: docs/PLAN-importador-inventario.md.

Grano del archivo (D5): 1 fila = 1 Product + SU Presentation única (la
principal). Multi-presentación por producto queda excluida de esta fase.

Reglas clave:
- product.name y presentation.sale_price son REQUIRED (CHECK DB
  `presentation_sale_price_positive` exige >0; billing lo consume). Sin precio
  válido ⇒ fila bloqueante. Nunca se inventan valores monetarios.
- Identidad de dedup: internal_code (único por organización). Filas SIN código
  con nombre normalizado repetido (en archivo o en catálogo) ⇒ conflicto
  UNCERTAIN (`duplicate_name`): la fila se omite Y se reporta — nunca dedup
  automática silenciosa ni creación automática (§5.2 del plan).
- Stock inicial SOLO vía `apply_stock_movement(..., 'in')` dentro del savepoint
  de fila: lock de Product, dual-write a Presentation.stock (unidades de
  presentación) y StockMovement(quantity_unit='base') auditable. Razón fija
  STOCK_INITIAL_REASON para mantener el movimiento filtrable.
- validate NO escribe nada; comparte proyección/limpieza con commit (el preview
  no miente). Commit es UNA transacción con savepoint por fila.
"""
import uuid
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from apps.inventory.models import Product, Presentation
from apps.inventory.serializers import PRODUCT_NAME_REGEX
from apps.inventory.services import apply_stock_movement

from .normalization import (
    normalize_base_unit,
    normalize_category,
    normalize_text,
    parse_bool,
    parse_decimal,
)
from .services import (
    _append_conflict,
    _append_row_error,
    _base_result,
    _project_row,
    check_mapping,
)

_CODE_MAX = 100           # Product.internal_code.max_length
_BARCODE_MAX = 100        # Presentation.barcode.max_length
_NAME_MAX = 255           # Product.name / Presentation.name
_MANUFACTURER_MAX = 255
_DESCRIPTION_MAX = 2000   # cap defensivo sobre TextField sin límite
_MONEY = Decimal('0.01')  # Presentation.* son decimal_places=2
_QTY4 = Decimal('0.0001')
# Topes de campo (max_digits): money Decimal(10,2) ⇒ < 10^8; cf Decimal(10,4) ⇒
# < 10^6. Se validan en CLEAN (validate-time) para que el preview sea honesto:
# un valor fuera de rango jamás llega al commit a reventar en full_clean.
_MONEY_MAX = Decimal('100000000')
_CF_MAX = Decimal('1000000')

STOCK_INITIAL_REASON = 'Stock inicial (importación)'


def _money(value):
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _qty4(value):
    return value.quantize(_QTY4, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Limpieza + validación pura de una fila (sin DB) — compartida validate/commit
# ---------------------------------------------------------------------------
def clean_inventory_row(data, org):
    """Valida y normaliza una fila inventory. Devuelve (clean, errors, warnings).

    Determinista: un valor ambiguo NUNCA se convierte silenciosamente en válido
    ("abc" → decimal es ERROR; bool ambiguo es ERROR). Defaults solo para
    ausencias legítimas (stock→0, cf→1, categoría→other…).
    """
    errors = []
    warnings = []
    clean = {}

    # --- Producto ---
    name = (data.get('product.name') or '').strip()
    if not name:
        errors.append({'field': 'product.name', 'message': 'El nombre del producto es requerido.'})
    elif not PRODUCT_NAME_REGEX.match(name):
        errors.append({'field': 'product.name', 'message': 'El nombre del producto contiene caracteres no permitidos.'})
    clean['name'] = name[:_NAME_MAX]

    clean['internal_code'] = (data.get('product.internal_code') or '').strip()[:_CODE_MAX]

    raw_category = (data.get('product.category') or '').strip()
    category = normalize_category(raw_category)
    if not raw_category:
        category = 'other'  # default del modelo; ausencia legítima, sin warning
    elif category is None:
        warnings.append({
            'field': 'product.category',
            'message': f'Categoría no reconocida ("{raw_category}") — se importará como "Otro".',
        })
        category = 'other'
    clean['category'] = category

    # D4: Presentation.base_unit es NOT NULL y no existe estado "pendiente" —
    # ausente o no reconocida ⇒ warning + 'unit'.
    raw_unit = (data.get('product.base_unit') or '').strip()
    unit = normalize_base_unit(raw_unit)
    if unit is None:
        if raw_unit:
            warnings.append({
                'field': 'product.base_unit',
                'message': f'Unidad no reconocida ("{raw_unit}") — se importará como "Unidad".',
            })
        else:
            warnings.append({
                'field': 'product.base_unit',
                'message': 'Sin unidad — se importará como "Unidad".',
            })
        unit = 'unit'
    clean['base_unit'] = unit

    # Bool estricto: requiere receta afecta billing/receta ⇒ ambiguo = ERROR.
    raw_rx = (data.get('product.requires_prescription') or '').strip()
    rx = parse_bool(raw_rx)
    if raw_rx and rx is None:
        errors.append({
            'field': 'product.requires_prescription',
            'message': f'Valor de "requiere receta" no reconocido: "{raw_rx}". Usa Sí/No.',
        })
    clean['requires_prescription'] = bool(rx)

    clean['manufacturer'] = (data.get('product.manufacturer') or '').strip()[:_MANUFACTURER_MAX]
    clean['description'] = (data.get('product.description') or '').strip()[:_DESCRIPTION_MAX]

    # --- Presentación ---
    clean['pres_name'] = (data.get('presentation.name') or '').strip()[:_NAME_MAX]
    clean['barcode'] = (data.get('presentation.barcode') or '').strip()[:_BARCODE_MAX]

    def _decimal_field(target, *, label, required=False, positive=False):
        """Parseo estricto de un campo decimal. Devuelve Decimal|None (None=error ya reportado)."""
        raw = (data.get(target) or '').strip()
        if not raw:
            if required:
                errors.append({'field': target, 'message': f'{label} es requerido.'})
            return None
        value, ok = parse_decimal(raw)
        if not ok:
            errors.append({'field': target, 'message': f'{label} inválido: "{raw}".'})
            return None
        if positive and value <= 0:
            errors.append({'field': target, 'message': f'{label} debe ser mayor a 0.'})
            return None
        if value < 0:
            errors.append({'field': target, 'message': f'{label} no puede ser negativo.'})
            return None
        return value

    # Precio de venta REQUIRED (D3): sin precio válido ⇒ bloqueante.
    sale_price = _decimal_field(
        'presentation.sale_price', label='El precio de venta', required=True, positive=True,
    )
    if sale_price is not None and abs(sale_price) >= _MONEY_MAX:
        errors.append({'field': 'presentation.sale_price', 'message': 'El precio de venta excede el máximo permitido.'})
    clean['sale_price'] = _money(sale_price) if sale_price is not None else None

    purchase_price = _decimal_field('presentation.purchase_price', label='El precio de compra')
    if purchase_price is not None and abs(purchase_price) >= _MONEY_MAX:
        errors.append({'field': 'presentation.purchase_price', 'message': 'El precio de compra excede el máximo permitido.'})
    clean['purchase_price'] = _money(purchase_price) if purchase_price is not None else None

    stock = _decimal_field('product.stock', label='La existencia inicial')
    if stock is not None and stock >= _MONEY_MAX:
        errors.append({'field': 'product.stock', 'message': 'La existencia inicial excede el máximo permitido.'})
    clean['stock'] = _money(stock) if stock is not None else Decimal('0')

    min_stock = _decimal_field('product.min_stock', label='El stock mínimo')
    if min_stock is not None and min_stock >= _MONEY_MAX:
        errors.append({'field': 'product.min_stock', 'message': 'El stock mínimo excede el máximo permitido.'})
    clean['min_stock'] = _money(min_stock) if min_stock is not None else Decimal('0')

    factor = _decimal_field(
        'presentation.conversion_factor', label='El factor de conversión', positive=True,
    )
    if factor is not None and factor >= _CF_MAX:
        errors.append({'field': 'presentation.conversion_factor', 'message': 'El factor de conversión excede el máximo permitido.'})
    if factor is None:
        clean['conversion_factor'] = Decimal('1')
        clean['quantity'] = Decimal('1')
    else:
        cf = _qty4(factor)
        if cf <= 0:
            # p.ej. "0.00001" redondea a 0 con 4 decimales: no es un factor válido.
            errors.append({
                'field': 'presentation.conversion_factor',
                'message': 'El factor de conversión debe ser mayor a 0.',
            })
            cf = Decimal('1')
        clean['conversion_factor'] = cf
        # Orden 4, I02: desde inventory.0028 el alias admite los mismos 4 decimales que el
        # factor, así que se copia exacto, igual que en el alta manual.
        clean['quantity'] = cf

    # Derivados a unidades base (paridad con alta manual: stock×cf).
    clean['stock_base'] = _qty4(clean['stock'] * clean['conversion_factor'])
    clean['min_stock_base'] = _qty4(clean['min_stock'] * clean['conversion_factor'])

    return clean, errors, warnings


# ---------------------------------------------------------------------------
# Bulk fetch del contexto existente (evita N+1)
# ---------------------------------------------------------------------------
def _build_existing_index(org, rows, columns, mapping):
    """Pre-chequeo honesto de duplicados contra la org.

    Devuelve (product_by_code, pres_by_barcode, db_names):
      - product_by_code: {normalize_text(internal_code): {name, public_id}}
      - pres_by_barcode: {barcode: {product_name, public_id}}  (solo no vacíos)
      - db_names: {normalize_text(name): {name, public_id}} — catálogo completo
        de la org en UNA query (los nombres no filtran por SQL normalizado).
    """
    codes = set()
    barcodes = set()
    for row in rows:
        data, _extras = _project_row(columns, mapping, row, extra_targets=('product.extra',))
        code = (data.get('product.internal_code') or '').strip()
        barcode = (data.get('presentation.barcode') or '').strip()
        if code:
            codes.add(code)
        if barcode:
            barcodes.add(barcode)

    product_by_code = {}
    if codes:
        qs = (
            Product.objects.for_organization(org)
            .filter(internal_code__in=codes)
            .values('internal_code', 'name', 'public_id')
        )
        for p in qs:
            product_by_code[normalize_text(p['internal_code'])] = {
                'name': p['name'],
                'public_id': str(p['public_id']),
            }

    pres_by_barcode = {}
    if barcodes:
        qs = (
            Presentation.objects.for_organization(org)
            .filter(barcode__in=barcodes)
            .values('barcode', 'product__name', 'public_id')
        )
        for p in qs:
            pres_by_barcode[p['barcode']] = {
                'product_name': p['product__name'],
                'public_id': str(p['public_id']),
            }

    db_names = {}
    for p in Product.objects.for_organization(org).values('name', 'public_id'):
        db_names.setdefault(normalize_text(p['name']), {
            'name': p['name'],
            'public_id': str(p['public_id']),
        })

    return product_by_code, pres_by_barcode, db_names


def _project_inventory_row(columns, mapping, row, imported_at=None):
    data, extras = _project_row(columns, mapping, row, imported_at,
                                extra_targets=('product.extra',))
    return data, extras.get('product.extra', [])


def _preview_inventory_row(row_num, clean):
    """Fila de preview (solo strings: job.result es JSONField)."""
    return {
        'row': row_num,
        'name': clean.get('name', ''),
        'internal_code': clean.get('internal_code', ''),
        'category': clean.get('category', ''),
        'base_unit': clean.get('base_unit', ''),
        'stock': str(clean.get('stock', '')),
        'sale_price': str(clean.get('sale_price', '')),
        'barcode': clean.get('barcode', ''),
    }


_PREVIEW_MAX = 20  # paridad con services._PREVIEW_MAX


def _run_inventory_pass(job, persist, created_by=None):
    """Núcleo compartido de validate/commit (el preview no miente).

    persist=False → dry-run: SOLO lectura y predicción.
    persist=True  → escritura real; DEBE llamarse dentro de transaction.atomic()
                    (lo garantiza commit_inventory_job).
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

    product_by_code, pres_by_barcode, db_names = _build_existing_index(
        org, job.rows, columns, job.mapping,
    )

    seen_codes = {}         # norm_code -> {'name': norm_name} (filas de este job)
    seen_barcodes = set()   # barcodes (exactos) de este job
    seen_nocode_names = set()  # nombres normalizados de filas SIN código aceptadas

    imported_at = timezone.now().isoformat() if persist else None

    for i, row in enumerate(job.rows, start=1):
        data, product_extra = _project_inventory_row(columns, job.mapping, row, imported_at)
        clean, errors, warnings = clean_inventory_row(data, org)
        for w in warnings:
            result['warnings'].append({'row': i, **w})
        if errors:
            # Paridad owner_pet: la fila cuenta UNA vez aunque acumule N errores.
            result['blocking_rows'] += 1
            result['error_rows'] += 1
            for e in errors:
                entry = {'row': i, **e}
                result['blocking'].append(entry)
                result['errors'].append(entry)
            continue

        code_key = normalize_text(clean['internal_code'])
        name_key = normalize_text(clean['name'])
        barcode = clean['barcode']

        # --- Conflicto fuerte: barcode ---
        if barcode:
            if barcode in seen_barcodes:
                _append_conflict(result, {
                    'row': i, 'type': 'duplicate_barcode',
                    'severity': 'conflict', 'scope': 'presentation',
                    'match_confidence': 'high',
                    'message': 'Ya existe una presentación con este código de barras en el archivo.',
                    'incoming': {
                        'name': clean['name'],
                        'internal_code': clean['internal_code'],
                        'barcode': barcode,
                    },
                    'existing': {},
                })
                continue
            if barcode in pres_by_barcode:
                existing = pres_by_barcode[barcode]
                _append_conflict(result, {
                    'row': i, 'type': 'duplicate_barcode',
                    'severity': 'conflict', 'scope': 'presentation',
                    'match_confidence': 'high',
                    'message': 'Ya existe una presentación con este código de barras.',
                    'incoming': {
                        'name': clean['name'],
                        'internal_code': clean['internal_code'],
                        'barcode': barcode,
                    },
                    'existing': {
                        'product_name': existing['product_name'],
                        'public_id': existing['public_id'],
                    },
                })
                continue
            seen_barcodes.add(barcode)

        # --- Identidad por código (fuerte) ---
        if code_key:
            if code_key in seen_codes:
                confidence = (
                    'high' if seen_codes[code_key]['name'] == name_key else 'uncertain'
                )
                _append_conflict(result, {
                    'row': i, 'type': 'duplicate_internal_code',
                    'severity': 'conflict', 'scope': 'product',
                    'match_confidence': confidence,
                    'message': 'Ya existe un producto con este código interno en el archivo.',
                    'incoming': {
                        'name': clean['name'],
                        'internal_code': clean['internal_code'],
                    },
                    'existing': {},
                })
                continue
            if code_key in product_by_code:
                existing = product_by_code[code_key]
                _append_conflict(result, {
                    'row': i, 'type': 'duplicate_internal_code',
                    'severity': 'conflict', 'scope': 'product',
                    'match_confidence': (
                        'high'
                        if normalize_text(existing['name']) == name_key
                        else 'uncertain'
                    ),
                    'message': 'Ya existe un producto con este código interno.',
                    'incoming': {
                        'name': clean['name'],
                        'internal_code': clean['internal_code'],
                    },
                    'existing': {
                        'name': existing['name'],
                        'public_id': existing['public_id'],
                    },
                })
                continue
            seen_codes[code_key] = {'name': name_key}
        elif name_key in seen_nocode_names or name_key in db_names:
            # §5.2: los nombres NO son identidad. Sin código ⇒ conflicto UNCERTAIN
            # (omitida + reportada), jamás dedup automática ni creación automática.
            existing = db_names.get(name_key, {})
            _append_conflict(result, {
                'row': i, 'type': 'duplicate_name',
                'severity': 'conflict', 'scope': 'product',
                'match_confidence': 'uncertain',
                'message': (
                    'Ya existe un producto con este nombre. Agrega el código '
                    'interno en tu archivo para confirmar si es otro producto.'
                ),
                'incoming': {
                    'name': clean['name'],
                    'internal_code': '',
                },
                'existing': {
                    'name': existing.get('name', ''),
                    'public_id': existing.get('public_id', ''),
                },
            })
            continue
        else:
            seen_nocode_names.add(name_key)

        # --- La fila ENTRA ---
        if persist:
            try:
                with transaction.atomic():
                    _product, _presentation = _create_product_with_presentation(
                        org, clean, product_extra,
                    )
                    if clean['stock'] > 0:
                        apply_stock_movement(
                            _presentation,
                            clean['stock_base'], 'in', org,
                            reason=STOCK_INITIAL_REASON, created_by=created_by,
                        )
            except Exception as exc:  # noqa: BLE001 — fila aislada por savepoint
                _append_row_error(result, i, {
                    'field': 'product', 'message': _humanize_inventory_exc(exc),
                })
                continue
            if clean['stock'] > 0:
                result['initial_stock_movements'] += 1
            result['created_presentations'] += 1

        result['created_products'] += 1
        if len(result['preview']) < _PREVIEW_MAX:
            result['preview'].append(_preview_inventory_row(i, clean))
        result['preview_total'] += 1

    return result


def _create_product_with_presentation(org, clean, product_extra):
    """Crea Product (+Presentation única). Sin código ⇒ algoritmo tmp→final
    (plan §5.3, verbatim de ProductSerializer.create)."""
    code = clean['internal_code']
    common = dict(
        organization=org,
        name=clean['name'],
        description=clean['description'],
        category=clean['category'],
        requires_prescription=clean['requires_prescription'],
        manufacturer=clean['manufacturer'],
        base_unit=clean['base_unit'],
        min_stock=clean['min_stock_base'],
        stock_quantity=Decimal('0'),  # el movimiento 'in' es quien suma
        extra_data=product_extra or [],
    )
    if code:
        product = Product.objects.create(internal_code=code, **common)
    else:
        # INSERT con código temporal único → UPDATE al definitivo que incrusta el
        # PK (único por tabla ⇒ único por org). Misma transacción/savepoint.
        product = Product.objects.create(internal_code=f'__tmp_{uuid.uuid4().hex}', **common)
        product.internal_code = f'PROD-{org.id}-{product.pk:04d}'
        product.save(update_fields=['internal_code'])

    pres_name = clean['pres_name'] or product.name
    pres = Presentation(
        product=product,
        organization=org,
        name=pres_name,
        base_unit=clean['base_unit'],
        quantity=clean['quantity'],
        conversion_factor=clean['conversion_factor'],
        sale_price=clean['sale_price'],
        purchase_price=clean['purchase_price'],
        barcode=clean['barcode'],
        stock=Decimal('0'),
        min_stock=clean['min_stock'],
    )
    pres.full_clean()
    Presentation.objects.bulk_create([pres])
    return product, pres


# Mensajes amigables para constraints de DB (nunca exponer el nombre crudo).
_INVENTORY_CONSTRAINT_MESSAGES = {
    'presentation_barcode_org_uniq':
        'Ya existe una presentación con este código de barras.',
    'internal_code':
        'Ya existe un producto con este código interno.',
}


def _humanize_inventory_exc(exc):
    from django.core.exceptions import ValidationError as DjangoValidationError
    text = str(exc)
    for constraint, friendly in _INVENTORY_CONSTRAINT_MESSAGES.items():
        if constraint in text:
            return friendly
    if isinstance(exc, DjangoValidationError):
        try:
            parts = []
            for field, msgs in exc.message_dict.items():
                label = 'Datos' if field == '__all__' else field
                parts.append(f"{label}: {', '.join(str(m) for m in msgs)}")
            joined = '; '.join(parts)
            if any(c in joined for c in _INVENTORY_CONSTRAINT_MESSAGES):
                return 'No se pudo importar la fila por un dato duplicado.'
            return joined or 'Datos inválidos.'
        except AttributeError:
            return '; '.join(str(m) for m in exc.messages)
    return 'No se pudo importar la fila.'


def validate_inventory_job(job):
    """Dry-run de inventario: predice el resultado SIN escribir. Idempotente."""
    return _run_inventory_pass(job, persist=False)


def commit_inventory_job(job, created_by=None):
    """Escritura real: UNA transacción con savepoint por fila. `created_by`
    queda auditado en cada StockMovement inicial (puede ser None)."""
    with transaction.atomic():
        return _run_inventory_pass(job, persist=True, created_by=created_by)
