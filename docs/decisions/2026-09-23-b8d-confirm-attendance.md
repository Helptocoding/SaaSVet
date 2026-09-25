# ADR — B8D: confirmación de asistencia futura

Fecha: 2026-09-23. Decisión implementada; aceptación registrada en el acta B8D.
Baseline: `b0d2d347ecb3b50ec0637122ec2460480b81dced`.

## Contexto

El plan canónico asigna asistencia a B8D, incluida la definición del modo contextual.
Agenda distingue confirmed (confirmación opcional previa) de in_progress (consulta).
B7A ya fija appointment_id y target_status=confirmed, pero B7B/B8A mantenían cerrado
CONTEXTUAL_DECLARATION. B8C aporta snapshot, locks y evidencia histórica de mutación.

## Decisión

1. Mantener parámetros v1 y única entrada execute_authorized_operation. Registrar
   ConfirmAttendanceAdapter LOCAL_ATOMIC. No conexión del LLM con APIs humanas.
2. Reutilizar mutations.py, ALLOWED_TRANSITIONS y el ledger de B8C. Extraer
   confirm_locked para que /status/ y el adapter compartan scheduled→confirmed y
   AppointmentStatusChange. No modificar la permisividad histórica humana.
3. Acotar nuevas definiciones a preconditions schema 3 y attendance_contract=1,
   incluidos en digest, con el snapshot B8C íntegro. Mantener lectores históricos;
   nunca convertir una definición antigua en un consentimiento de asistencia.
4. Habilitar el modo contextual solo para esa definición: tarjeta emitida exacta,
   reply-to con «sí confirmo que asistiré» o token CONFIRMAR exacto. Una declaración
   anterior a emisión, pregunta, bare sí, corrección o condición no autoriza.
   AuthorizationEvidence usa policy 2; witness de recepción B7B permanece versión 1.
   La constraint de decisión conserva policy 1 y admite policy 2 solo en este scope.
5. Exigir scheduled activa/futura, relaciones actuales y snapshot bajo Appointment
   FOR UPDATE. No hay restricción nueva para humanos. Un MedicalRecord asociado
   bloquea el comando autónomo por revisión humana, sin reinterpretar su estado.
6. Extender AppointmentMutationEffect con kind y enlace OneToOne nullable/PROTECT a
   AppointmentStatusChange. El enlace es obligatorio para confirmación; trigger
   verifica auditoría exacta y before→after, además del trigger inmutable de B8C.
   Una operación y una auditoría solo acreditan un efecto. source_operation B8B intacto.
7. Reconciliar historia, independientemente del estado actual de la cita. Confirmación
   humana previa sin ledger propio nunca es éxito del agente. Retry posterior a
   in_progress/done no escribe de nuevo. Contradicción exige UNCERTAIN.

## Consecuencias y límites

No nuevas tablas, servicios externos, colas ni event sourcing general. Dos migraciones
aditivas: agent.0027_attendance_consent_policy y appointments.0018_confirm_attendance_effect.
Sin backfill; NULL en auditorías antiguas mantiene el contrato B8C. Guards B7B/B8A,
fencing y locks conservan prioridad de corrección/revocación/takeover según commit.
Cache on_commit robusta y notificaciones derivadas existentes; no promesa de entrega
remota exactamente una vez ni interpretación clínica de presencia.

Producción conserva B0 cerrado, flags vacías, REGISTER_PET DISABLED y
PENDING_ACTIVATION_REQUIREMENTS. Sin despliegue ni B8E. Rollback funcional cierra
CONFIRM_ATTENDANCE y conserva efectos, auditoría y consentimiento; no reabre scheduled.
No volver a un lector que desconoce schema 3 tras persistir datos B8D.

Referencias: [contrato](../contrato-confirm-attendance-b8d.md),
[acta](../implementacion-b8d-agente-whatsapp-2026-09-23.md),
[plan](../plan-implementacion-auditoria-agente-whatsapp-2026-09md).
