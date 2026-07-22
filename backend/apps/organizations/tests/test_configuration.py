"""
Tests de OrganizationScheduleView, OrganizationSettingsView,
OrganizationConfigurationView (Fase 1 — ADR p53).

Cubre:
- GET/PUT /api/organizations/schedule/ — lectura, reemplazo completo,
  validaciones, atomicidad
- GET/PATCH /api/organizations/settings/ — lectura, actualización,
  validaciones de rango
- GET /api/settings/configuration/ — agregado de organización,
  settings, schedule
"""
from datetime import time as time_type

from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.organizations.models import Organization, OrganizationSchedule
from apps.users.models import User


def _seed_roles(org):
    wildcard, _ = Permission.objects.get_or_create(code="*.*")
    perms_map = {c: Permission.objects.get_or_create(code=c)[0] for c in PERMISSION_CODES}
    roles = {}
    for name, codes in PERMISSIONS.items():
        if name == "ADMIN_SAAS":
            continue
        role, _ = Role.objects.get_or_create(name=name, organization=org, defaults={"is_system_role": True})
        role.permissions.set([wildcard] if "*.*" in codes else [perms_map[c] for c in codes if c in perms_map])
        roles[name] = role
    return roles


def _make_user(username, org, role_name):
    u = User.objects.create_user(username=username, password="pass", organization=org, role=role_name)
    roles = _seed_roles(org)
    UserRole.objects.get_or_create(user=u, role=roles[role_name])
    return u


_SCHEDULE_PAYLOAD = [
    {"weekday": 1, "is_closed": False, "opens_at": "09:00", "closes_at": "19:00", "has_break": True, "break_start": "13:00", "break_end": "14:00"},
    {"weekday": 2, "is_closed": False, "opens_at": "09:00", "closes_at": "19:00", "has_break": True, "break_start": "13:00", "break_end": "14:00"},
    {"weekday": 3, "is_closed": False, "opens_at": "09:00", "closes_at": "19:00", "has_break": True, "break_start": "13:00", "break_end": "14:00"},
    {"weekday": 4, "is_closed": False, "opens_at": "09:00", "closes_at": "19:00", "has_break": True, "break_start": "13:00", "break_end": "14:00"},
    {"weekday": 5, "is_closed": False, "opens_at": "09:00", "closes_at": "19:00", "has_break": True, "break_start": "13:00", "break_end": "14:00"},
    {"weekday": 6, "is_closed": False, "opens_at": "09:00", "closes_at": "14:00", "has_break": False, "break_start": None, "break_end": None},
    {"weekday": 7, "is_closed": True, "opens_at": None, "closes_at": None, "has_break": False, "break_start": None, "break_end": None},
]


class OrganizationScheduleViewTests(APITestCase):
    """GET/PUT /api/organizations/schedule/"""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Schedule Org", timezone="UTC")
        cls.admin = _make_user("adm_sched", cls.org, "ADMIN")

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_get_returns_default_schedule(self):
        r = self.client.get('/api/organizations/schedule/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(len(r.data), 7)
        self.assertEqual(r.data[0]['weekday'], 1)
        self.assertEqual(r.data[6]['weekday'], 7)
        self.assertEqual(r.data[6]['is_closed'], True)

    def test_get_returns_ordered_by_weekday(self):
        r = self.client.get('/api/organizations/schedule/')
        weekdays = [item['weekday'] for item in r.data]
        self.assertEqual(weekdays, [1, 2, 3, 4, 5, 6, 7])

    def test_put_replaces_full_schedule(self):
        r = self.client.put(
            '/api/organizations/schedule/',
            _SCHEDULE_PAYLOAD,
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(len(r.data), 7)
        day1 = next(d for d in r.data if d['weekday'] == 1)
        self.assertEqual(day1['opens_at'], '09:00:00')
        self.assertEqual(day1['closes_at'], '19:00:00')
        self.assertEqual(day1['has_break'], True)
        self.assertEqual(day1['break_start'], '13:00:00')

        day7 = next(d for d in r.data if d['weekday'] == 7)
        self.assertEqual(day7['is_closed'], True)
        self.assertIsNone(day7['opens_at'])

    def test_put_persists_to_database(self):
        self.client.put(
            '/api/organizations/schedule/',
            _SCHEDULE_PAYLOAD,
            format='json',
        )
        schedules = OrganizationSchedule.objects.filter(organization=self.org).order_by('weekday')
        self.assertEqual(schedules.count(), 7)
        day1 = schedules.get(weekday=1)
        self.assertEqual(day1.opens_at, time_type(9, 0))
        self.assertEqual(day1.break_start, time_type(13, 0))

    def test_put_invalid_less_than_7_days_returns_400(self):
        payload = _SCHEDULE_PAYLOAD[:3]
        r = self.client.put(
            '/api/organizations/schedule/',
            payload,
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_put_duplicate_weekday_returns_400(self):
        payload = list(_SCHEDULE_PAYLOAD)
        payload.append({"weekday": 1, "is_closed": True, "opens_at": None, "closes_at": None, "has_break": False, "break_start": None, "break_end": None})
        r = self.client.put(
            '/api/organizations/schedule/',
            payload,
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_put_invalid_day_closed_with_hours_returns_400(self):
        payload = list(_SCHEDULE_PAYLOAD)
        payload[6] = {"weekday": 7, "is_closed": True, "opens_at": "09:00", "closes_at": "18:00", "has_break": False, "break_start": None, "break_end": None}
        r = self.client.put(
            '/api/organizations/schedule/',
            payload,
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_put_invalid_break_outside_hours_returns_400(self):
        payload = list(_SCHEDULE_PAYLOAD)
        payload[0] = {"weekday": 1, "is_closed": False, "opens_at": "09:00", "closes_at": "18:00", "has_break": True, "break_start": "08:00", "break_end": "09:00"}
        r = self.client.put(
            '/api/organizations/schedule/',
            payload,
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_put_not_a_list_returns_400(self):
        r = self.client.put(
            '/api/organizations/schedule/',
            {"not": "a list"},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_put_blocks_user_without_organization(self):
        user_no_org = User.objects.create_user(
            username="sched_no_org", password="x", organization=None, role="ASSISTANT",
        )
        self.client.force_authenticate(user_no_org)
        r = self.client.put(
            '/api/organizations/schedule/',
            _SCHEDULE_PAYLOAD,
            format='json',
        )
        self.assertIn(
            r.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )

    def test_delete_returns_405(self):
        r = self.client.delete('/api/organizations/schedule/')
        self.assertEqual(r.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class OrganizationSettingsViewTests(APITestCase):
    """GET/PATCH /api/organizations/settings/"""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Settings Org", timezone="UTC")
        cls.admin = _make_user("adm_sett", cls.org, "ADMIN")

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_get_returns_default_settings(self):
        r = self.client.get('/api/organizations/settings/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['locale'], 'es-MX')
        self.assertEqual(r.data['currency_code'], 'MXN')
        self.assertEqual(r.data['default_appointment_duration_minutes'], 30)
        self.assertEqual(r.data['appointment_buffer_minutes'], 0)
        self.assertEqual(r.data['week_starts_on'], 1)
        self.assertEqual(r.data['allow_emergency_walkin'], False)

    def test_patch_updates_settings(self):
        r = self.client.patch(
            '/api/organizations/settings/',
            {'default_appointment_duration_minutes': 45, 'appointment_buffer_minutes': 15},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['default_appointment_duration_minutes'], 45)
        self.assertEqual(r.data['appointment_buffer_minutes'], 15)

    def test_patch_invalid_duration_returns_400(self):
        r = self.client.patch(
            '/api/organizations/settings/',
            {'default_appointment_duration_minutes': 1},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_invalid_buffer_returns_400(self):
        r = self.client.patch(
            '/api/organizations/settings/',
            {'appointment_buffer_minutes': 999},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_invalid_week_starts_on_returns_400(self):
        r = self.client.patch(
            '/api/organizations/settings/',
            {'week_starts_on': 0},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_currency_code_uppercases(self):
        r = self.client.patch(
            '/api/organizations/settings/',
            {'currency_code': 'usd'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['currency_code'], 'USD')

    def test_patch_allow_emergency_walkin(self):
        r = self.client.patch(
            '/api/organizations/settings/',
            {'allow_emergency_walkin': True},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['allow_emergency_walkin'], True)

    def test_patch_requires_no_extra_fields(self):
        r = self.client.patch(
            '/api/organizations/settings/',
            {'locale': 'en-US'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['locale'], 'en-US')
        self.assertEqual(r.data['currency_code'], 'MXN')

    def test_blocks_user_without_organization(self):
        user_no_org = User.objects.create_user(
            username="sett_no_org", password="x", organization=None, role="ASSISTANT",
        )
        self.client.force_authenticate(user_no_org)
        r = self.client.get('/api/organizations/settings/')
        self.assertIn(
            r.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )


class OrganizationConfigurationViewTests(APITestCase):
    """GET /api/settings/configuration/"""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Config Org", timezone="UTC")
        cls.admin = _make_user("adm_cfg", cls.org, "ADMIN")

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_get_returns_aggregate(self):
        r = self.client.get('/api/settings/configuration/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('organization', r.data)
        self.assertIn('settings', r.data)
        self.assertIn('schedule', r.data)

    def test_aggregate_organization_shape(self):
        r = self.client.get('/api/settings/configuration/')
        org = r.data['organization']
        self.assertEqual(org['id'], self.org.pk)
        self.assertEqual(org['name'], 'Config Org')
        self.assertEqual(org['timezone'], 'UTC')

    def test_aggregate_settings_shape(self):
        r = self.client.get('/api/settings/configuration/')
        settings = r.data['settings']
        self.assertEqual(settings['locale'], 'es-MX')
        self.assertEqual(settings['currency_code'], 'MXN')

    def test_aggregate_schedule_shape(self):
        r = self.client.get('/api/settings/configuration/')
        schedule = r.data['schedule']
        self.assertEqual(len(schedule), 7)
        weekdays = [s['weekday'] for s in schedule]
        self.assertEqual(weekdays, [1, 2, 3, 4, 5, 6, 7])

    def test_aggregate_reflects_updated_settings(self):
        self.client.patch(
            '/api/organizations/settings/',
            {'default_appointment_duration_minutes': 60},
            format='json',
        )
        r = self.client.get('/api/settings/configuration/')
        self.assertEqual(r.data['settings']['default_appointment_duration_minutes'], 60)

    def test_aggregate_reflects_updated_schedule(self):
        payload = list(_SCHEDULE_PAYLOAD)
        payload[0] = {"weekday": 1, "is_closed": True, "opens_at": None, "closes_at": None, "has_break": False, "break_start": None, "break_end": None}
        self.client.put('/api/organizations/schedule/', payload, format='json')
        r = self.client.get('/api/settings/configuration/')
        day1 = next(d for d in r.data['schedule'] if d['weekday'] == 1)
        self.assertEqual(day1['is_closed'], True)

    def test_blocks_user_without_organization(self):
        user_no_org = User.objects.create_user(
            username="cfg_no_org", password="x", organization=None, role="ASSISTANT",
        )
        self.client.force_authenticate(user_no_org)
        r = self.client.get('/api/settings/configuration/')
        self.assertIn(
            r.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )
