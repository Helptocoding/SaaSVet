from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.inventory.models import Presentation, Product
from apps.notifications.models import Notification, NotificationReceipt
from apps.notifications.services import handle_cash_difference, handle_stock_transition
from apps.organizations.models import Organization
from apps.users.models import User


def _seed_roles(org):
    wildcard, _ = Permission.objects.get_or_create(code='*.*')
    perms_map = {c: Permission.objects.get_or_create(code=c)[0] for c in PERMISSION_CODES}
    roles = {}
    for name, codes in PERMISSIONS.items():
        if name == 'ADMIN_SAAS':
            continue
        role, _ = Role.objects.get_or_create(
            name=name, organization=org, defaults={'is_system_role': True},
        )
        role.permissions.set(
            [wildcard] if '*.*' in codes
            else [perms_map[c] for c in codes if c in perms_map]
        )
        roles[name] = role
    return roles


class NotificationsSetupMixin:
    def setUp(self):
        self.org = Organization.objects.create(
            name='Org Notif', timezone='America/Mexico_City', tax_rate=Decimal('0'),
        )
        self.org_b = Organization.objects.create(
            name='Org B', timezone='UTC', tax_rate=Decimal('0'),
        )
        self.roles = _seed_roles(self.org)
        _seed_roles(self.org_b)
        self.admin = User.objects.create_user(
            username='admin_nt', password='pass1234!', organization=self.org, role='ADMIN',
        )
        UserRole.objects.get_or_create(user=self.admin, role=self.roles['ADMIN'])
        self.vet = User.objects.create_user(
            username='vet_nt', password='pass1234!', organization=self.org, role='VET',
        )
        UserRole.objects.get_or_create(user=self.vet, role=self.roles['VET'])
        self.product = Product.objects.create(
            name='Amoxicilina', internal_code='AMX-NT', organization=self.org,
            base_unit='tablet', stock_quantity=Decimal('10'), min_stock=Decimal('5'),
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)


class StockExclusivityTests(NotificationsSetupMixin, TestCase):
    def _transition(self, prev, new, movement_id=1):
        self.product.stock_quantity = Decimal(new)
        with self.captureOnCommitCallbacks(execute=True):
            return handle_stock_transition(
                self.org, self.product, Decimal(prev), Decimal(new), movement_id,
            )

    def _call(self, *args, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            return handle_stock_transition(*args, **kwargs)

    def test_no_event_above_min(self):
        self.assertIsNone(self._call(
            self.org, self.product, Decimal('10'), Decimal('7'), 11))

    def test_low_event(self):
        self._call(self.org, self.product, Decimal('10'), Decimal('4'), 12)
        notif = Notification.objects.for_organization(self.org).filter(
            dedup_key='stock_low_entered:%s:12' % self.product.pk).first()
        self.assertIsNotNone(notif)

    def test_out_wins_over_low(self):
        self._call(self.org, self.product, Decimal('10'), Decimal('0'), 13)
        self.assertTrue(Notification.objects.for_organization(self.org).filter(
            dedup_key='stock_out:%s:13' % self.product.pk).exists())
        self.assertFalse(Notification.objects.for_organization(self.org).filter(
            dedup_key='stock_low_entered:%s:13' % self.product.pk).exists())

    def test_rearm_after_replenish(self):
        self._call(self.org, self.product, Decimal('10'), Decimal('4'), 14)
        self._call(self.org, self.product, Decimal('4'), Decimal('20'), 15)
        self._call(self.org, self.product, Decimal('20'), Decimal('4'), 16)
        self.assertTrue(Notification.objects.for_organization(self.org).filter(
            dedup_key='stock_low_entered:%s:16' % self.product.pk).exists())

    def test_idempotent_retry_same_movement(self):
        self._call(self.org, self.product, Decimal('10'), Decimal('4'), 17)
        self._call(self.org, self.product, Decimal('10'), Decimal('4'), 17)
        self.assertEqual(Notification.objects.for_organization(self.org).filter(
            dedup_key='stock_low_entered:%s:17' % self.product.pk).count(), 1)


class ReceiptSemanticsTests(NotificationsSetupMixin, TestCase):
    def test_inv_n1_mismatch_rejected(self):
        notif = Notification.objects.create(
            organization=self.org, type='stock_out', entity_type='product',
            occurred_at=timezone.now(), dedup_key='stock_out:1:99',
        )
        receipt = NotificationReceipt(
            organization=self.org, notification=notif,
            notification_key='otra-cosa', user=self.admin,
        )
        with self.assertRaises(ValidationError):
            receipt.full_clean()

    def test_persisted_creates_unseen_receipts(self):
        with self.captureOnCommitCallbacks(execute=True):
            handle_stock_transition(self.org, self.product, Decimal('10'), Decimal('0'), 21)
        receipts = NotificationReceipt.objects.for_organization(self.org).filter(
            notification_key='stock_out:%s:21' % self.product.pk)
        self.assertTrue(receipts.exists())
        self.assertTrue(all(r.seen_at is None for r in receipts))

    def test_tenant_isolation(self):
        with self.captureOnCommitCallbacks(execute=True):
            handle_stock_transition(self.org, self.product, Decimal('10'), Decimal('0'), 22)
        self.assertFalse(Notification.objects.for_organization(self.org_b).filter(
            dedup_key='stock_out:%s:22' % self.product.pk).exists())

    def test_unknown_key_cannot_create_receipt(self):
        response = self.client.post('/api/v1/notifications/not-a-real-key/seen/')
        self.assertEqual(response.status_code, 404)
        self.assertFalse(NotificationReceipt.objects.filter(
            organization=self.org, notification_key='not-a-real-key', user=self.admin,
        ).exists())

    def test_unseen_count_is_not_limited_by_feed_page(self):
        for index in range(3):
            notification = Notification.objects.create(
                organization=self.org, type='stock_out', entity_type='product',
                occurred_at=timezone.now(), dedup_key=f'stock-out-count:{index}',
            )
            NotificationReceipt.objects.create(
                organization=self.org, notification=notification,
                notification_key=notification.dedup_key, user=self.admin,
            )
        response = self.client.get('/api/v1/notifications/feed/?limit=1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['unseen_count'], 3)


class DerivedFeedTests(NotificationsSetupMixin, TestCase):
    _vet_seq = 0

    def _make_appointment(self, start, status='scheduled', vet=None):
        from apps.appointments.models import Appointment
        from apps.patients.models import Owner, Pet
        from apps.users.models import User
        if vet is None:
            type(self)._vet_seq += 1
            vet = User.objects.create_user(
                username=f'vet_feed_{type(self)._vet_seq}', password='pass1234!',
                organization=self.org, role='VET',
            )
        owner = Owner.objects.create(
            name='Ana López', phone='5512345678', organization=self.org,
        )
        pet = Pet.objects.create(name='Kira', species='dog', owner=owner, organization=self.org)
        return Appointment.objects.create(
            organization=self.org, pet=pet, veterinarian=vet or self.vet,
            date=start.date(), start_time=start.timetz(), end_time=(start + timedelta(minutes=30)).timetz(),
            start_datetime=start, end_datetime=start + timedelta(minutes=30),
            reason='Control', status=status,
        )

    @patch(
        'django.utils.timezone.now',
        return_value=datetime(2026, 10, 17, 12, 0, tzinfo=dt_timezone.utc),
    )
    def test_upcoming_window(self, _now):
        now = timezone.now()
        self._make_appointment(now + timedelta(minutes=10))
        self._make_appointment(now + timedelta(hours=5))
        response = self.client.get('/api/v1/notifications/feed/?limit=20')
        self.assertEqual(response.status_code, 200)
        keys = [i['key'] for i in response.data['items']]
        self.assertTrue(any('upcoming' in k for k in keys))
        self.assertFalse(any('delayed' in k for k in keys))

    def test_delayed_window(self):
        now = timezone.now()
        self._make_appointment(now - timedelta(minutes=30))
        self._make_appointment(now - timedelta(minutes=5))
        response = self.client.get('/api/v1/notifications/feed/?limit=20')
        keys = [i['key'] for i in response.data['items']]
        self.assertTrue(any('delayed' in k for k in keys))

    def test_seen_sparse_then_hidden_count(self):
        now = timezone.now()
        appt = self._make_appointment(now + timedelta(minutes=10))
        feed = self.client.get('/api/v1/notifications/feed/?limit=20').data
        key = next(i['key'] for i in feed['items'] if 'upcoming' in i['key'])
        self.assertIn('upcoming', key)
        r1 = self.client.post(f'/api/v1/notifications/{key}/seen/')
        self.assertEqual(r1.status_code, 200)
        feed2 = self.client.get('/api/v1/notifications/feed/?limit=20').data
        item = next(i for i in feed2['items'] if i['key'] == key)
        self.assertTrue(item['seen'])
        self.assertEqual(feed2['unseen_count'], feed['unseen_count'] - 1)

    def test_seen_all_marks_applicable(self):
        now = timezone.now()
        self._make_appointment(now + timedelta(minutes=10))
        self._make_appointment(now + timedelta(minutes=12))
        r = self.client.post('/api/v1/notifications/seen-all/')
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.data['marked'], 2)


class CashThresholdTests(NotificationsSetupMixin, TestCase):
    def test_above_threshold_creates_event_for_actor(self):
        from apps.cash.models import CashSession
        session = CashSession.objects.create(
            organization=self.org, opened_by=self.admin, opened_at=timezone.now(),
            opening_float=Decimal('100'), status='closed', closed_by=self.admin,
            closed_at=timezone.now(), expected_cash=Decimal('100'),
            counted_cash=Decimal('420'), difference=Decimal('320'),
        )
        with self.captureOnCommitCallbacks(execute=True):
            handle_cash_difference(self.org, session, actor=self.admin)
        self.assertTrue(Notification.objects.for_organization(self.org).filter(
            dedup_key=f'cash_difference:{session.public_id}').exists())

    def test_below_threshold_no_notification(self):
        from apps.cash.models import CashSession
        session = CashSession.objects.create(
            organization=self.org, opened_by=self.admin, opened_at=timezone.now(),
            opening_float=Decimal('100'), status='closed', closed_by=self.admin,
            closed_at=timezone.now(), expected_cash=Decimal('100'),
            counted_cash=Decimal('112'), difference=Decimal('12'),
        )
        handle_cash_difference(self.org, session, actor=self.admin)
        self.assertFalse(Notification.objects.for_organization(self.org).filter(
            dedup_key=f'cash_difference:{session.public_id}').exists())
