"""Exact reversal of immutable physical allocations.

A financial line can be fulfilled from multiple FEFO lots.  Returns therefore
operate on StockAllocation rows, never on InvoiceItem.lot or a first-allocation
shortcut.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone

from apps.inventory.services import restock_product

from .models import (
    PrescriptionFulfillmentEvent,
    StockAllocation,
    StockDispositionEvent,
)


RETURNED_KINDS = ('returned_restocked', 'returned_discarded')
RETURN_OUTCOMES = (*RETURNED_KINDS, 'retained_after_refund')


def _available_allocation_slices(invoice_item, quantity_base=None):
    allocations = list(
        StockAllocation.all_objects.select_for_update(of=('self',))
        .select_related('lot')
        .filter(invoice_item=invoice_item)
        .order_by('pk')
    )
    if not allocations:
        return []

    target = None if quantity_base is None else Decimal(quantity_base)
    if target is not None and (not target.is_finite() or target <= 0):
        raise ValidationError('La cantidad física a devolver debe ser positiva y finita.')

    slices = []
    remaining = target
    for allocation in allocations:
        previously_returned = (
            allocation.disposition_events.filter(kind__in=RETURNED_KINDS)
            .aggregate(total=Sum('quantity_base'))['total']
            or Decimal('0')
        )
        available = max(allocation.quantity_base - previously_returned, Decimal('0'))
        if available <= 0:
            continue
        take = available if remaining is None else min(available, remaining)
        if take > 0:
            slices.append((allocation, take))
        if remaining is not None:
            remaining -= take
            if remaining == 0:
                break

    if remaining is not None and remaining > 0:
        raise ValidationError(
            'La devolución física excede las asignaciones entregadas aún disponibles.'
        )
    return slices


def record_invoice_item_disposition(
    *, invoice_item, outcome, organization, user, reason,
    quantity_base=None, credit_note_item=None, occurred_at=None,
):
    """Record and, when applicable, reverse every exact allocation slice."""
    if outcome not in RETURN_OUTCOMES:
        raise ValidationError({'disposition': 'Disposición física inválida.'})
    slices = _available_allocation_slices(invoice_item, quantity_base)
    if not slices:
        raise ValidationError('La línea no tiene una asignación física reversible.')

    now = occurred_at or timezone.now()
    events = []
    for allocation, allocated_quantity in slices:
        if outcome == 'returned_restocked':
            restock_product(
                presentation=allocation.presentation,
                quantity_base=allocated_quantity,
                organization=organization,
                lot=allocation.lot,
                reason=reason,
                created_by=user,
                invoice=invoice_item.invoice,
            )
        event = StockDispositionEvent.objects.create(
            organization=organization,
            allocation=allocation,
            credit_note_item=credit_note_item,
            kind=outcome,
            quantity_base=allocated_quantity,
            stock_delta=(
                allocated_quantity
                if outcome == 'returned_restocked' else Decimal('0')
            ),
            custody=(
                'customer' if outcome == 'retained_after_refund'
                else ('clinic' if outcome == 'returned_restocked' else 'discarded')
            ),
            occurred_at=now,
            created_by=user,
        )
        if (
            invoice_item.dispensed_from_prescription_item_id
            and outcome != 'retained_after_refund'
        ):
            PrescriptionFulfillmentEvent.objects.create(
                organization=organization,
                prescription_item=invoice_item.dispensed_from_prescription_item,
                invoice_item=invoice_item,
                allocation=allocation,
                credit_note_item=credit_note_item,
                stock_disposition_event=event,
                kind='returned',
                quantity_delta=Decimal('0'),
                physical_quantity=allocated_quantity,
                occurred_at=now,
                created_by=user,
            )
        events.append(event)
    return events
