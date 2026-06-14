"""
Tests del importador owner_pet (Fase A): parsing, normalización, dry-run sin
escritura, commit atómico, dedup skip, multi-tenant, permisos, legacy_id.
"""
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.imports.models import ImportJob
from apps.imports.normalization import (
    normalize_species,
    normalize_text,
    suggest_mapping,
)
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User

MAPPING = {
    'Dueño': 'owner.name',
    'Teléfono': 'owner.phone',
    'Mascota': 'pet.name',
    'Especie': 'pet.species',
    'Expediente': 'pet.legacy_id',
}


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
    return SimpleUploadedFile('clientes.csv', text.encode('utf-8'), content_type='text/csv')


class NormalizationTests(TestCase):
    def test_species_alias(self):
        self.assertEqual(normalize_species('Perro'), 'canino')
        self.assertEqual(normalize_species('GATO'), 'felino')
        self.assertEqual(normalize_species('canino'), 'canino')
        self.assertIsNone(normalize_species('dinosaurio'))
        self.assertIsNone(normalize_species(''))

    def test_normalize_text_dedup_key(self):
        self.assertEqual(normalize_text('Juan  Pérez '), 'juan perez')
        self.assertEqual(normalize_text('MAX'), normalize_text('Max'))

    def test_suggest_mapping_aliases(self):
        cols = ['Dueño', 'WhatsApp', 'Paciente', 'Tipo de animal']
        s = suggest_mapping(cols, 'owner_pet')
        self.assertEqual(s['Dueño'], 'owner.name')
        self.assertEqual(s['WhatsApp'], 'owner.phone')
        self.assertEqual(s['Paciente'], 'pet.name')
        self.assertEqual(s['Tipo de animal'], 'pet.species')


class ImportApiTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Clínica A', timezone='UTC', tax_rate=Decimal('0'))
        roles = _seed_roles(self.org)
        self.admin = User.objects.create_user(
            username='admin_a', password='pass1234!', organization=self.org, role='ADMIN',
        )
        UserRole.objects.get_or_create(user=self.admin, role=roles['ADMIN'])
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _upload(self, text):
        res = self.client.post(
            '/api/imports/',
            {'entity_type': 'owner_pet', 'file': _csv(text)},
            format='multipart',
        )
        self.assertEqual(res.status_code, 201, res.data)
        return res.data['public_id']

    def _set_mapping(self, pid, mapping=MAPPING):
        res = self.client.patch(f'/api/imports/{pid}/mapping/', {'mapping': mapping}, format='json')
        self.assertEqual(res.status_code, 200, res.data)

    def test_upload_parses_headers_and_suggests(self):
        pid = self._upload('Dueño,Teléfono,Mascota,Especie,Expediente\nJuan,8112345678,Max,Perro,00231\n')
        job = ImportJob.objects.get(public_id=pid)
        self.assertEqual(job.status, 'pending')
        self.assertEqual(job.source_columns, ['Dueño', 'Teléfono', 'Mascota', 'Especie', 'Expediente'])
        self.assertEqual(len(job.rows), 1)

    def test_validate_does_not_write(self):
        pid = self._upload('Dueño,Teléfono,Mascota,Especie,Expediente\nJuan Pérez,8112345678,Max,Perro,00231\n')
        self._set_mapping(pid)
        before = Owner.objects.count(), Pet.objects.count()
        res = self.client.post(f'/api/imports/{pid}/validate/', format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['status'], 'validated')
        self.assertEqual(res.data['result']['created_owners'], 1)
        self.assertEqual(res.data['result']['created_pets'], 1)
        self.assertEqual((Owner.objects.count(), Pet.objects.count()), before)

    def test_commit_creates_owner_and_pet_with_legacy(self):
        pid = self._upload('Dueño,Teléfono,Mascota,Especie,Expediente\nJuan Pérez,8112345678,Max,Perro,00231\n')
        self._set_mapping(pid)
        res = self.client.post(f'/api/imports/{pid}/commit/', format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['status'], 'committed')
        self.assertEqual(res.data['result']['created_pets'], 1)
        owner = Owner.objects.for_organization(self.org).get(phone='8112345678')
        self.assertEqual(owner.name, 'Juan Pérez')
        pet = Pet.objects.for_organization(self.org).get(legacy_id='00231')
        self.assertEqual(pet.name, 'Max')
        self.assertEqual(pet.species, 'canino')
        self.assertEqual(pet.owner_id, owner.pk)

    def test_owner_without_phone_is_imported(self):
        pid = self._upload('Dueño,Teléfono,Mascota,Especie,Expediente\nAna López,,Luna,Gato,00232\n')
        self._set_mapping(pid)
        res = self.client.post(f'/api/imports/{pid}/commit/', format='json')
        owner = Owner.objects.for_organization(self.org).get(name='Ana López')
        self.assertEqual(owner.phone, '')
        self.assertTrue(Pet.objects.for_organization(self.org).filter(name='Luna').exists())
        # Teléfono opcional en import, pero con warning.
        self.assertTrue(any(w['field'] == 'owner.phone' for w in res.data['result']['warnings']))

    def test_pet_dedup_normalized_name(self):
        # Mismo dueño (mismo teléfono), "Max" y "MAX" misma especie → 1 pet, 1 skip.
        text = (
            'Dueño,Teléfono,Mascota,Especie,Expediente\n'
            'Juan,8112345678,Max,Perro,00231\n'
            'Juan,8112345678,MAX,Perro,\n'
        )
        pid = self._upload(text)
        self._set_mapping(pid)
        res = self.client.post(f'/api/imports/{pid}/commit/', format='json')
        result = res.data['result']
        self.assertEqual(result['created_pets'], 1)
        self.assertEqual(result['skipped_duplicates'], 1)
        self.assertEqual(result['reused_owners'], 1)
        self.assertEqual(Pet.objects.for_organization(self.org).filter(owner__phone='8112345678').count(), 1)

    def test_owner_reused_when_phone_exists(self):
        existing = Owner.objects.create(organization=self.org, name='Pedro', phone='8120000000')
        pid = self._upload('Dueño,Teléfono,Mascota,Especie,Expediente\nPedro,8120000000,Rocky,Perro,\n')
        self._set_mapping(pid)
        res = self.client.post(f'/api/imports/{pid}/commit/', format='json')
        self.assertEqual(res.data['result']['created_owners'], 0)
        self.assertEqual(res.data['result']['reused_owners'], 1)
        self.assertEqual(Owner.objects.for_organization(self.org).filter(phone='8120000000').count(), 1)
        self.assertEqual(existing.pets.count(), 1)

    def test_bad_species_is_row_error_not_crash(self):
        text = (
            'Dueño,Teléfono,Mascota,Especie,Expediente\n'
            'Juan,8112345678,Max,Perro,00231\n'
            'Ana,8113334444,Nemo,dinosaurio,00232\n'
        )
        pid = self._upload(text)
        self._set_mapping(pid)
        res = self.client.post(f'/api/imports/{pid}/commit/', format='json')
        result = res.data['result']
        self.assertEqual(result['created_pets'], 1)
        self.assertEqual(result['error_rows'], 1)
        self.assertTrue(any(e['row'] == 2 and e['field'] == 'pet.species' for e in result['errors']))

    def test_legacy_id_unique_per_org_conflict_reported(self):
        # Dos owners distintos (teléfonos distintos) con el mismo pet.legacy_id.
        text = (
            'Dueño,Teléfono,Mascota,Especie,Expediente\n'
            'Juan,8112345678,Max,Perro,00231\n'
            'Ana,8113334444,Luna,Gato,00231\n'
        )
        pid = self._upload(text)
        self._set_mapping(pid)
        res = self.client.post(f'/api/imports/{pid}/commit/', format='json')
        result = res.data['result']
        self.assertEqual(result['created_pets'], 1)
        self.assertEqual(result['error_rows'], 1)
        self.assertEqual(Pet.objects.for_organization(self.org).filter(legacy_id='00231').count(), 1)

    def test_commit_twice_conflicts(self):
        pid = self._upload('Dueño,Teléfono,Mascota,Especie,Expediente\nJuan,8112345678,Max,Perro,00231\n')
        self._set_mapping(pid)
        self.client.post(f'/api/imports/{pid}/commit/', format='json')
        res2 = self.client.post(f'/api/imports/{pid}/commit/', format='json')
        self.assertEqual(res2.status_code, 409)

    def test_cross_tenant_job_404(self):
        other = Organization.objects.create(name='Clínica B', timezone='UTC', tax_rate=Decimal('0'))
        job = ImportJob.objects.create(
            organization=other, entity_type='owner_pet', status='pending',
            source_columns=['Dueño'], rows=[['x']], mapping={},
        )
        res = self.client.get(f'/api/imports/{job.public_id}/')
        self.assertEqual(res.status_code, 404)

    def test_failed_pet_does_not_orphan_owner(self):
        # BLOCKER del review: owner nuevo creado en una fila cuyo pet falla NO
        # debe perderse ni dejar un owner huérfano en cache → la fila siguiente
        # que reusa ese owner debe poder crear su mascota.
        clash_owner = Owner.objects.create(organization=self.org, name='Previo', phone='8129999999')
        Pet.objects.create(organization=self.org, owner=clash_owner, name='Viejo', species='canino', legacy_id='DUP')
        text = (
            'Dueño,Teléfono,Mascota,Especie,Expediente\n'
            'Ana,8120000001,Nemo,Perro,DUP\n'   # pet.legacy_id DUP → falla el pet
            'Ana,8120000001,Rocky,Perro,\n'     # mismo owner → debe crear Rocky
        )
        pid = self._upload(text)
        self._set_mapping(pid)
        res = self.client.post(f'/api/imports/{pid}/commit/', format='json')
        result = res.data['result']
        # Ana se creó una vez y persiste; Rocky se creó; Nemo es error.
        self.assertEqual(result['created_owners'], 1)
        self.assertEqual(result['created_pets'], 1)
        self.assertEqual(result['error_rows'], 1)
        ana = Owner.objects.for_organization(self.org).get(phone='8120000001')
        self.assertEqual(ana.name, 'Ana')
        self.assertTrue(ana.pets.filter(name='Rocky').exists())
        # El mensaje de error NO filtra el nombre del constraint Postgres.
        msg = result['errors'][0]['message']
        self.assertNotIn('pet_legacy_id_unique_per_org', msg)

    def test_duplicate_target_mapping_rejected(self):
        text = 'Dueño,Apodo,Teléfono,Mascota,Especie\nJuan,Juanito,8112345678,Max,Perro\n'
        pid = self._upload(text)
        bad = {
            'Dueño': 'owner.name', 'Apodo': 'owner.name',  # colisión
            'Teléfono': 'owner.phone', 'Mascota': 'pet.name', 'Especie': 'pet.species',
        }
        self._set_mapping(pid, mapping=bad)
        res = self.client.post(f'/api/imports/{pid}/validate/', format='json')
        result = res.data['result']
        self.assertGreaterEqual(result['error_rows'], 1)
        self.assertTrue(any(e['field'] == 'mapping' for e in result['errors']))

    def test_validate_predicts_legacy_conflict(self):
        # Dos filas con el mismo pet.legacy_id dentro del archivo: validate debe
        # predecir el conflicto (preview honesto), no solo descubrirlo en commit.
        text = (
            'Dueño,Teléfono,Mascota,Especie,Expediente\n'
            'Juan,8112345678,Max,Perro,00231\n'
            'Ana,8113334444,Luna,Gato,00231\n'
        )
        pid = self._upload(text)
        self._set_mapping(pid)
        res = self.client.post(f'/api/imports/{pid}/validate/', format='json')
        result = res.data['result']
        self.assertEqual(result['created_pets'], 1)
        self.assertEqual(result['error_rows'], 1)
        self.assertTrue(any(e['field'] == 'pet.legacy_id' and e['row'] == 2 for e in result['errors']))

    def test_non_admin_forbidden(self):
        roles = _seed_roles(self.org)
        assistant = User.objects.create_user(
            username='asst_a', password='pass1234!', organization=self.org, role='ASSISTANT',
        )
        UserRole.objects.get_or_create(user=assistant, role=roles['ASSISTANT'])
        client = APIClient()
        client.force_authenticate(user=assistant)
        res = client.post(
            '/api/imports/',
            {'entity_type': 'owner_pet', 'file': _csv('Dueño\nJuan\n')},
            format='multipart',
        )
        self.assertEqual(res.status_code, 403)
