"""
Tests del command audit_stock_integrity (ADR p31).

Valida la matemática de reconciliación a nivel de Product.stock_quantity.
Los movimientos se crean DIRECTO (StockMovement.objects.create) con
quantity_unit='base' y product=product, para controlar de forma independiente
lo que dice el ledger vs lo que dice Product.stock_quantity.
"""
import json
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.inventory.models import Presentation, Product, StockMovement
from apps.organizations.models import Organization
from apps.patients.models import Owner  # noqa: F401  (asegura apps cargadas)


class AuditStockIntegrityTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Org Audit', timezone='UTC')
        self.product = Product.objects.create(
            name='Producto Audit', internal_code='AUD-1', organization=self.org,
            base_unit='unit',
        )
        self.presentation = Presentation.objects.create(
            product=self.product,
            name='Pres-Audit',
            base_unit='unit',
            quantity=Decimal('1'),
            sale_price=Decimal('10.00'),
            stock=Decimal('0'),
            organization=self.org,
        )

    def _set_stock(self, quantity):
        self.product.stock_quantity = Decimal(quantity)
        self.product.save()

    def _mv(self, movement_type, quantity, quantity_unit='base'):
        return StockMovement.objects.create(
            presentation=self.presentation,
            product=self.product,
            organization=self.org,
            movement_type=movement_type,
            quantity=Decimal(quantity),
            quantity_unit=quantity_unit,
        )

    def _run(self):
        out = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            call_command('audit_stock_integrity', '--org', str(self.org.pk), '--json', stdout=out)
        return json.loads(out.getvalue()), ctx.exception.code

    def test_no_baseline_is_not_drift(self):
        # Producto sin adjustment base: no hay baseline en el ledger.
        self._set_stock('50')
        self._mv('out', '5')  # solo deltas, sin baseline
        report, code = self._run()
        self.assertEqual(report['no_baseline'], 1)
        self.assertEqual(report['reconciled'], 0)
        self.assertEqual(report['drift_count'], 0)
        self.assertEqual(code, 0)

    def test_reconciles_from_last_adjustment(self):
        # adjustment(100) -> in(10) -> out(5) = 105. stock coincide -> sin drift.
        self._set_stock('105')
        self._mv('adjustment', '100')
        self._mv('in', '10')
        self._mv('out', '5')
        report, code = self._run()
        self.assertEqual(report['reconciled'], 1)
        self.assertEqual(report['no_baseline'], 0)
        self.assertEqual(report['drift_count'], 0)
        self.assertEqual(code, 0)

    def test_last_adjustment_resets_baseline(self):
        # Un adjustment posterior descarta toda la historia previa (reset absoluto).
        self._set_stock('30')
        self._mv('in', '999')          # ruido pre-reset, debe ignorarse
        self._mv('adjustment', '25')   # baseline = 25
        self._mv('in', '5')            # +5 = 30
        report, code = self._run()
        self.assertEqual(report['reconciled'], 1)
        self.assertEqual(report['drift_count'], 0)
        self.assertEqual(code, 0)

    def test_detects_drift_and_exits_1(self):
        # Ledger dice 105; stock dice 99 (escritura que saltó apply_stock_movement).
        self._set_stock('99')
        self._mv('adjustment', '100')
        self._mv('in', '10')
        self._mv('out', '5')
        report, code = self._run()
        self.assertEqual(report['reconciled'], 1)
        self.assertEqual(report['drift_count'], 1)
        self.assertEqual(code, 1)
        row = report['drift_sample'][0]
        self.assertEqual(row['product_id'], self.product.pk)
        self.assertEqual(row['stock_actual'], '99.0000')
        self.assertEqual(row['stock_esperado'], '105.0000')

    def test_legacy_movements_ignored(self):
        # Movimientos con quantity_unit='presentation' no cuentan para el audit.
        self._set_stock('50')
        self._mv('adjustment', '50', quantity_unit='presentation')  # legacy
        self._mv('out', '5', quantity_unit='presentation')          # legacy
        report, code = self._run()
        # Sin baseline base → no_baseline, no drift
        self.assertEqual(report['no_baseline'], 1)
        self.assertEqual(report['drift_count'], 0)
        self.assertEqual(code, 0)

    def test_json_output_structure(self):
        self._set_stock('20')
        self._mv('adjustment', '20')
        report, _ = self._run()
        required_keys = {
            'checked_products', 'reconciled', 'no_baseline',
            'drift_count', 'drift_sample', 'exit_code',
        }
        self.assertTrue(required_keys.issubset(report.keys()))
