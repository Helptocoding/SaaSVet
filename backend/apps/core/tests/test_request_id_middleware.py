"""
Tests del RequestIDMiddleware (P1-5 Fase A — A1).

Verifica la correlación end-to-end:
- genera uuid cuando falta el header
- respeta un X-Request-ID entrante válido
- ignora basura entrante (blindaje anti log-injection) y genera uno nuevo
- devuelve el id en el header de respuesta
- expone el id en request.request_id y en el contextvar durante el request
- limpia el contextvar al terminar (no se filtra al siguiente request)
"""
import uuid

from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from apps.core.middleware import RequestIDMiddleware
from apps.core.request_context import get_request_id


class RequestIDMiddlewareTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()

    def _run(self, **extra):
        captured = {}

        def get_response(request):
            captured["ctx"] = get_request_id()
            captured["attr"] = getattr(request, "request_id", None)
            return HttpResponse("ok")

        mw = RequestIDMiddleware(get_response)
        request = self.factory.get("/api/healthz/", **extra)
        response = mw(request)
        return response, captured

    def test_generates_uuid_when_missing(self):
        response, captured = self._run()
        rid = response["X-Request-ID"]
        uuid.UUID(rid)  # no levanta → es un uuid válido
        self.assertEqual(captured["attr"], rid)
        self.assertEqual(captured["ctx"], rid)

    def test_respects_valid_incoming(self):
        incoming = str(uuid.uuid4())
        response, captured = self._run(HTTP_X_REQUEST_ID=incoming)
        self.assertEqual(response["X-Request-ID"], incoming)
        self.assertEqual(captured["ctx"], incoming)

    def test_rejects_malformed_incoming(self):
        response, captured = self._run(HTTP_X_REQUEST_ID="garbage; DROP TABLE users")
        rid = response["X-Request-ID"]
        self.assertNotIn("DROP", rid)
        uuid.UUID(rid)  # se generó uno fresco y válido
        self.assertEqual(captured["ctx"], rid)

    def test_context_cleared_after_request(self):
        self._run()
        self.assertIsNone(get_request_id())

    def test_header_present_even_on_inner_exception(self):
        """Si la vista interna explota, el contextvar igual se limpia (finally)."""
        def boom(request):
            raise ValueError("inner")

        mw = RequestIDMiddleware(boom)
        request = self.factory.get("/api/healthz/")
        with self.assertRaises(ValueError):
            mw(request)
        self.assertIsNone(get_request_id())
