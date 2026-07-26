# Módulos: agent + channels (subsistema del agente conversacional)

> **Estado**: É-F3 completa — el agente lee, **agenda** (crear/confirmar/cancelar/
> reagendar + alta de cliente) y persigue **objetivos**, con guards de salida
> vinculantes y medición de calidad. 380 tests en CI. **Sin desplegar a prod.**
>
> Contratos: [`whatsapp-agent-epics.md`](../whatsapp-agent-epics.md) (registro de
> épicas) · [`whatsapp-agent-functional-spec.md`](../whatsapp-agent-functional-spec.md)
> (spec funcional + enmienda É-F3) · [`whatsapp-agent-epica-f3-conversacion-por-objetivos.md`](../whatsapp-agent-epica-f3-conversacion-por-objetivos.md)
> (plan de remediación) · [`whatsapp-agent-auditoria-conversacional-2026-07-24.md`](../whatsapp-agent-auditoria-conversacional-2026-07-24.md)
> (auditoría que lo originó).
>
> ADRs: **p51** identidad del actor · **p52** idempotencia de citas · **p53**
> configuración de clínica · **p54** objetivos + conservación vinculante.
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
| `ConversationGoal` | agent | **Objetivo en curso** (É-F3 W2). Estado explícito `active/paused/completed/cancelled/handoff`; `slots` `{slot:{value,confidence}}` con el valor YA normalizado por el validador; `missing`, `low_confidence`, `asked`, `stall_turns`. Constraint parcial: **un objetivo abierto por conversación** |
| `AgentSettings` | agent | OneToOne a Organization (patrón OrganizationSettings): `enabled` (kill switch, default False), `agent_user`, `faq_facts` (solo hechos sin campo propio), `default_veterinarian`, `scheduling_mode`, `nudge_enabled` |

## Flujo F0

```
Cliente → WhatsApp → POST /hooks/whatsapp/ (firma HMAC, fail-closed)
  → routing phone_number_id → ChannelAccount → org (R1)
  → dedup wamid → ContactIdentity (match Owner: 0/1/≥2=ambiguous)
  → Conversation abierta (o nueva) → Message(in, pending, available_at=+8s;
    cada entrante nuevo empuja la ventana de todo el hilo, tope 25 s)
Worker (run_agent_worker, SKIP LOCKED por conversación):
  → marca procesados → si NO hay salientes previos: encola 1ª respuesta
    (T0-GREET / T0-DISABLED / +sufijo fuera-de-horario, plantillas LITERALES)
Sender: outbox → Meta Cloud API (backoff 30s·2^n cap 1h, máx 5; ventana 24h
  se valida ANTES de intentar HTTP) → acuses sent/delivered/read forward-only
Staff → /inbox (bandeja): responder = tomar (human_active + claim).
```

## Endpoints

| Superficie | Auth | Notas |
|---|---|---|
| `GET/POST /hooks/whatsapp/` | Firma del proveedor (SIN JWT, fuera de `/api/`) | Handshake + eventos; sin firma válida no se toca la DB; siempre 200 tras firma válida |
| `GET /api/inbox/conversations/` (+`?state=`) | `agentinbox.view` | Default excluye cerradas; cap 100 |
| `GET /api/inbox/conversations/<uuid>/messages/` | `agentinbox.view` | Transcript cronológico, cap 200 |
| `POST …/send/` | `agentinbox.send` | Sanitizado, máx 4000; deja la conversación en `human_active` + claim |
| `POST …/claim/` · `…/close/` · `…/release/` | `agentinbox.claim` | Claim exclusivo → 409 `already_claimed` |
| `GET/PATCH /api/inbox/settings/` | `agentinbox.config` | Kill switch + `faq_facts` (caps 20×500; rechaza claves de la config de clínica). El horario NO se toca aquí: vive en `/config` |

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
Identidad (`agent/identity.py`): implícita (nombrar mascota) + reto UX-03.
Suite de regresión: 63 casos congelados en CI contra `StubLLMClient`
(bloqueante) + fixture trampa cross-tenant + aserciones prohibidas globales
(`agent/tests/harness.py`).

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
| Estancamiento | 3 turnos sin llenar un solo slot ⇒ escalada semántica (`T0_GOAL_STALLED`). Sustituye al presupuesto contable como disparador principal |
| Cierre | `completed` solo donde consta que el dominio aceptó la escritura (commit tier-2); `handoff` al escalar; `cancelled` al abrir otro objetivo |
| Métricas | `compute_goal_metrics`: abiertos, completados, tasa, por estado, por objetivo y **slots donde se atoran** — el embudo deja de inferirse de nombres de herramienta |

**No se tocó** ninguna barrera de control: el objetivo vive DESPUÉS del Policy
Engine y ANTES de la confirmación tier-2. El parafraseo por plantilla, el
commit de args staged y TC-SEC-03 siguen exactamente igual.

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
