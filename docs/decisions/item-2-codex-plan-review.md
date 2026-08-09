REQUEST CHANGES

# Revisión de plan — Item 2: restaurar `pending_action`

## Veredicto

El diseño acierta al restaurar el pendiente como vencido: el primer «sí» cae
en el re-parafraseo existente y no escribe en el dominio
(`backend/apps/agent/planner.py:607-619`). También prevé el scope por tenant,
el permiso dedicado y la actualización de Item 1. No es aprobable todavía: hay
transiciones que pueden perder la intención o liberar el handoff equivocado, y
F1 no puede afirmar atomicidad PostgreSQL con el modelo actual.

## Hallazgos

### P0 — `require_new_owner` no es atómico para un teléfono que aún no existe

- **Evidencia:** F1 solo añade el flag dentro de `atomic()` y declara que no
  habrá otra migración (`item-2-implementation-plan.md:94-114,237-244`).
  `Owner` no tiene unicidad por `(organization, phone)`
  (`backend/apps/patients/models.py:29-52`) y `create_with_patient` usa
  `Owner.objects.get_or_create(...)` (`backend/apps/appointments/views.py:359-364`).
  La revisión de seguridad ya exige una estrategia para este caso
  (`item-2-security-and-tests.md:134-158`).
- **Riesgo:** dos transacciones PostgreSQL, con idempotency keys distintas,
  pueden observar ausencia y crear dos Owners. Ambas habrán pasado
  `require_new_owner`; después el endpoint puede producir
  `MultipleObjectsReturned` o asociar datos a un expediente ambiguo.
- **Cambio requerido:** antes de F2, definir el tratamiento de teléfonos
  duplicados históricos y serializar *todos* los caminos de
  `create-with-patient` por `(organización, teléfono normalizado)`. Debe ser
  una restricción única tras migración/limpieza compatible con el producto, o
  un lock transaccional estable sobre una clave de deduplicación que cubra la
  ausencia de filas. Los duplicados históricos deben fallar cerrado como
  ambiguos. El mapa de migraciones debe reflejar la alternativa elegida.

### P0 — `owner_exists` puede borrar la intención antes de suspenderla

- **Evidencia:** `_commit_pending` invoca el commit y a continuación llama a
  `clear_pending` (`backend/apps/agent/planner.py:627-629`), que hace un
  `save()` independiente (`backend/apps/agent/confirmations.py:72-75`). F2
  ordena suspender antes de escalar, pero no especifica una transición única
  (`item-2-implementation-plan.md:127-129`).
- **Riesgo:** una excepción, crash o carrera entre ambos saves tras el `409
  owner_exists` deja el `pending_action` perdido y sin caso visible para staff.
  Es una violación directa del objetivo principal del Item.
- **Cambio requerido:** introducir un helper idempotente que, bajo
  `transaction.atomic()` y `select_for_update()` de `Conversation`, transfiera
  el staged íntegro a `flow['suspended']`, cree/retenga el `HumanHandoff` de
  identidad y elimine el pending en un solo commit. Esta rama no debe usar el
  `clear_pending` genérico.

### P0 — la carrera de `suspension_id` no puede completar el release

- **Evidencia:** R3 indica que si el `suspension_id` cambió no aplica el
  veredicto, pero que «el release sí procede»
  (`item-2-decision.md:239-245,836`).
- **Riesgo:** si se crea una segunda suspensión mientras R2 consulta el
  dominio, R3 puede activar la conversación, quitar el claim y resolver el
  handoff de la suspensión nueva sin haberla validado ni restaurado. Queda una
  intención inerte o se pierde.
- **Cambio requerido:** cuando el snapshot ya no coincida, R3 no debe mutar
  estado, claim ni handoff. Debe devolver conflicto/reintento, o repetir
  R1–R3 con el nuevo snapshot. Solo el snapshot que se verificó puede cerrar
  el handoff y liberar la conversación.

### P0 — F4 puede exponerse antes de que F3 haga seguro el release

- **Evidencia:** el grafo permite F4 tras F2, en paralelo con F3
  (`item-2-implementation-plan.md:31-55`). F4 habilita verificar, autorizar y
  liberar, mientras el release actual no restaura `flow['suspended']`
  (`backend/apps/agent/views.py:362-422`).
- **Riesgo:** una autorización correcta de staff seguida de release deja la
  intención congelada; no hay confirmación nueva ni ejecución posterior.
- **Cambio requerido:** F4 debe depender de F3 para despliegue/visibilidad del
  flujo, o sus endpoints y UI deben permanecer feature-gated hasta F3. El
  recorrido completo `owner_exists → verificar → autorizar → release → primer
  sí → re-parafraseo → segundo sí → commit` debe ser una prueba de aceptación.

### P1 — R3 debe volver a validar el lease y una transición de staff

- **Evidencia:** F3 revisa `processing_until` solo en R1
  (`item-2-decision.md:226-230`), pero libera el lock para la llamada HTTP. El
  worker puede adquirirlo después (`backend/apps/agent/worker.py:107-145`).
  Además, `claim_conversation` hace read-modify-write sin lock
  (`backend/apps/agent/views.py:331-348`).
- **Riesgo:** R3 puede reactivar o resolver una conversación mientras otro
  worker o miembro de staff ya tomó una instancia/claim nuevo, perdiendo keys
  de `flow`, un claim legítimo o el orden de mensajes.
- **Cambio requerido:** R3 debe revalidar bajo el mismo lock, como mínimo,
  `processing_until`, estado, claim y el handoff/suspensión observados en R1;
  ante diferencia, abortar o reintentar sin mutar. Claim, release y close deben
  serializarse por la misma fila o usar una revisión/compare-and-set explícita.

### P1 — la garantía de cupo sigue siendo read-then-write

- **Evidencia:** la disponibilidad se decide con `conflicts.exists()`
  (`backend/apps/appointments/serializers.py:113-130`). F0 solo bloquea la
  fila de la cita a actualizar (`item-2-implementation-plan.md:64-80`) y el
  modelo no tiene una exclusión de intervalo (`backend/apps/appointments/models.py`).
- **Riesgo:** dos POST, o dos reprogramaciones de citas distintas, pueden
  validar simultáneamente el mismo veterinario e intervalo y ambas persistir.
  `slot_taken` no es una garantía real en PostgreSQL.
- **Cambio requerido:** añadir al plan una garantía concurrente de cupo que
  cubra creación y PATCH: constraint de exclusión PostgreSQL o lock común por
  veterinario/franja, con migración, contrato de error y rollout. No declarar
  seguro el flujo hasta probarlo en PostgreSQL.

### P1 — la cobertura del contrato compartido de appointments está incompleta

- **Evidencia:** F0/F5 enumeran PATCH detalle y `/status/`, pero
  `DELETE /appointments/<id>/` también cancela la cita y crea
  `AppointmentStatusChange` sin precondición ni lock de la fila
  (`backend/apps/appointments/views.py:113-137`). El frontend lo consume
  (`frontend/src/api/appointments.js:25-28`).
- **Riesgo:** incluso tras el rollout obligatorio, DELETE puede competir con
  PATCH condicionado, generar una segunda auditoría o dejar una vía
  último-escritor-gana. El contrato documentado de «todos los actores» sería
  falso.
- **Cambio requerido:** incluir DELETE en la matriz del contrato: deprecarlo
  a favor de `/status/`, o aceptar/validar la misma `expected_state` bajo lock.
  Declarar también el alcance de `/assign-patient/` (incluido o excluido con
  justificación), actualizar ADR/contratos y conservar compatibilidad durante
  el periodo opt-in.

### P1 — el caso de verificación necesita atar aprobación, candidato y tenant

- **Evidencia:** el modelo proyectado tiene FKs separadas y F4 dice solo que
  el vínculo bloquea `ContactIdentity` (`item-2-implementation-plan.md:182-196`).
  Las FKs no prueban que `conversation`, `contact`, `owner_candidate` y su
  `organization` coincidan. La decisión exige que la aprobación sea del mismo
  caso abierto y candidato (`item-2-decision.md:647-687`).
- **Riesgo:** una aprobación para Owner A puede reutilizarse para Owner B, o
  una mala resolución puede crear auditoría/vínculo cross-tenant. Eso anula el
  RBAC y la trazabilidad que justifican FLUJO-C.
- **Cambio requerido:** derivar del servidor organización, contacto,
  conversación y actor; resolver el candidato exclusivamente con
  `Owner.objects.for_organization(conversation.organization)`; y exigir que la
  última aprobación corresponda al mismo candidato y al `HumanHandoff`
  `identity/owner_exists` aún abierto. Validar el invariante en servicio/modelo
  y bloquear `ContactIdentity` y el handoff al autorizar.

### P1 — los 409 de negocio deben salir de la telemetría de fallos técnicos

- **Evidencia:** F2 mapea conflictos en `tools.py`/`planner.py`
  (`item-2-implementation-plan.md:123-132`), pero `ToolExecutor.call()`
  registra los `>=400` como error HTTP técnico (`backend/apps/agent/executor.py:123-170`).
- **Riesgo:** `appointment_changed` y `owner_exists` contaminarán alertas y
  métricas de integración, contradiciendo la decisión de tratarlos como
  resultados de negocio auditables.
- **Cambio requerido:** incluir `executor.py` o una vía equivalente en F2 para
  clasificar los 409 conocidos como business outcomes redacted, con los eventos
  de dominio requeridos y sin `AGENT_TOOL_HTTP_ERROR`.

### P2 — coordinación documental de Item 1 incompleta

- **Evidencia:** el plan sí agenda sustituir «las tres únicas funciones» por
  cuatro (`item-2-implementation-plan.md:252-263`); la frase vigente está en
  `docs/whatsapp-agent-identity-context-fixes-plan.md:117-125`. La decisión
  además exige actualizar el docstring de `reset_contact_identity`
  (`item-2-decision.md:471-480`), obligación que no figura de forma explícita
  en F4.
- **Riesgo:** Item 1, su documentación operativa y el código describirán un
  número distinto de vías de promoción, debilitando la revisión futura del
  bloqueo `auto_rematch_blocked`.
- **Cambio requerido:** hacer esas dos actualizaciones parte explícita del DoD
  de F4 y mantener P2-8 como regresión bloqueante: una verificación de staff
  limpia `auto_rematch_blocked` solo mediante la vía auditada.

## Pruebas obligatorias antes de merge

- Línea base verde de `agent/` y `appointments/`; toda prueba de carrera debe
  ejecutarse con PostgreSQL, no SQLite.
- Dos conexiones y dos idempotency keys para la misma organización/teléfono:
  exactamente un Owner nuevo o un `409` cerrado; repetir mezclando actor agente
  y recepción.
- Dos POST/PATCH al mismo veterinario e intervalo: solo una cita persiste y la
  otra recibe el error de negocio definido.
- Inyectar una excepción entre `409 owner_exists` y la transición local: el
  staged completo debe seguir en `suspended` y el handoff de identidad abierto.
- Interleavings R1→nueva suspensión→R3, R1→claim de worker→R3 y
  R1→claim de otro staff→R3: ninguna transición nueva se libera, sobrescribe o
  pierde; la respuesta debe ser retry/conflicto cuando corresponda.
- Flujo extremo a extremo de FLUJO-C: `owner_exists`, verificar, autorizar,
  liberar, primer «sí» sin POST/PATCH y con re-paráfrasis, segundo «sí» con el
  único commit permitido.
- `expected_state` en PATCH detalle, `/status/` y DELETE: éxito, 409, cero
  `AppointmentStatusChange` adicional en conflicto y compatibilidad mientras
  la precondición sea opt-in.
- Tenant/RBAC: conversación o Owner candidato de otra organización devuelve
  404 sin filas de auditoría ni vínculo; aprobación del candidato A no autoriza
  B; rechazo o handoff cerrado invalida una aprobación previa.
- `appointment_changed` y `owner_exists` generan evento de negocio redacted,
  no elevan `AGENT_TOOL_HTTP_ERROR`, no cuentan como fallo técnico y no crean
  un handoff de `tool_failure`.
