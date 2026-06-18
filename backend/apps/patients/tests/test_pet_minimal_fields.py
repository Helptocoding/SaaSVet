"""
Alta MANUAL de mascota — datos mínimos (regla de producto piloto).

Requerido:  pet.name + owner.name + owner.phone (10 dígitos).
Opcional:   pet.species (''=pendiente), pet.birth_date, breed, sex, color.

Reglas finas:
- species: si viene con valor debe ser válida (SPECIES_CHOICES); vacía => ''.
- birth_date: opcional; si viene, no puede ser futura.
- teléfono SIGUE obligatorio en captura manual (no se relaja: ver
  test_owner_phone_validation.py y OwnerSerializer.validate_phone).

Estos tests son a nivel serializer (sin DB/auth): blindan el contrato de campos
mínimos sin acoplarse al endpoint. El aislamiento multi-tenant se cubre aparte en
test_pet_create_minimal_api.py.
"""
from datetime import date, timedelta
from types import SimpleNamespace

from django.test import TestCase

from apps.patients.serializers import PetSerializer


def _ctx():
    # organization solo necesita ser truthy para PetSerializer.validate(); el
    # is_valid() no persiste (no se llama .save()).
    user = SimpleNamespace(organization=SimpleNamespace(pk=1), is_authenticated=True)
    return {'request': SimpleNamespace(user=user, data={})}


def _data(**over):
    base = {
        'name': 'Firulais',
        'species': 'canino',
        'birth_date': '2020-01-01',
        'owner': {'name': 'Juan Perez', 'phone': '8112345678'},
    }
    base.update(over)
    return base


class PetMinimalFieldsTests(TestCase):
    def test_minimal_valid_data(self):
        s = PetSerializer(data=_data(), context=_ctx())
        self.assertTrue(s.is_valid(), s.errors)

    # ── birth_date opcional ──────────────────────────────────────────────
    def test_birth_date_absent_is_valid(self):
        d = _data()
        d.pop('birth_date')
        s = PetSerializer(data=d, context=_ctx())
        self.assertTrue(s.is_valid(), s.errors)
        self.assertIsNone(s.validated_data.get('birth_date'))

    def test_birth_date_null_is_valid(self):
        s = PetSerializer(data=_data(birth_date=None), context=_ctx())
        self.assertTrue(s.is_valid(), s.errors)
        self.assertIsNone(s.validated_data.get('birth_date'))

    def test_birth_date_future_rejected(self):
        future = (date.today() + timedelta(days=1)).isoformat()
        s = PetSerializer(data=_data(birth_date=future), context=_ctx())
        self.assertFalse(s.is_valid())
        self.assertIn('birth_date', s.errors)

    # ── species opcional (pendiente) ─────────────────────────────────────
    def test_species_blank_means_pending(self):
        s = PetSerializer(data=_data(species=''), context=_ctx())
        self.assertTrue(s.is_valid(), s.errors)
        self.assertEqual(s.validated_data.get('species', ''), '')

    def test_species_invalid_value_rejected(self):
        s = PetSerializer(data=_data(species='dinosaurio'), context=_ctx())
        self.assertFalse(s.is_valid())
        self.assertIn('species', s.errors)

    def test_species_value_normalized_lower(self):
        s = PetSerializer(data=_data(species='CANINO'), context=_ctx())
        self.assertTrue(s.is_valid(), s.errors)
        self.assertEqual(s.validated_data['species'], 'canino')

    # ── requeridos que NO se relajan ─────────────────────────────────────
    def test_name_still_required(self):
        s = PetSerializer(data=_data(name=''), context=_ctx())
        self.assertFalse(s.is_valid())
        self.assertIn('name', s.errors)

    def test_phone_still_required(self):
        d = _data()
        d['owner'] = {'name': 'Juan Perez', 'phone': ''}
        s = PetSerializer(data=d, context=_ctx())
        self.assertFalse(s.is_valid())
        self.assertIn('owner', s.errors)
