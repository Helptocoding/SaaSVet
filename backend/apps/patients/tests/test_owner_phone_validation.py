"""
Contrato de teléfono en alta MANUAL de cliente (OwnerSerializer).

Regla (Sprint import): el alta/edición manual exige teléfono de 10 dígitos —
el teléfono es comercialmente crítico para datos nuevos. La excepción de
teléfono opcional vive SOLO en el importador (apps/imports), que no pasa por
este serializer. Estos tests blindan que el contrato manual no se relaje por
accidente al tocar el flujo de import.
"""
from django.test import TestCase

from apps.patients.serializers import OwnerSerializer


class OwnerPhoneManualContractTests(TestCase):
    def test_manual_owner_requires_phone(self):
        s = OwnerSerializer(data={'name': 'Juan', 'phone': ''})
        self.assertFalse(s.is_valid())
        self.assertIn('phone', s.errors)

    def test_manual_owner_rejects_short_phone(self):
        s = OwnerSerializer(data={'name': 'Juan', 'phone': '123'})
        self.assertFalse(s.is_valid())
        self.assertIn('phone', s.errors)

    def test_manual_owner_accepts_ten_digit_phone(self):
        s = OwnerSerializer(data={'name': 'Juan', 'phone': '8112345678'})
        self.assertTrue(s.is_valid(), s.errors)
