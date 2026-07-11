"""
Tests A2 — la consulta de Vacuna ligada a inventario consume el lote y materializa.

Al finalizar: descuenta 1 dosis del lote (auto-alta de MedicalRecordProduct qty=1,
modo = product.default_cost_behavior) y crea VaccineRecord con product+lot+snapshot.
"""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.models import Invoice, InvoiceItem
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.inventory.models import MedicalRecordProduct, Presentation, Product, StockLot
from apps.inventory.services import receive_stock
from apps.medical_records.models import MedicalRecord, VaccineRecord
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


class VaccineLotMaterializationTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Org VacLot', timezone='UTC', tax_rate=Decimal('0'))
        self.roles = _seed_roles(self.org)
        self.admin = User.objects.create_user(
            username='adm_vl', password='pass1234!', organization=self.org, role='ADMIN')
        UserRole.objects.get_or_create(user=self.admin, role=self.roles['ADMIN'])
        self.owner = Owner.objects.create(name='Dueño VL', phone='5550000020', organization=self.org)
        self.pet = Pet.objects.create(name='Luna', species='dog', owner=self.owner, organization=self.org)
        self.product = Product.objects.create(
            name='Vacuna Rabia', internal_code='VAC-VL', organization=self.org,
            base_unit='vial', tracks_lots=True, manufacturer='Zoetis',
            default_cost_behavior='charge')
        self.presentation = Presentation.objects.create(
            product=self.product, name='Vial', base_unit='vial', quantity=Decimal('1'),
            conversion_factor=Decimal('1'), sale_price=Decimal('150.00'),
            stock=Decimal('0'), organization=self.org)
        today = timezone.localdate()
        with transaction.atomic():
            receive_stock(
                self.presentation,
                lots=[{'lot_number': 'L-VAC', 'expiry_date': today + timedelta(days=400), 'quantity': Decimal('10')}],
                organization=self.org, created_by=self.admin)
        self.lot = StockLot.objects.get(product=self.product, lot_number='L-VAC')

        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _make_vaccine_mr(self, draft_extra=None):
        vaccine_draft = {
            'vaccine_name': 'Rabia',
            'application_date': str(timezone.localdate()),
            'scheduleBooster': False,
            'next_due_date': None,
            'notes': '',
            'product_id': self.product.id,
            'product_tracks_lots': True,
            'lot_id': self.lot.id,
        }
        if draft_extra:
            vaccine_draft.update(draft_extra)
        return MedicalRecord.objects.create(
            pet=self.pet, veterinarian=self.admin, organization=self.org,
            consultation_type='vaccine', diagnosis='Vacunación anual',
            consultation_draft={'vaccine': vaccine_draft})

    def _close(self, mr):
        return self.client.post(f'/api/medical-records/{mr.public_id}/close/')

    def test_close_consumes_lot_and_materializes(self):
        mr = self._make_vaccine_mr()
        resp = self._close(mr)
        self.assertEqual(resp.status_code, 200, resp.data)

        self.lot.refresh_from_db(); self.product.refresh_from_db()
        self.assertEqual(self.lot.quantity_on_hand, Decimal('9'))       # 1 dosis consumida
        self.assertEqual(self.product.stock_quantity, Decimal('9'))

        vr = VaccineRecord.objects.get(medical_record=mr)
        self.assertEqual(vr.product_id, self.product.id)
        self.assertEqual(vr.lot_id, self.lot.id)
        self.assertEqual(vr.lot_number, 'L-VAC')                        # snapshot
        self.assertEqual(vr.manufacturer, 'Zoetis')
        self.assertIsNotNone(vr.lot_expiry)

        mrp = MedicalRecordProduct.objects.get(medical_record=mr, presentation=self.presentation)
        self.assertEqual(mrp.quantity, Decimal('1'))
        self.assertEqual(mrp.lot_id, self.lot.id)
        self.assertEqual(mrp.cost_behavior, 'charge')                   # de default_cost_behavior

        # charge → línea de cobro creada
        invoice = Invoice.objects.get(medical_record=mr)
        self.assertTrue(InvoiceItem.objects.filter(
            invoice=invoice, presentation=self.presentation, is_active=True).exists())

    def test_included_default_does_not_bill(self):
        Product.objects.filter(pk=self.product.pk).update(default_cost_behavior='included')
        mr = self._make_vaccine_mr()
        resp = self._close(mr)
        self.assertEqual(resp.status_code, 200, resp.data)

        mrp = MedicalRecordProduct.objects.get(medical_record=mr, presentation=self.presentation)
        self.assertEqual(mrp.cost_behavior, 'included')
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.quantity_on_hand, Decimal('9'))       # consume igual
        invoice = Invoice.objects.filter(medical_record=mr).first()
        if invoice:
            self.assertFalse(InvoiceItem.objects.filter(
                invoice=invoice, presentation=self.presentation, is_active=True).exists())

    def test_missing_lot_blocks_close(self):
        mr = self._make_vaccine_mr({'lot_id': None})
        resp = self._close(mr)
        self.assertEqual(resp.status_code, 400)
        # rollback: no se materializó ni consumió
        self.assertFalse(VaccineRecord.objects.filter(medical_record=mr).exists())
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.quantity_on_hand, Decimal('10'))

    def test_free_text_vaccine_still_works(self):
        # Sin product_id → texto libre, sin consumo de inventario (fallback).
        mr = self._make_vaccine_mr({'product_id': None, 'product_tracks_lots': False, 'lot_id': None})
        resp = self._close(mr)
        self.assertEqual(resp.status_code, 200, resp.data)
        vr = VaccineRecord.objects.get(medical_record=mr)
        self.assertIsNone(vr.product_id)
        self.assertEqual(vr.lot_number, '')
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.quantity_on_hand, Decimal('10'))      # sin consumo
