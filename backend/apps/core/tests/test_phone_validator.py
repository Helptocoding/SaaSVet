"""Regla de teléfono MX — dueño único (`apps.core.validators`).

Protege lo que hacía que el campo aceptara basura antes:
- `"5"` se guardaba como `"5"`.
- `"no sé"` se guardaba como `""` EN SILENCIO (el ADMIN creía haber terminado).
- `1111111111` pasaba y el dato seguía siendo inútil.

Es la base del hito `has_clinic_contact`: si el campo no puede contener basura,
*existir* equivale a *ser válido* y el endpoint de activación solo mira `bool()`.
"""
from django.test import SimpleTestCase
from rest_framework import serializers

from apps.core.validators import (
    PHONE_FILLER_ERROR,
    PHONE_LENGTH_ERROR,
    is_filler_phone,
    phone_digits,
    validate_mx_phone,
)


class PhoneDigitsTests(SimpleTestCase):

    def test_strips_formatting(self):
        for raw, expected in [
            ("55 1234 5678", "5512345678"),
            ("(55) 1234-5678", "5512345678"),
            ("+52 55 1234 5678", "525512345678"),
            ("no sé", ""),
            ("", ""),
            (None, ""),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(phone_digits(raw), expected)


class IsFillerPhoneTests(SimpleTestCase):

    def test_rejects_repeated_and_sequential(self):
        # `1234567890` es el caso que se escapa si el paso no se compara mod 10
        # (el salto 9→0 vale −9, no +1).
        for digits in ["1111111111", "0000000000", "9999999999",
                       "1234567890", "0123456789", "9876543210", "0987654321"]:
            with self.subTest(digits=digits):
                self.assertTrue(is_filler_phone(digits))

    def test_accepts_real_looking_numbers(self):
        # Un número mexicano real repite dígitos o rompe la progresión: el check
        # NO puede rechazarlos (solo existen 3 secuencias estrictas de 10 dígitos).
        for digits in ["5512345678", "8112345670", "5599887766", "3313579246"]:
            with self.subTest(digits=digits):
                self.assertFalse(is_filler_phone(digits))

    def test_only_applies_to_ten_digits(self):
        self.assertFalse(is_filler_phone("111"))


class ValidateMxPhoneTests(SimpleTestCase):

    def test_normalizes_valid_input(self):
        self.assertEqual(validate_mx_phone("(55) 1234-5678"), "5512345678")

    def test_rejects_short_number(self):
        with self.assertRaises(serializers.ValidationError) as ctx:
            validate_mx_phone("5")
        self.assertIn(PHONE_LENGTH_ERROR, str(ctx.exception))

    def test_rejects_text_instead_of_saving_blank(self):
        """El bug original: texto sin dígitos se guardaba como '' sin avisar."""
        for raw in ["no sé", "pendiente", "-"]:
            with self.subTest(raw=raw):
                with self.assertRaises(serializers.ValidationError):
                    validate_mx_phone(raw, allow_blank=True)

    def test_rejects_filler(self):
        with self.assertRaises(serializers.ValidationError) as ctx:
            validate_mx_phone("1111111111")
        self.assertIn(PHONE_FILLER_ERROR, str(ctx.exception))

    def test_blank_allowed_only_when_opted_in(self):
        self.assertEqual(validate_mx_phone("", allow_blank=True), "")
        self.assertEqual(validate_mx_phone(None, allow_blank=True), "")
        self.assertEqual(validate_mx_phone("   ", allow_blank=True), "")
        with self.assertRaises(serializers.ValidationError):
            validate_mx_phone("")
