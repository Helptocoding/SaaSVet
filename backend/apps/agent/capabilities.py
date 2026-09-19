"""Static B2 capability effects. Neither prompts nor tool arguments edit this."""
from types import MappingProxyType
from dataclasses import dataclass

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


@dataclass(frozen=True)
class OperationCapability:
    operation_kind: str | None
    goal: str | None
    identity_policy: str
    authorization_mode: str
    # (field, normalization type, required). Server schema, not tool/LLM JSON.
    schema: tuple = ()
    schema_version: int = 1
    family_allowed: bool = False
    effect: str = WRITE_BUSINESS


_SCHEDULE = (('date', 'date', True), ('start_time', 'time', True),
             ('end_time', 'time', True), ('veterinarian_id', 'id', True))
OPERATIONS = MappingProxyType({
    'create_appointment': OperationCapability('CREATE_APPOINTMENT', 'schedule_appointment',
        'CURRENT_LINK', 'EXPLICIT_CONFIRMATION',
        (('pet_id', 'id', True), *_SCHEDULE, ('reason', 'text255', True)), family_allowed=True),
    'reschedule_appointment': OperationCapability('RESCHEDULE_APPOINTMENT', 'reschedule_appointment',
        'CURRENT_OWNER', 'EXPLICIT_CONFIRMATION', (('appointment_id', 'id', True), *_SCHEDULE)),
    'cancel_appointment': OperationCapability('CANCEL_APPOINTMENT', 'cancel_appointment',
        'CURRENT_OWNER', 'EXPLICIT_CONFIRMATION',
        (('appointment_id', 'id', True), ('cancellation_reason', 'text100', False))),
    'confirm_appointment': OperationCapability('CONFIRM_ATTENDANCE', 'confirm_appointment',
        'CURRENT_OWNER', 'CONTEXTUAL_DECLARATION',
        (('appointment_id', 'id', True), ('target_status', 'confirmed', True))),
    'register_pet_only': OperationCapability('REGISTER_PET', 'add_pet_only',
        'CURRENT_OWNER', 'EXPLICIT_CONFIRMATION',
        (('owner_id', 'id', True), ('name', 'text255', True),
         ('species', 'species', False), ('birth_date', 'date', False))),
    # E5 / new-owner effects have no B7A definition or preparation adapter.
    'register_new_client_and_pet': OperationCapability(None, None, 'CONTACT', 'EXPLICIT_CONFIRMATION'),
    'register_pet_and_schedule': OperationCapability(None, None, 'CURRENT_OWNER', 'EXPLICIT_CONFIRMATION'),
})


def operation_capability(kind):
    return next((spec for spec in OPERATIONS.values() if spec.operation_kind == kind), None)
