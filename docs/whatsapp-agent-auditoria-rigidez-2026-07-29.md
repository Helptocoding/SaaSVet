# Auditoría de rigidez conversacional — agente WhatsApp

**Fecha**: 2026-07-29
**Alcance**: `apps/agent` completo (policy, planner, goals, tools, prompts, guards, matchers, worker, views) + evidencia de producción (org 3).
**Commit auditado**: `103196e`
**Veredicto**: sí, el agente cruzó el punto. No por exceso de reglas — por **fragmentación de
estado** y, más al fondo, por **ausencia de una autoridad única del turno** (§9).

**Revisión del PO, 2026-07-29** — tres piezas que faltaban y que reencuadran la auditoría:
gobernanza explícita (§9), *desviar* como concepto de primera clase (§10) y un cuerpo de
reglas conversacionales evaluables (§11). El modelo mental de **compromisos** sustituye al
de slots. Esas tres secciones son suyas; §1-§8 y §12-§16 son el hallazgo original.

> **Plan de implementación**: [`whatsapp-agent-f4-gobernanza-plan.md`](whatsapp-agent-f4-gobernanza-plan.md) — §14 de aquí es el bosquejo de fases; el plan es lo ejecutable (archivos, tests, gates, migraciones).
> Auditoría previa: [`whatsapp-agent-auditoria-conversacional-2026-07-24.md`](whatsapp-agent-auditoria-conversacional-2026-07-24.md).
> Contrato funcional: [`whatsapp-agent-functional-spec.md`](whatsapp-agent-functional-spec.md).
> Módulo: [`modules/agent.md`](modules/agent.md).

---

## 1. Diagnóstico general

El agente **no** es demasiado rígido porque tenga demasiadas reglas. Es rígido porque
tiene **dos memorias que no se hablan**, y cada capa toma decisiones con la mitad de
los hechos.

```
        ┌──────────────────────────────┐
        │  ROUTER DETERMINISTA          │  dueño de: identidad, tamiz, retos,
        │  policy.evaluate()            │  urgencia, opt-out, confirmación
        │  estado → Conversation.flow   │
        └──────────────┬───────────────┘
                       │  ✗ NO publica flow al modelo
                       │  ✗ NO clasifica el mensaje entrante
        ┌──────────────▼───────────────┐
        │  PLANNER LLM                  │  dueño de: la conversación
        │  prompts.assemble_messages()  │  lee: 12 mensajes + 8 campos DATOS
        │  estado → ConversationGoal    │  (solo para 4 objetivos de escritura)
        └──────────────────────────────┘
                       │  ✗ NO devuelve al router lo que aprendió
                       ▼
```

Consecuencia estructural: **el sistema sabe cosas que su parte conversacional
desconoce, y dice cosas que su parte determinista nunca registra.** Casi todos los
síntomas observados —incluido el que el PO leyó como "pierde el contexto"— caen de
ahí.

Los tres hechos duros de la conversación 13 (`85a2a691`) lo demuestran: el cliente
dijo su mascota, dijo que ya era cliente y dijo el nombre del titular. El router
capturó los tres, los usó, y **jamás se los pasó al modelo**. Cuando salieron de la
ventana de 12 mensajes, dejaron de existir para la conversación.

### El caso más grave

Reconstrucción con datos de producción:

| Cliente dijo | Realidad en la base |
|---|---|
| "cita para *Oliver*" | `Pet` 59318 `Oliver` ✓ |
| "ya he ido varias veces" | ✓ (clasificado `returning` correctamente) |
| "*Ana*" | `Owner` 36518 `Ana Cruz` ✓ |
| "*4586*" | `Ana Cruz.phone` termina en **4586** ✓ |

**Los cuatro factores correctos.** El sistema lo identificó bien —`_seed_family_challenge`
saltó directo a `stage='digits'` porque emparejó Oliver con Ana. Y aun así el cliente
terminó escalado a un humano con `reason=identity_ambiguous`, `detail=family:failed_digits`.

Su único error fue preguntar **"¿para qué necesitas eso?"** antes de dar los dígitos.

```
02:09:36  AGENTE   ¿los últimos 4 dígitos del teléfono del titular?
02:09:51  CLIENTE  para que necesitas eso            ← pregunta legítima
02:10:00  AGENTE   Mmm, ese dato no me coincide.     ← fails=1
02:10:18  CLIENTE  te estoy preguntando, para que necesitas ese dato
02:10:27  AGENTE   No pude validar esos datos.       ← fails=2 → HANDOFF
02:11:10  CLIENTE  4586                              ← correcto, pero el reto ya no existe
02:11:20  AGENTE   ¿es la primera vez que nos visitan…?   ← vuelve al inicio
```

Una recepcionista habría contestado *"es para confirmar que eres tú y proteger los
datos de Ana"* y habría seguido. El sistema contó la pregunta como respuesta
equivocada, dos veces, y cerró la puerta.

---

## 2. Síntomas encontrados

| # | Síntoma | Severidad | Evidencia |
|---|---|---|---|
| S1 | Una pregunta durante un reto se cuenta como respuesta equivocada | **crítica** | conv 13 02:09:51 → 02:10:27 |
| S2 | El sistema borra una verificación en curso al escalar; la respuesta correcta posterior cae al vacío | **crítica** | conv 13 02:11:10 |
| S3 | El agente niega hechos que el cliente sí dijo ("no me lo dijiste aún") | **crítica** | conv 13 02:13:39 y 02:14:03 |
| S4 | Pide 4 veces un dato que él mismo ya enunció | alta | conv 12 `asked={'date':4,'time':4}` |
| S5 | Meta-preguntas ("¿se te borró el contexto?", "¿qué te dije?") no tienen ninguna política | alta | conv 13 completa |
| S6 | Un hecho decidido (`identity_triage_done='returning'`) se sobrescribe con `'unclear'` | alta | conv 13 flow final |
| S7 | El agente pide disculpas por mensajes que escribió el router, no él | media | conv 13 02:12:54 → 02:13:04 |
| S8 | Aviso de fuera-de-horario disparado en el peor momento posible | media | conv 13 02:12:20 |
| S9 | Objetivo cerrado al escalar y nunca reabierto; handoff sin resolver mientras el agente vuelve a hablar | media | conv 13 handoff 14 `resolved=None`, `state=active` |
| S10 | El cliente es coaccionado a satisfacer una restricción de schema ("el sistema me pide una fecha") | media | conv 12 21:22:24, 21:24:38 |
| S11 | Preguntar **incrementa el contador de estancamiento** hacia la escalada | alta | `_settle_goal`, planner.py:525 |
| S12 | `ya_preguntado_2_veces` se publica al modelo y no cambia nada del comportamiento | media | goals.py:360 |
| S13 | Confianza por slot está expuesta en el schema pero el modelo siempre manda 1.0 | baja | conv 12 todos los slots `confidence: 1.0`, `lowconf=[]` |

---

## 3. Causas raíz

### CR-1 · Los estados de reto son **estados absorbentes sin arbitraje**

`policy.evaluate` pasos 8, 8b, 8c (`policy.py:177-192`):

```python
challenge = flow.get('identity_challenge')
if challenge:
    return _advance_challenge(conversation, contact, text, challenge)
family = flow.get('family_challenge')
if family:
    return _advance_family_challenge(conversation, contact, text, family)
triage = flow.get('identity_triage')
if triage:
    return _advance_identity_triage(conversation, contact, burst_text, triage)
```

No hay **ninguna** clasificación del mensaje. La existencia de la clave en `flow`
determina la interpretación: todo lo que llegue *es* una respuesta al reto. El LLM
nunca se invoca — así que ni siquiera existe la posibilidad de que alguien note que
el cliente preguntó algo.

`_family_fail` (`policy.py:503`) trata indistintamente "dígitos incorrectos",
"homónimos ambiguos" y "el cliente hizo una pregunta". Los tres suman `fails += 1`.

**Esto es peor que un agente LLM ingenuo**, que al menos habría contestado.

### CR-2 · `Conversation.flow` no se publica al modelo

`prompts.assemble_messages` (`prompts.py:157-174`) construye:

```python
context = {clinica, fecha_hoy, dia_semana, hoy_legible, hora_actual,
           numero_registrado, verificado, cliente, [en_curso]}
```

Bloque real emitido en conv 13:

```json
{"clinica":"Clinica Bebe coche","fecha_hoy":"2026-07-29","dia_semana":"miércoles",
 "hoy_legible":"miércoles 29 de julio de 2026","hora_actual":"20:50",
 "numero_registrado":false,"verificado":false,"cliente":null}
```

Lo que el router sabía y **no** viajó: que el cliente declaró ser cliente existente,
que dio "Ana" como titular, que nombró a Oliver, que hubo un reto en curso, que hubo
un handoff, que un humano escribió "ok". Ninguno de esos hechos tiene representación
durable legible por el modelo.

El único canal durable que existe (`ConversationGoal` → `en_curso`) cubre 4 objetivos
de escritura y solo se abre cuando el modelo llama una tool de escritura. **La
identidad —la dimensión más crítica— es la que menos memoria tiene.**

### CR-3 · `HISTORY_WINDOW = 12` cuenta mensajes crudos

Reconstrucción exacta del turno de S3 (simulada contra la base de producción):

```
HISTORY_WINDOW = 12   ·   mensajes previos = 20

DENTRO de la ventana:              FUERA de la ventana:
  user: te estoy preguntando…        user: hola quiero una cita para Oliver   ←
  asst: No pude validar…             asst: ¡Hola! Bienvenido a…
  asst: ok                     ←     user: ya he ido varias veces             ←
  user: 4586                         asst: ¿A nombre de quién…?
  asst: ¿es la primera vez…?         user: Ana                                ←
  user: que miras de la conv…        asst: ¿los últimos 4 dígitos…?
  asst: Perdón, me expliqué mal      user: para que necesitas eso
  user: se te borró el contexto?     asst: Mmm, ese dato no me coincide
  asst: fuera de horario…
  user: no te pedí ningún horario
  asst: Tienes razón, me fui…
  user: que te dije hace rato?
```

**El modelo no mintió.** Dijo la verdad sobre un contexto amputado. Los tres hechos
centrales quedaron fuera, y ningún bloque de DATOS los repuso.

Dos decisiones se agravan mutuamente:

- La ventana cuenta **mensajes**, no turnos. En WhatsApp-MX el cliente escribe en
  ráfagas de 1-4 palabras (conv 12: 7 mensajes en 43 s). Un solo pensamiento del
  cliente consume medio contexto.
- **Cada plantilla tier-0 gasta un slot.** En la ventana de arriba, 6 de 12 son
  plantillas deterministas y 1 es el "ok" de un humano. El modelo tenía 12 espacios y
  gastó más de la mitad en la papelería del propio sistema.

### CR-4 · Nadie clasifica la intención del mensaje

No existe en el código ninguna función que responda "¿qué quiere este mensaje?".
Lo que hay es:

- `policy.evaluate`: una escalera fija de 13 predicados de **seguridad**. Es un router
  de riesgo, no de intención. Todo lo no capturado cae a `RUN_PLANNER`.
- Dentro de `RUN_PLANNER`: el modelo decide, pero recibe `me_falta: [...]` cada turno
  **sin ninguna señal de si el cliente está cooperando con el objetivo o no**.

La respuesta a "¿existe una política para decidir entre responder una duda / seguir
el objetivo / cambiar de objetivo / pausarlo?" es: **existe a medias, y por accidente.**

| Decisión | ¿Existe? | Dónde | Cómo falla |
|---|---|---|---|
| Responder una duda | **no** | — | sin mecanismo; el LLM lo hace o no |
| Seguir el objetivo | sí | `_goal_gate` | es el camino por defecto de todo |
| Cambiar de objetivo | sí | `goals.open_goal` | cancela el anterior en silencio |
| Pausar el objetivo | sí, pero mal | `_settle_goal` | solo si la interrupción se pudo responder **con otra tool** |

Ese último renglón es la inversión más dañina del sistema:

```python
def _settle_goal(conversation, *, goal_progressed, goal_attempted, other_tool_used):
    goal = goals.get_open_goal(conversation)
    if goal is None or goal_progressed:
        return False
    if goal_attempted:
        return goals.bump_stall(goal)      # ← intentó y no avanzó
    if other_tool_used:
        goals.pause(goal); return False    # ← interrupción "válida"
    return goals.bump_stall(goal)          # ← ★ preguntar cae AQUÍ
```

"¿Para qué necesitas ese dato?" no se responde con ninguna tool → cae en el último
`bump_stall`. **El sistema castiga al cliente por preguntar**, y a los 3 turnos lo
escala. Un cliente curioso es indistinguible de una conversación atascada.

### CR-5 · El router destruye sus propios hechos

Dos destrucciones distintas, ambas en producción:

1. `_advance_identity_triage` a los 2 `unclear` → `flow['identity_triage_done'] = 'unclear'`
   (`policy.py:406`). En conv 13 eso **sobrescribió** el `'returning'` que
   `_seed_family_challenge` había escrito 3 minutos antes. El sistema borró una
   clasificación correcta porque dos meta-preguntas se leyeron como respuestas ambiguas.

2. `_family_fail` con `fails >= 2` → `flow.pop('family_challenge')`. Se van con él
   `titular='Ana'`, `candidate_ids=[36518]` y `stage='digits'`. Cuando el cliente
   mandó `4586` —correcto— no había nada contra qué compararlo.

Esto no es "pérdida de contexto". Es **el sistema borrando una verificación en curso
y reiniciándola desde cero**.

### CR-6 · El modelo no distingue su voz de la del router

`policy.REPLY` → `enqueue_outbound` → `return` (`planner.py:66-76`). La plantilla sale.
El modelo nunca se entera, y la plantilla entra al historial como `assistant`,
indistinguible de lo que él escribió.

En conv 13 02:12:20 el modelo vio en su historial `assistant: "Ahorita estamos fuera
de horario…"` —un mensaje que **no escribió**— y en el turno siguiente el cliente le
reclamó "no te pedí ningún horario". El modelo se disculpó por un acto del router.
No tiene forma de saber que no fue él.

Agravante: `_after_hours_prefix` (`planner.py:551`) se dispara en el **primer**
`planner_reply` de la conversación sea cual sea el tema. En conv 13 se disparó en
medio de una queja por pérdida de contexto y **causó** el mensaje siguiente del
cliente. Es un aviso correcto sin ningún sentido de oportunidad conversacional.

### CR-7 · El objetivo solo ingiere argumentos de tools de escritura

`goals.capture` se invoca desde exactamente dos sitios:

- `_goal_gate` (`tools.py:710`) — argumentos de una tool de escritura.
- `_capture_slot_from_read` (`tools.py:585`) — **solo** `date`, **solo** desde
  `find_available_slots`, **solo** si ya estaba en `missing`.

O sea: el único camino por el que un dato entra al sistema es que el modelo decida
ponerlo en los argumentos de una llamada. Lo que el cliente dijo y lo que el agente
respondió **en prosa** no existen para el estado.

Conv 12 es literalmente esto:

```
21:23:16  CLIENTE  martes a las 9
21:23:27  TOOL     find_available_slots(date=2026-08-04)  → occupied: 0
21:23:29  AGENTE   El *martes 4 de agosto* a las *9:00 am* está libre 🎉
   …
GOAL 2   missing=['date','time']   asked={'date':4,'time':4}   stall=0
```

El agente **dijo la fecha y la hora**, y el objetivo siguió reportándolas como
faltantes. `date` hoy sí se captura (fix de ayer); **`time` sigue sin captura desde
lecturas.**

Anti-patrón #9 del brief, confirmado al pie de la letra: la conversación la gobierna
el marshalling de argumentos, no el objetivo.

### CR-8 · Capacidad ≠ intención (y el sistema las confunde)

`ConversationGoal.name` ∈ `{schedule, register_and_schedule, cancel, reschedule}` — es
decir, **el catálogo de objetivos es el catálogo de tools**. Un cliente que quiere
"registrarme sin agendar" no tiene objetivo representable.

Conv 12: su intención real era inexpresable, así que se le forzó a
`register_and_schedule`, cuyos slots faltantes se le exigieron indefinidamente. El
agente terminó **discutiendo con el cliente en nombre de una restricción de schema**:

```
21:22:24  Entiendo, pero el sistema me pide al menos una *fecha y hora* para
          poder registrar a Luna.
21:24:38  Ah, el sistema me pide una *fecha y hora*… Es solo un requisito del alta
```

El fondo no es la fuga de G7 (que el PO ya desprioritizó): es que **se le pide al
cliente que satisfaga la base de datos**. La causa técnica es real —
`create-with-patient` es atómico cliente+mascota+cita— pero el sistema no tiene forma
de decir "esto no se puede" y por tanto no deja de pedir.

### CR-9 · Los guards son puramente negativos y solo cubren al LLM

`guards.check_output` valida léxico: UUIDs, jerga, consejo médico, promesas, precios
inventados. Nada valida **conducta**: repetir la misma pregunta 3 veces, contradecir
el historial, afirmar un éxito sin tool (BUG-AGENT-001, abierto).

Y corren **solo** en el camino del LLM. Las plantillas tier-0 los saltan por completo
— razonable para contenido, pero significa que los fallos conversacionales del
**router** (que son los peores de esta auditoría) no se validan ni se loguean.

### CR-10 · Las salidas de emergencia son una whitelist de 4

Orden de `policy.evaluate`: urgencia (3), pide humano (4), opt-out (5), pregunta-bot
(6) corren **antes** de los retos (8/8b/8c). Una pregunta cualquiera no corre antes de
nada.

Resultado: **la única forma de que un cliente confundido salga de un reto es pedir un
humano o decir accidentalmente "convulsiona".** La flexibilidad del sistema es una
lista blanca de cuatro predicados de seguridad.

---

## 4. Meta-conversaciones (pregunta 4 del brief)

Grep de los patrones del brief en `matchers.py`: **cero**. No existe ningún matcher
para ninguno.

| Mensaje del cliente | Qué pasa hoy | Por qué |
|---|---|---|
| "¿Para qué quieres ese dato?" | cuenta como respuesta **equivocada** | CR-1 |
| "¿Qué acabas de decir?" | LLM, con ventana quizá amputada | CR-3 |
| "¿No te acuerdas?" | LLM responde con lo que ve; puede negar hechos reales | CR-3 |
| "¿Se perdió el contexto?" | LLM improvisa (en conv 13 contestó con la fecha de hoy) | CR-3 |
| "¿Por qué preguntas otra vez?" | `bump_stall` → acerca la escalada | CR-4 |
| "¿Qué estás haciendo?" | LLM libre | — |
| "¿Qué información necesitas?" | LLM libre; `me_falta` sí está en DATOS → suele salir bien | — |
| "¿Ya te respondí eso?" | `bump_stall` | CR-4 |
| "¿No acabamos de hablar de eso?" | `bump_stall` | CR-4 |

El caso perverso: **"¿por qué preguntas otra vez?" es el mensaje de mayor valor
diagnóstico que un cliente puede mandar** — es un reporte directo de un defecto. Hoy
es el mensaje que más probabilidad tiene de provocar una escalada por estancamiento.

Y el sistema **ya sabe** que se repitió: `goals.context_block` publica
`ya_preguntado_2_veces`. Lo publica como dato y no hace absolutamente nada más. En
conv 12 preguntó 4 veces; la única salida fue que el modelo llamara `request_human`
por su cuenta.

---

## 5. Interrupciones (pregunta 5)

| Contexto | ¿Responde la pregunta y retoma? |
|---|---|
| Reto de identidad / familiar / tamiz activo | **no** — la ignora y la penaliza (CR-1) |
| `pending_action` (confirmación tier-2) activo | parcial — `unclear` cae al planner, que puede responder; el pending sobrevive ✓ |
| `handoff_pending` | no — un acuse y luego silencio (correcto por diseño) |
| Objetivo activo, pregunta respondible con otra tool | **sí** — se pausa el objetivo y se retoma ✓ |
| Objetivo activo, pregunta **no** respondible con tool | no — `bump_stall` (CR-4) |
| Sin estado | sí (el LLM decide) |

Lo mejor implementado del sistema es la rama de `pending_action`: sobrevive a la
interrupción, distingue afirmativa/negativa/dilatoria/ambigua, y las falsas
afirmativas no ejecutan ni cierran. **Ese es exactamente el patrón que los retos de
identidad necesitan y no tienen.** El diseño correcto ya existe en la casa, aplicado a
otro problema.

---

## 6. Handoff: qué se conserva (pregunta 7)

```
                 ┌──────────────────────────────────────────┐
   ACTIVE ───────► escalate_to_human()                       │
                 │   flow.pop('pending_action')       ✗ pierde│
                 │   flow.pop('handoff_ack_sent')            │
                 │   goals.close_open_goal(HANDOFF)   ✗ pierde│
                 │   state = HANDOFF_PENDING                  │
                 └──────────────┬───────────────────────────┘
                                │
              claim_conversation│ state = HUMAN_ACTIVE
                                │ (agente en silencio — correcto)
                                ▼
              release_conversation()
                 state = ACTIVE
                 ✗ NO reabre el objetivo
                 ✗ NO resuelve el HumanHandoff
                 ✗ NO limpia flow rancio
                                │
                                ▼
                 ACTIVE — el agente vuelve a hablar
                 con un handoff todavía abierto
```

| Elemento | ¿Sobrevive al handoff + release? | Nota |
|---|---|---|
| Historial (`Message`) | ✓ pero recortado a 12 | CR-3 |
| Identidad (`ContactIdentity`) | ✓ durable | correcto |
| Objetivo + slots | ✗ `STATUS_HANDOFF`, nunca se reabre | CR-5 |
| Reto en curso (`family_challenge`) | ✗ `pop` | CR-5 |
| `pending_action` | ✗ `pop` | deliberado, defendible |
| `identity_triage_done` | ✓ sobrevive… a veces con el valor equivocado | CR-5 |
| `HumanHandoff.resolved_at` | ✗ queda `None` | conv 13 handoff 14 |
| Lo que dijo el humano | ✓ entra como `assistant` | **bien hecho** |

Verificado en producción: conv 13 terminó `state=active` con `handoff 14
resolved=None`. El agente reanudó la conversación mientras el caso seguía formalmente
en la cola humana.

Nota a favor: mapear los mensajes del staff a `assistant` (`prompts.py:150`) es la
decisión correcta y evita que el agente contradiga a su compañero. Pero en conv 13 ese
mecanismo gastó un slot de contexto en un "ok" que desplazó un hecho real.

---

## 7. Flexibilidad y humanidad (preguntas 8 y 10)

El prompt **no** es el problema. `prompts.py` v7 dice explícitamente "Si algo falla
hablas como persona", da 4 ejemplos de tono, y permite disculparse y aclarar. Y el
modelo obedece: en conv 13 intentó recuperarse tres veces por su cuenta
("Tienes razón, disculpa", "me fui por otro lado", "Vamos de nuevo").

**La rigidez no está en el prompt. Está en las capas que ni consultan al modelo.**
Los 4 mensajes más robóticos de conv 13 —los que rompieron la conversación— son
plantillas deterministas:

| Momento | Lo que dijo el sistema | Lo que diría una recepcionista |
|---|---|---|
| Cliente pregunta por qué se le piden dígitos | "Mmm, ese dato no me coincide." | "Es para confirmar que eres tú y proteger los datos de Ana 🙂 ¿Me los pasas?" |
| Cliente insiste con la misma pregunta | "No pude validar esos datos. Te comunico con el equipo." | "Perdón si sonó raro — es el único dato que me falta para poder ayudarte yo mismo." |
| Cliente manda 4586 (correcto) | "¿es la primera vez que nos visitan…?" | "¡Listo, Ana! Ya te ubico. ¿Te agendo a Oliver?" |
| Cliente pregunta "¿qué te dije hace rato?" | "No me lo dijiste aún, por eso te pregunto 😊" | "Me dijiste que ya habías venido, y que el registro es a nombre de Ana." |

El tercer renglón es el más caro del sistema: **el cliente dio la respuesta correcta y
el agente lo devolvió al principio.** Ninguna persona hace eso.

El cuarto es el único donde el modelo es formalmente inocente: contestó con exactitud
lo que su contexto contenía.

---

## 8. Principios violados — diagnóstico

Esta sección es el **hallazgo**; el cuerpo normativo de reglas vive en **§11**. La columna
derecha da la trazabilidad completa: cada violación observada tiene su regla, su causa raíz y su
evidencia.

| Principio violado | Regla | Evidencia / causa |
|---|---|---|
| Nunca castigues una pregunta | **R1**, R10 | preguntar suma `fails` (CR-1) y suma `stall` (CR-4) |
| Un hecho dicho una vez es un hecho para siempre | **R2** | ventana de 12 + `flow` no publicado (CR-2, CR-3) |
| No pidas lo que ya tienes | **R3** | conv 12, 4 veces (CR-7) |
| Distingue "no me respondiste" de "me respondiste mal" | **R1** | `_family_fail` los colapsa (CR-1) |
| Nunca niegues lo que el cliente dijo | **R2** | S3 (CR-3) |
| El progreso del cliente no se tira | **R5**, **R8** | `pop` del reto al escalar (CR-5) |
| Una interrupción vuelve donde empezó | **R4** | no existe `desviar` (§10.4) |
| Di la verdad sobre lo que no puedes hacer | **R6** | conv 12: en vez de "no puedo", pide el dato para siempre (CR-8) |
| Habla de la clínica, no del sistema | **R6** | "el sistema me pide una fecha" (CR-8) |
| Toda pregunta tiene un motivo decible | **R9** | `T0_TRIAGE_DIGITS` sin motivo (conv 13) |
| Responde por lo tuyo, no por lo ajeno | **R11** | el modelo se disculpa por el router (CR-6) |
| Una interacción, una fuente de verdad | **R7** | 5 implementaciones del mismo objeto (§10.2) |

---

## 9. ¿Quién gobierna el turno?

Esta es la pieza que faltaba en §1-§8. La fragmentación de estado es un síntoma; la causa es
que **nadie tiene la autoridad del turno**. Hay tres capas decidiendo y una cuarta influyendo,
y gana la que llega primero.

### 9.1 · Evidencia: 22 puntos de salida en 3 módulos

`grep -cE "return \{'decision'" planner.py` → **22**. Veintidós lugares distintos donde un
turno termina, cada uno con su propia lógica y ninguno consciente de los otros:

| Capa | Cómo termina el turno | Sitios | ¿Debería poder? |
|---|---|---|---|
| Policy · salvaguardas | `SILENT` / `ESCALATE` / `CLOSE` | 3 | **sí** — son cortacircuitos |
| Policy · plantillas | `REPLY` (tier-0) | 1 | sí, pero hoy sin clasificar el mensaje (CR-1) |
| Policy · retos | `_advance_*` → `REPLY` | 3 máquinas | **no** como está: decide sin arbitraje |
| Planner | `planner_reply`, `guard_blocked`, `goal_stalled`, `tool_budget_exhausted` | 4 | **sí** — es el ejecutor |
| Planner · commit | 7 salidas de `_commit_pending` | 7 | sí |
| **Tool** | `needs_confirmation=True` → cierra el turno | 4 | **no** |
| **Tool** | `reply_text` → **escribe copy al cliente** | 1 | **no** |
| **Tool** | `client_error` → elige la instrucción que recibe el modelo | ~20 strings | **no** |
| **Tool** | `_goal_gate` → decide *preguntar un dato* | 4 call sites | **no** |
| LLM | emitir texto | 1 | no decide: redacta |

Los cuatro renglones marcados son el hallazgo. **Una tool gobierna la conversación**, y de
tres maneras distintas:

1. `ToolOutcome(reply_text=...)` (`tools.py:1168`) → `planner.py:252` encola ese texto **tal
   cual** al cliente y cierra el turno. Una función de dominio escribiendo copy.
2. `ToolOutcome(needs_confirmation=True)` (4 sitios) → el turno acaba porque la tool lo dijo.
3. `_soft_error_hint(client_error)` (`planner.py:485`) es una veintena de instrucciones de
   coaching indexadas por el **código de error de la tool**. Es decir: **el código de error de
   una tool elige lo que el agente va a decir en el siguiente mensaje.**

Y `_goal_gate` (`tools.py:698`) es una tool que decide, sola, que toca pedirle un dato al
cliente — la decisión conversacional más frecuente del sistema, tomada en la capa de menos
autoridad.

### 9.2 · El costo oculto: el turno no es auditable

El dict de telemetría tiene 22 etiquetas posibles de `decision`, pero **no existe un registro
de decisión**: ninguna fila dice "en este turno el veredicto fue X porque Y". Por eso
diagnosticar la conv 13 exigió reconstruir la ventana de contexto a mano contra la base de
producción.

Una autoridad única no es solo corrección — es **observabilidad**. Un veredicto por turno ⇒
una fila por turno ⇒ `tasa_repregunta`, `tasa_desvío`, `compromisos_abandonados` se **calculan**
en vez de inferirse. Esto se formaliza como **R12** (§11).

### 9.3 · La jerarquía

Lo que hoy no existe: **una capa cuyo único trabajo sea responder "¿qué debe pasar con ESTE
turno?"**. No clasifica mensajes (eso es un insumo). No ejecuta (eso es el planner). Decide.

Regla de lectura: **la autoridad baja, los datos suben.**

```
  USUARIO
     │  mensaje (ráfaga)
     ▼
┌────────────────────────────────────────────────────────────┐
│ 0 · SALVAGUARDAS            cortacircuitos, NO negociables │
│     urgencia · bloqueado · humano activo · opt-out         │
│     preemptan todo, incluido al árbitro                    │
└────────────────────────┬───────────────────────────────────┘
                         ▼
┌────────────────────────────────────────────────────────────┐
│ 1 · ÁRBITRO DEL TURNO       ÚNICA autoridad                │
│     entra: (mensaje, estado, compromisos)                  │
│     sale : UN veredicto  →  continuar │ desviar │           │
│                             suplantar │ abortar │ responder │
│     no redacta · no ejecuta · deja registro                │
└────────────────────────┬───────────────────────────────────┘
                         ▼
┌────────────────────────────────────────────────────────────┐
│ 2 · COMPROMISOS             qué prometimos y en qué punto   │
│     fuente única de verdad de la interacción (§10)         │
└────────────────────────┬───────────────────────────────────┘
                         ▼
┌────────────────────────────────────────────────────────────┐
│ 3 · PLANNER                 ejecuta el veredicto           │
│     no decide QUÉ pasa; decide CÓMO se cumple              │
└────────────────────────┬───────────────────────────────────┘
                         ▼
┌────────────────────────────────────────────────────────────┐
│ 4 · LLM                     redacta y propone              │
│     nunca decide ignorar una pregunta: no es su decisión   │
└────────────────────────┬───────────────────────────────────┘
                         ▼
┌────────────────────────────────────────────────────────────┐
│ 5 · TOOLS                   autoridad CERO                 │
│     devuelven hechos. No terminan turnos. No escriben copy.│
└────────────────────────────────────────────────────────────┘
```

### 9.4 · Dos divergencias respecto al boceto del PO

El boceto era `Usuario → Conversation Policy → Objetivo → Planner → Tools → LLM`. Me separo en
dos puntos, y creo que importa:

**(a) Las salvaguardas van ARRIBA del árbitro, no dentro.** Si el árbitro puede razonar sobre
la urgencia, la urgencia pasa a ser una cuestión de política. No puede serlo: hoy es el paso 3
de `policy.evaluate` y ahí debe quedarse. Un cortacircuito no es una decisión sobre el turno —
es la negativa a tener esa decisión. Cinco predicados, ninguno discutible.

**(b) Tools con autoridad *cero*, no "por debajo del LLM".** Ordenarlas al final no basta: hay
que **quitarles dos capacidades** que hoy tienen. `reply_text` y `needs_confirmation` salen del
contrato. Una tool *propone* un compromiso y *devuelve* hechos; el árbitro decide si se
parafrasea y el planner lo redacta. Mientras `ToolOutcome` pueda encolar texto al cliente, la
jerarquía es decorativa.

Nota sobre el orden LLM↔Tools: en **ejecución** la tool va después del LLM (el modelo la
invoca); en **autoridad** la tool va última. Confundir ambas cosas es parte del desorden actual
— por eso las separo explícitamente.

### 9.5 · Cómo se evita que el árbitro sea un segundo planner

Objeción del PO, y es la correcta: si en seis meses el árbitro tiene 500 líneas de reglas
especiales, excepciones, heurísticas y prioridades, **solo se movió la complejidad**.

No es una preocupación hipotética. **Ya pasó en esta casa, con esta misma capa.**

#### El precedente: `policy.evaluate`

Nació como "un router de predicados de seguridad en el orden EXACTO de la spec". Hoy:

| Medida | Valor |
|---|---|
| Líneas de `evaluate()` | **203** |
| Pasos numerados | **20** |
| Slots que el esquema original preveía (0…13) | 14 |
| Pasos **encajados a presión** (`2b`, `6b`, `8b`, `8c`, `10b`, `12b`) | **6** |
| `save()` dentro de la función "pura" | **6** |
| Helpers privados en el módulo | 13 |

La numeración es el registro fósil: **cada sufijo `b`/`c` es un caso que no cupo en el esquema
y se metió con calzador.** Nadie decidió que `evaluate` tuviera 20 pasos; llegó ahí un `b` a la
vez. Ese es exactamente el destino que hay que hacerle imposible al árbitro — no improbable.

#### El principio que lo mantiene pequeño (PO)

> **El árbitro nunca decide contenido. Solo decide control de flujo.**
>
> No puede decidir *"pregunta esto"*. Solo *"el siguiente paso es responder la interrupción"*.
> La redacción sigue siendo del planner/LLM.

Prueba para distinguir control de contenido: **¿se puede renderizar el veredicto en otro idioma,
otro tono u otro canal sin tocar el árbitro?** Si sí, es control. Si no, es contenido.

```python
# ✗ CONTENIDO — el árbitro se convirtió en planner
{"action": "ask", "slot": "digits", "text": "¿los últimos 4 dígitos?"}

# ✓ CONTROL — el árbitro solo dice qué pasa y sobre qué
{"verdict": "desviar", "commitment": "identity", "return_to": "digits"}
```

**Corolario que refuerza R9**: si el árbitro no puede decir *por qué* se pide un dato (es
contenido), ese "por qué" tiene que vivir en otro lado — y el lugar correcto es el **factor del
compromiso**. Cada factor declara su propio `why`:

```python
Factor(name='digits', why='confirmar que eres tú y proteger los datos del titular')
```

El árbitro dice `return_to='digits'`; el planner busca el `why` del factor y el LLM lo redacta.
Así **R9 pasa de hábito de revisión de copy a garantía estructural**: un factor sin `why` no
compila. La observación del PO sobre contenido/control es lo que hace posible ese endurecimiento.

#### Cinco mecanismos, no buenas intenciones

Un principio no detiene el crecimiento por sí solo. Lo que sí:

**A1 · Conjunto de veredictos CERRADO.** Cinco (`continuar`, `desviar`, `suplantar`, `abortar`,
`responder`) como enum. Un sexto exige ADR. El repo ya usa esa compuerta (`METRICS_SCHEMA_VERSION`).
La complejidad de una capa de decisión la fija su **espacio de salida**, no su entrada.

**A2 · El árbitro es PURO.** Cero `save()`, cero red, cero DB. `(ráfaga, estado, hechos) →
TurnDecision`. Esto no es cosmético: los 6 `save()` de `policy.evaluate` son la razón de que sus
pasos no se puedan reordenar, testear por separado ni tabular. **Un paso que muta estado esconde
una decisión dentro de un efecto secundario.** Su docstring ya admite la mutación con
franqueza — y es precisamente ahí donde perdió la tabulabilidad.

**A3 · Hechos de entrada, sin cómputo propio.** El árbitro no llama matchers, ni al ORM, ni
nada. Recibe un struct de hechos ya calculados. Entonces su cuerpo es una **tabla de decisión**
sobre un conjunto fijo de hechos, no una cadena de `if`. El crecimiento aparece como **hechos
nuevos, en la capa de matchers**, donde corresponde y donde cada uno se testea solo.

**A4 · Presupuesto de tamaño con test que lo bloquea.** Un test que falla si la función de
decisión excede N ramas. Suena tosco; es lo único que funciona contra la deriva de seis meses.
El repo ya bloquea CI con gates de este tipo (`noConsoleTokenLeak.test.js`, el gate de
`.public_id || .id`). Sin esto, A1-A3 son recomendaciones.

**A5 · Cero prioridades dentro del árbitro.** El PO nombra "prioridades" como olor, y tiene
razón. La única precedencia real del sistema (urgencia primero) vive **arriba**, en las
salvaguardas (§9.4a). Consecuencia: el árbitro **no tiene lógica de precedencia en absoluto**.
Si algún día alguien necesita ordenar dos veredictos, es señal de que un hecho está mal
modelado — no de que falte una regla.

> Métrica de salud, verificable en cualquier momento: **si el árbitro no cabe en una tabla,
> dejó de ser un árbitro.**

#### Dónde migrará la complejidad después

Observación del PO, y es general: en cuanto el árbitro tiene presupuesto (A1-A5), **el riesgo deja
de ser el árbitro y pasa a ser el modelo de hechos** — porque cuando una arquitectura descubre los
*facts*, tiende a convertir todo en un fact.

Eso no es casualidad, es conservación:

> **La complejidad migra a la capa que no tiene presupuesto.**

De ahí sale una heurística para la próxima auditoría, que no depende de este caso: **preguntar
cuál capa carece hoy de presupuesto y mirar ahí.** La respuesta ahora es el modelo de hechos, y por
eso existe **R13** (§11.1).

Y una distinción que evita sobrecorregir: **no toda migración es mala.** Comparar dos capas de este
mismo repo, con cantidad comparable de complejidad y salud opuesta:

| Capa | Tamaño | Forma | ¿Sana? |
|---|---|---|---|
| `matchers.py` | **349 lemas** en 17 listas | plana, aditiva, cada lema testeable solo, cero ramas | **sí** |
| `policy.evaluate` | 203 líneas, 20 pasos, 6 con calzador | ramificada, secuencial, con efectos | **no** |

`matchers.py` tiene *más* complejidad que `evaluate` por cualquier medida de volumen, y está sana.

> **El problema nunca es la cantidad de complejidad: es su forma.** Crecer en una lista plana es
> salud; crecer en una decisión ramificada es decadencia.

Corolario operativo: cuando A3 empuje complejidad del árbitro hacia los matchers, **eso es el
diseño funcionando**, no una fuga. El destino correcto de la complejidad es siempre la capa más
plana que pueda absorberla.

### 9.6 · Qué NO cambia

La jerarquía es de *gobierno conversacional*, no de seguridad. Intactos:

- `run_tool` revalida tier, verificación y ownership. El árbitro no autoriza nada.
- La confirmación tier-2 sigue siendo la barrera antes de escribir; la afirmativa ejecuta los
  args **staged**, nunca regenerados (TC-SEC-03).
- La urgencia sigue preemptando todo (§9.4a).
- El LLM sigue sin poder autorizar. Gana voz, no permisos.

---

## 10. Compromisos conversacionales

El modelo mental de **slots** llegó a su techo. El de **compromisos** es más natural y —esto es
lo decisivo— es el único que puede representar lo que se rompió en la conv 13.

### 10.1 · Por qué es mejor que slots

| Slot | Compromiso |
|---|---|
| un hueco en un formulario | una **promesa hecha al cliente** |
| lo posee la tool que lo necesita | lo posee la conversación |
| solo se llena desde args de tool (CR-7) | lo avanza cualquier cosa: el cliente, una lectura, un humano |
| no sabe que se le prometió algo a alguien | sí, y por eso "no olvidar qué estaba haciendo" es **exigible** |
| existe mientras la tool lo pida | existe hasta cumplirse o abandonarse |

El argumento que cierra la discusión: **la verificación de identidad no tiene slots.**
`identity_challenge`, `family_challenge` y `identity_triage` son claves de un dict `flow` con
máquinas de etapas ad-hoc. El modelo de slots **literalmente no puede representar** lo que
falló en la conv 13. El de compromisos sí, porque un compromiso es "qué prometí", no "qué
campos me faltan".

### 10.2 · Cinco implementaciones de un solo concepto

| Hoy | El compromiso, dicho en voz alta | Etapas | Paciencia | Terminal |
|---|---|---|---|---|
| `flow['identity_triage']` | "voy a saber quién eres" | ask→titular | `asks` 2 | done / unclear |
| `flow['family_challenge']` | "voy a validar que eres de la familia de X" | pet→digits | `fails` 2 | linked / handoff |
| `flow['identity_challenge']` | "voy a confirmar que eres el titular" | pet→owner | `fails` 2 + `retried` | verified / handoff |
| `flow['pending_action']` | "voy a hacer X si me confirmas" | — | TTL 30 min | committed / discarded |
| `ConversationGoal` | "voy a agendarte" | slots | `stall` 3 | completed / cancelled / handoff |

Los cinco tienen: una promesa, un paso actual, lo ya reunido, cuántas veces se preguntó, un
presupuesto de paciencia y una salida terminal. **Cinco implementaciones del mismo objeto, cada
una con su propio bug.** Solo una (`ConversationGoal`) está en una tabla; las otras cuatro
viven en un blob JSON que no se agrega, no se mide y se destruye con un `pop`.

Esto es la Regla 7 (§11) aplicada: una interacción, una fuente de verdad.

### 10.3 · Ciclo de vida — nunca "desaparece"

```
                   ┌──────────┐
      adquirido ──►│  ACTIVO  │──────────► COMPLETADO   (cumplido)
                   └────┬─────┘
        desviar ────────┤◄──────── retomar (dirección de retorno)
                   ┌────▼─────┐
                   │ DESVIADO │   el agente atiende otra cosa y VUELVE al punto exacto
                   └────┬─────┘
      suplantar ────────┤◄──────── ofrecer de vuelta
                   ┌────▼───────┐
                   │ SUSPENDIDO │  otro compromiso tomó el frente (urgencia, handoff)
                   └────┬───────┘
                   ┌────▼───────┐
                   │ BLOQUEADO  │  el dominio no puede cumplirlo → se dice la verdad, se deja de pedir
                   └────────────┘
                   ┌────────────┐
                   │ ABANDONADO │  el cliente lo abandonó explícitamente
                   └────────────┘
```

### 10.4 · El veredicto del árbitro sobre el compromiso

Los tres estados del PO, con un cuarto que hace falta:

| Veredicto | Qué le pasa al compromiso | Hoy |
|---|---|---|
| **continuar** | avanza una etapa | ✓ |
| **desviar** | se guarda la **dirección de retorno**, se atiende lo otro, se vuelve al punto exacto | ✗ **no existe** |
| **suplantar** | otro compromiso toma el frente legítimamente; el desplazado se **recuerda y se ofrece de vuelta** | ✗ `open_goal` cancela en silencio |
| **abortar** | el cliente lo abandona | parcial |

**Sobre `desviar`, el hallazgo concreto**: `goals.pause()` existe (`goals.py:219`) pero **no
guarda dirección de retorno**. Registra que el objetivo está pausado; no registra *qué pregunta
estaba pendiente*. Retomar significa re-derivarlo de la ventana de 12 mensajes — que es
exactamente lo que falla (CR-3).

> **Una pausa sin dirección de retorno no es una pausa: es una interrupción que sobreviviste
> por suerte.** Por eso "vuelve exactamente donde estaba" no se cumple hoy aunque el estado
> `paused` exista.

**Sobre `suplantar` ≠ `abortar`**: hoy ambos colapsan en `close(CANCELLED)`. Un cliente cuyo
perro convulsiona a mitad de agendar **no abandonó la cita**. Al cerrar la urgencia, una
recepcionista dice "¿retomamos la cita de Luna?". El sistema hoy no puede: la borró.

### 10.5 · Lo que los compromisos habrían evitado

| Síntoma | Por qué desaparece |
|---|---|
| S1 · pregunta contada como respuesta | el veredicto es `desviar`, no "respuesta equivocada" |
| S2 · verificación borrada al escalar | `SUSPENDIDO`, y el `4586` posterior la resuelve |
| S3 · el agente niega hechos reales | el compromiso es fuente de verdad anclada, fuera de la ventana |
| S4 · pedir 4 veces la misma fecha | el compromiso sabe qué tiene, sin depender de args de tool |
| S9 · objetivo cerrado y nunca reabierto | `SUSPENDIDO` → `release` lo reanuda |
| S10 · el cliente satisface un schema | `BLOQUEADO` → se dice la verdad y se deja de pedir |

---

## 11. Reglas conversacionales

No arquitectura: **reglas**. Sirven para evaluar cualquier cambio futuro sin volver a discutir
los principios. Las siete primeras son del PO; las cuatro últimas las añado. Donde afiné una
regla, digo por qué.

### 11.1 · El cuerpo de reglas

> **R1 · Una no-respuesta nunca es una respuesta equivocada.**
> *(generalización de "una pregunta nunca puede contarse como una respuesta": cubre también
> "mmm", el cambio de tema y el silencio. El sistema debe distinguir "no me respondiste" de "me
> respondiste mal" — son categorías distintas, y confundirlas no aporta ninguna seguridad.)*

> **R2 · El agente nunca puede negar un hecho que existe en el estado.**
> *Prerrequisito: solo es exigible si el estado se **publica** (§12 P1). Hoy la regla es
> inaplicable por construcción — el modelo no puede honrar hechos que nunca recibió.*

> **R3 · El agente nunca puede pedir un dato que ya posee.**
> *Salvedad: **confirmar** no es pedir. "¿Te confirmo el martes 4 a las 9?" es válido; obliga a
> cero trabajo al cliente y nombra el valor. Lo prohibido es preguntar **como si no lo
> tuviera**. Sin esta salvedad, R3 anularía el mecanismo de baja confianza.*

> **R4 · Toda interrupción debe terminar exactamente donde empezó.**
> *Excepción única: una **salvaguarda** (urgencia, petición de humano) suplanta legítimamente y
> no retoma sola — se **ofrece** de vuelta. Sin esta excepción, R4 prohibiría la preempción por
> urgencia, que es correcta.*

> **R5 · El objetivo nunca desaparece.** Activo, desviado, suspendido, bloqueado, completado o
> abandonado — pero **nunca ausente**. Ningún `pop`.

> **R6 · El cliente nunca debe satisfacer restricciones internas.**
> *Corolario que la vuelve accionable: si una restricción no se puede satisfacer sin que el
> cliente se entere, **la restricción es un bug de producto, no un problema de copy.** El
> arreglo honesto de la conv 12 no es redactar mejor "el sistema me pide una fecha": es hacer
> posible el alta sin cita.*

> **R7 · Toda interacción debe poder resumirse en una única fuente de verdad.**
> *Mata las cinco implementaciones de §10.2.*

> **R8 · Ningún dato correcto aportado por el cliente se pierde por un fallo del sistema.**
> *El `4586` de la conv 13 era correcto, llegó, y se tiró porque el sistema había destruido el
> reto 40 segundos antes.*

> **R9 · Toda pregunta del agente debe llevar una razón que pueda decir en voz alta.**
> *Si el agente pide los últimos 4 dígitos, tiene que poder contestar "¿para qué?". En la conv 13
> no podía — `T0_TRIAGE_DIGITS` no trae el motivo y el router no tenía rama para la pregunta.*
> *Empezó como gate de revisión de copy y el principio contenido/control (§9.5) la vuelve
> **estructural**: el `why` vive en el **factor del compromiso**, y un factor sin `why` no
> compila. Deja de depender de que alguien se acuerde en la revisión.*

> **R10 · Repetir una pregunta es siempre defecto del sistema, nunca del cliente.**
> *Corolario operativo: la repetición debe cambiar la **conducta** del sistema, no solo
> aparecer en un bloque de datos (hoy `ya_preguntado_2_veces` se publica y no hace nada). Y
> preguntar **nunca** puede acercar al cliente a una escalada (CR-4).*

> **R11 · El agente responde solo por sus propios actos.**
> *No se disculpa por lo que escribió el router ni contradice a un humano del equipo. Requiere
> atribución de autoría (§12 P6).*

> **R12 · Toda decisión conversacional debe poder explicarse después. No al usuario: al
> desarrollador.**
>
> ```python
> TurnDecision(
>     verdict='desviar',                    # QUÉ pasó      (enum cerrado, 5 valores)
>     because='client_asked_question',      # POR QUÉ pasó  (enum cerrado de hechos)
>     commitment='identity',                # SOBRE QUÉ
>     return_to='digits',                   # DÓNDE se retoma
> )
> ```
>
> Tres afinados sobre la forma que propuso el PO, y los tres importan:
>
> **(a) `because` es un enum, no prosa — y ORTOGONAL al contexto.** Con texto libre R12 da
> depurabilidad de UN turno; con enum da agregación sobre 10 000. Pero un enum que absorbe el
> contexto es peor que la prosa: solo mueve el problema de sitio. Ver §11.2.
>
> **(b) Se persiste, no se loguea.** Una fila por turno, como ya se hace con `LLMCall` (mismo
> orden de magnitud). Es la condición para que lo de §9.2 sea real: stdout no es consultable al
> volumen que hace falta.
>
> **(c) Nunca lleva PII.** Referencias y enums; jamás el cuerpo del mensaje. El texto ya vive en
> `Message` y se enlaza por FK (regla R15 de la spec).
>
> **El argumento más fuerte de R12 no es depurar: es el sustrato de la regresión conversacional.**
> Con decisiones persistidas se puede **reproducir** la conv 13 contra el árbitro nuevo y afirmar
> que los veredictos cambiaron. Hoy eso no existe — diagnosticar esa conversación exigió
> reconstruir a mano la ventana de contexto contra la base de producción. R12 convierte el
> tráfico real en la suite de pruebas.

> **R13 · Un hecho solo existe si puede cambiar una decisión futura.**
>
> Si un dato jamás puede modificar el comportamiento del sistema, no pertenece al modelo de
> hechos: pertenece al **historial de mensajes**. Mantiene el modelo pequeño y evita que
> `facts_produced` se vuelva un inventario infinito.
>
> *Es la regla que protege a la capa donde migrará la complejidad **después** del árbitro
> (§9.5 in fine). Se comprueba con un gate estático —un hecho que ninguna fila del árbitro lee es
> código muerto— y un reporte estadístico que **no** es gate: un hecho raro puede ser
> irrenunciable (§11.2).*

### 11.2 · El rastro del turno — forma, y qué NO puede pasarle

#### El riesgo que hay que vigilar: la explosión de enums (PO)

```python
# ✗ El enum absorbió el contexto. Solo se movió el problema.
CLIENT_ASKED
CLIENT_ASKED_WHILE_IDENTITY
CLIENT_ASKED_WHILE_IDENTITY_AFTER_DIGITS
CLIENT_ASKED_WHILE_IDENTITY_AFTER_PET
CLIENT_ASKED_DURING_CONFIRMATION
CLIENT_ASKED_DURING_HANDOFF

# ✓ El motivo de CONTROL es uno; el contexto son coordenadas
because   = CLIENT_INTERRUPT
commitment= identity
stage     = digits
```

Es el error clásico de esquema en estrella: **el enum es la dimensión, los campos son las
coordenadas.** Denormalizar coordenadas dentro del nombre de la dimensión multiplica valores y
destruye la agregación. Este repo ya sabe hacerlo bien en otro sitio: `DailyOrgMetrics` tiene los
7 KPIs como **columnas**, no filas con un `metric_name` string.

#### Ya está pasando aquí, en un órgano más pequeño

`HumanHandoff.reason_code` son 7 motivos de control y está bien planteado. Pero tiene la
enfermedad en dos direcciones, y ambas se ven en la conv 13:

| Campo | Valor real en conv 13 | Problema |
|---|---|---|
| `reason_code` | `identity_ambiguous` | el enum **diagnostica**, no clasifica — y **el diagnóstico era falso**: nada fue ambiguo, el cliente contestó con una pregunta. Debería ser `identity` (dimensión) y el qué-pasó vivir aparte |
| `reason_detail` | `family:failed_digits` | coordenadas `{compromiso}:{resultado}` denormalizadas **dentro de un string libre**. Inconsultable: no se puede contar por compromiso ni por resultado |

Es exactamente la advertencia del PO, ya materializada: **la palabra de contexto metida en el
enum mintió en producción**, y las coordenadas acabaron en texto libre. `because=CLIENT_INTERRUPT`
+ `commitment` + `stage` es el arreglo, y conviene aplicarlo también a `reason_code` cuando se
toque.

#### Dos compuertas mecánicas, no buenas intenciones

**G1 · Prueba de ortogonalidad.** *¿Se puede contar un valor de `because` independientemente de
cualquier compromiso?* Si `SELECT count(*) WHERE because='CLIENT_INTERRUPT'` no da un número con
sentido across compromisos, el enum está contaminado.

**G2 · Gate en CI, grep-able.** Ningún valor de `because` puede contener como substring el nombre
de un compromiso ni de una etapa. Es comprobable mecánicamente contra los dos catálogos:

```python
for value in Because:
    assert not any(c in value for c in COMMITMENT_NAMES | STAGE_NAMES)
assert len(Because) <= 12    # presupuesto de cardinalidad
```

El presupuesto de cardinalidad es el hermano de A4 (§9.5): sin número, la deriva no tiene freno.
`because` describe **motivos de control**, que son pocos y cerrados — del mismo orden que los
veredictos, no de su producto cartesiano.

#### La forma completa: el rastro de ejecución conversacional

Propuesta del PO, y es el equivalente conversacional de un plan de ejecución:

```python
TurnDecision(
    # ── identidad ────────────────────────────────────────────────
    id, conversation_id, turn,
    # ── ORÁCULO · determinista, sobre esto SÍ se afirma en tests ─
    verdict,            # enum cerrado (5)
    because,            # enum cerrado, ortogonal (G1/G2)
    active_commitment,  # coordenada
    return_to,          # coordenada — la dirección de retorno (§10.4)
    supplanted_by,      # coordenada — qué tomó el frente
    facts_consumed,     # qué hechos leyó para decidir
    facts_produced,     # qué hechos dejó
    # ── DIAGNÓSTICO · variable, sobre esto NUNCA se afirma ───────
    planner_used, tools_called, duration_ms,
)
```

**Tres invariantes que lo mantienen sano:**

**(i) La frontera oráculo/diagnóstico es load-bearing.** Los campos de decisión son deterministas
(el árbitro es puro, A2) y por eso son un oráculo de test válido. `duration_ms` y `tools_called`
no lo son. Sin marcar la línea, alguien escribe una regresión que afirma sobre `duration_ms` y la
suite se vuelve inestable — y una suite inestable se apaga.

**(ii) Escritura pura: el runtime JAMÁS lee el rastro.** El PO ya lo dijo ("no para que el runtime
dependa de ello") y conviene elevarlo a invariante: si la lógica del turno lo lee, el rastro se
vuelve una segunda fuente de verdad y **viola R7**. Append-only, como `Payment` y `VitalSigns`.

**(iii) R12 y A2 son la misma decisión vista de dos lados.** Un árbitro impuro produce un rastro
irreproducible; un rastro que se quiere reproducible obliga a que el árbitro sea puro. Se
sostienen mutuamente.

#### Lo que el rastro convierte en una consulta

**Regresión por secuencia de decisiones, no por texto.** En un sistema con LLM el texto generado
es no determinista: **nunca se puede afirmar sobre él.** La secuencia de veredictos sí. R12 es la
única superficie afirmable que tiene este sistema, y hoy no existe.

Y algo que el PO no nombró y que cae solo de `facts_consumed` / `facts_produced`:

> **`facts_produced` que nunca aparecen en un `facts_consumed` posterior = CR-2, detectado por
> `SELECT`.**

CR-2 es "el router captura hechos y nadie los consume". En la conv 13, `identity_triage_done =
'returning'` se **produjo** y jamás se **consumió** — ni por el modelo (nunca se publicó) ni por
el router (lo sobrescribió). Con el rastro, un reporte de hechos huérfanos lo habría marcado
**antes del piloto**, sin que nadie leyera una conversación.

Eso convierte la fragmentación de estado de opinión arquitectónica en **métrica**.

#### `consumed` no basta: hace falta `justified`

Observación del PO, y cierra un hueco real: **consumir un hecho no significa haberlo usado.**

```
facts_consumed: identity=returning
      ↓ affected
verdict = continuar
      ↓ because
already_verified
```

Con eso el rastro responde dos preguntas distintas, no una: *¿qué hechos quedaron huérfanos?* y
**¿qué hechos influyeron de verdad en una decisión?**

**El riesgo que el PO nombra —y que es el correcto— es que `facts_consumed` degenere en
coverage.** Y como todo coverage, se infla: declarar `consumed: [identity, pet, owner, date,
time]` cuando solo `identity` movió el veredicto. Su taxonomía de tres niveles resuelve el qué:

| Nivel | Significado |
|---|---|
| **visible** | el hecho estaba disponible en el struct |
| **consultado** | el código lo leyó |
| **determinante** | **sin él, el veredicto habría sido otro** |

Solo el tercero explica decisiones. Falta el cómo — y aquí está la pieza:

> **`determinante` se DERIVA, nunca se declara.** Si lo reporta quien decide, es coverage y se
> inflará. Si se computa, la inflación es imposible.

Y se puede computar porque el árbitro es **puro** (A2) y **pequeño** (A1/A4): por ablación.

```python
determinante = {f for f in consultado if arbiter(facts - f) != arbiter(facts)}
```

Con ≤12 hechos, son ≤12 reevaluaciones de una función pura: microsegundos. Los tres niveles
quedan mecánicos, **con cero anotación humana**:

| Nivel | Cómo se obtiene |
|---|---|
| visible | claves del struct |
| consultado | proxy que registra los accesos al struct |
| determinante | ablación contra el árbitro puro |

Es el **tercer beneficio de A2**, después de la testabilidad y del rastro reproducible: la pureza
es lo que hace derivable la atribución causal. Sin ella, `determinante` sería una declaración de
buena fe — es decir, coverage.

#### El embudo de compromisos

Segunda propuesta del PO: `commitment_created → progressed → completed`. Detecta otra clase de
huérfano — *1000 creados, 150 completados: algo está muy mal*.

Con una condición para que el embudo no mienta: **los terminales deben PARTICIONAR** los creados.
Si no, 1000→150 es indistinguible de un sistema sano donde 800 se suplantaron y se retomaron
luego. Y cada terminal apunta a un dueño distinto:

| Terminal | Qué mide | Dueño |
|---|---|---|
| `completado` | valor entregado | — |
| `abandonado` | el cliente se fue (mirar en qué **etapa**) | producto |
| `bloqueado` | el dominio no puede cumplirlo | **PO — es R6** |
| `suplantado sin retomar` | lo desplazamos y nunca lo ofrecimos de vuelta | **ingeniería — viola R4** |
| `handoff` | tasa de escalada | ambos |
| `expirado` | eficacia del nudge | producto |

`suplantado sin retomar` es lo más valioso de la tabla: **una violación de R4 contable**, hoy
inmedible.

Y el poder real del embudo es el **corte por etapa**: "el 60 % de los compromisos de identidad
muere en `digits`" es un grito. La conv 13 no es un caso aislado — es una etapa con un acantilado,
y con este corte se habría visto en días sin que nadie leyera una conversación.

#### R13, mecánica

R13 (§11.1) mantiene pequeño el modelo de hechos. Se comprueba con **dos** gates, y confundirlos
sería un error:

**Estático (gate de CI, vinculante).** Un hecho que **ninguna fila** de la tabla del árbitro
referencia no puede cambiar ninguna decisión: es código muerto.

```python
for fact in FACTS:
    assert any(fact in row.reads for row in ARBITER_TABLE)   # si no, se borra
```

**Estadístico (reporte, NO gate).** Un hecho referenciado pero nunca `determinante` en 30 días
merece revisión, no borrado automático. `is_blocked` puede ser determinante el 0.01 % de los
turnos y aun así ser irrenunciable. **Un gate estadístico borraría la salvaguarda.**

La misma maquinaria de ablación produce el reporte de hechos muertos: un mecanismo, tres usos
(atribución causal, huérfanos, hechos muertos).

### 11.3 · Exigibilidad — que no sea un póster

Cada regla necesita saber **cómo se comprueba**, o es decoración:

| Regla | Cómo se comprueba | Necesita antes |
|---|---|---|
| R1 | test determinista sobre `policy.evaluate` (es pura) | nada — **Fase 0** |
| R2 | guard conversacional: contradicción vs. hecho anclado | P1 (estado publicado) |
| R3 | invariante en el árbitro: `slot ∈ ya_tengo` ⇒ no se pide | §10 compromisos |
| R4 | test: desviar → responder → mismo paso y misma pregunta | dirección de retorno (§10.4) |
| R5 | grep-gate: cero `flow.pop` de un compromiso + constraint de estado | §10 compromisos |
| R6 | **revisión de diseño**, no automatizable. Todo `client_error` que solo se puede explicar hablando del sistema abre un ticket de producto | — |
| R7 | un solo modelo de compromiso; se comprueba por ausencia de los otros cuatro | §10 |
| R8 | test: factor correcto tardío resuelve el compromiso suspendido | §10 + P3 |
| R9 | `Factor` sin `why` no compila (§9.5); hasta entonces, revisión de copy | §10 compromisos |
| R10 | guard conversacional: 3ª repetición del mismo slot = violación | P8 |
| R11 | `author_type` en el historial + test de que el modelo no hereda voz del router | P6 |
| R12 | fila `TurnDecision` por turno; test de que ningún camino sale sin dejarla | **nada** — ver abajo |
| R12·orto | G1 ortogonalidad + G2 gate CI (`because` sin nombres de compromiso/etapa; `len ≤ 12`) | nada |
| R12·causal | `determinante` por ablación, no declarado | árbitro puro (A2) |
| R13 | gate **estático**: todo hecho leído por ≥1 fila del árbitro | árbitro tabular (A3) |

Solo **R6 queda como revisión humana**, y está bien: es un gate de producto, más barato que
cualquier código. R9 empezó ahí y §9.5 la vuelve verificable en compilación. Las otras diez son
testeables, y dos se pueden cerrar **ya**:

- **R1** — `policy.evaluate` es pura, no necesita proveedor.
- **R12** — **no necesita al árbitro.** Los 22 puntos de salida desembocan todos en el `return`
  de `handle_inbound` (los 4 directos y los 2 que delegan a `_run_planner` / `_commit_pending`).
  Un envoltorio en esa única frontera persiste hoy `verdict = result['decision']` y da la
  observabilidad que falta, antes de mover una sola línea de arquitectura. Es el hallazgo que
  convierte R12 de dependencia de Fase 3 en victoria de Fase 1.

---

## 12. Propuesta de arquitectura

Ocho principios. Ninguno es "agrega una excepción al prompt". **P2 queda subsumido por el
árbitro del turno (§9)**: lo que ahí describí como un clasificador es en realidad un *insumo*
de la autoridad, no la autoridad misma.

### P1 · Un solo estado conversacional, publicado íntegro

Hoy hay tres memorias (`flow`, `ConversationGoal`, `Message[:12]`). Principio:

> **Todo hecho que el sistema decide deterministamente se publica al modelo como
> dato; todo hecho que el modelo aprende se puede persistir en estado durable.**

Concreto: una proyección `ConversationState` armada una vez por turno, que reemplace
el `context` ad-hoc de `assemble_messages` y contenga:

- identidad: nivel, titular declarado, mascotas mencionadas, reto en curso y su etapa
- hechos aportados por el cliente (no solo los que cupieron en args de tool)
- preguntas ya hechas y cuántas veces
- interacción activa (reto / confirmación / objetivo) y su motivo

El modelo **nunca autoriza** desde ahí (la seguridad no cambia: `run_tool` revalida
tier/verificación/ownership). Solo puede **narrar** desde ahí.

Se publica en lenguaje semántico, no con claves internas: `"el cliente dice que ya es
cliente"`, no `"identity_triage_done": "returning"`.

### P2 · Arbitraje del turno antes de avanzar estado

Insertar una etapa que hoy no existe entre "hay una interacción en curso" y "el
mensaje la responde". Dos ejes independientes por mensaje entrante:

```
              ¿responde la interacción activa?   ¿trae una petición propia?
"4586"                    sí                              no          → avanzar
"para que necesitas eso"  no                              sí          → responder, NO penalizar
"es 4586, para que?"      sí                              sí          → avanzar + responder
"mmm"                     no                              no          → aclarar, NO penalizar
```

Lo esencial: el clasificador del eje A **ya existe y es determinista**
(`owner_digits_match`, `owner_has_pet`, `classify_client_triage`). Lo que falta es su
**rama negativa**: hoy "no coincide" y "no es una respuesta" son el mismo camino.

Versión mínima y barata: un predicado `is_answer_shaped(stage, text)` por factor.
Para dígitos: `re.search(r'\d{4}', text)`. "para que necesitas eso" no tiene 4
dígitos → **no es una respuesta** → no puede contar como fallo. Ese único predicado
habría salvado la conv 13 completa.

### P3 · La interacción es un objeto con suspender/reanudar, no una clave de dict

`flow['family_challenge']` pasa a ser una entidad con ciclo de vida explícito
(`kind`, `stage`, `factors_given`, `asks`, `fails`, `suspended_at`).

- Escalar la **suspende**, no la destruye.
- `release_conversation` la reanuda y resuelve el `HumanHandoff`.
- Una respuesta correcta posterior la resuelve aunque llegue tarde (el `4586` de conv 13).
- `staff_verified` la cancela (el humano ya validó; no se re-interroga).

### P4 · Separar capacidad de intención

El catálogo de objetivos deja de ser el catálogo de tools. Un objetivo puede quedar
**insatisfacible**: `blocked_reason` seteado ⇒ el sistema **deja de pedir slots**, lo
dice una vez con honestidad y ofrece la alternativa real.

Requiere una decisión de producto (¿existe alta sin cita?) — no la tomo aquí.

### P5 · La repetición es un defecto del sistema, no del cliente

`asked[slot] >= 2` debe cambiar **conducta**, no solo aparecer en DATOS:

- 2 preguntas → el sistema reconoce la repetición explícitamente y **cambia de
  estrategia** (reformula, o toma el dato de otra fuente).
- 3 → escala con el slot **nombrado** en `reason_detail`.
- Y el contador de estancamiento **no incrementa** en turnos donde el cliente
  preguntó algo: eso es interés, no atasco.

### P6 · Atribuir la autoría de los salientes

`Message.author_type` ya existe (`AUTHOR_SYSTEM` / agente / staff) y
`assemble_messages` lo ignora. Usarlo: las plantillas del router se etiquetan como
tales, las del humano como colega. El modelo deja de heredar la voz del router y de
disculparse por actos ajenos.

### P7 · Ventana por turnos y por relevancia, no por conteo de mensajes

- Contar **turnos** (ráfagas ya agrupadas), no mensajes. En un canal de ráfagas, 12
  mensajes es un bug.
- El bloque de estado de P1 va **anclado siempre**: salir de la ventana hace perder
  el fraseo, nunca el hecho.

Así la ventana degrada suavemente en vez de amputar.

### P8 · Guards conversacionales, simétricos a los de contenido

Mismo mecanismo que `guards.check_output` (un reintento correctivo, luego plantilla),
aplicado a conducta:

- misma pregunta 3 veces
- contradicción de un hecho anclado ("no me lo dijiste" cuando el estado dice que sí)
- éxito afirmado sin tool ejecutada en el turno (**BUG-AGENT-001**, ya abierto)

Y extenderlos al camino tier-0: hoy los fallos del router no se validan ni se loguean.

---

## 13. Riesgos de cada propuesta

| # | Riesgo | Mitigación |
|---|---|---|
| P1 | Más superficie de prompt injection y de fuga G7 (el modelo citando claves internas) | publicar semántica en español, no claves; los guards de jerga ya bloquean `flow`/`public_id` |
| P1 | El modelo "razona" sobre identidad y se auto-autoriza | invariante intacto: `run_tool` revalida; el estado es narrativo, no autorizante |
| P2 | Falso negativo: una respuesta con forma de pregunta ("¿es 4586?") se lee como interrupción | `is_answer_shaped` permisivo (busca la forma en cualquier parte); la rama pregunta solo si **no** hay forma de respuesta |
| P2 | Un atacante evita el reto formulando todo como pregunta | no avanza el reto ⇒ **nunca se verifica** ⇒ no obtiene acceso; solo evita el contador de fallos. Añadir tope de turnos sin avance (≠ fallos) |
| P3 | Reanudar un reto que el humano ya resolvió → re-interrogar a un cliente validado | `staff_verified` cancela la interacción suspendida |
| P3 | Reto suspendido eterno | TTL (el patrón de 30 min de `pending_action` ya existe) |
| P4 | Requiere decisión de producto; mal implementado, el agente se rinde antes de tiempo | `blocked_reason` solo lo setea el dominio, nunca el modelo |
| P5 | Abandonar un slot genuinamente obligatorio | cambia la **estrategia**, no el requisito |
| P6 | Cambiar roles del historial puede alterar el estilo del modelo | cambio de etiqueta, no de contenido; medir `tasa_repregunta` antes/después |
| P7 | Más tokens (conv 13 ya en ~3.8k de entrada) | agrupar ráfagas probablemente **baja** el conteo; el bloque anclado es pequeño |
| P8 | Falsos positivos escalan conversaciones sanas | `SOFT` (log + reintento) antes que `HARD`; empezar solo en modo observación |
| **Árbitro** | **Se convierte en un segundo planner: 500 líneas de excepciones y prioridades. Solo se movió la complejidad.** Precedente real: `policy.evaluate` → 203 líneas, 20 pasos, 6 encajados a presión | A1-A5 de §9.5, y **A4 (presupuesto de ramas con test en CI) es la única no negociable** — sin ella las otras cuatro son recomendaciones |
| **Árbitro** | Empieza a decidir contenido ("pregunta esto") y absorbe al planner | principio contenido/control (§9.5): prueba de renderizado en otro idioma/tono/canal sin tocarlo |
| **R12** | Una fila por turno crece sin control, o se cuela PII | mismo orden que `LLMCall` (ya aceptado); `because` enum y cero cuerpos de mensaje — el texto vive en `Message` por FK |
| **R12** | `because` degenera en prosa libre y deja de agregarse | enum cerrado; un valor nuevo se añade con el hecho que lo produce, en la capa de matchers |
| **R12** | **`because` absorbe el contexto y explota (`CLIENT_ASKED_WHILE_IDENTITY_AFTER_DIGITS`). Se movió el problema de sitio.** Precedente: `reason_code='identity_ambiguous'` **mintió** en la conv 13 y `reason_detail='family:failed_digits'` son coordenadas en un string | G1 (prueba de ortogonalidad) + G2 (gate CI: ningún `because` contiene nombre de compromiso o etapa; `len(Because) <= 12`) — §11.2 |
| **R12** | Alguien afirma sobre `duration_ms` en una regresión y la suite se vuelve inestable | frontera oráculo/diagnóstico explícita en el modelo; una suite inestable se apaga y R12 se pierde |
| **R12** | El runtime empieza a **leer** el rastro → segunda fuente de verdad, viola R7 | append-only, escritura pura, como `Payment`/`VitalSigns` |
| **R12** | **`facts_consumed` degenera en coverage y se infla**: se declaran 5 hechos cuando solo 1 movió el veredicto | `determinante` se **deriva por ablación** contra el árbitro puro, nunca se declara. Cero anotación humana ⇒ inflación imposible (§11.2) |
| **R12** | El embudo de compromisos miente (1000→150 parece roto y quizá está sano) | los terminales **particionan** los creados; cada uno con dueño (§11.2) |
| **R13** | Un gate **estadístico** de hechos muertos borra una salvaguarda rara (`is_blocked`: determinante el 0.01 % de turnos) | el gate vinculante es **estático** (¿alguna fila del árbitro lo lee?); lo estadístico es reporte, no gate |
| **R13** | Se aplica con tanto celo que hechos legítimos acaban solo en el historial y reaparece CR-2 | la prueba es *"¿puede cambiar una decisión?"*, no *"¿la cambió?"*; el gate estático la implementa literalmente |

---

## 14. Plan incremental

Ordenado por (daño que ocurre hoy) × (costo). Cada fase indica **qué regla de §11 satisface** —
así se sabe cuándo está terminada sin discutir.

| Fase | Entrega | Reglas que cierra |
|---|---|---|
| 0 | no penalizar no-respuestas | **R1** |
| 1 | suspender en vez de destruir; hechos anclados; **`TurnDecision`** | **R5**, **R8**, **R12**, R2 (parcial) |
| 2 | autoría + ventana por turnos | **R11**, R2 |
| 3 | árbitro del turno + compromisos unificados | **R3**, **R4**, **R7**, R9 (estructural) |
| 4 | guards conversacionales | **R10**, R2 (cierra) |
| 5 | alta sin cita (producto) | **R6** |
| — | revisión de copy: todo *ask* con su motivo | **R9** (hoy, sin código) |

Dos cierres baratos que no dependen de nada:

- **R9 esta semana, sin código**: añadir el motivo a las plantillas que piden un dato.
  `T0_TRIAGE_DIGITS` es el caso testigo. En Fase 3 se endurece a `Factor.why` (§9.5).
- **R12 en Fase 1, sin el árbitro**: un envoltorio en el `return` de `handle_inbound` — la única
  frontera por donde salen las 22 decisiones. Conviene hacerlo **antes** de Fase 3: la
  arquitectura grande se mide contra el comportamiento de hoy, y sin `TurnDecision` esa
  comparación vuelve a ser manual.

### Fase 0 — desbloquear el caso conv 13 · bug, no arquitectura

1. `is_answer_shaped(stage, text)` en los 3 estados de reto: un mensaje sin forma de
   respuesta **no** suma `fails`.
2. Rama de pregunta: contestar el *por qué* del factor y repetir la petición.
3. No sobrescribir un `identity_triage_done` ya decidido con `'unclear'`.
4. `time` capturado desde `find_available_slots` como ya se hace con `date`.

Testeable sin proveedor (`policy.evaluate` es pura). Tests de regresión: la conv 13
completa como caso.

### Fase 1 — no perder progreso

1. Suspender en vez de destruir (P3, versión mínima: no hacer `pop` al escalar).
2. `release_conversation` resuelve el handoff y reanuda lo suspendido.
3. Anclar hechos de identidad en DATOS (P1 mínimo): cliente declarado, titular
   declarado, mascota mencionada.
4. **`TurnDecision` persistido** (R12) como envoltorio del `return` de `handle_inbound`, sin
   árbitro todavía: `verdict` = el `decision` actual, `because` enum ortogonal, cero PII. Da la
   línea base contra la que se medirá Fase 3.
   - Con **G1/G2 desde el primer commit** (§11.2). El enum contaminado es barato de crear y muy
     caro de deshacer: `reason_code='identity_ambiguous'` sigue mintiendo en producción.
   - `facts_consumed` / `facts_produced` desde el día 1, aunque al principio queden casi vacíos:
     es lo que habilita el reporte de **hechos huérfanos** (detector de CR-2) sin leer una sola
     conversación.
   - Aprovechar el paso para arreglar `reason_code` → `identity` + coordenadas aparte.

### Fase 2 — que el modelo vea la verdad

1. Autoría de salientes (P6).
2. Ventana por turnos + bloque anclado (P7).
3. `_after_hours_prefix` con criterio de oportunidad (no en medio de una queja).

### Fase 3 — el mecanismo general · la fase de arquitectura real

1. **Árbitro del turno** (§9.3): única autoridad, un veredicto, un registro. Sustituye el
   predicado de Fase 0 por la decisión de verdad, y absorbe las 22 salidas en una.
   **Se entrega con los cinco mecanismos A1-A5 de §9.5 desde el primer commit**, no después:
   enum cerrado, función pura, hechos de entrada, presupuesto de ramas con test, cero
   precedencia. Sin A4 en CI, el árbitro es `policy.evaluate` otra vez en seis meses.
2. **Compromisos unificados** (§10): los cinco mecanismos de §10.2 pasan a un solo modelo con
   ciclo de vida explícito, **dirección de retorno** y `Factor.why` (endurece R9).
3. Demotar las tools a autoridad cero (§9.4b): `reply_text` y `needs_confirmation` salen del
   contrato de `ToolOutcome`.
4. `ConversationState` como proyección única (P1 completo).

### Fase 4 — calidad como invariante

1. Repetición-como-defecto (P5).
2. Guards conversacionales (P8), incluido BUG-AGENT-001.

### Fase 5 — producto

1. Capacidad ≠ intención (P4). Bloqueada por la decisión de alta sin cita.

---

## 15. Lo que está bien y no hay que tocar

Para que el plan no destruya lo que funciona:

- **`pending_action` de tier-2.** Sobrevive interrupciones, distingue 4 veredictos, y
  las falsas afirmativas no ejecutan ni cierran. Es el modelo a imitar en los retos.
- **`guards.py` como capa vinculante.** El principio "una regla en el prompt es
  advisoria, en código es vinculante" es correcto. El problema es su *cobertura*, no
  su diseño.
- **Los mensajes del staff como `assistant`.** Evita que el agente contradiga a su
  compañero.
- **El prompt v7.** El tono, los ejemplos y la reescritura de prohibiciones a conducta
  funcionan; el modelo intentó recuperarse solo tres veces en conv 13.
- **Errores suaves que no escalan** (`_soft_error_hint`). Correcto: solo un
  `tool_failure` real rebota a un humano.
- **La urgencia por delante de todo.** Ninguna propuesta debe moverla del paso 3.
- **El objetivo persistido.** `ConversationGoal` es la pieza que hay que *extender* a
  identidad, no reemplazar.

---

## 16. Anexo · evidencia

| Fuente | Referencia |
|---|---|
| conv 13 | `85a2a691-3c4e-4f00-9dc8-5dc3a228adf6`, org 3, 2026-07-30 02:08–02:14 UTC, 5 llamadas LLM (`reception-f3-v7`), **0 ToolExecution** |
| conv 12 | `0d56b976-1d03-4582-9e65-2db57c5d3d3f`, 2026-07-28 21:16–21:28, goal 2 `register_and_schedule` `missing=['date','time']` `asked={'date':4,'time':4,'reason':2}` `stall_turns=0` |
| Identidad real | `Owner` 36518 `Ana Cruz` (tel …4586) → `Pet` 59318 `Oliver` |
| Handoff | 14, `identity_ambiguous`, `family:failed_digits`, `resolved_at=None` con `state=active` |
| Ventana | simulación de `assemble_messages` sobre el turno de 02:13:39: 20 mensajes previos, 12 en ventana, los 3 hechos centrales fuera |
