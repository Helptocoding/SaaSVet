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


def _assert_extra(tc, entries, expected):
    """Verifica datos del sistema anterior (Fase D, decisión final PO).

    expected = [(label, value, source_column), …] en orden. Cada entrada además
    DEBE traer `imported_at` (fecha del proceso de importación). El timestamp
    exacto no se compara (es now()); solo que exista y no sea vacío.
    """
    tc.assertEqual(len(entries), len(expected), entries)
    for entry, (label, value, source) in zip(entries, expected):
        tc.assertEqual(entry['label'], label)
        tc.assertEqual(entry['value'], value)
        tc.assertEqual(entry['source_column'], source)
        tc.assertIn('imported_at', entry)
        tc.assertTrue(entry['imported_at'])


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

    def test_automap_priority_and_no_double_assign(self):
        # Cliente/Dueño/Propietario → nombre cliente; Mascota/Paciente/Animal →
        # nombre mascota; y NUNCA dos columnas al mismo destino.
        s = suggest_mapping(['Propietario', 'Dueño', 'Mascota', 'Animal'], 'owner_pet')
        self.assertEqual(s.get('Propietario'), 'owner.name')
        self.assertNotEqual(s.get('Dueño'), 'owner.name')   # destino ya tomado
        self.assertEqual(s.get('Mascota'), 'pet.name')
        self.assertNotEqual(s.get('Animal'), 'pet.name')
        assigned = [v for v in s.values() if v]
        self.assertEqual(len(assigned), len(set(assigned)))  # sin destinos repetidos


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

    def test_upload_xlsx_parses(self):
        # Path XLSX end-to-end (requiere openpyxl). El teléfono va como número en
        # la celda → debe leerse "8112345678", no "8112345678.0".
        import io
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["Dueño", "Teléfono", "Mascota", "Especie"])
        ws.append(["Juan Pérez", 8112345678, "Max", "Perro"])
        buf = io.BytesIO()
        wb.save(buf)
        upload = SimpleUploadedFile(
            "clientes.xlsx", buf.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        res = self.client.post(
            '/api/imports/', {'entity_type': 'owner_pet', 'file': upload}, format='multipart',
        )
        self.assertEqual(res.status_code, 201, res.data)
        job = ImportJob.objects.get(public_id=res.data['public_id'])
        self.assertEqual(job.source_columns, ["Dueño", "Teléfono", "Mascota", "Especie"])
        self.assertEqual(len(job.rows), 1)
        self.assertEqual(job.rows[0][0], "Juan Pérez")
        self.assertEqual(job.rows[0][1], "8112345678")

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
        # El owner solo se cuenta cuando el pet entra (Fase 1: fila = unidad lógica).
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
        self.assertEqual(result['created_owners'], 1)
        self.assertEqual(result['reused_owners'], 0)
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

    def test_unrecognized_species_warns_not_errors(self):
        # Especie opcional: una especie no reconocida NO bloquea — se importa como
        # pendiente ('') con warning. No se asigna especie por defecto en masa.
        text = (
            'Dueño,Teléfono,Mascota,Especie,Expediente\n'
            'Juan,8112345678,Max,Perro,00231\n'
            'Ana,8113334444,Nemo,dinosaurio,00232\n'
        )
        pid = self._upload(text)
        self._set_mapping(pid)
        res = self.client.post(f'/api/imports/{pid}/commit/', format='json')
        result = res.data['result']
        self.assertEqual(result['created_pets'], 2)
        self.assertEqual(result['error_rows'], 0)
        self.assertTrue(any(w['row'] == 2 and w['field'] == 'pet.species' for w in result['warnings']))
        nemo = Pet.objects.for_organization(self.org).get(name='Nemo')
        self.assertEqual(nemo.species, '')

    def test_missing_species_imports_as_pending(self):
        # Columna especie no mapeada → mascota se importa igual, especie pendiente.
        pid = self._upload('Dueño,Teléfono,Mascota,Expediente\nJuan,8112345678,Max,00231\n')
        self._set_mapping(pid, mapping={
            'Dueño': 'owner.name', 'Teléfono': 'owner.phone',
            'Mascota': 'pet.name', 'Expediente': 'pet.legacy_id',
        })
        res = self.client.post(f'/api/imports/{pid}/commit/', format='json')
        result = res.data['result']
        self.assertEqual(result['created_pets'], 1)
        self.assertEqual(result['error_rows'], 0)
        self.assertTrue(any(w['field'] == 'pet.species' for w in result['warnings']))
        self.assertEqual(Pet.objects.for_organization(self.org).get(name='Max').species, '')

    def test_legacy_id_unique_per_org_conflict_reported(self):
        # Dos owners distintos (teléfonos distintos) con el mismo pet.legacy_id.
        # Fase 1: la 2ª fila se omite sin crear owner → skipped_conflicts, no error_row.
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
        self.assertEqual(result['created_owners'], 1)
        self.assertEqual(result['skipped_conflicts'], 1)
        self.assertEqual(result['error_rows'], 0)
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
        # Fase 1: el pet legacy_id conflictivo se detecta ANTES de crear el owner.
        # Ana solo se crea cuando Rocky (sin conflicto) entra. Nemo es skipped_conflict.
        clash_owner = Owner.objects.create(organization=self.org, name='Previo', phone='8129999999')
        Pet.objects.create(organization=self.org, owner=clash_owner, name='Viejo', species='canino', legacy_id='DUP')
        text = (
            'Dueño,Teléfono,Mascota,Especie,Expediente\n'
            'Ana,8120000001,Nemo,Perro,DUP\n'   # pet.legacy_id DUP → conflicto, owner NO se crea
            'Ana,8120000001,Rocky,Perro,\n'     # mismo owner, pet sin conflicto → owner + pet creados
        )
        pid = self._upload(text)
        self._set_mapping(pid)
        res = self.client.post(f'/api/imports/{pid}/commit/', format='json')
        result = res.data['result']
        # Ana se creó una vez y persiste; Rocky se creó; Nemo es conflicto (no error).
        self.assertEqual(result['created_owners'], 1)
        self.assertEqual(result['created_pets'], 1)
        self.assertEqual(result['skipped_conflicts'], 1)
        self.assertEqual(result['error_rows'], 0)
        ana = Owner.objects.for_organization(self.org).get(phone='8120000001')
        self.assertEqual(ana.name, 'Ana')
        self.assertTrue(ana.pets.filter(name='Rocky').exists())
        # El mensaje de conflicto tiene mensaje humano, no el constraint Postgres.
        msg = result['conflicts'][0]['message']
        self.assertNotIn('pet_legacy_id_unique_per_org', msg)
        self.assertNotIn('legacy_id', msg.lower())

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
        # predecir el conflicto como skipped_conflicts, no como error_row. La 2ª
        # fila no crea owner → preview honesto.
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
        self.assertEqual(result['created_owners'], 1)
        self.assertEqual(result['skipped_conflicts'], 1)
        self.assertEqual(result['error_rows'], 0)
        self.assertTrue(any(c['scope'] == 'pet' and c['row'] == 2 for c in result['conflicts']))

    def test_extra_data_imported_as_ordered_list(self):
        # Columnas sin campo del sistema → owner.extra / pet.extra → lista ordenada
        # de {label, value, source_column, imported_at}, preservando el orden de
        # columnas. source_column = nombre ORIGINAL del Excel/CSV (no se pierde).
        text = (
            'Dueño,Teléfono,Mascota,Especie,Fecha Alta,Observaciones,Facebook\n'
            'Juan,8112345678,Max,Perro,2018-01-01,Nervioso,fb/juan\n'
        )
        pid = self._upload(text)
        self._set_mapping(pid, mapping={
            'Dueño': 'owner.name', 'Teléfono': 'owner.phone',
            'Mascota': 'pet.name', 'Especie': 'pet.species',
            'Fecha Alta': 'pet.extra', 'Observaciones': 'pet.extra',
            'Facebook': 'owner.extra',
        })
        self.client.post(f'/api/imports/{pid}/commit/', format='json')

        pet = Pet.objects.for_organization(self.org).get(name='Max')
        _assert_extra(self, pet.extra_data, [
            ('Fecha Alta', '2018-01-01', 'Fecha Alta'),
            ('Observaciones', 'Nervioso', 'Observaciones'),
        ])
        owner = Owner.objects.for_organization(self.org).get(name='Juan')
        _assert_extra(self, owner.extra_data, [('Facebook', 'fb/juan', 'Facebook')])

    def test_extra_data_allows_repeated_labels(self):
        # Dos columnas homónimas "Comentario" → dos entradas distintas (lista).
        text = (
            'Dueño,Teléfono,Mascota,Especie,Comentario,Comentario\n'
            'Juan,8112345678,Max,Perro,A,B\n'
        )
        pid = self._upload(text)
        self._set_mapping(pid, mapping={
            'Dueño': 'owner.name', 'Teléfono': 'owner.phone',
            'Mascota': 'pet.name', 'Especie': 'pet.species',
            'Comentario': 'pet.extra',
        })
        self.client.post(f'/api/imports/{pid}/commit/', format='json')
        pet = Pet.objects.for_organization(self.org).get(name='Max')
        _assert_extra(self, pet.extra_data, [
            ('Comentario', 'A', 'Comentario'),
            ('Comentario', 'B', 'Comentario'),
        ])

    def test_extra_targets_exempt_from_dedup_but_system_fields_not(self):
        # Muchas columnas → pet.extra OK (sin error de "mismo campo").
        text = 'Dueño,Teléfono,Mascota,Especie,C1,C2\nJuan,8112345678,Max,Perro,x,y\n'
        pid = self._upload(text)
        self._set_mapping(pid, mapping={
            'Dueño': 'owner.name', 'Teléfono': 'owner.phone',
            'Mascota': 'pet.name', 'Especie': 'pet.species',
            'C1': 'pet.extra', 'C2': 'pet.extra',
        })
        res = self.client.post(f'/api/imports/{pid}/validate/', format='json')
        self.assertEqual(res.data['result']['error_rows'], 0, res.data['result'])

        # Pero dos columnas al MISMO campo del sistema sigue siendo error.
        pid2 = self._upload('A,B,Mascota,Especie\nx,y,Max,Perro\n')
        self._set_mapping(pid2, mapping={
            'A': 'owner.name', 'B': 'owner.name',  # colisión 1:1
            'Mascota': 'pet.name', 'Especie': 'pet.species',
        })
        res2 = self.client.post(f'/api/imports/{pid2}/validate/', format='json')
        self.assertTrue(any(e['field'] == 'mapping' for e in res2.data['result']['errors']))

    def test_extra_data_custom_label_rename_keeps_source_column(self):
        # El valor del mapping puede ser {target, label} para renombrar el dato
        # visible; renombrar el label NO cambia source_column: la columna original
        # ("Color fav") se conserva como referencia (de dónde vino el dato).
        text = 'Dueño,Teléfono,Mascota,Especie,Color fav\nJuan,8112345678,Max,Perro,Rojo\n'
        pid = self._upload(text)
        self._set_mapping(pid, mapping={
            'Dueño': 'owner.name', 'Teléfono': 'owner.phone',
            'Mascota': 'pet.name', 'Especie': 'pet.species',
            'Color fav': {'target': 'pet.extra', 'label': 'Color favorito'},
        })
        self.client.post(f'/api/imports/{pid}/commit/', format='json')
        pet = Pet.objects.for_organization(self.org).get(name='Max')
        # label renombrado, pero source_column = la columna original del archivo.
        _assert_extra(self, pet.extra_data, [('Color favorito', 'Rojo', 'Color fav')])

    def test_extra_data_value_truncated_to_500(self):
        long_val = 'x' * 600
        text = f'Dueño,Teléfono,Mascota,Especie,Nota\nJuan,8112345678,Max,Perro,{long_val}\n'
        pid = self._upload(text)
        self._set_mapping(pid, mapping={
            'Dueño': 'owner.name', 'Teléfono': 'owner.phone',
            'Mascota': 'pet.name', 'Especie': 'pet.species', 'Nota': 'pet.extra',
        })
        self.client.post(f'/api/imports/{pid}/commit/', format='json')
        pet = Pet.objects.for_organization(self.org).get(name='Max')
        self.assertEqual(len(pet.extra_data[0]['value']), 500)

    def test_extra_data_exposed_in_serializer(self):
        text = 'Dueño,Teléfono,Mascota,Especie,Nota\nJuan,8112345678,Max,Perro,hola\n'
        pid = self._upload(text)
        self._set_mapping(pid, mapping={
            'Dueño': 'owner.name', 'Teléfono': 'owner.phone',
            'Mascota': 'pet.name', 'Especie': 'pet.species', 'Nota': 'pet.extra',
        })
        self.client.post(f'/api/imports/{pid}/commit/', format='json')
        pet = Pet.objects.for_organization(self.org).get(name='Max')
        res = self.client.get(f'/api/pets/{pet.public_id}/')
        self.assertEqual(res.status_code, 200)
        _assert_extra(self, res.data['extra_data'], [('Nota', 'hola', 'Nota')])

    def test_extra_data_is_read_only_via_pet_patch(self):
        # extra_data lo escribe SOLO el importador: la edición manual de la ficha
        # no puede modificarlo (read_only en el serializer). PATCH lo ignora.
        text = 'Dueño,Teléfono,Mascota,Especie,Nota\nJuan,8112345678,Max,Perro,hola\n'
        pid = self._upload(text)
        self._set_mapping(pid, mapping={
            'Dueño': 'owner.name', 'Teléfono': 'owner.phone',
            'Mascota': 'pet.name', 'Especie': 'pet.species', 'Nota': 'pet.extra',
        })
        self.client.post(f'/api/imports/{pid}/commit/', format='json')
        pet = Pet.objects.for_organization(self.org).get(name='Max')
        # PATCH válido de la ficha (el front siempre manda owner) intentando colar
        # extra_data → el serializer lo ignora (read_only): no se puede editar.
        res = self.client.patch(
            f'/api/pets/{pet.public_id}/',
            {
                'name': 'Max', 'species': 'canino',
                'owner': {'name': 'Juan', 'phone': '8112345678'},
                'extra_data': [{'label': 'hackeado', 'value': 'x'}],
            },
            format='json',
        )
        self.assertEqual(res.status_code, 200, res.data)
        pet.refresh_from_db()
        _assert_extra(self, pet.extra_data, [('Nota', 'hola', 'Nota')])

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

    # ── Fase 1: Integridad del commit (fila = unidad lógica) ──────────────

    def test_idempotent_reimport_creates_zero_owners(self):
        # Subir + commit un archivo; re-subir el MISMO archivo y commit →
        # 0 owners nuevos, 0 pets nuevos, N skipped. Cero owners huérfanos en DB.
        text = (
            'Dueño,Teléfono,Mascota,Especie,Expediente\n'
            'Juan,8112345678,Max,Perro,00231\n'
            'Ana,8113334444,Luna,Gato,00232\n'
        )
        pid1 = self._upload(text)
        self._set_mapping(pid1)
        res1 = self.client.post(f'/api/imports/{pid1}/commit/', format='json')
        self.assertEqual(res1.data['result']['created_pets'], 2)
        self.assertEqual(res1.data['result']['created_owners'], 2)
        owners_before = Owner.objects.for_organization(self.org).count()
        pets_before = Pet.objects.for_organization(self.org).count()

        # Re-subir el MISMO archivo.
        pid2 = self._upload(text)
        self._set_mapping(pid2)
        res2 = self.client.post(f'/api/imports/{pid2}/commit/', format='json')
        result = res2.data['result']
        self.assertEqual(result['created_owners'], 0)
        self.assertEqual(result['created_pets'], 0)
        self.assertGreater(result['skipped_conflicts'] + result['skipped_duplicates'], 0)
        # Cero owners/pets nuevos en la DB.
        self.assertEqual(Owner.objects.for_organization(self.org).count(), owners_before)
        self.assertEqual(Pet.objects.for_organization(self.org).count(), pets_before)

    def test_owner_shared_valid_and_conflict_row(self):
        # Fila A: pet nuevo + owner X creado. Fila B: mismo owner X + pet con
        # legacy_id conflictivo → owner X NO se duplica, pet A existe, pet B omitido.
        # Pre-crear un pet con legacy_id que choque con la fila B.
        pre_owner = Owner.objects.create(organization=self.org, name='Previo', phone='8119999999')
        Pet.objects.create(organization=self.org, owner=pre_owner, name='Viejo', species='canino', legacy_id='CLASH')
        text = (
            'Dueño,Teléfono,Mascota,Especie,Expediente\n'
            'Ana,8112345678,Rocky,Perro,\n'      # fila A: pet válido
            'Ana,8112345678,Nemo,Perro,CLASH\n'  # fila B: mismo owner, pet conflictivo
        )
        pid = self._upload(text)
        self._set_mapping(pid)
        res = self.client.post(f'/api/imports/{pid}/commit/', format='json')
        result = res.data['result']
        self.assertEqual(result['created_pets'], 1)
        self.assertEqual(result['created_owners'], 1)
        self.assertEqual(result['reused_owners'], 0)
        self.assertEqual(result['skipped_conflicts'], 1)
        # Owner Ana existe UNA SOLA VEZ.
        self.assertEqual(Owner.objects.for_organization(self.org).filter(phone='8112345678').count(), 1)
        ana = Owner.objects.for_organization(self.org).get(phone='8112345678')
        self.assertTrue(ana.pets.filter(name='Rocky').exists())
        self.assertFalse(ana.pets.filter(name='Nemo').exists())

    def test_all_conflict_rows_create_zero_owners(self):
        # Archivo donde TODAS las filas tienen pet conflictivo →
        # created_owners == 0 y sin nuevos owners en DB.
        existing = Owner.objects.create(organization=self.org, name='Juan', phone='8112345678')
        Pet.objects.create(organization=self.org, owner=existing, name='Max', species='canino', legacy_id='00231')
        Pet.objects.create(organization=self.org, owner=existing, name='Nemo', species='canino', legacy_id='00232')
        owners_before = Owner.objects.for_organization(self.org).count()
        text = (
            'Dueño,Teléfono,Mascota,Especie,Expediente\n'
            'Juan,8112345678,Max,Perro,00233\n'    # nombre normalizado duplicado (Max ya existe)
            'Juan,8112345678,Nemo,Perro,00234\n'   # nombre normalizado duplicado (Nemo ya existe)
        )
        pid = self._upload(text)
        self._set_mapping(pid)
        res = self.client.post(f'/api/imports/{pid}/commit/', format='json')
        result = res.data['result']
        self.assertEqual(result['created_owners'], 0)
        self.assertEqual(result['created_pets'], 0)
        self.assertGreater(result['skipped_duplicates'], 0)
        self.assertEqual(Owner.objects.for_organization(self.org).count(), owners_before)

    def test_validate_preview_honest_on_reimport(self):
        # validate_job sobre un archivo ya importado debe predecir
        # created_owners == 0 (no el bug de "40 clientes nuevos").
        text = (
            'Dueño,Teléfono,Mascota,Especie,Expediente\n'
            'Juan,8112345678,Max,Perro,00231\n'
            'Ana,8113334444,Luna,Gato,00232\n'
        )
        pid1 = self._upload(text)
        self._set_mapping(pid1)
        self.client.post(f'/api/imports/{pid1}/commit/', format='json')

        # Re-subir y validar (sin commit).
        pid2 = self._upload(text)
        self._set_mapping(pid2)
        res = self.client.post(f'/api/imports/{pid2}/validate/', format='json')
        result = res.data['result']
        # Preview honesto: no predice owners nuevos porque los pets son conflicto.
        self.assertEqual(result['created_pets'], 0)
        self.assertEqual(result['created_owners'], 0)
        self.assertGreater(result['skipped_conflicts'] + result['skipped_duplicates'], 0)

    # ── Fase 2: Clasificación + contexto del existente ──────────────────

    def test_conflicts_bring_incoming_and_existing_context(self):
        # Un pet con legacy_id duplicado debe traer incoming + existing.public_id
        # + existing.pet_name + owner_name en el conflict.
        existing_owner = Owner.objects.create(organization=self.org, name='Juan Pérez', phone='8112345678')
        Pet.objects.create(organization=self.org, owner=existing_owner, name='Max', species='canino', legacy_id='00231')
        text = (
            'Dueño,Teléfono,Mascota,Especie,Expediente\n'
            'Ana,8113334444,Luna,Gato,00231\n'  # mismo legacy_id, distinto owner
        )
        pid = self._upload(text)
        self._set_mapping(pid)
        res = self.client.post(f'/api/imports/{pid}/validate/', format='json')
        result = res.data['result']
        self.assertEqual(result['skipped_conflicts'], 1)
        conflict = result['conflicts'][0]
        self.assertEqual(conflict['type'], 'duplicate_legacy_id')
        self.assertEqual(conflict['scope'], 'pet')
        self.assertEqual(conflict['incoming']['pet_name'], 'Luna')
        self.assertEqual(conflict['incoming']['owner_name'], 'Ana')
        self.assertEqual(conflict['existing']['pet_name'], 'Max')
        self.assertEqual(conflict['existing']['owner_name'], 'Juan Pérez')
        self.assertTrue(conflict['existing']['public_id'])
        # match_confidence: different pet_name, different owner_name → uncertain
        self.assertEqual(conflict['match_confidence'], 'uncertain')

    def test_match_confidence_high_when_names_match(self):
        # Mismo dueño (normalizado), misma mascota → high confidence.
        # Usamos un nombre de mascota DIFERENTE para que no lo atrape el dedup
        # por nombre antes del check de legacy_id.
        existing_owner = Owner.objects.create(organization=self.org, name='Juan Pérez', phone='8112345678')
        Pet.objects.create(organization=self.org, owner=existing_owner, name='Max', species='canino', legacy_id='00231')
        text = (
            'Dueño,Teléfono,Mascota,Especie,Expediente\n'
            'Juan Perez,8112345678,Bella,Perro,00231\n'  # distinto nombre, mismo legacy_id
        )
        pid = self._upload(text)
        self._set_mapping(pid)
        res = self.client.post(f'/api/imports/{pid}/validate/', format='json')
        result = res.data['result']
        # El legacy_id choca (ya existe), no el nombre.
        self.assertEqual(result['skipped_conflicts'], 1)
        conflict = result['conflicts'][0]
        # owner_name normalizado coincide (juan perez == juan perez) pero pet_name no
        # → uncertain (plan: high solo si AMBOS coinciden)
        self.assertEqual(conflict['match_confidence'], 'uncertain')

    def test_conflict_not_in_blocking(self):
        # duplicate_legacy_id cae en conflicts[], NO en blocking[].
        owner = Owner.objects.create(organization=self.org, name='Juan', phone='8112345678')
        Pet.objects.create(organization=self.org, owner=owner, name='Max', species='canino', legacy_id='00231')
        text = (
            'Dueño,Teléfono,Mascota,Especie,Expediente\n'
            'Ana,8113334444,Luna,Gato,00231\n'
        )
        pid = self._upload(text)
        self._set_mapping(pid)
        res = self.client.post(f'/api/imports/{pid}/validate/', format='json')
        result = res.data['result']
        self.assertGreater(len(result['conflicts']), 0)
        # blocking[] solo tiene datos faltantes/imposibles, no legacy conflicts.
        self.assertFalse(any('legacy' in b.get('field', '') for b in result['blocking']))

    def test_no_pk_exposed_in_result(self):
        # existing nunca debe traer PK (id entero), solo public_id (UUID).
        existing_owner = Owner.objects.create(organization=self.org, name='Juan', phone='8112345678')
        pet = Pet.objects.create(organization=self.org, owner=existing_owner, name='Max', species='canino', legacy_id='00231')
        text = (
            'Dueño,Teléfono,Mascota,Especie,Expediente\n'
            'Ana,8113334444,Luna,Gato,00231\n'
        )
        pid = self._upload(text)
        self._set_mapping(pid)
        res = self.client.post(f'/api/imports/{pid}/validate/', format='json')
        result = res.data['result']
        conflict = result['conflicts'][0]
        self.assertNotIn('id', conflict.get('existing', {}))
        self.assertNotIn('pk', conflict.get('existing', {}))
        self.assertEqual(conflict['existing']['public_id'], str(pet.public_id))
