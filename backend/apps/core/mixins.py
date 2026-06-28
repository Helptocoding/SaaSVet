"""Reusable DRF view mixins (cross-domain, no business logic)."""


class NoStoreResponseMixin:
    """Force ``Cache-Control: no-store`` on every response (H-09).

    Auth endpoints (login, refresh, self-service password change) return
    credential material — access/refresh tokens. A misconfigured intermediary
    proxy that caches by URL must never persist these responses where a third
    party on the same network could read them back.

    Applied via ``finalize_response`` so it covers success, validation-error,
    and throttle (429) responses uniformly — every return path of the handler
    passes through here, including the early ``Response`` objects the auth
    views build by hand.
    """

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response
