import hashlib
import json
import logging
from decimal import Decimal, ROUND_HALF_UP

from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, connection, transaction
from django.db.models import F, Q
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status as http_status
from rest_framework.exceptions import APIException, NotFound

from apps.core.permissions import user_has_permission

from .models import (
    Presentation, Product, StockLot, StockMovement, StockReceptionReceipt,
)
from .units import presentation_conversion_factor

# Precisión máxima para base_units en StockMovement (decimal_places=4)
_QTY_PRECISION = Decimal('0.0001')

# Motivo con el que toda recepción entra al libro de movimientos.
RECEPTION_MOVEMENT_REASON = 'Entrada de mercancía'

logger = logging.getLogger(__name__)


def apply_stock_movement(
    presentation,
    quantity,
    movement_type,
    organization,
    reason='',
    created_by=None,
    medical_record=None,
    invoice=None,
    lot=None,
    allow_non_consumable=False,
    reception_operation=None,
):
    """
    Único punto de entrada de bajo nivel para todos los cambios de stock (ADR p31).
    **Single-lot**: mueve stock de UN lote (o de ninguno). El reparto multi-lote y
    la política FEFO viven en `consume_product` (spec inventario 2026-07-10, §10),
    no aquí.

    ⚠️ CONTRATO DE LOCK (CRÍTICO):
    El caller DEBE llamar dentro de transaction.atomic(). Esta función adquiere su
    propio select_for_update() sobre Product internamente. El orden de locks del
    caller debe ser: CashSession → MedicalRecord → Invoice → (esta función).
    No pre-lockear Product antes de llamar. Si se pasa `lot`, se lockea DESPUÉS del
    Product (el lote pertenece al producto ya lockeado) → orden de locks intacto.

    `quantity` DEBE estar en unidades base. Los callers convierten:
        quantity_base = quantity_presentations * presentation.conversion_factor

    `lot` (StockLot | None) — trazabilidad por lote:
      - None (default): comportamiento HISTÓRICO idéntico (productos sin tracks_lots
        y todos los flujos legacy). Cero cambio.
      - StockLot: además de Product.stock_quantity, ajusta StockLot.quantity_on_hand
        bajo lock, valida saldo del lote en 'out', y denormaliza lot_number en el
        movimiento (el ledger conserva la identidad aunque el lote se borre).

    Lanza ValidationError si un movimiento 'out' dejaría stock (de Product o de lote)
    negativo.
    """
    org_id = getattr(organization, 'pk', organization)
    user_id = getattr(created_by, 'pk', None)

    factor = presentation_conversion_factor(presentation)

    # Normalizar quantity a ≤4 decimal places (límite de StockMovement.quantity).
    quantity = Decimal(quantity).quantize(_QTY_PRECISION, rounding=ROUND_HALF_UP)

    # Lock product: garantiza read-validate-update atómico sobre stock_quantity.
    # ⚠️ Uses all_objects para bypass de filtros de tenant y soft-delete.
    locked_product = Product.all_objects.select_for_update().get(
        pk=presentation.product_id
    )
    if (
        locked_product.organization_id != org_id
        or presentation.organization_id != org_id
    ):
        raise ValidationError('La presentación y el producto pertenecen a otra organización.')

    # Lock del lote DESPUÉS del producto (pertenece al producto ya lockeado).
    locked_lot = None
    if lot is not None:
        locked_lot = StockLot.all_objects.select_for_update().get(pk=lot.pk)
        if (
            locked_lot.organization_id != org_id
            or locked_lot.product_id != locked_product.pk
        ):
            raise ValidationError('El lote no pertenece al producto y organización indicados.')

    if movement_type == 'out':
        if (
            locked_lot is not None
            and not allow_non_consumable
            and not locked_lot.is_consumable
        ):
            raise ValidationError(
                f"El lote '{locked_lot.lot_number}' no está disponible para consumo "
                f"(estado: {locked_lot.effective_status})."
            )
        if locked_product.stock_quantity < quantity:
            logger.warning(
                "Stock insuficiente | organization_id=%s user_id=%s product=%s "
                "presentation=%s solicitado=%s disponible=%s",
                org_id, user_id, locked_product.pk, presentation.pk,
                quantity, locked_product.stock_quantity,
            )
            raise ValidationError(
                f"Stock insuficiente para '{locked_product.name}'. "
                f"Disponible: {locked_product.stock_quantity} {locked_product.base_unit}, "
                f"solicitado: {quantity}."
            )
        if locked_lot is not None and locked_lot.quantity_on_hand < quantity:
            logger.warning(
                "Stock de lote insuficiente | organization_id=%s user_id=%s "
                "product=%s lot=%s solicitado=%s disponible=%s",
                org_id, user_id, locked_product.pk, locked_lot.pk,
                quantity, locked_lot.quantity_on_hand,
            )
            raise ValidationError(
                f"Stock insuficiente en el lote '{locked_lot.lot_number}'. "
                f"Disponible: {locked_lot.quantity_on_hand}, solicitado: {quantity}."
            )
        Product.all_objects.filter(pk=locked_product.pk).update(
            stock_quantity=F('stock_quantity') - quantity
        )
        if locked_lot is not None:
            StockLot.all_objects.filter(pk=locked_lot.pk).update(
                quantity_on_hand=F('quantity_on_hand') - quantity
            )
        # Dual-write: Presentation.stock en unidades de presentación (compatibilidad).
        Presentation.all_objects.filter(pk=presentation.pk).update(
            stock=F('stock') - (quantity / factor)
        )

    elif movement_type == 'in':
        Product.all_objects.filter(pk=locked_product.pk).update(
            stock_quantity=F('stock_quantity') + quantity
        )
        if locked_lot is not None:
            StockLot.all_objects.filter(pk=locked_lot.pk).update(
                quantity_on_hand=F('quantity_on_hand') + quantity
            )
        Presentation.all_objects.filter(pk=presentation.pk).update(
            stock=F('stock') + (quantity / factor)
        )

    elif movement_type == 'adjustment':
        if locked_lot is not None:
            # Ajuste POR LOTE: fija el saldo del lote absoluto y mueve el agregado
            # del Product por el DELTA, para mantener Σ lotes == Product.stock_quantity.
            delta = quantity - locked_lot.quantity_on_hand
            StockLot.all_objects.filter(pk=locked_lot.pk).update(
                quantity_on_hand=quantity
            )
            Product.all_objects.filter(pk=locked_product.pk).update(
                stock_quantity=F('stock_quantity') + delta
            )
            Presentation.all_objects.filter(pk=presentation.pk).update(
                stock=F('stock') + (delta / factor)
            )
        else:
            # Ajuste a nivel Product (comportamiento histórico, absoluto).
            Product.all_objects.filter(pk=locked_product.pk).update(
                stock_quantity=quantity
            )
            Presentation.all_objects.filter(pk=presentation.pk).update(
                stock=quantity / factor
            )

    else:
        logger.error(
            "movement_type desconocido: %s | organization_id=%s user_id=%s product=%s",
            movement_type, org_id, user_id, locked_product.pk,
        )
        raise ValidationError(f"Tipo de movimiento inválido: {movement_type}")

    movement = StockMovement.objects.create(
        presentation=presentation,
        product=locked_product,
        lot=locked_lot,
        lot_number=(locked_lot.lot_number if locked_lot is not None else ''),
        organization=organization,
        movement_type=movement_type,
        quantity=quantity,
        quantity_unit='base',
        reason=reason,
        created_by=created_by,
        medical_record=medical_record,
        invoice=invoice,
        reception_operation=reception_operation,
    )

    try:
        from apps.notifications.services import handle_stock_transition
        prev_qty = locked_product.stock_quantity
        locked_product.refresh_from_db(fields=['stock_quantity', 'min_stock', 'name'])
        handle_stock_transition(
            organization, locked_product, prev_qty,
            locked_product.stock_quantity, movement.pk, actor=created_by,
        )
    except Exception:
        logger.exception("notifications: hook stock best-effort falló")

    logger.info(
        "StockMovement | type=%s qty_base=%s product=%s presentation=%s lot=%s "
        "organization_id=%s user_id=%s reason=%r",
        movement_type, quantity, locked_product.pk, presentation.pk,
        (locked_lot.pk if locked_lot else None), org_id, user_id, reason,
    )
    return movement


def resolve_consumption_lots(product, quantity_base, *, lock=False):
    """
    Política FEFO (First Expired First Out) — spec §Políticas operativas (P1).
    Devuelve una asignación `[(StockLot, cantidad_base), ...]` para consumir
    `quantity_base` del `product`, tomando primero los lotes de caducidad más
    próxima entre los **elegibles** (effective_status = ACTIVE: status activo, no
    vencido, con saldo). Los vencidos/en cuarentena/retirados NO son elegibles.

    Reparte entre varios lotes si uno no alcanza. Si no hay saldo elegible
    suficiente → ValidationError (P2: no se consume "a ciegas").

    NO lockea (lectura de asignación). El lock real y la validación autoritativa
    ocurren en `apply_stock_movement` por lote. `consume_product` orquesta ambos
    dentro de la misma transacción.
    """
    qty = Decimal(quantity_base).quantize(_QTY_PRECISION, rounding=ROUND_HALF_UP)
    today = timezone.localdate()

    lots_query = (
        StockLot.objects.for_organization(product.organization)
        .filter(
            product=product,
            status=StockLot.STATUS_ACTIVE,
            quantity_on_hand__gt=0,
        )
        .filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=today))
        .order_by(F('expiry_date').asc(nulls_last=True), 'id')
    )
    if lock:
        lots_query = lots_query.select_for_update()
    lots = list(lots_query)

    remaining = qty
    allocations = []
    for stock_lot in lots:
        if remaining <= 0:
            break
        take = min(stock_lot.quantity_on_hand, remaining)
        if take <= 0:
            continue
        allocations.append((stock_lot, take))
        remaining -= take

    if remaining > 0:
        raise ValidationError(
            f"No hay lotes elegibles con saldo suficiente para consumir "
            f"'{product.name}' (faltan {remaining} {product.base_unit})."
        )
    return allocations


def discard_lot(lot, organization, quantity=None, reason='Descarte de lote', created_by=None):
    """
    Merma / write-off de un lote (B2c). Movimiento `out` sobre el lote — NO es un
    consumo clínico ni una venta; saca del inventario stock vencido/retirado. Puede
    aplicarse a lotes vencidos/en cuarentena/retirados (no valida `is_consumable`;
    esa es la razón de existir). `quantity` en base-units; default = saldo del lote.
    Debe correr dentro de transaction.atomic().
    """
    assert connection.in_atomic_block, (
        "discard_lot() debe llamarse dentro de transaction.atomic()."
    )
    locked_lot = StockLot.all_objects.select_for_update().get(pk=lot.pk)
    qty = (
        Decimal(str(quantity)).quantize(_QTY_PRECISION, rounding=ROUND_HALF_UP)
        if quantity is not None else locked_lot.quantity_on_hand
    )
    if qty <= 0:
        raise ValidationError("La cantidad a descartar debe ser mayor a 0.")
    if qty > locked_lot.quantity_on_hand:
        raise ValidationError(
            f"No puedes descartar más que el saldo del lote "
            f"({locked_lot.quantity_on_hand})."
        )
    presentation = locked_lot.product.presentations.first()
    if presentation is None:
        raise ValidationError("El producto no tiene una presentación configurada.")
    apply_stock_movement(
        presentation=presentation, quantity=qty, movement_type='out',
        organization=organization, reason=reason, created_by=created_by, lot=locked_lot,
        # Una merma es una salida administrativa, no consumo clínico/venta;
        # por eso puede retirar lotes vencidos o bloqueados sin relajar los
        # callers de consumo.
        allow_non_consumable=True,
    )
    return locked_lot


def set_lot_status(lot, status, organization, created_by=None):
    """
    Cambia el estado administrativo del lote (B2c): active | quarantined | recalled.
    `recalled` bloquea el consumo conservando el saldo (retiro de laboratorio);
    `quarantined` idem (revisión). No es append-only (es un flag mutable); la
    trazabilidad del bloqueo vive en el log + el ledger de movimientos posteriores.
    """
    valid = {StockLot.STATUS_ACTIVE, StockLot.STATUS_QUARANTINED, StockLot.STATUS_RECALLED}
    if status not in valid:
        raise ValidationError(f"Estado de lote inválido: {status}.")
    StockLot.all_objects.filter(pk=lot.pk).update(status=status)
    logger.info(
        "STOCKLOT_STATUS_CHANGED | lot=%s product=%s new_status=%s organization_id=%s user_id=%s",
        lot.pk, lot.product_id, status,
        getattr(organization, 'pk', organization), getattr(created_by, 'pk', None),
    )
    lot.refresh_from_db(fields=['status'])
    return lot


def first_consumable_lot(product):
    """
    Lote FEFO elegible (effective_status=ACTIVE: activo, no vencido, con saldo) de
    menor caducidad, o None. Para selección automática cuando el caller no elige
    lote explícito (P1). No lockea — el consumo real valida bajo lock.
    """
    today = timezone.localdate()
    return (
        StockLot.objects.for_organization(product.organization)
        .filter(product=product, status=StockLot.STATUS_ACTIVE, quantity_on_hand__gt=0)
        .filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=today))
        .order_by(F('expiry_date').asc(nulls_last=True), 'id')
        .first()
    )


def consume_product(
    presentation,
    quantity_base,
    organization,
    reason='',
    created_by=None,
    medical_record=None,
    invoice=None,
    lot=None,
    force=False,
):
    """
    **Única entrada pública de consumo de inventario** (spec §10). Todos los
    consumidores (MedicalRecordProduct, Billing, y futuros: hospitalización,
    transferencias, ajustes automáticos) pasan por aquí. Ninguno llama a
    `resolve_consumption_lots` directamente → la política de lotes vive en un solo
    lugar y el próximo consumidor no puede olvidarse de aplicarla.

    Flujo:
      - Producto sin `tracks_lots` → un `apply_stock_movement('out', lot=None)`
        (idéntico al histórico).
      - Producto con `tracks_lots`:
          * `lot` dado (override manual, P3) → se respeta ese lote. Si el lote no es
            consumible (vencido/cuarentena/retirado) se bloquea salvo `force=True`
            (P2/§6 — el `force` lo habilitará B2 con permiso + atestación).
          * `lot` None → FEFO (`resolve_consumption_lots`, P1), reparte entre lotes.

    Debe correr dentro de transaction.atomic() (el caller ya lo garantiza).
    """
    assert connection.in_atomic_block, (
        "consume_product() debe llamarse dentro de transaction.atomic(); sin tx los "
        "select_for_update() por lote no aplican lock real."
    )

    product = presentation.product
    if not product.tracks_lots:
        movement = apply_stock_movement(
            presentation, quantity_base, 'out', organization,
            reason=reason, created_by=created_by,
            medical_record=medical_record, invoice=invoice,
        )
        return [(movement, None, movement.quantity)]

    qty = Decimal(quantity_base).quantize(_QTY_PRECISION, rounding=ROUND_HALF_UP)

    org_id = getattr(organization, 'pk', organization)
    locked_product = Product.all_objects.select_for_update().get(pk=product.pk)
    if locked_product.organization_id != org_id:
        raise ValidationError('El producto pertenece a otra organización.')

    if lot is not None:
        locked_lot = StockLot.all_objects.select_for_update().get(pk=lot.pk)
        if (
            locked_lot.organization_id != org_id
            or locked_lot.product_id != locked_product.pk
        ):
            raise ValidationError('El lote no pertenece al producto y organización indicados.')
        if not force and not locked_lot.is_consumable:
            raise ValidationError(
                f"El lote '{locked_lot.lot_number}' no está disponible para consumo "
                f"(estado: {locked_lot.effective_status})."
            )
        allocations = [(locked_lot, qty)]
    else:
        allocations = resolve_consumption_lots(locked_product, qty, lock=True)

    committed = []
    for stock_lot, take in allocations:
        movement = apply_stock_movement(
            presentation, take, 'out', organization,
            reason=reason, created_by=created_by,
            medical_record=medical_record, invoice=invoice,
            lot=stock_lot,
            allow_non_consumable=force,
        )
        committed.append((movement, stock_lot, take))
    return committed


def restock_product(
    presentation,
    quantity_base,
    organization,
    lot=None,
    reason='',
    created_by=None,
    medical_record=None,
    invoice=None,
):
    """
    Devuelve stock al inventario (movimiento 'in'). Primitiva inversa de
    `consume_product`. Si se pasa `lot`, acredita a ESE lote — así los reversos
    (cancelación de factura, refund con restock, eliminación de producto en
    consulta) devuelven al **lote original** (política P4). El caller lee el lote
    original del ledger. Sin `lot`, acredita a nivel Product (histórico).

    Debe correr dentro de transaction.atomic().
    """
    apply_stock_movement(
        presentation, quantity_base, 'in', organization,
        reason=reason, created_by=created_by,
        medical_record=medical_record, invoice=invoice, lot=lot,
    )


def receive_stock(
    presentation,
    lots,
    organization,
    supplier_name='',
    received_at=None,
    created_by=None,
    reception_operation=None,
):
    """
    Recepción de mercancía **multi-lote** (spec §7, fase B1). Una recepción = una
    presentación + N líneas de lote. Cada línea encuentra-o-crea el `StockLot`
    `(product, lot_number, expiry_date)` y aplica un movimiento `in` lot-scoped
    (acredita el lote + el agregado del Product). Una compra suele traer varios
    lotes → esto se contempla desde el diseño.

    Solo para productos con `tracks_lots` (los demás usan el ajuste histórico).
    `quantity` de cada línea está en unidades de PRESENTACIÓN → se convierte a
    base con `conversion_factor`. Debe correr dentro de transaction.atomic().

    `lots` = [{'lot_number', 'expiry_date', 'quantity'}, ...].
    `reception_operation` queda enlazada a cada movimiento: esa es la evidencia de
    lo que aplicó esta operación, independiente de los saldos posteriores.
    Devuelve la lista de StockLot afectados.
    """
    product = presentation.product
    if not product.tracks_lots:
        raise ValidationError(
            "La recepción por lotes requiere un producto con control de lotes."
        )

    cf = presentation_conversion_factor(presentation)
    default_received = received_at or timezone.localdate()
    affected = []

    for line in lots:
        lot_number = (line.get('lot_number') or '').strip()
        expiry_date = line.get('expiry_date')
        qty_pres = Decimal(str(line['quantity']))

        stock_lot, _created = StockLot.objects.get_or_create(
            organization=organization,
            product=product,
            lot_number=lot_number,
            expiry_date=expiry_date,
            defaults={
                'received_at': default_received,
                'supplier_name': supplier_name,
                'quantity_on_hand': Decimal('0'),
            },
        )

        locked_pres = Presentation.objects.select_for_update().get(pk=presentation.pk)
        apply_stock_movement(
            presentation=locked_pres,
            quantity=qty_pres * cf,
            movement_type='in',
            organization=organization,
            reason=RECEPTION_MOVEMENT_REASON,
            created_by=created_by,
            lot=stock_lot,
            reception_operation=reception_operation,
        )
        affected.append(stock_lot)

    return affected


# ---------------------------------------------------------------------------
# Operaciones de recepción: intención durable antes de tocar stock (orden 4, I01)
# ---------------------------------------------------------------------------
class ReceptionConflict(APIException):
    """409 de una operación de recepción; `code` distingue qué debe resolver la UI."""
    status_code = http_status.HTTP_409_CONFLICT
    default_code = 'reception_conflict'

    def __init__(self, code, message, **payload):
        super().__init__(detail=message)
        self.default_code = code
        self.error_payload = payload


def can_supervise_receptions(user):
    """Ver y cerrar operaciones ajenas exige un permiso de administración del
    equipo que ya existe; nunca permite ejecutarlas en nombre de otra persona."""
    return user_has_permission(user, 'staff.reset_password')


def _canonical_reception_payload(validated_data):
    canonical = json.dumps(
        validated_data, cls=DjangoJSONEncoder, sort_keys=True, separators=(',', ':'),
    )
    return json.loads(canonical), hashlib.sha256(canonical.encode()).hexdigest()


def _assert_same_reception(operation, actor, presentation, digest):
    if (operation.actor_id != actor.pk
            or operation.presentation_id != presentation.pk
            or operation.payload_hash != digest):
        raise ReceptionConflict(
            'reception_operation_conflict',
            'La operación no coincide con la recepción solicitada.',
        )


def _unresolved_reception_conflict(organization, actor, product):
    operation_id = (
        StockReceptionReceipt.objects
        .filter(organization=organization, actor=actor, product=product,
                status=StockReceptionReceipt.STATUS_PENDING)
        .values_list('operation_id', flat=True)
        .first()
    )
    return ReceptionConflict(
        'reception_unresolved',
        'Tienes una recepción sin resolver de este producto. '
        'Complétala o descártala antes de registrar otra.',
        unresolved_operation_id=str(operation_id) if operation_id else None,
    )


def _create_reception_intent(organization, actor, presentation, operation_id, payload, digest):
    """Intención nueva o, si otra petición ganó la carrera, la ya existente."""
    product = presentation.product
    has_unresolved = StockReceptionReceipt.objects.filter(
        organization=organization, actor=actor, product=product,
        status=StockReceptionReceipt.STATUS_PENDING,
    ).exists()
    if has_unresolved:
        raise _unresolved_reception_conflict(organization, actor, product)
    try:
        return StockReceptionReceipt.objects.get_or_create(
            organization=organization, operation_id=operation_id,
            defaults={
                'actor': actor, 'presentation': presentation, 'product': product,
                'payload': payload, 'payload_hash': digest,
                'conversion_factor_snapshot': presentation_conversion_factor(presentation),
            },
        )
    except IntegrityError as exc:
        diag = getattr(exc.__cause__, 'diag', None)
        if getattr(diag, 'constraint_name', None) == 'stock_reception_one_pending':
            raise _unresolved_reception_conflict(organization, actor, product) from exc
        raise


def prepare_reception(*, organization, actor, presentation, validated_data, operation_id):
    """Registra la intención sin tocar stock. Idempotente por operation_id."""
    payload, digest = _canonical_reception_payload(validated_data)
    operation = StockReceptionReceipt.objects.filter(
        organization=organization, operation_id=operation_id,
    ).first()
    created = False
    if operation is None:
        operation, created = _create_reception_intent(
            organization, actor, presentation, operation_id, payload, digest,
        )
    if not created:
        _assert_same_reception(operation, actor, presentation, digest)
    return operation, created


def build_reception_result(presentation, affected_lots):
    from .serializers import PresentationSerializer, StockLotSerializer

    presentation.refresh_from_db()
    for lot in affected_lots:
        lot.refresh_from_db()
    result = {
        'presentation': PresentationSerializer(presentation).data,
        'lots': StockLotSerializer(affected_lots, many=True).data,
    }
    return json.loads(json.dumps(result, cls=DjangoJSONEncoder))


def _apply_reception_locked(operation, actor):
    """Aplica la captura guardada. El caller tiene la fila bloqueada y la transacción
    abierta: stock, movimientos y confirmación se publican juntos o no se publican."""
    if operation.payload is None:
        raise ReceptionConflict(
            'reception_payload_unavailable',
            'Esta operación no conserva lo que se capturó. Solo puede descartarse.',
        )
    presentation = Presentation.all_objects.select_related('product').get(
        pk=operation.presentation_id,
    )
    if not (presentation.is_active and presentation.product.is_active):
        raise ValidationError('La presentación o el producto ya no están activos. Descarta esta operación.')
    if presentation_conversion_factor(presentation) != operation.conversion_factor_snapshot:
        raise ReceptionConflict(
            'reception_factor_changed',
            'El factor de la presentación cambió desde que se capturó esta recepción. '
            'Descártala y regístrala de nuevo con el factor vigente.',
        )
    payload = operation.payload
    affected = receive_stock(
        presentation=presentation,
        lots=[
            {
                'lot_number': line['lot_number'],
                'expiry_date': parse_date(line['expiry_date']) if line.get('expiry_date') else None,
                'quantity': Decimal(line['quantity']),
            }
            for line in payload['lots']
        ],
        organization=operation.organization,
        supplier_name=payload.get('supplier_name', ''),
        received_at=parse_date(payload['received_at']) if payload.get('received_at') else None,
        created_by=actor,
        reception_operation=operation,
    )
    operation.result = build_reception_result(presentation, affected)
    operation.status = StockReceptionReceipt.STATUS_CONFIRMED
    operation.resolved_at = timezone.now()
    operation.resolved_by = actor
    operation.save(update_fields=['result', 'status', 'resolved_at', 'resolved_by'])


def _raise_if_discarded(operation):
    if operation.status == StockReceptionReceipt.STATUS_DISCARDED:
        raise ReceptionConflict(
            'reception_discarded',
            'Esta operación se descartó y no sumó stock. Si la mercancía llegó, '
            'registra una recepción nueva.',
        )


def complete_reception(*, organization, actor, operation_id):
    """Ejecuta la intención propia una sola vez. Una repetición concurrente espera el
    lock y devuelve lo ya confirmado, sin movimientos nuevos."""
    with transaction.atomic():
        try:
            operation = StockReceptionReceipt.objects.select_for_update().get(
                organization=organization, operation_id=operation_id, actor=actor,
            )
        except StockReceptionReceipt.DoesNotExist:
            raise NotFound() from None
        _raise_if_discarded(operation)
        if operation.status == StockReceptionReceipt.STATUS_CONFIRMED:
            return operation, False
        _apply_reception_locked(operation, actor)
    return operation, True


def receive_with_identity(*, organization, actor, presentation, validated_data, operation_id):
    """Recepción identificada en una sola petición: intención y efecto se publican
    juntos, así que mientras esté en vuelo no es descubrible. El flujo de la app usa
    prepare_reception + complete_reception; esta vía queda para clientes que ya la usan."""
    payload, digest = _canonical_reception_payload(validated_data)
    with transaction.atomic():
        operation = StockReceptionReceipt.objects.filter(
            organization=organization, operation_id=operation_id,
        ).first()
        if operation is None:
            operation, _ = _create_reception_intent(
                organization, actor, presentation, operation_id, payload, digest,
            )
        operation = StockReceptionReceipt.objects.select_for_update().get(pk=operation.pk)
        _assert_same_reception(operation, actor, presentation, digest)
        _raise_if_discarded(operation)
        if operation.status != StockReceptionReceipt.STATUS_CONFIRMED:
            _apply_reception_locked(operation, actor)
    return operation


def discard_reception(*, organization, actor, operation_id, reason, note=''):
    """Cierra una intención sin aplicarla, conservando quién y por qué. Una ejecución
    que llegue después encuentra el estado terminal y no suma stock."""
    with transaction.atomic():
        queryset = StockReceptionReceipt.objects.select_for_update().filter(
            organization=organization, operation_id=operation_id,
        )
        if not can_supervise_receptions(actor):
            queryset = queryset.filter(actor=actor)
        try:
            operation = queryset.get()
        except StockReceptionReceipt.DoesNotExist:
            raise NotFound() from None
        if operation.status == StockReceptionReceipt.STATUS_CONFIRMED:
            raise ReceptionConflict(
                'reception_already_confirmed',
                'Esta recepción ya sumó stock y no puede descartarse.',
            )
        if operation.status == StockReceptionReceipt.STATUS_PENDING:
            operation.status = StockReceptionReceipt.STATUS_DISCARDED
            operation.discard_reason = reason
            operation.discard_note = note
            operation.resolved_at = timezone.now()
            operation.resolved_by = actor
            operation.save(update_fields=[
                'status', 'discard_reason', 'discard_note', 'resolved_at', 'resolved_by',
            ])
    return operation


def receptions_visible_to(organization, user, *, include_others=False):
    queryset = StockReceptionReceipt.objects.filter(organization=organization)
    return queryset if include_others else queryset.filter(actor=user)


def get_visible_reception(organization, user, operation_id):
    """Ajena sin facultad de supervisión u otra clínica: 404, sin confirmar existencia."""
    queryset = receptions_visible_to(
        organization, user, include_others=can_supervise_receptions(user),
    )
    try:
        return queryset.select_related(
            'actor', 'resolved_by', 'product', 'presentation',
        ).prefetch_related('movements__lot').get(operation_id=operation_id)
    except StockReceptionReceipt.DoesNotExist:
        raise NotFound() from None


def reception_allowed_actions(operation, user):
    if operation.status != StockReceptionReceipt.STATUS_PENDING:
        return []
    is_own = operation.actor_id == user.pk
    actions = []
    if is_own and operation.payload is not None:
        actions.append('complete')
    if is_own or can_supervise_receptions(user):
        actions.append('discard')
    return actions


def unattributed_reception_entries(organization, user, *, include_others=False):
    """Entradas del libro sin identidad de operación. Son hechos, pero nada permite
    atribuirlas a un intento concreto: la conclusión queda en manos de una persona."""
    queryset = StockMovement.objects.for_organization(organization).filter(
        movement_type='in', reason=RECEPTION_MOVEMENT_REASON, reception_operation__isnull=True,
    )
    if not include_others:
        queryset = queryset.filter(created_by=user)
    return queryset.select_related('product', 'presentation__product', 'created_by')


def reception_current_balance(operation):
    """Saldo de HOY de los lotes implicados. Acumula otras entradas y salidas: nunca
    es la cantidad de esta operación."""
    product = Product.all_objects.get(pk=operation.product_id)
    source_lines = (operation.payload or {}).get('lots') or (operation.result or {}).get('lots') or []
    lot_numbers = {line['lot_number'] for line in source_lines if line.get('lot_number')}
    lots = StockLot.all_objects.filter(
        organization_id=operation.organization_id, product=product, lot_number__in=lot_numbers,
    ).order_by('expiry_date', 'id')[:20]
    return {
        'as_of': timezone.now(),
        'product_stock_quantity': product.stock_quantity,
        'base_unit': product.base_unit,
        'lots': [
            {
                'public_id': lot.public_id,
                'lot_number': lot.lot_number,
                'expiry_date': lot.expiry_date,
                'quantity_on_hand': lot.quantity_on_hand,
                'effective_status': lot.effective_status,
            }
            for lot in lots
        ],
    }


def reception_ledger_since_intent(operation, limit=20):
    """Lo que entró a este producto desde la intención, para que una persona decida
    si esa mercancía ya se registró por otra vía antes de completar o descartar."""
    rows = list(
        StockMovement.all_objects.filter(
            organization_id=operation.organization_id, product_id=operation.product_id,
            movement_type__in=['in', 'adjustment'], created_at__gte=operation.created_at,
        ).select_related('product', 'presentation__product', 'created_by').order_by('-created_at', '-id')[:limit + 1]
    )
    return {'entries': rows[:limit], 'truncated': len(rows) > limit}
