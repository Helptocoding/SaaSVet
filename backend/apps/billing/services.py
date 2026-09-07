from django.db import transaction
from django.db.models import Sum
from django.core.exceptions import ValidationError
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

# Late-arrival observability (ADR p17 Día 5 — warn-only).
# Logger dedicado para que monitoring stack consuma estos eventos sin ruido.
_analytics_events = logging.getLogger('analytics.events')

from decimal import Decimal

from apps.inventory.units import presentation_quantity_to_base
from apps.billing.money import money
from .models import Invoice, InvoiceAuditLog, InvoiceItem, Payment
from .stock_returns import record_invoice_item_disposition


VALID_PAYMENT_METHODS = {'cash', 'card', 'transfer', 'other'}


def _qty_base(item):
    """Convierte cantidad de InvoiceItem (presentaciones) a base_units (ADR p31)."""
    return presentation_quantity_to_base(
        item.quantity, item.conversion_factor_snapshot,
    )


def _warn_if_late_arrival(invoice, anchor_field, anchor_value, metric_class, writer_name):
    """
    Emit ANCHOR_LATE_ARRIVAL warning if the anchor falls in a frozen bucket.

    Día 5 is warn-only; Día 7+ will raise LateAnchorError.
    The ``event`` field in the extra dict is an operational contract consumed
    by the monitoring stack — do not change its value without coordination.
    """
    from apps.analytics.services import is_bucket_frozen
    from apps.core.datetime_utils import org_today_local

    anchor_date_local = org_today_local(invoice.organization, now=anchor_value)
    if not is_bucket_frozen(metric_class, anchor_date_local, invoice.organization):
        return

    today_local = org_today_local(invoice.organization)
    age_days = (today_local - anchor_date_local).days
    threshold = 2  # T+2 freeze window for financial_cash

    _analytics_events.warning(
        'ANCHOR_LATE_ARRIVAL',
        extra={
            'event': 'ANCHOR_LATE_ARRIVAL',
            'anchor_field': anchor_field,
            'anchor_value_iso': anchor_value.isoformat(),
            'bucket_date_local_iso': anchor_date_local.isoformat(),
            'frozen_threshold_days': threshold,
            'age_days': age_days,
            'organization_id': invoice.organization_id,
            'writer': writer_name,
            'metric_class': metric_class,
        },
    )


# ---------------------------------------------------------------------------
# Payment ledger (ADR p27 / docs/financial-event-model-contract.md)
# ---------------------------------------------------------------------------

def _validate_payment_lines(raw_lines):
    """
    Normaliza y valida líneas de pago → [{method, amount (Decimal>0), reference}].
    Levanta ValidationError early (antes de tocar stock o estado).
    """
    if not raw_lines:
        raise ValidationError("Se requiere al menos una línea de pago.")
    out = []
    for raw in raw_lines:
        method = raw.get('method')
        if method not in VALID_PAYMENT_METHODS:
            raise ValidationError(
                f'Método de pago inválido. Opciones: {sorted(VALID_PAYMENT_METHODS)}'
            )
        try:
            amount = money(Decimal(str(raw.get('amount'))))
        except Exception:
            raise ValidationError("Monto de pago inválido.")
        if amount <= 0:
            raise ValidationError("El monto de cada pago debe ser mayor a cero.")
        out.append({
            'method': method,
            'amount': amount,
            'reference': (raw.get('reference') or '')[:100],
        })
    return out


def _legacy_single_line(payment_method, amount):
    """Compat (ADR p27): traduce un `payment_method` único a una sola línea."""
    if payment_method is None:
        raise ValidationError("Se requiere payment_method o payment_lines.")
    return [{'method': payment_method, 'amount': amount}]


def _is_payment_replay(invoice, idempotency_key):
    """Idempotencia (contrato §9): True si esta operación ya registró pagos."""
    if not idempotency_key:
        return False
    return Payment.all_objects.filter(
        organization_id=invoice.organization_id,
        idempotency_key=f"{idempotency_key}:0",
    ).exists()


def _log_idempotent_dedupe(invoice, idempotency_key):
    logger.info("IDEMPOTENT_PAYMENT_DEDUPED", extra={
        'event': 'IDEMPOTENT_PAYMENT_DEDUPED',
        'invoice_id': invoice.pk,
        'organization_id': invoice.organization_id,
        'idempotency_key': idempotency_key,
    })


def _resolve_cash_session_for_payment(user, organization):
    """
    ADR p28 + p39: asociación ≠ obligatoriedad. Si el actor tiene caja abierta,
    el pago se asocia SIEMPRE a esa sesión (con o sin toggle) — de lo contrario
    el Z del turno reportaba $0 ventas y diferencias falsas cuando
    `require_open_cash_session` estaba apagado. El toggle solo decide si se
    BLOQUEA el cobro cuando NO hay caja abierta.

    CashSession es la CABEZA del orden global de locks → se adquiere ANTES de
    lockear la Invoice (sin ABBA: close lockea solo la sesión). Un pago en vuelo
    contra una sesión que se está cerrando bloquea en el lock y al reanudar ve
    status != 'open' → ningún pago se cuela después del cierre Z.
    """
    from apps.cash.models import CashSession
    session = (
        CashSession.objects.for_organization(organization)
        .select_for_update()
        .filter(status='open', opened_by=user)
        .first()
    )
    if session is not None:
        return session
    from apps.organizations.utils import get_org_setting
    if get_org_setting(organization, 'require_open_cash_session'):
        raise ValidationError(
            "No hay una caja abierta. Abre un turno de caja para registrar el cobro."
        )
    return None


def _mark_invoice_paid(invoice, user, now):
    """
    Writer del anchor `paid_at`. Transiciona posted → paid cuando la cobranza
    queda saldada (remaining_balance == 0). `payment_method` legacy/derivado:
    método único si todos los pagos coinciden, si no NULL (deprecado, DD-009).
    """
    previous_status = invoice.status
    methods = set(
        Payment.all_objects.filter(invoice=invoice).values_list('method', flat=True)
    )
    invoice.status = 'paid'
    invoice.payment_method = next(iter(methods)) if len(methods) == 1 else None
    invoice.paid_at = now
    invoice.paid_at_source = 'service'
    invoice.save(update_fields=[
        'status', 'payment_method', 'paid_at', 'paid_at_source', 'updated_at',
    ])
    from .models import CollectionCase
    CollectionCase.all_objects.filter(invoice=invoice, status='open').update(
        status='resolved', resolution='paid', resolved_at=now, updated_at=now,
    )
    _log_status_change(invoice, previous=previous_status, new='paid', user=user)
    _warn_if_late_arrival(invoice, 'paid_at', invoice.paid_at,
                          'financial_cash', 'pay_invoice')


def _pay_locked_invoice(invoice, user, lines, *, require_full, idempotency_key=None,
                        command_receipt=None, cash_session=None):
    """
    Registra Payment(s) append-only sobre una Invoice YA emitida y lockeada;
    si la cobranza queda saldada la transiciona a `paid` (writer de `paid_at`).

    `lines` ya viene normalizado por _validate_payment_lines. La idempotencia
    (replay) y la validación de estado las maneja el caller público.

    require_full=True  (venta directa / pago de un paso): exige cubrir el saldo
                       exacto.
    require_full=False queda reservado a conciliaciones controladas; los flujos
    operativos actuales exigen liquidación exacta.

    Ver docs/financial-event-model-contract.md §8 (remaining_balance, paid_at).
    """
    total_in = sum((l['amount'] for l in lines), Decimal('0.00'))
    remaining = invoice.remaining_balance
    if total_in > remaining:
        raise ValidationError(
            f"El pago ({total_in}) excede el saldo pendiente ({remaining})."
        )
    if require_full and total_in != remaining:
        raise ValidationError(
            f"El pago debe cubrir el saldo exacto de la venta ({remaining})."
        )

    now = timezone.now()
    for i, line in enumerate(lines):
        if command_receipt is not None:
            key = f"cr1:{command_receipt.receipt_uuid.hex}:p:{i:04d}"
        else:
            key = f"{idempotency_key}:{i}" if idempotency_key else None
        Payment(
            organization=invoice.organization,
            invoice=invoice,
            amount=line['amount'],
            method=line['method'],
            occurred_at=now,
            actor=user,
            provenance='service',
            reference=line.get('reference', ''),
            idempotency_key=key,
            command_receipt=command_receipt,
            command_line_index=(i if command_receipt is not None else None),
            cash_session=cash_session,
        ).save()

    if invoice.remaining_balance <= Decimal('0.00'):
        _mark_invoice_paid(invoice, user, now)
    return invoice


# ---------------------------------------------------------------------------
# Wrappers públicos — con @transaction.atomic y lock propio.
# ---------------------------------------------------------------------------

@transaction.atomic
def pay_invoice(invoice, user, payment_method=None, *, payment_lines=None, idempotency_key=None):
    """
    Registra el pago total de una factura posted. Authoritative writer del anchor
    `paid_at` (siempre cuando se cobra, porque el pago saldea el total).

    Soporta pago único (legacy `payment_method`) y split (`payment_lines` =
    [{'method','amount'[,'reference']}, ...]). Idempotente vía `idempotency_key`
    (contrato §9). **No admite pago parcial** (revisión ADR p30, 2026-05-29): la
    suma de líneas debe igualar el saldo exacto. Supera la regla original de ADR
    p27 que admitía parcial en consulta — decisión de producto: una factura se
    cobra completa.

    Llamado por billing/views.py::pay_invoice y por flujos futuros. No editar
    `paid_at` desde otro lugar — el contrato analítico depende de un único writer.
    Ver docs/financial-event-model-contract.md §8.
    """
    from .checkout_services import _claim_receipt, _complete_receipt

    payload = {
        'invoice': str(invoice.public_id), 'payment_method': payment_method,
        'payment_lines': payment_lines,
    }
    receipt, replay = _claim_receipt(
        organization=invoice.organization, user=user, command_kind='pay_invoice',
        idempotency_key=idempotency_key, payload=payload,
    )
    if replay:
        return Invoice.all_objects.get(pk=receipt.response_data['invoice_id'])

    # CommandReceipt es la cabeza; CashSession se toma después y antes de Invoice.
    cash_session = _resolve_cash_session_for_payment(user, invoice.organization)

    invoice = Invoice.objects.for_organization(invoice.organization).select_for_update().get(pk=invoice.pk)

    if invoice.status == 'paid':
        raise ValidationError('La factura ya fue pagada.')
    if invoice.status != 'posted':
        raise ValidationError('Solo se pueden pagar facturas emitidas pendientes.')

    raw = payment_lines if payment_lines else _legacy_single_line(
        payment_method, invoice.remaining_balance
    )
    lines = _validate_payment_lines(raw)
    invoice = _pay_locked_invoice(
        invoice, user, lines, require_full=True,
        command_receipt=receipt, cash_session=cash_session,
    )
    _complete_receipt(
        receipt, invoice_id=invoice.pk, invoice_public_id=str(invoice.public_id),
    )
    return invoice


# ---------------------------------------------------------------------------
# Devoluciones / notas de crédito (ADR p29 — Sprint B)
# ---------------------------------------------------------------------------

def _write_metric_adjustment(organization, date_local, metric_name, delta, *, reason='', source_invoice=None):
    """
    Registra un MetricAdjustment append-only (dual-window §2.8). NO toca snapshots
    frozen — el neto se computa en read-time. delta firmado (− para refund).
    """
    from apps.analytics.models import MetricAdjustment
    MetricAdjustment.objects.create(
        organization=organization,
        date=date_local,
        metric_name=metric_name,
        delta=delta,
        reason=(reason or '')[:255],
        source_invoice=source_invoice,
    )


@transaction.atomic
def process_refund(invoice, user, *, credit_lines, refund_lines, reason_code,
                   reason_notes='', idempotency_key=None):
    """
    Emite nota de crédito + reembolso sobre una factura PAGADA (ADR p29).

    NO reabre la factura (permanece `paid`, contrato §8.2). Registra un
    MetricAdjustment negativo en `revenue_paid` del día del reembolso (dual-window
    §2.8) — los snapshots frozen no se tocan. Restock por línea según disposition.

    Orden de locks: CashSession → Invoice → Presentation → CreditNote/items/refund.
    """
    from apps.core.datetime_utils import org_today_local
    from apps.core.sanitize import sanitize_text
    from .checkout_services import _claim_receipt, _complete_receipt
    from .models import (
        CreditNote, CreditNoteItem, RefundPayment, CREDIT_NOTE_REASON_CODES,
    )

    if reason_code not in CREDIT_NOTE_REASON_CODES:
        raise ValidationError("Causa de devolución (reason_code) inválida.")
    if not credit_lines:
        raise ValidationError("Se requiere al menos una línea a devolver.")

    receipt, replay = _claim_receipt(
        organization=invoice.organization, user=user, command_kind='refund_invoice',
        idempotency_key=idempotency_key,
        aggregate_type='invoice', aggregate_public_id=invoice.public_id,
        payload={
            'invoice': str(invoice.public_id), 'credit_lines': credit_lines,
            'refund_lines': refund_lines, 'reason_code': reason_code,
            'reason_notes': reason_notes or '',
        },
    )
    if replay:
        return CreditNote.objects.for_organization(invoice.organization).get(
            pk=receipt.response_data['credit_note_id'],
        )

    # CashSession a la cabeza del orden de locks (igual que el pago).
    cash_session = _resolve_cash_session_for_payment(user, invoice.organization)
    invoice = Invoice.objects.for_organization(
        invoice.organization
    ).select_for_update().get(pk=invoice.pk)

    if invoice.status != 'paid':
        raise ValidationError("Solo se pueden reembolsar facturas pagadas.")

    items_by_pk = {it.pk: it for it in InvoiceItem.all_objects.filter(invoice=invoice)}
    normalized = []
    total_refunded = Decimal('0.00')
    for raw in credit_lines:
        item = items_by_pk.get(raw.get('invoice_item'))
        if item is None:
            raise ValidationError("Ítem de factura inválido para esta factura.")
        try:
            qty = money(Decimal(str(raw.get('quantity'))))
            amt = money(Decimal(str(raw.get('amount'))))
        except Exception:
            raise ValidationError("Cantidad o monto inválido en la línea de devolución.")
        disposition = raw.get('disposition', 'restock')
        if disposition not in ('restock', 'discard', 'retained'):
            raise ValidationError("disposition inválido (restock|discard|retained).")
        if qty <= 0 or amt < 0:
            raise ValidationError("Cantidad debe ser > 0 y monto >= 0.")
        # Un refund monetario totalmente revertido deja de consumir capacidad
        # reembolsable. El ledger histórico permanece append-only.
        prior_q = Decimal('0.00')
        prior_a = Decimal('0.00')
        prior_items = CreditNoteItem.all_objects.filter(
            invoice_item=item,
        ).prefetch_related('credit_note__refund_payments__reversals')
        for prior_item in prior_items:
            refunds = list(prior_item.credit_note.refund_payments.all())
            fully_reversed = bool(refunds) and all(
                bool(list(refund.reversals.all())) for refund in refunds
            )
            if not fully_reversed:
                prior_q += prior_item.quantity
                prior_a += prior_item.amount
        if qty > (item.quantity - prior_q):
            raise ValidationError(f"Cantidad a devolver excede lo disponible en '{item.description}'.")
        if amt > (item.subtotal - prior_a):
            raise ValidationError(f"Monto a devolver excede el de la línea '{item.description}'.")
        normalized.append((item, qty, amt, disposition))
        total_refunded += amt

    # Cómo se devuelve el dinero — debe igualar exactamente el total a devolver.
    rlines = _validate_payment_lines(refund_lines)
    refund_sum = sum((l['amount'] for l in rlines), Decimal('0.00'))
    if refund_sum != total_refunded:
        raise ValidationError(
            f"El reembolso ({refund_sum}) debe igualar el total a devolver ({total_refunded})."
        )

    now = timezone.now()
    credit_note = CreditNote(
        organization=invoice.organization, original_invoice=invoice, status='issued',
        created_by=user, issued_at=now, issued_at_source='service',
        total_refunded=total_refunded, reason_code=reason_code,
        reason_notes=sanitize_text(reason_notes or '', max_length=5000),
    )
    credit_note.save()

    for item, qty, amt, disposition in normalized:
        credit_item = CreditNoteItem(
            organization=invoice.organization, credit_note=credit_note,
            invoice_item=item, quantity=qty, amount=amt, disposition=disposition,
        )
        credit_item.save()
        if item.presentation_id:
            has_allocations = item.stock_allocations.exists()
            if not has_allocations and disposition in {'restock', 'discard'}:
                raise ValidationError(
                    'No se puede revertir inventario sin asignaciones físicas de entrega.'
                )
            if has_allocations:
                qty_base = presentation_quantity_to_base(
                    qty, item.conversion_factor_snapshot,
                ).quantize(Decimal('0.0001'))
                kind = {
                    'restock': 'returned_restocked',
                    'discard': 'returned_discarded',
                    'retained': 'retained_after_refund',
                }[disposition]
                record_invoice_item_disposition(
                    invoice_item=item,
                    outcome=kind,
                    organization=invoice.organization,
                    user=user,
                    reason=f'Devolución — NC #{credit_note.pk}',
                    quantity_base=qty_base,
                    credit_note_item=credit_item,
                    occurred_at=now,
                )

    for i, line in enumerate(rlines):
        key = f"cr1:{receipt.receipt_uuid}:r:{i}"
        RefundPayment(
            organization=invoice.organization, credit_note=credit_note,
            amount=line['amount'], method=line['method'], occurred_at=now,
            actor=user, provenance='service', reference=line['reference'],
            idempotency_key=key, cash_session=cash_session,
            command_receipt=receipt, command_line_index=i,
        ).save()

    # Dual-window: revenue_paid -= total_refunded en el día del reembolso. Los
    # snapshots frozen NO se reescriben (read-time net = gross + Σ adjustments).
    _write_metric_adjustment(
        invoice.organization, org_today_local(invoice.organization, now=now),
        'revenue_paid', -total_refunded,
        reason=f'refund:{reason_code}', source_invoice=invoice,
    )

    logger.info("REFUND_PROCESSED", extra={
        'event': 'REFUND_PROCESSED', 'credit_note_id': credit_note.pk,
        'invoice_id': invoice.pk, 'organization_id': invoice.organization_id,
        'total_refunded': str(total_refunded), 'reason_code': reason_code,
        'actor_id': getattr(user, 'pk', None),
    })
    _complete_receipt(receipt, credit_note_id=credit_note.pk)
    return credit_note


@transaction.atomic
def reverse_credit_note(credit_note, user, *, reason_code='', reason_notes='', idempotency_key=None):
    """
    Contra-asiento de una nota de crédito emitida por error (ADR p29, contrato §6).

    NO edita ni borra: emite un `RefundReversal` por cada `RefundPayment` de la
    nota (≤1 por refund, garantizado por unique en `reverses`). Registra un
    MetricAdjustment POSITIVO que cancela el negativo del refund. El refund en
    efectivo revertido suma a `expected_cash` de la caja abierta (vía el término
    de cierre, ADR p28).
    """
    from apps.core.datetime_utils import org_today_local
    from apps.core.sanitize import sanitize_text
    from .checkout_services import _claim_receipt, _complete_receipt
    from .models import CreditNote, CreditNoteItem, RefundPayment, RefundReversal

    receipt, replay = _claim_receipt(
        organization=credit_note.organization, user=user,
        command_kind='reverse_credit_note', idempotency_key=idempotency_key,
        aggregate_type='credit_note', aggregate_public_id=credit_note.public_id,
        payload={
            'credit_note': str(credit_note.public_id),
            'reason_code': reason_code or '', 'reason_notes': reason_notes or '',
        },
    )
    if replay:
        return CreditNote.objects.for_organization(credit_note.organization).get(
            pk=receipt.response_data['credit_note_id'],
        )

    cash_session = _resolve_cash_session_for_payment(user, credit_note.organization)
    # Orden total entre tablas: Invoice siempre antes que CreditNote.
    Invoice.objects.for_organization(credit_note.organization).select_for_update().get(
        pk=credit_note.original_invoice_id,
    )
    credit_note = CreditNote.objects.for_organization(
        credit_note.organization
    ).select_for_update().get(pk=credit_note.pk)

    refund_payments = list(RefundPayment.all_objects.filter(credit_note=credit_note))
    if not refund_payments:
        raise ValidationError("La nota de crédito no tiene reembolsos que revertir.")

    if CreditNoteItem.all_objects.filter(
        credit_note=credit_note, disposition='restock', invoice_item__presentation__isnull=False,
    ).exists():
        raise ValidationError(
            'stock_reversal_requires_manual_reconciliation: la devolución reingresó inventario.'
        )

    already = set(
        RefundReversal.all_objects.filter(reverses__in=refund_payments)
        .values_list('reverses_id', flat=True)
    )
    if already and len(already) != len(refund_payments):
        raise ValidationError('Ledger inconsistente: la nota tiene reversos parciales.')
    if already:
        raise ValidationError("Esta nota de crédito ya fue revertida.")
    pending = refund_payments

    now = timezone.now()
    notes_clean = sanitize_text(reason_notes or '', max_length=5000)
    total_reversed = Decimal('0.00')
    for i, rp in enumerate(pending):
        key = f"cr1:{receipt.receipt_uuid}:v:{i}"
        RefundReversal(
            organization=credit_note.organization, reverses=rp,
            amount=rp.amount, method=rp.method, occurred_at=now, actor=user,
            cash_session=cash_session, provenance='service',
            reason_code=reason_code or '', reason_notes=notes_clean,
            idempotency_key=key,
            command_receipt=receipt, command_line_index=i,
        ).save()
        total_reversed += rp.amount

    # Cancela el ajuste negativo del refund: +total_reversed en el día del reverso.
    _write_metric_adjustment(
        credit_note.organization, org_today_local(credit_note.organization, now=now),
        'revenue_paid', total_reversed,
        reason=f'refund_reversal:{reason_code or "correction"}',
        source_invoice=credit_note.original_invoice,
    )
    logger.info("REFUND_REVERSED", extra={
        'event': 'REFUND_REVERSED', 'credit_note_id': credit_note.pk,
        'organization_id': credit_note.organization_id,
        'total_reversed': str(total_reversed), 'actor_id': getattr(user, 'pk', None),
    })
    _complete_receipt(receipt, credit_note_id=credit_note.pk)
    return credit_note


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _log_status_change(invoice, previous, new, user, notes=''):
    InvoiceAuditLog.objects.create(
        invoice=invoice,
        previous_status=previous,
        new_status=new,
        changed_by=user,
        notes=notes,
    )
