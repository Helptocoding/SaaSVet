"""
Tests de correlación del 500 con el request_id (P1-5 Fase A — A1).

Verifica que el handler de excepciones:
- reusa el request_id del contexto (no acuña uno distinto al de los logs)
- lo incluye en el body de la respuesta 500
- lo escribe en el log del 500 (correlación log ↔ respuesta ↔ Sentry)
- acuña uno válido si no hay request_id en contexto
"""
import uuid
from unittest.mock import patch

from django.test import TestCase

from apps.core.exceptions import custom_exception_handler
from apps.core.request_context import reset_request_id, set_request_id


class _Ctx(dict):
    def __init__(self, request=None, view=None):
        super().__init__()
        self["request"] = request
        self["view"] = view


# Mock del envío a Sentry: los tests no deben emitir eventos reales (el .env de
# dev puede tener un DSN). Verificamos el wiring (que se llamó) sin red.
@patch("sentry_sdk.capture_exception")
class ServerErrorRequestIdTests(TestCase):

    def test_500_reuses_context_request_id(self, mock_capture):
        rid = "11111111-1111-1111-1111-111111111111"
        token = set_request_id(rid)
        try:
            with self.assertLogs("django", level="ERROR") as cm:
                response = custom_exception_handler(ValueError("boom"), _Ctx())
        finally:
            reset_request_id(token)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["code"], "server_error")
        self.assertEqual(response.data["request_id"], rid)
        # El mismo id quedó en el log → correlación respuesta ↔ stdout.
        self.assertTrue(any(rid in line for line in cm.output))
        # Se reportó a Sentry (con el scope enriquecido).
        mock_capture.assert_called_once()

    def test_500_generates_valid_id_without_context(self, mock_capture):
        with self.assertLogs("django", level="ERROR"):
            response = custom_exception_handler(ValueError("x"), _Ctx())
        self.assertEqual(response.status_code, 500)
        uuid.UUID(response.data["request_id"])  # válido aunque no hubiera contexto
