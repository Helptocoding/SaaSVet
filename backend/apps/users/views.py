from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from rest_framework.exceptions import ValidationError
from django.contrib.auth import get_user_model

from apps.core.permissions import make_permission, build_permissions_list
from apps.core.views import resolve_public_id
from apps.users.serializers import UserSerializer, CreateEmployeeSerializer

User = get_user_model()

VALID_ROLES = ['ADMIN', 'VET', 'ASSISTANT']


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        org = user.organization
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
            "permissions": build_permissions_list(request.user),
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
        user.is_active = False
        user.save()
        return Response(status=status.HTTP_204_NO_CONTENT)
