"""
test_token.py — Token de WhatsApp cifrado en DB + rotación desde la UI.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.channels.crypto import decrypt_secret, encrypt_secret
from apps.channels.models import ChannelAccount
from apps.channels.providers import MetaWhatsAppProvider
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSIONS
from apps.organizations.models import Organization
from apps.users.models import User


def _seed_role(org, role_name):
    codes = PERMISSIONS[role_name]
    role, _ = Role.objects.get_or_create(
        name=role_name, organization=org, defaults={"is_system_role": True})
    if "*.*" in codes:
        w, _ = Permission.objects.get_or_create(code="*.*")
        role.permissions.set([w])
    else:
        role.permissions.set(
            [Permission.objects.get_or_create(code=c)[0] for c in codes])
    return role


class CryptoRoundtripTests(TestCase):
    def test_encrypt_decrypt_roundtrip(self):
        secret = "dummy-super-secreto/con=chars+raros"
        ct = encrypt_secret(secret)
        self.assertNotEqual(ct, secret)          # cifrado, no claro
        self.assertNotIn(secret, ct)
        self.assertEqual(decrypt_secret(ct), secret)

    def test_empty_and_garbage(self):
        self.assertEqual(encrypt_secret(""), "")
        self.assertEqual(decrypt_secret(""), "")
        self.assertEqual(decrypt_secret("no-es-fernet"), "")   # nunca lanza


class ChannelTokenTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Tok Org", timezone="UTC")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="111222333")

    def test_set_get_token(self):
        self.channel.set_access_token("dummy-token-1234")
        self.channel.save()
        self.channel.refresh_from_db()
        self.assertTrue(self.channel.has_db_token)
        self.assertEqual(self.channel.access_token_last4, "1234")
        self.assertNotIn("EAAG", self.channel.access_token_encrypted)  # cifrado
        self.assertEqual(self.channel.get_access_token(), "dummy-token-1234")

    def test_clear_token(self):
        self.channel.set_access_token("x")
        self.channel.set_access_token("")
        self.assertFalse(self.channel.has_db_token)
        self.assertEqual(self.channel.access_token_last4, "")


class ProviderTokenSourceTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Prov Org", timezone="UTC")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="444555666",
            provider_credentials_ref="WHATSAPP_ACCESS_TOKEN")

    def test_prefers_db_token_over_env(self):
        self.channel.set_access_token("db-token")
        self.channel.save()
        with self.settings(WHATSAPP_ACCESS_TOKEN="env-token"):
            provider = MetaWhatsAppProvider(self.channel)
            self.assertEqual(provider._access_token(), "db-token")

    def test_falls_back_to_env_when_no_db_token(self):
        with self.settings(WHATSAPP_ACCESS_TOKEN="env-token"):
            provider = MetaWhatsAppProvider(self.channel)
            self.assertEqual(provider._access_token(), "env-token")


class TokenEndpointTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Tok API Org", timezone="UTC")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="777888999")
        admin_role = _seed_role(self.org, "ADMIN")
        self.admin = User.objects.create_user(
            username="tok_admin", password="p", organization=self.org, role="ADMIN")
        UserRole.objects.get_or_create(user=self.admin, role=admin_role)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_set_token_is_write_only(self):
        r = self.client.post("/api/inbox/whatsapp-token/",
                             {"token": "dummy-nuevo-9876"},  # gitleaks:allow
                             format="json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body["configured"])
        self.assertEqual(body["last4"], "9876")
        self.assertNotIn("9876", str(body.get("token", "")))  # nunca el token
        self.assertNotIn("token", body)
        self.channel.refresh_from_db()
        self.assertEqual(self.channel.get_access_token(), "dummy-nuevo-9876")

    def test_get_status_no_token(self):
        r = self.client.get("/api/inbox/whatsapp-token/")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["configured"])

    def test_empty_token_rejected(self):
        r = self.client.post("/api/inbox/whatsapp-token/", {"token": ""},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_assistant_forbidden(self):
        assistant_role = _seed_role(self.org, "ASSISTANT")
        asst = User.objects.create_user(
            username="tok_asst", password="p", organization=self.org,
            role="ASSISTANT")
        UserRole.objects.get_or_create(user=asst, role=assistant_role)
        self.client.force_authenticate(asst)
        r = self.client.post("/api/inbox/whatsapp-token/", {"token": "x"},
                             format="json")
        self.assertEqual(r.status_code, 403, r.content)
