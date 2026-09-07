"""Authoritative unit conversion invariants shared by Inventory and Billing."""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError


def validated_conversion_factor(value) -> Decimal:
    """Return a finite, positive base-units-per-presentation factor."""
    try:
        factor = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({'conversion_factor': 'El factor de conversión es inválido.'})
    if not factor.is_finite() or factor <= 0:
        raise ValidationError({
            'conversion_factor': 'El factor debe ser finito y mayor a cero.'
        })
    return factor


def presentation_conversion_factor(presentation) -> Decimal:
    return validated_conversion_factor(presentation.conversion_factor)


def presentation_quantity_to_base(quantity, conversion_factor) -> Decimal:
    """Convert presentation units using the immutable factor captured by a writer."""
    try:
        normalized_quantity = Decimal(str(quantity))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({'quantity': 'La cantidad es inválida.'})
    if not normalized_quantity.is_finite() or normalized_quantity <= 0:
        raise ValidationError({'quantity': 'La cantidad debe ser finita y mayor a cero.'})
    return normalized_quantity * validated_conversion_factor(conversion_factor)
