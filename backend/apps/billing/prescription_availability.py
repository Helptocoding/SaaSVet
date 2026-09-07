"""Single source of truth for prescription and stock availability in Checkout.

All quantities whose name ends in ``_base`` use ``Product.base_unit``.  A
CheckoutItem with a Presentation stores whole commercial presentation units.
Availability is advisory; terminal posting repeats the same unit checks and then
settles stock under database locks.
"""

from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db.models import F, Q, Sum
from django.utils import timezone

from apps.inventory.models import StockLot
from apps.inventory.units import (
    presentation_conversion_factor,
    presentation_quantity_to_base,
)
from apps.prescriptions.models import Prescription

from .models import CheckoutItem, PrescriptionFulfillmentEvent


ZERO = Decimal('0')
BASE_QUANTUM = Decimal('0.0001')


def _base_string(value) -> str:
    return format(Decimal(value).quantize(BASE_QUANTUM), 'f')


def validated_presentation_quantity(value) -> Decimal:
    """Validate an indivisible commercial presentation quantity."""
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({'quantity': 'La cantidad de presentación es inválida.'})
    if not quantity.is_finite() or quantity <= ZERO:
        raise ValidationError({'quantity': 'La cantidad debe ser finita y mayor a cero.'})
    if quantity != quantity.to_integral_value():
        raise ValidationError({
            'quantity': 'Las presentaciones comerciales se dispensan en unidades enteras.'
        })
    return quantity


def presentation_units_to_base(quantity, presentation) -> Decimal:
    return presentation_quantity_to_base(
        validated_presentation_quantity(quantity),
        presentation_conversion_factor(presentation),
    )


def _whole_presentations(quantity_base, factor) -> int:
    if quantity_base <= ZERO:
        return 0
    return int(quantity_base // factor)


def _event_totals(prescription_item_id):
    events = PrescriptionFulfillmentEvent.all_objects.filter(
        prescription_item_id=prescription_item_id,
    )
    fulfilled = events.aggregate(total=Sum('quantity_delta'))['total'] or ZERO
    returned = events.filter(kind='returned').aggregate(
        total=Sum('physical_quantity')
    )['total'] or ZERO
    redelivered = events.filter(kind='redelivered').aggregate(
        total=Sum('physical_quantity')
    )['total'] or ZERO
    return fulfilled, returned, redelivered


def _consumable_lots(product):
    today = timezone.localdate()
    return list(
        StockLot.objects.for_organization(product.organization)
        .filter(
            product=product,
            status=StockLot.STATUS_ACTIVE,
            quantity_on_hand__gt=0,
        )
        .filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=today))
        .order_by(F('expiry_date').asc(nulls_last=True), 'pk')
    )


def _physical_stock(product):
    product_stock = max(Decimal(product.stock_quantity), ZERO)
    if not product.tracks_lots:
        return product_stock, []
    lots = _consumable_lots(product)
    lot_stock = sum((Decimal(lot.quantity_on_hand) for lot in lots), ZERO)
    # Both ledgers are authoritative invariants.  Availability fails safe to the
    # lower observable balance until audit_stock_integrity reconciles any drift.
    return min(product_stock, lot_stock), lots


def build_checkout_prescription_suggestions(checkout, *, include_closed=False):
    if not checkout.medical_record_id:
        return []
    if checkout.lifecycle != 'open' and not include_closed:
        return []

    prescription = Prescription.objects.for_organization(checkout.organization).filter(
        medical_record_id=checkout.medical_record_id,
    ).first()
    if prescription is None:
        return []

    selected_by_rx = defaultdict(lambda: {
        'total': ZERO, 'new': ZERO, 'redelivery': ZERO,
    })
    demand_by_product = defaultdict(lambda: ZERO)

    active_lines = CheckoutItem.all_objects.filter(
        checkout=checkout,
        is_active=True,
        presentation__isnull=False,
    ).select_related('presentation__product')
    if checkout.lifecycle == 'open':
        for line in active_lines:
            if line.fulfillment_source == 'already_fulfilled':
                continue
            quantity_base = presentation_quantity_to_base(
                line.quantity, line.conversion_factor_snapshot,
            )
            demand_by_product[line.presentation.product_id] += quantity_base
            if line.prescription_item_id:
                bucket = selected_by_rx[line.prescription_item_id]
                bucket['total'] += quantity_base
                if line.fulfillment_source == 'redelivery':
                    bucket['redelivery'] += quantity_base
                else:
                    bucket['new'] += quantity_base

    decisions = {
        row.prescription_item_id: row
        for row in checkout.prescription_selections.all()
    }
    result = []
    rx_items = prescription.items.select_related('product').prefetch_related(
        'product__presentations'
    )
    for item in rx_items:
        selected = selected_by_rx[item.pk]
        fulfilled, returned, redelivered = _event_totals(item.pk)
        neutral_total = (
            max(returned - redelivered, ZERO)
            if checkout.kind == 'replacement' else ZERO
        )
        selected_neutral = min(selected['redelivery'], neutral_total)
        selected_cap = selected['new'] + max(selected['redelivery'] - neutral_total, ZERO)
        legal_remaining = max(Decimal(item.quantity) - fulfilled - selected_cap, ZERO)
        neutral_remaining = max(neutral_total - selected_neutral, ZERO)
        clinical_available = legal_remaining + neutral_remaining
        selection = decisions.get(item.pk)

        stock_base, lots = _physical_stock(item.product)
        checkout_demand = demand_by_product[item.product_id]
        stock_after_checkout = max(stock_base - checkout_demand, ZERO)
        presentation_rows = []
        for presentation in item.product.presentations.filter(is_active=True):
            factor = presentation_conversion_factor(presentation)
            clinical_max = _whole_presentations(clinical_available, factor)
            stock_max = _whole_presentations(stock_after_checkout, factor)
            maximum = min(clinical_max, stock_max)
            reasons = []
            if checkout.lifecycle != 'open':
                reasons.append('checkout_not_open')
                maximum = 0
            if clinical_available <= ZERO:
                reasons.append('prescription_fulfilled')
            elif clinical_max == 0:
                reasons.append('below_presentation_size')
            if stock_after_checkout <= ZERO:
                reasons.append(
                    'no_consumable_lot' if item.product.tracks_lots else 'out_of_stock'
                )
            elif stock_max == 0:
                reasons.append('stock_below_presentation_size')

            presentation_rows.append({
                'id': presentation.pk,
                'name': str(presentation),
                'sale_price': str(presentation.sale_price),
                'conversion_factor': _base_string(factor),
                'conversion_factor_base_per_presentation': _base_string(factor),
                'available_stock_quantity_base': _base_string(stock_base),
                'checkout_stock_demand_quantity_base': _base_string(checkout_demand),
                'available_stock_after_checkout_quantity_base': _base_string(stock_after_checkout),
                'available_stock_quantity_presentations': _whole_presentations(stock_base, factor),
                'clinical_max_additional_quantity': clinical_max,
                'stock_max_additional_quantity': stock_max,
                'max_selectable_quantity': maximum,
                'max_selectable_semantics': 'additional_presentation_units',
                'blocking_reasons': reasons,
                'lots': [
                    {
                        'id': lot.pk,
                        'lot_number': lot.lot_number,
                        'expiry_date': (
                            lot.expiry_date.isoformat() if lot.expiry_date else None
                        ),
                        'available_quantity_base': _base_string(lot.quantity_on_hand),
                        'available_quantity_presentations': _whole_presentations(
                            Decimal(lot.quantity_on_hand), factor,
                        ),
                    }
                    for lot in lots
                ],
            })

        result.append({
            'prescription_item_id': item.pk,
            'product_name': item.product.name,
            'dose': item.dose,
            'product_public_id': str(item.product.public_id),
            'tracks_lots': item.product.tracks_lots,
            'base_unit': item.product.base_unit,
            'base_unit_display': item.product.get_base_unit_display() or '',
            'prescribed_quantity_base': _base_string(item.quantity),
            'fulfilled_quantity_base': _base_string(fulfilled),
            'selected_quantity_base': _base_string(selected['total']),
            'selected_cap_consuming_quantity_base': _base_string(selected_cap),
            'legal_remaining_quantity_base': _base_string(legal_remaining),
            'neutral_redelivery_remaining_quantity_base': _base_string(neutral_remaining),
            'remaining_quantity_base': _base_string(legal_remaining),
            'eligible_remaining_at_open_base': _base_string(
                selection.eligible_remaining_at_open if selection else legal_remaining
            ),
            'decision': selection.decision if selection else 'pending',
            'decline_reason': selection.decline_reason if selection else '',
            # Compatibility aliases.  They are derived here, never recomputed by
            # serializers or frontend business logic.
            'suggested_quantity': _base_string(item.quantity),
            'prescribed_quantity': _base_string(item.quantity),
            'dispensed_quantity': _base_string(selected['total']),
            'remaining_quantity': _base_string(legal_remaining),
            'presentations': presentation_rows,
        })
    return result
