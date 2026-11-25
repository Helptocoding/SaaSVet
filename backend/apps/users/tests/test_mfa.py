"""ADR p68: verificación en dos pasos (TOTP) opcional para ADMIN.

- TOTP según los vectores del RFC 6238; un código no se acepta dos veces.
- Activar exige contraseña y un código de la app; devuelve 10 códigos de
  respaldo de un solo uso. Solo ADMIN, nunca en la demo.
- Con MFA activo la contraseña sola no emite tokens: devuelve un reto que se
  completa en ``/api/token/mfa/`` con un código. El reto vale 5 minutos, un
  inicio de sesión, cinco intentos, y muere si cambia la versión de sesión.
- Restablecer la contraseña (clínica o plataforma) o reactivar quita el MFA.
"""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from apps.core.models import set_current_user
from apps.organizations.models import Organization
from apps.users import mfa as mfa_service
from apps.users import totp
from apps.users.models import StaffAccessEvent, UserMFA

User = get_user_model()
# Contraseña de prueba, no una credencial real.
PASSWORD = 'Contrasena-Segura-1'  # gitleaks:allow
FAST = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


class TotpTests(SimpleTestCase):
    # Secreto público de los vectores de prueba del RFC 6238 (b'12345678901234567890').
    RFC_SECRET = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'  # gitleaks:allow

    def test_rfc6238_sha1_vectors_truncated_to_six_digits(self):
        for unix_time, expected in ((59, '287082'), (1111111109, '081804'),
                                    (1111111111, '050471'), (1234567890, '005924'),
                                    (2000000000, '279037'), (20000000000, '353130')):
            self.assertEqual(totp.code_at(self.RFC_SECRET, unix_time // 30), expected, unix_time)

    def test_window_and_replay(self):
        now = 1_700_000_000
        step = totp.current_step(now)
        for delta in (-1, 0, 1):
            code = totp.code_at(self.RFC_SECRET, step + delta)
            self.assertEqual(totp.matching_step(self.RFC_SECRET, code, now=now), step + delta)
        self.assertIsNone(totp.matching_step(self.RFC_SECRET, totp.code_at(self.RFC_SECRET, step - 2), now=now))
        code = totp.code_at(self.RFC_SECRET, step)
        self.assertIsNone(totp.matching_step(self.RFC_SECRET, code, now=now, after_step=step))
        self.assertEqual(totp.matching_step(self.RFC_SECRET, code[:3] + ' ' + code[3:], now=now), step)
        self.assertIsNone(totp.matching_step(self.RFC_SECRET, '12345', now=now))

    def test_secret_is_encrypted_and_a_wrong_key_does_not_decrypt(self):
        secret = totp.new_secret()
        token = totp.encrypt_secret(secret)
        self.assertNotIn(secret, token)
        self.assertEqual(totp.decrypt_secret(token), secret)
        with override_settings(MFA_ENCRYPTION_KEY='otra-clave'):
            self.assertIsNone(totp.decrypt_secret(token))

    def test_recovery_codes(self):
        codes = totp.new_recovery_codes()
        self.assertEqual(len(set(codes)), 10)
        self.assertEqual(totp.hash_recovery_code(codes[0].upper().replace('-', ' ')),
                         totp.hash_recovery_code(codes[0]))
        self.assertNotIn(codes[0], totp.hash_recovery_code(codes[0]))


@FAST
class _Base(APITestCase):
    def setUp(self):
        set_current_user(None)
        cache.clear()
        caches['throttle_login'].clear()
        self.org = Organization.objects.create(name='Clinica MFA', timezone='UTC')
        self.admin = User.objects.create_user(
            username='mfa_admin', email='mfa_admin@example.com', password=PASSWORD,
            organization=self.org, role='ADMIN', first_name='Ana')
        self.client.force_authenticate(self.admin)

    def enable_mfa(self, user=None):
        user = user or self.admin
        client = APIClient()
        client.force_authenticate(user)
        res = client.post('/api/users/mfa/setup/', {'password': PASSWORD}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        secret = res.data['secret'].replace(' ', '')
        res = client.post('/api/users/mfa/enable/',
                          {'code': totp.code_at(secret, totp.current_step())}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        return secret, res.data['recovery_codes']

    def password_login(self, username='mfa_admin'):
        return APIClient().post('/api/token/', {'username': username, 'password': PASSWORD},
                                format='json')

    def second_step(self, token, code):
        return APIClient().post('/api/token/mfa/', {'mfa_token': token, 'code': code}, format='json')


class EnrollmentTests(_Base):
    def test_full_enrollment(self):
        res = self.client.get('/api/users/mfa/')
        self.assertEqual(res.data, {'available': True, 'enabled': False, 'enabled_at': None,
                                    'recovery_codes_remaining': 0})
        res = self.client.post('/api/users/mfa/setup/', {'password': PASSWORD}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertIn('no-store', res['Cache-Control'])
        secret = res.data['secret'].replace(' ', '')
        self.assertTrue(res.data['otpauth_uri'].startswith('otpauth://totp/'))
        self.assertIn(f'secret={secret}', res.data['otpauth_uri'])
        self.assertFalse(mfa_service.is_mfa_enabled(self.admin))

        wrong = self.client.post('/api/users/mfa/enable/', {'code': '000000'}, format='json')
        self.assertEqual(wrong.status_code, status.HTTP_400_BAD_REQUEST)
        res = self.client.post('/api/users/mfa/enable/',
                               {'code': totp.code_at(secret, totp.current_step())}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual(len(res.data['recovery_codes']), 10)
        self.assertTrue(res.data['enabled'])
        self.assertEqual(res.data['recovery_codes_remaining'], 10)
        row = UserMFA.objects.get(user=self.admin)
        self.assertNotIn(secret, row.secret_encrypted)
        self.assertNotIn(res.data['recovery_codes'][0], str(row.recovery_code_hashes))
        self.assertTrue(StaffAccessEvent.objects.filter(member=self.admin, kind='mfa_enabled').exists())
        again = self.client.post('/api/users/mfa/setup/', {'password': PASSWORD}, format='json')
        self.assertEqual(again.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(again.data['code'], 'mfa_already_enabled')

    def test_setup_needs_the_password(self):
        res = self.client.post('/api/users/mfa/setup/', {'password': 'otra'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', res.data['errors'])

    def test_only_admins_and_never_the_demo(self):
        vet = User.objects.create_user(username='mfa_vet', password=PASSWORD,
                                       organization=self.org, role='VET')
        client = APIClient()
        client.force_authenticate(vet)
        self.assertFalse(client.get('/api/users/mfa/').data['available'])
        res = client.post('/api/users/mfa/setup/', {'password': PASSWORD}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data['code'], 'mfa_not_available')
        demo = Organization.objects.create(name='Demo MFA', timezone='UTC', is_demo=True)
        demo_admin = User.objects.create_user(username='mfa_demo', password=PASSWORD,
                                              organization=demo, role='ADMIN')
        client.force_authenticate(demo_admin)
        res = client.post('/api/users/mfa/setup/', {'password': PASSWORD}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_an_expired_setup_key_must_be_generated_again(self):
        res = self.client.post('/api/users/mfa/setup/', {'password': PASSWORD}, format='json')
        secret = res.data['secret'].replace(' ', '')
        UserMFA.objects.filter(user=self.admin).update(
            pending_created_at=timezone.now() - timedelta(hours=1))
        res = self.client.post('/api/users/mfa/enable/',
                               {'code': totp.code_at(secret, totp.current_step())}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_disable_and_regenerate_need_password_and_a_code(self):
        secret, codes = self.enable_mfa()
        res = self.client.post('/api/users/mfa/disable/', {'password': PASSWORD, 'code': '111111'},
                               format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        res = self.client.post('/api/users/mfa/recovery-codes/',
                               {'password': PASSWORD, 'code': codes[0]}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        new_codes = res.data['recovery_codes']
        self.assertNotIn(codes[1], new_codes)
        res = self.client.post('/api/users/mfa/disable/',
                               {'password': PASSWORD, 'code': codes[1]}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, 'el código viejo ya no vale')
        res = self.client.post('/api/users/mfa/disable/',
                               {'password': PASSWORD, 'code': new_codes[0]}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertFalse(res.data['enabled'])
        self.assertFalse(UserMFA.objects.filter(user=self.admin).exists())
        self.assertTrue(StaffAccessEvent.objects.filter(member=self.admin, kind='mfa_disabled').exists())


class LoginTests(_Base):
    def test_without_mfa_the_password_still_returns_tokens(self):
        res = self.password_login()
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertIn('access', res.data)

    def test_with_mfa_the_password_alone_issues_no_tokens(self):
        secret, _ = self.enable_mfa()
        before = OutstandingToken.objects.filter(user=self.admin).count()
        res = self.password_login()
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual(set(res.data), {'mfa_required', 'mfa_token'})
        self.assertEqual(OutstandingToken.objects.filter(user=self.admin).count(), before)

        step = self.second_step(res.data['mfa_token'], totp.code_at(secret, totp.current_step() + 1))
        self.assertEqual(step.status_code, status.HTTP_200_OK, step.content)
        self.assertIn('no-store', step['Cache-Control'])
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {step.data["access"]}')
        self.assertEqual(client.get('/api/users/mfa/').status_code, status.HTTP_200_OK)

    def test_a_code_and_a_challenge_are_single_use(self):
        secret, _ = self.enable_mfa()
        code = totp.code_at(secret, totp.current_step() + 1)
        first = self.password_login().data['mfa_token']
        self.assertEqual(self.second_step(first, code).status_code, status.HTTP_200_OK)
        again = self.second_step(first, totp.code_at(secret, totp.current_step() + 1))
        self.assertEqual(again.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(again.data['code'], 'mfa_challenge_invalid')
        replay = self.second_step(self.password_login().data['mfa_token'], code)
        self.assertEqual(replay.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(replay.data['code'], 'mfa_code_invalid')

    def test_five_wrong_codes_kill_the_challenge(self):
        secret, _ = self.enable_mfa()
        token = self.password_login().data['mfa_token']
        for _ in range(mfa_service.LOGIN_CHALLENGE_MAX_ATTEMPTS):
            res = self.second_step(token, '000000')
            self.assertEqual(res.data['code'], 'mfa_code_invalid')
        res = self.second_step(token, totp.code_at(secret, totp.current_step() + 1))
        self.assertEqual(res.data['code'], 'mfa_challenge_invalid')

    def test_recovery_code_works_once(self):
        _, codes = self.enable_mfa()
        res = self.second_step(self.password_login().data['mfa_token'], codes[0].upper())
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual(res.data['recovery_codes_remaining'], 9)
        res = self.second_step(self.password_login().data['mfa_token'], codes[0])
        self.assertEqual(res.data['code'], 'mfa_code_invalid')

    def test_tampered_expired_or_outdated_challenges_are_rejected(self):
        secret, _ = self.enable_mfa()
        code = lambda: totp.code_at(secret, totp.current_step() + 1)
        token = self.password_login().data['mfa_token']
        self.assertEqual(self.second_step(token[:-2] + 'xx', code()).data['code'], 'mfa_challenge_invalid')
        with mock.patch.object(mfa_service, 'LOGIN_CHALLENGE_MAX_AGE', -1):
            self.assertEqual(self.second_step(token, code()).data['code'], 'mfa_challenge_invalid')
        from apps.users.services import bump_session_version
        bump_session_version(User.objects.get(pk=self.admin.pk))
        self.assertEqual(self.second_step(token, code()).data['code'], 'mfa_challenge_invalid')

    def test_inactive_clinic_is_rejected_at_the_second_step(self):
        secret, _ = self.enable_mfa()
        token = self.password_login().data['mfa_token']
        Organization.objects.filter(pk=self.org.pk).update(is_active=False)
        res = self.second_step(token, totp.code_at(secret, totp.current_step() + 1))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data['code'], 'organization_inactive')

    def test_missing_fields_are_a_validation_error(self):
        res = APIClient().post('/api/token/mfa/', {'mfa_token': 'x'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


class ResetRemovesMFATests(_Base):
    def test_clinic_reset_removes_mfa_so_the_password_logs_in(self):
        other_admin = User.objects.create_user(username='mfa_admin2', password=PASSWORD,
                                               organization=self.org, role='ADMIN')
        self.enable_mfa(other_admin)
        res = self.client.post(f'/api/staff/{other_admin.public_id}/reset-password/')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertFalse(UserMFA.objects.filter(user=other_admin).exists())
        event = StaffAccessEvent.objects.filter(member=other_admin, kind='password_reset').get()
        self.assertEqual(event.changes, {'mfa_removed': True})
        login = APIClient().post('/api/token/', {'username': 'mfa_admin2',
                                                 'password': res.data['temp_password']}, format='json')
        self.assertIn('access', login.data)

    def test_platform_reset_removes_mfa(self):
        from apps.platform.services.platform_reset_password import platform_reset_password
        self.enable_mfa()
        operator = User.objects.create_user(username='mfa_op', password='x', role='ADMIN_SAAS',
                                            is_superuser=True, is_staff=True)
        platform_reset_password(actor=operator, target_user=User.objects.get(pk=self.admin.pk))
        self.assertFalse(UserMFA.objects.filter(user=self.admin).exists())
        event = StaffAccessEvent.objects.get(member=self.admin, kind='password_reset')
        self.assertEqual(event.changes, {'source': 'platform', 'mfa_removed': True})
