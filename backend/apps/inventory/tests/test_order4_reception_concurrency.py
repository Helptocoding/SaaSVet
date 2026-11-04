from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from apps.inventory.models import Product, StockLot, StockMovement
from apps.inventory.tests.test_stock_reception import ReceptionSetupMixin
from apps.users.models import User


class ReceptionConcurrencyTests(ReceptionSetupMixin, TransactionTestCase):
    def test_identical_operation_from_two_connections_applies_once(self):
        self.assertEqual(connection.vendor, 'postgresql')
        barrier = Barrier(2)
        key = str(uuid4())
        url = self._receive_url()
        user_id = self.admin.pk

        def post():
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(User.objects.get(pk=user_id))
                barrier.wait(timeout=15)
                response = client.post(url, {'lots': [{'lot_number': 'SYN', 'quantity': '2'}]},
                                       format='json', HTTP_X_IDEMPOTENCY_KEY=key)
                return response.status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(post) for _ in range(2)]
            self.assertEqual([future.result(timeout=40) for future in futures], [200, 200])
        product = Product.all_objects.get(pk=self.product.pk)
        self.assertEqual(product.stock_quantity, Decimal('2'))
        self.assertEqual(StockLot.all_objects.get(product=product).quantity_on_hand, Decimal('2'))
        self.assertEqual(StockMovement.all_objects.filter(product=product, created_by=self.admin).count(), 1)
