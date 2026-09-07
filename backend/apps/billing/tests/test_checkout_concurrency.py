from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from apps.billing.checkout_services import (
    add_checkout_item,
    create_direct_sale_checkout,
    post_checkout,
)
from apps.billing.models import Checkout, CommandReceipt, Invoice, Payment
from apps.inventory.models import Presentation, Product
from apps.organizations.models import Organization
from apps.patients.models import Owner
from apps.users.models import User


class CheckoutPayConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.organization = Organization.objects.create(
            name='Checkout concurrency', timezone='UTC',
        )
        self.user = User.objects.create_user(
            username='checkout-concurrency-admin', password='x',
            organization=self.organization, role='ADMIN',
        )
        self.owner = Owner.objects.create(
            name='Cliente concurrencia', phone='5559000100',
            organization=self.organization,
        )
        self.product = Product.objects.create(
            name='Producto concurrencia', internal_code='CONCURRENT-1',
            category='food', base_unit='unit', stock_quantity=Decimal('10'),
            organization=self.organization,
        )
        self.presentation = Presentation.objects.create(
            product=self.product, name='Unidad', base_unit='unit',
            conversion_factor=Decimal('1'), stock=Decimal('10'),
            sale_price=Decimal('50.00'), organization=self.organization,
        )
        checkout = create_direct_sale_checkout(
            organization=self.organization, customer=self.owner, pet=None,
            user=self.user,
        )
        add_checkout_item(
            checkout, self.user, presentation=self.presentation,
            quantity=Decimal('2'),
        )
        checkout.refresh_from_db()
        self.checkout_pk = checkout.pk
        self.checkout_version = checkout.version

    def _race_pay(self, keys):
        barrier = Barrier(len(keys))

        def worker(idempotency_key):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '15s'")
                checkout = Checkout.all_objects.get(pk=self.checkout_pk)
                user = User.objects.get(pk=self.user.pk)
                barrier.wait(timeout=10)
                invoice = post_checkout(
                    checkout,
                    user,
                    payment_method='card',
                    expected_version=self.checkout_version,
                    idempotency_key=idempotency_key,
                )
                return ('ok', invoice.pk)
            except Exception as exc:  # Return the cross-thread outcome for assertions.
                return ('error', exc)
            finally:
                # Worker-local persistent connections outlive the Future when
                # CONN_MAX_AGE > 0; close explicitly so test DB teardown is safe.
                connection.close()

        with ThreadPoolExecutor(max_workers=len(keys)) as pool:
            return list(pool.map(worker, keys))

    def _assert_single_financial_and_stock_effect(self):
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('8.0000'))

    def test_simultaneous_retry_with_same_key_replays_one_committed_result(self):
        outcomes = self._race_pay(['same-pay-key', 'same-pay-key'])

        self.assertEqual([kind for kind, _ in outcomes], ['ok', 'ok'])
        self.assertEqual(len({invoice_pk for _, invoice_pk in outcomes}), 1)
        self.assertEqual(
            CommandReceipt.objects.filter(
                command_kind='pay_checkout', idempotency_key='same-pay-key',
                status='succeeded',
            ).count(),
            1,
        )
        self._assert_single_financial_and_stock_effect()

    def test_simultaneous_different_keys_allow_only_one_checkout_transition(self):
        outcomes = self._race_pay(['pay-key-a', 'pay-key-b'])

        successes = [value for kind, value in outcomes if kind == 'ok']
        errors = [value for kind, value in outcomes if kind == 'error']
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ValidationError)
        self.assertEqual(
            CommandReceipt.objects.filter(command_kind='pay_checkout').count(),
            1,
        )
        self._assert_single_financial_and_stock_effect()
