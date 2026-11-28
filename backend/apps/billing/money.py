from decimal import Decimal, ROUND_HALF_UP

MONEY = Decimal("0.01")


def money(v: Decimal) -> Decimal:
    """Redondea a 2 decimales con HALF_UP. Usar en todo valor monetario antes de guardar."""
    return v.quantize(MONEY, rounding=ROUND_HALF_UP)


def line_subtotal(qty: Decimal, price: Decimal, discount: Decimal = Decimal("0")) -> Decimal:
    """Subtotal de un ítem: (qty * price) - descuento ya calculado, redondeado."""
    gross = qty * price
    return money(gross - discount)


def discount_amount(gross: Decimal, discount_type: str, discount_value: Decimal) -> Decimal:
    """Calcula el monto de descuento dado el bruto, tipo y valor."""
    if discount_type == "percentage":
        return money(gross * (discount_value / Decimal("100")))
    if discount_type == "fixed":
        return money(min(discount_value, gross))
    return Decimal("0.00")


def unit_price_with_tax(amount, tax_rate) -> Decimal | None:
    """Precio de UNA unidad con el impuesto de la organización (ADR p70 D4).

    Mismo redondeo que `invoice_totals` aplicado a un subtotal de un artículo,
    así que coincide con el total de un Checkout de una sola unidad. Con varios
    artículos el Checkout redondea el impuesto sobre el subtotal y la suma de
    precios unitarios puede diferir en centavos: no se usa para totales.
    Sin precio → None (el llamador lo presenta como «lo confirma el equipo»).
    """
    if amount is None or tax_rate is None:
        return None
    return invoice_totals(Decimal(str(amount)), Decimal(str(tax_rate)))[2]


def context_tax_rate(serializer_context, obj):
    """Tasa vigente de la organización dueña de `obj`, para mostrar precios.

    Usa la organización ya cargada en la sesión cuando es la misma (sin consulta
    extra por fila) y cae a `obj.organization` en otro caso.
    """
    request = (serializer_context or {}).get('request')
    organization = getattr(getattr(request, 'user', None), 'organization', None)
    if organization is not None and organization.pk == obj.organization_id:
        return organization.tax_rate
    return obj.organization.tax_rate


def invoice_totals(subtotal: Decimal, tax_rate: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """
    Devuelve (subtotal, tax_amount, total), todos redondeados a 2 decimales.
    Entrada: subtotal ya redondeado, tax_rate en [0, 1].
    """
    subtotal = money(subtotal)
    tax = money(subtotal * tax_rate)
    total = money(subtotal + tax)
    return subtotal, tax, total
