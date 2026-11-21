import uuid

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from django.contrib.auth import get_user_model

from apps.core.network import get_client_ip, get_user_agent
from apps.core.mixins import NoStoreResponseMixin
from apps.core.permissions import (
    HybridPermission, NotDemoAccount, build_permissions_list, make_permission,
    user_has_permission,
)
from apps.core.views import resolve_public_id
from apps.users.serializers import (
    UserSerializer,
    CreateEmployeeSerializer,
    ChangePasswordSerializer,
    UpdateEmployeeSerializer,
)
from apps.users.services import (
    change_password,
    deactivate_staff,
    reactivate_staff,
    reset_password_for_staff,
    update_staff_profile,
)

User = get_user_model()

VALID_ROLES = ['ADMIN', 'VET', 'ASSISTANT']


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        org = user.organization
        # ADR p46: documentos legales pendientes para el gate del frontend.
        from apps.legal.services import pending_documents
        _pending_legal = pending_documents(user)
        return Response({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
            "specialty": user.specialty,
            # Día 6 Fase 4: emite organization (id PK, retrocompat) +
            # organization_public_id (UUID, nuevo). Frontend nuevo debe
            # consumir organization_public_id para deep links.
            "organization": org.id if org else None,
            "organization_public_id": str(org.public_id) if org else None,
            "organization_name": org.name if org else None,
            "organization_timezone": org.timezone if org else "America/Mexico_City",
            # Demo tenant: el frontend oculta "cambiar contraseña" e "importar
            # datos" para los usuarios de la org demo; el backend además bloquea
            # esos endpoints vía NotDemoAccount (no se confía en el frontend).
            "is_demo": bool(getattr(org, "is_demo", False)) if org else False,
            "permissions": build_permissions_list(request.user),
            # ADR p21: credential lifecycle. Frontend reads this to
            # force-redirect to /change-password while True.
            "must_change_password": bool(getattr(user, 'password_must_change', False)),
            # ADR p46: LegalAcceptanceGate. Frontend redirige a /aceptar-terminos
            # mientras legal_acceptance_required=True.
            "legal_acceptance_required": len(_pending_legal) > 0,
            "pending_legal_documents": [
                {
                    "public_id": str(d.public_id),
                    "doc_type": d.doc_type,
                    "version": d.version,
                    "landing_url": d.landing_url,
                }
                for d in _pending_legal
            ],
        })


class StaffListView(APIView):
    """GET /api/staff/ — activos (por defecto, lo consume Citas) o, con
    ``?archived=true``, los inactivos (plan Equipo A2, D6). Ver inactivos exige
    además ``staff.reactivate``: son datos de ex empleados."""
    permission_classes = [make_permission("staff.list")]

    def get(self, request):
        archived = request.query_params.get('archived') == 'true'
        if archived and not user_has_permission(request.user, 'staff.reactivate'):
            raise PermissionDenied("No tienes permiso para ver el personal inactivo.")
        # ADR p51: los service accounts (agente virtual) no son Equipo — se
        # excluyen por flag, nunca por nombre de rol.
        qs = User.objects.filter(
            organization=request.user.organization,
            is_active=not archived,
        ).exclude(role='ADMIN_SAAS').exclude(is_service_account=True).select_related('organization')

        role = request.query_params.get('role')
        if role:
            if role not in VALID_ROLES:
                raise ValidationError(f"Rol inválido. Opciones válidas: {', '.join(VALID_ROLES)}")
            qs = qs.filter(role=role)

        serializer = UserSerializer(qs, many=True)
        return Response(serializer.data)


class StaffCreateView(APIView):
    permission_classes = [make_permission("staff.create")]

    def post(self, request):
        serializer = CreateEmployeeSerializer(
            data=request.data,
            context={'request': request}
        )
        if serializer.is_valid():
            user = serializer.save()
            return Response(
                UserSerializer(user).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class StaffDetailView(APIView):
    """DELETE desactiva (`staff.destroy`); PATCH edita nombre, apellido, correo
    (A1, plan Equipo), especialidad y cédula (`staff.update`, M01 orden 7).
    HybridPermission deriva el código del método."""
    permission_classes = [HybridPermission]
    resource_name = "staff"
    http_method_names = ['patch', 'delete', 'options']

    def patch(self, request, pk):
        target = resolve_public_id(
            User.objects.filter(
                organization=request.user.organization,
                is_active=True,
            ).exclude(role='ADMIN_SAAS').exclude(is_service_account=True),
            pk,
        )
        serializer = UpdateEmployeeSerializer(
            data=request.data,
            context={'request': request, 'target': target},
        )
        serializer.is_valid(raise_exception=True)
        user = update_staff_profile(
            admin=request.user, target_user=target, changes=serializer.validated_data,
        )
        return Response(UserSerializer(user).data)

    def delete(self, request, pk):
        # Día 6 Fase 5 (Issue #38): lookup por public_id (UUID).
        # Antes <int:pk> permitía enumeration de usuarios cross-org.
        # ADR p51: service accounts excluidos (404-as-403) — el kill switch
        # del agente es AgentSettings.enabled, no la API de staff.
        user = resolve_public_id(
            User.objects.filter(
                organization=request.user.organization,
                is_active=True,
            ).exclude(is_service_account=True),
            pk,
        )
        # H-06: la desactivación + revocación de sesiones vive en el service
        # (cambio de estado con efecto secundario sobre tokens → backend
        # CLAUDE.md "todo cambio de estado pasa por services"). El guard de
        # self-deactivation (F13, lockout prevention) y los gates de tenant /
        # ADMIN_SAAS se aplican dentro del service como defensa-en-profundidad.
        request_id = (
            request.META.get('HTTP_X_REQUEST_ID')
            or str(uuid.uuid4())
        )
        deactivate_staff(
            admin=request.user,
            target_user=user,
            request_id=request_id,
            client_ip=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChangeMyPasswordView(NoStoreResponseMixin, APIView):
    """
    Self-service password change.

    POST /api/users/change-password/

    Body: ``current_password``, ``new_password``, ``confirm_password``.

    On success, returns 200 with a fresh ``access`` + ``refresh`` token
    pair. The client must replace its stored tokens (use the central
    auth manager — never write to localStorage from form components).

    Throttle scope ``change_password`` (10/hour by user) deters
    brute-force of ``current_password``. See ADR p20 for full design
    notes including JWT lifecycle and access-token behavior.
    """

    # NotDemoAccount: la cuenta demo comparte credenciales fijas; cambiar la
    # contraseña dejaría inaccesible la demo pública (ni el UI muestra la opción).
    permission_classes = [IsAuthenticated, NotDemoAccount]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'change_password'

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        request_id = (
            request.META.get('HTTP_X_REQUEST_ID')
            or str(uuid.uuid4())
        )

        result = change_password(
            actor=request.user,
            request=request,
            current_password=serializer.validated_data['current_password'],
            new_password=serializer.validated_data['new_password'],
            request_id=request_id,
            client_ip=get_client_ip(request),
            user_agent=get_user_agent(request),
        )

        return Response({
            "detail": "Contraseña actualizada.",
            "request_id": result.request_id,
            "duration_ms": result.duration_ms,
            "access": result.access,
            "refresh": result.refresh,
        }, status=status.HTTP_200_OK)


class StaffResetPasswordView(NoStoreResponseMixin, APIView):
    """
    Admin-initiated password reset for a staff member of the same
    organization (ADR p21). The response carries a temporary password, so it
    is ``Cache-Control: no-store`` (plan Equipo, D11).

    POST /api/staff/<public_id>/reset-password/

    Generates a cryptographically random temporary password, applies it
    to the target user, flips ``password_must_change=True`` with a
    24-hour validity window, blacklists every refresh token the target
    held, and returns the temp password ONCE in the response. The temp
    password is never persisted to logs.

    Authorisation (defence in depth — service re-checks):
      - Caller has ``staff.reset_password`` permission (ADMIN only —
        VET / ASSISTANT lack it via PERMISSIONS dict).
      - Caller and target share the same organization.
      - Caller is not the target (self-reset uses change-password).
      - Target is not ``ADMIN_SAAS`` (no clinic admin can affect
        platform operators).
    """

    permission_classes = [make_permission('staff.reset_password')]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'staff_password_reset'

    def post(self, request, pk):
        # ADR p51: service accounts excluidos (404-as-403) — un reset pondría
        # password_must_change=True y el gate inutilizaría todas las tools
        # del agente. La cuenta no se gestiona por la API de staff.
        target = resolve_public_id(
            User.objects.filter(
                organization=request.user.organization,
                is_active=True,
            ).exclude(is_service_account=True),
            pk,
        )

        request_id = (
            request.META.get('HTTP_X_REQUEST_ID')
            or str(uuid.uuid4())
        )

        result = reset_password_for_staff(
            admin=request.user,
            target_user=target,
            request_id=request_id,
            client_ip=get_client_ip(request),
            user_agent=get_user_agent(request),
        )

        return Response({
            "detail": "Contraseña temporal generada.",
            "request_id": result.request_id,
            "duration_ms": result.duration_ms,
            "temp_password": result.temp_password,
            "expires_in_seconds": result.expires_in_seconds,
            "must_change_on_first_login": True,
        }, status=status.HTTP_201_CREATED)


class StaffReactivateView(NoStoreResponseMixin, APIView):
    """POST /api/staff/<public_id>/reactivate/ (plan Equipo A2).

    Reactivates the same account with a temporary password that must be changed
    on first login, revoking every earlier session (ADR p65). 201 with the same
    shape as the reset plus ``member``; 409 ``already_active`` if it is already
    active. ``no-store``: the body carries a temporary password.

    The view opens no transaction: ``reactivate_staff`` is durable and must be
    the outermost one. The response is built only from what the service
    returned, i.e. after the commit.
    """

    permission_classes = [make_permission('staff.reactivate')]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'staff_reactivate'

    def post(self, request, pk):
        target = resolve_public_id(
            User.objects.filter(
                organization=request.user.organization,
            ).exclude(role='ADMIN_SAAS').exclude(is_service_account=True),
            pk,
        )
        result = reactivate_staff(
            admin=request.user,
            target_user=target,
            request_id=request.META.get('HTTP_X_REQUEST_ID') or str(uuid.uuid4()),
            client_ip=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
        return Response({
            "detail": "Acceso reactivado.",
            "request_id": result.request_id,
            "duration_ms": result.duration_ms,
            "temp_password": result.temp_password,
            "expires_in_seconds": result.expires_in_seconds,
            "must_change_on_first_login": True,
            "member": UserSerializer(result.user).data,
        }, status=status.HTTP_201_CREATED)
