"""
Tests del endpoint /api/version/ (P1-5 Fase A — A5).

Verifica:
- responde 200 sin autenticación (probe pública, como healthz)
- expone version / commit / environment
- refleja los valores configurados en settings
"""
from django.test import TestCase, override_settings


class VersionEndpointTests(TestCase):

    def test_public_and_shape(self):
        resp = self.client.get("/api/version/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("version", data)
        self.assertIn("commit", data)
        self.assertIn("environment", data)

    @override_settings(APP_VERSION="abc1234", GIT_SHA="abc1234", ENVIRONMENT="production")
    def test_reports_configured_values(self):
        resp = self.client.get("/api/version/")
        data = resp.json()
        self.assertEqual(data["version"], "abc1234")
        self.assertEqual(data["commit"], "abc1234")
        self.assertEqual(data["environment"], "production")

    @override_settings(GIT_SHA="")
    def test_commit_null_when_unset(self):
        resp = self.client.get("/api/version/")
        self.assertIsNone(resp.json()["commit"])

    def test_response_carries_request_id_header(self):
        """La probe pasa por RequestIDMiddleware → header de correlación presente."""
        resp = self.client.get("/api/version/")
        self.assertIn("X-Request-ID", resp)
