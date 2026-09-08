import logging
from decimal import Decimal, ROUND_HALF_UP

from django.db import connection
from django.db.models import F, Q
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Presentation, Product, StockLot, StockMovement
from .units import presentation_conversion_factor

# Precisión máxima para base_units en StockMovement (decimal_places=4)
_QTY_PRECISION = Decimal('0.0001')

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
            reason='Entrada de mercancía',
            created_by=created_by,
            lot=stock_lot,
        )
        affected.append(stock_lot)

    return affected
