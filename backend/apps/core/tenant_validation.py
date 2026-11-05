"""Validación de pertenencia a la organización en serializers (ADR p14, Fase 2).

Fuente única: antes había dos copias de un helper en `billing` y `prescriptions`, y
comparaciones sueltas en `appointments`, `inventory` y `medical_records`. Solo las dos
primeras registraban el intento, de modo que en las demás referenciar a otra clínica
era indistinguible de un error de validación ordinario.

Falla en cerrado: un actor o un recurso SIN organización se rechaza. Las copias de
`billing` y `prescriptions` los dejaban pasar; las demás ya los rechazaban, y se adoptó
la regla estricta porque sin organización no hay pertenencia que comprobar.
"""
import logging

from rest_framework import serializers

# Evento a WARNING, separado de TENANT_MISMATCH_DETECTED (HybridPermission, ERROR) para
# no saturar la señal operacional con typos de UI o IDs obsoletos del frontend.
tenant_logger = logging.getLogger('apps.tenant_validation')

DEFAULT_MESSAGE = 'Acceso inválido.'


def same_organization(value, request, *, field, serializer):
    """True si `value` es de la organización del actor. Registra el rechazo.

    Para validaciones a nivel de objeto, que deciden la forma de su propio error.
    `None` es una FK opcional sin valor y no hay nada que comprobar.
    """
    assert request is not None, 'La validación de tenant requiere el request en el contexto'
    if value is None:
        return True
    user_org_id = getattr(request.user, 'organization_id', None)
    resource_org_id = getattr(value, 'organization_id', None)
    if user_org_id is not None and resource_org_id == user_org_id:
        return True
    tenant_logger.warning('TENANT_VALIDATION_REJECTED', extra={
        'source': 'serializer',
        'serializer': serializer,
        'field': field,
        'user_id': getattr(request.user, 'pk', None),
        'user_org_id': user_org_id,
        'resource_org_id': resource_org_id,
        'resource_pk': getattr(value, 'pk', None),
        'endpoint': getattr(request, 'path', None),
        'method': getattr(request, 'method', None),
    })
    return False


def require_same_organization(value, request, *, field, serializer, message=DEFAULT_MESSAGE):
    """Devuelve `value`, o rechaza con `ValidationError` a nivel de campo."""
    if not same_organization(value, request, field=field, serializer=serializer):
        raise serializers.ValidationError(message)
    return value
