from decimal import Decimal

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

from django.apps import apps
from django.contrib.admin.sites import AdminSite
from django.db import connection
from django.test import SimpleTestCase, TestCase

from apps.inventory.serializers import PresentationCreateSerializer
from apps.inventory.models import Presentation, Product, StockMovement
from apps.inventory.admin import PresentationAdmin
from apps.organizations.models import Organization


class PresentationAliasTests(SimpleTestCase):
    def validate(self, values, partial=False):
        data = {'base_unit': 'piece', 'stock': '0', 'sale_price': '10'}
        data.update(values)
        serializer = PresentationCreateSerializer(data=data, partial=partial)
        serializer.is_valid()
        return serializer

    def test_one_or_both_names_match_without_rounding(self):
        for values in ({'quantity': '0.125'}, {'conversion_factor': '1.2345'},
                       {'quantity': '3', 'conversion_factor': '3'}):
            with self.subTest(values=values):
                serializer = self.validate(values)
                self.assertFalse(serializer.errors)
                self.assertEqual(serializer.validated_data['quantity'], serializer.validated_data['conversion_factor'])

    def test_conflicting_and_invalid_values_rejected(self):
        for values in ({'quantity': '2', 'conversion_factor': '3'},
                       {'quantity': '0'}, {'conversion_factor': '-1'},
                       {'quantity': None}, {'quantity': 'NaN'},
                       {'conversion_factor': 'Infinity'}, {'quantity': '1000000'},
                       {'quantity': '1.23456'}):
            with self.subTest(values=values):
                self.assertTrue(self.validate(values).errors)

    def test_partial_without_alias_does_not_change_it(self):
        serializer = PresentationCreateSerializer(data={'sale_price': '20'}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn('quantity', serializer.validated_data)
        self.assertNotIn('conversion_factor', serializer.validated_data)

    def test_default_both_are_one(self):
        serializer = self.validate({})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        instance = Presentation(**serializer.validated_data)
        self.assertEqual(instance.quantity, Decimal('1'))
        self.assertEqual(instance.conversion_factor, Decimal('1'))

    def test_backfill_preflight_stops_before_update_on_invalid_factor(self):
        rows = Mock()
        rows.exclude.return_value.count.return_value = 2
        model = SimpleNamespace(_base_manager=Mock())
        model._base_manager.using.return_value = rows
        historical_apps = SimpleNamespace(get_model=lambda *args: model)
        backfill = import_module('apps.inventory.migrations.0029_presentation_alias_backfill').backfill_alias
        with self.assertRaisesRegex(RuntimeError, '2 factores inválidos'):
            backfill(historical_apps, SimpleNamespace(connection=SimpleNamespace(alias='isolated')))
        self.assertEqual(rows.exclude.call_count, 1)
        rows.exclude.return_value.update.assert_not_called()


class AliasBackfillTests(TestCase):
    def test_backfill_is_idempotent_and_preserves_other_fields(self):
        org = Organization.objects.create(name='Synthetic')
        product = Product.objects.create(organization=org, name='Synthetic', internal_code='syn',
                                         base_unit='piece', stock_quantity=Decimal('8'), min_stock=Decimal('2'))
        pres = Presentation.objects.create(organization=org, product=product, name='Synthetic',
                                           base_unit='piece', quantity=1, conversion_factor=Decimal('1.2345'),
                                           sale_price=10, stock=3, min_stock=2)
        movement = StockMovement.objects.create(organization=org, product=product, presentation=pres,
                                                quantity=8, quantity_unit='base', movement_type='in')
        before_product = Product.all_objects.filter(pk=product.pk).values().get()
        before_movement = StockMovement.all_objects.filter(pk=movement.pk).values().get()
        before_pres = Presentation.all_objects.filter(pk=pres.pk).values().get()
        backfill = import_module('apps.inventory.migrations.0029_presentation_alias_backfill').backfill_alias
        for _ in range(2):
            backfill(apps, SimpleNamespace(connection=connection))
            after = Presentation.all_objects.filter(pk=pres.pk).values().get()
            self.assertEqual(after.pop('quantity'), Decimal('1.2345'))
            expected = dict(before_pres)
            expected.pop('quantity')
            self.assertEqual(after, expected)
            self.assertEqual(Product.all_objects.filter(pk=product.pk).values().get(), before_product)
            self.assertEqual(StockMovement.all_objects.filter(pk=movement.pk).values().get(), before_movement)

    def test_admin_syncs_only_an_explicit_factor_change(self):
        org = Organization.objects.create(name='Synthetic admin')
        product = Product.objects.create(organization=org, name='Synthetic', internal_code='admin')
        pres = Presentation.objects.create(organization=org, product=product, name='Unit',
                                           base_unit='piece', quantity=1, conversion_factor=3, sale_price=10)
        admin = PresentationAdmin(Presentation, AdminSite())
        self.assertIn('quantity', admin.readonly_fields)
        admin.save_model(None, pres, SimpleNamespace(changed_data=['sale_price']), True)
        pres.refresh_from_db()
        self.assertEqual(pres.quantity, 1)
        pres.conversion_factor = Decimal('1.2345')
        admin.save_model(None, pres, SimpleNamespace(changed_data=['conversion_factor']), True)
        pres.refresh_from_db()
        self.assertEqual(pres.quantity, Decimal('1.2345'))
