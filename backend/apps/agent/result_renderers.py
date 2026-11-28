"""B2 bounded deterministic receipts. Free LLM prose cannot edit these facts."""
from decimal import Decimal
import re

from . import endpoint_contracts as contracts

PROTECTED_READS = frozenset({
    'list_my_pets', 'get_appointments', 'get_vaccine_status', 'get_service_catalog',
    'find_available_slots', 'check_appointment_slot', 'check_product_availability',
    'get_offered_specialties', 'get_recent_product_queries',
})
UNKNOWN = 'No pude verificar esa información en este momento. Puedes pedir ayuda a una persona del equipo.'
PARTIAL = 'Estos son los resultados que pude verificar; la consulta no demuestra que sean todos.'


def in_scope(outcome, context):
    return all(outcome.scope.get(key) == getattr(context, key)
               for key in ('organization_id', 'conversation_id', 'contact_id'))


def _label(value):
    contracts.require(isinstance(value, str) and bool(value.strip()) and len(value) <= 300)
    # Domain strings stay labels, never become standalone instructions.
    return ' '.join(value.split()).replace('*', '').replace('`', '')


def _price(entry, concept, currency):
    amount = entry.get('amount')
    if amount is None:
        return f'{concept}: el equipo puede confirmar su precio.'
    # The wire adapter may parse DRF strings. The renderer accepts Decimal only.
    contracts.require(type(amount) is Decimal and amount.is_finite() and amount > 0)
    contracts.require(isinstance(currency, str) and bool(re.fullmatch('[A-Z]{3}', currency)))
    contracts.require(entry.get('currency') == currency)
    # ADR p70 D4: `amount` es el precio con IVA; se dice expresamente.
    return f'{concept}: ${amount:,.2f} {currency}, IVA incluido.'


def effect_matches(tool, outcome, *, context=None, partial=False):
    if not outcome.validated or (context is not None and not in_scope(outcome, context)):
        return False
    if not partial and outcome.kind != 'EFFECT':
        return False
    effects = outcome.partial_effects if partial else outcome.effects
    required = {
        'create_appointment': {'appointment': 'scheduled'},
        'confirm_appointment': {'appointment': 'confirmed'},
        'cancel_appointment': {'appointment': 'canceled'},
        'reschedule_appointment': {'appointment': None},
        'register_new_client_and_pet': {'appointment': 'scheduled'},
        'register_pet_and_schedule': {'pet': 'registered', 'appointment': 'scheduled'},
        'register_pet_only': {'pet': 'registered'},
        'request_human': {'human_handoff': 'persisted'},
    }.get(tool)
    if not required:
        return False
    if partial:
        required = {'pet': 'registered'} if tool == 'register_pet_and_schedule' else {}
        if not required:
            return False
    for entity, state in required.items():
        if not any(isinstance(e, dict) and e.get('entity') == entity
                   and e.get('action') == tool
                   and e.get('result') in ('success', 'already_done')
                   and (e.get('state') == state if state else e.get('state') in ('scheduled', 'confirmed'))
                   and (str(e.get('reference', '')).isdigit() if entity == 'human_handoff'
                        else contracts.public_id(e.get('reference')))
                   for e in effects):
            return False
    return True


def render_effect(tool, outcome, *, context=None):
    if effect_matches(tool, outcome, context=context, partial=True):
        try:
            name = _label((outcome.data or {}).get('nombre'))
        except contracts.InvalidResponse:
            return UNKNOWN
        return f'{name} quedó registrada. No pude verificar que la cita quedara agendada; el equipo puede revisarlo.'
    if not effect_matches(tool, outcome, context=context):
        return ('No pude verificar el resultado de la operación. El equipo debe revisarlo antes de intentarlo de nuevo.'
                if outcome.error_kind == 'uncertain' else UNKNOWN)
    if tool == 'request_human':
        return 'Tu solicitud de atención humana quedó registrada. Aún no tengo confirmación de que una persona la haya atendido.'
    already = any(e.get('result') == 'already_done' for e in outcome.effects)
    if already:
        if tool in ('create_appointment', 'register_new_client_and_pet'):
            return 'La cita de esa solicitud ya está agendada en el sistema.'
        return {'cancel_appointment': 'La cita ya está cancelada.',
                'confirm_appointment': 'La asistencia a esa cita ya está confirmada.',
                'reschedule_appointment': 'La cita ya está en el horario solicitado.'}.get(tool, UNKNOWN)
    if tool == 'cancel_appointment':
        return 'Listo, cancelé tu cita. Si quieres agendar otra, con gusto te ayudo 🙂'
    if tool == 'confirm_appointment':
        return 'La asistencia a esa cita quedó confirmada.'
    if tool == 'register_pet_only':
        return 'Tu mascota quedó registrada en tu expediente.'
    try:
        when = _label((outcome.data or {}).get('cuando'))
    except contracts.InvalidResponse:
        return UNKNOWN
    prefix = {'register_new_client_and_pet': 'El registro quedó realizado y la cita agendada',
              'create_appointment': 'La cita quedó agendada',
              'reschedule_appointment': 'La cita quedó reprogramada',
              'register_pet_and_schedule': 'Tu mascota quedó registrada y la cita agendada'}.get(tool)
    return f'¡Listo! ✅ {prefix} para el {when.rstrip(".")}.' if prefix else UNKNOWN


def render_read(tool, outcome, context):
    if tool not in PROTECTED_READS:
        return None
    if outcome.kind == 'ERROR':
        return {
            'verification_required': 'Para consultar ese dato necesitamos verificar tu vínculo con el expediente.',
            'unknown_handle': 'Necesito identificar la mascota o cita que quieres consultar.',
            'need_date': 'Indícame el día y la hora que quieres consultar.',
            'bad_date': 'Necesito una fecha y hora válidas para consultar la agenda.',
            'past_date': 'Esa fecha ya pasó; indícame una fecha futura para consultar disponibilidad.',
            'binding_required': 'Necesito identificar la mascota o cita de este asunto antes de consultar sus datos.',
            'stale_binding': 'Necesito volver a consultar los datos de este asunto.',
        }.get(outcome.client_error, UNKNOWN)
    if outcome.kind != 'READ' or not outcome.validated or not in_scope(outcome, context):
        return UNKNOWN
    rows = outcome.data
    try:
        if tool == 'check_appointment_slot':
            contracts.require(isinstance(rows, dict) and type(rows.get('available')) is bool)
            contracts.iso_date(rows.get('date'))
            contracts.iso_time(rows.get('time'))
            contracts.iso_time(rows.get('end_time'))
            contracts.require(outcome.scope.get('date') == rows['date'] and outcome.scope.get('time') == rows['time'])
            contracts.require(outcome.completeness == 'complete')
            return (f"El horario del {rows['date']} a las {rows['time']} "
                    + ('está disponible al consultar la agenda.' if rows['available'] else 'no está disponible en la agenda consultada.'))
        contracts.require(isinstance(rows, (list, tuple)))
        if not rows:
            if not outcome.empty:
                return 'No pude verificar todos los resultados de esa consulta en este momento.'
            return {
                'list_my_pets': 'No encontré mascotas registradas en el expediente consultado.',
                'get_appointments': 'No encontré citas para las mascotas consultadas en este expediente.',
                'get_vaccine_status': 'No encontré registros administrativos de vacunas para esa mascota.',
                'find_available_slots': 'No encontré horarios disponibles para el día y la franja consultados.',
            }.get(tool, 'No encontré coincidencias para esa consulta en el catálogo consultado.')
        lines = []
        for row in rows:
            contracts.require(isinstance(row, dict))
            if tool == 'get_service_catalog':
                contracts.require(contracts.public_id(row.get('service_id')))
                lines.append(_price(row, _label(row.get('servicio')), outcome.scope.get('currency')))
            elif tool == 'list_my_pets':
                lines.append(f"{_label(row.get('nombre'))}: {_label(row.get('especie'))}.")
            elif tool == 'get_appointments':
                contracts.require(row.get('estado') in ('programada', 'confirmada', 'en consulta', 'atendida', 'cancelada', 'no asistió'))
                lines.append(f"Cita de {_label(row.get('mascota'))}, {_label(row.get('cuando'))}: {row['estado']}.")
            elif tool == 'get_vaccine_status':
                lines.append(f"Registro administrativo de {_label(row.get('vacuna'))}: {_label(row.get('estado'))}; aplicación: {_label(row.get('aplicada'))}.")
                if row.get('proximo_refuerzo'):
                    lines.append(f"Próximo refuerzo registrado: {_label(row['proximo_refuerzo'])}.")
            elif tool == 'find_available_slots':
                contracts.iso_date(row.get('iso_date'))
                contracts.iso_time(row.get('iso_time'))
                contracts.iso_time(row.get('iso_end_time'))
                contracts.require(row['iso_date'] == outcome.scope.get('date'))
                lines.append(f"Horario disponible al consultar: {row['iso_date']}, {row['iso_time']}–{row['iso_end_time']}.")
            elif tool == 'get_offered_specialties':
                lines.append(f"Especialidad disponible en el catálogo: {_label(row.get('especialidad'))}.")
            elif tool == 'get_recent_product_queries':
                lines.append(f"Consulta anterior sobre {_label(row.get('producto'))}: {_label(row.get('cuando'))}.")
            elif tool == 'check_product_availability':
                name = _label(row.get('producto'))
                contracts.require(type(row.get('disponible')) is bool)
                lines.append(f"{name}: " + ('con existencia al consultar.' if row['disponible'] else 'sin existencia en la consulta.'))
                if row['disponible']:
                    presentations = row.get('presentaciones') or ([row] if 'amount' in row else [])
                    for entry in presentations:
                        lines.append(_price(entry, f"{name}, {_label(entry.get('presentacion'))}", outcome.scope.get('currency')))
        if outcome.completeness != 'complete':
            lines.append(PARTIAL)
        return '\n'.join(lines)
    except (contracts.InvalidResponse, TypeError, KeyError):
        return UNKNOWN
