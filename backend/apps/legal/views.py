"""
Endpoints de aceptación legal (ADR p46).

GET  /api/legal/current/  → documentos vigentes requeridos para el rol del user
                            + si ya los aceptó.
POST /api/legal/accept/   → registra la aceptación (ip/user-agent server-side).

Ambos usan IsAuthenticated (no HybridPermission) y están en `_LEGAL_WHITELIST`
→ alcanzables por un user con aceptación pendiente (si no, quedaría lockeado).
"""
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.network import get_client_ip, get_user_agent

from .services import (
    current_required_documents,
    legal_acceptance_required,
    pending_documents,
    record_acceptances,
)


def _serialize(doc, accepted):
    return {
        "public_id": str(doc.public_id),
        "doc_type": doc.doc_type,
        "version": doc.version,
        "effective_date": doc.effective_date.isoformat(),
        "landing_url": doc.landing_url,
        "accepted": accepted,
    }


class CurrentLegalView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        required = list(current_required_documents(request.user))
        pending_ids = {d.id for d in pending_documents(request.user)}
        documents = [_serialize(d, d.id not in pending_ids) for d in required]
        return Response({
            "documents": documents,
            "acceptance_required": len(pending_ids) > 0,
        })


class AcceptLegalView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'legal_accept'

    def post(self, request):
        ids = request.data.get('document_public_ids')
        if not isinstance(ids, list) or not ids:
            raise ValidationError({
                "document_public_ids": ["Requerido: lista de public_id de documentos."],
            })
        # Solo se aceptan documentos VIGENTES y aplicables al rol del user — no se
        # confía en el cliente para aceptar documentos arbitrarios/desfasados.
        applicable = {str(d.public_id): d for d in current_required_documents(request.user)}
        docs = []
        for pid in ids:
            doc = applicable.get(str(pid))
            if doc is None:
                raise ValidationError({
                    "document_public_ids": [f"Documento no vigente o no aplicable: {pid}"],
                })
            docs.append(doc)

        record_acceptances(
            user=request.user,
            documents=docs,
            ip=get_client_ip(request),
            user_agent=get_user_agent(request),
        )
        return Response(
            {"acceptance_required": legal_acceptance_required(request.user)},
            status=status.HTTP_200_OK,
        )
