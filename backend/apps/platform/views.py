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


class PhysicalDeletionPreviewView(APIView):
    permission_classes = [IsPlatformOperator]

    def post(self, request):
        from rest_framework import serializers
        from apps.platform.services.physical_deletion import preview

        class Payload(serializers.Serializer):
            organization_id = serializers.UUIDField()
            target_type = serializers.ChoiceField(choices=('owner', 'pet', 'organization'))
            target_id = serializers.UUIDField()
            reason = serializers.CharField(min_length=8, max_length=255, trim_whitespace=True)

        data = Payload(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(preview(actor=request.user, **data.validated_data))


class PhysicalDeletionExecuteView(APIView):
    permission_classes = [IsPlatformOperator]

    def post(self, request):
        from rest_framework import serializers
        from apps.platform.services.physical_deletion import execute

        class Payload(serializers.Serializer):
            organization_id = serializers.UUIDField()
            target_type = serializers.ChoiceField(choices=('owner', 'pet', 'organization'))
            target_id = serializers.UUIDField()
            reason = serializers.CharField(min_length=8, max_length=255, trim_whitespace=True)
            confirmation = serializers.CharField(required=False)
            idempotency_key = serializers.UUIDField()

        data = Payload(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(execute(actor=request.user, **data.validated_data))


class PlatformOrganizationHistoryView(APIView):
    permission_classes = [IsPlatformOperator]

    def get(self, request, pk):
        from apps.organizations.models import Organization
        from apps.patients.models import Owner, Pet
        from apps.billing.models import Invoice
        from apps.medical_records.models import MedicalRecord
        from rest_framework.exceptions import ValidationError
        org = resolve_public_id(Organization.objects.all(), pk)
        try:
            page = int(request.query_params.get('page', '1'))
        except (TypeError, ValueError) as exc:
            raise ValidationError({'page': 'Página inválida.'}) from exc
        if not 1 <= page <= 100000:
            raise ValidationError({'page': 'Página inválida.'})
        offset = (page - 1) * 100
        limit = offset + 100
        return Response({
            'organization_id': str(org.public_id), 'is_active': org.is_active,
            'page': page, 'page_size': 100,
            'archived_owners': [
                {'public_id': str(owner.public_id), 'name': owner.name}
                for owner in Owner.all_objects.filter(organization=org, is_active=False).order_by('pk')[offset:limit]
            ],
            'archived_pets': [
                {'public_id': str(pet.public_id), 'name': pet.name}
                for pet in Pet.all_objects.filter(organization=org, is_active=False).order_by('pk')[offset:limit]
            ],
            'invoices': [
                {'public_id': str(invoice.public_id), 'status': invoice.status,
                 'subject_snapshot': invoice.subject_snapshot}
                for invoice in Invoice.all_objects.filter(organization=org).order_by('-pk')[offset:limit]
            ],
            'medical_records': [
                {'public_id': str(record.public_id), 'status': record.status,
                 'subject_snapshot': record.subject_snapshot}
                for record in MedicalRecord.all_objects.filter(organization=org).order_by('-pk')[offset:limit]
            ],
        })


class PlatformOrgStateView(APIView):
    permission_classes = [IsPlatformOperator]

    def post(self, request, pk, action):
        from apps.organizations.models import Organization
        from apps.organizations.state import change_organization_state
        from rest_framework.exceptions import ValidationError
        if action not in ('deactivate', 'reactivate'):
            raise ValidationError({'action': 'Acción inválida.'})
        org = resolve_public_id(Organization.objects.all(), pk)
        updated = change_organization_state(
            actor=request.user, public_id=org.public_id,
            active=action == 'reactivate', reason=request.data.get('reason'),
        )
        return Response({'public_id': str(updated.public_id), 'is_active': updated.is_active})


class PlatformSubjectArchiveView(APIView):
    permission_classes = [IsPlatformOperator]

    def post(self, request, organization_id, kind, pk, action):
        from apps.organizations.models import Organization
        from apps.patients.archive import change_archive_state
        from apps.patients.serializers import OwnerSerializer, PetSerializer
        from rest_framework.exceptions import ValidationError
        if kind not in ('owners', 'pets') or action not in ('archive', 'restore'):
            raise ValidationError({'action': 'Acción inválida.'})
        org = resolve_public_id(Organization.objects.all(), organization_id)
        subject = change_archive_state(
            actor=request.user, organization_id=org.pk,
            kind='owner' if kind == 'owners' else 'pet', public_id=pk,
            archive=action == 'archive',
        )
        serializer = OwnerSerializer if kind == 'owners' else PetSerializer
        return Response(serializer(subject, context={'request': request}).data)


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
