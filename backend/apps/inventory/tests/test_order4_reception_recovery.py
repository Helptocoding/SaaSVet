"""I01: recover a reception when the client lost its identity, payload and session.

Helpers deliberately drop every response and identifier they produce, so each test
can only learn about an operation by asking the server, as a clean browser would.
"""
import json
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.core.cache import caches
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.models import Permission, Role, UserRole
from apps.inventory.models import (
    Presentation, Product, StockLot, StockMovement, StockReceptionReceipt,
)
from apps.inventory.services import apply_stock_movement
from apps.inventory.tests.test_stock_reception import ReceptionSetupMixin, _seed_roles
from apps.organizations.models import Organization
from apps.users.models import User

LIST_URL = '/api/inventory/receptions/'
UNATTRIBUTED_URL = '/api/inventory/receptions/unattributed/'
PASSWORD = 'pass1234!'
PAYLOAD = {'supplier_name': 'Dist X', 'lots': [{'lot_number': 'SYN', 'expiry_date': '2027-05-01', 'quantity': '2'}]}


class RecoverySetupMixin(ReceptionSetupMixin):
    def _prepare_url(self, presentation=None):
        return f'/api/inventory/presentations/{(presentation or self.presentation).public_id}/receptions/'

    def _send_intent_and_lose_response(self, client=None, presentation=None, payload=None):
        (client or self.client).post(
            self._prepare_url(presentation), payload or PAYLOAD, format='json',
            HTTP_X_IDEMPOTENCY_KEY=str(uuid4()),
        )

    def _send_all_and_lose_responses(self, client=None, presentation=None, payload=None):
        client = client or self.client
        key = str(uuid4())
        response = client.post(
            self._prepare_url(presentation), payload or PAYLOAD, format='json',
            HTTP_X_IDEMPOTENCY_KEY=key,
        )
        assert response.status_code == 201, response.data
        response = client.post(f'{LIST_URL}{key}/complete/')
        assert response.status_code == 200, response.data

    def _fresh_login(self, username='admin_rc'):
        """Clean session: real credentials, nothing carried over from the sender."""
        caches['throttle_login'].clear()  # Per address, and every test shares one.
        client = APIClient()
        response = client.post('/api/token/', {'username': username, 'password': PASSWORD}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        return client

    def _only_operation(self, client, **params):
        response = client.get(LIST_URL, params)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data['results']), 1, response.data)
        return response.data['results'][0]

    def _user_with_permissions(self, username, codes, organization=None):
        organization = organization or self.org
        user = User.objects.create_user(
            username=username, password=PASSWORD, organization=organization, role='ASSISTANT',
        )
        role = Role.objects.create(name=f'Rol {username}', organization=organization)
        role.permissions.set([Permission.objects.get_or_create(code=code)[0] for code in codes])
        UserRole.objects.get_or_create(user=user, role=role)
        return user

    def _authenticated(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _stock_state(self):
        return {
            'operations': StockReceptionReceipt.objects.count(),
            'movements': StockMovement.objects.filter(product=self.product).count(),
            'stock': Product.objects.get(pk=self.product.pk).stock_quantity,
            'lots': list(StockLot.objects.filter(product=self.product).values_list('lot_number', 'quantity_on_hand')),
        }


class ConfirmedOperationRecoveryTests(RecoverySetupMixin, TestCase):
    def test_lost_response_after_commit_is_discovered_after_new_login(self):
        self._send_all_and_lose_responses()
        before = self._stock_state()
        fresh = self._fresh_login()

        operation = self._only_operation(fresh)

        self.assertEqual(operation['status'], 'confirmed')
        self.assertEqual(operation['evidence_level'], 'ledger')
        self.assertEqual(operation['product_name'], 'Vacuna Rabia')
        self.assertEqual(operation['supplier_name'], 'Dist X')
        self.assertEqual(operation['requested_lines'][0]['quantity'], '2.00')
        self.assertEqual(operation['applied_lines'][0]['lot_number'], 'SYN')
        self.assertEqual(Decimal(operation['applied_lines'][0]['quantity_base']), Decimal('2'))
        self.assertEqual(operation['allowed_actions'], [])
        self.assertEqual(self._stock_state(), before)

        # Using the recovered identity replays the evidence and adds nothing.
        replay = fresh.post(f"{LIST_URL}{operation['operation_id']}/complete/")
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(replay.data['status'], 'confirmed')
        self.assertEqual(self._stock_state(), before)
        self.assertEqual(before['movements'], 1)
        self.assertEqual(Product.objects.filter(organization=self.org).count(), 1)

    def test_historical_quantity_is_not_the_current_balance(self):
        self._send_all_and_lose_responses()
        self._send_all_and_lose_responses(payload={'lots': [{'lot_number': 'SYN', 'expiry_date': '2027-05-01', 'quantity': '3'}]})
        lot = StockLot.objects.get(product=self.product, lot_number='SYN')
        with transaction.atomic():
            apply_stock_movement(self.presentation, Decimal('1'), 'out', self.org, reason='Sintético', lot=lot)

        oldest = self._fresh_login().get(LIST_URL).data['results'][-1]
        detail = self._fresh_login().get(f"{LIST_URL}{oldest['operation_id']}/").data

        self.assertEqual(Decimal(detail['applied_lines'][0]['quantity_base']), Decimal('2'))
        self.assertEqual(Decimal(detail['current_balance']['product_stock_quantity']), Decimal('4'))
        self.assertEqual(Decimal(detail['current_balance']['lots'][0]['quantity_on_hand']), Decimal('4'))

    def test_presentation_factor_is_kept_with_the_operation(self):
        box = Presentation.objects.create(
            product=self.product, name='Caja 5', base_unit='vial', quantity=Decimal('5'),
            conversion_factor=Decimal('5'), sale_price=Decimal('500'), stock=Decimal('0'), organization=self.org,
        )
        self._send_all_and_lose_responses(presentation=box)

        operation = self._only_operation(self._fresh_login())

        self.assertEqual(operation['presentation_name'], 'Caja 5')
        self.assertEqual(Decimal(operation['applied_lines'][0]['quantity_base']), Decimal('10'))
        self.assertEqual(Decimal(operation['applied_lines'][0]['quantity_presentation']), Decimal('2'))

        # Changing the factor later does not rewrite what this operation received.
        Presentation.objects.filter(pk=box.pk).update(conversion_factor=Decimal('10'), quantity=Decimal('10'))
        later = self._only_operation(self._fresh_login())
        self.assertEqual(Decimal(later['applied_lines'][0]['quantity_presentation']), Decimal('2'))
        self.assertEqual(Decimal(later['conversion_factor_snapshot']), Decimal('5'))

    def test_two_identical_receptions_are_two_valid_operations(self):
        self._send_all_and_lose_responses()
        self._send_all_and_lose_responses()

        results = self._fresh_login().get(LIST_URL).data['results']

        self.assertEqual(len(results), 2)
        self.assertNotEqual(results[0]['operation_id'], results[1]['operation_id'])
        self.assertEqual([r['status'] for r in results], ['confirmed', 'confirmed'])
        self.assertEqual(Product.objects.get(pk=self.product.pk).stock_quantity, Decimal('4'))
        self.assertEqual(StockLot.objects.get(product=self.product).quantity_on_hand, Decimal('4'))
        self.assertEqual(StockMovement.objects.filter(product=self.product).count(), 2)

    def test_reading_changes_nothing(self):
        self._send_intent_and_lose_response()
        operation = StockReceptionReceipt.objects.get()
        before = (self._stock_state(), operation.status, operation.resolved_at, operation.result)
        fresh = self._fresh_login()

        fresh.get(LIST_URL)
        fresh.get(f'{LIST_URL}{operation.operation_id}/')
        fresh.get(UNATTRIBUTED_URL)

        operation.refresh_from_db()
        self.assertEqual((self._stock_state(), operation.status, operation.resolved_at, operation.result), before)


class PendingOperationReconciliationTests(RecoverySetupMixin, TestCase):
    def test_intent_without_execution_stays_pending_and_can_be_completed_once(self):
        self._send_intent_and_lose_response()
        self.assertEqual(self._stock_state()['movements'], 0)
        fresh = self._fresh_login()

        operation = self._only_operation(fresh, status='pending')

        self.assertEqual(operation['status'], 'pending')
        self.assertEqual(operation['evidence_level'], 'intent')
        self.assertEqual(operation['allowed_actions'], ['complete', 'discard'])
        self.assertEqual(self._stock_state()['movements'], 0)

        first = fresh.post(f"{LIST_URL}{operation['operation_id']}/complete/")
        second = fresh.post(f"{LIST_URL}{operation['operation_id']}/complete/")

        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertEqual(first.data['status'], 'confirmed')
        self.assertEqual(self._stock_state()['movements'], 1)
        self.assertEqual(Product.objects.get(pk=self.product.pk).stock_quantity, Decimal('2'))

    def test_matching_stock_does_not_confirm_a_pending_operation(self):
        self._send_intent_and_lose_response()
        # Same lot, quantity and resulting balance, through a call with no identity.
        response = self.client.post(self._receive_url(), PAYLOAD, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Product.objects.get(pk=self.product.pk).stock_quantity, Decimal('2'))

        operation = self._only_operation(self._fresh_login())

        self.assertEqual(operation['status'], 'pending')
        self.assertEqual(operation['applied_lines'], [])

    def test_review_shows_other_entries_since_the_intent_without_their_identity(self):
        self._send_intent_and_lose_response()
        self.client.post(self._receive_url(), PAYLOAD, format='json')
        operation_id = StockReceptionReceipt.objects.get().operation_id

        detail = self._fresh_login().get(f'{LIST_URL}{operation_id}/').data

        entries = detail['ledger_since_intent']['entries']
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['lot_number'], 'SYN')
        self.assertFalse(entries[0]['attributed_to_operation'])
        self.assertNotIn('operation_id', entries[0])

    def test_unresolved_intent_blocks_only_a_new_entry_of_that_product(self):
        self._send_intent_and_lose_response()
        fresh = self._fresh_login()
        operation_id = str(StockReceptionReceipt.objects.get().operation_id)

        blocked_prepare = fresh.post(self._prepare_url(), PAYLOAD, format='json', HTTP_X_IDEMPOTENCY_KEY=str(uuid4()))
        blocked_direct = fresh.post(self._receive_url(), PAYLOAD, format='json', HTTP_X_IDEMPOTENCY_KEY=str(uuid4()))

        for blocked in (blocked_prepare, blocked_direct):
            self.assertEqual(blocked.status_code, 409, blocked.data)
            self.assertEqual(blocked.data['code'], 'reception_unresolved')
            self.assertEqual(blocked.data['unresolved_operation_id'], operation_id)
        self.assertEqual(self._stock_state()['movements'], 0)

        other = Product.objects.create(
            name='Otro', internal_code='OT-RC', organization=self.org, base_unit='vial', tracks_lots=True,
        )
        other_presentation = Presentation.objects.create(
            product=other, name='Vial', base_unit='vial', quantity=Decimal('1'), conversion_factor=Decimal('1'),
            sale_price=Decimal('10'), stock=Decimal('0'), organization=self.org,
        )
        allowed = fresh.post(self._prepare_url(other_presentation), PAYLOAD, format='json', HTTP_X_IDEMPOTENCY_KEY=str(uuid4()))
        self.assertEqual(allowed.status_code, 201, allowed.data)

    def test_new_explicit_reception_after_resolving_is_allowed(self):
        self._send_intent_and_lose_response()
        fresh = self._fresh_login()
        operation_id = StockReceptionReceipt.objects.get().operation_id
        discarded = fresh.post(f'{LIST_URL}{operation_id}/discard/', {'reason': 'entered_in_error'}, format='json')
        self.assertEqual(discarded.status_code, 200, discarded.data)

        self._send_all_and_lose_responses(client=fresh)

        self.assertEqual(self._stock_state()['movements'], 1)
        statuses = sorted(r['status'] for r in fresh.get(LIST_URL).data['results'])
        self.assertEqual(statuses, ['confirmed', 'discarded'])

    def test_discard_is_terminal_and_keeps_who_and_why(self):
        self._send_intent_and_lose_response()
        fresh = self._fresh_login()
        operation_id = StockReceptionReceipt.objects.get().operation_id

        response = fresh.post(
            f'{LIST_URL}{operation_id}/discard/',
            {'reason': 'already_registered', 'note': '<b>remisión</b> 123'}, format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'discarded')
        self.assertEqual(response.data['discard_reason'], 'already_registered')
        self.assertEqual(response.data['discard_note'], 'remisión 123')
        self.assertTrue(response.data['resolved_by_name'])
        self.assertEqual(response.data['allowed_actions'], [])

        late_complete = fresh.post(f'{LIST_URL}{operation_id}/complete/')
        late_direct = fresh.post(self._receive_url(), PAYLOAD, format='json', HTTP_X_IDEMPOTENCY_KEY=str(operation_id))
        same_prepare = fresh.post(self._prepare_url(), PAYLOAD, format='json', HTTP_X_IDEMPOTENCY_KEY=str(operation_id))

        self.assertEqual(late_complete.status_code, 409)
        self.assertEqual(late_complete.data['code'], 'reception_discarded')
        self.assertEqual(late_direct.status_code, 409)
        self.assertEqual(late_direct.data['code'], 'reception_discarded')
        self.assertEqual(same_prepare.status_code, 200)
        self.assertEqual(same_prepare.data['status'], 'discarded')
        self.assertEqual(self._stock_state()['movements'], 0)

    def test_discard_requires_a_known_reason_and_never_undoes_a_confirmed_entry(self):
        self._send_all_and_lose_responses()
        operation_id = StockReceptionReceipt.objects.get().operation_id

        invalid = self.client.post(f'{LIST_URL}{operation_id}/discard/', {'reason': 'porque sí'}, format='json')
        confirmed = self.client.post(f'{LIST_URL}{operation_id}/discard/', {'reason': 'entered_in_error'}, format='json')

        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(confirmed.status_code, 409)
        self.assertEqual(confirmed.data['code'], 'reception_already_confirmed')
        self.assertEqual(Product.objects.get(pk=self.product.pk).stock_quantity, Decimal('2'))

    def test_failure_on_a_later_line_applies_nothing_and_keeps_the_intent(self):
        two_lots = {'lots': [{'lot_number': 'A', 'quantity': '1'}, {'lot_number': 'B', 'quantity': '1'}]}
        self._send_intent_and_lose_response(payload=two_lots)
        operation_id = StockReceptionReceipt.objects.get().operation_id
        real_writer = apply_stock_movement
        calls = []

        def fail_on_second_line(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise ValidationError('fallo sintético')
            return real_writer(*args, **kwargs)

        with patch('apps.inventory.services.apply_stock_movement', side_effect=fail_on_second_line):
            failed = self.client.post(f'{LIST_URL}{operation_id}/complete/')

        self.assertEqual(failed.status_code, 400, failed.data)
        self.assertEqual(self._stock_state()['movements'], 0)
        self.assertEqual(self._stock_state()['lots'], [])
        self.assertEqual(self._only_operation(self._fresh_login())['status'], 'pending')

        retried = self.client.post(f'{LIST_URL}{operation_id}/complete/')

        self.assertEqual(retried.status_code, 200, retried.data)
        self.assertEqual(self._stock_state()['movements'], 2)
        self.assertEqual(Product.objects.get(pk=self.product.pk).stock_quantity, Decimal('2'))

    def test_changed_factor_is_not_applied_with_a_different_meaning(self):
        self._send_intent_and_lose_response()
        operation_id = StockReceptionReceipt.objects.get().operation_id
        Presentation.objects.filter(pk=self.presentation.pk).update(conversion_factor=Decimal('5'), quantity=Decimal('5'))

        response = self.client.post(f'{LIST_URL}{operation_id}/complete/')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'reception_factor_changed')
        self.assertEqual(self._stock_state()['movements'], 0)
        self.assertEqual(self._only_operation(self.client)['allowed_actions'], ['complete', 'discard'])

    def test_late_intent_after_a_new_reception_stays_inert_until_someone_resolves_it(self):
        """A prepare stuck in transit lands after the user already registered the delivery."""
        lost_key = str(uuid4())
        self._send_all_and_lose_responses()
        before = self._stock_state()

        late = self.client.post(self._prepare_url(), PAYLOAD, format='json', HTTP_X_IDEMPOTENCY_KEY=lost_key)

        self.assertEqual(late.status_code, 201, late.data)
        self.assertEqual(self._stock_state()['movements'], before['movements'])
        self.assertEqual(self._stock_state()['stock'], before['stock'])
        pending = self._only_operation(self._fresh_login(), status='pending')
        self.assertEqual(pending['allowed_actions'], ['complete', 'discard'])

    def test_retry_with_conserved_identity_executes_a_prepared_operation(self):
        key = str(uuid4())
        self.client.post(self._prepare_url(), PAYLOAD, format='json', HTTP_X_IDEMPOTENCY_KEY=key)

        response = self.client.post(self._receive_url(), PAYLOAD, format='json', HTTP_X_IDEMPOTENCY_KEY=key)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('lots', response.data)
        self.assertEqual(self._stock_state()['movements'], 1)
        self.assertEqual(StockReceptionReceipt.objects.get().status, 'confirmed')

    def test_prepare_is_idempotent_and_rejects_a_reused_identity(self):
        key = str(uuid4())
        first = self.client.post(self._prepare_url(), PAYLOAD, format='json', HTTP_X_IDEMPOTENCY_KEY=key)
        replay = self.client.post(self._prepare_url(), PAYLOAD, format='json', HTTP_X_IDEMPOTENCY_KEY=key)
        changed = self.client.post(
            self._prepare_url(), {'lots': [{'lot_number': 'SYN', 'quantity': '9'}]},
            format='json', HTTP_X_IDEMPOTENCY_KEY=key,
        )
        missing = self.client.post(self._prepare_url(), PAYLOAD, format='json')
        invalid = self.client.post(self._prepare_url(), PAYLOAD, format='json', HTTP_X_IDEMPOTENCY_KEY='no-uuid')

        self.assertEqual((first.status_code, replay.status_code), (201, 200))
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(changed.data['code'], 'reception_operation_conflict')
        self.assertEqual((missing.status_code, invalid.status_code), (400, 400))
        self.assertEqual(StockReceptionReceipt.objects.count(), 1)


class HonestLimitsTests(RecoverySetupMixin, TestCase):
    def _legacy_receipt(self, result):
        return StockReceptionReceipt.objects.create(
            organization=self.org, actor=self.admin, presentation=self.presentation,
            product=self.product, operation_id=uuid4(), payload_hash='a' * 64, payload=None,
            status='confirmed' if result else 'pending', result=result,
        )

    def test_receipt_from_before_the_intent_record_does_not_invent_quantities(self):
        receipt = self._legacy_receipt({
            'presentation': {'stock': '99.00'},
            'lots': [{'lot_number': 'OLD', 'expiry_date': '2027-01-01', 'quantity_on_hand': '98.7654'}],
        })
        StockLot.objects.create(
            organization=self.org, product=self.product, lot_number='OLD',
            expiry_date='2027-01-01', quantity_on_hand=Decimal('5'),
        )
        before = self._stock_state()
        fresh = self._fresh_login()

        operation = self._only_operation(fresh)
        detail = fresh.get(f'{LIST_URL}{receipt.operation_id}/').data
        replay = fresh.post(f'{LIST_URL}{receipt.operation_id}/complete/')

        self.assertEqual(operation['status'], 'confirmed')
        self.assertEqual(operation['evidence_level'], 'legacy_receipt')
        self.assertIsNone(operation['requested_lines'])
        self.assertEqual(operation['applied_lines'], [])
        self.assertEqual(operation['legacy_lots'], [{'lot_number': 'OLD', 'expiry_date': '2027-01-01'}])
        self.assertNotIn('98.7654', json.dumps(operation, default=str))
        self.assertEqual(Decimal(detail['current_balance']['lots'][0]['quantity_on_hand']), Decimal('5'))
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(self._stock_state(), before)

    def test_receipt_without_result_or_capture_can_only_be_discarded(self):
        receipt = self._legacy_receipt(None)

        operation = self._only_operation(self.client)
        attempt = self.client.post(f'{LIST_URL}{receipt.operation_id}/complete/')
        discard = self.client.post(f'{LIST_URL}{receipt.operation_id}/discard/', {'reason': 'entered_in_error'}, format='json')

        self.assertEqual(operation['evidence_level'], 'unavailable')
        self.assertEqual(operation['allowed_actions'], ['discard'])
        self.assertEqual(attempt.status_code, 409)
        self.assertEqual(attempt.data['code'], 'reception_payload_unavailable')
        self.assertEqual(discard.status_code, 200, discard.data)
        self.assertEqual(self._stock_state()['movements'], 0)

    def test_entry_without_identity_is_listed_for_review_and_gets_no_receipt(self):
        response = self.client.post(self._receive_url(), PAYLOAD, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(StockReceptionReceipt.objects.count(), 0)
        fresh = self._fresh_login()

        operations = fresh.get(LIST_URL)
        unattributed = fresh.get(UNATTRIBUTED_URL)

        self.assertEqual(operations.data['results'], [])
        self.assertEqual(len(unattributed.data['results']), 1)
        entry = unattributed.data['results'][0]
        self.assertEqual(entry['lot_number'], 'SYN')
        self.assertEqual(entry['product_name'], 'Vacuna Rabia')
        self.assertEqual(Decimal(entry['quantity']), Decimal('2'))
        self.assertFalse(entry['attributed_to_operation'])
        self.assertEqual(StockReceptionReceipt.objects.count(), 0)

    def test_entries_of_an_operation_are_not_listed_as_unattributed(self):
        self._send_all_and_lose_responses()

        self.assertEqual(self.client.get(UNATTRIBUTED_URL).data['results'], [])


class AccessIsolationTests(RecoverySetupMixin, TestCase):
    def setUp(self):
        super().setUp()
        self._send_intent_and_lose_response()
        self.operation = StockReceptionReceipt.objects.get()
        self.detail_url = f'{LIST_URL}{self.operation.operation_id}/'
        self.state = self._stock_state()

    def _assert_cannot_reach(self, client, expected_status):
        for response in (
            client.get(self.detail_url),
            client.post(f'{self.detail_url}complete/'),
            client.post(f'{self.detail_url}discard/', {'reason': 'entered_in_error'}, format='json'),
        ):
            self.assertEqual(response.status_code, expected_status, response.data)
            self.assertNotIn('requested_lines', response.data)
            self.assertNotIn('product_name', response.data)
        self.operation.refresh_from_db()
        self.assertEqual(self.operation.status, 'pending')
        self.assertEqual(self._stock_state(), self.state)

    def test_other_organization_sees_nothing_not_even_by_identity(self):
        other = Organization.objects.create(name='Otra clínica', timezone='UTC', tax_rate=Decimal('0'))
        roles = _seed_roles(other)
        outsider = User.objects.create_user(username='outsider_i01', password=PASSWORD, organization=other, role='ADMIN')
        UserRole.objects.get_or_create(user=outsider, role=roles['ADMIN'])
        client = self._authenticated(outsider)

        self._assert_cannot_reach(client, 404)
        for scope in ('own', 'organization'):
            self.assertEqual(client.get(LIST_URL, {'scope': scope}).data['results'], [])
            self.assertEqual(client.get(UNATTRIBUTED_URL, {'scope': scope}).data['results'], [])
        self.assertEqual(client.get(LIST_URL, {'product': str(self.product.public_id)}).status_code, 404)

    def test_cursor_from_another_tenant_only_moves_inside_the_caller_data(self):
        self._send_all_and_lose_responses(presentation=self._second_presentation())
        cursor_page = self.client.get(LIST_URL, {'page_size': 1})
        self.assertIsNotNone(cursor_page.data['next'])
        other = Organization.objects.create(name='Otra cursor', timezone='UTC', tax_rate=Decimal('0'))
        roles = _seed_roles(other)
        outsider = User.objects.create_user(username='cursor_i01', password=PASSWORD, organization=other, role='ADMIN')
        UserRole.objects.get_or_create(user=outsider, role=roles['ADMIN'])

        response = self._authenticated(outsider).get(cursor_page.data['next'])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'], [])

    def _second_presentation(self):
        product = Product.objects.create(
            name='Segundo', internal_code='SG-RC', organization=self.org, base_unit='vial', tracks_lots=True,
        )
        return Presentation.objects.create(
            product=product, name='Vial', base_unit='vial', quantity=Decimal('1'), conversion_factor=Decimal('1'),
            sale_price=Decimal('10'), stock=Decimal('0'), organization=self.org,
        )

    def test_role_without_stock_permission_is_refused(self):
        vet = User.objects.create_user(username='vet_i01', password=PASSWORD, organization=self.org, role='VET')
        UserRole.objects.get_or_create(user=vet, role=self.roles['VET'])
        client = self._authenticated(vet)

        self._assert_cannot_reach(client, 403)
        self.assertEqual(client.get(LIST_URL).status_code, 403)
        self.assertEqual(client.get(UNATTRIBUTED_URL).status_code, 403)

    def test_colleague_with_stock_permission_neither_sees_nor_adopts_it(self):
        colleague = self._user_with_permissions('clerk_i01', ['inventory.update', 'inventory.list'])
        client = self._authenticated(colleague)

        self._assert_cannot_reach(client, 404)
        self.assertEqual(client.get(LIST_URL).data['results'], [])
        self.assertFalse(client.get(LIST_URL).data['can_supervise'])
        self.assertEqual(client.get(LIST_URL, {'scope': 'organization'}).status_code, 403)
        self.assertEqual(client.get(UNATTRIBUTED_URL, {'scope': 'organization'}).status_code, 403)
        # Discovering the identity does not let anyone reuse it either.
        reuse = client.post(self._prepare_url(), PAYLOAD, format='json', HTTP_X_IDEMPOTENCY_KEY=str(self.operation.operation_id))
        self.assertEqual(reuse.status_code, 409)
        self.assertEqual(reuse.data['code'], 'reception_operation_conflict')
        self.assertNotIn('requested_lines', reuse.data)

    def test_supervisor_can_read_and_close_but_never_execute_for_someone_else(self):
        supervisor = self._user_with_permissions('super_i01', ['inventory.update', 'staff.reset_password'])
        client = self._authenticated(supervisor)

        self.assertEqual(client.get(LIST_URL).data['results'], [])
        listed = client.get(LIST_URL, {'scope': 'organization'}).data
        self.assertTrue(listed['can_supervise'])
        self.assertEqual(listed['results'][0]['operation_id'], str(self.operation.operation_id))
        self.assertFalse(listed['results'][0]['is_own'])
        self.assertEqual(listed['results'][0]['allowed_actions'], ['discard'])

        execute = client.post(f'{self.detail_url}complete/')
        self.assertEqual(execute.status_code, 404)
        self.assertEqual(self._stock_state()['movements'], 0)

        closed = client.post(f'{self.detail_url}discard/', {'reason': 'not_received'}, format='json')
        self.assertEqual(closed.status_code, 200, closed.data)
        self.operation.refresh_from_db()
        self.assertEqual(self.operation.actor, self.admin)
        self.assertEqual(self.operation.resolved_by, supervisor)
        # The actor's late attempt finds the closure instead of adding stock.
        late = self.client.post(f'{self.detail_url}complete/')
        self.assertEqual(late.status_code, 409)
        self.assertEqual(self._stock_state()['movements'], 0)

    def test_anonymous_and_disabled_organization_get_no_data(self):
        anonymous = APIClient()
        self.assertEqual(anonymous.get(LIST_URL).status_code, 401)
        self.assertEqual(anonymous.get(UNATTRIBUTED_URL).status_code, 401)
        self._assert_cannot_reach(anonymous, 401)

        token = str(RefreshToken.for_user(self.admin).access_token)
        self.org.is_active = False
        self.org.save(update_fields=['is_active'])
        disabled = APIClient()
        disabled.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        for response in (disabled.get(LIST_URL), disabled.get(self.detail_url), disabled.post(f'{self.detail_url}complete/')):
            self.assertIn(response.status_code, (401, 403), response.data)
            self.assertNotIn('results', response.data)
            self.assertNotIn('requested_lines', response.data)
        self.assertEqual(self._stock_state(), self.state)

    def test_invalid_filters_are_rejected(self):
        self.assertEqual(self.client.get(LIST_URL, {'status': 'x'}).status_code, 400)
        self.assertEqual(self.client.get(LIST_URL, {'scope': 'x'}).status_code, 400)
        self.assertEqual(self.client.get(LIST_URL, {'product': str(uuid4())}).status_code, 404)
        self.assertEqual(self.client.get(f'{LIST_URL}{uuid4()}/').status_code, 404)
        self.assertEqual(self.client.get(f'{LIST_URL}not-a-uuid/').status_code, 404)


class DiscoveryBoundsTests(RecoverySetupMixin, TestCase):
    def _bulk_confirmed(self, count):
        StockReceptionReceipt.objects.bulk_create([
            StockReceptionReceipt(
                organization=self.org, actor=self.admin, presentation=self.presentation, product=self.product,
                operation_id=uuid4(), payload_hash='a' * 64, status='confirmed', result={'lots': []},
                payload={'lots': [{'lot_number': f'L{i}', 'quantity': '1.00'} for i in range(12)]},
            )
            for _ in range(count)
        ])

    def test_cursor_walks_every_operation_once(self):
        self._bulk_confirmed(5)
        seen = []
        url = LIST_URL + '?page_size=2'
        while url:
            page = self.client.get(url).data
            self.assertLessEqual(len(page['results']), 2)
            seen.extend(row['operation_id'] for row in page['results'])
            url = page['next']
        self.assertEqual(len(seen), 5)
        self.assertEqual(len(set(seen)), 5)

    def test_page_size_and_lines_per_row_are_capped_in_the_list_only(self):
        self._bulk_confirmed(105)

        page = self.client.get(LIST_URL, {'page_size': 1000}).data
        operation = page['results'][0]
        detail = self.client.get(f"{LIST_URL}{operation['operation_id']}/").data

        self.assertEqual(len(page['results']), 100)
        self.assertEqual(len(operation['requested_lines']), 10)
        self.assertEqual(operation['lines_total'], 12)
        self.assertEqual(len(detail['requested_lines']), 12)

    def test_query_count_does_not_grow_with_rows(self):
        self._bulk_confirmed(2)
        self.client.get(LIST_URL)  # Permissions stay cached on the user afterwards.
        with CaptureQueriesContext(connection) as small:
            self.client.get(LIST_URL)
        self._bulk_confirmed(30)
        with CaptureQueriesContext(connection) as large:
            self.client.get(LIST_URL)
        self.assertEqual(len(small), len(large))
