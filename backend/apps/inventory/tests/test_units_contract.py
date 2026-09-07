from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from apps.inventory.models import Presentation, Product
from apps.inventory.units import validated_conversion_factor
from apps.organizations.models import Organization


class PresentationUnitContractTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Unit Contract', timezone='UTC')
        cls.product = Product.objects.create(
            name='Unit Product', internal_code='UNIT-CONTRACT', category='medication',
            base_unit='tablet', organization=cls.org,
        )

    def test_runtime_validation_rejects_non_finite_and_non_positive_factors(self):
        for value in ('0', '-1', 'NaN', 'Infinity', '-Infinity'):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validated_conversion_factor(value)

    def test_database_constraint_rejects_zero_factor(self):
        presentation = Presentation.all_objects.create(
            product=self.product, name='Zero target', base_unit='tablet',
            quantity=Decimal('1'), conversion_factor=Decimal('1'),
            sale_price=Decimal('10'), organization=self.org,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Presentation.all_objects.filter(pk=presentation.pk).update(
                conversion_factor=Decimal('0'),
            )

    def test_database_constraint_rejects_nan_factor(self):
        presentation = Presentation.all_objects.create(
            product=self.product, name='NaN target', base_unit='tablet',
            quantity=Decimal('1'), conversion_factor=Decimal('1'),
            sale_price=Decimal('10'), organization=self.org,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    'UPDATE inventory_presentation '
                    'SET conversion_factor = %s WHERE id = %s',
                    [Decimal('NaN'), presentation.pk],
                )
