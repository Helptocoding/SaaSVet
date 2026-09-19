# ADR p55 — Autoridad del turno y compromisos conversacionales

> **Enmienda B3 (2026-09-15).** La autoridad operativa local requiere witness
> vigente (org/conversación/trabajo/lease_token/epoch). Goals/slots/decision y
> respuesta final se consolidan atómicamente con completion; un compromiso o
> TurnDecision no concede ownership. La planificación ocurre en memoria.
> [Contrato B3](../contrato-trabajo-durable-b3.md). Sender externo sigue en B4.

> **Enmienda B0 (2026-09-13), vigente para esta release.** Un compromiso, un veredicto semántico o un pending heredado no concede permiso de escritura durante B0. Las escrituras contenidas se derivan mediante la suspensión/handoff existentes. No cambian FSM, modelos ni número de suspendidos. Crear handoff no prueba aviso, owner humano ni respuesta.
> Alcance, pruebas, límites y rollback: [acta B0](../implementacion-b0-agente-whatsapp-2026-09-13.md). El resto del ADR conserva sus decisiones salvo esta contención temporal.

**Fecha**: 2026-07-30
**Estado**: ACEPTADO — **escrito ANTES de implementar** (É-F4 Fase 3). Este
documento es la brújula del sprint, no su acta.
**Contexto de producto**: subsistema del agente WhatsApp, tras la
[auditoría de rigidez](../whatsapp-agent-auditoria-rigidez-2026-07-29.md) y con
las Fases 0-2 del [plan É-F4](../whatsapp-agent-f4-gobernanza-plan.md) ya en
`develop`.
**Cierra**: R3 (no pedir lo que ya se tiene), R4 (toda interrupción vuelve
donde empezó), R7 (una interacción, una fuente de verdad), R9 (toda pregunta
lleva una razón decible).

> **Por qué antes y no después.** Fase 3 cambia a la vez el contrato de
> `ToolOutcome`, introduce `Commitment`, introduce el árbitro y cierra el
> veredicto de `TurnDecision`. Durante esa implementación se toman decenas de
> microdecisiones. Un ADR escrito al final no decide nada: documenta. Por eso
> aquí solo hay **autoridad, contratos, responsabilidades e invariantes** —
> ningún detalle de implementación, que es justo lo que envejece.

---

## Contexto

La auditoría de rigidez concluyó que el agente no es rígido por tener
demasiadas reglas, sino porque **nadie tiene la autoridad del turno**. Tres
hechos duros, todos verificados en producción:

1. **22 puntos de salida de turno** repartidos en tres módulos, cada uno con su
   propia lógica y ninguno consciente de los otros.
2. **Una herramienta gobierna la conversación**: `ToolOutcome` puede escribir
   copy al cliente (`reply_text`), terminar el turno (`needs_confirmation`) y
   —vía el código de error— elegir lo que el agente dirá después.
3. **Cinco implementaciones del mismo concepto**: `identity_triage`,
   `family_challenge`, `identity_challenge`, `pending_action` y
   `ConversationGoal`. Los cinco tienen promesa, paso actual, lo ya reunido,
   presupuesto de paciencia y salida terminal. Solo uno está en una tabla; los
   otros cuatro viven en un blob JSON que no se agrega, no se mide y se destruye
   con un `pop`.

Las Fases 0-2 ya corrigieron los síntomas más caros y —esto es lo que hace
posible este ADR— dejaron una **línea base objetiva**: `TurnDecision` registra
qué decidió el sistema en cada turno, así que el cambio arquitectónico se puede
medir contra el comportamiento de hoy en vez de justificarse solo.

## Decisión

### 1. Jerarquía de autoridad

Regla de lectura: **la autoridad baja, los datos suben.**

| Nivel | Responsabilidad | Puede terminar un turno |
|---|---|---|
| 0 · **Salvaguardas** | cortacircuitos no negociables: urgencia, contacto bloqueado, humano activo, opt-out | **sí** — preemptan incluso al árbitro |
| 1 · **Árbitro** | ÚNICA autoridad sobre *qué pasa* con el turno | **sí**, y es quien lo decide |
| 2 · **Compromisos** | qué se prometió y en qué punto va | no — es estado, no decisión |
| 3 · **Planner** | ejecuta el veredicto: decide *cómo* se cumple, nunca *qué* pasa | solo cumpliendo un veredicto |
| 4 · **LLM** | redacta y propone | no — no decide ignorar una pregunta |
| 5 · **Tools** | devuelven hechos | **no** (ver §4) |

Dos precisiones que no son cosméticas:

- **Las salvaguardas van ARRIBA del árbitro, no dentro.** Si el árbitro puede
  razonar sobre la urgencia, la urgencia pasa a ser una cuestión de política, y
  no puede serlo. Un cortacircuito no es una decisión sobre el turno: es la
  negativa a tener esa decisión.
- **Orden de ejecución ≠ orden de autoridad.** En ejecución la tool corre
  *después* del LLM (el modelo la invoca); en autoridad la tool va *última*.
  Confundir ambas cosas es parte del desorden que este ADR retira.

### 2. El árbitro: contrato y presupuesto

**Contrato**: `(hechos, compromiso) → veredicto`. Función **pura**.

**Conjunto CERRADO de cinco veredictos** — `continuar`, `desviar`, `suplantar`,
`abortar`, `responder`. Un sexto veredicto **exige un ADR nuevo**: la
complejidad de una capa de decisión la fija su espacio de salida, no su entrada.

**El árbitro nunca decide contenido, solo control de flujo.** Prueba para
distinguirlos: *¿se puede renderizar el veredicto en otro idioma, otro tono u
otro canal sin tocar el árbitro?* Si sí, es control. Si no, es contenido.

```
✗ CONTENIDO — el árbitro se volvió un segundo planner
  {"action": "ask", "slot": "digits", "text": "¿los últimos 4 dígitos?"}

✓ CONTROL — el árbitro dice qué pasa y sobre qué
  {"verdict": "desviar", "commitment": "identity", "return_to": "digits"}
```

Cinco mecanismos lo mantienen pequeño. **Los cinco nacen en el primer commit**;
un presupuesto añadido después no se añade nunca:

| | Mecanismo | Por qué |
|---|---|---|
| A1 | Veredictos como enum cerrado | un sexto exige ADR |
| A2 | Función **pura**: cero DB, cero red, cero efectos | un paso que muta estado esconde una decisión dentro de un efecto secundario — es lo que le quitó la tabulabilidad a `policy.evaluate` |
| A3 | Recibe **hechos ya calculados**; no llama matchers ni al ORM | su cuerpo es una tabla de decisión sobre un conjunto fijo, no una cadena de `if` |
| A4 | **Presupuesto de ramas** con test bloqueante | sin esto, A1-A3 son recomendaciones |
| A5 | **Cero precedencia interna** | la única precedencia real (urgencia primero) vive arriba, en las salvaguardas |
| A6 | **El ejecutor no reinterpreta** | si no, la complejidad solo se muda de capa (ver abajo) |

> **Métrica de salud, verificable en cualquier momento: si el árbitro no cabe
> en una tabla, dejó de ser un árbitro.**

#### A6 · El ejecutor consume veredictos; no los reinterpreta

Añadido por el PO (2026-07-30) tras ver el árbitro ya puro, y cierra el flanco
que A1-A5 dejaban abierto. Cuando una capa de decisión se vuelve pequeña
aparece la tentación de mover el comportamiento a la de al lado, y se pasa de
*árbitro pequeño + ejecutor pequeño* a **árbitro mínimo → ejecutor enorme**.
Eso no simplifica nada: solo desplaza la complejidad.

> **El ejecutor puede reaccionar a una SECUENCIA de veredictos, pero nunca
> REINTERPRETARLOS.**

```
✓  desviar · desviar · desviar   →  handoff        (reacciona a la secuencia)
✗  desviar  →  "en realidad era un fallo"  →  fallo (reinterpreta)
```

Lo segundo **es** la conv 13: una pregunta contada como respuesta equivocada,
dos veces, con los cuatro factores correctos ya en la mano. Reaccionar a la
repetición es legítimo —tres desvíos seguidos merecen una persona—; reetiquetar
la repetición no lo es nunca.

Se hace cumplir **por construcción, no por disciplina**: cada veredicto lleva
**su propio contador** (`working_state['deviations']` para los desvíos,
`attempts_failed` para los fallos reales) y ningún ejecutor toca el de otro.
Gate estático + prueba de comportamiento (dos desvíos y un dato equivocado
tienen que dejar 2 y 1, nunca 3).

**Alcance real del gate, dicho antes de que alguien lo asuma.** Hoy cubre la
**única** frontera donde hay veredictos ejecutándose: el desvío durante un reto
de identidad. Como el árbitro todavía no es dueño de las 22 salidas de turno
del planner, `suplantar`, `abortar`, `responder` y `continuar` no tienen
ejecutor propio, y sobre ellos este gate **no dice nada**. Cuando el árbitro
las absorba, tendrá que crecer con ellas.

Para que esa deuda no se vuelva silenciosa —que es como mueren estas cosas— la
obligación de crecer **es ella misma un test**: cada veredicto declara a quién
pertenece su contador, y ejecutar uno sin declararlo pone el gate en rojo. Una
nota al pie dependería de que alguien se acuerde de leerla; esto no.

Límite que queda incluso así, y conviene tenerlo presente: declarar un contador
**no demuestra** que no haya reinterpretación — solo impide la forma conocida
(mezclar contadores). Una forma nueva necesitará su propia comprobación, y el
precedente para escribirla será, como siempre, un caso real. Es la misma
disciplina de §9.0: sin precedente, no se añade un gate.

El precedente que justifica tanta disciplina es de esta misma casa:
`policy.evaluate` nació como "un router de predicados en el orden exacto de la
spec" y hoy tiene 203 líneas, 20 pasos —seis de ellos metidos con calzador— y
seis `save()` dentro de una función documentada como pura. Nadie decidió eso;
llegó ahí un sufijo `b` a la vez.

**Dónde migrará la complejidad después.** En cuanto el árbitro tiene
presupuesto, el riesgo se muda al modelo de hechos: cuando una arquitectura
descubre los *facts*, tiende a convertir todo en un fact. No es casualidad, es
conservación — **la complejidad migra a la capa que no tiene presupuesto**. Por
eso el modelo de hechos nace con su propia regla (§6).

> **A6 es esa misma ley aplicada al vecino de al lado.** Yo había mirado hacia
> abajo (los hechos) y no hacia el costado (el ejecutor), que tampoco tenía
> presupuesto. La heurística de la próxima auditoría no cambia, pero se usa
> mejor si se pregunta por **todas** las capas adyacentes a la que se acaba de
> acotar, no solo por la siguiente.

Y una distinción que evita sobrecorregir: **no toda migración es mala.** Cuando
A3 empuje complejidad del árbitro hacia los matchers, eso es el diseño
funcionando. `matchers.py` tiene *más* complejidad que `policy.evaluate` por
cualquier medida de volumen y está sana, porque crece en listas planas. El
problema nunca es la cantidad de complejidad: es su forma.

### 3. Compromisos: un solo concepto

`Commitment` sustituye a las cinco implementaciones de §Contexto. Un compromiso
es **una promesa hecha al cliente**, no un formulario a medio llenar.

| Slot (modelo viejo) | Compromiso (modelo nuevo) |
|---|---|
| un hueco en un formulario | una promesa hecha al cliente |
| lo posee la tool que lo necesita | lo posee la conversación |
| solo se llena desde argumentos de tool | lo avanza cualquier cosa: el cliente, una lectura, un humano |
| existe mientras la tool lo pida | existe hasta cumplirse o abandonarse |

El argumento que cierra la discusión: **la verificación de identidad no tiene
slots**. El modelo de slots literalmente no puede representar lo que falló en
la conv 13; el de compromisos sí, porque un compromiso es "qué prometí", no
"qué campos me faltan".

**Ciclo de vida — un compromiso nunca desaparece** (R5, ya vigente desde Fase 1
con un solo slot de suspensión; aquí se generaliza):

```
   adquirido ──► ACTIVO ─────────────────► COMPLETADO
                   │  ▲
        desviar ───┤  └── retomar (por la DIRECCIÓN DE RETORNO)
                   ▼
               DESVIADO        el agente atiende otra cosa y vuelve al punto exacto
                   │  ▲
      suplantar ───┤  └── ofrecer de vuelta
                   ▼
              SUSPENDIDO       otro compromiso tomó el frente (urgencia, handoff)
                   │
                   ▼
              BLOQUEADO        el dominio NO PUEDE cumplirlo → se dice la verdad
                                y SE DEJA DE PEDIR
              ABANDONADO       el cliente lo abandonó explícitamente
```

Tres distinciones vinculantes:

- **`desviar` exige DIRECCIÓN DE RETORNO.** Una pausa sin dirección de retorno
  no es una pausa: es una interrupción que se sobrevivió por suerte. Registrar
  que algo está pausado sin registrar *qué pregunta estaba pendiente* obliga a
  re-derivarla de la ventana de contexto — que es exactamente lo que falla.
- **`suplantar` ≠ `abortar`.** Un cliente cuyo perro convulsiona a mitad de
  agendar **no abandonó la cita**. Al cerrar la urgencia, una recepcionista
  dice "¿retomamos la cita de Luna?". Colapsar ambos en un `cancelled` hace esa
  frase imposible.
- **`bloqueado` ≠ `abandonado`.** `bloqueado` es *el dominio **no puede***
  (productor real: `no_vet` — una clínica sin veterinario activo no puede
  agendar, y ahí lo honesto es decirlo una vez y dejar de pedir). `abandonado`
  es *el cliente no quiere*. Confundirlos manda a un humano casos que solo
  necesitaban cerrarse, y deja pidiendo para siempre los que de verdad no
  tienen salida.

  > **Ojo con el caso que parece `bloqueado` y no lo es.** Un cliente que pide
  > darse de alta **sin** cita choca con una restricción **deliberada de
  > producto** (decisión del PO, 2026-07-30: el alta va siempre con la primera
  > cita). El dominio *sí* puede cumplir el compromiso; quien no quiere el paso
  > exigido es el cliente ⇒ el terminal correcto es `abandonado`. Lo que R6
  > prohíbe no es la restricción: es **enunciarla como schema** ("el sistema me
  > pide una fecha") y **no dejar de pedirla**. Ambas cosas las cierra este ADR
  > — la primera vía el `why` del factor (§5), la segunda vía el terminal.

**El embudo de compromisos parte los creados en terminales con dueño**:
`completado` · `abandonado` (producto) · `bloqueado` (**PO** — es R6) ·
`suplantado sin retomar` (**ingeniería**: viola R4) · `handoff` · `expirado`.
Un terminal sin dueño es un terminal que nadie arregla.

### 4. Tools con autoridad cero — cambio de contrato de `ToolOutcome`

**Salen del contrato**: `reply_text` y `needs_confirmation`.

Ordenar las tools al final de la jerarquía no basta: hay que **quitarles esas
dos capacidades**. Mientras `ToolOutcome` pueda encolar texto al cliente o
cerrar un turno, la jerarquía es decorativa.

A partir de este ADR: **una tool propone un compromiso y devuelve hechos.** El
árbitro decide, el planner redacta. El coaching indexado por código de error de
tool deja de ser la voz del agente y pasa a ser un **hecho de entrada** del
árbitro.

Es el cambio semántico más grande del sprint y la razón principal de que este
ADR se escriba antes.

### 5. Todo factor lleva su `why` (R9 estructural)

Un `Factor` es `(nombre, why, validador)`. **Un factor sin `why` no compila.**

R9 nació como criterio de revisión de copy ("si el agente pide los últimos 4
dígitos, tiene que poder contestar «¿para qué?»") y el principio
contenido/control la vuelve estructural: como el árbitro no puede decir *por
qué* se pide un dato —eso es contenido—, el porqué tiene que vivir en el
factor. Deja de depender de que alguien se acuerde en la revisión.

### 6. Modelo de hechos (R13)

> ⚠️ **ENMENDADO por [ADR p56](2026-08-01-p56-perception-situation-and-turn-as-root.md) §3**
> (2026-08-01). Lo que sigue describe los **hechos de CONTROL** y sigue vigente
> tal cual para ellos. p56 añade una segunda clase —los **hechos de SITUACIÓN**,
> que cambian *cómo se dice* y no *qué pasa*— con el gate **simétrico**: si una
> función de decisión los lee, es un bug. Sin esa separación, el gate estático de
> abajo los borraría por «código muerto» y la regla, literalmente, prohibiría la
> empatía.

**Un hecho solo existe si puede cambiar una decisión futura.** Si un dato jamás
puede modificar el comportamiento del sistema, no pertenece al modelo de
hechos: pertenece al historial de mensajes.

- El gate **vinculante** es **estático**: un hecho que ninguna fila del árbitro
  lee es código muerto.
- El análisis estadístico ("nunca fue determinante en 30 días") es **reporte,
  no gate**. Un hecho puede ser determinante en el 0.01 % de los turnos y ser
  irrenunciable — un gate estadístico borraría justo las salvaguardas.

La atribución causal (qué hechos fueron *determinantes* en un turno) se **deriva
por ablación**, nunca se declara: si la reporta quien decide, es *coverage* y se
infla. Es posible solo porque el árbitro es puro y pequeño (A1/A2/A4).

### 7. Rastro del turno: **se retiene por utilidad, no por tiempo**

`TurnDecision` (ya vigente desde Fase 1) cierra su `verdict` a los cinco
veredictos de §2. `because` sigue siendo un enum cerrado y **ortogonal al
contexto** — un enum que absorbe el contexto es peor que la prosa libre: solo
mueve el problema de sitio.

Retención:

| Qué | Cuánto | **Para qué** (es la razón, no el número) |
|---|---|---|
| `TurnDecision` en crudo | **90 días** | regresión conversacional, depuración, incidentes. Esa utilidad decae rápido: nadie depura un turno de hace ocho meses |
| Agregado mensual | indefinido | tendencias, KPIs, decisiones de producto |

> **El principio, no el número**: se retiene por **utilidad**, no por tiempo. 90
> no es mágico; es el punto donde el uso cambia de "reconstruir un caso" a
> "mirar una tendencia". Si el uso cambia, cambia el número — y eso es una
> decisión, no un ajuste de configuración.

El agregado hereda el invariante de PII: enums y referencias, jamás el cuerpo
del mensaje.

### 8. Propiedad del contrato — quién puede cambiar esto

Fase 3 introduce o cierra cuatro contratos que son, juntos, la **API interna
del runtime conversacional**: `TurnResult`, `ToolOutcome`, `Commitment`,
`TurnDecision`.

> **Regla de gobierno: todo cambio SEMÁNTICO del runtime conversacional entra
> por este ADR.**

Sin ella, dentro de seis meses alguien dice *"solo agregué un bool"* y termina
cambiando el significado de un compromiso. La regla es mecánicamente
clasificable, que es lo que la salva de volverse burocracia:

| Cambio | Requisito |
|---|---|
| Campo **añadido** opcional; valor de enum nuevo que pasa ortogonalidad y cardinalidad | **bump de versión de contrato**. Sin ADR |
| Campo **eliminado**, renombrado o re-tipado; validador cambiado; **significado** cambiado; veredicto o estado de compromiso nuevo | **ADR** (enmienda a p55 o ADR nuevo que lo supersede), referenciado en el commit |

El gate mecánico es un snapshot del contrato versionado en git que se diffea
contra la forma real — mismo patrón que `requirements.lock`. Ya existe desde
Fase 1 para tres de los cuatro tipos; `Commitment` entra al snapshot al nacer.

**Coste declarado**: cualquier campo nuevo, aunque sea trivial, obliga a tocar
el snapshot. Es exactamente el precio de que §4 no pueda ocurrir en silencio.

### 9. Disciplina de alcance del sprint

Fase 3 es la fase de mayor riesgo del plan y llega justo cuando existe una
línea base valiosa. Esa línea base **pierde valor cuanto más se mezclen los
cambios**.

> Para cada cambio propuesto durante la implementación: **¿es necesario para
> cerrar R3, R4, R7 o R9?** Si la respuesta es no, queda fuera — por bueno que
> sea. Va al backlog, no al sprint.

No es una preferencia de estilo: es lo que permite atribuir cualquier cambio de
comportamiento observado a la arquitectura nueva y no a un arreglo colado.

## Invariantes (vinculantes)

1. El árbitro es **puro**: no toca DB, red ni estado.
2. El árbitro **no produce contenido**: solo control de flujo.
3. El conjunto de veredictos es **cerrado**; ampliarlo exige ADR.
3-bis. El **ejecutor consume** veredictos: puede reaccionar a una secuencia,
   nunca reinterpretarlos. Cada veredicto lleva su propio contador (A6).
4. Las salvaguardas **preemptan** al árbitro, siempre.
5. Una tool **no termina turnos y no escribe copy al cliente**.
6. Un compromiso **nunca desaparece**: siempre está en uno de sus estados.
7. `desviar` sin dirección de retorno es un estado **inválido**.
8. Un `Factor` sin `why` **no compila**.
9. Un hecho que ninguna fila del árbitro lee es **código muerto**.
10. `TurnDecision` es **append-only** y el runtime **jamás la lee** — si la
    lógica del turno la consulta, se vuelve una segunda fuente de verdad y
    viola R7.
11. `TurnDecision` y su agregado **nunca llevan PII**.
12. Todo cambio semántico de los cuatro contratos pasa por este ADR.

## Lo que NO cambia

Esta es una jerarquía de **gobierno conversacional**, no de seguridad. Intactos:

- `run_tool` revalida **tier, verificación y ownership**. El árbitro no autoriza
  nada.
- La **confirmación tier-2** sigue siendo la barrera antes de escribir, y la
  afirmativa ejecuta los argumentos **staged**, nunca regenerados (TC-SEC-03).
- La **urgencia** sigue preemptando todo.
- El **LLM sigue sin poder autorizar**. Gana voz, no permisos.
- El aislamiento **multi-tenant** y el boundary de frontera del subsistema.

## Alternativas descartadas

1. **Dejar el ADR para el final del sprint.** Rechazado por el PO: con cuatro
   contratos cambiando a la vez, un ADR posterior no decide — documenta, y para
   entonces las microdecisiones ya se tomaron sin brújula.
2. **Salvaguardas dentro del árbitro** (boceto inicial). Convertiría la urgencia
   en una cuestión de política discutible. Un cortacircuito es la negativa a
   tener esa decisión.
3. **Tools "por debajo del LLM" pero conservando `reply_text`/
   `needs_confirmation`.** Ordenar sin quitar capacidades deja la jerarquía
   decorativa.
4. **Un motor de diálogo genérico / máquina de estados configurable** para los
   compromisos. Mismo argumento que descartó el DSL de slots en p54: mantener un
   framework cuesta en cada revisión; cinco mecanismos concretos, no.
5. **`because` como texto libre.** Da depurabilidad de UN turno; el enum da
   agregación sobre diez mil. Con texto libre, el análisis vuelve a ser manual —
   que es lo que costó tres horas en la auditoría.
6. **Gate estadístico para hechos muertos** ("nunca determinante en 30 días").
   Borraría salvaguardas raras e irrenunciables. El gate vinculante es estático;
   lo estadístico es reporte.
7. **Retención por tiempo a secas** para `TurnDecision`. Un número sin una razón
   detrás se renegocia en cada revisión de costos. El criterio es la utilidad;
   el número se deriva de ella.

## Consecuencias

- (+) Un solo lugar responde *"¿qué debe pasar con este turno?"*, y deja
  registro. Las 22 salidas se reducen a cinco veredictos + salvaguardas.
- (+) Una interrupción vuelve **al punto exacto**: R4 pasa de aspiración a
  invariante comprobable.
- (+) El tráfico real se vuelve suite de regresión: la conv 13 y la conv 12 se
  reproducen contra el árbitro nuevo y se afirma que los veredictos cambiaron —
  sin llamar al LLM, en milisegundos y a costo cero (posible solo porque el
  árbitro es puro).
- (+) "No pidas lo que ya tienes" (R3) deja de depender de que el modelo mande
  el dato en los argumentos de una tool.
- (−) **Es la fase de mayor riesgo del plan**: tabla nueva, migración de datos
  de las conversaciones vivas y cambio de contrato consumido por varios módulos.
  Mitigación: la línea base de Fase 1, la reproducción de decisiones como
  criterio de aceptación y la disciplina de alcance de §9.
- (−) Los cinco mecanismos del árbitro (sobre todo A4) van a **molestar**: habrá
  cambios legítimos que obliguen a mover un hecho a los matchers en vez de meter
  una rama. Ese roce es el mecanismo funcionando, no un defecto.
- (−) El snapshot de contratos obliga a tocarlo por cada campo nuevo, trivial o
  no. Coste aceptado y declarado en §8.

## Fuera de alcance de este ADR

- **Alta sin cita** (Fase 5 del plan): **cancelada**. Decisión del PO
  (2026-07-30): dar de alta sin cita no debe poder hacerse — el alta va siempre
  con la primera cita. La restricción es política de la clínica, no una fuga
  del schema, así que no hay nada que quitar.

  **R6 sí queda cerrado por este ADR**, por otra vía: lo que la regla prohíbe
  es que el cliente tenga que satisfacer una restricción *interna*, y el
  defecto real de la conv 12 fue **cómo se enunció** ("el sistema me pide una
  fecha") y **que no dejara de pedir**. Lo primero lo cierra el `why`
  obligatorio del factor (§5) — que exige un motivo decible en voz de clínica;
  lo segundo, el terminal `abandonado` del ciclo de vida (§3).
- **Guards conversacionales** (Fase 4): extienden el mecanismo existente a
  conducta; no cambian autoridad ni contratos.
- Transcripción de audio, cambio de proveedor LLM y presupuesto de conversación:
  carriles propios.


## Enmienda B5 — 2026-09-16

Prevalece el [contrato safety/handoff B5](../contrato-safety-handoff-b5md) en las fronteras afectadas.
Safety contextual precede funnel/identidad/goal/owner humano; consume TurnContext
causal y no interpreta binario ni depende del LLM. HumanHandoff es cola Inbox,
no notificación ni atención. Acuse nuevo solo por acción explícita de claim con
actor y timestamp, sin backfill legacy. No se cierran casos humanos sin resolver
por inactividad. Una guía finita por caso abierto pasa por Message/B4, bajo grant
específico mensaje/TurnWork/epoch; takeover posterior revoca admisión y no borra
realidad HTTP ya admitida. Humano activo conserva ownership y recibe prioridad
en bandeja, sin mensaje bot competidor. Múltiples casos legacy siguen visibles.

Corpus/protocolo **VETERINARY_REVIEW_REQUIRED**, automatización B5 apagada por
defecto y activación **PENDING_ACTIVATION_REQUIREMENTS**. No se atribuye revisión
clínica, notificación secundaria, SLA ni disponibilidad. WRITE autónomo cerrado;
sin B6–B9, E1–E5 ni P-A/P-B. No despliegue automático.

## Enmienda B6 — 2026-09-17

Prevalece el [contrato matter/binding B6](../contrato-matter-binding-b6md)
para continuidad semántica. ConversationGoal es una instancia de asunto con
bound_owner/bound_pet/bound_appointment y binding_revision propia; no equivale
a ownership ni identidad. Slots válidos tienen provenance schema 1 y snapshots
de dependencia. Correcciones retiran derivados y pending legacy atómicamente,
conservando aportes explícitos independientes. Legacy sin evidencia queda unknown.

Una READ pública incidental conserva el asunto. Un compuesto se aclara antes
de mezclar datos; reemplazo explícito abandona la instancia incompatible. «Olvida
eso» abandona el asunto conversacional, nunca cancela una cita. Homónimos/plural
ambiguo no crean binding. Solo nombre contextual exacto, continuación inmediata
singular y corrección explícita; referencias históricas y multi-goal avanzado
siguen fuera. El LLM no asigna entidades ni provenance y no autoriza operaciones.

Policy aplica B6 después de safety/owner B5 y antes de confirmations. Planner
recibe proyección vigente; tools validan argumentos y resultados contra scope y
revisión. TurnContext conserva causalidad y TurnChanges valida CAS al publicar
con B3. No cambios B4 ni infraestructura. WRITE autónomo permanece cerrado.
H12: alcance beta sujeto a evidencia del acta. H13: mitigación parcial, B7/E1
pendientes. Activación PENDING_ACTIVATION_REQUIREMENTS; no despliegue automático.
Véase [ADR B6](../decisions/2026-09-17-b6-matter-entity-bindingmd).

## Enmienda B7A — 2026-09-18

El commitment/matter B6 alimenta ConversationOperation: definición exacta e
inmutable ligada a goal, entidades y binding_revision. Cambio de revisión o
abandono retira PENDING; reemplazo crea otra fila enlazada, sin editar parámetros.
TurnDecision explica la decisión pero no autoriza efectos. B3 prepara al publicar
el estado local del turno; no envía propuesta ni concede consentimiento.
Contrato y lifecycle: [B7A](../contrato-conversation-operation-b7amd).
