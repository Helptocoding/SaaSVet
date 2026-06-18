import logging

from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.core.models import set_current_user

logger = logging.getLogger(__name__)


class TenantJWTAuthentication(JWTAuthentication):
    """
    Extiende JWTAuthentication para cargar el user con select_related('organization')
    y setear el contexto de audit trail (created_by / updated_by).
    """

    def authenticate(self, request):
        result = super().authenticate(request)

        if result is None:
            return None

        user, token = result

        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.select_related('organization').get(pk=user.pk)

        set_current_user(user)
        self._tag_sentry(user)

        if user.organization is None:
            logger.warning(
                "JWT autenticado pero sin organización | user_id=%s",
                user.pk,
            )

        return (user, token)

    @staticmethod
    def _tag_sentry(user):
        """
        Adjunta contexto de tenant a los eventos Sentry del request (P1-5 A2).

        Solo ids internos (no PII): `organization_id` como tag para filtrar
        "qué clínica fue afectada", y `user.id` (sin email/username — el
        scrubbing de observability.before_send + send_default_pii=False
        garantizan que no salga PII). No-op si Sentry no está inicializado.
        """
        try:
            import sentry_sdk

            sentry_sdk.set_user({"id": str(user.pk)})
            if user.organization_id is not None:
                sentry_sdk.set_tag("organization_id", user.organization_id)
        except Exception:  # pragma: no cover - defensivo
            pass
