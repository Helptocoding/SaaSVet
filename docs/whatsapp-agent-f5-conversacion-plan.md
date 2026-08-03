# É-F5 — La conversación al centro · plan de arquitectura

**Fecha**: 2026-07-31
**Estado**: propuesta, pendiente de aprobación del PO
**Base**: [auditoría de arquitectura 2026-07-31](whatsapp-agent-auditoria-arquitectura-2026-07-31.md) · [auditoría de rigidez 2026-07-29](whatsapp-agent-auditoria-rigidez-2026-07-29.md) · [ADR p54](decisions/2026-07-25-p54-agent-goals-and-binding-rules.md) · [ADR p55](decisions/2026-07-30-p55-turn-authority-and-commitments.md) · [spec funcional](whatsapp-agent-functional-spec.md)
**Alcance**: gobierno conversacional del subsistema `apps/agent`. **No toca** seguridad multi-tenant, RBAC, FSM de negocio ni contabilidad.

> **Lo que este plan NO es**: no es "deja que el LLM haga todo". El LLM gana **voz y
> conducción**, no permisos. Las cuatro barreras que hoy protegen dinero, agenda,
> datos personales y salud (`_verification_ok`, tier-2 con args staged,
> `guards.check_output`, RBAC del rol AGENT) quedan **intactas y sin excepciones**.
> Lo que cambia es quién decide *qué se dice y en qué orden*.

---

## Revisión del PO · 2026-07-31 (v2) — el plan pensaba en arquitectura, no en conversación

La v1 de este documento cambiaba **quién** gobierna la conversación y no cambiaba
**qué pregunta se hace el sistema**. Seguía siendo *«¿cómo cumplo el compromiso?»* en
vez de *«¿qué necesita esta persona?»*. El diagnóstico del PO es correcto y el riesgo
que nombra es exacto:

> **Pasar de FSM-driven a Commitment-driven. Mismo síntoma, más elegante.**

La evidencia es medible sobre el propio texto de la v1:

| Vocabulario de máquina | | Vocabulario de persona | |
|---|---|---|---|
| `tool` | 56 | `cliente` | 21 |
| `hecho` | 39 | `persona` | 9 |
| `compromiso` | 31 | `usuario` | 2 |
| `guard` | 30 | `tono` | 1 |
| `estado` | 28 | `escuchar` | 1 |
| `veredicto` + `planner` | 36 | **`empatía`** | **0** |
| `percepción` | 17 | **`siente`** | **0** |

≈230 contra ≈32. Un documento sobre conversación en el que las palabras *empatía* y
*siente* no aparecen ni una vez no está hablando de conversación.

**Por qué ocurrió, que es lo útil**: heredé la ontología de p54/p55, donde una
conversación *es* una secuencia de compromisos. Cuestioné **quién posee** el
compromiso (la tool → la conversación) y nunca cuestioné **si el compromiso es el
objeto raíz correcto**. Es exactamente el fallo que le diagnostiqué a É-F4
—preguntar quién tiene la autoridad del turno sin preguntar cuánta conversación llega
a la capa que conversa— repetido un nivel más arriba.

**Cinco defectos concretos de la v1**, para que la corrección no se quede en el
prólogo:

| # | Defecto de la v1 | Dónde |
|---|---|---|
| 1 | El detector de estancamiento **castiga la conversación**: un turno social ("jaja sí perdón") no avanza ningún slot ⇒ `bump_stall +1`; tres ⇒ handoff. La v1 lo conservaba explícitamente | `planner._settle_goal` · v1 §11.9 |
| 2 | La percepción existía **para alimentar el compromiso** ("hechos aportados → validador → compromiso"). Eso no es percibir: es capturar slots con la boca más ancha | v1 §5.1, §5.2 |
| 3 | `identify_client` es una herramienta de **verificación**, no de percepción. No puede percibir *«mi perro está nervioso»* | v1 §5.2 |
| 4 | El estado publicado abría con las obligaciones del sistema (`me_falta`), no con la persona. El orden en un prompt encuadra el turno | v1 §5.3 |
| 5 | El diseño de conversación paralela traía la agenda incorporada: *«contesta el porqué **Y vuelve a pedir el dato**»*. Un humano a veces solo contesta | v1 §7.2 |

Lo que la v2 añade: **§2bis (la situación)**, tres principios nuevos (C10-C12), el
reordenamiento del estado, la corrección de los cinco defectos, y **§9bis**, que
sustituye la métrica de software por métrica de conversación. Y un conflicto de
reglas que había que destapar: **R13, tal como está escrita, prohíbe estructuralmente
la capa que el PO pide** (§2bis.4).

### v3 — economía conversacional

Segunda ronda del PO sobre el mismo §12bis. La v2 trataba la verbosidad como un
problema de **tono** y la delegaba a revisión humana; es un problema de
**eficiencia**, y por tanto medible. Liberar al modelo no elimina la artificialidad:
la mueve de `cliente → FSM → 15 palabras` a `cliente → LLM → 180 palabras`. Las dos
se sienten a máquina; la segunda llega sola, empujada por el crecimiento del prompt,
y ninguna revisión humana detecta una pendiente de tres palabras por mes.

Añade el principio **C13** (economía conversacional, del PO) con cuatro consecuencias
derivadas —longitud, **una sola decisión por mensaje**, no repetir contexto, no
explicar de más—, reescribe §12bis como riesgo de deriva y no de estilo, y añade
**§9bis.1**: palabras por mensaje del agente como *leading indicator*, segmentada por
`author_type` y `prompt_version`, en p50/p90, y **nunca como objetivo**.

### v4 — el propósito del turno, y la primera respuesta útil

Dos precisiones del PO sobre C13 y sobre la observabilidad.

**(a) «Avanzar» era demasiado estrecho.** *«Mi perro acaba de morir»* no avanza
preguntando: avanza acompañando. C13 pasa a decir **«la longitud mínima que cumpla el
propósito de ese turno»** — que a veces es tranquilizar, reconocer un error, explicar,
acompañar, confirmar o cerrar. El propósito **no se persiste ni se enumera**: se
aplica al escribir y se juzga en corpus, o sería la FSM #3 con nombre nuevo.

Esta precisión destapó un defecto real y vivo: **`nudge_abandoned_flows` no mira nada
de lo que pasó en la conversación.** Manda *«¿Seguimos con tu cita?»* 60 minutos
después, con la misma indiferencia si el cliente acaba de perder a su mascota o si
acaba de decir *«déjame pensarlo»* (el segundo caso es el flujo normal del producto,
no una tragedia). Es el mismo error de oportunidad que É-F4 Fase 2 ya corrigió para
el aviso de fuera de horario y que nadie aplicó al recordatorio. **C13 gobierna
también los mensajes que el sistema inicia.**

**(b) Tercera métrica: turnos hasta la primera respuesta útil** (§9bis.2). Corpus
review con dos proxies mecánicos exactos. Es, además, la primera métrica que
**comprueba R9** — una regla que el proyecto tiene desde la auditoría de rigidez, que
p55 §5 volvió estructural, y que nunca se ha verificado en una conversación real.

### v5 — gobernanza de los principios

Riesgo que señala el PO sobre **este documento**: trece principios excelentes que en
seis meses son veintisiete y vuelven a ser una máquina de estados sin que nadie lo
decida.

No es hipotético — **ya pasó en este repo**: hay dos series `R` en el mismo espacio de
nombres (R1-R13 = reglas conversacionales de la auditoría de rigidez; R14-R16 =
riesgos de `whatsapp-agent-architecture.md`), el código cita ambas indistintamente
(`guards.py:205` → R2 regla; `executor.py:81` → R15 riesgo; `policy.py:105` → R16
riesgo) y un documento ya las confunde por escrito. La colisión es invisible solo
porque los rangos no se solapan por casualidad.

§2.1 añade la **regla de admisión del PO** (precedente en producción + no derivable)
con cuatro mecanismos que la hacen exigible (P1-P4), y la **regla de salida** que
faltaba: *un principio que se convierte en mecanismo deja de ser un principio* — que
es lo que hace que la lista **encoja** mientras el sistema se endurece, tal como hizo
p54 con el prompt.

Primera aplicación, sobre la lista propia: **13 → 11**. `C8` retirado (era R9, ya
impuesto por el compilador), `C11` fusionado en `C10` (era, por mi propia redacción,
«la mitad enforceable»), `C1` anotado como candidato. Los números **no se reutilizan**
— misma disciplina de deprecación que el resto del repo.

### v6 — sin números en la filosofía, y el mal uso previsible

Dos correcciones del PO sobre §2.1.

**(a) Fuera el «≤6» de los ontológicos.** Seis no es una propiedad de las
conversaciones: es una propiedad de este documento hoy. Convertirlo en objetivo trae
Goodhart de vuelta — **el mismo aviso que este documento escribe para C13 y que
incumplí dos secciones después**. Se sustituye por el criterio: *excepcionalmente
pocos y estables; crecer exige demostrar una propiedad fundamental de toda
conversación, no derivable de otra*. De ahí sale una distinción que faltaba: **el
examen de admisión no es el mismo para los dos tipos** — un operativo se justifica con
un precedente de producción (P1); un ontológico necesita **universalidad**, y una
conversación real no basta.

**(b) Nace P5: cada principio declara su mal uso previsible.** *¿Qué mala decisión
permitiría si se leyera demasiado literalmente?* P1-P4 solo cubrían un lado de la
rotura: **P2 detecta incumplimiento, P5 detecta celo.** El ejemplo del PO es el mejor
argumento: *«una decisión por mensaje»* llevado al extremo prohibiría *«tengo estos
tres horarios, ¿cuál prefieres?»*, que es el ejemplo con el que se justificó la regla.

P5 se aplica retroactivamente a los once principios vivos, y en la primera pasada
encuentra algo que P1-P4 no podían ver: **la primera colisión entre dos principios**
(C6 «un mensaje es varias cosas» vs C13 «longitud mínima»), que resulta ser falsa
porque gobiernan mitades distintas del turno — percepción y producción. Era
exactamente el riesgo que motivó §2.1.

### v7 — P6, la optimización miope

Última pieza de gobernanza, del PO, y es un modo de fallo **distinto** de P5: no hace
falta leer mal C13 para romper el sistema, basta con **optimizarlo**. Se celebra menos
palabras, menos preguntas, menos turnos; el agente contesta *«Sí.» «No.»
«Entendido.»*, cumple C13 en todos los mensajes, y la conversación es pésima. En P5
falla una persona en una decisión; en P6 **no falla nadie** y solo se ve en el
agregado.

> **P6 · Cada principio con un número asociado declara qué emergería si ese número
> fuera el KPI principal del equipo.**

Un principio no se defiende de Goodhart escribiendo un principio mejor. Se defiende
**con un contrapeso** (otra métrica que empeore al maximizar la primera) o
**declarando que nunca es un KPI** cuando no existe contrapeso honesto —el caso de
`tasa_handoff`, donde minimizar significa no escalar y el costo de una urgencia no
atendida no aparece en ningún tablero. Detalle en §2.1.

Dos cosas que P6 destapó en su primera pasada:

1. **La tercera métrica del PO (§9bis.2) era ya el contrapeso de la segunda**, sin que
   nadie lo hubiera buscado. El conjunto quedó auto-frenado por instinto.
2. **La métrica insignia de este documento, maximizada, borra las salvaguardas.**
   Llegar al 100 % de mensajes redactados por el agente exige eliminar las plantillas
   que quedan, que son precisamente las de urgencia, opt-out y handoff. Que el peor
   caso de P6 estuviera en la métrica bandera del propio plan es el mejor argumento a
   favor de P6.

### v8 — el techo sin número, y quién persigue cada métrica

**(a) Fuera el «70-85 %».** La v7 defendió la métrica insignia con un rango fijo, que
es exactamente el `≤6` retirado una revisión antes — **el mismo error, dos veces, en
el mismo documento**. Y eso ya no es un descuido: es evidencia de que **avisar de
Goodhart no basta; hay que sacar el número de la frase.** Reformulado como propiedad
(del PO): *el porcentaje nunca puede acercarse al 100 % porque hay clases de mensajes
cuya **literalidad es una garantía del sistema***. Con eso el techo pasa a depender de
la mezcla de tráfico —una semana con más urgencias lo baja, y es correcto— en vez de
ser una constante que marcaría esa semana como regresión. El rango observado sirve
para monitorizar; no entra al principio.

**(b) P6 gana su segunda mitad: ¿quién tendría incentivo real?** No toda métrica corre
el mismo riesgo. Dos hallazgos de la primera pasada:

- **Optimizar latencia reproduce el sistema actual.** El agente más rápido posible es
  el que responde con plantillas y nunca llama al modelo. Es una fuerza que tira de
  vuelta al formulario y la sostiene el equipo que implementa este plan. Protección ya
  existente y del tipo correcto: la spec fija la latencia como **umbral**, no como algo
  a minimizar. De ahí una regla general — **un umbral que respetar es Goodhart-seguro;
  un número que maximizar no lo es.**
- **El titular más peligroso no es una persona**: un evaluador automático o un reward
  model optimiza sin juicio y sin cansarse. `agent_eval` y `agent_quality` son el sitio
  exacto donde eso aterrizaría. Regla: pueden **medir** estas métricas; su puntuación
  **no puede ser función de ellas**.

**(c) Síntesis de las tres defensas** (patrón del PO): interpretación → P5 ·
optimización → P6 · implementación → gates. Más admisión y salida, el ciclo queda
cerrado por los dos extremos. Detalle en §2.1.

---

## 1. Diagnóstico — la causa, no los síntomas

### 1.1 El hecho que reencuadra todo

La conversación del brief se ejecutó con **cero llamadas al LLM**. Los cinco mensajes
del agente son constantes de `tier0.py` emitidas por `policy.evaluate`. No es que el
agente *parezca* un formulario: en esa conversación **no había agente**, había una
máquina de estados de 36 salidas devolviendo literales.

No es un caso raro. `policy.evaluate` tiene 36 puntos de decisión y **28 terminan el
turno sin consultar al modelo**. De los 22 salientes que emite `planner.py`, **uno
solo** lleva texto redactado por el modelo.

### 1.2 La causa arquitectónica

Tres capas de causa, de la superficial a la de fondo.

**Causa 1 — el reparto está invertido.** El sistema aplica determinismo donde menos
vale y lo quita donde más vale:

| | Determinismo | LLM |
|---|---|---|
| Vale cuando | el error es caro e irreversible: escribir una cita, mover dinero, revelar datos de otro cliente, dar una dosis | el error es barato pero la rigidez es carísima: entender una frase ambigua, reconocer frustración, explicar un porqué, retomar un hilo |
| **Hoy gobierna** | identidad, tamiz, retos, quejas, interrupciones, primer contacto — **lo emocionalmente delicado** | proponer horarios, rellenar 4 slots — **lo transaccional** |

**Causa 2 — el sistema fue diseñado para verificar que el usuario siga el flujo, no
para entender al usuario** (formulación del PO). No es una metáfora: se lee en las
firmas. `matchers.py` tiene 13 funciones públicas; 12 devuelven `bool` o un enum
cerrado y **ninguna devuelve un valor extraído del mensaje**. 368 líneas de análisis
de lenguaje que, por construcción, **no pueden emitir un dato**. La única pregunta
que la capa que lee al cliente sabe contestar es *«¿esto encaja con lo que yo
esperaba?»*. Nunca *«¿qué me dijo?»*.

**Causa 3 — el sistema trabaja en modo *pull*.** Persigue el siguiente dato
(`missing` → pregunto → espero → ¿llegó?). Una conversación humana es *push*: el
cliente suelta lo que quiere, en el orden que quiere, y el receptor **guarda todo y
después revisa qué falta**.

Verificable: **el único puerto de escritura de memoria del sistema es
`goals.capture`, y sus dos únicos call sites están en `tools.py`.** Un dato entra al
estado solo si (a) el router cede al planner, (b) el modelo llama una tool de
escritura y (c) mete el dato en los args. En la conversación del brief falló (a), en
los cinco turnos.

Por eso «Ana» no se perdió por falta de un extractor: **no había dónde ponerlo.**

> El sistema tiene **exactamente un** mecanismo push: `policy.py:200-203`, la
> verificación implícita por nombre de mascota. Es la única interacción del producto
> de la que ninguna auditoría se ha quejado nunca (`identity.py:11`: *«sube
> phone_match → confirmed_in_chat sin fricción»*). Y está apagada cuando
> `owner_id is None` — justo el caso que falló. **La prueba de que push funciona ya
> está dentro del sistema, confinada a una rama.**

### 1.3 El hallazgo más incómodo: el ADR ya describe el modelo correcto

ADR p55 §3 define la diferencia entre un slot y un compromiso:

| Slot (modelo viejo) | Compromiso (modelo nuevo) |
|---|---|
| un hueco en un formulario | una promesa hecha al cliente |
| **lo posee la tool que lo necesita** | **lo posee la conversación** |
| **solo se llena desde argumentos de tool** | **lo avanza cualquier cosa: el cliente, una lectura, un humano** |
| existe mientras la tool lo pida | existe hasta cumplirse o abandonarse |

La implementación está **íntegra en la columna izquierda**: `_goal_gate` abre el
compromiso con `goals.TOOL_GOALS[tool_name]` (lo posee la tool, se llama como la
tool) y `capture` solo se alimenta de `raw_args` (solo se llena desde argumentos).

**El ADR no está equivocado. El código no lo implementa.** Fase 3 de É-F4 movió los
tres retos de identidad a la tabla de compromisos —almacenamiento— pero conservó el
mecanismo de slots. Buena parte de este plan es **cobrar la deuda de p55**, no
inventar arquitectura nueva.

### 1.4 Por qué É-F4 no lo resolvió

É-F4 preguntó *«¿quién tiene la autoridad del turno?»* y construyó gobierno para
responderlo: árbitro puro, veredictos cerrados, `TurnDecision`, ciclo de vida de
compromisos, `Factor.why` estructural. Todo bien construido.

Ninguna auditoría preguntó lo anterior: **¿cuánta conversación llega siquiera a la
capa que conversa?** Por eso todo ese aparato gobierna turnos que el modelo nunca ve.
El síntoma más claro: `arbiter.decide` tiene **un** call site de producción con
**un** hecho (`interrupts`); tres de sus cinco veredictos son inalcanzables. Se
construyó el techo antes que el cimiento — el cimiento que falta es **percepción**.

---

## 2. Principios del nuevo modelo conversacional

Nueve. Los cuatro primeros son la inversión; los cinco siguientes la contienen.
Sirven para evaluar cualquier cambio futuro sin volver a discutir el fondo — misma
función que R1-R13 de la auditoría de rigidez, que **siguen vigentes** y no se tocan.

> **C1 · Escuchar antes de decidir.**
> Todo turno empieza registrando qué dijo el cliente, **antes** de evaluar qué toca
> hacer. Hoy es al revés: se evalúa la etapa y el mensaje solo se mira para ver si
> la satisface.

> **C2 · Todo lo que el cliente aporta se guarda, se lo hayan pedido o no.**
> El modo push, dicho como regla. Corolario: el sistema no tiene un "campo esperado"
> — tiene un conjunto de hechos que crece.

> **C3 · El estado se publica íntegro; el modelo narra desde él y jamás autoriza
> desde él.**
> P1 de la auditoría de rigidez. La mitad que suele olvidarse es la segunda: publicar
> no es permitir. `run_tool` revalida tier, verificación y ownership siempre.

> **C4 · La conversación la conduce el modelo; el sistema pone límites, no guion.**
> El sistema decide **qué se puede hacer** y **qué no se puede decir**. Nunca **qué
> frase toca ahora**.

> **C5 · Preempción solo donde la contención es imposible.**
> Ambas cumplen "la regla no depende del modelo"; solo la preempción cobra humanidad.
> La contención es imposible únicamente cuando el daño ocurre *al decir* y no hay
> acción posterior que interceptar (urgencia, opt-out, contacto bloqueado).

> **C6 · Un mensaje puede ser varias cosas a la vez.**
> Responder, preguntar, corregir y quejarse no son excluyentes. Cualquier
> representación que obligue a elegir una es incorrecta. *(Es el defecto exacto de
> `_is_interruption`, que implementa "interrumpe ⇔ pregunta ∧ ¬responde".)*

> **C7 · Repetir es defecto del sistema; el sistema debe notarlo y cambiar de
> estrategia.**
> R10 de la rigidez, con el corolario que faltaba: la detección debe cubrir **todos**
> los salientes, no solo los del modelo. Hoy el router repite verbatim y ningún
> contador sube.

> ~~**C8 · Una restricción se explica en voz de clínica o no se pide.**~~
> **RETIRADO (§2.1)** — es R9, y R9 **ya es mecanismo**: `Factor.__post_init__`
> levanta `ValueError` si falta el `why` (p55 §5). Un principio no restatea lo que el
> compilador ya impone. Su aporte real —*el `why` viaja como hecho publicado, no como
> plantilla `"Te lo pido para {why}"`*— es implementación y vive en §5.3.
> **El número no se reutiliza.**

> **C9 · Toda decisión sigue siendo explicable después.**
> R12 intacto. `TurnDecision` no se toca en su naturaleza: append-only, sin PII, el
> runtime jamás la lee.

Los tres siguientes son la corrección de la v2. C10 es del PO; C11 y C12 son la mitad
**exigible** de C10 — sin ellas, C10 es un póster.

> **C10 · La conversación nunca existe únicamente para obtener información.**
> Hay turnos cuyo propósito es tranquilizar, reconocer un error, agradecer o
> simplemente responder a una broma. Son turnos legítimos y completos. Un sistema que
> solo entiende turnos productivos es un formulario, aunque lo conduzca un LLM.
>
> **Exigibilidad** *(absorbe el antiguo C11, §2.1)*: **un turno que no avanza ningún
> compromiso es un turno válido**, y el detector de estancamiento no puede contar los
> turnos en que el cliente conversó. Hoy `_settle_goal` incrementa `stall_turns` en
> cualquier turno sin progreso de slot —incluidos una pregunta, una disculpa y una
> broma— y tres de esos mandan al cliente con un humano. El sistema mide la paciencia
> del cliente como si fuera su propio atasco. **Test**: tres turnos conversacionales
> seguidos no producen handoff.
>
> **Precedente**: conv del brief (turnos 3-5) y conv 12.

> ~~**C11**~~ **FUSIONADO en C10 (§2.1)** — era, por mi propia redacción, «la mitad
> enforceable de C10». Dos entradas para una idea. **El número no se reutiliza.**

> **C12 · Un compromiso es algo que el sistema DEBE, no una agenda a la que tiene
> derecho.**
> El compromiso no dicta el tema del turno. Si el cliente dice *«mi perro está
> nervioso»* con una verificación pendiente, el tema del turno es el perro. La
> verificación sigue ahí, sin caducar, sin repetirse y sin empujar.

> **C13 · Economía conversacional — cada mensaje debe maximizar el avance de la
> conversación con el menor esfuerzo cognitivo posible para el cliente.**
> *(Del PO.)* No es "sé cálido" ni "sé breve": es **no hacerle trabajo a la persona**.
> Una recepcionista no escribe párrafos; escribe *«Claro 😊»*, *«ya casi
> terminamos»*, *«gracias por esperar»*. Cinco palabras.

C13 es la contraparte necesaria de C4 y C10: liberar al modelo mueve el fallo del
otro lado. Antes: `cliente → FSM → 15 palabras`. Después, si nadie lo vigila:
`cliente → LLM → 180 palabras`. **Las dos cosas se sienten artificiales**, y la
segunda es la que llega sola.

**Precisión del PO sobre «avanzar» (v4).** La v3 decía *«la longitud mínima que
permita avanzar»*. Avanzar no siempre es el propósito:

```
Cliente:  «Mi perro acaba de morir.»
          → la conversación no avanza preguntando nada. Avanza acompañando.

Cliente:  «Perdón, creo que me expliqué mal.»
          → no hay que avanzar. Hay que reconstruir el entendimiento.
```

La formulación correcta es **la longitud mínima que permita cumplir el propósito de
ese turno**. Normalmente el propósito será avanzar; a veces será *tranquilizar ·
reconocer un error · explicar · acompañar · confirmar · cerrar*. Todos caben en C13.

> **El propósito del turno NO se persiste ni se enumera.** No es un campo, no es un
> enum y ninguna función lo lee — se aplica al escribir y se juzga en revisión de
> corpus. Convertirlo en `turn_purpose` sería exactamente la FSM #3 que §2bis.2
> prohíbe, con nombre nuevo.

Cinco consecuencias que se derivan de C13, y ninguna es de tono:

- **Longitud**: la mínima que cumpla el propósito del turno. Acompañar en dos líneas
  *cumple*; preguntar algo en ese momento **no cumple**, por corto que sea.
- **Una sola DECISIÓN por mensaje.** No "una sola pregunta": *«para el martes tengo
  10:00, 12:30 o 4:00 — ¿cuál te acomoda?»* son tres opciones y **una** decisión, y
  está bien. *«¿Cómo se llama tu mascota? ¿Y qué día te acomoda?»* son dos decisiones
  en un mensaje, y obliga al cliente a sostener las dos en la cabeza y contestar en
  orden. Es el defecto que aparece en cuanto el modelo conduce: agrupar preguntas es
  eficiente **para el sistema** y caro **para la persona**.
- **No repetir contexto que el cliente ya tiene.** Ya lo dice el prompt (*no repitas
  de vuelta lo que el cliente acaba de decir*) y con el modelo conduciendo pasa de
  consejo de estilo a regla de economía.
- **No explicar de más.** El `why` de un factor se dice **cuando lo preguntan**, no
  de forma preventiva en cada petición.
- **También gobierna los mensajes que el sistema inicia.** Un mensaje proactivo tiene
  que cumplir un propósito igual que uno de respuesta. Ver el defecto de abajo.

#### Defecto concreto que destapa esta precisión: el recordatorio no sabe qué pasó

`policy.nudge_abandoned_flows` envía **«¿Seguimos con tu cita? Aquí sigo para
ayudarte 🐾»** 60 minutos después de que un `pending_action` quedara sin responder.
Sus únicas condiciones son mecánicas: conversación activa, dentro de la ventana de
24 h, no bloqueado, no opt-out, sin nudge previo. **No mira absolutamente nada de lo
que ocurrió en la conversación.**

Dos consecuencias que hoy están vivas en el código:

| Situación | Lo que el sistema hace una hora después |
|---|---|
| El cliente dice que su mascota murió a mitad de agendar | *«¿Seguimos con tu cita?»* |
| El cliente dice *«déjame pensarlo»* → `T0_DEFER` responde *«aquí queda pendiente — me dices»* y **conserva** el `pending_action` | *«¿Seguimos con tu cita?»* — insistiendo sobre alguien que pidió explícitamente tiempo |

El segundo caso no necesita ninguna tragedia: ocurre en el flujo más normal del
producto. Ambos son el mismo defecto — **un mensaje proactivo que no tiene noción de
oportunidad**, que es el mismo error de INT-03 que É-F4 Fase 2 ya corrigió para el
aviso de fuera de horario (*«un aviso correcto en el momento equivocado es ruido»*) y
que nadie aplicó al nudge.

Corrección: el nudge lee la **situación** (§2bis) antes de disparar, y `T0_DEFER`
deja de ser compatible con un recordatorio automático a los 60 minutos. Va en la
Fase 1, junto con los hechos de situación de los que depende.

> **C13 se mide, nunca se fija como objetivo.** La longitud es un *proxy* de esfuerzo
> del cliente, no el esfuerzo mismo: *«¿Cuál?»* son dos palabras y obliga a releer;
> doce palabras bien puestas no obligan a nada. Convertirla en meta produce un agente
> que contesta *«Ok.»* a todo — otra forma de robot. Ver §9bis.

### 2.1 Gobernanza de los principios — cómo esta lista no llega a C27

Riesgo señalado por el PO, y es el riesgo de este documento sobre sí mismo: **trece
principios excelentes que en seis meses son veintisiete y vuelven a ser, sin querer,
una máquina de estados.** No porque ninguno sea malo — porque a partir de cierto
número empiezan a interactuar entre sí, y entonces cumplir la lista sustituye a
atender al cliente. Es la misma enfermedad, en la capa del documento.

**No es hipotético: ya pasó en este repo, y nadie lo vio.** Existen dos series `R`
distintas en el mismo espacio de nombres:

| Serie | Dónde | Qué son |
|---|---|---|
| **R1-R13** | [auditoría de rigidez §11](whatsapp-agent-auditoria-rigidez-2026-07-29.md) | **reglas** conversacionales |
| **R14-R16** | [`whatsapp-agent-architecture.md`](whatsapp-agent-architecture.md) §R | **riesgos** del subsistema |

El código cita ambas como si fueran una sola: `guards.py:205` invoca *R2* (regla,
negar un hecho), `executor.py:81` invoca *R15* (riesgo, PII en logs) y `policy.py:105`
invoca *R16* (riesgo, urgencia). Y la propia auditoría de rigidez escribe *«regla R15
de la spec»* — R15 no es una regla, no está en la spec, y es un riesgo de otro
documento. **La colisión es invisible solo porque los rangos no se solapan por
casualidad.** El día que alguien escriba una R14 conversacional, dos cosas distintas
tendrán el mismo nombre en producción.

#### La regla de admisión (del PO)

> **Todo principio nuevo debe demostrar (a) que corrige una clase de conversaciones
> observada en producción, y (b) que no se deriva de un principio existente.**

Es la disciplina que el proyecto ya aplica a los gates —*sin precedente, no se añade
un gate* (ADR p55 §9.0)— trasladada a los principios. Y como cualquier regla de este
proyecto, necesita ser exigible o es un póster. Seis mecanismos, **los seis nacen
aquí**: un presupuesto añadido después no se añade nunca (p55 A4).

| | Mecanismo | Por qué |
|---|---|---|
| **P1** | **Cada principio cita su conversación precedente**, por ID | Es la evidencia que ya se exige a los ADRs de este subsistema (conv 12, conv 13). Un principio sin precedente es una buena idea, y las buenas ideas van al backlog |
| **P2** | **Cada principio lleva su cláusula de exigibilidad**: cómo se comprueba que se cumple (código, test, métrica o revisión de corpus) | Sin ella es un póster. Y hace visible la redundancia: dos principios con la misma cláusula son un principio |
| **P3** | **Admitir uno obliga a revisar los trece**: quien propone C14 declara cuál deja redundante | El costo de añadir no puede ser cero, o la lista crece por acumulación. Es lo único que ataca el mecanismo real del problema |
| **P4** | **Una serie, un documento, un significado.** Los principios conversacionales viven aquí y solo aquí | El precedente `R` de arriba. Se marca como retirado, **nunca se renumera** — misma disciplina que `STATUS_CANCELLED_DEPRECATED` y `REASON_IDENTITY_AMBIGUOUS_DEPRECATED` |
| **P5** | **Cada principio declara su mal uso previsible**: *¿qué mala decisión permitiría si alguien lo leyera demasiado literalmente?* | *(Del PO.)* Un principio se rompe por dos lados y P1-P4 solo cubrían uno. **P2 detecta incumplimiento; P5 detecta celo.** Definir el límite **al nacer** evita que dentro de un año alguien lo convierta en dogma citando el documento |
| **P6** | **Cada principio con un número asociado declara qué emergería si ese número fuera el KPI principal del equipo** | *(Del PO.)* Goodhart no llega por mala lectura, llega por buena intención. Ver abajo: es un modo de fallo **distinto** de P5 y necesita una defensa distinta |

#### P5 aplicado a los once principios vivos

El ejemplo del PO lo dice todo: *«una decisión por mensaje»* es correcto, y leído al
pie de la letra prohibiría **«tengo estos tres horarios, ¿cuál prefieres?»** — que es
justo el ejemplo con el que se justificó la regla. Un principio trae su propia mala
lectura incorporada; hay que escribirla.

| | Mal uso previsible | Límite |
|---|---|---|
| **C1** escuchar antes de decidir | parálisis: pedir aclaraciones hasta entenderlo todo antes de mover un dedo | escuchar no es interrogar. Con lo que hay, se actúa |
| **C2** todo lo aportado se guarda | dar por bueno un dato dicho de pasada o en broma; acumular PII | guardar ≠ dar por válido: validador y confianza siguen en serie. Y R15: el cuerpo del mensaje no entra al rastro |
| **C3** estado publicado íntegro | publicar todo lo que existe en la base → superficie de injection y jerga interna | se publica lo que puede cambiar **cómo se habla**, no todo lo que hay. Y nunca autoriza desde ahí |
| **C4** el modelo conduce | retirar salvaguardas «porque ahora decide el modelo» | las capas 0 y 4 no son negociables en ninguna fase |
| **C5** preempción solo si no hay contención | mover la urgencia al modelo alegando que «se puede contener después» | el daño de la demora **no** se contiene después. La urgencia no se toca |
| **C6** un mensaje es varias cosas | atender las cuatro cosas en una sola respuesta → 180 palabras | ver la colisión con C13, abajo |
| **C7** repetir es defecto del sistema | no volver a pedir nunca un dato necesario → el agente se rinde o lo inventa | cambia la **estrategia**, no el requisito |
| **C9** explicable después | registrar tanto que aparece PII, o que el runtime empiece a leer el rastro | invariantes 10 y 11 de p55: append-only, sin PII, el runtime jamás lee |
| **C10** la conversación no es solo información | turnos sociales infinitos; el agente nunca cierra nada | el compromiso sigue vivo: **no avanzar no es dejar de existir** |
| **C12** el compromiso es deuda, no agenda | no retomar nunca → el cliente se queda esperando la cita que pidió | no empujar ≠ olvidar. Hay un momento en que retomar es lo cortés, y lo elige el modelo leyendo a la persona |
| **C13** economía conversacional | *(el del PO)* «una decisión» leído como «una pregunta»; y «mínimo de palabras» → *«Ok.»* a todo | el **propósito del turno** manda: tres horarios son una decisión; acompañar en dos líneas cumple |

#### P5 encuentra algo que P1-P4 no podían: colisiones entre principios

**C6 vs C13.** C6 dice que un mensaje puede ser respuesta + pregunta + corrección +
queja. C13 dice: la longitud mínima que cumpla el propósito. Leídos juntos y mal:
*«hay que atender las cuatro cosas, breve»* — imposible, y el resultado real sería un
mensaje largo.

Resolución: **gobiernan mitades distintas del turno.** C6 es de **percepción** (no
descartes contenido: el defecto de `_is_interruption`); C13 es de **producción** (no
lo vuelques todo). Percibir cuatro cosas y responder la que toca **no es una
contradicción: es exactamente lo que hace una persona.**

Es la primera interacción entre principios que este documento detecta, y era justo el
riesgo que motivó §2.1: *demasiados principios empiezan a interactuar entre sí*. P5 es
el mecanismo que las saca a la luz.

#### P6 · la optimización miope — por qué no es P5 otra vez

Distinción del PO, y es real:

| | **P5 · mal uso** | **P6 · optimización** |
|---|---|---|
| Quién falla | una persona leyendo la regla en un caso concreto | **nadie**. Todos la cumplen |
| Dónde se ve | en esa decisión | solo en el agregado, y tarde |
| Se corrige | escribiendo el límite en el principio | **no se puede** — el fallo es que el principio pasó a ser la meta |

C13 lo ilustra sin necesidad de que nadie lo lea mal. Basta con **celebrarlo**: menos
palabras, menos preguntas, menos turnos. El agente empieza a contestar *«Sí.»*,
*«No.»*, *«Entendido.»* — **cumple C13 en todos los mensajes** y la conversación es
pésima.

**Un principio no se defiende de Goodhart escribiendo un principio mejor.** Se
defiende de dos maneras, y hay que elegir una explícitamente:

**(1) Con un contrapeso**: otra métrica que se mueva en dirección contraria, de modo
que maximizar la primera empeore la segunda. Aplicado a los números de este plan:

| Número | Maximizarlo produce | Contrapeso |
|---|---|---|
| Palabras por mensaje ↓ (C13) | *«Sí.» «No.» «Entendido.»* | **turnos hasta la primera respuesta útil** — respuestas de una palabra no resuelven nada, así que se dispara |
| Tasa de repregunta → 0 (C7) | el agente no vuelve a pedir nunca lo que hace falta: se rinde o lo inventa | **turnos hasta la primera tool exitosa** — si no pregunta, no completa |
| Turnos puramente conversacionales ↑ (C10) | charla infinita, no cierra nada | **turnos por resolución** (ya existe en `metrics.py`) |

> Vale la pena notarlo: **la tercera métrica del PO (§9bis.2) resultó ser el
> contrapeso de la segunda.** Sin haberlo buscado, el conjunto quedó auto-frenado.

**(2) Declarando que nunca es un KPI**, cuando no existe contrapeso honesto. Es el
caso de `tasa_handoff`: minimizarla significa *no escalar cuando había que escalar*, y
**el costo de una urgencia no atendida no aparece en ningún tablero**. No hay número
que lo compense. Se queda como diagnóstico, jamás como objetivo — y esto aplica al
sistema **de hoy**, no solo al que propone este plan.

#### P6 aplicado a la métrica insignia — el hallazgo incómodo

**«% de mensajes que el agente redacta de verdad»** es la métrica bandera de esta
épica (§9bis). Maximizada hasta el final, la forma de llegar al 100 % es **borrar las
plantillas que quedan** — y las que quedan son **las salvaguardas**. El óptimo de mi
propia métrica insignia es *la plantilla de urgencia generada por el LLM*.

Nadie tendría que leer nada mal para llegar ahí: bastaría con perseguir el número.

Defensa, formulada **sin número** (corrección del PO — la v7 decía «70-85 %», que es
exactamente el `≤6` que se acababa de retirar, una revisión después):

> **El porcentaje de mensajes redactados por el agente nunca puede acercarse al
> 100 %, porque existen clases de mensajes cuya literalidad *es* una garantía del
> sistema**: salvaguardas, urgencias, opt-out, handoff.

El techo deja de ser una constante y pasa a ser **una consecuencia de una propiedad**.
Y eso no es cosmético: el techo **se mueve con la mezcla de tráfico**. Una semana con
más urgencias lo baja mecánicamente. Con «85 %» escrito como objetivo, esa semana
parecería una regresión cuando el sistema se comportó exactamente como debía.

Refuerzo que ya existe y no hay que inventar: la spec §1.3 declara las plantillas
tier-0 **literales, con test por igualdad** — acercarse al 100 % pone esos tests en
rojo antes de llegar a producción. **La garantía es el test, no el número.**

Operativamente sí se puede usar un rango **observado** para monitorizar; lo que no
puede es entrar al principio. Misma separación que ya hace este documento entre
filosofía y observabilidad (§9bis.1: la métrica de palabras se mide, nunca se fija).

Que P6 encuentre su peor caso en la métrica bandera del propio documento, a las dos
horas de nacer, es el argumento más fuerte a favor de P6. Y que el número prohibido
reapareciera en la propia defensa, una revisión después de haberlo retirado, dice algo
sobre el tirón: **no basta con avisar de Goodhart; hay que sacar el número de la
frase.**

#### La segunda mitad de P6: ¿quién tendría incentivo real para perseguirlo?

*(Del PO.)* No toda métrica corre el mismo riesgo, y saber **quién** la perseguiría
decide qué defensa hace falta —o si no hace falta ninguna.

| Métrica | Quién tiene el incentivo | Riesgo | Defensa |
|---|---|---|---|
| **% sin plantilla** | quien mida el éxito de esta épica; un evaluador automático | **alto** — es la métrica bandera, la que se va a mirar cada semana | propiedad estructural (arriba) + tests de literalidad tier-0 |
| **Palabras por mensaje** | un reward model; **y cualquiera que optimice costo de tokens** — menos palabras es literalmente más barato | **alto**: el incentivo es económico y constante | contrapeso (turnos hasta la primera respuesta útil) + nunca objetivo |
| **`tasa_handoff`** | PM, dueño de la clínica: *«el agente resuelve más solo»* | **alto, y ya presente hoy** | no-KPI declarado. No hay contrapeso honesto |
| **Latencia p50/p95** | ingeniería | ver abajo | umbral, no objetivo |

**El caso de la latencia merece pararse.** El agente más rápido posible es el que
responde con plantillas y nunca llama al modelo — **es decir, el sistema de hoy.**
Optimizar latencia es una fuerza que tira de vuelta al formulario, y la sostiene
precisamente el equipo que va a implementar este plan. La protección ya existe y es
del tipo correcto: la spec fija la latencia como **umbral** (p50 < 15 s, urgencias
< 10 s), no como algo a minimizar. Vale como regla general:

> **Un umbral que respetar es Goodhart-seguro; un número que maximizar no lo es.**
> Donde se pueda, convertir objetivo en umbral.

**Y el titular del incentivo más peligroso no es una persona.** Un evaluador
automático o un reward model optimiza de forma continua, sin juicio y sin cansarse.
Este proyecto ya tiene el sitio donde eso aterrizaría: `agent_eval` (nightly, LLM
real) y `agent_quality`. **Si alguna vez puntúan una conversación con estas métricas y
alguien ajusta el prompt contra esa puntuación, Goodhart deja de necesitar un humano
distraído.** Regla que se deriva: un evaluador automático puede medir estas métricas,
pero **su puntuación no puede ser función de ellas**.

#### Síntesis · las tres defensas contra la degradación

Patrón que el PO detectó leyendo la evolución completa, y conviene dejarlo escrito
porque hace legible toda esta sección. Contra la degradación hay **tres** mecanismos,
cada uno para un modo de fallo distinto:

| | Qué falla | Quién falla | Defensa | Cuándo se detecta |
|---|---|---|---|---|
| **P5** | **interpretación** — alguien lee mal el principio | una persona, en una decisión | el límite ya está escrito en el principio | en la revisión de esa decisión |
| **P6** | **optimización** — el principio se persigue | **nadie**: todos lo cumplen | otro indicador que se mueve en contra, o «nunca es KPI» | semanas o meses, en el agregado |
| **Gates** | **implementación** — alguien cambia el código | quien commitea | CI en rojo | en el commit |

```
        interpretación  →  optimización  →  implementación
             P5                P6              gates
```

Dos cosas que la tabla hace visibles:

- **La defensa más barata cubre el fallo más caro.** Un gate cuesta CI y atrapa en el
  commit; P6 cuesta una métrica y atrapa meses después, cuando el problema ya es
  cultural. Escribir una frase de límite (P5) o de contrapeso (P6) es lo más barato
  que existe y es lo único que cubre los dos modos que ningún test ve.
- **No se sustituyen.** Un gate no impide que alguien persiga un número; un contrapeso
  no impide que alguien borre el test.

Con la **admisión** (P1 / universalidad) y la **salida** (graduación a mecanismo), el
ciclo queda cerrado por los dos extremos:

```
   ¿debería existir?  →  ¿se puede leer mal?  →  ¿se puede perseguir?
        admisión                 P5                     P6
                                                         ↓
   ¿sigue haciendo falta?  ←  ¿se puede romper en código?
         salida                        gates
```

Nada entra sin precedente, nada se rompe sin que algo lo detecte, y nada permanece
cuando deja de hacer falta. **Es el criterio de este plan aplicado a sí mismo**: que
la lista encoja a medida que el sistema se endurece.

#### La regla de salida — es la que hace que la lista encoja

La regla del PO gobierna la entrada. Falta la puerta contraria, y es la que decide si
esto funciona a largo plazo:

> **Un principio que se convierte en mecanismo deja de ser un principio.**

Cuando una regla pasa a estar hecha cumplir por código —un validador, un guard, un
constraint, un gate de CI— ya no hace falta recordarla: **se cumple sola**. Sacarla de
la lista no la debilita, la gradúa. Es literalmente lo que hizo p54 con el prompt:
G1/G2/G3/G7 salieron del prompt, entraron a `guards.py`, y *«el prompt se acortó y el
sistema quedó MÁS estricto»*.

De ahí sale la taxonomía que mantiene la lista corta sin congelarla:

- **Ontológicos**: definen qué es una conversación para este sistema. Hoy C4, C5, C6,
  C10, C12. No se pueden mecanizar.
  > **Deben ser excepcionalmente pocos y estables. Crecer exige demostrar que el
  > principio nuevo describe una propiedad fundamental de *toda* conversación y que
  > no se deriva de otro existente.**
- **Operativos**: describen una conducta que todavía no está en el código. C2, C7,
  C13… **Cada uno tiene fecha de caducidad implícita**: el día que su mecanismo
  exista, se retira.

**Sin número, y a propósito** (corrección del PO). La v5 decía *«no deberían pasar de
media docena»*. Seis no es una propiedad de las conversaciones: es una propiedad del
estado de este documento hoy. En tres años podrían ser siete, o cinco, y seguir siendo
correcto. Poner el número lo convierte en objetivo y reaparece Goodhart — **el mismo
aviso que este documento escribe para C13 dos secciones más arriba y que yo incumplí
aquí mismo.**

Consecuencia que se deriva y que la v5 no distinguía: **los dos tipos no se admiten
con el mismo examen.**

| | Bar de admisión |
|---|---|
| **Operativo** | **P1**: una clase de conversaciones observada en producción, citada por ID |
| **Ontológico** | **Universalidad**: es cierto de *toda* conversación, no de las que fallaron. Una conversación de producción **no basta** para justificarlo |

Y un test retrospectivo barato: **si un principio ontológico hay que editarlo, casi
seguro no era ontológico.** La estabilidad no es una aspiración, es el síntoma.

#### Aplicando la regla ahora mismo — 13 → 11

Empezar aplicándola a la lista propia, que es donde duele:

| Principio | Veredicto | Motivo |
|---|---|---|
| **C8** | **RETIRADO** | Es R9, que **ya es mecanismo** desde p55 §5: `Factor.__post_init__` levanta `ValueError` si falta el `why`. Un principio no puede restatear una regla que el compilador ya impone. Su único aporte real —*el `why` viaja como hecho publicado, no como plantilla*— es una decisión de implementación y se muda a §5.3 |
| **C11** | **FUSIONADO en C10** | Mi propio texto lo definía como *«la mitad enforceable de C10»*. Dos entradas para una idea es exactamente lo que P2 detecta: pasa a ser la cláusula de exigibilidad de C10 |
| **C1** | **candidato**, no retirado | *Escuchar antes de decidir* probablemente se deriva de C2 + C12: si todo lo que el cliente aporta se guarda y el compromiso no dicta el tema, escuchar primero cae solo. No lo retiro porque C1 añade una restricción de **orden dentro del turno** que las otras dos no expresan. Queda anotado para la próxima revisión — el objetivo es que la lista se revise, no que quede bonita |

Que la regla encuentre dos redundancias **en su primera aplicación, sobre un documento
escrito la misma semana**, es la mejor prueba de que hacía falta.

---

## 2bis. La situación — lo que el sistema sabe de la persona

Esta sección no existía en la v1 y es la corrección de fondo.

### 2bis.1 Qué es

Junto a los **hechos de control** (qué se prometió, qué falta, quién está verificado)
el sistema necesita registrar la **situación**: qué está haciendo esta persona con
este mensaje y en qué estado llega.

```
aporta un dato · pregunta por el proceso · corrige al agente · se disculpa
insiste · se desahoga · bromea · agradece · está apurada · está asustada
lleva 3 mensajes sin obtener lo que pidió · es su primer contacto
```

Nada de esto llama a una herramienta. Nada de esto cambia un permiso. **Todo esto
cambia cómo se habla**, que es el 90 % de lo que el cliente percibe como calidad.

Ejemplos del PO, y lo que hoy hace el sistema con ellos:

| El cliente escribe | Qué necesita | Qué hace el sistema hoy |
|---|---|---|
| *«Estoy desesperada»* | que le bajen la ansiedad antes que cualquier trámite | nada — no hay dónde registrarlo |
| *«Perdón por preguntar tanto»* | *«no te preocupes, para eso estoy»* | `is_complaint_or_meta` lo detecta y lo usa **solo** para no anteponer un aviso de horario |
| *«jaja sí perdón»* | una línea humana y seguir | ningún slot avanza ⇒ **`stall_turns +1`** |
| *«mi perro está nervioso»* (con verificación pendiente) | *«¿qué le pasó?»* | el estado dice `me_falta: [titular]` ⇒ el modelo se va a identidad |

### 2bis.2 Dónde vive — y las tres cosas que nunca hace

La situación **se publica en el estado, se lee en el prompt, y se mide**. No hace
nada más. Tres prohibiciones, y las tres existen para que esto no se convierta en la
tercera máquina de estados del subsistema:

1. **Nunca es un enum consumido por una función de decisión.**
   `situacion == 'desesperada' → tono = 'calmado'` sería FSM #3, y peor que las dos
   anteriores porque la emoción no discretiza. Se publica como texto legible por el
   modelo, no como valor de un `switch`.
2. **Nunca gatea nada.** Ninguna capacidad, ninguna tool, ninguna escalada, ningún
   permiso depende de la situación. Si algún día una precondición la lee, se ha
   construido lo que este plan viene a desmontar.
3. **Nunca compite con una salvaguarda.** *«estoy desesperada, mi perro no respira»*
   es **urgencia**, primero, siempre, sin pasar por el modelo. La capa de situación
   toca todo el sistema **excepto los cortacircuitos**. Es la frontera más importante
   de esta sección: una capa de empatía bien intencionada que retrase una urgencia es
   el peor resultado posible de este plan.

Se hace cumplir con un gate estático simétrico al de R13: **`arbiter.py` y las
salvaguardas no pueden leer hechos de situación.** Un import ahí pone CI en rojo.

### 2bis.3 Por qué no es una capa técnica nueva

Porque el modelo ya sabe hacer esto. Un LLM decente, ante *«estoy desesperada»*,
responde con calidez sin que nadie se lo pida. Lo que hoy se lo impide no es falta de
capacidad: es que **(a)** casi nunca le toca el turno y **(b)** cuando le toca, lo que
recibe es una orden de trabajo (`objetivo`, `me_falta`, `ya_preguntado`), no una
persona.

Por eso la corrección es en su mayor parte **sustractiva**: dejar de encuadrar el
turno como un formulario. Lo aditivo es pequeño y no lleva lógica — publicar qué se
sabe de la persona, no solo qué se le debe.

### 2bis.4 Conflicto con R13 — la regla actual prohíbe esta capa

Hay que destaparlo porque es vinculante. ADR p55 §6 / R13:

> *Un hecho solo existe si puede cambiar una decisión futura. El gate **vinculante**
> es **estático**: un hecho que ninguna fila del árbitro lee es código muerto.*

Los hechos de situación, por diseño (2bis.2), **ninguna fila del árbitro los lee**.
Con R13 tal como está escrita, el gate estático los clasifica como código muerto y
los borra. **La regla, literalmente, prohíbe la empatía.**

R13 conflaciona dos clases de hecho. La v2 las separa:

| | **Hecho de control** | **Hecho de situación** |
|---|---|---|
| Cambia | *qué pasa* | *cómo se dice* |
| Lo lee | el árbitro, las salvaguardas | el modelo (y el reporte) |
| Gate | R13 tal cual: si el árbitro no lo lee, es muerto | **el simétrico**: si una función de decisión lo lee, **es un bug** |

La misma disciplina, espejada. Un hecho de situación que empieza a gatear se detecta
igual de mecánicamente que un hecho de control que nadie lee.

**Requiere enmienda a p55** (§10.3): no es un matiz de redacción, es la diferencia
entre que esta capa exista o no.

---

## 3. Qué se conserva — y por qué

Aproximadamente el **65 % del subsistema no se toca**. Esto no es cortesía: es lo que
hace que el plan sea incremental en vez de una reescritura.

| Componente | Por qué se conserva |
|---|---|
| **`ToolExecutor` + loopback HTTP + `ToolExecution`** | La costura correcta entre conversación y negocio: reusa serializers, RBAC, validadores de tenant y shape de errores sin duplicar nada, y deja auditoría completa. Es la mejor decisión del subsistema. **Cero cambios.** |
| **Confirmación tier-2** (`confirmations.py` + `_commit_pending`) | Args staged, ejecutados verbatim, jamás regenerados (TC-SEC-03). Es **la** propiedad de seguridad que importa cuando el LLM escribe en el dominio. La auditoría de rigidez ya la señaló como "el modelo a imitar". **Cero cambios, en ninguna fase.** |
| **`_verification_ok` en `run_tool`** | La barrera real de datos personales **no es el router**: es este predicado, evaluado por debajo del modelo. Es lo que hace seguro dejar conversar al LLM sobre identidad. **Cero cambios.** |
| **`guards.check_output`** (G1/G2/G3/G7) | Verificación **posterior** sobre el texto ya generado: restringe el resultado sin restringir el proceso. Es contención pura, y el patrón que este plan generaliza. Se **extiende** (§5.5), no se reescribe. |
| **Salvaguardas** (8, §5.1) | Cortacircuitos donde la contención es imposible. La urgencia sigue en el paso 3 y nada de este plan la mueve. |
| **`worker.py`** | Lease, drain-on-pickup, aislamiento de fallos, `_discard_if_superseded`. Infra sólida. **Cero cambios.** |
| **`ConversationGoal`** como tabla y su ciclo de vida | Los 7 estados, `return_to`, `supplanted_by`, `blocked_reason` y las dos constraints parciales son correctos y ya modelan lo que hace falta. Lo que cambia es **quién los escribe**, no su forma. |
| **`TurnDecision`** | Append-only, `because` ortogonal, frontera oráculo/diagnóstico. Además es **el instrumento que hace medible este plan** (§9 Fase 0). Se llenan los 4 campos de oráculo hoy vacíos; el contrato no cambia. |
| **`LLMCall`** | Costo y latencia por turno. Es cómo se paga la factura del riesgo #11.2. |
| **Tabla de `refs` / handles** | El modelo nunca ve UUIDs. Simple y efectivo. |
| **R1-R13** | Vigentes sin excepción. Este plan **no relaja ninguna**; C1-C9 las presuponen. |
| **Suite de regresión + `harness.run_turn`** | `StubLLMClient` + `RealApiTransport` + aserciones prohibidas globales + exhaustividad de `TurnDecision`. Es el sustrato de todo el plan. **Cero cambios de motor.** |

---

## 4. Qué debe cambiar — análisis componente por componente

### 4.1 `policy.evaluate` — deja de ser router y pasa a ser salvaguarda

**Veredicto: reducción del 75 %.** De 36 salidas a 9. No desaparece: sin él la
urgencia sería una cuestión de política discutible (ADR p55 §1).

Lo que **se queda** (pasa el criterio C5 — el daño es *al decir*):

| Salvaguarda | Por qué no puede ser contención |
|---|---|
| kill switch / demo | operativo, no conversacional: apagado no debe haber turno |
| contacto bloqueado | no hay acción posterior que interceptar; el daño es responder |
| humano activo · handoff pendiente | prometimos una persona; el modelo no puede renegociar la promesa |
| **urgencia** | el daño es la demora. Contener después no sirve de nada |
| petición explícita de humano | el modelo tendería a seguir ayudando |
| opt-out | legal; el daño es el mensaje mismo |
| **afirmativa a un `pending_action`** | ejecuta args ya staged sin volver al LLM. Si esto pasa al planner, un "sí" puede ampliar el alcance de lo confirmado (TC-SEC-03) |
| presupuesto agotado | límite de costo |
| media sin texto | no hay entrada que interpretar |

Lo que **se va** (tiene contención disponible, o no hace daño): tamiz de identidad,
los tres retos, `is_bot_question`, `is_thanks`, `is_bare_greeting`, pagos, y el texto
de la respuesta a media.

### 4.2 `matchers.py` — se parte en dos

**Veredicto: sobrevive la mitad de seguridad, muere la mitad semántica.**

| Se queda | Se va |
|---|---|
| `is_emergency`, `wants_human`, `wants_optout`, `classify_confirmation` | `classify_client_triage` + los ~70 lemas `_TRIAGE_*` |
| — son salvaguardas: ahí el recall determinista vale más que el matiz, y un falso negativo es peligroso | `looks_like_question`, `is_answer_shaped`, `_QUESTION_LEMMAS` — el aparato de "¿esto es respuesta o pregunta?", que implementa un falso dilema (C6) |
| `is_complaint_or_meta` — **asciende**: deja de decidir si se antepone un aviso y pasa a ser un hecho publicado | `is_bot_question`, `is_thanks`, `is_bare_greeting` — conveniencias, no salvaguardas |

### 4.3 `goals.py` / Commitment — no se replantea: se le cobra el ADR

**Veredicto: la forma es correcta, la propiedad está mal.** ADR p55 §3 ya especifica
lo que hace falta (§1.3). Tres cambios:

1. **El compromiso deja de pertenecer a la tool.** `TOOL_GOALS[tool_name]` como
   constructor desaparece; un compromiso se abre porque **la conversación adquirió
   una promesa**, no porque el modelo llamó una función.
2. **`capture` se abre a la percepción.** Deja de ser exclusivo de `raw_args`. El
   validador y el umbral de confianza se conservan íntegros — lo que cambia es la
   fuente, no el filtro.
3. **Los retos de identidad dejan de tener FSM.** Siguen siendo compromisos con
   factores y `why`; lo que muere es la máquina que decide qué frase toca
   (`_advance_*`). Un compromiso de identidad pasa a ser **un checklist que el modelo
   consulta**, no **un modo en el que la conversación entra**.

Se corrige de paso el defecto que produjo `Te lo pido para  🙂`: hoy `return_to` es
un `CharField` libre que no referencia ningún `Factor` declarado, así que la garantía
"un factor sin `why` no compila" no cubre las etapas que la FSM realmente usa. Al
desaparecer la FSM, `return_to` pasa a ser **siempre** un nombre de factor del
catálogo, verificable.

### 4.4 `planner.py` — no desaparece: deja de decidir

**Veredicto: de 23 salidas a 4.** El planner se queda como **orquestador** (bucle
LLM ↔ tools, aplicación de guards, ejecución del commit staged) y pierde su papel de
tomador de decisiones conversacionales.

Las 19 salidas que se van son las que hoy eligen una plantilla según
`outcome.client_error`. En su lugar: el error vuelve al modelo como **hecho**, y el
modelo redacta. Las 4 que quedan: `respondió` · `propuso` (tier-2) · `ejecutó`
(commit) · `escaló` (salvaguarda o guard duro).

Corolario: `_soft_error_hint` — 20 instrucciones imperativas redactadas que hoy se
inyectan como sistema (*«Pregúntale al cliente…»*, *«Discúlpate y ofrece…»*) —
pasa de **guion** a **hecho**: `{'error': 'slot_taken', 'significa': 'ese horario se
ocupó'}`. El sistema informa; no dicta la frase.

### 4.5 `arbiter.py` — cambia de jurisdicción, no de forma

**Veredicto: no muere; deja de ser autoridad del *turno* y pasa a ser autoridad del
*compromiso*.**

Hoy es `bool → {DEVIATE, CONTINUE}` con un call site: una capa entera —módulo, ADR,
presupuesto de ramas, suite propia— cuya función efectiva es un booleano, porque los
hechos que la harían valiosa (`proposes_other_commitment`, `client_declined`) **nunca
se construyen**: nadie clasifica la intención del entrante. Es CR-4 de la rigidez,
todavía abierta.

Con percepción, esos hechos **existen**. El árbitro pasa a responder *«¿qué le pasó
al compromiso en este turno?»* —continuó, se desvió, fue suplantado, lo abandonaron—
que es una transición de estado determinista que alimenta el embudo y el tope de
desvíos. Sus cinco veredictos siguen siendo los correctos y su pureza se conserva.

Lo que pierde: decidir qué se le dice al cliente. Nunca lo hizo bien y ADR p55 §2 ya
lo prohibía ("el árbitro nunca decide contenido").

**Esto es un cambio semántico de contrato ⇒ exige ADR (p55 §8).** Ver §10.3.

### 4.6 `prompts.py` — el contexto ad-hoc pasa a proyección

**Veredicto: el `context` dict se sustituye por `ConversationState`.**

Hoy: 8 claves elegidas a mano + `anchored_identity_facts`, que ancla **tres** hechos
seleccionados manualmente. Es un parche correcto a un agujero estructural, y el
cuarto hecho que haga falta exigirá otra entrada escrita después del próximo
incidente.

El `SYSTEM_PROMPT` cambia poco y **no pierde ninguna prohibición** (regla de gobierno
de p54 §2: ninguna edición de prompt puede reducir el conjunto de comportamientos
prohibidos). Gana una sección de conducta de identidad y pierde la de agendar, que
pasa a ser estado publicado.

### 4.7 `tier0.py` — de 31 plantillas a ~5

**Veredicto: sobreviven las de salvaguarda.** Urgencia, handoff, opt-out, buzón
apagado, problema técnico. Todo lo demás lo redacta el modelo con el hecho publicado.

Motivo estructural, no estético: **una plantilla es un `format()` que no puede
fallar visiblemente.** `T0_WHY_THEN_REASK` con `why=''` produjo `Te lo pido para  🙂`
dos veces en producción y ningún test lo vio. Un hecho ausente en un bloque de estado
es diagnosticable; un hueco de formato vacío, no.

### 4.8 `ToolOutcome` — ya es correcto; falta que el planner lo trate como tal

**Veredicto: sin cambios de contrato.** ADR p55 §4 ya le quitó `reply_text` y
`needs_confirmation`, y el planner detecta propuestas comparando estado. Lo que falta
no es contrato: es que el planner deje de convertir `client_error` en una rama de
conducta (§4.4).

---

## 5. La arquitectura nueva

### 5.1 Pipeline

```
                      ENTRANTE (ráfaga completa)
                              │
     ┌────────────────────────▼────────────────────────┐
  0  │  SALVAGUARDAS · 9 predicados deterministas      │  preemptan todo
     │  urgencia · bloqueado · humano · opt-out · …    │  ─► pueden terminar el turno
     └────────────────────────┬────────────────────────┘
                              │
     ┌────────────────────────▼────────────────────────┐
  1  │  PERCEPCIÓN  (NUEVO)                            │  «¿qué me está diciendo
     │  ┌── DATOS ─────► validador ─► compromiso       │    esta persona?»
     │  └── SITUACIÓN ──► estado (jamás a una decisión)│  NO decide nada
     └────────────────────────┬────────────────────────┘
                              │
     ┌────────────────────────▼────────────────────────┐
  2  │  ESTADO · ConversationState                     │  proyección íntegra,
     │  quién es · cómo llega · qué nos dijo ·         │  en español semántico,
     │  qué le debemos                                 │  en ESE orden
     └────────────────────────┬────────────────────────┘
                              │
     ┌────────────────────────▼────────────────────────┐
  3  │  CONDUCCIÓN · planner + LLM                     │  «¿qué hago y cómo lo digo?»
     │  bucle LLM ↔ tools · 4 salidas                  │
     └────────────────────────┬────────────────────────┘
                              │
     ┌────────────────────────▼────────────────────────┐
  4  │  CONTENCIÓN                                     │  puede VETAR, nunca redactar
     │  _verification_ok · guards · tier-2 staged      │
     └────────────────────────┬────────────────────────┘
                              │
     ┌────────────────────────▼────────────────────────┐
  5  │  ARBITRAJE DEL COMPROMISO + RASTRO              │  qué le pasó al compromiso
     │  arbiter.decide · TurnDecision                  │  no toca el saliente
     └────────────────────────┬────────────────────────┘
                              ▼
                          SALIENTE
```

Dos lecturas del diagrama:

- **La autoridad ya no baja: se reparte por naturaleza del riesgo.** Las capas 0 y 4
  son del sistema y son absolutas. La capa 3 es del modelo y es absoluta *dentro de
  lo que 0 y 4 permiten*. No hay negociación entre ellas.
- **Las capas 1, 2 y 5 no deciden nada.** Perciben, publican y registran. Que no
  decidan es lo que les permite ser exhaustivas sin volverse un segundo router.

### 5.2 Percepción — dos salidas, no una

**Corrección de la v2.** La v1 definía percepción como *«hechos aportados → validador
→ compromiso»*. Eso no es percibir: es capturar slots con la boca más ancha, y deja
fuera todo lo que no es un dato — que es la mitad de una conversación. *«Mi perro
está nervioso»* no llena ningún slot y es lo más importante que dijo esa persona.

Percepción produce **dos** salidas, y su asimetría es deliberada:

| | **Datos** | **Situación** |
|---|---|---|
| Ejemplo | «me llamo Ana», «el martes», «Oliver» | «está apurada», «se disculpa», «pregunta por el proceso», «bromea» |
| Pasa por | validador + umbral de confianza | nada — no se valida un estado de ánimo |
| Va a | compromiso (persistido, agregable) | estado publicado + reporte |
| Lo lee | árbitro, tools, métricas de embudo | **solo el modelo** |
| Si se equivoca | un slot mal llenado ⇒ el validador o la confirmación lo atrapan | una frase con el tono levemente desviado ⇒ **coste cero** |

Esa última fila es la que justifica no poner ninguna maquinaria de control sobre la
situación: **equivocarse leyendo el ánimo de alguien no rompe nada.** Todo el aparato
de validadores, umbrales y confirmación existe porque un dato mal capturado sí rompe
cosas. Aplicárselo a la situación sería copiar el rigor al lugar donde no hay riesgo
— que es la definición del problema que este plan viene a resolver.

#### La verificación es una herramienta; la percepción no

**Segunda corrección de la v2.** En la v1 fusioné ambas en `identify_client` y eso
volvía a atar la percepción a un compromiso concreto: una tool de verificación no
puede percibir que el perro está nervioso.

- **`identify_client` se queda** — como lo que es: la herramienta de **verificación**
  de identidad (§5.2b). Resuelve C2 (el veredicto lo dicta el código) y el caso de
  identidad, que es el de la Fase 2.
- **La situación no es una tool.** No tiene efecto, no tiene permiso, no tiene
  resultado que el modelo necesite consultar. Se deriva del turno y se publica.

Cómo se deriva se decide con datos, no ahora. En orden de costo: **(a)** los matchers
que ya existen y ya funcionan (`is_complaint_or_meta` detecta bien: *no te entiendo,
ya te dije, me estás repitiendo, no sirves*) ascendidos de "decidir si se antepone un
aviso" a hecho publicado; **(b)** señales derivables sin lenguaje: cuántos turnos
lleva sin obtener lo que pidió, si es primer contacto, si ya se le pidió el mismo dato
antes; **(c)** si (a) y (b) se quedan cortos, una lectura del propio modelo. **(a) y
(b) no cuestan una sola llamada extra** y cubren los cuatro ejemplos del PO.

### 5.2b `identify_client` — la verificación

Decisión de diseño: la verificación de identidad deja de ser una FSM y pasa a ser una
herramienta que el modelo invoca cuando conversando descubre algo relevante.

`identify_client(owner_name?, pet_name?, phone_digits?, is_returning?)` — todos los
argumentos opcionales (`required: []`, igual que las tools de objetivo desde p54):

1. **Persiste lo que llegó** en el compromiso de identidad (push: guarda lo que vino,
   no lo que se pidió), pasando por los validadores existentes.
2. **Verifica contra la base** con las funciones deterministas que ya existen
   (`try_verify_by_pet_answer`, `try_verify_by_owner_name`, `find_link_candidates`,
   `owner_digits_match`). **El modelo aporta el candidato; el código dictamina.**
3. **Devuelve hechos, jamás nombres**: `{verificado: bool, falta: [...],
   ya_tengo: [...]}`.

Tres invariantes de esta tool, y las tres son de seguridad o privacidad:

- **Nunca devuelve nombres ni conteos de candidatos.** El modelo no puede enumerar lo
  que no sabe (G4: *«el cliente aporta, el sistema verifica»*; nada de "¿eres Ana
  Cruz?"). Es contención, no confianza.
- **Comportamiento uniforme exista o no el registro.** Pedir los 4 dígitos no puede
  significar "encontré a alguien con ese nombre", o la tool se vuelve un oráculo de
  existencia. El código actual ya lo resuelve así (`_seed_family_challenge` siembra
  aunque no haya candidatos) y la propiedad se conserva.
- **Sigue sin poder subir el nivel de verificación por su cuenta**: `verification_level`
  solo lo escriben `identity._promote` y `identity.link_family`, ambos evaluando el
  dato contra la base. Un test estático lo ancla (§9 Fase 1).

Por qué no un segundo LLM de extracción: duplica costo y latencia por turno, y
`identify_client` consigue el mismo efecto push reutilizando el bucle de tools que ya
existe. Coste asumido: si el modelo **no** llama la tool, el hecho solo vive en la
ventana de mensajes. Riesgo real, medido en Fase 2 (§11.4).

### 5.3 `ConversationState` — la proyección

Una sola función, una vez por turno, en español semántico y no con claves internas
(*"el cliente dice que ya es cliente"*, no `"identity_triage_done": "returning"`):

**El orden importa y es parte del diseño** (corrección de la v2). La proyección abre
con la persona y cierra con las obligaciones del sistema. Un bloque que empieza con
`objetivo: schedule_appointment · me_falta: [date, time]` encuadra el turno como un
formulario antes de que el modelo lea una sola palabra del cliente:

```
1. QUIÉN ES        cómo se llama (si lo sabe), sus mascotas, si ya es cliente,
                   si es su primer contacto
2. CÓMO LLEGA      cómo viene este mensaje: apurada, molesta, disculpándose,
                   bromeando, preguntando por el proceso, insistiendo
                   ── y cuánto lleva sin obtener lo que pidió
3. QUÉ NOS DIJO    todo lo que ha aportado en esta conversación, lo hayamos
                   pedido o no
4. QUÉ LE DEBEMOS  el compromiso del frente y el suspendido: qué le prometimos,
                   qué falta, dónde íbamos, y el PORQUÉ de cada dato pendiente
5. QUÉ YA LE PEDIMOS   qué datos y cuántas veces  (C7: repetir es defecto nuestro)
6. LA CLÍNICA      fecha/hora local, nombre, horario, si está abierto ahora
```

Los bloques 1-3 son de la persona; el 4-5 del sistema. En la v1 el orden era el
inverso y no había bloque 1 ni 2.

Va **anclado siempre**, fuera de la ventana de mensajes: salir de la ventana hace
perder el fraseo, nunca el hecho (P7 de la rigidez). Sustituye al `context` ad-hoc y
a `anchored_identity_facts` — que deja de ser un caso especial.

### 5.4 Contención — lo que ya existe, dicho como capa

No hay nada que construir aquí; hay que **dejar de duplicarlo con preempción**:

| Barrera | Qué impide | Estado |
|---|---|---|
| `_verification_ok` en `run_tool` | que un contacto sin verificar toque datos personales | existe, intacta |
| Confirmación tier-2 con args staged | que un "sí" ejecute algo distinto de lo parafraseado | existe, intacta |
| `guards.check_output` | precios inventados, consejo médico, promesas, jerga | existe, se extiende |
| RBAC del rol AGENT + DRF + constraints | cualquier escritura ilegítima de dominio | existe, intacta |

### 5.5 Contención simétrica — el hueco que queda

Hoy los guards **solo miran el texto del modelo**. El router repitió `T0_TRIAGE_TITULAR`
tres veces verbatim y ningún contador subió, ningún guard disparó, y
`metrics.tasa_repregunta` lo registró como **0.00** — porque `mark_asked` solo se
llama desde `_goal_gate` y `_asked_counters` excluye los compromisos de identidad.

Se vigilaba al sospechoso equivocado. En la arquitectura nueva **todo saliente pasa
por los guards, venga de donde venga**, y `asked` se incrementa cuando se pide un
dato, no cuando lo pide un componente concreto.

---

## 6. Responsabilidades — fronteras

| Capa | **Decide** | **Nunca decide** | **Recibe** | **Produce** |
|---|---|---|---|---|
| **Salvaguardas** | si el turno se corta antes de conversar | cómo se dice nada que no sea su propia plantilla | ráfaga cruda, estado de conversación y contacto | corte + plantilla, o paso a la siguiente capa |
| **Percepción** | **nada** | absolutamente nada — no decide, registra | ráfaga + compromiso vigente + catálogo de factores | hechos validados persistidos + hechos del turno |
| **Estado** | **nada** | qué hacer con lo que publica | compromisos, contacto, org, contadores | una proyección en español, anclada |
| **Planner** | el bucle: cuántas vueltas, cuándo parar, qué hacer con un resultado | qué se le permite al cliente; qué texto es aceptable | estado + historial + specs de tools | llamadas a tools + un texto candidato |
| **LLM** | qué se dice, en qué orden, con qué palabras; qué tool llamar y con qué args | si tiene permiso; si un dato es válido; si algo se ejecuta | estado + historial + resultados de tools | texto + propuestas de llamada |
| **Tools** | nada sobre la conversación | terminar turnos, escribir copy (ADR p55 §4) | args del modelo + conversación + executor | **hechos** (`ToolOutcome`) |
| **Contención** | si un texto sale o no; si una tool corre o no | qué se dice en su lugar (eso es plantilla de salvaguarda) | texto candidato + hechos del turno + nivel de verificación | veto + motivo, o paso |
| **Árbitro** | qué le pasó al **compromiso** | qué se le dice al cliente; si se escala | hechos del turno + foto del compromiso | veredicto (5 valores) + `return_to` |
| **Rastro** | nada | nada | veredicto + hechos + diagnóstico | una fila `TurnDecision` |

Regla de lectura, y es la que evita que esto se degrade en seis meses:
**quien decide contenido no toca control; quien decide control no toca contenido.**
La prueba de p55 §2 sigue valiendo: *¿se puede renderizar en otro idioma, tono o canal
sin tocar este módulo?* Si sí, es control.

---

## 7. Conversaciones paralelas

El caso canónico: *«¿Por qué necesitas esos datos?»* a mitad de una verificación.

### 7.1 Por qué hoy es imposible

Tres razones, y ninguna se arregla con una regla nueva:

1. `TurnVerdict` es **escalar**. Un mensaje es *o* respuesta *o* interrupción.
2. `_is_interruption` implementa *interrumpe ⇔ pregunta ∧ ¬(tiene forma de
   respuesta)*, y `is_answer_shaped` solo conoce una forma (`digits`). En las otras
   cuatro etapas, **cualquier** mensaje con `?` es interrupción aunque traiga la
   respuesta.
3. `DEVIATE` **descarta el contenido**: el caller retorna la `PolicyDecision` y el
   texto no se vuelve a mirar. `ya te dije\nAna` pierde el nombre.

### 7.2 Cómo funciona en la arquitectura nueva

```
CLIENTE ─► «¿para qué necesitas eso?»
   │
   ├─ PERCEPCIÓN  → hechos del turno: {pregunta_sobre_el_proceso: true}
   │                (ningún dato nuevo; ninguna decisión)
   │
   ├─ ESTADO      → compromiso: verificar identidad
   │                dónde iba: los 4 dígitos
   │                por qué se piden: «confirmar que eres tú y proteger
   │                                   los datos del titular»   ← HECHO, no plantilla
   │
   ├─ MODELO      → contesta el porqué. Y decide él si vuelve a pedir el dato
   │                en el mismo mensaje o deja que la persona respire.
   │                (genera; no rellena `T0_WHY_THEN_REASK`)
   │
   └─ ÁRBITRO     → `desviar`, return_to='digits'   ← para el embudo, NO para empujar
```

**Corrección de la v2**: la v1 decía *«contesta el porqué **Y vuelve a pedir el
dato**»*. Eso es la agenda incorporada al diseño (C12). Un humano al que le preguntan
*«¿para qué necesitas eso?»* a veces solo contesta, y espera. El `return_to` existe
para que el sistema **no pierda** dónde iba, no para que **empuje** a volver. Quién
decide si toca retomar en este mensaje es el modelo, que es quien está leyendo a la
persona.

Cuatro propiedades que se obtienen de la estructura, no de una regla:

- **No se reinicia nada** porque el compromiso nunca se tocó: percepción no decide y
  el árbitro no redacta.
- **No se pierde el objetivo** porque `return_to` ya existe y ya es obligatorio
  (invariante 7 de p55).
- **La pregunta se responde de verdad** porque el `why` viaja como hecho. Y si algún
  día falta, el modelo improvisa una respuesta razonable en vez de emitir
  `Te lo pido para  🙂`.
- **No se repite verbatim** porque no hay plantilla que repetir.

### 7.3 El caso mixto — el que hoy no se puede representar

`«ya te dije, Ana»` es **queja + respuesta**:

| | Hoy | Nuevo |
|---|---|---|
| Percepción | — | `owner_name='Ana'` **+** `se_queja_de_repeticion=true` |
| Estado | el nombre no entra a ningún lado | el compromiso ya tiene `owner_name` |
| Modelo | — | reconoce, usa el dato, avanza |
| Árbitro | `desviar` (×3 → handoff) | `continuar` — **no fue un desvío: fue una respuesta con queja** |

Nótese que el árbitro **no necesita una regla nueva** para esto: con el hecho
`owner_name` presente, `interrupts` es falso y `CONTINUE` sale solo. El defecto nunca
estuvo en el árbitro; estuvo en que recibía un hecho mal calculado.

---

## 8. Gestión de contexto

Los cuatro fallos que el PO nombró, con el mecanismo que los cierra. Tres de los
cuatro **ya tienen la maquinaria construida**: el problema no es de memoria, es de
**publicación**.

| Fallo | Causa hoy | Mecanismo | ¿Existe ya? |
|---|---|---|---|
| Vuelve a preguntar datos ya dichos | el dato nunca entró (pull) y, si entró, no se publica | percepción (§5.2) + `ya_tengo` en el estado (§5.3) + `asked` que **cambia conducta** | parcial: `capture` y `asked` existen; falta abrir la fuente y hacer que actúen |
| Ignora información espontánea | no hay dónde poner un hecho no solicitado | percepción | **no** — es el único hueco real |
| Pierde el contexto tras una interrupción | `DEVIATE` descarta el mensaje y la ventana amputa | `return_to` + estado anclado fuera de la ventana | **sí**: `return_to` es obligatorio desde p55; nunca se publicó al modelo |
| Reinicia una conversación que no terminó | `flow['suspended']` se escribe y **nadie lo lee** | ciclo de vida del compromiso + `supplanted_by` → "¿retomamos la cita de Luna?" | **sí** en la tabla; el lector no existe |

Dos decisiones de diseño sobre el contexto:

**Ventana.** Se conserva por turnos (`HISTORY_TURNS=12`), que ya fue la corrección
correcta. Lo que cambia es que **salir de la ventana deja de perder hechos**: el
estado va anclado. La ventana degrada el *fraseo*, no la *memoria*.

**Resumen rodante.** `Conversation.summary` existe desde F0 y **no se escribe en
ningún sitio** — verificado, cero escrituras. Queda **fuera de alcance** de este plan:
con el estado publicado, el resumen deja de ser urgente, y añadirlo ahora mezclaría
variables. Backlog explícito, no olvido.

---

## 9. Plan incremental

Seis fases, ordenadas por (daño que ocurre hoy) × (costo). Cada una declara qué
principio de §2 cierra. Regla de alcance heredada de p55 §9: **para cada cambio
propuesto durante la implementación, ¿es necesario para cerrar el principio de esta
fase? Si no, va al backlog.**

---

### Fase 0 · Línea base reproducible
**Cierra**: nada (no cambia comportamiento). Es la condición para poder medir todo lo demás.

**Objetivo.** Convertir las conversaciones reales del piloto en suite de regresión, y
capturar la línea base con la que se juzgarán las fases siguientes.

**Por qué primero, y por qué no es opcional.** No hay tráfico real: todas las orgs
activas son demo (decisión registrada 2026-07-30). "Observar en producción" no es una
opción disponible. Sin corpus, el experimento del PO no es falsable.

**Impacto.** Cero en runtime. Solo tests y un comando de reporte.

**Archivos.** `tests/test_corpus_conversacional.py` (nuevo) · `metrics.py` ·
`management/commands/agent_quality.py` · `tests/harness.py` (helpers, sin tocar el motor).

**Contenido.**
- Tres conversaciones como casos guionizados sobre `harness.run_turn`: **conv 12**
  (repregunta ×4), **conv 13** (los 4 factores correctos → handoff) y la **del brief**
  (`Te lo pido para  🙂` ×2 → handoff).
- Reporte de línea base derivado de tablas existentes: `% turnos con
  planner_used=False` · `TurnDecision.because` por conversación · turnos hasta la
  primera tool personal exitosa · `HumanHandoff.reason_code` · `LLMCall.cost_estimate`
  y `latency_ms` p50/p95 por conversación.

**Riesgos.** El corpus se escribe "a favor" del cambio que viene y no falla hoy.
Mitigación: **los tres casos deben estar ROJOS al cerrar la fase**, afirmando el
comportamiento defectuoso actual. Es la lección registrada de É-F4 Fase 2 (un test
que no puede fallar antes del fix no prueba nada).

**Criterio de salida.** Los 3 casos reproducen el fallo · el reporte corre y su
salida queda versionada como fixture de comparación · CI verde.

#### ✅ EJECUTADA — 2026-08-01

**Entregado**

| Archivo | Qué |
|---|---|
| `tests/test_corpus_conversacional.py` (nuevo) | los 3 casos + la línea base congelada |
| `metrics.py` | `compute_conversation_metrics()` — métrica de conversación, cero campos nuevos |
| `management/commands/agent_quality.py` | el informe abre con **conversación** y luego **motor**; cada número lleva escrita su regla de P6 |
| `tests/harness.py` | `run_turn(..., burst=[...])` — sin ráfagas no se puede reproducir el caso del brief |

**Mecanismo de los casos en rojo.** Afirman la conducta **deseada** y llevan
`unittest.expectedFailure`: CI sigue verde mientras el defecto exista, y el día que
la Fase 2 lo corrija `unittest` reporta *unexpected success*, `wasSuccessful()`
devuelve `False` y **CI se pone en rojo**, obligando a quitar el decorador. El gate
se limpia solo.

**Verificación de que fallan por la razón correcta.** `expectedFailure` oculta la
diferencia entre «falló la aserción» y «reventó el setup», así que se comprobó una a
una. Las cinco fallan por aserción, y la reproducción es literal:

```
'Te lo pido para  ' unexpectedly found in 'Te lo pido para  🙂\n\n¡Perfecto! ¿A nombre de quién…'
'¿A nombre de quién está el registro?' unexpectedly found in  ← el nombre venía en la misma ráfaga
'Te lo pido para  🙂…' == 'Te lo pido para  🙂…'              ← dos salientes idénticos
<HumanHandoff: HumanHandoff<identity normal>> is not None
4 not less than or equal to 2                                 ← el `asked={'date': 4}` de la conv 12
```

**Desviación respecto al plan, y es buena noticia.** El plan decía «los 3 casos deben
estar ROJOS». **La conv 13 quedó VERDE**: É-F4 ya la había cerrado (Fase 0, una
no-respuesta no es una respuesta equivocada; Fase 1, el reto se suspende en vez de
destruirse). Se conserva en el corpus como **regresión protectora** — la mitad que no
puede volver a romperse. Rojos: el caso del brief (4 aserciones, los cierra la Fase 2)
y la conv 12 (1 aserción, la cierra la Fase 3).

**Línea base congelada** (conversación del brief, 5 turnos):

| Métrica | Hoy |
|---|---|
| `pct_redactado_por_agente` | **0.0** — ni un solo mensaje lo escribió el modelo |
| `pct_turnos_sin_modelo` | **1.0** — los cinco turnos sin una llamada al LLM |
| `salientes_repetidos` | **≥ 1** |
| `palabras_por_mensaje_agente.muestras` | **0** — sin mensajes del agente no hay muestra, y por eso esa métrica no dice nada hasta que la Fase 2 la levante |

**Honestidad de método que quedó en el código**: `cambios_de_tema_exitosos` devuelve
`None`. No es derivable hoy — `goals.resume()` limpia `supplanted_by`, así que la
evidencia de que un compromiso fue suplantado desaparece justo al retomarlo. Antes que
inventar un proxy malo, se declara ausente; necesitaría un campo nuevo y eso es otro
sprint.

> **Fase 1 queda BLOQUEADA hasta ADR p56 + la enmienda a R13** (§10.3). No es
> ceremonia: p55 §8 exige que todo cambio semántico del runtime conversacional entre
> por ADR **antes** de implementarse — «con cuatro contratos cambiando a la vez, un
> ADR posterior no decide, documenta».

---

### Fase 1 · Percepción, situación y verificación como herramienta
**Cierra**: C2 (push), C11 (turno conversacional válido). Habilita C1, C10, C12.

**Objetivo.** Que exista un puerto de escritura para hechos no solicitados, que la
verificación sea invocable sin la FSM, y que **el sistema deje de castigar la
conversación**. **Añadir antes de quitar**: la FSM sigue corriendo; las dos vías
coexisten.

**Por qué la situación entra aquí y no en la Fase 3** (corrección de la v2): si el
experimento de la Fase 2 corre con el estado abriendo en `me_falta` y con el detector
de estancamiento contando las preguntas del cliente, **se está probando una versión
mutilada de la hipótesis**. La parte barata de la situación no cuesta ninguna llamada
extra y tiene que estar antes del experimento.

**Impacto.** Aditivo salvo un cambio de conducta deliberado (el estancamiento deja de
contar turnos conversacionales — reduce escaladas, nunca las aumenta).

**Archivos.** `tools.py` (`identify_client` + spec) · `goals.py` (spec de identidad
unificado; `capture` deja de exigir origen de args) · `identity.py` (sin cambios de
lógica; se reusa) · `prompts.py` (describir la tool; bloques 1-2 del estado) ·
`matchers.py` (`is_complaint_or_meta` asciende a hecho publicado; se le suman
disculpa, insistencia y agradecimiento) · `planner.py` (`_settle_goal`: un turno con
señal conversacional **no** incrementa `stall_turns`) · `policy.py`
(`nudge_abandoned_flows` consulta la situación antes de disparar; un `T0_DEFER`
reciente lo inhibe).

**Contenido de situación en esta fase — coste cero en llamadas al LLM:**
- De matchers que **ya existen y ya funcionan**: se queja · pide repetición · se
  disculpa · pregunta por el proceso · agradece.
- Derivadas sin lenguaje: es primer contacto · cuántos turnos lleva sin obtener lo
  que pidió · si ya se le pidió este mismo dato antes.

**Pruebas.**
- La tool acepta llamadas parciales y persiste lo válido; un dato inválido no llena
  el slot y viaja como `rechazado`.
- **Nunca devuelve nombres ni conteos**: aserción sobre el payload, no sobre el texto.
- **Comportamiento uniforme**: mismo `falta` exista o no un `Owner` con ese nombre
  (anti-oráculo de existencia).
- **Gate estático de seguridad**: `verification_level` tiene exactamente dos
  escritores, ambos en `identity.py`. Cualquier otro módulo que lo asigne pone CI en
  rojo.
- **Gate estático anti-FSM#3**: `arbiter.py` y las salvaguardas **no leen hechos de
  situación**. Un import ahí pone CI en rojo. Es el simétrico del gate de R13
  (§2bis.4) y lo único que impide que la empatía se convierta en la tercera máquina
  de estados del subsistema.
- **Conducta (C11)**: un turno con señal conversacional —pregunta, disculpa,
  agradecimiento, broma— **no** incrementa `stall_turns`. Test de comportamiento:
  tres turnos así seguidos no producen handoff. Hoy sí lo producen.
- **La urgencia sigue preemptando**: *«estoy desesperada, mi perro no respira»* sale
  por la plantilla de urgencia, sin pasar por el modelo, con la situación registrada
  o no. Es el test que protege la frontera de §2bis.2 (3).
- **Oportunidad del recordatorio (C13)**: un cliente que respondió *«déjame
  pensarlo»* (`T0_DEFER`) **no** recibe el nudge a los 60 minutos. Hoy sí lo recibe,
  y es el flujo normal del producto — no un caso extremo.
- Adversariales `TC-SEC-05` (no revelar a nombre de quién está el número) y
  `TC-SEC-06` (insistencia agresiva) verdes por la vía nueva.

**Riesgos.**
| Riesgo | Mitigación |
|---|---|
| El modelo usa la tool para sondear qué nombres existen | payload sin nombres + comportamiento uniforme; el tope de tools por turno (5) acota el sondeo; `ToolExecution` lo deja auditado |
| Dos vías de verificación conviviendo divergen | la vía nueva **reusa** las funciones de `identity.py`; no se escribe lógica de match nueva |

**Criterio de salida.** Tool auditada en `ToolExecution` · los 5 tests anteriores
verdes · corpus de Fase 0 **sigue rojo** (no se arregló nada todavía, y eso es
correcto).

---

### Fase 2 · Retirar la preempción de identidad · **el experimento**
**Cierra**: C4, C5, C6 (en el dominio de identidad).

**Objetivo.** Que el modelo conduzca la identidad. Es el experimento acotado que
propuso el PO, y el que decide si el resto del plan se ejecuta.

**Impacto.** El más grande del plan en comportamiento observable, y el más acotado en
superficie. **Cero migraciones.**

**Archivos.**
- `policy.py`: fuera el paso 12b y los pasos 8/8b/8c; fuera `_advance_challenge`,
  `_advance_family_challenge`, `_advance_identity_triage`, `_seed_family_challenge`,
  `_check_interruption`, `_is_interruption`, `start_identity_*`, `_inbound_history`,
  `_family_fail`. **~370 líneas.**
- `matchers.py`: fuera `_TRIAGE_*`, `classify_client_triage`, `_QUESTION_LEMMAS`,
  `looks_like_question`, `is_answer_shaped`. **~120 líneas.**
- `tier0.py`: fuera `T0_TRIAGE_*`, `T0_CHALLENGE_*`, `T0_WHY_THEN_REASK`,
  `T0_FAMILY_LINK_START`.
- `planner.py`: `verification_required` deja de ser rama terminal y pasa a hecho
  realimentado (una rama menos, no una nueva).
- `prompts.py`: bloque de identidad en el estado + sección de conducta en el
  `SYSTEM_PROMPT`; `PROMPT_VERSION` → `reception-f5-v9`.
- `flow`: fuera `identity_triage_done` y `suspended` (esta última ya era código
  muerto).

**Pruebas.**
- **Los 3 casos del corpus pasan de rojo a verde.** Es el criterio principal.
- Ningún saliente contiene un nombre de cliente por debajo de `confirmed_in_chat`
  (aserción prohibida global, ya en el harness).
- Una tool personal antes de verificar sigue devolviendo `verification_required` y
  **no ejecuta nada** (contención, no preempción).
- Regresión completa de É-F0..É-F4 verde salvo los tests que afirmaban sobre la FSM
  retirada, que se reescriben contra la conducta observable (no contra la etapa
  interna).

**Riesgos.**
| Riesgo | Mitigación |
|---|---|
| **Fuga de datos personales**: el modelo revela o enumera antes de verificar | `_verification_ok` intacto (la barrera nunca fue el router) + payload sin nombres (Fase 1) + aserciones prohibidas globales en cada saliente + suite adversarial |
| El modelo se rinde y escala más | comparar `tasa_handoff` contra la línea base; el tope de desvíos deja de existir como mecanismo (ya no hay etapas), lo sustituye el estancamiento del compromiso |
| Reescribir tests "a favor" del cambio | los tests de la FSM retirada se reescriben **antes** de tocar el runtime, afirmando conducta (qué ve el cliente, qué se escribió en dominio), no estructura |
| Más costo por turno | medido: turnos que hoy cuestan 0 llamadas pasan a costar 1-2. Es el precio explícito del cambio (§11.2) |

**Criterio de salida.** Corpus verde · cero fugas en adversariales · `planner_used`
≈ 100 % en los turnos de identidad · **decisión del PO** según la tabla de lectura de
resultados (§9 in fine).

#### ✅ EJECUTADA — 2026-08-02

**Retirado: ~620 líneas**, más de las ~500 estimadas.

| Archivo | Antes → después |
|---|---|
| `policy.py` | 779 → 457 (**−331**, 12 funciones de FSM) |
| `matchers.py` | 368 → 229 (**−139**) |
| `tier0.py` | 290 → 234 (**−56**, 13 plantillas) |
| `tools.py` | **−51** (`link_family_member` + spec) |
| `planner.py` | **−45** (rama terminal de verificación + propuesta de reto) |
| `test_policy.py` | 704 → 289 (**−415**) |

**Tres cosas que el recorte destapó y que el plan no preveía:**

**1 · `link_family_member` quedó huérfana.** Su propio docstring lo delataba —*«el
resto del reto lo conduce el Policy Engine, sin LLM»*—: ese conductor dejó de
existir, así que sembraba un reto que nadie avanzaba. `identify_client` (Fase 1) la
sustituye en una llamada. Retirada.

**2 · El árbitro se quedó SIN CONSUMIDOR de producción.** Su único call site era
`policy._check_interruption`. Se conserva porque la Fase 4 le da jurisdicción sobre el
compromiso, pero **la advertencia quedó escrita en el propio módulo**: si esa fase se
cancela, es código muerto y hay que borrarlo. Un componente con ADR y sin llamadas es
justo el patrón que la auditoría señaló.

**3 · Se rompió un requisito legal en silencio, y lo cazó un test.** El aviso de
privacidad (LFPDPPP, spec §4) tenía dos productores: el alta de cliente y el paso 12b
del router. Al retirar el segundo, **pedir nombre o dígitos a un desconocido dejó de
ir precedido del aviso** — que es exactamente recolección de datos personales. Lo
detectó `test_privacy_notice_precedes_first_identity_challenge`, escrito en É-F4 W0.
Repuesto donde ahora corresponde: cuando una tool rebota con `verification_required`,
el **sistema** antepone el aviso al texto del modelo. Lo pone el sistema y no el
modelo a propósito — es un literal legal, y pedirle al modelo que lo recuerde
volvería advisoria una regla vinculante.

> Es la lección más cara de la fase: **retirar 620 líneas arrastra cosas que nadie
> mira.** Sin ese test, el hueco se habría ido a producción tapado por 165 fallos
> «esperados» de tests de FSM.

**Resultado del experimento — con la precisión que exige §9 in fine:**

| Señal | Antes | Ahora |
|---|---|---|
| Casos del brief | 🔴 4 rojos | 🟢 verde |
| `pct_turnos_sin_modelo` | 1.0 | < 1.0 |
| `pct_redactado_por_agente` | 0.0 | > 0.0 |
| Fugas en adversariales (TC-SEC-05) | 0 | **0** |
| Conv 12 | 🔴 | 🔴 — la cierra la Fase 3 |

> **Verde por retirada de plantillas y porque el push funciona; NO todavía verde por
> conversación.** El corpus corre con stub: demuestra que la vía existe, no que el
> modelo la use bien. Eso lo dice el eval con LLM real y la revisión de corpus.

**La pérdida que hay que declarar, porque no es de seguridad y por eso se pasa por
alto:** la verificación cambió de naturaleza.

    antes:  4 factores correctos → verificado.  Lo garantizaba la FSM.
    ahora:  4 factores correctos → verificado SI el modelo llama a `identify_client`.

`_verification_ok` sigue impidiendo el acceso indebido —nadie entra sin verificar— así
que **la seguridad no cambia**. Lo que deja de estar garantizado es que un cliente
legítimo *atraviese*, y que uno atascado llegue a un humano: la escalada tras dos
datos equivocados la conducía el router. Es el riesgo §11.4, ahora con caso concreto,
y se mide con llamadas a `identify_client` por conversación en el eval real.

**Tests**: 166 fallos → 0. Cinco clases de `test_policy` retiradas con nota de a dónde
fue cada garantía; `test_family_link` conserva 5 de 9 intactos y porta 3; TC-SEC-05
mantiene su aserción de seguridad **sin tocar** (solo cambió el nombre de la rama).
Guarda nueva: **el router no puede volver a emitir una plantilla de identidad**,
probada sobre cinco frases.

---

### Fase 3 · Estado publicado íntegro
**Cierra**: C3, C7, C8.

**Objetivo.** Que publicar un hecho nuevo no requiera escribir un camino nuevo.

**Impacto.** Sustituye el `context` ad-hoc de `assemble_messages`.
`anchored_identity_facts` desaparece como caso especial.

**Archivos.** `prompts.py` (`build_state`, nuevo) · `goals.py` (`context_block` se
absorbe) · `guards.py` (`check_behaviour` pasa a mirar **todos** los salientes) ·
`metrics.py` (`asked` deja de ser ciego al origen).

**Pruebas.** El estado se publica en español sin claves internas (gate: ninguna clave
de `flow` ni nombre de campo aparece en el bloque) · un hecho nuevo entra por datos,
no por código · `tasa_repregunta` detecta una repetición emitida por una plantilla.

**Riesgos.** Más superficie de prompt injection y de fuga G7 → el bloque es semántico
en español y los guards de jerga ya bloquean `public_id`/`invoice`/`draft`. Más
tokens → medido contra la línea base; el bloque es pequeño frente al historial.

**Criterio de salida.** `anchored_identity_facts` eliminado sin regresión · guards
cubren salientes de plantilla · corpus verde.

#### ✅ EJECUTADA — 2026-08-03

**1 · C7 deja de ser un dato y pasa a ser conducta.** Faltaba una distinción que la
auditoría de rigidez ya había escrito (§P5) y que nadie implementó: **dos umbrales,
no uno.**

    2 preguntas → el sistema CAMBIA DE ESTRATEGIA. `_goal_gate` devuelve
                  `change_approach` (código y guía distintos) y deja de
                  incrementar `asked`.
    3 preguntas → es un bucle; el guard lo marca sobre el texto ya generado.

Solo existía el segundo (`REPEATED_ASK_LIMIT = 3`), así que `asked` subía sin tope y
el modelo repetía. En el piloto llegó a `{'date': 4, 'time': 4}` y el cliente se fue.

> **Por qué dejar de contar no es maquillar el contador.** `asked` cuenta
> PREGUNTAS; a partir del segundo intento el sistema ya no pregunta igual —
> devuelve otra instrucción. Capar el número sin cambiar la conducta habría puesto
> el test en verde dejando la conversación igual de mala.

**2 · Guard simétrico en el punto de salida.** `enqueue_outbound` es por donde pasa
**todo** —plantillas y texto del modelo— y ahí se detecta el saliente repetido. Hasta
aquí los guards de conducta solo miraban al modelo: **se vigilaba al sospechoso
equivocado**, porque quien repitió tres veces la misma plantilla en la conversación
del brief fue el router, y ningún contador subió.

Detecta y registra; **no bloquea**, y es deliberado: un saliente repetido es un
defecto del sistema que hay que ver, no un texto peligroso que retener — retenerlo
dejaría al cliente sin respuesta.

**3 · C3/C8 — el estado se publica en español, con su porqué.**

```
antes   objetivo: schedule_appointment · estado: active · me_falta: ['date','time']

ahora   le_prometi: agendarle una cita
        me_falta:  [{dato: el día de la cita,
                     para: apartar el día en la agenda del veterinario}, …]
```

`Factor` gana `label` **junto a `why`**, no en un mapa aparte: un mapa obliga a tocar
dos sitios por factor nuevo, que es el «camino nuevo por cada hecho» que esta fase
existe para eliminar. Los 20 factores quedaron etiquetados; si falta uno, `as_fact()`
cae al nombre interno y se ve.

Efecto lateral que era el objetivo de C8: **el `why` por fin llega al modelo.** Vivía
en el `Factor` desde p55 y solo salía por una plantilla (la que produjo
`Te lo pido para  🙂`). Ahora viaja con cada dato que falta.

Y `ya_preguntado_2_veces` pasó de dato a instrucción —
`ya_lo_pediste_dos_veces_no_lo_repitas`—: era el ejemplo que la auditoría usaba para
«se publica y no hace nada».

**Frontera que NO se movió, y hay un test que la ancla:** el objetivo publica el dato
y su motivo; **la pregunta la sigue redactando el modelo** (contrato p54). Sin esa
mitad, «publicar en español» degeneraría en que el dominio escriba copy y el
compromiso volvería a ser un motor de diálogo.

**Resultado: el corpus queda COMPLETAMENTE VERDE.** Las tres conversaciones —brief,
conv 12 y conv 13— sin ningún `expectedFailure`. El gate autolimpiante disparó por
segunda vez y se retiró el último decorador.

---

### Fase 4 · El árbitro gobierna el compromiso
**Cierra**: C9 completo · cierra la deuda declarada de É-F4 (`TurnDecision.verdict`
con texto libre).

**Objetivo.** Que los cinco veredictos tengan productor y ejecutor reales, y que los
cuatro campos de oráculo hoy vacíos se llenen.

**Impacto.** Cambio semántico de contrato ⇒ **ADR** (§10.3).

**Archivos.** `arbiter.py` (sin cambio de forma; cambia quién lo llama y con qué
hechos) · `planner.py` (invoca al árbitro al cerrar el turno) · `models.py`
(`TurnDecision.verdict` a enum cerrado) · migración aditiva.

**Pruebas.** Los 5 veredictos son producibles y cada uno declara su contador (gate A6
de p55, que hoy solo cubre una frontera) · `active_commitment`/`return_to`/
`supplanted_by`/`facts_consumed` se llenan en todos los turnos · el corpus reproduce
veredictos, no solo textos.

**Criterio de salida.** Gate A6 extendido a los 5 veredictos · cero filas con oráculo
incompleto.

---

### Fase 5 · Contención simétrica y retiro de plantillas
**Cierra**: C7 completo.

**Objetivo.** Terminar el trabajo: `_soft_error_hint` de guion a hecho, y las
plantillas de conveniencia (saludo, gracias, bot, pagos) al modelo con su hecho.

**Impacto.** ~26 de las 31 plantillas desaparecen. **Sube el costo por conversación**:
los turnos triviales que hoy cuestan 0 llamadas pasan a costar 1. Decisión de producto,
no técnica.

**Archivos.** `tier0.py` · `planner.py` · `policy.py` (últimas conveniencias).

**Criterio de salida.** ≤ 6 plantillas vivas, todas de salvaguarda · costo por
conversación dentro del presupuesto que fije el PO.

---

### Cómo leer el resultado de la Fase 2

| Observación | Lectura | Qué hacer |
|---|---|---|
| Mejora clara y **se sostiene** en conversaciones largas | el problema era **quién tenía el control** | seguir con Fases 3-5 |
| Mejora y **degrada al alargarse** | el control era parte del problema, pero falta push efectivo | el modelo no está llamando `identify_client`; reforzar percepción antes de seguir |
| No mejora | la hipótesis es falsa | parar. Habrá costado dos fases, no una épica |
| Mejora **pero aparece una fuga de datos** | la contención falló | revertir de inmediato; es la única condición de reversión no negociable |

---

## 9bis. Qué se mide — métrica de conversación, no de software

Corrección de la v2. Lo que se mide hoy —handoffs, tools, costo, latencia, tasa de
repregunta— **describe el software**. Ninguna de esas métricas se habría movido si el
agente hubiera atendido bien la conversación del brief, y ninguna se mueve si la
atiende mal con las mismas llamadas. Se está midiendo el motor, no el viaje.

Las métricas del PO, evaluadas con honestidad sobre lo que de verdad se puede
computar. La clasificación importa: prometer automatización para lo que exige
juicio humano acabaría en listas de patrones léxicos, que es la enfermedad que este
plan viene a curar.

### Derivables HOY, sin instrumentación nueva

| Métrica | Cómo | Valor actual estimado |
|---|---|---|
| **% de mensajes respondidos sin ninguna plantilla** | `Message.author_type`: `agent` / (`agent`+`system`) | **≈5 %** |
| **Interrupciones recuperadas** | `ConversationGoal`: `deviated` con `return_to` → `completed`, sobre el total de `deviated` | 0 medido |
| **Cambios de tema exitosos** | `suspended` con `supplanted_by` → `resume` → `completed`, sobre el total de `suspended` | 0 medido |
| **Turnos que el modelo no vio** | `TurnDecision.planner_used = False` | **≈78 %** de las salidas del router |
| **Palabras por mensaje del agente** (C13) | `Message.body`, solo `author_type='agent'`, p50 + p90 | ver §9bis.1 |

> **La primera es la métrica insignia de esta épica.** Es el marcador directo de la
> tesis, no necesita una sola línea de instrumentación, y hoy vale ~5 %. Si al
> terminar la Fase 2 no ha subido de forma evidente, el plan no funcionó — sin
> discusión de interpretación.
>
> **Techo estructural (P6, §2.1): el objetivo NO es 100 %, y no se fija con un
> número.** Nunca puede acercarse al 100 % porque hay clases de mensajes cuya
> **literalidad es una garantía del sistema** (salvaguardas, urgencias, opt-out,
> handoff). El techo real depende de la mezcla de tráfico —una semana con más
> urgencias lo baja, y eso es correcto—, así que un objetivo fijo marcaría como
> regresión una semana que se comportó bien. La garantía la da el test: la spec §1.3
> hace las tier-0 **literales con test por igualdad**. Para monitorizar sí se puede
> usar el rango **observado**; al principio no entra.

### 9bis.1 Palabras por mensaje — el detector de deriva

Métrica del PO, y es la contraparte de la insignia: la primera mide **cuánto habla el
agente de verdad**; ésta, **si se está volviendo pesado**. Sin la segunda, esta épica
puede "tener éxito" y producir un agente que nadie aguanta.

Cuatro decisiones de método, y las cuatro cambian lo que la gráfica significa:

**1 · Solo `author_type='agent'`.** Las plantillas del sistema no cuentan. Es
crítico: a medida que las fases retiran plantillas (Fase 5 quita ~26), un promedio
sobre todos los salientes se movería por composición y no por deriva. **La métrica
cambiaría de significado a mitad del plan** — el mismo error que ya se cometió con
`tasa_repregunta`.

**2 · p50 y p90, no promedio.** El promedio esconde la cola. Un modelo que
ocasionalmente escribe 200 palabras mueve el p90 mucho antes que la media, y esa cola
**es** la deriva en su fase temprana.

**3 · Segmentada por `prompt_version`.** El campo ya existe (`LLMCall.prompt_version`,
poblado en cada llamada). Unida por conversación, cada edición del prompt se convierte
en un experimento visible: si `f5-v9` sube el p90 respecto de `f5-v8`, se ve en la
primera semana en vez de en la primera queja. Es lo que convierte la métrica en
**leading indicator** en vez de en autopsia.

**4 · Nunca es un objetivo.** Si alguien la optimiza, el agente contesta *«Ok.»* a
todo — Goodhart puro, y una forma nueva de robot. Es un **detector de pendiente**: lo
que se vigila es la derivada, no el valor absoluto. No lleva umbral ni alerta
automática en v1; se mira junto a la revisión de corpus, que es quien puede decir si
las palabras de más estorbaban o servían.

**Línea base**: se captura en Fase 0 sobre el corpus. Con el agente hablando en ~5 %
de los mensajes, el valor de hoy es poco representativo — su utilidad empieza
justamente cuando la Fase 2 lo suba.

### 9bis.2 Turnos hasta la primera respuesta útil

Tercera métrica del PO, y la que más se parece a lo que el cliente **siente**. No el
primer token, no la primera respuesta: **la primera respuesta que de verdad atiende
lo que la persona necesitaba.**

```
Cliente:  ¿Para qué necesitas los cuatro dígitos?
Agente:   ¿Cuáles son los cuatro dígitos?
Agente:   ¿Cuáles son los cuatro dígitos?
Agente:   ¿Cuáles son los cuatro dígitos?
                                    → NUNCA hubo respuesta útil

vs.

Agente:   Para asegurarme de abrir la ficha correcta 😊
                                    → turno 1
```

**Se cuenta en turnos, no en segundos.** El reloj en WhatsApp lo domina el cliente
—contesta a los 20 minutos porque estaba trabajando—, así que medir tiempo mide su
agenda, no nuestra utilidad. Es el mismo razonamiento por el que
`metrics.compute_quality_metrics` ya mide la latencia desde el **último** entrante:
la espera deseada no es lentitud.

**Automatización: parcial y honesta.** Juzgar si una respuesta *atendió* algo es
juzgar significado, y hacerlo con listas de patrones es la enfermedad que este plan
viene a curar. La métrica vive en la revisión de corpus. Pero tiene **dos proxies
mecánicos que sirven de alarma temprana**, y los dos son exactos:

| Proxy | Cómo | En la conversación del brief |
|---|---|---|
| Turnos hasta el primer saliente que **no repite** al anterior | comparación literal / casi-literal entre salientes consecutivos. Hoy es 100 % exacto porque son plantillas | **nunca** — tres salientes idénticos carácter por carácter |
| Turnos hasta que el cliente **deja de reformular** | percepción registra «se queja · pide repetición · reformula»; se busca el turno donde deja de aparecer | nunca — escaló primero |

**Es la primera métrica que verifica una regla que el proyecto ya tenía.** R9
(*«toda pregunta del agente debe llevar una razón que pueda decir en voz alta»*)
existe desde la auditoría de rigidez, se volvió estructural en p55 §5 y **jamás se ha
comprobado en una conversación**. Esta métrica es exactamente su comprobación: la
conversación del brief tenía `why=''`, y el resultado fue *«Te lo pido para  🙂»*
dos veces y un handoff.

### Derivables DESPUÉS de percepción (Fase 1-3)

| Métrica | Cómo |
|---|---|
| **Veces que el cliente tuvo que repetir un dato** | percepción registra el mismo dato dos veces sobre un compromiso que ya lo tenía. **Es la métrica correcta** — la de hoy (`asked`) cuenta cuántas veces *preguntamos*, no cuántas veces *él tuvo que repetir*, y es ciega a las plantillas |
| **Información espontánea aprovechada** | hechos que percepción registró sin que el sistema los hubiera pedido, y que después se usaron. Mide directamente el push |
| **Turnos puramente conversacionales** | turnos sin tool, sin slot y sin escalada, que **no** cuentan como estancamiento (C11). Que este número sea > 0 es señal de salud, no de desperdicio |

### NO mecanizables — revisión de corpus, no dashboard

*«Veces que el agente reconoció un error»*, *«disculpas necesarias»*, *«preguntas
respondidas antes de continuar»*. Las tres exigen juzgar si una respuesta **atendió**
algo, y eso no se resuelve buscando *«perdón»* en el texto: exactamente ese enfoque
—listas de lemas para juzgar significado— es lo que produjo `_QUESTION_LEMMAS` y el
bucle del brief.

Propuesta honesta: **rúbrica de revisión sobre N conversaciones por semana**, con
cuatro preguntas de sí/no por conversación (¿respondió lo que se le preguntó antes de
seguir? · ¿reconoció el error cuando lo cometió? · ¿pidió dos veces algo que ya
sabía? · ¿sonó a persona?). Es más lento y es lo único que no miente. El corpus de la
Fase 0 es el sustrato: las mismas conversaciones, revisadas antes y después.

### Qué se retira

`tasa_repregunta` tal como está calculada (sobre `goal.asked`, ciega al router y a
las plantillas — registró **0.00** en la conversación del brief, donde el agente
repitió la misma pregunta tres veces verbatim). Se sustituye por la métrica de
repetición basada en percepción. Mantenerla sería conservar un indicador que dice
que todo está bien mientras el cliente se va.

---

## 10. Compatibilidad, migraciones y contratos

### 10.1 Qué se mantiene compatible

- **Contrato externo del subsistema**: webhook, bandeja (`views.py`), API de inbox y
  `AgentSettings`. Sin cambios.
- **`ToolExecution`, `LLMCall`, `HumanHandoff`**: sin cambios de forma.
- **`ConversationGoal`**: mismos campos y constraints. Cambia quién los escribe.
- **Confirmación tier-2**: sin cambios en ninguna fase.
- **Todas las barreras de seguridad**: sin cambios.

### 10.2 Migraciones

| Fase | Migración | Compatibilidad con datos existentes |
|---|---|---|
| 0-3 | **ninguna** | — |
| 4 | aditiva: `TurnDecision.verdict` de `CharField` libre a enum cerrado | Las filas históricas tienen ~20 valores libres. **No se reescriben** (append-only, invariante 10 de p55): el enum aplica a filas nuevas y el reporte trata los valores viejos como `legacy`. Mismo patrón que `REASON_IDENTITY_AMBIGUOUS_DEPRECATED` y `STATUS_CANCELLED_DEPRECATED` |

Las filas `ConversationGoal` de identidad creadas por la FSM vieja quedan en un
terminal al retirarse (Fase 2). No hace falta traducirlas: son conversaciones
cerradas o de demo. **Si al ejecutar hubiera conversaciones vivas con reto en curso,
se cierran como `handoff`** — nunca se dejan huérfanas.

### 10.3 ADRs necesarios

| ADR | Qué decide | Cuándo |
|---|---|---|
| ✅ **[p56](decisions/2026-08-01-p56-perception-situation-and-turn-as-root.md)** · Percepción, situación y el turno como unidad de razonamiento | La inversión preempción→contención; el criterio C5; qué queda como salvaguarda; el contrato de `identify_client` y sus tres invariantes de privacidad; **los hechos de situación y sus prohibiciones**; que la percepción **ocurre siempre**; C10-C12 | **ACEPTADO 2026-08-01**, antes de escribir código — p55 §8 |
| ✅ **Enmienda a p55 · R13** | **Separa hecho de control de hecho de situación** y les da gates simétricos. Sin esto, el gate estático de R13 borra la capa de situación por «código muerto» — la regla actual prohíbe la empatía | **Aceptada dentro de p56 §3** (un solo documento: las tres decisiones son separables en código e inseparables en efecto). p55 §6 lleva el aviso de enmienda in situ |
| **Enmienda a p55 · autoridad** | El árbitro pasa de autoridad del turno a autoridad del compromiso; la jerarquía de §1 se reordena; `TurnDecision.verdict` se cierra | antes de Fase 4 |

Ambos son **cambios semánticos**, no aditivos, según la tabla de p55 §8. El
snapshot de contratos se bumpea en cada fase que toque los cuatro tipos.

### 10.4 Qué contratos cambian

| Contrato | Cambio | Fase |
|---|---|---|
| Jerarquía de autoridad (p55 §1) | el LLM sube de nivel 4 a conducción; el árbitro baja a compromiso | 2 y 4 |
| `TurnResult` | 23 salidas → 4 | 2 |
| `TurnDecision.verdict` | texto libre → enum de 5 | 4 |
| `Commitment` | la fuente de escritura deja de ser exclusiva de args de tool | 1 |
| `ToolOutcome` | **sin cambios** | — |
| `SYSTEM_PROMPT` | `reception-f4-v8` → `f5-v9`; regla de p54 §2 vigente: ninguna prohibición se retira sin entrar al código con un test | 2 |

---

## 11. Riesgos

### 11.1 Seguridad y privacidad — el riesgo dominante

Si el modelo conduce la identidad, ¿puede filtrar datos o auto-autorizarse?

**No, y la razón es estructural, no de confianza.** La barrera nunca fue el router:
es `_verification_ok`, evaluada en `run_tool`, por debajo del modelo. Un planner
conversando libremente sobre identidad **no puede** ejecutar una tool personal — la
llamada rebota sin tocar nada. Tres capas independientes:

1. **No puede ejecutar**: `_verification_ok` + RBAC del rol AGENT + tier-2 staged.
2. **No puede saber**: `identify_client` nunca devuelve nombres ni conteos. No se
   puede enumerar lo que no se conoce.
3. **No puede afirmar**: `verification_level` tiene dos escritores, ambos evaluando
   contra la base, con gate estático en CI.

Riesgo residual real: **el modelo dice algo que sugiere existencia** ("ah, sí, Ana
Cruz") a partir de un dato que el propio cliente aportó. Es aceptable —el cliente
aportó el nombre— pero se cubre con la aserción prohibida global que ya corre en cada
saliente del harness. Y la condición de reversión inmediata de Fase 2 es exactamente
ésta.

### 11.2 Costo de tokens — el riesgo de producto más caro

**Este plan compra humanidad con tokens, y hay que decirlo con números.**

Hoy 28 de 36 salidas del router cuestan **cero** llamadas al LLM. Al pasar identidad
al planner, esos turnos pasan a costar 1-2 llamadas cada uno.

| Fase | Efecto esperado |
|---|---|
| 2 (identidad) | turnos de identidad: 0 → 1-2 llamadas. Es una minoría del tráfico pero la de más turnos por conversación |
| 3 (estado) | +300-600 tokens de entrada por turno; el bloque es pequeño frente al historial |
| 5 (plantillas) | saludo/gracias/bot pasan de 0 a 1 llamada. **Es el mayor incremento del plan** y por eso va último y separado |

Mitigaciones: `LLMCall.cost_estimate` ya mide por conversación (línea base en Fase 0)
· el presupuesto de 40 turnos sigue vigente · Fase 5 es **opcional y separable**: si
el costo no compensa, se para ahí y el sistema queda bien igualmente.

### 11.3 Pérdida de determinismo

Distinción que hay que sostener: **deja de ser determinista el fraseo y el orden de
las preguntas. Sigue siendo determinista todo lo que importa** — quién puede hacer
qué, qué se escribe en el dominio, qué se dice sobre dinero, medicina y promesas, y
qué se ejecuta tras un "sí".

Coste real y aceptado: los tests de conversación dejan de poder afirmar igualdad
literal en las rutas que pasen al modelo. Ya está resuelto: la spec §1.3 lo previó
("texto LLM = elementos obligatorios/prohibidos, nunca igualdad") y el harness lo
implementa. Lo que cambia es que **más casos se evalúan así**.

### 11.4 El modelo no llama a `identify_client`

Es el riesgo específico de la decisión de §5.2 (percepción como tool en vez de
llamada de extracción propia). Si el modelo no la llama, el hecho solo vive en la
ventana y la conversación degrada al salir de ella.

Detección: la Fase 2 mide `identify_client` por conversación en `ToolExecution`.
Si la tasa es baja, la siguiente palanca —en orden de costo— es (a) reforzar la
descripción de la tool, (b) forzar `tool_choice` en la primera llamada del turno,
(c) llamada de extracción dedicada. **No se decide ahora**: se decide con el dato.

### 11.5 Alucinación

El caso caro (precio inventado) ya está contenido por G1, que compara todo importe
contra los resultados de tools del turno. El caso nuevo (afirmar una cita que no se
creó) tiene guard desde É-F4 Fase 4 (`unbacked_success`), hoy en SOFT. **Fase 2 es el
momento de revisar sus disparos y decidir si sube a HARD** — con los logs
`AGENT_OUTPUT_GUARD`, no con intuición.

### 11.6 Herramientas llamadas fuera de tiempo

Contenido por construcción: `run_tool` revalida tier y verificación en cada llamada,
el tope de 5 tools por turno sigue vigente, y la mutación exige confirmación tier-2.
Una tool llamada "antes de tiempo" rebota; no rompe nada.

### 11.7 Trazabilidad

**Mejora.** Hoy los 28 turnos de router dejan filas `TurnDecision` con
`planner_used=False` y cuatro campos de oráculo vacíos. Tras Fase 4, los cinco
veredictos tienen productor y los cuatro campos se llenan.

### 11.8 Latencia y rendimiento

Turnos que hoy responden en milisegundos (plantilla) pasarán a 2-6 s (una llamada
al LLM). El objetivo de la spec (p50 < 15 s, urgencias < 10 s) se mantiene: **las
urgencias siguen siendo plantilla y no pasan por el modelo** — es precisamente la
salvaguarda que no se toca. `metrics.compute_quality_metrics` ya mide p50/p95 y la
línea base de Fase 0 lo captura.

### 11.9 Conversaciones más largas

Sin FSM que corte, una conversación puede alargarse. Contención existente: el
presupuesto de 40 turnos, el cierre por inactividad (24 h) y el estancamiento del
compromiso. Los dos primeros no se tocan.

**El tercero sí cambia, y es una corrección de la v2** (C11). Hoy `_settle_goal`
incrementa `stall_turns` en **cualquier** turno que no llene un slot: una pregunta,
una disculpa, una broma, un *«perdón por preguntar tanto»*. Tres de esos mandan al
cliente con un humano con el mensaje *«creo que por aquí nos estamos enredando»*.

El sistema está contando **la conversación del cliente como su propio atasco**. Es el
mismo error que É-F4 Fase 0 corrigió para los retos de identidad —*«una no-respuesta
nunca es una respuesta equivocada»*, R1— sin aplicarlo al detector de estancamiento,
que quedó con la regla vieja.

Estancamiento pasa a significar lo que dice su nombre: **el sistema no está logrando
avanzar**, no *«el cliente no me dio lo que le pedí»*. Un turno en el que la persona
preguntó, se disculpó, se desahogó o bromeó **no cuenta**. Lo que sigue contando: el
modelo llamando la misma herramienta con los mismos datos, vuelta tras vuelta — que
es el bucle real que el detector existe para cazar (piloto conv 12).

### 11.10 El riesgo de meta-nivel

**Que este plan produzca una capa más.** Es el patrón del subsistema: cinco épicas,
ninguna eliminó un mecanismo (§F2 de la auditoría).

Contramedida estructural: **cada fase de este plan tiene una cuenta de líneas
retiradas como criterio de salida, no solo de líneas añadidas.** Fase 2 retira ~500;
Fase 3 retira `anchored_identity_facts` y `context_block`; Fase 5 retira ~26
plantillas. Una fase que solo añade es una fase mal ejecutada.

---

## 12. Lo que este plan deja explícitamente fuera

Para que no se cuele por la puerta de atrás durante la implementación:

- **Resumen rodante** (`Conversation.summary`). Existe el campo, no el escritor. Con
  estado publicado deja de ser urgente. Backlog.
- **`low_confidence` por slot.** Mecanismo completo que el modelo nunca ejercita (el
  piloto manda 1.0 siempre — S13 de la rigidez). Se retira o se hace funcionar en su
  propio carril, con su propia evidencia.
- **Transcripción de audio** (UX-14), **cambio de proveedor LLM**, **botones
  interactivos de WhatsApp**. Carriles propios, ya declarados en p54/p55.
- **Quinto objetivo** (alta de mascota para cliente existente).
- **Alta sin cita**: cancelada por decisión de producto (p55, fuera de alcance).

---

## 12bis. El riesgo contrario — la deriva de verbosidad

Este es el riesgo que el plan **crea**, y merece el mismo rigor que los que resuelve.

Liberar al modelo no elimina la artificialidad: la mueve de sitio.

```
ANTES     cliente → FSM → 15 palabras        rígido, telegráfico
AHORA     cliente → LLM → 180 palabras       amable, agotador
```

Las dos se sienten a máquina. La segunda llega **sola**, sin que nadie la decida, y
es peor de detectar porque cada mensaje suelto parece correcto: solo el agregado
revela que hablar con el agente se volvió cansado.

**Y no llega de golpe: llega por el prompt.** Es el mecanismo, y está documentado en
sistemas de todo tipo — alguien añade una línea al system prompt para cubrir un caso,
el modelo se vuelve un poco más explicativo, nadie lo nota. Seis meses y quince líneas
después, el agente abre con *«¡Hola! 😊 Muchas gracias por comunicarte con
nosotros…»*. Ningún commit introdujo eso; lo introdujeron todos.

Por eso la contramedida no es una regla de estilo (que es lo que proponía la v2 de
esta sección, y era flojo): es **C13 como principio** y **una métrica de deriva**
(§9bis). Ninguna revisión humana detecta una pendiente de 3 palabras por mes; una
gráfica sí, y avisa meses antes de que alguien diga *«se siente pesado»*.

**Decisión deliberada: se instrumenta, no se pone guard.** Un guard de longitud
truncaría los casos legítimamente largos (explicar algo complejo, ofrecer opciones) y
no sabe distinguirlos de los inflados. Además la disciplina del proyecto lo prohíbe
hoy: *sin precedente, no se añade un gate* (p55 §9.0) — y todavía no hay deriva
observada, porque el modelo casi no habla. Si la métrica muestra pendiente y el
prompt no la corrige, **entonces** se discute un guard SOFT, con datos.

**Que un mensaje del agente pueda ser de cinco palabras es tan importante como que
pueda ser cálido.**

---

## 13. Conclusión

El agente no falla por bugs ni por el modelo. Falla porque **la conversación no es el
centro del sistema: es el `else` del router** — literalmente, el paso 13 de
`policy.evaluate`, comentado *«Nada aplicó»*.

Y —corrección de la v2— quitarle el gobierno a la FSM no basta si lo hereda el
compromiso. Un sistema cuya pregunta central es *«¿cómo cumplo lo que prometí?»*
produce el mismo síntoma que uno cuya pregunta es *«¿qué transición ejecuto?»*, con
mejor arquitectura. La pregunta tiene que ser **«¿qué necesita esta persona?»**, y el
compromiso pasa a ser lo que el sistema **debe**, no la agenda a la que se cree con
derecho.

De ahí salen las tres cosas que la v1 no tenía y que son la mitad del valor de este
documento: que existan hechos sobre **la persona** y no solo sobre la tarea; que un
turno **puramente conversacional sea válido** y deje de empujar al cliente hacia un
humano; y que se mida **la conversación** en vez del motor.

Y la v3 añade lo que faltaba para que el éxito no se convierta en el problema
siguiente: **economía conversacional**. El objetivo no es que el agente hable más. Es
que hable **cuando toca, lo justo, y sin hacerle trabajo a la persona**.

Dos números lo resumen, y los dos se calculan hoy sin instrumentación nueva:

| | Hoy | Qué significa que se mueva |
|---|---|---|
| **% de mensajes que el agente redacta de verdad** | ≈5 % | sube ⇒ el plan funciona |
| **Palabras por mensaje del agente** (p50/p90) | irrelevante todavía | sube con pendiente sostenida ⇒ el plan se está pasando de frenada |

El primero sin el segundo produce un agente que habla mucho. El segundo sin el
primero produce el formulario de siempre, más corto. **La calidad está entre los
dos**, y por primera vez ambos se pueden ver en la misma gráfica.

Este plan no propone confiar más en el LLM. Propone **dejar de gastar preempción
donde ya hay contención**. Las cuatro barreras que protegen dinero, agenda, datos
personales y salud no se tocan en ninguna fase; lo que se retira son ~500 líneas de
máquina de estados que deciden qué frase toca ahora, que es la única cosa que un
modelo hace mejor que una tabla.

Y no exige creer nada por adelantado: la Fase 2 es un experimento con tres desenlaces
y los tres son útiles. Si mejora y se sostiene, el resto del plan es aplicar el mismo
recorte rama por rama. Si mejora y luego degrada, el culpable es la percepción y se
sabe exactamente dónde. Si no mejora, este documento se equivoca — y haberlo
descubierto habrá costado dos fases, no una épica.
