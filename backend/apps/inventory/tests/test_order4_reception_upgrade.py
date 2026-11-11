"""Upgrade from inventory.0030 with synthetic receipts, and rollback of the new state."""
from decimal import Decimal
from uuid import uuid4

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

RECEIPT_ONLY = ('inventory', '0030_stock_reception_receipt')


class ReceptionOperationUpgradeTests(TransactionTestCase):
    def _migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return MigrationExecutor(connection).loader.project_state(targets).apps

    def test_existing_receipts_are_classified_without_inventing_evidence(self):
        self.assertEqual(connection.vendor, 'postgresql')
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        previous = [node for node in latest if node[0] != 'inventory'] + [RECEIPT_ONLY]
        try:
            historical = self._migrate(previous)
            org = historical.get_model('organizations', 'Organization').objects.create(name='Upgrade I01')
            user = historical.get_model('users', 'User').objects.create(organization=org, username='upgrade_i01')
            product = historical.get_model('inventory', 'Product').objects.create(
                organization=org, name='Producto', internal_code='UP-I01', base_unit='vial',
                tracks_lots=True, stock_quantity='7',
            )
            presentation = historical.get_model('inventory', 'Presentation').objects.create(
                organization=org, product=product, name='Vial', base_unit='vial', quantity='1',
                conversion_factor='1', stock='7', sale_price='10',
            )
            movement = historical.get_model('inventory', 'StockMovement').objects.create(
                organization=org, presentation=presentation, product=product, movement_type='in',
                quantity='7', quantity_unit='base', reason='Entrada de mercancía', created_by=user,
            )
            Receipt = historical.get_model('inventory', 'StockReceptionReceipt')
            confirmed_id, without_result_id = uuid4(), uuid4()
            snapshot = {'lots': [{'lot_number': 'OLD', 'quantity_on_hand': '7.0000'}]}
            Receipt.objects.create(
                organization=org, actor=user, presentation=presentation, operation_id=confirmed_id,
                payload_hash='a' * 64, result=snapshot,
            )
            Receipt.objects.create(
                organization=org, actor=user, presentation=presentation, operation_id=without_result_id,
                payload_hash='b' * 64, result=None,
            )

            self._migrate(latest)

            from apps.inventory.models import Product, StockMovement, StockReceptionReceipt
            confirmed = StockReceptionReceipt.objects.get(operation_id=confirmed_id)
            self.assertEqual(confirmed.status, 'confirmed')
            self.assertEqual(confirmed.product_id, product.pk)
            self.assertIsNone(confirmed.payload)
            self.assertIsNone(confirmed.conversion_factor_snapshot)
            self.assertIsNone(confirmed.resolved_at)
            self.assertEqual(confirmed.result, snapshot)
            self.assertFalse(confirmed.movements.exists())
            without_result = StockReceptionReceipt.objects.get(operation_id=without_result_id)
            self.assertEqual(without_result.status, 'pending')
            self.assertIsNone(without_result.payload)
            self.assertIsNone(StockMovement.objects.get(pk=movement.pk).reception_operation_id)
            self.assertEqual(Product.all_objects.get(pk=product.pk).stock_quantity, Decimal('7'))

            # Rollback refuses to drop an open intent that still holds a capture...
            StockReceptionReceipt.objects.filter(pk=without_result.pk).update(
                payload={'lots': [{'lot_number': 'N', 'quantity': '1.00'}]},
            )
            with self.assertRaisesMessage(RuntimeError, 'recepciones sin resolver'):
                self._migrate(previous)
            # ...and goes through once it is resolved, keeping the receipt and its stock.
            self._migrate(latest)
            StockReceptionReceipt.objects.filter(pk=without_result.pk).update(
                status='discarded', discard_reason='entered_in_error', resolved_at=confirmed.created_at,
            )
            historical = self._migrate(previous)
            Receipt = historical.get_model('inventory', 'StockReceptionReceipt')
            self.assertEqual(Receipt.objects.get(operation_id=confirmed_id).result, snapshot)
            self.assertIsNone(Receipt.objects.get(operation_id=without_result_id).result)
            Product = historical.get_model('inventory', 'Product')
            self.assertEqual(Product.objects.get(pk=product.pk).stock_quantity, Decimal('7'))
        finally:
            self._migrate(latest)
