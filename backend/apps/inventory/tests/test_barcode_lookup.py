"""
Tests del lookup de presentación por código de barras (POS scanner).

Regresión: la ruta 'inventory/presentations/barcode/' estaba declarada DESPUÉS
del catch-all 'inventory/presentations/<str:pk>/', por lo que Django resolvía
"barcode" como pk → 404 permanente. El endpoint nunca fue alcanzable.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.inventory.models import Presentation, Product
from apps.organizations.models import Organization
from apps.users.models import User

BARCODE = '4005900515865'
URL = '/api/inventory/presentations/barcode/'


def _seed_roles(org):
    wildcard, _ = Permission.objects.get_or_create(code='*.*')
    perms_map = {
        code: Permission.objects.get_or_create(code=code)[0]
        for code in PERMISSION_CODES
    }
    roles = {}
    for name, codes in PERMISSIONS.items():
        if name == 'ADMIN_SAAS':
            continue
        role, _ = Role.objects.get_or_create(
            name=name,
            organization=org,
            defaults={'is_system_role': True},
        )
        role.permissions.set(
            [wildcard] if '*.*' in codes
            else [perms_map[c] for c in codes if c in perms_map]
        )
        roles[name] = role
    return roles


def _create_presentation(org, *, name, internal_code, barcode):
    product = Product.objects.create(
        name=name,
        internal_code=internal_code,
        organization=org,
    )
    return Presentation.objects.create(
        product=product,
        name='Unidad',
        base_unit='piece',
        quantity=Decimal('1'),
        conversion_factor=Decimal('1'),
        sale_price=Decimal('100.00'),
        stock=Decimal('10'),
        barcode=barcode,
        organization=org,
    )


class BarcodeLookupTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            name='Org Barcode',
            timezone='UTC',
            tax_rate=Decimal('0'),
        )
        roles = _seed_roles(self.org)
        self.user = User.objects.create_user(
            username='admin_barcode',
            password='pass1234!',
            organization=self.org,
            role='ADMIN',
        )
        UserRole.objects.get_or_create(user=self.user, role=roles['ADMIN'])

        self.presentation = _create_presentation(
            self.org, name='Shampoo Dermo', internal_code='SHA-001', barcode=BARCODE,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_lookup_por_barcode_devuelve_presentacion(self):
        """Regresión orden de rutas: barcode/ no debe caer en el detail <pk>."""
        res = self.client.get(URL, {'barcode': BARCODE})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['public_id'], str(self.presentation.public_id))
        self.assertEqual(res.data['barcode'], BARCODE)
        self.assertEqual(res.data['product_name'], 'Shampoo Dermo')

    def test_sin_parametro_barcode_400(self):
        res = self.client.get(URL)
        self.assertEqual(res.status_code, 400)

    def test_barcode_inexistente_404(self):
        res = self.client.get(URL, {'barcode': '0000000000000'})
        self.assertEqual(res.status_code, 404)

    def test_cross_tenant_404(self):
        """El barcode de otra organización nunca se expone (cross-org = 404)."""
        other_org = Organization.objects.create(
            name='Org Ajena',
            timezone='UTC',
            tax_rate=Decimal('0'),
        )
        _create_presentation(
            other_org, name='Producto Ajeno', internal_code='AJE-001',
            barcode='7501000000000',
        )
        res = self.client.get(URL, {'barcode': '7501000000000'})
        self.assertEqual(res.status_code, 404)
