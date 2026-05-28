from django.core.exceptions import ValidationError as DjValidationError
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.core.permissions import HybridPermission, make_permission
from apps.core.sanitize import sanitize_text
from apps.core.views import TenantQueryMixin, resolve_public_id

from . import services
from .models import CashSession
from .serializers import CashSessionSerializer


@api_view(['POST'])
@permission_classes([make_permission("cashsession.open")])
def open_session(request):
    """Abre un turno de caja para el usuario autenticado."""
    notes = sanitize_text(request.data.get('notes') or '', max_length=5000)
    try:
        session = services.open_cash_session(
            request.user,
            opening_float=request.data.get('opening_float', 0),
            notes=notes,
        )
    except DjValidationError as e:
        return Response({'detail': e.messages}, status=status.HTTP_400_BAD_REQUEST)
    return Response(CashSessionSerializer(session).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([make_permission("cashsession.close")])
def close_session(request, pk):
    """Cierra un turno: cuenta efectivo, computa el Z, congela el snapshot."""
    session = resolve_public_id(
        CashSession.objects.for_organization(request.user.organization), pk
    )
    counted_cash = request.data.get('counted_cash')
    if counted_cash is None:
        return Response(
            {'error': 'Se requiere el campo counted_cash'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    notes = sanitize_text(request.data.get('notes') or '', max_length=5000)
    force = bool(request.data.get('force', False))
    try:
        session = services.close_cash_session(
            session, request.user, counted_cash, notes=notes, force=force,
        )
    except DjValidationError as e:
        return Response({'detail': e.messages}, status=status.HTTP_400_BAD_REQUEST)
    return Response(CashSessionSerializer(session).data)


@api_view(['GET'])
@permission_classes([make_permission("cashsession.retrieve")])
def current_session(request):
    """Sesión abierta del usuario (o null). Z en vivo del turno actual."""
    session = services.get_open_session(request.user)
    if session is None:
        return Response({'session': None})
    return Response(CashSessionSerializer(session).data)


class CashSessionListView(TenantQueryMixin, generics.ListAPIView):
    serializer_class = CashSessionSerializer
    permission_classes = [HybridPermission]
    resource_name = "cashsession"

    def get_queryset(self):
        qs = CashSession.objects.for_organization(self.request.user.organization)
        st = self.request.query_params.get('status')
        if st:
            qs = qs.filter(status=st)
        return qs
