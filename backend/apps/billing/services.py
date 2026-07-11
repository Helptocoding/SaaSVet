from django.db import transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.core.exceptions import ValidationError
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

# Late-arrival observability (ADR p17 Día 5 — warn-only).
# Logger dedicado para que monitoring stack consuma estos eventos sin ruido.
_analytics_events = logging.getLogger('analytics.events')

from decimal import Decimal

from apps.inventory.services import consume_product, restock_product, first_consumable_lot
from apps.inventory.models import Presentation, StockLot
from apps.billing.money import money, discount_amount, line_subtotal
from .models import Invoice, InvoiceAuditLog, InvoiceItem, Payment


VALID_PAYMENT_METHODS = {'cash', 'card', 'transfer', 'other'}


def apply_invoice_item_quantity_delta(item, delta):
    """
    Mutación atómica de InvoiceItem.quantity usando F('quantity') + delta.

    Convención del proyecto: TODA mutación numérica contable en InvoiceItem
    DEBE usar F() (paralelo a apply_stock_movement para Presentation.stock),
    incluso cuando el caller posee select_for_update() sobre el InvoiceItem.

    ⚠️ CONTRATO:
      - El caller DEBE poseer select_for_update() sobre el item.
      - El caller DEBE estar dentro de transaction.atomic().
      - delta puede ser negativo (decremento), pero el resultado no puede ser <= 0.
        Si el caller necesita borrar el item, debe llamar item.delete() ANTES
        de invocar este helper (proyectar item.quantity + delta primero).

    Recomputa subtotal del item + totales de la factura. Usa los mismos helpers
    que InvoiceItem.save() (money, discount_amount, line_subtotal) para no
    divergir del cálculo canónico.

    Returns:
        Decimal — la nueva cantidad después del delta.
    """
    projected = item.quantity + delta
    if projected <= 0:
        raise ValidationError(
            f"La cantidad resultante ({projected}) no es positiva. "
            f"Llama item.delete() antes de invocar apply_invoice_item_quantity_delta."
        )

    InvoiceItem.all_objects.filter(pk=item.pk).update(quantity=F('quantity') + delta)
    item.refresh_from_db(fields=['quantity'])

    gross = money(item.quantity * item.unit_price)
    disc = discount_amount(gross, item.discount_type, item.discount_value)
    new_subtotal = line_subtotal(item.quantity, item.unit_price, disc)
    InvoiceItem.all_objects.filter(pk=item.pk).update(subtotal=new_subtotal)

    item.invoice.recalculate_totals()
    item.refresh_from_db(fields=['subtotal'])
    return item.quantity


def _lock_presentations(presentation_ids):
    if not presentation_ids:
        return {}
    return {
        p.pk: p
        for p in Presentation.objects.select_for_update().filter(
            pk__in=sorted(set(presentation_ids))
        )
    }


def _qty_base(item):
    """Convierte cantidad de InvoiceItem (presentaciones) a base_units (ADR p31)."""
    return item.quantity * (item.presentation.conversion_factor or 1)


def _items_settling_stock(invoice, items):
    """
    Ítems de la factura que LIQUIDAN stock en la ruta de confirmación/cancelación
    (ADR p30). Ruta ÚNICA de descuento — la usan _confirm_locked_invoice
    (descuenta 'out') y cancel_invoice (revierte 'in'). No existe una segunda
    función que mueva stock por ítem.

      - direct_sale: todo ítem con presentación.
      - consultation: SOLO ítems dispensados de una receta interna
        (dispensed_from_prescription_item). Los demás ítems con presentación
        (sincronizados desde MedicalRecordProduct) YA movieron stock al
        consumirse en la consulta; volver a moverlos aquí sería doble descuento.
        Los servicios no tienen presentación → nunca mueven stock.

    Devuelve una lista materializada con presentation__product ya cargado (para
    el mensaje de stock insuficiente sin N+1).
    """
    qs = items.select_related('presentation__product')
    if invoice.invoice_type == 'direct_sale':
        return [i for i in qs if i.presentation_id]
    return [i for i in qs if i.presentation_id and i.dispensed_from_prescription_item_id]


# ---------------------------------------------------------------------------
# Funciones internas — asumen invoice YA lockeada con select_for_update().
# Sin @transaction.atomic propio; el caller maneja la transacción.
# ---------------------------------------------------------------------------

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


def _confirm_locked_invoice(invoice, user):
    """
    Confirma una factura que YA está lockeada con select_for_update().

    Descuenta stock de los ítems que LIQUIDAN inventario al confirmar
    (`_items_settling_stock`): toda venta directa, y en una consulta solo los
    ítems dispensados de receta (los insumos sincronizados desde
    MedicalRecordProduct ya descontaron al consumirse). Ruta ÚNICA (ADR p30).
    Orden estricto: validar → validar stock → descontar → cambiar estado.
    """
    if invoice.status != 'draft':
        raise ValidationError("Solo se pueden confirmar facturas en borrador.")

    active_items = InvoiceItem.all_objects.filter(invoice=invoice, is_active=True)

    if not active_items.exists():
        raise ValidationError("No se puede confirmar una factura sin ítems.")

    items_to_settle = _items_settling_stock(invoice, active_items)

    if items_to_settle:
        for item in items_to_settle:
            if item.quantity <= 0:
                raise ValidationError(
                    f"Cantidad inválida en ítem '{item.description}'."
                )

        # ADR p31: validación pre-check contra Product.stock_quantity (en base_units).
        # La validación autoritativa ocurre dentro de apply_stock_movement (con lock).
        errors = []
        for item in items_to_settle:
            qty_base = _qty_base(item)
            product = item.presentation.product
            if product.stock_quantity < qty_base:
                errors.append(
                    f"'{product.name}': disponible {product.stock_quantity} "
                    f"{product.base_unit}, requerido {qty_base}."
                )
        if errors:
            raise ValidationError(errors)

        is_direct = invoice.invoice_type == 'direct_sale'
        reason = (
            f'Venta directa — Factura #{invoice.pk}' if is_direct
            else f'Dispensación de receta — Factura #{invoice.pk}'
        )
        for item in items_to_settle:
            try:
                # Única entrada de consumo (spec §10). lot=item.lot (None en
                # productos sin tracks_lots → path histórico idéntico).
                consume_product(
                    presentation=item.presentation,
                    quantity_base=_qty_base(item),
                    organization=invoice.organization,
                    lot=item.lot,
                    reason=reason,
                    created_by=user,
                    invoice=invoice,
                )
            except Exception as e:
                logger.error(
                    f"Error aplicando movimiento de stock en factura {invoice.pk}: {str(e)}"
                )
                raise

    invoice.status = 'confirmed'
    invoice.confirmed_at = timezone.now()
    invoice.confirmed_at_source = 'service'
    invoice.save(update_fields=[
        'status', 'confirmed_at', 'confirmed_at_source', 'updated_at',
    ])
    _log_status_change(invoice, previous='draft', new='confirmed', user=user)
    _warn_if_late_arrival(invoice, 'confirmed_at', invoice.confirmed_at,
                          'financial_cash', 'confirm_invoice')


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
    Writer del anchor `paid_at`. Transiciona confirmed → paid cuando la cobranza
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
    _log_status_change(invoice, previous=previous_status, new='paid', user=user)
    _warn_if_late_arrival(invoice, 'paid_at', invoice.paid_at,
                          'financial_cash', 'pay_invoice')


def _pay_locked_invoice(invoice, user, lines, *, require_full, idempotency_key=None, cash_session=None):
    """
    Registra Payment(s) append-only sobre una invoice YA lockeada y confirmada;
    si la cobranza queda saldada la transiciona a `paid` (writer de `paid_at`).

    `lines` ya viene normalizado por _validate_payment_lines. La idempotencia
    (replay) y la validación de estado las maneja el caller público.

    require_full=True  (venta directa / pago de un paso): exige cubrir el saldo
                       exacto.
    require_full=False (consulta): permite pago parcial → queda `confirmed`.

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
            cash_session=cash_session,
        ).save()

    if invoice.remaining_balance <= Decimal('0.00'):
        _mark_invoice_paid(invoice, user, now)
    return invoice


# ---------------------------------------------------------------------------
# Wrappers públicos — con @transaction.atomic y lock propio.
# ---------------------------------------------------------------------------

@transaction.atomic
def confirm_invoice(invoice, user):
    """Confirma una factura. Lock + validación + transición atómica."""
    invoice = Invoice.objects.for_organization(invoice.organization).select_for_update().get(pk=invoice.pk)
    _confirm_locked_invoice(invoice, user)


@transaction.atomic
def cancel_invoice(invoice, user, notes=''):
    """
    Cancela una factura. Si estaba confirmed, revierte el stock.
    Facturas paid no se pueden cancelar directamente.
    """
    invoice = Invoice.objects.for_organization(invoice.organization).select_for_update().get(pk=invoice.pk)

    if invoice.status == 'paid':
        raise ValidationError("Las facturas pagadas no se pueden cancelar directamente.")
    if invoice.status == 'cancelled':
        raise ValidationError("La factura ya está cancelada.")
    # ADR p27: una factura confirmed con pagos parciales registrados no se
    # cancela en seco (dejaría dinero sin devolver). La devolución va por nota
    # de crédito (ADR p29). Las facturas paid ya están bloqueadas arriba.
    if Payment.all_objects.filter(invoice=invoice).exists():
        raise ValidationError(
            "No se puede cancelar una factura con pagos registrados. "
            "Emite una devolución (nota de crédito)."
        )

    previous_status = invoice.status

    # Revierte SOLO los ítems que descontaron stock al confirmar (misma ruta que
    # _confirm_locked_invoice via _items_settling_stock): venta directa completa,
    # o ítems dispensados de receta en una consulta. Los insumos de consulta
    # (MedicalRecordProduct) se revierten al borrar el MRP, no aquí (ADR p30).
    if previous_status == 'confirmed':
        items_to_revert = _items_settling_stock(
            invoice,
            InvoiceItem.all_objects.filter(invoice=invoice, is_active=True),
        )
        if items_to_revert:
            for item in items_to_revert:
                try:
                    # Reverso al MISMO lote del que se descontó (P4). lot=None en
                    # productos sin tracks_lots → path histórico idéntico.
                    restock_product(
                        presentation=item.presentation,
                        quantity_base=_qty_base(item),
                        organization=invoice.organization,
                        lot=item.lot,
                        reason=f'Reversión por cancelación — Factura #{invoice.pk}',
                        created_by=user,
                        invoice=invoice,
                    )
                except Exception as e:
                    logger.error(
                        f"Error revirtiendo stock en factura {invoice.pk}: {str(e)}"
                    )
                    raise

    invoice.status = 'cancelled'
    invoice.cancelled_at = timezone.now()
    invoice.cancelled_at_source = 'service'
    invoice.save(update_fields=[
        'status', 'cancelled_at', 'cancelled_at_source', 'updated_at',
    ])
    _log_status_change(invoice, previous=previous_status, new='cancelled', user=user, notes=notes)
    _warn_if_late_arrival(invoice, 'cancelled_at', invoice.cancelled_at,
                          'financial_cash', 'cancel_invoice')


@transaction.atomic
def pay_invoice(invoice, user, payment_method=None, *, payment_lines=None, idempotency_key=None):
    """
    Registra el pago de una factura confirmada. Authoritative writer del anchor
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
    # CashSession es la CABEZA del orden de locks (ADR p28): adquirir antes que Invoice.
    cash_session = _resolve_cash_session_for_payment(user, invoice.organization)

    invoice = Invoice.objects.for_organization(invoice.organization).select_for_update().get(pk=invoice.pk)

    if _is_payment_replay(invoice, idempotency_key):
        _log_idempotent_dedupe(invoice, idempotency_key)
        return invoice

    if invoice.status == 'paid':
        raise ValidationError('La factura ya fue pagada.')
    if invoice.status != 'confirmed':
        raise ValidationError(
            'Solo se pueden pagar facturas confirmadas. Confirma la factura primero.'
        )

    raw = payment_lines if payment_lines else _legacy_single_line(
        payment_method, invoice.remaining_balance
    )
    lines = _validate_payment_lines(raw)
    return _pay_locked_invoice(
        invoice, user, lines, require_full=True,
        idempotency_key=idempotency_key, cash_session=cash_session,
    )


# ---------------------------------------------------------------------------
# Direct sale — pay atómico (confirmar + pagar en una sola transacción)
# ---------------------------------------------------------------------------

@transaction.atomic
def pay_direct_sale(invoice, user, payment_method=None, *, payment_lines=None, idempotency_key=None):
    """
    Paga una venta directa confirmando y cobrando en una sola transacción.

    UX: draft → paid (un solo paso para el cajero).
    Interno: draft → confirmed → paid (máquina de estados completa).

    Analytics: confirmed_at y paid_at tendrán valores casi idénticos (ms de
    diferencia). Para métricas de accrual vs cash, esto significa que en
    direct_sale ambas curvas coinciden — comportamiento esperado y distinto
    al de consultation donde puede haber horas/días entre confirmación y pago.
    Ver docs/dashboard-metrics-contract.md §3.1.2 (revenue_accrual).

    Un solo select_for_update() — sin re-locks internos.

    Soporta pago único (legacy `payment_method`) o split (`payment_lines`). El
    pago DEBE cubrir el total exacto (sin parciales en venta directa).
    Idempotente vía `idempotency_key`. Ver financial-event-model-contract.md §8.
    """
    # CashSession es la CABEZA del orden de locks (ADR p28): antes que Invoice.
    cash_session = _resolve_cash_session_for_payment(user, invoice.organization)

    invoice = Invoice.objects.for_organization(invoice.organization).select_for_update().get(pk=invoice.pk)

    if _is_payment_replay(invoice, idempotency_key):
        _log_idempotent_dedupe(invoice, idempotency_key)
        return invoice

    if invoice.invoice_type != 'direct_sale':
        raise ValidationError(
            'La acción direct-pay solo está disponible para ventas directas.'
        )
    if invoice.status == 'paid':
        raise ValidationError('La factura ya fue pagada.')
    if invoice.status != 'draft':
        raise ValidationError(
            'Solo se pueden cobrar directamente facturas en borrador.'
        )

    # Validar método/monto early (antes de tocar stock en _confirm). El monto
    # del legacy single line se fija al total (= remaining en un draft sin pagos).
    raw = payment_lines if payment_lines else _legacy_single_line(
        payment_method, invoice.remaining_balance
    )
    lines = _validate_payment_lines(raw)

    # Refunds (devolución de venta directa pagada) → ADR p29, no cancel_invoice.
    _confirm_locked_invoice(invoice, user)
    return _pay_locked_invoice(
        invoice, user, lines, require_full=True,
        idempotency_key=idempotency_key, cash_session=cash_session,
    )


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
    from .models import (
        CreditNote, CreditNoteItem, RefundPayment, CREDIT_NOTE_REASON_CODES,
    )

    if reason_code not in CREDIT_NOTE_REASON_CODES:
        raise ValidationError("Causa de devolución (reason_code) inválida.")
    if not credit_lines:
        raise ValidationError("Se requiere al menos una línea a devolver.")

    # CashSession a la cabeza del orden de locks (igual que el pago).
    cash_session = _resolve_cash_session_for_payment(user, invoice.organization)
    invoice = Invoice.objects.for_organization(
        invoice.organization
    ).select_for_update().get(pk=invoice.pk)

    if invoice.status != 'paid':
        raise ValidationError("Solo se pueden reembolsar facturas pagadas.")

    # Idempotencia (contrato §9): refund ya procesado → no-op.
    if idempotency_key and RefundPayment.all_objects.filter(
        organization_id=invoice.organization_id, idempotency_key=f"{idempotency_key}:0",
    ).exists():
        logger.info("IDEMPOTENT_REFUND_DEDUPED", extra={
            'event': 'IDEMPOTENT_REFUND_DEDUPED', 'invoice_id': invoice.pk,
            'idempotency_key': idempotency_key,
        })
        return (
            CreditNote.objects.for_organization(invoice.organization)
            .filter(original_invoice=invoice).order_by('-id').first()
        )

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
        if disposition not in ('restock', 'discard'):
            raise ValidationError("disposition inválido (restock|discard).")
        if qty <= 0 or amt < 0:
            raise ValidationError("Cantidad debe ser > 0 y monto >= 0.")
        prior = CreditNoteItem.all_objects.filter(invoice_item=item).aggregate(
            q=Sum('quantity'), a=Sum('amount'),
        )
        prior_q = prior['q'] or Decimal('0.00')
        prior_a = prior['a'] or Decimal('0.00')
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
        CreditNoteItem(
            organization=invoice.organization, credit_note=credit_note,
            invoice_item=item, quantity=qty, amount=amt, disposition=disposition,
        ).save()
        if disposition == 'restock' and item.presentation_id:
            # ADR p31: qty está en presentaciones; convertir a base_units para stock.
            qty_base = qty * (item.presentation.conversion_factor or 1)
            # Reverso al lote original del ítem (P4); None si el producto no usa lotes.
            restock_product(
                presentation=item.presentation, quantity_base=qty_base,
                organization=invoice.organization, lot=item.lot,
                reason=f'Devolución — NC #{credit_note.pk}', created_by=user, invoice=invoice,
            )

    for i, line in enumerate(rlines):
        key = f"{idempotency_key}:{i}" if idempotency_key else None
        RefundPayment(
            organization=invoice.organization, credit_note=credit_note,
            amount=line['amount'], method=line['method'], occurred_at=now,
            actor=user, provenance='service', reference=line['reference'],
            idempotency_key=key, cash_session=cash_session,
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
    from .models import CreditNote, RefundPayment, RefundReversal

    cash_session = _resolve_cash_session_for_payment(user, credit_note.organization)
    credit_note = CreditNote.objects.for_organization(
        credit_note.organization
    ).select_for_update().get(pk=credit_note.pk)

    refund_payments = list(RefundPayment.all_objects.filter(credit_note=credit_note))
    if not refund_payments:
        raise ValidationError("La nota de crédito no tiene reembolsos que revertir.")

    already = set(
        RefundReversal.all_objects.filter(reverses__in=refund_payments)
        .values_list('reverses_id', flat=True)
    )
    pending = [rp for rp in refund_payments if rp.pk not in already]
    if not pending:
        raise ValidationError("Esta nota de crédito ya fue revertida.")

    # Idempotencia: si ya se registró este reverso (misma key), no-op.
    if idempotency_key and RefundReversal.all_objects.filter(
        organization_id=credit_note.organization_id, idempotency_key=f"{idempotency_key}:0",
    ).exists():
        logger.info("IDEMPOTENT_REVERSAL_DEDUPED", extra={
            'event': 'IDEMPOTENT_REVERSAL_DEDUPED', 'credit_note_id': credit_note.pk,
            'idempotency_key': idempotency_key,
        })
        return credit_note

    now = timezone.now()
    notes_clean = sanitize_text(reason_notes or '', max_length=5000)
    total_reversed = Decimal('0.00')
    for i, rp in enumerate(pending):
        key = f"{idempotency_key}:{i}" if idempotency_key else None
        RefundReversal(
            organization=credit_note.organization, reverses=rp,
            amount=rp.amount, method=rp.method, occurred_at=now, actor=user,
            cash_session=cash_session, provenance='service',
            reason_code=reason_code or '', reason_notes=notes_clean,
            idempotency_key=key,
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


@transaction.atomic
def get_or_create_invoice_for_medical_record(medical_record):
    """
    Fuente única de verdad para obtener o crear la Invoice de una consulta.

    Reglas:
    1) Si la consulta tiene cita, busca la factura vinculada a la cita primero
       (con filtro multi-tenant explícito: misma organización)
    2) Si la factura de cita existe, la linkea al medical_record
    3) Fallback: crea factura nueva vinculada al medical_record

    Usado por _sync_invoice_item en medical_records/views.py e inventory/views.py.
    """
    from apps.medical_records.models import MedicalRecord

    medical_record = MedicalRecord.objects.for_organization(
        medical_record.organization
    ).select_for_update().get(pk=medical_record.pk)
    org = medical_record.organization

    if medical_record.appointment_id:
        invoice = Invoice.objects.select_for_update().filter(
            appointment=medical_record.appointment,
            organization=org,
        ).first()
        if invoice:
            if invoice.medical_record_id is None:
                invoice.medical_record = medical_record
                invoice.save(update_fields=['medical_record'])
            return invoice

    invoice, _ = Invoice.objects.get_or_create(
        medical_record=medical_record,
        defaults={
            'owner': medical_record.pet.owner,
            'pet': medical_record.pet,
            'organization': org,
            'status': 'draft',
            'invoice_type': 'consultation',
            'tax_rate': org.tax_rate,
        }
    )
    return Invoice.objects.for_organization(org).select_for_update().get(pk=invoice.pk)


def _fmt_base_qty(value):
    """Formatea un Decimal sin ceros sobrantes para mensajes ('2.00' → '2')."""
    return format(value.normalize(), 'f')


def _enforce_prescribed_quantity_cap(invoice, rx_items, requested_base, exclude_item_id=None):
    """
    Tope clínico de dispensación: por cada ítem de receta, lo ya dispensado en
    la factura (líneas activas con FK `dispensed_from_prescription_item`, en
    unidades base del producto) más lo solicitado no puede exceder
    `PrescriptionItem.quantity`. La receta se captura en unidades base (el VET
    receta por producto, ADR p31); cada línea dispensada pesa
    `quantity × presentation.conversion_factor`. El cliente puede llevar menos
    de lo recetado; nunca más — ni en una llamada ni acumulado entre llamadas
    mientras la factura siga en draft.

    Args:
        invoice: factura de consulta ya lockeada por el caller (las líneas
            dispensadas viven bajo ese lock; sin carrera entre dispensaciones).
        rx_items: dict {PrescriptionItem.id: PrescriptionItem} de la receta.
        requested_base: dict {PrescriptionItem.id: Decimal} con las unidades
            base solicitadas en esta llamada.
        exclude_item_id: PK de un InvoiceItem a excluir del acumulado — para
            editar la cantidad de una línea dispensada existente (PATCH), donde
            la cantidad nueva reemplaza a la vieja en vez de sumarse.

    Raises:
        ValidationError: si algún ítem excede lo recetado (mensaje con
            amparado / dispensado / restante).
    """
    if not requested_base:
        return
    already_qs = (
        InvoiceItem.all_objects
        .filter(
            invoice=invoice,
            is_active=True,
            dispensed_from_prescription_item_id__in=requested_base.keys(),
        )
    )
    if exclude_item_id is not None:
        already_qs = already_qs.exclude(pk=exclude_item_id)
    already_rows = (
        already_qs
        .values('dispensed_from_prescription_item')
        .annotate(
            base=Sum(
                ExpressionWrapper(
                    F('quantity') * F('presentation__conversion_factor'),
                    output_field=DecimalField(max_digits=24, decimal_places=6),
                )
            )
        )
    )
    already_base = {
        row['dispensed_from_prescription_item']: row['base'] or Decimal('0')
        for row in already_rows
    }
    for rx_item_id, req_base in requested_base.items():
        rx_item = rx_items[rx_item_id]
        prescribed = rx_item.quantity
        dispensed = already_base.get(rx_item_id, Decimal('0'))
        if dispensed + req_base > prescribed:
            remaining = max(prescribed - dispensed, Decimal('0'))
            unit = rx_item.product.get_base_unit_display() or 'unidad(es)'
            raise ValidationError(
                f"'{rx_item.product.name}': la receta ampara "
                f"{_fmt_base_qty(prescribed)} {unit} y ya se dispensaron "
                f"{_fmt_base_qty(dispensed)}; puedes dispensar máximo "
                f"{_fmt_base_qty(remaining)} más."
            )


def enforce_dispensed_item_quantity_cap(invoice, item, new_quantity):
    """
    Cap de receta al EDITAR la cantidad de una línea dispensada (PATCH de
    InvoiceItem). La cantidad nueva reemplaza a la vieja, por eso el acumulado
    excluye al propio ítem. No-op si la línea no proviene de una receta.

    El caller debe poseer los locks de Invoice e InvoiceItem y estar dentro de
    transaction.atomic() (la view de edición ya lo garantiza).

    Raises:
        ValidationError: si la cantidad nueva excede lo recetado.
    """
    rx_item = item.dispensed_from_prescription_item
    if rx_item is None:
        return
    if item.presentation_id:
        cf = item.presentation.conversion_factor or Decimal('1')
    else:
        cf = Decimal('1')
    _enforce_prescribed_quantity_cap(
        invoice,
        {rx_item.id: rx_item},
        {rx_item.id: Decimal(new_quantity) * cf},
        exclude_item_id=item.pk,
    )


@transaction.atomic
def dispense_prescription_into_invoice(prescription, lines, user):
    """
    ADR p30: agrega a la MISMA factura de consulta los productos de la receta
    interna que el cliente decide llevar. NO crea una factura aparte.

    Cada línea se inserta como `InvoiceItem` con `dispensed_from_prescription_item`
    seteado. Ese FK es el discriminador de la ruta única de descuento: al
    confirmar la factura de consulta, `_confirm_locked_invoice` descuenta stock
    SOLO de los ítems dispensados (los insumos sincronizados desde
    MedicalRecordProduct ya descontaron al consumirse). No hay una segunda
    función de stock. Por eso aquí NO se mueve inventario: solo se arman las
    líneas en el draft. El pre-check de stock es best-effort (autoritativo al
    confirmar bajo lock).

    La `prescription` interna es el respaldo legal de los productos
    requires_prescription, por lo que NO se crea ExternalPrescriptionAttestation
    (ADR p26, que cubre la venta SIN receta previa). El permiso
    billing.rx_dispense lo valida la view antes de llamar a este servicio.

    Args:
        prescription: Prescription resuelta y tenant-validada por el caller.
        lines: lista de {'presentation_id': int, 'quantity': Decimal-like,
            'prescription_item_id': int|None}. Líneas con la misma presentación
            se agregan (unique_together(invoice, presentation)).
        user: actor (created_by).

    Returns:
        La Invoice de consulta (draft) con las líneas dispensadas agregadas.

    Raises:
        ValidationError: sin líneas, cantidad no positiva, presentación o ítem de
            receta inválidos, factura no editable, stock insuficiente (pre-check),
            o la presentación ya está en la factura como ítem NO dispensado.
    """
    org = prescription.organization

    if not prescription.medical_record_id:
        raise ValidationError("La receta no está ligada a una consulta.")

    # Mapas de la receta para resolver/validar el ítem origen de cada línea.
    # rx_item_by_product es fallback para líneas legacy SIN prescription_item:
    # si la receta tuviera el MISMO producto en dos ítems, setdefault ata todo
    # al primero — el tope de dispensación se carga a ese ítem (conservador:
    # rechaza antes, nunca permite de más). El frontend siempre envía
    # prescription_item explícito, donde esto no aplica.
    rx_items = {}
    rx_item_by_product = {}
    for it in prescription.items.all():
        rx_items[it.id] = it
        rx_item_by_product.setdefault(it.product_id, it)

    # Resolver la factura de consulta (lockea MedicalRecord -> Invoice, orden
    # canónico). Es la fuente única de la factura de la consulta (ADR p30 / p7).
    from apps.medical_records.models import MedicalRecord
    mr = MedicalRecord.objects.for_organization(org).get(pk=prescription.medical_record_id)
    invoice = get_or_create_invoice_for_medical_record(mr)  # ya viene lockeada

    if invoice.status != 'draft':
        raise ValidationError(
            "Solo se puede dispensar mientras el cobro está en borrador. "
            "Esta factura ya fue confirmada o pagada."
        )

    # Agregar cantidad por presentación; recordar el ítem de receta resuelto.
    aggregated = {}   # pres_id -> {'qty': Decimal, 'rx_item': PrescriptionItem}
    for line in lines:
        qty = Decimal(str(line['quantity']))
        if qty <= 0:
            raise ValidationError("La cantidad a dispensar debe ser mayor a 0.")
        pres_id = line['presentation_id']
        entry = aggregated.setdefault(pres_id, {
            'qty': Decimal('0'),
            'rx_item_id': line.get('prescription_item_id'),
            'lot_id': line.get('lot_id'),
        })
        entry['qty'] += qty

    if not aggregated:
        raise ValidationError("Selecciona al menos un producto a dispensar.")

    locked = _lock_presentations(list(aggregated.keys()))

    # Fase 1 — resolver y validar cada línea (sin mutar nada todavía).
    requested_base = {}   # rx_item.id -> unidades base solicitadas en esta llamada
    for pres_id, entry in aggregated.items():
        pres = locked.get(pres_id)
        if pres is None or pres.organization_id != org.id:
            raise ValidationError("Presentación fuera de tu organización.")

        # Resolver el ítem de receta (provenance + discriminador de stock).
        rx_item_id = entry['rx_item_id']
        rx_item = rx_items.get(rx_item_id) if rx_item_id is not None else rx_item_by_product.get(pres.product_id)
        if rx_item is None:
            raise ValidationError(
                f"'{pres.product.name}' no corresponde a un ítem de esta receta."
            )
        if rx_item.product_id != pres.product_id:
            raise ValidationError(
                "La presentación elegida no corresponde al producto recetado."
            )

        qty = entry['qty']
        if pres.stock < qty:
            raise ValidationError(
                f"Stock insuficiente para '{pres.product.name}': "
                f"disponible {pres.stock}, solicitado {qty}."
            )

        # unique_together(invoice, presentation): si ya existe la línea, solo se
        # acumula sobre un ítem dispensado; un insumo de consulta (sin FK) o un
        # servicio no se mezclan — recepción lo ajusta en el cobro.
        existing = (
            InvoiceItem.all_objects.select_for_update()
            .filter(invoice=invoice, presentation=pres)
            .first()
        )
        if existing is not None and existing.dispensed_from_prescription_item_id is None:
            raise ValidationError(
                f"'{pres.product.name}' ya está en este cobro como insumo de la "
                f"consulta; ajusta su cantidad directamente en la factura."
            )

        # Lote (B2b): obligatorio y consumible si el producto lo trackea. Si el
        # ítem dispensado ya existe, conserva su lote (inmutable); el nuevo lote
        # solo aplica al crear la línea.
        stock_lot = None
        if pres.product.tracks_lots:
            if existing is not None:
                stock_lot = existing.lot  # inmutable: conserva el lote de la línea
            else:
                lot_id = entry.get('lot_id')
                if lot_id is not None:
                    # Override explícito (si la UI lo envía).
                    stock_lot = (
                        StockLot.objects.for_organization(org)
                        .filter(pk=lot_id, product=pres.product).first()
                    )
                    if stock_lot is None:
                        raise ValidationError("Lote inválido para este producto.")
                    if not stock_lot.is_consumable:
                        raise ValidationError(
                            f"El lote {stock_lot.lot_number} no está disponible "
                            f"({stock_lot.effective_status})."
                        )
                else:
                    # FEFO automático (P1) — se fija en el ítem para que el reverso
                    # (cancelación/devolución) vuelva al mismo lote.
                    stock_lot = first_consumable_lot(pres.product)
                    if stock_lot is None:
                        raise ValidationError(
                            f"'{pres.product.name}' no tiene lotes disponibles para dispensar."
                        )

        entry['pres'] = pres
        entry['rx_item'] = rx_item
        entry['existing'] = existing
        entry['lot'] = stock_lot
        cf = pres.conversion_factor or Decimal('1')
        requested_base[rx_item.id] = requested_base.get(rx_item.id, Decimal('0')) + qty * cf

    # Fase 2 — tope clínico: dispensado acumulado + solicitado ≤ recetado.
    _enforce_prescribed_quantity_cap(invoice, rx_items, requested_base)

    # Fase 3 — mutar: crear o acumular las líneas dispensadas.
    for entry in aggregated.values():
        pres = entry['pres']
        existing = entry['existing']
        qty = entry['qty']
        if existing is not None:
            apply_invoice_item_quantity_delta(existing, qty)
        else:
            InvoiceItem.objects.create(
                invoice=invoice,
                presentation=pres,
                description=str(pres),
                quantity=qty,
                unit_price=pres.sale_price,
                organization=org,
                dispensed_from_prescription_item=entry['rx_item'],
                lot=entry.get('lot'),
            )

    return Invoice.objects.for_organization(org).select_for_update().get(pk=invoice.pk)
