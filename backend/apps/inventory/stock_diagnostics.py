"""Read-only stock evidence for a future individually approved review."""
import hashlib
import json
from decimal import Decimal

from django.db.models import Q, Sum

from .models import Presentation, StockLot, StockMovement


def diagnose_product(product):
    movements = StockMovement.all_objects.filter(
        Q(product=product) | Q(product__isnull=True, presentation__product=product),
        organization_id=product.organization_id,
    ).order_by('pk')
    digest = hashlib.sha256()
    baseline = None
    expected = None
    flags = set()
    for m in movements.iterator(chunk_size=500):
        digest.update(json.dumps([m.pk, m.movement_type, str(m.quantity), m.quantity_unit,
                                  m.product_id, m.presentation_id, m.lot_id, m.lot_number], separators=(',', ':')).encode())
        if m.product_id is None:
            flags.add('missing_product_reference')
            if baseline is not None:
                expected = None
            continue
        if m.quantity_unit != 'base':
            flags.add('legacy_or_mixed_units')
            if baseline is not None:
                expected = None
            continue
        if m.movement_type == 'adjustment':
            if m.lot_id is None and not m.lot_number and m.product_id == product.pk:
                baseline = m.pk
                expected = m.quantity
            else:
                flags.add('lot_adjustment_delta_unverifiable')
                if baseline is not None:
                    expected = None
        elif baseline is not None and expected is not None:
            if m.movement_type == 'in':
                expected += m.quantity
            elif m.movement_type == 'out':
                expected -= m.quantity
            else:
                flags.add('unknown_movement')
                expected = None
    if baseline is None:
        coverage = 'no_baseline'
    elif expected is None:
        coverage = 'unverifiable'
    else:
        coverage = 'absolute_product_baseline'
    lot_total = None
    if product.tracks_lots:
        flags.add('tracks_lots')
        lot_total = StockLot.all_objects.filter(product=product).aggregate(total=Sum('quantity_on_hand'))['total'] or Decimal('0')
        if lot_total != product.stock_quantity:
            flags.add('lot_balance_mismatch')
    presentations = list(Presentation.all_objects.filter(product=product).order_by('public_id').values_list('public_id', 'conversion_factor'))
    return {
        'organization_public_id': str(product.organization.public_id),
        'product_public_id': str(product.public_id),
        'observed_balance': str(product.stock_quantity), 'base_unit': product.base_unit,
        'presentations': [{'public_id': str(pk), 'conversion_factor': str(factor)} for pk, factor in presentations],
        'ledger_watermark_sha256': digest.hexdigest(), 'coverage': coverage,
        'expected_from_baseline': str(expected) if expected is not None else None,
        'lot_total': str(lot_total) if lot_total is not None else None,
        'ambiguities': sorted(flags),
        'proposed_action': 'revisar reconstrucción desde saldo observado; no aplicar automáticamente',
        'expected_effect': 'ninguna escritura durante diagnóstico; no certifica el pasado',
        'approval': None, 'actor': None, 'approved_at': None, 'reason': None,
    }


def compare_proposal(prepared, observed):
    """Compare evidence only; never apply, approve or certify historical stock."""
    fields = ('organization_public_id', 'product_public_id', 'observed_balance',
              'base_unit', 'presentations', 'ledger_watermark_sha256', 'coverage',
              'expected_from_baseline', 'lot_total', 'ambiguities')
    missing = [field for field in fields if field not in prepared or field not in observed]
    changed = [field for field in fields if prepared.get(field) != observed.get(field)]
    ambiguous = bool(observed.get('ambiguities')) or observed.get('coverage') == 'unverifiable'
    return {
        'requires_new_review': bool(changed) or bool(missing) or ambiguous,
        'changed_fields': changed,
        'missing_fields': missing,
        'ambiguous': ambiguous,
        'approval': None,
    }
