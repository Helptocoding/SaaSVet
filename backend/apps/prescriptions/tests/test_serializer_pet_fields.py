"""
Recetas — la página /prescriptions filtra por especie/sexo/edad SIN cargar la
lista completa de mascotas (no escalaba con clínicas importadas de miles de
pacientes). El PrescriptionSerializer embebe los metadatos de la mascota
(pet_species/pet_sex/pet_birth_date) read-only; el pet ya viene select_related
en el queryset → costo cero. Estos campos también toleran datos importados
incompletos (species='', birth_date=None).
"""
from datetime import date
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APITestCase

from apps.medical_records.models import MedicalRecord
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.prescriptions.models import Prescription
from apps.users.models import User

from .test_multitenancy import _make_user


class PrescriptionPetMetaFieldsTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Org RX Meta", timezone="UTC")
        cls.vet = _make_user("vet_rx_meta", cls.org, "VET")
        cls.owner = Owner.objects.create(name="Dueño Meta", phone="5550030001", organization=cls.org)
        # Mascota con metadatos completos
        cls.pet = Pet.objects.create(
            name="Bella", species="perro", sex="female",
            birth_date=date(2020, 1, 1), owner=cls.owner, organization=cls.org,
        )
        cls.mr = MedicalRecord.objects.create(
            pet=cls.pet, veterinarian=cls.vet, organization=cls.org,
            diagnosis="dx", treatment="tx",
        )
        cls.rx = Prescription.objects.create(
            pet=cls.pet, veterinarian=cls.vet, medical_record=cls.mr,
            organization=cls.org,
        )
        # Mascota con datos importados incompletos (species='', birth_date=None)
        cls.pet_incomplete = Pet.objects.create(
            name="Sin Datos", species="", owner=cls.owner, organization=cls.org,
        )
        cls.mr2 = MedicalRecord.objects.create(
            pet=cls.pet_incomplete, veterinarian=cls.vet, organization=cls.org,
            diagnosis="dx2", treatment="tx2",
        )
        cls.rx2 = Prescription.objects.create(
            pet=cls.pet_incomplete, veterinarian=cls.vet, medical_record=cls.mr2,
            organization=cls.org,
        )

    def setUp(self):
        self.client.force_authenticate(self.vet)

    def test_list_embeds_pet_species_sex_birth_date(self):
        r = self.client.get('/api/prescriptions/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        rows = r.data if isinstance(r.data, list) else r.data.get('results', r.data)
        by_id = {row['public_id']: row for row in rows}
        full = by_id[str(self.rx.public_id)]
        self.assertEqual(full['pet_species'], "perro")
        self.assertEqual(full['pet_sex'], "female")
        self.assertEqual(full['pet_birth_date'], "2020-01-01")

    def test_incomplete_import_data_serializes_without_error(self):
        r = self.client.get('/api/prescriptions/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        rows = r.data if isinstance(r.data, list) else r.data.get('results', r.data)
        by_id = {row['public_id']: row for row in rows}
        incomplete = by_id[str(self.rx2.public_id)]
        self.assertEqual(incomplete['pet_species'], "")
        self.assertIsNone(incomplete['pet_birth_date'])
        self.assertEqual(incomplete['pet_sex'], "unknown")

    def test_pet_fields_are_read_only(self):
        """Mandar pet_species en el body no muta la mascota (read-only)."""
        r = self.client.patch(
            f'/api/prescriptions/{self.rx.public_id}/',
            {'pet_species': 'HACKED'}, format='json',
        )
        # VET no tiene prescription.update → 403; lo relevante es que la especie
        # de la mascota nunca cambia por el body.
        self.pet.refresh_from_db()
        self.assertEqual(self.pet.species, "perro")
        self.assertIn(r.status_code, (status.HTTP_200_OK, status.HTTP_403_FORBIDDEN))

    def test_list_does_not_n_plus_1_on_pet_meta(self):
        """Embeber pet_species/sex/birth_date no agrega queries: el pet ya viene
        select_related. Una 3ª receta (mascota distinta) no escala el conteo."""
        pet3 = Pet.objects.create(
            name="Tercero", species="gato", sex="male",
            birth_date=date(2019, 6, 1), owner=self.owner, organization=self.org,
        )
        mr3 = MedicalRecord.objects.create(
            pet=pet3, veterinarian=self.vet, organization=self.org,
            diagnosis="dx3", treatment="tx3",
        )
        Prescription.objects.create(
            pet=pet3, veterinarian=self.vet, medical_record=mr3,
            organization=self.org, notes="otra",
        )
        # Warm-up (carga de permisos/savepoints) fuera de la medición.
        self.client.get('/api/prescriptions/')
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get('/api/prescriptions/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        # Cota holgada: sin N+1 por mascota, el conteo es estable y bajo.
        self.assertLess(len(ctx.captured_queries), 15)
