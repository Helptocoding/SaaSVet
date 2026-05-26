"""
Tests del command audit_stock_integrity.

Valida la matematica de reconciliacion (adjustment como reset absoluto, deltas
posteriores, drift) sin depender de datos de prod. Movimientos creados DIRECTO
(StockMovement.objects.create), no via apply_stock_movement, para controlar de
forma independiente lo que dice el ledger vs lo que dice Presentation.stock.
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
        )

    def _presentation(self, stock):
        return Presentation.objects.create(
            product=self.product,
            name=f'Pres-{stock}',
            base_unit='unit',
            quantity=Decimal('1'),
            sale_price=Decimal('10.00'),
            stock=Decimal(stock),
            organization=self.org,
        )

    def _mv(self, presentation, movement_type, quantity):
        return StockMovement.objects.create(
            presentation=presentation,
            organization=self.org,
            movement_type=movement_type,
            quantity=Decimal(quantity),
        )

    def _run(self):
        out = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            call_command('audit_stock_integrity', '--org', str(self.org.pk), '--json', stdout=out)
        return json.loads(out.getvalue()), ctx.exception.code

    def test_no_baseline_is_not_drift(self):
        # Presentacion sin adjustment: stock de apertura no esta en el ledger.
        p = self._presentation('50.00')
        self._mv(p, 'out', '5')  # solo deltas, sin baseline
        report, code = self._run()
        self.assertEqual(report['no_baseline'], 1)
        self.assertEqual(report['reconciled'], 0)
        self.assertEqual(report['drift_count'], 0)
        self.assertEqual(code, 0)

    def test_reconciles_from_last_adjustment(self):
        # adjustment(100) -> in(10) -> out(5) = 105. stock coincide -> sin drift.
        p = self._presentation('105.00')
        self._mv(p, 'adjustment', '100')
        self._mv(p, 'in', '10')
        self._mv(p, 'out', '5')
        report, code = self._run()
        self.assertEqual(report['reconciled'], 1)
        self.assertEqual(report['no_baseline'], 0)
        self.assertEqual(report['drift_count'], 0)
        self.assertEqual(code, 0)

    def test_last_adjustment_resets_baseline(self):
        # Un adjustment posterior descarta toda la historia previa (reset absoluto).
        p = self._presentation('30.00')
        self._mv(p, 'in', '999')          # ruido pre-reset, debe ignorarse
        self._mv(p, 'adjustment', '25')   # baseline = 25
        self._mv(p, 'in', '5')            # +5 = 30
        report, code = self._run()
        self.assertEqual(report['reconciled'], 1)
        self.assertEqual(report['drift_count'], 0)
        self.assertEqual(code, 0)

    def test_detects_drift_and_exits_1(self):
        # Ledger dice 105; stock dice 99 (escritura que salto apply_stock_movement).
        p = self._presentation('99.00')
        self._mv(p, 'adjustment', '100')
        self._mv(p, 'in', '10')
        self._mv(p, 'out', '5')
        report, code = self._run()
        self.assertEqual(report['reconciled'], 1)
        self.assertEqual(report['drift_count'], 1)
        self.assertEqual(code, 1)
        row = report['drift_sample'][0]
        self.assertEqual(row['presentation_id'], p.pk)
        self.assertEqual(row['stock_actual'], '99.00')
        self.assertEqual(row['stock_esperado'], '105.00')
        self.assertEqual(row['diff'], '-6.00')
