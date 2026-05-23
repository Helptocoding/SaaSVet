"""
Network helpers — request-side parsing of headers and proxy chains.

Module dedicated to HTTP/network concerns. Distinct from `apps/core/utils.py`
(which we intentionally avoid as an arch-cementery) and from
`apps/core/middleware.py` (which is request-pipeline). Future home for:
forwarded headers, trusted-proxy validation, IP geo enrichment, security
event correlation, audit-trail context extraction.
"""
from __future__ import annotations


def get_client_ip(request) -> str:
    """
    Best-effort extraction of the originating client IP from a Django request.

    Honors ``X-Forwarded-For`` by taking the first (left-most) hop, which is
    the canonical convention when running behind a single trusted proxy
    (Railway, nginx, Cloudflare). When the header is absent, falls back to
    ``REMOTE_ADDR``.

    This implementation does NOT validate the proxy chain — it assumes
    Railway's edge is trusted to strip spoofed headers. If we ever sit
    behind multiple proxy layers, revisit and apply a trusted-proxy
    allowlist (see e.g. Django's ``USE_X_FORWARDED_HOST`` discussion and
    ``django-ipware`` for inspiration).

    Returns an empty string when no source can be determined (very unusual
    in production but possible in tests with bare ``RequestFactory``).
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        # XFF is a comma-separated chain: "client, proxy1, proxy2".
        # The originating client is the left-most entry.
        first = forwarded.split(',')[0].strip()
        if first:
            return first
    return request.META.get('REMOTE_ADDR', '') or ''


def get_user_agent(request, *, max_length: int = 255) -> str:
    """
    Truncated User-Agent string for audit logging.

    Cap at ``max_length`` (default 255) so a bloated UA cannot blow up
    log size or DB columns. Returns an empty string when the header is
    missing.
    """
    ua = request.META.get('HTTP_USER_AGENT', '') or ''
    return ua[:max_length]
