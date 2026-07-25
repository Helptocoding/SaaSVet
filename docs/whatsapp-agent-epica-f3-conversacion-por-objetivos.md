# É-F3 — Remediación + conversación por objetivos

**Fecha del plan**: 2026-07-24
**Estado**: PENDIENTE DE APROBACIÓN (protocolo de épicas: plan → aprobación → código)
**Contratos**: [`whatsapp-agent-functional-spec.md`](whatsapp-agent-functional-spec.md) (F1 congelada — esta épica la **enmienda**, ver §7) · [`whatsapp-agent-implementation-plan.md`](whatsapp-agent-implementation-plan.md) (diseño v1.1) · [`whatsapp-agent-auditoria-conversacional-2026-07-24.md`](whatsapp-agent-auditoria-conversacional-2026-07-24.md) (hallazgos)
**Estimación**: W0 ~2 d · W1 ~3 d · W2 ~5 d · W3 ~2 d → **~12 días** de una persona, en 4 tramos con gate propio.

---

## 0. Enmiendas a la auditoría (decisiones del Product Owner, 2026-07-24)

Tres correcciones del PO que **modifican las recomendaciones** de la auditoría. Quedan registradas aquí porque cambian el trabajo, no sólo el tono.

### E1 — La secuencia infra-primero fue correcta. No es un error de asignación de esfuerzo.

La auditoría enmarcó el desbalance infra/conversación como una mala distribución del presupuesto de rigor. **El PO lo corrige y tiene razón**: el orden inverso habría producido un agente agradable capaz de agendar citas incorrectas, y en un SaaS clínico multi-tenant el fallo de control es irreversible mientras que el fallo de tono es iterable. *Un agente aburrido se mejora; un agente peligroso se apaga y se pierde el cliente.*

Reformulación aceptada: **no hubo mala asignación, hubo una fase**. La fase de control está cerrada y validada por CI. Esta épica abre la fase de conversación, que sólo era abordable con las barreras ya puestas.

Consecuencia práctica: ninguna barrera de control se relaja en esta épica. Todo lo que se construye aquí vive **antes** de la confirmación tier-2 y **después** del Policy Engine, sin tocar ninguno de los dos.

### E2 — Las reglas conservadoras no se quitan. Se reescriben y, cuando se puede, se endurecen.

La auditoría §7.2 proponía eliminar bloques del prompt. El PO discrepa: en medicina veterinaria se prefiere pecar de conservador; cambia la **forma**, no el conjunto de reglas.

**Aceptado, con una precisión que refuerza la postura del PO**: una regla escrita en el prompt es *advisoria* — el modelo puede desobedecerla y nadie se entera. Una regla escrita en código es *vinculante*. Por lo tanto:

> **Principio rector de W1: la conservación se muda del prompt al runtime. El prompt se acorta y el sistema se vuelve MÁS estricto, no menos.**

Reclasificación de las reglas duras vigentes (G1–G8 de la spec §2.2):

| Regla | Hoy | Tras W1 | Efecto neto |
|---|---|---|---|
| G1 no inventar datos (precios/fechas/horarios) | Prompt | Prompt (reformulado) **+ guard de salida**: precio o fecha que no aparezca en los resultados de tools del turno ⇒ se bloquea la respuesta y se re-genera | **Más estricto** |
| G2 cero consejo médico | Prompt | Prompt **+ plantilla determinista `T0_OUT_MEDICAL` (ya escrita, hoy muerta) + guard de salida** con los patrones de `tests/harness.py::FORBIDDEN_MEDICAL` promovidos a runtime | **Mucho más estricto** |
| G3 no prometer en nombre de la clínica | Prompt | Prompt (reformulado) + guard de salida sobre patrones de promesa | **Más estricto** |
| G4 no revelar bajo nivel de verificación | Policy + tools | Sin cambio (ya es código) | Igual |
| G5 fechas absolutas | Prompt | Parafraseo por plantilla (ya es código) + resolución determinista de fechas (W2) | **Más estricto** |
| G6 datos ≠ instrucciones | Prompt + delimitadores | Sin cambio | Igual |
| G7 sin cifras de stock/costos | Proyecciones de tools | Sin cambio (ya es código) + guard de salida | **Más estricto** |
| G8 no pedir el teléfono | Prompt | Prompt + el slot es de origen `sistema` (W2) | **Más estricto** |

Los guards de salida son un filtro determinista sobre el texto generado, **antes** de encolar el saliente. Las listas ya existen y están probadas — hoy sólo corren en tests (`harness.py:28-38`). Promoverlas a producción es barato y convierte cuatro reglas advisorias en cuatro reglas vinculantes.

Lo que **sí** sale del prompt no es ninguna regla de seguridad:
- `REGLA ABSOLUTA DE TURNO` — es un parche a un bug técnico (el historial no le devuelve al modelo sus propias llamadas a herramientas). Se arregla la causa (W1-3) y el parche sobra. Ninguna regla de negocio se pierde.
- `CLIENTE NUEVO vs REGISTRADO` — es lógica determinista duplicada en prosa. Pasa a ser estado del objetivo (W2). La regla no desaparece: se vuelve inviolable.
- Redundancias literales (la misma prohibición repetida en tres bloques). Se dice una vez, en el lugar correcto.

**Regla de oro de esta épica**: *ningún cambio de prompt puede reducir el conjunto de comportamientos prohibidos. Si una regla sale del prompt, entra al código con un test que la ancle.*

### E3 — Falta la conversación por objetivos. Es el siguiente gran salto del producto.

Aceptado íntegramente, y con evidencia que refuerza el punto: **no es que falte diseñarla — está diseñada y no se implementó**. Ver §1.

---

## 1. Hallazgo nuevo: la capa de objetivos se diseñó y se perdió en la implementación

`whatsapp-agent-architecture.md` §7.3 (Sub-estado de flujo / slot filling) especifica:

```
flow = {
  "name": "schedule_appointment",
  "slots": { "pet_ref": "mascota_1", "date": "2026-07-15", "time": null, "reason": "vacuna" },
  "refs":  { ... },
  "pending_action": ...
}
```

El plan v1.1 conservó `flow` como columna de `Conversation` (§C2) sin objetar los slots. `models.py:139-140` documenta el campo como *"Estado del flujo activo (F1): slots, tabla de refs, pending_action"*.

**Verificación en código (2026-07-24)**: las únicas claves que se escriben en `flow` son `refs`, `pending_action`, `identity_challenge`, `family_challenge` y `nudge_sent`. `name` y `slots` **no existen en ninguna parte del código ni de los tests**.

Consecuencias directas, todas observables hoy:

1. **`create_appointment` es todo-o-nada.** Exige `pet_handle` + `date` + `time` + `reason` en una sola llamada (`tools.py:587`); si falta uno devuelve `need_data` y `_soft_error_hint` (`planner.py:343-345`) le dice al modelo *"pregúntale al cliente lo que falte"*. **El sistema sabe exactamente qué falta y descarta esa información** en lugar de persistirla.
2. **Cada turno re-deriva la intención desde cero**, leyendo una ventana de 12 mensajes. No hay noción persistente de "qué estamos haciendo".
3. **No hay memoria de lo ya preguntado** → el agente repite preguntas, que es uno de los tics más reconociblemente robóticos.
4. **La interrupción destruye el progreso.** La spec §2.7 exige que una lectura intercalada (*"¿cuánto cuesta?"*) no descarte el flujo activo. Sin flujo activo persistido, eso no se puede cumplir: lo único que sobrevive es lo que el modelo alcance a re-leer del historial.
5. **La escalada es contable, no semántica.** Se escala al agotar 15 llamadas al LLM, no al detectar que la conversación no avanza.
6. **Las métricas del embudo se aproximan por nombres de tool** (`metrics.py:19-22`) porque no existe el objeto que representa la intención.

El diagnóstico del PO es exacto: el agente hoy es `mensaje → intent → tool → respuesta`. Lo que falta es `objetivo → qué me falta → lo obtengo → continúo → cierro`.

---

## 2. Arquitectura de la capa de objetivos

### 2.1 Principio: el sistema es dueño del checklist; el modelo es dueño de la conversación

Esta es la decisión que hace que la capa de objetivos sea **más conservadora** que lo que hay hoy, no menos:

| Responsabilidad | Hoy | Con objetivos |
|---|---|---|
| Saber qué datos hacen falta | El LLM (implícito) | **Código** (`REQUIRED_SLOTS` por objetivo) |
| Extraer el valor de un mensaje | El LLM | LLM propone → **código valida y normaliza** |
| Resolver "el martes" a una fecha | El LLM (aritmética mental) | **Código** (parser es-MX + `org_today_local`) |
| Decidir que ya se puede agendar | El LLM (llama la tool con lo que crea) | **Código** (todos los slots llenos y válidos) |
| Redactar la pregunta | El LLM | El LLM (con la variable a pedir dictada por código) |
| Ejecutar la mutación | Confirmación tier-2 | Confirmación tier-2 (**sin cambios**) |

El LLM pierde autoridad sobre *qué* se necesita y *cuándo* está completo, y conserva autoridad sólo sobre *cómo se pregunta*. Es exactamente el principio "el LLM propone, el sistema dispone" extendido del dominio de la autorización al dominio del diálogo.

### 2.2 Contrato de un objetivo (revisión del PO, 2026-07-24)

Nuevo módulo `apps/agent/goals.py` (~200 líneas, sin framework). Tres decisiones del PO simplifican el contrato original y una lo enriquece:

**(a) Slot = nombre + validador. Nada más.** Se descartan `extractor` y `slot_spec`: **el LLM propone el valor, el código lo valida**. *"el próximo martes como las cuatro"* → el modelo propone `date=2026-07-28`, `time=16:00` → el validador acepta o rechaza. Escribir decenas de parsers de lenguaje natural es un pozo sin fondo y el modelo ya hace bien esa tarea; lo que no puede hacerse bien es **confiar** en el resultado, y para eso está el validador.

**(b) El objetivo NO sabe preguntar.** Se descarta `question_hint`: el objetivo publica `missing_slots = ['pet', 'time']` y el modelo decide cómo pedirlo. En cuanto el dominio empieza a redactar preguntas, se convierte en un motor de diálogo y arrastra copy, tono y localización a una capa que debería ser puramente estructural.

**(c) Confianza por slot.** El modelo acompaña cada valor con una confianza; **por debajo del umbral el slot no se llena**. Evita la clase de error más molesta —preguntas equivocadas y datos asumidos— sin necesidad de más reglas.

**(d) Estado explícito del objetivo**, no sólo su existencia: `active | paused | completed | cancelled | handoff`. Vale para el diálogo y, sobre todo, para analytics más adelante.

```
Goal = {
    name:            'schedule_appointment'
    required_slots:  ['pet', 'reason', 'date', 'time']
    validators:      {slot: callable(value, conversation) -> (ok, normalized, error)}
    build_action:    slots -> args de la tool tier-2 existente
    max_stall_turns: 3
}
```

Todo lo que el objetivo expone hacia arriba: `name`, `status`, `filled`, `missing_slots`, `low_confidence`. Ni una palabra de copy.

### 2.3 Confianza por slot

El modelo propone, por cada slot, `valor` + `confianza ∈ [0,1]` (parámetros planos `<slot>_confidence` en el esquema de la tool — mucho más fiable en modelos pequeños que objetos anidados). El código decide:

| Confianza | Acción del sistema |
|---|---|
| `≥ AGENT_SLOT_CONFIDENCE_THRESHOLD` (default 0.70) | Se valida y, si pasa, se llena el slot |
| `< umbral` | **No se llena.** El slot entra en `low_confidence` y el contexto le dice al modelo que lo confirme con el cliente |
| ausente | Se asume 1.0 (compatibilidad con la suite actual y con modelos que no la emitan) |

Ejemplo del PO: `pet=Luna (0.99)` se llena; `date=mañana (0.84)` se llena; `reason=vacuna (0.63)` **no** se llena y el agente pregunta el motivo en vez de asumirlo. El valor rechazado no se pierde: viaja al contexto como sugerencia a confirmar, nunca como hecho.

La confianza **no sustituye al validador**: un valor con confianza 0.99 que no pasa el validador se rechaza igual. Son dos filtros en serie (¿el modelo está seguro? y ¿el dato es válido?), no alternativos.

### 2.4 Estado y persistencia

Nuevo modelo `ConversationGoal` (tabla propia, no JSON en `flow`) — decisión derivada de (d): un blob JSON no se agrega, y el PO pide explícitamente que esto sirva para analytics. Sigue el precedente de `HumanHandoff` (fila de ciclo de vida org-scoped, con estado mutable y timestamps).

| Campo | Notas |
|---|---|
| `organization`, `conversation` | tenancy + hilo |
| `name` | del catálogo (§2.5) |
| `status` | `active \| paused \| completed \| cancelled \| handoff` |
| `slots` | JSON `{slot: {value, confidence}}` — **redactado**, sin PII innecesaria |
| `missing` | JSON, snapshot del último cálculo (para el embudo por slot) |
| `asked` | JSON `{slot: n}` — anti-repetición |
| `stall_turns` | turnos consecutivos sin progreso |
| `opened_at`, `last_progress_at`, `closed_at`, `closed_reason` | ciclo de vida |

Invariante: **como máximo un `Goal` en `active` o `paused` por conversación** (constraint parcial en DB, patrón `cashsession_one_open_per_user`). `flow` conserva sólo `refs` y `pending_action`; la whitelist de claves y el tope de tamaño de `flow` (deuda ADR p50 pendiente desde F1, `models.py:140`) se implementan aquí.

Transiciones, todas de código:

| De → A | Disparador |
|---|---|
| — → `active` | El modelo llama una tool de escritura con datos parciales o completos |
| `active` → `paused` | Cambio de tema a una lectura (FAQ) — se retoma al terminar |
| `paused` → `active` | Turno siguiente sin otro objetivo abierto |
| `active` → `completed` | El commit tier-2 se ejecuta correctamente |
| `active` → `cancelled` | El cliente lo descarta, abre otro objetivo, o expira |
| `active`/`paused` → `handoff` | Cualquier escalada a humano con el objetivo abierto |

### 2.5 Catálogo v1 — cuatro objetivos, ni uno más

| Objetivo | Slots requeridos | Cierra con |
|---|---|---|
| `schedule_appointment` | pet, reason, date, time | `create_appointment` (tier-2) |
| `register_and_schedule` | owner_name, pet_name, pet_species, reason, date, time | `register_new_client_and_pet` (tier-2) |
| `cancel_appointment` | appointment | `cancel_appointment` (tier-2) |
| `reschedule_appointment` | appointment, new_date, new_time | `reschedule_appointment` (tier-2) |

**Las intenciones de lectura NO llevan objetivo.** Precios, horarios, vacunas, "mis citas" y disponibilidad se resuelven en un turno y no necesitan estado. Restringir los objetivos a lo multi-turno es lo que impide que esto se convierta en un motor de diálogo genérico (riesgo de sobreingeniería, auditoría §19).

### 2.6 Integración con el pipeline existente

```
policy.evaluate  (SIN CAMBIOS en orden ni reglas)
      │
      ├─ REPLY / ESCALATE / CLOSE / SILENT ......... igual que hoy
      │
      └─ RUN_PLANNER
            │
            ├─ (nuevo) objectives.ingest(conversation, texto_de_la_ráfaga)
            │      extrae y VALIDA slots del mensaje; abre objetivo si aplica;
            │      actualiza `asked` y `last_progress_at`
            │
            ├─ (nuevo) contexto DATOS += {objetivo, slots_llenos, falta: [...]}
            │
            ├─ bucle LLM ↔ tools .................. igual que hoy
            │
            ├─ (nuevo) si el objetivo está completo → el planner llama la tool
            │      tier-2 con los args construidos por CÓDIGO (no por el modelo)
            │
            └─ confirmación tier-2 + commit ....... SIN CAMBIOS (TC-SEC-03 intacto)
```

Puntos que **no** se tocan: el orden de las 13 reglas del Policy Engine, el parafraseo por plantilla, la ejecución del `pending_action` staged, el executor loopback, el RBAC, la auditoría.

### 2.7 Qué gana el producto, en concreto

- **Interrupciones sin pérdida**: FAQ intercalada → se responde → *"Volviendo a la cita de Luna: me falta la hora, ¿te sirve 11:00 o 4:00?"*. La spec §2.7 pasa de aspiración a comportamiento.
- **Cero preguntas repetidas**: `asked[slot] >= 2` → cambiar de estrategia (ofrecer opciones concretas) en lugar de repetir.
- **Escalada semántica**: `max_stall_turns` sin progreso ⇒ escalar. Sustituye al presupuesto contable como disparador principal (el presupuesto queda como red de contención, subido a 40).
- **Menos llamadas al LLM**: los slots que se pueden extraer con código (fecha, especie, nombre de mascota contra la lista del owner) ya no requieren una vuelta del modelo.
- **Métricas reales**: objetivo abierto → completado → abandonado, por etapa y por slot. `metrics.py` deja de inferir el embudo desde nombres de tool.
- **Menos superficie para alucinar fechas**: la resolución de "el martes" pasa a código. Es el bug que ya mordió en piloto (`7a492fe`, `a8a55e2`); esta es su cura estructural.

---

## 3. Workstreams

### W0 — Bloqueantes (~2 d) · *bugfixes puros, sin cambio de arquitectura*

| # | Cambio | Archivos |
|---|---|---|
| W0-1 | Zona horaria de la organización en el generador de slots (usar `org_today_local`/`local_date_time_to_utc`, ya existentes) | `tools.py:427-428,463,500-502` |
| W0-2 | Matchers de seguridad (urgencia, humano, opt-out) sobre la **ráfaga completa**, no sólo el último mensaje | `planner.py:46`, `worker.py:78-95` |
| W0-3 | Aislamiento de fallos del worker: `try/except` por conversación + contador de intentos en el entrante + dead-letter con escalado a humano | `worker.py`, `channels/models.py` (+1 campo), `run_agent_worker.py` |
| W0-4 | Alerta a ops en handoff urgente (reusar `core/services.py::send_support_report`) + prioridad visible y ordenada en `/inbox` | `policy.py`, `views.py`, `frontend/src/pages/inbox/index.jsx` |
| W0-5 | `no_vet` explícito si no hay `default_veterinarian` (dejar de elegir el primer VET por pk) | `tools.py:396-400` |
| W0-6 | Aviso de privacidad just-in-time (código ya escrito, sólo falta invocarlo) + `privacy_notice_sent_at` | `planner.py`, `tier0.py:156` |
| W0-7 | Transacción por conversación (sacar la red externa de la transacción del lote) | `worker.py:63-73,145-162` |

**Gate W0**: los 5 hallazgos críticos de la auditoría cerrados, suite verde, smoke manual de agendado a las 09:00 y a las 18:30 hora local.

### W1 — Experiencia y conservación vinculante (~3 d)

| # | Cambio | Nota |
|---|---|---|
| W1-1 | **Guards de salida deterministas** (E2): promover `FORBIDDEN_MEDICAL`/`FORBIDDEN_JARGON` de tests a runtime + verificación de que precios y fechas emitidos existan en los resultados de tools del turno. Violación ⇒ re-generar una vez ⇒ si persiste, plantilla segura + handoff | **Endurece G1/G2/G3/G7** |
| W1-2 | Reescritura del prompt: mismas reglas, forma conductual + 3-5 ejemplos de intercambio ideal + formato WhatsApp (`*negritas*`) + prohibición de re-saludar. `PROMPT_VERSION` → `reception-f3-v6` | Ninguna prohibición se elimina |
| W1-3 | Hilo de tools devuelto al modelo (mensajes `assistant` con `tool_calls` + `tool` con `tool_call_id`) ⇒ permite retirar `REGLA ABSOLUTA DE TURNO` | Causa raíz del auto-diálogo |
| W1-4 | Debounce real: empujar `available_at` de los pendientes al ingerir (ventana ~8 s) + cap duro 25 s + descarte del saliente si llegó entrante nuevo | Síntoma #1 |
| W1-5 | Presupuesto a 40 + copy de escalado variado por motivo + acuse único al cliente que insiste en `HANDOFF_PENDING` | Síntoma #3 |
| W1-6 | Reto de identidad tolerante (nombre de pila único) + reevaluación del match teléfono→Owner cuando el contacto sigue `unknown` | Deja de expulsar y duplicar clientes |
| W1-7 | Plantilla determinista para media entrante (audio/imagen/sticker) antes de invocar al LLM | Spec GB-1, hoy inexistente |
| W1-8 | Mapeo honesto de errores 400 por `code` (dejar de traducir todo a `slot_taken`) | Deja de mentir y expone fallos reales en el piloto |
| W1-9 | Saludo institucional + aviso de fuera de horario también con el agente encendido | Restaura T0-GREET |
| W1-10 | `is_blocked` ≠ `proactive_opt_out`; mensajes de `human_staff` al contexto | Deja de silenciar clientes para siempre |

**Gate W1**: 20 conversaciones de ensayo revisadas a mano por el PO; cero violaciones de los guards; cero asteriscos visibles; cero preguntas repetidas atribuibles al prompt.

### W2 — Conversación por objetivos (~5 d) · *el salto*

| # | Cambio |
|---|---|
| W2-1 | `goals.py`: contrato (slot + validador, sin extractores ni copy), catálogo de 4 |
| W2-2 | Confianza por slot: parámetros `<slot>_confidence` en las tools de escritura + umbral configurable + `low_confidence` al contexto |
| W2-3 | Modelo `ConversationGoal` con `status` explícito + constraint de un objetivo abierto por conversación + whitelist/tope de `flow` (deuda ADR p50) |
| W2-4 | Inyección al contexto como DATOS: `objetivo`, `tengo`, `faltan`, `confirmar` — sin texto de pregunta (el modelo redacta) |
| W2-5 | Cierre por código: objetivo completo ⇒ el planner arma los args y dispara la tier-2 existente |
| W2-6 | Interrupción/retorno vía `paused` (spec §2.7) + anti-repetición (`asked`) + escalada por estancamiento (`stall_turns`) |
| W2-7 | Métricas por objetivo, estado y slot (sustituyen la inferencia por nombre de tool en `metrics.py`) |

**Gate W2**: los 30 casos F2 de la suite verdes sin modificar sus aserciones de efecto de dominio; +12 casos nuevos de objetivos (interrupción, retorno, estancamiento, slot inválido, cambio de objetivo); TC-SEC-03 y TC-INT20-06 verdes (bloqueantes absolutos, no negociables).

### W3 — Medición (~2 d)

Turnos por resolución · tasa de repregunta · abandono por etapa del objetivo · latencia p50/p95 real · % de entrantes de audio · motivos de handoff · muestreo semanal de 20 transcripts revisados por una persona. Sin esto no hay ciclo de mejora y el piloto sólo sabrá responder "¿agendó?".

---

## 4. Migraciones

| App | Cambio | Naturaleza |
|---|---|---|
| `channels` | `Message.process_attempts` (PositiveSmallInteger, default 0) | Aditiva, sin rewrite |
| `agent` | `Conversation.processing_until` (DateTime null) | Aditiva |
| `agent` | `ContactIdentity.proactive_opt_out` (Boolean, default False) | Aditiva |
| `agent` | Tabla nueva `ConversationGoal` + constraint parcial de un objetivo abierto por conversación (W2) | Aditiva, sin FK entrante desde dominio |

Sin migraciones de datos. Reversibles. Compatibilidad: una conversación sin `ConversationGoal` se trata como "sin objetivo abierto" (las conversaciones en vuelo durante el deploy no se rompen).

---

## 5. Riesgos

| Riesgo | Nivel | Mitigación |
|---|---|---|
| El objetivo se "pega" y el cliente queda atrapado en un flujo que ya no quiere | Medio | Cierre por cambio de objetivo explícito, por estancamiento (`max_stall_turns`), por TTL, y por petición de humano (siempre disponible) |
| Extractores deterministas que capturan un valor equivocado (p.ej. fecha mal parseada) | Medio | Todo slot pasa por validador; el parafraseo tier-2 sigue siendo el último filtro humano — el cliente ve la fecha absoluta antes de que se escriba nada |
| El prompt nuevo relaja un comportamiento prohibido | **Alto** | Regla de oro E2 + guards de salida en runtime + los 8 casos `TC-SEC-*` y las aserciones prohibidas globales del harness corren contra el prompt nuevo antes de desplegar |
| W2 se convierte en un motor de diálogo genérico | Medio | Catálogo cerrado de 4 objetivos, sólo multi-turno, sin DSL. Revisión explícita en el gate |
| El deploy pilla conversaciones en vuelo | Bajo | `flow` retro-compatible; `pending_action` intacto |
| Regresión en el orden del Policy Engine | Bajo | W2 no toca `policy.evaluate`; `test_policy.py::PriorityOrderTests` lo ancla |

---

## 6. Pruebas

- **No se relaja ninguna aserción existente.** Los 63 casos F1 + 30 F2 deben quedar verdes con las mismas aserciones de efecto de dominio.
- **Nuevos, W1**: guards de salida (precio inventado, consejo médico, promesa) bloquean y re-generan; media entrante responde plantilla sin llamar al LLM; ráfaga con urgencia en el primer mensaje escala; debounce agrupa 3 mensajes en 1 turno.
- **Nuevos, W2**: apertura/cierre de objetivo; interrupción y retorno; anti-repetición; estancamiento → handoff; slot inválido no avanza; cambio de objetivo descarta el anterior con aviso; objetivo completo dispara tier-2 con args construidos por código.
- **Nuevos, W0**: slots correctos a las 09:00 y 18:30 hora local de la org; mensaje envenenado no tumba el worker y termina en dead-letter; handoff urgente dispara alerta a ops.
- **Eval nightly** con LLM real corre contra `v5` y `v6` para comparar (hoy `prompt_version` se guarda y nunca se explota).

---

## 7. Enmienda a la spec congelada

Esta épica **enmienda** la spec funcional F1 en tres puntos, que dejan de ser divergencias silenciosas y pasan a ser contrato:

1. §2.4 gana la mecánica de objetivo (slots persistidos, interrupción, retorno, estancamiento).
2. §2.6: el presupuesto de 15 llamadas se sustituye por 40 + escalada por estancamiento como disparador principal.
3. §4 INT-00 / GB-1 / §2.3: saludo institucional, aviso de privacidad y plantilla de media **se implementan tal como estaban especificados** (hoy no lo están).

---

## 8. Lo que esta épica NO construye

Botones interactivos de WhatsApp, transcripción de audio, soft-hold de horarios, rejilla de disponibilidad con duración real, memoria de cliente, resumen rodante, continuidad entre conversaciones, RLS. Todos están en el backlog de la auditoría (§16/§17) con su trigger. **Meterlos aquí convertiría una remediación de 12 días en un proyecto de dos meses y retrasaría el piloto**, que es lo único que puede responder las preguntas que ningún documento puede.

Excepción a evaluar en el gate W1: la rejilla con duración real (auditoría MP-5) si el bucle "se acaba de ocupar" aparece en el ensayo.

---

## 9. Secuencia y aprobación

```
W0 (bugfixes, sin arquitectura) ──▶ gate W0 ──▶ W1 (experiencia + guards) ──▶ gate W1
                                                        │
                                                        ▼
                                        ensayo con números propios (48 h)
                                                        │
                                                        ▼
                                     W2 (objetivos) ──▶ gate W2 ──▶ W3 (medición) ──▶ PILOTO
```

W0 puede empezar de inmediato: son correcciones de defectos, no cambios de arquitectura, y no requieren RFC. **W2 sí requiere aprobación explícita** (introduce una capa nueva en el pipeline conversacional).

- [ ] W0 aprobado — Product Owner
- [ ] W1 aprobado — Product Owner
- [ ] W2 aprobado — Product Owner (capa de objetivos)
- [ ] W3 aprobado — Product Owner

---

*Este plan incorpora las tres enmiendas del PO del 2026-07-24 (§0) y el hallazgo de §1, no presente en la auditoría original.*
