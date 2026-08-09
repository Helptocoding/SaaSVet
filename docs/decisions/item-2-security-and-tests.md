# Revisión de seguridad y pruebas — Item 2: restaurar `pending_action`

**Fecha:** 2026-08-08
**Alcance:** revisión de la propuesta de `item-2-backend.md` y del Item 2 de
`whatsapp-agent-identity-context-fixes-plan.md`. No se modificó código de
producción.

## Dictamen

**REQUEST CHANGES — no aprobar tal cual.** La decisión de forzar el `pending_action` restaurado a
vencido es correcta y debe conservarse: impide que el primer «sí» posterior a
un hand-off ejecute una orden que el cliente no acaba de ver. Sin embargo, la
propuesta deja dos rutas de cambio obsoleto: una reprogramación puede pisar una
edición humana posterior, y un alta de cliente puede ejecutarse aunque el
humano haya cambiado la identidad durante el hand-off. También depende de un
PK interno en una consulta HTTP que dejará de funcionar cuando se desactive el
lookup legacy.

La alternativa recomendada es tratar un release como una **nueva propuesta**:

1. Validar si el trabajo ya quedó resuelto usando sólo identificadores públicos
   y siempre con el `ToolExecutor` de la organización de la conversación.
2. Si se conserva, restaurarlo vencido y exigir el re-parafraseo existente.
3. En el commit posterior, revalidar las precondiciones que un humano pudo
   cambiar; para mutaciones sobre una cita existente, exigir una precondición
   de versión/estado y rechazar el conflicto sin sobrescribir.

El re-parafraseo mitiga la intención obsoleta del cliente; no resuelve por sí
solo que el recurso del dominio cambie entre el chequeo de release y el segundo
«sí».

## Hechos verificados

- `policy.escalate_to_human` mueve el pending a un único
  `flow['suspended']` y borra `pending_action`; hoy no conserva
  `suspended_at` ni el motivo (`backend/apps/agent/policy.py:327-368`).
- `release_conversation` está acotado por tenant mediante `_get_conversation`,
  pero no bloquea la fila de conversación, no toca `flow` y no hace llamadas
  al dominio (`backend/apps/agent/views.py:40-45,362-422`).
- Una afirmativa llega a `_commit_pending` sin LLM. Si el pending expiró,
  re-stagea los mismos argumentos y emite el parafraseo; no ejecuta la acción
  (`backend/apps/agent/planner.py:601-619`). Esta es una salvaguarda adecuada.
- Crear cita y alta compuesta propagan una `X-Idempotency-Key`; cancelar y
  reprogramar no (`backend/apps/agent/tools.py:845-855,932-943,994-1010,
  1130-1143`). La idempotencia que existe en `appointments` sólo cubre POST de
  creación, no PATCH (`backend/apps/appointments/views.py:77-101,305-390`).
- El worker serializa normalmente por conversación mediante un lease de cinco
  minutos, pero `release_conversation` y el cron de nudge no participan de ese
  protocolo (`backend/apps/agent/worker.py:46,99-145`;
  `backend/apps/agent/policy.py:398-440`).
- La API de citas filtra por organización a partir del usuario AGENT. Éste es
  el boundary correcto para las verificaciones de release
  (`backend/apps/agent/executor.py:91-171`,
  `backend/apps/appointments/views.py:46-75,110-112`).

## Hallazgos y decisiones recomendadas

### P0 — una reprogramación restaurada puede sobrescribir al humano

Guardar `from_date`/`from_start_time` sólo permite decidir qué hacer al
liberar. No protege el intervalo posterior:

1. El release consulta la cita y concluye que aún está en el horario de origen.
2. El humano la mueve antes de que el cliente vea el re-parafraseo o antes de
   su segundo «sí».
3. `commit_reschedule_appointment` hace un PATCH incondicional con el destino
   viejo. `AppointmentDetailView` usa el serializer sin `If-Match`, versión o
   comparación del origen; por tanto prevalece el último escritor
   (`backend/apps/agent/tools.py:994-1010`,
   `backend/apps/appointments/views.py:104-112`,
   `backend/apps/appointments/serializers.py:79-149`).

**Riesgo:** una confirmación nueva, correctamente re-parafraseada, puede aun
así materializar una decisión desactualizada y deshacer trabajo explícito del
staff. Es especialmente grave porque la propuesta pretende precisamente no
pelear con cambios humanos.

**Alternativa:** al proponer guardar un precondition token del recurso
(idealmente una revisión/version del dominio; como mínimo `updated_at`, estado
y horario origen). El endpoint de actualización debe aplicar compare-and-swap
o `If-Match`; si no coincide, no debe actualizar ni escalar como fallo técnico:
debe informar que la cita cambió y pedir una nueva selección. `from_*` es un
dato necesario para explicar la discrepancia, pero no es un control de
concurrencia suficiente.

La misma comprobación debe cubrir `cancel_appointment`: después del release el
humano puede cancelarla, completarla o reprogramarla. Hoy un segundo PATCH de
cancelación devuelve un 400 que el commit clasifica como `tool_failure` y
escala, en vez de ser un no-op/estado ya resuelto
(`backend/apps/agent/tools.py:932-943`,
`backend/apps/agent/planner.py:631-675`).

### P0 — `register_new_client_and_pet` no vuelve a comprobar identidad

La tool verifica `contact.owner_id is None` sólo antes de stagear
(`backend/apps/agent/tools.py:1063-1083`). Su commit no vuelve a comprobarlo
antes de invocar `create-with-patient` (`1130-1177`). Si el staff identifica o
vincula al contacto durante el hand-off, pero no crea exactamente la misma
mascota y cita, el chequeo heurístico de release devuelve “no resuelto”. Tras
la re-confirmación se puede crear una mascota/cita usando `get_or_create` por
teléfono para un cliente que ya era conocido.

**Riesgo:** datos duplicados o una cita creada bajo el flujo de “cliente
nuevo” después de que un humano ya resolvió la identidad. La heuristic de tres
señales no cubre este cambio de contexto.

**Alternativa:** antes del commit, volver a evaluar al menos:

- `contact.owner_id`, `is_ambiguous` y el bloqueo de auto-rematch;
- que el teléfono staged siga siendo el contacto correcto;
- que el registro compuesto no exista ya con la misma clave de idempotencia.

Eso por sí solo sigue dejando una carrera: el contacto puede cambiar después
de releerlo y antes del POST, y un contacto que permanece `unknown` no está
autorizado a reutilizar un expediente ajeno sólo porque coincide el teléfono.
El teléfono localiza una posible ficha; no prueba identidad ni autoriza a
colgarle una mascota o cita. `create_with_patient` hace precisamente ese
`get_or_create(organization, phone)` y después crea la mascota bajo el owner
que devuelva (`backend/apps/appointments/views.py:350-363`).

**Cambio requerido:** el endpoint compartido debe aceptar una precondición
explícita, p. ej. `require_new_owner=true`, y comprobarla **dentro de la misma
transacción que crea Owner/Pet/Appointment**: si ya existe un Owner para el
teléfono, devolver `409 owner_exists` sin crear mascota, cita ni vínculo de
identidad. El commit del agente debe releer la `ContactIdentity` desde la base
y sólo usar esa modalidad cuando no tenga identidad verificada; ante
`identity_changed` u `owner_exists` debe conservar/suspender el caso para
staff, no interpretar el resultado como un fallo técnico ni auto-vincularlo.
La vía manual existente debe conservar su comportamiento actual sin el flag,
con contrato y rollout documentados. Para este tool recomiendo además **nunca
descartar automáticamente por la heurística**: restaurar vencido y dejar que
la precondición de commit decida evita un falso positivo silencioso.

### P0 — el endpoint compuesto no garantiza unicidad de Owner por teléfono

`Owner` no tiene una restricción única sobre `(organization, phone)`
(`backend/apps/patients/models.py:9-49`), pero `create_with_patient` depende
de `Owner.objects.get_or_create(organization=org, phone=owner_phone)`
(`backend/apps/appointments/views.py:350-353`). `get_or_create` no serializa
dos requests con claves de idempotencia distintas si la base no protege la
clave de búsqueda: ambos pueden observar ausencia y crear dos Owners. Tras
ello, una llamada futura puede fallar con `MultipleObjectsReturned`. La
idempotencia actual sólo es única por `(organization, appointment
idempotency_key)` y no impide este caso.

**Riesgo:** dos confirmaciones, un reintento con clave renovada o un actor
humano concurrente pueden duplicar expedientes y mascotas; el endpoint deja
de cumplir su promesa de "owner reutilizado por teléfono". Es además un
problema de autorización: no hay una identidad estable a la cual asociar la
decisión posterior.

**Cambio requerido:** producto y dominio deben definir la semántica de
teléfonos duplicados (migración de datos incluida). Para hacer atómico
`require_new_owner`, no basta un `exists()` previo: se requiere una
restricción/índice único compatible con la regla de negocio, o un protocolo de
lock sobre una clave de deduplicación que cubra también el caso "no existe
aún". Si hay duplicados históricos permitidos, `require_new_owner` debe fallar
cerrado como ambiguo y escalar, nunca elegir una fila arbitraria.

### P1 — el match de `create_appointment` no sobrevive al cutover a UUID

El staged de creación guarda `pet` como PK interno
(`backend/apps/agent/tools.py:831-837`). El plan propone usarlo como
`?pet=<staged.pet>`, pero `AppointmentListCreateView` resuelve ese filtro como
`Pet.public_id`; el PK sólo funciona mientras `ALLOW_LEGACY_ID_LOOKUP=True`
(`backend/apps/appointments/views.py:50-73`,
`backend/apps/core/views.py:35-56`). Con el flag apagado la verificación falla
y cae en el modo “no resuelto”, que re-ofrece una cita ya creada por el humano.

No es una fuga cross-tenant —la resolución sigue org-scoped—, pero rompe el
criterio de aceptación de descartar una cita ya realizada y reintroduce
duplicados conversacionales en el modo de seguridad futuro.

**Alternativa:** guardar también `pet_public_id` en el snapshot, usarlo sólo
para la lectura HTTP y conservar el PK sólo para el POST actual. Añadir una
prueba con `ALLOW_LEGACY_ID_LOOKUP=False`; no aceptar como cobertura una prueba
que herede el default legacy.

### P1 — TOCTOU entre release, worker, nudge y dos acciones de staff

El release actual hace lecturas y escrituras separadas sin
`transaction.atomic()`/`select_for_update()` sobre la conversación. El worker
sólo mantiene el lock durante el claim y después trabaja con una instancia
fuera de transacción; el nudge lee `nudge_sent`, encola y lo escribe sin lock.
Dos releases, un release y un nudge, o un release mientras un worker termina
pueden perder actualizaciones de `flow`, restaurar dos veces o emitir más de un
recordatorio.

El `idempotency_key` reduce el daño para POST de cita/alta, pero no hace
atómico el estado conversacional ni cubre PATCH. Limpiar `nudge_sent` aumenta
la probabilidad de recorrer esta carrera.

**Alternativa:** concentrar la transición en un servicio de release con un
lock de la fila `Conversation`; resolver el `HumanHandoff`, consumir el
suspendido y publicar el nuevo `flow` en una transición indivisible. La lectura
HTTP no debe mantener una transacción larga: capturar un token/version de
conversación, consultar fuera del lock y reabrir el lock para aplicar el
resultado sólo si el suspendido es el mismo snapshot. Si cambió, repetir o
abortar sin sobrescribir. El nudge debe reclamar atómicamente el derecho a
enviar (update condicional de `nudge_sent`), no hacer read-then-send.

Además, el endpoint debe ser idempotente: un segundo release no debe refrescar
el vencimiento ni rearmar el nudge de una misma suspensión. Para ello se
necesita un identificador inmutable de suspensión (`suspension_id` UUID) y no
sólo comparar el diccionario JSON.

### P1 — el dominio de agenda tampoco hace atómica la precondición ni el cupo

El control de precondición propuesto para cancelar/reprogramar debe ejecutarse
en el endpoint de `appointments`, no como `GET` seguido de `PATCH` en
`agent`. Hoy el PATCH genérico carga la cita y el serializer hace consultas de
conflicto antes de guardar, sin `select_for_update()` sobre la cita ni una
operación condicional (`backend/apps/appointments/views.py:104-112`;
`backend/apps/appointments/serializers.py:79-149`). Dos escritores pueden
validar el mismo estado y el último guardar gana. Del mismo modo, dos
creaciones/reprogramaciones hacia un mismo intervalo pueden pasar ambos
`conflicts.exists()` antes de insertar/guardar: no hay exclusión ni constraint
de solape en PostgreSQL.

**Riesgo:** un `expected_state` implementado como lectura previa por el agente
es una falsa protección; una cita editada por staff puede ser sobrescrita. La
promesa de que el dominio rechazará `slot_taken` tampoco es fiable bajo
concurrencia real, por lo que pueden quedar dos citas solapadas.

**Cambio requerido:** la mutación debe tomar el lock de la cita y comparar el
estado esperado en la misma `transaction.atomic()` que escribe; un desacuerdo
debe devolver un `409` de negocio y no crear `AppointmentStatusChange` ni
efectos secundarios. Separadamente, definir y aplicar la garantía de cupo
concurrente (constraint de exclusión/intervalo o lock común por veterinario y
ventana) para POST y PATCH. No declarar esta garantía hasta validarla en
PostgreSQL; SQLite no ejerce estos locks ni reproduce el aislamiento.

### P1 — estado suspendido viejo, corrupto o incompatible

Hay conversaciones históricas con `{'kind', 'state'}` sin los campos nuevos;
el estado es JSON sin schema. La propuesta debe definir comportamiento ante:

- `kind` distinto de `pending_action`;
- estado sin `tool`, `args`, `paraphrase`, `expires_at` o con tool desconocida;
- `suspended_at` ausente, no parseable o futuro;
- dos requests que intentan consumir el mismo suspendido.

No restaurar un pending malformado “para que el planner lo arregle”: el planner
sólo descarta tool desconocida después de que una afirmativa llegue al flujo.
Eso deja una orden ambigua expuesta al cliente. Registrar un evento sin PII,
consumir el suspendido y dejar trazabilidad de descarte es más seguro. Para
filas legacy válidas, falta `suspended_at` debe significar “restaurar vencido”,
nunca inferir que sigue vigente.

### P2 — vencimiento y nudge requieren una política coherente

Estoy de acuerdo con no reusar el TTL de 30 minutos: al release debe quedar
vencido aunque el hand-off durara segundos. No recomiendo un descarte silencioso
por 24/48 h: un timeout de producto no prueba que el cliente desistió. Si se
añade un límite, debe cerrar el pendiente de forma observable para staff y
tener una razón auditable, no simplemente hacer `pop`.

También debe decidirse qué hacer con `deferred_at`. Si el cliente había dicho
«déjame pensarlo» antes de la escalada, borrar sólo `nudge_sent` no hará que el
nudge vuelva a salir porque `nudge_abandoned_flows` bloquea también por
`deferred_at` (`backend/apps/agent/policy.py:419-430`). Preservarlo parece
correcto para respetar la promesa de esperar; si producto quiere un recordatorio
tras el release, debe borrar ambos flags de forma explícita y documentar que
la promesa fue reemplazada por el contexto humano.

## Aislamiento y autorización

La dirección planteada es válida sólo con estas guardas:

- El release debe obtener la conversación con el usuario staff y
  `for_organization(request.user.organization)`, como hoy; la prueba
  cross-tenant debe exigir 404.
- La verificación de dominio debe construir el executor desde
  `conversation.organization` y su `AgentSettings.agent_user`, nunca del
  usuario staff ni de un id recibido del request. Las APIs de owner, mascota y
  citas ya aplican el queryset de la organización del AGENT.
- Los valores staged son datos no confiables para formar una ruta sin validar:
  aceptar únicamente los cuatro tools permitidos, UUIDs/PKs con el tipo
  esperado y fechas/horas parseables. Un flow es scratchpad, no fuente de
  verdad.
- Las búsquedas por teléfono para el alta deben comparar igualdad exacta tras
  normalización; `?search` es `icontains` y puede devolver hasta 20 filas.
  Nunca descartar por el primer resultado ni por el nombre de mascota sin
  verificar tenant, teléfono exacto y la cita exacta.

## Matriz de pruebas propuesta

Las pruebas de aceptación actuales T5–T9 son necesarias, pero insuficientes.
Las siguientes deben añadirse antes de aprobar la implementación.

| Prioridad | Prueba concreta | Preparación y aserción principal |
|---|---|---|
| P0 | `test_release_then_first_yes_only_reparaphrases` | Suspender cada uno de los cuatro tools, liberar sin resolución y enviar «sí». Afirmar que no hay POST/PATCH ni mutación; que se encoló `EXPIRED_REPARAPHRASE`. Un segundo «sí» es el único que puede invocar el commit. |
| P0 | `test_reschedule_commit_rejects_human_change_after_release` | Suspender una reprogramación; liberar cuando sigue en origen; modificar la cita como staff; confirmar dos veces. Afirmar que la cita conserva el cambio humano, no hay PATCH ciego y se obtiene un resultado de negocio para elegir de nuevo. |
| P0 | `test_cancel_commit_is_idempotent_when_staff_already_canceled` | Entre release y segunda confirmación, cancelar como staff. Afirmar: ninguna segunda transición, no se crea/escalona un handoff técnico y el pending queda terminalmente resuelto. |
| P0 | `test_register_commit_rechecks_identity_changed_during_handoff` | Suspender un alta; durante el hand-off enlazar `ContactIdentity` a un Owner; liberar y reconfirmar. Afirmar: no se llama `create-with-patient`, no se crea Pet/Appointment y se devuelve `identity_changed`. |
| P0 | `test_register_requires_new_owner_atomically` | Con un Owner existente del mismo teléfono y contacto no verificado, ejecutar el commit con `require_new_owner=true`. Afirmar `409 owner_exists`, cero Pet/Appointment nuevo y cero auto-vínculo. Repetir con identidad que cambia justo antes del commit. |
| P0 | `test_concurrent_new_owner_registration_same_phone_is_single_or_fails_closed` | Dos conexiones PostgreSQL, misma org/teléfono y dos claves de idempotencia. Liberarlas con una barrera en la sección crítica. Afirmar exactamente un Owner o un resultado explícito `owner_exists`/ambiguo; nunca dos Owners, Pets ni citas huérfanas. |
| P1 | `test_release_create_match_uses_pet_uuid_with_legacy_lookup_disabled` | Con `@override_settings(ALLOW_LEGACY_ID_LOOKUP=False)`, crear manualmente la cita coincidente y liberar. Afirmar que se descarta, no se restaura. Confirma que la lectura no usa el PK staged. |
| P1 | `test_release_cross_tenant_is_404_and_never_calls_executor` | Usuario de org B intenta liberar conversación de A, con transport espía. Afirmar 404, flow y handoff intactos y cero llamadas HTTP. |
| P1 | `test_domain_lookup_is_scoped_to_agent_organization` | Crear Owner/Pet/cita idénticos en A y B; liberar A. El transport debe ver token de A y la coincidencia B nunca puede provocar descarte. |
| P1 | `test_release_domain_timeout_restores_expired_not_live_pending` | Simular timeout/599 en cada tool. Afirmar que se restaura, se borra sólo el flag de nudge definido por política y `expires_at <= now`; el primer sí no ejecuta. |
| P1 | `test_release_is_idempotent_for_same_suspension` | POST release dos veces, incluido tras haber restaurado. Afirmar un único handoff resuelto, un único `suspension_id`, mismo vencimiento y que no se reabre el nudge por segunda vez. |
| P1 | `test_concurrent_release_and_nudge_emit_at_most_one_nudge` | `TransactionTestCase` con dos conexiones y una barrera: nudge y release compiten sobre la misma conversación. Afirmar a lo sumo un saliente de nudge y un flow final válido. Ejecutar contra PostgreSQL, no SQLite. |
| P1 | `test_concurrent_two_releases_do_not_lose_flow_or_double_resolve` | Dos requests staff concurrentes con el mismo suspendido. Afirmar un solo consumo/restauración, un solo cierre de handoff y ausencia de pérdida de `deferred_at`/otros campos no relacionados. |
| P1 | `test_expected_state_is_checked_under_lock_against_staff_patch` | Dos conexiones PostgreSQL: agente y staff intentan mutar la misma cita desde el mismo estado, coordinadas para competir. Afirmar un único ganador; el perdedor recibe `409 appointment_changed`, no hay sobrescritura ni segundo evento de estado. |
| P1 | `test_concurrent_slot_claims_do_not_overlap` | Ejecutar en PostgreSQL dos POST/PATCH hacia el mismo veterinario e intervalo mediante una barrera después de la validación. Afirmar que sólo uno persiste y el otro recibe el error de negocio definido. |
| P1 | `test_legacy_and_corrupt_suspended_states_fail_closed` | Parametrizar: falta `suspended_at` válida, fecha inválida, tool desconocido, args/paraphrase ausentes y kind ajeno. Afirmar legacy válido → restaurado vencido; corrupto → descartado/auditado sin llamado al dominio ni commit posterior. |
| P2 | `test_register_heuristic_requires_exact_phone_pet_and_appointment` | Casos de teléfono parcial, homónimos de mascota, dos Owners y cita en otra hora. Afirmar que ninguno descarta. Repetir con las tres coincidencias exactas sólo si producto aprueba la heurística. |
| P2 | `test_release_preserves_deferred_at_and_does_not_nudge` | Pending diferido antes de escalar; tras release no debe enviar nudge. Si se decide la política contraria, sustituir por una prueba que pruebe el borrado explícito de ambos flags y el texto de producto. |
| P2 | `test_suspension_age_boundary_is_observable` | Si se aprueba un máximo de edad, probar justo antes/después del umbral, zona horaria y timestamp futuro; exigir evento con razón y nunca un descarte silencioso. |

Para los cuatro tools debe existir además una tabla parametrizada de resultado
del chequeo: resuelto exacto, no resuelto, ambiguo, 404, 400, 5xx y timeout.
Sólo el match exacto puede descartar. Las demás rutas deben restaurar vencidas,
salvo corrupción local que debe cerrarse de forma segura y auditable.

## Cobertura existente y ejecución

Existen pruebas de confirmación vencida y de idempotencia de creación:

- `backend/apps/agent/tests/test_write_tools.py:367-389` y
  `test_regression_f2.py:200-210` cubren que un pending vencido no ejecuta.
- `backend/apps/agent/tests/test_inbox_api.py:253-289` cubre resolver el
  handoff y los compromisos de identidad, no `pending_action`.
- `backend/apps/agent/tests/test_policy.py:95-111` cubre suspender, no
  restaurar.

Intenté ejecutar `test_write_tools`, `test_policy`, `test_inbox_api` y
`test_idempotency`, pero el entorno no tiene Django instalado:
`python3 manage.py test …` falla durante el arranque con
`ModuleNotFoundError: No module named 'django'`. Por ello este documento no
afirma que la línea base pase; las pruebas anteriores se identificaron por
lectura directa.

## Decisiones de producto que siguen abiertas

1. Para alta de cliente, aprobar explícitamente “nunca auto-descartar” salvo
   idempotency key del mismo commit; es la opción segura recomendada.
2. Definir si el teléfono puede ser una clave única por tenant y cómo se
   migrarán/atenderán duplicados históricos. Mientras no exista esa decisión,
   el agente debe fallar cerrado ante Owner existente o ambiguo.
3. Definir si un cambio humano posterior debe prevalecer siempre. Recomiendo
   que sí: el commit condicionado debe pedir una nueva elección, no reintentar
   el destino viejo.
4. Decidir la semántica de `deferred_at` al liberar. Por defecto debe
   preservarse para no contradecir una promesa hecha al cliente.
5. Si se establece edad máxima, definir el cierre visible/auditable y su UX;
   no convertirlo en pérdida silenciosa.
