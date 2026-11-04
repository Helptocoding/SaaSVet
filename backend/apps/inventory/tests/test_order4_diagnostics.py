from decimal import Decimal

from django.test import TestCase

from apps.inventory.models import Product, Presentation, StockLot, StockMovement
from apps.inventory.stock_diagnostics import diagnose_product, compare_proposal
from apps.organizations.models import Organization


class StockDiagnosticTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Synthetic')
        self.product = Product.objects.create(organization=self.org, name='Test', internal_code='T',
                                              base_unit='piece', stock_quantity=Decimal('5'))
        self.pres = Presentation.objects.create(organization=self.org, product=self.product,
                                                 name='Test', base_unit='piece', sale_price=10)

    def move(self, kind, quantity, **kwargs):
        return StockMovement.objects.create(organization=self.org, product=self.product,
                                            presentation=self.pres, movement_type=kind,
                                            quantity=quantity, quantity_unit='base', **kwargs)

    def test_initial_in_is_not_a_baseline_and_diagnostic_is_read_only(self):
        self.move('in', 5)
        before = list(StockMovement.all_objects.values())
        first = diagnose_product(self.product)
        self.assertEqual(first['coverage'], 'no_baseline')
        self.assertIsNone(first['approval'])
        self.assertEqual(first, diagnose_product(self.product))
        self.assertEqual(before, list(StockMovement.all_objects.values()))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 5)

    def test_lot_adjustment_is_not_an_absolute_product_baseline(self):
        self.product.tracks_lots = True
        self.product.save(update_fields=['tracks_lots'])
        lot = StockLot.objects.create(organization=self.org, product=self.product,
                                      lot_number='synthetic', quantity_on_hand=5)
        self.move('adjustment', 5, lot=lot)
        report = diagnose_product(self.product)
        self.assertEqual(report['coverage'], 'no_baseline')
        self.assertIn('lot_adjustment_delta_unverifiable', report['ambiguities'])
        self.move('adjustment', 5)
        report = diagnose_product(self.product)
        self.assertEqual(report['coverage'], 'absolute_product_baseline')
        self.move('adjustment', 2, lot=lot)
        report = diagnose_product(self.product)
        self.assertEqual(report['coverage'], 'unverifiable')
        self.assertIsNone(report['expected_from_baseline'])

    def test_deleted_lot_snapshot_does_not_become_product_baseline(self):
        self.product.tracks_lots = True
        self.product.save(update_fields=['tracks_lots'])
        lot = StockLot.objects.create(organization=self.org, product=self.product,
                                      lot_number='synthetic-deleted', quantity_on_hand=5)
        movement = self.move('adjustment', 5, lot=lot, lot_number=lot.lot_number)
        original = diagnose_product(self.product)
        lot.delete()
        movement.refresh_from_db()
        self.assertIsNone(movement.lot_id)
        self.assertEqual(movement.lot_number, 'synthetic-deleted')
        before = list(StockMovement.all_objects.values())
        report = diagnose_product(self.product)
        self.assertEqual(report['coverage'], 'no_baseline')
        self.assertIsNone(report['expected_from_baseline'])
        self.assertIn('lot_adjustment_delta_unverifiable', report['ambiguities'])
        self.assertNotEqual(original['ledger_watermark_sha256'], report['ledger_watermark_sha256'])
        self.assertEqual(before, list(StockMovement.all_objects.values()))
        self.assertEqual(report, diagnose_product(self.product))
        self.assertIsNone(report['approval'])
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 5)

    def test_legacy_reference_and_lot_mismatch_remain_ambiguous(self):
        self.product.tracks_lots = True
        self.product.save(update_fields=['tracks_lots'])
        self.move('adjustment', 5)
        legacy = self.move('in', 1)
        StockMovement.all_objects.filter(pk=legacy.pk).update(product=None, quantity_unit='presentation')
        before = list(StockMovement.all_objects.values())
        report = diagnose_product(self.product)
        self.assertEqual(report['coverage'], 'unverifiable')
        self.assertIn('missing_product_reference', report['ambiguities'])
        self.assertIn('lot_balance_mismatch', report['ambiguities'])
        self.assertIsNone(report['expected_from_baseline'])
        self.assertEqual(before, list(StockMovement.all_objects.values()))

    def test_changed_ledger_changes_watermark_without_approval(self):
        self.move('adjustment', 5)
        first = diagnose_product(self.product)
        self.assertEqual(first['coverage'], 'absolute_product_baseline')
        self.move('in', 1)
        second = diagnose_product(self.product)
        self.assertNotEqual(first['ledger_watermark_sha256'], second['ledger_watermark_sha256'])
        self.assertEqual(second['expected_from_baseline'], '6.0000')
        self.assertIsNone(second['approval'])

    def test_legacy_units_after_baseline_are_unverifiable(self):
        self.move('adjustment', 5)
        legacy = self.move('in', 1)
        StockMovement.all_objects.filter(pk=legacy.pk).update(quantity_unit='presentation')
        report = diagnose_product(self.product)
        self.assertEqual(report['coverage'], 'unverifiable')
        self.assertIn('legacy_or_mixed_units', report['ambiguities'])
        self.assertIsNone(report['expected_from_baseline'])

    def test_proposal_requires_review_when_evidence_changes_or_is_ambiguous(self):
        self.move('adjustment', 5)
        prepared = diagnose_product(self.product)
        self.assertFalse(compare_proposal(prepared, diagnose_product(self.product))['requires_new_review'])
        for field, value in (('observed_balance', '9'), ('base_unit', 'ml'),
                             ('ledger_watermark_sha256', 'changed'),
                             ('organization_public_id', 'other'),
                             ('lot_total', '3'), ('coverage', 'unverifiable')):
            with self.subTest(field=field):
                observed = {**prepared, field: value}
                comparison = compare_proposal(prepared, observed)
                self.assertTrue(comparison['requires_new_review'])
                self.assertIn(field, comparison['changed_fields'])
                self.assertIsNone(comparison['approval'])
        ambiguous = {**prepared, 'ambiguities': ['lot_adjustment_delta_unverifiable']}
        self.assertTrue(compare_proposal(ambiguous, ambiguous)['requires_new_review'])
        self.assertTrue(compare_proposal({}, {})['requires_new_review'])
