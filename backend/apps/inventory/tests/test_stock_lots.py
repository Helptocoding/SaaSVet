"""
Tests de B0 — núcleo de trazabilidad por lote (StockLot).

Cubre el servicio de consumo (spec inventario 2026-07-10):
  - resolve_consumption_lots  → política FEFO (P1), reparto, exclusiones, insuficiencia (P2)
  - consume_product           → única entrada; tracks_lots=False sin cambio (regresión)
  - apply_stock_movement      → lot-aware, guard de saldo por lote
  - StockLot.effective_status → precedencia BINDING
  - invariante Σ lotes == Product.stock_quantity

NO se re-rutean callers en B0 (eso es B2); estos tests ejercen los servicios directo.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.test import TestCase
from django.utils import timezone

from apps.inventory.models import Presentation, Product, StockLot, StockMovement
from apps.inventory.services import (
    apply_stock_movement,
    consume_product,
    resolve_consumption_lots,
    restock_product,
)
from apps.organizations.models import Organization


class LotSetupMixin:
    def setUp(self):
        self.org = Organization.objects.create(
            name='Org Lotes', timezone='UTC', tax_rate=Decimal('0'),
        )
        self.today = timezone.localdate()
        self.product = Product.objects.create(
            name='Vacuna Rabia', internal_code='VAC-001',
            organization=self.org, base_unit='vial',
            tracks_lots=True, manufacturer='Zoetis',
        )
        self.presentation = Presentation.objects.create(
            product=self.product, name='Vial', base_unit='vial',
            quantity=Decimal('1'), conversion_factor=Decimal('1'),
            sale_price=Decimal('120.00'), stock=Decimal('0'),
            organization=self.org,
        )
        self._lot_seq = 0

    def make_lot(self, qty, days_to_expiry=365, status=StockLot.STATUS_ACTIVE, lot_number=None):
        self._lot_seq += 1
        expiry = None if days_to_expiry is None else self.today + timedelta(days=days_to_expiry)
        lot = StockLot.objects.create(
            product=self.product, organization=self.org,
            lot_number=lot_number or f'L{self._lot_seq:03d}',
            expiry_date=expiry, quantity_on_hand=Decimal(str(qty)), status=status,
        )
        # Mantener el agregado del producto = Σ lotes (todos, incluso vencidos: son
        # existencia física real). También el dual-write legacy Presentation.stock
        # (cf=1) — en producción se sincroniza vía apply_stock_movement('in') en la
        # recepción; aquí los lotes se crean directo, así que se espeja a mano.
        Product.all_objects.filter(pk=self.product.pk).update(
            stock_quantity=F('stock_quantity') + Decimal(str(qty))
        )
        Presentation.all_objects.filter(pk=self.presentation.pk).update(
            stock=F('stock') + Decimal(str(qty))
        )
        self.product.refresh_from_db()
        return lot


class ResolveFefoTests(LotSetupMixin, TestCase):
    def test_single_eligible_lot_auto(self):
        lot = self.make_lot(10)
        allocs = resolve_consumption_lots(self.product, Decimal('4'))
        self.assertEqual(len(allocs), 1)
        self.assertEqual(allocs[0][0].pk, lot.pk)
        self.assertEqual(allocs[0][1], Decimal('4'))

    def test_picks_earliest_expiry_first(self):
        far = self.make_lot(10, days_to_expiry=400, lot_number='FAR')
        near = self.make_lot(10, days_to_expiry=30, lot_number='NEAR')
        allocs = resolve_consumption_lots(self.product, Decimal('5'))
        self.assertEqual(len(allocs), 1)
        self.assertEqual(allocs[0][0].pk, near.pk)
        self.assertNotEqual(allocs[0][0].pk, far.pk)

    def test_splits_across_lots_fefo(self):
        near = self.make_lot(3, days_to_expiry=30, lot_number='NEAR')
        far = self.make_lot(10, days_to_expiry=400, lot_number='FAR')
        allocs = resolve_consumption_lots(self.product, Decimal('5'))
        self.assertEqual(len(allocs), 2)
        self.assertEqual((allocs[0][0].pk, allocs[0][1]), (near.pk, Decimal('3')))
        self.assertEqual((allocs[1][0].pk, allocs[1][1]), (far.pk, Decimal('2')))

    def test_excludes_expired_quarantined_recalled_zero(self):
        self.make_lot(5, days_to_expiry=-1, lot_number='EXPIRED')
        self.make_lot(5, status=StockLot.STATUS_QUARANTINED, lot_number='QUAR')
        self.make_lot(5, status=StockLot.STATUS_RECALLED, lot_number='RECALL')
        self.make_lot(0, lot_number='ZERO')
        good = self.make_lot(5, lot_number='GOOD')
        allocs = resolve_consumption_lots(self.product, Decimal('5'))
        self.assertEqual(len(allocs), 1)
        self.assertEqual(allocs[0][0].pk, good.pk)

    def test_raises_when_no_eligible_lot(self):
        self.make_lot(5, days_to_expiry=-1, lot_number='EXPIRED')
        with self.assertRaises(ValidationError):
            resolve_consumption_lots(self.product, Decimal('1'))

    def test_raises_when_insufficient(self):
        self.make_lot(5)
        with self.assertRaises(ValidationError):
            resolve_consumption_lots(self.product, Decimal('10'))


class ConsumeProductTests(LotSetupMixin, TestCase):
    def test_tracks_lots_decrements_lot_and_product(self):
        lot = self.make_lot(10)
        with transaction.atomic():
            consume_product(self.presentation, Decimal('4'), self.org, reason='consulta')
        lot.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(lot.quantity_on_hand, Decimal('6'))
        self.assertEqual(self.product.stock_quantity, Decimal('6'))
        mov = StockMovement.objects.get(product=self.product, movement_type='out')
        self.assertEqual(mov.lot_id, lot.pk)
        self.assertEqual(mov.lot_number, lot.lot_number)  # snapshot denormalizado

    def test_split_creates_two_movements(self):
        self.make_lot(3, days_to_expiry=30, lot_number='NEAR')
        self.make_lot(10, days_to_expiry=400, lot_number='FAR')
        with transaction.atomic():
            consume_product(self.presentation, Decimal('5'), self.org)
        movs = StockMovement.objects.filter(product=self.product, movement_type='out')
        self.assertEqual(movs.count(), 2)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('8'))  # 13 - 5

    def test_explicit_override_uses_given_lot(self):
        near = self.make_lot(10, days_to_expiry=30, lot_number='NEAR')
        far = self.make_lot(10, days_to_expiry=400, lot_number='FAR')
        with transaction.atomic():
            consume_product(self.presentation, Decimal('2'), self.org, lot=far)
        far.refresh_from_db()
        near.refresh_from_db()
        self.assertEqual(far.quantity_on_hand, Decimal('8'))   # override respetado (P3)
        self.assertEqual(near.quantity_on_hand, Decimal('10'))  # FEFO no tocó este

    def test_blocked_lot_rejected_without_force(self):
        expired = self.make_lot(10, days_to_expiry=-1, lot_number='EXP')
        with self.assertRaises(ValidationError):
            with transaction.atomic():
                consume_product(self.presentation, Decimal('1'), self.org, lot=expired)

    def test_blocked_lot_allowed_with_force(self):
        expired = self.make_lot(10, days_to_expiry=-1, lot_number='EXP')
        with transaction.atomic():
            consume_product(self.presentation, Decimal('1'), self.org, lot=expired, force=True)
        expired.refresh_from_db()
        self.assertEqual(expired.quantity_on_hand, Decimal('9'))

    def test_apply_out_lot_insufficient_raises(self):
        lot = self.make_lot(2)
        # Product tiene 2; pedir 3 del lote → guard de lote dispara.
        with self.assertRaises(ValidationError):
            with transaction.atomic():
                apply_stock_movement(
                    self.presentation, Decimal('3'), 'out', self.org, lot=lot,
                )

    def test_restock_returns_to_lot(self):
        lot = self.make_lot(10)
        with transaction.atomic():
            consume_product(self.presentation, Decimal('4'), self.org)
            restock_product(self.presentation, Decimal('4'), self.org, lot=lot)
        lot.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(lot.quantity_on_hand, Decimal('10'))  # reverso al lote original (P4)
        self.assertEqual(self.product.stock_quantity, Decimal('10'))

    def test_invariant_sum_lots_equals_product(self):
        self.make_lot(3, days_to_expiry=30, lot_number='NEAR')
        self.make_lot(10, days_to_expiry=400, lot_number='FAR')
        with transaction.atomic():
            consume_product(self.presentation, Decimal('5'), self.org)
        self.product.refresh_from_db()
        total = sum(
            l.quantity_on_hand for l in StockLot.objects.for_organization(self.org)
        )
        self.assertEqual(total, self.product.stock_quantity)


class NoLotRegressionTests(TestCase):
    """tracks_lots=False → consume_product recorre el path histórico (lot=None)."""

    def setUp(self):
        self.org = Organization.objects.create(
            name='Org NoLot', timezone='UTC', tax_rate=Decimal('0'),
        )
        self.product = Product.objects.create(
            name='Shampoo', internal_code='SH-001', organization=self.org,
            base_unit='piece', tracks_lots=False,
        )
        self.presentation = Presentation.objects.create(
            product=self.product, name='Pieza', base_unit='piece',
            quantity=Decimal('1'), conversion_factor=Decimal('1'),
            sale_price=Decimal('50.00'), stock=Decimal('100'), organization=self.org,
        )
        Product.all_objects.filter(pk=self.product.pk).update(stock_quantity=Decimal('100'))
        self.product.refresh_from_db()

    def test_consume_without_lots_decrements_product_lot_null(self):
        with transaction.atomic():
            consume_product(self.presentation, Decimal('7'), self.org)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('93'))
        mov = StockMovement.objects.get(product=self.product, movement_type='out')
        self.assertIsNone(mov.lot_id)
        self.assertEqual(mov.lot_number, '')
        self.assertFalse(StockLot.objects.filter(product=self.product).exists())


class EffectiveStatusTests(LotSetupMixin, TestCase):
    def test_precedence_recalled_over_expired(self):
        lot = self.make_lot(5, days_to_expiry=-1, status=StockLot.STATUS_RECALLED)
        self.assertEqual(lot.effective_status, StockLot.EFFECTIVE_RECALLED)

    def test_precedence_quarantined_over_expired(self):
        lot = self.make_lot(5, days_to_expiry=-1, status=StockLot.STATUS_QUARANTINED)
        self.assertEqual(lot.effective_status, StockLot.EFFECTIVE_QUARANTINED)

    def test_expired_when_active_and_past_date(self):
        lot = self.make_lot(5, days_to_expiry=-1)
        self.assertEqual(lot.effective_status, StockLot.EFFECTIVE_EXPIRED)

    def test_consumed_when_zero_qty(self):
        lot = self.make_lot(0)
        self.assertEqual(lot.effective_status, StockLot.EFFECTIVE_CONSUMED)

    def test_active_when_stocked_and_fresh(self):
        lot = self.make_lot(5, days_to_expiry=365)
        self.assertEqual(lot.effective_status, StockLot.EFFECTIVE_ACTIVE)
        self.assertTrue(lot.is_consumable)
