"""
End-to-end integration tests for tenant provisioning.

Validates that a freshly provisioned org + admin is genuinely usable:
  - Admin can authenticate via the public token endpoint.
  - Admin's RBAC permissions cover ADMIN_SAAS-equivalent ADMIN scope
    (everything inside their own tenant).
  - Throttle scope kicks in after the configured budget.
  - request_id supplied via X-Request-ID header propagates to logs +
    response.
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.core.permissions import build_permissions_list
from apps.organizations.models import Organization


User = get_user_model()


def _payload(**overrides):
    base = {
        'name': 'Clinica Integration',
        'timezone': 'America/Mexico_City',
        'tax_rate': '0.1600',
        'admin_username': 'integadmin',
        'admin_email': 'integadmin@test.com',
        'admin_password': 'IntegPass1234!',
        'admin_first_name': 'Integ',
        'admin_last_name': 'Admin',
    }
    base.update(overrides)
    return base


class PlatformProvisioningE2ETests(TestCase):
    URL = '/api/platform/organizations/'

    def setUp(self):
        self.client = APIClient()
        op_org = Organization.objects.create(name='Vet Care Internal')
        self.platform_op = User.objects.create_superuser(
            username='platformop',
            email='ops@vetcare.internal',
            password='PlatformPass1234!',
            role='ADMIN_SAAS',
            organization=op_org,
        )
        self.client.force_authenticate(user=self.platform_op)
        # Throttle uses cache backend — clear between tests.
        cache.clear()
        # Login throttle usa la cache `throttle_login` (alias distinto de
        # `default`); limpiarla aísla el bucket 5/15min entre tests (evita 429).
        caches['throttle_login'].clear()

    def test_provisioned_admin_can_login_via_token_endpoint(self):
        response = self.client.post(self.URL, _payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Fresh client without auth — exercise the real login flow.
        public = APIClient()
        login = public.post(
            '/api/token/',
            {
                'username': 'integadmin',
                'password': 'IntegPass1234!',
            },
            format='json',
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.assertIn('access', login.data)
        self.assertIn('refresh', login.data)

    def test_provisioned_admin_has_full_tenant_permissions(self):
        response = self.client.post(self.URL, _payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        admin = User.objects.get(username='integadmin')

        perms = build_permissions_list(admin)
        # ADMIN role has wildcard ('*.*') so the list should be non-empty
        # and cover the canonical core ops.
        for required in [
            'appointment.create',
            'medicalrecord.create',
            'invoice.create',
            'staff.create',
            'patient.create',
        ]:
            self.assertIn(required, perms, msg=f"missing {required}")

    def test_provisioned_admin_can_call_me_endpoint(self):
        response = self.client.post(self.URL, _payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Login + call /me/ as the new admin.
        public = APIClient()
        login = public.post(
            '/api/token/',
            {'username': 'integadmin', 'password': 'IntegPass1234!'},
            format='json',
        )
        access = login.data['access']

        authed = APIClient()
        authed.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        me = authed.get('/api/me/')
        self.assertEqual(me.status_code, status.HTTP_200_OK)
        self.assertEqual(me.data['username'], 'integadmin')
        self.assertEqual(me.data['role'], 'ADMIN')
        self.assertEqual(me.data['organization_name'], 'Clinica Integration')

    def test_x_request_id_header_propagates_to_response(self):
        response = self.client.post(
            self.URL,
            _payload(),
            format='json',
            HTTP_X_REQUEST_ID='trace-from-client-001',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['request_id'], 'trace-from-client-001')

    def test_x_request_id_header_propagates_to_logs(self):
        with self.assertLogs('platform.events', level='INFO') as logs:
            self.client.post(
                self.URL,
                _payload(),
                format='json',
                HTTP_X_REQUEST_ID='trace-log-002',
            )
        success = [r for r in logs.records if r.msg == 'PLATFORM_ORG_PROVISIONED']
        self.assertEqual(len(success), 1)
        self.assertEqual(success[0].request_id, 'trace-log-002')

    def test_response_no_password_field(self):
        response = self.client.post(self.URL, _payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn('password', response.data['admin'])
        self.assertNotIn('admin_password', response.data['admin'])
        # also scan full body string for the literal password value
        self.assertNotIn('IntegPass1234!', response.content.decode('utf-8'))

    def test_provisioned_admin_gated_until_password_change(self):
        """must_change=True admin: blocked on gated endpoints, but /me/ and
        change-password stay reachable; after changing, access is restored."""
        resp = self.client.post(self.URL, _payload(), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        # Real login flow.
        public = APIClient()
        login = public.post(
            '/api/token/',
            {'username': 'integadmin', 'password': 'IntegPass1234!'},
            format='json',
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.assertTrue(login.data.get('must_change_password'))

        authed = APIClient()
        authed.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        # Gated endpoint rejected while must_change=True.
        self.assertEqual(
            authed.get('/api/staff/').status_code,
            status.HTTP_403_FORBIDDEN,
        )
        # /me/ stays reachable (whitelisted).
        self.assertEqual(authed.get('/api/me/').status_code, status.HTTP_200_OK)

        # change-password is reachable while gated AND lifts the gate.
        changed = authed.post(
            '/api/users/change-password/',
            {
                'current_password': 'IntegPass1234!',
                'new_password': 'BrandNewPass5678!',
                'confirm_password': 'BrandNewPass5678!',
            },
            format='json',
        )
        self.assertEqual(changed.status_code, status.HTTP_200_OK)

        # Fresh tokens returned; gate lifted → gated endpoint now allowed.
        authed2 = APIClient()
        authed2.credentials(HTTP_AUTHORIZATION=f"Bearer {changed.data['access']}")
        self.assertEqual(authed2.get('/api/staff/').status_code, status.HTTP_200_OK)


class PlatformProvisioningThrottleTests(TestCase):
    """Throttle scope kicks in after configured budget.

    Patches the ScopedRateThrottle rate directly because
    `override_settings(REST_FRAMEWORK=...)` does not flush DRF's
    `api_settings` import cache reliably across reuses.
    """

    URL = '/api/platform/organizations/'

    def setUp(self):
        self.client = APIClient()
        op_org = Organization.objects.create(name='Vet Care Internal')
        self.platform_op = User.objects.create_superuser(
            username='platformop',
            email='ops@vetcare.internal',
            password='PlatformPass1234!',
            role='ADMIN_SAAS',
            organization=op_org,
        )
        self.client.force_authenticate(user=self.platform_op)
        cache.clear()
        # Login throttle usa la cache `throttle_login` (alias distinto de
        # `default`); limpiarla aísla el bucket 5/15min entre tests (evita 429).
        caches['throttle_login'].clear()

    def test_throttle_blocks_after_budget(self):
        from unittest import mock
        from rest_framework.throttling import ScopedRateThrottle

        # Patch the rate parser to return a 2/hour rate when asked for
        # the platform_org_create scope. Other scopes pass through.
        original_get_rate = ScopedRateThrottle.get_rate

        def fake_get_rate(self):
            if getattr(self, 'scope', None) == 'platform_org_create':
                return '2/hour'
            return original_get_rate(self)

        with mock.patch.object(ScopedRateThrottle, 'get_rate', fake_get_rate):
            # Budget = 2/hour.
            for i in range(2):
                response = self.client.post(
                    self.URL,
                    _payload(
                        name=f'Org {i}',
                        admin_username=f'admin{i}',
                        admin_email=f'admin{i}@test.com',
                    ),
                    format='json',
                )
                self.assertEqual(
                    response.status_code,
                    status.HTTP_201_CREATED,
                    msg=f"call #{i} failed: {response.data}",
                )

            # 3rd call must be throttled (429).
            third = self.client.post(
                self.URL,
                _payload(
                    name='Org 2',
                    admin_username='admin2',
                    admin_email='admin2@test.com',
                ),
                format='json',
            )
            self.assertEqual(third.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
