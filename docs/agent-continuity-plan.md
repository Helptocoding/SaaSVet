# Plan — continuidad conversacional e identidad del agente

**Fecha**: 2026-08-16 (rev. 14 tras decimotercera revisión externa)
**Estado**: **COMPLETO Y EN PRODUCCIÓN** (`a00afb6`, desplegado 2026-08-17).
F0 (`9df40b8`) · F1a (`8cab9c5`) · F2+F3 (`778bb15`) · F1b (`1b59fc4`) ·
F4 (`3301114`) · inbox agrupado (`bf897d4`, `a9e7043`) · retiro de los endpoints
por episodio (`1376c3f`, `1034db5`) · **F5** (retiro de `Conversation.summary`).

> **La remediación corrió en el despliegue** y encontró exactamente lo que la
> auditoría predijo: 1 contacto degradado (`contact 1`, `verified_at` =
> `2026-08-14 20:55:48`, el instante del `ToolExecution 81` donde el sistema se
> verificó contra un nombre que él mismo filtró) y 1 reto `identity_triage`
> cerrado como `retired_machinery`. Backfill de `Message.contact`: 470/470.
>
> **Lo único que sigue sin verificar es la obediencia del modelo a F1a.** Los
> tests anclan que las reglas y los ejemplos están; que el modelo las siga
> necesita un eval contra el proveedor real.

> **Qué quedó hecho en F0** — suite del agente en verde (669 tests):
> `agent/identity_evidence.py` (servicio único: gramática cerrada, procedencia
> derivada por el servidor, `match_mode`, anti-eco, TTL, reducer puro +
> reconciliador, transacción con cierre y reanudación) · `identity.py` (matchers
> puros, `_promote` con un solo llamador, `try_verify_by_owner_name` eliminada,
> puntuación como límite de token) · `goals.py` (`TITULAR_CHALLENGE` solo `pet`,
> choke point de procedencia en `satisfy`, invariante semántico en
> `finish_identity`, tres conjuntos + predicado, `open_goal` rechaza identidad,
> `bind`/`mark` de la pregunta) · `policy.py` (ruta pasiva por el servicio,
> reconciliación ordenada, reanudación por predicado, escalado por eco) ·
> `planner.py` (escritor único del reto, cláusula determinista, guía reescrita,
> guard de fuga) · `worker.py` (ráfaga como objetos, sellado al enviar) ·
> `prompts.py` (nombre gateado por verificación vigente, hechos sin procedencia
> no viajan) · `channels/selectors.py` (mensajes realmente emitidos) ·
> `tier0.py` (dos plantillas, declaradas en el gate de salvaguardas) ·
> `remediate_identity_f0` (comando idempotente, dry-run por defecto) ·
> `test_identity_evidence.py` (43 casos: gramática adversarial, anti-eco,
> `match_mode`, transacción, caducidad, remediación y **gate estático** de
> `_promote`).
>
> **Qué quedó hecho en F1a** — suite del agente en verde (684 tests):
> `prompts.py` v11 — el bloque IDENTIDAD se parte por el valor de `verificado`;
> la prohibición pasa de «no afirmes que quedó verificado» a «no lo afirmes tú,
> pero si los DATOS lo traen, úsalo»; deja de enumerar los factores retirados y
> de formular la pregunta del reto (la añade el sistema); explica la caducidad en
> vez de disimularla; y lleva un ejemplo trabajado por cada rama.
> `test_prompts.VerifiedBehaviourPromptTests` ancla las reglas, los ejemplos, el
> bump de versión y —la otra mitad— que el nombre **de verdad** no viaja cuando
> `verificado` es false. **Lo que NO prueban: que el modelo obedezca.** Eso
> necesita un eval contra el proveedor real; un `assertIn` sobre una plantilla no
> lo decide.
>
> **Qué quedó hecho en F2 + F3** — 734 tests verdes (agent + channels):
> `Message.contact` denormalizado con migración **expand-first en tres pasos**
> (campo nullable → backfill por lotes → índice `CONCURRENTLY`) ·
> `Conversation.close_reason`, estampado en los cuatro sitios que cierran ·
> `prompts._history_queryset`: el transcript sale de `(contact, channel_account)`
> **si la verificación está vigente**, y de la conversación actual si no (D19) ·
> `_has_outbound` y los hechos `ya_hablamos_antes`/`ultima_vez`/
> `ultimo_mensaje_hace` derivados del contacto, **excluyendo la ráfaga en curso**
> · creación de sesión serializada sobre `ContactIdentity` (el `select_for_update`
> de una conversación no protege la ausencia de fila) con resolución de
> duplicados **por precedencia**, que se detiene si hay dos sesiones humanas ·
> `test_f2_continuity.py` (16 casos: continuidad, aislamiento por contacto y por
> cuenta, gate de verificación, `failed` fuera del historial, hechos de contacto y
> carrera de sesiones).
>
> **Qué quedó hecho en F1b + F4** — 748 tests verdes: `guards.check_behaviour`
> gana `has_history` y la violación `denies_history` (SOFT) — «no tengo contexto
> de lo anterior» era honesto cuando el contexto moría con el hilo y desde F2
> contradice el estado propio · `get_past_visits` (mismo `appointment.list`,
> filtro invertido; **nunca `MedicalRecord`**) y `get_recent_product_queries`,
> ambas `min_verification: confirmed_in_chat` y con alcance
> `(contact, channel_account)` · proyección propia `product_query_resolved` con
> el producto **resuelto** —no `args_redacted`, que guarda el texto crudo del
> cliente pese a declararse libre de PII (R15)— y con `tool_name` propio para no
> contar dos ejecuciones por búsqueda · predicado explícito de «exitosa»
> (`http_status` < 400 o local, `error_code` vacío, `policy_decision` no denegada
> ni escalada), porque `ToolExecution` no tiene campo `success` ·
> `test_f4_memory.py` (11 casos: cruce de sesiones, aislamiento por contacto y
> cuenta, y las tres formas de no-éxito).
>
> **Fuera de F2, a propósito**: el **inbox agrupado** (§4). Necesita `public_id`
> en `ContactIdentity` y `ChannelAccount`, ruta compuesta y trabajo de frontend;
> es una superficie distinta y merece su propio cambio. Lo que arreglaba la queja
> del agente ya está.
**Origen**: queja de piloto — «cada conversación que se cierra arranca de cero» +
«me pide el nombre en el mismo mensaje donde me llama por mi nombre».

> **Historial de revisiones.**
> **Rev. 1** proponía *reactivar* la conversación cerrada. Una revisión externa
> mostró que eso convierte `Conversation` en dos conceptos incompatibles y rompe
> las métricas de negocio.
> **Rev. 2** dejó de reactivar: la sesión sigue siendo por episodio y lo que pasa
> a leerse por contacto es el **contexto**.
> **Rev. 3** corrigió el **alcance por cuenta de canal**, un orden de fases
> imposible, un `ultima_vez` que diría «hace segundos» y un selector de mensajes
> visibles que incluía salientes que el cliente nunca recibió. Además proponía
> subir la evidencia de identidad de `flow` (por sesión) a un store por contacto.
> **Rev. 4** **retira ese store**. Una tercera revisión mostró que abría
> tres agujeros nuevos —acumulación de factores sin ventana, dígitos sin
> candidato contra el que comprobarlos, y un anti-eco que necesita historia que
> no existe— y ninguno de los tres era necesario: la evidencia a nivel contacto
> era **continuidad, no seguridad**. Retirada, la acumulación vuelve a estar
> acotada a la sesión — que la rev. 4 creyó una ventana de 24 h y **no lo es**
> (rev. 5): la ventana real la fija `IDENTITY_EVIDENCE_TTL`. Rev. 4 además hace de la **remediación del contacto comprometido** una
> precondición de F1a, ancla el guard en evidencia **reciente** y saca F4 de
> encima de una violación conocida de R15.
> **Rev. 5** corrige una premisa falsa de la rev. 4 —la sesión **no** muere
> a las 24 h, el cierre es por inactividad— y con ella cierra la última ventana
> abierta: `IDENTITY_EVIDENCE_TTL`. Añade que **`from_message` lo deriva el
> servidor** (si lo eligiera el LLM la procedencia sería teatro) y **retira
> `owner_name` como factor de verificación**, lo que elimina la necesidad de
> marcar factores «quemados» y neutraliza el eco por vía humana.
> **Rev. 6** cierra el contrato del factor que queda. Al ser `pet_name` el
> único de autoservicio, se centraliza la **segunda ruta de verificación** que
> vivía fuera de todo control (`policy.py:224`), el anti-eco pasa a **primera
> mención dentro del TTL**, el TTL gana un **reducer único**, el **historial
> cruzado exige verificación vigente**, `TITULAR_CHALLENGE` deja de pedir el
> titular, `try_verify_by_owner_name` se **elimina**, y el riesgo residual del
> factor queda aceptado por escrito (§2.3).
> **Rev. 7** cierra el contrato de implementación: el **plumbing del burst**
> (hoy solo viajan cuerpos, sin PK que sellar), la **firma y transaccionalidad** del
> servicio, el **split reducer puro / reconciliador**, el **selector de mensajes
> realmente emitidos** adelantado a F0, `_promote` con **un solo llamador** (ambas
> funciones de mascota promovían, no solo la del router) y el **orden dentro del
> turno** como requisito.
> **Rev. 8** cierra la última puerta abierta: la ruta pasiva **no extraía
> entidad** —tokenizaba y promovía con cualquier coincidencia, así que una mascota
> llamada «Sol» verificaba con «¿habrá sol mañana?»—. Añade marco explícito, match
> exacto y candidato único (D30), la reasignación de la identidad fresca tras la
> transacción (D31), el compromiso como opcional (D32) y la secuencia exacta del
> turno.
> **Rev. 9** convierte el marco de la ruta pasiva en **gramática cerrada**
> («¿venden lentes para sol?» pasaba el marco laxo), corrige que el «match exacto»
> de la rev. 8 habría roto el caso compuesto («cita para Luna» con «Luna Bella»
> registrada), hace que el servicio devuelva **todo** el estado mutado —no solo la
> identidad— y mete **`finish_identity` + reanudación** dentro del contrato
> atómico: sin eso, el agente quedaba atascado justo después de verificar bien.
> **Rev. 10** separa el matcher de **aceptación** del de **revelación** —eran
> necesidades opuestas y reusar el estricto dejaba pasar un eco con typo—, evalúa la
> negación **por función sintáctica** (una regla ciega tiraba «Luna no come»), cierra
> `se llama` con sujeto posesivo, extiende el refresh explícito al **reconciliador**,
> declara la normalización de tokens, y **retira** el algoritmo de precedencia de
> reanudación: los constraints de `ConversationGoal` lo vuelven una aserción, no una
> selección.
> **Rev. 11** (esta) hace ejecutable el rechazo y el lifecycle: `resolve_pet_evidence`
> devuelve una **unión cerrada** y verificar un `ECHO_REJECTED` es inexpresable; las
> dos rutas escalan al mismo estado final; y se añade el invariante **semántico** de
> goals, porque los constraints resuelven cardinalidad y no significado —
> «identity activo + identity suspendido» lo produce `open_goal`, así que verificar
> bien podía terminar reanudando otro reto de identidad.
> **Rev. 12** cierra la **autoridad** del régimen probatorio: `match_mode` lo
> deriva el servidor, porque deducirlo del call site dejaba al modelo saltarse la
> gramática pasiva llamando a `identify_client`. Declara el **escritor único** de
> goals de identidad (hoy no hay ninguno en producción, así que el modo tolerante
> sería inalcanzable salvo por resurrección), corrige una afirmación falsa de la
> rev. 11 sobre `open_goal`, y añade el cierre de las **filas legacy** de la FSM
> retirada, que `policy` resucita al frente.
> **Rev. 13** exige que la pregunta del reto **se haya emitido de verdad**
> —un `pet_asked_at` suelto solo probaba la intención, y un saliente `pending` o
> `failed` habría habilitado el régimen tolerante sin que el cliente viera nada—,
> nombra al **único caller productivo** que crea el reto, y convierte «huérfano» en
> un predicado con tres conjuntos, con orden de despliegue y remediación
> idempotente.
> **Rev. 14** (esta) cierra el último hueco de autoridad: la **pregunta del reto la
> pone el sistema** (D38), porque la guía actual deja al modelo preguntar por los
> dígitos y sellar eso como si fuera el reto de la mascota; retira el requisito de
> «último saliente emitido» —que era mío, no era demostrable y pedía una migración
> innecesaria— y lo sustituye por `pet_asked_at` estampado en el envío; y nombra al
> tercer escritor, el que **liga** la pregunta al encolarla.
> El §7 documenta los veredictos de las trece revisiones con su motivo.

---

## 0 · Evidencia (producción, 2026-08-15, deploy `cf21f85`)

### 0.1 Proliferación de hilos

Un solo contacto (`contact_id=1`) acumula **19 conversaciones**, 18 cerradas.
No hay una sola causa:

| conv | idle al cerrar | causa |
|---|---|---|
| 1, 2, 7, 12, 13, 14, 16 | **24.00 h** | `policy.close_inactive_conversations` |
| 4, 11, 15, 19 | 0.003 – 0.026 h | cierre **manual** desde la bandeja (`close_conversation` / `reset_contact_identity`) |
| 3, 5, 6, 8, 17, 18 | 0.3 – 14.7 h | manual |

`policy.CLOSE` solo lo produce **opt-out** ("stop"): ninguna despedida cierra.
Tras cerrar, `services.get_or_create_open_conversation` (`services.py:216`)
excluye el hilo cerrado y abre otro — el hilo 5 nació **10 segundos** después de
cerrarse el 4. El agente solo lee mensajes de *su* conversación, así que empieza
de cero.

### 0.2 Bypass de verificación de identidad — **P0 de seguridad, vivo**

Conv 18, `ToolExecution` 79-81:

```
20:54:50  identify_client  aporto=[pet_name]              verificado=false
20:55:08  in  «ya me haz atendido»
20:55:19  out «Claro, Andrés 😊 Solo necesito tu nombre…»   ← fuga de PII
20:55:36  in  «Entonces para que me lo preguntas»
20:55:37  in  «si ya lo sabes»
20:55:48  identify_client  aporto=[owner_name, pet_name]  verificado=TRUE
```

**El cliente nunca escribió «Andrés».** El modelo lo leyó de
`context['cliente']` (`prompts.py:354`, que publica `contact.owner.name` con
solo `phone_match`), se lo pasó a `identify_client`, y
`identity.try_verify_by_owner_name` lo comparó contra el mismo valor →
`_promote` → `confirmed_in_chat`.

Dos defectos en uno:

1. **Fuga**: se revela el nombre del titular a un contacto no verificado
   (teléfono reciclado, familiar con el celular, SIM robada).
2. **Bypass**: el segundo factor deja de existir — el sistema verifica contra un
   dato que él mismo suministró. Contradice el principio escrito en
   `tools.py:1723` («el cliente APORTA, el sistema VERIFICA — jamás al revés»).

Estado hoy: `contact_id=1` está en `confirmed_in_chat` por esta vía.

### 0.3 No existe conducta para el caso verificado

Conv 20, con el contacto **ya** `confirmed_in_chat`:

```
in   sabes quién soy?
out  Todavía no, Andrés. ¿Me confirmas tu nombre y el de tu mascota? 🐾
```

El `SYSTEM_PROMPT` dedica ~30 líneas a IDENTIDAD y **todas son sobre pedir**.
No hay una sola regla para cuando ya se sabe, y
`«Nunca digas ni des por hecho que alguien quedó verificado»` empuja al modelo a
desconfiar de un dato que el sistema le dio como cierto.

### 0.4 Saluda como nuevo a un cliente veterano

`prompts._has_outbound(conversation)` deriva `first_contact` **del hilo**. Conv
11 (décimo hilo del mismo contacto) abrió con
`«¡Hola! Bienvenido a Clinica Bebe coche 🐾»`.

### 0.5 Presupuesto — problema de la rev. 1, ya no del plan

`policy._budget_exhausted` → `conversation.total_llm_calls >= cap` (100 en prod,
`.env.prod:215`). Con la rev. 1 (hilo permanente) el contador nunca se reseteaba
y condenaba al cliente. **Desde la rev. 2 la sesión sigue siendo por episodio,
así que el presupuesto sigue significando lo que significaba.** Se conserva sin
cambios. Calibración medida (llamadas por mensaje entrante):

```
conv 16: 62/34 = 1.82   conv 3: 1.63   conv 18: 1.38   conv 17: 1.33
conv 15: 1.20   conv 19: 1.00   conv 12: 0.48   conv 1: 0.33
```

Mediana ≈1.2, máximo 1.82 ⇒ 100 llamadas ≈ 55 turnos por episodio. Correcto.

### 0.6 Defectos preexistentes que este plan destapa

Ninguno lo introduce el plan; todos empeoran al unir sesiones:

| Defecto | Evidencia |
|---|---|
| Salientes `failed` entran al contexto del modelo | `worker.py:350` los marca cuando la ventana de 24 h cerró (**el cliente no los recibió**); `prompts.py:398` solo excluye `DISCARDED` |
| `Message.conversation` es nullable | `channels/models.py:163` — media huérfana y errores de parseo |
| `ContactIdentity` no es direccionable por API | no hereda `PublicIdMixin` |
| `Conversation.summary` es campo muerto | `models.py:161` — nadie escribe, nadie lee |
| `args_redacted` documentado como libre de PII, pero guarda la consulta literal del cliente | `models.py:305` y `executor.py:81` dicen «SIN PII cruda, regla R15»; `tools.py:251` guarda `{'query': <texto del cliente>}` |
| `Conversation` no tiene `close_reason` | ningún cierre registra por qué |

---

## 1 · Arquitectura: el thread ya existe, pero hay que fijar su alcance

El defecto de fondo de la rev. 1: `Conversation` es a la vez sesión, dueño del
claim y de los `HumanHandoff`, dueño de `ConversationGoal`/`flow`/`pending_action`/
presupuesto, **unidad de métrica comercial**
(`metrics.compute_business_metrics:281` cuenta por `Conversation.created_at`) y
unidad de muestreo de calidad. Volverla permanente rompe lo último.

El thread permanente ya está modelado — `ContactIdentity`, unique
`(organization, channel_type, external_id)` — pero **su unicidad no incluye
`channel_account`**, mientras `Conversation` y `Message` sí pertenecen a una
cuenta concreta. Como `ChannelAccount.external_account_id` es unique **global**,
nada impide que una organización opere dos números.

### La regla, con su alcance explícito

> **La sesión sigue siendo por episodio.**
> **El contexto se lee por `(contact, channel_account)`.**
> **La identidad sigue siendo por `contact`.**

El reparto no es cosmético:

| Concepto | Alcance | Motivo |
|---|---|---|
| Transcript que ve el LLM, memoria, anti-eco, inbox agrupado | `(contact, channel_account)` | Dos números de la misma clínica pueden ser dos flujos (agenda vs. mostrador). Mezclar sus hilos mete al modelo en una conversación que no es la suya. `Message` ya tiene la FK → **cero migración** |
| `verification_level`, `owner`, `linked_via`, `privacy_notice_sent_at` | `contact` | Es un hecho sobre **quién es la persona dentro de la organización**, no sobre por qué número escribió. Partirlo obligaría a re-verificarse por cambiar de número de la misma clínica: fricción sin ganancia — el `Owner` es el mismo tenant |
| Sesión, presupuesto, claim, handoff, goals, `flow` | `Conversation` | Sin cambios |

**No es cross-tenant.** Una `Organization` es una clínica y
`external_account_id` es unique global, así que un número pertenece a
exactamente una organización por constraint. Dos cuentas de una org son la misma
clínica; el riesgo es mezclar **flujos**, no clínicas.

### Consecuencia sobre `Message`

`Message` solo tiene FK a `conversation` (nullable). Para leer por contacto se
añade `Message.contact` denormalizado + índice
`(organization, contact, channel_account, created_at)`.

---

## 2 · Decisiones cerradas

| # | Decisión | Motivo |
|---|---|---|
| D1 | La sesión no cambia; el contexto se lee por contacto. **No hay reactivación** de conversaciones cerradas | Da el chat permanente sin convertir la sesión operativa en la unidad de todo el sistema. Preserva `metrics.py` sin tocarlo |
| D2 | El thread es `ContactIdentity`, no una tabla nueva — **con alcance de contexto por `(contact, channel_account)`** y alcance de identidad por `contact` | Ver §1. La tabla nueva sería renombrar lo que ya existe; el alcance sí faltaba |
| D3 | Presupuesto **por sesión**, valor actual (100) | Medido: ≈55 turnos por episodio |
| D4 | El nombre del titular **proveniente de `Owner`** no viaja al modelo sin verificación vigente. Un nombre que **el propio cliente aportó** sí puede viajar como hecho anclado, si tiene procedencia válida | Cierra fuga y bypass (§0.2) sin amputar lo que el cliente dijo de sí mismo |
| D4b | **`owner_name` deja de ser factor de verificación** para contactos ya vinculados (`phone_match`); único factor de autoservicio = `pet_name`. Sigue siendo **clave de búsqueda** en el reto familiar. Sin mascotas registradas → escalado humano **explicado** (§2.2.2) | §2.2. Cierra de raíz el factor quemado y la fuga por vía humana, sin migración. Y no es criterio nuevo: `EVIDENCE_CHOICES` ya excluye toda evidencia basada en el teléfono por circular (ADR p57 §5.5.3) — D4b aplica esa regla al reto conversacional. **Costo aceptado por el PO el 2026-08-15** |
| D5 | **La evidencia de identidad se queda en `Conversation.flow`** (ámbito de sesión), con procedencia sellada. **NO** se sube a un store por contacto | Rev. 3 proponía subirla; rev. 4 lo retira. Ver §2.1 — la persistencia era continuidad, no seguridad, y abría tres agujeros nuevos |
| D6 | **Dos familias de matcher, con propósitos opuestos.** **Aceptación** (¿el cliente aportó el factor?): `passive_free_text` → exacto normalizado contra el nombre completo o un token completo ≥3 chars, **sin** distancia de edición; `challenge_response` → `_name_matches` tolerante. **Revelación** (¿lo dijimos nosotros antes?): **siempre conservador** — nombre completo, tokens, **y lev≤1**. `phone_digits` → comparación exacta. El hecho sellado guarda **`match_mode`** | Las dos necesidades apuntan al revés: aceptar exige estricto (menos falsos positivos), detectar un eco exige tolerante (menos falsos negativos). Con un solo matcher estricto: staff escribe «Lun**n**a», el anti-eco no lo encuentra, el cliente dice «Luna» y **promueve con un factor sembrado**. Y con «Luna Bella» revelada, «Luna» debe contar como repetición. Sin `match_mode` sellado, la auditoría no distingue qué régimen aceptó la evidencia |
| D33 | **Rechazo por anti-eco ⇒ escalado con motivo legible**, nunca reintento. `resolve_pet_evidence` devuelve una **unión cerrada** (`NO_EVIDENCE` · `SEALED_EVIDENCE` · `ECHO_REJECTED`) y verificar un `ECHO_REJECTED` debe ser **imposible de expresar**, no algo que haya que recordar no hacer. **Las dos rutas** (pasiva en `policy.evaluate` y `identify_client` en el tool loop) producen el **mismo estado final**: sin promoción, sin factor en `flow`, sin slot satisfecho, `HumanHandoff(reason_code='identity')`, agente silenciado y ejecución detenida. El texto al cliente es **genérico y no confirma el nombre**, y vive en `tier0` (fuente única de plantillas), nunca inline. **Garantía en runtime, no solo de tipos**: `EchoRejected` no expone `.sealed`, y `verify_pet_evidence` rechaza cualquier objeto que no sea `SealedPetEvidence` aunque los chequeos estáticos no corran | Un falso rechazo **no cuesta «un turno»**: el cliente no verifica, el modelo pregunta, el cliente repite el mismo nombre — que sigue siendo eco dentro del TTL. Es un bucle hasta que la revelación caduque. Y el contexto ayuda: si el nombre lo dijo staff, ya hay una persona en la conversación a la que devolver el caso |
| D7 | **Grounding reciente**, validado **al capturar**: el factor solo cuenta si el cliente lo escribió en el burst actual o en entrantes posteriores a la última respuesta del agente. Una vez sellado, vale hasta el menor entre **cierre de sesión** y **`IDENTITY_EVIDENCE_TTL`** | Revalidar en cada reunión del reto rompería el caso multi-turno (nombre → mascota → dígitos): los factores previos dejarían de ser «recientes» |
| D7b | **`IDENTITY_EVIDENCE_TTL`** sobre `from_message.created_at` (propuesta: 60 min) | La sesión **no** muere a las 24 h — `close_inactive_conversations` mide **inactividad** (`policy.py:441`), y en prod hay sesiones de 29 h y 47 h. Sin TTL no existe ninguna ventana, ni con el store ni sin él |
| D7c | **Anti-eco por primera mención**, dentro de la ventana `IDENTITY_EVIDENCE_TTL`: se busca el valor en **todos** los salientes de ese periodo; si el sistema o el staff lo emitió **antes** de que el cliente lo aportara, es eco → inválido | El grounding prueba **autoría**, no **independencia**: staff escribe el nombre (la bandeja se lo muestra, `serializers.py:113`) y el cliente lo repite. «Saliente inmediatamente anterior» era demasiado estrecho: `staff: ¿cómo está Luna?` → `cliente: ¿por qué?` → `agente: solo confirmo datos` → `cliente: Luna` lo evadía |
| D17 | **Un único servicio de evidencia de mascota.** `policy` deja de llamar a `identity.try_verify_by_pet_name`; ambas vías (pasiva y `identify_client`) pasan por `resolve_pet_evidence` / `verify_pet_evidence` | Con `pet_name` como único factor de autoservicio, dos caminos hacia `_promote` es insostenible. La ruta pasiva **sí** tenía grounding (recibe el burst del cliente, lo más fresco que hay) pero **no** anti-eco y **no** satisfacía el slot — ver §2.3 |
| D18 | **Un reducer único**, `valid_identity_facts(conversation, now)`, consumido por `identify_client`, la vía pasiva, `goals.satisfy`/`missing_slots`, `anchored_identity_facts` y `context_block`. Al topar con evidencia vencida: ignorar, limpiar el slot y **recalcular `me_falta`** | El TTL no es una comparación, es un estado derivado. Hay **dos** copias persistidas (`flow['aportado']` y `ConversationGoal.slots`) y `missing_slots` sale de `spec.required_slots` + valor del slot (`goals.py:789`): si solo `identify_client` mira la fecha, el modelo sigue viendo el factor satisfecho con evidencia caduca |
| D19 | **El historial cruzado de sesiones exige verificación vigente.** Sin ella, el contexto se limita a la conversación actual; los hechos de F3 (`ya_hablamos_antes`, `ultima_vez`) sí viajan porque no son PII | El transcript viejo puede contener el nombre de la mascota, que ahora es **la respuesta del reto**. Reduce la superficie, no la elimina (la sesión actual ya puede contenerlo hoy): el bypass lo cierra D7c, esto cierra la **fuga**. El `else` conserva el comportamiento actual → sin regresión. La bandeja humana mantiene acceso completo por permisos de staff |
| D20 | `TITULAR_CHALLENGE` pasa a exigir **solo `pet`**; se actualizan `return_to`, textos `why` y tests. Y **no se crea el compromiso** si el `Owner` no tiene mascotas: se escala antes | Verificado en `goals.py:363-371`: hoy exige `(pet, owner)`. Cambiar solo `identify_client.falta` no sirve — `context_block` seguiría publicando «falta el nombre del titular» y el modelo lo pediría |
| D21 | **`try_verify_by_owner_name` se elimina** | Corrección de la rev. 5, que decía que seguía sirviendo al reto familiar: **falso**, esa vía usa `find_link_candidates`/`owner_has_pet`/`owner_digits_match` y nunca la llama. Sin la rama de `identify_client` queda sin consumidores; dejarla viva es una invitación a reabrir el factor. Consumidores a migrar (lista completa): `test_identity.py:36,47,54,60,70,77,122`, `test_w1_experience.py:389`, `test_stale_phone_identity.py:234,242` |
| D24 | El worker pasa **`burst_messages=pending`** (objetos `Message`) hasta el servicio; cuerpos y `payload_types` se derivan **dentro** | Sin PKs no hay `from_message` que sellar. Y hoy ya viajan **dos** listas paralelas (`burst=[m.body …]`, `payload_types=[m.payload_type …]`, `worker.py:165-171`): añadir una tercera empeora una fragilidad existente en vez de arreglarla |
| D25 | Firma `verify_pet_evidence(conversation, sealed)`. En **una transacción corta**: `_promote` + `flow` + slot + **cierre del reto y reanudación de la tarea suspendida** (D32), con **todos** los goals afectados bloqueados y orden de locks **`ContactIdentity` → `Conversation` → `ConversationGoal` (por id)** | El servicio escribe `flow`, localiza el compromiso y satisface su slot: con solo `contact` no puede. Y el turno corre **fuera** de transacción (diseño del lease), así que sin ella cabe «contacto promovido + `flow` sin guardar + slot sin satisfacer». El orden no intersecta el global de dominio: ninguna es fila de dominio y el servicio no llama a ninguna API |
| D26 | **Reducer puro** `reduce_identity_facts(conversation, now) → (valid, expired)` + **reconciliador con efectos** `reconcile_identity_facts(...)`, que corre **una vez al inicio del turno**. Después, `missing_slots`, `context_block`, `anchored_identity_facts` y los prompts son **lectores puros** | D18 mezclaba lectura y escritura: `missing_slots` podría escribir en DB y el ensamblado de un prompt mutar estado. Y hay recursión real — `goals.satisfy` llama a `missing_slots`; si éste invocara un reducer que recalcula `missing`, se muerde la cola. Precedente del propio proyecto: `situation.read` es pura *«para que el gate estático de pureza sea trivial de sostener»* (`situation.py:76`) |
| D27 | El selector de **mensajes realmente emitidos** se adelanta de F2 a **F0**: salientes `sent`/`delivered`/`read`, entrantes `pending`/`processed`; fuera `failed`, `discarded` y salientes `pending`. Orden `created_at, id` | El anti-eco lo necesita en F0, y escribir uno mínimo ahí obligaría a unificar dos selectores después. `failed` = ventana de 24 h cerrada, `discarded` = el cliente siguió escribiendo, `pending` = sin enviar: **el cliente no los vio**, y contarlos rechazaría factores legítimos |
| D28 | `try_verify_by_pet_name` y `try_verify_by_pet_answer` pasan a ser **matchers puros** (booleano, sin estado). Invariante gate-able: **`identity._promote` tiene exactamente un llamador**, el servicio | D17 decía «el servicio es el único que promueve», pero **ambas** funciones llaman a `_promote` hoy: cerrar solo la del router deja la puerta de al lado abierta. Con D21 eliminando la tercera, `_promote` queda con un caller y el gate es una comprobación estática trivial |
| D30 | La ruta `passive_free_text` exige **gramática cerrada de marco fuerte** (§2.3.1), **match del modo pasivo** (D6) y **candidato único por nombre normalizado distinto**, con **longest-match** en nombres compuestos. Lo que la gramática no reconoce **no promueve** | Hoy `try_verify_by_pet_name` parte el texto en tokens y promueve si cualquiera matchea (`identity.py:124`): «Sol» promueve con *«¿va a haber sol mañana?»*. Y un marco laxo no arregla el significado: *«¿venden lentes para sol?»* encaja con `para <mascota>` y *«No es Luna»* con `es <mascota>`. «Candidato único» se define por **nombre distinto**, no por fila `Pet`: dos mascotas del mismo dueño llamadas «Luna» no deben invalidar la identidad |
| D31 | **Ambas fronteras con efectos** devuelven el estado que mutaron y el caller lo reasigna: `reconcile_identity_facts` → `conversation.flow` + invalidar el estado de goals; `verify_pet_evidence` → `verified`, `contact_identity` fresca, `conversation_flow`, `goal_satisfied`, `resumed_goal`, `source_message_id`, `match_mode`, reasignando también **cualquier variable local** que ya tuviera el contacto | Hoy funciona por **coincidencia**: `policy.evaluate` toma `contact = conversation.contact` y `try_verify_*` guarda sobre esa misma instancia; el `select_for_update` la rompe. Reasignar solo `contact` no basta —la transacción muta `flow` y los goals, y `anchored_identity_facts` lee `conversation.flow` de la instancia recibida— y reasignar `conversation.contact` tampoco actualiza un `contact = …` local anterior. El reconciliador es el caso más traicionero: si el turno **no** trae mascota, `verify_pet_evidence` no corre, el `flow` viejo sobrevive y se **republica la evidencia que se acaba de borrar**. Prueba dedicada: turno **sin** evidencia nueva tras reconciliar |
| D32 | El compromiso es **opcional**, y cerrar el reto es parte del **contrato atómico**: con reto activo → bloquear, satisfacer `pet`, **`finish_identity`**; sin reto → promover y sellar `flow` sin crear un goal artificial. **Semántica única para el estado inconsistente**: la **DB es la defensa** (un segundo foreground es `IntegrityError`), el servicio **comprueba el invariante y loguea la anomalía**, y **no se usa `assert` de Python como control productivo**. La defensa runtime que sí hace falta es **semántica**: si el suspendido que se iba a reanudar es otro `IDENTITY_GOAL`, se cierra (`abandoned`, `duplicate_identity_goal`) y **no se reanuda**. Los goals afectados se bloquean en orden de **id**, tras `ContactIdentity` → `Conversation` |
| D34 | **Los constraints resuelven cardinalidad, no significado**: «un solo suspendido» no garantiza que sea la tarea correcta. El invariante semántico de D32 es **defensa**, y su objetivo real son las **filas legacy resucitadas** (abajo) | **Corrección de la rev. 11**, que afirmaba que el flujo normal producía «identity activo + identity suspendido». **Falso**: `start_identity` (`goals.py:586-612`) cierra el identity vivo **y** el identity suspendido antes de crear el nuevo, y el único caller productivo de `open_goal` es `tools._goal_gate:868` con `goals.TOOL_GOALS` — nunca un nombre de identidad. **Pero el estado sí ocurre por otra vía**: `policy.py:171-174` **resucita** un suspendido de identidad al frente, y producción tiene una fila `identity_triage` suspendida (maquinaria retirada en É-F5 Fase 2). Si `finish_identity` la reanuda, el agente vuelve a pedir identidad justo después de verificar |
| D35 | **`match_mode` lo deriva el SERVIDOR**, nunca el caller. `challenge_response` **solo** si: (1) hay exactamente un identity goal foreground; (2) su slot `pet` estaba pendiente al preguntar; (3) existe `pet_asked_message_id` con **`asked_state='emitted'`**; (4) ese saliente es de **la misma conversación**; (5) su estado es visible (`sent`/`delivered`/`read`); (6) **`pet_asked_at` < `created_at` del entrante**; (7) dentro del TTL; (8) ese saliente llevaba la **cláusula determinista** de D38. Cualquier fallo ⇒ `passive_free_text`. El hecho sellado **registra** el modo derivado; jamás lo recibe | **Corrección de la rev. 13**, que exigía «el último saliente emitido». Ese requisito lo añadí yo, no carga peso (si la pregunta se emitió, es anterior y está en TTL, da igual que saliera otro mensaje en medio) y **no es demostrable**: `Message` no tiene `sent_at` y el sender usa `skip_locked` con réplicas, así que `created_at` no prueba el orden de emisión. Retirado, desaparece la necesidad de migración. La comparación de (6) **no** usa `Message.created_at` (momento de encolado) sino **`pet_asked_at`, estampado en el envío real** — vive en el goal, no en el mensaje |
| D38 | **Cláusula determinista de identidad**: cuando el sistema abre el reto, **él** añade al saliente la pregunta que sostiene la garantía; el modelo redacta el resto. Solo ese saliente combinado se liga al reto. Y la guía de `verification_required` (`planner.py:952`) se **reescribe**: hoy ofrece «su nombre, el de su mascota o los últimos 4 dígitos» | Sin esto el modelo vuelve a la frontera de autorización por la puerta de al lado: pregunta por los dígitos, ese saliente se sella, el cliente responde «Luna» y el régimen tolerante se activa sobre una pregunta que nunca se hizo. Precedente exacto en el propio código: `_privacy_prefix` (`planner.py:453-459`) — *«Lo pone el sistema, no el modelo, y a propósito: es un literal legal»*, idempotente por contacto. La reescritura de la guía es obligatoria además porque **contradice D4b**: `owner_name` ya no verifica y los 4 dígitos no prueban nada para quien escribe desde su propio número | Si el modo se dedujera del call site, el modelo saltaría toda la gramática pasiva llamando a `identify_client`: «¿es luna llena?» → `identify_client(pet_name="Luna")` → régimen tolerante → promoción indebida. Sería el mismo bypass con otro nombre: el modelo no elegiría `from_message`, pero sí **el régimen probatorio** |
| D36 | **Dos escritores, uno cada cosa.** `start_identity` es el **único creador** del compromiso, y su **único caller productivo autorizado** es la rama `verification_required` de `planner.py:558`. `bind_identity_question_enqueued(goal, message)` hace `none → enqueued` y lo llama **solo** el planner, sobre su **respuesta final normal** (nunca `guard_blocked`, fallbacks ni errores técnicos); `enqueue_outbound` ya devuelve el `Message` (`outbound.py:17`). `mark_identity_question_emitted(goal, message)` hace `enqueued → emitted` y lo llama el **sender** (`worker.py:392`), **sobre el goal ligado por PK** — nunca «el goal actual»; si fue cerrado o reemplazado, **no sella**. `open_goal` **rechaza** nombres de identidad, con gate estático | Los tres escritores son distintos y ninguno puede hacer el trabajo del otro. **Fallo del sellado con el mensaje ya aceptado por WhatsApp**: se registra la anomalía y se cae a **modo pasivo**; **jamás** se revierte `STATUS_SENT` ni se reenvía. `_send_one` guarda el estado dentro de la transacción del batch (`worker.py:392-394`), así que un write añadido después podría hacer rollback de un mensaje ya entregado y **duplicarlo** | Hoy `start_identity` **no tiene callers productivos** (solo un comentario en `tools.py:60` y la lista de código retirado en `policy.py:304`), así que `challenge_response` es **inalcanzable salvo por resurrección**. O F0 declara el escritor, o el matcher tolerante es código muerto: no puede quedar ambiguo, porque es la diferencia entre un régimen probatorio y un adorno. Y el gate impide que un refactor futuro produzca de verdad el estado que D34 repara |
| D37 | **Tres conjuntos, no uno.** `HISTORICAL_IDENTITY_GOALS` = {`identity_triage`, `family_challenge`, `identity_challenge`} · `STARTABLE` = {`family_challenge`, `identity_challenge`} · `RESUMABLE` = solo compromisos vigentes con procedencia válida. **Conjunto de nombres y predicado sobre la fila son cosas distintas**: `RESUMABLE_IDENTITY_GOAL_NAMES` (nombres) e `is_resumable_identity_goal(goal, now)` (nombre ∈ conjunto **y** versión vigente **y** procedencia válida **y** no vencido). **`policy.py:171-174` deja de reanudar por pertenecer a `IDENTITY_GOALS`** y pasa a llamar al **predicado**, no a comprobar pertenencia. `identity_triage` queda **histórico**: nunca iniciable, nunca reanudable, y **nunca tratado como tarea normal**. **Huérfano** = predicado formal: reto de identidad **no `RESUMABLE`**, o `RESUMABLE` sin compromiso vigente ni procedencia válida | «Huérfano» sin definir hacía la remediación ambigua en los dos sentidos: cerrar de más destruye un reto válido; cerrar solo la fila observada deja viva la vía que resucitaría otra. Producción tiene **1** `identity_triage` suspendida, de la FSM retirada en É-F5 Fase 2 |
| D29 | **Orden obligatorio dentro del turno**, en esta secuencia exacta: **reconciliar vencidos → resolver y sellar la evidencia del burst → resto de `policy.evaluate` → ensamblar prompt** | Reconciliar **después** de capturar limpiaría o recalcularía el estado recién actualizado. Y verificar antes del ensamblado es lo que permite que quien escribe «cita para Luna» verifique **y** reciba su historial en el **mismo** turno con el gate de D19 activo. Deja de ser un detalle de implementación |
| D22 | La proyección de productos se registra con `tool_name='product_query_resolved'`, no reusando `check_product_availability` | Dos filas con el mismo nombre contarían **dos ejecuciones por una búsqueda** y falsearían las métricas. Y el producto consultado puede revelar información sanitaria indirecta → mismo alcance y retención que el resto del dato ligado al contacto |
| D23 | **Aceptación explícita de riesgo**: `pet_name` es un factor de **conocimiento de baja entropía**, no un secreto fuerte. No se describe como autenticación fuerte y no habilita más que lo que ya habilitaba | Puede aparecer en redes sociales o conocerlo un familiar. Ver §2.3 para qué habilita y qué no |
| D8 | **No hay marca de «factor quemado»** — la resuelve D4b retirando el factor para todos | `ContactIdentity` no tiene dónde persistirla, `auto_rematch_blocked` tiene otra semántica y `_promote` lo limpia (`identity.py:165`), y hardcodear IDs no es una solución |
| D9 | Las visitas pasadas salen de `Appointment`, nunca de `MedicalRecord` | El rol `AGENT` no tiene `medicalrecord.*` (`permissions_codes.py:227`). La cita da el *motivo*; el diagnóstico no sale por WhatsApp |
| D10 | Memoria larga = datos estructurados, **solo ejecuciones exitosas** (predicado explícito por tool), y para agenda **manda el estado del dominio**. **No se lee `args_redacted`**: se registra una proyección propia con el objeto resuelto | Una llamada fallida o revertida no es un hecho. Y `args_redacted` está documentado como libre de PII (R15) pero guarda la consulta literal del cliente: construir memoria permanente encima cementaría la violación |
| D15 | Ningún hecho **sin procedencia** viaja al modelo, legacy o no. **El punto de control es `goals.satisfy`**: rechaza guardar un valor sin procedencia válida | Sin esto, retirar el nombre de `context['cliente']` no sirve. Y filtrar solo `flow['aportado']` tampoco: `anchored_identity_facts` publica `titular_declarado` desde `ConversationGoal.slots`, que escribe `goals.satisfy`. Bloquear en el escritor cubre cualquier vía futura de publicación; filtrar al publicar, solo las conocidas |
| D16 | La remediación del contacto comprometido es **precondición de F1a**, no auditoría posterior | F1a instruye al modelo a confiar en `verificado: true`; desplegarla antes consolidaría un estado obtenido por el bypass |
| D11 | **Selector único de mensajes visibles**, compartido por prompt y bandeja | Hoy el prompt excluye `discarded` pero incluye `failed` — mensajes que el cliente nunca recibió. Al unir sesiones el error gana impacto |
| D12 | `ContactIdentity` gana `PublicIdMixin` | La bandeja pasa a navegar por contacto; sin `public_id` no es direccionable, y exponer PKs contradice ADR p18 |
| D13 | Un guard HARD nuevo (fuga de nombre), con límites de palabra **y** excepción solo si el nombre está **fundamentado recientemente** | Comparar `_norm(owner.name)` contra todo el texto daría falsos positivos con «Sol», «Leo», «Luz»; y `has_hard` **descarta la respuesta al cliente**. «Fundamentado recientemente» y no «el cliente lo escribió alguna vez»: eso último convertía la repetición de una fuga vieja en autorización permanente |
| D14 | `Conversation.summary` se borra **en una fase contract propia** (F5) | Borrar un campo no es aditivo: exige que ningún lector desplegado lo toque |

### 2.1 · Por qué se retira el store de evidencia por contacto (rev. 4)

La rev. 3 proponía sacar la evidencia de identidad de `Conversation.flow` a un
`ContactIdentityFact` por `(contact, channel_account)`. La tercera revisión mostró
que abría tres agujeros, y al mirarlos juntos se ve que ninguno era necesario:

1. **Acumulación sin ventana.** El store la habría hecho ilimitada: un atacante
   aportando un factor por sesión, durante meses.
   ⚠️ **Premisa refutada** (rev. 5): la rev. 4 justificó esto diciendo que «la
   sesión muere a las 24 h», y por tanto que la sesión ya era una ventana. **Es
   falso** — se conserva aquí porque explica por qué la rev. 4 creyó que no hacía
   falta un TTL, no como razonamiento vigente.
   `close_inactive_conversations` mide **inactividad**, no vida
   (`policy.py:441`), y en producción hay sesiones de 29 h (conv 1) y 47 h
   (conv 16). Un cliente con actividad diaria mantiene una sesión abierta
   semanas. Retirar el store reduce el riesgo pero **no establece ninguna
   ventana** — la establece `IDENTITY_EVIDENCE_TTL` (D7b), que hoy no existe ni
   con store ni sin él.
2. **Dígitos sin candidato.** «Persistir satisfacción, no el secreto» solo
   funciona cuando ya hay un `Owner` contra el que comprobar. En el reto familiar
   los dígitos pueden llegar primero, así que no hay nada que satisfacer — y
   guardarlos a nivel contacto exige HMAC con clave de servidor, porque 10 000
   combinaciones hacen inútil un hash simple.
3. **Anti-eco sin historia.** Acotarlo a «salientes emitidos mientras el contacto
   no estaba verificado» exige un snapshot de verificación por mensaje que no
   existe: `Message` no lo guarda y `ContactIdentity` solo conserva el último
   `verified_at`.

**El dato decisivo**: nada del bypass requiere que la evidencia sobreviva al
episodio. La verificación ya persiste en `ContactIdentity.verification_level`, que
es por contacto. Subir la evidencia era **continuidad**, no seguridad — y la
continuidad la resuelven F2/F3/F4.

Retirado el store: (1) la ventana la fija **`IDENTITY_EVIDENCE_TTL`** (D7b) — no
la sesión, que puede durar semanas; (2) los dígitos se quedan donde ya están;
(3) el anti-eco general se sustituye por grounding reciente + primera-mención
dentro del TTL (D7c) + el guard.

**Precondiciones si algún día se construye** (no opcionales): `attempt_id` +
`expires_at` con reducer que solo consume el intento vigente, y HMAC con clave de
servidor para `phone_digits`, con el `attempt_id` en la entrada.

### 2.2 · Por qué se retira `owner_name` como factor de verificación (D4b)

La rev. 4 pretendía «quemar» el factor en los contactos cuyo nombre ya se filtró.
No hay dónde persistir esa marca: `ContactIdentity` no tiene el campo,
`auto_rematch_blocked` tiene otra semántica y `_promote` lo limpia
(`identity.py:165`), y hardcodear IDs no es una solución.

Y hay un problema que ninguna marca por contacto resuelve: **el grounding prueba
autoría, no independencia**. La bandeja le muestra el nombre del titular al staff
(`serializers.py:113`); si una persona escribe «Hola Andrés» y el cliente
responde «sí, Andrés», el segundo mensaje está recientemente fundamentado y sigue
siendo un eco de algo que suministró el sistema. Un guard de salida no puede
vigilar lo que escribe un humano.

Retirar el factor cierra las dos cosas a la vez:

- No hace falta marca, ni campo, ni migración, ni caso especial por contacto.
- Da igual quién filtre el nombre —modelo, staff, o la propia bandeja— porque
  deja de abrir nada.

**Está contenido**: `try_verify_by_owner_name` solo se invoca desde
`identify_client`, en la rama `contact.owner_id is not None`. El reto familiar usa
el nombre en `find_link_candidates` como **clave de búsqueda**, y ahí el sistema
no conoce todavía al `Owner` — no puede filtrarlo. Esa vía no cambia.

Efecto en `identify_client`: para `owner_id is not None`, `falta` deja de listar
`owner_name`. El prompt no necesita cambio — ya obliga a pedir exactamente lo que
la herramienta liste en `falta`. Un nombre que el cliente aporte igual se guarda
(con procedencia) y puede viajar como `dijo_llamarse`: lo que pierde es el poder
de verificar.

#### 2.2.1 · Por qué no hay factor de reemplazo

Con `phone_match`, los tres candidatos posibles y qué prueba cada uno:

| Factor | ¿Prueba identidad de quien escribe? |
|---|---|
| `owner_name` | **No.** El sistema lo conoce y lo enseña: al modelo (bug §0.2) y a staff en la bandeja (`serializers.py:113`). Además es lo menos secreto de una persona: está en su perfil de WhatsApp y en los contactos de cualquiera |
| `phone_digits` | **No, y es circular.** El contacto llegó *por ese número*: pedirle los últimos 4 dígitos de su propio teléfono es pedirle que repita el dato que ya usamos para encontrarlo. El prompt ya lo dice, y `identify_client` a propósito no los lista en `falta` para estos contactos |
| `pet_name` | **Sí.** Es lo único que exige conocer el expediente y no se puede deducir del canal |

**Esto no es un criterio nuevo.** `ContactIdentityVerification.EVIDENCE_CHOICES`
(ADR p57 §5.5.3) ya excluye deliberadamente toda evidencia basada en el teléfono,
con este razonamiento textual: *«el número ya se sabe que coincide —es lo que creó
el caso—, así que usarlo como prueba sería circular. Por eso ninguna opción del
enum se basa en él.»* D4b aplica esa misma regla al reto conversacional, donde
hasta ahora no se aplicaba.

De ahí se sigue la consecuencia, que es **decisión de producto aceptada por el
PO** (2026-08-15): un contacto `phone_match` cuyo `Owner` **no tenga mascotas
registradas** no tiene ningún factor de autoservicio y **debe** ir a verificación
humana. Es un caso real: un `Owner` puede existir sin `Pet` (creado desde el POS
en una venta de mostrador con cliente real).

#### 2.2.2 · Cómo se ve el escalado (y por qué queda claro para el equipo)


Sin esto, `identify_client` devolvería `verificado: false` con `falta` **vacío** y
el modelo se quedaría dando vueltas: pidiendo nada, o inventándose qué pedir. Así
que la ausencia de factor **no es un estado de espera, es un escalado**.

Cuando el contacto tiene `owner` y el `Owner` no tiene mascotas no genéricas:

```
policy.escalate_to_human(
    conversation,
    reason_code = HumanHandoff.REASON_IDENTITY,
    detail      = "Este número corresponde a un cliente sin mascotas "
                  "registradas, así que no hay dato del expediente que él "
                  "pueda darnos para confirmar que es él. Verifícalo tú y "
                  "registra la verificación.",
)
```

- **`reason_code = REASON_IDENTITY`** — el valor correcto para escalados nuevos.
  **No** `identity_ambiguous`, que está deprecado y además *mintió en producción*
  (conv 13): aquí nada es ambiguo, simplemente no hay factor disponible.
- **`reason_detail` es lo que lee una persona.** La bandeja lo publica
  (`get_handoff_reason_detail`, cuyo propio docstring dice que `reason_code`
  clasifica para la máquina y `reason_detail` es *«el que le dice algo a una
  persona»*). El texto tiene que decir **qué pasa, por qué, y qué hacer** — nunca
  «verificación fallida», que haría pensar que el cliente contestó mal.
- **Qué hace staff**: la vía existente de FLUJO-C — registrar un
  `ContactIdentityVerification` con `evidence_kind` ∈ `in_person_id` ·
  `known_record` · `callback`, y luego «Autorizar vínculo». El botón sale
  deshabilitado hasta que exista la verificación aprobada **de ese mismo caso**:
  no es un fallo, es el contrato (ADR p57 §5.5).
- **Al cliente** no se le dice que algo falló: la plantilla de identidad de
  `tier0` ya habla en voz de negocio («déjame confirmarlo con el equipo»).
- **Métrica de vigilancia** (§9): número de escalados con este `reason_detail`. Si
  resulta frecuente, la conversación a tener **no** es reponer `owner_name` como
  factor — es que esos `Owner` sin mascotas existan, o darle a staff una vía más
  rápida. El factor no vuelve por volumen.

### 2.3 · Contrato del factor único (`pet_name`)

Al quedar como el único factor de autoservicio, `pet_name` pasa de ser una
comodidad a ser **la barrera**. Todo lo que sigue existe por eso.

#### Dos rutas hacia `_promote`, y una sola debe quedar

Hoy hay dos caminos que promueven a `confirmed_in_chat` por nombre de mascota:

| Ruta | Llama a `_promote` | Grounding | Anti-eco | Satisface el slot |
|---|---|---|---|---|
| `identify_client` → `try_verify_by_pet_answer` | **sí** | sí (F0) | sí (F0) | sí |
| **`policy.py:224` → `try_verify_by_pet_name(contact, burst_text)`** | **sí** | **sí, implícito** | **NO** | **NO** |

Las **dos** promueven. Cerrar solo la del router habría dejado la otra abierta.

Matiz importante, porque cambia el tamaño del arreglo: la ruta pasiva **no
carece de procedencia**. Recibe `burst_text`, que es lo que el cliente acaba de
escribir en este turno — la evidencia más fresca y mejor fundamentada del
sistema; un TTL ahí se satisface trivialmente. Lo que le falta es:

1. **Anti-eco**: promueve aunque el nombre lo haya dicho el staff dos mensajes
   antes. Es el escenario de D7c, y por esta vía entra sin filtro.
2. **Actualizar el compromiso**: no pasa por `goals.satisfy`, así que el slot
   `pet` queda sin satisfacer y `me_falta` **sigue pidiendo la mascota después de
   haber verificado con ella**. Eso ya es un bug hoy, no una consecuencia de este
   plan.

De ahí D17: **un servicio único** que ambas vías llaman.

```python
reconciled = reconcile_identity_facts(conversation, now)   # D29 — PRIMERO
conversation.flow = reconciled.conversation_flow           # D31 — también aquí

resolution = resolve_pet_evidence(conversation, burst_messages)
#   → EXTRAE el candidato del burst con la GRAMÁTICA CERRADA de §2.3.1:
#     marco fuerte + matcher de ACEPTACIÓN del modo + candidato único.
#     Un token fuera de marco nunca es evidencia.
#   → deriva el mensaje origen (D24), grounding reciente, TTL, y anti-eco por
#     primera mención con el matcher de REVELACIÓN, que es tolerante (D6/D7c)
#   → devuelve una UNIÓN CERRADA: NO_EVIDENCE | SEALED_EVIDENCE | ECHO_REJECTED

if resolution.kind is ECHO_REJECTED:                  # D33 — igual en las 2 rutas
    return escalate_identity_echo(                    # handoff + silencio + STOP
        conversation,
        source_message_id=resolution.source_message_id,
        disclosure_message_id=resolution.disclosure_message_id,
    )
if resolution.kind is NO_EVIDENCE:
    return                                            # el turno sigue su curso

result = verify_pet_evidence(conversation, resolution.sealed)   # D25
#   → transacción corta: _promote + flow + slot + finish_identity
#     (cierra el reto Y reanuda la tarea suspendida — D32)
#   → locks: ContactIdentity → Conversation → ConversationGoal (por id)
#   → ÚNICO llamador de identity._promote (D28)

# D31 — obligatorio: se reasigna TODO lo que mutó, no solo el contacto
conversation.contact = result.contact_identity
conversation.flow    = result.conversation_flow
contact              = result.contact_identity   # la variable local también
```

`sealed` no recibe un `candidate` de nadie: **extraerlo es parte del servicio**.
Si el candidato viniera de fuera, cada llamador podría derivarlo con su propio
criterio — que es exactamente el estado actual (§2.3.1).

**Los dos matchers no son el mismo** (D6): aceptar usa el estricto del modo,
detectar un eco usa el tolerante. Reusar el estricto para el anti-eco deja pasar
«Lun**n**a» dicho por staff y luego promueve con «Luna».

`policy.py` usa **exactamente** ese servicio. Y no basta con cambiar `policy.py`:
**`try_verify_by_pet_name` y `try_verify_by_pet_answer` llaman las dos a
`_promote`** hoy, así que ambas pasan a matchers puros (D28). El invariante que se
puede verificar estáticamente es *«`_promote` tiene un solo llamador»* — más fuerte
que enumerar funciones prohibidas, que envejece mal.

**El plumbing es parte del contrato** (D24): hoy el worker manda cuerpos, no
mensajes (`worker.py:165`), así que no hay PK que sellar. La cadena pasa a ser
`worker → planner.handle_inbound(burst_messages=…) → policy.evaluate(burst_messages=…)
→ identify_client / ruta pasiva → resolve_pet_evidence`, derivando los textos
dentro. **Sin listas paralelas nuevas** — ya hay dos que pueden desalinearse.

**El orden dentro del turno es requisito, no detalle** (D29): la verificación
pasiva corre en `policy.evaluate` antes de que el planner ensamble el prompt. Por
eso quien escribe «cita para Luna» verifica *y* recibe su historial en el mismo
turno, incluso con el gate de D19.

#### 2.3.1 · Qué cuenta como mención de la mascota (D30)

Hoy no hay extracción de entidad: `try_verify_by_pet_name` normaliza el texto, lo
parte en tokens y promueve si **cualquiera** matchea (`identity.py:124`), con la
tolerancia de `_name_matches` encima (lev≤1 en ≥4 caracteres, subconjunto de
tokens). Consecuencias reales:

| Mascota | Mensaje del cliente | Hoy |
|---|---|---|
| Sol | «¿va a haber sol mañana?» | **promueve** |
| Canela | «¿tienen algo con canela?» | **promueve** |
| Luna | «anoche vi la luna» | **promueve** (`_norm` quita el artículo) |

Con D19 eso ya no solo habilita tools del turno: **abre el historial cruzado**.
D23 no lo cubre — aceptar que el factor es de baja entropía no es aceptar
promociones por lenguaje ordinario.

Y un marco laxo **no arregla el significado** — «match exacto» prueba qué palabra
apareció, no por qué:

| Mascota | Mensaje | Marco laxo |
|---|---|---|
| Sol | «¿venden lentes para sol?» | encaja con `para <mascota>` |
| Luna | «No es Luna» | encaja con `es <mascota>` |
| Luna | «¿es luna llena?» | encaja con `es <mascota>` |

Por eso el contrato es una **gramática cerrada**, no una lista ilustrativa: lo que
no reconoce, no promueve.

**Acepta** — exige sustantivo clínico, relación posesiva o verbo de estado:

```
(cita|consulta|vacuna|revisión|urgencia|baño|cirugía) … (para|de) <mascota>
mi (mascota|perro|perrita|gato|gatita|cachorro) [se llama] <mascota>
<mascota> (necesita|tiene|presenta|está|se puso|le duele|no come|no quiere)
```

**Rechaza**: `para <nombre>` sin sustantivo clínico · `es <nombre>` aislado ·
preguntas metalingüísticas (`¿es…?`, `¿se llama…?`) · **y todo lo demás**.

**La negación se evalúa por función sintáctica, no por presencia de `no`.** Una
regla ciega tiraría *«Luna no come»*, que es de los mensajes clínicos más
importantes que manda un cliente:

| | Ejemplos | Veredicto |
|---|---|---|
| Negación de **identidad** | «no es Luna» · «no se llama Luna» · «ni Luna» · «eso no se llama Luna» | **rechaza** |
| Negación de **estado clínico** | «Luna no come» · «Luna no camina» · «Luna no quiere agua» | **acepta** |

**`se llama <mascota>` exige sujeto posesivo en modo pasivo.** Suelto, admitía «el
producto se llama Luna», «la clínica se llama Luna», «eso se llama Luna». En
`challenge_response` sí basta «se llama Luna» —o «Luna» a secas—, porque el sistema
**acaba de preguntar** por el nombre.

**Match del modo pasivo** (D6): igualdad exacta normalizada contra el nombre
completo **o contra uno de sus tokens completos (≥3 caracteres)**, sin distancia de
edición.

> Corrección de la rev. 8, que pedía «exacto» a secas: eso habría **regresionado**
> el caso compuesto. `identity.py` documenta la vía de subconjunto de tokens porque
> el reto *«rechazaba el nombre de pila del propio cliente — un cliente legítimo
> diciendo la verdad terminaba en handoff»*. Con «Luna Bella» registrada,
> *«cita para Luna»* tiene que funcionar. Lo que se elimina es la **distancia de
> edición**, que es de donde salían los falsos positivos.

**Normalización, declarada** (hoy `_norm` no toca puntuación, `identity.py:29`, así
que «cita para Luna, por favor» dejaría el token `luna,`):

1. Normalización Unicode (NFD) + minúsculas + eliminación de diacríticos.
2. **Puntuación como límite de token**, no como parte de él.
3. **Nunca substring** — solo tokens completos.
4. **Longest-match antes de evaluar unicidad**, no después.

**Candidato único = un solo nombre normalizado distinto**, no una sola fila `Pet`:
dos mascotas del mismo dueño llamadas «Luna» no invalidan la identidad. En nombres
compuestos gana el **longest-match**: si el texto contiene «Luna Bella», ese es el
candidato, no «Luna».

Falla seguro por los dos lados: lo que la gramática no reconoce no promueve y el
modelo pregunta (recuperable, un turno de más), y nunca promueve por una palabra
suelta.

**Sobre las citas de mensajes ajenos**: en WhatsApp Cloud API una respuesta citada
**no trae el texto citado en `body`** (viaja como `context.id` en el payload), así
que el caso real es el cliente escribiendo la cita a mano. La gramática lo cubre
por defecto (`«eso no se llama Luna»` tiene negación); **no hace falta parsear
metadata** para esto.

**Alternativa descartada**: permitir promoción pasiva solo con
`TITULAR_CHALLENGE` activo. Es más segura pero reintroduce la fricción que la
ruta pasiva existe para evitar — «cita para Luna» dejaría de verificar, la tool
rebotaría con `verification_required`, el modelo preguntaría y el cliente
repetiría el nombre **que ya dijo**. Es el bucle que É-F5 se propuso eliminar.

**Endurecimiento opcional, no core**: lista de palabras comunes del español para
nombres de ≤3 caracteres. El marco explícito ya resuelve los casos conocidos; se
añade solo si el piloto muestra falsos positivos que sobrevivan al marco.

#### Riesgo residual, aceptado explícitamente (D23)

`pet_name` es un factor de **conocimiento de baja entropía**: puede estar en las
redes sociales del cliente, en una conversación anterior, o conocerlo cualquier
familiar. **No es un secreto fuerte y no debe describirse como autenticación
fuerte** en ningún documento ni en ninguna UI.

Lo que habilita hoy (sin cambios respecto a antes de este plan):

| Habilita | No habilita |
|---|---|
| Leer sus mascotas, sus citas próximas y el estado de vacunas | Nada de billing, caja ni pagos |
| Crear, confirmar, cancelar y reagendar **sus** citas | Expedientes clínicos, diagnósticos, recetas |
| Alta de otra mascota en su expediente | Datos de otro cliente |
| — | Operar sobre un `Owner` **ajeno**: eso exige el reto triple o verificación humana (FLUJO-C) |

Si el nivel de sensibilidad de lo que el agente pueda hacer sube, este factor
**no** es suficiente y hay que revisarlo. Queda anotado como condición, no como
advertencia genérica.

---

## 3 · Fases

```
F0  identidad (P0, vivo en producción)   ← implementable solo, sin migración
    └─ remediación del contacto comprometido = PRECONDICIÓN de F1a (D16)
F2  contexto por (contact, channel_account) + selector de mensajes visibles
F3  hechos de contacto
F1  conducta del caso verificado         ← DEPENDE de F3 (ver nota)
F4  memoria estructurada
F5  contract: borrar summary, índices concurrentes, paginación por cursor
```

**Nota sobre F1** (defecto de la rev. 2): su orden decía F1 antes de F3, pero el
guard de F1 necesita `ya_hablamos_antes`, que nace en F3. Se **divide** en vez de
reordenar el bloque entero, porque el prompt de F1 es P0 y no debe esperar
detrás de una migración:

- **F1a** (con F0, sin dependencias): prompt v11 — conducta del caso verificado.
- **F1b** (después de F3): alimentar `check_behaviour` con los hechos nuevos.

---

### F0 · Cerrar la fuga y el bypass — P0, sin migración

Ocho cambios y una remediación, **sin migración**: no requiere modelos nuevos, ni
HMAC, ni un intento con caducidad (§2.1), ni marca de factor quemado (§2.2), ni el
contrato del inbox.

1. El nombre de `Owner` no viaja sin verificación vigente.
2. `owner_name` deja de ser factor de verificación (D4b), **con escalado
   explicado** cuando el `Owner` no tiene mascotas (§2.2.2). Se elimina
   `try_verify_by_owner_name` (D21) y `TITULAR_CHALLENGE` pasa a exigir solo
   `pet` (D20).
3. Procedencia sellada, derivada por el servidor (6 reglas, abajo).
4. `IDENTITY_EVIDENCE_TTL` + **reducer puro + reconciliador** (D18/D26) + el
   selector de mensajes emitidos, adelantado de F2 (D27).
5. **Servicio único de evidencia de mascota** con `_promote` de un solo llamador;
   las dos funciones de mascota pasan a matchers puros (D17/D28, §2.3). Incluye la
   **gramática cerrada de extracción** (D30, §2.3.1), el **plumbing del burst**
   (D24), la **reasignación de todo el estado mutado** (D31), el compromiso
   opcional **con cierre y reanudación en el mismo commit** (D32) y la secuencia
   exacta del turno (D29).
6. Ningún hecho sin procedencia viaja al modelo, bloqueado en `goals.satisfy`.
7. Guard HARD de fuga de nombre con excepción por grounding reciente.
8. Remediación de `contact_id=1` — **precondición de F1a**.

**`prompts.py:354`**

```python
# hoy
'cliente': contact.owner.name if contact.owner_id else None,
# propuesta
'cliente': (contact.owner.name
            if contact.owner_id and identity.is_verification_current(contact)
            else None),
```

Con `phone_match` viaja `numero_registrado: true` y nada más.

**Procedencia sellada, dentro de `flow['aportado']`** (D5 rev. 4 — sin store
nuevo). La forma pasa de valor plano a valor con origen:

```python
# hoy      {'owner_name': 'Andrés'}
# rev. 4   {'owner_name': {'value': 'Andrés', 'from_message': 387}}
```

`phone_digits` sigue guardándose **como hoy** (en `flow`, ámbito de sesión). La
rev. 3 decía «solo satisfacción, nunca el secreto»: era incorrecto — en el reto
familiar los dígitos pueden llegar **antes** de que exista candidato contra el
que comprobarlos, así que no hay satisfacción que marcar. Se retira esa regla.

**Reglas de procedencia, las seis obligatorias:**

1. **`from_message` lo deriva el SERVIDOR, nunca el LLM.** El modelo aporta el
   valor; el servidor recibe el conjunto de mensajes del burst, busca cuál lo
   contiene con el matcher de su tipo y guarda ese PK. Si el `from_message`
   viniera en los argumentos de la tool, la procedencia sería teatro: el modelo
   elegiría su propia prueba.
2. Se resuelve contra **todos los mensajes del burst**, no contra
   `triggered_by`: en una ráfaga de 1-4 mensajes, `triggered_by` puede ser solo
   el último.
3. Validación del mensaje origen: `direction='in'`, `author_type='client'` y
   **`conversation_id == conversation.id`**. «Misma organización y misma cuenta»
   **no basta** — podría apuntar al mensaje de otro contacto de la misma clínica.
4. El factor debe coincidir con ese cuerpo con el **matcher de aceptación del
   modo** (D6): `passive_free_text` → exacto normalizado (nombre completo o token
   completo ≥3 chars, sin lev); `challenge_response` → `_name_matches` tolerante;
   `phone_digits` → comparación exacta de dígitos. **Nunca `in`**, y **nunca** el
   matcher de *revelación* (ése es tolerante y solo se usa para el anti-eco).
5. **Grounding reciente + sellado** (D7): el mensaje origen debe pertenecer al
   burst actual o a entrantes posteriores a la última respuesta del agente. Se
   valida **al capturar**; después el factor vale hasta el menor entre cierre de
   sesión y `IDENTITY_EVIDENCE_TTL` (D7b). Así la acumulación multi-turno
   (nombre → mascota → dígitos en tres turnos, documentada en `tools.py` como un
   fix previo) sigue funcionando y a la vez tiene caducidad real.
6. **Anti-eco por primera mención** (D7c): se busca el valor en **todos los
   mensajes realmente emitidos** dentro de `IDENTITY_EVIDENCE_TTL`; si el sistema
   o el staff lo dijo **antes** de que el cliente lo aportara, es eco → inválido.
   «Realmente emitidos» = el selector de D27: salientes `sent`/`delivered`/`read`
   y entrantes `pending`/`processed`; **fuera** `failed`, `discarded` y salientes
   `pending`, que son mensajes que el cliente nunca vio y producirían rechazos
   falsos.

**`owner_name` deja de verificar** (D4b, §2.2). Se retira la rama
`try_verify_by_owner_name` de `identify_client`, `falta` deja de listarlo y **la
función se elimina** (D21): no tiene otro consumidor — el reto familiar usa
`find_link_candidates`/`owner_has_pet`/`owner_digits_match` y nunca la llama.

**Ningún hecho sin procedencia viaja al modelo** (D15), con el punto de control en
**`goals.satisfy`**: rechaza guardar un valor sin procedencia válida. Filtrar solo
`flow['aportado']` no bastaría — `anchored_identity_facts` publica
`titular_declarado` desde `ConversationGoal.slots`, y quien lo escribe es
`goals.satisfy`. Bloquear en el escritor cubre cualquier vía futura de
publicación. La forma vieja (string plano) se tolera para auditoría, no verifica,
no se publica, y registra `AGENT_IDENTITY_FACT_UNSOURCED`.

**Remediación previa, no posterior** (D16) — **precondición de F1a**:

- `contact_id=1` está `confirmed_in_chat` por el bypass → se degrada a
  `phone_match` (conserva `owner`, se limpia `verified_at`). **No hace falta marcar
  ningún factor como quemado**: con D4b `owner_name` ya no verifica para nadie.
- **Filas legacy de identidad** (D37), en este **orden de despliegue**, que no es
  intercambiable:
  1. Impedir **en código** la resurrección de retos retirados (`policy.py:171-174`
     pasa a exigir `RESUMABLE`).
  2. Auditar y **clasificar** las filas existentes (conteos por nombre y estado).
  3. Cerrar `identity_triage` **incondicionalmente** (`abandoned`,
     `retired_machinery`).
  4. Cerrar otros retos **solo** bajo el predicado formal de orfandad (D37).
  5. Activar el escritor nuevo (D36) y la reanudación restringida.

  La remediación es **idempotente** y registra **conteos antes/después**: correrla
  dos veces no cambia nada más. Invertir 1 y 3 deja una ventana en la que la fila
  cerrada puede volver por otra vía.

**Guard de salida (HARD)** — encaja en el pipeline existente
(`guards.check_output` → `has_hard` → `correction_message` + reintento,
`planner.py:389-411`):

> Con el contacto **no verificado**, un saliente que contenga el nombre
> registrado del titular es violación HARD, **salvo que esté fundamentado**: que
> el cliente lo haya escrito en el burst actual o en entrantes posteriores a la
> última respuesta del agente. Comparación con **límites de palabra**, tolerante
> a acentos y nombres compuestos (D13).

La excepción por grounding **reciente** —no «alguna vez en el historial»— es lo
que evita dos cosas a la vez: el falso positivo de «hay **sol** hoy» cuando el
titular se llama Sol, y que la repetición de una fuga vieja autorice para
siempre emitir ese nombre.

**Tests**

- Reproducción literal de conv 18 → `verificado: False`, nivel intacto, saliente
  con el nombre bloqueado.
- `owner_name` no verifica a un contacto `phone_match`, aunque coincida (D4b).
- El reto familiar (sin owner) **sigue** encontrando candidatos por nombre.
- `Owner` **sin mascotas** + contacto `phone_match` → `HumanHandoff` con
  `reason_code='identity'` y el `reason_detail` de §2.2.2. **Nunca**
  `verificado: false` con `falta` vacío: eso deja al modelo pidiendo nada.
- `identify_client` no lista `phone_digits` en `falta` para un contacto que ya
  tiene `owner` (sería pedirle su propio número).
- Adversarial de eco humano: staff escribe «Hola Andrés», el cliente responde
  «sí, Andrés» → no verifica nada (D4b lo hace irrelevante; para `pet_name`, D7c).
- `from_message` derivado por el servidor: un argumento de la tool que apunte a
  otro mensaje se ignora; un mensaje de **otro contacto** de la misma clínica se
  rechaza.
- Burst de 4 mensajes con el factor en el **primero** → se resuelve igual (no se
  asume `triggered_by`).
- Factor con `from_message` más viejo que `IDENTITY_EVIDENCE_TTL` → rechazado.
- Legítimo multi-turno: nombre turno 1, mascota turno 3, dígitos turno 5, dentro
  del TTL → vincula (no revalidar grounding en cada reunión).
- Un valor guardado sin procedencia por `goals.satisfy` → rechazado en el
  escritor, no filtrado al publicar.
- Mismo teléfono en dos `ChannelAccount` de la org → la evidencia de una cuenta
  no vale como aporte en la otra.
- Nombres cortos («Sol», «Luz») y compuestos en el guard, con y sin grounding.
- Un hecho legacy sin procedencia **no** aparece en `anchored_identity_facts`.
- **Ruta pasiva**: `policy` no llama a `identity.try_verify_by_pet_name`
  directamente; va por el servicio único, y un eco (staff dijo el nombre primero)
  **no** promueve (D17).
- Verificar por la ruta pasiva **satisface el slot** `pet` del compromiso: nadie
  vuelve a pedir la mascota después de haber verificado con ella.
- Evidencia vencida: el reducer la ignora, limpia el slot y **recalcula
  `me_falta`** — el `context_block` no la publica como satisfecha (D18).
- `TITULAR_CHALLENGE` ya no pide `owner`; `context_block` no menciona el nombre
  del titular.
- `Owner` sin mascotas: **no se crea el compromiso**, se escala (§2.2.2).
- **Gate estático**: `identity._promote` tiene exactamente un llamador (D28). El
  test falla si aparece un segundo.
- Anti-eco: un saliente `failed`/`discarded`/`pending` que contenga el nombre
  **no** invalida el factor (el cliente nunca lo vio) — D27.
- El servicio es transaccional: si falla el guardado del slot, el contacto **no**
  queda promovido (D25).
- `burst_messages` con el factor en el primer mensaje de una ráfaga de 4 → sella
  ese PK, no el de `triggered_by` (D24).
- `missing_slots` y `anchored_identity_facts` **no escriben** en DB (D26); la
  reconciliación ocurre una vez, al inicio del turno.
- Verificación pasiva en el turno T ⇒ el prompt del turno T **ya** trae el
  historial cruzado (D29 + D19), y una tool personal del mismo turno **no**
  rebota (D31 — prueba de integración, no unitaria).
- **Colisión semántica** (D30/§2.3.1), no promueven: «¿habrá sol mañana?» ·
  «anoche vi la luna» · «¿tienen algo con canela?» · **«¿venden lentes para
  sol?»** · **«No es Luna»** · **«¿es luna llena?»** · **«eso no se llama Luna»** ·
  typo dentro de una frase no identitaria · dos nombres distintos candidatos.
- Sí promueven: «cita para Luna, por favor» · «mi perrita se llama Luna Bella» ·
  «Luna necesita revisión».
- **«cita para Luna» con «Luna Bella» registrada → promueve** (token completo; la
  corrección de la rev. 9 al «exacto a secas»).
- **«Luna no come» → promueve**; «no es Luna» y «eso no se llama Luna» → no.
- «el producto se llama Luna» → **no** promueve (falta sujeto posesivo); en
  `challenge_response`, «se llama Luna» y «Luna» sí.
- «cita para Luna, por favor» → promueve (la coma es límite de token).
- **Anti-eco asimétrico**: staff escribe «Lun**n**a», el cliente dice «Luna» → **no**
  promueve, y **escala con motivo** en vez de reintentar (D6/D33).
- Eco emitido por `system` y eco emitido por `human_staff`: mismo resultado.
- Un saliente `failed`/`pending` con el nombre **no** dispara handoff (no fue visto).
- **Las dos rutas paran igual**: la pasiva antes del ensamblado del prompt, la de
  `identify_client` cortando el tool loop.
- El texto al cliente **no contiene el nombre** y sale de `tier0`.
- Ante eco: **cero mutaciones** de identidad, `flow` y slots.
- Registrada «Luna Bella», staff dice «Luna Bella», cliente dice «Luna» → eco
  detectado (matcher de revelación tolerante).
- **Turno sin evidencia nueva tras reconciliar**: la evidencia vencida **no**
  reaparece en el prompt (D31, el caso del reconciliador).
- Dos `Pet` llamados «Luna» del mismo dueño → **promueve** (candidato único por
  nombre distinto, no por fila).
- «Luna» y «Luna Bella» registradas, texto con «Luna Bella» → gana el
  longest-match.
- Sin `TITULAR_CHALLENGE` → promueve y sella `flow`, **sin** crear goal (D32).
- Verificación exitosa con reto activo → **reto cerrado y tarea reanudada** en el
  mismo commit.
- **Segundo foreground** → lo rechaza el **constraint** (`IntegrityError`), no una
  rama de recuperación.
- **Identity activo + identity suspendido** (alcanzable por la **resurrección** de
  `policy.py:171-174` sobre filas legacy, no por el flujo normal) → se repara: el
  suspendido se cierra `abandoned`, **no se reanuda**, log de severidad alta.
- **Identity activo + tarea normal suspendida** → la tarea **sí** se reanuda.
- **`match_mode` derivado por el servidor** (D35), casos obligatorios:
  - `identify_client(pet_name="Luna")` sobre «¿es luna llena?» **sin reto** →
    `passive_free_text` → **no promueve**.
  - `identify_client` sobre «algo con canela» sin reto → `passive` → no promueve.
  - Reto activo pero `pet` **aún no preguntado** → `passive`.
  - Reto creado y pregunta **`pending`, `failed` o `discarded`** → `passive`
    (`asked_state` nunca llegó a `emitted`: el cliente no la vio).
  - Pregunta `sent`, con `pet_asked_at` **anterior** al entrante y con la cláusula
    de D38 → `challenge_response`, tolera typo.
  - Pregunta de **otra conversación** → `passive`.
  - `pet_asked_at` **posterior** al entrante → `passive` (el cliente respondió algo
    que aún no había visto).
  - **Saliente sin la cláusula determinista** —el modelo preguntó por los dígitos
    por su cuenta— → `passive`, aunque exista reto y el mensaje se haya emitido
    (D38).
  - Sellado que falla con el mensaje ya enviado → `passive` + anomalía, y
    `STATUS_SENT` **intacto** (sin reenvío).
  - `bind_identity_question_enqueued` **no** se llama en `guard_blocked`,
    fallbacks ni errores técnicos.
- `identity_triage` suspendido → **nunca** se reanuda (D37).
- Reto vigente con procedencia válida (`RESUMABLE`) → sí se reanuda.
- La remediación corre **dos veces sin cambios adicionales** (idempotente).
- `start_identity` tiene **exactamente un** caller productivo autorizado (D36).
- `open_goal` rechaza **todos** los nombres históricos de identidad.
- `open_goal` con un nombre de `IDENTITY_GOALS` → **rechazado** (D36), con gate
  estático que impide un segundo escritor.
- Fila legacy `identity_triage` suspendida → la remediación la cierra y **no**
  se resucita (D37).
- **Fallo al cerrar el reto ⇒ rollback también de `_promote`** (un solo commit).
- Evidencia vencida reconciliada **no reaparece** en el mismo turno por caché ORM
  (D31).
- Orden del turno: reconciliar **antes** de capturar; una evidencia sellada en
  este turno **no** la limpia el reconciliador (D29).

**Verificación de la remediación**: query de promociones cuyo factor no aparece
en ningún entrante. Se corre **antes** de F1a y su resultado se remedia; no
queda como auditoría abierta.

---

### F1a · Conducta del caso verificado — P0, prompt + eval

Bump `PROMPT_VERSION` → `reception-f5-v11` (identifica la plantilla en cada
`LLMCall`).

- Con `verificado: true` **ya sabes quién es**: úsalo por su nombre, no pidas
  nombre ni mascota, no lo hagas identificarse otra vez.
- Con `numero_registrado: true, verificado: false`: no tienes su nombre → pide
  exactamente lo que diga `falta`.
- Reescribir `«Nunca digas ni des por hecho que alguien quedó verificado»`:
  sigue prohibiendo **afirmar** la verificación, deja de prohibir **usarla**.
- **Verificación expirada**: decir por qué se vuelve a pedir («por seguridad,
  cada tanto confirmo con quién hablo»). Sin esto, un cliente de meses recibe un
  interrogatorio sin explicación.
- Dos ejemplos en `ASÍ SUENAS` — el modelo imita muestras, no adjetivos.

**Eval con el proveedor real.** `test_corpus_conversacional.py` inyecta
`LLMResult` fabricados: prueban el andamiaje, no la obediencia. Se complementa
con regresiones deterministas (los guards, que sí son código).

---

### F2 · Contexto por `(contact, channel_account)` — migración aditiva

**`channels.Message`**

```python
contact = FK('agent.ContactIdentity', on_delete=PROTECT, null=True, blank=True)
# Meta.indexes += Index(fields=['organization', 'contact', 'channel_account', 'created_at'])
```

`null=True` **no es transitorio**: `Message.conversation` ya es nullable para
media huérfana y errores de parseo (`channels/models.py:163`), y esos mensajes no
tienen contacto resoluble. Contrato: `contact` se llena siempre que
`conversation` esté presente; los huérfanos quedan con ambos nulos y **no entran
al contexto ni a la bandeja**.

**Migración**: expand-first y en pasos separados —
`AddField` nullable → índice con `CREATE INDEX CONCURRENTLY` (`atomic = False`)
→ backfill **por lotes** (`contact_id = conversation.contact_id`) → escritores →
lectores. Hacer índice y backfill en una sola migración bloquea la tabla cuando
crezca.

**Inventario de escritores de `Message`** (requisito de mergeo, no opcional):
`services.ingest_inbound_message`, `outbound.enqueue_outbound`, la respuesta
humana de la bandeja (`views.send_message`) y cualquier vía nueva. Cada uno debe
llenar `contact`, o quedar clasificado como huérfano con evidencia.

**Auditoría post-backfill**: comando que detecte inconsistencias entre
`message.contact`, `message.conversation.contact`, `organization` y
`channel_account`. Es la única forma de saber que el backfill quedó bien.

**Selector único de mensajes visibles** (D11) — **su núcleo se implementa en F0**
(D27, lo necesita el anti-eco); aquí se le añaden los consumidores de contexto y
bandeja. No se escriben dos selectores. Hoy no existe y cada consumidor filtra a
mano:

```python
def visible_messages(qs):
    # entrantes: pending (el burst actual) y processed; NUNCA discarded
    # salientes: sent | delivered | read; NUNCA discarded ni failed
```

`failed` es un saliente que el cliente **no recibió** (ventana de 24 h cerrada,
`worker.py:350`). Hoy entra al prompt. Lo usan `prompts.assemble_messages` y
`views.conversation_messages`.

**`prompts.assemble_messages`** — el historial cruzado **exige verificación
vigente** (D19):

```python
if identity.is_verification_current(contact):
    qs = visible_messages(contact=contact, channel_account=account)
else:
    qs = visible_messages(conversation=conversation)   # como hoy: sin regresión
```

La ventana (`HISTORY_TURNS=12`, `HISTORY_MESSAGE_CAP=40`) **no cambia**. Los
hechos de F3 (`ya_hablamos_antes`, `ultima_vez`) viajan en ambos casos: el agente
sabe que es un cliente recurrente sin recibir su transcript.

Motivo: el transcript viejo puede contener el nombre de la mascota, que con D4b es
**la respuesta del reto**. El gate **reduce la superficie, no la elimina** — la
sesión actual ya puede contenerlo hoy. El *bypass* lo cierra el anti-eco (D7c);
esto cierra la *fuga*. La bandeja humana conserva acceso completo por permisos de
staff.

**Creación de sesión — carrera**: hoy `get_or_create_open_conversation` puede
crear dos filas con dos webhooks simultáneos (el `select_for_update` no protege
la *ausencia* de fila). Se toma `select_for_update` sobre la fila de
`ContactIdentity`, que siempre existe. Precedente: `resolve_contact_identity` ya
resuelve su carrera contra el unique.

**Constraint, no solo lock**: unique parcial que garantice **como máximo una
sesión no cerrada por `(contact, channel_account)`**. El lock cierra la carrera
conocida; el constraint protege contra cualquier escritor futuro. Precedente en
el repo: `cashsession_one_open_per_user`.

> Advertencia con precedente propio: un constraint así **falla cerrado** si hay
> duplicados vivos al migrar — la misma trampa que `appointments/0014` (INV-D).
> Hay que auditar y limpiar **antes** de aplicarlo. Prod hoy tiene una sola
> sesión abierta por contacto, así que es seguro, pero el paso no se omite.

**Estado heredado**: si existen dos sesiones abiertas (producto de la carrera),
**no se cierra «la más antigua»** — eso podría cerrar una `human_active` y dejar
viva una `active` más nueva, sacándole la conversación de las manos a quien la
está atendiendo. Precedencia para elegir la que sobrevive:

```
human_active  >  handoff_pending  >  active      (y a igualdad, la más reciente)
```

Si hay **dos** con estado humano o handoff, **se detiene la migración** y se
exige resolución manual: elegir por reloj entre dos personas operando no es una
decisión que deba tomar un script.

**`Conversation.close_reason` no existe hoy** — se añade en esta fase
(`CharField` con choices `idle`/`staff`/`opt_out`/`identity_reset`/
`duplicate_session`/`legacy_unknown`). `legacy_unknown` es el valor de las filas
ya cerradas: no se les inventa una razón. Orden obligatorio:
**añadir campo → auditar duplicados → limpiar → añadir el constraint parcial.**

**Punto abierto declarado**: qué otros keys de `flow` necesitan contraparte por
contacto. `flow['aportado']` se resuelve con D5; el resto (`refs`,
`pending_action`, `suspended`, `deferred_at`) es legítimamente por sesión, pero
hay que **decirlo explícitamente** antes de mergear, no descubrirlo después.

**Lo que NO cambia** (y por eso la fase es acotada): `metrics.py`, presupuesto,
`close_inactive_conversations`, `close_conversation`, `send_message` (sigue
rechazando sesiones cerradas), `release_conversation`, y toda la maquinaria de
`flow`/goals/handoff.

**Tests**: contexto con mensajes de sesiones anteriores del mismo contacto ·
aislamiento entre contactos · **aislamiento entre `channel_account` de la misma
org** · saliente `failed` ausente del contexto · huérfano sin `conversation`
ausente · dos ingests concurrentes → una sesión · dos sesiones abiertas
heredadas → resolución determinista · `compute_business_metrics` idéntico antes
y después · contacto con 5 000 mensajes usa el índice.

---

### F3 · Hechos de contacto en el bloque 1 — sin migración

```python
# hoy
first_contact = not _has_outbound(conversation)      # por conversación
# propuesta
first_contact = not _contact_had_real_interaction(contact, channel_account)
```

`_contact_had_real_interaction` usa `visible_messages` (D11): un saliente
`failed` o `discarded` **no** cuenta como haber hablado con alguien.

```json
{"ya_hablamos_antes": true,
 "ultima_vez": "2026-07-28",
 "ultimo_mensaje_hace": "18 días"}
```

**Se calculan excluyendo el burst en curso.** El entrante ya está persistido
cuando el worker arma el prompt, así que medir «última actividad» sin excluirlo
daría `hace segundos` **siempre** — el campo diría lo contrario de lo que quiere
decir. La referencia es el primer mensaje del burst actual.

`ya_hablamos_antes` alimenta el guard `contradicts_state` en **F1b**.

---

### F4 · Memoria estructurada — sin migración

| Tool | Fuente | Resuelve |
|---|---|---|
| `get_recent_product_queries(limit=3)` | proyección **propia** con el producto **resuelto** (no el texto del cliente) | «el producto que pregunté antes» |
| `get_recent_appointment_actions(limit=3)` | `ToolExecution` de agenda exitosas, **contrastadas contra el estado actual de `Appointment`** | «lo que movimos la vez pasada» |
| visitas pasadas | `GET /api/appointments/?pet=` filtrando `status='done'` y fecha anterior | «¿cuándo vine la última vez?» |

Reglas (D10):

- **Dónde se persiste la proyección** (contrato, no detalle): hoy
  `executor.call` escribe la fila de auditoría **antes** de que
  `check_product_availability` filtre y construya `projection`
  (`tools.py:248` vs `262`), así que el producto resuelto no queda en ninguna
  parte. Se registra con **`executor.record_local`** — el mecanismo append-only
  que ya usa `identify_client` — en una fila propia:

  ```
  tool_name = 'product_query_resolved'        # NO 'check_product_availability'
  result_summary_redacted = {product_public_id, display_name, available}
  triggered_by_message = <el mensaje del cliente>
  ```

  El `tool_name` propio no es cosmético: reusar el nombre existente contaría
  **dos ejecuciones por una sola búsqueda** y falsearía las métricas por tool
  (D22). Y el producto consultado puede revelar información sanitaria indirecta
  → mismo alcance `(contact, channel_account)` y misma retención que el resto del
  dato ligado al contacto.
- **`args_redacted` no se usa como fuente de memoria.** Está documentado como
  «proyecciones SIN PII cruda — los cuerpos viven solo en `Message`, regla R15»
  (`models.py:305`, `executor.py:81`), pero `check_product_availability` guarda
  la **consulta literal** del cliente (`tools.py:251`). Construir memoria
  permanente encima cementaría esa violación. La memoria de productos se registra
  aparte, con el **producto resuelto**; y la violación en sí queda como **bug
  independiente** a corregir (redactar la consulta a conteo/coincidencia).
- **Predicado explícito de «exitosa»** — `ToolExecution` no tiene campo
  `success`. Por familia:
  - HTTP: `200 ≤ http_status < 400` **y** `error_code` vacío.
  - Locales (sin HTTP): contrato por tool, declarado en su spec.
  - Agenda: `policy_decision` permitido **y** el objeto de dominio existe hoy
    (`domain_object_public_id` resoluble y en estado coherente).
- **Para agenda manda el dominio.** El log dice qué se intentó; `Appointment`
  dice qué es verdad. Si difieren, gana el dominio.
- Todas con `min_verification: 'confirmed_in_chat'`, alcance
  `(contact, channel_account)`.

Las visitas pasadas **no requieren permiso ni backend nuevo**:
`list_upcoming_appointments` ya pide todas las citas de la mascota y descarta las
pasadas en Python. Métrica de vigilancia (no revisión manual): filas devueltas
por mascota; si alguna supera ~50, se añaden `status`/`before`/`ordering` al
endpoint.

---

### F5 · Fase contract — después de que F2-F4 estén desplegadas

- Borrar `Conversation.summary` (D14). No es aditivo: exige que ningún lector
  desplegado lo toque.
- Índices restantes con `CONCURRENTLY`.
- Paginación por cursor del transcript en bandeja (`TRANSCRIPT_CAP = 200` hoy
  pasa a ser tamaño de página) + virtualización en frontend.

---

## 4 · Contrato del inbox agrupado (requisito de F2)

Agrupar por contacto **no es gratis**: lo era solo frente a una migración de
`thread_id`. Antes de implementar hay que fijar:

| Pregunta | Decisión propuesta |
|---|---|
| Identificador del thread | **Ruta compuesta** `/inbox/threads/{contact_public_id}/{account_public_id}`. `ContactIdentity.public_id` **solo no basta**: la fila es por par, y dos cuentas del mismo contacto colisionarían en un id. Exige `PublicIdMixin` en `ContactIdentity` (D12) **y** en `ChannelAccount` |
| Migración de los `public_id` | Escalonada, según el precedente `patients/0009`: `AddField` nullable → `RunPython` con un UUID distinto por fila → `AlterField` unique. **Nunca** un campo unique con default en una sola operación |
| Clave de agrupación | `(contact, channel_account)` — una fila por par |
| Sesión vigente | la única no cerrada; si hay varias, la más reciente y las otras se cierran como `duplicate_session` |
| Todas cerradas | la fila se muestra **archivada**, sin acciones de respuesta |
| Claim / handoff / estado en la fila | los de la **sesión vigente**; si está archivada, ninguno |
| Recorrer episodios | endpoint paginado por sesión, orden descendente |
| Qué id usa `send_message` | el de la **sesión**, no el del thread. Escribir sobre una archivada sigue devolviendo 400 con el `public_id` de la vigente si existe |
| N+1 | `select_related`/`prefetch` explícito de sesión vigente y último mensaje; sin conteos por fila sin índice |

---

## 5 · Documentación

- `docs/modules/agent.md:47` — «**CLOSED es terminal** (mensaje posterior = hilo
  nuevo)» **sigue siendo cierto**. Lo que cambia es que el contexto ya no muere
  con el hilo: hay que decirlo, o la línea se lee como que el agente olvida.
- `docs/modules/agent.md:428` — el párrafo de F3 justifica la decisión §9.4
  diciendo que «el `flow` muere con el hilo». Sigue siendo verdad: `flow` es por
  sesión. **No hay que corregirlo.**
- **ADR p58**: el thread pasa a ser la unidad de contexto del agente; la
  identidad gana **procedencia sellada dentro de la sesión** (no un store
  persistido — retirado en rev. 4) y **pierde `owner_name` como factor de
  verificación** (D4b). Toca contrato de seguridad → ADR.
- `docs/modules/agent.md` §identidad: la matriz de factores cambia — con
  `phone_match`, el único factor de autoservicio pasa a ser `pet_name`. Debe
  quedar escrito **por qué** los otros dos no sirven (§2.2.1), o el primer
  ingeniero que vea un cliente atorado repondrá `owner_name` «para
  desatorarlo».
- `docs/modules/agent.md` §hand-off: añadir el caso «cliente sin mascotas
  registradas» a la lista de motivos de `reason_code='identity'`, con el
  `reason_detail` y la acción de staff (§2.2.2). Es lo que va a leer recepción.
- `docs/modules/agent.md` §identidad: dejar escrito que **`_promote` por
  `pet_name` solo se alcanza por el servicio único** y que el router ya no
  verifica por su cuenta (D17). Y el riesgo residual del factor (D23) — si no
  está escrito, alguien lo tratará como autenticación fuerte.

---

## 6 · Qué falta para aprobar cada fase

| Fase | Estado |
|---|---|
| **F0** | **Aprobable, sin migración.** No depende del inbox agrupado ni de F2, ni de un modelo nuevo, HMAC o intento con caducidad. Alcance real tras la rev. 14: servicio único de evidencia con `_promote` de un llamador (D17/D28), **`match_mode` derivado por el servidor** sobre una pregunta **realmente emitida y puesta por el sistema** (D35/D38), **tres escritores distintos** crear/ligar/sellar con caller productivo nombrado y gate (D36), **tres conjuntos + predicado** de goals de identidad y remediación ordenada e idempotente (D37), y la reescritura de la guía de `verification_required`, **gramática cerrada de extracción** con negación por función sintáctica y normalización declarada (D30, §2.3.1), **dos familias de matcher** aceptación/revelación (D6) con escalado en vez de bucle (D33), plumbing del burst (D24), transacción corta que incluye **cierre del reto y reanudación** (D25/D32), refresh explícito de **ambas** fronteras con efectos (D31), reducer puro + reconciliador (D18/D26), selector de mensajes emitidos adelantado (D27), `TITULAR_CHALLENGE` (D20), borrado de `try_verify_by_owner_name` (D21) y la secuencia del turno (D29). **Es notablemente más trabajo que en la rev. 5** — todo del mismo subsistema y sin schema, pero conviene planearlo como tal |
| **F1a** | Aprobable **con la remediación de F0 ya aplicada** (D16). Antes de eso consolidaría el estado obtenido por el bypass |
| **F2** | Requiere: inventario de escritores de `Message`, el selector `visible_messages` (D11) y el contrato del §4 |
| **F3** | Requiere F2 (usa `visible_messages`) |
| **F1b** | Requiere F3 |
| **F4** | Requiere F2 **y** el contrato de almacenamiento de la proyección de productos (`record_local`, §3.F4). Sin él, «memoria del producto resuelto» no tiene dónde vivir |
| **F5** | Requiere F2-F4 desplegadas y estables |

F0 **no se sostiene** esperando el contrato del inbox: corrige un bypass vivo en
producción y no comparte una línea con él.

---

## 7 · Veredictos de las revisiones externas

### 7.1 Primera revisión (13 puntos)

**Aceptados tal cual**: #1 (diagnóstico: `Conversation` era dos conceptos —
verificado en `metrics.py:281`), #4 (los 19 hilos seguirían visibles), #6
(concurrencia por ausencia de fila), #12 (`TRANSCRIPT_CAP = 200`), #13
(mecanismo de guards).

**Disueltos por la rev. 2** (correctos contra la rev. 1): #5 reactivar desde
bandeja · #7 campos no declarados · #8 borrar `suspended` con handoff abierto
(`services._capture_witness:434` lo consume) · #9 ventana no móvil · #10 rollback
de la variable de presupuesto.

**Aceptados con otra solución**:

- **#1 · tabla nueva `ContactThread`** → rechazada: el thread ya es
  `ContactIdentity` y la `InteractionSession` propuesta es la `Conversation`
  actual campo por campo. Aceptado el diagnóstico, no la tabla.
- **#2 · «solo factores del burst actual»** → rechazado ese alcance: regresiona
  un fix documentado en `tools.py` (el familiar legítimo que aporta en tres
  turnos). Adoptado: procedencia sellada en el turno de captura + anti-eco.
- **#3 · memoria diferida** → aceptado adelantarla; su vía (`ToolExecution`) es
  viable, verificado que el término de búsqueda no está redactado.
- **#13 · tres guards** → uno aceptado como HARD; «bloquear respuestas que pidan
  identificación» rechazado como guard (es intención, no hecho, y `has_hard`
  descarta la respuesta al cliente); el tercero ya existía
  (`check_behaviour`/`DENIAL_PATTERNS`).

**Rechazados con datos**: #9b («2–4 llamadas por mensaje» → medido 0.33–1.82,
mediana 1.2; pero la exigencia de calibrar era correcta y corrigió el 40 a
mantener el 100 por sesión) · #11 (endpoint sin filtros: diagnóstico correcto,
dimensionamiento no — son 5-20 filas por mascota; deuda con métrica de
vigilancia) · #12b (retención de mensajes: preexistente, expediente propio; este
plan no la cambia).

### 7.2 Segunda revisión (9 puntos)

**Aceptados tal cual**:

| # | Punto | Verificación |
|---|---|---|
| 1 | Falta alcance por `channel_account` | `ContactIdentity` unique sin `channel_account`; `external_account_id` unique global no impide dos cuentas por org → §1, D2 |
| 2 | La evidencia sigue en `flow` (por sesión) | D5 · store append-only |
| 2b | «El valor debe aparecer en el cuerpo» contradice el matcher lev≤1 | D6 · **el mejor catch de la revisión**: con `in` se rechazaban aportes legítimos |
| 3 | F1 depende de F3 | Corregido dividiendo F1 en F1a/F1b |
| 4 | `ultima_vez` diría «ahora» | Correcto: el entrante ya está persistido cuando se arma el prompt → F3 excluye el burst |
| 5 | `Message.contact` mal especificado | `conversation` es nullable (`channels/models.py:163`); `failed` entra al contexto (`worker.py:350` + `prompts.py:398`) → D11, inventario, auditoría |
| 6 | El inbox agrupado no es «gratis» | `ContactIdentity` no hereda `PublicIdMixin` → D12 + contrato §4 |
| 7 | `ToolExecution` no es memoria confiable | D10 · solo exitosas, y para agenda manda el dominio |
| 8 | El guard necesita comparación precisa | D13 · límites de palabra + «el cliente nunca lo escribió» |
| 9 | D8 (borrar `summary`) sin fase | F5 · fase contract |

**Aceptado con matiz de severidad**

- **Alcance del anti-eco / TTL**: su dilema («solo la sesión» no ve la fuga
  anterior; «todo el historial» bloquea una re-verificación legítima) se resuelve
  con un tercer alcance: **solo salientes emitidos mientras el contacto no
  estaba verificado** (D7). Consecuencia declarada: un factor ya filtrado queda
  quemado (D8) — correcto desde seguridad, y quedan `pet_name` y staff.

**Rechazado**

- **«Eso puede mezclar clínicas» (#1)**: factualmente incorrecto. Una
  `Organization` es una clínica y `ChannelAccount.external_account_id` es unique
  **global** → un número pertenece a exactamente una organización por
  constraint. Dos cuentas de una org son la misma clínica. El riesgo real es
  mezclar **flujos** dentro de una clínica, que es lo que el alcance de §1
  cierra. La distinción cambia el fix: **no** hay que partir la identidad por
  cuenta.
- **«Definir el thread como `(contact, channel_account)`» aplicado a todo**:
  aceptado para contexto/memoria/anti-eco/inbox, **rechazado para la
  identidad**. `verification_level` es un hecho sobre quién es la persona dentro
  de la organización; partirlo obligaría a re-verificarse por escribir al otro
  número de la misma clínica — fricción sin ganancia de seguridad, porque el
  `Owner` es el mismo tenant.
- **«No aprobar el plan»** en bloque: se acepta para F2/F3/F4/F5 (§6), se
  rechaza para **F0 + F1a**. F0 corrige un bypass vivo en producción y no
  comparte una línea con el contrato del inbox; sostenerlo semanas por algo que
  no lo toca aumenta la exposición sin reducir el riesgo.

### 7.3 Tercera revisión (5 P0 + 7 puntos)

**Los cinco P0 son ciertos.** Tres de ellos existían **porque la rev. 3 subía la
evidencia de identidad a nivel contacto**, así que la corrección no fue
especificar mejor ese store: fue **retirarlo** (§2.1 / D5).

| # | Punto | Veredicto |
|---|---|---|
| P0-1 | El anti-eco necesita saber si cada saliente se emitió con el contacto no verificado, y eso no está persistido | **Cierto.** Aceptado el hallazgo, **rechazado `IdentityDisclosure`**: con el guard impidiendo la emisión, el conjunto futuro es vacío por construcción, y el histórico son **2 contactos** → remediación puntual (D8). Un modelo permanente para un conjunto cerrado es infraestructura sin cliente. Sustituido por **grounding reciente** (D7) |
| P0-2 | Los factores no tienen intento ni caducidad → ensamblado del reto triple a lo largo de meses | **Cierto, y era una regresión que introducía yo.** Retirado el store queda acotado a la sesión — que, **corrección de la rev. 5**, puede durar semanas: la ventana real la fija `IDENTITY_EVIDENCE_TTL` (D7b). `attempt_id`/`expires_at` quedan como **precondición obligatoria** si algún día se sube a nivel contacto |
| P0-3 | `phone_digits` no puede ser «solo satisfacción»: en el reto familiar llegan antes de que exista candidato | **Cierto, y mi regla era el error.** Retirada: los dígitos se quedan donde están hoy. HMAC con clave de servidor (no hash simple — 10 000 combinaciones) queda como precondición del mismo escenario futuro |
| P0-4 | La compatibilidad legacy contradice D4: un `owner_name` legacy seguiría llegando por `anchored_identity_facts` | **Cierto.** Aceptado y endurecido: **ningún hecho sin procedencia viaja al modelo** (D15) — más simple y más amplio que condicionarlo a coincidir con el nombre registrado |
| P0-5 | F1a no debe preceder la remediación del contacto comprometido | **Cierto.** Pasa a precondición (D16), no auditoría posterior «caso por caso» |

**Los siete puntos adicionales, aceptados:**

- **Guard con grounding reciente** en vez de «alguna vez en el historial» — cierto
  y mejor que mi regla: una mención antigua se volvía autorización permanente
  (D7/D13). Con su reformulación de la métrica (§9).
- **`source_kind='staff'`** era un estado imposible en mi propio modelo (las
  reglas exigían `direction='in'`/`author_type='client'`). Muere con el store.
- **`_name_matches` no aplica a todos los factores** — cierto; especificado por
  tipo en D6.
- **Identificador del inbox ambiguo** — cierto: la fila es por par y
  `ContactIdentity.public_id` colisionaría entre cuentas. Ruta compuesta + 
  `PublicIdMixin` en ambos modelos + migración escalonada según `patients/0009`.
- **`close_reason` no existe** — cierto, me lo inventé; se añade en F2. Y el
  **unique parcial** es mejor que el lock solo (precedente
  `cashsession_one_open_per_user`), con la advertencia de que **falla cerrado**
  con duplicados vivos, igual que `appointments/0014`.
- **Predicado exacto de «`ToolExecution` exitosa»** — cierto: no hay campo
  `success`. Definido por familia en F4.
- **`args_redacted` viola R15** — cierto y confirmado (`models.py:305` +
  `executor.py:81` dicen «SIN PII cruda»; `tools.py:251` guarda la consulta
  literal). Aceptada su conclusión fuerte: **no se construye memoria encima de
  una violación conocida**. F4 usa una proyección propia con el producto
  resuelto, y la violación queda como bug independiente.

**Sobre el veredicto de aprobación**: se acepta que F1a espere la remediación. No
se acepta que F0 espere al store de evidencia — retirado el store, F0 son cambios
sin migración que cierran un bypass vivo.

### 7.4 Cuarta revisión (4 P0 + 4 puntos)

**Los cuatro P0 son ciertos**, y uno derriba la justificación de la rev. 4.

| # | Punto | Veredicto |
|---|---|---|
| P0-A | No existe dónde persistir el factor «quemado»; `auto_rematch_blocked` tiene otra semántica y `_promote` lo limpia | **Cierto.** Aceptado, y resuelto con una tercera opción que su lista no contemplaba: **retirar `owner_name` como factor de verificación** (D4b, §2.2). Sin campo, sin migración, sin caso especial por contacto — y cierra también P0-D |
| P0-B | La sesión **no** muere a las 24 h: el cierre es por inactividad | **Cierto, y derriba mi premisa de §2.1.** Verificado en prod: sesiones de 29 h (conv 1) y 47 h (conv 16). Aceptado `IDENTITY_EVIDENCE_TTL` sobre `from_message.created_at` (D7b) — la ventana no existía ni con store ni sin él |
| P0-C | `from_message` debe derivarlo el servidor, resolverse contra todo el burst, y exigir `conversation_id` igual | **Cierto, y es el hallazgo más importante de la ronda.** Nunca declaré quién lo elige; si lo elige el LLM la procedencia es teatro. Aceptado entero, incluida la corrección de que «misma org y cuenta» no basta |
| P0-D | El grounding prueba autoría, no independencia: staff escribe el nombre (la bandeja lo muestra, `serializers.py:113`) y el cliente lo repite | **Cierto.** Con D4b deja de importar para `owner_name`. Su **anti-eco local** se acepta y se **retargetea a `pet_name`** (D7c), que pasa a ser el único factor secreto |

**Los cuatro puntos adicionales, aceptados:**

- **D15 debe cubrir `ConversationGoal.slots`** — cierto: `titular_declarado` se
  publica desde el compromiso, no desde `flow`. Aceptado con un punto de control
  **mejor** que filtrar al publicar: bloquear en **`goals.satisfy`**, que es quien
  escribe el valor. Un solo sitio, y ninguna vía futura se lo salta.
- **Semántica del grounding** — su lectura es la correcta y mi redacción era
  ambigua: se valida **al capturar**, y el factor queda sellado hasta el menor
  entre cierre de sesión y TTL (D7).
- **Precedencia al limpiar duplicados** — cierto: «la más antigua» podía cerrar
  una `human_active`. Aceptada la precedencia y el **alto de la migración** si hay
  dos sesiones con estado humano. Y `close_reason` con `legacy_unknown` + orden
  explícito.
- **Almacenamiento de la proyección de productos** — cierto: `executor.call`
  persiste **antes** de construir `projection`. De sus tres opciones se toma la
  primera, con el mecanismo que ya existe (`executor.record_local`). §6 lo declara
  como requisito de F4.

**Nada rechazado en esta ronda.** La única diferencia es que P0-A se resuelve
retirando el factor en vez de marcándolo, lo cual además absorbe P0-D.

### 7.5 Quinta revisión (4 P0 + 4 puntos + limpieza)

| # | Punto | Veredicto |
|---|---|---|
| P0-1 | Segunda ruta que verifica por mascota sin controles (`policy.py:224`) | **Cierto y grave** — con `pet_name` como único factor, esa ruta pasa a ser la barrera. Aceptado el servicio único (D17). **Discrepancia de encuadre**: de los 5 controles que lista le faltan **2**, no 5 — recibe `burst_text`, o sea la evidencia del cliente en el turno actual, que es el grounding más fuerte posible y hace trivial el TTL. Lo que le falta es **anti-eco** y **satisfacer el slot** (esto último ya es bug hoy). Importa porque el cambio en `policy.py` es rutear, no rediseñar |
| P0-2 | El anti-eco «inmediatamente anterior» es demasiado estrecho | **Cierto**, su contraejemplo lo evade. Adoptada la regla de **primera mención dentro del TTL** (D7c) |
| P0-3 | El TTL necesita reducer, no comparación | **Cierto.** Hay dos copias persistidas y `missing_slots` deriva del slot (`goals.py:789`), así que el modelo vería el factor satisfecho con evidencia caduca. Adoptado `valid_identity_facts` como fuente única (D18), con `from_message` en el slot |
| P0-4 | El historial cruzado debe depender de la verificación | **Cierto.** Adoptado su contrato (D19), con la precisión de que **reduce la superficie, no la elimina**: la sesión actual ya puede contener el nombre hoy. El bypass lo cierra D7c; esto cierra la fuga |

**Los cuatro puntos de implementación, aceptados:**

- **`TITULAR_CHALLENGE` sigue exigiendo el titular** — cierto y verificado
  (`goals.py:363-371`). Cambiar `identify_client.falta` no basta: `context_block`
  lo seguiría publicando. Entra en F0 con `return_to`, textos `why`, tests, y el
  escalado **antes** de crear un compromiso imposible (D20).
- **`try_verify_by_owner_name` quedaría muerto** — cierto, **y la rev. 5 decía lo
  contrario**: afirmaba que servía al reto familiar, cuando esa vía usa
  `find_link_candidates`/`owner_has_pet`/`owner_digits_match` y nunca la llama. Se
  elimina (D21), reescribiendo `test_stale_phone_identity.py:234,242`.
- **`goals.satisfy` como choke point con alcance documentado** — aceptado: valida
  procedencia **solo** para factores de identidad; el nombre es genérico y podría
  usarse para otros goals.
- **La proyección de productos necesita identidad propia** — cierto: reusar
  `check_product_availability` contaría dos ejecuciones por búsqueda (D22).

**Riesgo residual** — aceptado y documentado en §2.3/D23: `pet_name` es un factor
de conocimiento de **baja entropía**, no un secreto fuerte; queda por escrito qué
habilita y qué no, y que no se describa como autenticación fuerte.

**Limpieza documental** — las cuatro ciertas y corregidas: «Rev. 4 (esta)», «la
ventana vuelve a ser la sesión» (×2, incluida la del historial de revisiones) y el
test del factor quemado.

### 7.6 Sexta revisión (4 ajustes contractuales + bypass + tests + limpieza)

**Nada rechazado.** Los cuatro ajustes son ciertos y uno destapa que el problema ya
existe en el código.

| # | Punto | Veredicto |
|---|---|---|
| 1 | El burst transporta cuerpos, no `Message`: sin PK no hay `from_message` que sellar | **Cierto** (`worker.py:165`). Y su advertencia sobre listas paralelas está **ya materializada**: hoy viajan **dos** (`burst`, `payload_types`). Adoptado `burst_messages=pending` derivando los textos dentro (D24) — arregla una fragilidad existente en vez de añadir la tercera |
| 2 | El servicio necesita `conversation`, y la escritura debe ser transaccional | **Cierto**, mi pseudocódigo era descuidado. Adoptada la firma y una transacción corta con orden `ContactIdentity → Conversation → ConversationGoal` (D25). El turno corre fuera de transacción por el diseño del lease, así que sin ella cabe «promovido pero sin slot» |
| 3 | Separar reducer puro de reconciliación con efectos | **Cierto**: D18 mezclaba lectura y escritura, con recursión real (`goals.satisfy` → `missing_slots` → reducer → recalcula `missing`). Adoptado el split (D26), con el precedente de pureza + gate estático que ya usa `situation.read` |
| 4 | El anti-eco debe mirar solo salientes realmente emitidos | **Cierto**: `failed`, `discarded` y salientes `pending` son mensajes que el cliente no vio; contarlos rechazaría factores legítimos. Y su nota de secuenciación también: el selector se **adelanta de F2 a F0** (D27) en vez de escribir uno mínimo que habría que unificar |

**Vía de bypass más ancha de lo documentado** — cierto y el hallazgo más útil de la
ronda: **`try_verify_by_pet_answer` también llama a `_promote`**. Cerrar solo la del
router dejaba la puerta de al lado abierta. Ambas pasan a matchers puros, y el gate
se formula como invariante: **`_promote` tiene exactamente un llamador** (D28) —
más robusto que enumerar funciones prohibidas.

**Cobertura de tests** — cierto, mi D21 listaba dos consumidores y hay más:
`test_identity.py:36,47,54,60,70,77,122` y `test_w1_experience.py:389`. Migran a
tests del matcher puro, del servicio sellado, y uno que pruebe que **ninguna vía
externa puede promover** por mascota.

**Añadido por mi parte a partir de su nota**: el orden dentro del turno pasa a ser
requisito explícito (D29). La verificación pasiva corre antes del ensamblado del
prompt, y eso es lo que permite verificar y recibir el historial en el **mismo**
turno con el gate de D19 activo. Sin declararlo, un refactor futuro lo invierte y
el agente se queda sin memoria justo cuando el cliente acaba de identificarse.

**Contradicciones internas** — las cuatro corregidas: el anti-eco de F0 (líneas
499-501), la permanencia de `try_verify_by_owner_name` (503-506), «Rev. 5 (esta)», y
la premisa de la rev. 4 sobre la sesión, ahora marcada explícitamente como
**refutada** en vez de reescrita (explica por qué la rev. 4 no vio la necesidad del
TTL).

### 7.7 Séptima revisión (1 P0 + 3 P1 + limpieza)

| # | Punto | Veredicto |
|---|---|---|
| P0 | La ruta pasiva no define cómo obtiene un candidato seguro: hoy tokeniza y promueve con cualquier coincidencia | **Cierto y es un bug vivo** (`identity.py:124`): «Sol» promueve con «¿habrá sol mañana?». Con D19 además abre el historial. Aceptado, pero **con su opción (b), no la (a)** — restringir la promoción pasiva al reto activo reintroduce el bucle de fricción que É-F5 eliminó. Añado dos refuerzos que su propuesta no traía: **match exacto** en la vía pasiva (la tolerancia solo tiene sentido cuando el cliente *responde* a la pregunta por el nombre) y candidato único (D30, §2.3.1) |
| P1-1 | Instancia ORM cacheada tras la promoción | **Cierto.** Y la razón exacta importa: hoy funciona por **coincidencia de instancia compartida** (`policy` toma `conversation.contact` y `try_verify_*` guarda sobre ella); el `select_for_update` la rompe. Aceptado el resultado estructurado + reasignación explícita (D31) |
| P1-2 | No está definido el caso sin `TITULAR_CHALLENGE` | **Cierto.** Aceptadas dos de sus tres ramas; en la tercera **discrepo**: con más de un reto activo **promuevo igual y no satisfago slot**, con log. La decisión de seguridad no depende de cuál compromiso sea — lo ambiguo es la contabilidad, y fallar cerrado ahí bloquea a un cliente legítimo por un desorden interno (D32) |
| P1-3 | El orden del reconciliador sigue ambiguo | **Cierto.** Declarada la secuencia exacta en D29: reconciliar → sellar evidencia del burst → resto de policy → ensamblar prompt |

**Limpieza** — las cuatro ciertas y corregidas: «Rev. 6 (esta)», el resumen de la
rev. 4 (ahora dice que creyó que la sesión era una ventana y no lo era), el
encabezado (la remediación es precondición de **F1a**, no de F0) y la fila de
riesgos, que ahora habla del invariante de `_promote` y no de una función concreta.

**Gate estático ampliado** (su recomendación, aceptada): un solo llamador de
`_promote` en código productivo **y** ambos matchers sin `save`/`update` ni
llamadas mutantes.

### 7.8 Octava revisión (1 P0 + 3 P1 + limpieza)

| # | Punto | Veredicto |
|---|---|---|
| P0 | «Marco explícito» no implica intención: «¿venden lentes para sol?» y «No es Luna» pasarían | **Cierto.** Mi lista era ilustrativa, que es la invitación a añadir un patrón laxo. D30 pasa a **gramática cerrada** (§2.3.1) con sustantivo clínico / relación posesiva / verbo de estado, rechazo de negaciones y metalingüísticas, y «todo lo demás no promueve» |
| P1-1 | D31 refrescaba solo `ContactIdentity` | **Cierto**, y con un detalle fino que se me pasó: reasignar `conversation.contact` **no** actualiza un `contact = …` local, que es el patrón de `policy.evaluate`. Sin refrescar `flow`, una evidencia recién reconciliada **reaparece en el mismo turno**. El resultado devuelve todo lo que mutó |
| P1-2 | Satisfacer `pet` no termina el reto | **Cierto y es el mejor hallazgo de la ronda.** `goals.finish_identity` es `close(...)` + `resume(get_suspended_goal(...))` (`goals.py:658`): omitirlo deja «verificado + reto en primer plano + tarea suspendida» = agente atascado justo después de verificar bien. Entra en el contrato atómico (D32). Y su refinamiento de la rama múltiple **corrige mi rev. 8**: dejar los duplicados vivos hacía que el prompt siguiera pidiendo identidad |
| P1-3 | D6 contradecía a D30 | **Cierto.** Dos modos con nombre propio, `passive_free_text` y `challenge_response`, y `match_mode` sellado en el hecho para auditoría |

**Corrección de un error propio que su recomendación de longest-match destapó**: mi
«match exacto» a secas habría **regresionado** el caso compuesto. `identity.py`
documenta la vía de subconjunto porque el reto *«rechazaba el nombre de pila del
propio cliente»*; con «Luna Bella» registrada, «cita para Luna» debe funcionar. El
modo pasivo queda en igualdad exacta contra el nombre completo **o un token
completo ≥3 chars**, sin distancia de edición — se elimina la fuente de falsos
positivos, no el caso legítimo.

**Aceptadas también**: candidato único por **nombre normalizado distinto** (dos
`Pet` «Luna» del mismo dueño no invalidan identidad), longest-match en compuestos, y
la batería adversarial completa. Sobre las citas de mensajes ajenos, una precisión
práctica: WhatsApp no manda el texto citado en `body` (`context.id` en el payload),
así que **no hace falta parsear metadata** — la gramática ya cubre el caso escrito a
mano.

**Limpieza** — las tres ciertas y corregidas: «Rev. 7 (esta)», la columna duplicada
de la fila D29 y el conteo de F0 («seis cambios» → ocho).

### 7.9 Novena revisión (1 P0 + 4 P1 + limpieza)

| # | Punto | Veredicto |
|---|---|---|
| P0 | El matcher de aceptación no puede reutilizarse para el anti-eco | **Cierto y bien argumentado.** Staff escribe «Lun**n**a», el anti-eco estricto no lo encuentra, el cliente dice «Luna» y promueve con un factor sembrado. Dos familias de matcher (D6). **Discrepo en el costo**: un falso rechazo **no** cuesta un turno — repetir el nombre sigue siendo eco hasta que caduque el TTL, así que es un bucle. De ahí D33: rechazo por eco ⇒ **escalado con motivo**, nunca reintento |
| P1-1 | La gramática se contradecía con su propia regla de negación | **Cierto.** Una implementación literal tiraba «Luna no come». La negación se evalúa por **función sintáctica**: de identidad se rechaza, de estado clínico se acepta (§2.3.1) |
| P1-2 | `se llama <mascota>` seguía demasiado abierto | **Cierto**: «el producto se llama Luna» pasaba. En modo pasivo exige sujeto posesivo; en `challenge_response` basta «se llama Luna» o «Luna», porque el sistema acaba de preguntar |
| P1-3 | D31 debe cubrir también al reconciliador | **Cierto, y es el caso más traicionero**: sin mascota en el turno, `verify_pet_evidence` no corre, el `flow` viejo sobrevive y `anchored_identity_facts` republica lo que el reconciliador borró. Ambas fronteras devuelven su estado |
| P1-4 | La precedencia de reanudación se declara pero no se documenta | Cierto que no estaba. **Pero discrepo con escribirla**: `commitment_one_suspended_per_conversation` y `conversationgoal_one_open_per_conversation` (unique sobre `conversation` con `status in (active, deviated)` = `FOREGROUND_STATUSES`) hacen que **dos retos activos sean imposibles** y que `get_suspended_goal().first()` ya sea determinista. Ambas ramas pasan a **aserciones con log**, no a algoritmos de selección: diseñar una precedencia para un estado que la base prohíbe es maquinaria especulativa |

**Normalización de tokens** — cierto y aceptado: `_norm` no toca puntuación
(`identity.py:29`), así que «cita para Luna, por favor» dejaría `luna,`. Declarada
en §2.3.1 (NFD, minúsculas, sin diacríticos, puntuación como límite, nunca
substring, longest-match antes de unicidad).

**Limpieza** — las cinco ciertas y corregidas: «Rev. 8 (esta)», el pseudocódigo
(ahora dice gramática cerrada y distingue los dos matchers), D25 (incluye cierre,
reanudación y todos los goals bloqueados), §6 y la tabla de riesgos.

### 7.10 Décima revisión (3 P1 + limpieza)

| # | Punto | Veredicto |
|---|---|---|
| P1-1 | D33 necesita resultado tipado y conducta para sus dos call sites | **Cierto.** Mi pseudocódigo caía directo en `verify_pet_evidence`. Unión cerrada `NO_EVIDENCE / SEALED_EVIDENCE / ECHO_REJECTED`, y verificar un `ECHO_REJECTED` **imposible de expresar** en vez de algo que haya que recordar. Mismo estado final desde las dos rutas. Añado una convención del proyecto: el texto al cliente vive en `tier0`, no inline |
| P1-2 | Un solo suspendido no garantiza que sea la tarea correcta | **Cierto, y más grave de lo planteado.** No es solo «permitido por cardinalidad»: `goals.open_goal` (`goals.py:434-442`) suspende el compromiso actual al abrir otro de nombre distinto, e `IDENTITY_SPECS` tiene más de un nombre → «identity activo + identity suspendido» **lo produce el flujo normal**. Sin el invariante semántico, verificar bien terminaría **reanudando otro reto de identidad**. D34 |
| P1-3 | «Aserción» y «rama de recuperación» se contradecían | **Cierto.** Semántica única en D32: la DB es la defensa (`IntegrityError`), el servicio comprueba el invariante y loguea, y **nada de `assert` de Python** como control productivo |

**Dato sobre el alcance real del anti-eco**: revisé quién puede revelar un nombre de
mascota a un contacto no verificado. Las plantillas de confirmación lo incluyen
(`CONFIRM_CREATE = "…cita para *{pet}*…"`), pero `create_appointment` exige
`confirmed_in_chat`; y en `register_new_client_and_pet` (que admite `unknown`) el
nombre lo aportó el cliente, así que la primera mención ya lo cubre. **El disparador
práctico es staff** — y ahí ya hay una persona en la conversación, así que el
escalado de D33 no introduce fricción nueva.

**Limpieza** — las cinco ciertas y corregidas: «Rev. 8 (esta)», la columna residual
de la fila D31 (rompía la tabla), la regla 4 de procedencia (decía `_name_matches`
para todos los nombres, contra D6), el test de «dos retos activos» (sustituido por
los tres casos reales) y el nombre de la métrica.

### 7.11 Undécima revisión (1 P0 + 1 P1 + limpieza)

| # | Punto | Veredicto |
|---|---|---|
| P0 | Falta definir **quién elige `challenge_response`** | **Cierto, y es el bypass más fino de las once rondas.** Si el modo se deduce del call site, el modelo salta la gramática pasiva llamando a `identify_client`: no elegiría `from_message`, pero sí **el régimen probatorio**. Aceptado entero: `match_mode` derivado por el servidor con las cinco condiciones, registrado y nunca recibido (D35) |
| P1 | D34 no coincide con el camino actual del código | **Cierto — mi afirmación era falsa.** Verificado: `start_identity` cierra el identity vivo **y** el suspendido antes de crear (`goals.py:586-612`), y el único caller productivo de `open_goal` es `_goal_gate` con `TOOL_GOALS`. Retirada la frase «lo produce el flujo normal» |
| — | Falta identificar el escritor de `TITULAR_CHALLENGE` | **Cierto y necesario.** Aceptado el paquete: escritor único `start_identity`, `open_goal` rechaza nombres de identidad, gate estático, y `pet_asked_at` como insumo de `derive_match_mode` (D36) |
| — | Garantía en runtime para D33 | Aceptada: `EchoRejected` sin `.sealed` y rechazo de cualquier objeto que no sea `SealedPetEvidence`, aunque los chequeos estáticos no corran |

**Hallazgo propio que la corrección destapó, y que cambia el contrato más que el
propio P1**: el estado «identity activo + identity suspendido» **sí ocurre en
producción**, no por creación sino por **resurrección**. `policy.py:171-174` reanima
un suspendido de identidad al frente, y la base de producción tiene una fila
`identity_triage` **suspendida** — maquinaria retirada en É-F5 Fase 2
(`IDENTITY_SPECS` la sigue declarando, `goals.py:332`). Consecuencias: (1)
`get_identity_commitment` puede devolver no-`None` hoy; (2) con el modo por call
site, ese goal resucitado habilitaba el régimen tolerante; (3) **F0 tiene que
cerrar esas filas** (D37) o la única vía real de identity-goal-en-foreground sigue
viva.

**Limpieza** — las tres ciertas y corregidas: «Rev. 10 (esta)», la columna residual
de la fila D34 y el alcance de §6. D34 ahora cita `start_identity` y distingue el
comportamiento actual del riesgo defensivo.

### 7.12 Duodécima revisión (1 P0 + 2 P1 + limpieza)

| # | Punto | Veredicto |
|---|---|---|
| P0 | `pet_asked_at` prueba **intención** de preguntar, no que la pregunta se emitiera | **Cierto, y contradecía D27** (solo cuentan los mensajes realmente emitidos). Aceptado el contrato con `pet_asked_message_id` + estado visible + orden. **Con una sustitución**: su chequeo (7) —«el mensaje representa realmente la pregunta por la mascota»— **no es implementable**: esa frase la **compone el modelo** desde É-F5 Fase 2, y el propio código lo dice en el gate (`planner.py:568`, «El modelo redacta la pregunta»). Verificarlo exigiría clasificar texto libre. Se sustituye por un proxy verificable: **último saliente emitido antes del entrante, sellado al enviarse** como cierre de un turno con `pet` pendiente (`asked_state` `enqueued`→`emitted` en `worker.py:392`) |
| P1-1 | «Huérfano» no estaba definido | **Cierto.** Adoptados los tres conjuntos (`HISTORICAL`/`STARTABLE`/`RESUMABLE`), el predicado formal, la reanudación por `RESUMABLE` en vez de por `IDENTITY_GOALS`, la remediación idempotente con conteos y el orden de despliegue (D37) |
| P1-2 | Falta nombrar el caller productivo de `start_identity` | **Cierto.** Nombrado: la rama `verification_required` de `planner.py:558` — el único punto donde el sistema decide que necesita identificar a quien escribe, y donde ya levanta el aviso de privacidad. Sin nombrarlo, o el matcher tolerante era código muerto o alguien introducía un segundo escritor informal (D36) |

**Escritores partidos** (aceptado): `start_identity` crea, `mark_identity_question_emitted`
sella. La frase «o quien conduzca el reto» desaparece — debilitaba el escritor único.

**Limpieza** — las cuatro ciertas y corregidas: la columna residual de D37, la marca
«(esta)» de la revisión anterior, «huérfano» convertido en predicado, y la
separación explícita entre crear el reto y sellar su pregunta.

### 7.13 Decimotercera revisión (2 P0 + 1 P1 + ajuste)

| # | Punto | Veredicto |
|---|---|---|
| P0-1 | El modelo aún activa el régimen tolerante indirectamente: la guía de `verification_required` (`planner.py:952`) le dice que pida nombre, mascota **o** dígitos, así que puede sellarse una pregunta que no era por la mascota | **Cierto.** Adoptada su **cláusula determinista** (D38), con el precedente que ustedes citan: `_privacy_prefix` ya es un literal que pone el sistema sobre texto del modelo. **Y añado un arreglo obligatorio que se me había pasado**: esa guía **contradice D4b** —sigue ofreciendo `owner_name` y los dígitos como factores— así que F0 la reescribe de todos modos |
| P0-2 | «Último emitido» no es determinable: `Message` no tiene `sent_at` y el sender usa `skip_locked` con réplicas | **Cierto el hallazgo, rechazada la migración.** «Último emitido» lo añadí yo en la rev. 13 y no carga peso: emitida, anterior y dentro del TTL basta. Retirado el requisito, desaparece la necesidad de `Message.sent_at`. Y su objeción de orden **también** afectaba al «antes del entrante»: se resuelve comparando **`pet_asked_at`, estampado en el envío real** y guardado en el goal, no `Message.created_at` (que es el encolado). F0 sigue sin migración y la garantía queda **más fuerte** que con `created_at` |
| P1 | Falta el escritor de la transición `enqueued` | **Cierto**: nombré creador y sellador, no el que liga. Adoptado `bind_identity_question_enqueued` con sus cuatro condiciones. La cuarta es la de más peso operativo: si el sellado falla con el mensaje ya aceptado por WhatsApp, **anomalía + modo pasivo**, nunca rollback de `STATUS_SENT` ni reenvío — `_send_one` guarda dentro de la transacción del batch (`worker.py:392-394`), así que un write posterior podría duplicar un mensaje ya entregado |
| — | `RESUMABLE` mezclaba conjunto y predicado | Aceptado: `RESUMABLE_IDENTITY_GOAL_NAMES` + `is_resumable_identity_goal(goal, now)`, y `policy` llama al **predicado** |

---

## 8 · Riesgos

| Riesgo | Mitigación |
|---|---|
| F0 rompe verificaciones legítimas (dato dado por audio) | La transcripción no existe hoy; el caso ya fallaba. `AGENT_IDENTITY_FACT_UNSOURCED` lo hace visible |
| Retirar `owner_name` deja sin autoservicio a un `Owner` sin mascotas | Verificación por staff (FLUJO-C), con `reason_detail` que explica el caso y qué hacer (§2.2.2). Decisión de producto aceptada por el PO, no efecto colateral |
| Staff no entiende por qué le llega el caso y lo devuelve al agente sin resolver | El `reason_detail` dice qué pasa, por qué y qué hacer; y el escalado usa `reason_code='identity'`, no el deprecado `identity_ambiguous` que ya mintió en producción |
| Alguien añade un **segundo llamador de `_promote`** y salta el anti-eco | Gate estático sobre el invariante «`_promote` tiene exactamente un llamador en código productivo» + ambos matchers sin `save`/`update` ni llamadas mutantes (D28). Más robusto que enumerar funciones prohibidas |
| Una mascota con nombre de palabra común («Sol», «Canela», «Luna») promueve por texto ordinario | **Gramática cerrada** + matcher de aceptación del modo + candidato único (D30, §2.3.1). Con el match por token suelto que hay hoy, «¿habrá sol mañana?» promovía; con un marco laxo, «¿venden lentes para sol?» también |
| El anti-eco no detecta una revelación con typo y se promueve un factor sembrado | Matcher de **revelación** tolerante, distinto del de aceptación (D6). La dirección del error manda: falso rechazo = fricción; falso negativo = historial y tools abiertos |
| El anti-eco rechaza y el agente entra en bucle pidiendo el mismo dato | Rechazo por eco ⇒ **escalado con motivo legible**, nunca reintento (D33). Repetir el nombre seguiría siendo eco hasta que caduque el TTL |
| La DB queda promovida y el turno no lo ve | El servicio devuelve **todo** el estado mutado y el caller lo reasigna, incluida la variable local (D31). Hoy funciona por coincidencia de instancia compartida; el lock la rompe |
| El cliente verifica y el agente sigue pidiéndole identidad | `finish_identity` (cierre + reanudación de la tarea suspendida) va **dentro** del commit; con retos duplicados, ninguno queda en primer plano (D32) |
| La gramática de §2.3.1 no reconoce una forma legítima de nombrar la mascota | **Falla segura**: no promueve y el modelo pregunta — un turno de más, recuperable. Se calibra con tráfico real; ninguna gramática de este tipo se puede probar completa de antemano |
| Un cliente con verificación expirada pierde el historial y el agente suena amnésico | Los hechos de F3 viajan igual (`ya_hablamos_antes`, `ultima_vez`): sabe que es recurrente sin ver el transcript. Se mide (§9) |
| `pet_name` se trata como autenticación fuerte en un documento o UI futura | D23 lo prohíbe explícitamente y §2.3 lista qué habilita y qué no |
| El guard HARD bloquea un saliente legítimo | Solo con contacto no verificado + límites de palabra + excepción por **grounding reciente** |
| `IDENTITY_EVIDENCE_TTL` demasiado corto corta un reto legítimo | Es una constante, no arquitectura. Se calibra con los casos del piloto; 60 min cubre un intercambio de chat con holgura |
| F2 filtra mensajes de otro contacto o de otra cuenta | Tests de aislamiento por ambos ejes; el filtro es por FK, no heurístico |
| Backfill/índice bloquean la tabla | `CONCURRENTLY` + lotes + pasos separados |
| Inbox agrupado con N+1 | `select_related`/`prefetch` explícitos; sin conteos por fila sin índice |
| Mensajes huérfanos aparecen o desaparecen sin criterio | `visible_messages` es el único selector, y los huérfanos quedan fuera por contrato |
| Prompt v11 regresiona conductas cubiertas | Corpus + eval real + los guards como red determinista |

---

## 9 · Verificación post-deploy (umbrales)

- `AGENT_IDENTITY_FACT_UNSOURCED` = **0** pasado el periodo de transición.
- **Cero emisiones NO FUNDAMENTADAS** del nombre registrado hacia contactos no
  verificados. (No «cero salientes con el nombre»: si el cliente acaba de
  escribirlo, repetirlo es legítimo — la métrica anterior prohibía eso.)
- Repregunta de identidad a contactos con verificación vigente: **<1 %**.
- Escalados por «cliente sin mascotas registradas» (§2.2.2): se cuentan. Si son
  frecuentes, la respuesta **no** es reponer `owner_name` como factor — es revisar
  por qué existen esos `Owner`, o acelerar la vía de staff.
- Verificaciones logradas por `pet_name` / total de retos: si cae mucho, revisar
  si el matcher tolerante quedó demasiado estricto, no relajar el factor.
- **Intentos de verificación pasiva rechazados por anti-eco** (no «promociones
  rechazadas»: no hubo promoción que rechazar): si son > 0 de forma sostenida, hay
  staff diciéndole el nombre de la mascota al cliente antes de que él lo aporte —
  es un tema de operación, no de código.
- Turnos servidos **sin** historial cruzado por verificación no vigente (D19):
  mide el costo real del gate.
- Factores descartados por TTL vencido: calibra `IDENTITY_EVIDENCE_TTL`.
- **Como máximo una** sesión abierta por `(contact, channel_account)`.
- `compute_business_metrics` idéntico antes/después de F2 sobre el mismo rango.
- Auditoría de consistencia post-backfill: **0** inconsistencias
  contacto/conversación/organización/cuenta.
- Handoffs por `budget_exhausted`: sin aumento (siguen siendo por sesión).
- P95 del ensamblado de contexto y del listado agrupado del inbox.
- Filas de citas devueltas por mascota (disparador de los filtros server-side).
- Muestreo humano de **≥20 conversaciones** con contexto cruzado de sesiones
  antes del rollout completo.

---

## 10 · Fuera de alcance

- Fusionar físicamente los 19 hilos históricos: reasignar mensajes invalidaría
  `ToolExecution`, goals, handoffs y métricas históricas. La bandeja los agrupa;
  las filas quedan inmutables.
- Resumen conversacional rodante (D10/D14).
- Exponer datos clínicos al agente (D9).
- Transcripción de audio.
- Retención / minimización de mensajes (preexistente, expediente propio).
- `consultar_historial` genérica: solo si F4 resulta insuficiente con casos
  reales.
