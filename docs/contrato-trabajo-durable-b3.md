# Contrato B3 — trabajo durable y autoridad local

Fecha: 2026-09-15. Base: `a06b4f7`. Alcance exclusivo B3/C4/C5 del
[plan canónico](plan-implementacion-auditoria-agente-whatsapp-2026-09md).

> Actualización 2026-09-16: la frontera externa ya está implementada en el
> [contrato B4](contrato-sender-durable-b4.md). La enmienda B4 al final prevalece
> sobre las referencias al sender legacy; lo siguiente conserva el corte B3.

**B3 garantiza autoridad y publicación local durable. B4 resolverá la frontera
de dispatch externo y resultados inciertos.** `COMPLETED` describe trabajo local;
no acredita éxito de negocio, entrega de Meta ni atención humana. Containment
B0, `TurnContext` B1 y el manifiesto/`ToolOutcome` B2 conservan su autoridad.

## Datos y causalidad

`agent.TurnWork` es la única nueva tabla operativa. Contiene organization,
conversation, anchor_message/anchor_created_at, cursor_message_id/cursor_created_at,
context_at, clinic_timezone, status, lease_token, lease_expires_at, attempts,
next_attempt_at, claimed_at, completed_at, outcome_code y ownership_epoch.
Estados: `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`.

- `(conversation, anchor_message)` identifica establemente el turno.
- Índice único parcial: como máximo un trabajo `PENDING`/`PROCESSING` por conversación.
- `Message.turn_work` fija los miembros inbound. El anchor es el último miembro;
  el cursor B1 exclusivo es `(created_at, id)` del primero. No hay otra tabla de
  membership, transcript duplicado ni snapshot persistido.
- `context_at` y `clinic_timezone` fijan el reloj contextual B1. La recuperación
  carga **solo** esos miembros y reconstruye `TurnContext` inmutable; el historial
  anterior conserva el límite exclusivo y los permisos existentes.
- Los triggers PostgreSQL impiden reasignar miembros, cambiar su evidencia
  causal (incluido payload_type), anexar miembros tras el claim o cruzar
  organización/conversación/contacto/canal. Protegen también la
  identidad causal del trabajo y la monotonía del epoch.

Migraciones aditivas:

1. `agent.0022_conversation_ownership_epoch_turnwork`.
2. `channels.0011_message_origin_epoch_message_output_ordinal_and_more`.
3. `channels.0012_b3_scope_and_membership` (guards PostgreSQL).

Constraints: `turnwork_unique_anchor`, `turnwork_one_nonterminal`,
`turnwork_processing_lease`, `turnwork_completed_outcome`,
`message_unique_turn_output`, `message_turn_output_evidence`.
Índices de polling: `turnwork_poll_retry`, `turnwork_poll_lease`; se conservan
los índices FK y las unicidades previas de webhook/outbox. Triggers:
`b3_turnwork_scope`, `b3_message_scope`, `b3_conversation_epoch`.

## Claim, witness y recuperación

`durable.claim_turn` bloquea Conversation y luego TurnWork en una transacción
corta. Un lease vigente impide otro claim. Si no hay trabajo no terminal,
fija los inbound elegibles sin asignar y crea el trabajo. Si el lease expiró,
recupera **el mismo trabajo** con un nuevo UUID y aumenta attempts. Cada transición
comprueba estado/token/epoch/scope; no hay una segunda generación o token.

`OwnershipWitness` es un value object inmutable con organization_id,
conversation_id, turn_work_id, lease_token y ownership_epoch. No se persiste.
Su validación consulta la concesión actual y el epoch actual de Conversation.
La publicación/finalización toma locks y hace CAS condicionado por UUID, epoch,
scope, estado `PROCESSING` y lease no expirado. Cero filas actualizadas significa
pérdida de autoridad, lanza error y revierte la transacción.

El reloj de autoridad es PostgreSQL (`statement_timestamp()`/`Now()`), nunca
el argumento opcional de reloj del polling. Lease: **15 minutos**. Deadline
local: **12 minutos**, comprobado al entrar, entre pasos, antes de LLM/HTTP y
al finalizar. Las llamadas conservan sus timeouts existentes; una llamada
bloqueada que sobrepasa el lease no puede publicar al volver. No hay thread de
heartbeat ni renovación periódica: este margen y las comprobaciones bastan
para el flujo actual contenido. No se promete cancelar una llamada ya iniciada.

Se conserva el límite de **3 intentos** del worker. Backoff simple: 30 s tras
el primero, 60 s tras el segundo; polling existente. Después queda `FAILED`
con outcome diagnóstico. La escalación técnica existente y su aviso local
deduplicado pueden persistirse en la misma transacción del fallo terminal,
correlacionado con el trabajo y ordinal 0. No acredita aviso externo.

Los inbound permanecen `PENDING` durante el claim y los retries. Solo completion
local válida los proyecta a `PROCESSED`. En `FAILED` siguen pendientes pero
**asignados**, por lo que no originan otro TurnWork automáticamente. Requieren
atención/reconciliación operativa; no existe replay automático de fallos.

`processing_until` permanece como proyección de compatibilidad escrita al
claim/final/fallo/invalidation. Worker y release leen TurnWork, no esa proyección.
`process_attempts` conserva una proyección por miembro. No hay dos autoridades.

## Planificación y publicación

`worker._run_turn(witness)` usa `TurnWork → TurnContext`. `TurnChanges` adapta
los escritores locales existentes: Conversation, ContactIdentity, goals/slots,
handoff y diagnósticos. Acumula cambios y texto en memoria; no crea Messages
borrador. Reserva secuencias PostgreSQL para referencias internas entre cambios
nuevos, sin insertar filas; los huecos de secuencia tras un crash son normales.

Los escritores validan scope y witness. Durante LLM, herramientas HTTP,
planificación y rendering no se mantiene la transacción final abierta.
`finalize_turn` persiste en **un commit**:

1. cambios locales y diagnóstico (`TurnDecision` incluye work/epoch);
2. outputs finales `Message(out, PENDING)` con turn_work, origin_epoch y ordinal
   determinista 0..N-1;
3. completion por CAS y proyección final de inbound.

La unicidad parcial `(turn_work, output_ordinal)` refuerza la publicación
idempotente local. Un error antes del commit no deja estado local parcialmente
publicado; un error dentro revierte todo. Los logs de llamadas abortadas pueden
existir, pero sus filas diagnósticas no conceden autoridad. Las alertas externas
opcionales existentes se intentan después del commit; durabilidad de atención
humana corresponde a B5. Las APIs de negocio no reciben guards B8 nuevos.

## Nuevo input y no-starvation

Ingestión, claim y consolidación se coordinan sobre Conversation. M3 que llega
mientras W1 contiene M1/M2 se guarda normalmente, sin incorporarse a W1 ni
mover su cursor. `has_new_input` detecta un inbound posterior al anchor.
En la transacción final se suprime toda publicación de W1 si apareció ese input;
W1 termina `COMPLETED/deferred_to_new_input`, con sus cambios locales válidos y
miembros procesados. El siguiente trabajo toma M3. No se reinicia W1.

Esta política conservadora también difiere ante cortesías: B3 no interpreta
correcciones de mascota, fecha o acción. Binding revisions e invalidación
semántica quedan en B6/B7. No se habilitan efectos WRITE con input más nuevo.

## Ownership, tenant y locks

`Conversation.ownership_epoch` empieza en **0** para legacy; es generación de
autoridad, no versión de cada mensaje. Takeover humano, respuesta que toma la
conversación, return/release, cierre y reset/unlink operativo invalidan autoridad
mediante el helper común bajo lock de Conversation. Repetir el mismo claim
humano sin transición no incrementa el epoch. Reset alcanza los episodios del
contacto en orden de PK y conserva historial.

La invalidación incrementa epoch, termina trabajo no terminal y descarta bot
pending identificable. Nunca borra enviados ni reinterpreta delivery. Un witness
anterior no puede guardar goal/slots, publicar, completar ni liberar el lease
del nuevo worker. Guards de DB y validación server-side impiden scope cruzado.

Orden B3: **Conversation → TurnWork → Message**. Cambios locales dependientes
se consolidan después de adquirir los primeros locks. La creación de episodio
conserva el mutex ContactIdentity existente, pero lo suelta antes de reparar
duplicados tomando locks de Conversation. El sender legacy solo bloquea Message;
no adquiere después un lock de Conversation. No se modifican locks de agenda,
billing ni inventario y no se declara implementada la matriz B8.

## Sender compatible y legacy

El sender sigue seleccionando `PENDING` y usando su transporte/batch actual.
Antes de llamar al proveedor comprueba epoch actual, tenant/canal/contacto y
correlación de trabajo. Acepta outputs de trabajo COMPLETED; un aviso técnico
correlacionado puede proceder de FAILED. Epoch obsoleto/scope inválido se
descarta con causa. Mensajes humanos nuevos y publicaciones locales fuera de
turno capturan epoch bajo lock, aunque no tengan TurnWork.

Históricos: Conversation obtiene epoch 0 como versión inicial; inbound ya
procesado conserva turn_work NULL; outbound sin evidencia conserva turn_work
NULL/origin_epoch NULL. **No se fabrica epoch 0 para esos Messages.** Siguen
siendo legibles. Los pendientes sin origin_epoch se descartan al seleccionar con
`failure_reason=legacy_unverified`; no se reenvían automáticamente, incluidos
los humanos ambiguos. Los enviados/delivered/read no se alteran.

El chequeo antes de dispatch no cancela ni cerca completamente un HTTP remoto
ya admitido. El sender aún mantiene su lock/transacción durante HTTP, con los
riesgos legacy de resultado incierto o duplicado después de crash. No existen
SENDING, UNCERTAIN persistente, send_token, send_lease_until ni reconciliación.
Eso es B4 y **no impide desplegar B3 con el sender compatible**.

## Observación y límites

Eventos JSON `AGENT_TURN_CREATED`, `CLAIMED`, `RECLAIMED`, `LEASE_EXPIRED`,
`COMPLETED`, `FAILED`, `RETRY_SCHEDULED`, `FENCING_REJECT`,
`DEFERRED_TO_NEW_INPUT`, `OWNERSHIP_CHANGED` (todos con prefijo AGENT_TURN).
Transitions se registran al commit; rechazo se registra aunque haya rollback.
Attempts y work/conversation/org IDs son campos de log, no labels de métricas.
Al crear trabajo se registra `oldest_pending_age_seconds` de sus miembros.
No se añade transcript/PII ni se registra el token completo. No es el paquete B9.

Impacto: H06, parte fundamental de H08, causalidad H11 y exclusión/recuperación
de H19. **H07 sigue abierto; H08 y escalabilidad H19 no quedan resueltos por
completo.** No se promete entrega exactamente una vez.

Despliegue requiere ventana controlada, nunca workers viejos y B3 simultáneos.
Secuencia, observación, legacy y rollback en el
[runbook](runbooks/agent-whatsapp.md#b3-despliegue-controlado-y-rollback).
Activación: `PENDING_ACTIVATION_REQUIREMENTS`. Sin despliegue automático.

## Enmienda de frontera B4 — 2026-09-16

La sección «Sender compatible y legacy» anterior describe el corte B3.
Para el runtime actual la sustituye el [contrato sender B4](contrato-sender-durable-b4.md):
claim individual, admisión/HTTP/finalización separados y UNCERTAIN durable.
El sender toma Conversation→Message; no espera Meta bajo locks. La autoridad
de procesamiento TurnWork y su publicación atómica permanecen como aquí se
definieron. El helper de invalidación descarta además SENDING sin admisión;
los admitidos conservan la posibilidad de registrar su resultado externo.


## Enmienda B3/C4/W1 v1 — 2026-09-30 (FROZEN)

La espera preclaim queda enmendada por [elegibilidad monotónica preclaim](contrato-elegibilidad-preclaim-b3-c4-w1-v1.md).
Antes de READY se conservan 8 s / cap 25 s; después del vencimiento, inbound
ordinario anterior al claim se incorpora elegible al mismo conjunto. El claim
sigue congelando membership/TurnContext/anchor/cursor, con continuación B3
para input posterior. READY no concede autoridad ni capacidad. Los recibos
históricos y gates productivos cerrados conservan su estado.
