# ADR p56 — Percepción, situación y el turno como objeto raíz

> **Enmienda B0 (2026-09-13), vigente para esta release.** El filtro temporal de contención tiene prioridad sobre la publicación de salida libre cubierta por el corpus. No modifica percepción, arbiter, historia ni el orden de safety/ownership. C1 queda acordado como contexto causal acotado para B1, sin implementar DTO global, leases o revisiones en B0.
> Alcance, pruebas, límites y rollback: [acta B0](../implementacion-b0-agente-whatsapp-2026-09-13.md). El resto del ADR conserva sus decisiones salvo esta contención temporal.

**Fecha**: 2026-08-01
**Estado**: **ACEPTADO** (PO, 2026-08-01) — **sin implementar**
**Contexto de producto**: subsistema del agente WhatsApp, tras la [auditoría de arquitectura conversacional](../whatsapp-agent-auditoria-arquitectura-2026-07-31.md) y el plan [É-F5](../whatsapp-agent-f5-conversacion-plan.md)
**Relación con p55**: lo **enmienda** (§6/R13 y la jerarquía de autoridad). No lo supersede: 10 de sus 12 invariantes quedan intactos.

---

## Contexto

Tres épicas de gobernanza conversacional (É-F3, É-F4) produjeron un sistema
correcto, auditable y bien gobernado que **se comporta como un formulario**. La
auditoría del 2026-07-31 encontró la causa, y no era ninguna de las que las dos
auditorías anteriores habían diagnosticado:

1. **La conversación que motivó todo esto se ejecutó con cero llamadas al
   modelo.** Los cinco mensajes del agente son constantes de `tier0.py`
   emitidas por `policy.evaluate`. No es que el agente *parezca* un formulario:
   en esa conversación no había agente.
2. **`policy.evaluate` tiene 36 puntos de decisión y 28 terminan el turno sin
   consultar al modelo.** De los 22 salientes que emite `planner.py`, **uno
   solo** lleva texto redactado por el modelo.
3. **El único puerto de escritura de memoria es `goals.capture`, y sus dos call
   sites están en `tools.py`.** Un dato entra al estado solo si el modelo llama
   una herramienta de escritura y lo mete en los argumentos.

El punto 3 tiene una consecuencia que ninguna regla vigente podía evitar: cuando
el cliente escribió *«mi nombre es Ana»* en la misma ráfaga que su respuesta al
tamiz, el dato **no se perdió — no había dónde ponerlo**, y el agente preguntó por
ese nombre medio segundo después.

### Lo que este ADR reconoce sobre p55

p55 §3 define correctamente la diferencia entre un slot y un compromiso: *«lo
posee la conversación»*, *«lo avanza cualquier cosa: el cliente, una lectura, un
humano»*. **La implementación está íntegra en la columna que el propio ADR marca
como equivocada**: `_goal_gate` abre el compromiso con
`goals.TOOL_GOALS[tool_name]` (lo posee la tool, se llama como la tool) y
`capture` solo se alimenta de `raw_args`.

É-F4 Fase 3 movió los tres retos de identidad a la tabla de compromisos —
almacenamiento — y conservó la semántica de slots. Buena parte de lo que sigue es
**cobrar la deuda de p55**, no inventar arquitectura.

### Por qué UN ADR y no tres

El PO señaló tres decisiones (situación vs control · el compromiso deja de ser
raíz · percepción ≠ extracción) y propuso ADR propio para la segunda. Se empaquetan
en uno, y el argumento es de eficacia, no de comodidad:

> **Las tres son separables en código e inseparables en efecto.**

- Adoptar la situación **sin** destronar el compromiso es implementable: se
  publica *«está molesta»* junto a *«me_falta: [fecha]»* y la agenda sigue
  mandando. Resultado: el mecanismo sin el efecto. **Es exactamente el fallo de la
  v1 del plan É-F5**, que el PO detectó leyendo el documento.
- Destronar el compromiso **sin** percepción deja la frase vacía: si el sistema no
  tiene hechos sobre la persona, «el turno es la raíz» no significa nada.
- Percibir sin la separación control/situación obliga a validar el estado de ánimo
  con el aparato de los datos, que no existe y no hace falta.

Tres ADRs permitirían implementar dos, creer que se terminó y no mover el
comportamiento. Es el mismo argumento con el que p55 se escribió entero en vez de
por partes: *«con cuatro contratos cambiando a la vez, un ADR posterior no decide,
documenta»*.

---

## Decisión

### 1. El objeto raíz del razonamiento conversacional pasa a ser el TURNO

Es el cambio más profundo desde que empezó el subsistema, y conviene enunciarlo
sin ambigüedad.

**Primero, qué significa «raíz», porque la palabra sola no lo dice.** El sistema
tiene tres unidades y este ADR solo mueve una:

| Unidad | Qué es | ¿Cambia? |
|---|---|---|
| **`Conversation`** | la unidad **PERSISTENTE**: el hilo, la FSM de cuatro estados, la ventana de 24 h, el lease del turno | **no** |
| **el turno** | la unidad primaria de **RAZONAMIENTO**: lo que el sistema mira para decidir qué hacer | **sí — pasa a serlo** |
| **`Commitment`** | la unidad de **COMPROMISO**: lo que se prometió y en qué punto va | **no cambia de forma**, cambia de rango |

> **`Conversation` sigue siendo la unidad persistente. El turno pasa a ser la
> unidad primaria de razonamiento.**

Nada de esto toca el almacenamiento: no hay tabla nueva, no hay migración, y
`Conversation`/`ConversationGoal` conservan su esquema.

| | Antes (vigente) | Ahora |
|---|---|---|
| Pregunta central del sistema | *¿cómo cumplo el compromiso?* | ***¿qué necesita esta persona?*** |
| Objeto que organiza el turno | `Commitment` | el **turno**: qué dijo, cómo llega, qué le debemos |
| El compromiso es… | el marco de todo | **una deuda del sistema**, no una agenda a la que tiene derecho |
| Sin compromiso abierto | no hay nada que decidir (`ANSWER`) | hay una persona hablando, que es suficiente |

**Qué NO significa.** El compromiso **no se degrada ni desaparece**: la tabla, los
siete estados, `return_to`, `supplanted_by`, `blocked_reason`, las dos constraints
parciales y el embudo por terminales de p55 §3 quedan **intactos**. Lo que cambia
es su **rango**: deja de ser aquello alrededor de lo cual gira el turno y pasa a
ser uno de los hechos que el turno consulta.

**Consecuencia inmediata y verificable**: un compromiso abierto no dicta el tema.
Si el cliente dice *«mi perro está nervioso»* con una verificación pendiente, el
tema del turno es el perro.

### 2. Percepción ≠ extracción, y produce DOS clases de hecho

**Extracción** pregunta *«¿qué slots del compromiso abierto hay en este mensaje?»*
— objetivo cerrado, definido por lo que el sistema quería.
**Percepción** pregunta *«¿qué intentó comunicarme esta persona?»* — sin objetivo
cerrado, definido por lo que ella hizo.

Percepción produce dos salidas con **epistemologías distintas**, y la asimetría es
deliberada:

| | **Hecho de CONTROL** (dato) | **Hecho de SITUACIÓN** |
|---|---|---|
| Ejemplo | «me llamo Ana», «el martes», «Oliver» | «está apurada», «se disculpa», «pregunta por el proceso», «bromea», «lleva 3 turnos sin obtener lo que pidió» |
| Quién lo propone | el modelo | el modelo o los matchers deterministas |
| Validación | validador + umbral de confianza (contrato p54, intacto) | **ninguna** — no existe un validador para un estado de ánimo |
| Se persiste | sí, en el compromiso; agregable | como enum/booleano en el rastro; **jamás el texto** |
| Quién lo lee | árbitro, tools, embudo | **solo el modelo** (y el reporte) |
| Si es incorrecto | un slot mal llenado → lo atrapa el validador o la confirmación | una frase con el tono levemente desviado → **coste cero** |

**La última fila justifica la penúltima.** No validar la situación es aceptable
**precisamente porque** no puede alcanzar una decisión; y no dejarla alcanzar una
decisión es lo que hace innecesario validarla. Las dos mitades se sostienen
mutuamente: quitar una obliga a añadir la otra.

#### La percepción ocurre SIEMPRE

**Todo mensaje atraviesa percepción, exista o no un compromiso abierto.**

Es la línea que habilita el cambio de paradigma, y hay que escribirla porque la
optimización que la rompe suena razonable: *«como no había compromiso, saltamos
percepción»*. Eso restauraría el modelo viejo en silencio — **percibir solo
cuando hay algo que llenar ES extracción**, con otro nombre.

Corolario de orden, y es lo que lo hace exigible: la percepción corre **antes**
de consultar si hay compromiso, así que no puede estar condicionada por uno. El
primer mensaje de una conversación —cuando por definición no hay compromiso— es
justamente el turno donde el cliente suele decir más cosas de golpe. Es el turno
1 del caso del brief.

#### La válvula de un solo sentido: inhibir un automatismo

> **Enmienda aprobada por el PO, 2026-08-01**, con la formulación y las tres
> condiciones que siguen. No amplía la capa de situación: le da nombre a una
> propiedad que el sistema **ya ejercía** sin tenerlo.

> **La situación puede impedir que el sistema INICIE una conversación cuya
> oportunidad haya desaparecido. Nunca puede impedir que el sistema RESPONDA
> una conversación iniciada por el cliente, ni omitir una validación,
> salvaguarda o decisión de negocio.**

El precedente ya existe y lleva meses en producción: `_after_hours_prefix`
suprime el aviso de fuera de horario cuando detecta una queja. No toca
permisos, tools, handoffs, RBAC ni compromisos — solo dice *«este automatismo
ya no es oportuno»*. Es exactamente la misma clase de decisión.

Los dos casos que la motivan tienen la misma naturaleza:

| | El cliente dice | El sistema iba a | Por qué no |
|---|---|---|---|
| 1 | «déjame pensarlo» | recordarle la cita a los 60 min | le prometimos esperar |
| 2 | «mi mascota murió» | «¿Seguimos con tu cita?» | el turno dejó de tener sentido |

En ninguno de los dos se deja de atender al cliente: se deja de **iniciar** un
turno que ya no procede.

**Tres condiciones, y hacen falta LAS TRES.** Si falta una, la situación no
interviene:

1. **No fue provocado por un mensaje nuevo del cliente.**
2. **Lo inicia el sistema**, no la conversación.
3. **Su ausencia nunca empeora la seguridad ni rompe una garantía
   contractual.**

> **La deriva que estas condiciones existen para impedir** (planteada por el
> PO): con solo *«la situación puede callar automatismos»*, dentro de seis
> meses alguien escribe *«está muy molesto → no le pidamos verificar
> identidad»* o *«está desesperado → agenda sin confirmar»*.
>
> Eso violaría el ADR **no por habilitar algo, sino por dejar de ejecutar una
> regla**. Es el modo de fallo que el invariante 2 no cubría: se vigilaba que
> la situación no *abriera* puertas y no que *apagara* controles. Sin la
> restricción a automatismos iniciados por el sistema, «situación» acaba
> siendo una segunda política de control disfrazada de empatía.

**El contrato, que es lo único que este ADR cierra:**

| Camino | ¿Lee situación? |
|---|---|
| **Reactivo** — responder a un mensaje del cliente | **nunca** |
| **Proactivo** — lo que el sistema inicia | **sí, y solo para cancelar un automatismo**. Nada más |

**Lo que este ADR NO decide: dónde vive el camino proactivo.** Hoy el único
consumidor conocido es `nudge_abandoned_flows`, dentro de `policy.py`. Extraer
un módulo ahora significaría diseñar su API alrededor de un solo caso, y lo que
viene no se conoce todavía: recordatorio de cita, seguimiento postoperatorio,
refuerzo de vacuna, encuesta, aviso de laboratorio. La forma correcta se ve
cuando se ven varios, no uno (decisión del PO, 2026-08-01).

> **Quién dispara la extracción: el propio gate.** El gate estático prohíbe que
> `policy.py` importe `situation` — y el camino proactivo vive ahí dentro. El
> día que alguien implemente una supresión por situación, CI se pone en rojo, y
> ese es exactamente el momento en que la presión arquitectónica existe. El
> arreglo entonces **no es relajar el gate**: es sacar el camino proactivo de
> `policy.py`.
>
> Así el pendiente no depende de que alguien lo recuerde ni envejece en una
> nota al pie: se cobra solo, y en el momento correcto.

Verificado al cerrar la Fase 1: `policy.py` tiene **cero** referencias a
`situation`; el único consumidor es `prompts.py`, que la publica al modelo. La
arquitectura no contradice este ADR en ningún commit.

#### El modelo puede ignorar la situación por completo

Que solo el modelo la lea no significa que deba responder a ella.

> **La situación es información disponible, no una obligación de respuesta.**

Sin esta frase, alguien leerá *«si hay una situación detectada, hay que
atenderla»* — y eso convierte la situación en un gate **social** en vez de uno de
código, que es el mismo daño con otro disfraz: los invariantes 1-2 quedarían
cumplidos al pie de la letra y violados en la práctica. El resultado sería el tic
del asistente ansioso: tres líneas empáticas donde sobraban cuatro palabras.

Ante *«jaja sí perdón»*, la respuesta correcta puede ser *«jaja no te preocupes
🙂»*, puede ser seguir con lo que estaban haciendo, y puede ser las dos cosas.
**Quien decide es el modelo, que es quien está leyendo a la persona.**

### 3. Enmienda a R13 (p55 §6) — el gate se parte en dos

R13 vigente dice: *«un hecho que ninguna fila del árbitro lee es código muerto»*,
con gate **estático** y vinculante.

Los hechos de situación, por diseño (§2), ninguna fila del árbitro los lee. **Con
R13 tal como está escrita, el gate estático los clasifica como código muerto y los
borra: la regla, literalmente, prohíbe la empatía.**

R13 conflaciona dos clases de hecho. Se separan, con gates **simétricos**:

| | Hecho de control | Hecho de situación |
|---|---|---|
| Cambia | *qué pasa* | *cómo se dice* |
| Gate vinculante | **R13 tal cual**: si ninguna fila del árbitro lo lee, es muerto | **el simétrico**: si una función de decisión lo lee, **es un bug** |
| Se comprueba | estáticamente | estáticamente (`arbiter.py` y las salvaguardas no pueden importarlo) |

La misma disciplina, espejada. Un hecho de situación que empieza a gatear se
detecta igual de mecánicamente que un hecho de control que nadie lee.

> El análisis estadístico sigue siendo **reporte, no gate**, para ambas clases
> (p55 §6 sin cambios): un hecho puede ser determinante en el 0.01 % de los turnos
> y ser irrenunciable.

### 4. Reparto de autoridad: preempción vs. contención

El principio *«el LLM propone, el sistema dispone»* se implementó como *«el sistema
dispone **y además escribe el mensaje»***. Son cosas distintas.

| | **Preempción** | **Contención** |
|---|---|---|
| Cómo | el router intercepta antes de que haya conversación | la conversación ocurre; el sistema limita lo que puede *causar* |
| Cuesta | humanidad — el modelo nunca ve el mensaje | nada conversacional |
| ¿Depende del modelo? | no | **tampoco** |
| Hoy | 28 salidas de router, 31 plantillas | `_verification_ok`, `guards.check_output`, args staged de tier-2 |

> **Criterio vinculante: preempción SOLO donde la contención es imposible** — es
> decir, cuando el daño ocurre *al decir* y no hay acción posterior que
> interceptar.

Pasan el criterio y **siguen siendo deterministas**: kill switch · contacto
bloqueado · humano activo / handoff pendiente · **urgencia** · petición explícita
de humano · opt-out · **afirmativa a un `pending_action`** · presupuesto agotado ·
entrante sin texto.

No lo pasan y salen del router: tamiz de identidad, los tres retos, «¿eres una
persona?», agradecimientos, saludo, pagos.

**La afirmativa a un `pending_action` merece mención expresa**: ejecuta argumentos
ya staged sin volver al modelo (TC-SEC-03). Si pasa al planner, un «sí» puede
ampliar el alcance de lo confirmado. **No se mueve en ninguna fase.**

### 5. La verificación de identidad: el modelo conversa, el código dictamina

La barrera que impide que un contacto sin verificar toque datos personales **no es
el router**: es `_verification_ok`, evaluada en `run_tool`, por debajo del modelo y
ajena a la conversación. Es lo que hace seguro dejar conversar al LLM sobre
identidad — una tool personal rebota sin tocar nada.

Se hace explícito lo que hasta hoy era implícito:

- El modelo **aporta el candidato**; `identity.try_verify_by_*` **dictamina**
  contra la base. `ContactIdentity.verification_level` tiene exactamente dos
  escritores, ambos en `identity.py`.
- Una herramienta de identidad **nunca devuelve nombres ni conteos de
  candidatos**. El modelo no puede enumerar lo que no sabe (G4: *el cliente
  aporta, el sistema verifica*).
- **Comportamiento uniforme exista o no el registro.** Pedir los últimos 4 dígitos
  no puede significar «encontré a alguien con ese nombre», o la herramienta se
  vuelve un oráculo de existencia. El código actual ya lo resuelve así
  (`_seed_family_challenge` siembra aunque no haya candidatos); aquí se eleva a
  invariante.

### 5-bis. Enmienda a p55 · el árbitro CLASIFICA el desenlace del compromiso

> **Sobre el verbo, que no es cosmética** (precisión del PO): no *gobierna* el
> compromiso — lo **clasifica**. «Gobernar» implica autoridad; lo que hace es
> **interpretar** qué fue de la promesa en este turno. Aplicar los efectos que
> se derivan de esa interpretación es del **ejecutor**, y esa separación ya
> estaba en p55 A6 («el ejecutor consume veredictos; no los reinterpreta»).
> Nombrarlo «gobernar» reintroducía por la puerta de atrás la autoridad que
> esta enmienda le quita.

> **Estado: PROPUESTA — pendiente de aceptación del PO.** Requisito de la Fase 4
> del plan É-F5; p55 §8 exige que entre por ADR **antes** de implementarse.

**El problema, medido.** `arbiter.decide` tiene hoy **cero call sites de
producción**: el único era `policy._check_interruption`, dentro de la FSM que la
Fase 2 retiró. Antes de eso tenía uno, alimentado por **un solo hecho**
(`interrupts`), así que una capa entera —módulo, ADR, presupuesto de ramas y
suite propia— funcionaba efectivamente como `bool → {DEVIATE, CONTINUE}` y tres
de sus cinco veredictos eran inalcanzables.

El diagnóstico de É-F5 fue que el árbitro no está mal construido: **recibía un
hecho mal calculado**. Con percepción (Fase 1) existen por fin
`proposes_other_commitment` y `client_declined`.

**Qué cambia:**

| | p55 (vigente) | Enmienda |
|---|---|---|
| Pregunta que responde | *¿qué debe pasar con este turno?* | ***¿qué le pasó al compromiso en este turno?*** |
| Cuándo corre | **antes**, como puerta | **al final**, sobre lo que ya ocurrió |
| Qué hace con ello | decide | **clasifica**; el ejecutor aplica |

**La consecuencia de mover el «cuándo» es la que importa: deja de ser un gate y
pasa a ser una clasificación *post-hoc*.** Ya no decide si el cliente recibe una
plantilla o una respuesta del modelo —eso lo decidió el planner— sino qué quedó
de la promesa: continuó, se desvió, la suplantó otra, la abandonaron.

Eso **refuerza** los invariantes de p55 en vez de relajarlos: el árbitro sigue
siendo puro (§1), sigue sin producir contenido (§2), y ahora es literalmente
incapaz de afectar lo que el cliente lee, porque corre después de que el texto
esté escrito.

> **Invariante nuevo, y cierra la puerta que quedaba abierta** (aportación del
> PO): **los efectos derivados de un veredicto aplican únicamente al estado
> persistente del compromiso, y NUNCA al mensaje ya emitido en ese turno.**
>
> Sin esta frase, dentro de seis meses alguien escribe:
>
> ```
> planner → el LLM responde → el árbitro dice SUPPLANT
>        → «ah, entonces reemplazo la respuesta»
> ```
>
> No. **Ese turno ya ocurrió.** El cliente ya leyó el mensaje. Lo único que el
> veredicto puede tocar es qué queda registrado del compromiso para el turno
> siguiente.

#### La propiedad que esto habilita: el árbitro se puede volver a correr

Consecuencia señalada por el PO, y es la más valiosa de la enmienda. Con el
árbitro **puro** (p55 A1) **y post-hoc**, sus veredictos se pueden **recalcular
sobre conversaciones históricas**:

```
Conversation → mensajes ya guardados → hechos recomputados → árbitro NUEVO
                                                                  ↓
                                                    comparación con lo que dijo
                                                    el árbitro de entonces
```

Sin volver a llamar al LLM, sin coste y en milisegundos. Antes era imposible
porque el árbitro **intervenía**: recalcularlo habría cambiado la conversación
que se pretendía medir.

Habilita tres cosas que hoy no existen: **comparar versiones del árbitro** ·
**validar una regla nueva contra tráfico real antes de desplegarla** · **medir
el efecto de un cambio arquitectónico** sobre conversaciones ya ocurridas. Es lo
que p55 §Consecuencias prometía —«el tráfico real se vuelve suite de
regresión»— y que no podía cumplirse del todo mientras el árbitro fuera una
puerta.

> **Y de rebote impone una disciplina útil: los hechos deben seguir
> produciéndose de forma determinista.** El día que un `TurnFact` venga del
> modelo, la reproducción exige volver a llamarlo y la propiedad se pierde. La
> replicabilidad deja de ser un beneficio y pasa a ser una razón estructural
> para que los productores de hechos sigan siendo matchers y no generación.

**Qué NO cambia:** el conjunto cerrado de cinco veredictos · `CommitmentView` y
`TurnFacts` como fotos inmutables (A2/A3) · el presupuesto de ramas (A4) · la
regla A6 —el ejecutor consume veredictos, cada uno con su propio contador—, que
ahora **por fin cubre los cinco** en vez de la única frontera que existía.

**`TurnDecision.verdict` se cierra** al enum de cinco. Hoy guarda el nombre
interno de la salida del planner (`planner_reply`, `escalate`, `silent`…) porque
Fase 1 no tenía árbitro; era deuda declarada en el propio docstring del modelo.
El desenlace operativo del turno no se pierde: pasa a `facts_produced`, que ya
existe y es diagnóstico. Las filas históricas **no se reescriben** (append-only,
invariante 10 de p55): el enum aplica a filas nuevas y el reporte trata los
valores viejos como `legacy`, mismo patrón que `STATUS_CANCELLED_DEPRECATED`.

**Riesgo declarado.** Un árbitro post-hoc puede volverse decorativo por segunda
vez si nadie consume sus veredictos. La defensa es el criterio de salida de la
Fase 4 —los cinco veredictos con productor **y** ejecutor, cero filas con
oráculo incompleto— y la advertencia que ya vive en `arbiter.py`: si esto no se
cumple, es código muerto y se borra.

### 6. Extensión del invariante 8: `return_to` referencia un Factor declarado

p55 invariante 8: *un `Factor` sin `why` no compila* — `Factor.__post_init__`
levanta `ValueError`.

**Y aun así produjo un mensaje vacío en producción, dos veces seguidas.** La etapa
que el FSM estaba pidiendo (`return_to='titular'`) **no es un `Factor` declarado**
del compromiso de tamiz, así que `why_for()` devolvió `''` y el cliente recibió
literalmente `Te lo pido para  🙂`. `return_to` es un `CharField(max_length=32)`
libre y nadie comprueba que su valor exista en el catálogo.

> **La garantía se declaró estructural y se implementó sobre una tabla, mientras la
> máquina de estados seguía operando sobre strings de otra.**

Se cierra la clase de bug, no el caso: **`return_to` solo puede tomar el nombre de
un `Factor` declarado del compromiso**, verificable estáticamente.

### 7. Un turno sin avance de compromiso es un turno válido

`planner._settle_goal` incrementa `stall_turns` en cualquier turno que no llene un
slot — incluidos una pregunta, una disculpa y una broma. Tres de esos escalan a un
humano con *«creo que por aquí nos estamos enredando»*.

**El sistema cuenta la conversación del cliente como su propio atasco.** Es el
mismo error que É-F4 Fase 0 corrigió para los retos de identidad (R1: *una
no-respuesta nunca es una respuesta equivocada*) sin aplicarlo al detector de
estancamiento, que quedó con la regla vieja.

Estancamiento pasa a significar lo que dice su nombre: **el sistema no está
logrando avanzar**. Lo que sigue contando: el modelo llamando la misma herramienta
con los mismos datos, vuelta tras vuelta.

---

## Invariantes (vinculantes)

Los de p55 que se conservan no se repiten aquí; ver §Lo que NO cambia.

1. **Un hecho de situación que una función de decisión lee es un bug.** Gate
   estático: `arbiter.py` y las salvaguardas no pueden importarlo ni leerlo.
2. **La situación nunca gatea.** Ninguna capacidad, tool, escalada ni permiso
   depende de ella. **Y tampoco obliga al modelo**: es información disponible, no
   una obligación de respuesta — si no, el gate se reconstruye socialmente.
2-ter. **Válvula de un solo sentido** (enmienda del PO, 2026-08-01): la
   situación **puede inhibir un automatismo iniciado por el sistema** cuya
   oportunidad desapareció. **Nunca** puede impedir responder a un mensaje del
   cliente, ni omitir una validación, salvaguarda o decisión de negocio. Las
   tres condiciones son acumulativas: no provocado por un mensaje nuevo del
   cliente · iniciado por el sistema · su ausencia no empeora la seguridad ni
   rompe una garantía. **El modo de fallo que cierra no es la permisividad sino
   la OMISIÓN**: «está molesto ⇒ no le pidamos verificar» viola este ADR aunque
   no habilite nada.
2-bis. **Todo mensaje atraviesa percepción**, exista o no un compromiso abierto,
   y **antes** de consultar si lo hay. Percibir solo cuando hay algo que llenar
   es extracción con otro nombre.
3. **La situación nunca compite con una salvaguarda.** *«Estoy desesperada, mi
   perro no respira»* es urgencia, primero, siempre, sin pasar por el modelo.
4. **La situación nunca lleva texto del cliente al rastro** — enums y booleanos
   (hereda la regla de PII de p55 inv. 11 / R15).
5. **Elevar el nivel de verificación a `confirmed_in_chat` ocurre únicamente en
   `identity.py`**, evaluando contra la base — jamás por afirmación del modelo.

   > **Corrección (2026-08-01, misma fecha).** La redacción original decía «dos
   > escritores, ambos en `identity.py`». Era imprecisa: el gate estático, en su
   > primera corrida, encontró un **tercer** sitio que elevaba el nivel (el
   > auto-vínculo del alta, en `tools.py`) y otros que escriben el campo sin
   > afirmar identidad. Lo que importa es la **dirección**, no el número de
   > asignaciones: fijar `phone_match` (`services.py`, resolución por teléfono)
   > no habilita ninguna tool personal —`_verification_ok` exige
   > `confirmed_in_chat`— y bajar a `unknown` (`views.py`, staff revocando un
   > vínculo) va en la dirección segura.
   >
   > El tercer elevador se **movió a `identity.py`** (`link_self_registered`) en
   > vez de añadirle una excepción al invariante: la idea es cerrar el hueco, no
   > silenciar el gate que lo detecta. Es legítimo elevar ahí sin reto porque el
   > `Owner` se acaba de crear a partir de ese mismo contacto — no hay
   > expediente previo que suplantar, que es lo que el reto existe para impedir.
6. **Una herramienta de identidad no revela nombres ni conteos**, y se comporta
   igual exista o no el registro.
7. **`return_to` solo puede ser el nombre de un `Factor` declarado** del
   compromiso (extensión del inv. 8 de p55).
8. **Preempción solo donde la contención es imposible.** Añadir una salvaguarda
   nueva exige justificar por qué el daño no se puede contener después.
9. **Un turno con señal conversacional no incrementa el estancamiento.**

## Lo que NO cambia

Auditoría explícita de los doce invariantes de p55: **diez intactos, uno se
extiende, uno se enmienda.**

| # | Invariante p55 | Estado |
|---|---|---|
| 1 | el árbitro es puro | intacto |
| 2 | el árbitro no produce contenido | intacto |
| 3 | conjunto cerrado de veredictos | intacto (cambia su jurisdicción, no su forma — §Fuera de alcance) |
| 3-bis | el ejecutor consume, no reinterpreta; cada veredicto su contador (A6) | intacto |
| 4 | las salvaguardas preemptan al árbitro | intacto, y **reforzado** por §4 |
| 5 | una tool no termina turnos ni escribe copy | intacto |
| 6 | un compromiso nunca desaparece | intacto |
| 7 | `desviar` sin dirección de retorno es inválido | intacto |
| 8 | un `Factor` sin `why` no compila | **extendido** (§6) |
| 9 | **R13** · un hecho que el árbitro no lee es código muerto | **enmendado** (§3) |
| 10 | `TurnDecision` append-only; el runtime jamás la lee | intacto |
| 11 | `TurnDecision` y su agregado sin PII | intacto |
| 12 | todo cambio semántico pasa por ADR | intacto — **esto es su aplicación** |

Y, fuera de p55, **sin tocar en ninguna fase**:

- `ToolExecutor`, loopback HTTP, RBAC del rol AGENT, `ToolExecution`.
- La confirmación tier-2 completa: parafraseo por plantilla, args staged,
  ejecución verbatim (TC-SEC-03).
- `_verification_ok` y la revalidación de tier/verificación/ownership en
  `run_tool`.
- `guards.check_output` (G1/G2/G3/G7).
- El aislamiento multi-tenant y la frontera del subsistema.
- La **FSM de negocio** (`ALLOWED_TRANSITIONS` en `appointments`, estados de
  `billing`): está al otro lado de la frontera HTTP y **es inalcanzable desde
  aquí**. Ningún rediseño conversacional puede degradar la corrección del negocio.

---

## Alternativas descartadas

1. **Publicar la situación como enum consumido por el árbitro**
   (`situacion=='desesperada' → tono='calmado'`). Sería la tercera máquina de
   estados del subsistema, y peor que las dos anteriores porque la emoción no
   discretiza. Es el modo de fallo que los invariantes 1-2 existen para impedir.
2. **Mantener el compromiso como raíz y solo añadir hechos de situación.**
   Implementable y **ineficaz**: el agente recibe *«está molesta»* junto a
   *«me_falta: [fecha]»* y la agenda sigue mandando. Es el fallo documentado de la
   v1 del plan É-F5.
3. **Validar los hechos de situación con el aparato de los datos** (validador +
   umbral). No existe un validador para un estado de ánimo, y no hace falta: el
   gate del invariante 1 hace que equivocarse cueste cero.
4. **Una segunda llamada al LLM dedicada a percepción.** Duplica costo y latencia
   por turno. Se prefiere reusar el bucle de tools existente y **decidir con
   datos** si hace falta (medición en la Fase 2 del plan: cuántas veces el modelo
   ejerce la percepción por su cuenta).
5. **Tres ADRs separados** (propuesta inicial del PO). Permitiría implementar dos
   de los tres y creer que se terminó, sin mover el comportamiento — ver §Contexto.
6. **Absorber el árbitro dentro del planner.** Ésta es la alternativa real —
   nadie propondría borrarlo; lo que invita es **fusionarlo**, porque hoy es
   efectivamente `bool → {DEVIATE, CONTINUE}` con un solo call site y parece una
   capa de más.

   Se rechaza por una razón distinta de la que rechazaría el borrado, y es la
   importante: **fusionarlo le quita la pureza**. Hoy `arbiter.decide` es una
   función sin DB, sin red y sin efectos, así que un veredicto se puede reproducir
   contra el corpus **sin llamar al modelo, en milisegundos y a costo cero** — es
   lo que permite que el tráfico real sea suite de regresión (p55 §Consecuencias).
   Dentro del planner, comprobar un veredicto exigiría un LLM.

   Y el diagnóstico de fondo: el problema nunca fue el árbitro, sino que
   **recibía un hecho mal calculado**. Con percepción, los hechos que le faltaban
   (`proposes_other_commitment`, `client_declined`) existen y tres de sus cinco
   veredictos dejan de ser inalcanzables. Fusionarlo justo cuando empieza a servir
   sería el peor momento posible.
7. **Eliminar el router entero.** Rechazado: sin él la urgencia pasaría a ser una
   cuestión de política discutible (p55 §1). Encoge de 36 salidas a 9; no
   desaparece.

---

## Consecuencias

- (+) Un dato que el cliente aporta por su cuenta **tiene dónde vivir**. Es la
  causa directa del defecto que abrió esta épica y ninguna regla vigente podía
  cerrarla.
- (+) El estado emocional de la persona pasa a ser **representable**. Hoy
  `matchers.is_complaint_or_meta` detecta bien que el cliente está molesto y su
  único consumidor es decidir si se antepone un aviso de horario.
- (+) La clase de bug de `Te lo pido para  🙂` desaparece por construcción (§6), no
  por parche.
- (+) El árbitro deja de ser decorativo: con hechos reales, tres de sus cinco
  veredictos dejan de ser inalcanzables.
- (−) **Sube el costo por turno.** 28 de 36 salidas del router cuestan hoy cero
  llamadas al modelo; muchas pasarán a costar 1-2. Es el precio explícito de la
  decisión y se mide con `LLMCall.cost_estimate`, cuya línea base ya está tomada
  (É-F5 Fase 0).
- (−) **Sube la latencia** en turnos que hoy responden en milisegundos. Las
  urgencias **no**: siguen siendo plantilla y no pasan por el modelo.
- (−) Menos determinismo **en el fraseo y el orden de las preguntas**. Intacto todo
  lo demás: quién puede hacer qué, qué se escribe en el dominio, qué se dice sobre
  dinero, medicina y promesas, y qué se ejecuta tras un «sí».
- (−) **Sube la variabilidad conversacional**, y es un costo aparte del anterior:
  dos conversaciones idénticas pueden terminar con dos respuestas distintas. No es
  malo —una persona tampoco contesta igual dos veces— pero **cambia el sistema** y
  hay que reconocerlo:

  | Se pierde | Se conserva |
  |---|---|
  | **Reproducibilidad**: repetir la entrada ya no garantiza la misma salida | **Reconstructibilidad**: `Message` + `TurnDecision` + `ToolExecution` permiten reconstruir exactamente qué pasó en una conversación concreta |

  Consecuencias prácticas: reproducir un fallo reportado se vuelve más difícil
  (hay que leer la conversación, no repetirla), y comparar dos versiones exige más
  muestras. Lo que **no** se rompe es la suite: la spec §1.3 ya prohibía afirmar
  igualdad literal sobre texto del modelo, y el corpus de la Fase 0 afirma sobre
  conducta observable —repetición, handoff, estado en la base—, nunca sobre
  palabras.
- (−) Más superficie de prompt injection al publicar más estado. Mitigado: el
  bloque es semántico en español (no claves internas), los guards de jerga ya
  bloquean `public_id`/`invoice`/`draft`, y **publicar no autoriza**.
- (−) Riesgo nuevo de **deriva de verbosidad**: liberar al modelo mueve la
  artificialidad de `FSM → 15 palabras` a `LLM → 180 palabras`. Se instrumenta
  (palabras por mensaje, p50/p90, segmentado por `prompt_version`), **no se
  guardea**: sin precedente no se añade un gate (p55 §9.0).

---

## Fuera de alcance de este ADR

- **La jurisdicción del árbitro** (pasar de autoridad del turno a autoridad del
  compromiso) y el cierre de `TurnDecision.verdict` al enum de cinco: es la Fase 4
  del plan y entra por **una enmienda posterior a p55**, con su propia línea base.
- **Cómo se deriva la situación** (matchers ascendidos vs. lectura del modelo): es
  implementación, se decide con la medición de la Fase 2.
- **El resumen rodante** (`Conversation.summary`, campo existente sin escritor).
- **`low_confidence` por slot**: mecanismo completo que el modelo nunca ejercita
  (manda 1.0 siempre). Se retira o se hace funcionar en su propio carril.
- Transcripción de audio, cambio de proveedor LLM, botones interactivos de
  WhatsApp.

---

## Propiedad del contrato

Este ADR **enmienda p55** y hereda su regla de gobierno (p55 §8): todo cambio
semántico del runtime conversacional entra por ADR — enmienda a p55/p56, o un ADR
nuevo que los supersede. Campo añadido opcional o valor de enum que pase
ortogonalidad y cardinalidad: bump del snapshot de contratos, sin ADR.

Los hechos de situación **entran al snapshot al nacer**, con su gate simétrico
(invariante 1). Un presupuesto añadido después no se añade nunca (p55 A4).
