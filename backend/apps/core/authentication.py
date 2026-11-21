import logging

from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.core.models import set_current_user

logger = logging.getLogger(__name__)

# ADR p65: claim con la versión de sesión del usuario al emitir el token.
SESSION_VERSION_CLAIM = 'sv'
SESSION_REVOKED_MESSAGE = 'La sesión ya no es válida. Inicia sesión de nuevo.'


class SessionRevoked(AuthenticationFailed):
    """401 de un token emitido antes del último cambio de credenciales o de
    acceso (ADR p65). `default_code` es lo que publica el handler de errores."""
    default_detail = SESSION_REVOKED_MESSAGE
    default_code = 'session_revoked'


def stamp_session_version(token, user):
    """Estampa la versión de sesión vigente del usuario en un token (ADR p65).

    Se estampa en el refresh: simplejwt copia el claim al access y lo conserva
    al rotar. Devuelve el mismo token para encadenar.
    """
    token[SESSION_VERSION_CLAIM] = user.session_version
    return token


def token_session_version(token):
    """Versión que declara el token: 0 si no trae el claim (tokens anteriores a
    p65 y del agente); `None` si el claim no es un entero no negativo."""
    try:
        value = token[SESSION_VERSION_CLAIM]
    except KeyError:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def session_version_matches(token, user):
    """True si el token pertenece a la sesión vigente del usuario (ADR p65).

    Igualdad estricta: la versión solo crece, así que un token con versión
    mayor solo saldría de una transacción revertida, que nunca responde.
    """
    version = token_session_version(token)
    if version == user.session_version:
        return True
    logger.info(
        "AUTH_SESSION_REVOKED",
        extra={
            "event": "AUTH_SESSION_REVOKED",
            "user_id": user.pk,
            "token_session_version": version,
            "current_session_version": user.session_version,
        },
    )
    return False


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
        if user.organization_id and not user.organization.is_active:
            raise AuthenticationFailed('Organización desactivada.', code='organization_inactive')
        # ADR p65: un token emitido antes de desactivar, reactivar, restablecer o
        # cambiar la contraseña ya no sirve, aunque no haya vencido. Usa la
        # instancia recién releída: no agrega consultas.
        if not session_version_matches(token, user):
            raise SessionRevoked()

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
