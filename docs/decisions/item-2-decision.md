# Decisión — Item 2: retomar `pending_action` al liberar una conversación

**Fecha**: 2026-08-08 (rev. 5 — los **lectores** de identidad entran al
contrato: bloqueador de la revisión OCR)
**Estado**: **APROBADA — implementable.** Las decisiones de producto que
bloqueaban el arranque quedaron resueltas el 2026-08-08 (§9.1, §9.2, §9.6); la
segunda ronda cerró las dos que la revisión de plan dejaba abiertas (§9.12,
§9.13) y la tercera aprobó las dos consecuencias operativas de INV-D como
comportamiento deseado (§9.14 atención sin cita, §9.15 reactivación). Las
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
| [`item-2-codex-plan-review.md`](item-2-codex-plan-review.md) | **REQUEST CHANGES sobre el plan (1ª revisión).** Cuatro P0 y cinco P1 de atomicidad, orden de transiciones y alcance del contrato. **No se modifica**: se responde. Adjudicación en §0 (filas O–Y), cierre en §12. |
| [`item-2-codex-plan-review-round2.md`](item-2-codex-plan-review-round2.md) | **P0: el inventario de F1 estaba incompleto** — `POST /api/pets/` y la edición del teléfono de `Owner` eludían el servicio único. Adjudicación en §0 (fila Z), diseño en §4.7.4, §4.9 y §4.10, cierre en §12.1. |
| Revisión OCR ronda 1 (`.ocr/sessions/2026-08-08-task-2782bc85-…/rounds/round-1/final.md`) | **REQUEST CHANGES. Bloqueador: los *lectores* de identidad del agente** (`agent/services.py`) comparaban normalizado contra `Owner.phone` crudo → elección automática entre duplicados históricos. Más dos ajustes: preview del importador y valor normalizado del `Owner` genérico. Artefacto **no se modifica**: adjudicación en §0 (fila AA), diseño en §4.7.4 (familia E), §4.8, §4.11 y §4.12, cierre en §12.2. |

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

**Segunda ronda (2026-08-08, tras la revisión de plan).** Producto cerró las dos
preguntas que la revisión dejaba en el aire. Ambas son **invariantes de
dominio**, no reglas del agente:

> **INV-C — Un teléfono normalizado identifica *como máximo* un expediente
> dentro de una organización. Si hay más de un `Owner` histórico con el mismo
> teléfono normalizado, el resultado es `owner_ambiguous` y el caso escala a
> staff. El sistema NUNCA fusiona registros ni elige uno automáticamente.**

> **INV-D — Un veterinario no puede tener dos citas activas con horarios
> solapados. Es un invariante del dominio para **todos los actores** y se
> garantiza de forma atómica en PostgreSQL, no por una lectura previa. Una
> futura configuración de capacidad/concurrencia por clínica queda fuera de
> alcance.**
>
> **INV-D no admite excepciones en Item 2** (aprobado 2026-08-08, §9.14 y
> §9.15). Los dos caminos que hoy pueden crear un solape quedan cubiertos y su
> nuevo comportamiento es **aprobado**, no tolerado:
>
> - **Atención sin cita**: no puede crear una cita activa que se solape con otra
>   del mismo veterinario. Recibe `slot_taken` y recepción escoge alternativa.
> - **Reactivación** (`canceled`/`no_show → scheduled`): no puede desplazar ni
>   solaparse con una cita ya existente. Recibe `slot_taken` y exige una
>   programación nueva.
>
> Espera, sobrecupo o múltiples recursos serán una **feature separada**, con su
> propio diseño y su propio ADR.

Consecuencias inmediatas de la segunda ronda:

- La unicidad de teléfono **no se puede imponer con un `UNIQUE` global**: eso
  exigiría limpiar/fusionar los duplicados históricos, y INV-C lo prohíbe. La
  atomicidad se consigue con un **lock transaccional sobre la clave de
  deduplicación** `(organización, teléfono normalizado)`, que además cubre el
  caso «la fila todavía no existe» (§4.7).
- `owner_ambiguous` es un desenlace de negocio nuevo, hermano de `owner_exists`
  y con la misma ruta de recuperación humana (§5.2, §5.5).
- La detección de conflictos de agenda deja de ser `exists()` + `save()`: pasa a
  ser una **restricción de exclusión de PostgreSQL** que cubre creación,
  reprogramación, atención sin cita y reactivación desde `canceled`/`no_show`
  (§3.4).
- INV-D aplica también a la **atención sin cita** —que hoy no comprueba solapes
  (`appointments/views.py`, `walk_in`)— y a la **reactivación** desde
  `canceled`/`no_show` —que hoy tampoco los valida—. Ambos cambios de
  comportamiento están **aprobados explícitamente** (§9.14, §9.15): no son
  efectos colaterales que alguien tenga que ratificar después.

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

### Adjudicación de las revisiones de plan

Filas O–Y: [`item-2-codex-plan-review.md`](item-2-codex-plan-review.md)
(1ª revisión). Fila Z: [`item-2-codex-plan-review-round2.md`](item-2-codex-plan-review-round2.md) (2ª revisión). Fila AA: revisión OCR ronda 1. **Todas se aceptan íntegras**;
ninguna se rebate. Dos se resuelven por decisión de producto (INV-C, INV-D), el
resto por diseño.

| # | Hallazgo de la revisión | Severidad | **Decisión** | Dónde se resuelve |
|---|---|---|---|---|
| O | `require_new_owner` no es atómico para un teléfono que aún no existe (`get_or_create` sin unicidad) | P0 | **Aceptado.** Un servicio único de resolución de expediente por teléfono, con **lock transaccional sobre la clave de deduplicación** (cubre la ausencia de fila) y conteo bajo ese lock. `UNIQUE` global **descartado** por incompatible con INV-C | §4.7 |
| P | Duplicados históricos por teléfono | P0 | **Aceptado + cerrado por producto (INV-C)**: fallan cerrado como `owner_ambiguous`, escalan a staff, **nunca** se fusionan ni se elige uno. Detección por comando de auditoría; migración aditiva sin backfill destructivo | §4.7, §4.8 |
| Q | `owner_exists` puede borrar la intención antes de suspenderla (`clear_pending` corre antes) | P0 | **Aceptado.** Transición **atómica** `pending_action → suspended` + hand-off en un solo commit bajo lock de `Conversation`; esta rama **no** usa el `clear_pending` genérico | §5.5.4 |
| R | La carrera de `suspension_id` no puede completar el release | P0 | **Aceptado.** Si el snapshot cambió, R3 **no muta nada**: reintenta R1–R3 una vez y, si vuelve a diferir, responde `409 release_conflict`. Solo el snapshot verificado cierra el hand-off y libera | §2, §5.6, §7 |
| S | F4 puede desplegarse antes de que F3 haga seguro el release | P0 | **Aceptado.** F4 **depende de F3** para despliegue; el recorrido completo de FLUJO-C es prueba de aceptación (P0-15) | plan §2, §8.1 |
| T | R3 debe revalidar lease y claim, no solo la suspensión | P1 | **Aceptado.** R3 revalida bajo el mismo lock estado, `processing_until`, `claimed_by` y el hand-off observado en R1. `claim`/`release`/`close` se serializan sobre la misma fila | §2, §5.6 |
| U | La garantía de cupo sigue siendo read-then-write | P1 | **Aceptado + cerrado por producto (INV-D)**: restricción de exclusión de PostgreSQL sobre `(organización, veterinario, intervalo)` para estados activos. Cubre creación, PATCH, atención sin cita y reactivación | §3.4 |
| V | El contrato de precondición no cubre `DELETE` ni declara `assign-patient` | P1 | **Aceptado.** Matriz completa de mutaciones: `DELETE` entra al contrato **y** queda deprecado a favor de `/status/` (Sunset RFC 8594); `assign-patient` **incluido** (lock + precondición opcional), fuera de INV-D; `complete_appointment_on_record_close` **excluido** con justificación | §3.3 |
| W | La aprobación de verificación no está atada a candidato/handoff/tenant | P1 | **Aceptado.** Todo se deriva del servidor; el candidato se resuelve solo dentro de la organización de la conversación; la aprobación debe ser del **mismo** candidato y del **mismo** hand-off `identity/owner_exists` abierto; invariante validado en servicio y modelo | §5.5.2, §5.5.3 |
| X | Los 409 de negocio contaminan la telemetría de fallos técnicos | P1 | **Aceptado.** Los desenlaces de negocio declarados salen de `AGENT_TOOL_HTTP_ERROR` y se registran como evento de negocio redactado, sin `tool_failure` ni hand-off técnico. Incluye los 400 de negocio ya existentes (`slot_taken`, `past_date`) | §5.4 |
| Y | Coordinación documental de Item 1 incompleta | P2 | **Aceptado.** Las dos correcciones (plan de Item 1 y docstring de `reset_contact_identity`) son DoD explícito de F4, con P2-8 como regresión bloqueante | §4.4, plan §7 |
| **Z** | **F1 no cubría `POST /api/pets/` ni la edición del teléfono de `Owner`** (2ª revisión) | **P0** | **Aceptado.** El inventario de tres consumidores se sustituye por un **inventario cerrado por familias** (crear `Owner` · asociar `Pet` · mutar `phone` · normalizar): cada vía usa el servicio o queda excluida **con evidencia**. `/api/pets/` pierde su regla propia de identidad por `(nombre, teléfono)`; el cambio de teléfono bloquea las dos claves en orden total y comprueba y guarda sin ventana | §4.7.4, §4.9, §4.10 |
| **AA** | **Los *lectores* de identidad del agente quedaban fuera de la normalización** (revisión OCR): `agent/services.py` compara el valor normalizado del `wa_id` contra `Owner.phone` **en crudo**, en la creación de `ContactIdentity` y en `_rematch_owner` | **Bloqueador** | **Aceptado.** El inventario gana la familia **E** (vías de *lectura*): ambas usan el resolvedor sobre `phone_normalized`, tenant-scoped y con `is_generic=False`; ante duplicados devuelven `owner_ambiguous` **sin vincular**, sin subir nivel y **sin tocar `auto_rematch_blocked`**. Se suman la paridad preview↔escritura del importador y la definición del `Owner` genérico (`phone_normalized = NULL`) | §4.7.4 (E), §4.8, §4.11, §4.12 |

---

## 1. Decisión final recomendada

**Se implementa Item 2 bajo el modelo «un release es una propuesta nueva, no la
reanudación de una vieja»**, con **doce** decisiones vinculantes. D2 y D3 son
aplicaciones de INV-A e INV-B; D8–D12 lo son de INV-C e INV-D y de la revisión
de plan. Ninguna es opcional.

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

**D8 — Una sola puerta para resolver un expediente por teléfono (INV-C).** Todo
camino que cree o reutilice un `Owner` a partir de un teléfono pasa por un
servicio único del dominio de `patients`, que normaliza el número, **toma un
lock transaccional sobre la clave de deduplicación `(organización, teléfono
normalizado)`** y cuenta bajo ese lock. Sus cuatro desenlaces son
`created` / `reused` / `owner_exists` / `owner_ambiguous`, y son exhaustivos: no
existe una rama que «elija» entre duplicados. `get_or_create(phone=…)` deja de
ser una vía legítima (§4.7).

**D9 — El no-solapamiento de citas es una restricción de la base, no una
consulta previa (INV-D).** PostgreSQL rechaza el segundo solape mediante una
restricción de exclusión sobre `(organización, veterinario, intervalo)` para los
estados activos. La validación del serializer se conserva como **mensaje**, no
como garantía; la garantía es la restricción (§3.4).

**D10 — La transición de una intención a suspendida es atómica.** Suspender el
`pending_action`, crear o retener el `HumanHandoff` y limpiar el pendiente
ocurre en **un solo commit**, bajo `select_for_update()` de `Conversation`, con
un helper idempotente. Ninguna rama que suspenda puede apoyarse en el
`clear_pending` genérico (§5.5.4).

**D11 — El release aplica su veredicto solo sobre el mundo que verificó.** Si
entre R1 y R3 cambió la suspensión, el estado, el claim o el lease, R3 **no muta
nada**: reintenta el ciclo completo una vez y, si vuelve a diferir, responde
`409 release_conflict`. Liberar la conversación, quitar el claim y resolver el
hand-off son consecuencias del veredicto verificado, nunca actos independientes
(§5.6).

**D12 — Un conflicto de negocio no es una avería.** Los desenlaces declarados
—`appointment_changed`, `already_done`, `owner_exists`, `owner_ambiguous`,
`slot_taken`, `past_date`, `invalid_data`— se registran como resultado de
negocio redactado y **no** como error técnico de integración, cualquiera que sea
su código HTTP. Sin `AGENT_TOOL_HTTP_ERROR`, sin `tool_failure`, sin hand-off de
sistema (§5.4).

### 1.1 Alcance: Item 2 toca `appointments` y `patients` por diseño, no por accidente

| Módulo | Cambio | Naturaleza |
|---|---|---|
| `appointments/views.py`, `appointments/serializers.py` | Precondición condicional en las mutaciones de cita (bajo `select_for_update`, dentro del `atomic()` que escribe), con la matriz completa de §3.3; `require_new_owner` en `create-with-patient` | **Garantía de dominio (INV-A/INV-B).** Se documenta y se prueba como capacidad propia de `appointments`, no como una necesidad del agente |
| `appointments/models.py` + migración | Restricción de exclusión de no-solapamiento por veterinario (INV-D) + extensión `btree_gist` | **Garantía de dominio (INV-D).** Cubre a todos los actores y a todos los caminos de escritura, incluido el que hoy no valida (atención sin cita) |
| `patients/models.py` + migración, `patients/services.py` *(nuevo)* | Teléfono normalizado persistido + índice; servicio único con **dos operaciones**: resolver expediente por teléfono y **cambiar el teléfono de un expediente**, ambas con lock de deduplicación (INV-C) | **Garantía de dominio (INV-C).** `appointments` y `patients` pasan a compartir una sola definición de «este teléfono ya tiene expediente» |
| `patients/serializers.py`, `patients/views.py` | `PetSerializer.create` deja de resolver el cliente por `(nombre, teléfono)` y adopta los dos modos de §4.9; `PetSerializer.update` y `OwnerSerializer` enrutan el cambio de teléfono por §4.10; la validación de forma pasa a `validate_mx_phone` | **Cierre del hallazgo Z**: eran las dos vías que eludían el servicio, una de ellas con una regla de identidad propia |
| `imports/services.py` | La resolución de `Owner` por teléfono usa el servicio; el `.first()` sobre duplicados desaparece y pasa a error de fila `owner_ambiguous` | INV-C: el importador tampoco puede **elegir** entre duplicados |
| `agent/tools.py` | Snapshot con precondición + `pet_public_id`; revalidación de identidad en el commit; nuevos `client_error` | Primer consumidor de la garantía |
| `agent/planner.py` | Ramas nuevas en `_commit_pending` para `appointment_changed`, `already_done`, `identity_changed`, `owner_exists` | Traducción a conversación (§5) |
| `agent/views.py`, `agent/policy.py` (o `agent/services.py`) | Servicio de release: lock, chequeo, restaurar/descartar | Previsto en el plan original |
| `agent/models.py` (+ migración), `agent/identity.py`, `agent/views.py`, `agent/urls.py`, `agent/serializers.py` | Caso de verificación: registro append-only, `link_staff_verified`, dos endpoints nuevos, exposición del caso en la bandeja | **FLUJO-C**. Fase propia (§5.5), no bloquea las anteriores |
| `core/permissions_codes.py` | Permiso nuevo `agentinbox.identity_verify` | **FLUJO-C**. `seed_permissions` lo propaga en el deploy |
| `frontend/src/pages/inbox/`, `frontend/src/api/inbox.js` | Caso visible + acciones de verificar/autorizar/rechazar | **FLUJO-C**. Primer cambio de frontend del Item |

**Documentación obligatoria del cambio** (regla de `docs/CLAUDE.md`: cambia una
regla crítica y un contrato de API):

- **ADR propio** (siguiente número libre: **p57**) — «Precondición atómica de
  cita, no-solapamiento garantizado y autorización de escritura sobre `Owner`
  existente». Es un ADR de dominio, no de `agent`, y cubre los cuatro
  invariantes (INV-A…INV-D) más el mapa de migraciones de §4.8 y §3.4.
- [`modules/appointments.md`](../modules/appointments.md) — contrato del
  `expected_state`, del 409, del `require_new_owner`, de la restricción de
  no-solapamiento y de la deprecación de `DELETE` (§3.3).
- [`modules/patients.md`](../modules/patients.md) — el teléfono normalizado, el
  servicio único de resolución de expediente y `owner_ambiguous` (§4.7).
- [`system-module-operations.md`](../system-module-operations.md) §2 y §3 — las
  acciones de cita y de alta de cliente ganan precondiciones y bloqueos nuevos.
- [`system-reference.md`](../system-reference.md) §3 — INV-A…INV-D como
  invariantes del sistema; §1, filas de diagnóstico para `appointment_changed`,
  `owner_exists`, `owner_ambiguous`, `slot_taken` (constraint) y
  `release_conflict`; §4, «jamás resolver un `Owner` por teléfono fuera del
  servicio único» y «jamás confiar en `exists()` para el cupo».
- [`modules/agent.md`](../modules/agent.md) — **referencia** la garantía (no la
  redefine) y documenta el caso de verificación de identidad (§5.5).
- [`modules/frontend.md`](../modules/frontend.md) — los códigos de error nuevos
  y las acciones de la bandeja (convención: el frontend distingue por `code`).
- [`whatsapp-agent-identity-context-fixes-plan.md`](../whatsapp-agent-identity-context-fixes-plan.md)
  §Item 1 — «las tres únicas funciones» → **cuatro** (§4.4). Es DoD de F4, no
  una tarea de limpieza posterior.

### 1.2 Rollout de la precondición (INV-A no se cumple el día 1)

INV-A dice «ningún actor». Hoy el único que puede enviarla es el que se está
implementando. Se declara el estado final y la secuencia para llegar, porque una
garantía a medias que nadie documente como tal es una garantía falsa.

| Fase | Quién envía `expected_state` | Estado del dominio | Alcance |
|---|---|---|---|
| **1 — este Item** | el agente, siempre | acepta y aplica si viene, en **todas** las mutaciones de §3.3; sin ella, comportamiento actual. `DELETE` entra en ventana de deprecación | Item 2 |
| **2 — seguimiento** | el frontend (`/appointments`, `AppointmentQuickModal`), desde la cita ya cargada | igual; el frontend migra de `DELETE` a `/status/` | ticket propio, no bloquea Item 2 |
| **3 — cierre de INV-A** | todos | **exige** la precondición para mutar la tupla de agenda o el estado; sin ella → `400 precondition_required`. `DELETE /appointments/<id>/` responde `410 endpoint_sunset` | ADR + ventana de deprecación (Sunset RFC 8594, como ya hace el proyecto) |

Hasta la Fase 3, **la garantía de INV-A solo cubre a quien la envía** (§10).
Fijar el calendario de las fases 2 y 3 es la decisión abierta §9.9.

**INV-D no tiene rollout por fases**: una restricción de base cubre a todos los
actores desde el instante en que se aplica la migración. Lo que sí tiene
secuencia es la **limpieza previa** de solapes históricos (§3.4), porque
PostgreSQL no admite añadir una restricción de exclusión sobre datos que ya la
violan.

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
- **Fusión de expedientes duplicados** (INV-C): ni automática ni asistida. El
  duplicado se detecta, se declara ambiguo y lo ordena una persona con las
  herramientas que ya existen (§4.8).
- **Restricción única de teléfono por organización**: descartada, no aplazada
  (§4.7.1). Introducirla sería otra decisión con su propia limpieza de datos.
- **Configuración de capacidad o concurrencia por clínica** (varias citas
  simultáneas por veterinario, salas, agendas paralelas): fuera de alcance por
  decisión de producto §9.13. Hoy el invariante es binario.
- **Lista de espera, sobrecupo y múltiples recursos**: **feature separada**
  (§9.14, §9.15). No es una fase posterior de Item 2 ni una bandera que se añade
  luego: es otro diseño, con su propio ADR.
- **Cualquier bandera de forzado del solape** (`force`, `allow_overlap`, permiso
  que lo salte): no existe y no se añade. Un invariante con puerta trasera es un
  aviso (§3.4).

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
 │      · toma el TESTIGO de release (§5.6): suspension_id, state,
 │        claimed_by_id, processing_until y el id del HumanHandoff abierto
 │      · copia el snapshot; libera el lock
 │
 │  R2  Chequeo de dominio FUERA de toda transacción:
 │      · UNA sola lectura HTTP, vía ToolExecutor construido desde
 │        conversation.organization + AgentSettings.agent_user
 │        (NUNCA request.user, NUNCA ORM directo — executor.py:1-21)
 │      · timeout 10 s (executor.HTTP_TIMEOUT); queda auditada en ToolExecution
 │      · solo identificadores públicos (§3.1)
 │
 │  R3  tx#2 (corta): SELECT ... FOR UPDATE de nuevo. COMPARE-AND-SET.
 │      · re-lee el testigo completo. Si CUALQUIER campo difiere del de R1
 │        → NO se muta NADA (ni flow, ni state, ni claim, ni handoff):
 │          · 1er desajuste  → se repite R1–R3 una sola vez
 │          · 2º  desajuste  → 409 release_conflict {reason}
 │        (log AGENT_RELEASE_CONFLICT con el campo que cambió)
 │      · si el testigo coincide, y SOLO entonces, en el mismo commit:
 │          · aplica el veredicto (descartar | restaurar vencido)
 │          · state=ACTIVE, claimed_by=None, resuelve ESE HumanHandoff,
 │            compromiso de identidad como hoy (views.py:392-420)
 │          · un solo save de `flow` (read-modify-write bajo el lock)
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

El contrato requerido en `appointments` —**capacidad del dominio, no del
agente**— cubre **todas** las mutaciones de cita, no solo las dos que el agente
usa. La matriz completa, con el alcance declarado de cada una, está en §3.3.

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

### 3.3 Matriz de mutaciones: qué entra en el contrato y qué no

La revisión de plan tiene razón en que enumerar «PATCH detalle y `/status/`»
dejaba el contrato incompleto: `DELETE /api/appointments/<id>/` **también
cancela** la cita y escribe `AppointmentStatusChange`, sin lock ni precondición
(`appointments/views.py`, `AppointmentDetailView.destroy`), y el frontend lo
consume (`frontend/src/api/appointments.js`). Un contrato que dijera «todos los
actores» dejando esa puerta abierta sería falso.

Toda mutación de `Appointment` queda clasificada. **No hay categoría implícita**:
lo que no aparece aquí, no existe hoy y su aparición futura es un cambio de
contrato.

| Mutación | Lock de fila | `expected_state` | INV-D (no solape) | Decisión |
|---|---|---|---|---|
| `PATCH /api/appointments/<public_id>/` | **sí** (`select_for_update` dentro del `atomic()` que escribe) | **acepta**, opcional en Fase 1 | **sí** | Campo declarado en `AppointmentSerializer`; comparación bajo lock; `409 appointment_changed` con `current` |
| `PATCH /api/appointments/<public_id>/status/` | **sí** — la lectura se **mueve dentro** del `atomic()` existente (hoy lee fuera) | **acepta**, opcional en Fase 1 | **sí** — la reactivación `canceled\|no_show → scheduled` hoy **no** valida cupo y pasa a hacerlo: si el hueco ya está ocupado, `slot_taken` y hay que programar de nuevo (**aprobado**, §9.15) | ídem |
| `DELETE /api/appointments/<public_id>/` | **sí** | **acepta** (en el cuerpo; hoy nadie lo envía → comportamiento intacto) | n/a (solo cancela) | **Entra al contrato y queda deprecado.** Durante la ventana emite cabeceras `Deprecation`/`Sunset` (RFC 8594) y el log `DEPRECATED_ENDPOINT_HIT` que el proyecto ya tiene; en la Fase 3 responde `410 endpoint_sunset`. Mientras exista, **no** puede ser una vía último-escritor-gana ni producir una segunda auditoría bajo conflicto |
| `POST /api/appointments/` | n/a (crea) | n/a | **sí** | Sin precondición de estado: no hay estado previo que comparar. La idempotencia de creación (ADR p52) se conserva |
| `POST /api/appointments/create-with-patient/` | n/a (crea) | n/a | **sí** | `require_new_owner` (§4.3) + resolución de expediente por el servicio único (§4.7) |
| `POST /api/appointments/walk-in/` | n/a (crea) | n/a | **sí — cambio de comportamiento aprobado (§9.14)** | Hoy crea en `in_progress` **sin verificar solapes**. INV-D es «para todos los actores», así que la restricción también la cubre: si el veterinario está ocupado, el dominio rechaza con `slot_taken` y recepción escoge alternativa (otro veterinario u otra hora). **Sin excepción, sin bandera de fuerza, sin sobrecupo** |
| `PATCH /api/appointments/<public_id>/assign-patient/` | **sí** | **acepta**, opcional | **no** (no toca `veterinarian`, `date`, `start_time` ni `end_time`) | **Incluida con justificación**: muta la cita y escribe `AppointmentStatusChange`, así que necesita el lock y la precondición para no competir con un PATCH condicionado. Se excluye de INV-D porque no mueve la tupla de agenda |
| `appointments.services.create_appointment` (helper legacy) | n/a | n/a | n/a | **Se retira.** No tiene llamadores de producción y está roto de hecho (filtra por un campo `datetime` que el modelo ya no tiene), pero conserva el patrón `exists()` + `create()` que INV-D prohíbe. Dejarlo vivo es dejar una vía read-then-write lista para reutilizarse por error. Si alguien lo necesitara, se reescribe delegando en el endpoint |
| `services.complete_appointment_on_record_close` (cierre de consulta, ADR p34) | no (UPDATE condicional, a propósito) | **no** | **no** | **Excluida con justificación**: no es un llamador externo con una expectativa que declarar; es una transición interna `in_progress → done` que ya **falla cerrada** (el UPDATE condicional no aplica si el estado cambió) y que evita a propósito un orden de locks `Appointment↔MedicalRecord` que generaría ABBA con `assign-patient`. Cambiarla a `select_for_update` sería introducir un riesgo mayor que el que resuelve |

Regla derivada, que va a `system-reference.md` §4: **ninguna vía nueva puede
mutar una cita sin lock de fila**. Si aparece una, entra en esta matriz antes de
mergear.

### 3.4 INV-D — no-solapamiento garantizado por PostgreSQL

**El problema real.** La disponibilidad se decide hoy con `conflicts.exists()`
en `AppointmentSerializer.validate` y se escribe después
(`appointments/serializers.py`). Dos `POST`, o dos reprogramaciones de citas
distintas, pueden validar a la vez el mismo veterinario y el mismo intervalo y
**ambas persistir**: `slot_taken` es un mensaje, no una garantía. Y la
reactivación desde `canceled`/`no_show` vía `/status/` ni siquiera pasa por esa
validación.

**La garantía.** Una **restricción de exclusión** de PostgreSQL sobre la tabla
de citas:

| Elemento | Contenido |
|---|---|
| Clave de igualdad | `organization_id`, `veterinarian_id` |
| Clave de solape | el intervalo `[start_datetime, end_datetime)` con el operador de solape de rangos |
| Predicado parcial | solo estados **activos** (`scheduled`, `confirmed`, `in_progress`) y solo filas con veterinario e instantes no nulos |
| Requisito | extensión `btree_gist` (los componentes de igualdad no son indexables por GiST sin ella), creada en la misma migración — precedente en el proyecto: `TrigramExtension` en `patients/0012` |

Consecuencias que hacen que esto **sea** la garantía y no otra capa de aviso:

- Cubre **creación y reprogramación** por igual, y también la atención sin cita
  y la reactivación, porque vive en la tabla y no en un endpoint. Los dos
  últimos son comportamiento **aprobado**, no daño colateral (§9.14, §9.15).
- Cubre a **cualquier actor**, presente o futuro (frontend, importador, script
  de soporte, integración), sin rollout por fases.
- `done`, `canceled` y `no_show` quedan fuera del predicado: una cita cancelada
  no bloquea el hueco, que es la regla de negocio vigente.
- **Citas sin veterinario asignado** (`veterinarian` es nullable) quedan fuera:
  no hay recurso que reservar. Es coherente con la validación actual, que
  también requiere veterinario para comprobar conflictos.

**Contrato de error (compatibilidad deliberada).** La validación del serializer
**se conserva**: sigue siendo la que produce el mensaje legible y el `400` que el
frontend y `map_domain_400` ya entienden. Lo que cambia es que dejar de ganar la
carrera ya no significa escribir: la violación de la restricción se traduce al
**mismo** desenlace de negocio.

| Camino | Respuesta | Por qué |
|---|---|---|
| Pre-chequeo del serializer detecta el solape | `400` con el mensaje actual **+ `code: 'slot_taken'`** | Aditivo: ningún consumidor actual se rompe, y el frontend gana el `code` que la convención pide |
| La restricción de la base rechaza (perdió la carrera) | **el mismo `400 slot_taken`** | El llamador no puede —ni debe— distinguir «ya estaba ocupado» de «lo ocuparon hace 3 ms»: la acción a tomar es idéntica. Se traduce el error de integridad **por nombre de restricción**, nunca capturando `IntegrityError` a ciegas |
| Cualquier otro `IntegrityError` | se propaga | Capturar todo convertiría un bug en un `slot_taken` mentiroso |

Se descartó devolver `409` para el solape: el `409` de este Item está reservado
para **precondiciones vencidas** (`appointment_changed`, `owner_exists`,
`owner_ambiguous`, `release_conflict`), donde el cliente debe releer y volver a
decidir. Un horario ocupado es una validación del payload propuesto, no un
estado obsoleto, y ya tiene un contrato en producción que funciona.

**Datos históricos.** PostgreSQL **no** admite añadir una restricción de
exclusión `NOT VALID`: si existe un solape previo, la migración falla. Por eso
la secuencia es:

1. Comando de auditoría `audit_appointment_overlaps` (patrón
   `audit_stock_integrity`: exit 0 limpio / 1 con hallazgos), que lista por
   organización los pares solapados con sus `public_id`.
2. **Remediación humana** por clínica (mover, cancelar o desasignar
   veterinario). No se corrige automáticamente: cancelar una cita real sin que
   nadie lo decida es peor que el solape.
3. Migración que crea `btree_gist` y añade la restricción. Toma un lock fuerte
   mientras construye el índice GiST; con el tamaño de tabla del piloto es una
   pausa de segundos y se agenda en la ventana de deploy. Si el volumen creciera,
   la alternativa (construir el índice de forma concurrente y adjuntarlo) se
   evalúa entonces, no ahora.
4. El comando de auditoría **queda** en el repositorio como red de seguridad
   post-migración, igual que el de stock.

**Los dos caminos que cambian de comportamiento, aprobados (§9.14, §9.15).** No
son excepciones ni casos límite: son las dos vías que hoy pueden producir un
solape y que dejan de poder hacerlo.

| Camino | Hoy | Con INV-D | Qué hace el usuario |
|---|---|---|---|
| **Atención sin cita** (`walk-in`) | crea en `in_progress` sin comprobar solapes | si el veterinario tiene una cita activa en ese intervalo → `400 slot_taken`; **no** se crea nada | recepción escoge alternativa: otro veterinario o distinto horario. La atención no se pierde, se coloca donde cabe |
| **Reactivación** (`canceled`/`no_show → scheduled`) | no valida cupo: puede resucitar una cita sobre un hueco ya reasignado | si el hueco está ocupado → `400 slot_taken`; la cita sigue `canceled`/`no_show` | programar de nuevo (fecha/hora libre), como ya obliga el guard de fecha pasada |

Reglas que acompañan a esa aprobación y que **no** se implementan de otra forma:

- **No hay bandera de forzado.** Ni `force`, ni `allow_overlap`, ni un permiso
  que lo salte. Un invariante con puerta trasera es un aviso.
- **No se desplaza ni se mueve nada automáticamente.** La reactivación no
  reubica la cita existente ni la propia: rechaza y pide una decisión.
- **Espera, sobrecupo y múltiples recursos** (dos consultorios, dos mesas,
  agendas paralelas) son una **feature separada** con su propio diseño y ADR, no
  una extensión de Item 2 (§1.3, §9.13).
- El desenlace es el `slot_taken` que ya existe: el agente ya sabe ofrecer otro
  horario y el frontend ya sabe mostrarlo. No se inventa un código nuevo.

### 3.5 Lo que ninguna de las dos capas detecta

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
| C5 | `require_new_owner: true` en el body de `create-with-patient` | dominio, **bajo el lock de deduplicación**, dentro de la transacción (§4.7) | `409 owner_exists` (existe uno) o `409 owner_ambiguous` (existe más de uno) → **escalar a humano**, sin escribir |

C5 es el control que cierra el vector 2, y vive en el dominio a propósito: una
pre-consulta desde el agente (`GET /api/owners/?search=<phone>`) sería
`icontains`, acotada a 20 filas y con una ventana TOCTOU hasta el `POST`.

**Lo que la revisión de plan corrigió**: no basta con que el endpoint «se
niegue». `Owner.objects.get_or_create(organization, phone)` no serializa dos
transacciones que observan la ausencia de la fila —no hay unicidad que lo
impida—, así que dos altas concurrentes podían pasar ambas el control y crear
dos expedientes. La atomicidad de C5 la aporta el servicio único con lock de
deduplicación de §4.7; sin él, C5 sería una comprobación optimista con otro
nombre.

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

### 4.7 Estrategia transaccional de `create-with-patient` (INV-C)

Este es el hueco P0 que la revisión de plan detectó: el flag no era atómico
porque **nada en la base impide dos expedientes con el mismo teléfono**.

#### 4.7.1 Por qué no una restricción única

La salida obvia —`UNIQUE (organization, phone)`— está **descartada por INV-C**:
para aplicarla habría que limpiar o fusionar los duplicados históricos, y
producto cerró que los duplicados **nunca** se fusionan ni se resuelven
automáticamente. Una restricción única sobre datos que legítimamente pueden
tener duplicados no se puede crear, y crearla «solo para filas nuevas» exigiría
un estado implícito (qué fila está dentro del índice y cuál no) que nadie podría
razonar seis meses después.

La revisión admite explícitamente la alternativa: *«o un lock transaccional
estable sobre una clave de deduplicación que cubra la ausencia de filas»*. Es la
que se adopta, y es la única compatible con INV-C.

#### 4.7.2 El teléfono normalizado, persistido

`Owner.phone` es texto libre (`blank=True`; el importador admite vacío) y el
agente compara contra los últimos 10 dígitos del `wa_id`
(`tools._wa_id_to_local10`). Comparar formatos distintos sería una fuente
silenciosa de falsos «no existe».

- Se añade a `Owner` un **teléfono normalizado persistido** (10 dígitos
  nacionales; `NULL` cuando no hay teléfono, cuando no alcanza a 10 dígitos y
  **siempre para el `Owner` genérico**, §4.12), derivado siempre por el dominio,
  nunca por el cliente.
- **Es la clave de lectura, no solo de escritura.** `ContactIdentity` ya guarda
  su propio `phone_normalized` desde el día 1; lo que faltaba era el lado del
  expediente. Toda comparación va normalizado ↔ normalizado: comparar un valor
  normalizado contra `Owner.phone` en crudo fue el bypass que la revisión OCR
  encontró (§4.11).
- Índice `(organización, teléfono normalizado)` para que el conteo sea una
  búsqueda por igualdad y no un `icontains` sobre un GIN de trigramas.
- La normalización es **una sola función**, compartida por `patients`, el
  importador y el agente. Dos normalizaciones distintas son dos verdades
  distintas.

#### 4.7.3 El servicio único y su lock

Todo camino que resuelva un expediente a partir de un teléfono llama a un
servicio del dominio de `patients` que, **dentro de la transacción del
llamador**:

1. Normaliza el teléfono. Sin teléfono normalizable → no hay clave de
   deduplicación: el `Owner` se crea siempre nuevo (comportamiento actual del
   importador, que ya lo documenta) y `require_new_owner` se satisface.
2. Toma un **lock de aviso a nivel de transacción** de PostgreSQL sobre la clave
   `(organización, teléfono normalizado)`. Es lo que cubre el caso que un lock
   de fila no puede cubrir: **la fila todavía no existe**. Se libera solo con el
   commit o el rollback; no hay que acordarse de soltarlo.
3. Cuenta los `Owner` no genéricos de esa organización con ese teléfono
   normalizado, **bajo el lock**.
4. Devuelve un desenlace de cuatro valores, exhaustivo:

| Conteo | `require_new` | Desenlace | Efecto |
|---|---|---|---|
| 0 | cualquiera | `created` | crea el `Owner` dentro del mismo lock |
| 1 | `False` | `reused` | reutiliza (comportamiento actual de recepción, §4.4) |
| 1 | `True` | **`owner_exists`** | `409`, cero escrituras |
| ≥ 2 | cualquiera | **`owner_ambiguous`** | `409`, cero escrituras — **también para recepción**: si el dominio no sabe cuál es el expediente, nadie puede fingir que sí |

Notas de implementación que son parte del contrato, no detalles:

- La clave del lock es un entero derivado por hash del par
  `(organización, teléfono normalizado)`. Una colisión de hash solo produce
  **serialización de más** entre dos claves distintas; jamás incorrección. Se
  elige a propósito una función de hash estable entre sesiones, no el `hash()`
  de Python.
- El lock es **PostgreSQL-only**. No se degrada a un no-op en otros motores: un
  fail-open invisible es exactamente la clase de bug que este Item existe para
  cerrar. En un backend sin locks de aviso el servicio falla ruidosamente, y las
  pruebas de carrera corren sobre PostgreSQL (§8.4).
- El orden global de locks del proyecto no se altera: el lock de aviso se toma
  antes de cualquier lock de fila del alta y se libera al commit, así que no
  introduce un ciclo con `CashSession → MedicalRecord → Invoice → …`.
- El servicio tiene **tres operaciones**, no una: *resolver un expediente para un
  teléfono* (una clave, la de arriba), **cambiar el teléfono de un expediente**
  (dos claves —la anterior y la nueva— tomadas en orden total, §4.10) y
  **consultar sin escribir** (modo lectura, sin lock, mismos desenlaces — lo que
  usan los lectores de identidad del agente y las tres pasadas del importador,
  §4.11 y §4.8). Las tres comparten normalización, conteo, exclusión del
  genérico y desenlaces; separarlas volvería a producir dos verdades, que es
  justo lo que la revisión OCR encontró.
- **El conteo excluye siempre** a los `Owner` genéricos y a las filas sin clave
  normalizada (`NULL`): sin clave no hay identidad por teléfono (§4.12).

#### 4.7.4 Inventario completo de vías (hallazgo Z de la 2ª revisión)

La versión anterior de esta sección enumeraba tres caminos y añadía «cualquier
vía futura». **No bastaba**: dos vías *actuales* eludían el servicio, y una de
ellas resolvía identidad con una regla propia. Un inventario incompleto es
equivalente a no tener el servicio, porque la garantía vale lo que valga su
camino más débil.

El inventario se organiza por **lo que la vía puede hacerle a la identidad de un
expediente**, no por módulo. Toda vía o **usa el servicio único**, o queda
**excluida con evidencia** de que no puede alterar identidad ni expediente.

**A — Vías que crean un `Owner`**

| # | Vía | Qué hace hoy | Decisión |
|---|---|---|---|
| A1 | `POST /api/appointments/create-with-patient/` | `Owner.objects.get_or_create(organization, phone)` | **Usa el servicio** (obligatorio). Con `require_new_owner` del agente y sin él para recepción |
| A2 | `POST /api/owners/` (`OwnerViewSet.perform_create`) | crea sin ninguna deduplicación | **Usa el servicio**. Sin esto, un alta manual concurrente crea el duplicado que el agente acaba de evitar |
| A3 | **`POST /api/pets/`** (`PetSerializer.create`) | `Owner.objects.get_or_create(name, phone, organization)` — **una segunda regla de deduplicación, por `(nombre, teléfono)`** | **Usa el servicio, con contrato nuevo** (§4.9). Es el P0: hoy crea un segundo expediente para el mismo teléfono si el nombre difiere, y cuelga una mascota de un expediente localizado **solo por teléfono y nombre** |
| A4 | Importador CSV/Excel (`imports/services._resolve_owner` → `_create_owner`) | `filter(phone=…).first()` + `Owner(...).save()` | **Usa el servicio, por fila.** El `.first()` actual **elige** entre duplicados: incompatible con INV-C. Pasa a producir un error de fila `owner_ambiguous` (la fila se salta y se reporta, que es su política vigente para filas problemáticas: no aborta el import) |
| A5 | `patients.utils.get_or_create_generic_patient` y `organizations.signals.initialize_organization` | crean el `Owner` genérico con teléfono de relleno `'0000000000'` | **Excluidos con evidencia**: `is_generic=True`, protegidos por `UniqueConstraint(organization, is_generic)`, y **el conteo del servicio excluye los genéricos** (§4.7.3), así que su teléfono de relleno no puede colisionar con el de un cliente real. Además corren una sola vez por organización, en su creación |
| A6 | `seed_demo_clinic` y `agent_eval` (comandos de gestión) | crean owners de siembra | **Excluidos con evidencia**: siembra de un tenant propio (demo/eval), ejecución single-writer, sin actor externo concurrente. Si algún día sembraran sobre un tenant real, entran en A1–A4 |

**B — Vías que crean o asocian una `Pet` a un `Owner`**

| # | Vía | Qué hace hoy | Decisión |
|---|---|---|---|
| B1 | `POST /api/pets/` | crea la mascota bajo el `Owner` resuelto por `(nombre, teléfono)` | **Usa el servicio** dentro de la **misma transacción y el mismo lock** que resuelve el `Owner` (§4.9) |
| B2 | `POST /api/appointments/create-with-patient/` | `Pet.objects.create(owner=…)` — **siempre** crea mascota nueva | **Usa el servicio** para el `Owner`; la creación de la mascota vive dentro del mismo `atomic()` |
| B3 | Importador | `Pet` bajo el `Owner` resuelto | **Usa el servicio** (A4). Su dedup de mascota por `(owner, nombre normalizado, especie)` no cambia |
| B4 | `PATCH /api/pets/<id>/` (`PetSerializer.update`) | **no** re-parenta: no toca `instance.owner` | **Excluida de la resolución de expediente con evidencia** (no puede mover una mascota a otro cliente) — pero **entra por C2**, porque sí escribe `owner.phone` |
| B5 | `PATCH /api/appointments/<id>/assign-patient/` | cambia la mascota **de la cita**, exigiendo que la actual sea genérica y que la nueva sea del mismo tenant | **Excluida con evidencia**: opera sobre `Appointment.pet`, no sobre `Pet.owner`; no crea ni resuelve ningún `Owner` |
| B6 | `agent/tools.register_new_client_and_pet` | llama a A1/B2 por HTTP | **Cubierta por A1**: el agente no tiene ninguna otra vía de alta de mascota (§4.6) |

**C — Vías que modifican `Owner.phone`**

| # | Vía | Qué hace hoy | Decisión |
|---|---|---|---|
| C1 | `PATCH/PUT /api/owners/<id>/` (`OwnerViewSet` + `OwnerSerializer`) | valida formato y guarda; **cero** deduplicación, cero lock | **Usa la operación de cambio de teléfono** (§4.10) |
| C2 | **`PATCH/PUT /api/pets/<id>/`** (`PetSerializer.update`) | escritura **anidada**: `owner.phone = …; owner.save()` desde la ficha de la mascota | **Usa la operación de cambio de teléfono** (§4.10). Es la vía menos evidente y la más peligrosa: mueve la identidad de un cliente desde una pantalla que parece de mascota |
| C3 | Importador | reutiliza el `Owner` existente **sin** tocar su teléfono (`_resolve_owner` no lo actualiza) | **Excluida con evidencia**: no muta `phone` de filas existentes; solo lo escribe al **crear** (cubierto por A4) |
| C4 | Django admin (`/admin`, slug configurable) | `Owner` **no está registrado** en ningún `admin.py` de `patients` | **Excluida con evidencia** hoy. Si alguien lo registrara, entra en C1 — y es un caso que el ADR debe nombrar para que no pase inadvertido |

**E — Vías que *leen* identidad por teléfono (añadida por la revisión OCR)**

El inventario anterior cubría **escrituras**. La revisión de código encontró que
eso no basta: un **lector** que compara con `Owner.phone` en crudo puede
**elegir** una fila donde la clave normalizada dice «ambiguo», y de ahí sale un
vínculo automático de identidad. Leer también es decidir.

| # | Vía | Qué hace hoy | Decisión |
|---|---|---|---|
| E1 | **`agent/services.py` — creación de `ContactIdentity`** (primer mensaje de un número) | `Owner.objects.for_organization(org).filter(phone=<valor normalizado del wa_id>, is_generic=False)[:2]`: compara un valor **normalizado** contra la columna **cruda** | **Usa el resolvedor** sobre `phone_normalized` (§4.11) |
| E2 | **`agent/services._rematch_owner`** (reintento en cada mensaje posterior) | idéntico: `filter(phone=contact.phone_normalized, …)` — normalizado contra crudo | **Usa el resolvedor** sobre `phone_normalized` (§4.11) |
| E3 | Importador — pasada de **validación/preview** y pasada de **dry-run** (dos lecturas distintas de las del commit) | `filter(phone=…).first()`: **elige** una fila | **Usa el resolvedor** en modo lectura; el preview muestra el mismo desenlace que la escritura (§4.8) |
| E4 | `OwnerViewSet` `?search` (bandeja/dropdowns) | `phone__icontains`, acotado a 20 filas | **Excluida con evidencia**: es búsqueda para que **una persona** elija, no resolución de identidad. §3.1 ya prohíbe usarla para decidir. Añade `is_generic=False` para que el genérico no aparezca como candidato |
| E5 | Chequeo de dominio del release (§3.1) | lee citas por `public_id`; **nunca** resuelve `Owner` por teléfono | **Excluida con evidencia** |
| E6 | `tools._verification_ok` y los gates de las tools | leen `contact.owner_id` y el nivel ya persistidos; no consultan `Owner` por teléfono | **Excluidas con evidencia**: consumen la decisión de E1/E2, no la toman |

**D — Vías que normalizan o derivan el teléfono normalizado**

| # | Vía | Qué hace hoy | Decisión |
|---|---|---|---|
| D1 | `core.validators.validate_mx_phone` / `phone_digits` | normaliza a 10 dígitos y rechaza relleno; la usan `OwnerSerializer` y `OrganizationSerializer` | **Es la base de la normalización única.** El servicio deriva de aquí; no se escribe una segunda |
| D2 | `agent/tools._wa_id_to_local10` **y `agent/services.normalize_wa_id`** | ambas derivan los 10 dígitos nacionales del `wa_id`; `normalize_wa_id` es además la que alimenta `ContactIdentity.phone_normalized` | **Convergen**: la normalización del dominio debe producir el mismo valor para el mismo número. Es la razón por la que el campo se persiste — comparar `wa_id` contra `phone` en crudo era comparar dos formatos, y es exactamente el bypass que la revisión OCR encontró |
| D2b | `ContactIdentity.phone_normalized` (ya existe, `agent/models.py`) | guarda el valor normalizado del contacto | **El lado del contacto ya está normalizado desde el día 1.** Lo que faltaba era el lado del expediente: la unión correcta es `ContactIdentity.phone_normalized` ↔ `Owner.phone_normalized`, normalizado contra normalizado (§4.11) |
| D3 | `imports/services` (`_PHONE_DIGITS` + comprobación de 10 dígitos) | normalización propia, con teléfono vacío permitido | **Converge** a D1, conservando su excepción de teléfono vacío (que produce clave nula: sin clave, sin deduplicación por teléfono) |
| D4 | `PHONE_REGEX` en `patients/serializers.py` | valida forma en la escritura anidada de `PetSerializer` | **Se reemplaza** por D1: hoy es una tercera regla, más laxa que la de `OwnerSerializer` (no rechaza rellenos) |
| D5 | El campo persistido de `Owner` | *no existe todavía* | Lo introduce F1·a. Se deriva **siempre** en el dominio a partir de D1; **nunca** se acepta del cliente |

**Regla que cierra el inventario** (va a `system-reference.md` §4):

> Jamás crear un `Owner`, asociarle una `Pet` ni modificar su teléfono fuera del
> servicio único de `patients`. `get_or_create(...phone...)` y
> `get_or_create(...name..., ...phone...)` quedan prohibidos como forma de
> resolver identidad; el grep gate de CI cubre ambos (P2-12).

Y una regla de proceso, porque el fallo de la primera versión fue de método:
**una vía nueva no se «considera cubierta» por la fórmula «cualquier vía
futura»**. Entra en la tabla A, B, C o D —usando el servicio o excluida con
evidencia— antes de mergear.

### 4.8 Duplicados históricos: detección y migración segura

INV-C convierte los duplicados en un caso **soportado**, no en un error a
erradicar. Lo que hace falta es verlos y que nunca produzcan una elección
arbitraria.

| Paso | Qué es | Naturaleza |
|---|---|---|
| 1 | Migración **aditiva**: columna de teléfono normalizado + índice. Backfill derivado del `phone` existente, en lotes, sin borrar ni tocar el `phone` original | Reversible; no bloquea escrituras de forma apreciable |
| 2 | Comando `audit_owner_phone_duplicates` (patrón `audit_stock_integrity`): por organización, lista los teléfonos normalizados con más de un `Owner`, con `public_id` y nombre. Exit 0 limpio / 1 con hallazgos | Diagnóstico, **no** remediación |
| 3 | **Ninguna fusión automática, ni ahora ni después.** Un duplicado se resuelve solo si una persona de la clínica decide qué expediente es cuál, con las herramientas que ya existen (`/pets`, edición de cliente) | Decisión de producto (INV-C) |
| 4 | En tiempo de ejecución, cualquier duplicado se traduce en `owner_ambiguous` con el caso visible para staff (§5.5) | El sistema falla cerrado y **explica** |

**Paridad preview ↔ escritura en el importador** (ajuste de la revisión OCR). El
importador tiene **tres** lecturas por teléfono, no una: la pasada de
validación/preview, la de dry-run y la del commit. Cambiar solo la última deja
un fallo de producto silencioso: **la vista previa diría «se reutilizará el
cliente X» y el commit rechazaría esa misma fila como `owner_ambiguous`**. El
usuario aprueba una cosa y obtiene otra.

Regla: **las tres pasadas usan el mismo resolvedor y el mismo contrato de cuatro
desenlaces** (`0` → alta nueva · `1` → reutiliza · `owner_exists` ·
`owner_ambiguous`). En concreto:

- El preview **no puede mostrar una elección que la escritura rechazaría**. Una
  fila cuyo teléfono normalizado tenga dos o más expedientes se muestra desde el
  principio como **fila con error `owner_ambiguous`**, dentro del bloque de
  omitidas que la UI ya sabe presentar.
- Desaparece el `.first()` de las tres pasadas: ni el preview elige.
- El conteo de «se importarán N filas» que ve el usuario incluye ya esas
  exclusiones, así que coincide con el resultado real del commit.
- La política de la fila no cambia: una fila problemática **no aborta** el
  import; se salta y se reporta.

Consecuencias que se aceptan por escrito:

- Una clínica con duplicados históricos verá `owner_ambiguous` en las altas por
  WhatsApp contra esos teléfonos, y también en su propia alta manual, hasta que
  alguien ordene el dato. Es el comportamiento pedido: mezclar dos expedientes
  clínicos es peor que pedir una decisión humana.
- **No se añade una restricción única** en ningún momento del plan. Si algún día
  producto decidiera prohibir duplicados a futuro, sería una decisión nueva con
  su propia migración y su propia limpieza; este documento no la presupone.

### 4.9 `/api/pets/`: alta de mascota sin identidad implícita por teléfono

**El problema exacto** (`patients/serializers.py`, `PetSerializer.create`): el
alta de mascota resuelve el cliente con
`Owner.objects.get_or_create(name=…, phone=…, organization=…)`. Eso produce
**dos** fallos distintos, y ninguno es teórico:

1. **Cuelga una mascota de un expediente ajeno localizado por teléfono.** Si el
   `(nombre, teléfono)` coincide con un `Owner` existente, la mascota nueva entra
   en ese expediente. Es exactamente el vector que INV-B prohíbe, solo que por
   una puerta distinta a la del agente.
2. **Fabrica duplicados de teléfono.** Si el teléfono coincide pero el nombre no
   («Ana López» vs «Ana Lopez»), crea un **segundo** `Owner` con el mismo
   número — el duplicado que INV-C obliga a tratar como ambiguo, creado por el
   propio sistema.

**Contrato nuevo del alta de mascota.** Dos modos explícitos, y ninguno resuelve
identidad por teléfono a espaldas del usuario:

| Modo | Cómo se pide | Qué hace |
|---|---|---|
| **Referencia** | el cliente ya elegido, por `public_id` | asocia la mascota a **ese** expediente. Elegirlo es un acto del staff, no una inferencia del sistema: por eso es legítimo (§4.4) |
| **Alta** | datos del cliente (`nombre`, `teléfono`), como hoy | pasa por el servicio único, bajo el lock de deduplicación |

Desenlaces del **modo alta**, bajo el lock y en la misma transacción que crea la
mascota:

| Expedientes con ese teléfono | Nombre | Resultado |
|---|---|---|
| 0 | — | **crea** `Owner` + `Pet` (comportamiento actual) |
| 1 | coincide (normalizado) | **reutiliza** el expediente y crea la mascota — idéntico a hoy |
| 1 | **no** coincide | **`409 owner_exists`** con el candidato (`public_id`, nombre) — la UI pregunta «¿es este cliente?» y el usuario reenvía en **modo referencia** o corrige el teléfono. **Nunca** se crea un segundo expediente con el mismo número, y **nunca** se decide por el usuario |
| ≥ 2 | — | **`409 owner_ambiguous`** (INV-C): cero escrituras, el dato se ordena primero |

Reglas que acompañan:

- **La resolución del `Owner` y la creación de la `Pet` son una sola
  transacción**, con el lock de deduplicación tomado **antes** de ambas. No
  existe el estado «cliente creado, mascota no».
- **El agente no usa esta vía**: no tiene tool de alta de mascota (§4.6). Que
  `/api/pets/` sea de staff no la exime — lo que se cierra aquí es la
  fabricación de duplicados y la asociación implícita, no un permiso.
- La validación de forma del teléfono en el alta anidada pasa a ser la del
  dominio (`validate_mx_phone`, D1 del inventario), no el `PHONE_REGEX` local,
  más laxo.
- **El flujo de staff aprobado no cambia** en el caso normal: cliente nuevo →
  crea; cliente conocido con el mismo nombre → reutiliza, como hoy. Lo único
  nuevo es que el caso ambiguo pregunta en vez de inventar.

### 4.10 Cambiar `Owner.phone`: la identidad se mueve, y hay que serializarla

Cambiar el teléfono de un cliente es **mover la clave de deduplicación**: libera
una y ocupa otra. Hoy ocurre en dos vías (C1 y C2 del inventario), ninguna con
lock ni comprobación, y una de ellas —la ficha de la mascota— ni siquiera parece
una operación de identidad.

**Bloqueo determinista de las dos claves.** La operación toma el lock de
deduplicación del teléfono **anterior** y del **nuevo**, ambos, en un **orden
total fijo** (el de la clave normalizada). El orden fijo no es cosmético: sin él,
dos cambios cruzados (A→B y B→A) se bloquean mutuamente y PostgreSQL aborta uno
por deadlock. Con orden total, uno espera y el otro termina.

- Si el teléfono no cambia (mismo valor normalizado), no hay identidad que
  mover: la operación se comporta como una edición corriente.
- Si el teléfono nuevo no normaliza a una clave (vacío, en el caso del dato
  importado), no hay clave que ocupar: solo se libera la anterior.

**Comprobación y guardado sin ventana entre medias.** Bajo esos locks, en la
misma transacción:

1. Se recomputa el normalizado con la función única.
2. Se cuentan los `Owner` no genéricos de la organización con el teléfono
   **nuevo**, excluyendo la propia fila.
3. Se decide y **se escribe en el mismo bloque**.

| Conteo del teléfono nuevo (excluyendo la fila) | Resultado |
|---|---|
| 0 | **se escribe** el teléfono y su normalizado |
| 1 | **`409 owner_exists`**: mover ahí fabricaría un duplicado nuevo. Cero escrituras |
| ≥ 2 | **`409 owner_ambiguous`** (duplicado histórico, INV-C): cero escrituras, se ordena el dato primero |

Exigencia de implementación, no de estilo: **la comprobación no puede vivir en
`Serializer.validate`**. DRF valida y guarda en pasos separados; un chequeo allí
y un `save()` después es precisamente la ventana que esta sección elimina. La
comprobación vive en el servicio, bajo los locks, junto a la escritura.

**Cero escrituras parciales.** Un `409` en la vía anidada (`PATCH /api/pets/`)
no deja ni el teléfono cambiado ni los campos de la mascota guardados: la
operación entera es una transacción. Hoy `PetSerializer.update` guarda el
`Owner` y luego la `Pet` en dos `save()` sueltos; eso pasa a estar dentro del
mismo `atomic()`.

**Lo que no cambia**: el staff sigue pudiendo corregir un teléfono mal
capturado, desde Clientes o desde la ficha de la mascota. Lo único que ya no
puede es mover un cliente **encima** de otro sin que nadie lo note.

### 4.11 Los lectores de identidad del agente (bloqueador de la revisión OCR)

**El problema exacto.** `agent/services.py` tiene dos lecturas de producción que
resuelven identidad por teléfono:

- **Creación de `ContactIdentity`** (primer mensaje de un número): calcula el
  valor normalizado del `wa_id` con `normalize_wa_id` y lo compara **contra la
  columna cruda**: `filter(phone=<normalizado>, is_generic=False)[:2]`.
- **`_rematch_owner`** (cada mensaje posterior de un contacto aún `unknown`):
  el mismo patrón, con `contact.phone_normalized` contra `Owner.phone`.

Ambas ya distinguen «una» de «varias» —si ve dos, marca `is_ambiguous`— así que
la intención estaba bien. **El bypass es el lado del que se compara**: un
expediente guardado como `"55 1234 5678"` y otro como `"5512345678"` normalizan
a la misma clave, pero la igualdad cruda solo encuentra el segundo. El lector ve
**una** coincidencia donde INV-C dice **ambigua**, y vincula la
`ContactIdentity` a esa fila. Es una **elección automática entre duplicados
históricos**: exactamente lo que INV-C prohíbe, por una puerta que el inventario
de escrituras no miraba.

Que el nivel resultante sea `phone_match` —que no autoriza nada por sí solo
(`tools._verification_ok` exige además `owner_id`)— **no lo hace inocuo**: ese
vínculo es el punto de partida de la promoción a `confirmed_in_chat`, y arrastra
consigo el expediente equivocado.

**La regla.** Las dos lecturas usan el **mismo resolvedor** que las escrituras,
en su modo de solo lectura:

| Aspecto | Contrato |
|---|---|
| Clave | `Owner.phone_normalized`, **nunca** `Owner.phone` en crudo |
| Unión | normalizado ↔ normalizado: `ContactIdentity.phone_normalized` contra `Owner.phone_normalized` |
| Alcance | `for_organization(...)` **siempre primero** + `is_generic=False` (§4.12) |
| Selección | **ninguna**: el resolvedor cuenta, no elige. `.first()` y `[:2]` como forma de decidir quedan prohibidos |

Desenlaces del modo lectura, alineados con los de escritura:

| Candidatos | Resultado para el lector | Efecto |
|---|---|---|
| 0 | sin expediente | `ContactIdentity` queda `unknown`, sin `owner`. Comportamiento actual |
| 1 | expediente único | vínculo `phone_match` como hoy — **sin cambio de comportamiento** |
| ≥ 2 | **`owner_ambiguous`** | **no se vincula ningún `owner`**, `is_ambiguous=True`, el nivel **no** sube, y **`auto_rematch_blocked` no se toca ni se limpia**. Si el flujo en curso requiere resolverlo (p. ej. un alta), escala por la vía segura de FLUJO-C en vez de adivinar |

Reglas que acompañan, para que la corrección no se deshaga sola:

- **La ambigüedad nunca limpia `auto_rematch_blocked`.** Ese flag solo lo limpia
  una de las cuatro vías de promoción auditadas (§4.4); un lector no es ninguna
  de ellas.
- **Un contacto ambiguo no se «desambigua» solo.** `_rematch_owner` vuelve a
  correr en mensajes posteriores: si el dato se ordenó y queda un único
  candidato, entonces sí vincula. Que el conteo cambie es información del
  dominio, no una decisión del lector.
- **El modo lectura no toma el lock de deduplicación.** No lo necesita: no crea
  ni mueve claves. Su peor caso es un resultado que envejece —un alta concurrente
  puede volver ambiguo lo que se leyó único—, y ese caso se corrige solo en el
  siguiente mensaje. Escribir un `phone_match` de más nunca autoriza nada por sí
  mismo; lo que este cambio impide es que ese `phone_match` apunte a un
  expediente **elegido** entre duplicados.
- **Respuesta explícita a la pregunta de la revisión**: sí, «`patients`, el
  importador y el agente convergen» **incluye** la creación de contacto y el
  rematch de `agent/services.py`. Estaban implícitos y por eso se colaron; ahora
  son las filas E1 y E2 del inventario.

### 4.12 El `Owner` genérico, definido con precisión

El genérico existe para las ventas de mostrador y la atención sin cita
(`Público General` / `Propietario Genérico`), y nace con un teléfono de relleno
`'0000000000'` (`patients.utils`, `organizations.signals`). Ese relleno **no es
identidad de nadie** y no puede comportarse como si lo fuera.

| Aspecto | Regla |
|---|---|
| `phone_normalized` | **`NULL`**, siempre. Nunca `''` ni `'0000000000'`. `NULL` es la representación de «no tiene clave de cliente», y hace que quede fuera de cualquier índice parcial y de cualquier comparación por igualdad sin necesidad de recordarlo en cada consulta |
| Backfill de la migración | los `Owner` con `is_generic=True` reciben `NULL`, sin pasar por la normalización |
| Validación de teléfono de cliente | el validador compartido rechaza rellenos evidentes (`is_filler_phone`), así que el genérico **no lo pasaría**. El *bypass* de esa validación existe **solo** para `is_generic=True`, y solo ahí |
| Deduplicación y conteo | **excluido**: no cuenta como candidato en ninguna de las cuatro decisiones (`created`/`reused`/`owner_exists`/`owner_ambiguous`) |
| Locks | **no participa**: sin clave normalizada no hay clave de deduplicación que bloquear |
| Lectores de identidad (§4.11) | **excluido**: un contacto de WhatsApp jamás puede quedar vinculado al genérico por coincidencia de teléfono |
| Búsqueda (`?search`, dropdowns) | **excluido** de los resultados de identidad: no es un cliente al que se pueda «elegir» para colgarle una mascota. Sigue existiendo para los flujos que lo usan explícitamente (venta directa, ADR p25), que lo referencian por su condición de genérico, no por su teléfono |
| Su `phone` de texto | **se conserva** tal cual: hay código y datos que lo esperan, y cambiarlo sería una migración con riesgo y sin beneficio. Lo que cambia es que deja de tener una **clave** derivada |

Regla de una línea, para el ADR y para `system-reference.md` §4: **el teléfono
del `Owner` genérico nunca es identidad**.

---

## 5. Comportamiento cuando una precondición falla

Aplica a las dos familias de precondición: la de **estado** (INV-A,
`expected_state`) y la de **autorización** (INV-B/INV-C: identidad,
`require_new_owner` y unicidad de expediente).

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
| `require_new_owner` violado (existe **un** `Owner` con ese teléfono) | agente | `409 owner_exists` | ninguno: **no** se crea `Owner`, `Pet` ni `Appointment` | «Necesito que alguien del equipo confirme tus datos antes de registrarte 🙏» + **caso de verificación visible en Inbox**, con la intención preservada (§5.5) | `AGENT_COMMIT_OWNER_EXISTS` |
| Existe **más de un** `Owner` con ese teléfono normalizado (INV-C) | agente | `409 owner_ambiguous` con el **conteo**, nunca con la lista de candidatos | ninguno | mismo mensaje al cliente que `owner_exists` — la diferencia le importa al staff, no a él. El caso se abre igual (§5.5), con la nota de que hay varios expedientes | `AGENT_COMMIT_OWNER_AMBIGUOUS` |
| Existe más de un `Owner` con ese teléfono normalizado (INV-C) | recepción / staff | `409 owner_ambiguous` | ninguno | la UI dice que ese teléfono tiene varios expedientes y pide elegir/ordenar antes de continuar. **Nunca** se elige uno por el usuario | log del dominio |
| Alta de mascota (`POST /api/pets/`) cuyo teléfono ya tiene **un** expediente con **otro** nombre (§4.9) | recepción / staff | `409 owner_exists` con el candidato (`public_id`, nombre) | ninguno: no se crea `Owner` ni `Pet` | «Ese teléfono ya es de *Ana López*. ¿Es el mismo cliente?» → el usuario elige el expediente o corrige el teléfono. **Nunca** se crea un segundo expediente ni se decide por él | log del dominio |
| Cambio de `Owner.phone` hacia un número que ya tiene **un** expediente (§4.10) | recepción / staff | `409 owner_exists` | ninguno: ni el teléfono ni los demás campos editados se guardan | «Ese teléfono ya pertenece a otro cliente» — mover ahí fabricaría un duplicado | log del dominio |
| Cambio de `Owner.phone` hacia un número con **duplicados históricos** (§4.10) | recepción / staff | `409 owner_ambiguous` | ninguno | «Ese teléfono tiene varios expedientes; hay que ordenarlos primero» | log del dominio |
| Horario ocupado para ese veterinario (INV-D) | cualquiera | `400 slot_taken` (pre-chequeo **o** restricción de la base, indistinguible) | ninguno | agente: «Uy, justo se ocupó ese horario 😅 ¿Buscamos otra opción?» (ruta existente). Frontend: el hueco deja de estar disponible | evento de negocio (§5.4) |
| Horario ocupado — **atención sin cita** (§9.14) | recepción | mismo `400 slot_taken` | ninguno: la cita **no** se crea | la UI pide escoger alternativa (otro veterinario u otro horario). No hay forzado | evento de negocio |
| Horario ocupado — **reactivación** `canceled\|no_show → scheduled` (§9.15) | cualquiera | mismo `400 slot_taken` | ninguno: la cita sigue `canceled`/`no_show` | «ese horario ya está ocupado; hay que programarla de nuevo». Nada se desplaza ni se mueve solo | evento de negocio |
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

### 5.4 Observabilidad: el conflicto de negocio sale de la telemetría de averías

Los conflictos se cuentan como **evento de negocio**, separados de los errores
técnicos. Un `appointment_changed` frecuente no es un bug: es la señal de que
staff y agente están operando sobre las mismas citas al mismo tiempo, y es
información que produce decisiones. Los eventos no llevan PII: identificadores
públicos, estado y motivo.

**Esto exige un cambio, no solo una intención** (hallazgo X de la revisión).
Hoy `ToolExecutor.call()` registra `AGENT_TOOL_HTTP_ERROR` para **cualquier**
respuesta `>= 400` (`agent/executor.py`). Sin tocarlo, los desenlaces nuevos
contaminarían las alertas de integración — y los que ya existen (`slot_taken`,
`past_date`) ya las contaminan hoy.

Contrato del cambio:

| Aspecto | Regla |
|---|---|
| Declaración | Cada llamada declara qué códigos son **desenlaces de negocio esperados** para ella. No hay lista global implícita: un `owner_exists` es negocio en el alta y sería una anomalía en cualquier otra tool |
| Códigos declarados | `appointment_changed`, `already_done`, `owner_exists`, `owner_ambiguous`, `slot_taken`, `past_date`, `invalid_data` |
| Auditoría | La fila de `ToolExecution` **se sigue creando** con su `error_code`: es la traza, y no se pierde |
| Log | `AGENT_TOOL_BUSINESS_CONFLICT` (INFO, redactado: ids públicos, código, tool) **en vez de** `AGENT_TOOL_HTTP_ERROR` (WARNING) |
| Métricas | No cuentan como fallo de integración ni alimentan alertas de disponibilidad |
| Conducta | Nunca derivan en `tool_failure` ni en un `HumanHandoff` de fallo de sistema. El único hand-off que pueden producir es el **de identidad** de FLUJO-C, que es un caso de negocio |
| Lo no declarado | Sigue siendo `AGENT_TOOL_HTTP_ERROR` con su comportamiento actual. El silencio por defecto sería el fail-open de la observabilidad |

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
| 1 | **Pendiente** | `409 owner_exists` **o** `409 owner_ambiguous` en el commit → transición atómica de §5.5.4 (suspender + hand-off `REASON_IDENTITY` con `reason_detail = 'owner_exists' | 'owner_ambiguous'`) | nadie aún | sin tocar | `HANDOFF_PENDING`; intención suspendida en `flow['suspended']`; el bot calla |
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

**Enlace estricto (hallazgo W de la revisión).** Tener cuatro FKs no prueba que
apunten al mismo caso: sin más reglas, una aprobación emitida para el Owner A
podría usarse para autorizar el vínculo con el Owner B, o una resolución mal
formada podría dejar auditoría cruzada entre organizaciones. Ambas cosas
anularían el RBAC y la trazabilidad que justifican FLUJO-C. El vínculo se ata
así:

| Dato | De dónde sale | Prohibido |
|---|---|---|
| `organization` | `conversation.organization` | tomarla del body o de `request.user` sin comparar |
| `conversation` | la ruta, vía `_get_conversation` (tenant-scoped) | resolverla por id del body |
| `contact` | `conversation.contact` | aceptar un `contact` del body |
| `owner_candidate` | resuelto **solo** con `Owner.objects.for_organization(conversation.organization)` por `public_id` | cualquier lookup sin `for_organization`; cualquier uso del PK entero |
| `handoff` | el `HumanHandoff` **abierto** de esa conversación con `reason_code='identity'` y `reason_detail ∈ {owner_exists, owner_ambiguous}` | resolver un handoff por id del body; aceptar uno ya resuelto o de otra conversación |
| `actor` | `request.user` | leerlo del body (se ignora si viene) |

Precondiciones de **autorizar** (4), todas verificadas en el mismo `atomic()`,
con `select_for_update()` sobre `ContactIdentity` **y** sobre el `HumanHandoff`:

1. Existe un hand-off de identidad **abierto** para esta conversación.
2. El **último** registro de verificación para `(contact, owner_candidate)` es
   `approved` **y** su `handoff` es exactamente ese hand-off abierto **y** su
   `conversation` es esta conversación. Si el último es `rejected`, o pertenece
   a otro caso/candidato → `409 verification_required`.
3. El `owner_candidate` sigue existiendo en la organización de la conversación
   → si no, `409 owner_changed`.
4. `contact.owner_id is None` → si ya está vinculado, `409 already_linked` con
   el vínculo vigente.

El invariante de organización (`organization` idéntica en conversación,
contacto, candidato, hand-off y registro) se valida **en el servicio y en el
modelo**, no solo en la vista: una vía futura que escriba el registro sin pasar
por el endpoint no puede saltárselo. Un desajuste es un error de programación,
no un 400 de usuario: falla ruidosamente y no persiste nada.

#### 5.5.3 Evidencia y auditoría

`ContactIdentity` guarda `verified_at` pero **no guarda quién verificó**, y no
puede representar un **rechazo** (no hay «nivel de verificación negativo»). El
punto 3 del flujo aprobado exige quién, cuándo y **resultado**, así que hace
falta un registro propio, **append-only** —consistente con el invariante de
auditoría del sistema (`system-reference.md` §3.3)—:

| Campo | Contenido | Nota |
|---|---|---|
| `organization` | FK | aislamiento de tenant desde el día 0; igual a la de todas las demás FKs |
| `contact` | FK → `ContactIdentity` | derivado de la conversación |
| `owner_candidate` | FK → `patients.Owner` | el expediente en disputa; resuelto solo dentro de la organización de la conversación |
| `conversation` | FK | trazabilidad con el caso |
| `handoff` | FK → `HumanHandoff` | **campo añadido por la revisión**: ata la aprobación al caso concreto. Sin él, «la aprobación es del caso abierto» sería una intención, no una regla |
| `decision` | `approved` \| `rejected` | |
| `evidence_kind` | tipificado: `in_person_id` \| `known_record` \| `callback` \| `other` | ninguna opción basada en el teléfono |
| `evidence_note` | texto sanitizado, corto | qué comprobó la persona |
| `actor` | FK → `users.User` | server-side, **nunca** del body |
| `created_at` | server-side | |

Append-only: sin `PATCH`, sin `DELETE` (405), como el resto de la auditoría del
sistema.

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

#### 5.5.4 Preservación de la intención: una sola transición atómica

Este es el hallazgo Q de la revisión de plan, y es el más peligroso de todos
porque **falla en silencio y destruye justo lo que el Item existe para
proteger**.

**El problema exacto.** `_commit_pending` llama a
`confirmations.clear_pending(conversation)` **antes** de evaluar el resultado
(`planner.py`), y `clear_pending` hace su propio `save()`
(`confirmations.py`). Si la rama de `owner_exists` escala «tal cual»,
`escalate_to_human` ya no encuentra ningún `pending_action` que suspender
(`policy.py`) y la intención se pierde. Y aunque se reordenaran las llamadas,
**seguirían siendo dos `save()` distintos**: una excepción, un reinicio del
worker o una carrera entre ambos deja la conversación sin pendiente y sin
suspensión — con el `409` ya devuelto y el cliente esperando.

**La regla.** Un helper **idempotente y único** ejecuta, dentro de un solo
`transaction.atomic()` y con `select_for_update()` sobre `Conversation`:

1. Re-lee `flow` bajo el lock (read-modify-write, nunca sobre una instancia
   vieja).
2. Copia el `pending_action` **íntegro** a `flow['suspended']` con
   `suspension_id`, `suspended_at` y `handoff_reason='identity'` (§6.1). El
   staged no se reescribe ni se recorta: TC-SEC-03 sigue valiendo.
3. Elimina `flow['pending_action']`.
4. Crea **o retiene** el `HumanHandoff` de identidad con su `reason_detail`
   (`owner_exists` | `owner_ambiguous`). Retener significa: si ya había uno
   abierto para esta conversación, se reutiliza; no se abren dos casos por el
   mismo hecho.
5. Deja `state = HANDOFF_PENDING`.

Todo eso es **un commit**. Si algo falla, no queda ni medio estado: ni pendiente
huérfano, ni suspensión sin caso, ni caso sin intención.

**Consecuencias en el planner, explícitas para no reintroducir el bug:**

- `_commit_pending` **deja de limpiar el pendiente a ciegas** justo después del
  handler. La limpieza pasa a ser responsabilidad de cada desenlace: los que hoy
  limpian siguen limpiando (mismo comportamiento observable), y los que
  suspenden lo hacen **dentro** de la transición atómica.
- La rama de `owner_exists`/`owner_ambiguous` **no puede** usar el
  `clear_pending` genérico ni el `escalate_to_human` genérico por separado. Está
  prohibido explícitamente: son las dos llamadas cuya separación causa el bug.
- Que el comportamiento de las ramas existentes no cambie es una **regresión
  bloqueante** (P2-11), no una suposición.

El caso resultante muestra al staff qué pidió el cliente (nombre, mascota,
especie, día y hora) sin que nadie tenga que leer el transcript entero.

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

### 5.6 El release aplica su veredicto solo sobre el mundo que verificó (D11)

Hallazgos R y T de la revisión. La formulación anterior —«si el `suspension_id`
cambió no se aplica el veredicto, pero el release sí procede»— tenía un agujero
real: liberar la conversación, quitar el claim y resolver el hand-off **son**
mutaciones. Aplicarlas sobre una suspensión que nadie verificó puede resolver el
caso equivocado y dejar una intención inerte o perdida. Y revisar el lease solo
en R1 permite que el worker tome un turno, o que otra persona reclame la
conversación, durante la llamada HTTP de R2 —que corre fuera del lock a
propósito—.

**El testigo de release.** R1 captura, bajo el lock, cinco datos:

| Campo | Por qué está |
|---|---|
| `flow['suspended']['suspension_id']` | es la propuesta que se está juzgando |
| `state` | una conversación cerrada o re-escalada no se libera con un veredicto viejo |
| `claimed_by_id` | otra persona pudo reclamarla mientras tanto: su claim no se pisa |
| `processing_until` | el worker pudo tomar el turno después de R1 (`worker._claim_turn` lo hace bajo lock corto) |
| id del `HumanHandoff` abierto observado | se resuelve **ese** caso, no «el último abierto», que puede ser otro. R3 comprueba **dos cosas**: que el id sea el mismo **y** que ese hand-off **siga abierto** (`resolved_at` nulo). Un mismo id ya resuelto por otra persona no autoriza a resolverlo de nuevo |

**La regla de aplicación (compare-and-set).** En R3, bajo el mismo lock, se
vuelve a leer el testigo completo:

| Situación | Qué hace el servicio |
|---|---|
| El testigo coincide en los cinco campos | aplica el veredicto **y** las mutaciones de release en el mismo commit |
| Algún campo difiere, primer intento | **no muta nada** y repite el ciclo R1–R3 una sola vez, con el snapshot nuevo |
| Algún campo difiere, segundo intento | **no muta nada** y responde `409 release_conflict` con un `reason` (`suspension_changed` \| `turn_in_progress` \| `claim_changed` \| `state_changed` \| `handoff_changed`) y el estado actual, para que el staff decida |

Un solo reintento, no un bucle: si en dos vueltas el mundo sigue moviéndose, hay
alguien más operando y la respuesta correcta es decírselo a quien pulsó el botón,
no insistir.

**Serialización de las acciones de bandeja.** `claim_conversation` hace hoy un
read-modify-write sin lock (`agent/views.py`), así que dos personas pueden
reclamar «a la vez» y el release puede pisar un claim legítimo. Reclamar,
liberar y cerrar pasan a **serializarse sobre la misma fila** (`select_for_update`
+ comparación explícita del estado leído). Es la condición sin la cual el
testigo de arriba no significa nada: no se puede comparar contra algo que otro
camino escribe sin lock.

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

**Escritores de `flow['suspended']` — exactamente dos, y ambos atómicos:**

| Escritor | Cuándo | Transacción |
|---|---|---|
| `escalate_to_human` | escalada ordinaria (urgencia, fallo de tool, petición explícita) | pasa a escribir bajo el mismo helper atómico de §5.5.4 — la suspensión y el hand-off en un commit |
| la transición de `owner_exists` / `owner_ambiguous` | conflicto de identidad en el commit | §5.5.4, con `handoff_reason='identity'` y su `reason_detail` |

No hay una tercera vía. Cualquier código que quiera «guardar el pendiente para
después» usa el helper; escribir `flow['suspended']` a mano vuelve a abrir el
hueco Q.

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
| `create_appointment` | sí (`tools.py:836, 853`) | `UniqueConstraint(org, idempotency_key)` + replay 200 (ADR p52) + **restricción de no-solapamiento** (INV-D): dos claves distintas hacia el mismo hueco ya no pueden persistir ambas |
| `register_new_client_and_pet` | sí (`tools.py:1121, 1141`) | ídem (`views.py:305-314`) + **lock de deduplicación** (INV-C): dos claves distintas con el mismo teléfono ya no pueden crear dos expedientes |
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
| | `409 owner_exists` (`require_new_owner`) | commit | §5.2: no escribir; **transición atómica** de §5.5.4 (suspender + caso), nunca `clear_pending` + escalada por separado | «necesito que alguien del equipo confirme tus datos 🙏» | `AGENT_COMMIT_OWNER_EXISTS` | No |
| | `409 owner_ambiguous` (INV-C: ≥2 expedientes con ese teléfono) | commit | idéntico al anterior, con `reason_detail='owner_ambiguous'` | mismo mensaje | `AGENT_COMMIT_OWNER_AMBIGUOUS` | No |
| | `400 slot_taken` por la **restricción** de no-solapamiento (INV-D) | commit / cualquier escritura | ruta existente de `slot_taken`: se ofrece otro horario | «uy, justo se ocupó ese horario 😅» | evento de negocio (§5.4) | No |
| | `identity_changed` (C2/C3/C4) | commit, pre-HTTP | §5.2: no escribir; seguir por la vía de cliente conocido | «ya te tengo registrado ✅ ¿te agendo la cita?» | `AGENT_COMMIT_IDENTITY_CHANGED` | No |
| **Expirado** | `is_expired(pending)` — **siempre true** en el primer intento tras un release | 1ª confirmación | re-stage con TTL fresco + `EXPIRED_REPARAPHRASE`; **no ejecuta** | la propuesta completa, re-mostrada | ninguno nuevo (ruta existente) | No |
| | conversación cerrada por inactividad (24 h) | cron | el `flow` muere con el hilo | **nada** (pérdida silenciosa preexistente, §6.4) | ninguno — **es el hueco** | No |
| **Error técnico** | timeout / 5xx / 599 en el chequeo de release | release | **restaurar vencido** (falla segura) | nada | `AGENT_RELEASE_DOMAIN_CHECK_FAILED` | No |
| | 404 del recurso referenciado | release | consumir la suspensión sin restaurar | nada | `AGENT_RELEASE_PENDING_UNRESOLVABLE` | No |
| | `suspended` corrupto: `kind` ajeno, falta `tool`/`args`/`paraphrase`, tool desconocida, `suspended_at` ilegible o futuro | release, **antes** de llamar al dominio | consumir sin restaurar y **sin llamada HTTP** | nada | `AGENT_RELEASE_SUSPENSION_INVALID` (sin PII) | No |
| | `suspended` legacy `{kind, state}` sin campos nuevos, pero íntegro | release | **restaurar vencido** (nunca inferir vigencia por ausencia de `suspended_at`) | nada | `AGENT_RELEASE_PENDING_RESTORED` (+`legacy=true`) | No |
| | el **testigo de release** (suspensión, estado, claim, lease o hand-off) cambió entre R1 y R3 | release, R3 | **nada se muta**: se repite R1–R3 una vez; si vuelve a diferir, `409 release_conflict` con el `reason` (§5.6) | nada | `AGENT_RELEASE_CONFLICT` (+ campo que cambió) | No |
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
| **P0-15** | `test_flujo_c_end_to_end` | `agent/tests/test_inbox_api.py` | **Prueba de aceptación del recorrido completo** (hallazgo S): `owner_exists` → caso visible → verificar → autorizar → liberar → primer «sí» sin POST/PATCH y con re-paráfrasis → segundo «sí» con **el único commit permitido**. Es el gate que impide desplegar F4 sin F3 |
| **P0-16** | `test_concurrent_registrations_create_at_most_one_owner` | `appointments/tests/` (`TransactionTestCase`) | **INV-C, hallazgo O**: dos conexiones, dos claves de idempotencia distintas, misma organización y teléfono → **exactamente un** `Owner` nuevo, o `409` cerrado. Repetir mezclando actor agente y actor recepción. **PostgreSQL** |
| **P0-17** | `test_duplicate_historical_phone_fails_closed_as_ambiguous` | `appointments/tests/` + `patients/tests/` | **INV-C**: con dos `Owner` preexistentes del mismo teléfono normalizado → `409 owner_ambiguous` para el agente **y** para recepción; cero escrituras; **jamás** se elige uno ni se fusionan |
| **P0-18** | `test_no_overlapping_appointments_under_concurrency` | `appointments/tests/` (`TransactionTestCase`) | **INV-D, hallazgo U**: dos `POST` y dos `PATCH` simultáneos al mismo veterinario e intervalo → **solo una cita activa persiste**; la otra recibe `slot_taken`. Incluye la reactivación `canceled → scheduled` sobre un hueco ya ocupado. **PostgreSQL** |
| **P0-19** | `test_owner_exists_transition_survives_a_crash` | `agent/tests/test_write_tools.py` | **Hallazgo Q**: inyectar una excepción entre el `409 owner_exists` y la transición local → o bien todo quedó aplicado (staged íntegro en `suspended` + hand-off de identidad abierto), o bien nada; **nunca** un pendiente borrado sin suspensión |
| **P0-20** | `test_walk_in_and_reactivation_respect_no_overlap` | `appointments/tests/` | **INV-D sin excepciones (§9.14, §9.15)**: (a) `walk-in` sobre un veterinario con cita activa solapada → `400 slot_taken`, **cero** citas creadas y cero `AppointmentStatusChange`; (b) reactivar `canceled → scheduled` sobre un hueco ya ocupado → `400 slot_taken`, la cita sigue `canceled`, la existente intacta; (c) con el hueco libre, ambas operaciones siguen funcionando como hoy. **Ninguna bandera de forzado existe** |
| **P0-21** | `test_pets_endpoint_and_create_with_patient_are_serialized` | `patients/tests/` (`TransactionTestCase`) | **Hallazgo Z**: dos conexiones, una por `POST /api/pets/` y otra por `create-with-patient`, mismo teléfono → **exactamente un** `Owner` o un `409` cerrado. Cero duplicados fabricados. **PostgreSQL** |
| **P0-22** | `test_concurrent_phone_changes_to_the_same_number` | `patients/tests/` (`TransactionTestCase`) | **§4.10**: dos `Owner` distintos cambian a la vez al **mismo** teléfono nuevo → uno gana, el otro recibe `409`; ningún duplicado nuevo. Incluye el caso **cruzado** (A→B y B→A simultáneos): con el orden total de claves, ninguna transacción aborta por deadlock. **PostgreSQL** |
| **P0-23** | `test_phone_change_versus_new_registration` | `patients/tests/` (`TransactionTestCase`) | **§4.10 vs §4.7**: una transacción mueve un `Owner` al teléfono X mientras otra da de alta un cliente con X (por `/api/pets/`, `/api/owners/` o `create-with-patient`) → exactamente una persiste; la otra `409`. **PostgreSQL** |
| **P0-24** | `test_historical_duplicate_blocks_every_path` | `patients/tests/` + `appointments/tests/` | **INV-C, todas las vías**: con dos `Owner` preexistentes del mismo teléfono normalizado, `POST /api/pets/`, `POST /api/owners/`, `PATCH` de teléfono, `create-with-patient` e importador devuelven `owner_ambiguous` (el importador, error de fila) con **cero** escrituras. Ninguna elige una fila |
| **P0-25** | `test_owner_identity_tenant_isolation_and_no_partial_writes` | `patients/tests/` | **Aislamiento y atomicidad**: un `Owner` con el mismo teléfono en **otra** organización no interfiere en ninguna vía (ni bloquea, ni cuenta, ni aparece); y ante cualquier `409` no queda `Owner`, ni `Pet`, ni `Appointment`, ni el teléfono cambiado, ni los demás campos de la mascota guardados |
| **P0-26** | `test_agent_identity_readers_use_the_normalized_key` | `agent/tests/` + `patients/tests/` | **Bloqueador OCR (§4.11)**: dos `Owner` históricos que **solo tras normalizar** resultan iguales (p. ej. `"55 1234 5678"` y `"5512345678"`, o con `+52`/`52`/`521` delante) → tanto la **creación de `ContactIdentity`** como **`_rematch_owner`** devuelven `owner_ambiguous`: **cero vínculo**, `is_ambiguous=True`, nivel sin subir y **`auto_rematch_blocked` intacto**. Con un único candidato (aunque su formato crudo difiera del `wa_id`) → `phone_match`, como hoy. Con cero → `unknown`. Paridad exigida: el resolvedor devuelve lo mismo para el lector que para la escritura |
| **P0-27** | `test_import_preview_matches_commit_outcome` | `imports/tests/` | **Ajuste OCR (§4.8)**: con un duplicado histórico, las **tres** pasadas del importador (validación/preview, dry-run y commit) coinciden: la fila aparece desde el preview como `owner_ambiguous`, el conteo de importables ya la excluye, y ninguna pasada usa `.first()`. Nunca se previsualiza una reutilización que el commit rechazaría |
| **P0-28** | `test_generic_owner_has_no_normalized_key_and_is_never_identity` | `patients/tests/` | **Ajuste OCR (§4.12)**: el genérico creado por `patients.utils` **y** por el signal de alta de organización tiene `phone_normalized = NULL`; el backfill de la migración deja `NULL` en los genéricos preexistentes; el genérico no cuenta como candidato, no bloquea ninguna clave, no aparece en la búsqueda de identidad y **ningún contacto de WhatsApp puede quedar vinculado a él por teléfono**. La validación de teléfono de cliente se salta **solo** para `is_generic=True` |

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
| **P1-19** | `test_release_aborts_when_a_new_suspension_appears` | **Hallazgo R**: interleaving `R1 → nueva suspensión → R3` → ninguna mutación de `flow`, `state`, claim ni hand-off; respuesta de reintento/conflicto. La suspensión nueva sigue intacta |
| **P1-20** | `test_release_aborts_when_worker_claims_the_turn` | **Hallazgo T**: interleaving `R1 → el worker toma el lease → R3` → sin mutación, `409` con `reason='turn_in_progress'`; no se pierde ninguna clave de `flow` |
| **P1-21** | `test_release_aborts_when_another_staff_claims` | **Hallazgo T**: interleaving `R1 → otro staff reclama → R3` → el claim ajeno **no** se pisa; `409` con `reason='claim_changed'` |
| **P1-22** | `test_claim_and_release_are_serialized` | Dos `claim` simultáneos → uno gana, el otro `409 already_claimed`; un `claim` y un `release` simultáneos no dejan la conversación en un estado mixto (activa **y** reclamada) |
| **P1-23** | `test_delete_appointment_honors_precondition_and_is_deprecated` | `DELETE` con `expected_state` desfasado → `409`, cita intacta y **cero** `AppointmentStatusChange` adicionales; sin `expected_state` → comportamiento actual; la respuesta trae las cabeceras de deprecación |
| **P1-24** | `test_verification_approval_is_bound_to_case_and_candidate` | **Hallazgo W**: una aprobación de candidato A **no** autoriza al candidato B; una aprobación de un hand-off ya cerrado no vale; conversación u `Owner` de otra organización → 404 **sin** filas de auditoría ni vínculo |

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
| **P2-11** | `test_commit_branches_still_clear_pending_as_before` | **REGRESIÓN, iron rule**: al mover la limpieza del pendiente fuera del camino común (§5.5.4), los desenlaces existentes (`committed`, `slot_taken`, `past_date`, `invalid_data`, escalada genérica) siguen dejando `flow` exactamente como hoy |
| **P2-12** | `test_owner_resolution_has_a_single_entry_point` | **Gate de INV-C, ampliado por el hallazgo Z. Doble: funcional + estático.** *Funcional*: `/api/pets/`, `/api/owners/` (alta y edición), `create-with-patient` y el importador producen los desenlaces del servicio, y ninguna vía deja el teléfono normalizado obsoleto respecto de `phone`. *Estático*: el gate **no** puede limitarse a `get_or_create(...phone...)` — debe detectar también `get_or_create(...name..., ...phone...)`, construcciones multirrenglón (`Owner(` … `.save()`), **asignaciones a `phone` seguidas de `save()`** y —tras la revisión OCR— **cualquier `filter`/`get` sobre `Owner` por `phone` crudo**, que es la forma que tomó el bypass de lectura. Un grep de una sola línea sobre las escrituras es exactamente lo que dejó pasar los hallazgos Z y el bloqueador OCR |
| **P2-14** | `test_pet_creation_staff_flow_unchanged` | **REGRESIÓN, iron rule (§4.9)**: alta de mascota con cliente nuevo → crea `Owner` + `Pet` como hoy; con cliente existente y **mismo** nombre → reutiliza como hoy; editar una mascota **sin** tocar el teléfono guarda igual que hoy. Lo único nuevo es el `409` del caso ambiguo |
| **P2-15** | `test_generic_owner_never_participates_in_deduplication` | El `Owner` genérico (teléfono de relleno `0000000000`) no cuenta en la deduplicación, no bloquea ninguna clave y no puede ser devuelto como candidato (`reused`) por ninguna vía (A5 del inventario) |
| **P2-13** | `test_business_conflicts_are_not_technical_failures` | **Hallazgo X**: `appointment_changed`, `owner_exists`, `owner_ambiguous` y `slot_taken` producen evento de negocio redactado, **no** elevan `AGENT_TOOL_HTTP_ERROR`, no cuentan como fallo de integración y **no** crean un hand-off de `tool_failure`. La fila de `ToolExecution` sí se crea |

### 8.4 Condición de ejecución y pruebas que exigen PostgreSQL

La revisión de seguridad **no pudo ejecutar la suite** en este worktree
(`ModuleNotFoundError: No module named 'django'`), así que la línea base está
identificada por lectura, no verificada. **Correr la suite completa de
`agent/` y `appointments/` en verde es parte del gate de aprobación**, no un
paso posterior.

**Ninguna prueba de carrera vale en SQLite.** Los tres mecanismos que este
documento adopta —lock de aviso de deduplicación, restricción de exclusión y
compare-and-set bajo `select_for_update`— o no existen o son no-ops en SQLite:
una suite verde ahí sería una garantía imaginaria. Corren sobre PostgreSQL, con
`TransactionTestCase` y dos conexiones reales:

| Prueba | Qué garantiza |
|---|---|
| P0-16 | un solo `Owner` por teléfono bajo concurrencia (INV-C) |
| P0-17 | duplicado histórico → `owner_ambiguous`, nunca elección |
| P0-18 | no-solapamiento real en creación **y** reprogramación (INV-D) |
| P0-20 | atención sin cita y reactivación respetan INV-D, sin excepción ni forzado (§9.14, §9.15) — la parte concurrente de este caso vive en P0-18 |
| P0-21 | `/api/pets/` y `create-with-patient` compiten por el mismo teléfono: un solo `Owner` o `409` |
| P0-22 | dos cambios de teléfono al mismo número, incluido el caso cruzado (sin deadlock, por el orden total de claves) |
| P0-23 | cambio de teléfono contra alta nueva sobre el mismo número |
| P0-24 | duplicado histórico: **todas** las vías del inventario fallan cerrado como `owner_ambiguous` |
| P0-25 | aislamiento por tenant y ausencia de escrituras parciales en todas las vías de identidad |
| P0-26 | los **lectores** del agente (creación de contacto y rematch) resuelven por clave normalizada: duplicado distinguible **solo tras normalizar** → `owner_ambiguous`, sin vínculo y sin tocar `auto_rematch_blocked` |
| P0-27 | paridad preview ↔ commit del importador ante un duplicado histórico |
| P0-28 | el `Owner` genérico tiene `phone_normalized = NULL` y queda fuera de búsqueda, locks, deduplicación e identidad |
| P0-19 | la transición `owner_exists` es todo-o-nada |
| P1-6, P1-7 | release vs. nudge y release vs. release |
| P1-14 | dos escritores con el mismo `expected_state`: hay lock, no solo comparación |
| P1-16 | dos autorizaciones simultáneas → un solo vínculo |
| P1-19, P1-20, P1-21, P1-22 | los cuatro interleavings del release y la serialización del claim |

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

**9.12 — [CERRADA · APROBADA] Más de un `Owner` con el mismo teléfono
normalizado en la organización ⇒ `owner_ambiguous` y escalada a staff.** El
sistema **nunca** fusiona registros ni elige uno automáticamente (INV-C).
*Consecuencias asumidas*: la unicidad de teléfono **no** se impone con una
restricción única —sería incompatible con tolerar duplicados históricos—, sino
con un lock transaccional sobre la clave de deduplicación (§4.7); los duplicados
existentes se **detectan** con un comando de auditoría y se ordenan a mano, sin
migración destructiva (§4.8); una clínica con duplicados verá `owner_ambiguous`
también en su alta manual hasta que ordene el dato, y eso es preferible a mezclar
dos expedientes clínicos.

**9.13 — [CERRADA · APROBADA] Un veterinario no puede tener dos citas activas
solapadas.** Es invariante de dominio para **todos los actores** y se garantiza
de forma atómica en PostgreSQL (INV-D). Una configuración futura de
capacidad/concurrencia por clínica queda **fuera de alcance**.
*Consecuencias asumidas*: la restricción cubre también la **atención sin cita** y
la **reactivación**, ambas aprobadas por separado en §9.14 y §9.15; hay que
auditar y ordenar los solapes históricos **antes** de aplicar la migración,
porque PostgreSQL no admite añadir la restricción sobre datos que la violan; el
contrato de error se mantiene en `400 slot_taken` por compatibilidad, con el
`code` tipificado añadido.

**9.14 — [CERRADA · APROBADA] La atención sin cita no puede crear un solape.**
Un `walk-in` no puede crear una cita activa que se solape con otra del mismo
veterinario: recibe `slot_taken` y recepción **escoge alternativa** (otro
veterinario u otro horario).
*Consecuencias asumidas*: es un cambio de comportamiento en mostrador —hoy el
`walk-in` no comprueba nada y siempre crea la cita—, y ocurre con el paciente ya
presente. Se acepta a cambio de que la agenda no mienta: dos atenciones
simultáneas del mismo veterinario nunca fueron reales, solo estaban registradas
como si lo fueran. **No hay bandera de forzado ni permiso que lo salte** (§3.4).

**9.15 — [CERRADA · APROBADA] Reactivar una cita cancelada no puede desplazar ni
solaparse.** Una transición `canceled`/`no_show → scheduled` sobre un intervalo
ya ocupado recibe `slot_taken` y **exige una programación nueva**; la cita
permanece en su estado terminal y nada se mueve automáticamente.
*Consecuencias asumidas*: hoy esa transición no valida cupo, así que reactivar
sobre un hueco reasignado «funciona» y produce dos citas a la misma hora. El
comportamiento nuevo es coherente con el guard de fecha pasada que ya existe en
esa misma transición: si el mundo cambió, se programa de nuevo.

**Alcance común de §9.14 y §9.15**: **no existen excepciones en Item 2**. Espera,
sobrecupo o múltiples recursos (varios consultorios, agendas paralelas) serán una
**feature separada**, con su propio diseño, su propio ADR y su propia revisión —
no una extensión de este trabajo ni una bandera añadida después.

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
resolución fuera de banda (§3.5). ¿Se extiende el mismo tratamiento a todos los
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
- **Fricción operativa de INV-D, con el comportamiento ya aprobado** (§9.14,
  §9.15): la atención sin cita puede ser rechazada por cupo con el paciente en
  el mostrador, y una cita cancelada puede no poder reactivarse sobre su horario
  original. Ya no es una consecuencia pendiente de ratificar — es la conducta
  decidida. Lo que queda como riesgo es **operativo**: hay que avisar a
  recepción antes del deploy y tener claro el gesto siguiente (escoger otro
  veterinario u otro horario), porque el sistema ya no va a aceptar el atajo. Si
  el volumen de rechazos resultara alto, la señal a mirar es la capacidad real
  de la agenda, no relajar el invariante: espera y sobrecupo son una feature
  separada.
- **Solapes históricos bloquean la migración de INV-D** hasta que cada clínica
  los ordene (§3.4). No se corrigen automáticamente porque cancelar o mover una
  cita real sin que nadie lo decida es peor que el solape. El coste es una tarea
  operativa previa al deploy, con su comando de auditoría.
- **Duplicados de teléfono preexistentes degradan la experiencia de esa
  clínica** (§4.8): mientras existan, esas altas —del agente y de recepción—
  terminan en `owner_ambiguous`. Aceptado por INV-C.
- **El lock de deduplicación cubre a quien lo toma** (§4.7.4): la garantía vale
  para los caminos enumerados. Una vía nueva que cree `Owner` con teléfono sin
  pasar por el servicio único vuelve a abrir el hueco; por eso hay gate de
  regresión (P2-12) y regla en `system-reference.md`, no solo buena voluntad.
  La 2ª revisión demostró que este riesgo **no es teórico**: la primera versión
  del inventario tenía tres entradas y faltaban dos vías vivas. El control real
  es el inventario cerrado por familias (A/B/C/D) más el grep gate, no la
  fórmula «cualquier vía futura».
- **El alta de mascota pregunta donde antes inventaba** (§4.9): un teléfono ya
  registrado con **otro** nombre pasa de crear un segundo expediente en silencio
  a devolver `409` con el candidato. Es más fricción en un caso real —el mismo
  cliente escrito de dos formas— y es deliberada: la alternativa era seguir
  fabricando los duplicados que INV-C obliga a tratar como ambiguos.
- **El importador deja de elegir entre duplicados**: filas que hoy se importan
  reutilizando la primera coincidencia pasarán a reportarse como
  `owner_ambiguous` y a saltarse. Es coherente con su política vigente (una fila
  problemática no aborta el import, se reporta), pero cambia el conteo de
  importadas en clínicas con el dato sucio.
- **Un contacto que hoy queda vinculado pasará a quedar ambiguo** cuando su
  teléfono coincida con dos expedientes tras normalizar (§4.11). Es la conducta
  correcta —el vínculo actual apunta a un expediente elegido a ciegas—, pero
  para esa clínica significa que el cliente deja de ser reconocido hasta que
  alguien ordene el dato. La señal a mirar es el reporte de duplicados, no el
  número de contactos ambiguos.
- **El modo lectura no toma el lock** (§4.11): un alta concurrente puede volver
  ambiguo lo que se acaba de leer como único. Aceptado: el `phone_match`
  resultante no autoriza nada por sí solo y el siguiente mensaje lo reevalúa.
  Lo que sí queda cerrado es la **elección** entre duplicados.
- **`Owner` fuera del admin de Django** (C4): la exclusión vale mientras nadie lo
  registre. Queda escrito en el ADR precisamente porque registrarlo sería un
  cambio de una línea que reabre el vector sin que nadie lo relacione.
- **`release_conflict` traslada trabajo al staff** (§5.6): cuando el mundo se
  mueve dos veces seguidas, el botón responde «vuelve a intentarlo» en vez de
  resolverlo solo. Es deliberado: la alternativa era aplicar un veredicto sobre
  un caso que nadie verificó.

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

**Verificadas en la segunda ronda (revisión de plan):**

- `patients/models.py` — `Owner.phone` es `CharField(blank=True)` **sin**
  unicidad por `(organization, phone)`; los índices son GIN de trigramas para
  búsqueda por substring, no para igualdad. Es la base del hallazgo O.
- `imports/services.py` — el importador deduplica por `(org, phone)` con
  `filter(...).first()` y admite owners sin teléfono (`dedup_key` nulo); tercera
  vía que hoy resuelve expedientes por teléfono con su propia definición.
- `appointments/serializers.py` — la detección de conflictos es
  `conflicts.exists()` seguida de `save()`, sin lock ni exclusión: base del
  hallazgo U.
- `appointments/models.py` — no hay constraint de solape; `start_datetime` /
  `end_datetime` son nullable y `veterinarian` es `SET_NULL`, lo que determina el
  predicado parcial de §3.4.
- `appointments/views.py` — `AppointmentDetailView.destroy` cancela y escribe
  `AppointmentStatusChange` sin lock ni precondición (hallazgo V);
  `update_status` no revalida cupo al reactivar desde `canceled`/`no_show`;
  `walk_in` crea `in_progress` **sin** verificar solapes.
- `appointments/services.py` — `complete_appointment_on_record_close`: UPDATE
  condicional deliberado, sin `select_for_update`, para no crear un orden de
  locks `Appointment↔MedicalRecord` que generaría ABBA con `assign-patient`.
  Justifica su exclusión en §3.3.
- `agent/views.py` — `claim_conversation` es read-modify-write **sin** lock
  (hallazgo T); `release_conversation` resuelve «el último hand-off abierto»,
  no uno identificado.
- `agent/worker.py` — `_claim_turn` toma el lease bajo lock corto y puede
  adquirirlo **después** de R1, durante la llamada HTTP de R2.
- `agent/executor.py` — `call()` registra `AGENT_TOOL_HTTP_ERROR` para
  **cualquier** `>= 400`, incluidos los 400 de negocio actuales (hallazgo X).
- `agent/planner.py` — `_commit_pending` llama a `clear_pending` justo después
  del handler y antes de evaluar el resultado (hallazgo Q).
- `patients/migrations/0012` — precedente de creación de extensión de
  PostgreSQL dentro de una migración (`TrigramExtension`), aplicable a
  `btree_gist` en §3.4.

**Verificadas en la tercera ronda (2ª revisión de Codex, hallazgo Z):**

- `patients/serializers.py`, `PetSerializer.create` —
  `Owner.objects.get_or_create(name=…, phone=…, organization=…)`: **segunda
  regla de deduplicación** del sistema, por `(nombre, teléfono)`. Es la que
  fabrica duplicados cuando el nombre difiere y la que cuelga una mascota de un
  expediente localizado por teléfono (§4.9).
- `patients/serializers.py`, `PetSerializer.update` — escritura anidada
  `owner.phone = …; owner.save()` seguida de `instance.save()`: dos `save()`
  sueltos, sin transacción, sin lock y sin comprobación de duplicados (§4.10).
- `patients/serializers.py`, `PHONE_REGEX` — tercera validación de formato de
  teléfono, más laxa que `validate_mx_phone` (no rechaza rellenos).
- `patients/views.py`, `OwnerViewSet` — `ModelViewSet` completo: `perform_create`
  guarda sin deduplicar y el `PATCH/PUT` cambia el teléfono sin comprobación.
- `patients/utils.get_or_create_generic_patient` y
  `organizations/signals.initialize_organization` — el `Owner` genérico nace con
  teléfono de relleno `'0000000000'`; de ahí que el conteo del servicio deba
  excluir los genéricos (A5 del inventario, P2-15).
- `imports/services._resolve_owner` — `filter(phone=…, is_generic=False).first()`:
  **elige** una fila entre duplicados, que es justo lo que INV-C prohíbe.
- `patients/admin.py` — `Owner` **no** está registrado en el admin de Django
  (C4 del inventario: excluida hoy, con la advertencia de que registrarlo la
  convertiría en una vía viva).
- `frontend/src/pages/pets.jsx` + `api/pets.js` — el alta y la edición de
  mascota envían `owner: {name, phone}` anidado; son los consumidores reales de
  las dos vías del hallazgo Z.

**Verificadas en la cuarta ronda (revisión OCR):**

- `agent/services.py` — creación de `ContactIdentity`:
  `Owner.objects.for_organization(org).filter(phone=<normalizado>, is_generic=False)[:2]`.
  Compara el valor normalizado del `wa_id` contra la **columna cruda**: es el
  bloqueador (§4.11). Ya distingue 1 de ≥2, pero sobre el conjunto equivocado.
- `agent/services._rematch_owner` — mismo patrón con
  `contact.phone_normalized` contra `Owner.phone`; corre en **cada** mensaje de
  un contacto aún `unknown`, así que el bypass no es de una sola vez.
- `agent/models.py` — `ContactIdentity.phone_normalized` (10 chars) e índice
  `(organization, phone_normalized)` **ya existen**: el lado del contacto estaba
  normalizado desde el día 1; faltaba el del expediente.
- `agent/services.normalize_wa_id` — segunda función de normalización del
  agente, hermana de `tools._wa_id_to_local10` (D2 del inventario).
- `imports/services.py` — **tres** lecturas por teléfono con `.first()`: la de
  validación/preview, la de dry-run y la de `_resolve_owner` (commit). Cambiar
  solo la última rompía la paridad preview ↔ escritura (§4.8).
- `patients/utils.py` y `organizations/signals.py` — el genérico nace con
  `phone='0000000000'`, un relleno que `core.validators.is_filler_phone`
  rechazaría en cualquier cliente real: de ahí que su bypass de validación deba
  estar acotado a `is_generic=True` y su clave normalizada sea `NULL` (§4.12).

---

## 12. Cierre de las revisiones de plan

Estado de los once hallazgos de la primera revisión
([`item-2-codex-plan-review.md`](item-2-codex-plan-review.md)) y del P0 de
[`item-2-codex-plan-review-round2.md`](item-2-codex-plan-review-round2.md) (§12.1). **Ninguna revisión se modifica**: se responden aquí y en el
plan.

| Hallazgo | Severidad | Estado | Resuelto en | Prueba que lo ancla |
|---|---|---|---|---|
| O — `require_new_owner` no atómico | P0 | **Resuelto por diseño** | §4.7 (servicio único + lock de deduplicación) | P0-16 |
| P — duplicados históricos | P0 | **Resuelto por producto (INV-C) + diseño** | §4.8 (auditoría, sin fusión, sin migración destructiva) | P0-17, P2-12 |
| Q — `owner_exists` borra la intención | P0 | **Resuelto por diseño** | §5.5.4 (transición atómica única) | P0-19, P0-10, P2-11 |
| R — carrera de `suspension_id` | P0 | **Resuelto por diseño** | §5.6 (testigo + compare-and-set + `409 release_conflict`) | P1-19 |
| S — F4 antes que F3 | P0 | **Resuelto por secuencia** | plan §2 (F4 depende de F3) | P0-15 |
| T — R3 no revalida lease ni claim | P1 | **Resuelto por diseño** | §5.6 (cinco campos del testigo + serialización de claim/release/close) | P1-20, P1-21, P1-22 |
| U — cupo read-then-write | P1 | **Resuelto por producto (INV-D) + diseño** | §3.4 (restricción de exclusión + migración + contrato de error) | P0-18 |
| V — contrato incompleto (`DELETE`, `assign-patient`) | P1 | **Resuelto por diseño** | §3.3 (matriz completa; `DELETE` incluido y deprecado) | P1-23 |
| W — aprobación no atada a caso/candidato/tenant | P1 | **Resuelto por diseño** | §5.5.2 (enlace estricto), §5.5.3 (FK `handoff`) | P1-24, P0-12 |
| X — 409 de negocio en telemetría técnica | P1 | **Resuelto por diseño** | §5.4 (desenlaces declarados por llamada) | P2-13, P1-11 |
| Y — coordinación documental de Item 1 | P2 | **Resuelto por proceso** | §4.4 + DoD de F4 en el plan | P2-8 |

### 12.1 Segunda revisión: el inventario de vías (hallazgo Z)

| Hallazgo | Severidad | Estado | Resuelto en | Prueba que lo ancla |
|---|---|---|---|---|
| **Z — F1 no cubría dos vías reales que eluden el servicio único** (`item-2-codex-plan-review-round2.md`): `POST /api/pets/` (resolvía identidad con su propia regla, `(nombre, teléfono)`) y la **edición del teléfono de `Owner`** (`PATCH /api/owners/` y la escritura anidada de `PATCH /api/pets/`) | **P0** | **Resuelto por diseño** | §4.7.4 (inventario completo por familias A/B/C/D), §4.9 (alta de mascota con dos modos, sin identidad implícita por teléfono), §4.10 (cambio de teléfono con bloqueo determinista de las dos claves y sin ventana entre comprobar y guardar) | P0-21, P0-22, P0-23, P0-24, P0-25, P2-12 (ampliada), P2-14, P2-15 |

Lo que esta revisión corrige **no es una vía olvidada, sino un método**: la
versión anterior enumeraba tres consumidores y confiaba en la fórmula
«cualquier vía futura». Por eso la respuesta no es «añadir dos filas», sino
sustituir la enumeración por un **inventario cerrado por familias** —crear
`Owner`, asociar `Pet`, mutar `phone`, normalizar— donde cada vía **usa el
servicio** o queda **excluida con evidencia**, y donde una vía nueva no se
considera cubierta hasta entrar en la tabla.

Lo que **no** cambia: el comportamiento aprobado de la atención sin cita
(§9.14), el de la reactivación (§9.15) y el flujo de staff (§4.4, §4.9) — alta
de mascota con cliente nuevo, reutilización cuando el cliente es el mismo, y
corrección de un teléfono mal capturado desde Clientes o desde la ficha de la
mascota.

### 12.2 Revisión OCR ronda 1: los lectores de identidad

Estado de la revisión multi-agente
(`.ocr/sessions/2026-08-08-task-2782bc85-WA-02-Decidir-reoferta-segura/rounds/round-1/final.md`,
veredicto REQUEST CHANGES). Ese artefacto **no se modifica**: se responde aquí.

| Hallazgo | Severidad | Estado | Resuelto en | Prueba que lo ancla |
|---|---|---|---|---|
| **Los lectores de identidad del agente quedaban fuera de la normalización** — `agent/services.py` compara el valor normalizado del `wa_id` contra `Owner.phone` **en crudo**, en la creación de `ContactIdentity` y en `_rematch_owner`. Dos expedientes que solo coinciden **tras normalizar** dan una única coincidencia cruda → vínculo automático donde INV-C exige ambigüedad | **Bloqueador** | **Resuelto por diseño** | §4.7.4 (familia **E**, vías de *lectura*), §4.11 (contrato del resolvedor en modo lectura, desenlaces y prohibición de tocar `auto_rematch_blocked`), §4.7.2 (unión normalizado ↔ normalizado) | P0-26, P2-12 (ampliada al `filter` por `phone` crudo) |
| **El preview del importador seguía eligiendo el primer duplicado** — tres pasadas por teléfono, y solo la del commit iba a cambiar: la vista previa podía prometer una reutilización que la escritura rechazaría | Should fix | **Resuelto por diseño** | §4.8 (paridad preview ↔ escritura: mismo resolvedor, mismos cuatro desenlaces, sin `.first()` en ninguna pasada) | P0-27, P0-24 (ampliada) |
| **El valor normalizado del `Owner` genérico no estaba definido** — se excluía del conteo, pero no se decía qué guarda ni cómo se comporta en migración y validación | Should fix | **Resuelto por diseño** | §4.12 (`phone_normalized = NULL` siempre; bypass de validación **solo** para `is_generic=True`; excluido de búsqueda, locks, deduplicación e identidad) | P0-28 |

Respuestas a las dos preguntas de clarificación de la revisión:

- **¿«`patients`, importador y agente convergen» incluye la creación de contacto
  y el rematch de `agent/services.py`?** **Sí.** Eran implícitos y por eso se
  colaron; ahora son las filas E1 y E2 del inventario, con su contrato en §4.11.
- **¿`phone_normalized = NULL` es la representación prevista para el `Owner`
  genérico, incluido el backfill?** **Sí**, y es invariante, no preferencia:
  `NULL` lo deja fuera de índices parciales y de comparaciones por igualdad sin
  que nadie tenga que acordarse de excluirlo (§4.12).

Lo que esta revisión corrige es un **punto ciego de categoría**: el inventario
del hallazgo Z cubría *escrituras*. Un lector que compara mal también decide —
y decidir entre duplicados históricos es lo que INV-C prohíbe, venga de un
`INSERT` o de un `SELECT`.
