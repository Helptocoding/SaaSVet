"""Historical migration upgrade with synthetic clinical and financial snapshots."""
from decimal import Decimal
from importlib import import_module

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone
from apps.core.subject_history import snapshot


class AliasUpgradeTests(TransactionTestCase):
    def test_upgrade_preserves_balances_and_document_snapshots(self):
        self.assertEqual(connection.vendor, 'postgresql')
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        previous = [node for node in latest if node[0] != 'inventory'] + [('inventory', '0027_preserve_stock_and_consumption')]
        try:
            executor.migrate(previous)
            historical = executor.loader.project_state(previous).apps
            Org = historical.get_model('organizations', 'Organization')
            User = historical.get_model('users', 'User')
            Owner = historical.get_model('patients', 'Owner')
            Pet = historical.get_model('patients', 'Pet')
            Record = historical.get_model('medical_records', 'MedicalRecord')
            Product = historical.get_model('inventory', 'Product')
            Presentation = historical.get_model('inventory', 'Presentation')
            Clinical = historical.get_model('inventory', 'MedicalRecordProduct')
            Invoice = historical.get_model('billing', 'Invoice')
            InvoiceItem = historical.get_model('billing', 'InvoiceItem')
            Checkout = historical.get_model('billing', 'Checkout')
            org = Org.objects.create(name='Upgrade sintético orden 4')
            owner = Owner.objects.create(organization=org, name='Titular sintético')
            pet = Pet.objects.create(organization=org, owner=owner, name='Mascota sintética')
            user = User.objects.create(organization=org, username='upgrade_order4')
            subject = snapshot(organization=org, owner=owner, pet=pet)
            record = Record.objects.create(organization=org, pet=pet, veterinarian=user, subject_snapshot=subject)
            product = Product.objects.create(organization=org, name='Producto', internal_code='UP4',
                                             base_unit='piece', stock_quantity='12', min_stock='3')
            pres = Presentation.objects.create(organization=org, product=product, name='Caja', base_unit='piece',
                                               quantity='1', conversion_factor='1.2345', stock='2',
                                               min_stock='1', sale_price='10')
            clinical = Clinical.objects.create(organization=org, medical_record=record, presentation=pres,
                                               quantity='1', conversion_factor_snapshot='2.3456')
            checkout = Checkout.objects.create(organization=org, customer=owner, pet=pet,
                                               origin='direct_sale', kind='direct_sale', subject_snapshot=subject)
            invoice = Invoice.objects.create(organization=org, owner=owner, pet=pet, checkout=checkout,
                                             status='posted', posted_at=timezone.now(), subject_snapshot=subject)
            item = InvoiceItem.objects.create(organization=org, invoice=invoice, presentation=pres,
                                              description='Sintético', quantity='1', unit_price='10',
                                              conversion_factor_snapshot='3.4567')
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            from apps.inventory.models import Product as CurrentProduct, Presentation as CurrentPresentation
            from apps.inventory.models import MedicalRecordProduct
            from apps.billing.models import InvoiceItem as CurrentInvoiceItem
            upgraded = CurrentPresentation.all_objects.get(pk=pres.pk)
            self.assertEqual(upgraded.quantity, Decimal('1.2345'))
            self.assertEqual(upgraded.conversion_factor, Decimal('1.2345'))
            self.assertEqual(upgraded.stock, Decimal('2'))
            current_product = CurrentProduct.all_objects.get(pk=product.pk)
            self.assertEqual(current_product.stock_quantity, Decimal('12'))
            self.assertEqual(current_product.min_stock, Decimal('3'))
            self.assertEqual(MedicalRecordProduct.all_objects.get(pk=clinical.pk).conversion_factor_snapshot, Decimal('2.3456'))
            self.assertEqual(CurrentInvoiceItem.all_objects.get(pk=item.pk).conversion_factor_snapshot, Decimal('3.4567'))
            import_module('apps.inventory.migrations.0029_presentation_alias_backfill').backfill_alias(
                historical, type('Schema', (), {'connection': connection})())
            upgraded.refresh_from_db()
            self.assertEqual(upgraded.quantity, Decimal('1.2345'))
        finally:
            MigrationExecutor(connection).migrate(latest)
