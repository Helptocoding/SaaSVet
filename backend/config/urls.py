"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from decouple import config
from django.contrib import admin
from django.urls import path, include
from apps.core.views import healthz, readyz, version, SupportMessageView
from apps.channels.views import whatsapp_webhook
from apps.dashboard.views import (
    dashboard_stats, analytics_health, operations_series, financial_series,
    dashboard_summary, dashboard_activation,
)
from apps.users.views import (
    MeView,
    StaffListView,
    StaffCreateView,
    StaffDetailView,
    StaffResetPasswordView,
    StaffReactivateView,
    StaffRoleView,
    StaffImpactView,
    StaffHistoryView,
    StaffProfileView,
    StaffAppointmentsView,
    StaffAbsenceListView,
    StaffMemberAbsencesView,
    StaffAbsenceDetailView,
    StaffPermissionCatalogView,
    MyMFAView,
    MyMFASetupView,
    MyMFAEnableView,
    MyMFADisableView,
    MyMFARecoveryCodesView,
    ChangeMyPasswordView,
)
from rest_framework.routers import DefaultRouter
from apps.patients.views import PetViewSet, OwnerViewSet
from apps.imports.views import ImportJobViewSet
from apps.organizations.views import (
    OrganizationMeView,
    OrganizationSettingsView,
    OrganizationScheduleView,
    OrganizationConfigurationView,
)
from rest_framework_simplejwt.views import (
    TokenBlacklistView,
    TokenObtainPairView,
    TokenRefreshView,
)
from apps.users.serializers import EmailOrUsernameTokenObtainPairSerializer
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
import logging
from apps.core.mixins import NoStoreResponseMixin
from apps.core.throttling import (
    LoginMFAThrottle, LoginRateThrottle, LoginUserRateThrottle, TokenLogoutThrottle,
)
from apps.core.sanitize import sanitize_text

_login_logger = logging.getLogger('django')


class ThrottledTokenObtainPairView(NoStoreResponseMixin, TokenObtainPairView):
    # Issue #13 / ADR p15: el default global REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES
    # ahora es IsAuthenticated. Las vistas públicas (login, refresh) DEBEN declarar
    # AllowAny explícito para no romper el flujo de autenticación.
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle, LoginUserRateThrottle]
    # ADR p48: resuelve login por correo O username antes de autenticar.
    serializer_class = EmailOrUsernameTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code in (400, 401):
            ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
            raw_username = (request.data or {}).get('username', '')
            _login_logger.warning(
                "LOGIN_FAILED",
                extra={
                    "ip": ip.split(',')[0].strip(),
                    # sanitizar para prevenir payload injection en logs
                    "username": sanitize_text(raw_username, max_length=100),
                }
            )
            return response

        # ADR p68: con verificación en dos pasos la contraseña correcta devuelve
        # un reto, no tokens; las compuertas corren en el segundo paso.
        if response.status_code == 200 and response.data.get('mfa_required'):
            return response

        # ADR p21: temp-password lifecycle gates that need a successful
        # authentication to evaluate. We run them AFTER super().post()
        # because they require resolving the user, which the parent
        # class did for us during password validation.
        if response.status_code == 200:
            from django.contrib.auth import get_user_model
            from rest_framework_simplejwt.tokens import AccessToken
            from rest_framework_simplejwt.exceptions import TokenError

            User = get_user_model()
            # ADR p48: resolver el usuario por el user_id del access token recién
            # emitido, NO por `request.data['username']`. El login ahora acepta
            # correo o username (resolver del serializer), así que buscar por
            # username rompía el gate de temp-password para los logins por correo
            # (DoesNotExist → se saltaba el 403 de expiración). El token ya
            # codifica el usuario autenticado → lookup agnóstico al identificador.
            try:
                uid = AccessToken(response.data['access'])['user_id']
                user = User.objects.get(pk=uid)
            except (KeyError, TokenError, User.DoesNotExist):
                # Race: user borrado entre auth y re-fetch, o token sin user_id.
                # Dejar pasar la respuesta — el próximo request fallará naturalmente.
                return response

            gate = _login_gate_response(user)
            if gate is not None:
                return gate

            # Tag the response with the must_change flag so the frontend
            # can force-redirect to /change-password without an extra
            # round-trip to /me/.
            if user.password_must_change:
                response.data['must_change_password'] = True

            # Fase 1 Equipo: último acceso, solo tras pasar todas las compuertas
            # (un login rechazado arriba no cuenta como acceso).
            from apps.users.services import record_user_access
            record_user_access(user)

        return response


def _login_gate_response(user):
    """Compuertas que exigen saber quién se autenticó (ADR p21 y orden 2): clínica
    desactivada y contraseña temporal vencida. ``None`` si puede entrar. Las
    comparten el login con contraseña y el segundo paso con MFA (ADR p68)."""
    from rest_framework.response import Response
    from apps.users.services import is_temp_password_expired

    if user.organization_id and not user.organization.is_active:
        return Response({'code': 'organization_inactive',
                         'detail': 'Organización desactivada.'}, status=403)

    if is_temp_password_expired(user):
        _login_logger.warning(
            "TEMP_PASSWORD_EXPIRED",
            extra={
                "event": "TEMP_PASSWORD_EXPIRED",
                "user_id": user.pk,
                "username": user.username,
                "issued_at": user.password_temp_issued_at.isoformat()
                    if user.password_temp_issued_at else None,
            },
        )
        return Response(
            {
                "code": "temp_password_expired",
                "detail": "Contraseña temporal expirada. Solicita un nuevo reset al administrador.",
            },
            status=403,
        )
    return None


class TokenMFAView(NoStoreResponseMixin, APIView):
    """POST /api/token/mfa/ — segundo paso del login con verificación en dos
    pasos (ADR p68). Body ``{mfa_token, code}``: el reto que devolvió
    ``/api/token/`` y un código de la app o de respaldo. Responde lo mismo que un
    login normal; ``recovery_codes_remaining`` cuando se usó un código de respaldo."""
    permission_classes = [AllowAny]
    throttle_classes = [LoginMFAThrottle]

    def post(self, request):
        from rest_framework.exceptions import ValidationError
        from rest_framework.response import Response
        from apps.users.mfa import complete_login_challenge
        from apps.users.serializers import EmailOrUsernameTokenObtainPairSerializer
        from apps.users.services import record_user_access

        data = request.data or {}
        token, code = data.get('mfa_token'), data.get('code')
        if not isinstance(token, str) or not token or not isinstance(code, str) or not code.strip():
            raise ValidationError({'code': ['Escribe el código de tu app o un código de respaldo.']})
        user, method, remaining = complete_login_challenge(token, code)
        gate = _login_gate_response(user)
        if gate is not None:
            return gate
        refresh = EmailOrUsernameTokenObtainPairSerializer.get_token(user)
        body = {'refresh': str(refresh), 'access': str(refresh.access_token)}
        if user.password_must_change:
            body['must_change_password'] = True
        if method == 'recovery':
            body['recovery_codes_remaining'] = remaining
        record_user_access(user)
        return Response(body)


class PublicTokenRefreshView(NoStoreResponseMixin, TokenRefreshView):
    """Refresh endpoint público — sin esto, el default IsAuthenticated bloquea
    el flujo de renovación de tokens (Issue #13 / ADR p15).

    Throttle dedicado (LoginRateThrottle) para prevenir spam de refresh con un
    token robado — sin él solo aplicaría user/anon default (500/h), insuficiente
    para una operación de credencial-equivalente."""
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle, LoginUserRateThrottle]

    def post(self, request, *args, **kwargs):
        # Comprobar antes de rotar/blacklistear el refresh anterior.
        from django.contrib.auth import get_user_model
        from rest_framework_simplejwt.tokens import RefreshToken
        from rest_framework_simplejwt.exceptions import TokenError
        from rest_framework.response import Response
        from apps.core.authentication import SessionRevoked, session_version_matches
        try:
            refresh = RefreshToken(request.data.get('refresh', ''))
            uid = refresh['user_id']
            user = get_user_model().objects.select_related('organization').get(pk=uid)
        except (TokenError, KeyError, get_user_model().DoesNotExist):
            return super().post(request, *args, **kwargs)
        if user.organization_id and not user.organization.is_active:
            return Response({'code': 'organization_inactive',
                             'detail': 'Organización desactivada.'}, status=403)
        # ADR p65: un refresh emitido antes del último cambio de credenciales o
        # de acceso no se rota (ni crea un OutstandingToken nuevo).
        if not session_version_matches(refresh, user):
            raise SessionRevoked()
        response = super().post(request, *args, **kwargs)
        # Fase 1 Equipo: una sesión que se renueva sola también es actividad;
        # sin esto, «último acceso» envejecería aunque la persona use el sistema
        # a diario. Como máximo una escritura por hora (record_user_access).
        if response.status_code == 200:
            from apps.users.services import record_user_access
            record_user_access(user)
        return response

class PublicTokenLogoutView(NoStoreResponseMixin, TokenBlacklistView):
    """Revoca el refresh recibido. Sin autenticación por access token, que puede
    haber expirado: la prueba de posesión es el propio refresh, y un token de otro
    tipo o ya revocado responde 401.

    El access token sigue siendo válido hasta expirar (15 min): JWT sin estado.
    Revocarlo exigiría una lista consultada en cada petición, fuera de este alcance."""
    permission_classes = [AllowAny]
    throttle_classes = [TokenLogoutThrottle]


router = DefaultRouter()
router.register(r'pets', PetViewSet, basename='patient')
router.register(r'owners', OwnerViewSet, basename='owner')
router.register(r'imports', ImportJobViewSet, basename='import')
# Nota PR-4B / ADR p16: `organizations` ya NO es ModelViewSet — list/create/
# destroy no se exponen. Dos paths explícitos abajo: /me/ (singleton) y
# /<int:pk>/ (legacy con validación + Sunset RFC 8594).

# Admin URL slug. Configurable por env para ofuscar la superficie de ataque en
# producción (un slug secreto ≠ 'admin' deja `/admin` sin ruta → Django 404).
# Default 'admin' para dev/test. `config()` (decouple) para consistencia con el
# resto de settings; bajo docker `env_file` también queda en os.environ, así que
# el Caddyfile puede leer la MISMA variable vía {$DJANGO_ADMIN_URL}.
# IMPORTANTE: el slug de producción NO debe empezar con 'admin' — el Caddyfile
# fuerza 404 sobre `/admin*` literal y lo capturaría.
_ADMIN_URL = config('DJANGO_ADMIN_URL', default='admin').strip('/')

urlpatterns = [
    path(f'{_ADMIN_URL}/', admin.site.urls),
    # Webhook de WhatsApp (É-F0) — FUERA de /api/: público, autentica por
    # firma HMAC del proveedor (vista Django plana, sin DRF).
    path('hooks/whatsapp/', whatsapp_webhook, name='whatsapp-webhook'),
    # Bandeja del agente conversacional (É-F0 PR-6, permisos agentinbox.*).
    path('api/inbox/', include('apps.agent.urls')),
    # Health endpoints — Docker healthchecks + external uptime monitor (Capa 0).
    # No auth; never log to RBAC audit. Keep first so they short-circuit on cheap match.
    path('api/healthz/', healthz, name='healthz'),
    path('api/readyz/', readyz, name='readyz'),
    # Build/version probe (P1-5) — qué commit/environment está corriendo.
    path('api/version/', version, name='version'),
    # Rutas explícitas que colisionarían con el router deben ir ANTES del include del router
    path('api/organizations/schedule/', OrganizationScheduleView.as_view(), name='organization-schedule'),
    path('api/organizations/settings/', OrganizationSettingsView.as_view()),
    path('api/organizations/me/', OrganizationMeView.as_view(), name='organization-me'),
    path('api/settings/configuration/', OrganizationConfigurationView.as_view(), name='configuration-aggregate'),
    path('api/appointments/', include('apps.appointments.urls')),
    path('api/token/', ThrottledTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/mfa/', TokenMFAView.as_view(), name='token_mfa'),
    path('api/users/mfa/', MyMFAView.as_view(), name='my-mfa'),
    path('api/users/mfa/setup/', MyMFASetupView.as_view(), name='my-mfa-setup'),
    path('api/users/mfa/enable/', MyMFAEnableView.as_view(), name='my-mfa-enable'),
    path('api/users/mfa/disable/', MyMFADisableView.as_view(), name='my-mfa-disable'),
    path('api/users/mfa/recovery-codes/', MyMFARecoveryCodesView.as_view(),
         name='my-mfa-recovery-codes'),
    path('api/token/refresh/', PublicTokenRefreshView.as_view(), name='token_refresh'),
    path('api/token/logout/', PublicTokenLogoutView.as_view(), name='token_logout'),
    path('api/', include(router.urls)),
    path('api/me/', MeView.as_view()),
    path('api/staff/', StaffListView.as_view(), name='staff-list'),
    path('api/staff/create/', StaffCreateView.as_view(), name='staff-create'),
    # ADR p67: rutas fijas de ausencias ANTES de `<str:pk>/`.
    path('api/staff/absences/', StaffAbsenceListView.as_view(), name='staff-absences'),
    path('api/staff/permission-catalog/', StaffPermissionCatalogView.as_view(),
         name='staff-permission-catalog'),
    path('api/staff/absences/<str:pk>/', StaffAbsenceDetailView.as_view(),
         name='staff-absence-detail'),
    path('api/staff/<str:pk>/', StaffDetailView.as_view(), name='staff-detail'),
    # ADR p21: admin-initiated password reset for staff member.
    path('api/staff/<str:pk>/reset-password/', StaffResetPasswordView.as_view(),
         name='staff-reset-password'),
    # Plan Equipo (A2): reactivar a un integrante desactivado.
    path('api/staff/<str:pk>/reactivate/', StaffReactivateView.as_view(),
         name='staff-reactivate'),
    # ADR p66: cambio de rol, impacto antes de desactivar e historial de accesos.
    path('api/staff/<str:pk>/role/', StaffRoleView.as_view(), name='staff-role'),
    path('api/staff/<str:pk>/impact/', StaffImpactView.as_view(), name='staff-impact'),
    path('api/staff/<str:pk>/history/', StaffHistoryView.as_view(), name='staff-history'),
    path('api/staff/<str:pk>/profile/', StaffProfileView.as_view(), name='staff-profile'),
    path('api/staff/<str:pk>/appointments/', StaffAppointmentsView.as_view(),
         name='staff-appointments'),
    path('api/staff/<str:pk>/absences/', StaffMemberAbsencesView.as_view(),
         name='staff-member-absences'),
    # ADR p20: credential self-change. Explicit action endpoint — NOT a
    # field PATCH on /staff/<id>/, which would bypass token invalidation,
    # validate_password, and audit logging.
    path('api/users/change-password/', ChangeMyPasswordView.as_view(),
         name='change-password'),
    path('api/', include('apps.medical_records.urls')),
    path('api/', include('apps.inventory.urls')),
    path('api/', include('apps.billing.urls')),
    path('api/', include('apps.cash.urls')),
    path('api/', include('apps.prescriptions.urls')),
    path('api/', include('apps.legal.urls')),
    path('api/', include('apps.notifications.urls')),
    path('api/dashboard/stats/', dashboard_stats),
    path('api/internal/analytics-health/', analytics_health),
    path('api/v1/dashboard/operations/series/', operations_series),
    path('api/v1/dashboard/financial/series/', financial_series),
    path('api/v1/dashboard/summary/', dashboard_summary),
    path('api/v1/dashboard/activation/', dashboard_activation),
    # Cross-tenant SaaS platform operations (ADR-16 / 2026-05-22).
    # Routes inside require IsPlatformOperator — distinct from /api/ tenant scope.
    path('api/platform/', include('apps.platform.urls')),
    path('api/support/message/', SupportMessageView.as_view(), name='support-message'),
]
