# ADR p58 — Continuidad conversacional e identidad del agente

> **Enmienda B3 (2026-09-15).** Recuperar TurnWork conserva miembros/cursor B1;
> el historial no se calcula desde pendientes actuales. Reset/unlink cercan
> trabajo anterior aumentando epochs de los episodios afectados bajo locks de
> Conversation; conservan historial e identidad según las reglas existentes.
> Deferred conserva estado local del asunto para continuidad, sin interpretar
> correcciones semánticas B6. [Contrato B3](../contrato-trabajo-durable-b3.md).

> **Enmienda B1 (2026-09-14).** Hechos de contacto, transcript y señal de contacto previo usan un límite exclusivo `(created_at,id)` anterior al primer inbound de `TurnContext`. `PENDING`/`PROCESSED` no determinan qué es pasado. El alcance exige organización, contacto y cuenta; el transcript privado de otros episodios solo se lee con verificación vigente. Se conserva la excepción D19 para hechos de existencia/fecha de contacto previo, sin entregar su contenido. Para historia causal se admiten entrantes recibidos y salientes emitidos; la visibilidad inmediata de un borrador humano en Inbox no acredita emisión. El turno actual se agrega una sola vez desde C1, nunca como historial anterior. No se cambia la verificación, su TTL ni el anti-eco. [Acta B1](../implementacion-b1-agente-whatsapp-2026-09-14.md).

**Fecha**: 2026-08-17
**Estado**: **ACEPTADO** (PO, 2026-08-15/16) — **implementado y en producción** (`a00afb6`; F5 en `91c8618`)
**Addendum de visibilidad del Inbox**: 2026-08-23
**Contexto de producto**: subsistema del agente WhatsApp, tras dos defectos observados en el piloto
**Plan de implementación**: [`docs/agent-continuity-plan.md`](../agent-continuity-plan.md) — catorce revisiones, con el veredicto y el motivo de cada punto
**Relación con p56/p57**: los **complementa**. Aplica al reto conversacional el mismo criterio que p57 §5.5.3 ya había fijado para la verificación humana, y no toca ninguno de sus invariantes.

---

## Contexto

Dos síntomas del piloto, reportados por el PO el 2026-08-15:

1. *«Cada conversación que se cierra y el cliente manda mensaje se crea una
   nueva, empezando desde 0.»* Un solo contacto acumuló **19 conversaciones**;
   la 20 arrancó preguntando quién era.
2. *«Pide el nombre en el mismo texto donde menciona el nombre con el que se
   identifica.»*

La auditoría en producción encontró que el segundo no era un defecto de
redacción sino **un bypass de verificación**. Conv 18, `ToolExecution` 79-81:

```
20:54:50  identify_client  aporto=[pet_name]              verificado=false
20:55:08  in  «ya me haz atendido»
20:55:19  out «Claro, Andrés 😊 Solo necesito tu nombre…»   ← fuga de PII
20:55:36  in  «Entonces para que me lo preguntas»
20:55:37  in  «si ya lo sabes»
20:55:48  identify_client  aporto=[owner_name, pet_name]  verificado=TRUE
```

**El cliente nunca escribió «Andrés».** El modelo lo leyó del bloque de contexto
—que publicaba `contact.owner.name` con solo `phone_match`—, se lo pasó a
`identify_client`, y `try_verify_by_owner_name` lo comparó contra el mismo
valor. El segundo factor no existía: el sistema se verificaba contra un dato que
él mismo había suministrado.

---

## Decisiones

### 1. El nombre del titular deja de ser factor de verificación

Con `phone_match`, el **único** factor de autoservicio es el nombre de una
mascota. Los otros dos candidatos no prueban nada:

| Factor | ¿Prueba quién escribe? |
|---|---|
| `owner_name` | **No.** El sistema lo conoce y lo enseña —al modelo en el contexto, al staff en la bandeja— y es lo menos secreto de una persona |
| `phone_digits` | **No, y es circular**: el contacto llegó *por ese número* |
| `pet_name` | **Sí.** Exige conocer el expediente y no se deduce del canal |

**No es un criterio nuevo.** `ContactIdentityVerification.EVIDENCE_CHOICES`
(p57 §5.5.3) ya excluye toda evidencia telefónica con este razonamiento textual:
*«el número ya se sabe que coincide —es lo que creó el caso—, así que usarlo
como prueba sería circular»*. p58 aplica esa misma regla al reto conversacional,
donde no se aplicaba.

**Consecuencia aceptada por el PO (2026-08-15)**: un `Owner` **sin mascotas
registradas** —posible, se crean desde el POS— no tiene factor de autoservicio y
va a verificación humana, con un `reason_detail` que dice qué pasó y qué hacer.
Si esos escalados resultan frecuentes, la respuesta **no** es reponer
`owner_name`: es revisar por qué existen esos `Owner`.

### 2. La autoridad sobre la prueba es del servidor, nunca del modelo

El modelo aporta el **valor**. No elige nada más:

| Qué | Quién decide | Por qué |
|---|---|---|
| Qué mensaje prueba el aporte (`from_message`) | Servidor, desde la ráfaga | Si lo eligiera el modelo, elegiría su propia prueba |
| Con qué tolerancia se juzga (`match_mode`) | Servidor, con siete condiciones | Si se dedujera del call site, el modelo saltaría la gramática pasiva llamando a `identify_client` — el mismo bypass con otro nombre |
| Qué cuenta como mención de la mascota | Gramática **cerrada** | Un token suelto no es evidencia: con una mascota «Sol», *«¿va a haber sol mañana?»* promovía |
| La pregunta que abre el reto | El sistema la añade | Si la redactara el modelo podría preguntar por los dígitos y sellar eso como si fuera el reto de la mascota |

La negación se evalúa **por función sintáctica**: se rechaza la de identidad
(«no es Luna»), se acepta la clínica («Luna no come») — una regla ciega sobre
`no` tiraba uno de los mensajes más importantes que manda un cliente.

### 3. Un solo camino a la promoción

`identity._promote` tiene **exactamente un llamador**: el servicio de evidencia.
Antes había dos rutas que promovían —el router y la tool— y **ninguna
comprobaba si el dato lo había dicho el sistema primero**; la pasiva además no
satisfacía el slot del compromiso, así que el agente volvía a pedir la mascota
después de haber verificado con ella.

El invariante se verifica con un **gate estático**, no con una convención.

### 4. La sesión es del episodio; el contexto, de la persona

`CLOSED` **sigue siendo terminal** —un mensaje posterior abre un hilo nuevo—
pero eso ya no significa empezar de cero: el transcript que ve el modelo sale de
`(contact, channel_account)`.

**La sesión NO se volvió permanente, y es deliberado.** De ella cuelgan las
métricas de negocio (`compute_business_metrics` cuenta por
`Conversation.created_at`), el presupuesto de llamadas, el claim, los
`HumanHandoff`, los `ConversationGoal` y el `flow`. Hacerla eterna habría roto
todo eso para arreglar el transcript.

**El historial cruzado exige verificación vigente.** Sin ella el contexto se
limita a la conversación actual: el transcript viejo puede contener el nombre de
una mascota, que ahora es la respuesta del reto. Los hechos de contacto
(`ya_hablamos_antes`, `ultima_vez`, `ultimo_mensaje_hace`) sí viajan siempre
porque no son PII, y se calculan **excluyendo la ráfaga en curso**.

### 5. Memoria sobre hechos, no sobre texto

Un hilo continuo no es memoria: la ventana sigue siendo 12 turnos / 40 mensajes.
Las tools de memoria (`get_past_visits`, `get_recent_product_queries`) leen
**hechos**, solo de ejecuciones exitosas, y para agenda **manda el estado del
dominio** — el log dice qué se intentó, `Appointment` dice qué es verdad.

**No se lee `MedicalRecord`**: el rol `AGENT` no tiene `medicalrecord.*` por
decisión escrita, y el diagnóstico no sale por WhatsApp. La cita da el *motivo*,
que es lo que el cliente dijo al agendar.

### 6. `Conversation.summary` se retira

Declarado en É-F1 y nunca escrito ni leído (20 filas en producción, 0 con
contenido). Un resumen generado por el LLM habría sido una segunda fuente de
verdad —lo que prohíbe ADR p50— con compresión con pérdida sobre datos que ya
teníamos exactos.

---

## Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| **Reactivar la conversación cerrada** (propuesta inicial) | Convierte `Conversation` en dos conceptos incompatibles: sesión operativa y unidad de métrica. Un hilo de agosto reusado en diciembre no contaría como interacción de diciembre |
| **Una tabla `ContactThread` nueva** | El thread ya está modelado: `ContactIdentity`, unique por `(org, canal, external_id)`. La `InteractionSession` propuesta era la `Conversation` actual campo por campo |
| **Ventana de reactivación de N días** | Constante sin fundamento. El baseline es el humano: ve un chat con todo arriba, y no se confunde por ello |
| **Promoción pasiva solo con reto activo** | Más segura, pero reintroduce el bucle que É-F5 eliminó: «cita para Luna» dejaría de verificar y el cliente repetiría el nombre que ya dijo |
| **Marcar el factor «quemado» por contacto** | No hay dónde persistirlo, y ninguna marca resuelve que el grounding prueba **autoría, no independencia**: staff dice el nombre y el cliente lo repite. Retirar el factor cierra las dos cosas |
| **Resumen conversacional rodante** | Viaja en cada turno aunque no sirva, comprime con pérdida y crea una segunda fuente de verdad. La memoria es una **tool**, bajo demanda — mismo movimiento que p56 §5 con la identidad |
| **`Message.sent_at`** para ordenar emisiones | El requisito que lo pedía («el último saliente emitido») no cargaba peso. Se retiró el requisito, no se añadió la columna |

---

## Riesgo residual, aceptado explícitamente

`pet_name` es un factor de **conocimiento de baja entropía**: puede estar en
redes sociales o conocerlo un familiar. **No es un secreto fuerte y no debe
describirse como autenticación fuerte** en ningún documento ni UI.

Lo que habilita (sin cambios respecto a antes de p58): leer sus mascotas, citas
y vacunas; crear, mover y cancelar **sus** citas; dar de alta otra mascota en su
expediente. Lo que **no**: nada de billing, caja ni pagos; expedientes clínicos;
datos de otro cliente; operar sobre un `Owner` ajeno —eso exige el reto triple o
verificación humana (FLUJO-C).

**Si el nivel de sensibilidad de lo que el agente pueda hacer sube, este factor
no es suficiente y hay que revisarlo.** Queda anotado como condición, no como
advertencia genérica.

---

## Lo que NO está verificado

Los tests anclan que las reglas y los ejemplos están en el prompt, y que el
nombre no viaja cuando no debe. **Ninguno prueba que el modelo obedezca**: eso
necesita un eval contra el proveedor real, y un `assertIn` sobre una plantilla
no lo decide. Los guards son la red determinista debajo del prompt, no su
sustituto.

---

## Reglas que este ADR añade

1. **`identity._promote` tiene exactamente un llamador** (gate estático). Una
   vía nueva que promueva por su cuenta reintroduce la falta de anti-eco.
2. **El modelo no elige su prueba, ni el régimen con que se le juzga, ni la
   pregunta que abre el reto.**
3. **Jamás describir `pet_name` como autenticación fuerte.**
4. **Los goals de identidad tienen un escritor único** (`start_identity`, desde
   la rama `verification_required` del planner). `open_goal` los rechaza.
5. **`policy` no reanima un compromiso por pertenecer a `IDENTITY_GOALS`** sino
   por el predicado `is_resumable_identity_goal`: `identity_triage` es
   maquinaria retirada y volvía al frente arrastrando un `GoalSpec` sin
   conductor.
6. **Un saliente que el cliente no recibió no cuenta como emitido.** El
   anti-eco usa `channels.selectors.emitted_outbound`, limitado a
   `sent`/`delivered`/`read`. Desde el addendum del 2026-08-23,
   `visible_messages` tiene una excepción operacional deliberada: incluye el
   `pending` escrito por `human_staff` para que el Inbox lo muestre de
   inmediato y para mantener continuidad en los consumidores históricos de
   contexto. Los `pending` de agente/sistema y todos los `failed`/`discarded`
   siguen fuera. Responder deja el episodio en `human_active`, pero ningún
   consumidor debe usar `visible_messages` para inferir entrega o anti-eco.

## Enmienda B4 — emisión observable (2026-09-16)

Se sustituye para el sender la ausencia previa de fechas de emisión por
`Message.provider_accepted_at`, `delivered_at` y `read_at`, sin otra fecha sent.
Son primeras observaciones locales distintas; `created_at` no acredita entrega.
Legacy conserva fechas NULL. `SENT` nuevo exige wamid compatible, mientras
SENDING/UNCERTAIN nunca prueban emisión autorizable. Inbox puede mostrar estos
estados sin incorporarlos al selector causal/de emisión B1 ni conceder permisos.
No se modifican identidad, anti-eco, bindings ni autorización B7.
Contrato vigente: [B4](../contrato-sender-durable-b4.md).
