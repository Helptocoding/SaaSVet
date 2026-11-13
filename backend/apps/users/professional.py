"""Cédula profesional del firmante (M01, orden 7; ADR p64).

Solo dígitos, de 5 a 10. No se verifica contra el registro de la SEP. Es
obligatoria para todo VET (serializers de Equipo) y para quien firma una
consulta o una receta, sea cual sea su rol (dominio clínico).
"""
import re

from rest_framework import serializers

LICENSE_NUMBER_RE = re.compile(r'^[0-9]{5,10}$')
LICENSE_REQUIRED_ROLES = frozenset({'VET'})
LICENSE_FORMAT_MESSAGE = 'La cédula profesional debe tener solo dígitos, entre 5 y 10.'
LICENSE_REQUIRED_MESSAGE = 'La cédula profesional es obligatoria para veterinarios.'


def normalize_license_number(value):
    """Devuelve '' o la cédula sin espacios en los bordes; rechaza otro formato."""
    value = (value or '').strip()
    if value and not LICENSE_NUMBER_RE.fullmatch(value):
        raise serializers.ValidationError(LICENSE_FORMAT_MESSAGE)
    return value
