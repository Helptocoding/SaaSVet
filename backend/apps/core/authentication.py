import logging

from rest_framework.exceptions import AuthenticationFailed
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

        # H-06: defensa-en-profundidad sobre cuentas desactivadas.
        # simplejwt YA rechaza tokens de usuarios inactivos en get_user()
        # cuando CHECK_USER_IS_ACTIVE=True (su default, vigente aquí), pero ese
        # comportamiento depende de un flag de la librería que un upgrade o un
        # override futuro podría apagar silenciosamente. Re-validamos sobre la
        # instancia re-cargada (la que setea el contexto de audit) para que la
        # garantía "desactivar = cortar acceso" sea local y no dependa del
        # default de un tercero. El refresh token se revoca aparte al desactivar
        # (apps.users.services.deactivate_staff), de modo que el endpoint de
        # refresh tampoco siga emitiendo access tokens para la cuenta.
        if not user.is_active:
            raise AuthenticationFailed('Cuenta desactivada.', code='user_inactive')

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
