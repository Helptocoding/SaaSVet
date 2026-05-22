"""
Input validation tests for `PlatformOrgCreateView`.

Covers:
  - Privilege-escalation guards: payload cannot inject ADMIN_SAAS,
    is_superuser, is_staff via request body. Server forces safe defaults.
  - Pre-DB duplicate checks (username, email, org name) return 400.
  - Password floor (12 chars) enforced.
  - Password never echoed in response.
  - tax_rate range.
  - HTML sanitization on text fields.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.organizations.models import Organization


User = get_user_model()


def _payload(**overrides):
    base = {
        'name': 'Clinica Test',
        'timezone': 'America/Mexico_City',
        'tax_rate': '0.1600',
        'admin_username': 'newadmin',
        'admin_email': 'newadmin@test.com',
        'admin_password': 'SuperPass1234!',
        'admin_first_name': 'Laura',
        'admin_last_name': 'García',
    }
    base.update(overrides)
    return base


class PlatformOrgCreateValidationTests(TestCase):
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

    # --- Privilege escalation guards -------------------------------------

    def test_payload_cannot_inject_role_admin_saas(self):
        """Even if payload tries to set role='ADMIN_SAAS', the server
        forces role='ADMIN' for the freshly provisioned tenant admin."""
        response = self.client.post(
            self.URL,
            _payload(role='ADMIN_SAAS', admin_role='ADMIN_SAAS'),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        admin = User.objects.get(username='newadmin')
        self.assertEqual(admin.role, 'ADMIN')

    def test_payload_cannot_inject_is_superuser(self):
        response = self.client.post(
            self.URL,
            _payload(is_superuser=True, admin_is_superuser=True),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        admin = User.objects.get(username='newadmin')
        self.assertFalse(admin.is_superuser)

    def test_payload_cannot_inject_is_staff(self):
        response = self.client.post(
            self.URL,
            _payload(is_staff=True, admin_is_staff=True),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        admin = User.objects.get(username='newadmin')
        self.assertFalse(admin.is_staff)

    # --- Duplicate checks -------------------------------------------------

    def test_duplicate_username_400(self):
        op_org = self.platform_op.organization
        User.objects.create_user(
            username='newadmin',
            email='other@test.com',
            password='OtherPass1234!',
            role='VET',
            organization=op_org,
        )
        response = self.client.post(self.URL, _payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('admin_username', response.data['errors'])

    def test_duplicate_email_400(self):
        op_org = self.platform_op.organization
        User.objects.create_user(
            username='otherone',
            email='newadmin@test.com',
            password='OtherPass1234!',
            role='VET',
            organization=op_org,
        )
        response = self.client.post(self.URL, _payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('admin_email', response.data['errors'])

    def test_duplicate_org_name_400(self):
        Organization.objects.create(name='Clinica Test')
        response = self.client.post(self.URL, _payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('name', response.data['errors'])

    def test_duplicate_org_name_case_insensitive_400(self):
        Organization.objects.create(name='clinica test')
        response = self.client.post(self.URL, _payload(name='Clinica Test'), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # --- Password validators ---------------------------------------------

    def test_password_min_12_enforced(self):
        response = self.client.post(
            self.URL,
            _payload(admin_password='Short1!Ab'),  # 9 chars
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('admin_password', response.data['errors'])

    def test_password_exactly_12_accepted(self):
        response = self.client.post(
            self.URL,
            _payload(admin_password='AbcDef12345!'),  # 12 chars
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_password_numeric_only_rejected_by_django_validators(self):
        response = self.client.post(
            self.URL,
            _payload(admin_password='123456789012'),  # 12 digits, all numeric
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('admin_password', response.data['errors'])

    def test_password_never_in_response(self):
        response = self.client.post(self.URL, _payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.content.decode('utf-8')
        self.assertNotIn('SuperPass1234!', body)
        self.assertNotIn('password', response.data.get('admin', {}))

    # --- tax_rate ---------------------------------------------------------

    def test_invalid_tax_rate_negative_400(self):
        response = self.client.post(
            self.URL,
            _payload(tax_rate='-0.1000'),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_tax_rate_over_one_400(self):
        response = self.client.post(
            self.URL,
            _payload(tax_rate='1.5000'),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # --- Sanitization -----------------------------------------------------

    def test_sanitize_text_strips_html_from_name(self):
        """sanitize_text + comment-only input → empty name → 400.

        Note on bleach behavior: with strip=True, bleach removes tag
        wrappers but keeps inner text content. So '<script>alert(1)</script>'
        becomes 'alert(1)' (still non-empty). Comment-only input is the
        case that fully collapses to '' and triggers the empty check."""
        response = self.client.post(
            self.URL,
            _payload(name='<!-- only comment -->'),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('name', response.data['errors'])

    def test_sanitize_text_removes_script_wrapper(self):
        """<script> wrapper stripped; inner text persisted clean."""
        response = self.client.post(
            self.URL,
            _payload(name='Clinica <script>x</script>'),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        org = Organization.objects.get(
            public_id=response.data['organization']['public_id']
        )
        self.assertNotIn('<script>', org.name)
        self.assertNotIn('</script>', org.name)

    def test_sanitize_text_strips_html_keeps_text(self):
        """If the name contains HTML *plus* real text, the HTML is
        stripped and the rest is persisted clean."""
        response = self.client.post(
            self.URL,
            _payload(name='Clinica <b>X</b>'),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        org = Organization.objects.get(public_id=response.data['organization']['public_id'])
        self.assertEqual(org.name, 'Clinica X')

    def test_empty_required_field_400(self):
        response = self.client.post(
            self.URL,
            _payload(admin_first_name=''),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('admin_first_name', response.data['errors'])

    # --- Response shape ---------------------------------------------------

    def test_response_contains_request_id_and_duration(self):
        response = self.client.post(self.URL, _payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('request_id', response.data)
        self.assertIn('duration_ms', response.data)

    def test_response_uses_public_ids_not_pk(self):
        response = self.client.post(self.URL, _payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('public_id', response.data['organization'])
        self.assertIn('public_id', response.data['admin'])
        # public_id is a UUID string, length 36.
        self.assertEqual(len(response.data['organization']['public_id']), 36)
        self.assertEqual(len(response.data['admin']['public_id']), 36)
