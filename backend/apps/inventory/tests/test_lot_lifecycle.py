"""
Tests de B2c — caducidad, descarte (discard) y estado del lote (cuarentena/retiro).
"""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.inventory.models import Presentation, Product, StockLot, StockMovement
from apps.inventory.services import receive_stock
from apps.organizations.models import Organization
from apps.users.models import User


def _seed_roles(org):
    wildcard, _ = Permission.objects.get_or_create(code='*.*')
    perms_map = {c: Permission.objects.get_or_create(code=c)[0] for c in PERMISSION_CODES}
    roles = {}
    for name, codes in PERMISSIONS.items():
        if name == 'ADMIN_SAAS':
            continue
        role, _ = Role.objects.get_or_create(
            name=name, organization=org, defaults={'is_system_role': True})
        role.permissions.set(
            [wildcard] if '*.*' in codes
            else [perms_map[c] for c in codes if c in perms_map])
        roles[name] = role
    return roles


class LotLifecycleMixin:
    def setUp(self):
        self.org = Organization.objects.create(name='Org LC', timezone='UTC', tax_rate=Decimal('0'))
        self.roles = _seed_roles(self.org)
        self.admin = User.objects.create_user(
            username='adm_lc', password='pass1234!', organization=self.org, role='ADMIN')
        UserRole.objects.get_or_create(user=self.admin, role=self.roles['ADMIN'])
        self.product = Product.objects.create(
            name='Vacuna Rabia', internal_code='V-LC', organization=self.org,
            base_unit='vial', tracks_lots=True, manufacturer='Zoetis')
        self.presentation = Presentation.objects.create(
            product=self.product, name='Vial', base_unit='vial', quantity=Decimal('1'),
            conversion_factor=Decimal('1'), sale_price=Decimal('120.00'),
            stock=Decimal('0'), organization=self.org)
        self.today = timezone.localdate()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _receive(self, lot_number, days, qty):
        with transaction.atomic():
            receive_stock(
                self.presentation,
                lots=[{'lot_number': lot_number, 'expiry_date': self.today + timedelta(days=days), 'quantity': Decimal(str(qty))}],
                organization=self.org, created_by=self.admin)
        return StockLot.objects.get(product=self.product, lot_number=lot_number)

    def _discard_url(self, lot):
        return f'/api/inventory/lots/{lot.public_id}/discard/'

    def _status_url(self, lot):
        return f'/api/inventory/lots/{lot.public_id}/status/'


class DiscardTests(LotLifecycleMixin, TestCase):
    def test_discard_partial(self):
        lot = self._receive('L1', 400, 10)
        resp = self.client.post(self._discard_url(lot), {'quantity': '4', 'reason': 'Rotura'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        lot.refresh_from_db(); self.product.refresh_from_db()
        self.assertEqual(lot.quantity_on_hand, Decimal('6'))
        self.assertEqual(self.product.stock_quantity, Decimal('6'))
        self.assertTrue(StockMovement.objects.filter(lot=lot, movement_type='out').exists())

    def test_discard_all_default(self):
        lot = self._receive('L2', 400, 5)
        resp = self.client.post(self._discard_url(lot), {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        lot.refresh_from_db()
        self.assertEqual(lot.quantity_on_hand, Decimal('0'))
        self.assertEqual(lot.effective_status, StockLot.EFFECTIVE_CONSUMED)

    def test_discard_over_saldo_rejected(self):
        lot = self._receive('L3', 400, 3)
        resp = self.client.post(self._discard_url(lot), {'quantity': '10'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_discard_works_on_expired_lot(self):
        lot = self._receive('EXP', -5, 5)  # vencido
        resp = self.client.post(self._discard_url(lot), {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        lot.refresh_from_db()
        self.assertEqual(lot.quantity_on_hand, Decimal('0'))


class LotStatusTests(LotLifecycleMixin, TestCase):
    def test_quarantine(self):
        lot = self._receive('Q1', 400, 5)
        resp = self.client.post(self._status_url(lot), {'status': 'quarantined'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        lot.refresh_from_db()
        self.assertEqual(lot.status, StockLot.STATUS_QUARANTINED)
        self.assertEqual(lot.effective_status, StockLot.EFFECTIVE_QUARANTINED)
        self.assertFalse(lot.is_consumable)

    def test_recall_then_reactivate(self):
        lot = self._receive('R1', 400, 5)
        self.client.post(self._status_url(lot), {'status': 'recalled'}, format='json')
        lot.refresh_from_db()
        self.assertEqual(lot.effective_status, StockLot.EFFECTIVE_RECALLED)
        self.client.post(self._status_url(lot), {'status': 'active'}, format='json')
        lot.refresh_from_db()
        self.assertTrue(lot.is_consumable)

    def test_invalid_status_rejected(self):
        lot = self._receive('R2', 400, 5)
        resp = self.client.post(self._status_url(lot), {'status': 'destroyed'}, format='json')
        self.assertEqual(resp.status_code, 400)


class LotAlertsTests(LotLifecycleMixin, TestCase):
    def test_expiring_and_expired_partitioned(self):
        near = self._receive('NEAR', 10, 5)     # vence dentro de 30 días
        self._receive('FAR', 400, 5)            # no vence pronto
        expired = self._receive('EXP', -5, 5)   # vencido con saldo

        resp = self.client.get('/api/inventory/lots/alerts/?days=30')
        self.assertEqual(resp.status_code, 200)
        expiring_ids = {r['lot_number'] for r in resp.data['expiring_soon']}
        expired_ids = {r['lot_number'] for r in resp.data['expired_with_stock']}
        self.assertIn('NEAR', expiring_ids)
        self.assertNotIn('FAR', expiring_ids)
        self.assertNotIn('EXP', expiring_ids)
        self.assertIn('EXP', expired_ids)

    def test_quarantined_excluded_from_alerts(self):
        near = self._receive('QN', 10, 5)
        self.client.post(self._status_url(near), {'status': 'quarantined'}, format='json')
        resp = self.client.get('/api/inventory/lots/alerts/?days=30')
        expiring_ids = {r['lot_number'] for r in resp.data['expiring_soon']}
        self.assertNotIn('QN', expiring_ids)
