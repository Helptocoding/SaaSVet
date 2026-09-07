from decimal import Decimal
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.test import TestCase
from django.utils import timezone

from apps.billing.checkout_services import (
    abandon_checkout,
    adjust_replacement_exposure,
    add_checkout_item,
    assign_replacement_owner,
    attest_external_prescription,
    complete_no_charge,
    create_direct_sale_checkout,
    create_prescription_supplement,
    get_or_create_primary_checkout_for_medical_record,
    post_checkout,
    record_clinical_charge_delta,
    reprice_clinical_charge,
    issue_checkout_estimate,
    open_checkout_dispute,
    resolve_checkout_dispute,
    resolve_collection_case,
    decide_prescription_item,
    dispense_prescription_into_checkout,
    update_checkout_item,
    void_invoice_terminal,
    void_and_prepare_replacement,
    waive_replacement_exposure,
)
from apps.billing.models import (
    Checkout, CheckoutDispute, ClinicalChargeEntry, CollectionCase, CommandReceipt,
    ExternalPrescriptionAttestation,
    Invoice, Payment, PrescriptionFulfillmentEvent, RefundPayment, RefundReversal,
    Service, StockDispositionEvent,
)
from apps.billing.services import process_refund, reverse_credit_note
from apps.inventory.models import Presentation, Product
from apps.medical_records.models import MedicalRecord, MedicalRecordService
from apps.organizations.models import Organization, OrganizationSettings
from apps.patients.models import Owner, Pet
from apps.prescriptions.models import Prescription, PrescriptionItem
from apps.users.models import User


class AuthoritativeCheckoutFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Checkout Org', timezone='UTC')
        cls.user = User.objects.create_user(
            username='checkout-admin', password='x', organization=cls.org, role='ADMIN',
        )
        cls.owner = Owner.objects.create(
            name='Cliente Checkout', phone='5559000000', organization=cls.org,
        )
        cls.pet = Pet.objects.create(
            name='Paciente Checkout', species='dog', owner=cls.owner, organization=cls.org,
        )
        cls.service = Service.objects.create(
            name='Consulta', base_price=Decimal('100.00'), organization=cls.org,
        )
        cls.product = Product.objects.create(
            name='Alimento', internal_code='CHECKOUT-1', category='food',
            base_unit='unit', stock_quantity=Decimal('10'), organization=cls.org,
        )
        cls.presentation = Presentation.objects.create(
            product=cls.product, name='Unidad', base_unit='unit',
            conversion_factor=Decimal('1'), stock=Decimal('10'),
            sale_price=Decimal('50.00'), organization=cls.org,
        )

    def test_direct_sale_pay_emits_one_paid_invoice_and_replay_is_safe(self):
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=None, user=self.user,
        )
        add_checkout_item(
            checkout, self.user, presentation=self.presentation, quantity=Decimal('2'),
        )
        checkout.refresh_from_db()
        invoice = post_checkout(
            checkout, self.user, payment_method='cash',
            expected_version=checkout.version, idempotency_key='sale-1',
        )
        replay = post_checkout(
            checkout, self.user, payment_method='cash',
            expected_version=checkout.version, idempotency_key='sale-1',
        )
        self.assertEqual(invoice.pk, replay.pk)
        self.assertEqual(invoice.status, 'paid')
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 1)
        checkout.refresh_from_db()
        self.assertEqual(checkout.completion_kind, 'posted_paid')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('8.0000'))

    def test_open_dispute_blocks_financial_actions_until_accepted(self):
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=self.pet, user=self.user,
        )
        item = add_checkout_item(checkout, self.user, service=self.service)
        checkout.refresh_from_db()
        dispute = open_checkout_dispute(
            checkout, self.user, item_ids=[item.pk], statement='No reconoce el importe.',
            owner=self.user, review_due_at=timezone.now() + timedelta(days=2),
            expected_version=checkout.version, idempotency_key='dispute-open-1',
        )
        checkout.refresh_from_db()
        self.assertEqual(checkout.operational_hold, 'dispute')
        with self.assertRaises(ValidationError):
            post_checkout(
                checkout, self.user, payment_method='cash',
                expected_version=checkout.version, idempotency_key='dispute-pay-blocked',
            )
        resolved = resolve_checkout_dispute(
            dispute, self.user, resolution='accepted', reason='Cliente acepta tras revisión.',
            resolution_evidence={'channel': 'in_person'},
            expected_version=checkout.version, idempotency_key='dispute-resolve-1',
        )
        self.assertEqual(resolved.status, 'resolved')
        checkout.refresh_from_db()
        invoice = post_checkout(
            checkout, self.user, payment_method='cash',
            expected_version=checkout.version, idempotency_key='dispute-pay-after-accept',
        )
        self.assertEqual(invoice.status, 'paid')

    def test_dispute_full_adjustment_completes_no_charge_without_invoice(self):
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=self.pet, user=self.user,
        )
        item = add_checkout_item(checkout, self.user, service=self.service)
        checkout.refresh_from_db()
        dispute = open_checkout_dispute(
            checkout, self.user, item_ids=[item.pk], statement='Precio no aceptado.',
            owner=self.user, review_due_at=timezone.now() + timedelta(days=2),
            expected_version=checkout.version, idempotency_key='dispute-open-2',
        )
        checkout.refresh_from_db()
        resolve_checkout_dispute(
            dispute, self.user, resolution='adjusted_or_waived',
            reason='Condonación comercial autorizada.',
            adjustments=[{'item_id': item.pk, 'amount': '100.00'}],
            expected_version=checkout.version, idempotency_key='dispute-resolve-2',
        )
        checkout.refresh_from_db()
        self.assertEqual(checkout.lifecycle, 'completed')
        self.assertEqual(checkout.completion_kind, 'no_charge')
        self.assertEqual(checkout.total, Decimal('0.00'))
        self.assertFalse(Invoice.objects.filter(checkout=checkout).exists())
        self.assertEqual(CheckoutDispute.objects.get(pk=dispute.pk).resolution, 'adjusted_or_waived')

    def test_consultation_close_materializes_checkout_not_invoice(self):
        record = MedicalRecord.objects.create(
            pet=self.pet, veterinarian=self.user, organization=self.org,
            status=MedicalRecord.Status.OPEN,
        )
        used = MedicalRecordService.objects.create(
            medical_record=record, service=self.service,
            quantity=Decimal('1'), organization=self.org,
        )
        record_clinical_charge_delta(
            used, delta=Decimal('1'), user=self.user,
            mutation_key='test-service-create',
        )
        record.status = MedicalRecord.Status.CLOSED
        record.closed_at = timezone.now()
        record.save(update_fields=['status', 'closed_at', 'updated_at'])
        checkout = get_or_create_primary_checkout_for_medical_record(record, owner=self.user)
        self.assertEqual(Invoice.objects.count(), 0)
        line = checkout.items.get()
        self.assertEqual(line.medical_record_service_id, used.pk)
        self.assertEqual(line.unit_price, Decimal('100.00'))

    def test_zero_checkout_completes_without_financial_document(self):
        record = MedicalRecord.objects.create(
            pet=self.pet, veterinarian=self.user, organization=self.org,
            status=MedicalRecord.Status.CLOSED,
            closed_at='2026-09-03T12:00:00Z',
        )
        checkout = get_or_create_primary_checkout_for_medical_record(record, owner=self.user)
        checkout = complete_no_charge(
            checkout, self.user, reason='no_billable_items',
            expected_version=checkout.version, idempotency_key='zero-1',
        )
        self.assertEqual(checkout.completion_kind, 'no_charge')
        self.assertFalse(Invoice.objects.exists())

    def test_posted_invoice_can_only_be_corrected_with_protected_replacement(self):
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=None, user=self.user,
        )
        add_checkout_item(checkout, self.user, service=self.service)
        checkout.refresh_from_db()
        settings, _ = OrganizationSettings.objects.get_or_create(organization=self.org)
        settings.allow_post_unpaid = True
        settings.save(update_fields=['allow_post_unpaid'])
        invoice = post_checkout(
            checkout, self.user, expected_version=checkout.version,
            idempotency_key='post-1', due_at=timezone.now() + timedelta(days=30),
            credit_reason='authorized_credit', obligation_evidence={
                'basis': 'customer_acknowledgement',
                'accepting_party': self.owner.name, 'channel': 'in_person',
            },
        )
        replacement = void_and_prepare_replacement(
            invoice, self.user, idempotency_key='replace-1',
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'voided')
        self.assertTrue(replacement.items.get().required_replacement_baseline)
        with self.assertRaises(ValidationError):
            abandon_checkout(
                replacement, self.user, reason='try',
                expected_version=replacement.version, idempotency_key='abandon-replacement',
            )

    def test_replacement_adjustment_and_assignment_are_audited_and_keep_positive_exposure(self):
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=None, user=self.user,
        )
        add_checkout_item(checkout, self.user, service=self.service)
        checkout.refresh_from_db()
        settings, _ = OrganizationSettings.objects.get_or_create(organization=self.org)
        settings.allow_post_unpaid = True
        settings.save(update_fields=['allow_post_unpaid'])
        invoice = post_checkout(
            checkout, self.user, expected_version=checkout.version,
            idempotency_key='replacement-adjust-post',
            due_at=timezone.now() + timedelta(days=30),
            credit_reason='authorized_credit',
            obligation_evidence={
                'basis': 'customer_acknowledgement',
                'accepting_party': self.owner.name, 'channel': 'in_person',
            },
        )
        replacement = void_and_prepare_replacement(
            invoice, self.user, idempotency_key='replacement-adjust-void',
        )
        baseline = replacement.items.get(required_replacement_baseline=True)
        replacement = adjust_replacement_exposure(
            replacement, self.user, item_id=baseline.pk, amount='10.00',
            reason_code='pricing_correction', note='Corrección autorizada de precio.',
            expected_version=replacement.version, idempotency_key='replacement-adjust-1',
        )
        self.assertEqual(replacement.total, Decimal('90.00'))
        with self.assertRaises(ValidationError):
            adjust_replacement_exposure(
                replacement, self.user, item_id=baseline.pk, amount='90.00',
                reason_code='pricing_correction', note='No puede llegar a cero.',
                expected_version=replacement.version, idempotency_key='replacement-adjust-zero',
            )
        replacement = assign_replacement_owner(
            replacement, self.user, owner=self.user,
            correction_due_at=timezone.now() + timedelta(days=3),
            reason_code='follow_up', expected_version=replacement.version,
            idempotency_key='replacement-owner-1',
        )
        self.assertEqual(replacement.owner_id, self.user.pk)
        self.assertTrue(replacement.events.filter(kind='replacement_exposure_adjusted').exists())
        self.assertTrue(replacement.events.filter(kind='replacement_owner_assigned').exists())

    def test_first_price_governs_increment_until_explicit_reprice(self):
        record = MedicalRecord.objects.create(
            pet=self.pet, veterinarian=self.user, organization=self.org,
            status=MedicalRecord.Status.OPEN,
        )
        used = MedicalRecordService.objects.create(
            medical_record=record, service=self.service,
            quantity=Decimal('1'), organization=self.org,
        )
        first = record_clinical_charge_delta(
            used, delta=Decimal('1'), user=self.user, mutation_key='price-cycle-1',
        )
        self.service.base_price = Decimal('120.00')
        self.service.save(update_fields=['base_price', 'updated_at'])
        used.quantity = Decimal('2')
        used.save(update_fields=['quantity', 'updated_at'])
        same_cycle = record_clinical_charge_delta(
            used, delta=Decimal('1'), user=self.user, mutation_key='price-cycle-2',
        )
        self.assertEqual(first.pk, same_cycle.pk)
        same_cycle.refresh_from_db()
        self.assertEqual(same_cycle.current_quantity, Decimal('2'))
        self.assertEqual(same_cycle.unit_price, Decimal('100.00'))

        successor = reprice_clinical_charge(
            used, self.user, new_unit_price=Decimal('130.00'), reason='authorized_reprice',
            expected_quantity=Decimal('2'), idempotency_key='reprice-1',
        )
        self.assertEqual(successor.current_quantity, Decimal('2'))
        self.assertEqual(successor.unit_price, Decimal('130.00'))
        self.assertEqual(ClinicalChargeEntry.objects.filter(medical_record=record).count(), 2)
        first.refresh_from_db()
        self.assertEqual(first.lifecycle, 'closed')
        self.assertEqual(first.current_quantity, Decimal('0'))

        record.status = MedicalRecord.Status.CLOSED
        record.closed_at = timezone.now()
        record.save(update_fields=['status', 'closed_at', 'updated_at'])
        checkout = get_or_create_primary_checkout_for_medical_record(record, owner=self.user)
        line = checkout.items.get()
        self.assertEqual(line.quantity, Decimal('2'))
        self.assertEqual(line.unit_price, Decimal('130.00'))

    def test_estimate_is_an_immutable_checkout_version_snapshot(self):
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=None, user=self.user,
        )
        item = add_checkout_item(checkout, self.user, service=self.service)
        checkout.refresh_from_db()
        estimate = issue_checkout_estimate(
            checkout, self.user, expected_version=checkout.version,
            idempotency_key='estimate-1',
        )
        original_snapshot = estimate.snapshot
        update_checkout_item(item, self.user, quantity=Decimal('2'))
        estimate.refresh_from_db()
        checkout.refresh_from_db()
        self.assertEqual(estimate.snapshot, original_snapshot)
        self.assertEqual(estimate.snapshot['total'], '100.00')
        self.assertEqual(checkout.total, Decimal('200.00'))

    def test_pending_prescription_must_be_declined_or_selected_before_post(self):
        record = MedicalRecord.objects.create(
            pet=self.pet, veterinarian=self.user, organization=self.org,
            status=MedicalRecord.Status.OPEN,
        )
        used = MedicalRecordService.objects.create(
            medical_record=record, service=self.service,
            quantity=Decimal('1'), organization=self.org,
        )
        record_clinical_charge_delta(
            used, delta=Decimal('1'), user=self.user, mutation_key='rx-service',
        )
        prescription = Prescription.objects.create(
            medical_record=record, veterinarian=self.user, pet=self.pet,
            organization=self.org,
        )
        rx_item = PrescriptionItem.objects.create(
            prescription=prescription, product=self.product, dose='1 cada 24 h',
            quantity=Decimal('2'), organization=self.org,
        )
        record.status = MedicalRecord.Status.CLOSED
        record.closed_at = timezone.now()
        record.save(update_fields=['status', 'closed_at', 'updated_at'])
        checkout = get_or_create_primary_checkout_for_medical_record(record, owner=self.user)
        with self.assertRaises(ValidationError):
            post_checkout(
                checkout, self.user, payment_method='cash',
                expected_version=checkout.version, idempotency_key='pending-rx',
            )
        checkout.refresh_from_db()
        decide_prescription_item(
            checkout, rx_item, self.user, decision='declined',
            decline_reason='client_declined', expected_version=checkout.version,
        )
        checkout.refresh_from_db()
        invoice = post_checkout(
            checkout, self.user, payment_method='cash',
            expected_version=checkout.version, idempotency_key='declined-rx',
        )
        self.assertEqual(invoice.status, 'paid')
        self.assertFalse(PrescriptionFulfillmentEvent.objects.exists())

    def test_external_rx_attestation_is_revision_scoped_and_survives_line_change(self):
        self.product.requires_prescription = True
        self.product.save(update_fields=['requires_prescription', 'updated_at'])
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=None, user=self.user,
        )
        item = add_checkout_item(
            checkout, self.user, presentation=self.presentation,
            rx_attested=True, prescriber_name='Dra. Externa', quantity=Decimal('1'),
        )
        first_attestation = ExternalPrescriptionAttestation.objects.get()
        update_checkout_item(item, self.user, quantity=Decimal('2'))
        checkout.refresh_from_db()
        with self.assertRaises(ValidationError):
            post_checkout(
                checkout, self.user, payment_method='cash',
                expected_version=checkout.version, idempotency_key='stale-attestation',
            )
        add_checkout_item(
            checkout, self.user, presentation=self.presentation,
            rx_attested=True, prescriber_name='Dra. Externa', quantity=Decimal('1'),
        )
        checkout.refresh_from_db()
        invoice = post_checkout(
            checkout, self.user, payment_method='cash',
            expected_version=checkout.version, idempotency_key='fresh-attestation',
        )
        self.assertEqual(ExternalPrescriptionAttestation.objects.count(), 2)
        self.assertEqual(first_attestation.quantity, Decimal('1'))
        self.assertEqual(
            invoice.items.get().external_rx_attestation.regulatory_revision, 3,
        )

    def test_external_rx_attestation_correction_is_append_only_and_supersedes(self):
        self.product.requires_prescription = True
        self.product.save(update_fields=['requires_prescription', 'updated_at'])
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=None, user=self.user,
        )
        item = add_checkout_item(
            checkout, self.user, presentation=self.presentation,
            rx_attested=True, prescriber_name='Dra. Original', quantity='1',
        )
        original = ExternalPrescriptionAttestation.objects.get()
        checkout.refresh_from_db()
        corrected = attest_external_prescription(
            item, self.user, prescriber_name='Dra. Corregida',
            correction_reason='Nombre capturado incorrectamente.',
            expected_version=checkout.version, idempotency_key='attestation-correction-1',
        )
        self.assertEqual(ExternalPrescriptionAttestation.objects.count(), 2)
        self.assertEqual(corrected.supersedes_attestation_id, original.pk)
        self.assertEqual(corrected.regulatory_revision, 2)
        item.refresh_from_db()
        self.assertEqual(item.regulatory_revision, 2)

    def test_declined_prescription_can_be_dispensed_later_via_supplement(self):
        record = MedicalRecord.objects.create(
            pet=self.pet, veterinarian=self.user, organization=self.org,
            status=MedicalRecord.Status.CLOSED, closed_at=timezone.now(),
        )
        prescription = Prescription.objects.create(
            medical_record=record, veterinarian=self.user, pet=self.pet,
            organization=self.org,
        )
        rx_item = PrescriptionItem.objects.create(
            prescription=prescription, product=self.product, dose='1 cada 24 h',
            quantity=Decimal('2'), organization=self.org,
        )
        primary = get_or_create_primary_checkout_for_medical_record(record, owner=self.user)
        decide_prescription_item(
            primary, rx_item, self.user, decision='declined',
            decline_reason='client_declined', expected_version=primary.version,
        )
        primary.refresh_from_db()
        complete_no_charge(
            primary, self.user, reason='no_billable_items',
            expected_version=primary.version, idempotency_key='primary-no-charge-rx',
        )
        supplement = create_prescription_supplement(
            record, self.user, idempotency_key='supplement-1',
        )
        selection = supplement.prescription_selections.get()
        self.assertEqual(selection.eligible_remaining_at_open, Decimal('2'))
        supplement = dispense_prescription_into_checkout(
            prescription, [{
                'prescription_item_id': rx_item.pk,
                'presentation_id': self.presentation.pk, 'quantity': '1',
            }], self.user, expected_version=supplement.version,
            idempotency_key='supplement-dispense-1',
        )
        invoice = post_checkout(
            supplement, self.user, payment_method='cash',
            expected_version=supplement.version, idempotency_key='supplement-pay-1',
        )
        self.assertEqual(invoice.status, 'paid')
        self.assertEqual(
            PrescriptionFulfillmentEvent.objects.filter(
                prescription_item=rx_item,
            ).aggregate(total=Sum('quantity_delta'))['total'],
            Decimal('1.0000'),
        )
        second = create_prescription_supplement(
            record, self.user, idempotency_key='supplement-2',
        )
        self.assertEqual(
            second.prescription_selections.get().eligible_remaining_at_open,
            Decimal('1.0000'),
        )

    def test_collection_case_exists_only_for_enforced_dispute_and_can_be_withdrawn(self):
        settings, _ = OrganizationSettings.objects.get_or_create(organization=self.org)
        settings.allow_post_unpaid = True
        settings.save(update_fields=['allow_post_unpaid'])
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=self.pet, user=self.user,
        )
        item = add_checkout_item(checkout, self.user, service=self.service)
        checkout.refresh_from_db()
        dispute = open_checkout_dispute(
            checkout, self.user, item_ids=[item.pk], statement='Cargo objetado.',
            owner=self.user, review_due_at=timezone.now() + timedelta(days=2),
            expected_version=checkout.version, idempotency_key='collection-dispute-open',
        )
        checkout.refresh_from_db()
        resolved = resolve_checkout_dispute(
            dispute, self.user, resolution='enforced_under_terms',
            reason='Contrato de crédito vigente.',
            due_at=timezone.now() + timedelta(days=30),
            obligation_evidence={
                'basis': 'preauthorized_terms', 'reference': 'TERMS-1',
                'accepting_party': self.owner.name, 'channel': 'signed_terms',
            }, expected_version=checkout.version,
            idempotency_key='collection-dispute-enforce',
        )
        case = CollectionCase.objects.get(invoice=resolved.invoice)
        self.assertEqual(case.owner_id, dispute.owner_id)
        case = resolve_collection_case(
            case, self.user, resolution='customer_withdrew',
            reason='El cliente retiró la objeción.',
            idempotency_key='collection-withdraw',
        )
        self.assertEqual(case.status, 'resolved')
        self.assertEqual(case.resolution, 'customer_withdrew')

    def test_financial_child_identity_is_receipt_scoped_across_command_kinds(self):
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=None, user=self.user,
        )
        add_checkout_item(checkout, self.user, presentation=self.presentation)
        checkout.refresh_from_db()
        invoice = post_checkout(
            checkout, self.user, payment_method='cash',
            expected_version=checkout.version, idempotency_key='shared-key',
        )
        line = invoice.items.get()
        credit_note = process_refund(
            invoice, self.user,
            credit_lines=[{
                'invoice_item': line.pk, 'quantity': '1.00',
                'amount': '50.00', 'disposition': 'retained',
            }],
            refund_lines=[{'method': 'cash', 'amount': '50.00'}],
            reason_code='goodwill', idempotency_key='shared-key',
        )
        replay = process_refund(
            invoice, self.user,
            credit_lines=[{
                'invoice_item': line.pk, 'quantity': '1.00',
                'amount': '50.00', 'disposition': 'retained',
            }],
            refund_lines=[{'method': 'cash', 'amount': '50.00'}],
            reason_code='goodwill', idempotency_key='shared-key',
        )
        self.assertEqual(credit_note.pk, replay.pk)
        self.assertEqual(CommandReceipt.objects.filter(idempotency_key='shared-key').count(), 2)
        payment = Payment.objects.get()
        refund = RefundPayment.objects.get()
        self.assertNotEqual(payment.idempotency_key, refund.idempotency_key)
        self.assertNotEqual(payment.command_receipt_id, refund.command_receipt_id)

        reverse_credit_note(
            credit_note, self.user, reason_code='operator_error',
            reason_notes='Devolución capturada por error', idempotency_key='reverse-1',
        )
        reverse_credit_note(
            credit_note, self.user, reason_code='operator_error',
            reason_notes='Devolución capturada por error', idempotency_key='reverse-1',
        )
        self.assertEqual(RefundReversal.objects.count(), 1)
        process_refund(
            invoice, self.user,
            credit_lines=[{
                'invoice_item': line.pk, 'quantity': '1',
                'amount': '50', 'disposition': 'retained',
            }],
            refund_lines=[{'method': 'cash', 'amount': '50'}],
            reason_code='goodwill', idempotency_key='refund-after-reversal',
        )
        self.assertEqual(RefundPayment.objects.count(), 2)

    def test_payment_replay_canonicalizes_equivalent_split_line_order(self):
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=None, user=self.user,
        )
        add_checkout_item(checkout, self.user, service=self.service)
        checkout.refresh_from_db()
        first = post_checkout(
            checkout, self.user,
            payment_lines=[
                {'method': 'cash', 'amount': '60.0'},
                {'method': 'card', 'amount': '40.00', 'reference': 'AUTH-1'},
            ],
            expected_version=checkout.version, idempotency_key='split-order',
        )
        replay = post_checkout(
            checkout, self.user,
            payment_lines=[
                {'reference': 'AUTH-1', 'amount': Decimal('40'), 'method': 'card'},
                {'amount': '60.00', 'method': 'cash'},
            ],
            expected_version=checkout.version, idempotency_key='split-order',
        )
        self.assertEqual(first.pk, replay.pk)
        self.assertEqual(Payment.objects.filter(invoice=first).count(), 2)

    def test_refund_restock_is_not_financially_reversible_automatically(self):
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=None, user=self.user,
        )
        add_checkout_item(checkout, self.user, presentation=self.presentation)
        checkout.refresh_from_db()
        invoice = post_checkout(
            checkout, self.user, payment_method='cash',
            expected_version=checkout.version, idempotency_key='restock-pay',
        )
        line = invoice.items.get()
        credit_note = process_refund(
            invoice, self.user,
            credit_lines=[{
                'invoice_item': line.pk, 'quantity': '1',
                'amount': '50', 'disposition': 'restock',
            }],
            refund_lines=[{'method': 'cash', 'amount': '50'}],
            reason_code='customer_return', idempotency_key='restock-refund',
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('10.0000'))
        with self.assertRaises(ValidationError):
            reverse_credit_note(
                credit_note, self.user, reason_code='operator_error',
                reason_notes='No debe revertir inventario automáticamente.',
                idempotency_key='restock-reverse',
            )

    def test_retained_replacement_reissues_without_second_stock_exit(self):
        settings, _ = OrganizationSettings.objects.get_or_create(organization=self.org)
        settings.allow_post_unpaid = True
        settings.save(update_fields=['allow_post_unpaid'])
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=None, user=self.user,
        )
        add_checkout_item(checkout, self.user, presentation=self.presentation)
        checkout.refresh_from_db()
        invoice = post_checkout(
            checkout, self.user, expected_version=checkout.version,
            idempotency_key='retained-post', due_at=timezone.now() + timedelta(days=5),
            credit_reason='authorized_credit', obligation_evidence={
                'basis': 'customer_acknowledgement', 'accepting_party': self.owner.name,
                'channel': 'in_person',
            },
        )
        original_line = invoice.items.get()
        replacement = void_and_prepare_replacement(
            invoice, self.user,
            dispositions=[{
                'invoice_item': original_line.pk, 'outcome': 'goods_retained',
            }],
            idempotency_key='retained-replacement',
        )
        baseline = replacement.items.get()
        self.assertTrue(baseline.required_replacement_baseline)
        self.assertEqual(baseline.fulfillment_source, 'already_fulfilled')
        replacement_invoice = post_checkout(
            replacement, self.user, payment_method='cash',
            expected_version=replacement.version, idempotency_key='retained-reissue',
        )
        self.assertEqual(replacement_invoice.supersedes_invoice_id, invoice.pk)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('9.0000'))

    def test_replacement_waiver_requires_allowlisted_reason_and_evidence(self):
        settings, _ = OrganizationSettings.objects.get_or_create(organization=self.org)
        settings.allow_post_unpaid = True
        settings.save(update_fields=['allow_post_unpaid'])
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=None, user=self.user,
        )
        add_checkout_item(checkout, self.user, service=self.service)
        checkout.refresh_from_db()
        invoice = post_checkout(
            checkout, self.user, expected_version=checkout.version,
            idempotency_key='waiver-post', due_at=timezone.now() + timedelta(days=5),
            credit_reason='authorized_credit', obligation_evidence={
                'basis': 'customer_acknowledgement', 'accepting_party': self.owner.name,
                'channel': 'in_person',
            },
        )
        replacement = void_and_prepare_replacement(
            invoice, self.user, idempotency_key='waiver-replacement',
        )
        with self.assertRaises(ValidationError):
            waive_replacement_exposure(
                replacement, self.user, reason_code='anything', evidence={},
                expected_version=replacement.version, idempotency_key='bad-waiver',
            )
        waiver = waive_replacement_exposure(
            replacement, self.user, reason_code='authorized_waiver',
            evidence={'note': 'Dirección autoriza condonación total.'},
            expected_version=replacement.version, idempotency_key='good-waiver',
        )
        self.assertEqual(waiver.amount, Decimal('100.00'))
        replacement.refresh_from_db()
        self.assertEqual(replacement.completion_kind, 'replacement_waived')

    def test_terminal_void_requires_physical_disposition_and_restores_stock(self):
        settings, _ = OrganizationSettings.objects.get_or_create(organization=self.org)
        settings.allow_post_unpaid = True
        settings.save(update_fields=['allow_post_unpaid'])
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=None, user=self.user,
        )
        add_checkout_item(checkout, self.user, presentation=self.presentation)
        checkout.refresh_from_db()
        invoice = post_checkout(
            checkout, self.user, expected_version=checkout.version,
            idempotency_key='terminal-post', due_at=timezone.now() + timedelta(days=5),
            credit_reason='authorized_credit', obligation_evidence={
                'basis': 'customer_acknowledgement', 'accepting_party': self.owner.name,
                'channel': 'in_person',
            },
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('9.0000'))
        line = invoice.items.get()
        voided = void_invoice_terminal(
            invoice, self.user, reason_code='full_return',
            reason_notes='Cliente devolvió la unidad sin uso.',
            dispositions=[{'invoice_item': line.pk, 'outcome': 'returned_restocked'}],
            idempotency_key='terminal-void',
        )
        self.assertEqual(voided.status, 'voided')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('10.0000'))
        self.assertEqual(
            StockDispositionEvent.objects.filter(kind='returned_restocked').count(), 1,
        )

    def test_returned_rx_redelivery_moves_stock_without_consuming_cap_twice(self):
        settings, _ = OrganizationSettings.objects.get_or_create(organization=self.org)
        settings.allow_post_unpaid = True
        settings.save(update_fields=['allow_post_unpaid'])
        record = MedicalRecord.objects.create(
            pet=self.pet, veterinarian=self.user, organization=self.org,
            status=MedicalRecord.Status.OPEN,
        )
        used = MedicalRecordService.objects.create(
            medical_record=record, service=self.service,
            quantity=Decimal('1'), organization=self.org,
        )
        record_clinical_charge_delta(
            used, delta=Decimal('1'), user=self.user, mutation_key='redelivery-service',
        )
        prescription = Prescription.objects.create(
            medical_record=record, veterinarian=self.user, pet=self.pet,
            organization=self.org,
        )
        rx_item = PrescriptionItem.objects.create(
            prescription=prescription, product=self.product, dose='1 cada 24 h',
            quantity=Decimal('1'), organization=self.org,
        )
        record.status = MedicalRecord.Status.CLOSED
        record.closed_at = timezone.now()
        record.save(update_fields=['status', 'closed_at', 'updated_at'])
        checkout = get_or_create_primary_checkout_for_medical_record(record, owner=self.user)
        checkout.refresh_from_db()
        checkout = dispense_prescription_into_checkout(
            prescription, [{
                'prescription_item_id': rx_item.pk,
                'presentation_id': self.presentation.pk, 'quantity': '1',
            }], self.user, expected_version=checkout.version,
            idempotency_key='rx-dispense-initial',
        )
        invoice = post_checkout(
            checkout, self.user, expected_version=checkout.version,
            idempotency_key='rx-posted', due_at=timezone.now() + timedelta(days=5),
            credit_reason='authorized_credit', obligation_evidence={
                'basis': 'customer_acknowledgement', 'accepting_party': self.owner.name,
                'channel': 'in_person',
            },
        )
        product_line = invoice.items.get(dispensed_from_prescription_item=rx_item)
        replacement = void_and_prepare_replacement(
            invoice, self.user,
            dispositions=[{
                'invoice_item': product_line.pk, 'outcome': 'returned_restocked',
            }],
            idempotency_key='rx-replacement',
        )
        replacement = dispense_prescription_into_checkout(
            prescription, [{
                'prescription_item_id': rx_item.pk,
                'presentation_id': self.presentation.pk, 'quantity': '1',
            }], self.user, expected_version=replacement.version,
            idempotency_key='rx-dispense-redelivery',
        )
        self.assertEqual(replacement.kind, 'replacement')
        replacement_invoice = post_checkout(
            replacement, self.user, payment_method='cash',
            expected_version=replacement.version, idempotency_key='rx-redelivery-pay',
        )
        self.assertEqual(replacement_invoice.status, 'paid')
        events = PrescriptionFulfillmentEvent.objects.filter(
            prescription_item=rx_item,
        )
        self.assertEqual(
            events.aggregate(total=Sum('quantity_delta'))['total'], Decimal('1.0000'),
        )
        self.assertEqual(events.filter(kind='returned').count(), 1)
        self.assertEqual(events.filter(kind='redelivered').count(), 1)
