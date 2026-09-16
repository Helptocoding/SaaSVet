# Contrato B4 — sender durable e incertidumbre externa

Fecha: 2026-09-16. Base exacta: `5ae6077ab62432864c4563921d3305b76dad5529`.
Alcance exclusivo B4/C5 del [plan canónico](plan-implementacion-auditoria-agente-whatsapp-2026-09md).
B0 mantiene WRITE autónomo cerrado y activación `PENDING_ACTIVATION_REQUIREMENTS`.
No se implementan B5–B9, E1–E5 ni P-A/P-B.

## Autoridades y datos

`channels.Message` sigue siendo el outbox. No hay tabla de intentos/jobs/proveedor.
`TurnWork.lease_token` autoriza procesamiento local B3; `Message.send_token` es
un UUID aleatorio distinto por claim de envío. No hay generación secundaria ni
worker ID como autoridad. `Conversation.ownership_epoch` sigue cercando nuevos
dispatches; completar un envío no modifica autoridad conversacional.

Migración aditiva `channels.0013_b4_durable_sender`: `send_token`,
`send_started_at`, `send_lease_until`, `send_admitted_at`, `provider_accepted_at`,
`delivered_at`, `read_at`, `uncertain_at`, `supersedes_message`. Todos nullable,
sin backfill de evidencia. Se reutilizan `status`, `external_message_id`,
`attempts`, `next_attempt_at` y `failure_reason` (código diagnóstico seguro).
No se crean `sent_at` ni otro ID de proveedor.

`send_admitted_at` es la única ampliación respecto de la lista C5: distingue
durablemente claim de admisión, permite probar SEND-FI-01 y evita consumir dos
veces el mismo claim. No sustituye al token ni acredita recepción en la red.
Tres checks exigen evidencia para SENDING/UNCERTAIN/admisión. Tres índices
cubren pendientes/retry, leases SENDING y correlación org/cuenta/wamid. La
unicidad inbound/B3 y los guards de scope previos se conservan.

## Lifecycle

| Estado | Evidencia / siguiente paso |
| --- | --- |
| PENDING | Publicación local lista; puede reclamarla un sender |
| SENDING | Claim durable; no significa aceptación externa |
| SENT | Aceptación parseada con wamid válido o webhook sent correlacionado |
| DELIVERED | Webhook compatible de entrega |
| READ | Webhook compatible de lectura |
| FAILED | Fallo anterior al HTTP o rechazo conocido del intento; no incertidumbre |
| UNCERTAIN | No se puede demostrar aceptación ni ausencia de aceptación; revisión |
| DISCARDED | No elegible para un nuevo dispatch; no implica cancelación remota |

Camino normal `PENDING → SENDING → SENT → DELIVERED → READ`.
Única vuelta automática a PENDING: rechazo temporal explícitamente seguro,
token/lease vigentes, epoch actual y presupuesto de intentos disponible.
Nunca `UNCERTAIN → PENDING`, ni aceptación conocida → retry. Un fallo de delivery
posterior conserva SENT/DELIVERED/READ y añade diagnóstico; no borra aceptación.
Entrega, lectura y aceptación no prueban éxito de TurnWork, efecto de negocio ni
atención humana. I11 significa **incierto no equivale a no enviado**.

## Claim, admisión y finalización

Implementación en `agent/sender.py`, importada por `worker.py` para compatibilidad.
Orden de locks: **Conversation → Message**; los cambios de ownership B3 conservan
Conversation → TurnWork → Message. El sondeo global solo descubre IDs; cada
claim/finalización transporta org y cuenta y valida relaciones completas.

1. Transacción corta de claim individual: PENDING elegible, retry vencido,
   scope/cuenta activa/epoch/correlación B3 válidos y ventana de 24 horas.
   Se escribe SENDING, UUID, inicio, lease de **120 s**, attempts+1 y commit.
   `SKIP LOCKED` evita esperar otro claim; la exclusión no depende de un batch.
2. Transacción corta de admisión: verifica otra vez token, SENDING, lease no
   vencido, epoch, scope y ventana. Escribe `send_admitted_at` una sola vez y
   commit. Si takeover ganó antes, descarta y no llama al proveedor.
3. HTTP fuera de transacción. La entrada del sender rechaza invocaciones bajo
   `connection.in_atomic_block`. `requests.post(timeout=15, allow_redirects=False)`;
   sin retry de transporte. El timeout de requests no es un deadline total ante
   un servidor que transmita continuamente; el lease no autoriza otro envío.
4. Transacción corta de finalización, scope y CAS por ID/token/admisión/estado.
   Un resultado del intento admitido puede registrarse después del cambio de
   epoch o de la expiración. Nunca devuelve autoridad al bot. Un token distinto
   no puede finalizar. Evidencia superior llegada por webhook no se degrada.
   Error de DB deja SENDING durable; no vuelve a llamar HTTP.

La admisión COMMIT es el **inicio lógico** de §B4.6 del plan. Hay una separación
inevitable entre ese commit y la llamada de socket: no se afirma atomicidad
DB/HTTP. Si un proceso muere allí, queda incertidumbre conservadora. Takeover
posterior a la admisión no revoca ese intento aunque el socket aún no haya
empezado físicamente. No se mantienen locks esperando Meta ni se promete retirar
un request remoto. La prueba de progreso concurrente mantiene HTTP bloqueado
mientras otra conexión confirma takeover antes de liberar la barrera.

## Resultado de Meta y retry

`channels.providers.SendResult` es un valor inmutable acotado, distinto del
`TransportResponse`/`ToolOutcome` B2. Contiene kind, provider_id, code y retryable.

- **accepted**: 2xx, objeto JSON, exactamente un objeto messages con ID string
  `wamid.` no vacío, formato compatible y longitud hasta 128, sin objeto error.
  El ID y provider_accepted_at se persisten juntos bajo CAS. No se asigna delivery.
- **known_rejected**: credencial ausente antes de POST; o 4xx (excepto 408) con
  error Meta explícito de código 10, 100, 190, 200, 130429 o 131047, sin evidencia
  de messages. Lista cerrada para permiso/argumentos/autenticación/ventana/límite.
- **uncertain**: timeout incluido ConnectTimeout, desconexión, excepción legacy
  aunque `retryable=True`, 5xx incluso con error JSON, redirección, 4xx no
  clasificable, JSON inválido, shape inválido, 2xx sin wamid y resultado inválido.
  Los errores no exportan respuesta cruda, texto, teléfono ni credencial.

Solo `meta_130429` admite retry automático: máximo **5 claims**, esperas
**30/60/120/240 s**, fórmula con cap **1 h**. No se sigue ciegamente 429 ni
`retryable=True` de una excepción. La finalización no programa retry si el lease
expiró, hubo takeover o la recuperación ya registró UNCERTAIN. Fallos conocidos
restantes terminan FAILED. No hay scheduler B9.

Referencia de shape: colección oficial de Meta,
[Send Text Message](https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api?entity=request-13382743-93917ea7-098d-45cc-85cc-f5d3500dd1f8).
La lista conservadora se interpreta junto a la
[referencia de errores Meta](https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes/).
La consulta directa de esta última devolvió 429 durante implementación; no se
presenta como validación de llamadas reales. No se cambia la versión API.

## Crash, takeover y recuperación

| Frontera | Resultado |
| --- | --- |
| Takeover con PENDING | B3 descarta bot pending; selector descarta cualquier epoch obsoleto |
| Takeover tras claim sin admisión | DISCARDED, token histórico conservado, cero HTTP |
| Takeover tras admisión / durante HTTP | Conserva SENDING; resultado aceptado→SENT, incierto→UNCERTAIN, rechazado→FAILED |
| Crash tras claim sin admisión | Lease expirado→UNCERTAIN con `lease_expired_before_admission`; se sabe que no hubo admisión, sin replay |
| Crash después de admisión/aceptación sin resultado durable | Lease expirado→UNCERTAIN con `lease_expired_after_admission`; sin replay |
| Respuesta tardía del mismo token | Puede registrar aceptación probada, preservando uncertain_at |

El polling sender recupera de forma limitada SENDING vencidos; nunca los reclama
como PENDING. UUID, tiempos e ID ya conocido se conservan. UNCERTAIN queda fuera
del selector normal. La ausencia de wamid persistido tras crash puede impedir
definitivamente correlacionar un webhook: no se inventa matching por texto/hora/
teléfono ni se consulta Meta para buscar un mensaje perdido.

## Webhook monotónico y reconciliación

Se preserva HMAC del body crudo y el resolutor cuenta→org. Se ignoran estructuras
malformadas; estados desconocidos y IDs sin match quedan observables. Búsqueda
por **org + cuenta + wamid + dirección outbound**, exactamente una fila. Duplicados
históricos del ID no se resuelven escogiendo el primero. Se bloquea Conversation
y Message, se revalida scope y se usa `channels.delivery.apply_evidence`.

Rank `SENT < DELIVERED < READ`; nunca degradar por orden de llegada. Cada timestamp
es la **primera observación local** de ese evento y no cambia por duplicados.
READ puede llegar antes de DELIVERED: el estado sigue READ; una observación
posterior de DELIVERED llena solo su timestamp ausente. No se fabrica timestamp
de etapas que no se observaron. Un `sent` tardío puede añadir su propio tiempo
sin modificar READ. No se añade tabla de receipts ni efectos duplicados.

UNCERTAIN con wamid exacto puede avanzar directamente a SENT/DELIVERED/READ;
conserva uncertain_at y causa histórica. Si el adaptador tiene un ID parcial
seguro lo conserva; sin ID exacto queda para revisión. PENDING y DISCARDED no se
resucitan por webhook: los intentos admitidos no se descartan por takeover.
Legacy orphan con cuenta/org/wamid exactos puede recibir status sin inventar
conversación ni un nuevo dispatch.

## Reemisión y operación

`sender.reemit_uncertain(message_id, actor=..., reason=..., idempotency_key=...)`
exige operador activo del tenant, no service account y permisos existentes
`agentinbox.send`/`agentinbox.claim`. Revalida bajo Conversation. Solo UNCERTAIN,
con conversación abierta; crea **otro Message humano** con epoch nuevo, FK
supersedes, actor, motivo y clave idempotente existentes. Original intacto.
No copia TurnWork ni clave semántica de operación. El sender vuelve a validar
ventana/epoch. Servicio operativo, sin UI nueva de reemisión.

Inbox usa selector operacional separado del selector de emisión/contexto B1.
Muestra PENDING/SENDING/SENT/DELIVERED/READ/FAILED/UNCERTAIN/DISCARDED; expone tiempos
y `acceptance_known`, nunca send_token. SENT histórico sin ID conserva estado y
se muestra sin evidencia de aceptación. No convierte ese estado en autorización.

Logs JSON: pending age al claim, dispatch latency, sending age al expirar,
acceptance latency, delivery/read latency cuando hay fecha de aceptación real,
fallo/incertidumbre, conflictos, fencing/discard y webhook desconocido/unmatched.
Snapshot por estado con counts/edades, incluido uncertain age, cada 60 ciclos;
también `manage.py inspect_agent_outbound`, solo lectura. Sin IDs de tenant,
conversación, Message o wamid como labels; IDs internos solo contexto de logs.

`run_agent_worker --mode planner|sender|both`, default both compatible. Compose
separa worker planner y sender, misma imagen, 256 MiB por proceso. Batch CLI
1..50, sender hasta 100 candidatos por ciclo, poll 0.1..60 s, default 2 s y pausa
también con actividad. Deadman sender separado; sin broker ni cuotas nuevas.

## Legacy y límites

PENDING sin epoch sigue `legacy_unverified`/DISCARDED, sin replay. SENT con ID
conserva aceptación histórica y timestamps NULL; SENT sin ID sigue desconocido.
DELIVERED/READ históricos se conservan sin inventar tiempos. No había SENDING
pre-B4. Cutover inspecciona además PENDING que el sender viejo pudo haber enviado
y cuyo rollback ocultó el intento; los dudosos se ponen en cuarentena UNCERTAIN.

Garantías: claim local exclusivo, no blind retry, aceptación demostrada cuando
existe evidencia y status monotónico con reconciliación conservadora. No se
garantiza entrega exactamente una vez ni ausencia de duplicados externos.
Una reemisión humana de UNCERTAIN puede duplicar un mensaje aceptado previamente.
H07 se evalúa solo para esta frontera. H08 conserva pendientes B5/B8; H16/H19
reciben mediciones y separación, sin gates/carga B9. [Deploy/rollback](runbooks/agent-whatsapp.md#b4-cutover-controlado-y-rollback).
