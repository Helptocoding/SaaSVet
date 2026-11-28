"""Fixtures que respetan INV-L (ADR p70 D2): agente encendido ⇒ teléfono válido.

Desde p70, `AgentSettings.save()` rechaza encender el agente de una clínica sin
teléfono válido. Las pruebas que necesitan el agente encendido usan este helper:
captura un teléfono de prueba si la clínica no tiene uno válido y, solo
entonces, crea la configuración encendida, en el mismo orden que un ADMIN.
"""
from apps.agent.models import AgentSettings
from apps.core.validators import is_valid_mx_phone

# Número de prueba: 10 dígitos sin relleno evidente; nunca el de un piloto.
TEST_CLINIC_PHONE = '5512345678'


def ensure_clinic_phone(organization, phone=TEST_CLINIC_PHONE):
    """Captura un teléfono válido si la clínica no tiene uno; conserva el suyo."""
    if not is_valid_mx_phone(organization.phone or ''):
        organization.phone = phone
        organization.save(update_fields=['phone'])
    return organization


def create_enabled_agent_settings(organization, **fields):
    ensure_clinic_phone(organization)
    return AgentSettings.objects.create(organization=organization, enabled=True, **fields)
