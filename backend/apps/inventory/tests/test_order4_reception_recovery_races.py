"""I01: a reception still in flight, on independent PostgreSQL connections.

A temporary absence of evidence must never turn into a second entry, so each test
holds one transaction open while another connection reads or acts.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier, Event
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from apps.inventory import services
from apps.inventory.models import Presentation, Product, StockMovement, StockReceptionReceipt
from apps.inventory.tests.test_stock_reception import ReceptionSetupMixin
from apps.users.models import User

LIST_URL = '/api/inventory/receptions/'
PAYLOAD = {'lots': [{'lot_number': 'SYN', 'quantity': '2'}]}
WAIT_SECONDS = 30


class HeldExecution:
    """Keeps a completion inside its transaction until the test releases it."""

    def __init__(self, *, fail=False):
        self.entered = Event()
        self.release = Event()
        self.fail = fail
        self.real_receive_stock = services.receive_stock

    def __call__(self, *args, **kwargs):
        result = self.real_receive_stock(*args, **kwargs)
        self.entered.set()
        if not self.release.wait(WAIT_SECONDS):
            raise RuntimeError('La prueba no liberó la transacción.')
        if self.fail:
            raise ValidationError('fallo sintético antes del commit')
        return result


class ReceptionRaceTests(ReceptionSetupMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(connection.vendor, 'postgresql')
        self.user_id = self.admin.pk

    def _prepare_url(self):
        return f'/api/inventory/presentations/{self.presentation.public_id}/receptions/'

    def _call(self, method, url, data=None, key=None):
        """One request on this thread's own connection, as a separate server worker."""
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(User.objects.get(pk=self.user_id))
            extra = {'HTTP_X_IDEMPOTENCY_KEY': key} if key else {}
            response = getattr(client, method)(url, data, format='json', **extra)
            return response.status_code, dict(response.data)
        finally:
            close_old_connections()

    def _prepare_intent(self):
        key = str(uuid4())
        status_code, body = self._call('post', self._prepare_url(), PAYLOAD, key)
        self.assertEqual(status_code, 201, body)
        return key

    def _wait_until_blocked_on_lock(self):
        deadline = time.monotonic() + WAIT_SECONDS
        with connection.cursor() as cursor:
            while time.monotonic() < deadline:
                cursor.execute(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
                if cursor.fetchone()[0]:
                    return
                time.sleep(0.05)
        self.fail('Ninguna conexión llegó a esperar el lock.')

    def _state(self):
        return (
            StockMovement.all_objects.filter(product=self.product).count(),
            Product.all_objects.get(pk=self.product.pk).stock_quantity,
        )

    def test_execution_in_flight_is_pending_and_cannot_cause_a_second_entry(self):
        key = self._prepare_intent()
        held = HeldExecution()
        with patch('apps.inventory.services.receive_stock', held), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self._call, 'post', f'{LIST_URL}{key}/complete/')
            self.assertTrue(held.entered.wait(WAIT_SECONDS))

            # A clean session reading now sees the intent, not an empty list.
            status_code, listed = self._call('get', LIST_URL)
            self.assertEqual(status_code, 200)
            self.assertEqual([row['status'] for row in listed['results']], ['pending'])
            self.assertEqual(self._state(), (0, Decimal('0')))

            # Registering it again as new is refused while the first one is undecided.
            status_code, blocked = self._call('post', self._prepare_url(), PAYLOAD, str(uuid4()))
            self.assertEqual(status_code, 409, blocked)
            self.assertEqual(blocked['code'], 'reception_unresolved')

            # Completing the same operation queues behind the first and replays it.
            second = pool.submit(self._call, 'post', f'{LIST_URL}{key}/complete/')
            self._wait_until_blocked_on_lock()
            self.assertFalse(second.done())
            held.release.set()
            first_status, _ = first.result(timeout=WAIT_SECONDS)
            second_status, second_body = second.result(timeout=WAIT_SECONDS)

        self.assertEqual((first_status, second_status), (200, 200))
        self.assertEqual(second_body['status'], 'confirmed')
        self.assertEqual(self._state(), (1, Decimal('2')))

    def test_discard_waits_for_execution_in_flight_and_cannot_undo_it(self):
        key = self._prepare_intent()
        held = HeldExecution()
        with patch('apps.inventory.services.receive_stock', held), ThreadPoolExecutor(max_workers=2) as pool:
            completing = pool.submit(self._call, 'post', f'{LIST_URL}{key}/complete/')
            self.assertTrue(held.entered.wait(WAIT_SECONDS))
            discarding = pool.submit(self._call, 'post', f'{LIST_URL}{key}/discard/', {'reason': 'not_received'})
            self._wait_until_blocked_on_lock()
            held.release.set()
            completed_status, _ = completing.result(timeout=WAIT_SECONDS)
            discard_status, discard_body = discarding.result(timeout=WAIT_SECONDS)

        self.assertEqual(completed_status, 200)
        self.assertEqual(discard_status, 409)
        self.assertEqual(discard_body['code'], 'reception_already_confirmed')
        self.assertEqual(self._state(), (1, Decimal('2')))

    def test_failure_before_commit_leaves_the_intent_for_a_person_to_close(self):
        key = self._prepare_intent()
        held = HeldExecution(fail=True)
        with patch('apps.inventory.services.receive_stock', held), ThreadPoolExecutor(max_workers=2) as pool:
            completing = pool.submit(self._call, 'post', f'{LIST_URL}{key}/complete/')
            self.assertTrue(held.entered.wait(WAIT_SECONDS))
            discarding = pool.submit(self._call, 'post', f'{LIST_URL}{key}/discard/', {'reason': 'not_received'})
            self._wait_until_blocked_on_lock()
            held.release.set()
            completed_status, _ = completing.result(timeout=WAIT_SECONDS)
            discard_status, discard_body = discarding.result(timeout=WAIT_SECONDS)

        self.assertEqual(completed_status, 400)
        self.assertEqual(discard_status, 200, discard_body)
        self.assertEqual(discard_body['status'], 'discarded')
        self.assertEqual(self._state(), (0, Decimal('0')))
        late_status, late_body = self._call('post', f'{LIST_URL}{key}/complete/')
        self.assertEqual(late_status, 409)
        self.assertEqual(late_body['code'], 'reception_discarded')
        self.assertEqual(self._state(), (0, Decimal('0')))

    def test_failure_before_commit_keeps_the_intent_completable_with_one_entry(self):
        key = self._prepare_intent()
        with patch('apps.inventory.services.receive_stock', side_effect=ValidationError('fallo sintético')):
            status_code, _ = self._call('post', f'{LIST_URL}{key}/complete/')
        self.assertEqual(status_code, 400)
        self.assertEqual(self._state(), (0, Decimal('0')))
        _, listed = self._call('get', LIST_URL, {'status': 'pending'})
        self.assertEqual(len(listed['results']), 1)

        status_code, body = self._call('post', f'{LIST_URL}{key}/complete/')

        self.assertEqual(status_code, 200, body)
        self.assertEqual(self._state(), (1, Decimal('2')))

    def test_intent_not_yet_committed_is_absent_but_a_new_one_waits_and_is_refused(self):
        entered = Event()
        release = Event()

        def prepare_inside_open_transaction():
            close_old_connections()
            try:
                with transaction.atomic():
                    services.prepare_reception(
                        organization=self.org,
                        actor=User.objects.get(pk=self.user_id),
                        presentation=Presentation.objects.select_related('product').get(pk=self.presentation.pk),
                        validated_data=PAYLOAD,
                        operation_id=uuid4(),
                    )
                    entered.set()
                    self.assertTrue(release.wait(WAIT_SECONDS))
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            holder = pool.submit(prepare_inside_open_transaction)
            self.assertTrue(entered.wait(WAIT_SECONDS))

            # This is the empty list that proves nothing.
            _, listed = self._call('get', LIST_URL)
            self.assertEqual(listed['results'], [])

            new_entry = pool.submit(self._call, 'post', self._prepare_url(), PAYLOAD, str(uuid4()))
            self._wait_until_blocked_on_lock()
            self.assertFalse(new_entry.done())
            release.set()
            holder.result(timeout=WAIT_SECONDS)
            status_code, body = new_entry.result(timeout=WAIT_SECONDS)

        self.assertEqual(status_code, 409, body)
        self.assertEqual(body['code'], 'reception_unresolved')
        _, listed = self._call('get', LIST_URL)
        self.assertEqual([row['status'] for row in listed['results']], ['pending'])
        self.assertEqual(self._state(), (0, Decimal('0')))

    def test_two_new_intents_for_one_product_leave_a_single_open_one(self):
        barrier = Barrier(2)

        def prepare():
            barrier.wait(timeout=WAIT_SECONDS)
            return self._call('post', self._prepare_url(), PAYLOAD, str(uuid4()))

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(prepare) for _ in range(2)]
            results = [future.result(timeout=WAIT_SECONDS) for future in futures]

        self.assertEqual(sorted(status_code for status_code, _ in results), [201, 409])
        refused = next(body for status_code, body in results if status_code == 409)
        self.assertEqual(refused['code'], 'reception_unresolved')
        self.assertEqual(StockReceptionReceipt.objects.filter(status='pending').count(), 1)
        self.assertEqual(self._state(), (0, Decimal('0')))

    def test_two_completions_apply_once(self):
        key = self._prepare_intent()
        barrier = Barrier(2)

        def complete():
            barrier.wait(timeout=WAIT_SECONDS)
            return self._call('post', f'{LIST_URL}{key}/complete/')

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(complete) for _ in range(2)]
            statuses = [future.result(timeout=WAIT_SECONDS)[0] for future in futures]

        self.assertEqual(statuses, [200, 200])
        self.assertEqual(self._state(), (1, Decimal('2')))

    def test_complete_and_discard_at_once_have_one_coherent_outcome(self):
        key = self._prepare_intent()
        barrier = Barrier(2)

        def act(path, data=None):
            barrier.wait(timeout=WAIT_SECONDS)
            return self._call('post', f'{LIST_URL}{key}/{path}/', data)

        with ThreadPoolExecutor(max_workers=2) as pool:
            completing = pool.submit(act, 'complete')
            discarding = pool.submit(act, 'discard', {'reason': 'not_received'})
            complete_status, _ = completing.result(timeout=WAIT_SECONDS)
            discard_status, _ = discarding.result(timeout=WAIT_SECONDS)

        final = StockReceptionReceipt.objects.get().status
        if final == 'confirmed':
            self.assertEqual((complete_status, discard_status), (200, 409))
            self.assertEqual(self._state(), (1, Decimal('2')))
        else:
            self.assertEqual(final, 'discarded')
            self.assertEqual((complete_status, discard_status), (409, 200))
            self.assertEqual(self._state(), (0, Decimal('0')))
