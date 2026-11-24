"""Datos profesionales del personal: cédula del firmante (M01, orden 7; ADR p64) y
función clínica (ADR p66).

Cédula: solo dígitos, de 5 a 10. No se verifica contra el registro de la SEP. Es
obligatoria para quien atiende pacientes (Equipo) y para quien firma una consulta
o una receta, sea cual sea su rol (dominio clínico).

Función clínica: atiende pacientes quien es VET, o ADMIN marcado como que atiende
(el dueño veterinario de una clínica pequeña). ASSISTANT nunca. Es la única
respuesta a «¿quién atiende?»: agenda, agente y cédula la consultan aquí, nunca
comparando el nombre del rol.
"""
import re

from django.db.models import Q
from rest_framework import serializers

LICENSE_NUMBER_RE = re.compile(r'^[0-9]{5,10}$')
LICENSE_FORMAT_MESSAGE = 'La cédula profesional debe tener solo dígitos, entre 5 y 10.'
LICENSE_REQUIRED_MESSAGE = 'La cédula profesional es obligatoria para veterinarios.'
LICENSE_REQUIRED_CLINICIAN_MESSAGE = (
    'La cédula profesional es obligatoria para quien atiende pacientes.'
)

# Roles cuya función clínica decide el rol (no el campo `attends_patients`).
ALWAYS_CLINICAL_ROLES = frozenset({'VET'})
OPTIONALLY_CLINICAL_ROLES = frozenset({'ADMIN'})


def normalize_license_number(value):
    """Devuelve '' o la cédula sin espacios en los bordes; rechaza otro formato."""
    value = (value or '').strip()
    if value and not LICENSE_NUMBER_RE.fullmatch(value):
        raise serializers.ValidationError(LICENSE_FORMAT_MESSAGE)
    return value


def attends_for(role, attends_patients=False):
    """Función clínica resultante de un rol y del valor pedido para ADMIN."""
    if role in ALWAYS_CLINICAL_ROLES:
        return True
    if role in OPTIONALLY_CLINICAL_ROLES:
        return bool(attends_patients)
    return False


def is_clinician(user) -> bool:
    """True si ``user`` atiende pacientes (ADR p66)."""
    return attends_for(getattr(user, 'role', None), getattr(user, 'attends_patients', False))


def clinician_q() -> Q:
    """Filtro de queryset equivalente a ``is_clinician``."""
    return Q(role__in=ALWAYS_CLINICAL_ROLES) | Q(
        role__in=OPTIONALLY_CLINICAL_ROLES, attends_patients=True,
    )


def license_required_message(role):
    return LICENSE_REQUIRED_MESSAGE if role in ALWAYS_CLINICAL_ROLES else LICENSE_REQUIRED_CLINICIAN_MESSAGE


def require_signer_license(user, action):
    """Exige cédula a quien firma una consulta o una receta, sea cual sea su rol.

    `action` completa el mensaje («cerrar la consulta», «emitir la receta»). Sin
    firmante también se rechaza: un documento clínico sin veterinario no se firma.
    """
    if user is None:
        raise serializers.ValidationError({'license_number': [
            f'La consulta no tiene veterinario asignado; no se puede {action}.']})
    if not user.license_number:
        name = f'{user.first_name} {user.last_name}'.strip() or user.username
        raise serializers.ValidationError({'license_number': [
            f'Registra la cédula profesional de {name} en Equipo para {action}.']})
