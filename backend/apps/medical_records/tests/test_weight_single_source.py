"""M03 (orden 7): el peso sale solo de VitalSigns.

`MedicalRecord.weight` queda como columna sin lectores ni escritores hasta su
RemoveField. Estas pruebas fijan que ningún camino vuelve a leerla o escribirla.
"""
from datetime import timedelta
from importlib import import_module

from django.apps import apps as django_apps
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.medical_records.models import (
    MedicalRecord, VitalSigns, _get_last_weight, get_current_weight,
)
from apps.medical_records.serializers import MedicalRecordSerializer
from apps.medical_records.tests.test_vitals import _make_user
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet

BACKFILL = import_module(
    'apps.medical_records.migrations.0030_backfill_vitals_weight_from_record').backfill


class WeightSingleSourceTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Org Peso M03", timezone="UTC")
        cls.vet = _make_user("vet_peso_m03", cls.org, "VET")
        owner = Owner.objects.create(name="Owner", phone="5512345601", organization=cls.org)
        cls.pet = Pet.objects.create(name="Bruno", species="dog", owner=owner, organization=cls.org)

    def _record(self, **kwargs):
        return MedicalRecord.objects.create(
            pet=self.pet, veterinarian=self.vet, organization=self.org, **kwargs)

    def _legacy_weight(self, record, value):
        MedicalRecord.all_objects.filter(pk=record.pk).update(weight=value)

    def _vital(self, record, weight, minutes_ago=0):
        return VitalSigns.objects.create(
            medical_record=record, organization=self.org, weight=weight,
            recorded_at=timezone.now() - timedelta(minutes=minutes_ago))

    def test_serializer_weight_is_read_only(self):
        self.assertTrue(MedicalRecordSerializer().fields['weight'].read_only)
        self.assertNotIn('force_weight', MedicalRecordSerializer().fields)

    def test_patch_weight_does_not_write_the_legacy_column(self):
        record = self._record()
        self.client.force_authenticate(self.vet)
        r = self.client.patch(
            f"/api/medical-records/{record.public_id}/", {"weight": "9.99"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        record.refresh_from_db()
        self.assertIsNone(record.weight)
        self.assertIsNone(r.data["weight"])

    def test_api_weight_comes_from_latest_vital_with_weight(self):
        record = self._record()
        self._legacy_weight(record, "7.00")
        self._vital(record, "4.20", minutes_ago=30)
        self._vital(record, None, minutes_ago=5)
        self.client.force_authenticate(self.vet)
        r = self.client.get(f"/api/medical-records/{record.public_id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        self.assertEqual(r.data["weight"], "4.20")
        listed = self.client.get(f"/api/medical-records/?pet={self.pet.public_id}")
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.content)
        rows = listed.data["results"] if isinstance(listed.data, dict) else listed.data
        self.assertEqual([row["weight"] for row in rows], ["4.20"])

    def test_helpers_ignore_the_legacy_column(self):
        record = self._record()
        self._legacy_weight(record, "7.00")
        record.refresh_from_db()
        self.assertIsNone(_get_last_weight(self.pet))
        self.assertIsNone(get_current_weight(record))
        self._vital(record, "5.10", minutes_ago=10)
        self._vital(record, None)
        self.assertEqual(str(_get_last_weight(self.pet)), "5.10")
        self.assertEqual(str(get_current_weight(record)), "5.10")

    def test_backfill_copies_only_records_without_vital_weight(self):
        legacy_only = self._record()
        self._legacy_weight(legacy_only, "6.40")
        already = self._record()
        self._legacy_weight(already, "9.00")
        self._vital(already, "8.80")
        without = self._record()

        BACKFILL(django_apps, None)
        BACKFILL(django_apps, None)

        copied = VitalSigns.objects.get(medical_record=legacy_only)
        self.assertEqual(str(copied.weight), "6.40")
        self.assertIsNone(copied.recorded_by_id)
        self.assertEqual(copied.recorded_at, legacy_only.created_at)
        self.assertEqual(VitalSigns.objects.filter(medical_record=already).count(), 1)
        self.assertFalse(VitalSigns.objects.filter(medical_record=without).exists())
