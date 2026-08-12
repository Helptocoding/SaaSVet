# Plan: corrección de identidad y continuidad en el agente de WhatsApp

**Fecha**: 2026-08-07 (revisado en `/plan-eng-review` el mismo día)
**Estado**: Item 1 e Item 2 listos para implementar. **Item 3 retirado de
este plan** — ver nota abajo.
**Origen**: 3 fallas encontradas en `apps/agent` durante una sesión de investigación
(07-ago-2026), la tercera confirmada con transcript real de un cliente frustrado.

**Alcance explícito**: Item 1 (reset de identidad) e Item 2 (pending_action
al liberar). Comparten dominio (`apps/agent`) pero son fixes independientes
entre sí — se pueden implementar y revisar por separado.

> **Item 3 — retirado en la revisión eng (2026-08-07).** El diseño original
> proponía arreglar `goals.start_identity`/`satisfy`, pero la revisión (outside
> voice + verificación directa en código) encontró que esas funciones **no
> tienen ningún caller en producción** desde que É-F5 Fase 2 (commit `61dd5cd`,
> 02-ago) retiró la FSM de identidad que las invocaba — arreglarlas no habría
> tocado el bug real del transcript. El mecanismo que sí está vivo hoy
> (`flow['aportado']` + `identify_client`, publicado sin depender de ningún
> compromiso vía `prompts.py::anchored_identity_facts`) no fue lo que Item 3
> proponía cambiar. Se necesita una investigación nueva —¿el modelo no llama
> `identify_client` con los datos que ya tiene, o los llama y el estado
> publicado no le basta?— antes de volver a planear un fix. Ver TODOS.md.
>
> No incluye tampoco la capa general de percepción de
> [É-F5 §2bis](whatsapp-agent-f5-conversacion-plan.md) para turnos
> no-identidad — trabajo futuro del equipo, pendiente de su propia
> aprobación de PO.

---

## Item 1 — El reset de identidad debe persistir

> **Enmienda (2026-08-08, tras revisión OCR multi-agente sobre la
> implementación).** El plan original acotaba el flag a `_rematch_owner`
> (fila 2 de la tabla de auditoría) y marcaba `identity.link_self_registered`
> (fila 7) "fuera del problema" porque asumía que ese camino siempre crea un
> `Owner` **nuevo**. Esa premisa es falsa: `create-with-patient` hace
> `Owner.objects.get_or_create(phone=...)`, así que un contacto reseteado
> que completa el alta de "cliente nuevo" en la misma conversación puede
> reutilizar el `Owner` que un ADMIN acaba de desvincular — con **cero**
> factores de verificación, más débil que el reto implícito de un
> `phone_match` cualquiera. El revisor de seguridad de la ronda OCR lo
> confirmó con trazas de código reales (`tools.py::commit_register_new_client_and_pet`
> → `appointments/views.py::create_with_patient` →
> `identity.link_self_registered`, esta última invocada sin consultar el
> flag). La sección "Qué debe hacer" y la tabla de auditoría de abajo quedan
> actualizadas para reflejar el alcance real: el bloqueo cubre **cualquier**
> auto-enlace posterior por teléfono, no solo el de `_rematch_owner`.

### Qué debe hacer

Al ejecutar "Reiniciar identidad", el contacto no solo pierde `owner`/
`verification_level` — queda **marcado para que ningún flujo automático
vuelva a enlazarlo con un Owner existente por coincidencia de teléfono**,
sea cual sea la ruta. Esto incluye tanto un mensaje entrante normal
(`services.py::_rematch_owner`) como el alta de cliente nuevo
(`tools.py::register_new_client_and_pet` → `create-with-patient` →
`identity.link_self_registered`, que puede terminar reutilizando ese mismo
`Owner` vía `get_or_create`). El siguiente mensaje de ese número, aunque
coincida exactamente con un `Owner.phone` real, debe pasar por el reto de
identidad completo, no re-vincularse en silencio por ninguna vía.

### Quién la usa

ADMIN (permiso `agentinbox.config`) desde `/inbox`. El efecto lo vive el
cliente final en su siguiente conversación por WhatsApp.

### Todos los caminos que asignan una identidad confiable (auditoría completa)

Antes de decidir cuándo limpiar el flag, se mapearon los 7 sitios del código
que pueden dejar a un `ContactIdentity` con `owner` asignado o con
`verification_level` elevado. Es la única forma de saber con certeza cuáles
son los caminos legítimos para revertir la supresión (enmienda 2026-08-08:
son tres — ver "Reglas de negocio" abajo — no uno solo):

| # | Función | Requiere `owner_id` ya puesto? | Alcanzable con `owner_id=None`? | ¿Toca el flag nuevo? |
|---|---|---|---|---|
| 1 | `services.py::resolve_contact_identity` (creación de fila) | No — la crea | Solo una vez, al crear la fila (nunca en un contacto ya reseteado) | No aplica — no puede volver a ejecutarse sobre una fila existente |
| 2 | `services.py::_rematch_owner` | No | **Sí — es la causa del bug original** | **Respeta el flag (skip si está activo)** |
| 3 | `identity.try_verify_by_pet_name` | Sí (`owner_id is None → return False`) | No | Bloqueado indirectamente: nunca corre si #2/#7 no pusieron `owner_id` primero. Limpia el flag vía `_promote` — inocuo porque es inalcanzable con el flag activo |
| 4 | `identity.try_verify_by_pet_answer` | Sí | No | Igual que #3 |
| 5 | `identity.try_verify_by_owner_name` | Sí | No | Igual que #3 |
| 6 | `identity.link_family` (reto triple: titular+mascota+dígitos) | **No — funciona exactamente con `owner_id=None`** | Sí | **Limpia el flag** — representa la re-verificación de tres factores que este item exige |
| 7 | `identity.link_self_registered` (alta de cliente nuevo, vía `tools.commit_register_new_client_and_pet`) | No — `create-with-patient` hace `get_or_create(phone=...)`, así que **puede recibir un `Owner` YA EXISTENTE**, no necesariamente uno nuevo | **Sí — enmienda 2026-08-08: era la causa de un segundo bypass, no detectado en la auditoría original** | El **caller** (`tools.commit_register_new_client_and_pet`) respeta el flag: no invoca esta función si `contact.auto_rematch_blocked` es `True`. La función en sí limpia el flag al final, bajo la precondición de que el caller ya superó ese guard (documentada en su propio docstring) |

Adicional (fuera de alcance, documentado en TODOS.md): `views.py::unlink_family`
deja al contacto en el mismo estado vulnerable (`owner=None`,
`verification=unknown`) que `reset_contact_identity`, con el mismo riesgo
teórico de `_rematch_owner` — pero el caso real es mucho más raro (que el
teléfono propio de un contacto secundario coincida por casualidad con OTRO
Owner). Se decide dejarlo fuera de este plan y anotarlo como deuda conocida.

También se verificó: `LINKED_STAFF` existe como valor del enum
`linked_via` pero **ningún endpoint lo asigna hoy** — no hay un mecanismo de
"vincular manualmente por staff" en el código actual. No es necesario para
este item (la única vía de re-verificación sigue siendo el reto), pero queda
anotado como observación para quien lea el modelo y espere encontrar ese
camino implementado.

### Reglas de negocio

- El reset actual (`owner`/`verification_level`/`verified_at`/`linked_via`/
  `is_ambiguous` → limpio) se conserva sin cambios.
- Nuevo campo `ContactIdentity.auto_rematch_blocked` (booleano, default
  `False`). `reset_contact_identity` lo pone en `True`.
- `_rematch_owner` gana una guarda adicional al inicio: si
  `contact.auto_rematch_blocked` es `True`, retorna sin tocar nada — el
  contacto se queda `unknown` indefinidamente hasta que se re-verifique por
  el reto completo.
- `tools.commit_register_new_client_and_pet` gana la misma guarda antes de
  invocar `identity.link_self_registered`: si `contact.auto_rematch_blocked`
  es `True`, NO vincula el contacto al `Owner` que `create-with-patient`
  resolvió (nuevo o reutilizado) — la mascota y la cita se crean igual
  (el endpoint compartido no cambia), solo se suprime el auto-enlace de LA
  IDENTIDAD del contacto de WhatsApp.
- **El flag se limpia en `identity._promote` (verificación implícita/
  explícita en chat), `identity.link_self_registered`,
  `identity.link_family` y `identity.link_staff_verified`** — las **cuatro**
  únicas funciones que elevan a `confirmed_in_chat`/`staff_verified`
  (ADR p56 inv. 5). `_promote` y `link_self_registered` solo son alcanzables
  con el flag ya en `False` (por el guard de sus respectivos callers) —
  limpiarlo ahí es una operación idempotente, no la primera línea de defensa.
  `link_family` y `link_staff_verified` son las dos alcanzables con
  `owner_id=None`/flag en `True`: la primera representa la re-verificación de
  tres factores que este item exige; la segunda, la verificación **humana**
  de FLUJO-C.
- **`link_staff_verified` (ADR p57 §5.5, F4) es la vía más fuerte de las
  cuatro, y la única forma legítima de deshacer un reset.** Una persona
  identificada, con permiso propio (`agentinbox.identity_verify`), respondió
  por el cliente y dejó registro append-only (`ContactIdentityVerification`)
  de qué comprobó. Por eso limpia `auto_rematch_blocked`: ese flag apaga el
  auto-enlace porque **nadie había verificado nada**, y aquí alguien lo hizo
  con nombre y evidencia externa al teléfono. Cuando se escribió este item,
  `LINKED_STAFF` existía en el enum sin ningún escritor: un `409 owner_exists`
  terminaba en un hand-off que el staff resolvía fuera del sistema.
- El auto-match por teléfono **sigue existiendo para su caso original**
  (cliente nunca antes visto que se da de alta en mostrador o vía el
  asistente) — la supresión aplica solo a contactos que pasaron por un
  reset explícito, no a contactos nuevos (`auto_rematch_blocked` nace en
  `False`).
- El cierre del hilo activo al resetear (comportamiento actual) no cambia.

### Pantallas / API afectadas

- `ContactIdentity` — nuevo campo `auto_rematch_blocked` (booleano) +
  migración aditiva.
- `agent/services.py::_rematch_owner` — guarda nueva al inicio de la
  función.
- `agent/tools.py::commit_register_new_client_and_pet` — guarda nueva antes
  de invocar `identity.link_self_registered`.
- `agent/views.py::reset_contact_identity` — agrega `auto_rematch_blocked`
  al `update_fields` existente.
- `agent/identity.py::_promote`, `link_self_registered`, `link_family` —
  agregan `auto_rematch_blocked` a sus `update_fields` existentes (mismo
  `save()`, no transacción nueva).
- Sin cambios de frontend (mismo botón, mismo endpoint
  `POST .../reset-identity/`); sin cambios en `appointments/create-with-patient`
  (la reutilización de `Owner` por teléfono es comportamiento correcto para
  sus otros callers, p.ej. recepción).

### Criterios de aceptación

- Reset sobre contacto verificado → `owner=None`, `verification=unknown`,
  `auto_rematch_blocked=True`.
- Mismo número escribe de nuevo → **no** se re-vincula automáticamente aunque
  el teléfono coincida (`_rematch_owner` retorna temprano).
- Mismo número, misma conversación, ejecuta `register_new_client_and_pet`
  contra un `Owner` existente (el que se acaba de resetear) → **no** se
  re-vincula (`commit_register_new_client_and_pet` no invoca
  `link_self_registered`); el contacto sigue `owner=None`,
  `verification=unknown`, `auto_rematch_blocked=True`.
- Ese mismo número pidiendo algo personal → pasa por tamiz + reto completo,
  como número nunca visto.
- El mismo contacto completa el reto triple (`link_family`) exitosamente →
  `auto_rematch_blocked` vuelve a `False`.
- Regresión: un contacto **nuevo** (sin reset previo, `auto_rematch_blocked`
  en su default `False`) sigue beneficiándose del auto-match normal, tanto
  por mensaje entrante como por alta de cliente nuevo — no romper ninguno
  de los dos casos que el auto-enlace fue diseñado a resolver.

---

## Item 2 — La propuesta pendiente no se pierde al liberar

### Qué debe hacer

Al liberar una conversación, si había un `pending_action` suspendido por una
escalada: verificar contra el dominio real si ya se concretó durante el
hand-off. Si sí, descartarlo en silencio. Si no, **restaurarlo tal cual** a
`flow['pending_action']` — el mecanismo existente (confirmación en el
siguiente turno, o el nudge de inactividad) se encarga de retomarlo, sin
código de envío nuevo.

### Decisiones tomadas en revisión eng (revierten el borrador original)

Dos simplificaciones importantes respecto a la primera versión de este item,
ambas para no duplicar mecanismos que ya existen y ya tienen tests:

1. **Sin revalidación de disponibilidad en `release_conversation`.**
   `create_appointment` ya rechaza conflictos de horario al confirmar
   (`docs/system-module-operations.md` §3: "Bloquea la creación de una cita
   que se superponga"). Duplicar ese chequeo aquí sería DRY violation. Si el
   horario dejó de estar libre, el cliente lo descubre al confirmar — igual
   que en cualquier otra propuesta de cita hoy — y `map_domain_400` ya
   traduce el rechazo a `slot_taken`, que el modelo ya sabe convertir en una
   oferta alternativa.
2. **Sin envío inmediato al liberar.** `policy.nudge_abandoned_flows` (cron
   existente, UX-08) ya envía *"¿Seguimos con tu cita? Aquí sigo para
   ayudarte 🐾"* cuando hay un `pending_action` sin responder.
   `release_conversation` solo necesita restaurar el dato — el nudge y la
   confirmación normal del siguiente turno (`policy.evaluate` paso 7) lo
   recogen sin ninguna ruta de envío nueva. Construir un re-ofrecimiento
   síncrono dentro del endpoint de liberar habría exigido llamar al planner
   dentro de una acción de staff (latencia) y habría creado una segunda
   ruta de envío del mismo mensaje.
   - **Precisión de la revisión eng** (verificado en `policy.py:398-438`):
     el nudge se dispara por `last_inbound_at` — el **último mensaje del
     cliente**, no por el momento en que se libera. Si el hand-off duró 3
     horas, el nudge puede disparar segundos después de liberar, no "hasta
     60 min después" como decía el borrador original. El texto de este
     item se corrigió para no prometer una ventana de tiempo que el
     mecanismo real no da.
   - **Gap encontrado y cerrado**: `flow['nudge_sent']` es de una sola vez
     por conversación (`policy.py:419`). Si el nudge ya se había enviado
     **antes** de la escalada, no se reenvía al restaurar el
     `pending_action` — el cliente quedaría sin ese recordatorio si no
     vuelve a escribir. `release_conversation` también hace
     `flow.pop('nudge_sent', None)` al restaurar, para que el nudge pueda
     dispararse de nuevo sobre la propuesta restaurada.

### Quién la usa

Staff vía `/inbox` (botón "Liberar"). Efecto downstream en la conversación
del cliente: inmediato si escribe; si no escribe, depende de cuánto llevaba
inactivo antes de liberar (el nudge se cuenta desde su último mensaje, no
desde el momento de liberar — ver precisión arriba).

### Reglas de negocio

- Verificación "¿ya resuelto?" es específica por tipo de tool:
  - `create_appointment` → ¿existe ya un `Appointment` matching pet+fecha+hora,
    creado durante la ventana del hand-off? **Feasible confirmado**: el
    endpoint de citas ya soporta `?date=` (agent.md, usado por
    `find_available_slots`) y `.filter(pet=pet)` (`appointments/views.py:73`)
    — el chequeo hace `GET /appointments/?date=X` filtrado por mascota y
    compara `start_time` contra lo staged en `flow['suspended']['state']`,
    sin necesitar un endpoint nuevo.
  - `cancel_appointment` → ¿la cita objetivo ya no está activa?
  - `reschedule_appointment` → ¿la cita ya tiene el nuevo horario?
  - `register_new_client_and_pet` → ¿el Owner/Pet ya existen?
- Resuelto → se descarta `flow['suspended']` sin restaurar nada, sin mensaje
  adicional del bot.
- No resuelto → `flow['pending_action'] = flow['suspended']['state']`;
  `flow.pop('suspended')`; **también** `flow.pop('nudge_sent', None)` (ver
  gap cerrado arriba — sin esto, un `pending_action` restaurado tras un
  nudge ya enviado antes de la escalada nunca recibiría un segundo aviso).
  Sin revalidación adicional (ver decisión #1 arriba) y sin envío inmediato
  (ver decisión #2 arriba).
- El chequeo ocurre una sola vez, en `release_conversation` — no en cada
  turno.
- La verificación es **contra el dominio real, nunca contra el juicio del
  modelo** — mismo principio que el resto del sistema (`policy` decide,
  el LLM nunca autoriza).
- **Falla segura del chequeo de dominio**: la llamada al dominio ocurre
  dentro del request/response de `release_conversation` (loopback HTTP,
  agrega latencia a un botón de staff). Si falla o hace timeout, se asume
  **"no resuelto"** — se restaura el `pending_action` igual. Peor caso:
  una re-oferta redundante que el modelo puede reconciliar con el cliente;
  nunca una propuesta real perdida en silencio (que es exactamente el bug
  que este item corrige).

### Pantallas / API afectadas

- `agent/views.py::release_conversation`.
- `agent/policy.py` — nueva función de verificación contra dominio (reusa
  el loopback HTTP existente, respeta el boundary: `agent` nunca importa
  `appointments` directo). Try/except envolvente → falla segura hacia "no
  resuelto".
- Sin cambios de frontend visibles más allá del botón "Liberar" ya
  existente.
- Sin cambios en `policy.nudge_abandoned_flows` — se reusa tal cual.

### Criterios de aceptación

- Staff crea la cita manualmente en `/appointments` durante el hand-off,
  luego libera → el bot **no** vuelve a ofrecerla (`flow['pending_action']`
  queda vacío).
- Staff no la creó, libera → `flow['pending_action']` se restaura con el
  mismo contenido que tenía al suspenderse.
- El chequeo de dominio falla/timeout al liberar → se restaura el
  `pending_action` igual (falla segura).
- El horario propuesto ya no está disponible cuando el cliente por fin
  confirma → rechazado por el chequeo de conflicto **ya existente** de
  `create_appointment`, sin código nuevo.
- Un nudge ya se había enviado antes de la escalada → tras restaurar, puede
  volver a dispararse (`nudge_sent` se limpia al restaurar).
- Regresión: releases sin `pending_action` de por medio (el caso común hoy)
  siguen sin cambios.

---

## Item 3 — RETIRADO de este plan (ver nota al inicio del documento)

El diseño original de este item ("Los factores de identidad no se pierden",
extensión acotada de É-F5) se retiró en la revisión eng del 2026-08-07: el
código que proponía modificar (`goals.start_identity`, `goals.satisfy`
llamado desde ahí) no tiene ningún caller en producción desde el 02-ago
(É-F5 Fase 2 retiró la FSM que los invocaba). El texto completo del diseño
original queda preservado en el historial de git de este archivo para
referencia; no se repite aquí para no confundir a quien lea el plan con un
diseño que no se va a implementar. El seguimiento vive en `TODOS.md`
("Investigar por qué el agente re-pregunta datos de identidad ya dados").

---

## Revisión eng (2026-08-07) — cobertura de tests

Cobertura actual verificada en `agent/tests/`:

```
CODE PATHS (Item 1 — reset de identidad)                    TESTS HOY
[+] agent/views.py::reset_contact_identity
  ├── [★★  TESTED] limpia owner/verification            — test_inbox_api.py:309
  ├── [★★  TESTED] solo ADMIN puede resetear             — test_inbox_api.py:337
  ├── [★★  TESTED] scoping por tenant                    — test_inbox_api.py:346
  └── [GAP]  CRÍTICO  auto_rematch_blocked=True al resetear
[+] agent/services.py::_rematch_owner
  └── [GAP]  CRÍTICO  respeta auto_rematch_blocked (el bug real)
[+] agent/identity.py::link_family
  └── [GAP]            limpia auto_rematch_blocked al verificar

CODE PATHS (Item 2 — pending_action al liberar)             TESTS HOY
[+] agent/policy.py::escalate_to_human (lado SUSPEND)
  └── [★★★ TESTED] suspende sin destruir                 — test_policy.py:95
[+] agent/views.py::release_conversation (lado RESTORE — no existe hoy)
  ├── [GAP]  CRÍTICO  restaura si el dominio dice "no resuelto"
  ├── [GAP]  CRÍTICO  descarta si el dominio dice "ya resuelto"
  ├── [GAP]            falla segura si el chequeo de dominio falla
  └── [GAP]            release sin pending_action no cambia (REGRESIÓN)

COVERAGE: 4/10 paths tested (40%)  |  GAPS: 6 (5 críticos, 1 de robustez)
QUALITY: ★★★:1 ★★:3  |  Ningún gap es E2E-only (todos cubribles con tests
de integración de Django sobre la vista + el modelo, mismo patrón que
`test_inbox_api.py` existente).
```

### Tests a añadir (exactamente lo pedido: reset, no-rematch, regresión)

| # | Test | Archivo | Qué prueba | Prioridad |
|---|---|---|---|---|
| T1 | `test_reset_sets_auto_rematch_blocked` | `test_inbox_api.py` (extiende `InboxResetIdentityTests`) | Tras `POST reset-identity/`, `contact.auto_rematch_blocked is True` | P1 |
| T2 | `test_reset_then_same_phone_does_not_rematch` | `test_services.py` (nuevo o existente) | Reset → simular `resolve_contact_identity` con el mismo `wa_id` → `contact.owner` sigue `None`, `verification_level` sigue `unknown` | **P1 — CRÍTICO, es el bug exacto reportado** |
| T3 | `test_new_contact_still_autorematches` | `test_services.py` | Un `ContactIdentity` **recién creado** (nunca reseteado, `auto_rematch_blocked=False` por default) con teléfono que coincide con 1 Owner → sigue vinculándose vía `_rematch_owner` como hoy | **P1 — CRÍTICO, IRON RULE de regresión (toca comportamiento existente)** |
| T4 | `test_link_family_clears_auto_rematch_blocked` | `test_identity.py` | Contacto con `auto_rematch_blocked=True` completa el reto triple → `link_family` → flag vuelve a `False` | P2 |
| T5 | `test_release_restores_pending_action_when_not_resolved` | `test_inbox_api.py` | Escalada con `pending_action` suspendido, sin Appointment creado → `POST release/` → `flow['pending_action']` restaurado, `flow['suspended']` vacío | **P1 — CRÍTICO** |
| T6 | `test_release_discards_pending_action_when_already_resolved` | `test_inbox_api.py` | Mismo escenario pero con un `Appointment` ya creado matching el pending → `POST release/` → `flow['pending_action']` sigue vacío, no se restaura | **P1 — CRÍTICO** |
| T7 | `test_release_domain_check_failure_defaults_to_restore` | `test_inbox_api.py` | El chequeo de dominio lanza excepción/timeout (mock) → se restaura igual (falla segura) | P2 |
| T8 | `test_release_without_pending_action_unchanged` | `test_inbox_api.py` | Release normal, sin `flow['suspended']` — comportamiento idéntico a hoy | **P1 — REGRESIÓN (IRON RULE)** |
| T9 | `test_release_restore_clears_previous_nudge_sent` | `test_inbox_api.py` | `flow['nudge_sent']=True` de antes de la escalada + `pending_action` restaurado al liberar → `flow['nudge_sent']` queda limpio | P2 |

T2, T3, T5, T6 y T8 son de prioridad crítica por la regla de regresión
obligatoria del proceso de revisión: T3 y T8 protegen comportamiento
existente que el fix toca directamente; T2, T5 y T6 son la prueba positiva
de que el bug reportado en esta sesión queda cerrado.

Artefacto de test plan (para `/qa`): `~/.gstack/projects/Helptocoding-SaaSVet/lap-develop-eng-review-test-plan-20260807.md`.

## NOT in scope

- **`unlink_family` con el mismo fix de supresión** (Item 1) — comparte el
  estado vulnerable pero el caso real es más raro; decisión del usuario en
  esta revisión. Va a TODOS.md.
- **Endpoint de vínculo manual por staff** (`LINKED_STAFF`) — existe en el
  enum del modelo pero nunca se implementó; no es necesario para que Item 1
  funcione (el reto sigue siendo la única vía). No se construye en este plan.
- **Item 3 completo** (factores de identidad que se pierden) — retirado en
  esta revisión: el código target no tiene caller en producción. Necesita
  investigación nueva antes de volver a planearse. Va a TODOS.md.
- **Capa general de percepción É-F5 §2bis** — trabajo futuro del equipo con
  su propia aprobación de PO, independiente de la investigación de Item 3.
- **Revalidación de disponibilidad dentro de `release_conversation`** (Item
  2) — decidido en esta revisión que es redundante con el chequeo de
  conflicto que ya existe en `create_appointment`.
- **Re-ofrecimiento síncrono al liberar** (Item 2) — decidido en esta
  revisión que el nudge existente + la confirmación normal del siguiente
  turno ya lo cubren.

## What already exists (reusado, no reconstruido)

- `policy.nudge_abandoned_flows` (cron UX-08) — reusado tal cual para
  re-ofrecer un `pending_action` restaurado; Item 2 no construye una
  segunda ruta de envío.
- El chequeo de conflicto de horario de `create_appointment` (documentado
  en `system-module-operations.md` §3) — reusado como la única fuente de
  verdad de "¿sigue disponible el slot?"; Item 2 no duplica esta validación.
- `map_domain_400` — ya traduce el rechazo de conflicto a `slot_taken`; el
  modelo ya sabe convertirlo en una oferta alternativa.
- El patrón de test de `InboxResetIdentityTests` (`test_inbox_api.py`) —
  los nuevos tests de Item 1 lo extienden en vez de crear un suite paralelo.

## Failure modes

| Codepath nuevo | Fallo realista | ¿Test? | ¿Manejo de error? | ¿Visible o silencioso? |
|---|---|---|---|---|
| `_rematch_owner` con flag activo | Ninguno nuevo — es un early-return, sin I/O | T2 | N/A | N/A |
| Chequeo de dominio en `release_conversation` | Timeout/error de red del loopback HTTP | T7 | Sí — try/except → falla segura a "no resuelto" | Silencioso para el staff (la liberación igual completa), pero **nunca pierde el pending_action** — es el resultado correcto |
| `link_family` con doble `update_fields` | Ninguno nuevo — un campo más en el mismo `save()` ya existente | T4 | N/A (misma transacción que ya corre) | N/A |

Ningún failure mode queda sin test y sin manejo de error a la vez — no hay
gaps críticos de falla silenciosa.

## Worktree parallelization strategy

Item 1 e Item 2 tocan módulos distintos sin dependencia entre sí — Item 1 es
`services.py`/`identity.py`/modelo; Item 2 es `views.py`/`policy.py`. Item 3
se retiró de este plan en esta misma revisión (ver nota al inicio del
documento) — no hay trabajo de implementación que paralelizar para él.

| Step | Módulos tocados | Depende de |
|---|---|---|
| Item 1 (reset + flag) | `agent/models.py`, `agent/services.py`, `agent/identity.py`, `agent/views.py` (solo `reset_contact_identity`) | — |
| Item 2 (release + pending_action) | `agent/views.py` (solo `release_conversation`), `agent/policy.py` | — |

Ambos tocan `agent/views.py`, pero en funciones distintas (`reset_contact_identity`
vs. `release_conversation`) — riesgo de conflicto de merge bajo, no de lógica.

**Lane A**: Item 1 (independiente). **Lane B**: Item 2 (independiente).
Se pueden implementar en paralelo en worktrees separados y mergear ambos sin
coordinación especial — solo cuidado en el diff de `views.py` al mergear
(funciones distintas, no debería haber conflicto real de contenido).

## Implementation Tasks

- [ ] **T1 (P1, human: ~30min / CC: ~10min)** — agent/models — Agregar campo `auto_rematch_blocked` a `ContactIdentity` + migración
  - Surfaced by: Item 1, decisión de arquitectura #1
  - Files: `backend/apps/agent/models.py`, nueva migración
  - Verify: `python manage.py makemigrations --check`
- [ ] **T2 (P1, human: ~1h / CC: ~15min)** — agent/services — `_rematch_owner` respeta `auto_rematch_blocked`
  - Surfaced by: Item 1, causa raíz del bug de reset
  - Files: `backend/apps/agent/services.py`
  - Verify: test T2 (`test_reset_then_same_phone_does_not_rematch`)
- [ ] **T3 (P1, human: ~30min / CC: ~10min)** — agent/views — `reset_contact_identity` setea el flag
  - Surfaced by: Item 1
  - Files: `backend/apps/agent/views.py`
  - Verify: test T1
- [ ] **T4 (P2, human: ~30min / CC: ~10min)** — agent/identity — `link_family` limpia el flag
  - Surfaced by: Item 1, decisión de arquitectura #1
  - Files: `backend/apps/agent/identity.py`
  - Verify: test T4
- [ ] **T5 (P1, human: ~2h / CC: ~30min)** — agent/views+policy — `release_conversation` restaura/descarta `pending_action` contra el dominio real, incluye limpiar `nudge_sent` al restaurar
  - Surfaced by: Item 2 + outside voice (gap de `nudge_sent`)
  - Files: `backend/apps/agent/views.py`, `backend/apps/agent/policy.py`
  - Verify: tests T5, T6, T7, T8, T9
- [ ] **T6 (P3, human: ~15min / CC: ~5min)** — docs — Documentar `unlink_family` como deuda conocida en TODOS.md
  - Surfaced by: Item 1, decisión de arquitectura #2 (fuera de alcance)
  - Files: `TODOS.md`
  - Verify: entrada presente con contexto suficiente — **hecho** en esta misma revisión
- [ ] **T7 (P2, human: ~1-3 días / CC: ~2-4h)** — agent — Investigar la causa real de la repetición de preguntas de identidad (era Item 3)
  - Surfaced by: outside voice — el código que Item 3 proponía arreglar no tiene caller en producción
  - Files: a determinar por la investigación (candidatos: `tools.py::identify_client`, `prompts.py::anchored_identity_facts`)
  - Verify: entrada presente en `TODOS.md` con contexto suficiente — **hecho** en esta misma revisión

_JSONL de agregación para /autoplan: omitido — `jq` no está instalado en este entorno. Instalar `jq` para que /autoplan pueda agregar estas tareas automáticamente en una futura pasada._

## Completion Summary

- Step 0: Scope Challenge — alcance aceptado tal cual (revisión acotada a Item 1 e Item 2, por pedido explícito del usuario)
- Architecture Review: 2 issues encontrados y resueltos (cuándo limpiar el flag; alcance de `unlink_family`)
- Code Quality Review: 2 issues encontrados y resueltos (DRY en revalidación de horario; ruta de envío del re-ofrecimiento)
- Test Review: diagrama producido, 6 gaps identificados (5 críticos, 1 de robustez) — 9 tests especificados (T9 añadido tras el gap de `nudge_sent` encontrado en la revisión del outside voice)
- Performance Review: 1 issue encontrado y resuelto (falla segura del chequeo de dominio inline)
- NOT in scope: escrito
- What already exists: escrito
- TODOS.md updates: 2 items propuestos y creados (`unlink_family`, investigación de Item 3)
- Failure modes: 0 gaps críticos (todos tienen test + manejo de error)
- Outside voice: ejecutado — Codex instalado pero **no autenticado** en este entorno, se usó el subagente de Claude como fallback (según el protocolo del skill). Encontró **1 hallazgo crítico** (Item 3 apunta a código muerto — retirado del plan) y 2 hallazgos menores (precisión del timing del nudge; feasibility del chequeo de dominio, ambos verificados directamente en código tras el reporte)
- Parallelization: 2 lanes, ambas independientes
- Lake Score: 5/5 decisiones tomaron la opción completa/recomendada (T2's opción "sin revalidación" es la más simple, no la de mayor cobertura — elegida explícitamente por el usuario para evitar DRY violation, un trade-off válido, no un atajo)

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | not run |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | not run |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | ISSUES_OPEN | 5 issues found (2 arquitectura, 2 code quality, 1 performance) — todas resueltas con decisión del usuario |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | not run (sin alcance de UI) |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | not run (sin alcance de DX) |

- **CODEX:** Codex CLI presente pero no autenticado en este entorno — se usó el subagente de Claude como fallback, per protocolo del skill.
- **CROSS-MODEL:** el outside voice (Claude subagent) encontró 1 hallazgo crítico que la revisión interna no había detectado — **Item 3 apuntaba a `goals.start_identity`/`satisfy`, funciones sin ningún caller en producción desde É-F5 Fase 2 (`61dd5cd`, 02-ago-2026)**. Verificado directamente en código (`grep` + `git log -S`) antes de aceptarlo. Item 3 se retiró del plan; el seguimiento vive en `TODOS.md`. Dos hallazgos menores del outside voice (timing del nudge, feasibility del chequeo de dominio) también se verificaron y se incorporaron al Item 2.
- **VERDICT:** ENG REVIEW cerrado para Item 1 e Item 2 — listos para implementar. Item 3 NO cubierto por este review (se retiró antes de completarse su análisis); requiere investigación propia (ver TODOS.md) antes de una futura revisión.

NO UNRESOLVED DECISIONS
