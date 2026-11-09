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

from apps.inventory.models import Presentation, Product, StockLot, StockMovement
from apps.inventory.services import apply_stock_movement
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

    def test_without_adjustment_the_ledger_starts_from_zero(self):
        # Todo stock entra por el libro: una entrada inicial basta para auditar el producto.
        self._set_stock('7')
        self._mv('in', '10')
        self._mv('out', '3')
        report, code = self._run()
        self.assertEqual(report['reconciled'], 1)
        self.assertEqual(report['reconciled_from_zero'], 1)
        self.assertEqual(report['no_baseline'], 0)
        self.assertEqual(report['drift_count'], 0)
        self.assertEqual(code, 0)

    def test_balance_the_ledger_does_not_explain_is_drift(self):
        # Antes salía como no_baseline y nadie lo comparaba.
        self._set_stock('50')
        self._mv('out', '5')
        report, code = self._run()
        self.assertEqual(report['no_baseline'], 0)
        self.assertEqual(report['drift_count'], 1)
        self.assertEqual(report['drift_sample'][0]['stock_esperado'], '-5.0000')
        self.assertIsNone(report['drift_sample'][0]['baseline_adjustment_pk'])
        self.assertEqual(code, 1)

    def test_stock_without_any_movement_is_drift(self):
        self._set_stock('50')
        report, code = self._run()
        self.assertEqual(report['drift_count'], 1)
        self.assertEqual(report['drift_sample'][0]['stock_esperado'], '0.0000')
        self.assertEqual(code, 1)

    def test_empty_product_reconciles(self):
        report, code = self._run()
        self.assertEqual((report['reconciled'], report['drift_count'], code), (1, 0, 0))

    def test_real_writer_keeps_a_product_reconciled(self):
        apply_stock_movement(self.presentation, Decimal('10'), 'in', self.org, reason='Stock inicial')
        apply_stock_movement(self.presentation, Decimal('4'), 'out', self.org, reason='Venta')
        report, code = self._run()
        self.assertEqual((report['reconciled_from_zero'], report['drift_count'], code), (1, 0, 0))

    def _lot(self, number):
        return StockLot.objects.create(
            organization=self.org, product=self.product, lot_number=number,
        )

    def test_lot_adjustment_moves_the_total_by_its_delta(self):
        # Un ajuste de lote fija el saldo de ESE lote, no el del producto: tomarlo como
        # baseline daba diferencia falsa (8 esperado contra 13 reales).
        lot_a, lot_b = self._lot('A'), self._lot('B')
        apply_stock_movement(self.presentation, Decimal('10'), 'in', self.org, lot=lot_a)
        apply_stock_movement(self.presentation, Decimal('5'), 'in', self.org, lot=lot_b)
        apply_stock_movement(self.presentation, Decimal('8'), 'adjustment', self.org, lot=lot_a)
        report, code = self._run()
        self.assertEqual((report['reconciled_from_zero'], report['drift_count'], code), (1, 0, 0))

    def test_lot_adjustment_after_a_product_adjustment(self):
        lot_a = self._lot('A')
        apply_stock_movement(self.presentation, Decimal('10'), 'in', self.org, lot=lot_a)
        apply_stock_movement(self.presentation, Decimal('10'), 'adjustment', self.org)
        apply_stock_movement(self.presentation, Decimal('6'), 'adjustment', self.org, lot=lot_a)
        report, code = self._run()
        self.assertEqual((report['reconciled'], report['reconciled_from_zero']), (1, 0))
        self.assertEqual((report['drift_count'], code), (0, 0))

    def test_deleted_lot_keeps_its_history_through_the_snapshot(self):
        lot_a = self._lot('A')
        apply_stock_movement(self.presentation, Decimal('10'), 'in', self.org, lot=lot_a)
        apply_stock_movement(self.presentation, Decimal('10'), 'out', self.org, lot=lot_a)
        StockLot.all_objects.filter(pk=lot_a.pk).delete()
        report, code = self._run()
        self.assertEqual((report['drift_count'], code), (0, 0))

    def test_legacy_row_is_not_reconstructible_until_a_product_adjustment(self):
        self._set_stock('50')
        self._mv('out', '5', quantity_unit='presentation')
        report, _ = self._run()
        self.assertEqual((report['no_baseline'], report['reconciled']), (1, 0))
        self._mv('adjustment', '50')
        report, code = self._run()
        self.assertEqual((report['no_baseline'], report['reconciled']), (0, 1))
        self.assertEqual((report['drift_count'], code), (0, 0))

    def test_movement_without_product_reference_is_not_reconstructible(self):
        self._set_stock('50')
        StockMovement.objects.create(
            presentation=self.presentation, organization=self.org,
            movement_type='in', quantity=Decimal('50'), quantity_unit='base',
        )
        report, code = self._run()
        self.assertEqual((report['no_baseline'], report['drift_count'], code), (1, 0, 0))

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
