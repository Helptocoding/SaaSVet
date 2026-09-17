# ADR p60 — Decisiones de arquitectura y operación del WhatsApp Inbox v1

> **Enmienda vigente B4 (2026-09-16):** la sección B4 final y el
> [contrato sender](../contrato-sender-durable-b4.md) sustituyen el sender
> pendiente del corte B3: claim/admisión, evidencia externa e Inbox honesto.
> No cambian la idempotencia humana ni habilitan WRITE.

> **Enmienda B3 (2026-09-15).** Claim humano, respuesta que toma ownership,
> release y reset usan lock de Conversation e invalidación común de epoch.
> Pendientes bot identificables se descartan; enviados no se borran. Sender
> actual acepta PENDING B3 válidos y descarta legacy sin epoch como
> legacy_unverified. Idempotencia humana permanece; B4 externo no implementado.
> [Contrato B3](../contrato-trabajo-durable-b3.md) y
> [cutover/rollback](../runbooks/agent-whatsapp.md#b3-despliegue-controlado-y-rollback).

**Fecha**: 2026-08-22
**Estado**: **ACEPTADO** (PO, 2026-08-22); D-1..D-10 cerradas. La ejecución de las tareas se sigue por separado en el plan.
**Plan**: [`plan-implementacion-whatsapp-inbox-2026-08-22.md`](../plan-implementacion-whatsapp-inbox-2026-08-22.md)
**Alcance**: cierra D-1..D-10; no declara implementadas las tareas posteriores.

---

## 1 · Contexto

El backend del Inbox ya tiene aislamiento por organización, permisos granulares,
deduplicación de webhooks, outbox con reintentos y ventana de 24 horas. Antes
de este ADR, los puntos por cerrar estaban concentrados en retención/storage de media,
semántica multiusuario, operación humana y realtime.

Este ADR fija el contrato v1 para que la implementación no vuelva a decidir
estas reglas dentro de cada PR. Cuando una decisión incluya un gate de
cumplimiento o de infraestructura, «aceptada» significa que la arquitectura está
elegida; no autoriza a omitir el gate antes de producción.

---

## 2 · Decisiones aceptadas

### D-1 · Retención de media: 180 días, borrado físico

- El plazo aplica al **binario** de imagen, audio, video o documento recibido,
  no al texto del chat ni a la fila `Message`.
- Al vencer, el Inbox conserva el mensaje/caption y muestra un estado explícito
  «archivo expirado»; no deja un enlace roto ni oculta que hubo un adjunto.
- `MessageMedia` tendrá un vencimiento derivado de su persistencia operativa.
  La aplicación deja de servirlo al vencer y B2 elimina físicamente el objeto,
  incluyendo versiones anteriores/incompletas mediante lifecycle rules.
- El evento de expiración se registra sin PII. Una solicitud ARCO procedente
  puede exigir borrado anticipado del objeto operativo.
- Los backups cifrados de Postgres conservan el texto/caption del mensaje y los
  metadatos/referencias de media, pero **no** los binarios B2. Siguen p40: local
  14 días, `daily/` 30 días y `monthly/` 12 meses; no se reescriben
  retroactivamente al expirar un objeto. Antes de abrir al tráfico una
  restauración histórica se reaplican purgas/anonimizaciones procedentes y se
  reconcilian las expiraciones.
- Gate de producción: aviso de privacidad y proceso ARCO deben cubrir WhatsApp,
  media, finalidad, plazo y transferencia internacional. No se crea un checkbox
  aislado específico de media salvo que la revisión legal lo exija.
- El aviso público vive en el repositorio externo de la landing y el cambio es
  material. Antes de activar media se debe editar/publicar
  `/aviso-de-privacidad` y promover la nueva versión `privacy` en la app para
  re-consentimiento, siguiendo
  [`legal-version-sync.md`](../runbooks/legal-version-sync.md). Esta acción queda
  registrada como gate externo; no se considera completada por este ADR.

### D-2 · Storage v1: Backblaze B2 operativo

- Producción escribe el binario directamente en un bucket B2 privado dedicado.
  El VPS solo puede usar spool temporal durante descarga/subida y debe limpiarlo
  al completar o fallar; no es almacenamiento canónico.
- Postgres guarda únicamente metadatos, estado, hash y referencia del objeto.
- Dev/CI usan backend local intercambiable, sin credenciales B2.
- Bucket, prefijo y Application Key son exclusivos de media y distintos de
  backups. Nunca se reutiliza la clave de `rclone`; mínimo privilegio.
- El bucket operativo de media **no usa Object Lock**, porque bloquearía la
  retención de 180 días y borrados ARCO procedentes. Sus lifecycle rules deben
  eliminar versiones anteriores, hide markers y cargas multiparte incompletas.
- El servido v1 pasa por un endpoint Django autenticado y acotado a la
  organización. Este proxy es el **contrato v1 cerrado**: no hay bucket público
  ni URL persistente compartible. Los `presigned GET` quedan fuera de v1; solo
  podrán evaluarse mediante un ADR futuro con revisión específica de seguridad,
  expiración, revocación, caché y riesgo de fuga cross-tenant.
- Se acepta explícitamente que el cifrado at-rest gestionado por B2 no es la
  postura zero-knowledge de los backups `age` de p40.
- Gates de producción: DPA de Backblaze archivado; aviso de privacidad, proceso
  ARCO y transferencia internacional actualizados; bucket/key/lifecycle
  verificados. Ninguno se considera satisfecho por el uso previo de B2 para
  backups, porque media operativa es un tratamiento separado.

### D-3 · Unread por usuario y episodio vigente

Cada usuario mantiene su propio `InboxReadState`. El contador comprende los
entrantes visibles del episodio vigente posteriores a su último mensaje leído;
no revive sesiones históricas y la lectura de una persona no limpia la de otra.

### D-4 · Mark-read automático con visibilidad real

Abrir el hilo marca leído automáticamente solo cuando la ventana/pestaña está
visible y enfocada, después de un debounce breve. Un fetch en background o una
pestaña oculta no marca. El backend conserva idempotencia y monotonicidad.

### D-5 · NO-GO a SSE en v1

El rollout v1 conserva polling REST y lo optimiza con N+1 corregido, paginación,
merge/dedupe, `?since` y pausa/reducción al ocultar la pestaña. El Gunicorn
síncrono actual tiene capacidad limitada y cada stream SSE consumiría un
worker/thread; Redis pub/sub por sí solo no resuelve esa restricción.

SSE queda diferido. Solo se reevalúa si producción demuestra que la latencia del
polling causa un problema operativo, con medición de conexiones esperadas y una
propuesta de capacidad (ASGI o servicio dedicado, entre alternativas). Un GO
futuro requiere ADR p61; RT-01..03 no son parte del rollout v1.

### D-6 · Asignación operable por `agentinbox.claim`

Quien tenga `agentinbox.claim` puede asignar una conversación a cualquier
usuario activo de la misma organización que tenga `agentinbox.send`. V1 no
envía push. Toda asignación registra actor, origen, destino y fecha, respeta el
lock de la conversación y rechaza usuarios inactivos/cross-tenant.

### D-7 · Retry compartido por la clínica

Quien tenga `agentinbox.send` puede reintentar un saliente fallido aunque lo haya
creado otra persona. El retry conserva el mismo contenido, no edita el mensaje,
respeta idempotencia y la ventana de 24 horas, evita duplicados y registra actor
y resultado.

### D-8 · Contexto mínimo v1; expansión operativa futura

V1 muestra owner, mascotas, última cita no clínica y enlace al expediente. No
incrusta historial clínico en el Inbox. En una evolución futura el agente/Inbox
podrá exponer productos, servicios y precios vigentes mediante contratos y
permisos explícitos, consultando las fuentes de verdad del catálogo; no copia
esos datos a un modelo paralelo del Inbox.

### D-9 · Título v1; sonidos y Notification API futuros

V1 usa el título/contador de pestaña. Una fase futura añadirá sonido opcional y
silenciable y después podrá incorporar Notification API. Ambas requieren
preferencias por usuario, permiso del navegador, deduplicación/rate limiting y
una forma clara de evitar fatiga de notificaciones.

### D-10 · Orden de llegada en v1

**Aclaración B1 (2026-09-14):** el cursor causal exclusivo y el orden de eventos de `TurnContext` usan `(Message.created_at, Message.id)` persistidos localmente. `raw_metadata.timestamp` de Meta sigue siendo diagnóstico; no reordena mensajes ni reconstruye causalidad legacy. Caption/tipo/reply/action se conservan en la proyección validada `_channel_event` v1, sin binarios ni cuerpo duplicado. [Contrato y pruebas B1](../implementacion-b1-agente-whatsapp-2026-09-14.md).

El transcript continúa ordenado por persistencia local (`created_at`, `id`). El
timestamp del proveedor puede normalizarse y medirse en el futuro, pero no
reordena históricos ni altera cursores/unread en v1. Adoptarlo como autoridad de
orden requerirá evidencia de frecuencia/impacto y una nueva decisión.

---

## 3 · Consecuencias de implementación

1. D-1/D-2 desbloquean el diseño de MED-01, pero su activación en producción
   permanece bloqueada por privacidad/ARCO/DPA y configuración segura de B2.
2. D-3/D-4 fijan el contrato de UNR-01/02 y sus pruebas multiusuario.
3. D-5 retira RT-01..03 del rollout v1; PERF-03 es la estrategia de
   actualización incremental efectiva de esta versión.
4. D-6/D-7 exigen auditoría de actor y matrices RBAC/cross-tenant.
5. D-8/D-9 delimitan v1 sin cerrar la evolución del producto.
6. D-10 impide que ORD-01 cambie el orden global en este plan.

---

## 4 · Gates verificables

- Media: objeto de 181 días no se sirve y el proxy responde `410
  media_expired`; la fila/mensaje sigue visible y la UI renderiza «Archivo
  expirado» sin retry infinito; las versiones B2 quedan cubiertas por lifecycle.
- Storage: proxy Django autenticado como única vía v1; ninguna URL pública o
  presigned; petición cross-org responde 404; no quedan spools locales tras
  éxito/fallo/crash gracias al scavenger.
- Unread: dos usuarios tienen contadores independientes; pestaña oculta no
  marca leído.
- Asignación/retry: permiso, organización, usuario activo, lock, idempotencia y
  auditoría cubiertos por tests.
- Realtime: ninguna tarea RT-01..03 entra al rollout v1 sin un ADR p61 aceptado.
- Orden: `meta_timestamp` no participa en ordering v1.

---

## 5 · Lo que este ADR no decide

- Retención del texto de los chats. D-1 cubre exclusivamente binarios de media.
- Política legal definitiva: los gates se validan con asesoría/proceso de
  cumplimiento antes de producción.
- Arquitectura SSE futura; solo fija el NO-GO v1 y el criterio de reapertura.
- Alcance exacto de catálogo/precios o notificaciones futuras; deberán tener
  backlog y acceptance criteria propios.

## Enmienda B4 — evidencia del sender y takeover (2026-09-16)

Inbox ahora muestra los outbounds operacionales con estado explícito, incluidos
queued, sending, failed, uncertain y discarded; esos estados no acreditan que
el cliente haya recibido el texto. SENT se rotula «Aceptado por WhatsApp»;
DELIVERED/READ conservan sus eventos distintos. SENT histórico sin ID muestra
falta de evidencia. Se expone incertidumbre/fechas sin revelar send_token.

Takeover antes de admisión impide HTTP. Tras admisión se conserva la realidad
externa aunque el request termine después; nunca se promete cancelación remota.
Reemisión manual es otro Message con supersedes/actor/motivo, conservando el
original y la idempotencia humana. No nueva UI de handoff, SLA, acuse humano ni
notificación secundaria. Aceptación/entrega/lectura no equivale a atención.
Prevalece el [contrato B4](../contrato-sender-durable-b4.md) para esta frontera.


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
