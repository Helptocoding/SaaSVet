# Contrato B8D — CONFIRM_ATTENDANCE

Congelado antes del adapter, 2026-09-23. Baseline y HEAD inicial:
`b0d2d347ecb3b50ec0637122ec2460480b81dced`, cierre documental B8C.
Estado inicial ajeno: `D DEPLOY_VPS_PLAN.md`, `D DEPLOY_VPS_STATUS.md`,
`?? docs/auditoria-agente-conversacional-veterinario-2026-09-10.md`.
El plan canónico real conserva el nombre `plan-implementacion-auditoria-agente-whatsapp-2026-09md`;
§7 asigna B8D a asistencia y exige contrato contextual. No hay discrepancia de operación.

## Dominio observado y alcance

Appointment.status define scheduled, confirmed, in_progress, done, canceled y
no_show. Según Agenda (§ Flujo de cita programada), confirmed es confirmación
opcional previa a atención; in_progress inicia consulta al llegar el paciente.
No representa llegada, consulta, finalización ni cobro.

`PATCH /api/appointments/<public_id>/status/`, `update_status`, aplica
ALLOWED_TRANSITIONS bajo veterinarios→Appointment y expected_state. Solo scheduled
puede pasar a confirmed. Registra AppointmentStatusChange con actor y sin motivo.
La ruta humana permite confirmar una cita pasada; se conserva esa política.
PATCH genérico/serializer conserva su política histórica, distinta de /status/.
Se extrae únicamente confirm_locked a mutations.py para compartir transición y
auditoría con /status/, sin cambiar sus errores ni permisos.

B8D conserva la restricción de futuro de B7A: scheduled activa, inicio aún futuro,
pet/owner/contacto vigentes y exactos. confirmed previo de cualquier otro actor,
canceled, no_show, in_progress y done no son elegibles. Una reprogramación invalida
el snapshot aunque conserve scheduled. Walk-in normal nace in_progress y no es
elegible; una fila walk_in scheduled futura solo es elegible si cumple todas las
mismas condiciones. El flag walk_in no concede excepciones.
Como restricción conservadora del comando autónomo, una cita con MedicalRecord
asociado requiere revisión humana, incluso si su status quedó scheduled. No se
interpreta OPEN como presencia física. No se modifica ni crea ningún registro
clínico, Invoice, Payment, inventario ni otra cita.

## Definición y consentimiento

Parámetros B7A v1 intactos: appointment_id y target_status="confirmed".
FK persistida, parámetro, Appointment real, tenant, pet, owner y contact deben
coincidir. No búsqueda por teléfono, nombre ni siguiente cita.
Nuevas definiciones B8D: preconditions schema 3, appointment_snapshot B8C schema 1
y attendance_contract=1 incluidos en digest. Schema 1/2 de asistencia falla
cerrado; no backfill, rehash ni autorización retroactiva.

Modo CONTEXTUAL_DECLARATION acotado: tarjeta determinista emitida con mascota,
referencia pública de cita, fecha, ambos extremos con precisión original, zona y
veterinario. Autoriza únicamente una respuesta causal a esa tarjeta: declaración
completa «sí confirmo que asistiré» mediante reply-to exacto, o CONFIRMAR con el
token exacto visible. No se admiten preguntas, «sí» aislado, paráfrasis libres,
varios mensajes, condiciones ni correcciones. No segundo ritual. Se reutilizan
emisión B4, witness inmutable de recepción B7B, TTL y AuthorizationEvidence;
policy de asistencia versionada 2, sin alterar policy 1 de otras operaciones.
La declaración previa a la tarjeta no autoriza. Consentimiento no afirma efecto.

## Atomicidad, preconditions y evidencia

Única entrada execute_authorized_operation(key, ExecutionContext). Registry
explícito; ningún parámetro alternativo ni llamada de tool al endpoint humano.
AGENT continúa bloqueado en API humana. B0 + flag CONFIRM_ATTENDANCE estrictamente
True + adapter + guard B8A + preconditions son necesarios para un efecto nuevo.

Locks: Conversation → TurnWork → ContactIdentity → Goal → Operation → Organization
FOR SHARE → veterinario autorizado FOR UPDATE → Appointment FOR UPDATE → owner/pet
FOR SHARE. Snapshot comparado bajo lock, sin adquirir un nuevo vet fuera de orden.
Se revalidan zona, UTC/local, futuro, actividad, relaciones, permiso, revisiones,
expiry, evidencia causal, nuevos inputs, corrección, takeover, handoff y safety.
La ausencia de consulta se comprueba bajo el lock de Appointment. No red/LLM.

LOCAL_ATOMIC contiene guard final, locks, comparación, transición scheduled→confirmed,
AppointmentStatusChange, AppointmentMutationEffect, intento y resultado. Extensión
aditiva acotada del ledger B8C: nuevo kind y FK nullable PROTECT a status_change,
obligatoria para confirmaciones nuevas. Before contiene el snapshot autorizado;
after difiere únicamente en status; operación única, digest y committed_at DB.
Trigger protege evidencia inmutable y su enlace exacto a auditoría. source_operation
de B8B conserva exclusivamente procedencia de creación.

Reconcile consulta por operation_key global antes de ejecutar: evidencia completa
exacta → SUCCEEDED; ausencia probada → evaluar elegibilidad; contradicción/incompleta
→ UNCERTAIN. confirmed por sí solo no es prueba. Retry verifica evidencia histórica,
sin exigir que la cita siga confirmed ni revertir in_progress/done o cambios humanos
posteriores. Un fallo sin prueba de ausencia nunca es FAILED.

Migraciones aditivas: appointments.0018_confirm_attendance_effect extiende el
ledger con OneToOne nullable a auditoría, y agent.0027_attendance_consent_policy
admite policy 2 únicamente para asistencia schema 3/contract 1. La constraint
anterior de policy 1 se conserva como alternativa histórica; no se modifican filas.

## Side effects, gates y rollback

Confirmation produce una auditoría y la invalidación de dashboard on_commit robusta
existente. Notificaciones próximas/atrasadas se derivan por consulta para
scheduled/confirmed; no hay envío ni recordatorio remoto en esta transición.
Billing declara explícitamente ausencia de signal Appointment→Invoice. No eventos
financieros/clínicos ni promesa exactly-once externa. Retry no repite save/auditoría/cache.

CREATE B8B, RESCHEDULE/CANCEL B8C y CONFIRM B8D: adapters entregados, producción OFF.
REGISTER_PET continúa DISABLED/sin adapter incluso con flag accidental.
PENDING_ACTIVATION_REQUIREMENTS permanece. No despliegue ni B8E.
Rollback funcional: cerrar flag CONFIRM_ATTENDANCE y mantener B0 cerrado;
preservar citas, auditoría, operaciones, autorización y evidencia histórica.
No revertir confirmed a scheduled ni deshacer migración con datos B8D. Lector mínimo
para schema 3 y evidencia de confirmación: esta entrega. Cierre sujeto a aceptación.
