import logging
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import F
from django.core.exceptions import ValidationError

from .models import Presentation, Product, StockMovement

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
):
    """
    Único punto de entrada para todos los cambios de stock (ADR p31).

    ⚠️ CONTRATO DE LOCK (CRÍTICO):
    El caller DEBE llamar dentro de transaction.atomic(). Esta función adquiere
    su propio select_for_update() sobre Product internamente. El orden de locks
    del caller debe ser: CashSession → MedicalRecord → Invoice → (esta función).
    No pre-lockear Product antes de llamar a esta función — el lock se adquiere
    aquí para garantizar el orden correcto.

    Callers que cumplen el contrato:
      - billing/services.py::_confirm_locked_invoice
      - billing/services.py::cancel_invoice
      - billing/services.py::process_refund
      - inventory/views.py::adjust_stock, adjust_presentation_stock
      - inventory/models.py::MedicalRecordProduct.save / .delete

    `quantity` DEBE estar en unidades base (base_unit del Product).
    Los callers son responsables de convertir:
        quantity_base = quantity_presentations * presentation.conversion_factor

    `presentation` se usa únicamente para contexto/audit trail y para el
    dual-write de Presentation.stock (campo de compatibilidad durante la
    transición a ADR p31).

    Lanza ValidationError si un movimiento 'out' dejaría stock negativo.
    """
    org_id = getattr(organization, 'pk', organization)
    user_id = getattr(created_by, 'pk', None)

    # Normalizar quantity a ≤4 decimal places (límite de StockMovement.quantity).
    # Decimal arithmetic puede producir trailing zeros extra, e.g.
    # Decimal('3.00') * Decimal('1.0000') = Decimal('3.000000') → 6 places → error.
    quantity = Decimal(quantity).quantize(_QTY_PRECISION, rounding=ROUND_HALF_UP)

    # Lock product: garantiza read-validate-update atómico sobre stock_quantity.
    # ⚠️ Uses all_objects para bypass de filtros de tenant y soft-delete.
    locked_product = Product.all_objects.select_for_update().get(
        pk=presentation.product_id
    )

    if movement_type == 'out':
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
        Product.all_objects.filter(pk=locked_product.pk).update(
            stock_quantity=F('stock_quantity') - quantity
        )
        # Dual-write: Presentation.stock en unidades de presentación (compatibilidad).
        if presentation.conversion_factor:
            Presentation.all_objects.filter(pk=presentation.pk).update(
                stock=F('stock') - (quantity / presentation.conversion_factor)
            )

    elif movement_type == 'in':
        Product.all_objects.filter(pk=locked_product.pk).update(
            stock_quantity=F('stock_quantity') + quantity
        )
        if presentation.conversion_factor:
            Presentation.all_objects.filter(pk=presentation.pk).update(
                stock=F('stock') + (quantity / presentation.conversion_factor)
            )

    elif movement_type == 'adjustment':
        Product.all_objects.filter(pk=locked_product.pk).update(
            stock_quantity=quantity
        )
        if presentation.conversion_factor:
            Presentation.all_objects.filter(pk=presentation.pk).update(
                stock=quantity / presentation.conversion_factor
            )

    else:
        logger.error(
            "movement_type desconocido: %s | organization_id=%s user_id=%s product=%s",
            movement_type, org_id, user_id, locked_product.pk,
        )
        raise ValidationError(f"Tipo de movimiento inválido: {movement_type}")

    StockMovement.objects.create(
        presentation=presentation,
        product=locked_product,
        organization=organization,
        movement_type=movement_type,
        quantity=quantity,
        quantity_unit='base',
        reason=reason,
        created_by=created_by,
        medical_record=medical_record,
        invoice=invoice,
    )

    logger.info(
        "StockMovement | type=%s qty_base=%s product=%s presentation=%s "
        "organization_id=%s user_id=%s reason=%r",
        movement_type, quantity, locked_product.pk, presentation.pk,
        org_id, user_id, reason,
    )
