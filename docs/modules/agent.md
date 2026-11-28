# Módulos: agent + channels (subsistema del agente conversacional)

> **Inbox, fase 3 local — 22-10-2026:** RPL-07 y MED-01..05 implementadas;
> 170 pruebas PostgreSQL y 257 frontend únicas PASS. M4 temporal, proxy por clínica y worker
> privado con expiración a 180 días. [Evidencia](../evals/inbox-phase3-2026-10-22/README.md)
> y [contrato/operación](../runbooks/inbox-media.md). Producción y gates reales
> pendientes; no cambia el FAIL B9 ni habilita WRITE. Los cortes inferiores son históricos.

> **Estado consolidado — 2026-10-11:** [acta B9](../evals/b9-consolidation-2026-10-11/ACTA.md). B9A–D COMPLETED técnico; PROFILE 02-10 PASS para `0831046`; expediente B9E consolidado, sin inferir aceptación integral nueva del HEAD instrumentado. E4 CLOSED por límite confirmado; D29 cerrado con R1-04 PENDING aceptado y cero intentos adicionales. H16/H19 conservan límites de cobertura/carga; activación PENDING_ACTIVATION_REQUIREMENTS. Los cortes inferiores son históricos. Esta consolidación sólo organiza evidencia y Git; no cambia APIs, estados runtime, permisos, contratos ni el alcance UX de Inbox.

> **Frontera vigente B4 (2026-09-16):** Message incorpora claim, admisión y
> aceptación externa; HTTP fuera de transacción e incertidumbre sin replay.
> Inbox expone todos los estados outbound. La sección B4 al final y el
> [contrato sender](../contrato-sender-durable-b4.md) sustituyen las referencias
> históricas siguientes al sender pendiente. WRITE continúa cerrado.

> **Corte B3 (2026-09-15):** TurnWork fija miembros/cursor y recupera el mismo
> trabajo mediante lease UUID con reloj DB. OwnershipWitness y epoch monotónico
> cercan las mutaciones locales; goals/diagnóstico/outbound final/completion se
> publican en una transacción corta. Inbound sigue PENDING al claim. Nuevo input
> termina W1 como deferred, sin reiniciarlo. Sender actual comprueba epoch y
> descarta legacy ambiguo como legacy_unverified. B4 externo sigue pendiente;
> WRITE cerrado y activación PENDING_ACTIVATION_REQUIREMENTS. Contrato vigente:
> [B3](../contrato-trabajo-durable-b3.md); [acta](../implementacion-b3-agente-whatsapp-2026-09-15.md).

> **Corte B2 (2026-09-14):** `TransportResponse` separa HTTP/parseo de negocio;
> `ToolOutcome` C3 contiene READ/EFFECT/ERROR y completitud explícita. Los
> resultados sensibles se renderizan de forma determinista, desde campos
> validados y scope compatible con el `TurnContext` B1. Manifiesto estático
> READ_PUBLIC/READ_PERSONAL/WRITE_BUSINESS/CONTROL; público sin onboarding,
> personal con vínculo vigente y WRITE todavía bloqueado por B0. La evidencia
> local de handoff solo acredita solicitud registrada. Contratos, endpoints,
> compatibilidad de `ok`, diagnóstico y límites:
> [B2](../contrato-resultados-tools-b2.md). Activación continúa en
> **PENDING_ACTIVATION_REQUIREMENTS**; no se implementan fases posteriores.

> **Corte B1 (2026-09-14):** evidencia única del turno implementada sobre B0. `channels.events` normaliza texto/caption, tipo real y referencias explícitas en `_channel_event` v1; `agent.turn_context` congela eventos/IDs/cursor/reloj sin ORM ni persistencia adicional. Worker, policy, planner, prompts y wrapper del arbiter comparten C1. El historial usa cursor exclusivo y emisión, con los permisos de identidad existentes. La limitación de media sin comprensión binaria sigue explícita. No se habilitan escrituras ni consentimiento. Activación: **PENDING_ACTIVATION_REQUIREMENTS**. Contrato y pruebas: [acta B1](../implementacion-b1-agente-whatsapp-2026-09-14.md).

> **Estado**: É-F3 y É-F4 completas (gobernanza conversacional: interrupciones,
> suspender-no-destruir + `TurnDecision`, autoría de salientes, ventana por
> turnos, árbitro + compromiso unificado
> [ADR p55](../decisions/2026-07-30-p55-turn-authority-and-commitments.md), y
> guards de conducta). É-F5 con Fases 0-5 implementadas.
> **Continuidad e identidad (ADR p58) completa y en producción** desde el
> 2026-08-17: el bypass de verificación cerrado, el contexto leído por contacto
> y la bandeja agrupada por persona. **WhatsApp Inbox v1, corte 2026-08-23**:
> Fase 0 y los primeros cortes de Fase 1 implementados (idempotencia de envío,
> pendientes humanos visibles, tiempo por TZ de la clínica, separadores,
> estados de entrega y envío optimista). La suite integral de `apps.agent` del
> corte cerró con 769 tests (`skipped=1`); la evidencia posterior y los gates
> aún abiertos viven en el plan p60.
> Ver [`whatsapp-agent-f4-gobernanza-plan.md`](../whatsapp-agent-f4-gobernanza-plan.md).
>
> Contratos: [`whatsapp-agent-epics.md`](../whatsapp-agent-epics.md) (registro de
> épicas) · [`whatsapp-agent-functional-spec.md`](../whatsapp-agent-functional-spec.md)
> (spec funcional + enmienda É-F3) · [`whatsapp-agent-epica-f3-conversacion-por-objetivos.md`](../whatsapp-agent-epica-f3-conversacion-por-objetivos.md)
> (plan de remediación) · [`whatsapp-agent-auditoria-conversacional-2026-07-24.md`](../whatsapp-agent-auditoria-conversacional-2026-07-24.md)
> (auditoría que lo originó).
>
> ADRs: **p51** identidad del actor · **p52** idempotencia de citas · **p53**
> configuración de clínica · **p54** objetivos + conservación vinculante ·
> **[p55](../decisions/2026-07-30-p55-turn-authority-and-commitments.md)**
> autoridad del turno + compromisos (ACEPTADO e implementado; se escribió
> ANTES del código, que es lo que lo hizo servir de brújula) ·
> **[p56](../decisions/2026-08-01-p56-perception-situation-and-turn-as-root.md)**
> percepción, situación y el turno como unidad de razonamiento (ACEPTADO
> 2026-08-01) ·
> **[p58](../decisions/2026-08-17-p58-continuidad-e-identidad-del-agente.md)**
> continuidad conversacional e identidad (ACEPTADO 2026-08-16, **implementado y
> en producción**): el nombre del titular deja de verificar, la autoridad sobre
> la prueba es del servidor, y el contexto pasa a leerse por contacto ·
> **[p59](../decisions/2026-08-17-p59-interpretacion-al-modelo.md)** la
> interpretación vuelve al modelo (ACEPTADO 2026-08-17): **enmienda p58 §2** —
> el servidor conserva la autorización (procedencia, anti-eco, TTL) y suelta la
> comprensión del lenguaje, que era lo único que en producción rechazó a un
> cliente legítimo ·
> **[p60](../decisions/2026-08-22-p60-whatsapp-inbox-decisions.md)** decisiones
> operativas del Inbox v1 (ACEPTADO 2026-08-22; ejecución incremental en el
> [plan del Inbox](../plan-implementacion-whatsapp-inbox-2026-08-22.md)).
>
> Rediseño en curso: [auditoría de arquitectura](../whatsapp-agent-auditoria-arquitectura-2026-07-31.md)
> → [plan É-F5](../whatsapp-agent-f5-conversacion-plan.md). **Fase 0 hecha**
> (corpus de regresión + línea base); Fase 1 arranca con p56 ya aceptado.
>
> **Continuidad e identidad (p58)**: plan de implementación con las catorce
> revisiones y el motivo de cada decisión en
> [`agent-continuity-plan.md`](../agent-continuity-plan.md). Se lee cuando la
> pregunta es «¿por qué está hecho así?» — el ADR da la regla, el plan da el
> camino y las alternativas que se descartaron.
>
> Runbook operativo: [`runbooks/agent-whatsapp.md`](../runbooks/agent-whatsapp.md).

## Inbox: envío API y proyección de citas (WA-RPL-03, 2026-10-21)

`POST /api/inbox/conversations/{uuid}/send/` admite `reply_to_id` opcional, entero
positivo de 64 bits. Exige `agentinbox.send`. Tras resolver el recurso y el replay
idempotente, valida el destino de la misma clínica/persona/cuenta bajo el lock de
Conversation y del mensaje citado. Destino ajeno o inexistente: 400 con
`code: invalid_reply_target`, antes de takeover/outbox. Recurso de otra clínica:
404 incluso con una clave previa. Los errores de forma conservan la validación DRF.

La clave idempotente conserva cuerpo y cita originales, incluso si el nuevo POST
cambia la cita o llega después del cierre. Retry conserva la misma FK y autor.
Se admite historia de otros episodios y destinos ocultos/fallidos/descartados/media.

`MessageSerializer.reply_to` devuelve null o un nivel `{id, author_type,
human_author_name, payload_type, excerpt, status}`. Excerpt contiene como máximo
80 caracteres del cuerpo, incluido vacío. No expande citas de citas. Una FK legada
de otro hilo/clínica se proyecta como null; nombres de autores de otra clínica
quedan nulos. La respuesta POST se relee para reflejar si el takeover descartó
el destino pendiente del agente.

Transcript reciente, `before`, `around`, delta, episodio legado, replay y retry
cargan `reply_to__human_author` junto con los mensajes. El fingerprint del delta
incluye campos de la cita y solo los primeros 80 caracteres del destino: cambios
de excerpt/status/autor actualizan el mensaje que cita, aunque el destino esté
fuera de página y su propio updated_at no cambie. Una edición posterior al excerpt
no modifica la proyección del padre. El delta estable conserva mensajes vacíos.

Sin migración nueva ni cambios de frontend. La relación/API no acredita cita
nativa enviada a WhatsApp: el adaptador actual aún despacha solo texto; ese enlace
al proveedor debe implementarse al cerrar la cadena replies, además de su gate
Meta real. Composer, salto y bloques visuales siguen en RPL-05/06/04.
[Evidencia RPL-03](../evals/inbox-rpl-03-2026-10-21/README.md).

## Inbox: citas entrantes desde webhook (WA-RPL-02, 2026-10-21)

El webhook firmado reutiliza `ChannelEvent.reply_to_id`, el `context.id` normalizado
de B1. `provider_reply_target` busca un destino único por ID externo dentro de la
organización y cuenta receptoras, en cualquier dirección e incluyendo historia
oculta. Dos filas candidatas o ID ausente/inválido/largo no se convierten en cita.
El ID se compara completo, sin truncar ni convertir objetos a texto.

`ingest_inbound_message(..., reply_to=None)` admite un Message opcional. Después
del precheck dedup y bajo el lock de Conversation vuelve a resolver clínica,
contacto y cuenta mediante `resolve_reply_target(lock=True)`. El lock de destino
se conserva hasta persistir el entrante. Un destino desaparecido o fuera de scope
deja `reply_to=None`; el entrante se conserva. Se admiten citas entre episodios,
entrantes/salientes, fallidos/descartados/pendientes y media sin interpretar binarios.

Si un entrante nuevo declara referencia y queda sin relación, registra WARNING
`INBOUND_REPLY_UNRESOLVED`: UUID de clínica/cuenta, ID interno del entrante y motivo
genérico. Sin body, teléfono, ID externo o nombre. La redelivery no cambia la cita,
no hace backfill cuando llega tarde el destino ni repite ese aviso.

La proyección B1 mantiene el ID externo original; `Message.reply_to_id` es la FK
interna para Inbox. El selector del agente `referenced_message` conserva sus límites
de episodio, cursor y emisión: la relación Inbox no autoriza operaciones ni convierte
un mensaje pendiente/descartado en evidencia emitida.

Sin nueva migración; requiere M2 al aplicar el conjunto de cambios. M2/M3 siguen
sin aplicar a las bases habituales/preview. API/serializer/UI siguen en RPL-03..07.
[Evidencia RPL-02](../evals/inbox-rpl-02-2026-10-21/README.md).

## Inbox: modelo de respuestas citadas (WA-RPL-01, 2026-10-21)

`channels.Message.reply_to` es FK opcional a Message con `PROTECT` y reverse
`direct_replies`. El destino se conserva frente a borrado físico. Un índice
explícito `message_reply_target` sobre `reply_to_id` sustituye al automático de
FK (`db_index=False`) para no duplicarlo. La migración
`channels.0016_message_reply_to` (M2) añade columna nullable/FK/índice, sin backfill
ni default. Los mensajes previos quedan sin cita y el writer anterior sigue válido.

`channels.replies.resolve_reply_target` valida organización, contacto y cuenta
del destino. El `clean()` de Message lo usa cuando existe cita; `save()` normal
hereda `full_clean()` de OrganizationalModel. Se permite cruzar episodios de la
misma persona/cuenta. Incluye historia oculta/descartada: ocultar el destino no
debe romper un reply persistido. Target inválido devuelve ValidationError del
campo `reply_to` con código `invalid_reply_target`, sin contenido del mensaje.

La FK de DB asegura existencia; el scope de clínica/hilo lo comprueba la aplicación.
`save(validate=False)` y operaciones bulk/directas conservan el bypass explícito
del modelo base y deben validar antes de persistir. Esto está acreditado con dos
organizaciones: el servicio/save normal rechazan el cruce, la FK sola no lo hace.

M2 se ensayó con modelos históricos, comparando todas las columnas anteriores y
lectura/escritura de ambas versiones. Sin aplicar a las bases habitual/preview.
La conexión webhook/ingesta sigue en RPL-02 y API/UI en RPL-03..07.
[Evidencia RPL-01](../evals/inbox-rpl-01-2026-10-21/README.md).

## Inbox: asignación a compañeros (WA-ASN-01, 2026-10-21)

- `GET /api/inbox/assignable-users/`, permiso `agentinbox.claim`: directorio mínimo
  `{public_id, name}` de personas activas de la clínica con permiso DB
  `agentinbox.send` (incluye wildcards y superuser; sin fallback de rol histórico).
  Excluye service accounts y ADMIN_SAAS. Una consulta de usuarios, sin N+1.
  No amplía `staff.list` ni expone correos u otros datos del equipo.
- `POST /api/inbox/conversations/{uuid}/assign/`, mismo permiso, body
  `{user_public_id: UUID}`. La ruta exige UUID aun si el resolver general permite
  IDs antiguos. Conversación/objetivo ajenos o inexistentes: 404. Payload inválido,
  objetivo inactivo/sin permiso/no humano o conversación cerrada: 400.
- Bajo el mismo lock de Conversation de claim/close/release, revalida el objetivo
  con `user_has_permission_strict`, bloquea su fila y cambia a `human_active`.
  Permite reasignar desde otro empleado, asignarse a sí mismo y múltiples casos.
  Una repetición al mismo objetivo ya activo no cambia epoch, timestamps ni auditoría.
- Una transferencia real ejecuta `invalidate_ownership(reason='staff_assignment')`:
  invalida autoridad vieja y conserva las garantías de outbound B4. No envía un
  mensaje, marca lectura ni inventa acuse/notificación. El handoff mantiene su
  acuse histórico; asignar no afirma que el nuevo responsable haya acusado recibo.
- Tras commit registra `INBOX_CONVERSATION_ASSIGNED`, con UUID de clínica,
  conversación, actor, origen/destino y fecha. Sin nombres, teléfono, correo ni cuerpo;
  rollback no emite ese evento. El tracking existente alimenta lista/transcript delta.

Sin migración nueva ni activación. [Evidencia ASN-01](../evals/inbox-asn-01-2026-10-21/README.md).

## Inbox: búsqueda de contactos (WA-SRCH-01, 2026-10-21)

`GET /api/inbox/threads/?q=<texto>` requiere el mismo `agentinbox.view`. Recorta
espacios e ignora consultas de menos de dos caracteres. Aplica OR con `icontains`
sobre `contact.display_name`, `contact.external_id` y el nombre del cliente
vinculado de la misma organización. Para teléfono reutiliza `phone_digits` y
`normalize_wa_id`: los fragmentos conservan sus dígitos; un número MX completo
con 52/521 se compara con los diez dígitos canónicos. El identificador externo
también se compara con los dígitos originales. No añade condiciones telefónicas
vacías ni de un solo dígito que puedan ampliar accidentalmente la búsqueda.

La búsqueda no consulta cuerpos de mensaje ni usa el teléfono del cliente para
descubrir vínculos. Se combina con los segmentos mediante AND, conserva archivo,
agrupación y orden y se aplica antes de offset/cap. Se usan valores parametrizados
del ORM; comillas y metacaracteres LIKE son literales. El total personal de no
leídos permanece independiente de la búsqueda.

La consulta efectiva forma parte del scope de cursor. Cambiar `q` exige un full;
espacios de borde y consultas cortas equivalen al mismo filtro efectivo.
Renombrar un contacto puede retirarlo del delta de búsqueda. Sin nueva migración.
[Evidencia SRCH-01](../evals/inbox-srch-01-2026-10-21/README.md).

## Inbox: filtros de lista (WA-FIL-01, 2026-10-21)

`GET /api/inbox/threads/` conserva `agentinbox.view`, agrupación y paginación;
acepta filtros combinables AND, aplicados en SQL después de elegir la cabecera
del hilo y antes de paginar:

- `unanswered=1`: último mensaje operativo visible entrante, según la semántica
  existente de `has_unanswered`. `unanswered=0`: último operativo saliente
  («Esperando cliente»); los hilos sin mensajes quedan fuera de ambos segmentos.
- `urgent=1`: handoff no resuelto urgente del episodio abierto vigente.
  `urgent=0` desactiva este filtro; no significa «solo normales».
- `claimed=me|<user_public_id>`: responsable del episodio abierto vigente,
  limitado a la organización del solicitante. Un UUID de otra clínica devuelve
  200 vacío; no permite conocer si existe aquel usuario.

Los booleanos también aceptan `true`/`false`. Valores inválidos devuelven
`400 {code:'invalid_filter',error}`. `archived=1` conserva su contrato previo:
incluye hilos cerrados además de los abiertos. Un claim o handoff histórico de
una sesión cerrada no la convierte en sesión vigente ni califica como urgente/mía.
Un conjunto sin coincidencias devuelve 200 con `results:[]`, sin siguiente página.

Cada cursor incluye los filtros efectivos normalizados además de org/usuario,
archivo y offset. `claimed=me` y el UUID propio comparten scope; reutilizar un
cursor en otro segmento devuelve `invalid_sync_cursor`. El delta retira el hilo
que deja de cumplir el filtro. `unread_total` sigue siendo el total personal de
las conversaciones activas, independiente del segmento; filtrar no marca leído,
responde, toma ni reasigna una conversación. No hay cambios de schema.
[Evidencia FIL-01](../evals/inbox-fil-01-2026-10-21/README.md).

## Inbox: sincronización incremental (WA-PERF-03, 2026-10-21)

Los GET completos de lista y transcript reciente conservan sus campos y añaden
`mode='full'`, `sync_cursor: string|null`. El transcript también publica
`sync_floor`, límite firmado del rango leído; las páginas `before`/`around`
publican ese límite pero no un cursor delta. Permiso: `agentinbox.view`.

`GET /api/inbox/threads/?since=<sync_cursor>&archived=&offset=` devuelve
`{mode:'delta',sync_cursor,upserts:Thread[],removals:string[],unread_total,has_more,next_offset}`.
La clave de hilo es `contact_public_id:channel_account_public_id`. `order` aparece
solo si cambia el orden/pertenencia de la página y enumera sus claves completas.
Los cambios de mensaje, responsable, handoff, lectura, archivo y lease se reflejan
si modifican la proyección pública. No se envían filas cuyo JSON siga idéntico.

`GET /api/inbox/threads/{c}/{a}/messages/?since=<sync_cursor>&floor=<sync_floor>`
devuelve `{mode:'delta',sync_cursor,messages:Message[],removals:number[],metadata:{...}}`.
Incluye mensajes nuevos y modificaciones de filas existentes, incluidos ticks,
fallos y reintentos; `metadata` es vacío cuando no cambió la cabecera/lectura.
Al ampliar el historial añade `range_ids`, todos los IDs visibles de ese rango,
para retirar filas desaparecidas durante el GET anterior. No mezcla `since` con
`before`/`around`. `floor` se obtiene del servidor, sin reloj del cliente, y sigue
resolviendo el límite aunque se elimine físicamente su fila.

Cursor firmado y ligado a organización, usuario, recurso y filtros/offset.
Expira a los diez minutos; firma/scope incorrectos, pérdida de snapshot o mezcla
de cursores → `400 {code:'invalid_sync_cursor',message}` mediante el handler estándar.
La UI recupera con GET completo y conserva `floor`. Ese full devuelve el rango
cargado y `reset_range=true` para reconciliar retiradas sin dejar huecos en ráfagas
de más de 50 mensajes. Si el caché no puede guardar el snapshot, full funciona con
cursor null; delta sigue disponible tras recuperar el caché.

`inbox_sync` usa el caché default existente para snapshots inmutables de hashes,
IDs, orden y watermarks `(updated_at,id)`, sin cuerpos, nombres ni teléfonos.
No almacena autoridad de negocio. Compara pertenencia/fingerprints además del
watermark: detecta timestamps iguales, commits tardíos dentro del rango cargado,
retiradas y expiraciones sin escritura. SQL calcula hashes del rango leído;
materializa cuerpos solo si cambiaron. El preview usa Substr de 120 caracteres y
el contrato `latest_messages` existente del serializer.

`TimestampedQuerySet`/`OrganizationalModel.save` mantienen updated_at solo en los
cinco modelos opt-in: Message, Conversation, ContactIdentity, HumanHandoff e
InboxReadState. Cubre update atómico, bulk_update y save parcial, también con
all_objects, preservando sus filtros, validación, locks y default manager. No
cambia reglas de envío/entrega/ownership ni opta por otros dominios.

El coste SQL es proporcional a la página/rango cargados. Con 6.001 mensajes y
50 cargados, JSON sin compresión pasa de 52.002 a 303 bytes en poll estable;
EXPLAIN usa el índice existente de organización/contacto/cuenta/created_at para
50 filas. No se añade índice ni migración; M3 sigue sin aplicar a la base de trabajo.
[Decisión técnica](../decisions/2026-10-21-p60-perf03-cursors.md) y
[evidencia PERF-03](../evals/inbox-perf-03-2026-10-21/README.md).

## Inbox: contexto mínimo del cliente (WA-CTX-01, 2026-10-21)

`GET /api/inbox/threads/{contact_public_id}/{account_public_id}/context/`
requiere `agentinbox.view` y devuelve exactamente:

```json
{
  "owner": {"public_id": "uuid", "name": "Cliente", "phone": "5551234567"},
  "pets": [{"public_id": "uuid", "name": "Mascota", "species": "Perro"}],
  "last_appointment": {"date": "2026-10-20", "status": "canceled"}
}
```

Sin cliente vinculado: `owner=null`, `pets=[]`, `last_appointment=null`.
Sin citas anteriores: `last_appointment=null`. No busca coincidencias por teléfono
ni modifica identidad, conversación, mensajes o lectura. Funciona también con
hilos archivados. Ruta inexistente, par contacto/cuenta sin hilo o cliente
vinculado fuera de la clínica/inactivo/genérico → 404. VET tiene acceso de lectura;
AGENT recibe 403. Cada consulta usa la organización del caller.

`inbox_context.thread_context` es una proyección de lectura para la API del staff
autorizada por WA-CTX-01/D-8; no es una herramienta del agente ni amplía los
contratos HTTP de su ejecución autónoma. Reutiliza los serializers públicos de
patients con campos restringidos. Mascotas activas y no genéricas del cliente,
ordenadas por nombre/PK; las citas también se limitan a esas mascotas y clínica.
No publica PK internos, notas, motivo de cita, historia clínica ni datos de catálogo.

«Última cita» significa la más reciente cuya hora programada ya llegó; excluye
citas futuras y conserva su estado real, incluidas cancelada/no asistió. Usa
`start_datetime` UTC; filas legacy sin él se comparan con fecha/hora local de la
clínica. Ordena por fecha, hora y PK descendentes. No implica consulta completada.
El presupuesto medido es seis consultas de dominio tanto con una como con 36
mascotas, sin consultas por mascota. No añade migración ni aplica M3.
[Evidencia CTX-01](../evals/inbox-ctx-01-2026-10-21/README.md).

## Inbox: ventana de sesión visible (WA-WIN-01, 2026-10-21)

`ConversationListSerializer` añade dos proyecciones read-only a `conversation`
en el transcript del hilo y en el endpoint legacy del episodio:
`session_window_open: bool` y `session_window_expires_at: ISO8601|null`.
El vencimiento usa la duración B4 existente: `last_inbound_at + 24 horas`
transcurridas, como instante absoluto. No suma un día de calendario de la clínica;
un cambio DST no prolonga/acorta la ventana. Sin último entrante: false/null.
Si el episodio está cerrado: false/null; un hilo archivado conserva conversation=null.

La comparación respeta B4: el instante exacto de vencimiento aún pertenece a la
ventana; después devuelve false. Un vencimiento pasado conserva su timestamp
para la sesión abierta. No se añaden queries por mensaje ni se modifica el reloj,
los guards o el dispatch del sender. El GET no escribe estado de lectura ni conversación.

Un nuevo inbound renueva `last_inbound_at` mediante el servicio de ingesta existente.
Tras archivo crea el episodio vigente por ese mismo flujo; una página histórica
continúa proyectando la ventana del episodio vigente. La UI recibe la renovación
en su siguiente poll o al recuperar visibilidad. Sin migración nueva ni aplicación
de M3 a la base de trabajo. [Evidencia WIN-01](../evals/inbox-win-01-2026-10-21/README.md).

## Inbox: reintento de fallo conocido (WA-RETRY-01, 2026-10-21)

`POST /api/inbox/conversations/{conversation_public_id}/messages/{message_id}/retry/`
requiere `agentinbox.send` y devuelve 200 con el mismo `MessageSerializer`.
`conversation_public_id` es una proyección UUID de solo lectura añadida a cada
mensaje; identifica su episodio original aunque el transcript cruce sesiones.
No acepta otro cuerpo ni autor. La cabecera opcional `X-Idempotency-Key`, si se
envía, debe coincidir con la original; sin cabecera se conserva igualmente la key.

`inbox_retry.retry_failed_message` bloquea Conversation → Message y limita ambas
consultas a la organización del request. Solo permite outbound FAILED sin wamid,
aceptación, entrega, lectura ni incertidumbre histórica. No renueva ownership ni
TurnWork: reutiliza las validaciones B4 de scope, epoch, cuenta y salida autorizada.
Sesión cerrada → 400 `session_closed`; autoridad invalidada/legacy → 400
`retry_not_authorized`; evidencia externa → 400 `external_evidence`; estado distinto
de FAILED o inbound → 400 `message_not_failed`; key distinta → 400
`idempotency_conflict`; mensaje/ruta fuera de scope → 404.

Ventana desconocida o cerrada según reloj DB → 400
`{code: 'window_closed', message, suggestion: 'call'}`. Al admitir: misma fila,
cuerpo, autor, fecha, correlación y epoch; `status=pending`, `attempts=0`,
`next_attempt_at=now`, `failure_reason=''`, con actor y fecha de actualización.
Cualquier staff con send puede reintentar el mensaje de otro autor sin reasignar
la conversación. El evento `INBOX_MESSAGE_RETRY` registra IDs, autor original y
resultado, sin cuerpo ni clave. Dos POST concurrentes realizan una sola transición.

El sender existente vuelve a validar ventana/autoridad y asigna un token nuevo.
Se conserva el claim previo hasta entonces; su finalizador no puede modificar
PENDING ni una reclamación posterior. Acuses permanecen forward-only. UNCERTAIN
no es reenviable por esta ruta: timeout, desconexión y resultado no demostrado
conservan B4 y su reemisión operativa separada. Sin migración nueva ni activación.
[Evidencia local RETRY-01](../evals/inbox-retry-01-2026-10-21/README.md).

## Inbox: identidad de autor para agrupación (WA-GRP-01, 2026-10-20)

`MessageSerializer` añade `human_author_public_id` de sólo lectura: UUID público
del empleado en mensajes salientes `human_staff` con autor; `null` en los demás.
Permite distinguir empleados homónimos sin publicar su PK interno ni agrupar por
nombre. Los queries de transcript ya usan `select_related('human_author')`.
No requiere migración ni cambia envío, estados o idempotencia. Pruebas nuevas
sin base de datos y validación UI: [GRP-01](../evals/inbox-grp-01-2026-10-20/README.md).

## Inbox: indicador de turno (WA-AGT-01, 2026-10-21)

`ThreadSerializer.agent_processing` y `conversation.agent_processing` del
transcript son booleanos de solo lectura: sesión vigente con `processing_until`
posterior a `timezone.now()`. Lease ausente, vencido o exactamente en el límite
devuelve false; una sesión cerrada nunca indica actividad. El timestamp no se
publica. La fila agrupada usa la sesión vigente, sin heredar un turno del historial.

Es una proyección informativa que se actualiza con el polling. TurnWork conserva
la autoridad del turno; no cambia workers, guards, claim/release ni permisos.
Sin migraciones. [Evidencia AGT-01](../evals/inbox-agt-01-2026-10-21/README.md).

## Inbox: consulta agrupada (WA-PERF-01, 2026-10-21)

`list_threads` selecciona en PostgreSQL una cabecera por contacto/cuenta: sesión
abierta más reciente o, al incluir archivados, última cerrada si no hay abierta.
Subconsultas acotadas obtienen número de episodios, último mensaje operacional
del hilo y handoff vigente. El preview se recorta a 120 caracteres en SQL.
Las relaciones de contacto, cliente y empleado se cargan en la misma consulta.

Ordena por urgencia y actividad del mensaje; en empate conserva la actividad
del bucket. PERF-01 aplicó el cap existente antes de materializar como máximo
100 conversaciones y conservó `ThreadSerializer[]`. No carga episodios
históricos ni consulta por cada fila.
[Evidencia PERF-01](../evals/inbox-perf-01-2026-10-21/README.md).

### Paginación de hilos (WA-PERF-02, 2026-10-21)

`GET /api/inbox/threads/?archived=&offset=` devuelve
`{results: ThreadSerializer[], has_more: bool, next_offset: int|null, unread_total: int}`
(el total se añadió en UNR-02, descrito abajo).
Sin offset devuelve la primera página de 100; offset entero no negativo hasta
2147483647, inválido → 400 con `code=invalid_offset`. Al agotarse:
`has_more=false`, `next_offset=null`; fuera del rango de filas, results vacío.
Obtiene como máximo 101 cabeceras para detectar otra página, sin COUNT.
Contacto/cuenta desempatan el orden y PK desempatan sesiones de igual actividad.
La visibilidad operacional, permisos y tenant scoping se conservan.
Es paginación por offset sobre datos vivos, sin snapshot; la UI reconcilia
refrescando todas las páginas cargadas. No hay migraciones.
[Evidencia PERF-02](../evals/inbox-perf-02-2026-10-21/README.md).

### Transcript centrado en un mensaje (WA-HIST-03, 2026-10-21)

`GET /api/inbox/threads/{contact_public_id}/{account_public_id}/messages/?around=<id>`
requiere `agentinbox.view` y conserva los metadatos del transcript, incluida la
sesión vigente aunque el destino pertenezca a una sesión cerrada. Obtiene hasta
25 mensajes operacionales anteriores, el destino y hasta 24 posteriores, en
orden local `(created_at, id)`. En los extremos devuelve menos de 50, sin rellenar
desde el otro lado. `has_older` y `has_newer` indican continuidad; `next_before`
es el id más antiguo de la ventana si quedan anteriores, o null.

Solo el destino puede saltarse el filtro operacional de Inbox. Cada mensaje de
esta respuesta añade `is_hidden`: true únicamente si el destino no sería visible
en el transcript normal; conserva su cuerpo y estado real. Los vecinos siguen
filtrados. Un outbound discarded/failed/uncertain ya es evidencia operacional:
su `is_hidden` es false y su estado no implica entrega. El selector del agente,
el anti-eco y los permisos permanecen iguales.

El destino se busca dentro de la organización, contacto y cuenta de la ruta:
inexistente o ajeno → 404 `{code: 'not_found'}`. `around` debe ser un entero
positivo hasta 9223372036854775807; inválido → 400 `{code: 'invalid_cursor', message}`.
Su presencia junto con `before`, incluso vacío, devuelve ese mismo 400.
Sin `around` se conserva el contrato existente de página reciente/`before`,
sin los campos adicionales. Las ventanas se limitan en SQL con una fila extra
por lado; no cargan el historial completo ni ejecutan COUNT.

No hay migraciones. La UI de salto por citas o búsqueda corresponde a RPL-06/SRCH.
[Evidencia HIST-03](../evals/inbox-hist-03-2026-10-21/README.md).

### Lectura del staff por hilo (WA-UNR-01, 2026-10-21)

`InboxReadState` persiste el marcador por `(organization, user, contact,
channel_account)`, con unicidad en DB e índice `(organization, user, updated_at)`.
Usuario, contacto y cuenta tienen FK PROTECT; el mensaje tiene SET_NULL.
La validación del modelo impide FKs de otra clínica y marcadores salientes o de
otro hilo. El estado es interno: no expone un ID propio en la API.

`GET /api/inbox/threads/` añade `unread_count: int` por fila para el caller.
Cuenta solo entrantes operacionales (`pending`, `processed`, `failed`) de la
sesión vigente con `id > last_read_message_id`. Sin estado o con marcador null,
cuenta todos esos entrantes del episodio vigente. No cuenta discarded, salientes
ni sesiones históricas; hilos archivados devuelven 0. Una consulta agregada para
las cabeceras de la página obtiene los conteos, sin queries por fila ni cargar
mensajes o marcadores como instancias. Se conservan orden, paginación y campos
previos, incluido `has_unanswered`, cuya semántica sigue siendo independiente.

`POST /api/inbox/threads/{contact_public_id}/{account_public_id}/read/`, permiso
`agentinbox.view`, recibe `{last_read_message_id}` y devuelve 200
`{last_read_message_id, unread_count, unread_total}` (total añadido en UNR-02).
Organización y usuario salen del request.
Valida un entero positivo hasta 9223372036854775807 y exige un entrante visible
del mismo hilo; puede pertenecer a otra sesión. Inexistente/ajeno → 404 con
`code=not_found`; saliente/invisible → 400 `invalid_read_message`; body inválido →
400 `invalid_read_request` con errores por campo. Rutas ajenas conservan el 404
normal de la resolución de contacto/cuenta.

El servicio usa transacción, unicidad y bloqueo de fila para serializar el upsert,
incluida la carrera de primera creación. Solo avanza a un id mayor; repetir o
enviar uno anterior conserva marcador y `updated_at`. Registra el actor en los
campos de auditoría. Lecturas de distintos empleados no se limpian entre sí.
No modifica Message, claims, TurnWork ni la autoridad conversacional; tampoco
equivale a un acuse READ del cliente en WhatsApp. Los GET no marcan lectura.

Migración M3: `agent.0029_inbox_read_state`, aditiva y sin backfill. Se requiere
aplicarla al desplegar este código; la validación local usa una base temporal.
El contador/divisor y la llamada automática con foco y debounce pertenecen a
UNR-02. [Evidencia UNR-01](../evals/inbox-unr-01-2026-10-21/README.md).

### Proyecciones de lectura para la interfaz (WA-UNR-02, 2026-10-21)

La lista añade `unread_total`, contador del caller para todos los hilos vigentes,
también los que están fuera de la página solicitada. No suma solo las filas
materializadas. El total usa un COUNT con subconsulta de cabeceras; la página
conserva su agregación por episodio. El presupuesto previo de <=4 consultas y
la ausencia de N+1 se mantienen. Archivados e historial no aportan unread.
El POST read devuelve también este total confirmado.

El transcript añade cuatro metadatos propios del caller: `last_read_message_id`,
`unread_count`, `first_unread_message_id` y `latest_visible_inbound_id`.
Los dos últimos se calculan exclusivamente sobre los entrantes operacionales del
episodio vigente incluidos en la página que se devuelve, en su orden cronológico.
Son null en páginas solo históricas o hilos archivados. El destino automático
siempre pertenece a la página enviada a la UI. Un GET nunca marca lectura.

Estos metadatos evitan que la UI trate el inicio de una sesión cerrada como
mensajes nuevos cuando el marcador propio todavía es null. No hay una nueva
migración: sigue siendo necesaria M3 al incorporar el código.
[Evidencia UNR-02](../evals/inbox-unr-02-2026-10-21/README.md).

## Boundary (vinculante)

`channels` (transporte) y `agent` (núcleo conversacional) son dominios
**FRONTERA**: consumen el resto del sistema solo vía API HTTP autenticada
(desde É-F1, con el JWT del user AGENT) y **ningún módulo de dominio los
importa**. Entre ellos: `channels` referencia `agent.Conversation` por string
ref; `channels.views` importa `agent.services` perezoso.

## Modelos

| Modelo | App | Claves |
|---|---|---|
| `ChannelAccount` | channels | `external_account_id` (phone_number_id) **unique GLOBAL** — el enrutamiento número→org es el control anti cross-tenant (R1); `provider_credentials_ref` = NOMBRE de env var (secreto jamás en DB) |
| `Message` | channels | Tabla ÚNICA in/out. El inbound alimenta TurnWork y el outbox sigue siendo un filtro (`status`); turn_work fija membership, output_ordinal/origin_epoch correlacionan publicación B3. Inbound: unique parcial `(channel_account, external_message_id)` para dedup del wamid. Envíos del staff: `idempotency_key` con unique parcial `(organization, idempotency_key)` **solo** para `direction='out' + author_type='human_staff' + key no nula`; agent/system nunca comparten ese namespace público. `available_at` = ventana silenciosa del debounce (cada entrante empuja la de miembros aún sin trabajo: 8 s, tope 25 s desde el más viejo); `process_attempts` proyecta los intentos de TurnWork (≠ `Message.attempts`, envíos); al agotar retries el trabajo queda FAILED, conserva inbound pending asignado y escala a humano |
| `ContactIdentity` | agent | Identidad POR ORG (`unique org+channel+external_id` — el mismo cliente puede escribir a 2 clínicas); `verification_level` (unknown→phone_match→confirmed_in_chat→staff_verified); `phone_normalized` (Q5: últimos 10 dígitos, México-only); NO es un User — jamás recibe tokens |
| `Conversation` | agent | `PublicIdMixin`; FSM 4 estados: `active → handoff_pending → human_active → closed`; **CLOSED es terminal** (mensaje posterior = hilo nuevo) — pero **el contexto ya no muere con el hilo**: se lee por `(contacto, cuenta)` (F2, §Continuidad); `close_reason` registra por qué se cerró; org fijada al crear e inmutable; `flow` = scratchpad (ADR p50, jamás fuente de verdad); `ownership_epoch` = generación operativa; `processing_until` = proyección legacy sin autoridad. **`summary` se retiró en F5**: declarado en É-F1 y nunca escrito ni leído — la continuidad se resolvió sin él |
| `TurnWork` | agent | Trabajo causal durable: anchor/cursor B1, miembros por Message FK, estado y único lease_token, DB expiry, attempts/backoff, epoch; unicidad parcial de un no terminal por conversación. Completion y outputs finales atómicos; [contrato B3](../contrato-trabajo-durable-b3.md) |
| `ConversationGoal` | agent | **El COMPROMISO** (É-F3 W2; extendido por ADR p55 §3 — un solo modelo para tarea e identidad, R7). Estados `active/deviated/suspended/blocked/completed/abandoned/handoff` (+`cancelled` deprecado); `slots` `{slot:{value,confidence}}` YA normalizado; `missing`, `low_confidence`, `asked`, `stall_turns`; coordenadas `return_to`/`supplanted_by`/`blocked_reason`; `attempts_failed` (fallos reales ≠ turnos sin avance) y `working_state` (estado local del mecanismo). Dos constraints parciales: **uno al frente** (`active|deviated`) y **uno suspendido** por conversación |
| `TurnOperationAssessment` | agent | Decisión append-only de un turno posterior a recibo: `conversation + anchor_message` es única/idempotente; guarda veredicto, operación, fallos, modelos/prompts y la ráfaga fuente como relación ordenada. Un `ConversationGoal` autorizado la referencia; el runtime solo habilita agenda tras autorización+verificación semánticas. |
| `AgentSettings` | agent | OneToOne a Organization (patrón OrganizationSettings): `enabled` (kill switch, default False), `agent_user`, `faq_facts` (solo hechos sin campo propio), `default_veterinarian`, `scheduling_mode`, `nudge_enabled` |
| `TurnDecision` | agent | Rastro **append-only** de cada turno (R12, É-F4 Fase 1). **El runtime NUNCA la lee** — es solo para diagnóstico/regresión. `verdict` (veredicto del árbitro, `TurnDecision.Verdict`: los cinco de `arbiter.VERDICTS`, o vacío si el árbitro lanzó una excepción fuera de B3; orden 8, G07), `because` (enum cerrado ORTOGONAL, ≤12 valores, `TurnDecision.Because`), `active_commitment`/`return_to` (los del compromiso que juzgó el árbitro) y `supplanted_by`, `facts_consumed`/`facts_produced` (JSON, cero PII; la salida del planner va en `facts_produced['salida']`). Las filas anteriores a É-F5 Fase 4 conservan el texto libre de entonces. `planner_used`/`tools_called`/`duration_ms` son DIAGNÓSTICO — ningún test afirma sobre ellos |

## Flujo F0

```
Cliente → WhatsApp → POST /hooks/whatsapp/ (firma HMAC, fail-closed)
  → routing phone_number_id → ChannelAccount → org (R1)
  → dedup wamid → ContactIdentity (match Owner: 0/1/≥2=ambiguous — ver §Identidad
    por teléfono: la resolución la hace `patients.services`, no una query propia)
  → Conversation abierta (o nueva) → Message(in, pending, available_at=+8s;
    cada entrante nuevo empuja la ventana de los pendientes sin TurnWork, tope 25 s)
Worker (run_agent_worker, SKIP LOCKED por conversación):
  → claim TurnWork (miembros fijos; inbound sigue pending) → TurnContext B1
  → planificación en memoria → witness + commit local atómico
    (goals/diagnóstico + outbound final pending + completed + inbound processed)
Sender: outbox → chequeo epoch/scope/legacy → Meta Cloud API (backoff 30s·2^n cap 1h, máx 5; ventana 24h
  se valida ANTES de intentar HTTP) → acuses sent/delivered/read forward-only
Staff → /inbox (bandeja): responder = tomar (human_active + claim).
```

## Identidad por teléfono: leer también es decidir (INV-C — ADR p57)

El agente tiene **dos lectores** de identidad por teléfono y ninguno es dueño de
la regla: ambos consumen el resolvedor de `patients` en **modo lectura**
(`lookup_owner_by_phone`). Ver `modules/patients.md` § Identidad de expediente
por teléfono — este documento **referencia** la garantía, no la redefine.

| Lector | Cuándo corre |
|---|---|
| Creación de `ContactIdentity` (`resolve_contact_identity`) | primer mensaje de un número |
| `_rematch_owner` | **cada** mensaje posterior de un contacto aún `unknown` |

**El bypass que esto cerró** (bloqueador de la revisión OCR): ambos comparaban
el valor **normalizado** del `wa_id` contra `Owner.phone` **en crudo**. Un
expediente guardado como `"55 1234 5678"` y otro como `"5512345678"` normalizan
a la misma clave —INV-C dice **ambiguo**— pero la igualdad cruda solo encontraba
el segundo: el lector veía **una** coincidencia y vinculaba el contacto a esa
fila. Una **elección automática entre duplicados históricos**. Que el nivel
resultante fuera `phone_match` (que no autoriza nada por sí solo:
`tools._verification_ok` exige además `owner_id`) no lo hacía inocuo — ese
vínculo es el punto de partida de la promoción a `confirmed_in_chat`, y
arrastraba el expediente equivocado.

| Aspecto | Contrato |
|---|---|
| Clave | `Owner.phone_normalized`, **nunca** `Owner.phone` crudo |
| Unión | `ContactIdentity.phone_normalized` ↔ `Owner.phone_normalized` |
| Alcance | `for_organization(...)` primero + `is_generic=False` |
| Selección | **ninguna**: el resolvedor cuenta, no elige. `.first()` y `[:2]` como forma de decidir quedan prohibidos |

Desenlaces:

| Candidatos | Resultado |
|---|---|
| 0 | `unknown`, sin `owner` — sin cambio |
| 1 | vínculo `phone_match` — sin cambio (y ahora también encuentra al expediente guardado con espacios, que antes daba un falso «no registrado») |
| ≥ 2 | **`owner_ambiguous`**: **cero vínculo**, `is_ambiguous=True`, el nivel **no** sube y **`auto_rematch_blocked` no se toca ni se limpia** |

Reglas que impiden que la corrección se deshaga sola:

- **La ambigüedad nunca limpia `auto_rematch_blocked`.** Ese flag solo lo limpia
  una de las vías de promoción auditadas; un lector no es ninguna de ellas.
- **Un contacto ambiguo no se «desambigua» solo**, pero tampoco queda preso:
  `_rematch_owner` vuelve a correr en mensajes posteriores y, si alguien ordenó
  el dato y queda un único candidato, entonces sí vincula. Que el conteo cambie
  es información del dominio, no una decisión del lector.
- **El modo lectura no toma el lock de deduplicación**: no crea ni mueve claves.
  Su peor caso es un resultado que envejece (un alta concurrente puede volver
  ambiguo lo que se leyó único) y se corrige en el mensaje siguiente. Lo que este
  cambio cierra no es la carrera: es la **elección**.

Cambio de conducta a vigilar en el despliegue: un contacto que hoy queda
vinculado (porque solo una fila coincide en crudo) pasará a quedar
`is_ambiguous` cuando dos expedientes coincidan tras normalizar. Es la conducta
correcta —el vínculo actual apunta a un expediente elegido a ciegas—, pero para
esa clínica el cliente deja de ser reconocido hasta que alguien ordene el dato.
Se despliega con el reporte de `audit_owner_phone_duplicates` a la vista.

## Continuidad: la sesión es del episodio, el contexto es de la persona (F2)

**`CLOSED` sigue siendo terminal** —un mensaje posterior abre un hilo nuevo— pero
eso **ya no significa empezar de cero**. Lo que el modelo lee sale de
`(contact, channel_account)`, no de la conversación.

Por qué la sesión no se volvió permanente: de ella cuelgan las métricas de
negocio (`compute_business_metrics` cuenta por `Conversation.created_at`), el
presupuesto de llamadas, el claim de la bandeja, los `HumanHandoff`, los
`ConversationGoal` y el `flow`. Hacerla eterna habría roto todo eso para arreglar
el transcript.

| Concepto | Alcance |
|---|---|
| Transcript que ve el LLM, hechos de contacto | `(contact, channel_account)` — dos números de la misma clínica pueden ser dos flujos |
| `verification_level`, `owner`, `privacy_notice_sent_at` | `contact` — es un hecho sobre la persona dentro de la organización |
| Sesión, presupuesto, claim, hand-off, goals, `flow` | `Conversation` — sin cambios |

**El historial cruzado exige verificación vigente.** Sin ella, el contexto se
limita a la conversación actual, exactamente como antes: el transcript viejo
puede contener el nombre de una mascota, que es la respuesta del reto. Los hechos
de contacto sí viajan siempre porque no son PII:

```json
{"ya_hablamos_antes": true, "ultima_vez": "2026-07-28",
 "ultimo_mensaje_hace": "18 días"}
```

Se calculan **excluyendo la ráfaga en curso**: el entrante ya está persistido
cuando el worker arma el prompt, así que sin excluirlo `ultimo_mensaje_hace`
diría «unos minutos» siempre.

`Message.contact` es denormalizado (migración expand-first: campo → backfill por
lotes → índice `CONCURRENTLY`). Contrato: se llena siempre que haya
`conversation`; los huérfanos (media sin hilo, errores de parseo) quedan con
ambos nulos y **no entran ni al contexto ni a la bandeja**.

La creación de sesión se serializa sobre `ContactIdentity` —el
`select_for_update` de una conversación no protege la ausencia de fila— y si
encuentra duplicados abiertos los resuelve **por precedencia**
(`human_active` > `handoff_pending` > `active`, y a igualdad el más reciente),
cerrando el resto con `close_reason='duplicate_session'`. Con **dos** sesiones
humanas se detiene y lo registra: elegir por reloj entre dos personas operando no
es decisión de un script.

`Conversation.close_reason` registra por qué se cerró (`idle` · `staff` ·
`opt_out` · `identity_reset` · `duplicate_session` · `legacy_unknown`). Antes
ningún cierre lo decía, así que en los datos «lo cerró el barredor» y «lo cerró
recepción» eran indistinguibles.

> **Implementado desde p58**: la bandeja muestra una fila por
> `(ContactIdentity, ChannelAccount)` y usa la ruta compuesta de ambos
> `public_id`. Las sesiones siguen siendo episodios separados; el transcript y
> la actividad del hilo se agrupan sin convertir `Conversation` en una sesión
> eterna.

## Verificación en el chat: el factor único y su régimen probatorio (F0)

> Plan completo, con las trece revisiones que lo cerraron:
> [`docs/agent-continuity-plan.md`](../agent-continuity-plan.md).

**El nombre del titular ya NO verifica a nadie** (D4b). Con un contacto
`phone_match`, el **único** factor de autoservicio es el **nombre de una
mascota**. Los otros dos candidatos no prueban nada:

| Factor | ¿Prueba quién escribe? |
|---|---|
| `owner_name` | **No.** El sistema lo conoce y lo enseña —al modelo en el contexto, al staff en la bandeja (`serializers.get_owner_name`)—, y es lo menos secreto de una persona |
| `phone_digits` | **No, y es circular**: el contacto llegó *por ese número*. Mismo criterio que `ContactIdentityVerification.EVIDENCE_CHOICES`, cuyo enum ya excluye toda evidencia telefónica (ADR p57 §5.5.3) |
| `pet_name` | **Sí.** Exige conocer el expediente y no se deduce del canal |

Por qué se retiró: en producción (conv 18) el nombre del titular viajaba al
modelo con solo `phone_match`, el modelo lo pasó a `identify_client` y el sistema
lo verificó **contra el dato que él mismo había suministrado**. No era un fallo de
redacción: el segundo factor no existía.

**Consecuencia aceptada por el PO (2026-08-15)**: un `Owner` **sin mascotas
registradas** —posible, se crean desde el POS— no tiene factor de autoservicio y
va a verificación humana, con un `reason_detail` que dice qué pasó y qué hacer. Si
esos escalados resultan frecuentes, la respuesta **no** es reponer `owner_name`:
es revisar por qué existen esos `Owner`.

### Todo pasa por un solo servicio

`agent/identity_evidence.py`. `identity._promote` tiene **exactamente un
llamador** —invariante con gate estático en `test_identity_evidence.py`— y las
funciones de mascota son **matchers puros**. Antes había dos caminos que
promovían (`policy` y `identify_client`) y ninguno comprobaba el eco; el pasivo
además no satisfacía el slot, así que el agente volvía a pedir la mascota después
de haber verificado con ella.

> **ADR p59 (2026-08-17) retiró la gramática cerrada y los dos regímenes.** Se
> desplegaron con p58 y 15 h después rechazaron a un cliente legítimo que había
> contestado bien: se le preguntó el nombre de su mascota, escribió «koler», y el
> modo pasivo lo rechazó por venir «sin marco». Seis mensajes, 18 minutos, y se
> fue sin su cita. Enumeraban formas de nombrar una mascota y formas de negar
> identidad — dos espacios infinitos, así que cada fraseo nuevo era un bug nuevo.
>
> **La línea correcta**: el servidor decide si algo **autoriza**; el modelo decide
> qué **quiso decir** el cliente. Ver [ADR p59](../decisions/2026-08-17-p59-interpretacion-al-modelo.md).

| Pieza | Regla |
|---|---|
| **Quién propone** | El **modelo**, llamando `identify_client(pet_name=…)`. Es la **única vía**: la ruta pasiva de `policy` se retiró porque sin gramática promovía con cualquier coincidencia de token |
| **LA BARRERA** | El valor propuesto tiene que aparecer en un mensaje **entrante del cliente** de esta conversación, dentro del TTL. El modelo puede leer mal; **no puede inventar el aporte** |
| **Procedencia** | La deriva el **servidor**: localiza el mensaje origen él mismo, exigiendo `direction='in'`, `author_type='client'` y **misma conversación**. Nunca llega en los argumentos de una tool |
| **Matcher** | Uno solo, **tolerante** (typo, subconjunto de tokens). Se acepta contra lo que el modelo transcribió **o** contra el nombre registrado: con «Luna Bella» en el expediente, «cita para Luna» tiene que funcionar |
| **Candidato ambiguo** | Si la propuesta encaja con **dos** mascotas de nombre distinto, no se elige — mismo criterio que INV-C en su dominio |
| **La pregunta** | La añade el **sistema** (`T0_IDENTITY_QUESTION`): el modelo demostró en producción que pide los 4 dígitos si le dejas, y ése es un factor retirado por circular. Lo que p59 retiró es **ligar** ese saliente al reto, no la práctica de ponerlo |
| **Anti-eco** | **Primera mención gana**, dentro del TTL, sobre mensajes **realmente emitidos**, y con el matcher tolerante — staff escribiendo «Lunna» tiene que contar como revelación |
| **Rechazo por eco** | `HumanHandoff(identity)` + `T0_IDENTITY_ECHO`, **nunca reintento**: repetir el dato seguiría siendo eco hasta que caduque la ventana. El **planner** corta el turno y pone la plantilla — dejar redactar al modelo tras haber escalado le permitía repetir el nombre, que es la fuga que este camino cierra |
| **Nada que escalar** | Si el cliente **no dijo nada** y el modelo leyó su propio mensaje, es `NoEvidence`, no eco: se le pregunta y el turno sigue. El escalado se reserva para cuando el CLIENTE repite un dato que nosotros filtramos |
| **Caducidad** | `IDENTITY_EVIDENCE_TTL` (60 min) sobre el mensaje origen. La sesión **no** sirve como ventana: `close_inactive_conversations` mide inactividad, y en producción hay sesiones de 29 h y 47 h |
| **Transacción** | `_promote` + `flow` + slot + **cierre del reto y reanudación** en un solo commit, con locks `ContactIdentity → Conversation → ConversationGoal` (por id) |

**El caller reasigna lo que mutó** (`contact`, `flow` y cualquier variable local).
Hasta F0 funcionaba por coincidencia de instancia compartida; con
`select_for_update` esa coincidencia desaparece y la DB quedaría promovida con el
turno viéndose sin verificar.

**Orden del turno, que es contrato**: reconciliar vencidos → sellar la evidencia
de la ráfaga → resto de `policy.evaluate` → ensamblar el prompt. Por eso quien
escribe «cita para Luna» verifica **y** recibe su contexto en el **mismo** turno.

### Goals de identidad: tres conjuntos, no uno

`HISTORICAL` ⊃ `STARTABLE` ⊃ `RESUMABLE`. `policy` ya no reanima un suspendido
por pertenecer a `IDENTITY_GOALS` sino por el **predicado**
`is_resumable_identity_goal`: `identity_triage` es maquinaria retirada en É-F5
Fase 2 y producción tenía una fila suspendida que volvía al frente arrastrando un
`GoalSpec` que ya no conduce nadie.

`start_identity` es el **único creador**, y su único llamador productivo es la
rama `verification_required` de `planner._run_planner`. `open_goal` **rechaza**
nombres de identidad.

### Remediación de datos (precondición, no limpieza posterior)

`python manage.py remediate_identity_f0 [--org N] [--apply]` — dry-run por
defecto, idempotente, con conteos antes/después. Degrada los contactos
`confirmed_in_chat` sin `linked_via` (los que solo pudo verificar el reto
conversacional) y cierra los retos huérfanos. **Se corre antes de desplegar la
conducta del caso verificado**: instruir al modelo a confiar en
`verificado: true` antes de degradar consolidaría un estado obtenido por el
bypass.

## Endpoints

| Superficie | Auth | Notas |
|---|---|---|
| `GET/POST /hooks/whatsapp/` | Firma del proveedor (SIN JWT, fuera de `/api/`) | Handshake + eventos; sin firma válida no se toca la DB; siempre 200 tras firma válida |
| `GET /api/inbox/threads/` (+`?archived=1`) | `agentinbox.view` | **Bandeja agrupada por persona**: una fila por `(contacto, cuenta)`, con el estado/claim/escalada de la **sesión vigente** y la actividad del **hilo completo**. Cap 100 |
| `GET /api/inbox/threads/<contacto>/<cuenta>/sessions/` | `agentinbox.view` | Los episodios del hilo, del más reciente al más viejo. Paginado |
| `GET /api/inbox/threads/<contacto>/<cuenta>/messages/` | `agentinbox.view` | Transcript del hilo **cruzando sesiones**, con cursor `?before=`. Devuelve además la sesión vigente, su caso de identidad y su hand-off |
| ~~`GET /api/inbox/conversations/` (+`?state=`)~~ | `agentinbox.view` | **DEPRECADO** (RFC 8594, Sunset **2026-11-30**) → `GET /api/inbox/threads/`. Devolvía una fila por EPISODIO: un cliente con 19 conversaciones aparecía 19 veces. Sigue funcionando y emite `DEPRECATED_ENDPOINT_HIT`, que es el gate para cortarlo a `410` |
| `GET /api/inbox/conversations/<uuid>/messages/` | `agentinbox.view` | Transcript cronológico, cap 200 |
| `POST …/send/` | `agentinbox.send` | Sanitizado, máx. 4000; deja la conversación en `human_active` + claim. Acepta `X-Idempotency-Key` (máx. 64): repetir la misma clave dentro de la organización devuelve `201` con el mismo mensaje humano y no vuelve a tomar ni a encolar. La respuesta y los transcripts exponen `client_message_id` de solo lectura únicamente para salientes `human_staff`; entrantes y mensajes internos de agente/sistema devuelven `null` |
| `POST …/claim/` · `…/close/` · `…/release/` | `agentinbox.claim` | Claim exclusivo → 409 `already_claimed` |
| `POST …/unlink-family/` | `agentinbox.claim` | Revoca SOLO un vínculo `family_challenge` (PR-17b) — nunca toca `phone_match`/`self_register` legítimos |
| `POST …/reset-identity/` | `agentinbox.config` | Resetea el `ContactIdentity` a `unknown` (owner/verificación/`linked_via`, cualquier procedencia) + cierra el hilo activo. `resolve_contact_identity` solo matchea teléfono→Owner al CREAR la fila (nunca la re-deriva después, ni si `Owner.phone` cambia) — este endpoint es la única forma soportada de reabrir esa resolución con el mismo número real. Solo ADMIN: desligar una identidad ya verificada es sensible (mismo permiso que el kill switch) |
| `GET/PATCH /api/inbox/settings/` | `agentinbox.config` | Kill switch + `faq_facts` (caps 20×500; rechaza claves de la config de clínica). `enabled=true` exige teléfono de clínica válido → 400 (ver §Gate del kill switch). El horario NO se toca aquí: vive en `/config` |

Permisos (Q13): ADMIN todos (lista explícita, ADR p63) · ASSISTANT view+claim+send · VET view · AGENT
(el bot) ninguno de bandeja.

### Selectores de transcript y anti-eco (addendum p58, 2026-08-23)

No hay un único predicado para todas las lecturas de mensajes: visibilidad
operativa y evidencia de entrega son contratos distintos.

| Selector | Incluye | Excluye | Uso correcto |
|---|---|---|---|
| `channels.selectors.visible_messages` | Entrantes `received`; salientes `sent`/`delivered`/`read`; y salientes `pending` **solo** de `human_staff` | `pending` de agente/sistema; todos los `failed` y `discarded` | Transcript del Inbox y consumidores históricos de contexto. El pendiente humano aparece de inmediato, sin esperar al sender |
| `channels.selectors.emitted_outbound` | Salientes `sent`/`delivered`/`read` | Todo `pending`, `failed`, `discarded` e inbound | Anti-eco y cualquier decisión que necesite probar que un saliente fue emitido |

El `pending` humano visible no prueba entrega. Responder desde el Inbox cambia
la sesión a `human_active`, por lo que el agente normalmente no vuelve a
planificar en ese episodio; aun así, un consumidor nuevo **no debe inferir
anti-eco o entrega desde `visible_messages`**. Para reconciliar UI/servidor se
usa `client_message_id`, nunca coincidencias por cuerpo o tiempo.

## Comandos

- `provision_channel --org --phone-number-id [--display-number] [--credentials-ref]`
  — idempotente; guard R1 (número de otra org → error, sin escrituras).
- `ensure_agent_users [--org]` — repara/recrea el service account (ADR p51).
- `run_agent_worker [--once] [--poll] [--batch]` — el proceso worker (F1:
  corre policy→planner→tools por entrante; cierra inactivas 24h en el loop).
- `agent_eval [--json]` — eval nightly con LLM real (no bloqueante, rollback;
  skip si no hay `AGENT_LLM_API_KEY`). Gate del piloto: ≥95 % en 5 corridas.
- `agent_quality [--days 7] [--sample 20] [--org <public_id>] [--json]` — É-F3
  W3: métricas de calidad conversacional + **muestra estratificada de
  transcripts para leer** (escaladas / abandonadas / completadas). Semanal.

## Pipeline del turno

Pipeline por entrante (`agent/planner.py`): `policy.evaluate` resuelve
tier-0 sin LLM (urgencia/humano/opt-out/bot/confirmación/presupuesto);
`RUN_PLANNER` corre el bucle acotado LLM↔tools (executor loopback+RBAC
reales, resultado como DATOS G6, `LLMCall` por llamada). El LLM **nunca
autoautoriza**: policy decide antes, run_tool/executor revalidan
tier/verificación/ownership y, después de un recibo de operación, el
orquestador exige autorización semántica doble de la ráfaga antes de abrir un
objetivo nuevo. Proveedor LLM = elección del operador
(`AGENT_LLM_*` por env, cliente OpenAI-compatible en `agent/llm.py`).
Tools de **lectura** (tier 1): list_my_pets, get_vaccine_status,
**get_appointments**, get_clinic_info, get_service_catalog,
check_product_availability, find_available_slots,
get_recent_product_queries. De **escritura**: 
create_appointment, cancel_appointment, reschedule_appointment,
register_new_client_and_pet y **register_pet_and_schedule** /
**register_pet_only** (tier 2 — proponen y esperan el "sí"),
confirm_appointment (tier 1, benigna), link_family_member (arranca el reto
triple). request_human siempre disponible. Handles efímeros en `flow.refs`
con resolver+ownership server-side (handle desconocido = denegación dura).
Identidad (`agent/identity.py`): implícita (nombrar mascota) + reto UX-03.
Suite de regresión: 63 casos congelados en CI contra `StubLLMClient`
(bloqueante) + fixture trampa cross-tenant + aserciones prohibidas globales
(`agent/tests/harness.py`).

### Operación posterior a un recibo: la ráfaga es la autoridad (2026-08-27)

Un `operation_receipt` cerrado no se interpreta como una conversación que
puede retomar la operación anterior. Si no hay confirmación ni objetivo vivo,
el planner pierde todo capability de agenda y `operation_authorization.py`
evalúa la **ráfaga completa** (no solamente su último texto): un autorizador
tipado propone `conversational|operation|ambiguous`; si propone operación, un
verificador independiente acepta, rechaza o marca ambigüedad. Solo dos
veredictos compatibles abren un `ConversationGoal` nuevo y revelan sus tools.

Las fuentes ordenadas, ambos modelos/prompts y el resultado quedan en
`TurnOperationAssessment`; el objetivo autorizado la referencia y conserva el
último `Message` causal por compatibilidad. Un timeout, contrato inválido o
ambigüedad deja el turno sin agenda, pero permite una respuesta conversacional.
No hay parser de agradecimientos ni lista de frases; `begin_operation` no se
expone al modelo y se deniega incluso si aparece en un output atrasado. Ver ADR
`2026-08-27-semantic-turn-operation-authorization.md`.

### Una tool no decide qué es relevante (`get_appointments`, 2026-08-17)

`get_appointments` **reemplaza** a `list_upcoming_appointments` y
`get_past_visits`. Eran el mismo código con el filtro invertido, y cada una una
**pregunta congelada**: una asumía que el cliente pregunta por el futuro, la
otra que pregunta por visitas cerradas. Entre las dos dejaban un hueco del
tamaño del caso más común de una clínica.

Conv 21 en producción: el cliente abrió con «no pude acudir a mi cita». La cita
existía —ese día, 09:00, `scheduled`— y él la veía en el sistema. La API la
devolvía en las diez llamadas (`{"appointments": 1}` en `ToolExecution`), y
estos dos filtros la tiraban:

```python
list_upcoming_appointments:  if start_dt < now: continue
get_past_visits:             if status != 'done': continue
```

Una cita perdida es pasada **y** no `done`: caía por los dos, así que **ninguna
de las 18 tools podía verla**. El modelo recibía `0` y decía `0`, honestamente,
mientras el cliente insistía «deberías buscar bien». Y como los handles de cita
solo los emitía la primera, **reagendarla era imposible por construcción**.

Contrato nuevo, y es la regla general, no un parche:

| | |
|---|---|
| Devuelve | **todas** las citas del cliente, cada una con `estado`, `ya_paso` (resuelto contra el reloj de la clínica) y `motivo` |
| Filtra por estado o fecha | **no** — quien elige qué responde a la pregunta es quien leyó la conversación |
| Handle | para **todas**, no solo las futuras: es lo que permite cancelar o reagendar la que se perdió |
| Único recorte | volumen (`MAX_ITEMS`), y por **cercanía a ahora**, para que sobrevivan a la vez la que se perdió esta mañana y la próxima |

`_APPT_STATE_LABEL` pasó a cubrir los **seis** estados. Que faltaran
`done`/`canceled`/`no_show` era el mismo defecto por otra vía: el mapa cubría
exactamente lo que la tool había decidido de antemano que el cliente podía
preguntar.

**Regla que esto deja**, y la distinción es la parte útil: un filtro que
**reafirma una regla del dominio** está bien; un filtro que **adivina la
pregunta** es el defecto.

| Tipo de filtro | Ejemplo | Veredicto |
|---|---|---|
| Reformula un invariante | `status in (scheduled, confirmed, in_progress)` en `_day_occupancy` / `_own_appointment_at` — es el predicado de **INV-D** | **Legítimo.** Debe citar el invariante |
| Integridad del dato | fecha ilegible, dedup, `_confidence` | Legítimo |
| **Adivina qué preguntó el cliente** | `start_dt < now`, `status != 'done'` | **El defecto.** Retirados |

Revisados los 8 `continue` que quedan en `tools.py`: **ninguno es del tercer
tipo**. Los dos retirados eran los únicos. (Una revisión previa dijo «quedan ~11
del mismo patrón»; era falso, y retirar por error el predicado de INV-D
rompería la detección de solapes.)

### Las remediaciones de datos NO van en `release.sh`

`remediate_identity_f0` estuvo un día en `release.sh` y causó el peor incidente
del piloto. Dos motivos, y el segundo aplica a cualquier comando futuro:

1. **`release.sh` no corre «una vez por deploy».** El cron de la demo
   (`10,40 * * * *`) invoca `docker compose run --rm backend …`, y `run` arranca
   las dependencias del servicio — entre ellas `release`. En producción son
   **48 corridas al día**.
2. **Una remediación es de un solo uso; ese script no lo es.** Su predicado
   describe un estado histórico. En cuanto el código nuevo produce estados
   legítimos parecidos, el predicado los alcanza.

Y los alcanzó: el predicado era `confirmed_in_chat AND linked_via=''`, que **no
describe el estado comprometido sino el CORRECTO** — `identity._promote`, la
única vía del reto conversacional, nunca escribe `linked_via`. Log de la corrida
de las 17:40:

```
ANTES · contactos a degradar: 1
        contacto 1 org=3 verified_at=2026-08-17 17:27:41.865888+00:00
```

Ese instante es el de una verificación legítima, sellada en
`challenge_response`, destruida 13 minutos después. Y como el historial cruzado
se gatea en `is_verification_current` (D19), **la amnesia que p58 arregló volvía
cada media hora**.

Corrección: el comando exige **`--before <instante ISO>`** —la frontera del
despliegue de F0, que es cuando el bypass dejó de existir— y sin él no degrada
nada. Un gate (`ReleaseScriptTests`) falla si `remediate` reaparece en
`release.sh`. `migrate`/`collectstatic`/`seed_permissions` se quedan porque son
**convergentes**: su resultado no depende de cuándo corrieron.

### El agente consume las garantías del dominio (F2 — ADR p57)

Las escrituras del agente viajan con su **precondición** y traducen el conflicto
a conversación. Ninguno de estos desenlaces es una avería (§5.1 R2): no son
5xx, no producen `tool_failure` y **nunca se reintentan** — reintentar es pelear
con la decisión de otro.

**INV-A — precondición de estado.** `cancel_appointment` y
`reschedule_appointment` capturan al **proponer** la tupla que el cliente vio
parafraseada (`expected_status`/`expected_date`/`expected_start_time`) y la
envían como `expected_state` al confirmar. Capturarla al confirmar describiría
el mundo de después, y la precondición no diría nada.

| Desenlace | Cuándo | Qué hace el agente |
|---|---|---|
| `appointment_changed` | la cita cambió a otra cosa | cuenta al cliente **qué** cambió (estado real) y le deja decidir. No escala: es información, y el cliente está escribiendo ahora |
| `already_done` | la cita ya está como la pedía | éxito idempotente: cierra el objetivo como cumplido. Antes rebotaba a una persona para nada |

**INV-B — el alta exige expediente nuevo.**
`register_new_client_and_pet` envía **siempre** `require_new_owner=true`: en ese
flujo la premisa es literalmente «cliente nuevo», así que si el teléfono ya
tiene expediente la premisa era falsa y la decisión es de una persona. No se
pre-consulta desde el agente (sería `icontains` acotado a 20 filas con una
ventana TOCTOU hasta el POST).

Antes de llamar al dominio se comprueban **C1–C4** sobre el contacto releído de
la base: sin expediente, no ambiguo, y el mismo número que propuso. Si algo
cambió → `identity_changed`: ni se llama al dominio. No es un error, es la
buena noticia de que el humano ya lo resolvió (§4.5); la conversación sigue por
la vía de cliente conocido.

| Desenlace | Efecto en el dominio | Efecto en la conversación |
|---|---|---|
| `owner_exists` (un expediente) | **ninguno** | intención suspendida íntegra + caso de identidad en Inbox |
| `owner_ambiguous` (dos o más) | **ninguno** | idéntico para el cliente; el `reason_detail` del caso distingue |
| `identity_changed` (C1–C4) | ninguno (no se llama) | «Ya te tengo registrado ✅ ¿Te agendo la cita?» |

**Mascota nueva de un cliente YA identificado** (addendum 2026-08-14 del ADR
p57). `register_pet_and_schedule` cubre el hueco que el piloto encontró: un
cliente conocido que llega con otra mascota no tenía ningún camino
(`register_new_client_and_pet` se niega con `already_client`;
`create_appointment` exige un handle que solo sale de `list_my_pets`), y el
modelo lo prometía igual hasta acabar en hand-off por estancamiento.

El expediente sale de **`contact.owner_id`** —el vínculo verificado—, nunca de
resolver el teléfono en el momento: el `POST /api/pets/` va en **modo
referencia** (`owner_public_id`), que es lo que INV-B reserva para «alguien
eligió este expediente». Exige `confirmed_in_chat`; un vínculo **familiar** no
puede abrir expedientes en la ficha del titular (`family_restricted`).

`register_pet_only` existe porque el PO permitió el alta sin cita, pero **no se
ofrece**: el camino que se propone es siempre con cita. Son dos herramientas y
no una con bandera para que «se quedó sin cita» sea explícito y medible en
`ToolExecution`.

| Desenlace | Efecto | Conversación |
|---|---|---|
| `pet_exists` | ninguno | ya tiene una mascota con ese nombre; se devuelve su handle para agendarle a **ésa** |
| `pet_saved_appointment_failed` | mascota creada, cita no | **no escala**: «ya la registré, no pude apartar el horario, ¿otro?». El estado es válido, no un huérfano |

**La intención no se pierde.** Suspender el pendiente, abrir/retener el
`HumanHandoff` de identidad y pasar a `HANDOFF_PENDING` ocurre en **una sola
transición atómica** (`confirmations.suspend_pending`), bajo
`select_for_update()` de la conversación. Es el único escritor legítimo de
`flow['suspended']`, y `escalate_to_human` lo usa también: no hay dos formas de
suspender. Antes eran dos `save()` separados —limpiar el pendiente y escalar— y
entre ellos cabía perder la propuesta del cliente en silencio.

**Telemetría (§5.4).** Cada llamada declara sus `business_outcomes`: los códigos
declarados registran `AGENT_TOOL_BUSINESS_CONFLICT` (INFO, redactado) en vez de
`AGENT_TOOL_HTTP_ERROR` (WARNING) y **no cuentan como fallo de integración**. La
fila de `ToolExecution` se sigue creando con su `error_code` — la traza no se
pierde. No hay lista global: un `owner_exists` es negocio en el alta y sería una
anomalía en cualquier otra tool. Lo no declarado conserva su comportamiento; el
silencio por defecto sería el fail-open de la observabilidad.

### FLUJO-C — verificación humana de identidad (F4 — ADR p57 §5.5)

La **única** ruta por la que un contacto no verificado puede terminar operando
sobre un `Owner` existente, y toda ella pasa por una persona. Cierra el hueco
que INV-B dejaba al descubierto: `LINKED_STAFF` existía en el enum desde el día
1 **sin ningún escritor**, así que un `409 owner_exists` terminaba en un
hand-off que el staff resolvía fuera del sistema.

**El caso no es un modelo nuevo**: es el `HumanHandoff` que ya existe, con
`reason_code='identity'` y `reason_detail ∈ {owner_exists, owner_ambiguous}`.
La bandeja ya lo mostraba y lo ordenaba por urgencia. Lo que se añade es el
registro de verificación y las dos acciones.

| Paso | Acción | Permiso | Toca el dominio |
|---|---|---|---|
| 1 | el commit falla con `owner_exists`/`owner_ambiguous` → caso abierto + intención suspendida | — | **no** |
| 2 | staff reclama (`claim`) | `agentinbox.claim` | no |
| 3 / 3' | **verificar**: registra el juicio (aprobado o rechazado) | `agentinbox.identity_verify` | **no** |
| 4 | **autorizar**: vincula el contacto al `Owner` | `agentinbox.identity_verify` + verificación vigente | sí — `link_staff_verified` |
| 5 | staff libera (`release`) | `agentinbox.claim` | no |
| 6 | el cliente reconfirma → la escritura ocurre aquí, revalidando C1–C5 | el cliente | sí |

**Verificar y autorizar son dos endpoints, no uno con un booleano.** El primero
registra un juicio humano; el segundo ejecuta su consecuencia. Separarlos es lo
que permite auditar el juicio aunque nadie llegue a autorizar, y lo que impide
que un clic haga las dos cosas sin dejar constancia de la primera.

**Liberar no autoriza.** Si el staff libera sin verificar, el release restaura
la intención vencida, el cliente reconfirma y el commit vuelve a fallar con
`owner_exists` — y el caso se abre otra vez. Es lo correcto.

#### El registro (`ContactIdentityVerification`, append-only)

`ContactIdentity` guarda `verified_at` pero **no guarda quién verificó**, y no
puede representar un **rechazo**: no existe un «nivel de verificación negativo».
De ahí el modelo propio, con `organization`, `contact`, `owner_candidate`,
`conversation`, **`handoff`**, `decision`, `evidence_kind`, `evidence_note` y
`actor`. Sin `PATCH` ni `DELETE`: una decisión equivocada se corrige
registrando otra, y la autorización lee **el último** registro.

- **El sistema no juzga la evidencia**: registra que una persona identificada
  afirmó haberla comprobado. `evidence_kind` es una etiqueta de auditoría, no
  un puntaje.
- **La evidencia es externa al teléfono**: el número ya se sabe que coincide
  —es lo que creó el caso— y usarlo como prueba sería circular. Las cuatro
  opciones son `in_person_id`, `known_record`, `callback` (al teléfono **del
  expediente**) y `other`. Ninguna se basa en el número que escribe.
- `evidence_note` es una nota **operativa**, no un sitio para documentos. Los
  logs llevan ids; la nota **nunca** se loguea.

#### Enlace estricto (por qué cuatro FKs no bastan)

Tener las FKs no prueba que apunten al mismo caso: sin más reglas, una
aprobación emitida para el Owner A podría autorizar el vínculo con el Owner B.
Todo se deriva del servidor:

| Dato | De dónde sale |
|---|---|
| `organization` | `conversation.organization` |
| `conversation` | la ruta, vía `_get_conversation` (tenant-scoped → cross-tenant es **404**) |
| `contact` | `conversation.contact` |
| `owner_candidate` | `Owner.objects.for_organization(conversation.organization)` por `public_id` |
| `handoff` | el hand-off de identidad **abierto** de esa conversación |
| `actor` | `request.user` — si viene en el body, se ignora |

Autorizar comprueba las cuatro precondiciones **en el mismo `atomic()`**, con
`select_for_update()` sobre `ContactIdentity` **y** sobre el `HumanHandoff`:
caso abierto · último registro `approved` **de este hand-off y esta
conversación** · candidato aún existente · contacto sin vincular. Sus rechazos:
`no_identity_case`, `verification_required`, `owner_changed`, `already_linked`
(409). El invariante de organización se valida además **en el modelo**: una vía
futura que escriba el registro sin pasar por el endpoint no puede saltárselo.

**Frescura acotada por el caso, no por reloj**: la aprobación vale mientras
*este mismo* hand-off siga abierto. Evita inventar un TTL arbitrario y evita
que una aprobación de hace tres meses habilite una acción de hoy.

#### `link_staff_verified` — la cuarta vía de promoción

Es la **más fuerte** de las cuatro que elevan el nivel de verificación, y la
única forma legítima de deshacer un `reset_contact_identity`: por eso limpia
`auto_rematch_blocked`. Ese flag apaga el auto-enlace porque **nadie había
verificado nada**; aquí alguien lo hizo, con nombre y evidencia. Sigue sin
existir ningún camino automático que deshaga un reset.

#### Fuera de alcance, explícitamente (§5.5.6)

Nada de heurísticas, puntajes ni coincidencia difusa. Nada de que el modelo
«decida» que una identidad es suficiente. Nada de OTP/SMS, biometría, lectura
de documentos ni proveedores externos. Nada de auto-aprobación por antigüedad,
inactividad o reintento. Nada de re-verificación automática al re-escribir:
`auto_rematch_blocked` sigue mandando. Cualquiera de esas piezas sería un
diseño nuevo con su propio ADR y su propia revisión de seguridad.

### Por qué llegó el caso: el motivo del hand-off es visible (2026-08-14)

`HumanHandoff` guardaba desde siempre `reason_code` (clasifica) y
`reason_detail` (informa), y **ninguno de los dos llegaba a la bandeja**: la
API publicaba solo el código grueso y el frontend no pintaba ninguno. Quien
recibía el caso veía «Esperando» y tenía que leer el transcript entero para
deducir qué había pasado — o preguntarle al cliente algo que el sistema ya
sabía.

- `GET /api/inbox/conversations/` añade **`handoff_detail`** junto a
  `handoff_reason`. La lista muestra el fino y cae al grueso: «se atascó
  pidiendo datos» ubica, «baja confianza» no.
- `GET .../messages/` añade el bloque **`handoff`**: `reason`, `detail`,
  `priority`, `opened_at` y el **compromiso en juego** — qué prometió el
  agente, qué datos ya tenía y **cuáles le faltaban**, con las etiquetas de
  negocio de `goals.py` (`la mascota que vamos a atender`), nunca nombres de
  slot.
- Los casos de **identidad** siguen usando `identity_case`, que además trae
  acciones; este bloque cubre todo lo demás. La bandeja pinta uno u otro, no
  los dos.

El objetivo se busca con `goals.last_task_goal`, que **no** filtra por estados
de primer plano: al escalar, el compromiso queda en `handoff`/`blocked`, que es
justo lo que `get_open_goal` excluye. Sin eso no habría nada que contar.

### Liberar una conversación: el veredicto sobre lo suspendido (F3 — ADR p57)

Liberar no es «poner `state=active`»: es aplicar un **veredicto** sobre la
propuesta que el cliente dejó a medias. `services.release_conversation`, en tres
pasos:

| Paso | Qué hace | Dónde |
|---|---|---|
| **R1** | lock de la fila, valida la suspensión y captura el **testigo** | tx corta |
| **R2** | una lectura HTTP al dominio: ¿el humano ya hizo el trabajo? | **fuera** de toda transacción |
| **R3** | re-lee el testigo y, **solo si coincide**, aplica veredicto + release | tx corta, un commit |

R2 va fuera del lock porque una llamada de red dentro de una transacción la
mantiene abierta lo que tarde el otro extremo (invariante 7). El **testigo**
existe por eso: durante esa ventana el worker puede tomar el turno, otra persona
puede reclamar, o puede aparecer una suspensión nueva. Sus cinco campos:
`suspension_id`, `state`, `claimed_by_id`, `ownership_epoch` y el **id del
hand-off abierto observado** — se resuelve **ese** caso, no «el último abierto».

**Veredicto** (§3.1 — *solo el match exacto descarta*):

| Tool | Descarta si | Todo lo demás |
|---|---|---|
| `create_appointment` | existe cita ese día para esa mascota a esa hora, en estado vivo o `done` | restaura |
| `cancel_appointment` | la cita está `canceled` o `done` | restaura |
| `reschedule_appointment` | la cita ya vive en el destino y sigue activa | restaura — **incluido el «tercer horario»** |
| `register_new_client_and_pet` | **nunca** | siempre restaura |

Un 404 del recurso consume la suspensión sin restaurar (restaurar garantizaría
un fallo posterior ante el cliente sobre algo que ya no existe). Error, timeout
o suspensión ambigua → **restauran**: descartar de más deja al cliente esperando
algo que nadie hará.

**Restaurado vencido** (D1): el `pending_action` vuelve con `expires_at` en el
pasado, así que el primer «sí» posterior cae siempre en la rama de TTL vencido,
**re-parafrasea y no escribe**. Ningún «sí» viejo ejecuta nada por su cuenta.

**Sin reintentos silenciosos.** Si el testigo difiere se repite el ciclo **una
sola vez**; si vuelve a diferir → `409 release_conflict` con su `reason`
(`suspension_changed` · `state_changed` · `claim_changed` · `turn_in_progress` ·
`handoff_changed`). Dos vueltas con el mundo moviéndose significan que hay
alguien más operando, y eso lo decide una persona, no un bucle. Con un turno del
worker en vuelo: `409 turn_in_progress`, sin mutar nada.

`claim`, `release` y `close` se **serializan sobre la misma fila**
(`select_for_update`). Sin eso el testigo no significaría nada: no se puede
comparar contra algo que otro camino escribe sin lock.

#### Tres decisiones de producto que F3 deja explícitas

1. **Sin TTL nuevo ni mensajes automáticos** (§9.4). F3 no añade vencimiento
   propio a la suspensión. La pérdida silenciosa a ~24 h de
   `close_inactive_conversations` es **preexistente** y sigue igual: una
   conversación cerrada no se reabre, así que el `flow` muere con el hilo sin
   evento ni aviso. Convertirla en una baja con **razón auditable
   `conversation_inactive`** es una mejora **separada**, fuera de este alcance.
2. **Descarte silencioso** (§9.5). Cuando el chequeo prueba que el objetivo ya
   quedó resuelto, se descarta **sin avisar al cliente**. Un «esto ya lo había
   hecho el equipo» no aporta nada y reabre una conversación cerrada.
3. **`deferred_at` se conserva** (D7). El release no lo toca: una promesa de
   esperar hecha al cliente no la revoca un botón de staff. `nudge_sent` solo se
   limpia **en su ausencia**.

#### El claim ajeno preexistente se libera — decisión, no omisión

El testigo protege la ventana R1–R3, **no la propiedad del claim**. Si otra
persona ya tenía la conversación reclamada **antes** de que se pulsara liberar,
el release se la quita.

**Ratificado para el piloto** (decisión de producto, 2026-08-12): se mantiene
así. El motivo es operativo — si quien reclamó una conversación se ausenta, esa
conversación no puede quedar bloqueada para el resto del equipo, y en una
clínica pequeña eso pasa a diario. Es además el comportamiento previo a F3, que
no miraba el claim en absoluto: no hay cambio de conducta que comunicar.

Lo que sí protege el testigo: un claim que aparece **durante** la ventana aborta
ese intento y fuerza el reintento (`claim_changed`).

Cuando el piloto lo justifique, la evolución prevista es una política de
**«solo el titular o un supervisor libera»** — no un `409` a secas, porque eso
reintroduce el bloqueo por ausencia sin darle salida a nadie. Exige decidir
quién es «supervisor» (¿rol, permiso propio?), y por eso no se hace de paso.

Anclado en `test_a_pre_existing_foreign_claim_is_still_released`.

### Identidad de un número desconocido — RETIRADO el tamiz, vive el reto

> **Aquí había 70 líneas describiendo el tamiz `T0_TRIAGE`** (*«¿primera vez, o
> ya eres cliente y escribes desde otro número?»*) con sus ramas `new` /
> `returning` / `unclear`, sus lemas negados y su costo de 4 turnos. **Esa
> máquina se retiró en É-F5 Fase 2** (ADR p56 §4): el router decidía qué frase
> tocaba en cada etapa, y la conversación que abrió É-F5 se resolvió con **cero
> llamadas al modelo**. La documentación siguió describiéndola año y medio de
> commits después de que dejara de existir, que es la peor clase de doc: la que
> se lee como vigente.

Lo que hay hoy, y quién hace cada cosa:

| Situación | Quién la conduce |
|---|---|
| Número **desconocido** que pide algo personal | El **modelo**, conversando. La barrera no es el router: es `_verification_ok` dentro de `run_tool`, que se evalúa por debajo del modelo — una tool personal rebota sin tocar nada |
| El cliente aporta un dato de identidad | `identify_client`, que **registra y dictamina**. El modelo aporta el valor; el servidor deriva la procedencia, el régimen y el anti-eco (ADR p58 §2) |
| Número **ya vinculado** (`phone_match`) que necesita verificarse | Reto de un solo factor: **el nombre de una mascota**. `owner_name` se retiró como factor en p58 §1 y los 4 dígitos son circulares para quien escribe desde su propio número |
| Número desconocido actuando por un titular existente | Reto **familiar** de tres factores contra un mismo `Owner` (`find_link_candidates` + `owner_has_pet` + `owner_digits_match`). Ahí el nombre del titular es **clave de búsqueda**, no prueba: el sistema todavía no conoce al `Owner`, así que no puede filtrarlo |
| Nada de lo anterior alcanza | Verificación **humana** (FLUJO-C, ADR p57 §5.5) |

Lo que **sigue vigente** de aquella sección, porque no dependía del tamiz:

- **El sistema nunca asume que un número sin registro es un cliente nuevo.** Lo
  que cambió es que ya no lo pregunta con una plantilla: lo conversa.
- **Decir «ya vine antes» NO escala a un humano** (decisión del PO,
  2026-07-28): se busca, se verifica y se atiende. A un humano se llega si la
  verificación **falla** de verdad, o si no queda ningún factor que el cliente
  pueda aportar (§2.2.2 del plan de continuidad).
- **Aviso de privacidad just-in-time (UX-01)**: lo antepone el planner cuando el
  turno descubre que necesita identificar a alguien. Es un literal legal que
  pone el **sistema**, no el modelo — mismo patrón que la pregunta del reto
  (p58 §2).
- **Preguntas de precio, horario o ubicación no piden identidad**: son tier-1
  anónimo, y meterles una puerta era fricción gratuita.

**Costo que sigue en pie**: un cliente registrado que escribe desde un número
nuevo paga los tres factores del reto familiar. El tercero —los 4 dígitos del
teléfono registrado— se diseñó para un **familiar**, no para el titular que
cambió de número, así que puede fallar por memoria y acabar en humano. Revisado
con el PO el 2026-07-28: **se deja así**.

#### Interrupciones durante un reto (É-F4 Fase 0, 2026-07-30)

**Una pregunta del cliente durante `identity_challenge`/`family_challenge`/
`identity_triage` (stage `titular`) nunca cuenta como respuesta equivocada.**
`matchers.looks_like_question` + `matchers.is_answer_shaped(stage, text)`
(`policy._is_interruption`) distinguen "no respondió" de "respondió mal": si
el mensaje interroga y no trae la forma de la respuesta esperada (los 4
dígitos son la única etapa con forma verificable; nombres no la tienen), el
sistema responde el **por qué** (`tier0.FACTOR_WHY` + `T0_WHY_THEN_REASK`) y
re-pregunta **sin tocar `fails`**. Corrige el caso más caro de la auditoría
2026-07-29 (conv 13, `85a2a691`): un cliente con los 4 factores correctos
preguntó "¿para qué necesitas eso?" antes de dar los últimos 4 dígitos y el
sistema lo contó como 2 fallos y lo escaló, tirando un reto que estaba a
punto de pasar.

**Tope de 3 desvíos** (`flow['deviations']`, compartido por las 3 máquinas del
mismo intento de verificación): contestar todo con preguntas nunca avanza el
reto — al 3er desvío se escala (`handoff_detail='deviation_cap'`) en vez de
preguntar para siempre. Se resetea al arrancar un reto nuevo o al resolverlo
(verificado o escalado).

**El planner no re-tría un tamiz ya resuelto.** Si `flow['identity_triage_done']`
ya tiene veredicto y una tool personal vuelve a rebotar con
`verification_required` sobre un contacto sin owner, el planner escala
(`detail='triage_already_resolved'`) en vez de sembrar `start_identity_triage`
de nuevo — antes lo hacía incondicionalmente, y dos meta-preguntas al tamiz
nuevo podían pisar un `'returning'` correcto con `'unclear'`
(`flow.setdefault`, no asignación directa, es la segunda barrera). Mínimo
honesto de Fase 0; Fase 1 lo convierte en reanudar el compromiso suspendido.

Ver [`whatsapp-agent-f4-gobernanza-plan.md`](../whatsapp-agent-f4-gobernanza-plan.md)
§2 y [`whatsapp-agent-auditoria-rigidez-2026-07-29.md`](../whatsapp-agent-auditoria-rigidez-2026-07-29.md)
para el diagnóstico completo.

#### Suspender en vez de destruir + rastro del turno (É-F4 Fase 1, 2026-07-30)

**Un compromiso de identidad nunca desaparece, se suspende** (R5/R8). Los 4
sitios que antes hacían `flow.pop(...)` sobre un reto en curso ahora guardan
su estado en el slot único `flow['suspended'] = {'kind': <clave>, 'state':
<dict original>}` antes de popear: `_family_fail` (2 fallos reales),
`_advance_challenge` (2 fallos reales), `_advance_identity_triage` (2
"no entendí" sin resolver) y `escalate_to_human` (cualquier escalada con un
`pending_action` en curso — la urgencia SUPLANTA, no aborta, R4). Un gate de
test (`SuspendNotDestroyGateTests` en `test_policy.py`) exige que todo
`.pop()` de estas 4 claves esté justificado: suspendido, o una resolución
terminal reconocida (verificado, vinculado, declinado, tamiz resuelto).

**Resume perezoso**: `policy.evaluate` (paso 6c) reinstala `flow['suspended']`
en su clave original en cuanto NO hay ningún compromiso activo — el mensaje
siguiente cae de forma natural en los pasos 7/8/8b/8c existentes, sin
duplicar lógica de avance. Es lo que resuelve el `4586` tardío de la conv 13:
antes el reto se destruía al escalar; ahora sobrevive hasta que el cliente lo
retoma o un humano lo cancela.

**`release_conversation` cierra el círculo** (antes: conv 13 S9 — el
`HumanHandoff` quedaba con `resolved_at=None` mientras el agente ya volvía a
hablar). Al liberar: resuelve el handoff abierto más reciente
(`resolved_at` + `resolution=returned_to_agent`, `claimed_by` si nadie lo
había tomado) y decide qué hacer con `flow['suspended']` si existe — si el
contacto YA quedó verificado (`confirmed_in_chat`/`staff_verified`) por
cualquier vía mientras estaba suspendido, el compromiso se CANCELA (no tiene
sentido re-interrogar a alguien ya validado); si no, se deja intacto para
que el resume perezoso de `policy.evaluate` lo retome con el próximo mensaje.

**`HumanHandoff.reason_code`**: `'identity_ambiguous'` mintió en producción
(conv 13: los 4 factores eran correctos, nada fue ambiguo — el sistema los
tiró él solo). `REASON_IDENTITY` ahora vale `'identity'`;
`'identity_ambiguous'` queda **deprecado** — sigue en `REASON_CHOICES` solo
para no reescribir las filas históricas (migración `0011`, puramente
aditiva). No usar `'identity_ambiguous'` en código nuevo.

**`TurnDecision`** (ver tabla de modelos): un envoltorio único,
`planner.handle_inbound`, registra el veredicto de CADA turno tras llamar al
cuerpo real (renombrado a `planner._handle_inbound_inner`) — nunca puede
tumbar el turno (`try/except` + log). El harness compartido de la suite de
regresión (`tests/harness.py:run_turn`, usado por los 63 casos congelados +
4 archivos más) afirma que cada turno deja EXACTAMENTE una fila — cobertura
de exhaustividad "gratis" sobre el tráfico ya cubierto por esos tests. El
mapeo `decision → because` (`planner._infer_because`) es deliberadamente
GRUESO: Fase 1 no tiene árbitro todavía (llega en Fase 3), así que traduce
las ~20 salidas de texto libre de hoy a los 12 valores ortogonales de
`Because` con un `dict` de mapeo, no con lógica nueva de decisión.

Ver [`whatsapp-agent-f4-gobernanza-plan.md`](../whatsapp-agent-f4-gobernanza-plan.md)
§3 para el detalle de implementación.

#### Guards de conducta (É-F4 Fase 4, 2026-07-30)

`guards.check_output` juzga **lo que se dijo** (léxico: precios sin respaldo,
consejo médico, promesas, jerga). `guards.check_behaviour` juzga **cómo se está
comportando el sistema** — donde estaban los fallos más caros de la auditoría,
ninguno de los cuales era una palabra prohibida:

| Guard | Regla | Señal | Precedente |
|---|---|---|---|
| `repeated_question` | R10 | un slot con `asked >= 3` **y** el texto pregunta | conv 12: la fecha pedida 4 veces |
| `contradicts_state` | R2 | niega el historial teniendo hechos anclados | conv 13: *"no me lo dijiste aún"* |
| `unbacked_success` | BUG-AGENT-001 | afirma cita/cancelación/alta con **cero** herramientas en el turno | piloto: dio por agendada una cita inexistente |

Precisiones que evitan falsos positivos, que aquí cuestan una escalada:
- `repeated_question` exige que el texto **pregunte**: si el modelo por fin
  ofrece opciones, eso es salir del bucle, no repetirlo.
- `contradicts_state` marca solo negaciones del **historial** ("no me lo
  dijiste"), nunca peticiones de un dato que falta ("¿me confirmas la hora?").
- `unbacked_success` mira si corrió **alguna** herramienta, no si se escribió:
  confirmar tras una LECTURA es legítimo.

**Los tres nacen en `SOFT`, en modo observación**: un reintento correctivo y,
si persiste, se **envía** con log `AGENT_OUTPUT_GUARD`. Un guard nuevo en
`HARD` escala conversaciones sanas, y una escalada de más le cuesta al cliente
más que un log de más. Promover uno a `HARD` exige mirar antes esos logs — con
datos, no con intuición.

**El camino tier-0 también se valida**: las plantillas del router nunca pasaban
por los guards por ser constantes, y justo por eso nadie miraba lo que se
editaba en ellas. Un test recorre todas las `T0_*` y falla si alguna introduce
un precio, una promesa o jerga interna.

#### Autoridad del turno y compromisos (É-F4 Fase 3 · **ADR p55**, 2026-07-30)

**Un solo modelo de compromiso (R7).** Los cinco mecanismos que representaban
lo mismo —`identity_triage`, `family_challenge`, `identity_challenge` (dicts en
`Conversation.flow`), `pending_action` y `ConversationGoal`— se reducen a uno:
`ConversationGoal`, **extendido**, no reemplazado. Los tres primeros salieron
de `flow` (gate: `IdentityStateLivesInTheModelGateTests` sobre 5 módulos de
runtime). `pending_action` **sigue en `flow`**: la confirmación tier-2 queda
fuera del alcance por decisión del plan (§11) y unificarla es otro sprint.

Ciclo de vida (ADR p55 §3) — un compromiso **nunca desaparece**:

| Estado | Significado | Coordenada |
|---|---|---|
| `active` | al frente | — |
| `deviated` | el agente atiende otra cosa y **vuelve** | `return_to` (obligatorio) |
| `suspended` | otro compromiso tomó el frente; se **ofrece** de vuelta | `supplanted_by` |
| `blocked` | el **dominio no puede** (p.ej. `no_vet`) → se dice una vez y se deja de pedir | `blocked_reason` |
| `completed` / `abandoned` / `handoff` | terminales | — |

Dos distinciones que antes colapsaban y ahora no: **`suplantar` ≠ `abortar`**
(un perro que convulsiona a mitad de agendar no abandonó la cita) y
**`bloqueado` ≠ `abandonado`** (el dominio no puede vs. el cliente no quiere —
quien pide alta sin cita cae en el segundo: es política de clínica, el dominio
sí podía).

**Todo factor lleva su `why` (R9 estructural).** `Factor(name, why, validator)`
sustituye a `required_slots` + `validators`; **un factor sin `why` no compila**.
El motivo se escribe en voz de clínica y hay gate (`WhyVoiceTests`) que prohíbe
vocabulario de sistema — precedente: *"el sistema me pide al menos una fecha"*
(conv 12). Como el `why` es por factor y no global, el alta explica su fecha
distinto que una cita normal (*"el alta la hacemos junto con tu primera
cita"*), que es lo que cierra R6 sin necesitar la fase cancelada.

**El árbitro** (`agent/arbiter.py`): `decide(facts, commitment) → TurnVerdict`,
función **pura**. Cinco veredictos cerrados (`continuar` · `desviar` ·
`suplantar` · `abortar` · `responder`); un sexto exige ADR. Decide **control de
flujo, nunca contenido** — prueba: *¿se puede renderizar el veredicto en otro
idioma o canal sin tocar el árbitro?*

Los cinco presupuestos son tests bloqueantes (`test_arbiter.py`), no buenas
intenciones — el precedente es `policy.evaluate`, que nació como "un router de
predicados" y llegó a 203 líneas y 20 pasos un sufijo `b` a la vez:

| | Mecanismo |
|---|---|
| A1 | 5 veredictos, enum cerrado |
| A2 | pura: corre en `SimpleTestCase` (sin DB), no muta sus entradas |
| A3 | no importa matchers, modelos ni Django; `decide` solo construye su propio resultado |
| A4 | presupuesto de **6 ramas** por `ast` + "cabe en una tabla" (≤40 líneas) |
| A5 | no menciona salvaguardas; y se verifica que urgencia/bloqueo/humano/opt-out sigan corriendo **antes** en `policy.evaluate` |

Lo que el árbitro **no** decide, a propósito: escalar a un humano (es
salvaguarda, y las salvaguardas lo preemptan) y el **tope de desvíos** — él
juzga *un mensaje*, y que tres desvíos seguidos merezcan una persona es un
juicio sobre el *patrón*, que vive en el ejecutor.

**A6 · el ejecutor consume veredictos, no los reinterpreta.** El flanco que
abre un árbitro puro: mover el comportamiento a la capa de al lado y quedarse
con *árbitro mínimo → ejecutor enorme* no simplifica, solo desplaza. Reaccionar
a una **secuencia** es legítimo (`desviar ×3 → handoff`); **reetiquetarla** no
(`desviar → "en realidad era un fallo"`) — eso es exactamente la conv 13. Se
sostiene por construcción: cada veredicto lleva **su propio contador**
(`working_state['deviations']` vs `attempts_failed`) y ningún ejecutor toca el
del otro. Gate estático (`ExecutorConsumesVerdictsTests`) + prueba de que dos
desvíos y un dato equivocado dejan 2 y 1, nunca 3.

> **Alcance del gate** (dicho para que no se asuma de más): cubre la única
> frontera con veredictos ejecutándose hoy —el desvío en un reto de identidad—.
> `suplantar`/`abortar`/`responder`/`continuar` no tienen ejecutor propio
> mientras el árbitro no sea dueño de las 22 salidas del planner, y sobre ellos
> el gate no dice nada. La obligación de crecer **es un test**
> (`test_every_executed_verdict_declares_its_counter`): ejecutar un veredicto
> sin declarar su contador se pone rojo — no depende de que alguien lea una
> nota.

**Tools con autoridad cero.** `ToolOutcome` pierde `reply_text`,
`needs_confirmation` y `confirmation_text`: con ellos una herramienta podía
**escribirle copy al cliente** y **cerrar el turno**. Ordenarlas al final de la
jerarquía no bastaba — mientras conservaran la capacidad, la jerarquía era
decorativa.

Ahora una tool **propone** un compromiso persistiéndolo (`stage_pending` para
tier-2, `goals.start_identity` para un reto) y devuelve **hechos**. El planner
fotografía las propuestas abiertas *antes* de la llamada (`_open_proposals`) y
compara después (`_new_proposal`): si apareció una nueva, él decide cerrar el
turno y él redacta.

> Se compara el **contenido**, no la presencia: un `pending_action` puede
> preexistir al turno (policy paso 7 con veredicto `unclear` cae al planner sin
> descartarlo), y preguntar "¿hay pending?" haría que el planner cerrara el
> turno por una propuesta vieja.

**La barrera tier-2 no se movió** (§11 del plan): la afirmativa sigue
ejecutando los argumentos **staged**, jamás regenerados (TC-SEC-03).
`confirmations.py` y `_commit_pending` quedaron intactos — lo único que se
retiró es la capacidad de la tool de terminar el turno por su cuenta. El
parafraseo ya vivía en el `pending_action`; la bandera del `ToolOutcome` era
redundante.

> **Cerrado en el orden 8 (G07, 14-11-2026)**: desde É-F5 Fase 4 el árbitro
> corre en todos los turnos y `verdict` guarda su veredicto; sin compromiso en
> juego es `responder`. El modelo ahora solo admite esos cinco valores o vacío
> (`TurnDecision.Verdict`, validado por `full_clean()` al guardar). Vacío
> significa que el árbitro lanzó una excepción, lo que solo pasa fuera de B3
> (bajo B3 el turno falla). La salida del planner (`reply`, `silent`…) sigue
> en `facts_produced['salida']`, como diagnóstico.

#### Que el modelo vea la verdad (É-F4 Fase 2, 2026-07-30)

**Autoría de salientes (R11)**. `enqueue_outbound` tiene default
`author='system'`: hay que **optar** por afirmar que un texto es voz propia del
agente. La regla es una sola —

| `author_type` | Qué es | Quién lo pasa |
|---|---|---|
| `agent` | lo redactó el modelo este turno | solo `planner_reply`, y el parafraseo tier-2 (lo **propuso** el modelo con su tool call; §11 del plan deja tier-2 intacto) |
| `system` | plantilla tier-0 o texto fijo del router/planner | todo lo demás (default) |

`prompts.assemble_messages` deja de mapear por `direction` y etiqueta por
**autoría**: `system` → nota `role:'system'` (dato, con el texto, **sin** turno
`assistant`: el cliente lo recibió pero el modelo no lo redactó), `human_staff`
→ nota + el `assistant` de siempre (conservarlo evita que el agente contradiga
a su compañero — eso ya estaba bien), `agent` → `assistant` a secas. El
`SYSTEM_PROMPT` (**`reception-f4-v8`**) explica qué son esas notas; las notas
en sí son hechos, nunca órdenes (G6). Sin esto el modelo se disculpaba por
mensajes del router (conv 13, CR-6).

> **Colateral obligatorio**: `metrics.py` cuenta la latencia de respuesta sobre
> `agent` **y** `system`. Una plantilla tier-0 es la respuesta que el cliente
> recibió —y la más rápida—; filtrar solo por `agent` dejaría fuera justo esas
> y el p95 se vería peor de lo que es.

**Ventana por TURNOS, no por mensajes (R2)**. `HISTORY_TURNS = 12` (+
`HISTORY_MESSAGE_CAP = 40` como tope duro de filas leídas). Un turno corta al
cambiar de dirección y entre dos entrantes que **no comparten `available_at`** —
el worker ya asigna el mismo a toda una ráfaga, así que agrupar sale **sin
estado nuevo** (los 7 mensajes de la conv 12 comparten `21:19:06`). Un entrante
sin `available_at` (fixture o fila legacy) es su propio turno: nunca se agrupa
por ausencia de dato. Antes, en la conv 13, 6 de los 12 huecos eran plantillas
y uno el "ok" de un humano — los tres hechos centrales quedaron fuera (CR-3).

**Hechos de identidad anclados (R2)**. El bloque `DATOS` lleva ahora
`identidad: {ya_dijo_que_es_cliente | dijo_que_es_su_primera_vez,
titular_declarado, verificacion_pendiente}`, derivado de lo que el router ya
sabía (`identity_triage_done` + el reto **activo o suspendido**). Salir de la
ventana hace perder el **fraseo**, nunca el **hecho**: es la otra mitad del
"no me lo dijiste aún" de la conv 13 — el modelo decía la verdad sobre un
contexto amputado.

**Aviso de fuera de horario con oportunidad**. `_after_hours_prefix` recibe el
`burst_text` y se calla si `matchers.is_complaint_or_meta` da positivo. La
lista de lemas es **estrecha a propósito** (reclamo/meta-pregunta, no cualquier
pregunta: ante "¿cuánto cuesta?" el aviso sí es pertinente). Al suprimirlo
**no** se consume `flow['after_hours_notified']` — el turno normal siguiente sí
lo lleva. En la conv 13 ese aviso cayó en medio de una queja por pérdida de
contexto y **causó** el mensaje siguiente.

## Endurecimiento É-F3 W0 (2026-07-24)

Correcciones de la [auditoría conversacional](../whatsapp-agent-auditoria-conversacional-2026-07-24.md); plan en [É-F3](../whatsapp-agent-epica-f3-conversacion-por-objetivos.md).

| # | Cambio | Contrato nuevo |
|---|---|---|
| W0-1 | Horarios con el reloj de la ORG (`org_today_local`/`org_now_local`), no del proceso (`TIME_ZONE='UTC'`) | Toda comparación de "hoy"/"ya pasó" en slots usa la zona de la clínica |
| W0-2 | El Policy Engine evalúa la **ráfaga completa** (`burst`), no solo el último entrante | Urgencia, petición de humano, opt-out y confirmación se detectan en cualquier mensaje del grupo |
| W0-3 | Turno aislado: `try/except` por conversación + `process_attempts` + dead-letter | Un turno que revienta reintenta 3 veces y luego descarta + escala; **nunca** tumba el worker |
| W0-4 | Urgencia notificada a ops (webhook Discord) + prioridad en `/inbox` | `HumanHandoff(priority=urgent)` dispara aviso (sin PII) y la bandeja ordena urgentes primero |
| W0-5 | Se agenda con el veterinario **libre**, no con "el primer VET por pk" | Ver §Asignación de veterinario |
| W0-6 | Aviso de privacidad just-in-time | Se emite una vez por contacto, antes del primer reto de identidad o alta (`privacy_notice_sent_at`) |
| W0-7 / B3 | Transacción corta + lease/token de TurnWork; processing_until solo proyección | La red del planner queda fuera de la transacción; el transporte sender legacy conserva su frontera pendiente B4 |

### Configuración de clínica: fuente única (ADR p53)

Todo lo que el agente sabe de la clínica sale de `agent/clinic_context.py`, y
solo hay **una** superficie donde se edita: `/config` (Configuración).

| Dato | Fuente única | Dónde lo edita el ADMIN |
|---|---|---|
| Horario (slots, "¿abierto ahora?", aviso de fuera de horario) | `OrganizationSchedule` — 7 filas sembradas al crear la org (`create_default_schedule`); respeta `is_closed` y descanso | Configuración → Horario (`ScheduleSection`) |
| Teléfono (incluida la **plantilla de urgencia**), dirección, mapa, indicaciones, correo, sitio | `Organization` | Configuración → Clínica (`ClinicSection`) |
| FAQ libre (estacionamiento, aviso de privacidad…) | `AgentSettings.faq_facts` | `PATCH /api/inbox/settings/` |
| Nombre de la clínica (saludo, preámbulo, contexto `clinica`) | `Organization.public_name`: el comercial o, si falta, el legal (ADR p70 D5) | Configuración → Clínica |
| Cierres excepcionales (días festivos) | `OrganizationClosure` (ADR p70 D6) | Configuración → Horario → Cierres |

Puntos únicos de resolución: `effective_business_hours()`, `clinic_phone()`,
`clinic_facts()`, `humanize_schedule()`, y para una **fecha concreta** `day_ranges(org, day)`
(las franjas del día de la semana, o ninguna si un cierre vigente cubre esa fecha) y
`closed_today(org)`.

**Cierres excepcionales (ADR p70 D6, plan F2.1):** un día cerrado no ofrece huecos
(`find_available_slots`, `suggest_retention_slots` y la comprobación de una hora exacta usan
`day_ranges`), la operación
autorizada no agenda ni reagenda ahí (`schedule_closed`, revalidado bajo `FOR SHARE` de la fila
del horario en `appointments.creation`/`mutations`) y, si el cierre es hoy, «¿abierto ahora?» es
falso, así que se antepone el aviso de fuera de horario. `weekday_ranges` sigue describiendo el
horario **semanal** (lo que el agente cuenta del horario). Al personal no lo bloquea. Cualquier superficie nueva que pregunte
por horario o contacto pasa por ahí — no por `AgentSettings`.

### Gate del kill switch: `enabled=True` exige teléfono de clínica

No debe existir la combinación `AgentSettings.enabled=True` + `Organization.phone`
vacío o inválido. **No es UX, es seguridad**: el agente atiende urgencias, y la
plantilla de urgencia le dice al cliente *"acude de inmediato a la clínica"* — sin
teléfono, sin número al que llamar. Ese estado no debe ser alcanzable,
independientemente de si el ADMIN pasó por el onboarding nuevo o venía de antes.

- `PATCH /api/inbox/settings/` con `enabled: true` valida
  `apps.core.validators.is_valid_mx_phone(organization.phone)` → si no pasa, **400**
  con mensaje accionable que apunta a Configuración → Clínica. El predicado (en vez
  de `bool(phone)`) cubre las filas guardadas **antes** de que el serializer validara
  (un `"5"` histórico no habilita el agente).
- **Apagar nunca se bloquea** (`enabled: false` siempre pasa): es el kill switch.
  El gate tampoco bloquea editar `faq_facts` sin teléfono.
- El **horario NO entra** en el gate: `create_default_schedule` lo siembra al crear
  la org, así que "tiene horario" es verdadero desde el segundo cero y bloquear
  sobre una señal siempre verdadera no protege de nada.
- La UI de `/inbox` muestra el motivo del backend + atajo "Ir a Configuración"
  (nunca un error crudo).
- **INV-L, en los dos lados (ADR p70 D2).** El gate del serializer solo adelanta el
  mensaje; la garantía vive en los modelos:
  - `AgentSettings.save()` con `enabled=True` bloquea primero la fila de la
    organización (`lock_organization_phone`, `FOR NO KEY UPDATE`) y relee el teléfono
    persistido;
  - `Organization.save()` impide que un teléfono válido se vacíe o se vuelva inválido,
    comparando contra el persistido bajo el mismo bloqueo.

  Escritores enumerados el 2026-11-26: API de Configuración, admin de Django,
  `seed_demo_clinic`, `agent_eval` (ahora captura el teléfono antes de crear el agente
  encendido), `provision_channel` y la vista del Inbox (ambos crean apagado). Un gate
  estático (`apps/agent/tests/test_inv_l_clinic_phone.py`) impide `update()`/
  `bulk_update` que eviten `save()`. Las fixtures usan
  `apps/agent/tests/agent_settings_fixtures.py`. La migración `agent.0031` apagó los
  agentes sin teléfono válido.

**División de responsabilidades**: el onboarding (`FirstRunAssistant`, hito
`has_clinic_contact`) **educa** — te lleva al dato cuando arrancas; este gate
**garantiza** — impide el estado peligroso. Ninguno sustituye al otro.

**`AgentSettings.business_hours` se eliminó** (migración `0009`). Era una
segunda superficie de escritura del horario: el ADMIN podía configurarlo en
Configuración y el agente usar otro. Además dejaba dos modos de fallo — el
aviso de fuera de horario leía solo el legacy (una clínica migrada nunca decía
que estaba cerrada) y la plantilla de urgencia también (quedaba sin número al
que llamar).

`faq_facts` sobrevive **solo** para hechos sin campo propio: el serializer
rechaza las claves reservadas (`telefono`, `direccion`, `horario`, `correo`,
`mapa`, `indicaciones`…) con 400.

Semántica de horario, deliberada: **sin filas** → `is_open_now` devuelve `None`
y no se antepone aviso (no se inventa nada, G1); **filas con todos los días
cerrados** → `False`, y el aviso sí se emite.

### Asignación de veterinario (Q14, revisado 2026-07-25)

Decisión de producto del PO: **a la clínica le da igual quién atienda**. El
sistema no elige "un veterinario asignado al bot"; elige al que está **libre**.

| Configuración | Comportamiento |
|---|---|
| `default_veterinarian` **sin** configurar (default) | Candidatos = todos los **clínicos** activos de la org (VET, o ADMIN que atiende pacientes; ADR p66), menos los **ausentes ese día** (ADR p67). Un hueco se ofrece si **alguno** lo tiene libre, y la cita se asigna al primero libre a esa hora |
| `default_veterinarian` configurado | Solo se ofertan y asignan los huecos de ese veterinario (la clínica eligió explícitamente), si atiende pacientes; si no, se usan todos los clínicos |
| Sin ningún clínico activo | `no_vet` → el agente se disculpa y ofrece pasar con una persona. Es el único caso honesto: no hay con quién agendar |

**ADR p66 (2026-11-24):** «veterinario» ya no es `role='VET'`. Candidatos (`_scheduling_vets`), alta
(`appointments.creation`, `require_schedule`), reagendado (`appointments.mutations`) y ejecución autorizada
(`operation_execution`) usan el predicado único `apps.users.professional.clinician_q` / `is_clinician`: el
dueño veterinario con rol ADMIN marcado como que atiende recibe huecos. Los adapters B8 siguen apagados.

**ADR p68:** `get_offered_specialties` cruza por **código** del catálogo cerrado
(`apps.users.specialties`) los servicios activos con especialidad y los clínicos activos con
esa especialidad; devuelve la etiqueta. Antes comparaba textos libres por tokens.

**ADR p67:** un veterinario con ausencia vigente no tiene huecos ese día. `_present_vets` lo
excluye en `_free_slots_for_day`, `_exact_slot_status` y `pick_free_vet`; si nadie queda, la hora
sale `slot_taken` y se re-oferta. `validate_creation` (B8B) y `validate_mutation` (B8C) lo
revalidan bajo lock con la razón `veterinarian_absent`, añadida a `PRECONDITION_REASONS`.

Por qué importa: con "el primer VET por pk" la capacidad ofertada era la de
**un** veterinario aunque hubiera tres, y toda la agenda del bot caía sobre el
mismo. La ocupación del día se resuelve en **una sola** llamada a la API
(`GET /appointments/?date=`) agrupando por veterinario, no una por vet.

**Ocupación por intervalos (deuda MP-5 de la auditoría, revalidada en el
orden 8, G09).** Desde B2 (`9ccc31a`, 15-09) `_day_occupancy` guarda el
inicio y el fin de cada cita activa, y `_vet_free` descarta un hueco que se
solape con cualquiera de ellas. Por eso una cita larga (09:00–10:30) tapa
todos los huecos que cubre y una cita fuera de la rejilla (09:15–09:45) tapa
los dos que pisa; `check_appointment_slot` detecta también el solape parcial.
Lo fijan las pruebas de `tests/test_slots.py`.

Límite que queda: el agente ofrece citas de **30 min** (`SLOT_MINUTES`, la
misma duración que la atención sin cita), en pasos de 30 desde la apertura de
cada tramo del horario. Una ventana libre fuera de esa rejilla (las 09:15 tras
una cita de 09:00 a 09:15) no se ofrece, y el dominio no tiene duración por
servicio. El dominio revalida el solape real al crear (INV-D); si pierde la
carrera, el agente re-oferta.

### W1 — experiencia y conservación vinculante

Enmienda E2 del PO: **ninguna regla se eliminó**. Las verificables en código
pasaron del prompt (advisorio) al runtime (vinculante); el resto se reescribió
como conducta. Regla de oro: *si una regla sale del prompt, entra al código con
un test que la ancle.*

| # | Cambio | Contrato nuevo |
|---|---|---|
| W1-1 | `agent/guards.py`: filtro determinista sobre el texto generado | Precio sin respaldo de tool, consejo médico o promesa ⇒ 1 reintento con corrección ⇒ si persiste **no sale**: plantilla + handoff. G1/G2/G3/G7 dejan de ser advisorias |
| W1-2 | Prompt `reception-f3-v6`: mismas reglas en forma conductual + 4 ejemplos + formato WhatsApp (`*negritas*`) | Sale del prompt solo lo que era parche técnico o lógica determinista duplicada |
| W1-3 | Hilo de herramientas real (`assistant` con `tool_calls` + `tool` con `tool_call_id`) | El modelo ve sus propias llamadas: deja de repetir tools y de auto-responderse |
| W1-4 | Debounce por ventana silenciosa (8 s, tope 25 s) + descarte del saliente si llegó un entrante nuevo | La ráfaga humana se responde en UN turno. Solo se descartan respuestas de **texto puro** (nunca una confirmación) |
| W1-5 | Presupuesto 15 → **40** · copy de escalado por motivo · acuse único en `handoff_pending` | El presupuesto deja de ser el generador principal de handoffs |
| W1-6 | Reto tolerante al nombre de pila + re-match teléfono→Owner en contactos aún desconocidos | Un cliente dado de alta después de escribir deja de ser tratado como nuevo |
| W1-7 | Media entrante (audio/imagen/sticker) responde plantilla **sin invocar al modelo** | `payload_type` mide el volumen: >15 % de audio activa el gate de transcripción (UX-14) |
| W1-8 | 400 del dominio mapeado por su contenido (`map_domain_400`) | `slot_taken` solo cuando de verdad hay solape; el resto se pide o se registra |
| W1-9 | Saludo institucional + aviso de fuera de horario con el agente ENCENDIDO | T0-GREET deja de existir solo en el buzón apagado |
| W1-10 | `proactive_opt_out` ≠ `is_blocked` · mensajes de staff humano al contexto | Un "ya no me escriban" corta proactivos, no silencia al cliente |

### W2 — conversación por objetivos

El agente pasa de `mensaje → intent → tool → respuesta` a
`objetivo → qué me falta → lo obtengo → cierro`. La capa estaba **diseñada**
(arquitectura §7.3: `flow.name` + `flow.slots`) y nunca se implementó.

| Pieza | Contrato |
|---|---|
| `agent/goals.py` | Catálogo cerrado de **4 objetivos, solo multi-turno**: `schedule_appointment`, `register_and_schedule`, `cancel_appointment`, `reschedule_appointment`. Las lecturas de un turno NO llevan objetivo (es lo que impide que esto sea un motor de diálogo genérico) |
| Contrato de slot | **nombre + validador**, nada más. Sin extractores (el LLM propone el valor; el código lo valida) y **sin copy** (el objetivo publica `missing`; cómo se pregunta es del modelo) |
| Confianza | El modelo acompaña cada dato con `<slot>_confidence`. Por debajo de `AGENT_SLOT_CONFIDENCE_THRESHOLD` (0.70) el slot **no se llena**: pasa a `por_confirmar`. Filtro EN SERIE con el validador, no alternativo. Ausente ⇒ 1.0 (compatibilidad) |
| Herramientas de escritura | `required: []` y parámetros `<slot>_confidence` (los inyecta `as_openai_tools`). Llamada **parcial** = normal: persiste lo válido y devuelve qué falta. Antes eran todo-o-nada y el modelo inventaba lo que faltaba |
| Interrupción | Una lectura intercalada **pausa** el objetivo (no lo destruye) y se retoma con los slots intactos — spec §2.7, inejecutable hasta ahora |
| Estancamiento | 3 turnos **sin progreso** ⇒ escalada semántica (`T0_GOAL_STALLED`). Sustituye al presupuesto contable como disparador principal. Ver §Progreso abajo — la definición de "progreso" es lo que hace que esto funcione |
| Cierre | `completed` solo donde consta que el dominio aceptó la escritura (commit tier-2); `handoff` al escalar; `cancelled` al abrir otro objetivo |
| Métricas | `compute_goal_metrics`: abiertos, completados, tasa, por estado, por objetivo y **slots donde se atoran** — el embudo deja de inferirse de nombres de herramienta |

**No se tocó** ninguna barrera de control: el objetivo vive DESPUÉS del Policy
Engine y ANTES de la confirmación tier-2. El parafraseo por plantilla, el
commit de args staged y TC-SEC-03 siguen exactamente igual.

#### Progreso del objetivo (corrección 2026-07-29)

**Un dato que el cliente ya dio no se vuelve a pedir.** Tres reglas lo sostienen,
las tres nacidas del piloto (conv. 12 de `Clinica Bebe coche`: el agente pidió la
fecha **4 veces** — `asked = {'date': 4, 'time': 4}` — con `stall_turns = 0`,
después de que el cliente la diera *y el propio agente la dijera en voz alta*):

| Regla | Contrato |
|---|---|
| `filled` ≠ `advanced` | `goals.capture` compara contra una foto previa de los slots. **`filled`** = lo que la llamada escribió; **`advanced`** = un slot vacío se llenó, o el cliente **corrigió** uno ("martes → jueves"). Solo `advanced` resetea `stall_turns`. Reafirmar lo ya sabido no es avanzar |
| Estancamiento = intento **sin** avance | `planner` distingue `goal_attempted` / `goal_progressed` / `other_tool_used`. Antes bastaba con **llamar** una tool de objetivo para que el turno contara como productivo (`goal_touched`), así que un modelo repreguntando en bucle mantenía `stall_turns` en 0 para siempre — el detector era ciego justo al caso que existe para cazar |
| Las lecturas alimentan el objetivo | `find_available_slots(date=X)` captura `X` en el slot `date` si estaba **vacío** (`tools._capture_slot_from_read`). Hasta ahora el único acceso a los slots eran los argumentos de una tool de **escritura**: si el modelo resolvía la fecha, la usaba para consultar disponibilidad y se la anunciaba al cliente pero no la reenviaba al escribir, el sistema seguía reportando `me_falta: [date]`. **Solo rellena huecos** — nunca pisa lo elegido (el modelo consulta días alternativos y eso no debe borrar nada); la confirmación tier-2 sigue siendo la barrera real antes de escribir |

El modelo **nunca perdió el contexto**: `goals.context_block` le inyecta
`ya_tengo` / `me_falta` / `ya_preguntado_2_veces` en cada turno. Preguntaba
porque el sistema le decía la verdad — no tenía el dato. El defecto estaba en la
captura, no en la memoria.

`_goal_gate` publica `capturado` (= `advanced`) en el resultado de la tool, que es
la señal que el planner usa para decidir si hubo progreso. Sus salidas tempranas
también dejan `record_local`: antes una llamada parcial de escritura **no**
generaba `ToolExecution`, y la telemetría hacía creer que el modelo casi no
llamaba herramientas.

### W3 — medición de calidad conversacional

Las métricas de negocio responden *"¿agendó?"*. Estas responden la pregunta que
decide el piloto: ***"¿se siente como una buena recepcionista?"*** — con datos,
no con opinión. Todo se deriva de tablas existentes; **cero campos nuevos**.

| Métrica | Cómo se mide | Para qué |
|---|---|---|
| `latencia_respuesta_ms` p50/p95 | Del **último** entrante del cliente al saliente del agente (la ventana silenciosa del debounce es espera deseada, no lentitud). Los descartados no cuentan: nunca llegaron | Gate F1 §10.4 (<15 s) medido de verdad |
| `turnos_por_resolucion` | Mensajes del cliente en conversaciones con objetivo **completado** | Fricción real del flujo; los abandonos no contaminan el promedio |
| `tasa_repregunta` | Objetivos donde se pidió el MISMO dato ≥2 veces (`asked`) | El tic más reconociblemente robótico |
| `tasa_handoff` | Conversaciones con escalada / conversaciones (no escaladas/conversación) | Gate F1 (<40 %) |
| `pct_audio` | `payload_type` de entrantes | Trigger UX-14: >15 % ⇒ transcripción entra al gate de F2 |
| `respuestas_descartadas` | Salientes `discarded` (W1-4) | Si sube mucho, la ventana silenciosa está corta |
| `objetivos.slots_atorados` | Slots faltantes al cerrar sin completar | **En qué dato concreto** se pierde la gente |

Se exponen en `GET /api/inbox/metrics/` (bloque `calidad`) y en el comando
`agent_quality`, que además imprime la muestra de transcripts a leer: sin
lectura humana no hay ciclo de mejora, solo intuición.

## Catálogo, especialidades y escalación

- **Precios citados con IVA (ADR p70 D4).** `get_service_catalog` y
  `check_product_availability` proyectan `price_with_tax` / `sale_price_with_tax` de la
  API, nunca el precio sin IVA. El renderer determinista dice
  «$580.00 MXN, IVA incluido.». Si la API no trae el precio con IVA, es dato incompleto:
  «el equipo puede confirmar su precio». El contrato (`endpoint_contracts.py`) valida los
  campos cuando vienen.

- `get_offered_specialties` solo devuelve una especialidad si hay un servicio
  activo y al menos un miembro activo del personal con la misma especialidad.
  La proyección no expone nombres ni datos del personal.
- Una urgencia genera en el handoff un resumen categórico seguro (por ejemplo,
  "posibles convulsiones"), no el cuerpo del mensaje del cliente.
- Sin una confirmación pendiente, los acuses aislados como "ok" o "gracias"
  se distinguen de una confirmación de cita y nunca crean una cita ficticia.

## Invariantes propios (además de los globales)

1. La organización de una conversación nace del `ChannelAccount` receptor y
   NUNCA se re-deriva (R1).
2. Un wamid entrante se persiste a lo sumo una vez por canal (R5, constraint DB).
3. Cuerpos de mensaje SOLO en DB — jamás en logs ni Sentry (R15). El aviso de
   urgencia a ops lleva org, conversación y motivo: nunca texto del cliente.
4. Plantillas tier-0 son literales (contrato spec §1.3) — el copy no se
   improvisa en código.
5. Fuera de la ventana de 24 h no sale texto libre (lo valida el sender).
6. `enabled=False` no apaga la captura: solo cambia la primera respuesta.
7. Ninguna llamada de red ocurre dentro de una transacción de base de datos.
8. Un turno fallido nunca deja al cliente sin respuesta ni al worker caído.
9. El sistema es dueño del checklist del objetivo; el modelo solo redacta la
   pregunta. Ningún slot se llena con un valor que no pasó validador, y
   ninguno se llena con confianza por debajo del umbral.
10. Como máximo un `ConversationGoal` abierto por conversación (constraint DB).
11. **Toda escritura del agente sobre una cita existente viaja con su
    precondición** (INV-A), y un `409` **jamás** se reintenta sin ella: eso es
    exactamente la sobrescritura que la precondición cierra. Tampoco se degrada
    a último-escritor-gana tras N conflictos, ni se silencia el 409
    confirmándole al cliente que quedó hecho (§5.3).
12. **El alta del agente siempre pide expediente nuevo** (`require_new_owner`).
    Un teléfono coincidente localiza, nunca autoriza (INV-B): sin identidad
    verificada, escribir sobre un `Owner` existente es de una persona.
13. **`flow['suspended']` tiene un solo escritor**:
    `confirmations.suspend_pending`, que suspende, abre/retiene el hand-off y
    cambia el estado en **un commit**. Escribirlo a mano —o combinar
    `clear_pending` + `escalate_to_human` por separado— reabre el hueco por el
    que la intención del cliente se perdía en silencio.
14. **Una organización desactivada no admite trabajo nuevo** (orden 2, 28-10-2026):
    `durable.claim_turn` no reclama sus turnos y el sender devuelve a `pending`
    los mensajes reclamados que aún no se admitieron, sin tocar evidencia remota.
    Los pendientes se conservan para cuando se reactive. Contrato completo en
    [organizations.md](organizations.md).

## B4 — frontera Message / Meta (2026-09-16)

`sender.py` reemplaza el sender transaccional legacy de worker (se conserva su
import público). Claim individual UUID/lease 120 s, admisión lógica de un solo
uso, HTTP timeout 15 s fuera de DB y resultado CAS. El único outbox es Message;
migración channels.0013_b4_durable_sender aditiva. `channels/providers.py`
devuelve SendResult aceptado/rechazado conocido/incierto. `channels/delivery.py`
centraliza monotonía y `channels/status.py` correlaciona tenant/cuenta/wamid.

SENDING expirado→UNCERTAIN, nunca retry. Solo rechazo Meta 130429 explícito
4xx admite hasta cinco claims con backoff. Takeover invalida nueva admisión;
los resultados ya admitidos conservan realidad externa con token válido.
Modo planner/sender en management command y Compose; inspect_agent_outbound
expone counts/edades y el Inbox muestra incertidumbre sin otorgar emisión.
Reemisión explícita conserva original y crea Message humano supersedes.

Contrato: [B4](../contrato-sender-durable-b4.md). ADR y [acta](../implementacion-b4-agente-whatsapp-2026-09-16.md)
describen legacy, pruebas y riesgos. B0 WRITE sigue cerrado; ninguna fase B5+
se implementa como consecuencia de este cambio.


## Enmienda B5 — 2026-09-16

Prevalece el [contrato safety/handoff B5](../contrato-safety-handoff-b5md) en las fronteras afectadas.
Safety contextual precede funnel/identidad/goal/owner humano; consume TurnContext
causal y no interpreta binario ni depende del LLM. HumanHandoff es cola Inbox,
no notificación ni atención. Acuse nuevo solo por acción explícita de claim con
actor y timestamp, sin backfill legacy. No se cierran casos humanos sin resolver
por inactividad. Una guía finita por caso abierto pasa por Message/B4, bajo grant
específico mensaje/TurnWork/epoch; takeover posterior revoca admisión y no borra
realidad HTTP ya admitida. Humano activo conserva ownership y recibe prioridad
en bandeja, sin mensaje bot competidor. Múltiples casos legacy siguen visibles.

Corpus/protocolo **VETERINARY_REVIEW_REQUIRED**, automatización B5 apagada por
defecto y activación **PENDING_ACTIVATION_REQUIREMENTS**. No se atribuye revisión
clínica, notificación secundaria, SLA ni disponibilidad. WRITE autónomo cerrado;
sin B6–B9, E1–E5 ni P-A/P-B. No despliegue automático.

## Enmienda B6 — 2026-09-17

Prevalece el [contrato matter/binding B6](../contrato-matter-binding-b6md)
para continuidad semántica. ConversationGoal es una instancia de asunto con
bound_owner/bound_pet/bound_appointment y binding_revision propia; no equivale
a ownership ni identidad. Slots válidos tienen provenance schema 1 y snapshots
de dependencia. Correcciones retiran derivados y pending legacy atómicamente,
conservando aportes explícitos independientes. Legacy sin evidencia queda unknown.

Una READ pública incidental conserva el asunto. Un compuesto se aclara antes
de mezclar datos; reemplazo explícito abandona la instancia incompatible. «Olvida
eso» abandona el asunto conversacional, nunca cancela una cita. Homónimos/plural
ambiguo no crean binding. Solo nombre contextual exacto, continuación inmediata
singular y corrección explícita; referencias históricas y multi-goal avanzado
siguen fuera. El LLM no asigna entidades ni provenance y no autoriza operaciones.

Policy aplica B6 después de safety/owner B5 y antes de confirmations. Planner
recibe proyección vigente; tools validan argumentos y resultados contra scope y
revisión. TurnContext conserva causalidad y TurnChanges valida CAS al publicar
con B3. No cambios B4 ni infraestructura. WRITE autónomo permanece cerrado.
H12: alcance beta sujeto a evidencia del acta. H13: mitigación parcial, B7/E1
pendientes. Activación PENDING_ACTIVATION_REQUIREMENTS; no despliegue automático.
Véase [ADR B6](../decisions/2026-09-17-b6-matter-entity-bindingmd).

## B7A — operación persistente y permiso del actor (2026-09-18)

Nuevos módulos internos: operation_schema (v1/digest), operation_permission
(elegibilidad), operation_identity (revisión/CAS/revocación),
operation_model_contract (inmutabilidad/estados cerrados) y operations
(factory/revalidate/queries/renderer). ConversationOperation es el único modelo
nuevo; migración agent.0025_conversation_operation_b7a, aditiva y sin backfill.
Admin ofrece inspección de solo lectura sin parameters. Logs AGENT_B7A_* contienen
counts/schema, sin IDs/PII como labels. No API pública ni cambios frontend.

prepare_current se integra al flush B3 del estado B6; confirmations es fachada y
lector legacy diagnóstico. No hay consentimiento ni efecto autónomo. Registro
compuesto sigue fuera; los cinco kinds y schemas están en
[contrato B7A](../contrato-conversation-operation-b7amd). WRITE permanece cerrado.

### B7B (2026-09-20)

Actualiza el corte histórico B7A: operation_proposals concentra renderer/código,
emisión y witness de recepción; operation_consent interpreta el conjunto beta y
persiste decisión exacta/idempotente. B3 publica propuesta y vínculo en un commit;
B4 conserva lifecycle y consulta vigencia antes de admitir. B5/B6/identity/ownership
preceden la transición. No se llama al LLM ni a HTTP dentro de ese commit.

Migraciones agent.0026_b7b_consent_evidence y channels.0015_b7b_receipt_guard.
AuthorizationEvidence no es modelo y no copia transcript/digest/revisiones.
Admin de solo lectura distingue propuesta/emisión/consentimiento/NOT_STARTED.
AGENT_B7B_* usa count/schema; flag AGENT_B7B_CONSENT_ENABLED apagado por defecto.
Legacy no recibe consentimiento sintético. AUTHORIZED no ejecuta negocio;
WRITE continúa contenido. [Contrato B7B](../contrato-consentimiento-causal-b7bmd).

## Adapters B8C (2026-09-22)

RESCHEDULE_APPOINTMENT y CANCEL_APPOINTMENT entran solo por
execute_authorized_operation(UUID, ExecutionContext). No se habilitan tools WRITE
legacy ni PATCH/DELETE AGENT. FK exacta y preconditions schema 2 se contrastan bajo
locks; el ledger de Agenda prueba la transición histórica por UUID/digest. El
inspector readonly separa evidencia histórica, cita actual y reconciliación.
La evidencia histórica no afirma que el horario destino siga vigente. B0/flags
de producción OFF; asistencia/registro siguen DISABLED. [Contrato B8C](../contrato-appointment-mutations-b8cmd).

## Adapter B8D (2026-09-23)

El registry incorpora CONFIRM_ATTENDANCE por execute_authorized_operation, bajo
B0 y flag específica (ambos cerrados). REGISTER_PET continúa DISABLED/sin adapter.
Preconditions schema 3/attendance_contract 1 y parámetros v1 identifican una cita
exacta. Modo contextual policy 2: tarjeta emitida determinista, reply-to con
«sí confirmo que asistiré» o token exacto. Preguntas/afirmaciones libres y legacy
no conceden permiso. Emisión, causalidad, revisiones y TTL B7B/B8A se conservan.
Ledger histórico B8C con auditoría única permite replay sin transición ni cache
duplicada. Inspector distingue confirmed histórico de estado actual. Producción
OFF, PENDING_ACTIVATION_REQUIREMENTS y sin B8E. [Contrato](../contrato-confirm-attendance-b8d.md).
## Adapter B8E — REGISTER_PET (2026-09-25)

Nueva alta individual por `execute_authorized_operation(operation_key, context)`.
B6.change registra explícitamente pet_name/pet_species/pet_birth_date e invalida
operaciones al corregirlos. No se añade extractor ni tool legacy. B7A conserva
parámetros v1; preconditions 4/registration_contract 1 incluye snapshot del owner
en el digest. B7B muestra propietario, definición y desconocidos. Schema legacy
no obtiene ejecución retroactiva; CONTEXTUAL_DECLARATION no se habilita para Pet.

LOCAL_ATOMIC incluye guard final, locks, alta por patients.creation, ledger
PetRegistrationEffect, ToolExecution y resultado. La conciliación usa operation_key
exacta, nunca similitud de mascotas. Historia y estado actual se distinguen en el
inspector readonly. No hay creación implícita de owner, cita ni clínica.

Los cinco adapters existen; todos siguen productivamente OFF. B0 cerrado,
AGENT_B7B_CONSENT_ENABLED=False, AGENT_OPERATION_EXECUTION_ENABLED={} y
PENDING_ACTIVATION_REQUIREMENTS. Sin deploy, B9 ni extensiones E/P.
[Contrato](../contrato-register-pet-b8e.md), [ADR](../decisions/2026-09-25-b8e-register-pet.md),
[acta](../implementacion-b8e-agente-whatsapp-2026-09-25.md).

## B9A: harness de aplicación bajo contención

[Contrato](../contrato-harness-b9a.md) y [acta](../implementacion-b9a-agente-whatsapp-2026-09-26.md).
Los comandos eval ofrecen `--application-e2e` con PostgreSQL local aislado y
artefacto requerido. Recorren HTTP, worker y sender reales con proveedor externo
controlado. El worker conecta consentimiento B7B con el guard único B8A bajo
la transacción B3; B0/B7B/flags siguen cerrados por defecto. No se activan clínicas
ni se amplía el alcance administrativo de los cinco adapters. B9 permanece
IN_PROGRESS; B9B–B9E no están implementados por este hito.

## B9: proveedor y presupuesto operativo (2026-09-27)

[Contrato B9B](../contrato-presupuesto-turnwork-b9b.md). Los tres call sites
comparten admisión durable por TurnWork antes del POST no streaming compatible
con OpenAI. La selección de modelos por rol es configuración, no retry remoto.
Cada retry del planner obtiene otra admisión; el proveedor no ofrece en este
adapter un mecanismo de idempotencia/consulta de resultado recuperado.
Timeout o usage ausente conservan cupo. El adapter preserva enteros de usage
no negativos, incluidos ceros explícitos; otros valores son NULL. Un JSON de
argumentos inválido conserva el usage que sí reportó el proveedor. No se
introducen precios, cache o fallback nuevos. Privacy: sin prompts/respuestas
en contabilidad; errores y finish_reason usan vocabularios cerrados.

Sin deploy ni activación. B9 IN_PROGRESS; aceptación del componente en curso.

## B9C — Concurrencia de trabajo por organización

`durable.claim_turn` serializa adquisiciones con la fila Organization existente
(NO KEY UPDATE SKIP LOCKED). `active_org_work` deriva ocupación de TurnWork,
lease DB, tenant y epoch. La constante de release `ORG_ACTIVE_WORK_LIMIT = 1`
no es config opcional ni presupuesto por minuto. Ausencia de AgentSettings
mantiene el límite. No modelos/campos/migraciones nuevos.

`process_pending_conversations` excluye orgs ocupadas antes del corte del lote;
el claim atómico sigue siendo autoridad. Saturación no incrementa intentos,
asigna miembros ni consume LLMCall. B3 conserva retry, 15 min lease, 12 min
deadline, token/epoch y máximo tres intentos; completion/retry/failure/takeover/
expiry retiran ocupación según esa máquina existente. B9B conserva consumo del
mismo trabajo tras recuperación. Ningún lock cubre provider HTTP.

`_claim_turn_locked` es primitiva interna B3: solo el claim admitido y la
recepción safety atómica pueden llamarla. Safety debe completar todo antes del
commit; nunca entrega otro planner ni confirma un segundo PROCESSING. El
webhook conserva su fallback de inbound pendiente ante error SQL. Permisos de
guidance, takeover, consentimiento B7B y guard B8A mantienen autoridad propia.

`compute_concurrency(org)` expone snapshot readonly; no force-release. Harness
B9A observa capacidad antes de wire y registros de claim; corpus B9C prueba
N=1, carrera, crash/restart, stale y SCALE-01/02 con PostgreSQL multiproceso.
Ver [contrato](../contrato-concurrencia-b9c.md),
[ADR](../decisions/2026-09-27-b9c-turnwork-concurrency.md) y
[acta](../implementacion-b9c-agente-whatsapp-2026-09-27.md).
B9E conserva aceptación integral; no hay nuevas capacidades activadas.
## B9D — Readiness por release (2026-09-29)

- `beta_release.py`: valores inmutables Evidence/OrganizationApproval/Release,
  fuente productiva vacía y derivación READY/PENDING_ACTIVATION_REQUIREMENTS.
- `operation_execution.py`: consume el gate después de las autoridades
  existentes y antes de nuevos efectos. No altera conciliación de resultados.
- `management/commands/agent_inspect_beta.py`: consulta de organización explícita,
  sin crear AgentSettings ni cambiar approvals.
- `tests/test_b9d_release.py`: requisitos/procedencia, scopes, cinco adapters,
  retirada, nueva aprobación, operación antigua, rollback SQL e inspector.
- `tests/b9d_support.py`: solo PostgreSQL test_ y TEST_EVIDENCE; no es evidencia
  operacional. Los harness históricos la abren explícitamente junto a sus gates.

No se agregan modelos ORM, migraciones, API administrativa ni flags. Una
capability del LLM no puede aprobar el release. La edición autorizada ocurre en
el proceso de release con revisión humana y referencias externas. Los permisos
de Inbox/AgentSettings no conceden ese acceso al código. Mantener las referencias
privadas fuera de logs/prompts. [Contrato](../contrato-beta-release-b9d.md),
[acta](../implementacion-b9d-agente-whatsapp-2026-09-29.md).

## B9E — aceptación PROFILE-BETA-1 (2026-09-29)

El perfil técnico congelado se ejecutó con PostgreSQL real aislado, dos planners,
un sender y los proveedores controlados B9A. El primer ensayo base incumplió el
p95 canónico inbound sano→claim (21,726 s frente a 10 s); la variante con LLM
bloqueado también (22,049 s). Las demás fronteras medidas no revierten ese
fallo. El runner real hace dos llamadas LLM por turno READ básico, mientras el
modelo del perfil especifica una. No se redujo el threshold ni se alteró runtime.

La READ pública mantiene acceso sin identidad con WRITE cerrado; la personal
requiere verificación vigente, vínculo owner/pet y tenant. El gate de release B9D
se aplica a WRITE, no se traslada automáticamente a READ. Esta constatación
técnica no aprueba la READ para una clínica real. Ver
[perfil](../evals/profile-beta-1-v1.json),
[método](../evals/profile-beta-1-methodology.md),
[resultados](../evals/b9e-load-summary.json) y
[decisión](../reporte-aceptacion-b9-profile-beta-1-2026-09-29.md).

B9 sigue IN_PROGRESS, PROFILE-BETA-1 FAIL y activación
PENDING_ACTIVATION_REQUIREMENTS. Los defaults productivos continúan cerrados;
no hubo clínica activada ni despliegue.


## Enmienda B3/C4/W1 v1 — 2026-09-30 (FROZEN)

La espera preclaim queda enmendada por [elegibilidad monotónica preclaim](../contrato-elegibilidad-preclaim-b3-c4-w1-v1.md).
Antes de READY se conservan 8 s / cap 25 s; después del vencimiento, inbound
ordinario anterior al claim se incorpora elegible al mismo conjunto. El claim
sigue congelando membership/TurnContext/anchor/cursor, con continuación B3
para input posterior. READY no concede autoridad ni capacidad. Los recibos
históricos y gates productivos cerrados conservan su estado.

## Implementación de elegibilidad monotónica — 2026-09-30

Enmienda congelada `2f259f4d21802d00e705c3f7fc71e7e26f5694fa`; runtime/tests
`83285eb096a568dbeb1d67a5c98001dc0bee8352`. Ingest usa DB now fresco después
del mutex Conversation y conserva el deadline vencido para todo inbound
ordinario preclaim. No crea estado READY durable, TurnWork anticipado ni schema.
El selector E4 permanece KEEP y la continuación postclaim conserva su frontera.

Ver [acta de 60 campos y evidencia](../implementacion-elegibilidad-monotonica-preclaim-2026-09-30.md):
758 IDs únicos aprobados, incluidos 33 nuevos; races/FI con PostgreSQL real.
La causalidad se prueba directamente, incluyendo 7 incorporaciones READY bajo
condiciones del perfil. Diagnóstico sano p95 base 9.429650 s; LLM bloqueado
10.381673 s frente al gate original 10 s. **VERIFIED_SEMANTICS / PERFORMANCE_STOP**:
no se gastó rerun de acceptance. Hace falta una decisión E4 adicional separada.
B9 IN_PROGRESS, B9E FAIL, PROFILE histórico FAIL; producción cerrada, sin deploy.
