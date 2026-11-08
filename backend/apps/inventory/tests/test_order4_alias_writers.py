"""Orden 4, I02: cada writer de producción deja el alias `quantity` igual al factor.

Complementa test_order4_alias.py (serializer, backfill y admin) recorriendo los writers por
su entrada real y releyendo el par desde PostgreSQL: alta de producto, edición anidada desde
el producto, alta y edición de presentación, importación y seed de demo.
"""
from decimal import Decimal
from io import StringIO

from django.test import TestCase

from apps.core.management.commands.seed_demo_clinic import Command as SeedDemoClinic
from apps.imports.tests.test_inventory_import import INV_MAPPING, _InventoryAPIBase
from apps.inventory.models import Presentation, Product, StockMovement
from apps.users.models import User


class AliasWriterApiTests(_InventoryAPIBase, TestCase):
    def _create(self, code, presentation):
        return self.client.post('/api/inventory/products/', {
            'name': 'Alias ' + code, 'internal_code': code,
            'presentation_input': {'name': 'Caja', 'base_unit': 'piece', 'sale_price': '40',
                                   'stock': '0', **presentation},
        }, format='json')

    def _stored(self, code):
        pres = Presentation.objects.get(product__internal_code=code)
        return pres.quantity, pres.conversion_factor

    def test_create_normalizes_alias_only_equal_pair_none_and_limit(self):
        cases = {
            'A1': ({'quantity': '1.2345'}, '1.2345'),
            'A2': ({'quantity': '12', 'conversion_factor': '12.0000'}, '12'),
            'A3': ({}, '1'),
            'A4': ({'conversion_factor': '999999.9999'}, '999999.9999'),
        }
        for code, (presentation, expected) in cases.items():
            with self.subTest(code=code):
                response = self._create(code, presentation)
                self.assertEqual(response.status_code, 201, response.data)
                self.assertEqual(self._stored(code), (Decimal(expected), Decimal(expected)))

    def test_create_rejects_contradiction_and_invalid_factor_without_writing(self):
        cases = {
            'B1': {'quantity': '2', 'conversion_factor': '3'},
            'B2': {'conversion_factor': '0'},
            'B3': {'conversion_factor': '-1'},
            'B4': {'conversion_factor': 'NaN'},
            'B5': {'conversion_factor': 'Infinity'},
            'B6': {'conversion_factor': '1.23456'},
            'B7': {'quantity': '1000000'},
            'B8': {'quantity': 'abc'},
        }
        for code, presentation in cases.items():
            with self.subTest(code=code):
                response = self._create(code, {**presentation, 'stock': '1'})
                self.assertEqual(response.status_code, 400, response.data)
                self.assertFalse(Product.objects.filter(internal_code=code).exists())
                self.assertFalse(StockMovement.objects.filter(product__internal_code=code).exists())

    def test_product_patch_normalizes_the_nested_presentation_pair(self):
        self.assertEqual(self._create('C1', {'conversion_factor': '3'}).status_code, 201)
        product = Product.objects.get(internal_code='C1')
        url = f'/api/inventory/products/{product.public_id}/'
        steps = [
            ({'presentation_input': {'conversion_factor': '0.125'}}, 200, '0.125'),
            ({'presentation_input': {'quantity': '6'}}, 200, '6'),
            ({'presentation_input': {'quantity': '2', 'conversion_factor': '5'}}, 400, '6'),
            ({'name': 'Alias renombrado'}, 200, '6'),
        ]
        for body, status, expected in steps:
            with self.subTest(body=body):
                response = self.client.patch(url, body, format='json')
                self.assertEqual(response.status_code, status, response.data)
                self.assertEqual(self._stored('C1'), (Decimal(expected), Decimal(expected)))

    def test_presentation_patch_preserves_or_normalizes_the_pair(self):
        self.assertEqual(self._create('D1', {'conversion_factor': '3'}).status_code, 201)
        pres = Presentation.objects.get(product__internal_code='D1')
        url = f'/api/inventory/presentations/{pres.public_id}/'
        steps = [
            ({'sale_price': '41'}, 200, '3'),
            ({'conversion_factor': '1.2345'}, 200, '1.2345'),
            ({'quantity': '12'}, 200, '12'),
            ({'quantity': '2', 'conversion_factor': '5'}, 400, '12'),
            ({'conversion_factor': '0'}, 400, '12'),
        ]
        for body, status, expected in steps:
            with self.subTest(body=body):
                response = self.client.patch(url, body, format='json')
                self.assertEqual(response.status_code, status, response.data)
                self.assertEqual(self._stored('D1'), (Decimal(expected), Decimal(expected)))

    def test_new_presentation_normalizes_or_rejects_the_pair(self):
        product = self._make_product('E1', 'Producto E1')
        url = f'/api/inventory/products/{product.public_id}/presentations/'
        base = {'base_unit': 'piece', 'sale_price': '10', 'stock': '0'}
        response = self.client.post(url, {**base, 'name': 'Caja', 'quantity': '2', 'conversion_factor': '5'},
                                    format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(product.presentations.filter(name='Caja').exists())
        response = self.client.post(url, {**base, 'name': 'Blister', 'conversion_factor': '0.125'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        pres = product.presentations.get(name='Blister')
        self.assertEqual((pres.quantity, pres.conversion_factor), (Decimal('0.125'), Decimal('0.125')))

    def test_import_keeps_a_fractional_factor_as_alias(self):
        # Antes de I02 el alias se redondeaba a 2 decimales (0.125 → 0.13) y un factor
        # menor a 0.005 se rechazaba, aunque el alta manual sí lo acepta.
        pid = self._upload_ok(
            'Producto,Código,Unidad,Existencia,Precio,Factor\n'
            'Gasa estéril,GAS-001,pieza,8,12.00,0.125\n'
            'Hilo,GAS-002,pieza,1000,3.00,0.004\n'
        )
        self._set_mapping(pid, {**INV_MAPPING, 'Factor': 'presentation.conversion_factor'})
        self._validate(pid)
        response = self._commit(pid)
        self.assertEqual(response.status_code, 200, response.data)
        for code, factor, stock in (('GAS-001', '0.125', '1.0000'), ('GAS-002', '0.004', '4.0000')):
            with self.subTest(code=code):
                product = Product.objects.get(internal_code=code)
                pres = product.presentations.get()
                self.assertEqual((pres.quantity, pres.conversion_factor), (Decimal(factor), Decimal(factor)))
                self.assertEqual(product.stock_quantity, Decimal(stock))


class DemoSeedAliasTests(TestCase):
    """Ejecuta los pasos del seed que escriben presentaciones: organización y catálogo.

    El comando completo sigue con citas y cobros; esos pasos no escriben presentaciones.
    """

    def _rows(self, org):
        return list(Presentation.objects.filter(organization=org)
                    .order_by('pk').values_list('pk', 'quantity', 'conversion_factor', 'stock'))

    def test_demo_catalog_writes_alias_equal_to_factor_and_a_rerun_keeps_it(self):
        # El seed provisiona la organización demo con el primer superusuario.
        User.objects.create(username='seed-operator', role='ADMIN_SAAS',
                            is_superuser=True, is_staff=True, is_active=True)
        seed = SeedDemoClinic(stdout=StringIO())
        org = seed._ensure_org(None)
        seed._ensure_catalog(org)
        rows = self._rows(org)
        self.assertTrue(rows)
        self.assertTrue(all(quantity == factor for _, quantity, factor, _ in rows), rows)
        movements = StockMovement.objects.filter(organization=org).count()

        seed._ensure_catalog(org)
        self.assertEqual(self._rows(org), rows)
        self.assertEqual(StockMovement.objects.filter(organization=org).count(), movements)
