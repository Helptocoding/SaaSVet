"""
TEMP P1-7 SENTRY PROBE — DELETE after validation. Do NOT keep in production.

Validates the production Sentry backend pipeline end to end:
  raise -> DRF custom_exception_handler -> _capture_server_error ->
  Sentry event (environment + release=SHA tags) with before_send scrubbing.

Safety:
  - env-gated: returns 404 unless ENABLE_SENTRY_DEBUG=True (default False).
    The backend reads env at runtime, so the flag flips with a container
    restart — no rebuild. Leave the flag OFF except during the test window.
  - auth required (IsAuthenticated): the request carries an Authorization
    header, so the captured event proves the scrub filters it.

Cleanup (see runbook):
  1. delete this file
  2. remove its import + path in config/urls.py
  3. remove ENABLE_SENTRY_DEBUG in settings.py
  4. remove ENABLE_SENTRY_DEBUG from .env.prod
  5. redeploy
"""
from django.conf import settings
from django.http import Http404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated


class SentryProbeError(Exception):
    """Intentional error to validate Sentry capture. Not a real failure."""


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def sentry_debug(request):
    if not getattr(settings, "ENABLE_SENTRY_DEBUG", False):
        raise Http404()
    raise SentryProbeError(
        "P1-7 Sentry backend probe — intentional 500, safe to ignore."
    )
