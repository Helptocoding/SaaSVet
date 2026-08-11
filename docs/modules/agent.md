# Módulos: agent + channels (subsistema del agente conversacional)

> **Estado**: É-F3 completa. É-F4 (gobernanza conversacional) con Fases 0-3
> implementadas 2026-07-30 — R1/R9 interrupciones · R5/R8/R12
> suspender-no-destruir + `TurnDecision` · R11/R2 autoría de salientes +
> ventana por turnos · **R3/R4/R7/R9 árbitro + compromiso unificado
> ([ADR p55](../decisions/2026-07-30-p55-turn-authority-and-commitments.md))**.
> · R10/R2 guards de conducta. **É-F4 completa**; la Fase 5 se canceló por
> decisión de producto. 520 tests en CI. Ver
> [`whatsapp-agent-f4-gobernanza-plan.md`](../whatsapp-agent-f4-gobernanza-plan.md).
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
> 2026-08-01, **sin implementar**; enmienda R13 de p55 §6).
>
> Rediseño en curso: [auditoría de arquitectura](../whatsapp-agent-auditoria-arquitectura-2026-07-31.md)
> → [plan É-F5](../whatsapp-agent-f5-conversacion-plan.md). **Fase 0 hecha**
> (corpus de regresión + línea base); Fase 1 arranca con p56 ya aceptado.
> Runbook operativo: [`runbooks/agent-whatsapp.md`](../runbooks/agent-whatsapp.md).

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
| `Message` | channels | Tabla ÚNICA in/out. El inbox ES la cola y el outbox un filtro (`status`); dedup de reintentos: unique parcial `(channel_account, external_message_id)` solo inbound (patrón Payment/ADR p27); `available_at` = ventana silenciosa del debounce (cada entrante empuja la de TODO el hilo: 8 s, tope 25 s desde el más viejo); `process_attempts` = intentos de TURNO del entrante (≠ `attempts`, que cuenta envíos) → al agotar `MAX_PROCESS_ATTEMPTS` el mensaje se descarta y la conversación escala a humano |
| `ContactIdentity` | agent | Identidad POR ORG (`unique org+channel+external_id` — el mismo cliente puede escribir a 2 clínicas); `verification_level` (unknown→phone_match→confirmed_in_chat→staff_verified); `phone_normalized` (Q5: últimos 10 dígitos, México-only); NO es un User — jamás recibe tokens |
| `Conversation` | agent | `PublicIdMixin` (la bandeja navega por UUID); FSM 4 estados: `active → handoff_pending → human_active → closed`; **CLOSED es terminal** (mensaje posterior = hilo nuevo); org fijada al crear e inmutable; `flow`/`summary` = scratchpad (filosofía ADR p50, jamás fuente de verdad); `processing_until` = lease del turno en vuelo (serializa entre réplicas sin transacción abierta) |
| `ConversationGoal` | agent | **El COMPROMISO** (É-F3 W2; extendido por ADR p55 §3 — un solo modelo para tarea e identidad, R7). Estados `active/deviated/suspended/blocked/completed/abandoned/handoff` (+`cancelled` deprecado); `slots` `{slot:{value,confidence}}` YA normalizado; `missing`, `low_confidence`, `asked`, `stall_turns`; coordenadas `return_to`/`supplanted_by`/`blocked_reason`; `attempts_failed` (fallos reales ≠ turnos sin avance) y `working_state` (estado local del mecanismo). Dos constraints parciales: **uno al frente** (`active|deviated`) y **uno suspendido** por conversación |
| `AgentSettings` | agent | OneToOne a Organization (patrón OrganizationSettings): `enabled` (kill switch, default False), `agent_user`, `faq_facts` (solo hechos sin campo propio), `default_veterinarian`, `scheduling_mode`, `nudge_enabled` |
| `TurnDecision` | agent | Rastro **append-only** de cada turno (R12, É-F4 Fase 1). **El runtime NUNCA la lee** — es solo para diagnóstico/regresión. `verdict` (string libre todavía — cerrarlo a los 5 veredictos exige que el árbitro sea dueño de las 22 salidas del planner, que excede R3/R4/R7/R9), `because` (enum cerrado ORTOGONAL, ≤12 valores, `TurnDecision.Because`), `active_commitment`/`return_to`/`supplanted_by` (aún sin poblar, mismo motivo), `facts_consumed`/`facts_produced` (JSON, cero PII). `planner_used`/`tools_called`/`duration_ms` son DIAGNÓSTICO — ningún test afirma sobre ellos |

## Flujo F0

```
Cliente → WhatsApp → POST /hooks/whatsapp/ (firma HMAC, fail-closed)
  → routing phone_number_id → ChannelAccount → org (R1)
  → dedup wamid → ContactIdentity (match Owner: 0/1/≥2=ambiguous — ver §Identidad
    por teléfono: la resolución la hace `patients.services`, no una query propia)
  → Conversation abierta (o nueva) → Message(in, pending, available_at=+8s;
    cada entrante nuevo empuja la ventana de todo el hilo, tope 25 s)
Worker (run_agent_worker, SKIP LOCKED por conversación):
  → marca procesados → si NO hay salientes previos: encola 1ª respuesta
    (T0-GREET / T0-DISABLED / +sufijo fuera-de-horario, plantillas LITERALES)
Sender: outbox → Meta Cloud API (backoff 30s·2^n cap 1h, máx 5; ventana 24h
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

## Endpoints

| Superficie | Auth | Notas |
|---|---|---|
| `GET/POST /hooks/whatsapp/` | Firma del proveedor (SIN JWT, fuera de `/api/`) | Handshake + eventos; sin firma válida no se toca la DB; siempre 200 tras firma válida |
| `GET /api/inbox/conversations/` (+`?state=`) | `agentinbox.view` | Default excluye cerradas; cap 100 |
| `GET /api/inbox/conversations/<uuid>/messages/` | `agentinbox.view` | Transcript cronológico, cap 200 |
| `POST …/send/` | `agentinbox.send` | Sanitizado, máx 4000; deja la conversación en `human_active` + claim |
| `POST …/claim/` · `…/close/` · `…/release/` | `agentinbox.claim` | Claim exclusivo → 409 `already_claimed` |
| `POST …/unlink-family/` | `agentinbox.claim` | Revoca SOLO un vínculo `family_challenge` (PR-17b) — nunca toca `phone_match`/`self_register` legítimos |
| `POST …/reset-identity/` | `agentinbox.config` | Resetea el `ContactIdentity` a `unknown` (owner/verificación/`linked_via`, cualquier procedencia) + cierra el hilo activo. `resolve_contact_identity` solo matchea teléfono→Owner al CREAR la fila (nunca la re-deriva después, ni si `Owner.phone` cambia) — este endpoint es la única forma soportada de reabrir esa resolución con el mismo número real. Solo ADMIN: desligar una identidad ya verificada es sensible (mismo permiso que el kill switch) |
| `GET/PATCH /api/inbox/settings/` | `agentinbox.config` | Kill switch + `faq_facts` (caps 20×500; rechaza claves de la config de clínica). `enabled=true` exige teléfono de clínica válido → 400 (ver §Gate del kill switch). El horario NO se toca aquí: vive en `/config` |

Permisos (Q13): ADMIN `*.*` · ASSISTANT view+claim+send · VET view · AGENT
(el bot) ninguno de bandeja.

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
autoriza**: policy decide antes, run_tool/executor revalidan
tier/verificación/ownership. Proveedor LLM = elección del operador
(`AGENT_LLM_*` por env, cliente OpenAI-compatible en `agent/llm.py`).
Tools de **lectura** (tier 1): list_my_pets, get_vaccine_status,
list_upcoming_appointments, get_clinic_info, get_service_catalog,
check_product_availability, find_available_slots. De **escritura**: 
create_appointment, cancel_appointment, reschedule_appointment y
register_new_client_and_pet (tier 2 — proponen y esperan el "sí"),
confirm_appointment (tier 1, benigna), link_family_member (arranca el reto
triple). request_human siempre disponible. Handles efímeros en `flow.refs`
con resolver+ownership server-side (handle desconocido = denegación dura).
Identidad (`agent/identity.py`): implícita (nombrar mascota) + reto UX-03 +
tamiz UX-05 (abajo).
Suite de regresión: 63 casos congelados en CI contra `StubLLMClient`
(bloqueante) + fixture trampa cross-tenant + aserciones prohibidas globales
(`agent/tests/harness.py`).

### Tamiz de identidad (UX-05) — nuevo vs. ya registrado

**El sistema nunca asume que un número sin registro es un cliente nuevo.** Un
contacto con `owner_id IS NULL` que pide algo **personal** (agendar, ver sus
citas, cancelar/mover — `matchers.wants_personal_action`) recibe primero el
tamiz `T0_TRIAGE`: *"¿primera vez, o ya eres cliente y escribes desde otro
número?"*. Preguntas de precio/horario **no** lo disparan: se atienden en
anónimo (tier 1) y meterles un tamiz sería fricción gratuita.

Las dos ramas las resuelve el propio agente (`matchers.classify_client_triage`):

| Respuesta | Efecto |
|---|---|
| `new` | `RUN_PLANNER` → el modelo debe llamar `register_new_client_and_pet` (alta + cita en una transacción) |
| `returning` | Pide el nombre del titular → `identity.find_link_candidates` lo **busca en `Owner`** → siembra `family_challenge` → reto de 3 factores (titular → mascota → últimos 4 dígitos) → `link_family` → `RUN_PLANNER` verificado, y el agente **sigue atendiendo** |
| `unclear` | Una re-pregunta explícita sin costo; a la segunda cede al planner |

Detalles que evitan que el tamiz se sienta robótico (revisión UX 2026-07-28):

- **Negaciones primero**: `"no soy cliente"` contiene `"soy cliente"` y
  `"no es la primera"` contiene `"primera"`. Las listas negadas se evalúan
  antes que las positivas o ambas se clasifican al revés.
- **`sí`/`no` pelones se quedan en `unclear`** y se re-preguntan. Adivinar es
  peor que preguntar: un falso `new` abre un expediente **duplicado** sobre
  alguien que ya existe.
- **El reintento no dice "no te entendí"**: pide elegir entre *«soy nuevo»* y
  *«ya he venido»* — dos frases que el diccionario reconoce, así que la 2ª
  vuelta casi siempre resuelve.
- **Si el dato ya vino en el mismo mensaje** (`"soy nuevo, quiero cita"`) no se
  pregunta nada — es la repregunta que persigue `tasa_repregunta`.
- **Si la mascota ya se nombró** antes en el hilo (`"cita para Luna"`), ese
  factor del reto se da por aportado y se salta al de los dígitos. No debilita
  nada: el dato lo dio el cliente sin que el sistema enumerara (G4), y de hecho
  antes de saber que se le pediría.
- **Preguntas de política de citas e información** (`"¿necesito cita o puedo
  llegar así?"`, `"¿cuánto tarda una cita?"`, horarios, ubicación) **no** pasan
  por el tamiz: son tier-1 anónimo y meterles una puerta era fricción gratuita.
- **Aviso de privacidad (UX-01)**: las respuestas del tamiz llevan
  `meta['privacy_notice']` y el planner antepone `_privacy_prefix` en la rama
  `REPLY`. Sin eso, un cliente nuevo daba su nombre sin haber recibido el aviso
  just-in-time — el camino viejo sí lo emitía.
- **Primer contacto**: `tier0.render_triage(org, first_contact=True)` abre con
  la bienvenida institucional. Ese mensaje es lo primero que lee alguien que
  nunca ha escrito; arrancar con "este número no está registrado" era hablarle
  de la base de datos (§2.1).

**Costo conocido y aceptado**: un cliente ya registrado que escribe desde un
número nuevo paga **4 turnos** de verificación antes de avanzar (tamiz →
titular → mascota → 4 dígitos; 3 si ya nombró a la mascota). El tercer factor
—últimos 4 dígitos del teléfono registrado— se diseñó para un **familiar**, no
para el titular que cambió de número, así que puede fallar por memoria y acabar
en humano. Revisado con el PO el 2026-07-28: **se deja así**; la alternativa
(un tercer factor más débil) no compensa el riesgo.

**Decir "ya vine antes" NO escala a un humano** (decisión del PO, 2026-07-28):
se busca, se verifica y se atiende. A un humano solo se llega si la
verificación **falla** de verdad (2 fallos reales → `_family_fail`, E-06).

**Vive en el router determinista** (`policy.evaluate` paso 12b), no en el
planner. Antes solo reaccionaba si el **modelo** llamaba una tool personal y
ésta rebotaba con `verification_required` — un modelo que se ponía a recolectar
nombre/mascota/fecha en texto plano no disparaba nada. Fue exactamente el fallo
del piloto (2026-07-28, conv. 10 de `Clinica Bebe coche`): recolectó todo en
texto, jamás llamó una tool, y dio por agendada una cita inexistente — dos
veces, incluida la respuesta a un "¿la cita se creó bien?" del cliente. La
auditoría de 2026-07-24 había quitado esta regla del prompt asumiendo que
`T0_NEW_CLIENT` ya la cubría desde el planner; cubría solo la ruta con rebote
de tool. Pasar `numero_registrado` al contexto tampoco bastó: el modelo lo
tenía y lo ignoró.

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

> **Pendiente declarado**: `TurnDecision.verdict` sigue guardando el `decision`
> de texto libre (~20 valores). Cerrarlo a los 5 veredictos exige que el
> árbitro sea dueño de las 22 salidas de turno, y eso excede lo que R3/R4/R7/R9
> necesitan. Se hará cuando el árbitro absorba el resto del `planner`.

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
| W0-7 | Transacción corta por conversación + lease (`processing_until`) | La red (LLM, loopback) queda FUERA de toda transacción |

### Configuración de clínica: fuente única (ADR p53)

Todo lo que el agente sabe de la clínica sale de `agent/clinic_context.py`, y
solo hay **una** superficie donde se edita: `/config` (Configuración).

| Dato | Fuente única | Dónde lo edita el ADMIN |
|---|---|---|
| Horario (slots, "¿abierto ahora?", aviso de fuera de horario) | `OrganizationSchedule` — 7 filas sembradas al crear la org (`create_default_schedule`); respeta `is_closed` y descanso | Configuración → Horario (`ScheduleSection`) |
| Teléfono (incluida la **plantilla de urgencia**), dirección, mapa, indicaciones, correo, sitio | `Organization` | Configuración → Clínica (`ClinicSection`) |
| FAQ libre (estacionamiento, aviso de privacidad…) | `AgentSettings.faq_facts` | `PATCH /api/inbox/settings/` |

Puntos únicos de resolución: `effective_business_hours()`, `clinic_phone()`,
`clinic_facts()`, `humanize_schedule()`. Cualquier superficie nueva que pregunte
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
| `default_veterinarian` **sin** configurar (default) | Candidatos = todos los VET activos de la org. Un hueco se ofrece si **alguno** lo tiene libre, y la cita se asigna al primero libre a esa hora |
| `default_veterinarian` configurado | Solo se ofertan y asignan los huecos de ese veterinario (la clínica eligió explícitamente) |
| Sin ningún VET activo | `no_vet` → el agente se disculpa y ofrece pasar con una persona. Es el único caso honesto: no hay con quién agendar |

Por qué importa: con "el primer VET por pk" la capacidad ofertada era la de
**un** veterinario aunque hubiera tres, y toda la agenda del bot caía sobre el
mismo. La ocupación del día se resuelve en **una sola** llamada a la API
(`GET /appointments/?date=`) agrupando por veterinario, no una por vet.

Limitación conocida (deuda MP-5 de la auditoría): la rejilla compara
`start_time` exacto en pasos de 30 min, así que no modela duraciones distintas
ni citas fuera de rejilla. El dominio revalida el solape real al crear; si
pierde la carrera, el agente re-oferta.

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
