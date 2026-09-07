"""Small builders that keep cross-app tests on the authoritative Checkout flow."""
from decimal import Decimal
from uuid import uuid4

from apps.billing.checkout_services import (
    add_checkout_item,
    create_direct_sale_checkout,
    post_checkout,
)


def build_direct_sale_checkout(*, organization, owner, user, service=None,
                               presentation=None, quantity=Decimal('1'), pet=None):
    checkout = create_direct_sale_checkout(
        organization=organization,
        customer=owner,
        pet=pet,
        user=user,
    )
    add_checkout_item(
        checkout,
        user,
        service=service,
        presentation=presentation,
        quantity=quantity,
    )
    checkout.refresh_from_db()
    return checkout


def pay_checkout_for_test(checkout, *, user, payment_method=None, payment_lines=None,
                          idempotency_key=None):
    checkout.refresh_from_db()
    return post_checkout(
        checkout,
        user,
        payment_method=payment_method,
        payment_lines=payment_lines,
        expected_version=checkout.version,
        idempotency_key=idempotency_key or f'test-pay-{uuid4()}',
    )
