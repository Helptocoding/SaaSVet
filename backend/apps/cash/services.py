"""
cash/services.py — writers autoritativos de apertura/cierre de caja (ADR p28).

Orden global de locks (extiende ADR p12): CashSession va a la CABEZA.
    CashSession → MedicalRecord → Invoice → Presentation → InvoiceItem → MedicalRecordProduct
`close_cash_session` lockea SOLO CashSession (nunca Invoice) → sin ABBA.
"""
import logging
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import CashMovement, CashSession

logger = logging.getLogger(__name__)
_cash_events = logging.getLogger('cash.events')

# Versión del shape del Z congelado (closed_snapshot). Bump al cambiar la
# semántica de un campo del reporte (DD-003). v1=Sprint A (sin refunds);
# v2=Sprint B (ADR p29: cash_refunds/cash_reversals en el cuadre de efectivo);
# v3=ADR p39 (manual_in/manual_out: movimientos manuales del cajón).
REPORT_SCHEMA_VERSION = 3
ZERO = Decimal('0.00')

# Signo por tipo de movimiento (invariante #4: amount > 0 siempre).
MOVEMENT_TYPES = {'deposit', 'withdrawal', 'expense'}
_INFLOW_TYPES = {'deposit'}
_OUTFLOW_TYPES = {'withdrawal', 'expense'}


def get_open_session(user):
    """Sesión abierta del usuario en su organización, o None. Sin lock (lectura)."""
    if user is None or getattr(user, 'organization_id', None) is None:
        return None
    return CashSession.objects.for_organization(user.organization).filter(
        status='open', opened_by=user,
    ).first()


@transaction.atomic
def open_cash_session(user, opening_float=ZERO, notes=''):
    """Abre un turno. Una sola caja abierta por usuario (unique parcial en DB)."""
    org = user.organization
    try:
        opening_float = Decimal(str(opening_float if opening_float is not None else 0))
    except Exception:
        raise ValidationError("Fondo de apertura inválido.")
    if opening_float < 0:
        raise ValidationError("El fondo de apertura no puede ser negativo.")

    if CashSession.objects.for_organization(org).filter(status='open', opened_by=user).exists():
        raise ValidationError("Ya tienes una caja abierta. Ciérrala antes de abrir otra.")

    session = CashSession(
        organization=org, opened_by=user, opened_at=timezone.now(),
        opening_float=opening_float, status='open', notes=notes or '',
    )
    session.save()
    _cash_events.info("CASH_SESSION_OPENED", extra={
        'event': 'CASH_SESSION_OPENED',
        'cash_session_id': session.pk,
        'organization_id': org.pk,
        'opened_by': getattr(user, 'pk', None),
        'opening_float': str(opening_float),
    })
    return session


@transaction.atomic
def close_cash_session(session, user, counted_cash, notes='', force=False):
    """
    Cierra un turno: computa el Z, congela el snapshot, calcula la diferencia.

    Lockea SOLO la CashSession (head del orden global). NO lockea Invoice — por
    eso no hay ABBA con el flujo de pago (que lockea CashSession → Invoice).
    Un pago en vuelo que intente usar esta sesión bloqueará en el lock; al
    reanudar verá status != 'open' y será rechazado (ningún pago tras el conteo).
    """
    # import local: evita ciclo billing↔cash
    from apps.billing.models import Payment, RefundPayment, RefundReversal

    session = (
        CashSession.objects.for_organization(session.organization)
        .select_for_update().get(pk=session.pk)
    )
    if session.status != 'open':
        raise ValidationError("La caja ya está cerrada.")
    try:
        counted_cash = Decimal(str(counted_cash))
    except Exception:
        raise ValidationError("Efectivo contado inválido.")
    if counted_cash < 0:
        raise ValidationError("El efectivo contado no puede ser negativo.")

    _dec = DecimalField(max_digits=14, decimal_places=2)

    def _sum_cash(model):
        return model.all_objects.filter(cash_session=session, method='cash').aggregate(
            t=Coalesce(Sum('amount'), Value(ZERO), output_field=_dec))['t']

    # Totales por método (Σ Payment del turno). card/transfer son informativos
    # (no entran al conteo de efectivo).
    by_method = {
        row['method']: row['total']
        for row in (
            Payment.all_objects.filter(cash_session=session)
            .values('method')
            .annotate(total=Coalesce(Sum('amount'), Value(ZERO), output_field=_dec))
        )
    }
    cash_in = by_method.get('cash', ZERO)
    # ADR p29: refunds en efectivo restan; reversals (contra-asiento) suman.
    cash_refunds = _sum_cash(RefundPayment)
    cash_reversals = _sum_cash(RefundReversal)
    # ADR p39: movimientos manuales del cajón — entradas suman, retiros/gastos restan.
    movements_by_type = {
        row['movement_type']: row['total']
        for row in (
            CashMovement.all_objects.filter(cash_session=session)
            .values('movement_type')
            .annotate(total=Coalesce(Sum('amount'), Value(ZERO), output_field=_dec))
        )
    }
    manual_in = sum((movements_by_type.get(t, ZERO) for t in _INFLOW_TYPES), ZERO)
    manual_out = sum((movements_by_type.get(t, ZERO) for t in _OUTFLOW_TYPES), ZERO)
    expected = (
        session.opening_float + cash_in - cash_refunds + cash_reversals
        + manual_in - manual_out
    )
    difference = counted_cash - expected
    op_count = Payment.all_objects.filter(cash_session=session).count()
    movements_count = CashMovement.all_objects.filter(cash_session=session).count()

    snapshot = {
        'opening_float': str(session.opening_float),
        'totals_by_method': {k: str(v) for k, v in by_method.items()},
        'cash_refunds': str(cash_refunds),
        'cash_reversals': str(cash_reversals),
        'manual_in': str(manual_in),
        'manual_out': str(manual_out),
        'movements_by_type': {k: str(v) for k, v in movements_by_type.items()},
        'movements_count': movements_count,
        'cash_expected': str(expected),
        'cash_counted': str(counted_cash),
        'difference': str(difference),
        'operations': op_count,
        'actor': getattr(user, 'pk', None),
        'generated_at': timezone.now().isoformat(),
        'report_schema_version': REPORT_SCHEMA_VERSION,
    }

    session.status = 'force_closed' if force else 'closed'
    session.closed_by = user
    session.closed_at = timezone.now()
    session.expected_cash = expected
    session.counted_cash = counted_cash
    session.difference = difference
    session.closed_snapshot = snapshot
    session.report_schema_version = REPORT_SCHEMA_VERSION
    if notes:
        session.notes = notes
    session.save()

    _cash_events.info(
        "CASH_SESSION_FORCE_CLOSED" if force else "CASH_SESSION_CLOSED",
        extra={
            'event': "CASH_SESSION_FORCE_CLOSED" if force else "CASH_SESSION_CLOSED",
            'cash_session_id': session.pk,
            'organization_id': session.organization_id,
            'closed_by': getattr(user, 'pk', None),
            'expected_cash': str(expected),
            'counted_cash': str(counted_cash),
            'difference': str(difference),
        },
    )
    return session


@transaction.atomic
def register_cash_movement(user, movement_type, amount, reason):
    """
    Registra un movimiento manual del cajón (ADR p39) sobre la caja abierta
    del actor. Writer único de CashMovement — append-only, corrección =
    contra-movimiento.

    Lockea la CashSession (cabeza del orden global): serializado contra el
    cierre Z — si el cierre gana el lock, esta función ve status != 'open' y
    rechaza (ningún movimiento se cuela después del conteo).
    """
    org = user.organization
    if movement_type not in MOVEMENT_TYPES:
        raise ValidationError("Tipo de movimiento inválido.")
    try:
        amount = Decimal(str(amount))
    except Exception:
        raise ValidationError("Monto inválido.")
    if amount <= 0:
        raise ValidationError("El monto debe ser mayor a 0.")
    reason = (reason or '').strip()
    if not reason:
        raise ValidationError("El motivo es obligatorio.")

    session = (
        CashSession.objects.for_organization(org)
        .select_for_update()
        .filter(status='open', opened_by=user)
        .first()
    )
    if session is None:
        raise ValidationError(
            "No hay una caja abierta. Abre un turno para registrar movimientos."
        )

    movement = CashMovement(
        organization=org,
        cash_session=session,
        movement_type=movement_type,
        amount=amount,
        reason=reason,
        occurred_at=timezone.now(),
        actor=user,
    )
    movement.save()
    _cash_events.info("CASH_MOVEMENT_REGISTERED", extra={
        'event': 'CASH_MOVEMENT_REGISTERED',
        'cash_movement_id': movement.pk,
        'cash_session_id': session.pk,
        'organization_id': org.pk,
        'actor': getattr(user, 'pk', None),
        'movement_type': movement_type,
        'amount': str(amount),
    })
    return movement
