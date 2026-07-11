"""
Tests de B2a — consumo por lote en la consulta (MedicalRecordProduct).

MRP.save/delete rutean por consume_product/restock_product sobre MRP.lot:
  - lote obligatorio y consumible si tracks_lots (P1/P2)
  - descuenta el lote elegido; delete revierte al MISMO lote (P4)
  - producto sin tracks_lots: lote prohibido; path histórico intacto (regresión)
"""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.inventory.models import MedicalRecordProduct, Presentation, Product, StockLot
from apps.inventory.services import receive_stock
from apps.medical_records.models import MedicalRecord
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
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


class ConsultLotSetupMixin:
    def setUp(self):
        self.org = Organization.objects.create(
            name='Org ConsultLot', timezone='UTC', tax_rate=Decimal('0'))
        self.roles = _seed_roles(self.org)
        self.admin = User.objects.create_user(
            username='admin_cl', password='pass1234!', organization=self.org, role='ADMIN')
        UserRole.objects.get_or_create(user=self.admin, role=self.roles['ADMIN'])
        self.owner = Owner.objects.create(name='Dueño CL', phone='5550000009', organization=self.org)
        self.pet = Pet.objects.create(name='Firulais', species='dog', owner=self.owner, organization=self.org)
        self.mr = MedicalRecord.objects.create(pet=self.pet, veterinarian=self.admin, organization=self.org)

        self.product = Product.objects.create(
            name='Vacuna Rabia', internal_code='VAC-CL', organization=self.org,
            base_unit='vial', tracks_lots=True, manufacturer='Zoetis')
        self.presentation = Presentation.objects.create(
            product=self.product, name='Vial', base_unit='vial', quantity=Decimal('1'),
            conversion_factor=Decimal('1'), sale_price=Decimal('120.00'),
            stock=Decimal('0'), organization=self.org)
        today = timezone.localdate()
        with transaction.atomic():
            receive_stock(
                self.presentation,
                lots=[
                    {'lot_number': 'NEAR', 'expiry_date': today + timedelta(days=30), 'quantity': Decimal('10')},
                    {'lot_number': 'FAR', 'expiry_date': today + timedelta(days=400), 'quantity': Decimal('10')},
                ],
                organization=self.org, created_by=self.admin)
        self.near = StockLot.objects.get(product=self.product, lot_number='NEAR')
        self.far = StockLot.objects.get(product=self.product, lot_number='FAR')

        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _url(self):
        return f'/api/medical-records/{self.mr.public_id}/products/'


class ConsultLotConsumeTests(ConsultLotSetupMixin, TestCase):
    def test_add_with_lot_decrements_that_lot(self):
        resp = self.client.post(self._url(), {
            'presentation': self.presentation.pk, 'quantity': '2',
            'cost_behavior': 'included', 'lot': self.far.pk,
        })
        self.assertEqual(resp.status_code, 201, resp.data)
        self.far.refresh_from_db(); self.near.refresh_from_db(); self.product.refresh_from_db()
        self.assertEqual(self.far.quantity_on_hand, Decimal('8'))
        self.assertEqual(self.near.quantity_on_hand, Decimal('10'))
        self.assertEqual(self.product.stock_quantity, Decimal('18'))
        mrp = MedicalRecordProduct.objects.get(medical_record=self.mr, presentation=self.presentation)
        self.assertEqual(mrp.lot_id, self.far.pk)

    def test_lot_required_for_tracked_product(self):
        resp = self.client.post(self._url(), {
            'presentation': self.presentation.pk, 'quantity': '1', 'cost_behavior': 'included',
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn('lot', resp.data.get('errors', resp.data))

    def test_blocked_lot_rejected(self):
        self.near.status = StockLot.STATUS_RECALLED
        self.near.save()
        resp = self.client.post(self._url(), {
            'presentation': self.presentation.pk, 'quantity': '1',
            'cost_behavior': 'included', 'lot': self.near.pk,
        })
        self.assertEqual(resp.status_code, 400)

    def test_delete_reverts_to_same_lot(self):
        resp = self.client.post(self._url(), {
            'presentation': self.presentation.pk, 'quantity': '3',
            'cost_behavior': 'included', 'lot': self.far.pk,
        })
        self.assertEqual(resp.status_code, 201, resp.data)
        mrp_id = MedicalRecordProduct.objects.get(
            medical_record=self.mr, presentation=self.presentation).pk
        self.far.refresh_from_db()
        self.assertEqual(self.far.quantity_on_hand, Decimal('7'))

        self.client.delete(f'{self._url()}{mrp_id}/')
        self.far.refresh_from_db()
        self.assertEqual(self.far.quantity_on_hand, Decimal('10'))  # reverso al mismo lote

    def test_non_lot_product_rejects_lot(self):
        plain = Product.objects.create(
            name='Gasa', internal_code='GA-CL', organization=self.org,
            base_unit='piece', tracks_lots=False)
        pres = Presentation.objects.create(
            product=plain, name='Pieza', base_unit='piece', quantity=Decimal('1'),
            conversion_factor=Decimal('1'), sale_price=Decimal('5'), stock=Decimal('50'),
            organization=self.org)
        Product.all_objects.filter(pk=plain.pk).update(stock_quantity=Decimal('50'))
        resp = self.client.post(self._url(), {
            'presentation': pres.pk, 'quantity': '1',
            'cost_behavior': 'included', 'lot': self.far.pk,
        })
        self.assertEqual(resp.status_code, 400)
