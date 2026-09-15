# ADR p59 — La interpretación vuelve al modelo; el servidor conserva la autorización

> **Enmienda B2 (2026-09-15), solo §6.** `rows_read=0` no acredita ausencia:
> también puede reflejar error, recorte o cobertura desconocida. Las afirmaciones
> de existencia/ausencia en resultados sensibles tienen renderer determinista
> desde READ validada y su completitud. El guard léxico complementario
> `denies_domain_state` pasa a HARD para afirmaciones libres no respaldadas;
> no es un verificador universal. No se modifica la interpretación ni el
> mecanismo de identidad de este ADR.
> [Contrato B2](../contrato-resultados-tools-b2.md).

**Fecha**: 2026-08-17
**Estado**: **ACEPTADO** (PO, 2026-08-17) e **implementado**.
**Relación con p58**: **la enmienda**. p58 §2 (ADR de hace dos días) puso en el servidor tanto la autorización como la interpretación del lenguaje. Esta propuesta mantiene la primera y retira la segunda.
**Origen**: conv 21 en producción (2026-08-17), 15 h después de desplegar p58.

---

## 1 · Por qué esto existe

p58 cerró un bypass real: el sistema se verificaba contra un dato que él mismo
había filtrado. La regla que introdujo —**el modelo no elige su propia prueba**—
es correcta y no se toca.

Lo que se implementó, además de esa regla, fue una **gramática cerrada** que
decide si el cliente «quiso decir» que aportaba el nombre de su mascota. Eso no
es una decisión de autorización: es comprensión de lenguaje natural. Y es lo
único del diseño que en producción falló contra un cliente legítimo.

Medido contra el código desplegado (`a00afb6`):

```
### passive_free_text
  'koler'  -> None          ← rechazado
### challenge_response
  'koler'  -> 'Koler'       ← aceptado
```

El cliente contestó exactamente lo que se le preguntó, con el nombre correcto de
su mascota, y se rechazó por llegar «sin marco gramatical». Costó 6 mensajes del
agente y 18 minutos, y el cliente escribió, literalmente:

> «cada vez que necesite algo tendré que darles la información»
> «no la pueden ver o que»

Yo había escrito en el plan que este fallo costaría «un turno de más,
recuperable». Fue un orden de magnitud más caro.

---

## 2 · El error de diseño, dicho con precisión

El requisito de seguridad y la interpretación del lenguaje se trataron como una
sola cosa. Son dos:

| Pregunta | Quién debe decidirla | Por qué |
|---|---|---|
| ¿Esta evidencia **autoriza**? | **Servidor, siempre** | Es la frontera de seguridad. Procedencia derivada de la ráfaga, anti-eco, TTL, `_verification_ok`, alcance por organización, args staged de tier-2, INV-A/D |
| ¿Qué **quiso decir** el cliente? | **El modelo** | Es literalmente para lo que sirve. Un regex no infiere intención, y pedírselo produce una lista de casos que no tiene fondo |

**Mover la interpretación al modelo no reabre el bypass.** El bypass era que el
sistema aceptaba como prueba un dato que él había revelado primero. Eso lo
cierran tres mecanismos, y **ninguno de los tres es la gramática**:

1. **Procedencia** — el servidor localiza qué mensaje *del cliente*, en *esta*
   conversación, contiene el valor. Nunca llega en los argumentos de la tool.
2. **Anti-eco** — primera mención gana, sobre mensajes realmente emitidos.
3. **TTL** — 60 min sobre el mensaje origen.

La gramática solo añade «…y además venía bien enmarcado». Eso no protege de
nada que los otros tres no cubran.

---

## 3 · La contradicción interna que esto corrige

p58 aceptó **por escrito** que `pet_name` es un factor de **conocimiento de baja
entropía**, que **no es autenticación fuerte** y que no debe describirse como
tal. Y a ese factor débil le construí un parser de grado fortaleza.

Los costos son asimétricos al revés de como los traté:

| Dirección del error | Consecuencia | Frecuencia observada |
|---|---|---|
| **Falso positivo** (acepta de más) | Alguien que escribió una palabra ve *sus propias* mascotas y citas. Nada de billing, caja, ni expedientes clínicos, ni datos de otro cliente | 0 casos en el piloto |
| **Falso negativo** (rechaza de más) | Un cliente legítimo **no puede identificarse nunca** y se va sin su cita | 1 de 1 conversaciones reales |

Optimicé la dirección que menos importaba. Y no por accidente: cada regla de
este subsistema nació de un incidente, así que todas están afinadas para que
*ese* incidente no vuelva, y ninguna para que el caso normal funcione.

---

## 4 · Lo que se retira y lo que se queda

### Se retira

| Pieza | Motivo |
|---|---|
| `extract_pet_candidate` + gramática cerrada (`_CLINICAL_NOUNS`, `_PET_NOUNS`, `_LINK_WORDS`, `_STATE_STARTS`) | Enumera formas de nombrar una mascota. Espacio infinito |
| `_IDENTITY_NEGATIONS` | Enumera formas de negar identidad. Espacio infinito. La lista actual no cubre `no soy X`, y añadirlo sería repetir el método |
| `derive_match_mode` + los dos regímenes (`passive_free_text` / `challenge_response`) | Existían porque la gramática necesitaba saber si el cliente estaba «contestando». Si el modelo declara la intención, la distinción sobra |
| Condiciones 1-8 de D35, `bind_identity_question_enqueued`, `mark_identity_question_emitted`, `working_state['identity_question']` | Maquinaria para probar que el sistema había preguntado. Sin dos regímenes no hace falta |

### Se queda, intacto

- **Procedencia derivada del servidor** — sigue siendo el servidor quien busca
  el valor en la ráfaga y valida `direction='in'`, `author_type='client'` y
  misma conversación.
- **Anti-eco** con el matcher tolerante y primera-mención-gana.
- **`IDENTITY_EVIDENCE_TTL`**, reducer puro y reconciliador.
- **`_promote` con un solo llamador** y su gate estático.
- **La transacción** (`_promote` + flow + slot + `finish_identity` en un commit).
- **La cláusula determinista del sistema** (D38) — sigue siendo el sistema quien
  pregunta, porque el modelo ya demostró que pide los 4 dígitos si le dejas.
- **Todo `_verification_ok`, tier-2 con args staged, alcance por organización,
  INV-A/D.**

### Cómo queda el contrato

El modelo llama `identify_client(pet_name="Koler")` cuando **cree** que el
cliente se identificó. El servidor:

1. Busca `"Koler"` en los entrantes del cliente de la ventana (match tolerante:
   nombre completo o token completo, con distancia de edición ≤1 para el typo).
2. Si no aparece en ningún mensaje del cliente → **rechaza**. Ésta es la barrera
   real: el modelo no puede inventar el aporte, solo interpretarlo.
3. Anti-eco: si nosotros lo dijimos primero dentro del TTL → `EchoRejected` →
   hand-off, sin promoción.
4. TTL, procedencia, transacción: sin cambios.

El modelo pasa de **elegir el régimen probatorio** (que era el agujero fino de
D35) a **proponer una lectura que el servidor comprueba contra el texto real**.

---

## 5 · El riesgo que esto añade, sin adornos

**Un falso positivo se vuelve alcanzable**: el modelo podría llamar
`identify_client(pet_name="Sol")` sobre *«¿va a haber sol mañana?»* si la mascota
se llama Sol. El servidor encontraría «sol» en el mensaje del cliente y
promovería.

Qué lo acota:

- El modelo tiene que **decidir llamar la tool**. No es un promotor pasivo que
  se dispara con cualquier coincidencia — es justo lo contrario del bug que la
  gramática arregló, donde `try_verify_by_pet_name` tokenizaba el texto y
  promovía sin que nadie lo pidiera.
- Lo que se abre es **el expediente del titular de ese número**, que ya coincidía
  por teléfono. Sigue sin haber billing, caja, expedientes clínicos ni datos de
  terceros.
- p58 ya declaró este factor débil. El riesgo no es nuevo; lo que cambia es que
  deja de compensarse bloqueando a los clientes legítimos.

**Lo que NO se acepta**: que el modelo invente el aporte. El paso 2 lo impide, y
es verificable con tests adversariales (un `identify_client` cuyo valor no está
en ningún entrante del cliente → rechazo, con gate).

**Si el nivel de sensibilidad de lo que el agente pueda hacer sube**, este factor
no alcanza — y la respuesta sería un segundo factor real o verificación humana
(FLUJO-C), nunca reponer la gramática.

---

## 6 · Guard simétrico (implementado)

Descubierto en la misma conversación y **no dependía de esta decisión**.

`guards.check_behaviour` tiene `unbacked_success`: impide **afirmar lo que no
pasó** (dar por agendada una cita inexistente, BUG-AGENT-001).

**No existe el inverso: negar lo que sí pasó.** En conv 21 el agente dijo cuatro
veces «no tengo ninguna cita agendada» mientras las tools devolvían
`{"appointments": 1}`. Fue el fallo más caro de la conversación y ninguna de las
tres reglas de conducta lo mira.

Implementado: violación **`denies_domain_state`** — si el turno corrió una lectura
que devolvió N>0 y el texto niega existencia, es error del modelo. Nace **SOFT**
(un reintento correctivo y, si persiste, se envía con log), igual que los otros
tres. `rows_read` se acumula en el planner junto a `tool_facts`, en el mismo sitio.

**Su lista de patrones comparte la debilidad que este ADR le reprocha a la
gramática, y se acepta por la DIRECCIÓN del fallo**: un fraseo no cubierto
significa que no hay corrección (fail-open, se pierde una mejora), mientras que la
gramática fallaba al revés (fail-closed, un cliente legítimo sin poder
identificarse). Por eso esta lista puede crecer con el tráfico real y aquella
tenía que desaparecer.

Anécdota que lo ilustra: mi primera versión de la lista **no tenía la primera
persona** —«no TENGO ninguna cita»— que es literalmente la que usó el agente en
conv 21. Lo cazó el test, no yo.

---

## 7 · Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| **Añadir `no soy X` a la lista de negaciones** | Es el método que produjo el problema. `no soy`, `yo no me llamo`, `ese no es mi nombre`, `koler es el perro`, `te confundes`, `al revés`… no tiene fondo |
| **Ampliar la gramática con más marcos** | Igual, un nivel más arriba. Cada marco nuevo es un incidente ya pagado |
| **Bajar el umbral del matcher pasivo** (aceptar token suelto) | Reintroduce el falso positivo *sin* ganar comprensión: «¿habrá sol mañana?» volvería a promover, y esta vez sin que nadie lo haya pedido |
| **Extender `challenge_response` a las preguntas del modelo** | Era mi propuesta inicial. Deja la gramática en pie con una excepción más, y hace que el régimen probatorio dependa de que el modelo haya preguntado — un primo del agujero de D35 |
| **RAG / embeddings sobre la conversación** | No es un problema de recuperación: el texto estaba en el contexto. Añadiría una segunda fuente de verdad (prohibido por p50) sin tocar la gramática, que es lo que rechaza |
| **Verificación humana para todo** | Convierte cada cliente en un ticket. FLUJO-C existe para cuando no hay factor, no como vía normal |

---

## 8 · La decisión

**Aceptada por el PO el 2026-08-17.** Se relaja deliberadamente la barrera de
interpretación —conservando las tres de autorización— a cambio de que el único
factor de autoservicio funcione para los clientes reales. El factor ya estaba
declarado débil por escrito, y una barrera que rechaza al 100 % de los clientes
legítimos no está protegiendo: está cerrando.

### Lo que se retiró de verdad

| Pieza | Dónde vivía |
|---|---|
| `extract_pet_candidate` + gramática (`_CLINICAL_NOUNS`, `_PET_NOUNS`, `_LINK_WORDS`, `_STATE_STARTS`) | `identity_evidence.py` |
| `_IDENTITY_NEGATIONS` | idem |
| `derive_match_mode` + los dos regímenes | idem |
| `matches_pet_name_exact` | `identity.py` — matcher del régimen pasivo |
| `bind_identity_question_enqueued` · `mark_identity_question_emitted` · `working_state['identity_question']` | `goals.py` |
| El write de sellado en el sender | `worker.py` |
| **La ruta pasiva de `policy.evaluate` (paso 9)** | `policy.py` |

La ruta pasiva **no estaba en la propuesta y hubo que retirarla**: escaneaba la
ráfaga sin propuesta del modelo, y era la gramática la que decidía si el cliente
«había querido decirlo». Sin gramática, ese escaneo promueve con cualquier
coincidencia de token — el bug de «Sol» exactamente. Queda **una sola vía**:
`identify_client`.

**Consecuencia aceptada**: quien escribe «cita para Luna» se verifica dentro del
tool loop del mismo turno (la tool personal rebota, el modelo llama a
`identify_client`, reintenta), así que recibe su respuesta igual. Lo que llega un
turno tarde es el **transcript cruzado**, porque el prompt ya se había ensamblado.
Mucho mejor que no verificarse nunca.

### Dos huecos que el cambio destapó

1. **El eco no enviaba su plantilla.** `T0_IDENTITY_ECHO` solo lo ponía la ruta
   pasiva; por la de `identify_client` el modelo redactaba libremente **después**
   de haber escalado, así que podía repetir el nombre — la fuga que ese camino
   existe para cerrar. Al quedar `identify_client` como única vía, el hueco pasó a
   ser el camino principal. Ahora el planner corta el turno y pone la plantilla.
2. **El aporte parcial de un nombre compuesto.** Con «Luna Bella» registrada, el
   cliente escribe «cita para Luna» y el modelo propone «Luna»: buscar el nombre
   **completo** en el texto lo rechazaba. Se acepta contra lo que el modelo
   transcribió **o** contra el nombre registrado (`_says_the_pet`).

### Gate que impide la vuelta atrás

`test_the_retired_grammar_does_not_come_back` falla si reaparece
`extract_pet_candidate`, `derive_match_mode`, `_IDENTITY_NEGATIONS`,
`_CLINICAL_NOUNS` o `_STATE_STARTS`. Reponer una pieza con otro nombre
reintroduce el fallo: un fraseo nuevo vuelve a ser un bug nuevo.

---

## 9 · Lo que este documento no cubre

- El incidente de `remediate_identity_f0` corriendo cada 30 minutos: ya
  corregido, no necesita decisión.
- La consolidación del surface de tools (`get_appointments`): ya hecha, mismo
  diagnóstico de fondo (cada tool era una pregunta congelada) pero sin
  implicación de seguridad.
- Los `continue` restantes de `tools.py`: **revisados, ninguno es el mismo
  defecto**. Los 8 que quedan o reafirman el predicado de INV-D
  (`_day_occupancy`, `_own_appointment_at`) o cuidan la integridad del dato.
  Retirarlos por parecido rompería la detección de solapes.
- El mensaje de dos autores (el modelo pidiendo los 4 dígitos junto a la
  cláusula del sistema): necesita un guard propio, «el modelo pide un factor
  retirado». No hay ninguno hoy.
