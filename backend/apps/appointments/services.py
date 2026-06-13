from .models import Appointment, AppointmentStatusChange


def create_appointment(user, data):
    # eliminar organization de los datos enviados para evitar inyecciones
    data.pop("organization", None)

    # evitar doble reserva (usando for_user si está disponible, o filter seguro)
    exists = Appointment.objects.for_organization(user.organization).filter(
        veterinarian=data.get("veterinarian"),
        datetime=data.get("datetime"),
        status="scheduled"
    ).exists()

    if exists:
        raise Exception("Horario ocupado")

    return Appointment.objects.create(organization=user.organization, **data)


def complete_appointment_on_record_close(appointment, actor):
    """
    Finaliza la atención en agenda al cerrar la consulta médica vinculada.

    Sincroniza el ciclo de vida clínico (MedicalRecord open→closed) con el
    operativo (Appointment in_progress→done). El cierre del expediente ES el
    acto que termina la atención en una clínica veterinaria; sin esta
    sincronización la cita queda zombie en `in_progress` y la métrica
    `appointments_done` nunca refleja la consulta.

    Reglas (ver docs/system-module-operations.md §3):
      - appointment None → no-op (consulta sin cita: walk-in directo no aplica).
      - status != 'in_progress' → no-op (idempotente; respeta máquina de estados).
      - in_progress → done, registrando AppointmentStatusChange (append-only).

    NO toca Invoice ni pagos: `done` significa "la atención terminó", no
    "pagado". El cobro vive en billing (ADR p30).

    Debe invocarse DENTRO del `transaction.atomic()` del caller, que ya posee
    el lock del MedicalRecord. Usa un UPDATE condicional (no select_for_update)
    para no introducir un orden de locks Appointment↔MR que pudiera generar
    ABBA con assign_patient (que lockea Appt→MR). Appointment no está en la
    cadena canónica de locks (CashSession → MR → Invoice → Presentation →
    InvoiceItem → MRP).
    """
    if appointment is None:
        return None

    # Single source of truth de la máquina de estados (import diferido: evita
    # ciclo services↔views y mantiene una sola definición de ALLOWED_TRANSITIONS).
    from .views import ALLOWED_TRANSITIONS

    if 'done' not in ALLOWED_TRANSITIONS.get('in_progress', set()):
        # Defensa: si la máquina de estados cambia y deja de permitir la
        # transición, no forzarla.
        return appointment

    # UPDATE condicional atómico, gateado por status='in_progress'. Es:
    #   - idempotente: un segundo intento (o cita ya done/canceled) matchea 0
    #     filas → no se duplica la transición ni el AppointmentStatusChange.
    #   - libre de ABBA: no adquiere un lock explícito de fila Appointment
    #     dentro del atomic que ya posee el lock del MedicalRecord. El row lock
    #     implícito del UPDATE se libera al commit del caller.
    #   - consistente con update_status/assign_patient (UPDATE directo, sin clean()).
    updated = (
        Appointment.objects
        .for_organization(appointment.organization)
        .filter(pk=appointment.pk, status='in_progress')
        .update(status='done')
    )

    if not updated:
        # No-op: ya finalizada, cancelada, o nunca iniciada.
        return appointment

    AppointmentStatusChange.objects.create(
        appointment=appointment,
        from_status='in_progress',
        to_status='done',
        changed_by=actor,
        reason='Auto-completada al cerrar la consulta médica',
        organization=appointment.organization,
    )

    return appointment
