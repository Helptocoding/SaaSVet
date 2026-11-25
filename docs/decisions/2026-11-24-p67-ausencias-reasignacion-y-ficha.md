# ADR p67 — Ausencias de integrantes, reasignación de citas y ficha

**Fecha:** 2026-11-24
**Estado:** ACEPTADO (decisiones del PO del 2026-11-24, Fase 3 de
[`auditoria-modulo-equipo-2026-11-23.md`](../auditoria-modulo-equipo-2026-11-23.md))
**Enmienda a:** ADR p66 (deja de estar pendiente la reasignación al desactivar), ADR p57
(INV-A e INV-D se conservan en la reasignación en bloque) y el contrato de candidatos del
agente (Q14: un veterinario ausente no tiene huecos ese día).

## Contexto

Tras la Fase 2, desactivar o quitar la función clínica avisaba de las citas próximas, pero no
había cómo moverlas salvo una por una en la agenda. Tampoco había forma de decir «el doctor
está de vacaciones del 1 al 5»: recepción podía agendarle citas esos días y el agente de
WhatsApp ofrecía sus horarios. La información de un integrante estaba repartida entre la
tabla, un modal de historial y el aviso de impacto.

## Decisiones

1. **Ausencia = días completos, fechas locales de la clínica** (`StaffAbsence`: integrante,
   primer y último día incluidos, tipo, quién y cuándo la registró). Es la misma unidad que
   `Appointment.date`. Tipos: vacaciones, capacitación, permiso, otro. «Permiso» cubre una
   incapacidad sin registrar datos de salud. No se borra: se **cancela** (`cancelled_at/by`).
   No se permiten dos ausencias vigentes que se crucen (`409 absence_overlap`); sí adyacentes.
   Fechas: el último día no antes del primero, no terminada antes de hoy y como máximo 366 días.
2. **Una ausencia vigente bloquea (PO)** crear, mover, reasignar a, reactivar y atender sin cita
   a ese integrante esos días, para recepción y para el agente: `400 veterinarian_absent`
   (mensaje en `errors.error`, como `slot_taken`). Editar una cita de ese día sin moverla sigue
   permitido. Si al final sí viene, se cancela la ausencia.
3. **Registrar una ausencia no mueve citas (PO).** La respuesta trae las citas por atender de
   esos días; la interfaz ofrece reasignarlas en el mismo flujo.
4. **Reasignación en bloque (PO): un destino para todas.** `POST /api/appointments/reassign/`
   (`appointment.update`). Cada cita se mueve si el destino está libre a esa hora y no está
   ausente ese día; las demás se quedan como estaban y vuelven con su motivo
   (`appointment_changed`, `not_reassignable`, `veterinarian_absent`, `slot_taken`,
   `not_found`). Solo cambia el veterinario: nunca fecha ni hora. Cada cita viaja con su
   `expected_state` (INV-A, obligatorio); el origen debe seguir siendo su veterinario. Origen y
   destino se bloquean con `lock_veterinarians` (orden por pk) antes de leer (INV-D); la
   restricción de exclusión sigue siendo la garantía. Cada cita movida deja su
   `AppointmentStatusChange` (mismo estado), como la asignación de paciente. El origen puede
   estar inactivo; el destino debe ser un clínico activo (ADR p66). Máximo 100 por operación.
5. **Serialización sin locks nuevos.** Registrar una ausencia bloquea la fila `User` del
   integrante, la misma que toman `lock_veterinarians` (alta, edición, estado, atención sin
   cita, comandos del agente) y la reasignación. La cita o la ausencia que llega segunda ve a la
   primera ya confirmada. Todos los bloqueos de `User` son por pk ascendente.
6. **Permiso nuevo `staff.manage_absences`** (sensible, solo ADMIN, ADR p63). Leer ausencias
   para la agenda basta con `staff.list`, sin tipo ni autor; el tipo y quién la registró solo
   los ve quien gestiona personal.
7. **Agente:** `_present_vets` excluye a los ausentes al proponer huecos, al comprobar una hora y
   al elegir veterinario; `validate_creation` y `validate_mutation` lo revalidan bajo lock
   (`veterinarian_absent` se añade a las razones de precondición B8). Los adaptadores B8 siguen
   apagados.
8. **Ficha del integrante** (`/staff/:publicId`): datos, pendientes, citas por atender con
   «Reasignar citas», ausencias (registrar y cancelar) e historial. Sustituye al modal de
   historial; el nombre en la tabla y «Ver ficha» la abren. Tras desactivar a alguien con citas,
   el aviso ofrece ir a reasignarlas. Endpoints de solo lectura para quien gestiona personal:
   `GET /api/staff/<uuid>/profile/` (también inactivos) y `.../appointments/` (con
   `expected_state`).
9. **Historial:** `StaffAccessEvent` gana `absence_added`, `absence_cancelled` y
   `appointments_reassigned` (fechas, tipo y conteos; nunca nombres ni datos de clientes).

## Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| Ausencias por horas | Exige partir la agenda por intervalos y el caso real es el día completo (vacaciones, congreso); se puede añadir después sin romper esto |
| Solo avisar en la agenda | Decisión del PO: bloquear; el agente no puede «leer un aviso» |
| Mover las citas al registrar la ausencia | Elegiría por el usuario; el PO prefirió listarlas y decidir |
| Destino por cita | Más control, más clics; el PO eligió un destino para todas |
| 409 de toda la reasignación si una cita cambió | Perdería las demás, que sí son válidas |
| Reasignar cambiando también la hora | Sería reprogramar al cliente sin avisarle |

## Consecuencias

- Migración aditiva `users.0016` (tabla nueva vacía; `StaffAccessEvent.kind` pasa de 20 a 32
  caracteres con tres valores más). Sin backfill.
- Nuevo error de agenda `400 veterinarian_absent` y de Equipo `409 absence_overlap`.
- Pendiente fuera de alcance: ausencias por horas, recurrentes y aprobación de solicitudes;
  avisar al cliente cuando su cita cambia de veterinario.
