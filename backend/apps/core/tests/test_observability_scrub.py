"""
Tests del scrubbing de privacidad de Sentry (P1-5 Fase A — A2).

Invariante de privacidad de un SaaS clínico: nunca debe salir a un tercero
historial clínico, notas médicas, teléfonos, emails, datos financieros ni tokens.
"""
from django.test import SimpleTestCase

from apps.core.observability import before_send, scrub_event


class SentryScrubTests(SimpleTestCase):

    def test_drops_request_body_and_cookies(self):
        event = {
            "request": {
                # body puede traer notas clínicas / montos / teléfonos → fuera
                "data": {"diagnosis": "diabetes felina", "owner_phone": "5551234567"},
                "cookies": {"sessionid": "secret"},
                "headers": {
                    "Authorization": "Bearer supersecret",
                    "Cookie": "sessionid=secret",
                    "Content-Type": "application/json",
                },
            }
        }
        out = scrub_event(event)
        self.assertNotIn("data", out["request"])
        self.assertNotIn("cookies", out["request"])
        self.assertEqual(out["request"]["headers"]["Authorization"], "[Filtered]")
        self.assertEqual(out["request"]["headers"]["Cookie"], "[Filtered]")
        # Headers benignos se conservan para poder debuggear.
        self.assertEqual(out["request"]["headers"]["Content-Type"], "application/json")

    def test_filters_idempotency_and_csrf_headers(self):
        event = {"request": {"headers": {"X-Idempotency-Key": "k", "X-CSRFToken": "t"}}}
        out = scrub_event(event)
        self.assertEqual(out["request"]["headers"]["X-Idempotency-Key"], "[Filtered]")
        self.assertEqual(out["request"]["headers"]["X-CSRFToken"], "[Filtered]")

    def test_strips_user_pii_keeps_id(self):
        event = {"user": {"id": "42", "email": "a@b.com", "username": "vet", "ip_address": "1.2.3.4"}}
        out = scrub_event(event)
        self.assertEqual(out["user"]["id"], "42")  # id interno NO es PII → se mantiene
        for key in ("email", "username", "ip_address"):
            self.assertNotIn(key, out["user"])

    def test_handles_missing_request_and_user(self):
        self.assertEqual(scrub_event({}), {})
        self.assertIsNone(scrub_event(None))

    def test_before_send_scrubs_and_returns_event(self):
        event = {"request": {"data": {"x": 1}}}
        out = before_send(event, {})
        self.assertIs(out, event)
        self.assertNotIn("data", out["request"])

    def test_before_send_never_raises(self):
        # Shape inesperado no debe propagar excepción.
        try:
            before_send({"request": "not-a-dict"}, {})
        except Exception as exc:  # pragma: no cover
            self.fail(f"before_send levantó {exc!r}")
