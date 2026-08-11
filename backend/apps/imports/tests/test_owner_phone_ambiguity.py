"""P0-27 — El importador tampoco elige entre expedientes duplicados (INV-C).

Dos cosas se acreditan aquí, y la segunda es un fallo de **producto**, no de
concurrencia:

1. El `.first()` sobre los duplicados desaparece de las **tres** lecturas por
   teléfono (preview, dry-run y commit). Elegir una fila arbitraria es
   exactamente lo que INV-C prohíbe.
2. **Paridad preview ↔ escritura** (§4.8). Cambiar solo el commit dejaría la
   vista previa diciendo «se reutilizará el cliente X» y el commit rechazando
   esa misma fila: el usuario aprueba una cosa y obtiene otra. El conteo de
   «se importarán N filas» ya excluye la fila ambigua.

La política de fila no cambia: una fila problemática **no aborta** el import; se
salta y se reporta.
"""
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User

MAPPING = {
    'Dueño': 'owner.name',
    'Teléfono': 'owner.phone',
    'Mascota': 'pet.name',
    'Especie': 'pet.species',
}

PHONE = '8112345678'


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
            name=name, organization=org, defaults={'is_system_role': True},
        )
        role.permissions.set(
            [wildcard] if '*.*' in codes
            else [perms_map[c] for c in codes if c in perms_map]
        )
        roles[name] = role
    return roles


def _csv(text):
    return SimpleUploadedFile(
        'clientes.csv', text.encode('utf-8'), content_type='text/csv',
    )


class ImporterAmbiguityTests(TestCase):
    CSV = (
        'Dueño,Teléfono,Mascota,Especie\n'
        f'Ana Lopez,{PHONE},Luna,Perro\n'
        'Beto Ruiz,8199999999,Rocky,Perro\n'
    )

    def setUp(self):
        self.org = Organization.objects.create(
            name='Clínica dup', timezone='UTC', tax_rate=Decimal('0'),
        )
        roles = _seed_roles(self.org)
        self.admin = User.objects.create_user(
            username='adm_imp_dup', password='pass1234!',
            organization=self.org, role='ADMIN',
        )
        UserRole.objects.get_or_create(user=self.admin, role=roles['ADMIN'])
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _seed_historical_duplicate(self):
        """Dos expedientes que solo coinciden **tras normalizar**."""
        Owner.objects.create(organization=self.org, name='Ana López', phone='81 1234 5678')
        Owner.objects.create(organization=self.org, name='Ana Lopez', phone=PHONE)

    def _run(self, action):
        res = self.client.post(
            '/api/imports/',
            {'entity_type': 'owner_pet', 'file': _csv(self.CSV)},
            format='multipart',
        )
        self.assertEqual(res.status_code, 201, res.data)
        pid = res.data['public_id']
        res = self.client.patch(
            f'/api/imports/{pid}/mapping/', {'mapping': MAPPING}, format='json',
        )
        self.assertEqual(res.status_code, 200, res.data)
        res = self.client.post(f'/api/imports/{pid}/{action}/', format='json')
        self.assertEqual(res.status_code, 200, res.data)
        return res.data['result']

    def _ambiguous_errors(self, result):
        return [e for e in result['errors'] if e.get('code') == 'owner_ambiguous']

    def test_preview_reports_the_ambiguous_row_as_not_importable(self):
        self._seed_historical_duplicate()
        result = self._run('validate')

        errors = self._ambiguous_errors(result)
        self.assertEqual(len(errors), 1, result['errors'])
        self.assertEqual(errors[0]['row'], 1)
        self.assertEqual(errors[0]['field'], 'owner.phone')
        # El conteo que ve el usuario ya excluye la fila.
        self.assertEqual(result['created_pets'], 1)     # solo Beto/Rocky
        self.assertEqual(result['preview_total'], 1)
        self.assertEqual(result['blocking_rows'], 1)

    def test_commit_reaches_the_same_verdict_as_the_preview(self):
        self._seed_historical_duplicate()
        preview = self._run('validate')
        commit = self._run('commit')

        self.assertEqual(
            len(self._ambiguous_errors(preview)),
            len(self._ambiguous_errors(commit)),
        )
        self.assertEqual(preview['created_pets'], commit['created_pets'])
        self.assertEqual(preview['blocking_rows'], commit['blocking_rows'])

    def test_ambiguous_row_writes_nothing_and_does_not_abort_the_import(self):
        self._seed_historical_duplicate()
        result = self._run('commit')

        # La fila ambigua no crea nada…
        self.assertFalse(
            Pet.objects.for_organization(self.org).filter(name='Luna').exists()
        )
        self.assertEqual(
            Owner.objects.for_organization(self.org)
            .filter(is_generic=False, phone_normalized=PHONE).count(),
            2,
            "Ni un tercer expediente, ni una elección entre los dos.",
        )
        # …y el resto del archivo entra igual (política vigente de fila).
        self.assertTrue(
            Pet.objects.for_organization(self.org).filter(name='Rocky').exists()
        )
        self.assertEqual(result['created_pets'], 1)

    def test_clean_data_imports_exactly_as_before(self):
        """Iron rule: sin duplicados, el importador se comporta igual que antes."""
        result = self._run('commit')
        self.assertEqual(result['created_owners'], 2)
        self.assertEqual(result['created_pets'], 2)
        self.assertEqual(result['blocking_rows'], 0)

    def test_existing_single_record_is_still_reused_by_phone(self):
        """Su regla documentada (dedup por teléfono) NO se endurece a nombre."""
        existing = Owner.objects.create(
            organization=self.org, name='Otro Nombre', phone=PHONE,
        )
        result = self._run('commit')
        self.assertEqual(result['reused_owners'], 1)
        self.assertEqual(result['created_owners'], 1)
        self.assertTrue(existing.pets.filter(name='Luna').exists())

    def test_phoneless_rows_still_import(self):
        """Sin teléfono no hay clave: se importa igual (excepción del importador)."""
        self.CSV = (
            'Dueño,Teléfono,Mascota,Especie\n'
            'Sin Tel,,Luna,Perro\n'
        )
        result = self._run('commit')
        self.assertEqual(result['created_owners'], 1)
        owner = Owner.objects.for_organization(self.org).get(name='Sin Tel')
        self.assertIsNone(owner.phone_normalized)

    def test_imported_records_get_their_key_derived(self):
        self._run('commit')
        owner = Owner.objects.for_organization(self.org).get(name='Ana Lopez')
        self.assertEqual(owner.phone_normalized, PHONE)
