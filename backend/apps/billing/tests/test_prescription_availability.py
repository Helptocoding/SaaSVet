from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.billing.checkout_services import (
    CheckoutVersionConflict,
    create_prescription_supplement,
    dispense_prescription_into_checkout,
    get_or_create_primary_checkout_for_medical_record,
    post_checkout,
    void_invoice_terminal,
)
from apps.billing.models import PrescriptionFulfillmentEvent, StockDispositionEvent
from apps.billing.prescription_availability import (
    build_checkout_prescription_suggestions,
)
from apps.billing.services import process_refund
from apps.inventory.models import Presentation, Product, StockLot
from apps.medical_records.models import MedicalRecord
from apps.organizations.models import Organization, OrganizationSettings
from apps.patients.models import Owner, Pet
from apps.prescriptions.models import Prescription, PrescriptionItem
from apps.users.models import User


class PrescriptionAvailabilityContractTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Rx Availability', timezone='UTC')
        cls.user = User.objects.create_user(
            username='rx-availability-admin', password='x',
            organization=cls.org, role='ADMIN',
        )
        cls.owner = Owner.objects.create(
            name='Rx Owner', phone='5557000000', organization=cls.org,
        )
        cls.pet = Pet.objects.create(
            name='Rx Pet', species='dog', owner=cls.owner, organization=cls.org,
        )

    def setUp(self):
        self.case_number = 0
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def make_case(self, *, prescribed, factor, stock, legacy_stock=None,
                  tracks_lots=False):
        self.case_number += 1
        suffix = f'{self._testMethodName}-{self.case_number}'
        product = Product.objects.create(
            name=f'Product {suffix}', internal_code=suffix[:50],
            category='medication', base_unit='tablet',
            stock_quantity=Decimal(str(stock)), tracks_lots=tracks_lots,
            organization=self.org,
        )
        presentation = Presentation.objects.create(
            product=product, name='Commercial format', base_unit='tablet',
            conversion_factor=Decimal(str(factor)),
            stock=Decimal(str(stock if legacy_stock is None else legacy_stock)),
            sale_price=Decimal('10.00'), organization=self.org,
        )
        record = MedicalRecord.objects.create(
            pet=self.pet, veterinarian=self.user, organization=self.org,
            status=MedicalRecord.Status.CLOSED, closed_at=timezone.now(),
        )
        prescription = Prescription.objects.create(
            medical_record=record, veterinarian=self.user, pet=self.pet,
            organization=self.org,
        )
        rx_item = PrescriptionItem.objects.create(
            prescription=prescription, product=product, dose='contract dose',
            quantity=Decimal(str(prescribed)), organization=self.org,
        )
        checkout = get_or_create_primary_checkout_for_medical_record(
            record, owner=self.user,
        )
        checkout.refresh_from_db()
        return product, presentation, prescription, rx_item, checkout

    def projection(self, checkout):
        suggestion = build_checkout_prescription_suggestions(checkout)[0]
        return suggestion, suggestion['presentations'][0]

    def dispense(self, prescription, rx_item, presentation, checkout, *, quantity,
                 key='dispense-contract'):
        return dispense_prescription_into_checkout(
            prescription,
            [{
                'prescription_item_id': rx_item.pk,
                'presentation_id': presentation.pk,
                'quantity': quantity,
            }],
            self.user,
            expected_version=checkout.version,
            idempotency_key=f'{key}-{self._testMethodName}',
        )

    def test_factor_one_prescribed_two_has_max_two(self):
        _, _, _, _, checkout = self.make_case(
            prescribed=2, factor=1, stock=10,
        )
        suggestion, presentation = self.projection(checkout)
        self.assertEqual(suggestion['prescribed_quantity_base'], '2.0000')
        self.assertEqual(suggestion['fulfilled_quantity_base'], '0.0000')
        self.assertEqual(presentation['max_selectable_quantity'], 2)

    def test_smaller_base_remainder_than_commercial_format_is_valid_zero(self):
        _, _, _, _, checkout = self.make_case(
            prescribed=2, factor=100, stock=200,
        )
        suggestion, presentation = self.projection(checkout)
        self.assertEqual(suggestion['legal_remaining_quantity_base'], '2.0000')
        self.assertEqual(
            presentation['conversion_factor_base_per_presentation'], '100.0000',
        )
        self.assertEqual(presentation['clinical_max_additional_quantity'], 0)
        self.assertEqual(presentation['max_selectable_quantity'], 0)
        self.assertIn('below_presentation_size', presentation['blocking_reasons'])

    def test_product_stock_is_authority_when_presentation_stock_is_stale(self):
        _, _, _, _, checkout = self.make_case(
            prescribed=5, factor=1, stock=5, legacy_stock=0,
        )
        _, presentation = self.projection(checkout)
        self.assertEqual(presentation['available_stock_quantity_base'], '5.0000')
        self.assertEqual(presentation['max_selectable_quantity'], 5)

    def test_stock_caps_max_below_clinical_remaining(self):
        _, _, _, _, checkout = self.make_case(
            prescribed=5, factor=1, stock=2,
        )
        _, presentation = self.projection(checkout)
        self.assertEqual(presentation['clinical_max_additional_quantity'], 5)
        self.assertEqual(presentation['stock_max_additional_quantity'], 2)
        self.assertEqual(presentation['max_selectable_quantity'], 2)

    def test_lot_tracked_product_without_consumable_lot_has_zero(self):
        _, _, _, _, checkout = self.make_case(
            prescribed=5, factor=1, stock=5, tracks_lots=True,
        )
        _, presentation = self.projection(checkout)
        self.assertEqual(presentation['max_selectable_quantity'], 0)
        self.assertIn('no_consumable_lot', presentation['blocking_reasons'])

    def test_fulfilled_and_selected_are_distinct_and_not_double_counted(self):
        _, presentation, prescription, rx_item, checkout = self.make_case(
            prescribed=10, factor=1, stock=20,
        )
        checkout = self.dispense(
            prescription, rx_item, presentation, checkout, quantity=4,
            key='historical-four',
        )
        post_checkout(
            checkout, self.user, payment_method='cash',
            expected_version=checkout.version,
            idempotency_key=f'post-history-{self._testMethodName}',
        )
        supplement = create_prescription_supplement(
            prescription.medical_record,
            self.user,
            idempotency_key=f'supplement-{self._testMethodName}',
        )
        suggestion, availability = self.projection(supplement)
        self.assertEqual(suggestion['fulfilled_quantity_base'], '4.0000')
        self.assertEqual(suggestion['selected_quantity_base'], '0.0000')
        self.assertEqual(suggestion['legal_remaining_quantity_base'], '6.0000')
        self.assertEqual(availability['max_selectable_quantity'], 6)

        supplement = self.dispense(
            prescription, rx_item, presentation, supplement, quantity=2,
            key='current-two',
        )
        suggestion, availability = self.projection(supplement)
        self.assertEqual(suggestion['fulfilled_quantity_base'], '4.0000')
        self.assertEqual(suggestion['selected_quantity_base'], '2.0000')
        self.assertEqual(suggestion['legal_remaining_quantity_base'], '4.0000')
        self.assertEqual(availability['max_selectable_quantity'], 4)

    def test_dispense_is_whole_versioned_and_idempotent(self):
        _, presentation, prescription, rx_item, checkout = self.make_case(
            prescribed=5, factor=1, stock=10,
        )
        with self.assertRaises(ValidationError):
            dispense_prescription_into_checkout(
                prescription,
                [{
                    'prescription_item_id': rx_item.pk,
                    'presentation_id': presentation.pk,
                    'quantity': Decimal('0.5'),
                }],
                self.user,
                expected_version=checkout.version,
                idempotency_key=f'fractional-{self._testMethodName}',
            )

        expected_version = checkout.version
        first = self.dispense(
            prescription, rx_item, presentation, checkout, quantity=2,
            key='idempotent',
        )
        replay = dispense_prescription_into_checkout(
            prescription,
            [{
                'prescription_item_id': rx_item.pk,
                'presentation_id': presentation.pk,
                'quantity': 2,
            }],
            self.user,
            expected_version=expected_version,
            idempotency_key=f'idempotent-{self._testMethodName}',
        )
        self.assertEqual(first.pk, replay.pk)
        self.assertEqual(first.items.filter(prescription_item=rx_item).count(), 1)
        with self.assertRaises(CheckoutVersionConflict):
            dispense_prescription_into_checkout(
                prescription,
                [{
                    'prescription_item_id': rx_item.pk,
                    'presentation_id': presentation.pk,
                    'quantity': 1,
                }],
                self.user,
                expected_version=expected_version,
                idempotency_key=f'stale-version-{self._testMethodName}',
            )

    def test_dispense_api_requires_command_contract_and_reports_conflict(self):
        _, presentation, prescription, rx_item, checkout = self.make_case(
            prescribed=5, factor=1, stock=10,
        )
        url = f'/api/billing/prescriptions/{prescription.public_id}/dispense/'
        line = {
            'presentation': presentation.pk,
            'prescription_item': rx_item.pk,
            'quantity': 1,
        }
        missing = self.client.post(url, {'lines': [line]}, format='json')
        self.assertEqual(missing.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(checkout.items.filter(prescription_item=rx_item).exists())

        expected_version = checkout.version
        accepted = self.client.post(
            url,
            {'lines': [line], 'expected_version': expected_version},
            format='json',
            HTTP_X_IDEMPOTENCY_KEY=f'api-dispense-{self._testMethodName}',
        )
        self.assertEqual(accepted.status_code, status.HTTP_200_OK, accepted.data)
        replay = self.client.post(
            url,
            {'lines': [line], 'expected_version': expected_version},
            format='json',
            HTTP_X_IDEMPOTENCY_KEY=f'api-dispense-{self._testMethodName}',
        )
        self.assertEqual(replay.status_code, status.HTTP_200_OK, replay.data)
        self.assertEqual(checkout.items.filter(prescription_item=rx_item).count(), 1)

        stale = self.client.post(
            url,
            {'lines': [line], 'expected_version': expected_version},
            format='json',
            HTTP_X_IDEMPOTENCY_KEY=f'api-stale-{self._testMethodName}',
        )
        self.assertEqual(stale.status_code, status.HTTP_409_CONFLICT, stale.data)
        self.assertIn('current_version', stale.data)

    def test_post_splits_fefo_across_lots_and_fulfills_once(self):
        product, presentation, prescription, rx_item, checkout = self.make_case(
            prescribed=3, factor=1, stock=3, tracks_lots=True,
        )
        StockLot.objects.create(
            product=product, lot_number='EARLY',
            expiry_date=timezone.localdate() + timedelta(days=10),
            quantity_on_hand=Decimal('1'), organization=self.org,
        )
        StockLot.objects.create(
            product=product, lot_number='LATE',
            expiry_date=timezone.localdate() + timedelta(days=20),
            quantity_on_hand=Decimal('2'), organization=self.org,
        )
        checkout = self.dispense(
            prescription, rx_item, presentation, checkout, quantity=3,
            key='multi-lot',
        )
        invoice = post_checkout(
            checkout, self.user, payment_method='cash',
            expected_version=checkout.version,
            idempotency_key=f'post-multi-lot-{self._testMethodName}',
        )
        invoice_item = invoice.items.get(dispensed_from_prescription_item=rx_item)
        allocations = list(
            invoice_item.stock_allocations.order_by('lot__expiry_date')
            .values_list('lot__lot_number', 'quantity_base')
        )
        self.assertEqual(allocations, [
            ('EARLY', Decimal('1.0000')),
            ('LATE', Decimal('2.0000')),
        ])
        events = PrescriptionFulfillmentEvent.objects.filter(invoice_item=invoice_item)
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.get().quantity_delta, Decimal('3.0000'))
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, Decimal('0.0000'))

    def test_post_uses_line_factor_snapshot_after_catalog_edit(self):
        product, presentation, prescription, rx_item, checkout = self.make_case(
            prescribed=4, factor=2, stock=8,
        )
        checkout = self.dispense(
            prescription, rx_item, presentation, checkout, quantity=2,
            key='snapshot-factor',
        )
        checkout_item = checkout.items.get(prescription_item=rx_item)
        self.assertEqual(
            checkout_item.conversion_factor_snapshot, Decimal('2.0000'),
        )

        presentation.conversion_factor = Decimal('3')
        presentation.save(update_fields=['conversion_factor', 'updated_at'])
        invoice = post_checkout(
            checkout, self.user, payment_method='cash',
            expected_version=checkout.version,
            idempotency_key=f'post-snapshot-{self._testMethodName}',
        )

        invoice_item = invoice.items.get(dispensed_from_prescription_item=rx_item)
        self.assertEqual(
            invoice_item.conversion_factor_snapshot, Decimal('2.0000'),
        )
        self.assertEqual(
            invoice_item.stock_allocations.aggregate(total=Sum('quantity_base'))['total'],
            Decimal('4.0000'),
        )
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, Decimal('4.0000'))

    def test_refund_reverses_every_fefo_allocation_exactly(self):
        product, presentation, prescription, rx_item, checkout = self.make_case(
            prescribed=3, factor=1, stock=3, tracks_lots=True,
        )
        early = StockLot.objects.create(
            product=product, lot_number='REFUND-EARLY',
            expiry_date=timezone.localdate() + timedelta(days=10),
            quantity_on_hand=Decimal('1'), organization=self.org,
        )
        late = StockLot.objects.create(
            product=product, lot_number='REFUND-LATE',
            expiry_date=timezone.localdate() + timedelta(days=20),
            quantity_on_hand=Decimal('2'), organization=self.org,
        )
        checkout = self.dispense(
            prescription, rx_item, presentation, checkout, quantity=3,
            key='refund-multi-lot',
        )
        invoice = post_checkout(
            checkout, self.user, payment_method='cash',
            expected_version=checkout.version,
            idempotency_key=f'post-refund-multi-{self._testMethodName}',
        )
        invoice_item = invoice.items.get(dispensed_from_prescription_item=rx_item)

        credit_note = process_refund(
            invoice,
            self.user,
            credit_lines=[{
                'invoice_item': invoice_item.pk,
                'quantity': '3',
                'amount': '30.00',
                'disposition': 'restock',
            }],
            refund_lines=[{'method': 'cash', 'amount': '30.00'}],
            reason_code='customer_return',
            idempotency_key=f'refund-multi-{self._testMethodName}',
        )

        disposition_events = StockDispositionEvent.objects.filter(
            credit_note_item__credit_note=credit_note,
            kind='returned_restocked',
        ).order_by('allocation__lot__expiry_date')
        self.assertEqual(
            list(disposition_events.values_list(
                'allocation__lot__lot_number', 'quantity_base',
            )),
            [
                ('REFUND-EARLY', Decimal('1.0000')),
                ('REFUND-LATE', Decimal('2.0000')),
            ],
        )
        self.assertEqual(
            PrescriptionFulfillmentEvent.objects.filter(
                credit_note_item__credit_note=credit_note,
                kind='returned',
            ).count(),
            2,
        )
        product.refresh_from_db()
        early.refresh_from_db()
        late.refresh_from_db()
        self.assertEqual(product.stock_quantity, Decimal('3.0000'))
        self.assertEqual(early.quantity_on_hand, Decimal('1.0000'))
        self.assertEqual(late.quantity_on_hand, Decimal('2.0000'))

    def test_terminal_void_reverses_every_fefo_allocation(self):
        product, presentation, prescription, rx_item, checkout = self.make_case(
            prescribed=3, factor=1, stock=3, tracks_lots=True,
        )
        StockLot.objects.create(
            product=product, lot_number='VOID-EARLY',
            expiry_date=timezone.localdate() + timedelta(days=10),
            quantity_on_hand=Decimal('1'), organization=self.org,
        )
        StockLot.objects.create(
            product=product, lot_number='VOID-LATE',
            expiry_date=timezone.localdate() + timedelta(days=20),
            quantity_on_hand=Decimal('2'), organization=self.org,
        )
        checkout = self.dispense(
            prescription, rx_item, presentation, checkout, quantity=3,
            key='void-multi-lot',
        )
        settings, _ = OrganizationSettings.objects.get_or_create(
            organization=self.org,
        )
        settings.allow_post_unpaid = True
        settings.save(update_fields=['allow_post_unpaid'])
        invoice = post_checkout(
            checkout,
            self.user,
            expected_version=checkout.version,
            idempotency_key=f'post-void-multi-{self._testMethodName}',
            due_at=timezone.now() + timedelta(days=30),
            credit_reason='authorized_credit',
            obligation_evidence={
                'basis': 'customer_acknowledgement',
                'accepting_party': self.owner.name,
                'channel': 'in_person',
            },
        )
        invoice_item = invoice.items.get(dispensed_from_prescription_item=rx_item)

        void_invoice_terminal(
            invoice,
            self.user,
            reason_code='full_return',
            reason_notes='Retorno físico completo verificado.',
            dispositions=[{
                'invoice_item': invoice_item.pk,
                'outcome': 'returned_restocked',
            }],
            idempotency_key=f'void-multi-{self._testMethodName}',
        )

        returned = StockDispositionEvent.objects.filter(
            allocation__invoice_item=invoice_item,
            kind='returned_restocked',
        ).order_by('allocation__lot__expiry_date')
        self.assertEqual(
            list(returned.values_list(
                'allocation__lot__lot_number', 'quantity_base',
            )),
            [
                ('VOID-EARLY', Decimal('1.0000')),
                ('VOID-LATE', Decimal('2.0000')),
            ],
        )
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, Decimal('3.0000'))
