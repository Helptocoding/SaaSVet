"""
HTTP transport layer for cross-tenant platform operations.

Views in this module must stay thin: parse + validate input, delegate
to a service in `apps/platform/services/`, format the response. No
business logic, no transactions, no signal orchestration.
"""
import uuid

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.network import get_client_ip, get_user_agent
from apps.core.views import resolve_public_id
from apps.platform.permissions import IsPlatformOperator
from apps.platform.serializers import ProvisionOrgSerializer
from apps.platform.services.provision_organization import provision_organization
from apps.platform.services.platform_reset_password import platform_reset_password

User = get_user_model()


class PlatformOrgCreateView(APIView):
    """
    POST /api/platform/organizations/

    Provision a new tenant Organization together with its initial admin
    user. Requires `IsPlatformOperator` (role='ADMIN_SAAS').

    Response shape:
        {
          "request_id": "<uuid>",
          "duration_ms": <int>,
          "organization": {public_id, name, timezone, tax_rate},
          "admin":        {public_id, username, email}
        }

    The admin password is never echoed back. The caller must record it
    out-of-band (e.g. forward to the admin via email) — this endpoint
    does not send it.
    """

    permission_classes = [IsPlatformOperator]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'platform_org_create'

    def post(self, request):
        request_id = (
            request.META.get('HTTP_X_REQUEST_ID')
            or str(uuid.uuid4())
        )

        serializer = ProvisionOrgSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = provision_organization(
            actor=request.user,
            validated_data=serializer.validated_data,
            request_id=request_id,
        )

        return Response(
            {
                "request_id": result.request_id,
                "duration_ms": result.duration_ms,
                "organization": {
                    "public_id": str(result.organization.public_id),
                    "name": result.organization.name,
                    "timezone": result.organization.timezone,
                    "tax_rate": str(result.organization.tax_rate),
                },
                "admin": {
                    "public_id": str(result.admin.public_id),
                    "username": result.admin.username,
                    "email": result.admin.email,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class PlatformStaffResetPasswordView(APIView):
    """
    POST /api/platform/staff/<public_id>/reset-password/

    Platform-operator cross-tenant password reset (ADR p45).

    Generates a cryptographically random temporary password, applies it
    to the target user (any active non-ADMIN_SAAS user in any org), flips
    ``password_must_change=True`` with 24h validity, blacklists all
    existing tokens of target, returns the temp password once.

    Authorisation:
      - IsPlatformOperator (role='ADMIN_SAAS', is_superuser, is_staff).
      - Target must not be ADMIN_SAAS.
      - Actor cannot reset their own account.

    Response 201:
        {temp_password, expires_in_seconds, must_change_on_first_login,
         request_id, duration_ms}

    The temp_password is returned once and never persisted in logs.
    """

    permission_classes = [IsPlatformOperator]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'platform_password_reset'

    def post(self, request, pk):
        target = resolve_public_id(
            User.objects.filter(is_active=True).exclude(role='ADMIN_SAAS'),
            pk,
        )

        request_id = (
            request.META.get('HTTP_X_REQUEST_ID')
            or str(uuid.uuid4())
        )

        result = platform_reset_password(
            actor=request.user,
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
