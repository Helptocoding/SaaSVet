"""Frontera de capacidades para la primera atención de un contacto.

El modelo comprende cómo lo expresó el cliente y persiste una decisión tipada;
este módulo nunca intenta deducirla desde texto. La única responsabilidad del
servidor es decidir qué herramientas son seguras para esa decisión.
"""
from .models import Conversation
from .capabilities import PUBLIC_OR_HUMAN


PATH_NEW = Conversation.INTAKE_NEW_CLIENT
PATH_EXISTING = Conversation.INTAKE_EXISTING_CLIENT

# Mientras no se resuelva si hay que dar de alta o identificar, ninguna tool
# consulta ni modifica la agenda/ficha. El modelo conserva
# ``respond_to_client`` porque no se ejecuta por ``run_tool``.
PATH_SELECTION_TOOL = 'set_client_path'

# B0: contención de release, sin flag que permita reabrir escrituras legacy.
# B7/B8/B9 deberán sustituirla por capacidades con sus gates aprobados.
CONTAINED_WRITES = frozenset({
    'create_appointment', 'confirm_appointment', 'cancel_appointment',
    'reschedule_appointment', 'register_new_client_and_pet',
    'register_pet_and_schedule', 'register_pet_only',
})


def write_is_contained(tool_name):
    return tool_name in CONTAINED_WRITES


def current_path(conversation):
    """Ruta efectiva basada en hechos de dominio y, si hace falta, triaje."""
    if conversation.contact.owner_id is not None:
        return PATH_EXISTING
    return conversation.intake_path


def needs_selection(conversation):
    return not current_path(conversation)


def allows_tool(conversation, tool_name):
    """Si la capacidad está disponible en la ruta actual.

    Esto es la defensa de profundidad de ``as_openai_tools``. No reemplaza la
    validación en ``run_tool``: una tool puede llegar por un prompt viejo, un
    retry o un caller futuro que no haya usado el catálogo dinámico.
    """
    if write_is_contained(tool_name):
        return False
    if tool_name in PUBLIC_OR_HUMAN:
        return True
    path = current_path(conversation)
    if not path:
        return tool_name == PATH_SELECTION_TOOL
    if tool_name == PATH_SELECTION_TOOL:
        # Se conserva para que el modelo pueda corregir una interpretación
        # semántica antes de ejecutar una operación.
        return conversation.contact.owner_id is None
    if path == PATH_NEW:
        return tool_name != 'identify_client'
    if path == PATH_EXISTING:
        return tool_name != 'register_new_client_and_pet'
    return False


def context_fact(conversation):
    """Proyección semántica para el prompt; no filtra existencia de expedientes."""
    path = current_path(conversation)
    if path == PATH_NEW:
        return 'primera_visita'
    if path == PATH_EXISTING:
        return 'cliente_existente'
    return 'por_resolver'
