# Plan de implementación y revisión crítica: Agente WhatsApp

**Fecha**: 2026-07-14
**Estado**: PLAN — sin código, sin migraciones
**Documento base**: [`docs/whatsapp-agent-architecture.md`](whatsapp-agent-architecture.md) (§18 = respuestas Q1–Q15)
**Objetivo**: convertir la arquitectura en un plan de implementación de mínimo riesgo, con clasificación A/B/C/D de cada cambio, grafo de dependencias, ruta crítica y **revisión crítica honesta** del propio diseño (§7).

> Aviso de lectura: la revisión crítica (§7) **modifica el diseño original** — elimina 4 modelos, 3 estados de la FSM y 2 tiers de política. La Categoría B (§2) ya describe el diseño **simplificado (v1.1)**, no el del documento base. El §8 consolida el diseño resultante.

---

## 1. Categoría A — Bloqueadores

Definición aplicada: no se escribe código del agente (A-0), no se lanza piloto con clientes reales (A-1), no se enciende escritura (A-2) sin cumplirlos. Los gates escalonados evitan el error clásico de inflar "bloqueadores" hasta paralizar el proyecto.

### A-0 · Antes de escribir la primera línea del subsistema

**A0-1 — Decisión Q1 + trámites Meta (número y WABA de pruebas)** *(no-código)*
- **Por qué bloquea**: sin número receptor no existe `ChannelAccount` que probar ni webhook end-to-end; todo el F0 queda en mocks. Además la verificación de negocio ante Meta tiene tiempos externos no controlables — es, de hecho, el arranque de la ruta crítica (§6).
- **Impacto**: habilita F0 real. **Complejidad**: trámite, no ingeniería. **Riesgo**: rechazo/demora de verificación → usar número de pruebas del sandbox de Meta mientras tanto.
- **Archivos**: ninguno. **Tiempo**: 1–3 semanas de calendario (externo); iniciar el día 1 en paralelo a A0-2/A0-3.

**A0-2 — Actor agente: rol `AGENT` + exención tipada de gates + minting interno + throttle scope**
- **Por qué bloquea**: prerrequisito técnico inevitable — sin actor no hay Tool Executor (invariante actor-server-side, `docs/system-reference.md` §3.9). Y el gate legal (ADR p46) dejaría al user agente en 403 permanente (R14).
- **Impacto**: todo el pipeline de tools. **Complejidad**: baja-media en volumen, pero **toca `apps/core/permissions.py`** — el archivo por el que pasa cada request del sistema.
- **Riesgo**: medio-alto si se hace mal (una exención mal tipada abriría los gates a roles normales). Mitigación: exención estrictamente `role == 'AGENT'` (espejo del patrón `is_superuser` ya presente en `permissions.py:383` y `:524`) + tests de no-regresión: usuario normal con `password_must_change`/legal pendiente sigue bloqueado.
- **Archivos**: `apps/core/permissions_codes.py` (rol AGENT + asignación de permisos), `apps/core/permissions.py` (2 exenciones tipadas), `apps/users/models.py` (choice `AGENT` en `User.role` — migración trivial sin datos), `config/settings.py` (scope de throttle `agent_tools`), tests en `apps/core/tests/`.
- **Tiempo**: 1.5–2 días con tests.
- **Nota**: el comando de provisioning del user agente por org es Categoría B (vive en la app nueva); aquí solo entra lo que toca core.

**A0-3 — Fix del catálogo RBAC `vaccinerecord.*`** *(bug de producción independiente del agente)*
- **Por qué bloquea**: (a) corrige un riesgo real hoy — verificado 2026-07-13: las views declaran `resource_name="vaccinerecord"` (`apps/medical_records/views.py:561,594`) pero `PERMISSION_CODES` no contiene esos códigos → **VET/ASSISTANT con `UserRole` en DB reciben `RBAC_DENIED` en `GET /api/vaccines/`** (solo ADMIN pasa por `*.*`); (b) es prerrequisito de la tool T3 (el rol AGENT necesita códigos que existan en el catálogo para el seed).
- **Impacto**: restaura acceso de VET/ASSISTANT a vacunas (el frontend ya llama ese endpoint: ficha de mascota post-ADR p50). **Complejidad**: trivial. **Riesgo**: casi nulo — es aditivo; el seed valida `PERMISSION_CODES == set(PERMISSIONS)` así que ambos lados se actualizan juntos.
- **Archivos**: `apps/core/permissions_codes.py` (4 códigos + asignación VET todos / ASSISTANT list-retrieve), re-run `seed_permissions` (ya corre en deploy), 1 test de regresión RBAC.
- **Tiempo**: 0.5 día.

### A-1 · Antes de lanzar el piloto F1 (agente hablando con clientes reales)

**A1-1 — Consulta legal única (Q2 + Q3 + Q9)** *(no-código)*
- **Por qué bloquea**: F0 es interno (buzón para staff); F1 pone un sistema automatizado a tratar datos personales de clientes finales. Aviso de primer contacto, rol responsable/encargado, DPA del proveedor LLM y números de retención necesitan firma legal, no opinión de ingeniería.
- **Impacto**: textos de plantillas de primer contacto + contrato con proveedor LLM + política de retención. **Complejidad/Riesgo**: bajo (consulta puntual con las recomendaciones del §18 como borrador). **Tiempo**: 1 sesión + ajustes; en paralelo al desarrollo de F0/F1.

### A-2 · Antes de encender escritura (F2)

**A2-1 — Idempotencia en creación de citas**
- **Por qué bloquea F2**: sin ella, un retry de red del Tool Executor (o un reintento de webhook que escape al dedup) duplica citas — corrupción operativa de la agenda, el recurso más visible para la clínica. La mitigación heurística (releer agenda) no distingue intención.
- **Impacto**: `POST /api/appointments/` y `POST /api/appointments/create-with-patient/` aceptan `X-Idempotency-Key` opcional; replay devuelve la cita original. Beneficio lateral: protege también al frontend actual (doble click).
- **Complejidad**: baja — calca de `_is_payment_replay` (ADR p27, `billing/services.py`). **Riesgo**: bajo; campo nullable + unique parcial `(organization, idempotency_key)`, patrón ya probado en el dominio más crítico.
- **Archivos**: `apps/appointments/models.py` (campo + constraint, migración), `views.py`/`serializers.py` (lectura del header), tests, mini-ADR.
- **Tiempo**: 1 día.

**Qué NO es bloqueador** (decisiones deliberadas): RLS (D/C6 — el loopback-only-writes contiene el riesgo), lock del solape TOCTOU (D2), fix "PATCH al pasado" (C2 — el Policy Engine lo cubre), notificaciones push (C8), E.164 (D6).

---

## 2. Categoría B — Implementar junto con el agente

Funcionalidad nueva, no deuda. Organizada por fase; refleja el **diseño simplificado v1.1** (§7/§8).

### B-F0 · Buzón operable (sin LLM)

| # | Entregable | Contenido | Est. |
|---|---|---|---|
| B1 | Apps `channels` + `agent` | Estructura, `INSTALLED_APPS`, docs/modules stub | 0.5d |
| B2 | `ChannelAccount` + webhook `/hooks/whatsapp/` | Verificación de firma del proveedor, resolución número→org, **fuera de `/api/`** (no hereda `DEFAULT_PERMISSION_CLASSES`) | 1.5d |
| B3 | `Message` unificada (in/out) + dedup | Una sola tabla (§7-C1): dirección, autor, cuerpo, `external_message_id` con unique parcial inbound (patrón Payment), campos de entrega outbound (status/attempts/next_attempt_at) | 1.5d |
| B4 | Worker + **inbox-como-cola** | Proceso dedicado en compose; `FOR UPDATE SKIP LOCKED` sobre `Message(status=pending)` agrupado por conversación (FIFO por conversación); sin tabla de cola separada (§7-C4) | 2d |
| B5 | `Conversation` + `ContactIdentity` | Normalización últimos-10-dígitos (Q5), match a Owner, campos `flow`/`summary` embebidos (§7-C2), `privacy_notice_sent_at` | 1.5d |
| B6 | Outbox/Sender | Envío con reintentos exponenciales sobre los campos de `Message`; respeto de ventana 24 h | 1.5d |
| B7 | Plantillas tier-0 | Saludo+aviso, horario (`AgentSettings.business_hours`), fuera-de-horario, emergencia | 1d |
| B8 | `AgentSettings` mínimo | `enabled` (default False), `agent_user`, `business_hours`, `faq_facts` — nada más en v1 (§7-C7) | 0.5d |
| B9 | Provisioning | Mgmt command: user AGENT por org + AgentSettings + ChannelAccount | 1d |
| B10 | Bandeja `/inbox` (frontend) | Lista de conversaciones + transcript + responder como humano + claim; polling (patrón `useDashboardSummary`) | 3–4d |
| B11 | Ops | Servicio en compose, deadman Healthchecks.io, logger `agent.events`, runbook | 1d |

**Subtotal F0**: ~2–2.5 semanas de código (los trámites Meta de A0-1 corren en paralelo).

### B-F1 · Agente read-only

| # | Entregable | Contenido | Est. |
|---|---|---|---|
| B12 | Adaptador LLM (proveedor único) | Interfaz mínima: `complete(context, tools) → action`; reintentos; timeout | 1.5d |
| B13 | Policy Engine | Tiers 0/1/2/⛔ (§7-C5), reglas pre-planner (kill switch, demo, urgencias, presupuesto, sí/no sin LLM), post-planner (validación de args + ownership) | 3d |
| B14 | FSM v1.1 | 4 estados (`ACTIVE/HANDOFF_PENDING/HUMAN_ACTIVE/CLOSED`) + `pending_action` derivado (§7-C3); job de expiración | 1.5d |
| B15 | Tool Executor | Loopback HTTP + JWT del user AGENT (minting de A0-2), mapeo de errores DRF a eventos conversacionales, `ToolExecution` append-only | 2d |
| B16 | Tools de lectura | T1 (interna), T2, T3, T5, T6, T7, T8, T15 — con proyecciones acotadas | 3d |
| B17 | `LLMCall` + presupuesto | Registro por llamada (tokens/costo/latencia); tope de turnos por conversación (constante global v1, §7-C7) | 1d |
| B18 | Handoff completo | `HumanHandoff` + integración bandeja + alerta ops opcional (webhook Discord, patrón `send_support_report`) | 2d |
| B19 | Verificación de identidad | `phone_match` + confirmación en chat (`confirmed_in_chat`) | 1d |
| B20 | Prompts + evaluación | System prompt versionado (string, no tabla — §7-C6), set de casos de prueba conversacionales, hardening anti-injection | 3–5d |

**Subtotal F1**: ~3 semanas.

### B-F2 · Escritura de agenda

Depende de A2-1. T9–T14, flujo de confirmación tier-2 (`pending_action` + parafraseo por plantilla), `AgentSettings.scheduling_mode` (`fixed_vet` default), guard "fecha futura" en reagendado (hallazgo Q11). **~1.5–2 semanas.**

### B-F3 · Proactividad

Plantillas HSM (aprobación Meta — trámite externo, iniciar en F2), opt-in persistido, scheduler de recordatorios (job diario sobre la misma infraestructura de worker), `ClientMemoryFact` (T16). **~2 semanas + tiempos de aprobación de Meta.**

---

## 3. Categoría C — Mejoras recomendadas (posponibles)

| # | Mejora | Cuándo | Costo de postergarla |
|---|---|---|---|
| C1 | Fix de dominio "PATCH puede mover cita al pasado" (`serializers.py:98` solo aplica en creación) | Cualquier momento; one-liner + test | Bajo: el Policy Engine ya lo guarda para el agente; queda abierto solo para staff humano vía API directa (bug menor preexistente) |
| C2 | Promover `business_hours`/dirección/teléfono público a `organizations` | Cuando otra superficie los necesite (p.ej. página pública de la clínica) | Duplicación temporal en `AgentSettings` + migración de datos al promover — contenida y barata (misma "estrategia de promoción" que ADR p43 para `extra_data`) |
| C3 | Endpoint de disponibilidad de slots en el dominio `appointments` | Cuando exista un segundo consumidor (widget web de reservas) | La lógica vive en el subsistema; moverla después es extraer una función pura + ADR. Sin costo estructural |
| C4 | `AgentDailyUsage` materializada | Cuando el `GROUP BY` sobre `LLMCall` duela o al cobrar el add-on | Query de agregación al vuelo mientras tanto — trivial a este volumen (§7-C8) |
| C5 | Debounce con timer real en el buffer | Si drain-on-pickup + delay fijo (§7-C9) no basta según datos de F1 | Algunas ráfagas generan 2 turnos LLM en vez de 1 — costo marginal medible antes de optimizar |
| C6 | RLS en DB (ADR p23, ya diferido post-beta) | Según plan existente; el agente **sube su prioridad** | El aislamiento sigue siendo convención con un actor no-humano nuevo; contenido porque el agente escribe solo vía API (serializers ADR p14). Riesgo residual documentado |
| C7 | Broker de colas dedicado | Trigger DD: >50 msg/s sostenido o contención medida en la tabla | Ninguno hoy; registrar métrica de profundidad de cola desde F0 para tener el dato |
| C8 | Notificación push/email a staff por handoff | Si el tiempo-a-primer-humano en urgentes duele | Bandeja con polling + alerta Discord ops cubren v1 |
| C9 | Borrar `apps/appointments/serealizers.py` (typo, huérfano) | Housekeeping; verificar con grep de imports antes | Cero — solo confusión potencial para quien lea el directorio |
| C10 | E.164 en el dominio | Solo si internacionalización | Ninguno mientras México-only |

---

## 4. Categoría D — No tocar (aunque parezca deuda)

| # | "Deuda" aparente | Por qué dejarla exactamente como está |
|---|---|---|
| D1 | `Owner.phone` sin unique `(org, phone)` y `blank=True` a nivel modelo | Endurecerlo rompería el importador (ADR p43 lo relajó deliberadamente para datos históricos) y datos reales ya cargados. La ambigüedad se resuelve donde pertenece: `ContactIdentity` + desambiguación/handoff. Tocarlo = migración de datos con fallos garantizados por cero ganancia |
| D2 | Check de solape TOCTOU sin lock del veterinario (`appointments/services.py`) | Arreglarlo "bien" = `select_for_update` sobre User/vet (altera el orden global de locks, ADR p12 — exige ADR propio) o un exclusion constraint con `tstzrange` (cirugía de schema de alto riesgo). Al volumen actual, la compensación (releer y re-ofertar) es matemáticamente suficiente. Es el trade-off que el dominio ya aceptó para recepcionistas humanas |
| D3 | Fallback estático RBAC (`PERMISSIONS` dict) coexistiendo con DB | Su eliminación tiene gate propio ya definido (Sprint RBAC Fase 4: `fallback_rate=0` en logs). Quitarlo "de paso" durante el proyecto del agente mezcla dos riesgos sin relación. El rol AGENT funciona igual con o sin fallback |
| D4 | Redis efímero sin persistencia, prohibido como broker | Es una **decisión** (ADR p41), no deuda. El agente no lo necesita: cola en Postgres, memoria en Postgres. Reconfigurar Redis "para el agente" reabriría un ADR cerrado sin necesidad |
| D5 | `Invoice.payment_method` legacy, dual `id`/`public_id` baselineado, listados sin paginar (DD-009, DD-013, ADR p24) | Gobernados por DDs con triggers explícitos. El agente ni los toca: sus lecturas usan endpoints existentes tal cual. Cualquier "limpieza oportunista" es scope creep con riesgo de regresión en dominios que funcionan |
| D6 | `Owner.phone` en formato 10 dígitos (no E.164) | Decisión Q5: migrarlo toca serializer + datos + importador + frontend para cero beneficio México-only. La normalización vive en el subsistema |
| D7 | Helpers de timezone (`apps/core/datetime_utils.py`) | Reusar tal cual (`org_today_local`, `local_date_time_to_utc`, `filter_by_local_day`). Cualquier "mejora" arriesga los flujos de agenda existentes que dependen de su semántica exacta |

---

## 5. Dependency Graph

```
        NEGOCIO/EXTERNO                      CORE (Categoría A)                    SUBSISTEMA (Categoría B)
        ───────────────                      ──────────────────                    ────────────────────────

[A0-1 Q1: WABA + número Meta]────────────────────────────────────┐
                                                                 ▼
                                              [B2 ChannelAccount + Webhook + firma]
                                                                 ▼
                                              [B3 Message unificada + dedup wamid]
                                                                 ▼
                                              [B4 Worker · inbox-como-cola · FIFO/conv]
                                                                 ▼
                                 ┌──────────[B5 Conversation + ContactIdentity (norm. Q5)]──────────┐
                                 ▼                        ▼                                          ▼
                        [B6 Outbox/Sender]      [B7 Plantillas tier-0]                    [B10 Bandeja /inbox FE]
                                 └────────────┬───────────┘                                          │
                                              ▼                                                      │
                                   ╔══ F0: buzón operable ══╗◄────────────────────────[B11 ops/deadman]
                                              ▼
[A0-2 rol AGENT + gates + minting]───▶[B15 Tool Executor (loopback+JWT)]
[A0-3 fix vaccinerecord RBAC]────────────────┐│
                                             ▼▼
[B12 adaptador LLM]──▶[B13 Policy Engine]──▶[B16 tools lectura T1-T8,T15]──▶[B20 prompts+eval]
        [B14 FSM]────────────┘   [B17 LLMCall/presupuesto] [B18 handoff] [B19 identidad]
[A1-1 consulta legal]────────────────────────────────────────────┐
                                                                 ▼
                                   ╔══ F1: piloto read-only ══╗
                                              ▼
[A2-1 idempotencia citas]──────▶[B-F2 tools escritura + confirmación tier-2]
                                              ▼
                                   ╔══ F2: agenda 24/7 ══╗
                                              ▼
[HSM aprobadas por Meta (trámite)]──▶[B-F3 recordatorios + opt-in + memoria cliente]
                                              ▼
                                   ╔══ F3: proactividad ══╗
```

Dependencias transversales: **B15 depende de A0-2** (sin actor no hay JWT); **T3 depende de A0-3** (códigos en catálogo); **B10 depende solo de B5** (la bandeja no espera al LLM — paralelizable); **A1-1 no bloquea código**, bloquea el switch-on del piloto.

---

## 6. Critical Path

Cadena más larga (todo lo demás se paraleliza contra ella):

```
A0-1 (trámite Meta) → B2 → B3 → B4 → B5 → B6 → [F0] → B15(+A0-2) → B13/B12 → B16 → B20 → [F1 piloto]
                                                                → A2-1 → B-F2 → [F2]
```

| Tramo | Duración | Notas |
|---|---|---|
| A0-1 trámites Meta | 1–3 semanas **calendario** | ⚠️ **El ítem más largo de todo el plan no es código.** Iniciar día 1. El sandbox de Meta permite desarrollar B2–B6 sin esperar el número definitivo |
| A0-2 + A0-3 (core) | 2–2.5 días | Paralelo a trámites; primer código que se escribe |
| F0 (B1–B11) | ~2–2.5 semanas | B10 (bandeja) paraleliza con B6–B9 |
| F1 (B12–B20) | ~3 semanas | B20 (prompts+eval) es el tramo con más incertidumbre — presupuestar colchón |
| A2-1 | 1 día | Puede hacerse durante F1 (no depende de nada del subsistema) |
| F2 | ~1.5–2 semanas | |
| **Total a F2** | **~8–9 semanas** de una persona | Con piloto real desde la semana ~6 |

Dos observaciones de ruta crítica:
1. **Los trámites externos dominan**: Meta (número F0, verificación WABA, aprobación de plantillas HSM para F3) y la consulta legal. Todos se inician en la semana 1 aunque su consumo sea en semanas 4–10.
2. **B20 (calidad conversacional) es el único tramo sin precedente interno** — todo lo demás calca patrones del propio repo. Ahí va el colchón, no en la infraestructura.

---

## 7. Revisión crítica de la arquitectura propuesta

Crítica adversarial del documento base. Veredictos: **CAMBIAR** (el plan ya lo incorpora), **ELIMINAR**, **POSPONER**, **MANTENER** (la crítica no procede o el trade-off se sostiene).

### C1 — Tres tablas para el mismo mensaje → **CAMBIAR (3 → 1)**
El diseño original tiene `InboundMessage`, `OutboundMessage` **y** `ConversationMessage` — el cuerpo de cada mensaje vive dos veces y el transcript exige un UNION de dos tablas de transporte más una lógica. Es separación de capas ("transporte vs conversación") convertida en esquema: complejidad accidental pura.
**Diseño v1.1**: una tabla `Message` con `direction`, `author_type` (`client|agent|human_staff|system`), cuerpo, `external_message_id` (unique parcial `WHERE direction='in'` para el dedup wamid), y campos de entrega (`status/attempts/next_attempt_at`) que solo aplican a salientes. El outbox es un filtro (`direction='out' AND status='pending'`), no una tabla. Costo del cambio si algún día se separa: split de tabla — el mismo que hoy pagaríamos seguro en joins.

### C2 — `ConversationState` OneToOne → **ELIMINAR (campos en `Conversation`)**
Un OneToOne para `flow` + `summary` añade un join a cada carga de conversación y no protege nada (misma app, mismo ciclo de vida, mismo dueño). Era mimetismo del patrón `OrganizationSettings`, donde el split sí paga (settings raramente cargados). Aquí se cargan **siempre juntos**. `flow` y `summary` pasan a columnas de `Conversation` (con la misma whitelist de keys y tope de tamaño, patrón ADR p50).

### C3 — Estados `NEW`, `AWAITING_CONFIRMATION` y `BLOCKED` → **ELIMINAR (7 → 4 estados)**
- `NEW`: la resolución de identidad ocurre en el mismo turno del primer mensaje; el estado dura milisegundos. Estado sin observador = estado innecesario.
- `AWAITING_CONFIRMATION`: **doble fuente de verdad detectada en mi propio diseño** — el enum dice "esperando" y `pending_action.expires_at` puede decir "ya expiró". La condición se **deriva**: `pending_action IS NOT NULL`. Un solo dato, cero inconsistencia posible.
- `BLOCKED`: redundante con `ContactIdentity.is_blocked` (¡ambos estaban en el documento!). El bloqueo es propiedad del contacto, no de una conversación.
**FSM v1.1**: `ACTIVE → HANDOFF_PENDING → HUMAN_ACTIVE → CLOSED` (4 estados persistidos, 2 condiciones derivadas). Misma expresividad, menos transiciones que testear.

### C4 — Cola separada "particionada por conversación" → **CAMBIAR (el inbox ES la cola)**
El documento hablaba de una cola como componente propio. Una tabla de cola aparte de la tabla de mensajes duplica el estado (mensaje + su job) y abre la puerta a divergencias (job sin mensaje, mensaje sin job). `Message.status` (`pending → processing → processed`) **es** la cola; el worker toma la conversación con el pending más viejo (`FOR UPDATE SKIP LOCKED` sobre la fila de `Conversation`) y drena sus mensajes. El "particionado FIFO" resulta gratis: lockear la conversación serializa sus mensajes y paraleliza entre conversaciones. Menos un componente, menos una clase de bugs.

### C5 — Tiers 3 y 4 de política → **ELIMINAR de v1**
Tier 3 (identidad fuerte + allowlist por clínica) protege tools que la propia Q8 decidió **no construir** (T4/T17). Tier 4 ("aprobación humana previa") quedó "(reservado)" — la definición de YAGNI. Política v1.1: **0 / 1 / 2 / ⛔**. Reintroducir un tier cuando exista la primera tool que lo necesite cuesta una tarde; mantener niveles muertos cuesta confusión en cada revisión de política.

### C6 — `PromptVersion` como tabla → **ELIMINAR (string)**
Los prompts viven en código, versionados por git. `LLMCall.prompt_version` es un string (`"reception-v3"`) — una tabla añadiría CRUD, admin y sincronización para versionar algo que el repositorio ya versiona mejor.

### C7 — `AgentSettings` sobredimensionada → **CAMBIAR (recorte por fase)**
`allowed_write_tools` (por-org), `persona_config` JSON, `after_hours_behavior`, `daily_budget_llm_calls` por org: cuatro knobs de configuración **antes del primer usuario**. Violación directa del principio del proyecto ("evitar abstracciones prematuras", CLAUDE.md). v1.1: `enabled`, `agent_user`, `business_hours`, `faq_facts`; `scheduling_mode` llega con F2; presupuesto LLM = constante global en settings hasta que dos clínicas necesiten valores distintos; persona = nombre del asistente como campo simple, no JSON. Cada knob se añade cuando exista quien lo gire.

### C8 — `AgentDailyUsage` → **POSPONER (derivar de `LLMCall`)**
Materializar un rollup diario en el lanzamiento es optimización prematura: `LLMCall` tiene org, timestamp, tokens y costo — un `GROUP BY date` sobre meses de datos de pocas clínicas es trivial. La tabla nace cuando el add-on se cobre (necesidad de corte mensual estable) o la query duela. Precedente interno de este error evitado: analytics materializa snapshots **porque** tiene contrato de inmutabilidad y volumen — aquí no hay ni lo uno ni lo otro todavía.

### C9 — Message Buffer con debounce por timer → **CAMBIAR (drain-on-pickup + delay fijo)**
Timers reiniciables por mensaje = jobs retrasados, cancelaciones, carreras entre el timer y el mensaje N+1. El 90 % del beneficio se obtiene gratis: al tomar una conversación, el worker **drena todos** sus mensajes pendientes en un solo turno (consecuencia natural de C4), y el encolado usa `available_at = now() + 3s` fijo (una columna, cero timers). La afirmación original de "reduce ~60-70 % el costo" era un número sin datos — se medirá en F1; si las ráfagas reales lo justifican, el debounce adaptativo es C5 (§3).

### C10 — Handles efímeros para el LLM → **MANTENER, con honestidad reclasificada**
Crítica considerada: la barrera load-bearing contra "cancela la cita X ajena" es la **validación server-side de ownership** (que existe de todos modos), no los handles — así que ¿son teatro? Veredicto: mantener, porque su costo marginal es ~cero (el mapa `refs` ya vive en `flow`) y aportan dos beneficios reales: el prompt no acumula UUIDs (tokens + ruido) y un injection no puede exfiltrar identificadores estables en el texto de respuesta. Pero el documento base los vendía como control de seguridad primario — **degradados a defensa en profundidad**; el control primario es y será el re-chequeo de ownership en el Tool Executor.

### C11 — ¿Dos apps Django o una? → **MANTENER 2, por asimetría de costos**
Crítica considerada: `channels` + `agent` separadas es ceremonia (dos streams de migraciones) para un equipo de una persona; un módulo `transport/` dentro de una sola app bastaría. Veredicto: mantener el split porque la asimetría favorece equivocarse hacia la separación — mover modelos entre apps Django **después** (con datos en producción) es de lo más doloroso que existe (db_table remapping, migraciones falsas), mientras que una separación que resultara innecesaria cuesta exactamente nada. Y la costura transporte/cerebro es la más predecible del diseño (multi-canal es requisito explícito).

### C12 — Loopback HTTP → **MANTENER (la crítica no encontró alternativa superior)**
Re-examinado buscando sobreingeniería: ¿es "HTTP a ti mismo" un antipatrón aquí? No — la alternativa (services in-process) pierde los tenant validators (ADR p14, viven en serializers), y "reimplementar la validación" es exactamente el tipo de segunda-forma-de-hacer-algo que CLAUDE.md prohíbe. El costo real (latencia local, minting de JWT) es marginal frente al costo del LLM. Se mantiene con una guardia: si aparece un flujo que necesite atomicidad multi-endpoint, la respuesta es un endpoint compuesto en el dominio (precedente: `create-with-patient`), nunca bypass.

### C13 — Cola en Postgres → **MANTENER**
Re-examinado: ¿construir infraestructura de cola es NIH (not-invented-here)? Con C4 aplicado ya no se "construye una cola": se añade una columna `status` y un loop con `SKIP LOCKED` — ~100 líneas, no un framework. Un broker real introduciría la primera pieza de infra fuera del backup/DR existente (ADR p40 solo cubre Postgres). El trigger de migración queda documentado (C7).

### C14 — Síntesis: qué sobrevive del documento base
Las decisiones estructurales sobreviven la crítica: **write-path único vía API**, **actor RBAC AGENT**, **estado conversacional persistido fuera del LLM**, **policy determinista delante del modelo**, **Postgres para todo**, **canal-agnóstico**, **fases con gates**. Lo que cae es la **carne alrededor del hueso**: modelos de más (12 → 8), estados de más (7 → 4), tiers de más (6 → 4), un componente de más (cola separada), knobs de más (AgentSettings). Patrón del error: diseñar para el documento (completitud) en vez de para la primera versión (mínimo que funciona). El documento base queda como visión; **este plan es el contrato de implementación**.

---

## 8. Diseño v1.1 consolidado (delta sobre el documento base)

| Aspecto | Documento base | v1.1 (este plan) |
|---|---|---|
| Modelos | ~12 (`InboundMessage`, `OutboundMessage`, `ConversationMessage`, `ConversationState`, `AgentDailyUsage`, `ClientMemoryFact`, `PromptVersion` implícita…) | **8**: `ChannelAccount`, `Message`, `ContactIdentity`, `Conversation` (con `flow`+`summary`+contadores), `HumanHandoff`, `ToolExecution`, `LLMCall`, `AgentSettings`. `ClientMemoryFact` se diseña en F3 |
| Estados FSM | 7 (`NEW`, `ACTIVE`, `AWAITING_CONFIRMATION`, `HANDOFF_PENDING`, `HUMAN_ACTIVE`, `CLOSED`, `BLOCKED`) | **4** (`ACTIVE`, `HANDOFF_PENDING`, `HUMAN_ACTIVE`, `CLOSED`) + 2 condiciones derivadas (`pending_action`, `ContactIdentity.is_blocked`) |
| Tiers de política | 0–4 + ⛔ | **0, 1, 2, ⛔** |
| Cola | Componente propio "particionado por conversación" | `Message.status` + lock de `Conversation` (el inbox es la cola) |
| Buffer | Debounce con timer reiniciable | Drain-on-pickup + `available_at = now()+3s` |
| Config por org | 9+ campos | 4 campos (F0) + `scheduling_mode` (F2) |
| Handles del LLM | Control de seguridad primario | Defensa en profundidad; el control primario es la validación de ownership en el executor |
| Sin cambios | Loopback HTTP, rol AGENT, 2 apps, Postgres, fases, tools (inventario §9 del doc base), observabilidad (menos el rollup), memoria por capas |

---

## 9. Riesgos residuales del plan

1. **B20 (calidad conversacional) no tiene precedente interno** — único tramo donde la estimación puede fallar ×2. Mitigación: el gate de F1 es con clínica piloto y kill switch por org; fallar ahí no toca ningún dominio.
2. **Dependencia de trámites Meta** en F0 y F3 — fuera de control; mitigada arrancándolos la semana 1 y desarrollando contra sandbox.
3. **A0-2 toca `core/permissions.py`** — el cambio de mayor blast-radius del plan; contenido con exención tipada + tests de no-regresión de gates (es el único punto donde el proyecto del agente puede romper el sistema existente).
4. **El diseño v1.1 borra flexibilidad a propósito** (tiers, knobs, tablas) — si una necesidad real aparece antes de lo previsto, el costo es re-añadir una pieza ya diseñada en el documento base (que se conserva como referencia), no rediseñar.

---

*Este plan sustituye operativamente a los §6–§14 del documento base donde difieran (§8 lista los deltas). El documento base se conserva como registro de alternativas evaluadas y visión de largo plazo.*
