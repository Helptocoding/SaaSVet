"""
HTTP transport layer for cross-tenant platform operations.

Views in this module must stay thin: parse + validate input, delegate
to a service in `apps/platform/services/`, format the response. No
business logic, no transactions, no signal orchestration.
"""
import uuid

from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.platform.permissions import IsPlatformOperator
from apps.platform.serializers import ProvisionOrgSerializer
from apps.platform.services.provision_organization import (
    provision_organization,
)


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
