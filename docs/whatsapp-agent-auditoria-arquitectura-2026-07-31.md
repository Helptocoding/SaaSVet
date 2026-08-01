# Auditoría de arquitectura conversacional — ¿agente o workflow?

**Fecha**: 2026-07-31
**Alcance**: `apps/agent` completo en `develop` (post É-F4 Fases 0-4, `50fbc8c`)
**Encargo**: determinar si la arquitectura empuja al agente a comportarse como un formulario conversacional en lugar de como una persona que conversa. Diagnóstico, no propuesta de implementación.
**Método**: lectura del runtime completo + reconstrucción forense, línea por línea de código, de la conversación aportada en el brief.

> Auditorías previas: [conversacional 2026-07-24](whatsapp-agent-auditoria-conversacional-2026-07-24.md) · [rigidez 2026-07-29](whatsapp-agent-auditoria-rigidez-2026-07-29.md)
> Contratos vigentes: [ADR p54](decisions/2026-07-25-p54-agent-goals-and-binding-rules.md) · [ADR p55](decisions/2026-07-30-p55-turn-authority-and-commitments.md) · [`modules/agent.md`](modules/agent.md)

**Revisión del PO, 2026-07-31.** Cinco correcciones que reencuadran el documento y
que están incorporadas al texto:

1. **FSM de negocio ≠ FSM de conversación.** Lo que sobra es usar una máquina de
   estados para decidir cada frase; los estados de confirmar/cancelar/cobrar/cambiar
   titular son irrenunciables. Verificado: **ya están del otro lado de la frontera**
   (§2.7).
2. **El router no desaparece: encoge.** Urgencia → bloqueado → humano activo →
   opt-out → planner. La lista correcta es un poco más larga y una de las adiciones
   no es negociable (§2.6).
3. **«Todo por el LLM» no es la conclusión.** Que las reglas importantes no dependan
   del modelo es el activo del sistema. La distinción útil no es prompt-vs-código
   sino **preempción vs. contención** (§2.6).
4. **La tesis, en una frase** — del PO, mejor que cualquier párrafo de la v1:
   *el sistema fue diseñado para verificar que el usuario siga el flujo, no para
   entender al usuario*. Comprobada al nivel de los tipos (§2.4).
5. **Causa raíz que faltaba: modo pull.** El sistema siempre persigue el siguiente
   dato; una conversación humana funciona en push. Es upstream de casi todo lo demás
   (§2.5).

El §8 pasa a ser el **experimento acotado** que propuso el PO, no una reestructuración.

---

## 0. Veredicto

**Sí, el problema es estructural. Y no es el que las dos auditorías anteriores diagnosticaron.**

Aquellas concluyeron *fragmentación de estado* (2026-07-24) y *ausencia de autoridad
del turno* (2026-07-29). Ambos diagnósticos eran correctos, las correcciones son
buenas, y el código que salió de ellas está mejor que el que había. Pero las dos
miraron el problema desde dentro del reparto de autoridad ya existente y preguntaron
*quién manda*. Ninguna preguntó lo anterior: **cuánta conversación llega siquiera a
la capa que conversa.**

La respuesta, medida en el código:

> **La conversación del brief no pasó por el LLM ni una sola vez.**
> Los cinco mensajes del agente son cinco constantes de texto de `tier0.py`,
> emitidas por `policy.evaluate`. `llm_calls = 0` en los cinco turnos.

No es "el agente se comporta como un formulario". **Es un formulario.** En esa
conversación no había ningún agente: había una máquina de estados de 36 salidas
respondiendo con literales, y un LLM al que nunca se le preguntó nada.

Todo lo demás de esta auditoría se deriva de ahí. La rigidez que el PO percibe no
viene del prompt, ni del Commitment Engine, ni de la FSM siendo demasiado estricta:
viene de que **la arquitectura le da al modelo las conversaciones fáciles y a la FSM
las difíciles**, que es exactamente al revés de donde el valor de cada uno está.

Comprimido en una frase (formulación del PO, y es mejor que el párrafo anterior):

> **El sistema fue diseñado para verificar que el usuario siga el flujo, no para
> entender al usuario.**

La arquitectura pregunta *«¿qué transición ejecuto?»* cuando debería preguntar
*«¿qué acaba de intentar comunicarme el usuario?»* y decidir **después**. No es una
metáfora: se comprueba en la firma de las funciones (§2.4).

---

## 1. Evidencia — reconstrucción forense del brief

Ruta de código exacta de cada turno. El cliente escribe en ráfagas (el worker las
agrupa, `worker.py:167-171`), así que dos mensajes seguidos llegan como un solo
`burst`.

| # | Cliente escribió | Ruta de código | El agente respondió | LLM |
|---|---|---|---|---|
| 1 | `hola` + `quiero una cita para mi mascota` | `policy.py:244` paso 12b → `classify_client_triage` = `unclear` → `start_identity_triage` | `tier0.render_triage()` — literal | **0** |
| 2 | `ya he ido` + `mi nombre es Ana` | `policy.py:197` paso 8c → `_advance_identity_triage` → `classify_client_triage` = `returning` → `advance_to('titular')` | `tier0.T0_TRIAGE_TITULAR` — literal | **0** |
| 3 | `ya te dije` + `Ana` | `policy.py:454-455` → `_check_interruption` → `arbiter.decide(interrupts=True)` = `DEVIATE` | `T0_WHY_THEN_REASK.format(why='', …)` | **0** |
| 4 | `¿qué` | idéntico — `deviations = 2` | idéntico, carácter por carácter | **0** |
| 5 | `queeee` + `ese mensaje que` | idéntico — `deviations = 3` → `policy.py:365` `park_identity` + `ESCALATE` | `tier0.T0_CHALLENGE_FAILED` | **0** |

Los tres hallazgos que salen de esta tabla no son bugs de ajuste. Son consecuencias
necesarias del diseño.

### Hallazgo 1 — El dato pedido ya estaba en la ráfaga que lo precedió

Turno 2: el cliente escribe **`mi nombre es Ana`**. En el mismo `burst`.
`_advance_identity_triage` (`policy.py:461`) hace exactamente una cosa con ese texto:

```python
verdict = matchers.classify_client_triage(text)   # → 'returning'
```

`classify_client_triage` (`matchers.py:348`) busca lemas de tamiz —`ya he ido`,
`primera vez`— y **nada más**. No existe, en toda la ruta del router, ninguna función
que extraiga un nombre, una fecha, una mascota o cualquier otro dato de un mensaje
entrante. El sistema no tiene ojos para lo que el cliente aporta por su cuenta:
solo para lo que responde a la pregunta que él acaba de hacer.

Consecuencia: el agente pregunta **`¿A nombre de quién está el registro?`** cero coma
un segundo después de que el cliente dijera su nombre. No es un fallo de memoria —
el dato nunca fue percibido. Un formulario tampoco lee lo que escribiste en el campo
de al lado.

### Hallazgo 2 — «Te lo pido para 🙂»: la garantía R9 no cubre el caso que rompió

`T0_WHY_THEN_REASK = "Te lo pido para {why} 🙂\n\n{reask}"` (`tier0.py:195`), y el
`why` se resuelve así (`policy.py:372`):

```python
why=goals.why_for(commitment.name, factor)   # ('identity_triage', 'titular')
```

`IDENTITY_SPECS['identity_triage']` (`goals.py:273-281`) declara **un solo factor:
`client_kind`**. `'titular'` no está. `why_for` devuelve `''`. El cliente recibe,
literalmente, `Te lo pido para  🙂`.

Esto merece detenerse, porque es el hallazgo más revelador de toda la auditoría:

- **R9 es la regla mejor defendida del sistema.** `Factor.__post_init__`
  (`goals.py:131`) *levanta `ValueError`* si falta el `why`. El ADR p55 §5 la llama
  «estructural, no documentación». El docstring dice: *«Un `Factor` sin `why` **no
  compila** — literalmente»*.
- **Y aun así produjo un mensaje vacío en producción, dos veces seguidas.** Porque la
  etapa que el FSM estaba pidiendo (`return_to = 'titular'`, escrita en
  `policy.py:465`) **no es un `Factor` declarado**. `return_to` es un
  `CharField(max_length=32)` libre (`models.py:236`). Nadie comprueba que el valor que
  la FSM escribe ahí exista en el catálogo de factores del compromiso.
- **El gate lo confirma en vez de atraparlo.** `WhyVoiceTests`
  (`tests/test_w2_goals.py:327`) itera `goals.GOAL_SPECS` — **nunca `IDENTITY_SPECS`**.
  Y `test_policy.py:498` afirma sobre `why_for(FAMILY, 'digits')`, que sí es un factor
  declarado. El único caso probado es el que funciona.

La lección no es «falta un test». Es que **una garantía se declaró estructural y se
implementó sobre una tabla, mientras la máquina de estados sigue operando sobre
strings de otra tabla**. Hay cinco vocabularios paralelos para el concepto «el dato
que estoy pidiendo ahora mismo» (§3, E3) y ninguno se verifica contra los otros.

### Hallazgo 3 — «Ya te dije» está clasificado como pregunta, y responder no cuenta como responder

`policy._is_interruption` (`policy.py:324`):

```python
if not matchers.looks_like_question(text):
    return False
return matchers.is_answer_shaped(stage, text) is not True
```

Dos hechos duros:

1. `_QUESTION_LEMMAS` (`matchers.py:279`) contiene literalmente **`'ya te dije'`,
   `'que te dije'`, `'no te acuerdas'`, `'se te borro'`**. Es decir: *el reclamo del
   cliente por repetición está modelado como una interrupción*, no como una señal de
   que el sistema falló.
2. `is_answer_shaped` (`matchers.py:336`) solo conoce **una** forma verificable:
   `digits`. Para `titular`, `pet`, `owner` y `client_kind` devuelve `None`, y
   `None is not True` → `True`.

Combinados: **en cuatro de las cinco etapas de identidad, cualquier mensaje que
contenga `?`, `¿` o uno de 26 lemas es una interrupción, aunque traiga la respuesta
correcta en la misma línea.** `ya te dije\nAna` contiene el nombre. El sistema no
puede verlo, por construcción, no por probabilidad.

Y la respuesta a la interrupción es **repetir el mismo template, carácter por
carácter**. El bucle de los turnos 3 y 4 no es un caso raro: es el **punto fijo** de
la función de transición. Un cliente que se queja de que le repiten recibe la
repetición exacta que motivó la queja.

### Hallazgo 4 — El mensaje de cierre miente

Tras tres desvíos, `T0_CHALLENGE_FAILED`: *«No logro validar tus datos por aquí»*.
**Nada se validó ni falló.** El cliente nunca dio un dato equivocado: dio el correcto
y preguntó por qué. `attempts_failed` sigue en 0 (`register_failure` no se llama en
esta rama, `policy.py:360-369`); lo que se agotó fue `deviations`.

El equipo ya diagnosticó exactamente esta clase de mentira en el `reason_code`
(`models.py:390-397`: *«`identity_ambiguous` mintió en producción»*) y la corrigió
renombrando el enum. **Pero el texto que ve el cliente sigue mintiendo**, y es el
único de los dos que un cliente lee. La corrección se aplicó a la telemetría, no a
la conversación.

---

## 2. Diagnóstico general

### 2.1 El reparto está invertido

El sistema tiene dos motores y los aplica al revés de donde cada uno vale.

| | Determinismo (FSM/templates) | LLM |
|---|---|---|
| **Vale mucho cuando** | el costo de equivocarse es alto e irreversible: escribir una cita, mover dinero, dar una dosis, revelar datos de otro cliente | el costo de equivocarse es bajo pero el costo de la rigidez es altísimo: entender una frase ambigua, reconocer frustración, explicar un porqué, retomar un hilo |
| **Hoy gobierna** | identidad, tamiz, retos, meta-conversación, quejas, interrupciones, primer contacto — **toda la parte emocionalmente delicada** | proponer horarios, rellenar 4 slots, redactar la frase de una cita — **la parte transaccional** |

El resultado es un sistema que es **rígido justo donde necesita ser humano** y
**libre justo donde necesita ser estricto**. La barrera que sí protege lo caro —
`pending_action` con args staged, ejecutados verbatim, nunca regenerados
(`confirmations.py`, TC-SEC-03) — es excelente y no está en discusión. Lo que está mal
es haber extendido ese mismo instinto de control a la parte de la conversación donde
no hay nada que proteger: *nadie pierde dinero porque el agente entienda «Ana» de una
forma ligeramente distinta a la esperada.*

### 2.2 Los números del reparto

| Medida | Valor | Dónde |
|---|---|---|
| Puntos de decisión en el router | **36** | `policy.py` |
| …que terminan el turno **sin LLM** | **28** (18 `REPLY` + 6 `ESCALATE` + 1 `CLOSE` + 3 `SILENT`) | idem |
| …que ceden al planner | **8** | idem |
| Constantes de texto al cliente en `tier0.py` | **31** | `tier0.py` |
| `enqueue_outbound` en `planner.py` | **22** | `planner.py` |
| …que salen como `author='system'` | **20** (19 explícitos + `:395` por default) | idem |
| …que salen como `author='agent'` | **2** (`:330` y `:387`) | idem |
| …que llevan texto **redactado por el modelo** | **1** (`:330`) — `:387` es el parafraseo tier-2, plantilla | `confirmations.py:21-34` |
| Salidas de turno en `planner.py` | 23 | idem |

**Veintiuno de los veintidós mensajes que emite el "planner" son plantillas.** El
módulo que en el diagrama de arquitectura representa la capa conversacional es, en
volumen de código y de salidas, un despachador de literales con un LLM adjunto.

### 2.3 La memoria tiene un solo puerto de escritura, y está del lado equivocado

Esta es la causa raíz de la que cuelgan casi todos los síntomas.

Los hechos entran a la memoria del sistema por **una sola función**: `goals.capture`
(`goals.py:645`). Sus únicos dos call sites de producción están en `tools.py:609` y
`tools.py:725`. Es decir, un dato del cliente se convierte en estado persistido
**solo si**:

1. el router cede al planner, **y**
2. el modelo decide llamar a una tool de escritura, **y**
3. mete el dato en los argumentos de esa llamada.

Si cualquiera de las tres falla —y en la conversación del brief falló la primera, en
los cinco turnos— **el dato no existe para el sistema.** Nunca existió.

Corolario incómodo: el `ConversationGoal`, la tabla que el proyecto construyó
explícitamente para ser la memoria conversacional (ADR p54), **no puede recordar nada
que el LLM no haya decidido escribir en una llamada a herramienta.** Es una memoria
cuyo puerto de escritura es un side-effect de otra cosa.

### 2.4 La tesis, comprobada al nivel de los tipos

*«Verificar que el usuario siga el flujo, no entender al usuario»* no es una lectura
interpretativa: se puede leer en las firmas de `matchers.py`, que es el único módulo
que toca el mensaje entrante antes de cualquier decisión.

| Función | Qué devuelve |
|---|---|
| `is_emergency`, `wants_human`, `wants_optout`, `is_bot_question`, `is_bare_greeting`, `is_thanks`, `wants_personal_action`, `looks_like_question`, `is_complaint_or_meta` | `bool` |
| `classify_confirmation` | `'affirmative' \| 'negative' \| 'defer' \| 'unclear'` |
| `classify_client_triage` | `'new' \| 'returning' \| 'unclear'` |
| `is_answer_shaped` | `True \| False \| None` |

`matchers.py` tiene **13 funciones públicas**. Una (`normalize`) devuelve texto y es
un helper de limpieza. **Las otras doce devuelven un booleano o un enum cerrado.
Ninguna devuelve un valor extraído del mensaje.** 368 líneas de análisis de lenguaje
que, por construcción, **no pueden emitir un dato**.

Esa es la tesis del PO expresada como tipo de retorno: la capa que lee al cliente
solo sabe contestar *«¿esto encaja con lo que yo esperaba?»*. Nunca *«¿qué me
dijo?»*. El Hallazgo 1 (el nombre «Ana» descartado) no es un extractor que falta:
es el único resultado posible de un módulo cuyo codominio son booleanos.

### 2.5 El sistema trabaja en modo *pull* — y tiene exactamente un contraejemplo

Aportación del PO, y es la causa que faltaba. El sistema opera así:

```
me falta `titular` → pregunto `titular` → espero `titular` → ¿llegó `titular`?
```

Una conversación humana opera al revés: el cliente suelta lo que quiere, en el orden
que quiere, y el receptor **guarda todo y luego revisa qué falta**. Push.

El modo pull está en el tipo de todos los mecanismos de memoria, no en su
implementación:

| Mecanismo | Qué registra | Modo |
|---|---|---|
| `goals.capture(goal, args)` | lo que el modelo puso en los args de la tool que **él** eligió llamar | pull |
| `missing_slots` → `me_falta` | lo que el sistema **va a pedir** | pull |
| `mark_asked(goal, state['missing'])` | cuántas veces **pedimos** algo | pull |
| `_capture_slot_from_read` | un slot proveniente de **otra tool**, no del cliente | pull |
| `metrics.tasa_repregunta` | derivada de `asked` — mide **peticiones**, no recepciones | pull |

No existe en todo el subsistema un contador, un campo ni una función para *«esto me
lo dijo el cliente sin que se lo pidiera»*. Por eso el nombre «Ana» no se perdió: **no
había dónde ponerlo.** E2 («la memoria tiene un solo puerto de escritura») era el
mecanismo; el modo pull es la razón por la que ese puerto tiene esa forma.

Y explica el punto ciego de E6: en modo pull, **repreguntar no es un defecto, es la
operación normal**. Por eso la métrica que debería cazarlo se calcula sobre `asked`,
que es precisamente el contador de la operación normal.

**El contraejemplo, y es el hallazgo más útil de esta revisión:**

```python
# policy.py:200-203 — paso 9, «verificación IMPLÍCITA pasiva»
if contact.verification_level == contact.VERIFICATION_PHONE_MATCH:
    identity.try_verify_by_pet_name(contact, burst_text)
```

Esto es **push puro**: el cliente nombró a su mascota sin que nadie se lo pidiera, el
sistema lo captó y subió el nivel de verificación. Es el único punto del código donde
un hecho no solicitado escribe estado.

Dos observaciones sobre él:

- **Es el único mecanismo del subsistema del que ninguna auditoría se ha quejado
  jamás.** Al contrario: `identity.py:11-13` lo describe como *«sube phone_match →
  confirmed_in_chat sin fricción»*, y es literalmente el modo en que se verifica sin
  que el cliente note que fue verificado.
- **Está apagado exactamente en el caso del brief.** Requiere `owner_id is not None`
  (`identity.py:126`). El contacto de la conversación auditada no tenía owner, así que
  el único mecanismo push del sistema estaba deshabilitado justo donde se necesitaba.

O sea: la prueba de que push funciona ya está dentro del propio sistema, es la
interacción mejor valorada del producto, y está confinada a una sola rama.

### 2.6 Preempción vs. contención — el criterio correcto para qué sigue siendo determinista

La preocupación del PO («las reglas importantes no dependen del modelo, eso no debe
perderse») es correcta y no está en discusión. Pero la distinción útil **no es**
«regla en código vs. regla en prompt». Es **dónde se hace cumplir**:

| | **Preempción** | **Contención** |
|---|---|---|
| Cómo | el router intercepta antes de que haya conversación | la conversación ocurre; el sistema limita lo que puede *causar* |
| Cuesta | humanidad — el modelo nunca ve el mensaje | nada conversacional |
| ¿Depende del modelo? | no | **tampoco** |
| Implementado hoy | 28 salidas de router, 31 plantillas | `_verification_ok` (`tools.py:111`), `guards.check_output`, args staged de tier-2 |

**Ambas columnas cumplen «la regla no depende del modelo». Solo una cobra humanidad
por ello.** El sistema usa preempción en casi todo, teniendo contención ya construida,
probada y funcionando en tres mecanismos.

Criterio que se deriva: **preempción solo donde la contención es imposible.** Y es
imposible únicamente cuando el daño ocurre *al decir*, no *al hacer* — cuando no hay
acción posterior que interceptar.

Aplicado, el router mínimo es el del PO más cuatro que también pasan el criterio:

| Paso | Por qué es preempción legítima |
|---|---|
| kill switch / demo | operativo, no conversacional. Con el agente apagado no debe haber turno |
| contacto bloqueado | no hay acción que contener: el daño es responder |
| humano activo / handoff pendiente | prometimos una persona; el modelo no puede renegociar esa promesa |
| **urgencia** | el daño es la demora. Contener después no sirve de nada |
| pide humano explícito | el modelo tendería a seguir ayudando; la petición no se reinterpreta |
| opt-out | legal. El daño es el mensaje mismo |
| **afirmativa a un `pending_action`** | ⚠️ **el que no estaba en tu lista y es el más importante.** Un «sí» ejecuta args ya staged, sin volver a pasar por el LLM (TC-SEC-03, `planner.py:210-212`). Si esto va al planner, la afirmativa puede ampliar el alcance de lo confirmado. **No mover** |
| presupuesto agotado | límite de costo, no de conversación |

Y lo que **sale** del router por no pasar el criterio: tamiz de identidad, los tres
retos, `is_bot_question`, `is_thanks`, `is_bare_greeting`, pagos, y el texto de la
respuesta a media. Todos ellos tienen contención disponible o simplemente no hacen
daño.

### 2.7 Qué FSM sobra y cuál no — la frontera ya existe

Corrección del PO, y verificarla dejó algo mejor de lo que él afirmó: **la FSM de
negocio y la de conversación ya están separadas por una frontera de proceso.**

| | FSM de **negocio** | FSM de **conversación** |
|---|---|---|
| Qué modela | `scheduled → confirmed → in_progress → done`, `draft → confirmed → paid`, borrado con dependencias | qué frase toca ahora, qué etapa del reto, qué template |
| Dónde vive | `appointments/views.py:31` `ALLOWED_TRANSITIONS`, `billing/services.py`, constraints y CHECK en Postgres | `policy.evaluate`, `_advance_*`, `return_to` |
| Quién la hace cumplir | DRF + services + base de datos | 36 ramas de router |
| Autoridad del agente sobre ella | **ninguna** | total |

El agente **no puede** tocar la FSM de negocio aunque quiera: todas sus escrituras
salen por `executor.call` → HTTP → DRF → services (`executor.py:91`). Sus únicos
imports de dominio son de **lectura** (`Pet`, `Owner`, `User` para búsqueda y
verificación), y los `save()` de `apps/agent` son todos sobre modelos propios
(`ContactIdentity`, `Conversation`, `Message`, `ConversationGoal`).

Verificado con una excepción, que conviene nombrar para que la afirmación sea exacta:
`management/commands/agent_eval.py:124-126` sí hace `Owner.objects.create` /
`Pet.objects.create`. Es el arnés de evaluación —siembra un caso de prueba—, no
runtime: ninguna ruta de `webhook → worker → planner → tools` lo alcanza.

**Consecuencia operativa, y es la que hace barato el experimento del §8:** cualquier
rediseño de la capa conversacional es **incapaz por construcción** de degradar la
corrección del negocio. No hay que proteger la FSM de negocio del rediseño — ya está
protegida por la frontera HTTP, el RBAC del rol AGENT y los constraints de la DB.

Donde la crítica sí aplica, y aplica entera: la FSM **de conversación**, y en
particular sus ~400 líneas de identidad (`policy.py` pasos 12b/8/8b/8c +
`_advance_challenge` + `_advance_family_challenge` + `_advance_identity_triage` +
`_seed_family_challenge` + `_check_interruption`). Esas no modelan estados del
negocio: modelan **el orden en que el cliente tiene permitido hablar**.

### 2.8 La gobernanza se convirtió en el producto

É-F4 entregó: `TurnDecision` (append-only, oráculo/diagnóstico separados), el árbitro
puro con presupuesto de ramas, el ciclo de vida de 7 estados con dos constraints
parciales, `Factor.why` estructural, guards de conducta en modo observación, autoría
de mensajes, ventana por turnos. Todo bien construido, todo trazable a un incidente
real, todo documentado a un nivel que la mayoría de sistemas en producción no
alcanza.

Y sin embargo el comportamiento del brief es *peor* que el de un prompt simple con
tool calling, porque **todo ese aparato gobierna un turno que el modelo nunca vio**.

Un ejemplo que lo condensa: **`flow['suspended']` se escribe y no se lee nunca.**

```
policy.py:674   flow['suspended'] = {'kind': 'pending_action', 'state': …}
```

Es la implementación de R4/R5 («suspender, no destruir»: una urgencia *suplanta* el
`pending_action`, no lo aborta, «se ofrece de vuelta al retomar»). Búsqueda en todo
`backend/apps/`: el único lector es la migración de datos `0013` y un test que afirma
que la clave se escribió (`tests/test_policy.py:108`). **No hay ningún lector en
runtime.** Para el cliente, «suspendido» y «borrado» son idénticos; lo único que la
garantía produjo fue una clave JSON muerta y un test verde.

Ese patrón —**el test certifica que el estado se escribió, no que la conversación se
comportó distinto**— aparece a lo largo del subsistema, y es la razón por la que
1.586 tests en verde conviven con la conversación del brief.

---

## 3. Problemas estructurales

### E1 · El LLM no gobierna la conversación; gobierna un subconjunto de ella

No es que el planner tenga poca libertad *dentro* de su turno: dentro es
razonablemente libre (hilo de tools completo, `turn_messages`, un solo retry con
corrección, `max_tools=5`). El problema es **cuántos turnos son suyos**. El router se
queda con identidad, primer contacto, tamiz, retos, quejas, pagos, agradecimientos,
saludos, media y confirmación. El modelo hereda el resto.

Y el criterio de reparto no es «riesgo»: es **antigüedad**. Cada rama del router se
añadió porque un incidente concreto la exigió (los comentarios lo documentan
honestamente: *«antes esto solo reaccionaba si el MODELO llamaba una tool personal»*,
`policy.py:239`). El router creció por acumulación de parches, cada uno correcto
aisladamente, y el efecto agregado fue expropiarle al modelo la mitad emocionalmente
sensible de la conversación.

### E2 · La memoria solo se escribe desde una llamada a herramienta

Detallado en §2.3. Consecuencias verificadas:

- Durante un reto de identidad, la tarea que el cliente pidió queda `suspended`.
  `goals.get_open_goal` filtra por `FOREGROUND_STATUSES` (`goals.py:333`), así que
  `context_block` devuelve `None` → **mientras se verifica identidad, el modelo no
  recibe ningún dato de lo que el cliente vino a hacer.** Da igual: en esa fase el
  planner tampoco se invoca.
- `anchored_identity_facts` (`prompts.py:184`) es un parche correcto y bien pensado a
  este agujero: ancla tres hechos (`ya_dijo_que_es_cliente`, `titular_declarado`,
  `verificacion_pendiente`) fuera de la ventana. Pero son **tres hechos elegidos a
  mano**, no un mecanismo. El cuarto hecho que haga falta requerirá otra entrada en
  ese diccionario, escrita después del próximo incidente.

### E3 · Cinco vocabularios paralelos para «el dato que estoy pidiendo»

| Capa | Representación | Fichero |
|---|---|---|
| Catálogo de compromisos | `Factor.name` | `goals.py:107` |
| Estado persistido | `return_to` — `CharField` libre, 32 chars | `models.py:236` |
| Copy al cliente | `if stage == 'pet' … else …` eligiendo `T0_*` | `policy.py:382`, `571` |
| Contexto al modelo | `_FACTOR_LABEL` | `prompts.py:145` |
| Clasificación de entrada | `_ANSWER_SHAPES` | `matchers.py:331` |

Ninguno se valida contra los otros. El Hallazgo 2 es exactamente la grieta entre la
1 y la 2. Cuando cinco tablas indexan el mismo concepto y ninguna es la fuente, el
concepto no existe: existen cinco convenciones que se mantienen sincronizadas a mano
hasta que alguien añade una etapa.

### E4 · El árbitro es un booleano con un ADR encima

`arbiter.decide` es una función pura de 5 veredictos cerrados, con presupuesto de
ramas y test bloqueante. Su **único call site de producción** (`policy.py:353`):

```python
arbiter.decide(
    arbiter.TurnFacts(interrupts=_is_interruption(factor, text)),
    arbiter.CommitmentView(commitment.name, factor),
)
```

`proposes_other_commitment` y `client_declined` **nunca se construyen fuera de los
tests**. Es decir: de los cinco veredictos, `SUPPLANT`, `ABORT` y `ANSWER` son
inalcanzables en producción. El árbitro —la pieza central de ADR p55, la «única
autoridad sobre qué pasa con el turno»— es hoy `bool → {DEVIATE, CONTINUE}`, y solo
se consulta **dentro de un reto de identidad ya en curso**.

No es un fallo de implementación: los hechos que le faltan (`proposes_other`,
`declined`) requieren clasificar la intención del mensaje entrante, y **nadie
clasifica la intención del mensaje entrante** — era la causa raíz CR-4 de la
auditoría de rigidez y sigue abierta. El árbitro se construyó por encima de un hueco
que no se llenó.

### E5 · «Interrumpir» está modelado como el complemento de «responder»

`_is_interruption` implementa: *interrumpe ⇔ pregunta ∧ ¬(tiene forma de respuesta)*.
Con `is_answer_shaped` cubriendo una sola etapa, esto degenera en *interrumpe ⇔
pregunta*.

Un mensaje humano es rutinariamente **las dos cosas**: `«ya te dije, Ana»`,
`«¿para qué? es 4586»`, `«no entiendo, pero se llama Luna»`. La arquitectura no tiene
forma de representar eso: `TurnVerdict` es un escalar y `DEVIATE` **descarta el
contenido del mensaje** (`_check_interruption` devuelve la `PolicyDecision` y el
caller retorna; el texto no se vuelve a mirar). Cada vez que un cliente responde
*y* pregunta, el sistema se queda con la pregunta y tira la respuesta.

Es, textualmente, la pregunta 7 del brief («¿existe conversación paralela?»). La
respuesta es no, y no por falta de una regla: por el tipo de dato del veredicto.

### E6 · La maquinaria anti-repetición es ciega a la capa que repite

- `goals.mark_asked` — único call site: `tools.py:727`, dentro de `_goal_gate`.
- `guards.check_behaviour(asked=…)` — `_asked_counters` lee `goals.get_open_goal`,
  que **excluye los compromisos de identidad** (`goals.py:336`).
- `guards.check_output` / `check_behaviour` solo corren sobre `result.text` del LLM
  (`planner.py:277-288`).

Resultado: el router repitió `T0_TRIAGE_TITULAR` **tres veces literalmente idénticas**
y (a) ningún contador subió, (b) ningún guard se disparó, (c)
`metrics.tasa_repregunta` —que mide `asked ≥ 2`— la registra como **0.00**.

El síntoma más reconociblemente robótico del sistema es invisible para las tres
mecanismos construidos para detectarlo, porque los tres vigilan al LLM y el que
repite es la FSM. Se vigila al sospechoso equivocado.

### E7 · La frustración del cliente no es un hecho del sistema

`matchers.is_complaint_or_meta` existe y detecta bien (`no te entiendo`, `ya te
dije`, `me estas repitiendo`, `perdiste el contexto`, `no sirves`…). Su **único
consumidor** (`planner.py:758`) es decidir si se antepone el aviso de fuera de
horario.

O sea: el sistema **sabe detectar que el cliente está molesto** y usa esa información
exclusivamente para no adjuntar un anuncio. No hay veredicto, no hay `Because`, no
hay contador, no hay cambio de conducta, no hay métrica. En la conversación del brief
el cliente emitió señales de frustración en los turnos 3, 4 y 5 — las tres detectables
por un matcher que ya existe y ya estaba cargado en memoria — y las tres se ignoraron.

Esta es la respuesta más dura a la pregunta 6 del brief. **El sistema no es que
priorice el flujo sobre el usuario: es que el estado emocional del usuario no es un
hecho representable.** No hay dónde ponerlo.

### E8 · Las garantías se testean por escritura de estado, no por conducta

`flow['suspended']` (§2.4) es el caso puro: garantía declarada, estado escrito, test
verde, cero efecto observable. Variantes del mismo patrón:

- `low_confidence` por slot: mecanismo completo (schema `_with_confidence`, umbral,
  filtro en serie, publicación como `por_confirmar`). La auditoría de rigidez ya lo
  documentó como **S13: el modelo siempre manda 1.0** — lleva vivo dos épicas sin
  haber cambiado un solo comportamiento.
- `ya_preguntado_2_veces` publicado al modelo: **S12**, «se publica y no cambia nada».
  Sigue publicándose (`goals.py:769`).
- `TurnDecision.active_commitment` / `return_to` / `supplanted_by` / `facts_consumed`:
  campos del oráculo. `_record_turn_decision` (`planner.py:69`) **solo llena `verdict`,
  `because`, `facts_produced`**. Cuatro de los siete campos del oráculo se persisten
  vacíos en todos los turnos.

---

## 4. Problemas de filosofía de diseño

### F1 · Se confundió «el sistema decide» con «el sistema redacta»

El principio correcto —*el LLM propone, el sistema dispone*— aparece bien enunciado
en `policy.py:9`. Pero se implementó como: *el sistema dispone **y además escribe el
mensaje***.

Son cosas distintas y el proyecto ya lo sabe: ADR p55 §2 define la prueba exacta
(«¿se puede renderizar el veredicto en otro idioma sin tocar el módulo?») y `goals.py`
la enuncia impecablemente: *«El objetivo NO sabe preguntar. Publica `missing` y ya;
cómo se pregunta es del modelo»* (`goals.py:20`). Esa disciplina se respetó
**dentro** de la capa de objetivos… y se rompe por completo en el router, que tiene
31 constantes de copy y elige entre ellas con `if stage == 'pet'`.

La consecuencia es que el control de flujo y la redacción están fusionados en las
mismas 36 ramas. No se puede hacer al agente más cálido sin tocar la máquina de
estados, ni cambiar la máquina de estados sin reescribir copy.

### F2 · Cada incidente produjo una capa, ninguno produjo una simplificación

Trazabilidad real, y es admirable: conv 12 → detector de estancamiento semántico;
conv 13 → hechos anclados + `park_identity` + autoría + ventana por turnos; piloto
2026-07-28 → paso 12b del router; BUG-AGENT-001 → guard `unbacked_success`.

Pero **ninguna de las cinco épicas eliminó un mecanismo.** El inventario solo crece:
`policy` (762) + `planner` (847) + `goals` (782) + `tools` (1.484) + `matchers` (368)
+ `guards` (274) + `prompts` (368) + `arbiter` (106) + `confirmations` (75) +
`tier0` (290) = **~5.400 líneas de lógica conversacional** para un dominio de 4
objetivos y 13 herramientas.

La forma de esa complejidad es diagnóstica: no es abstracción gratuita (cada pieza
tiene un incidente detrás), es **complejidad compensatoria** — cada capa existe para
suplir información que la capa de abajo no tiene. Eso no es indisciplina; es la firma
de una **costura mal puesta**. Un equipo disciplinado sobre una costura equivocada
produce exactamente esto: capas de calidad creciente resolviendo cada vez mejor un
problema que no debería existir.

### F3 · La spec funcional modela interacciones, no conversación

`INT-00…INT-22`, `UX-01…UX-16`, `E-01…E-10`, `G1…G7`, `R1…R16`. El contrato del
sistema es un **catálogo enumerado de situaciones**, y la arquitectura es su reflejo
literal: una rama de router por entrada del catálogo.

Un catálogo es una lista cerrada. Una conversación es abierta. Cada mensaje real que
no cae en una entrada del catálogo cae en `RUN_PLANNER` por descarte —el paso 13,
`policy.py:268`, comentado como *«Nada aplicó»*. **La capa conversacional es el
`else` final del router.** Está ahí escrito.

### F4 · Los tests certifican mecánica, no experiencia

`agent_eval` y `agent_quality` existen, y `metrics.compute_quality_metrics` mide
cosas correctas (latencia, turnos por resolución, tasa de repregunta, handoff). Pero:

- `tasa_repregunta` deriva de `goal.asked`, que solo escribe `_goal_gate` → **ciega al
  router** (E6).
- `turnos_por_resolucion` solo cuenta conversaciones con objetivo `completed` → **la
  del brief no aparece en ninguna métrica de calidad**; entra en `tasa_handoff` como un
  número más, sin distinguirse de un handoff legítimo.
- Ninguna métrica responde *«¿el cliente tuvo que repetirse?»*, *«¿el sistema ignoró
  algo que el cliente dijo?»*, *«¿el cliente se molestó?»* — las tres cosas que pasaron.

Un sistema no puede volverse humano si su definición operativa de calidad no incluye
ninguna medida de humanidad.

### F5 · «Nunca asumir» se aplicó como «nunca inferir»

Regla de producto legítima: el sistema no asume que un número desconocido es cliente
nuevo (`policy.py:434`, `matchers.py:352`), porque un falso `new` duplica expedientes.
Correcta.

Pero se implementó como **prohibición de inferir en absoluto**: `classify_client_triage`
devuelve `unclear` ante un `sí` o un `no` pelones «porque son genuinamente ambiguos».
Una recepcionista ante esa ambigüedad **no vuelve a preguntar lo mismo**: dice *«¿me
das el nombre de tu peludo y lo busco?»* y resuelve las dos ramas de un tiro. El
sistema, en cambio, repite (`T0_TRIAGE_RETRY`) y a la segunda cede.

La diferencia no es tolerancia al riesgo. Es que **el humano tiene una tercera opción
—actuar de forma que la ambigüedad deje de importar— y la arquitectura solo tiene dos
casillas.**

---

## 5. Respuestas directas a las 11 preguntas del brief

**1 · ¿El agente conversa o espera datos?**
Espera datos. Con matiz: en las conversaciones que llegan al planner (cliente
verificado, petición transaccional limpia) sí conversa, y razonablemente bien. En
todo lo demás —28 de 36 salidas del router— espera el siguiente dato esperado. La
conversación no es el centro del sistema: es el `else` del router (F3).

**2 · ¿La FSM gobierna demasiado?**
Sí, y la pregunta correcta es más incómoda: **la FSM es el producto y el LLM es un
plugin**. Medida: 28/36 salidas del router terminan sin LLM; 21/22 salientes del
planner son plantillas; la conversación del brief tuvo 0 llamadas. La conversación no
existe para satisfacer la FSM — es peor: **en la mitad de los casos la conversación
no existe.**

**3 · ¿Los compromisos son slot-filling con otro nombre?**
Los de **tarea**, no: `ConversationGoal` con ciclo de vida, `return_to`, suplantación
y reanudación determinista es genuinamente más que slots, y es lo mejor del rediseño.
Los de **identidad**, sí: son la FSM anterior movida a la misma tabla. Prueba —
`_advance_challenge`, `_advance_family_challenge` y `_advance_identity_triage` siguen
siendo tres `if stage == …` de 40 líneas cada uno (`policy.py:377-604`), y el
compromiso solo aporta persistencia. R7 unificó el **almacenamiento**, no el
**mecanismo**. Y `pending_action` sigue fuera, en `flow` (declarado fuera de alcance,
plan É-F4 §11): de las cinco implementaciones del concepto, quedan tres.

**4 · ¿El planner tiene libertad real?**
Dentro de su turno, bastante: hilo de tools completo, retry con corrección, tools con
`required: []` para poder llamarlas con datos parciales (`tools.py:1435` — buena
decisión). Fuera de su turno, ninguna: **no decide si le toca hablar**. Y ni siquiera
redacta los momentos que más importan: el parafraseo de confirmación es plantilla
(`confirmations.py:21-34`) y el mensaje de éxito de una cita también
(`planner._commit_success_text`). El instante decisivo de la conversación —«¡Listo!
✅ Quedó agendada»— lo escribe un `f-string`.

**5 · ¿Las tools siguen gobernando indirectamente?**
Menos que antes: ADR p55 §4 les quitó `reply_text` y `needs_confirmation`, y el
planner detecta la propuesta comparando estado (`_open_proposals`/`_new_proposal`).
Eso está bien hecho. Pero siguen gobernando por otras dos vías: (a)
`outcome.client_error` **elige la rama de conducta del turno** entre cuatro
(`family_restricted` / `verification_required` / suave / `tool_failure`,
`planner.py:399-480`), y dos de ellas terminan el turno con una plantilla sin
consultar al modelo; (b) dentro de la rama suave, el mismo código de error selecciona
**1 de 20 instrucciones imperativas redactadas** que se inyectan al modelo como
sistema (`_soft_error_hint`, `planner.py:644-681`: «Pregúntale al cliente…»,
«Discúlpate y ofrece…»). Se sustituyó el copy al cliente por copy al modelo.

**6 · ¿Responde al usuario o al flujo?**
**Al flujo, y es demostrable con precisión quirúrgica.** En la conversación del brief
el cliente hizo cinco cosas: respondió (`ya he ido`), aportó (`Ana`), preguntó
(`¿qué?`), corrigió (`ya te dije`) y se frustró (`queeee`). El sistema procesó
**una**: la respuesta al tamiz. El aporte se descartó porque nadie extrae datos (E2);
la pregunta se convirtió en un contador de desvíos; la corrección se clasificó como
pregunta (E5); la frustración se detectó y se usó para no adjuntar un aviso (E7).
Cuatro de cinco señales cayeron al vacío.

**7 · ¿Existe conversación paralela?**
No, y la razón es de tipos, no de reglas: `TurnVerdict` es un escalar, `DEVIATE`
descarta el contenido del mensaje, y la respuesta al desvío es **repetir la pregunta
verbatim** en lugar de responder-y-seguir. `T0_WHY_THEN_REASK` es un intento honesto
de esto (dar el motivo y repreguntar), y en el brief salió con el motivo vacío. Nota
importante: `Factor.why` es **la idea correcta** —el porqué pertenece al dato, no a
una tabla de copy—; lo que falló es que no cubre las etapas que la FSM realmente usa.

**8 · ¿Existe memoria conversacional real?**
Existe la tabla, no el mecanismo. Único puerto de escritura: `goals.capture`, llamado
solo desde `tools.py` (§2.3). Que «Ana» no se vuelva a preguntar depende por completo
de que el planner corra **y** el modelo llame una tool de escritura **y** meta el dato
en los args. Las tres condiciones fallaron en el brief. `anchored_identity_facts` es
un buen parche de tres hechos elegidos a mano, no una memoria.

**9 · ¿Hay demasiadas capas?**
Sí, pero el diagnóstico útil no es «demasiadas»: es **compensatorias** (F2). Facts →
Commitments → Planner → Policy → FSM → Executor → Tools → LLM no añade inteligencia;
coordina un problema que el reparto crea. La prueba está en el árbitro (E4): una capa
completa —módulo, ADR, presupuesto de ramas, suite propia— cuya función efectiva es
`bool → {DEVIATE, CONTINUE}`, porque el hecho que la haría valiosa (clasificar la
intención del entrante) nunca se implementó. Se construyó el techo antes que el
cimiento.

**10 · ¿Qué haría una recepcionista?** → §7.

**11 · ¿Destruir el diseño?** No, y la revisión del PO acotó cuánto. Sobra la FSM
**de conversación** de identidad como mecanismo de diálogo — **no** la FSM de negocio
(que ya está al otro lado de la frontera HTTP, §2.7) ni la regla de autorización (que
vive en `_verification_ok`, no en el router). El router **encoge**, no desaparece: 8
salvaguardas + `RUN_PLANNER` (§2.6). El árbitro no justifica ser un módulo mientras no
reciba hechos de verdad. Las 31 plantillas deberían ser ~5. Lo que **no** sobra: el
executor, el contrato tier-2, los guards de salida, el worker y la tabla de
compromisos. Y nada de esto se decide sin el experimento del §8 primero.

---

## 6. Inventario de componentes

### 6.1 Aportan valor real — conservar sin discusión

| Componente | Por qué |
|---|---|
| `ToolExecutor` (loopback HTTP + JWT del AGENT + `ToolExecution`) | La costura correcta entre conversación y negocio. Reusa serializers, RBAC, validadores de tenant y shape de errores sin duplicar nada. Auditoría completa. Es la mejor decisión del subsistema. |
| Contrato tier-2 (`confirmations` + `_commit_pending`) | Args staged, ejecutados verbatim, jamás regenerados. Es **la** propiedad de seguridad que importa cuando el LLM escribe en el dominio. No tocar. |
| Salvaguardas (urgencia, bloqueado, humano activo, opt-out) | Cuatro cortacircuitos que deben ser deterministas y preemptar todo. Correctos. |
| `guards.check_output` (G1 precios, G2 consejo médico, G3 promesas, G7 jerga) | Verificación **posterior** sobre el texto generado: restringe el resultado sin restringir el proceso. La forma correcta de constreñir a un LLM. |
| `worker.py` (lease, drain-on-pickup, aislamiento de fallos, `_discard_if_superseded`) | Infra sólida y bien razonada. |
| Tabla de `refs` / handles (`tools._add_ref`) | El modelo nunca ve UUIDs. Simple y efectivo. |
| `ConversationGoal` como **tabla** | El único estado agregable del sistema. El problema es su puerto de escritura, no su existencia. |
| `LLMCall` / `ToolExecution` / `TurnDecision` como observabilidad | Trazabilidad real. Conservar; corregir que 4 de 7 campos del oráculo se llenen. |

### 6.2 Idea correcta, capa equivocada

| Componente | Diagnóstico |
|---|---|
| `Factor.why` | La idea es exacta: el motivo pertenece al dato. La grieta es que `return_to` es un string libre que no referencia un `Factor` (Hallazgo 2). |
| `goals.context_block` (`ya_tengo`/`me_falta`) | El principio «el sistema es dueño del checklist, el modelo redacta» es correcto y está bien escrito. Solo se aplica a 4 objetivos y desaparece cuando hay un reto en curso. |
| `anchored_identity_facts` | Parche correcto de un agujero estructural. Debería ser el mecanismo general (publicar el estado íntegro), no tres claves elegidas a mano. |
| `guards.check_behaviour` | Los tres guards de conducta apuntan a lo correcto (repetición, contradecir el estado, éxito no respaldado). Vigilan al LLM, y quien comete esos tres fallos es el router (E6). |

### 6.3 Eliminables

| Componente | Por qué |
|---|---|
| `flow['suspended']` | Escrito, nunca leído. Clave muerta con test verde. |
| `low_confidence` + `_with_confidence` + `por_confirmar` | Mecanismo completo que el modelo nunca ejercita (S13, dos épicas). |
| `arbiter.py` **como módulo separado** | Hoy es `bool → {DEVIATE, CONTINUE}` con un ADR encima. O recibe hechos de verdad, o no justifica ser una capa. |
| `flow['identity_triage_done']` | Duplica el `ConversationGoal` de tamiz que R7 creó para sustituirlo. Conviven, con `setdefault` defensivo para que no se pisen (`policy.py:496`). |
| ~26 de las 31 constantes `T0_*` | Solo las 4-5 de salvaguarda necesitan ser literales verificables. El resto es copy que el modelo escribiría mejor, con el hecho a comunicar como dato. |
| `_TRIAGE_*` (≈70 lemas) + `classify_client_triage` | 70 strings en español para resolver una clasificación binaria que un LLM resuelve mejor y que además es **verificable a posteriori** (buscar el owner). |
| `_QUESTION_LEMMAS` + `is_answer_shaped` + `_is_interruption` | Aparato para decidir «¿esto es respuesta o pregunta?» sobre un falso dilema (E5). |

### 6.4 Los que limitan activamente al LLM

Ordenados por severidad del daño:

1. **`policy.evaluate` (paso 12b y pasos 8/8b/8c).** Le quitan al modelo el 100 % de
   la conversación de identidad, que es donde la humanidad más importa: cliente nuevo,
   primera impresión, desconfianza, fricción. Es el limitador dominante y explica el
   brief completo.
2. **`_soft_error_hint` (`planner.py:644`).** 20 instrucciones imperativas redactadas
   que se inyectan como sistema. No es contexto: es guion. Sustituye el juicio del
   modelo por una tabla de respuestas.
3. **Parafraseos y mensajes de éxito por plantilla.** Los cuatro momentos de mayor
   carga emocional (confirmar, agendar, cancelar, registrar) están literalizados.
4. **`_privacy_prefix`, `_after_hours_prefix`, `_post_scheduling_info`.** Tres
   prefijos/sufijos concatenados al texto del modelo, que no puede integrarlos en su
   redacción ni decidir el momento. Producen mensajes con costuras visibles.
5. **`HISTORY_TURNS = 12` + `HISTORY_MESSAGE_CAP = 40`.** Contar turnos es mejor que
   contar mensajes (buena corrección), pero sigue siendo una ventana ciega: no hay
   resumen rodante (`Conversation.summary` existe en el modelo y **no se escribe
   nunca**).

---

## 7. Recepcionista humana vs. arquitectura actual

Cómo razona una recepcionista buena ante el mensaje `«ya te dije, Ana»`, paso a paso,
contra lo que hace el sistema:

| # | Recepcionista | Sistema | Existe la pieza? |
|---|---|---|---|
| 1 | Oye el mensaje **completo** y extrae todo lo utilizable: hay un reclamo *y* hay un nombre | `classify_client_triage(text)` busca lemas de tamiz; lo demás no se mira | **No.** Nada extrae datos no solicitados (E2) |
| 2 | Nota que el cliente está molesto y que la causa es ella | `is_complaint_or_meta` lo detecta… y solo decide no adjuntar un aviso | Detecta, no representa (E7) |
| 3 | Reconoce el error: *«perdón, sí me lo dijiste»* | No existe la categoría «me comporté mal con el cliente» | **No.** De los 12 `Because`, el único de culpa propia es `SYSTEM_ERROR`, y significa fallo técnico (tool en 5xx, commit rechazado). Repetir, ignorar o contradecir no tienen valor |
| 4 | Usa el dato que ya tenía y avanza | El dato nunca entró a la memoria | **No** (E2) |
| 5 | Si necesita otra cosa, la pide **distinto** de como la pidió antes | Repite el template idéntico | **No.** `mark_asked` es ciego al router (E6) |
| 6 | Explica el porqué sin abandonar el objetivo | `T0_WHY_THEN_REASK` — la idea correcta | **Sí**, pero con el `why` vacío en la etapa que importa (Hallazgo 2) |
| 7 | Si se atora, cambia de estrategia (buscar por mascota, por teléfono, por lo que sea) | Tres desvíos → handoff | **No.** El único plan B es un humano |
| 8 | No dice «no logro validar tus datos» cuando nadie validó nada | Lo dice | Mensaje incorrecto (Hallazgo 4) |

**Ocho pasos. La arquitectura tiene uno y medio.** Y el punto no es que falten siete
mecanismos: es que **los siete que faltan son el mismo mecanismo** —leer el mensaje
completo y decidir qué hacer con todo su contenido— que es exactamente lo que un LLM
hace de forma nativa y al que aquí no se le pregunta.

---

## 8. El experimento acotado (decisión del PO) — y por qué es mejor que rehacer

La v1 de esta auditoría se inclinaba por una reestructuración profunda. **El PO tiene
razón y esa inclinación era prematura.** El experimento correcto es el suyo:

> Tomar **solo** el flujo de identidad. Eliminar su FSM conversacional completa. Darle
> al planner el estado como hechos y el límite como restricción:
>
> ```
> Estado: cliente no verificado
> Ya sabemos: quiere agendar · dijo llamarse Ana · dijo que su mascota es Oliver
> Falta: verificar identidad
> Puedes conversar libremente. No puedes ejecutar ninguna acción hasta verificarla.
> ```
>
> Y observar.

### 8.1 Por qué este recorte y no otro

- **Es donde vivió el 100 % del fallo auditado.** Los cinco turnos del brief son
  identidad. Ninguna otra rama del router tiene esa densidad de evidencia.
- **Es el bloque más grande de FSM conversacional**: **~370 líneas en `policy.py`**
  (pasos 12b y 8/8b/8c, `_is_interruption`, `_check_interruption`,
  `_advance_challenge`, `_clear_challenge`, `_advance_identity_triage`,
  `start_identity_triage`, `_seed_family_challenge`, `_inbound_history`,
  `_advance_family_challenge`, `_family_fail`), **~120 más en `matchers.py`**
  (`_TRIAGE_*`, `classify_client_triage`, `_QUESTION_LEMMAS`, `looks_like_question`,
  `is_answer_shaped`) y las plantillas `T0_TRIAGE_*`/`T0_CHALLENGE_*`/
  `T0_WHY_THEN_REASK` de `tier0.py`. ~500 líneas en total.
- **No hay nada que construir para que sea seguro.** Ésta es la razón decisiva: la
  barrera que impide que un cliente no verificado toque datos personales **no es el
  router** — es `_verification_ok` (`tools.py:111`), evaluada en `run_tool`, por
  debajo del modelo y ajena por completo a la conversación. Un planner conversando
  libremente sobre identidad **no puede** ejecutar una tool personal: la llamada
  rebota con `verification_required` sin haber tocado nada.
- **Es reversible**: es una supresión más un bloque de contexto. Sin migración, sin
  cambio de esquema, sin tocar el dominio (§2.7).

### 8.2 Tres condiciones para que el resultado sea *interpretable*

Sin estas, el experimento va a dar un resultado bueno por la razón equivocada.

**C1 · Necesita un puerto de escritura push, o no prueba su propia tesis.**
El bloque que el PO escribió —*«dijo llamarse Ana · dijo que su mascota es Oliver»*—
**es** un almacén de hechos en modo push. Hoy nada lo escribiría: `goals.capture` solo
se invoca desde `tools.py` (§2.3) y el modo pull no tiene dónde poner un dato no
solicitado (§2.5). Si el experimento corre sin eso, el modelo conversará bien mientras
los hechos quepan en la ventana de 12 turnos y **degradará al salir de ella** — y la
lectura sería «el modelo era la solución», cuando lo que faltaba era el push. Cómo se
llene ese bloque es diseño; **que exista es condición de validez.**

**C2 · El veredicto de verificación sigue siendo del código, no del modelo.**
Esto es una frontera de seguridad, así que sin ambigüedad: el modelo puede conversar
sobre identidad, pedir el dato como quiera y en el orden que quiera, pero **quien
cambia `ContactIdentity.verification_level` debe seguir siendo
`identity.try_verify_by_*` evaluando el dato contra la base.** El modelo aporta el
candidato; el código dictamina si coincide. Si en algún momento el nivel de
verificación sube porque el modelo *afirma* que verificó, el experimento no habría
hecho al agente más humano: habría abierto un acceso no autorizado a expedientes de
terceros. Es el mismo invariante que ya protege las escrituras (args staged, TC-SEC-03)
aplicado a la lectura de datos personales.

**C3 · Instrumentación que sobreviva al propio recorte.**
«Observaría» necesita con qué. Las métricas actuales no sirven tal cual:
`tasa_repregunta` es ciega al router (E6) y, si identidad deja de crear filas
`ConversationGoal`, `compute_goal_metrics` cambia de significado a mitad del
experimento. Lo que **sí** es comparable antes/después, sin tocar nada:

| Señal | Fuente | Por qué es limpia |
|---|---|---|
| `HumanHandoff` con `reason_code='identity'` | tabla existente | el desenlace exacto del brief |
| `TurnDecision.because = VERIFICATION_REQUIRED` por conversación | tabla existente | mide cuántos turnos se gastan en identidad |
| Turnos hasta la primera tool personal exitosa | `ToolExecution` | mide fricción real, no proxy |
| Relectura de transcripciones | `Message` | lo único que mide humanidad hoy |

Nota que vale la pena decir: **`TurnDecision` es lo que hace medible este
experimento.** É-F4 construyó el instrumento con el que ahora se puede desmontar parte
de É-F4 con datos en vez de opinión. Esa es la definición de trabajo bien invertido,
aunque el veredicto sea recortar.

### 8.3 Qué NO se toca en este experimento

Una variable a la vez, o no hay señal:

- **El contrato tier-2** (`pending_action`, args staged, `_commit_pending`). Intacto.
- **Las salvaguardas** de §2.6. Intactas.
- **`_verification_ok`** y el gate de tools. Intacto — es justamente lo que hace
  seguro el experimento.
- **Los objetivos de tarea** (`SCHEDULE`/`REGISTER`/`CANCEL`/`RESCHEDULE`). Intactos.
- **La FSM de negocio.** No es alcanzable desde aquí (§2.7).

### 8.4 Cómo leer el resultado

| Observación | Lectura |
|---|---|
| Mejora clara y **se sostiene** en conversaciones largas | Hipótesis confirmada: el problema era **quién tenía el control**, no el modelo. El mismo recorte se aplica a las demás ramas del router una por una |
| Mejora al principio y **degrada al alargarse** la conversación | El control era parte del problema, pero **falta el push** (C1). No rehacer nada todavía: cerrar C1 y repetir |
| No mejora | La hipótesis es falsa y el documento se equivoca. Sería el resultado más valioso de los tres, y llega por ~400 líneas suprimidas en vez de por un rediseño |
| Mejora pero aparecen fugas de datos personales | C2 se rompió. Revertir de inmediato |

### 8.5 Si el experimento confirma — inventario para después

**Conservaría** (≈35 % del código actual, y es el 90 % del valor):

- `ToolExecutor` + loopback HTTP + `ToolExecution`. Intacto.
- El contrato de confirmación tier-2. Intacto, incluido `TC-SEC-03`.
- Las 4 salvaguardas deterministas, arriba de todo. Intactas.
- Los guards de salida sobre el texto generado, y **su simétrico ausente**: guards
  sobre la **conducta del sistema**, no solo sobre la del modelo.
- El worker completo.
- `ConversationGoal` como tabla de compromisos de tarea, con su ciclo de vida.
- Toda la observabilidad.

**Descartaría**:

- La FSM de identidad como **mecanismo conversacional**. La verificación de identidad
  no es un modo en el que la conversación entra: es un **predicado sobre hechos** que
  el sistema evalúa y publica («este contacto no está verificado; para hacer X hace
  falta Y»), y una **precondición que las tools ya imponen** (`_verification_ok`,
  `tools.py:111` — ya existe y ya es vinculante). Los tres retos multi-turno son 400
  líneas de router que duplican una barrera que las herramientas ya tienen.
- El router **como dueño de la conversación** — no el router. Quedaría el mínimo de
  §2.6: 8 salvaguardas + `RUN_PLANNER`. De 36 salidas a ~9.
- Las 31 plantillas, salvo las de salvaguarda.
- Los matchers de clasificación semántica (tamiz, interrupción, forma de respuesta).
  Los de seguridad (urgencia, humano, opt-out) se quedan: ahí el recall determinista
  vale más que el matiz.
- El árbitro como módulo, mientras no reciba hechos reales.

**Cambiaría de forma** — solo **después** de que el experimento del §8.1 dé señal.
Aquí está la decisión de arquitectura; podar es la consecuencia, no la decisión:

1. **Invertir el default.** Hoy: el sistema decide y delega los sobrantes. Debería
   ser: el modelo conduce, y el sistema conserva **veto** (salvaguardas + guards),
   **hechos** (estado publicado íntegro) y **ejecución** (tools + confirmación). El
   determinismo se aplica al *resultado* (contención), no al *proceso* (preempción)
   — §2.6.
2. **De pull a push: un puerto de escritura abierto en cada turno.** Que un hecho se
   registre no puede depender de que el modelo llame una herramienta de escritura
   (§2.5). Es la condición C1 del experimento, generalizada.
3. **Publicar el estado completo, siempre.** `anchored_identity_facts` +
   `context_block` + `flow` deberían ser una sola proyección, no tres parches. El
   modelo debe poder ver todo lo que el sistema sabe de esta conversación.
4. **Que el veredicto del turno deje de ser un escalar.** Un mensaje puede responder,
   preguntar, corregir y quejarse a la vez; mientras el tipo de dato no lo admita, la
   conversación paralela es irrepresentable.
5. **Medir humanidad.** Sin una métrica de «el cliente tuvo que repetirse» o «se
   ignoró algo que dijo», ninguna de estas correcciones es verificable y la próxima
   épica volverá a añadir una capa.

---

## 9. Conclusión

**Están construyendo un workflow conversacional, no un agente conversacional.** Y la
distinción no es semántica:

- **Un agente** tiene un objetivo, percibe el estado completo del mundo, elige qué
  hacer, y el sistema le pone **límites** (qué no puede decir, qué no puede escribir,
  cuándo debe pasar a un humano).
- **Un workflow** tiene un grafo de estados, consume los inputs que sus transiciones
  esperan, y usa un LLM para **rellenar los huecos de redacción** entre nodos.

Hoy: 28 de 36 salidas del router terminan sin modelo; 21 de 22 salientes del planner
son plantillas; el veredicto del árbitro es un booleano; la memoria solo se escribe
desde un tool call; y la conversación que motivó esta auditoría se ejecutó de
principio a fin sin que el LLM viera un solo mensaje. Eso es un workflow con un LLM
adjunto, y el cliente lo nota porque es exactamente lo que es.

**Tres precisiones para que este veredicto sea justo:**

**Primera: el trabajo hecho no está tirado.** El executor, el contrato tier-2, los
guards, el worker y la tabla de compromisos son piezas de calidad de producción que
sobreviven a cualquier rediseño. Lo que sobra es la capa de gobierno del turno, y
sobra porque gobierna turnos que no deberían decidirse ahí.

**Segunda: el problema no es exceso de disciplina.** Es el efecto de un equipo
disciplinado trabajando sobre una costura mal puesta. Cada capa tiene un incidente
real detrás y resuelve correctamente el problema que le tocó; el defecto es agregado,
no local, y por eso ninguna de las tres auditorías previas lo vio: **todas
preguntaron cómo repartir mejor la autoridad, ninguna preguntó por qué la
conversación tiene que pasar por un reparto de autoridad antes de existir.**

**Tercera, y es la que decide si esto se repite:** el sistema ya sabía casi todo lo
que necesitaba para atender bien la conversación del brief. Sabía que el cliente era
recurrente. Tenía «Ana» en el mensaje. Sabía —vía `is_complaint_or_meta`— que estaba
molesto. Sabía —vía `asked`— que le había preguntado lo mismo tres veces. **Los
cuatro hechos estaban en memoria, en el mismo proceso, en el mismo turno.** Nada de
eso llegó a ninguna decisión, porque la decisión ya estaba tomada por la etapa del
grafo en la que estaba parado.

Un agente que sabe cuatro cosas y usa cero no tiene un problema de información. Tiene
un problema de **quién decide**. Y ese es, exactamente, el problema que É-F4 se
propuso resolver — resuelto para la parte de la conversación que el modelo ya
gobernaba, y no aplicado a la parte que nunca llegó a él.

**Y sin embargo, la conclusión operativa no es rehacer.** Las dos correcciones del PO
que reencuadran este documento —la frontera de negocio ya existe (§2.7) y la
contención ya está implementada (§2.6)— significan que **la parte cara del rediseño
ya está hecha y funcionando**. Lo que queda por probar no es una arquitectura nueva:
es una supresión de ~400 líneas en un solo flujo, con la barrera de seguridad intacta
por debajo, y una pregunta con tres respuestas posibles y todas útiles (§8.4).

Si esa supresión mejora el comportamiento de forma evidente, la respuesta ya está y no
hace falta rediseñar nada más que aplicar el mismo recorte rama por rama. Si mejora y
luego se degrada, el culpable es el modo pull y se sabe exactamente dónde atacarlo. Si
no mejora, este documento se equivoca — y haberlo descubierto habrá costado una tarde
en vez de una épica.

Ninguno de los tres desenlaces requiere apostar el sistema. Ése es el argumento más
fuerte a favor del experimento, y es del PO, no del auditor.

---

## Anexo · Índice de evidencia

**Contraste documento↔código, 2026-07-31** (a petición del PO). Se re-verificó cada
cifra del texto contra `develop`. Resultado: **la tesis y los cuatro hallazgos se
sostienen sin cambios**; ocho afirmaciones se corrigieron por precisión, dos de ellas
numéricas:

| Afirmación v1 | Realidad | Efecto |
|---|---|---|
| «21 de 22 salientes con `author='system'`» | 20 system (19 explícitos + 1 por default) · 2 agent, de los cuales 1 es plantilla | ninguno en el fondo: sigue siendo **1 de 22** con texto del modelo |
| «Once de once funciones de `matchers`» | 13 públicas; 12 devuelven bool/enum | ninguno: la propiedad es la misma |
| «`client_error` selecciona 20 respuestas en un `if/elif`» | 4 ramas de conducta + 1 de 20 hints al modelo | corrige una conflación de dos mecanismos |
| «no hay un solo `save()` de dominio en `apps/agent`» | cierto en runtime; `agent_eval.py:124-126` sí crea `Owner`/`Pet` | acota el absoluto; no toca la frontera |
| «los 12 `Because` no incluyen fallo propio» | existe `SYSTEM_ERROR`, pero es fallo técnico | precisa el enunciado |
| `policy.py:198` / `:456` | `:197` / `:454-455` | anclas |
| «~400 líneas de FSM de identidad» | ~370 en `policy.py` + ~120 en `matchers.py` ≈ 500 | el recorte del §8 es **mayor** de lo estimado |

Verificadas sin cambio: 36 salidas de router (18/6/1/3/8), 31 constantes `T0_`, 23
salidas del planner, `flow['suspended']` sin lector, `arbiter.decide` con un call
site, `goals.capture` solo desde `tools.py`, `mark_asked` solo en `_goal_gate`,
`is_complaint_or_meta` con un consumidor, `IDENTITY_SPECS[TRIAGE]` con un solo factor,
`WhyVoiceTests` sin cubrir identidad, `_ANSWER_SHAPES` solo `digits`,
`Conversation.summary` sin escrituras, `ALLOWED_TRANSITIONS` en `appointments/views.py`.

| Afirmación | Ubicación |
|---|---|
| El router termina el turno sin LLM | `planner.py:171-202` |
| 36 salidas del router; 28 sin LLM | `policy.py` (18 REPLY, 6 ESCALATE, 1 CLOSE, 3 SILENT, 8 RUN_PLANNER) |
| 21 de 22 salientes del planner son `author='system'` | `planner.py` — único `author='agent'` con texto del modelo en `:330` |
| El nombre en la ráfaga se descarta | `policy.py:461` + `matchers.py:348` |
| `why` vacío en la etapa `titular` | `goals.py:273-281` vs `policy.py:372`, `policy.py:465` |
| `return_to` es un string libre no verificado | `models.py:236` |
| `WhyVoiceTests` no cubre `IDENTITY_SPECS` | `tests/test_w2_goals.py:327-346` |
| «ya te dije» clasificado como pregunta | `matchers.py:279-299` |
| `is_answer_shaped` solo cubre `digits` | `matchers.py:331-345` |
| Tope de desvíos → `T0_CHALLENGE_FAILED` sin fallo real | `policy.py:360-369` vs `tier0.py:181` |
| `arbiter.decide` con un solo call site y un solo hecho | `policy.py:353-355` |
| `mark_asked` solo desde `_goal_gate` | `tools.py:727` |
| `_asked_counters` excluye compromisos de identidad | `planner.py:710` → `goals.py:336` |
| `is_complaint_or_meta` con un único consumidor | `planner.py:758` |
| `goals.capture` solo desde `tools.py` | `tools.py:609`, `tools.py:725` |
| `flow['suspended']` escrito y nunca leído | `policy.py:674`; lectores: `migrations/0013`, `tests/test_policy.py:108` |
| `Conversation.summary` nunca se escribe | `models.py:148` |
| `TurnDecision`: 4 de 7 campos del oráculo vacíos | `planner.py:69-88` vs `models.py:547-555` |
| `_soft_error_hint` inyecta instrucciones redactadas | `planner.py:644-681` |
| Parafraseos y éxitos por plantilla | `confirmations.py:21-34`, `planner.py:629-641` |
| 12 de las 13 funciones públicas de `matchers` devuelven `bool`/enum; ninguna un valor (`normalize` devuelve texto, es helper) | `matchers.py` completo |
| Único puerto push del sistema (verificación implícita) | `policy.py:200-203` → `identity.py:124-141` |
| …y está apagado sin `owner_id` (el caso del brief) | `identity.py:126` |
| FSM de negocio fuera del alcance del agente | `appointments/views.py:31` `ALLOWED_TRANSITIONS`; escrituras solo vía `executor.py:91` |
| `apps/agent` no escribe modelos de dominio en runtime | imports solo de lectura: `identity.py:116,182`, `policy.py:565`, `services.py:21`, `tools.py:391`. Única excepción, fuera de runtime: `management/commands/agent_eval.py:124-126` |
| La barrera de identidad no es el router | `tools.py:111` `_verification_ok`, evaluada en `run_tool` (`tools.py:1481`) |
