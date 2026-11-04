"""
Tests del importador de inventario (entity_type=inventory), siguiendo el nivel
de cobertura de test_owner_pet_import.py. Fase 2: normalizadores + catálogo.
Fase 4: flujo end-to-end upload→mapping→validate(dry-run)→commit atómico,
paridad de stock con el alta manual (plan §6.2), auto-código §5.3.
"""
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.imports.models import ImportJob
from apps.imports.normalization import (
    FIELD_CATALOG,
    extra_target_fields,
    normalize_base_unit,
    normalize_category,
    normalize_text,
    parse_bool,
    parse_decimal,
    required_fields,
    suggest_mapping,
)
from apps.inventory.models import Product, Presentation, StockMovement
from apps.organizations.models import Organization
from apps.users.models import User

# Se reutilizan los helpers de seeding del suite owner_pet (misma RBAC).
from apps.imports.tests.test_owner_pet_import import _seed_roles

INV_MAPPING = {
    'Producto': 'product.name',
    'Código': 'product.internal_code',
    'Unidad': 'product.base_unit',
    'Existencia': 'product.stock',
    'Precio': 'presentation.sale_price',
}


class InventoryNormalizationTests(SimpleTestCase):
    def test_normalize_category_aliases(self):
        self.assertEqual(normalize_category('Medicamento'), 'medication')
        self.assertEqual(normalize_category('ALIMENTO'), 'food')
        self.assertEqual(normalize_category('accesorios'), 'accessory')
        self.assertEqual(normalize_category('Varios'), 'other')
        # Canónico pasa tal cual
        self.assertEqual(normalize_category('food'), 'food')
        # Desconocido/vacío → None (caller aplica warning + 'other')
        self.assertIsNone(normalize_category('juguetes'))
        self.assertIsNone(normalize_category(''))

    def test_normalize_base_unit_aliases(self):
        self.assertEqual(normalize_base_unit('Pieza'), 'piece')
        self.assertEqual(normalize_base_unit('PZA'), 'piece')
        self.assertEqual(normalize_base_unit('Tabletas'), 'tablet')
        self.assertEqual(normalize_base_unit('ml'), 'ml')
        self.assertEqual(normalize_base_unit('Kilo'), 'kg')
        self.assertEqual(normalize_base_unit('gramos'), 'g')
        self.assertEqual(normalize_base_unit('Ampolleta'), 'ampoule')
        self.assertEqual(normalize_base_unit('unidades'), 'unit')
        # Canónico pasa tal cual
        self.assertEqual(normalize_base_unit('vial'), 'vial')
        # Desconocido/vacío → None (caller aplica warning + 'unit', D4)
        self.assertIsNone(normalize_base_unit('litros'))
        self.assertIsNone(normalize_base_unit(''))

    def test_parse_decimal_valid(self):
        self.assertEqual(parse_decimal('12.50'), (Decimal('12.50'), True))
        self.assertEqual(parse_decimal('12,50'), (Decimal('12.50'), True))
        self.assertEqual(parse_decimal('$12.50'), (Decimal('12.50'), True))
        self.assertEqual(parse_decimal(' 12 '), (Decimal('12'), True))
        self.assertEqual(parse_decimal('0'), (Decimal('0'), True))
        self.assertEqual(parse_decimal('-5'), (Decimal('-5'), True))  # signo: regla de dominio del caller
        self.assertEqual(parse_decimal('8112345678.0'), (Decimal('8112345678.0'), True))

    def test_parse_decimal_absence_is_not_error(self):
        self.assertEqual(parse_decimal(None), (None, True))
        self.assertEqual(parse_decimal(''), (None, True))
        self.assertEqual(parse_decimal('   '), (None, True))
        self.assertEqual(parse_decimal('$'), (None, True))

    def test_parse_decimal_invalid_never_silently_zero(self):
        for raw in ('abc', '12.3.4', '12,34.56', '1,23,456', '1e5', '+3', 'doce'):
            value, ok = parse_decimal(raw)
            self.assertFalse(ok, raw)
            self.assertIsNone(value, raw)

    def test_parse_bool_strict(self):
        for raw in ('sí', 'SI', 'true', 'TRUE', 'x', '1', 'verdadero'):
            self.assertIs(parse_bool(raw), True, raw)
        for raw in ('no', 'NO', 'false', 'Falso', '0', 'f'):
            self.assertIs(parse_bool(raw), False, raw)
        for raw in ('tal vez', '', None, '2', 'si/no'):
            self.assertIsNone(parse_bool(raw), str(raw))

    def test_inventory_catalog_required_and_extra(self):
        self.assertEqual(
            required_fields('inventory'),
            ['product.name', 'presentation.sale_price'],
        )
        self.assertEqual(extra_target_fields('inventory'), {'product.extra'})
        keys = {f['key'] for f in FIELD_CATALOG['inventory']}
        self.assertIn('presentation.conversion_factor', keys)
        self.assertIn('product.stock', keys)

    def test_inventory_automap_aliases(self):
        cols = [
            'Producto', 'Código Interno', 'Categoría', 'Unidad',
            'Existencia', 'Precio', 'Costo', 'Código de Barras',
        ]
        s = suggest_mapping(cols, 'inventory')
        self.assertEqual(s['Producto'], 'product.name')
        self.assertEqual(s['Código Interno'], 'product.internal_code')
        self.assertEqual(s['Categoría'], 'product.category')
        self.assertEqual(s['Unidad'], 'product.base_unit')
        self.assertEqual(s['Existencia'], 'product.stock')
        self.assertEqual(s['Precio'], 'presentation.sale_price')
        self.assertEqual(s['Costo'], 'presentation.purchase_price')
        self.assertEqual(s['Código de Barras'], 'presentation.barcode')

    def test_inventory_automap_no_double_assignment(self):
        s = suggest_mapping(['Precio', 'PVP', 'Producto', 'Artículo'], 'inventory')
        self.assertEqual(s.get('Precio'), 'presentation.sale_price')
        self.assertNotEqual(s.get('PVP'), 'presentation.sale_price')  # destino tomado
        assigned = [v for v in s.values() if v]
        self.assertEqual(len(assigned), len(set(assigned)))


class _InventoryAPIBase:
    """Setup + helpers compartidos por las clases de API (sin duplicación)."""

    def setUp(self):
        self.org = Organization.objects.create(name='Clínica Inv', timezone='UTC', tax_rate=Decimal('0'))
        roles = _seed_roles(self.org)
        self.admin = User.objects.create_user(
            username=f'admin_{self.org.id}', password='pass1234!', organization=self.org, role='ADMIN',
        )
        UserRole.objects.get_or_create(user=self.admin, role=roles['ADMIN'])
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _upload(self, text, entity_type='inventory'):
        upload = SimpleUploadedFile(
            'inventario.csv', text.encode('utf-8'), content_type='text/csv',
        )
        res = self.client.post(
            '/api/imports/', {'entity_type': entity_type, 'file': upload},
            format='multipart',
        )
        return res

    def _upload_ok(self, text):
        res = self._upload(text)
        self.assertEqual(res.status_code, 201, res.data)
        return res.data['public_id']

    def _set_mapping(self, pid, mapping=INV_MAPPING):
        res = self.client.patch(f'/api/imports/{pid}/mapping/', {'mapping': mapping}, format='json')
        self.assertEqual(res.status_code, 200, res.data)

    def _validate(self, pid):
        res = self.client.post(f'/api/imports/{pid}/validate/', format='json')
        self.assertEqual(res.status_code, 200, res.data)
        return res.data

    def _commit(self, pid):
        return self.client.post(f'/api/imports/{pid}/commit/', format='json')

    def _make_product(self, code, name, barcode='', organization=None):
        org = organization or self.org
        product = Product.objects.create(organization=org, name=name, internal_code=code)
        Presentation.objects.create(
            product=product, organization=org, name=product.name,
            base_unit='piece', quantity=Decimal('1'), conversion_factor=Decimal('1'),
            sale_price=Decimal('10.00'), barcode=barcode,
        )
        return product


class InventoryImportApiTests(_InventoryAPIBase, TestCase):
    """Flujo end-to-end entity_type=inventory (Fase 4): upload → mapping →
    validate (dry-run real) → commit atómico. Paridad de stock §6.2."""

    ROW = 'Jeringa 3ml,JER-001,pieza,10,15.50'

    def test_new_presentation_stock_uses_ledger_and_patch_cannot_assign_stock(self):
        product = self._make_product('PRES-WRITER', 'Producto')
        response = self.client.post(f'/api/inventory/products/{product.public_id}/presentations/', {
            'name': 'Caja', 'base_unit': 'piece', 'quantity': '3',
            'sale_price': '10', 'stock': '2',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, Decimal('6'))
        pres = product.presentations.get(name='Caja')
        self.assertEqual(pres.quantity, Decimal('3'))
        self.assertEqual(pres.conversion_factor, Decimal('3'))
        self.assertEqual(pres.stock, Decimal('2'))
        movement = StockMovement.objects.get(product=product)
        self.assertEqual(movement.quantity, Decimal('6'))
        self.assertEqual(movement.created_by, self.admin)
        response = self.client.patch(f'/api/inventory/presentations/{pres.public_id}/', {'stock': '5'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, Decimal('6'))

    def test_new_lot_tracked_presentation_rejects_unidentified_stock(self):
        product = self._make_product('PRES-LOT', 'Producto con lotes')
        product.tracks_lots = True
        product.save(update_fields=['tracks_lots'])
        response = self.client.post(f'/api/inventory/products/{product.public_id}/presentations/', {
            'name': 'Caja', 'base_unit': 'piece', 'conversion_factor': '3',
            'sale_price': '10', 'stock': '2',
        }, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(product.presentations.filter(name='Caja').exists())
        self.assertFalse(StockMovement.objects.filter(product=product).exists())

    def test_manual_stock_factors_zero_and_lots(self):
        for factor in ('1', '3', '12', '0.125', '1.2345'):
            with self.subTest(factor=factor):
                response = self.client.post('/api/inventory/products/', {
                    'name': 'Prueba ' + factor, 'internal_code': 'f' + factor,
                    'presentation_input': {'name': 'Caja', 'base_unit': 'piece',
                        'conversion_factor': factor, 'sale_price': '40',
                        'stock': '2', 'min_stock': '1'},
                }, format='json')
                self.assertEqual(response.status_code, 201, response.data)
                product = Product.objects.get(internal_code='f' + factor)
                self.assertEqual(product.stock_quantity, Decimal('2') * Decimal(factor))
                self.assertEqual(product.min_stock, Decimal(factor))
                self.assertEqual(product.presentations.get().quantity, Decimal(factor))
                self.assertEqual(StockMovement.objects.filter(product=product).count(), 1)
        response = self.client.post('/api/inventory/products/', {
            'name': 'Por lote', 'internal_code': 'LOT0', 'tracks_lots': True,
            'presentation_input': {'base_unit': 'piece', 'sale_price': '10', 'stock': '0'},
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(StockMovement.objects.filter(product__internal_code='LOT0').exists())
        response = self.client.post('/api/inventory/products/', {
            'name': 'Por lote positivo', 'internal_code': 'LOT1', 'tracks_lots': True,
            'presentation_input': {'base_unit': 'piece', 'sale_price': '10', 'stock': '1'},
        }, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Product.objects.filter(internal_code='LOT1').exists())

    def test_manual_writer_failure_rolls_back_catalog(self):
        from unittest.mock import patch
        with patch('apps.inventory.services.apply_stock_movement', side_effect=RuntimeError('synthetic failure')):
            response = self.client.post('/api/inventory/products/', {
                'name': 'Rollback', 'internal_code': 'ROLLBACK',
                'presentation_input': {'base_unit': 'piece', 'sale_price': '10', 'stock': '1'},
            }, format='json')
        self.assertEqual(response.status_code, 500)
        self.assertFalse(Product.objects.filter(internal_code='ROLLBACK').exists())
        self.assertFalse(Presentation.objects.filter(product__internal_code='ROLLBACK').exists())
        self.assertFalse(StockMovement.objects.filter(product__internal_code='ROLLBACK').exists())

    def test_upload_inventory_entity_accepted(self):
        pid = self._upload_ok(f'Producto,Código,Unidad,Existencia,Precio\n{self.ROW}\n')
        job = ImportJob.objects.get(public_id=pid)
        self.assertEqual(job.entity_type, 'inventory')

    def test_validate_does_not_write(self):
        pid = self._upload_ok(f'Producto,Código,Unidad,Existencia,Precio\n{self.ROW}\n')
        self._set_mapping(pid)
        before = (
            Product.objects.count(),
            Presentation.objects.count(),
            StockMovement.objects.count(),
        )
        data = self._validate(pid)
        self.assertEqual(data['status'], 'validated')
        self.assertEqual(data['result']['created_products'], 1)
        self.assertEqual(data['result']['preview_total'], 1)
        self.assertEqual(
            (Product.objects.count(), Presentation.objects.count(), StockMovement.objects.count()),
            before,
        )

    def test_commit_creates_product_presentation_and_movement(self):
        pid = self._upload_ok(f'Producto,Código,Unidad,Existencia,Precio\n{self.ROW}\n')
        self._set_mapping(pid)
        self._validate(pid)
        res = self._commit(pid)
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['status'], 'committed')
        r = res.data['result']
        self.assertEqual(r['created_products'], 1)
        self.assertEqual(r['created_presentations'], 1)
        self.assertEqual(r['initial_stock_movements'], 1)
        self.assertEqual(r['skipped_conflicts'], 0)
        self.assertEqual(r['blocking_rows'], 0)

        product = Product.objects.get(organization=self.org, internal_code='JER-001')
        self.assertEqual(product.name, 'Jeringa 3ml')
        self.assertEqual(product.category, 'other')
        self.assertEqual(product.base_unit, 'piece')
        self.assertEqual(product.stock_quantity, Decimal('10.0000'))
        pres = product.presentations.get()
        self.assertEqual(pres.name, 'Jeringa 3ml')          # default = nombre producto
        self.assertEqual(pres.base_unit, 'piece')
        self.assertEqual(pres.conversion_factor, Decimal('1'))
        self.assertEqual(pres.quantity, Decimal('1'))
        self.assertEqual(pres.sale_price, Decimal('15.50'))
        self.assertEqual(pres.stock, Decimal('10.00'))       # dual-write (unidades presentación)
        movement = StockMovement.objects.get()
        self.assertEqual(movement.movement_type, 'in')
        self.assertEqual(movement.quantity, Decimal('10.0000'))
        self.assertEqual(movement.quantity_unit, 'base')
        self.assertEqual(movement.reason, 'Stock inicial (importación)')
        self.assertEqual(movement.created_by, self.admin)    # plumbing created_by (view→dispatcher)
        self.assertEqual(movement.product, product)
        self.assertEqual(movement.presentation, pres)

    def test_commit_with_conversion_factor_multiplies_to_base(self):
        text = (
            'Producto,Código,Unidad,Existencia,Precio,Factor\n'
            'Solución fisiológica,SOL-001,ml,2,40.00,3\n'
        )
        pid = self._upload_ok(text)
        self._set_mapping(pid, {**INV_MAPPING, 'Factor': 'presentation.conversion_factor'})
        self._validate(pid)
        res = self._commit(pid)
        self.assertEqual(res.status_code, 200, res.data)
        product = Product.objects.get(internal_code='SOL-001')
        self.assertEqual(product.stock_quantity, Decimal('6.0000'))   # 2 × 3 base units
        pres = product.presentations.get()
        self.assertEqual(pres.stock, Decimal('2.00'))                 # dual-write ÷ cf = unidades presentación
        self.assertEqual(pres.conversion_factor, Decimal('3'))
        movement = StockMovement.objects.get()
        self.assertEqual(movement.quantity, Decimal('6.0000'))

    def test_stock_parity_manual_vs_import(self):
        """GATE §6.2 (revisado tras decisión de dominio): consistencia con el
        CONTRATO CANÓNICO, no igualdad literal con el alta manual.

        - Campos autoritativos idénticos entre rutas: Product.stock_quantity,
          Presentation.stock (dual-write ÷cf), conversion_factor, min_stock.
        - Presentation.quantity = conversion_factor SIEMPRE en importación
          (semántica 'alias' canónica, docs/modules/inventory.md + migración 0018).
        - El alta manual usa el mismo alias y registra una entrada auditable."""
        # Alta manual equivalente vía API.
        res = self.client.post('/api/inventory/products/', {
            'name': 'Paridad Manual',
            'internal_code': 'PAR-M',
            'base_unit': 'piece',
            'presentation_input': {
                'name': 'Caja de 3',
                'base_unit': 'piece',
                'conversion_factor': '3',
                'sale_price': '40.00',
                'stock': '2',
            },
        }, format='json')
        self.assertIn(res.status_code, (200, 201), res.data)
        manual = Product.objects.get(internal_code='PAR-M')
        manual_pres = manual.presentations.get()

        # Importación equivalente.
        pid = self._upload_ok(
            'Producto,Código,Unidad,Existencia,Precio,Factor\n'
            'Paridad Import,PAR-I,piece,2,40.00,3\n'
        )
        self._set_mapping(pid, {**INV_MAPPING, 'Factor': 'presentation.conversion_factor'})
        self._validate(pid)
        res = self._commit(pid)
        self.assertEqual(res.status_code, 200, res.data)
        imported = Product.objects.get(internal_code='PAR-I')
        imported_pres = imported.presentations.get()

        # Contrato autoritativo: paridad exacta entre rutas.
        self.assertEqual(imported.stock_quantity, manual.stock_quantity)      # 6.0000 = 2×3
        self.assertEqual(imported_pres.stock, manual_pres.stock)              # 2.00 (unidades presentación)
        self.assertEqual(imported_pres.conversion_factor, manual_pres.conversion_factor)  # 3
        self.assertEqual(imported.min_stock, manual.min_stock)
        # Contrato canónico del importador: quantity == cf (alias).
        self.assertEqual(imported_pres.quantity, Decimal('3'))
        self.assertEqual(manual_pres.quantity, Decimal('3'))
        self.assertEqual(manual_pres.conversion_factor, Decimal('3'))
        # Proveniencia: única diferencia permitida entre rutas.
        self.assertEqual(StockMovement.objects.filter(product=imported).count(), 1)
        movement = StockMovement.objects.get(product=manual)
        self.assertEqual(movement.quantity, Decimal('6'))
        self.assertEqual(movement.quantity_unit, 'base')
        self.assertEqual(movement.created_by, self.admin)
        self.assertEqual(movement.reason, 'Stock inicial (alta manual)')

    def test_autocode_without_internal_code(self):
        pid = self._upload_ok(
            'Producto,Unidad,Existencia,Precio\n'
            'Shampoo Medico,piece,5,80.00\n'
            'Collar Talla M,piece,3,120.00\n'
        )
        self._set_mapping(pid, {k: v for k, v in INV_MAPPING.items() if k != 'Código'})
        self._validate(pid)
        res = self._commit(pid)
        self.assertEqual(res.status_code, 200, res.data)
        products = Product.objects.filter(organization=self.org).order_by('pk')
        self.assertEqual(products.count(), 2)
        codes = [p.internal_code for p in products]
        for code in codes:
            self.assertTrue(code.startswith(f'PROD-{self.org.id}-'), code)
        self.assertNotEqual(codes[0], codes[1])

    def test_missing_sale_price_blocks_row_and_commit(self):
        pid = self._upload_ok(
            'Producto,Código,Unidad,Existencia,Precio\n'
            'Sin Precio,SP-001,piece,5,\n'
        )
        self._set_mapping(pid)
        data = self._validate(pid)
        blocking_fields = {b['field'] for b in data['result']['blocking']}
        self.assertIn('presentation.sale_price', blocking_fields)
        self.assertEqual(data['result']['preview_total'], 0)
        before = Product.objects.count()
        res = self._commit(pid)
        self.assertEqual(res.status_code, 400)   # commit bloqueado por blocking[]
        self.assertEqual(Product.objects.count(), before)

    def test_recommit_and_revalidate_after_commit_are_409(self):
        pid = self._upload_ok(f'Producto,Código,Unidad,Existencia,Precio\n{self.ROW}\n')
        self._set_mapping(pid)
        self._validate(pid)
        res = self._commit(pid)
        self.assertEqual(res.status_code, 200)
        movements_before = StockMovement.objects.count()
        res = self._commit(pid)
        self.assertEqual(res.status_code, 409)
        res = self.client.post(f'/api/imports/{pid}/validate/', format='json')
        self.assertEqual(res.status_code, 409)
        self.assertEqual(StockMovement.objects.count(), movements_before)  # sin doble stock

    def test_extra_data_product_stored_with_source_column(self):
        mapping = dict(INV_MAPPING)
        mapping['Proveedor viejo'] = {'target': 'product.extra', 'label': 'Proveedor'}
        pid = self._upload_ok(
            'Producto,Código,Unidad,Existencia,Precio,Proveedor viejo\n'
            f'{self.ROW},Zoetis\n'
        )
        self._set_mapping(pid, mapping)
        self._validate(pid)
        res = self._commit(pid)
        self.assertEqual(res.status_code, 200, res.data)
        product = Product.objects.get(internal_code='JER-001')
        self.assertEqual(len(product.extra_data), 1)
        entry = product.extra_data[0]
        self.assertEqual(entry['label'], 'Proveedor')
        self.assertEqual(entry['value'], 'Zoetis')
        self.assertEqual(entry['source_column'], 'Proveedor viejo')
        self.assertIn('imported_at', entry)

    def test_cross_tenant_job_404(self):
        pid = self._upload_ok(f'Producto,Código,Unidad,Existencia,Precio\n{self.ROW}\n')
        other_org = Organization.objects.create(name='Otra', timezone='UTC', tax_rate=Decimal('0'))
        roles = _seed_roles(other_org)
        intruder = User.objects.create_user(
            username='intruder', password='pass1234!', organization=other_org, role='ADMIN',
        )
        UserRole.objects.get_or_create(user=intruder, role=roles['ADMIN'])
        other_client = APIClient()
        other_client.force_authenticate(user=intruder)
        res = other_client.post(f'/api/imports/{pid}/validate/', format='json')
        self.assertEqual(res.status_code, 404)
        res = other_client.post(f'/api/imports/{pid}/commit/', format='json')
        self.assertEqual(res.status_code, 404)
        self.assertEqual(Product.objects.count(), 0)


HEADER = 'Producto,Código,Unidad,Existencia,Precio'


def _row(name, code, unit, stock, price):
    return f'{name},{code},{unit},{stock},{price}'


class InventoryDedupAndRulesTests(_InventoryAPIBase, TestCase):
    """Conflictos de dedup (§5), reglas de fila, atomicidad por savepoint,
    aislamiento cross-tenant del contexto y permisos."""

    def _validate_rows(self, rows_text, mapping=None):
        pid = self._upload_ok(rows_text)
        self._set_mapping(pid, mapping or INV_MAPPING)
        data = self._validate(pid)
        return pid, data['result']

    def test_duplicate_internal_code_in_file_uncertain_and_high(self):
        # Mismo código, nombre distinto → uncertain.
        _, result = self._validate_rows(
            f'{HEADER}\n'
            f'{_row("Producto A", "CO-1", "pieza", "1", "10")}\n'
            f'{_row("Producto B", "CO-1", "pieza", "2", "20")}\n'
        )
        self.assertEqual(result['skipped_conflicts'], 1)
        self.assertEqual(result['conflicts_uncertain'], 1)
        conflict = result['conflicts'][0]
        self.assertEqual(conflict['type'], 'duplicate_internal_code')
        self.assertEqual(conflict['match_confidence'], 'uncertain')
        self.assertEqual(result['created_products'], 1)

        # Mismo código, mismo nombre → high.
        _, result = self._validate_rows(
            f'{HEADER}\n'
            f'{_row("Ibuprofeno", "IB-1", "pieza", "1", "10")}\n'
            f'{_row("Ibuprofeno", "IB-1", "pieza", "5", "12")}\n'
        )
        self.assertEqual(result['skipped_conflicts'], 1)
        self.assertEqual(result['conflicts_high'], 1)

    def test_duplicate_internal_code_vs_db_reports_existing_public_id(self):
        self._make_product('EX-1', 'Existente DB')
        _, result = self._validate_rows(
            f'{HEADER}\n{_row("Nombre Distinto", "EX-1", "pieza", "3", "15")}\n'
        )
        conflict = result['conflicts'][0]
        self.assertEqual(conflict['type'], 'duplicate_internal_code')
        self.assertEqual(conflict['match_confidence'], 'uncertain')
        self.assertEqual(conflict['existing']['name'], 'Existente DB')
        self.assertTrue(conflict['existing']['public_id'])
        # Commit: preview honesto — la fila se omite y el existente no cambia.
        pid = ImportJob.objects.latest('pk').public_id
        res = self._commit(pid)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['result']['created_products'], 0)
        self.assertEqual(Product.objects.get(internal_code='EX-1').name, 'Existente DB')

    def test_same_name_without_code_is_reported_not_silent(self):
        _, result = self._validate_rows(
            'Producto,Código,Unidad,Existencia,Precio\n'
            'Paracetamol,,pieza,1,5\n'
            'Paracetamol,,pieza,3,6\n'
        )
        self.assertEqual(result['conflicts_uncertain'], 1)
        self.assertEqual(result['skipped_duplicates'], 0)   # NUNCA dedup silenciosa
        conflict = result['conflicts'][0]
        self.assertEqual(conflict['type'], 'duplicate_name')
        self.assertEqual(conflict['match_confidence'], 'uncertain')
        self.assertEqual(result['created_products'], 1)
        # Los conflicts NO bloquean el commit; entra solo uno.
        pid = ImportJob.objects.latest('pk').public_id
        res = self._commit(pid)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Product.objects.filter(organization=self.org).count(), 1)
        self.assertEqual(res.data['result']['created_products'], 1)

    def test_same_name_with_different_codes_both_created(self):
        _, result = self._validate_rows(
            'Producto,Código,Unidad,Existencia,Precio\n'
            'Paracetamol 500,PA-500,pieza,1,5\n'
            'Paracetamol 1g,PA-1000,pieza,2,8\n'
        )
        self.assertEqual(result['conflicts'], [])
        self.assertEqual(result['created_products'], 2)

    def test_barcode_conflict_in_file_and_db(self):
        self._make_product('DB-1', 'Con Barcode DB', barcode='7501234567890')
        mapping = {**INV_MAPPING, 'Código de Barras': 'presentation.barcode'}
        _, result = self._validate_rows(
            'Producto,Código,Unidad,Existencia,Precio,Código de Barras\n'
            'Prod A,A-1,pieza,1,10,\n'
            'Prod B,B-1,pieza,1,10,111222333\n'
            'Prod C,C-1,pieza,1,10,111222333\n'
            'Prod D,D-1,pieza,1,10,7501234567890\n',
            mapping=mapping,
        )
        types = [(c['row'], c['type'], c['match_confidence']) for c in result['conflicts']]
        self.assertIn((3, 'duplicate_barcode', 'high'), types)     # dentro del archivo
        db_conflict = next(c for c in result['conflicts'] if c['row'] == 4)
        self.assertEqual(db_conflict['type'], 'duplicate_barcode')
        self.assertEqual(db_conflict['existing']['product_name'], 'Con Barcode DB')
        self.assertTrue(db_conflict['existing']['public_id'])
        self.assertEqual(result['created_products'], 2)  # entran A y B; C/D omitidos

        # Commit: preview honesto — A y B entran; nada huérfano.
        pid = ImportJob.objects.latest('pk').public_id
        res = self._commit(pid)
        self.assertEqual(res.status_code, 200)
        r = res.data['result']
        self.assertEqual(r['created_products'], 2)
        codes = set(Product.objects.filter(organization=self.org).values_list('internal_code', flat=True))
        self.assertEqual(codes, {'DB-1', 'A-1', 'B-1'})

    def test_cross_org_code_and_barcode_do_not_conflict(self):
        other_org = Organization.objects.create(name='Otra Org', timezone='UTC', tax_rate=Decimal('0'))
        self._make_product('SH-1', 'Ajeno', barcode='ABC123', organization=other_org)
        _, result = self._validate_rows(
            'Producto,Código,Unidad,Existencia,Precio,Código de Barras\n'
            'Mío Local,SH-1,pieza,4,25,ABC123\n'
        )
        self.assertEqual(result['conflicts'], [])
        self.assertEqual(result['created_products'], 1)

    def test_row_validation_rules_blocking_vs_warning(self):
        _, result = self._validate_rows(
            'Producto,Código,Unidad,Existencia,Precio,Factor,Categoría,Receta\n'
            'Stock Negativo,SN-1,pieza,-5,10,,,\n'
            'Stock No Numérico,SNN-1,piece,abc,10,,,\n'
            'Factor Cero,FC-1,pieza,1,10,0,,\n'
            'Receta Ambigua,RA-1,piece,1,10,,,tal vez\n'
            'Cat Rara,CR-1,piece,1,10,,juguetes,no\n'
            'Sin Unidad,SU-1,,2,5,,,no\n',
            mapping={**INV_MAPPING, 'Factor': 'presentation.conversion_factor',
                     'Categoría': 'product.category',
                     'Receta': 'product.requires_prescription'},
        )
        blocking_by_row = {}
        for b in result['blocking']:
            blocking_by_row.setdefault(b['row'], set()).add(b['field'])
        self.assertIn('product.stock', blocking_by_row.get(1, set()))
        self.assertIn('product.stock', blocking_by_row.get(2, set()))
        self.assertIn('presentation.conversion_factor', blocking_by_row.get(3, set()))
        self.assertIn('product.requires_prescription', blocking_by_row.get(4, set()))
        # Fila 5: categoría desconocida → warning (importa como other).
        warning_fields = {w['field'] for w in result['warnings'] if w['row'] == 5}
        self.assertIn('product.category', warning_fields)
        # Fila 6: unidad vacía → warning + 'unit' (D4).
        warning_fields_6 = {w['field'] for w in result['warnings'] if w['row'] == 6}
        self.assertIn('product.base_unit', warning_fields_6)
        self.assertEqual(result['blocking_rows'], 4)
        self.assertEqual(result['preview_total'], 2)

    def test_price_exceeding_max_digits_blocked_at_validate(self):
        """Honestidad preview==commit: overflow de max_digits se detecta en
        CLEAN (validate), nunca llega a reventar en commit."""
        _, result = self._validate_rows(
            f'{HEADER}\n{_row("Precio Gigante", "PG-1", "pieza", "1", "12345678999")}\n'
        )
        fields = {b['field'] for b in result['blocking']}
        self.assertIn('presentation.sale_price', fields)
        self.assertEqual(result['preview_total'], 0)

    def test_savepoint_isolation_mid_commit_failure_does_not_orphan(self):
        """Fallo determinista a mitad de commit (mock del servicio de stock en la
        2ª llamada): la fila 2 se revuelve COMPLETA (Product+Presentation) por el
        savepoint; las filas 1 y 3 persisten; cero huérfanos."""
        from unittest import mock
        from django.core.exceptions import ValidationError as DjangoValidationError
        import apps.imports.services_inventory as si

        pid = self._upload_ok(
            f'{HEADER}\n'
            f'{_row("Bueno Uno", "OK-1", "pieza", "3", "10")}\n'
            f'{_row("Explota", "PG-1", "pieza", "4", "11")}\n'
            f'{_row("Bueno Dos", "OK-2", "pieza", "5", "20")}\n'
        )
        self._set_mapping(pid)
        self._validate(pid)

        real = si.apply_stock_movement
        calls = {'n': 0}

        def flaky(*args, **kwargs):
            calls['n'] += 1
            if calls['n'] == 2:
                raise DjangoValidationError('boom')
            return real(*args, **kwargs)

        with mock.patch.object(si, 'apply_stock_movement', side_effect=flaky):
            res = self._commit(pid)
        self.assertEqual(res.status_code, 200)
        r = res.data['result']
        self.assertEqual(r['created_products'], 2)
        codes = set(Product.objects.filter(organization=self.org).values_list('internal_code', flat=True))
        self.assertEqual(codes, {'OK-1', 'OK-2'})   # PG-1 revertido por completo
        blocking_rows = {b['row'] for b in r['blocking']}
        self.assertEqual(blocking_rows, {2})
        self.assertEqual(r['initial_stock_movements'], 2)

    def test_non_admin_forbidden(self):
        roles = {r.name: r for r in Role.objects.filter(organization=self.org)}
        vet_role = roles.get('VET')
        vet = User.objects.create_user(
            username=f'vet_{self.org.id}', password='pass1234!', organization=self.org, role='VET',
        )
        UserRole.objects.get_or_create(user=vet, role=vet_role)
        client = APIClient()
        client.force_authenticate(user=vet)
        upload = SimpleUploadedFile('inv.csv', f'{HEADER}\nx,y,piece,1,1\n'.encode(), content_type='text/csv')
        res = client.post('/api/imports/', {'entity_type': 'inventory', 'file': upload}, format='multipart')
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.data['code'], 'permission_denied')

    def test_demo_account_blocked(self):
        self.org.is_demo = True
        self.org.save()
        upload = SimpleUploadedFile('inv.csv', f'{HEADER}\nx,y,piece,1,1\n'.encode(), content_type='text/csv')
        res = self.client.post('/api/imports/', {'entity_type': 'inventory', 'file': upload}, format='multipart')
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.data['code'], 'demo_account_restricted')

    def test_xlsx_decimal_cells_parse_exact(self):
        import io
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(['Producto', 'Código', 'Unidad', 'Existencia', 'Precio'])
        ws.append(['Solución X', 'SOLX', 'ml', 12.5, 99.9])
        buf = io.BytesIO()
        wb.save(buf)
        upload = SimpleUploadedFile(
            'inv.xlsx', buf.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        res = self.client.post(
            '/api/imports/', {'entity_type': 'inventory', 'file': upload}, format='multipart',
        )
        self.assertEqual(res.status_code, 201, res.data)
        pid = res.data['public_id']
        self._set_mapping(pid)
        self._validate(pid)
        res = self._commit(pid)
        self.assertEqual(res.status_code, 200, res.data)
        product = Product.objects.get(internal_code='SOLX')
        self.assertEqual(product.stock_quantity, Decimal('12.5000'))
        pres = product.presentations.get()
        self.assertEqual(pres.stock, Decimal('12.50'))
        self.assertEqual(pres.sale_price, Decimal('99.90'))
