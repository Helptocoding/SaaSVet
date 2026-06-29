"""
Tests del endpoint POST /api/support/message/ — envio de reportes a Discord.

Verifica:
- exito sin imagen
- exito con imagen
- error por mensaje vacio
- 503 si webhook no configurado
- 401 sin autenticacion
- validacion de tamano y tipo de imagen
- errores de red/timeout de Discord
"""
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.organizations.models import Organization
from apps.users.models import User

SUPPORT_URL = "/api/support/message/"


class SupportMessageTests(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Support Org", timezone="UTC")
        self.user = User.objects.create_user(
            username="support_user",
            password="pass1234!X",
            organization=self.org,
            role="VET",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @override_settings(DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/test/123")
    @patch("apps.core.services.requests.post")
    def test_success_without_image(self, mock_post):
        mock_post.return_value.status_code = 204

        resp = self.client.post(
            SUPPORT_URL,
            {"message": "Bug en boton de imprimir", "page_url": "https://app.example.com/invoices"},
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.json()["ok"])
        mock_post.assert_called_once()
        sent_payload = mock_post.call_args[1]["json"]
        embed = sent_payload["embeds"][0]
        self.assertEqual(embed["title"], "🚀 Nuevo reporte de problema")
        self.assertEqual(embed["description"], "Bug en boton de imprimir")
        self.assertEqual(embed["fields"][2]["value"], "https://app.example.com/invoices")

    @override_settings(DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/test/123")
    @patch("apps.core.services.requests.post")
    def test_success_with_image(self, mock_post):
        mock_post.return_value.status_code = 200

        image = SimpleUploadedFile(
            "screenshot.png",
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
            content_type="image/png",
        )
        resp = self.client.post(
            SUPPORT_URL,
            {"message": "Error en dashboard", "image": image},
            format="multipart",
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.json()["ok"])
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        self.assertIn("files", call_kwargs)
        self.assertEqual(call_kwargs["files"]["file"][0], "screenshot.png")

    @override_settings(DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/test/123")
    def test_missing_message_returns_400(self):
        resp = self.client.post(SUPPORT_URL, {"message": ""})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["code"], "validation_error")

    @override_settings(DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/test/123")
    def test_whitespace_message_returns_400(self):
        resp = self.client.post(SUPPORT_URL, {"message": "   "})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["code"], "validation_error")

    @override_settings(DISCORD_WEBHOOK_URL="")
    def test_no_webhook_url_returns_503(self):
        resp = self.client.post(
            SUPPORT_URL, {"message": "Bug report", "page_url": "https://app.example.com/"}
        )
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(resp.json()["code"], "service_unavailable")

    def test_unauthenticated_returns_401(self):
        client = APIClient()
        resp = client.post(SUPPORT_URL, {"message": "Bug"})
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    @override_settings(DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/test/123")
    def test_image_too_large_returns_400(self):
        large_image = SimpleUploadedFile(
            "big.jpg",
            b"\xff\xd8\xff\xe0" + b"x" * (5 * 1024 * 1024 + 1),
            content_type="image/jpeg",
        )
        resp = self.client.post(
            SUPPORT_URL,
            {"message": "Bug", "image": large_image},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("image", resp.json()["errors"])

    @override_settings(DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/test/123")
    def test_non_image_file_returns_400(self):
        text_file = SimpleUploadedFile(
            "notanimage.txt",
            b"hello world",
            content_type="text/plain",
        )
        resp = self.client.post(
            SUPPORT_URL,
            {"message": "Bug", "image": text_file},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("image", resp.json()["errors"])

    @override_settings(DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/test/123")
    @patch("apps.core.services.requests.post")
    def test_discord_returns_error_status(self, mock_post):
        mock_post.return_value.status_code = 400
        mock_post.return_value.text = "Invalid form body"

        resp = self.client.post(
            SUPPORT_URL, {"message": "Bug", "page_url": "https://app.example.com/"}
        )

        self.assertEqual(resp.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(resp.json()["code"], "service_error")

    @override_settings(DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/test/123")
    @patch("apps.core.services.requests.post")
    def test_discord_timeout(self, mock_post):
        import requests as req_lib
        mock_post.side_effect = req_lib.Timeout()

        resp = self.client.post(
            SUPPORT_URL, {"message": "Bug", "page_url": "https://app.example.com/"}
        )

        self.assertEqual(resp.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(resp.json()["code"], "service_error")

    @override_settings(DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/test/123")
    @patch("apps.core.services.requests.post")
    def test_discord_connection_error(self, mock_post):
        import requests as req_lib
        mock_post.side_effect = req_lib.ConnectionError()

        resp = self.client.post(
            SUPPORT_URL, {"message": "Bug", "page_url": "https://app.example.com/"}
        )

        self.assertEqual(resp.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(resp.json()["code"], "service_error")
