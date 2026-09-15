"""Static B2 capability effects. Neither prompts nor tool arguments edit this."""
from types import MappingProxyType

READ_PUBLIC = 'READ_PUBLIC'
READ_PERSONAL = 'READ_PERSONAL'
WRITE_BUSINESS = 'WRITE_BUSINESS'
CONTROL = 'CONTROL'

EFFECTS = MappingProxyType({
    'get_clinic_info': READ_PUBLIC,
    'get_service_catalog': READ_PUBLIC,
    'get_offered_specialties': READ_PUBLIC,
    'check_product_availability': READ_PUBLIC,
    'find_available_slots': READ_PUBLIC,
    'check_appointment_slot': READ_PUBLIC,
    'list_my_pets': READ_PERSONAL,
    'get_vaccine_status': READ_PERSONAL,
    'get_appointments': READ_PERSONAL,
    'get_recent_product_queries': READ_PERSONAL,
    'create_appointment': WRITE_BUSINESS,
    'confirm_appointment': WRITE_BUSINESS,
    'cancel_appointment': WRITE_BUSINESS,
    'reschedule_appointment': WRITE_BUSINESS,
    'register_new_client_and_pet': WRITE_BUSINESS,
    'register_pet_and_schedule': WRITE_BUSINESS,
    'register_pet_only': WRITE_BUSINESS,
    'set_client_path': CONTROL,
    'identify_client': CONTROL,
    'begin_operation': CONTROL,
    'request_human': CONTROL,
})

PUBLIC_OR_HUMAN = frozenset(name for name, effect in EFFECTS.items()
                           if effect == READ_PUBLIC) | {'request_human'}
