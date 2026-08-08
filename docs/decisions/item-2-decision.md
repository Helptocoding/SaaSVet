# Decisión — Item 2: retomar `pending_action` al liberar una conversación

**Fecha**: 2026-08-08
**Estado**: **APROBADA — implementable.** Las decisiones de producto que
bloqueaban el arranque quedaron resueltas el 2026-08-08 (§9.1, §9.2, §9.6). Las
preguntas abiertas que restan (§9.4, §9.5, §9.7–§9.11) no bloquean la
implementación.
**Alcance**: diseño y contrato. No se modificó ningún archivo de producción.
**Plan de ejecución**: [`item-2-implementation-plan.md`](item-2-implementation-plan.md).

**Entradas moderadas**

| Documento | Rol en esta decisión |
|---|---|
| [`whatsapp-agent-identity-context-fixes-plan.md`](../whatsapp-agent-identity-context-fixes-plan.md) §Item 2 | Diseño original + decisiones de la revisión eng (2026-08-07). |
| [`item-2-backend.md`](item-2-backend.md) | Segunda pasada de arquitectura contra el código real. Aporta el mecanismo de restaurar-vencido. |
| [`item-2-security-and-tests.md`](item-2-security-and-tests.md) | **Dictamen: no aprobar tal cual.** Aporta los dos controles obligatorios y la matriz de pruebas. |

> **Convención de referencias**: `§n` sin cualificar remite a **este**
> documento. Las referencias a los documentos de entrada se nombran
> explícitamente («§5.1 del análisis de arquitectura»).

**Premisa de la moderación**: la revisión de seguridad **no aprueba** la
propuesta original. Sus dos controles P0 —no sobrescribir un cambio humano en
una reprogramación, y revalidar identidad antes de confirmar un alta— se
adoptan como obligatorios. Item 2 no se implementa sin ellos.

---

## Decisiones de producto aprobadas (2026-08-08)

Producto aprobó dos principios que **elevan los controles P0 de la revisión de
seguridad a invariantes del sistema**. No son concesiones al alcance de Item 2:
son reglas de dominio que Item 2 es el primero en necesitar.

> **INV-A — Las precondiciones atómicas son una garantía reutilizable del
> dominio, no una protección exclusiva del agente. Ningún actor debe poder
> sobrescribir una cita si su estado cambió desde que se confirmó la
> intención.**

> **INV-B — Un teléfono sólo localiza un posible `Owner`; no autoriza
> escrituras. Cualquier modificación sobre un `Owner` existente requiere
> identidad verificada por el mecanismo de identidad que corresponda al actor.
> Si no está verificada, el flujo escala a humano o rechaza la operación de
> forma segura.**

> **FLUJO-C — Cuando `register_new_client_and_pet` encuentre un `Owner`
> existente por teléfono, el agente no puede escribir en ese expediente ni
> vincularlo automáticamente: debe crear/escalar un caso visible para staff, que
> lo resuelve con verificación manual, auditada y con RBAC.** Ningún
> `phone_match` habilita la acción por sí solo, y **nada de la verificación de
> identidad se automatiza** (§5.5, §9.6).

Consecuencias inmediatas sobre esta decisión:

- El mecanismo de precondición **se especifica, se implementa y se prueba en
  `appointments`**. El agente es su primer consumidor, no su dueño (§1, §3.2).
- El `409 owner_exists` deja de ser un callejón sin salida operativo: gana una
  ruta de resolución dentro del sistema (§5.5), que es lo que hace sostenible el
  coste asumido en §9.2.
- `LINKED_STAFF` —presente en el enum de `ContactIdentity` desde el día 1 y sin
  ningún escritor— pasa a tener por fin su mecanismo (§4.4). Eso **modifica una
  regla ya documentada de Item 1**: el flag `auto_rematch_blocked` deja de
  limpiarse en «las tres únicas funciones» y pasa a limpiarse en cuatro (§4.4,
  nota de coordinación).
- La pregunta «¿se acepta que Item 2 toque el contrato de `appointments`?» deja
  de existir: tocarlo es el punto (§9.1).
- La pregunta «¿un cambio humano posterior prevalece siempre?» queda cerrada por
  INV-A, y generalizada: prevalece el estado real frente a **cualquier** actor,
  no solo frente al agente (§9.3).
- `require_new_owner` deja de ser un flag ad-hoc para el agente y pasa a ser la
  aplicación de INV-B en el endpoint compuesto (§4.3).

---

## 0. Adjudicación punto por punto

| # | Punto en disputa | Propuesta backend | Revisión de seguridad | **Decisión** |
|---|---|---|---|---|
| A | ¿Restaurar el pending con su TTL original o vencido? | Vencido (§5.1 del análisis de arquitectura) | De acuerdo, «debe conservarse» | **Vencido.** Se adopta tal cual. |
| B | ¿Basta el re-parafraseo para impedir que un cambio humano se sobrescriba? | Sí (§7 del análisis) | **No** — mitiga la intención obsoleta del cliente, no el cambio del recurso entre el chequeo y el segundo «sí» | **No basta.** Se adopta el control de la revisión: precondición atómica (§3.2). |
| C | ¿Dónde vive la protección contra pelear con el humano? | En el chequeo de release (`from_date`/`from_start_time` para triage, §4.3 del análisis) | En el commit, con compare-and-swap | **En la escritura, y en el dominio** (INV-A). `from_*` se conserva, pero cambia de propósito: pasa de dato de triage a **precondición**. |
| D | ¿El alta de cliente revalida identidad antes de escribir? | No lo contempla | **P0**: obligatorio | **Obligatorio** (§4). Se amplía por INV-B: el control no cubre solo el vínculo de identidad, también la **reutilización del expediente** (§4.2). |
| E | ¿Descarte heurístico de 3 señales para el alta? | Sí, con reserva (§4.4 del análisis, pregunta 9.1) | «Nunca auto-descartar» | **Nunca auto-descartar.** La heurística se retira del diseño; ya no es pregunta abierta. |
| F | ¿`?pet=<PK staged>` para el chequeo de creación? | Sí | **P1**: rompe con `ALLOW_LEGACY_ID_LOOKUP=False` | **Se guarda `pet_public_id`** en el snapshot; el PK queda solo para el body del POST (ADR p18). |
| G | ¿Release sin transacción ni lock? | No lo contempla | **P1**: TOCTOU con worker, nudge y segundo release | **Release pasa a ser un servicio transaccional** con lock de fila e `suspension_id` (§2, §6). |
| H | ¿Qué hacer con un `suspended` legacy o corrupto? | No lo contempla | **P1**: fail-closed y auditado | **Fail-closed y auditado.** Legacy válido → restaurar vencido; corrupto → consumir + evento, sin llamar al dominio. |
| I | ¿Tope duro de antigüedad (24/48 h)? | No por defecto; pregunta abierta 9.2 del análisis | No a un descarte silencioso; si existe, observable | **No se implementa.** Pero se documenta que **hoy ya existe una pérdida silenciosa a las 24 h** (§6.4) — eso vuelve la pregunta de producto más urgente, no menos. |
| J | ¿`deferred_at` al liberar? | No lo contempla | Preservarlo | **Preservar.** `nudge_sent` se limpia solo si no hay `deferred_at` (§6.2). |
| K | ¿Reschedule cuando el humano movió la cita a un tercer horario (9.3 del análisis)? | Tratar como resuelto y descartar | No se pronuncia; exige que el cambio humano prevalezca | **Restaurar, no descartar.** Con la precondición, el conflicto se resuelve **con el cliente presente** en vez de decidirlo un heurístico a sus espaldas. Pregunta **cerrada por diseño**. |
| L | ¿La precondición es una defensa del agente o del dominio? | No se plantea | «El endpoint de actualización debe aplicar compare-and-swap o `If-Match`» | **Del dominio** (INV-A, aprobado por producto). Cualquier actor la puede usar y —al final del rollout— ninguno la puede eludir (§3.2, §9.9). |
| M | ¿Un teléfono coincidente autoriza escribir sobre un `Owner` existente? | Implícito que sí (el alta reutiliza el Owner) | Señala el riesgo de datos duplicados y de contexto de identidad cambiado | **No** (INV-B, aprobado por producto). Localiza, no autoriza (§4). |
| N | ¿Quién y cómo resuelve el `owner_exists` que INV-B produce? | No se plantea (la reutilización era automática) | Recomienda «nunca auto-descartar» y dar control manual al staff (9.4 de la revisión) | **Caso visible en Inbox + verificación manual auditada** (FLUJO-C, aprobado). Con RBAC propio, evidencia externa al teléfono y **sin automatización de la verificación** (§5.5). |

---

## 1. Decisión final recomendada

**Se implementa Item 2 bajo el modelo «un release es una propuesta nueva, no la
reanudación de una vieja»**, con siete decisiones vinculantes. D2 y D3 son ahora
aplicaciones de INV-A e INV-B, no controles locales del agente.

**D1 — Restaurar vencido.** Al liberar, el `pending_action` se restaura con
`expires_at` en el pasado. Ningún «sí» posterior a un hand-off ejecuta nada de
forma directa: el primero cae siempre en la rama de TTL vencido de
`_commit_pending` (`planner.py:607-619`), que re-parafrasea y no escribe. Se
reutiliza `EXPIRED_REPARAPHRASE`; no se abre ninguna ruta de envío nueva.

**D2 — Precondición atómica en el dominio (INV-A).** Toda mutación sobre una
cita existente viaja con la tupla de estado vigente cuando se confirmó la
intención —para el agente, la que el cliente vio parafraseada—. El dominio la
verifica **bajo lock, dentro de la misma transacción que escribe**, y responde
`409 appointment_changed` si no coincide. El re-parafraseo protege la intención
del cliente; la precondición protege el recurso. Comportamiento ante fallo: §5.

> La precondición **no puede vivir en el agente**. Un `GET` justo antes del
> `PATCH` en `commit_reschedule_appointment` estrecha la ventana pero no la
> cierra: `AppointmentDetailView` no lockea la fila y `update_status`
> (`appointments/views.py:145-148`) lee **fuera** de su `transaction.atomic()`.
> Sin lock no hay compare-and-swap, hay una carrera más corta. INV-A además
> exige que la garantía sirva a cualquier actor, y un control dentro de
> `agent/` por definición no protege al frontend ni a una integración futura.

**D3 — Identidad verificada antes de escribir sobre un `Owner` existente
(INV-B).** `commit_register_new_client_and_pet` re-lee la `ContactIdentity`
desde la base antes de llamar a `create-with-patient`, y el endpoint compuesto
gana la precondición `require_new_owner`, que impide colgar una mascota nueva de
un `Owner` preexistente cuando quien escribe no tiene identidad verificada.
Detalle y mapa por actor en §4.

**D4 — El chequeo de release solo descarta con evidencia exacta.** Deja de ser
un triage con criterio propio y pasa a ser una comprobación estrecha: descarta
únicamente cuando el dominio prueba que el trabajo ya está hecho. Todo lo demás
—ambigüedad, error, timeout, tercer horario, alta de cliente— restaura vencido.
La red de seguridad ya no es la exactitud del heurístico: es la precondición.
**`register_new_client_and_pet` nunca se descarta automáticamente.**

**D5 — El release es un servicio transaccional idempotente.** Lock de fila
sobre `Conversation`, `suspension_id` inmutable, lectura HTTP fuera del lock, y
aplicación del veredicto solo si la suspensión sigue siendo la misma. Un
segundo release no refresca vencimientos ni rearma el nudge.

**D6 — Estado suspendido legacy o corrupto: fail-closed y auditado.** Nunca se
restaura un pending malformado «para que el planner lo arregle»: el planner
solo lo descarta *después* de que una afirmativa del cliente llegue al flujo
(`planner.py:621-625`), y para entonces el cliente ya vio una orden ambigua.

**D7 — `deferred_at` se preserva; `nudge_sent` se limpia solo en su ausencia.**
Una promesa de esperar hecha al cliente no la revoca un botón de staff.

### 1.1 Alcance: Item 2 toca `appointments` por diseño, no por accidente

| Módulo | Cambio | Naturaleza |
|---|---|---|
| `appointments/views.py`, `appointments/serializers.py` | Precondición condicional en `PATCH` detalle y en `/status/` (bajo `select_for_update`, dentro del `atomic()` que escribe); `require_new_owner` en `create-with-patient` | **Garantía de dominio (INV-A/INV-B).** Se documenta y se prueba como capacidad propia de `appointments`, no como una necesidad del agente |
| `agent/tools.py` | Snapshot con precondición + `pet_public_id`; revalidación de identidad en el commit; nuevos `client_error` | Primer consumidor de la garantía |
| `agent/planner.py` | Ramas nuevas en `_commit_pending` para `appointment_changed`, `already_done`, `identity_changed`, `owner_exists` | Traducción a conversación (§5) |
| `agent/views.py`, `agent/policy.py` (o `agent/services.py`) | Servicio de release: lock, chequeo, restaurar/descartar | Previsto en el plan original |
| `agent/models.py` (+ migración), `agent/identity.py`, `agent/views.py`, `agent/urls.py`, `agent/serializers.py` | Caso de verificación: registro append-only, `link_staff_verified`, dos endpoints nuevos, exposición del caso en la bandeja | **FLUJO-C**. Fase propia (§5.5), no bloquea las anteriores |
| `core/permissions_codes.py` | Permiso nuevo `agentinbox.identity_verify` | **FLUJO-C**. `seed_permissions` lo propaga en el deploy |
| `frontend/src/pages/inbox/`, `frontend/src/api/inbox.js` | Caso visible + acciones de verificar/autorizar/rechazar | **FLUJO-C**. Primer cambio de frontend del Item |

**Documentación obligatoria del cambio** (regla de `docs/CLAUDE.md`: cambia una
regla crítica y un contrato de API):

- **ADR propio** (siguiente número libre: **p57**) — «Precondición atómica de
  cita y autorización de escritura sobre `Owner` existente». Es un ADR de
  dominio, no de `agent`.
- [`modules/appointments.md`](../modules/appointments.md) — contrato del
  `expected_state`, del 409 y del `require_new_owner`.
- [`system-module-operations.md`](../system-module-operations.md) §3 — las
  acciones de cita ganan una precondición y un bloqueo nuevos.
- [`system-reference.md`](../system-reference.md) §3 — INV-A e INV-B como
  invariantes del sistema; §1, fila de diagnóstico para `appointment_changed`.
- [`modules/agent.md`](../modules/agent.md) — **referencia** la garantía (no la
  redefine) y documenta el caso de verificación de identidad (§5.5).
- [`modules/frontend.md`](../modules/frontend.md) — el código de error nuevo y
  las acciones de la bandeja (convención: el frontend distingue por `code`).

### 1.2 Rollout de la precondición (INV-A no se cumple el día 1)

INV-A dice «ningún actor». Hoy el único que puede enviarla es el que se está
implementando. Se declara el estado final y la secuencia para llegar, porque una
garantía a medias que nadie documente como tal es una garantía falsa.

| Fase | Quién envía `expected_state` | Estado del dominio | Alcance |
|---|---|---|---|
| **1 — este Item** | el agente, siempre | acepta y aplica si viene; sin ella, comportamiento actual | Item 2 |
| **2 — seguimiento** | el frontend (`/appointments`, `AppointmentQuickModal`), desde la cita ya cargada | igual | ticket propio, no bloquea Item 2 |
| **3 — cierre de INV-A** | todos | **exige** la precondición para mutar la tupla de agenda o el estado; sin ella → `400 precondition_required` | ADR + ventana de deprecación (Sunset RFC 8594, como ya hace el proyecto) |

Hasta la Fase 3, **la garantía solo cubre a quien la envía** (§10). Fijar el
calendario de las fases 2 y 3 es la decisión abierta §9.9.

### 1.3 Lo que sigue sin construirse (confirmado)

- Revalidación de disponibilidad en el release — el conflicto de horario lo
  sigue resolviendo el dominio en el commit (`map_domain_400` → `slot_taken`).
- Envío síncrono / re-ofrecimiento dentro del endpoint de liberar.
- Ruta de envío nueva: el re-parafraseo y el nudge existentes son los únicos
  canales.
- Tope duro de antigüedad de la suspensión (§9.4).
- Fases 2 y 3 del rollout de la precondición (§1.2, §9.9).
- **Cualquier automatización de la verificación de identidad** (§5.5.6): no se
  construye ni ahora ni como fase posterior de este Item. Verificar es un acto
  humano; el sistema solo lo registra.
- Tool de alta de mascota para un cliente ya conocido (§4.6, §9.10).

---

## 2. Flujo seguro completo — de la escalada a la nueva confirmación

```
[E] ESCALADA                      policy.escalate_to_human (policy.py:352-364)
 │   flow['pending_action'] ──► flow['suspended'] = {suspension_id, kind,
 │                                state, suspended_at, handoff_reason}
 │   state = HANDOFF_PENDING     · el bot calla (paso 6b, policy.py:157-164)
 ▼
[H] HAND-OFF                      el humano atiende. Puede: no hacer nada,
 │                                crear/mover/cancelar la cita, resolver la
 │                                identidad, o resolverlo por teléfono (sin
 │                                huella en el dominio).
 ▼
[R] RELEASE                       POST /api/inbox/conversations/<pid>/release/
 │
 │  R1  tx#1 (corta): SELECT ... FOR UPDATE sobre Conversation.
 │      · si processing_until > now  → 409 turn_in_progress (hay un turno en
 │        vuelo; el staff reintenta en segundos — no se pisa al worker)
 │      · lee flow['suspended']; valida forma (§7, fila «error técnico»)
 │      · copia el snapshot + suspension_id; libera el lock
 │
 │  R2  Chequeo de dominio FUERA de toda transacción:
 │      · UNA sola lectura HTTP, vía ToolExecutor construido desde
 │        conversation.organization + AgentSettings.agent_user
 │        (NUNCA request.user, NUNCA ORM directo — executor.py:1-21)
 │      · timeout 10 s (executor.HTTP_TIMEOUT); queda auditada en ToolExecution
 │      · solo identificadores públicos (§3.1)
 │
 │  R3  tx#2 (corta): SELECT ... FOR UPDATE de nuevo.
 │      · si flow['suspended']['suspension_id'] cambió → NO se aplica el
 │        veredicto (log AGENT_RELEASE_SUSPENSION_RACE); el release sí procede
 │      · aplica el veredicto (descartar | restaurar vencido)
 │      · state=ACTIVE, claimed_by=None, resuelve el HumanHandoff,
 │        compromiso de identidad como hoy (views.py:392-420)
 │      · un solo save de `flow` (read-modify-write bajo el lock)
 ▼
[C] EL CLIENTE VUELVE
 │
 ├─ escribe «sí» ──► policy paso 7 (policy.py:179-199) → RUN_PLANNER
 │                   → _commit_pending → is_expired = True SIEMPRE
 │                   → re-stage con TTL fresco + EXPIRED_REPARAPHRASE
 │                   → **CERO escrituras en el dominio**
 │
 └─ no escribe ────► nudge_abandoned_flows (si no hay deferred_at y no se
                     envió antes) → NUDGE_TEXT. El pending sigue vencido:
                     responder al nudge cae en la misma rama.
 ▼
[C2] SEGUNDA CONFIRMACIÓN          el cliente vio el parafraseo completo
 │                                 (mascota, fecha, motivo) en ESTE intercambio
 │   _commit_pending → no vencido → COMMIT_HANDLERS[tool]
 │
 │   · cancel / reschedule → PATCH con precondición → el dominio compara
 │     bajo lock dentro de la transacción que escribe
 │   · register           → revalida identidad + require_new_owner
 │   · create             → POST con idempotency_key (ya existente)
 ▼
[F] DESENLACE                      §5 (fallo de precondición) · §7 (matriz)
```

**Coste de UX aceptado**: tras un hand-off el cliente confirma **dos veces**.
Es el precio del control y es defendible: la segunda confirmación no es un
«¿seguro?» desnudo, es la propuesta completa re-mostrada («Pasó un rato — te
confirmo de nuevo: cita para *Luna* el *martes 12 de agosto, 10:00 a. m.*,
motivo: vacuna. ¿Es correcto?»). El cliente reconfirma leyendo, no recordando.

---

## 3. Cómo se detecta que un humano cambió o completó una cita

Dos capas, con responsabilidades distintas. La primera evita ruido; la segunda
es la que protege el dato. **Solo la segunda es una garantía.**

### 3.1 Capa 1 — chequeo de release (evita reofrecer lo ya hecho)

Una sola lectura, con `public_id` exclusivamente, org-scoped por el token del
usuario AGENT de la organización de la conversación.

| Tool | Lectura | Descarta **solo si** | Restaura vencido |
|---|---|---|---|
| `create_appointment` | `GET /api/appointments/?date={staged.date}&pet={staged.pet_public_id}` | existe una cita con `start_time == staged.start_time` y `status ∈ {scheduled, confirmed, in_progress, done}` | cualquier otro caso |
| `cancel_appointment` | `GET /api/appointments/{appointment_public_id}/` | `status ∈ {canceled, done}` (el objetivo ya se cumplió o dejó de tener sentido) | `scheduled`, `confirmed`, `in_progress` |
| `reschedule_appointment` | `GET /api/appointments/{appointment_public_id}/` | `(date, start_time)` actuales **==** destino staged **y** `status` activo | todo lo demás, **incluido el «tercer horario»** |
| `register_new_client_and_pet` | **ninguna** | **nunca** | siempre |

Reglas transversales:

- **404 sobre el recurso referenciado** → `unresolvable`: se consume la
  suspensión, se registra `AGENT_RELEASE_PENDING_UNRESOLVABLE` y **no** se
  restaura. Restaurar garantizaría un fallo posterior frente al cliente sobre
  una cita que ya no existe.
- **400 / 5xx / timeout / transport_error (599)** → restaurar vencido. Falla
  segura, como ya decidía el plan.
- **Cualquier ambigüedad** (varias citas ese día, match parcial) → restaurar.
- `?search` **no se usa nunca** para decidir un descarte: en `OwnerViewSet` el
  teléfono se filtra con `phone__icontains` y la respuesta va acotada a 20 filas
  (`patients/views.py:193-205`) — no es una comparación de igualdad y no puede
  sostener una decisión de seguridad.

**Por qué el «tercer horario» ahora restaura** (revierte §4.3 del análisis de
arquitectura): descartar significaba decidir por el cliente, en silencio, que su
petición quedó superada porque un humano hizo otra cosa. Con la precondición ya
no hace falta esa apuesta: se restaura, el cliente reconfirma, el dominio
devuelve `409 appointment_changed` y el agente le dice qué pasó y le pide
elegir. El humano sigue ganando —su cambio no se toca— pero el cliente se
entera.

### 3.2 Capa 2 — precondición atómica (la garantía, INV-A)

**El `Appointment` no expone un token de versión.** Verificado: el modelo hereda
`updated_at` de `OrganizationalModel` (`core/models.py:148`), pero
`AppointmentSerializer` **no lo incluye** en `fields` (`appointments/serializers.py:44-58`).
Exponerlo sería posible; se descarta como precondición principal porque
`auto_now` se dispara con cualquier `save()` (una nota, un cambio de motivo) y
provocaría conflictos donde no hubo ninguno.

**Precondición adoptada: la tupla semántica vigente cuando se confirmó la
intención.** Para el agente, es exactamente lo que el cliente vio parafraseado;
para el frontend (Fase 2), lo que el usuario tenía en pantalla al abrir el
formulario.

```
expected_state = {status, date, start_time}
```

Contrato requerido en `appointments` —**capacidad del dominio, no del agente**:

| Endpoint | Cambio | Comportamiento |
|---|---|---|
| `PATCH /api/appointments/<public_id>/` | campo **declarado** `expected_state` (write-only, opcional en Fase 1) en `AppointmentSerializer`; `update()` envuelto en `transaction.atomic()` con `select_for_update()` sobre la fila | coincide → escribe; no coincide → `409` |
| `PATCH /api/appointments/<public_id>/status/` | mismo campo; **mover la lectura de la cita dentro** del `atomic()` existente y lockear la fila (hoy lee en `views.py:145-148`, fuera) | ídem |
| `POST /api/appointments/create-with-patient/` | flag `require_new_owner` (§4) | ídem |

Respuesta de conflicto, alineada con el contrato de errores del proyecto
(409 tipificado, como `resource_has_dependencies`) y **genérica**: la consume el
agente hoy y la UI de citas en la Fase 2.

```json
{ "code": "appointment_changed",
  "message": "La cita cambió desde que se propuso.",
  "current": { "status": "confirmed", "date": "2026-08-13", "start_time": "16:00" } }
```

Cuatro exigencias de diseño, todas verificables con test:

1. **El campo debe estar *declarado* en el serializer.** DRF ignora en silencio
   las claves desconocidas: un `expected_state` no declarado se descartaría y el
   `PATCH` pasaría **incondicionalmente** — un fail-open perfecto e invisible.
   Es la trampa principal de este diseño y tiene prueba propia (§8, P0-4).
2. **La comparación ocurre bajo `select_for_update`, en la misma transacción que
   escribe.** Fuera de ahí no es compare-and-swap.
3. **El 409 no es un error técnico** para ningún actor (§5.1).
4. **`already_done` es un desenlace legítimo.** Si la precondición falla porque
   la cita **ya está en el estado deseado** (cancelar algo ya cancelado), no es
   conflicto: es éxito idempotente. Hoy ese caso devuelve 400 (`canceled` no
   admite transición a `canceled`, `views.py:31-38`) y termina escalando a una
   persona por nada.

### 3.3 Lo que ninguna de las dos capas detecta

La resolución **fuera de banda** (el humano lo arregló por teléfono, sin dejar
huella en `Appointment`/`Owner`/`Pet`) es indetectable por definición. La
mitigación es estructural, no detectiva: ningún «sí» posterior a un release
ejecuta directo (D1), y toda mutación sobre una cita existente exige que el
mundo siga como el cliente lo vio (D2). Lo que quede fuera de eso es riesgo
residual asumido (§10) y alimenta la decisión de producto §9.6 (visibilidad para
el staff).

---

## 4. Cómo se impide que una alta reutilice la identidad de otra persona

INV-B da la regla: **el teléfono localiza, no autoriza**. Esta sección la aterriza.

### 4.1 Vector 1 — reutilización del *vínculo de identidad* (cubierto por Item 1)

`commit_register_new_client_and_pet` ya no llama a
`identity.link_self_registered` si `contact.auto_rematch_blocked` es `True`
(`tools.py:1164-1176`, guard implementado). Un contacto reseteado por un ADMIN
no puede re-vincularse solo diciendo «quiero registrarme».

**Insuficiente para Item 2**: ese guard se evalúa contra un `contact` leído
**antes** del hand-off. Entre la propuesta y el segundo «sí» pueden pasar horas
y el staff puede haber identificado o vinculado al contacto.

### 4.2 Vector 2 — reutilización del *expediente* (era el hueco de INV-B)

Verificado en `appointments/views.py:357-372`:

```python
owner, _ = Owner.objects.get_or_create(organization=org, phone=owner_phone, ...)
pet = Pet.objects.create(..., owner=owner, ...)      # SIEMPRE crea mascota nueva
```

El plan de Item 1 acepta explícitamente que «la mascota y la cita se crean
igual… solo se suprime el auto-enlace de LA IDENTIDAD». La consecuencia no
estaba dimensionada: para un contacto reseteado cuyo teléfono coincide con un
`Owner` existente —exactamente la razón por la que un ADMIN lo reseteó— el alta
**escribe una mascota nueva y una cita dentro del expediente de esa otra
persona**. La identidad de WhatsApp queda desvinculada, pero el dato clínico ya
se mezcló. Y si ese `Owner` real escribe algún día desde su número, verá esa
mascota como suya. Es el caso literal que INV-B prohíbe: un teléfono
coincidente autorizando una escritura.

**Dónde estaba —y dónde no— el hueco.** INV-B ratifica lo que el agente ya hace
en tres de sus cuatro tools de escritura; el hueco era exactamente una:

| Tool | `min_verification` | ¿Escribe sobre un `Owner` existente? | Estado frente a INV-B |
|---|---|---|---|
| `create_appointment` | `confirmed_in_chat` (`tools.py:1440-1443`) | sí (mascota del Owner vinculado) | **ya cumple** |
| `cancel_appointment` | `confirmed_in_chat` (`tools.py:1476-1479`) | sí | **ya cumple** (+ bloquea `LINKED_FAMILY`, `tools.py:894-895`) |
| `reschedule_appointment` | `confirmed_in_chat` (`tools.py:1493-1496`) | sí | **ya cumple** (+ bloquea `LINKED_FAMILY`, `tools.py:950-951`) |
| `register_new_client_and_pet` | **`unknown`** (`tools.py:1511-1514`) | **sí, vía `get_or_create(phone)`** | **hueco — lo cierra §4.3** |

`_verification_ok` (`tools.py:109-118`) exige además `contact.owner_id is not
None`, así que un contacto en `phone_match` no autoriza **nada**: ni siquiera
`list_my_pets`. El `min_verification='unknown'` del alta es correcto por diseño
(un cliente nuevo no tiene identidad que verificar) — lo que no era correcto es
que ese permiso llegara hasta un expediente ya existente.

### 4.3 Controles obligatorios en `commit_register_new_client_and_pet`

Se ejecutan **siempre**, no solo tras un release (INV-B es una regla del
sistema; el release solo fue el escenario que la hizo evidente):

| # | Control | Fuente | Si falla |
|---|---|---|---|
| C1 | Re-leer `ContactIdentity` **desde la base** (no usar la instancia cacheada en `conversation.contact`) | DB | — |
| C2 | `contact.owner_id is None` | DB fresca | `identity_changed` — no se escribe nada |
| C3 | `not contact.is_ambiguous` | DB fresca | `identity_changed` |
| C4 | `_wa_id_to_local10(contact.external_id) == staged['owner_phone']` | recomputado | `identity_changed` (el contacto ya no es el que propuso) |
| C5 | `require_new_owner: true` en el body de `create-with-patient` | dominio, dentro de la transacción | `409 owner_exists` → **escalar a humano**, sin escribir |

C5 es el control que cierra el vector 2, y vive en el dominio a propósito: una
pre-consulta desde el agente (`GET /api/owners/?search=<phone>`) sería
`icontains`, acotada a 20 filas y con una ventana TOCTOU hasta el `POST`. El
`get_or_create` ya sabe si el `Owner` existía; solo hace falta que pueda
**negarse** en vez de reutilizar.

`require_new_owner` no es «para contactos reseteados»: lo envía **todo** alta
originada por el agente, porque en ese flujo la premisa es literalmente «cliente
nuevo». Si el teléfono ya tiene expediente, la premisa era falsa y la decisión
es de una persona.

### 4.4 El mecanismo de verificación por actor (INV-B, aplicado)

| Actor | Mecanismo que cuenta como «identidad verificada» | Qué autoriza sobre un `Owner` existente |
|---|---|---|
| Agente, contacto `unknown` o `phone_match` | ninguno — el teléfono solo localiza | **nada**. Alta solo contra `Owner` nuevo (C5); si existe → humano |
| Agente, contacto `confirmed_in_chat` / `staff_verified` | `identity.py` (`_promote`, `link_self_registered`, `link_family`, y ahora `link_staff_verified`), TTL 182 días (`identity.py:25`) | agendar, cancelar, reprogramar sobre sus mascotas |
| Agente, contacto `LINKED_FAMILY` | reto triple (`link_family`) | consultar y agendar; **no** cancelar ni reprogramar (restricción vigente) |
| Staff en `/inbox` o `/appointments` | sesión autenticada + RBAC + presencia humana ante el cliente | todo lo que su rol permita; `create-with-patient` **sin** `require_new_owner` sigue reutilizando el Owner por teléfono, y es correcto |
| Staff verificando un contacto (`LINKED_STAFF`) | **acto humano explícito con evidencia externa al teléfono**, registrado append-only (§5.5) — permiso `agentinbox.identity_verify` | vincular el contacto a un `Owner` existente, y solo entonces habilitar la acción del cliente |
| Cron / worker | ninguno propio: nunca escribe sobre `Owner` | nada |

Consecuencia sobre el auto-enlace: `link_self_registered` es seguro **porque**
el `Owner` es nuevo. Con `require_new_owner`, esa premisa deja de ser un
supuesto y pasa a ser una garantía verificada dentro de la transacción. El guard
`auto_rematch_blocked` de Item 1 sigue siendo la segunda defensa, ahora
independiente de la primera.

**Nota de coordinación con Item 1 (regla ya documentada que cambia).** El plan
de Item 1 afirma que `auto_rematch_blocked` «se limpia en `identity._promote`,
`identity.link_self_registered` y `identity.link_family` — **las tres únicas**
funciones que elevan a `confirmed_in_chat`/`staff_verified` (ADR p56 inv. 5)».
Con FLUJO-C pasan a ser **cuatro**: `link_staff_verified` es la vía por la que
un contacto reseteado vuelve a estar verificado, y es la más fuerte de todas
(una persona identificada respondió por él). Al implementarla hay que
actualizar esa frase en el plan de Item 1 y el docstring de
`reset_contact_identity` (`views.py:234-250`), o quedarán contradiciendo al
código.

**El hueco que INV-B dejaba al descubierto queda cerrado.** `LINKED_STAFF`
existía en el enum de `ContactIdentity` (`models.py:87`) sin ningún escritor: no
había forma de que una persona del equipo verificara manualmente a un contacto,
así que un `409 owner_exists` terminaba en un hand-off que el staff resolvía
fuera del sistema. FLUJO-C (aprobado, §9.6) construye ese mecanismo; su
especificación completa —estados, actor, evidencia, auditoría, errores y
recuperación— está en §5.5.

### 4.5 Qué pasa después de un `identity_changed`

No es un error y no escala: es la buena noticia de que el humano ya resolvió la
identidad. Se descarta el pending, se informa al cliente con plantilla y la
conversación continúa por la vía normal — con `contact.owner_id` ya asignado y
el nivel de verificación que el staff dejó, `create_appointment` está disponible
y el agente puede agendar sin dar de alta a nadie. El objetivo
(`ConversationGoal`) sigue abierto: el modelo prosigue.

### 4.6 Consecuencia funcional descubierta: «cliente conocido con mascota nueva»

Hay que decirlo antes de implementar, porque aparece en cuanto FLUJO-C funciona
bien. Cuando el staff verifica y vincula el contacto a un `Owner` existente, el
cliente deja de ser «nuevo» — y entonces:

- `register_new_client_and_pet` lo rechaza por su propio guard:
  `contact.owner_id is not None → already_client` (`tools.py:1074-1075`).
- No existe ninguna tool para dar de alta **una mascota** a un cliente ya
  conocido: el catálogo (`tools.py:1359-1576`) tiene lecturas, agenda y el alta
  compuesta, nada más.
- `create_appointment` exige un `pet` que todavía no está en el sistema.

Resultado: un cliente antiguo que escribe por WhatsApp con **una mascota
nueva** queda sin ruta automatizada. La resuelve el staff creando la mascota en
`/pets` (o desde el propio caso) y después el agente puede agendar con
normalidad. Es aceptable para el piloto y es el desenlace **seguro**, pero no es
gratuito: convierte en trabajo manual un caso que hoy «funcionaba» reutilizando
el expediente sin verificar a nadie —justo lo que INV-B prohíbe—. Si se quiere
recuperar la automatización, la pieza es una tool nueva gateada a
`confirmed_in_chat`; queda como decisión abierta §9.10, fuera de este Item.

---

## 5. Comportamiento cuando una precondición falla

Aplica a las dos familias de precondición: la de **estado** (INV-A,
`expected_state`) y la de **autorización** (INV-B, identidad y
`require_new_owner`).

### 5.1 Reglas comunes (valen para cualquier actor)

**R1 — Falla cerrada y atómica.** Cero escrituras parciales. La comprobación y
la escritura viven en la misma transacción, bajo `select_for_update`. Si la
precondición falla, no se creó ni se modificó nada: ni `Owner`, ni `Pet`, ni
`Appointment`, ni `AppointmentStatusChange`.

**R2 — Una precondición fallida NO es un error técnico.** No es 5xx, no es
`tool_failure`, no genera `HumanHandoff` por fallo de sistema y no cuenta como
error de integración en métricas. Es un **resultado de negocio**: el mundo
cambió. Tratarlo como avería produce escaladas falsas y esconde la señal
operativa real.

**R3 — El estado real viaja en la respuesta.** El 409 incluye `current` para
que quien reintente lo haga informado. Nunca se responde «falló, vuelve a
intentar» sin decir qué cambió.

**R4 — La intención no se pierde, la propuesta sí.** Se limpia el
`pending_action` concreto (ya no describe la realidad), pero el
`ConversationGoal` sigue abierto: el agente puede volver a proponer sobre el
estado nuevo. En el frontend, el equivalente es recargar la cita y dejar al
usuario decidir.

**R5 — Nunca se reintenta automáticamente.** Una precondición fallida significa
que alguien más decidió algo; reintentar es pelear con esa decisión.

### 5.2 Comportamiento por precondición y por actor

| Precondición fallida | Actor | Respuesta del dominio | Efecto en el dominio | Qué recibe el cliente / usuario | Evento |
|---|---|---|---|---|---|
| `expected_state` ≠ estado real | agente | `409 appointment_changed` + `current` | ninguno | plantilla con el estado **real** y una pregunta: «Tu cita cambió mientras hablabas con el equipo: ahora está el *jueves 14, 4:00 p. m.* ¿La muevo al *martes 12, 10:00 a. m.* o la dejamos así?» | `AGENT_COMMIT_PRECONDITION_FAILED` |
| `expected_state` ≠ estado real | frontend / staff (Fase 2) | mismo 409 | ninguno | la UI **recarga** la cita y muestra «esta cita cambió mientras la editabas» antes de permitir guardar. Nunca auto-reintenta | log del dominio |
| `expected_state` ≠ estado real **pero ya está en el estado deseado** (`already_done`) | cualquiera | 200 idempotente o 409 con `current` que el consumidor reconoce como éxito | ninguno (ya estaba hecho) | agente: «Ya estaba cancelada ✅ ¿Te ayudo con algo más?»; objetivo cerrado como cumplido | `AGENT_COMMIT_ALREADY_DONE` |
| `require_new_owner` violado (existe `Owner` con ese teléfono) | agente | `409 owner_exists` | ninguno: **no** se crea `Owner`, `Pet` ni `Appointment` | «Necesito que alguien del equipo confirme tus datos antes de registrarte 🙏» + **caso de verificación visible en Inbox**, con la intención preservada (§5.5) | `AGENT_COMMIT_OWNER_EXISTS` |
| Identidad cambiada durante el hand-off (C2/C3/C4) | agente | — (ni siquiera se llama al dominio) | ninguno | «Ya te tengo registrado ✅ ¿Te agendo la cita?» y sigue por la vía de cliente conocido (§4.5) | `AGENT_COMMIT_IDENTITY_CHANGED` |
| Verificación insuficiente para la tool (`_verification_ok`) | agente | — (la tool no corre, `tools.py:1641`) | ninguno | el modelo pide los datos de verificación; comportamiento **ya existente**, ratificado por INV-B sin cambio de código | `VERIFICATION_REQUIRED` (ya existe) |
| Precondición ausente, Fase 3 | cualquiera | `400 precondition_required` | ninguno | error de integración legítimo: el llamador debe adoptarla | log del dominio |

### 5.3 Qué NO debe ocurrir (anti-comportamientos)

Cada uno convertiría la garantía en decorativa; todos tienen prueba asociada
(§8):

- **Reintentar el mismo `PATCH` sin `expected_state`** como «fallback» cuando
  vuelve 409. Es exactamente la sobrescritura que INV-A prohíbe.
- **Degradar a último-escritor-gana** tras N conflictos.
- **Escalar `appointment_changed` a un humano** como si fuera avería (R2): es
  información para el cliente, y el cliente está escribiendo en ese momento.
- **Silenciar el 409** y confirmarle al cliente que quedó hecho.
- **Escribir a medias**: crear el `Pet` y fallar la cita. Por eso la
  transacción es del dominio y no la orquesta el agente.
- **Reusar el `idempotency_key` staged para forzar el paso** tras un conflicto:
  la idempotencia deduplica reintentos de la *misma* intención, no legitima una
  intención vencida.
- **Descartar la propuesta en silencio** al recibir el 409: el cliente se queda
  esperando algo que nadie va a hacer.

### 5.4 Observabilidad

Los conflictos se cuentan como **evento de negocio**, separados de los errores
técnicos (`AGENT_TOOL_HTTP_ERROR`). Un `appointment_changed` frecuente no es un
bug: es la señal de que staff y agente están operando sobre las mismas citas al
mismo tiempo, y es información que produce decisiones. Los eventos no llevan
PII: identificadores públicos, estado y motivo.

### 5.5 Recuperación del `owner_exists`: caso de verificación de identidad

Especificación de FLUJO-C, aprobado en §9.6. Es la **única** ruta por la que un
contacto no verificado puede terminar operando sobre un `Owner` existente, y
toda ella pasa por una persona.

#### 5.5.1 Estados del caso

El caso **no es un modelo nuevo**: es el `HumanHandoff` que ya existe, con
`reason_code = REASON_IDENTITY` (`'identity'`, etiqueta «Identidad —
verificación requerida o fallida», `models.py:408,417`) y un `reason_detail`
discriminador (`owner_exists`). La bandeja ya lo muestra y ya lo ordena por
urgencia (`views.py:63-79`). Lo que se añade es el registro de verificación y
las dos acciones.

| # | Estado | Cómo se entra | Quién puede actuar | Estado del dominio | Estado de la conversación |
|---|---|---|---|---|---|
| 1 | **Pendiente** | `409 owner_exists` en el commit → `escalate_to_human(REASON_IDENTITY, detail='owner_exists')` | nadie aún | sin tocar | `HANDOFF_PENDING`; intención suspendida en `flow['suspended']`; el bot calla |
| 2 | **En revisión** | staff reclama la conversación (`claim`, ya existente) | `agentinbox.claim` | sin tocar | `HUMAN_ACTIVE` |
| 3 | **Verificado** | staff registra la verificación **positiva** con evidencia | `agentinbox.identity_verify` | **sin tocar** — verificar no escribe | `HUMAN_ACTIVE` |
| 3' | **Rechazado** | staff registra la verificación **negativa** | `agentinbox.identity_verify` | **sin tocar** | `HUMAN_ACTIVE` → §5.5.5 |
| 4 | **Autorizado** | staff vincula el contacto al `Owner` (`link_staff_verified`) | `agentinbox.identity_verify` + verificación positiva vigente | `ContactIdentity.owner`, `verification_level='staff_verified'`, `linked_via='staff'`, `auto_rematch_blocked=False` | `HUMAN_ACTIVE` |
| 5 | **Reanudado** | staff libera (`release`, §2) | `agentinbox.claim` | sin tocar | `ACTIVE`; pending restaurado **vencido** |
| 6 | **Reconfirmado** | el cliente responde y vuelve a confirmar | el cliente | la escritura ocurre aquí, y **revalida** (C1–C5) | normal |
| 7 | **Abandonado** | nadie resuelve y la conversación se cierra por inactividad (§6.4) | — | sin tocar | `CLOSED`; **el handoff sigue abierto** — el caso no se auto-resuelve |

**Verificar (3) y autorizar (4) son actos distintos y separados**, tal como
aprobó producto: el primero registra un juicio humano, el segundo ejecuta una
consecuencia. Se implementan como dos endpoints, no como uno con un booleano.

#### 5.5.2 Actor autorizado (RBAC y tenant)

- **Permiso nuevo `agentinbox.identity_verify`**, añadido a `PERMISSION_CODES`
  (`core/permissions_codes.py:133-136`) y propagado por `seed_permissions` en el
  deploy. Concedido inicialmente **solo a ADMIN**.
- **Por qué no reutilizar `agentinbox.config`**: hoy ese permiso cubre el kill
  switch y el token de WhatsApp. Verificar identidad es una función de
  mostrador, no de administración del canal; con un código propio, delegarla en
  una recepcionista de confianza no implica entregarle también el interruptor
  del agente. Es la misma lógica de separación con la que la bandeja no cuelga
  de `appointment.*`.
- **Simetría con el reset**: `reset_contact_identity` (desvincular) exige
  ADMIN. Vincular a un `Owner` existente es la operación inversa y **no puede
  ser menos exigente** — es literalmente la otra mitad del vector descrito en su
  propio docstring.
- **Tenant**: las dos acciones resuelven la conversación con
  `_get_conversation` (`views.py:40-45`), que ya filtra por
  `for_organization(request.user.organization)`. Cross-tenant → 404, nunca 403
  ni lista vacía. El `Owner` candidato se resuelve **dentro de la organización
  de la conversación**, jamás desde un id del request sin re-scopear.
- **`VET` no verifica**: hoy solo tiene `agentinbox.view` (contexto clínico).
  No se le concede el permiso nuevo salvo decisión explícita de la clínica.

#### 5.5.3 Evidencia y auditoría

`ContactIdentity` guarda `verified_at` pero **no guarda quién verificó**, y no
puede representar un **rechazo** (no hay «nivel de verificación negativo»). El
punto 3 del flujo aprobado exige quién, cuándo y **resultado**, así que hace
falta un registro propio, **append-only** —consistente con el invariante de
auditoría del sistema (`system-reference.md` §3.3)—:

```
ContactIdentityVerification            # append-only: sin PATCH, sin DELETE
  organization      FK   → aislamiento de tenant desde el día 0
  contact           FK   → ContactIdentity
  owner_candidate   FK   → patients.Owner (el expediente en disputa)
  conversation      FK   → trazabilidad con el caso/handoff
  decision              'approved' | 'rejected'
  evidence_kind         tipificado: in_person_id | known_record | callback | other
  evidence_note         texto sanitizado, corto (qué comprobó la persona)
  actor             FK   → users.User (server-side, NUNCA del body)
  created_at            server-side
```

Reglas:

- **El sistema no juzga la evidencia**: registra que una persona identificada
  afirmó haberla comprobado. `evidence_kind` es una etiqueta para auditoría, no
  un puntaje ni una validación.
- **La evidencia debe ser externa al teléfono** (punto 7 del flujo aprobado). El
  teléfono ya se sabe que coincide: es lo que creó el caso. Reutilizarlo como
  prueba sería circular. El copy de la UI lo dice explícitamente y
  `evidence_kind` no ofrece ninguna opción basada en el número.
- **Un rechazo posterior invalida una aprobación previa** para el mismo
  `(contact, owner_candidate)`: la autorización lee **el último** registro.
- **Frescura acotada por el caso, no por reloj**: la autorización (4) exige una
  aprobación registrada mientras **este mismo handoff** siga abierto. Si el caso
  se cerró y se abrió otro, hay que verificar de nuevo. Evita inventar un TTL
  arbitrario y evita que una aprobación de hace tres meses habilite una acción
  de hoy.
- **Sin PII de más**: `evidence_note` es una nota operativa («coincide
  expediente 2214, vino a mostrador»), no un lugar para números de documento.
  Los logs asociados llevan ids públicos, nunca el contenido de la nota.

#### 5.5.4 Preservación de la intención (punto 1) — requisito de implementación

Hay un detalle de orden que hay que respetar o el punto 1 queda incumplido en
silencio: `_commit_pending` llama a `confirmations.clear_pending(conversation)`
**antes** de evaluar el resultado (`planner.py:627-629`). Si la rama de
`owner_exists` escala tal cual, `escalate_to_human` no encontrará ningún
`pending_action` que suspender (`policy.py:352-364`) y la intención del cliente
se perderá — exactamente lo que Item 2 existe para evitar.

Requisito: la rama de `owner_exists` debe **suspender la intención
explícitamente** (staged íntegro, mismo `suspension_id`, `handoff_reason =
identity`) antes o dentro de la escalada. El caso muestra al staff qué pidió el
cliente (nombre, mascota, especie, día y hora) sin que nadie tenga que leer el
transcript entero.

#### 5.5.5 Errores y recuperación

| Situación | Respuesta | Efecto | Recuperación |
|---|---|---|---|
| Autorizar (4) sin verificación positiva vigente | `409 verification_required` | ninguno | el staff registra primero la verificación |
| Verificar o autorizar sin `agentinbox.identity_verify` | `403` | ninguno | lo hace quien tenga el permiso |
| Conversación de otra organización | `404` (convención «404-as-403») | ninguno | — |
| El `Owner` candidato cambió o se borró entre verificar y autorizar | `409 owner_changed` con el estado actual | ninguno | releer el caso y verificar de nuevo |
| Dos personas del equipo autorizan a la vez | lock de fila sobre `ContactIdentity` en la transacción de vínculo: una gana, la otra recibe `409 already_linked` con el vínculo vigente | un solo vínculo | ninguna acción: el resultado ya es el correcto |
| El contacto quedó vinculado por otra vía mientras el caso estaba abierto | `409 already_linked` | ninguno | cerrar el caso; el cliente sigue por la vía de cliente conocido (§4.5) |
| **Rechazo** (3') | 200 con el registro creado | **ninguna escritura sobre el `Owner` existente**, jamás | la intención se **cancela**: se descarta `flow['suspended']`, se informa al cliente con plantilla y, si procede, el staff abre un caso distinto (alta con datos correctos, o corrección del teléfono del expediente). Nunca se «reintenta» el alta original |
| Se libera sin verificar ni rechazar | el release restaura la intención **vencida** (§2) | ninguno | el cliente reconfirma, el commit vuelve a fallar con `owner_exists` y **se vuelve a crear el caso**. Es correcto: liberar no es autorizar |
| El caso queda abierto y la conversación se cierra a las 24 h | el handoff **sigue abierto** en la bandeja | ninguno | el staff lo cierra a mano; la intención murió con el hilo (§6.4, §9.4) |

**Punto 5, garantizado por el mecanismo ya decidido**: al reanudar, el cliente
**siempre** recibe una confirmación nueva. No hace falta código adicional — el
pending se restaura vencido (D1), así que el primer «sí» solo puede producir el
re-parafraseo. La propuesta antigua **nunca** se ejecuta automáticamente, ni
siquiera después de que el staff autorice el vínculo.

#### 5.5.6 Fuera de alcance, explícitamente

**No se construye ninguna automatización de la verificación de identidad**, ni
en este Item ni como fase posterior suya:

- Nada de verificación por heurística, puntaje o coincidencia difusa de datos.
- Nada de que el modelo «decida» que una identidad es suficiente: el LLM no
  autoriza; nunca lo ha hecho y este flujo no es la excepción.
- Nada de OTP/SMS, biometría, lectura de documentos ni proveedores externos de
  identidad.
- Nada de auto-aprobación por antigüedad del caso, por inactividad, ni por
  reintento del cliente.
- Nada de re-verificación automática al re-escribir: `auto_rematch_blocked`
  sigue mandando.

Si alguna de estas piezas se quisiera en el futuro, es un diseño nuevo con su
propio ADR y su propia revisión de seguridad, no una extensión de esta decisión.

---

## 6. Datos, TTL y consumo

### 6.1 Estado persistido

`Conversation.flow['suspended']` (JSON, escrito por `escalate_to_human`):

```python
{
  'suspension_id': uuid4().hex,          # NUEVO — clave de idempotencia del release
  'kind': 'pending_action',
  'state': { ... },                       # el pending_action tal cual (TC-SEC-03 intacto)
  'suspended_at': '2026-08-08T17:04:11+00:00',   # NUEVO
  'handoff_reason': 'clinical_urgency',          # NUEVO — trazabilidad
}
```

`state` es el `pending_action` de `stage_pending` (`confirmations.py:44-50`):
`tool`, `args`, `paraphrase`, `idempotency_key`, `expires_at`. **No se
reescribe** al suspender.

Ampliación de `args` en el momento de **proponer** (`tools.py`), no al liberar
—si se calculara al liberar dejaría de ser «lo que el cliente vio», y la
precondición perdería su sentido:

| Tool | Claves nuevas en `staged` | Para qué |
|---|---|---|
| `create_appointment` | `pet_public_id` | lectura HTTP del release con `ALLOW_LEGACY_ID_LOOKUP=False`. El `pet` (PK) se conserva para el body del POST (ADR p18) |
| `cancel_appointment` | `expected_status`, `expected_date`, `expected_start_time` | precondición de la escritura |
| `reschedule_appointment` | `from_date`, `from_start_time`, `expected_status` | precondición de la escritura (§0-C) |
| `register_new_client_and_pet` | — | sus controles son de identidad, no de snapshot |

### 6.2 Vigencias

| Dato | TTL | Quién lo escribe | Quién lo consume | Qué lo borra |
|---|---|---|---|---|
| `pending_action.expires_at` | 30 min (`PENDING_TTL`, `confirmations.py:18`) | `stage_pending` | `_commit_pending` vía `is_expired` | `clear_pending`, verdict `negative`, commit |
| `pending_action` restaurado | **ya vencido** (`now - 1s`) | servicio de release | 1ª confirmación → re-parafraseo; 2ª → commit | ídem |
| `flow['suspended']` | **sin TTL propio** | `escalate_to_human` | el release, **una sola vez** (por `suspension_id`) | el release (siempre lo consume: restaure o descarte) |
| `suspension_id` | vive con la suspensión | `escalate_to_human` | el release, para no aplicar dos veces el mismo veredicto | ídem |
| `nudge_sent` | 1 vez por conversación (`policy.py:419`) | `nudge_abandoned_flows` | el propio nudge | el release **solo si no hay `deferred_at`** |
| `deferred_at` | vive con la conversación | policy paso 7 (`policy.py:189`) | `nudge_abandoned_flows` (`policy.py:423-430`) | **el release NO lo toca** (D7) |
| `processing_until` | 5 min (`PROCESSING_LEASE`, `worker.py:46`) | `_claim_turn` | worker y —nuevo— el release, que respeta el lease | el propio worker |
| `expected_state` (en tránsito) | vida de un request | el llamador | el dominio, bajo lock | no se persiste |

### 6.3 Idempotencia de escritura

| Tool | `idempotency_key` | Protección real |
|---|---|---|
| `create_appointment` | sí (`tools.py:836, 853`) | `UniqueConstraint(org, idempotency_key)` + replay 200 (ADR p52) |
| `register_new_client_and_pet` | sí (`tools.py:1121, 1141`) | ídem (`views.py:305-314`) |
| `cancel_appointment` | **no** | **la precondición pasa a cubrirlo**: un segundo intento ve `status='canceled'` → `already_done`, no doble transición |
| `reschedule_appointment` | **no** | **la precondición pasa a cubrirlo**: el segundo intento no coincide con `expected_state` → 409, no PATCH ciego |

Esto convierte la brecha preexistente de §2.6 del análisis de arquitectura (y de
su riesgo residual §10) en un problema resuelto **como efecto lateral** del
control P0, sin añadir claves de idempotencia a los PATCH.

### 6.4 Techo real que hoy nadie documenta

`close_inactive_conversations(idle_hours=24)` (`policy.py:443-458`) cierra toda
conversación sin actividad por 24 h. Y una conversación cerrada **no se
reabre**: un mensaje posterior abre un hilo nuevo con `flow` vacío
(`services.py:194-222`). Por lo tanto:

> **Un `pending_action` restaurado ya tiene un tope duro de ~24 h, y hoy expira
> en silencio, sin evento, sin aviso al cliente y sin nada visible para el
> staff.**

Es exactamente la «pérdida silenciosa» que la revisión de seguridad rechaza para
un tope de 24/48 h explícito… y ya existe, solo que sin razón auditable. Item 2
no la introduce ni la agrava, pero sí la hace relevante: restaurar propuestas
aumenta cuántas mueren así. Alimenta la decisión de producto §9.4.

---

## 7. Matriz de estados

Los cinco estados pedidos, con el momento en que se determina cada uno. El
detalle conductual del estado «conflicto» vive en §5.

| Estado | Cómo se determina | Momento | Acción del sistema | Qué ve el cliente | Auditoría | ¿Escribe en el dominio? |
|---|---|---|---|---|---|---|
| **Completado** (ya resuelto) | evidencia exacta de §3.1, o `already_done` en la escritura | release **o** commit | consumir la suspensión; sin restaurar. En commit: cerrar el objetivo como cumplido | release: **nada** (silencio, §9.5). Commit: confirmación («ya estaba cancelada ✅») | `AGENT_RELEASE_PENDING_DISCARDED` / `AGENT_COMMIT_ALREADY_DONE` | No |
| **Aún válido** | el dominio no prueba resolución, o el chequeo no concluye | release | restaurar con `expires_at = now-1s`; `flow.pop('suspended')`; `nudge_sent` limpiado solo si no hay `deferred_at` | nada de inmediato. Al escribir: re-parafraseo completo | `AGENT_RELEASE_PENDING_RESTORED` (+`handoff_duration`) | No |
| **Conflicto** | `409 appointment_changed`: `expected_state` ≠ estado real bajo lock | commit (2ª confirmación) | §5.2: no escribir, limpiar el pending, objetivo abierto | estado **real** + pregunta | `AGENT_COMMIT_PRECONDITION_FAILED` | **No** — es el punto de la decisión |
| | `409 owner_exists` (`require_new_owner`) | commit | §5.2: no escribir; escalar a humano | «necesito que alguien del equipo confirme tus datos 🙏» | `AGENT_COMMIT_OWNER_EXISTS` | No |
| | `identity_changed` (C2/C3/C4) | commit, pre-HTTP | §5.2: no escribir; seguir por la vía de cliente conocido | «ya te tengo registrado ✅ ¿te agendo la cita?» | `AGENT_COMMIT_IDENTITY_CHANGED` | No |
| **Expirado** | `is_expired(pending)` — **siempre true** en el primer intento tras un release | 1ª confirmación | re-stage con TTL fresco + `EXPIRED_REPARAPHRASE`; **no ejecuta** | la propuesta completa, re-mostrada | ninguno nuevo (ruta existente) | No |
| | conversación cerrada por inactividad (24 h) | cron | el `flow` muere con el hilo | **nada** (pérdida silenciosa preexistente, §6.4) | ninguno — **es el hueco** | No |
| **Error técnico** | timeout / 5xx / 599 en el chequeo de release | release | **restaurar vencido** (falla segura) | nada | `AGENT_RELEASE_DOMAIN_CHECK_FAILED` | No |
| | 404 del recurso referenciado | release | consumir la suspensión sin restaurar | nada | `AGENT_RELEASE_PENDING_UNRESOLVABLE` | No |
| | `suspended` corrupto: `kind` ajeno, falta `tool`/`args`/`paraphrase`, tool desconocida, `suspended_at` ilegible o futuro | release, **antes** de llamar al dominio | consumir sin restaurar y **sin llamada HTTP** | nada | `AGENT_RELEASE_SUSPENSION_INVALID` (sin PII) | No |
| | `suspended` legacy `{kind, state}` sin campos nuevos, pero íntegro | release | **restaurar vencido** (nunca inferir vigencia por ausencia de `suspended_at`) | nada | `AGENT_RELEASE_PENDING_RESTORED` (+`legacy=true`) | No |
| | `suspension_id` cambió entre R1 y R3 | release | no aplicar el veredicto; el release sí procede | nada | `AGENT_RELEASE_SUSPENSION_RACE` | No |
| | turno en vuelo (`processing_until > now`) | release, R1 | `409 turn_in_progress`; nada se muta | nada | `AGENT_RELEASE_TURN_IN_PROGRESS` | No |
| | 5xx/timeout en el **commit** | commit | ruta existente: `tool_failure` → escalada a humano | «tuve un problema… te comunico con una persona 🙏» | `AGENT_TOOL_HTTP_ERROR` | Indeterminado (por eso la idempotencia de §6.3) |

Regla que atraviesa toda la tabla: **solo el match exacto descarta**. Toda otra
ruta restaura vencida, salvo corrupción local o 404, que se cierran de forma
segura y auditable.

---

## 8. Pruebas de aceptación obligatorias

Bloqueantes para el merge. Las T5–T9 del plan siguen siendo necesarias, pero
**ninguna cubre los dos invariantes**, así que no bastan.

### 8.1 P0 — sin estas, no se aprueba

| # | Prueba | Archivo | Aserción principal |
|---|---|---|---|
| P0-1 | `test_release_then_first_yes_only_reparaphrases` | `agent/tests/test_inbox_api.py` | Para **los cuatro tools**: suspender, liberar sin resolución, enviar «sí». Cero POST/PATCH al dominio (transport espía), `EXPIRED_REPARAPHRASE` encolado. Solo el segundo «sí» puede llamar al commit |
| P0-2 | `test_reschedule_commit_rejects_human_change_after_release` | `agent/tests/test_write_tools.py` | Liberar con la cita en origen; el staff la mueve; dos confirmaciones. La cita **conserva el cambio humano**, no hay PATCH ciego, el cliente recibe `appointment_changed` con el estado real |
| P0-3 | `test_cancel_commit_is_idempotent_when_staff_already_canceled` | `agent/tests/test_write_tools.py` | El staff cancela entre release y 2ª confirmación → `already_done`: ninguna segunda transición, **ningún handoff técnico**, pending cerrado como resuelto |
| P0-4 | `test_expected_state_is_declared_and_never_silently_ignored` | `appointments/tests/` | `expected_state` desfasado a `PATCH` detalle **y** a `/status/` → 409 en ambos. Sin `expected_state` → 200 (Fase 1). Cubre el fail-open de DRF (§3.2, exigencia 1) |
| P0-5 | `test_register_commit_rechecks_identity_changed_during_handoff` | `agent/tests/test_write_tools.py` | Vincular `ContactIdentity` a un Owner durante el hand-off → tras reconfirmar: **no** se llama `create-with-patient`, no se crea `Pet` ni `Appointment`, resultado `identity_changed` |
| P0-6 | `test_register_never_reuses_existing_owner_by_phone` | `agent/tests/` + `appointments/tests/` | Existe un `Owner` con ese teléfono → `require_new_owner` produce 409 `owner_exists`; **cero** `Pet` creados bajo ese Owner; el agente escala. Incluir el caso `auto_rematch_blocked=True` |
| **P0-7** | `test_precondition_is_enforced_for_any_actor` | `appointments/tests/` | **INV-A**: el 409 no es un privilegio del agente. Un usuario staff autenticado (ADMIN y VET) con `expected_state` desfasado recibe el mismo 409 y la cita no cambia. La garantía se prueba en `appointments`, sin montar el agente |
| **P0-8** | `test_phone_match_alone_cannot_write_on_existing_owner` | `agent/tests/test_write_tools.py` | **INV-B**: contacto en `phone_match` → `create/cancel/reschedule` rebotan por `_verification_ok`; el alta contra un teléfono con expediente existente → 409 `owner_exists`. Con `confirmed_in_chat` → las tres pasan. Prueba que el teléfono localiza y no autoriza |
| **P0-9** | `test_precondition_failure_never_partially_writes` | `appointments/tests/` | **R1**: 409 en `create-with-patient` → cero `Owner`/`Pet`/`Appointment` nuevos; 409 en reschedule → cita intacta, **sin** `AppointmentStatusChange` |
| **P0-10** | `test_owner_exists_creates_visible_case_and_preserves_intent` | `agent/tests/test_write_tools.py` | **FLUJO-C·1**: el `409 owner_exists` deja `HumanHandoff(reason_code='identity', reason_detail='owner_exists')` abierto y visible en `GET /api/inbox/conversations/`, **y** `flow['suspended']` con el staged íntegro. Cubre el orden de `clear_pending` (§5.5.4): si la intención se pierde, falla |
| **P0-11** | `test_link_requires_prior_positive_verification` | `agent/tests/test_inbox_api.py` | **FLUJO-C·4**: autorizar el vínculo sin registro de verificación aprobado → `409 verification_required` y `ContactIdentity` intacta. Con verificación aprobada → vínculo con `verification_level='staff_verified'`, `linked_via='staff'`, `auto_rematch_blocked=False` |
| **P0-12** | `test_identity_verification_rbac_and_tenant` | `agent/tests/test_inbox_api.py` | **FLUJO-C·2/7**: sin `agentinbox.identity_verify` → 403 (probar ASSISTANT y VET); org ajena → 404 y cero escrituras. Un contacto en `phone_match` **no** habilita ninguna de las dos acciones por sí solo |
| **P0-13** | `test_rejected_verification_never_writes_on_existing_owner` | `agent/tests/test_inbox_api.py` | **FLUJO-C·6**: tras un rechazo registrado, `Owner`/`Pet`/`Appointment` intactos, `ContactIdentity.owner` sigue `None`, la intención se cancela y una autorización posterior sobre ese mismo registro → `409 verification_required` |
| **P0-14** | `test_resume_after_authorization_requires_new_confirmation` | `agent/tests/test_inbox_api.py` | **FLUJO-C·5**: verificar → autorizar → liberar → el primer «sí» del cliente **solo re-parafrasea**; ninguna escritura ejecuta la propuesta antigua de forma automática |

### 8.2 P1 — aislamiento, concurrencia, estado degradado y conducta ante conflicto

| # | Prueba | Aserción principal |
|---|---|---|
| P1-1 | `test_release_create_match_uses_pet_uuid_with_legacy_lookup_disabled` | Con `@override_settings(ALLOW_LEGACY_ID_LOOKUP=False)` y la cita ya creada por el staff: se **descarta**. No se acepta cobertura que herede el default legacy |
| P1-2 | `test_release_cross_tenant_is_404_and_never_calls_executor` | Org B libera conversación de A → 404, `flow` y handoff intactos, **cero** llamadas HTTP |
| P1-3 | `test_domain_lookup_is_scoped_to_agent_organization` | Owner/Pet/cita idénticos en A y B; liberar A usa el token de A; la coincidencia en B jamás provoca descarte |
| P1-4 | `test_release_domain_timeout_restores_expired_not_live_pending` | Timeout/599 por tool → restaura, `expires_at <= now`, primer «sí» no ejecuta |
| P1-5 | `test_release_is_idempotent_for_same_suspension` | Dos POST de release: un solo handoff resuelto, un solo consumo por `suspension_id`, sin refrescar vencimiento ni rearmar el nudge |
| P1-6 | `test_concurrent_release_and_nudge_emit_at_most_one_nudge` | `TransactionTestCase`, dos conexiones con barrera. **Sobre PostgreSQL, no SQLite** |
| P1-7 | `test_concurrent_two_releases_do_not_lose_flow` | Un solo consumo/restauración; sin pérdida de `deferred_at` ni de otras claves de `flow` |
| P1-8 | `test_release_rejects_while_turn_in_progress` | `processing_until` vigente → 409 `turn_in_progress`, `flow` sin mutar |
| P1-9 | `test_legacy_and_corrupt_suspended_states_fail_closed` | Parametrizada: legacy válido → restaurado vencido; corrupto (`kind` ajeno, tool desconocida, `args`/`paraphrase` ausentes, `suspended_at` inválido o futuro) → consumido y auditado, **sin** llamada al dominio ni commit posterior |
| P1-10 | `test_release_check_outcome_matrix` | Por cada uno de los 4 tools: resuelto exacto / no resuelto / ambiguo / 404 / 400 / 5xx / timeout. **Solo el match exacto descarta** |
| **P1-11** | `test_precondition_failure_is_not_a_technical_failure` | **R2**: un `appointment_changed` no crea `HumanHandoff`, no se clasifica como `tool_failure` y no incrementa el contador de errores de integración. Sí encola el mensaje con el estado real |
| **P1-12** | `test_agent_never_retries_without_precondition_after_409` | **R5 / §5.3**: tras un 409, el transport espía no ve **ningún** PATCH posterior sin `expected_state` ni con el mismo `idempotency_key` forzado |
| **P1-13** | `test_conflict_keeps_goal_open_and_allows_new_proposal` | **R4**: tras el 409, el `pending_action` queda limpio, el `ConversationGoal` sigue abierto y una propuesta nueva sobre el estado real se puede stagear y confirmar |
| **P1-14** | `test_concurrent_writers_only_one_wins` | `TransactionTestCase`: dos escrituras con el **mismo** `expected_state` en paralelo → exactamente una escribe, la otra recibe 409. Es la prueba de que hay lock, no solo comparación |
| **P1-15** | `test_verification_record_is_append_only_and_records_actor` | PATCH/DELETE sobre `ContactIdentityVerification` → 405; `actor` se toma de `request.user` y **se ignora** si viene en el body; `created_at` server-side. Un rechazo posterior invalida la aprobación previa |
| **P1-16** | `test_concurrent_authorizations_link_once` | `TransactionTestCase`: dos staff autorizan a la vez → un solo vínculo, la segunda recibe `409 already_linked` con el vínculo vigente. PostgreSQL |
| **P1-17** | `test_release_without_verification_recreates_the_case` | Liberar sin verificar → intención restaurada vencida → el cliente reconfirma → `owner_exists` de nuevo → **caso nuevo abierto**. Liberar no es autorizar |
| **P1-18** | `test_owner_changed_between_verify_and_authorize` | El `Owner` candidato cambia o desaparece entre (3) y (4) → `409 owner_changed`, cero escrituras, el caso sigue abierto |

### 8.3 P2 — políticas y regresión

| # | Prueba | Aserción principal |
|---|---|---|
| P2-1 | `test_release_preserves_deferred_at_and_does_not_nudge` | Pending diferido antes de escalar → tras el release no sale nudge y `deferred_at` sigue ahí (D7) |
| P2-2 | `test_release_restore_clears_previous_nudge_sent` | (T9 del plan) `nudge_sent=True` sin `deferred_at` → se limpia al restaurar |
| P2-3 | `test_release_without_pending_action_unchanged` | (T8 del plan) **REGRESIÓN, iron rule**: release normal idéntico a hoy |
| P2-4 | `test_frontend_patch_without_precondition_unchanged` | **REGRESIÓN, iron rule**: los flujos de `/appointments` del frontend siguen funcionando sin `expected_state` durante la Fase 1 |
| P2-5 | `test_reception_create_with_patient_still_reuses_owner` | **REGRESIÓN, iron rule**: sin `require_new_owner`, `create-with-patient` sigue reutilizando el Owner por teléfono (el staff sí está verificado, §4.4) |
| **P2-6** | `test_family_linked_contact_still_cannot_cancel_or_reschedule` | **REGRESIÓN**: la restricción vigente de `LINKED_FAMILY` (`tools.py:894-895, 950-951`) sobrevive a los cambios de commit |
| **P2-7** | `test_conflict_message_states_the_real_appointment` | El texto que recibe el cliente contiene la fecha/hora **real** (no la propuesta) y una pregunta; nunca afirma que el cambio se hizo (§5.3) |
| **P2-8** | `test_staff_verified_clears_auto_rematch_blocked` | **REGRESIÓN de Item 1**: un contacto reseteado (`auto_rematch_blocked=True`) que pasa por verificación manual queda en `False`. Es la cuarta vía legítima (§4.4, nota de coordinación) |
| **P2-9** | `test_verification_evidence_kind_never_accepts_phone_based_evidence` | El enum de `evidence_kind` no ofrece ninguna opción basada en el número, y un valor fuera del enum → 400 (§5.5.3) |
| **P2-10** | `test_no_automatic_verification_path_exists` | **Gate de la exclusión (§5.5.6)**: ninguna ruta —tool del agente, cron, worker o signal— eleva `verification_level` a `staff_verified` sin pasar por el endpoint con permiso. El único escritor de `linked_via='staff'` es `link_staff_verified` |

### 8.4 Condición de ejecución

La revisión de seguridad **no pudo ejecutar la suite** en este worktree
(`ModuleNotFoundError: No module named 'django'`), así que la línea base está
identificada por lectura, no verificada. **Correr la suite completa de
`agent/` y `appointments/` en verde es parte del gate de aprobación**, no un
paso posterior. Las pruebas de concurrencia (P1-6, P1-7, P1-14) exigen
PostgreSQL.

---

## 9. Decisiones de producto

### Cerradas (aprobadas 2026-08-08)

**9.1 — [CERRADA · APROBADA] Las precondiciones atómicas se implementan en
`appointments` como garantía reutilizable del dominio.** No son una protección
exclusiva del agente: ningún actor puede sobrescribir una cita cuyo estado
cambió desde que se confirmó la intención (INV-A).
*Consecuencias asumidas*: Item 2 modifica un contrato de dominio compartido →
ADR p57 + actualización de `modules/appointments.md`, `system-module-operations.md`
y `system-reference.md` (§1.1); el rollout es por fases y la garantía no es
universal hasta la Fase 3 (§1.2, §9.9); el frontend deberá adoptarla.

**9.2 — [CERRADA · APROBADA] Un teléfono sólo localiza un posible `Owner`; no
autoriza escrituras.** Toda modificación sobre un `Owner` existente exige
identidad verificada por el mecanismo que corresponda al actor; sin ella, se
escala a humano o se rechaza de forma segura (INV-B).
*Consecuencias asumidas*: el alta por WhatsApp contra un teléfono que ya tiene
expediente **no se completa sola** — cae a una persona. Casos reales afectados:
familias que comparten teléfono y clientes antiguos cuyo contacto nunca se
vinculó. Es el coste deliberado de no mezclar expedientes. La fricción se
reduce cuando exista un mecanismo de verificación manual por staff (§9.6),
hoy inexistente pese a que `LINKED_STAFF` está en el enum.

**9.3 — [CERRADA · derivada de INV-A] Un cambio posterior prevalece siempre.**
La escritura condicionada pide una elección nueva, nunca reintenta el destino
viejo. Se generaliza respecto de la formulación original: no es «el cambio
*humano* prevalece sobre el agente», es **el estado real prevalece sobre
cualquier intención vencida**, venga del actor que venga.

**9.6 — [CERRADA · APROBADA] El `owner_exists` se resuelve con un caso visible
en Inbox y verificación manual auditada (FLUJO-C).** Cuando
`register_new_client_and_pet` encuentre un `Owner` existente por teléfono, el
agente no escribe en ese expediente ni lo vincula automáticamente. Flujo mínimo
aprobado, especificado en §5.5:

1. El agente devuelve un conflicto seguro y **preserva la intención** del
   cliente, sin reintentar ni escribir (§5.5.4).
2. El staff autorizado, **dentro del tenant correcto**, ve el caso en Inbox
   (§5.5.1, §5.5.2).
3. El staff verifica manualmente la identidad **con evidencia externa al
   teléfono**; el sistema registra **quién, cuándo y con qué resultado**
   (§5.5.3, append-only).
4. Solo tras la verificación explícita el staff puede autorizar el vínculo o la
   acción — verificar y autorizar son actos separados (§5.5.1).
5. Al reanudar, el cliente recibe **una confirmación nueva**; la propuesta
   antigua nunca se ejecuta automáticamente (garantizado por D1).
6. Si se rechaza la identidad, **no se escribe** sobre el `Owner` existente y la
   intención se cancela o deriva en un caso distinto (§5.5.5).
7. RBAC (`agentinbox.identity_verify`), tenant scoping y trazabilidad
   obligatorios. **Un `phone_match` por sí solo jamás habilita la acción.**

*Fuera de alcance, explícito*: **cualquier automatización de la verificación de
identidad** (§5.5.6). Verificar es un acto humano; el sistema lo registra, no lo
sustituye ni lo puntúa.
*Consecuencias asumidas*: primer cambio de frontend del Item; un permiso RBAC
nuevo; un modelo append-only nuevo con su migración; y una regla ya publicada de
Item 1 que hay que corregir (§4.4, nota de coordinación).

### Abiertas (no bloquean la implementación)

**9.4 — Tope de antigüedad de la suspensión, y la pérdida silenciosa que ya
existe.** No se implementa tope explícito. Pero §6.4 documenta que
`close_inactive_conversations` ya mata cualquier propuesta a las ~24 h **en
silencio y sin razón auditable**. ¿Se acepta esa muerte silenciosa como está, o
se exige que al cerrar un hilo con `pending_action` vivo quede un evento
observable (y opcionalmente un aviso al cliente)? Afecta el cron de cierre,
fuera del alcance de Item 2.

**9.5 — ¿Descarte silencioso o cierre explícito?** El diseño descarta en
silencio cuando el dominio prueba que ya se resolvió. ¿Confirma producto que
nunca hace falta un «veo que tu cita ya quedó agendada ✅»? (El dato no se
pierde: el cliente puede preguntar y `list_upcoming_appointments` responde. Es
proactividad, no disponibilidad.)

**9.7 — Semántica de `deferred_at` tras un hand-off.** Se preserva (D7): la
promesa de esperar no la revoca un botón de staff. Si producto considera que el
contacto humano **reemplaza** esa promesa, hay que borrar los dos flags de forma
explícita y escribir el texto que el cliente recibirá; no se deduce solo.

**9.8 — Textos de los desenlaces nuevos.** `appointment_changed`,
`already_done`, `identity_changed`, `owner_exists` y el aviso de conflicto de la
UI necesitan plantillas literales (no generadas por el modelo, como el resto del
sistema). Los borradores de §5.2 son eso: borradores.

**9.9 — Calendario de las Fases 2 y 3 del rollout (§1.2).** ¿Cuándo adopta el
frontend la precondición, y cuándo pasa a ser obligatoria para todos? Hasta la
Fase 3, INV-A se cumple solo para quien la envía (§10). Requiere ventana de
deprecación y su propia entrada en el ADR.

**9.10 — Alta de mascota para un cliente ya conocido (§4.6).** Consecuencia
directa de §9.2 + §9.6: tras verificar y vincular, el cliente antiguo con una
mascota nueva se queda sin ruta automatizada, porque
`register_new_client_and_pet` lo rechaza (`already_client`) y no existe ninguna
tool de alta de mascota. ¿Se acepta que lo haga el staff (suficiente para el
piloto) o se construye una tool gateada a `confirmed_in_chat`? Es trabajo de
`agent/tools.py` + su gate, fuera de este Item.

**9.11 — Visibilidad de la propuesta congelada en hand-offs que NO son de
identidad.** §9.6 resolvió el caso `owner_exists`: ahí el staff ve qué pidió el
cliente. Pero en cualquier otra escalada (urgencia clínica, fallo de
herramienta, petición explícita) la propuesta suspendida sigue siendo invisible
y no hay botón para descartarla — que era la única cobertura posible de la
resolución fuera de banda (§3.3). ¿Se extiende el mismo tratamiento a todos los
hand-offs con `flow['suspended']`? Frontend + un endpoint, fuera de Item 2.

---

## 10. Riesgos residuales aceptados

- **INV-A no es universal hasta la Fase 3**: entre sí, dos escrituras del
  frontend siguen en último-escritor-gana. El agente queda protegido desde el
  día 1; el resto del sistema, cuando §9.9 se decida. Es una limitación del
  rollout, no del diseño, y está declarada a propósito.
- **Resolución fuera de banda** (teléfono, mostrador): indetectable. Mitigada
  por D1 + D2, no eliminada. Para los casos de identidad queda cubierta por
  §5.5; para el resto de hand-offs sigue abierta (§9.11).
- **La verificación manual vale lo que valga la persona que la hace** (§5.5.3):
  el sistema registra quién afirmó qué y cuándo, pero no puede comprobar la
  evidencia. Es un riesgo aceptado a conciencia: la alternativa —automatizar el
  juicio— es justo lo que §5.5.6 prohíbe, y sería peor (una heurística
  equivocada no deja a nadie a quien preguntar). El control real es la
  trazabilidad: toda vinculación tiene nombre y fecha.
- **Fricción operativa del caso de verificación**: cada alta con teléfono ya
  registrado consume tiempo de una persona con permiso. Si el volumen resulta
  alto en el piloto, la señal a mirar no es «relajar la verificación» sino por
  qué tantos contactos coinciden con expedientes existentes (§5.4).
- **`flow['suspended']` es un slot único, no una pila** (`policy.py:362-364`):
  dos escaladas con una propuesta nueva en medio pisan la anterior. Preexistente;
  Item 2 no lo agrava ni lo arregla. `suspension_id` al menos lo hace visible en
  los logs.
- **Doble confirmación del cliente tras cada hand-off**: coste de UX asumido a
  cambio del control (§2).
- **Fricción del alta con teléfono ya registrado**: consecuencia directa y
  aceptada de §9.2, mitigable solo con §9.6.
- **`updated_at` no expuesto**: la precondición es semántica, no de versión. Dos
  ediciones que dejen la cita en el mismo `(status, date, start_time)` pasarían
  la precondición. Es el resultado correcto —el estado que el cliente vio sigue
  siendo el real—, pero conviene saber que no es una detección de «alguien tocó
  esta fila».
- **Cierre silencioso a 24 h** (§6.4): preexistente, sin evento. Item 2 aumenta
  cuántas propuestas mueren por esa vía. Pendiente de §9.4.

---

## 11. Referencias verificadas por lectura directa

- `agent/views.py:362-422` — `release_conversation` actual: no lee ni escribe
  `flow`, sin transacción ni lock.
- `agent/views.py:234-282` — `reset_contact_identity` (Item 1 ya implementado:
  levanta `auto_rematch_blocked`).
- `agent/policy.py:352-368` — suspensión en `escalate_to_human` (slot único).
- `agent/policy.py:179-199` — confirmación del `pending_action` (paso 7),
  `deferred_at`.
- `agent/policy.py:398-440` — `nudge_abandoned_flows` (`nudge_sent` de una vez,
  respeta `deferred_at`, dispara por `last_inbound_at`).
- `agent/policy.py:443-458` — `close_inactive_conversations` (24 h).
- `agent/services.py:194-222` — una conversación cerrada **no se reabre**; el
  siguiente mensaje abre un hilo nuevo con `flow` vacío.
- `agent/confirmations.py:18,39-52,59-69` — `PENDING_TTL`, `stage_pending`,
  `is_expired`.
- `agent/planner.py:303-311` — intercepción de `confirm=affirmative` sin LLM.
- `agent/planner.py:601-688` — `_commit_pending`: rama de TTL vencido, ramas
  `slot_taken`/`past_date`/`invalid_data`, escalada genérica.
- `agent/tools.py:109-118` — `_verification_ok`: exige `owner_id` **y** nivel
  mínimo; `phone_match` no autoriza nada por sí solo.
- `agent/tools.py:1641` — punto único donde se aplica `min_verification`.
- `agent/tools.py:1440-1443, 1476-1479, 1493-1496` — `create`/`cancel`/
  `reschedule` exigen `confirmed_in_chat` (**ya cumplen INV-B**).
- `agent/tools.py:1511-1514` — `register_new_client_and_pet` con
  `min_verification='unknown'` (el hueco que cierra §4.3).
- `agent/tools.py:894-895, 950-951` — restricción de `LINKED_FAMILY` en cancelar
  y reprogramar.
- `agent/tools.py:783-866` — `create_appointment` / commit (staged `pet` = PK;
  `idempotency_key` presente).
- `agent/tools.py:888-943` — `cancel_appointment` / commit (**sin**
  `idempotency_key`; cualquier ≥400 → `tool_failure`).
- `agent/tools.py:946-1010` — `reschedule_appointment` / commit (PATCH
  incondicional; staged sin origen).
- `agent/tools.py:1063-1181` — `register_new_client_and_pet` / commit (guard de
  `auto_rematch_blocked` en el vínculo, **no** en la escritura).
- `agent/identity.py:25,102-112,165-180,206-250` — `VERIFICATION_TTL` (182 d),
  `is_verification_current`, `_promote`, `link_self_registered`, `link_family`.
- `agent/models.py:32-40,85-95` — niveles de verificación y `linked_via`
  (`LINKED_STAFF` existe, nadie lo asigna: es lo que construye §5.5).
- `agent/models.py:397-436` — `HumanHandoff`: `REASON_IDENTITY` ya existe con
  la etiqueta «Identidad — verificación requerida o fallida»; el caso de §5.5
  **no necesita un modelo nuevo**.
- `agent/views.py:40-45,63-79` — `_get_conversation` (tenant scoping) y el
  prefetch de handoffs abiertos que ya alimenta la bandeja.
- `agent/urls.py` — 11 rutas actuales bajo `/api/inbox/`; §5.5 añade dos.
- `core/permissions_codes.py:133-136,182,211` — los cuatro códigos
  `agentinbox.*` y sus concesiones por rol (VET solo `view`; ASSISTANT
  `view/claim/send`; `config` solo ADMIN vía `*.*`).
- `frontend/src/api/inbox.js`, `frontend/src/pages/inbox/index.jsx` — superficie
  de bandeja existente sobre la que se monta el caso.
- `agent/executor.py:1-21,43-171` — boundary HTTP loopback, JWT del AGENT,
  `HTTP_TIMEOUT=10`, auditoría en `ToolExecution`.
- `agent/worker.py:46,99-145` — lease `processing_until` (5 min), lock corto.
- `appointments/views.py:46-75` — filtros `?date=` y `?pet=` (el segundo resuelve
  `Pet.public_id`; el PK solo con `ALLOW_LEGACY_ID_LOOKUP=True`).
- `appointments/views.py:104-112,142-217` — `AppointmentDetailView` sin
  precondición; `update_status` lee **fuera** del `atomic()` y sin lock;
  `canceled → canceled` no es transición válida.
- `appointments/views.py:295-380` — `create-with-patient`:
  `Owner.get_or_create(phone)` + `Pet.objects.create` siempre nueva.
- `appointments/serializers.py:44-58` — `updated_at` **no** expuesto.
- `appointments/models.py:8-92` — `Appointment` sin campo de versión propio;
  `UniqueConstraint(organization, idempotency_key)`.
- `core/models.py:125-148` — `OrganizationalModel` provee `updated_at`
  (`auto_now`).
- `core/views.py:35-56` — `_resolve_or_404` y el flag `ALLOW_LEGACY_ID_LOOKUP`.
- `patients/views.py:193-205` — `OwnerViewSet.?search`: `phone__icontains` y
  `[:20]`, no sirve para una comparación de igualdad.
- `docs/decisions/2026-07-19-p52-appointment-idempotency.md` — idempotencia de
  creación y guard de fecha pasada en update.
