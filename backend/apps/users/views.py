import uuid

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle
from rest_framework import status
from rest_framework.exceptions import ValidationError
from django.contrib.auth import get_user_model

from apps.core.network import get_client_ip, get_user_agent
from apps.core.permissions import make_permission, build_permissions_list, NotDemoAccount
from apps.core.views import resolve_public_id
from apps.users.serializers import (
    UserSerializer,
    CreateEmployeeSerializer,
    ChangePasswordSerializer,
)
from apps.users.services import change_password, reset_password_for_staff

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
    permission_classes = [make_permission("staff.list")]

    def get(self, request):
        qs = User.objects.filter(
            organization=request.user.organization,
            is_active=True
        ).exclude(role='ADMIN_SAAS')

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


class StaffDeactivateView(APIView):
    permission_classes = [make_permission("staff.destroy")]

    def delete(self, request, pk):
        # Día 6 Fase 5 (Issue #38): lookup por public_id (UUID).
        # Antes <int:pk> permitía enumeration de usuarios cross-org.
        user = resolve_public_id(
            User.objects.filter(
                organization=request.user.organization,
                is_active=True,
            ),
            pk,
        )
        # Día 6 audit F13: bloquear self-deactivation. Sin este guard, un
        # ADMIN que se desactiva queda fuera de su propia cuenta (lockout)
        # y la única recuperación es Django superuser shell — operativamente
        # costoso. La superficie con UUID lo hace trivial vía UI.
        if user.pk == request.user.pk:
            raise ValidationError("No puedes desactivar tu propia cuenta.")
        user.is_active = False
        user.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChangeMyPasswordView(APIView):
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


class StaffResetPasswordView(APIView):
    """
    Admin-initiated password reset for a staff member of the same
    organization (ADR p21).

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
        target = resolve_public_id(
            User.objects.filter(
                organization=request.user.organization,
                is_active=True,
            ),
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
