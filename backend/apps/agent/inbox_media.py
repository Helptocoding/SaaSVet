"""Authenticated proxy; storage names/provider identifiers never enter the API."""
import logging

from django.http import FileResponse
from django.utils.cache import patch_vary_headers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.channels.media_policy import MIME_TYPES
from apps.channels.media_clock import media_now
from apps.channels.media_revocations import revocation_record
from apps.channels.media_storage import safe_filename
from apps.channels.models import MessageMedia
from apps.core.permissions import make_permission

logger = logging.getLogger('agent.events')


@api_view(['GET'])
@permission_classes([make_permission('agentinbox.view')])
def inbox_media_view(request, public_id):
    media = (MessageMedia.objects.for_organization(request.user.organization)
        .select_related('message', 'channel_account').filter(public_id=public_id).first())
    if media is None or (media.message.organization_id != request.user.organization_id
            or media.message.channel_account_id != media.channel_account_id
            or media.channel_account.organization_id != request.user.organization_id):
        return Response({'code': 'not_found'}, status=404)
    if media.status == 'expired' or (media.expires_at is not None and media.expires_at <= media_now()):
        return Response({'code': 'media_expired', 'message': 'Archivo expirado'}, status=410)
    try:
        if revocation_record(media):
            return Response({'code': 'media_expired', 'message': 'Archivo expirado'}, status=410)
    except Exception:
        logger.error('MEDIA_ACCESS_HELD', extra=dict(event='MEDIA_ACCESS_HELD', organization_id=media.organization_id))
        return Response({'code': 'media_unavailable', 'message': 'Archivo no disponible'}, status=503)
    if media.status != 'ready' or not media.file.name:
        return Response({'code': 'media_unavailable', 'message': 'Archivo no disponible'}, status=409)
    mime = media.mime_type
    supported = set().union(*MIME_TYPES.values())
    if mime not in supported:
        return Response({'code': 'media_unavailable'}, status=409)
    try:
        stream = media.file.open('rb')
    except FileNotFoundError:
        logger.error('MEDIA_OBJECT_MISSING', extra=dict(event='MEDIA_OBJECT_MISSING',
            organization_id=media.organization_id, media_public_id=str(media.public_id)))
        return Response({'code': 'media_unavailable', 'message': 'Archivo no disponible'}, status=404)
    except Exception:
        logger.error('MEDIA_STORAGE_UNAVAILABLE', extra=dict(event='MEDIA_STORAGE_UNAVAILABLE',
            organization_id=media.organization_id, media_public_id=str(media.public_id)))
        return Response({'code': 'media_unavailable', 'message': 'No se pudo cargar el archivo'}, status=503)
    inline = mime.startswith(('image/', 'audio/', 'video/')) or mime == 'application/pdf'
    response = FileResponse(stream, content_type=mime, as_attachment=not inline,
        filename=safe_filename(media.filename, 'archivo'))
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "sandbox; default-src 'none'; frame-ancestors 'self'"
    if media.file_size is not None:
        response['Content-Length'] = str(media.file_size)
    patch_vary_headers(response, ['Authorization', 'Cookie'])
    return response
