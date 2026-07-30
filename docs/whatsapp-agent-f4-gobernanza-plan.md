# É-F4 · Gobernanza conversacional — plan de implementación

**Fecha**: 2026-07-29
**Base**: [`whatsapp-agent-auditoria-rigidez-2026-07-29.md`](whatsapp-agent-auditoria-rigidez-2026-07-29.md)
**Estado**: Fases 0, 1 y 2 **implementadas** (2026-07-30, en `develop`). Fase 3 con su
[ADR p55](decisions/2026-07-30-p55-turn-authority-and-commitments.md) escrito y aceptado, sin
código. Fase 4 pendiente. **Fase 5 cancelada** (§7).
**Contexto de riesgo — revisado 2026-07-30**: el plan se escribió asumiendo que org 3
(`Clinica Bebe coche`) era una clínica real probando el agente el mismo día. El PO aclaró que esa
y las demás organizaciones activas son **demo y pruebas**: no hay usuarios reales todavía. La regla
"una fase, un despliegue" se relaja mientras eso siga así — pero **vuelve a aplicar** en cuanto
entre la primera clínica real, y ese es el momento de releerla, no después.

La auditoría es el diagnóstico. Este documento es lo ejecutable: archivos, formas de código,
tests, criterio de terminado y qué NO entra.

---

## 0. Reglas del sprint

1. **Una fase, un despliegue.** No se acumulan fases sin pasar por producción: la conv 13 existe
   porque el piloto encontró en 6 minutos lo que la suite no vio.
2. **Cada tarea cierra una regla de §11 de la auditoría, o no entra.** Si no se puede nombrar la
   regla, es scope creep.
3. **Ningún cambio de seguridad.** `run_tool` revalida tier/verificación/ownership; la
   confirmación tier-2 ejecuta args staged; la urgencia preempta. Intactos en las 6 fases.
4. **Tests deterministas.** `policy.evaluate` es pura y los matchers también: Fases 0-2 se
   prueban **sin proveedor LLM**. Ningún test nuevo depende de DeepSeek.
5. **Sin `run_in_background`** para la suite. Foreground con timeout generoso.
6. **Los presupuestos (A4, G2, cardinalidad) se escriben en el MISMO commit** que la cosa que
   limitan. Un presupuesto añadido después no se añade nunca.

---

## 1. Secuencia y dependencias

```
Fase 0  R1 + R9(copy)        ── ✅ HECHA (8346f1c). Desbloquea al cliente real.
   │
   ├── Fase 1  R5 R8 R12     ── ✅ HECHA (666273e). Suspender + rastro.
   │      │
   │      ▼
   ├── Fase 2  R11 R2        ── ✅ HECHA (42dd994). Autoría + ventana.
   │      │
   │      ▼
   └── Fase 3  R3 R4 R7 R9*  ── árbitro + compromisos. ADR p55 ✅ escrito (f0323ab).
          │                     Necesita Fase 1 (línea base de TurnDecision).
          ▼
       Fase 4  R10 R2        ── guards conversacionales. Necesita Fase 3.

       Fase 5  R6            ── ❌ CANCELADA (2026-07-30): el alta sin cita no debe
                                existir. R6 se cierra dentro de Fase 3 (§7).
```

**Fase 1 antes de Fase 3 no es negociable**: la arquitectura grande se mide contra el
comportamiento de hoy. Sin `TurnDecision` previo, esa comparación vuelve a ser manual — que es
exactamente lo que costó tres horas en esta auditoría.

### La lógica de la secuencia (formulación del PO)

El plan **no** es "implementemos la arquitectura nueva". Es:

```
1. Corregir los fallos visibles del piloto              → Fase 0
2. Instrumentar y obtener una línea base objetiva       → Fase 1  (TurnDecision)
3. Hacer el comportamiento observable y medible         → Fase 2
4. RECIÉN ENTONCES sustituir la arquitectura            → Fase 3
```

Ese orden es lo que evita que Fase 3 termine siendo una reescritura grande **sin forma objetiva de
demostrar que mejoró algo**. Es el riesgo real de esta clase de proyecto: la arquitectura nueva se
justifica sola, se entrega, y nadie puede decir si el agente atiende mejor.

---

## 1.5 · El principio que sostiene la mantenibilidad: oráculo ≠ diagnóstico

Merece sección propia porque **cambia cómo se prueba un sistema con LLM**, y es lo que decide si
este agente se puede mantener durante años.

En un sistema probabilístico no se puede afirmar sobre el texto:

```python
# ✗ Se rompe por diferencias de redacción. Rojo permanente.
assert reply == "Te lo pido para confirmar que eres tú 🙂"

# ✓ Determinista. Es el comportamiento, no la prosa.
assert decision.verdict    == 'desviar'
assert decision.because    == 'CLIENT_INTERRUPT'
assert decision.return_to  == 'digits'
assert 'identity' in decision.facts_determinantes
```

> **Separar oráculo de diagnóstico convierte un sistema probabilístico en uno parcialmente
> determinista.** Y esa parte determinista es la única sobre la que se puede construir una suite de
> regresión que sobreviva años.

El modo de muerte que esto evita es concreto y conocido: una suite que falla por diferencias de
texto **no se ignora, se apaga.** Y una vez apagada, no hay suite.

Tres consecuencias prácticas:

1. **El tráfico real se vuelve fixture.** Hoy la conv 13 solo puede ser un caso de estudio manual.
   Con el oráculo es un test: se reproduce la secuencia de hechos y se afirma la secuencia de
   veredictos.
2. **Sin proveedor, sin costo, sin inestabilidad.** El árbitro es puro (A2), así que la regresión
   conversacional corre en milisegundos y **$0** — no llama al LLM.
3. **La frontera es load-bearing, no cosmética.** `duration_ms` y `tools_called` viven en la misma
   fila pero **nunca** se afirman. Un solo test que afirme sobre `duration_ms` reintroduce la
   inestabilidad y con ella el apagado de la suite.

| Fase | Esfuerzo | Riesgo de despliegue | Reglas | Estado |
|---|---|---|---|---|
| 0 | **M** (1-2 d) | bajo · lógica pura + copy | R1, R9 (copy) | ✅ hecha |
| 1 | **M** (2 d) | medio · 1 migración, toca escalada | R5, R8, R12 | ✅ hecha |
| 2 | **S** (1 d) | bajo · afecta contexto del modelo | R11, R2 (parcial) | ✅ hecha |
| 3 | **XL** (sprint) | alto · contrato de `ToolOutcome` | R3, R4, R7, R9 (estructural) | ADR listo |
| 4 | **M** (2 d) | medio · puede escalar de más | R10, R2 | pendiente |
| 5 | ~~L (3-5 d)~~ | — | ~~R6~~ → se cierra en Fase 3 | ❌ cancelada |

---

## 2. Fase 0 · Una no-respuesta no es una respuesta equivocada

**Cierra R1.** Y **R9 en copy no es una fase aparte: es dependencia de esta.** Para contestar
*"¿para qué necesitas eso?"* hay que tener el *por qué* escrito. La auditoría los listaba como
pistas separadas; es un error de secuenciación — van en el mismo commit.

### 0.1 · Predicados nuevos (`matchers.py`)

```python
_QUESTION_LEMMAS = (
    'para que', 'pa que', 'por que', 'pq', 'que necesitas',
    'para que lo quieres', 'para que sirve', 'no entiendo', 'como asi',
    'a que te refieres', 'que es eso', 'es seguro', 'es necesario',
    'tengo que darte', 'y eso', 'que dije', 'que te dije',
    'no te acuerdas', 'ya te dije', 'se te borro', 'que miras',
    'no acabamos de', 'no me acabas de',
)

def looks_like_question(text):
    """¿El mensaje interroga en vez de responder?

    Ojo: `normalize()` borra la puntuación, así que los signos se miran sobre el
    texto CRUDO antes de normalizar. Sin esto '¿para qué?' pierde el '?'.
    """
    raw = text or ''
    if '?' in raw or '¿' in raw:
        return True
    n = normalize(raw)
    return bool(n) and _has_any(n, _QUESTION_LEMMAS)


_ANSWER_SHAPES = {
    'digits': lambda n: re.search(r'\d{4}', n) is not None,
}

def is_answer_shaped(stage, text):
    """True / False / **None**.

    `None` = esta etapa no tiene forma verificable (los nombres no la tienen) y
    es una respuesta honesta, no un fallo: el caller la trata como 'no sé'.
    """
    shape = _ANSWER_SHAPES.get(stage)
    if shape is None:
        return None
    return shape(normalize(text))
```

### 0.2 · La regla de desvío (`policy.py`)

```python
def _is_interruption(stage, text):
    """Pregunta que NO trae la respuesta → desvío. Nunca un fallo.

    `is not True` cubre False y None: en una etapa de nombre (None) una pregunta
    es interrupción; en 'digits', '¿es 4586?' trae la respuesta y NO lo es.
    """
    if not matchers.looks_like_question(text):
        return False
    return matchers.is_answer_shaped(stage, text) is not True
```

Se llama al **entrar** en las tres máquinas: `_advance_challenge`, `_advance_family_challenge`,
`_advance_identity_triage`. Si es interrupción → `REPLY(why + reask)`, **sin tocar `fails` ni
`asks`**.

**Tope de desvíos — obligatorio.** Sin él, Fase 0 sustituye un bucle por otro:

```python
state['deviations'] = state.get('deviations', 0) + 1
if state['deviations'] >= 3:
    # 3 desvíos sin una sola respuesta: no avanzamos. Motivo DISTINTO
    # del fallo de verificación (no se le imputa al cliente un dato malo).
    return PolicyDecision(kind=ESCALATE, ...,
                          meta={'handoff_detail': 'deviation_cap'})
```

Esto también cierra el hueco adversario: contestar todo con preguntas evita el contador de
fallos, pero **jamás avanza el reto** → no se obtiene acceso, y a los 3 desvíos hay un humano.

### 0.3 · El `why` por factor (`tier0.py`) — R9

```python
FACTOR_WHY = {
    'digits':  'confirmar que eres tú y proteger los datos del titular',
    'pet':     'proteger el expediente: ese nombre solo lo sabes tú',
    'owner':   'ubicar el expediente correcto',
    'titular': 'buscar el registro con el nombre correcto',
}
T0_WHY_THEN_REASK = "Te lo pido para {why} 🙂\n\n{reask}"
```

Compone con la plantilla original del factor → **cero copy nuevo por factor** más allá del `why`.
En Fase 3 esto migra a `Factor.why` y deja de ser un dict paralelo.

### 0.4 · No sobrescribir un tamiz ya decidido

```python
# policy._advance_identity_triage, rama de 2 'unclear'
flow.setdefault('identity_triage_done', 'unclear')   # antes: asignación directa
```

En conv 13 la asignación directa pisó un `'returning'` correcto con `'unclear'`.

### 0.5 · El planner no reinicia un tamiz ya resuelto

`planner.py:274` llama `policy.start_identity_triage` en **todo** `verification_required` con
`owner_id is None`, ignorando `identity_triage_done`. Es la razón de que en conv 13, tras fallar
la verificación, el `4586` correcto recibiera de vuelta *"¿es la primera vez que nos visitan?"*.

Fase 0 (mínimo honesto): si `identity_triage_done` ya está decidido, **no re-triar** — escalar con
`detail='triage_already_resolved'`. En Fase 1 pasa a *reanudar el compromiso suspendido*, que es
la conducta correcta.

### 0.6 · `time` desde `preferred_time` — y por qué NO arregla la conv 12

`_capture_slot_from_read(conversation, 'time', preferred)` cuando `args['preferred_time']` trae una
hora concreta (`HH:MM`), no un bucket (`"mañana"`).

> **Corrección a la auditoría (§14 Fase 0 ítem 4).** Yo lo listé como si cerrara la repregunta de
> la conv 12. **No lo hace.** La `ToolExecution` real registra
> `args={'date': '2026-08-04', 'preferred': ''}`: el modelo **nunca mandó** `preferred_time`. El
> cliente dijo "martes a las 9", el agente respondió "a las 9:00 am está libre", y esa hora vivió
> solo en prosa. Ninguna tool la vio.
>
> Capturar desde `preferred_time` es correcto y barato, pero es **parcial**. La hora dicha en prosa
> entra al sistema en **Fase 3**, cuando el compromiso deja de alimentarse solo de argumentos de
> herramienta (CR-7). No pretendo cerrar CR-7 aquí.

### 0.7 · Deuda que introdujo el fix de ayer (`103196e`)

`_capture_slot_from_read` solo rellena si `slot in goal.missing`. Si el modelo sondea el lunes
(captura `date=lunes`) y el cliente elige el martes, la lectura **no** actualiza. Hoy lo salva que
los args de escritura sí sobrescriben — pero conv 12 demuestra que el modelo puede no mandarlos.
**Test de regresión**, no cambio de código todavía: dejar anclado el comportamiento antes de que
Fase 3 lo reescriba.

### Tests (Fase 0)

| Archivo | Qué afirma |
|---|---|
| `test_matchers.py` | `looks_like_question`: `?`/`¿` sobre texto crudo; los 24 lemas con `subTest`; `"4586"` no es pregunta |
| `test_matchers.py` | `is_answer_shaped`: `digits` True con 4 dígitos en cualquier posición; **None** en `pet`/`owner`/`titular` |
| `test_policy.py` | **conv 13 completa como caso**: pregunta en `digits` → REPLY con el `why`, `fails == 0` |
| `test_policy.py` | `"¿es 4586?"` en `digits` → avanza (NO desvío) |
| `test_policy.py` | 3 desvíos → ESCALATE con `deviation_cap` |
| `test_policy.py` | `'returning'` no se pisa con `'unclear'` |
| `test_planner.py` | `verification_required` con tamiz resuelto → no re-tría |
| `test_tools.py` | `preferred_time='09:00'` llena el slot; `'mañana'` no |
| `test_tools.py` | (deuda) `date` de un sondeo NO se actualiza desde otra lectura |

### Terminado cuando

- [x] La conv 13 replicada en test da: pregunta → respuesta con motivo → `4586` → verificado
      (`DeviationTests.test_conv13_question_at_digits_gets_reason_not_fail`).
- [x] `fails` nunca sube por un mensaje que no es una respuesta.
- [x] Suite de agente verde completa (**423 tests**, 1 skip preexistente — 2026-07-30).
- [ ] Desplegado y re-probado por WhatsApp contra org 3 — **pendiente, requiere
      confirmación explícita antes de tocar producción.**

### Rollback

Sin migración, sin cambio de contrato. `git revert` del commit y `bash scripts/deploy.sh`.

---

## 3. Fase 1 · No perder progreso + el rastro

**Cierra R5, R8, R12.** Primera migración.

### 1.1 · Suspender en vez de destruir (R5, R8)

Cuatro sitios hacen `pop` de un compromiso en curso:

| Archivo | Sitio | Hoy | Fase 1 |
|---|---|---|---|
| `policy.py` | `_family_fail` (`fails>=2`) | `pop('family_challenge')` | → `flow['suspended']` |
| `policy.py` | `_advance_challenge` (2 fallos) | `pop('identity_challenge')` | → `flow['suspended']` |
| `policy.py` | `_advance_identity_triage` | `pop('identity_triage')` | → `flow['suspended']` |
| `policy.py` | `escalate_to_human` | `pop('pending_action')` + `close_open_goal(HANDOFF)` | suspender ambos |

Versión mínima deliberada: **un solo slot `flow['suspended']`**, no una tabla. La tabla llega en
Fase 3 con el modelo de compromisos. Aquí solo hay que dejar de tirar el progreso.

Y el factor correcto que llega tarde lo resuelve (R8): al entrar un mensaje con
`flow['suspended']` y sin compromiso activo, si el mensaje satisface el factor pendiente → se
reanuda y se resuelve. Es el `4586` de la conv 13.

### 1.2 · `release_conversation` cierra el círculo (`views.py`)

Hoy devuelve `state=ACTIVE` y deja el `HumanHandoff` con `resolved_at=None` — el agente vuelve a
hablar con el caso formalmente en la cola humana (conv 13, handoff 14). Añadir:

- `resolved_at = now()`, `resolved_by = request.user`
- reanudar `flow['suspended']` si existe
- si el humano ya verificó, `staff_verified` **cancela** el compromiso suspendido (no se
  re-interroga a alguien ya validado)

### 1.3 · `TurnDecision` (R12) — sin árbitro todavía

Modelo nuevo, migración `0010_turndecision`. Campos con la frontera explícita:

```python
class TurnDecision(models.Model):
    """Rastro append-only de la decisión de cada turno (R12).

    INVARIANTE: el runtime NUNCA lee esta tabla. Si la lógica del turno la
    consulta, se vuelve una segunda fuente de verdad y viola R7.
    Append-only, como Payment / VitalSigns.
    """
    # ── ORÁCULO · determinista. Los tests SÍ afirman sobre esto ──
    verdict            # enum cerrado
    because            # enum cerrado, ORTOGONAL (G1/G2)
    active_commitment  # coordenada
    return_to          # coordenada
    supplanted_by      # coordenada
    facts_consumed     # JSON
    facts_produced     # JSON
    # ── DIAGNÓSTICO · variable. Los tests NUNCA afirman sobre esto ──
    planner_used, tools_called, duration_ms
```

**Cero PII**: referencias y enums. El texto vive en `Message`, enlazado por FK
(`triggered_by_message`).

Punto de escritura: **un solo envoltorio.** Los 22 puntos de salida desembocan todos en el
`return` de `handle_inbound` (4 directos + 2 que delegan a `_run_planner` / `_commit_pending`).

```python
def handle_inbound(conversation, **kw):          # envoltorio que registra
    started = time.monotonic()
    result = _handle_inbound_inner(conversation, **kw)
    _record_turn(conversation, result, started, kw.get('triggered_by'))
    return result
```

Refactor pequeño y seguro: renombrar el cuerpo actual a `_handle_inbound_inner`. En Fase 1
`verdict` = el `decision` que ya existe; se re-mapea a los 5 veredictos en Fase 3.

**Y el registro nunca puede tumbar el turno** — mismo patrón que `_persist_llm_call`:
`try/except` + `logger.exception`.

### 1.4 · G1/G2 en el primer commit

```python
# tests/test_turn_decision.py
def test_because_is_orthogonal_to_context(self):
    for value in Because.values:
        for name in COMMITMENT_NAMES | STAGE_NAMES:
            self.assertNotIn(name, value)

def test_because_cardinality_budget(self):
    self.assertLessEqual(len(Because.values), 12)
```

El enum contaminado es barato de crear y carísimo de deshacer. Prueba viva:
`reason_code='identity_ambiguous'` **mintió** en la conv 13 (nada fue ambiguo).

### 1.5 · Arreglar `reason_code` de paso

`REASON_IDENTITY = 'identity_ambiguous'` → el valor diagnostica y el diagnóstico fue falso.

Migración cuidadosa, **sin reescribir historia**: añadir `'identity'` a `REASON_CHOICES`, dejar
`'identity_ambiguous'` como deprecado para las filas viejas, escribir `'identity'` en las nuevas.
El qué-pasó va a las coordenadas, no al enum. Documentar el sunset en
[`modules/agent.md`](modules/agent.md).

### Tests (Fase 1)

| Archivo | Qué afirma |
|---|---|
| `test_policy.py` | escalar suspende, no destruye: `flow['suspended']` conserva titular y candidatos |
| `test_policy.py` | factor correcto tardío reanuda y resuelve (**el `4586`**) |
| `test_inbox_api.py` | `release` resuelve el handoff y reanuda |
| `test_inbox_api.py` | `staff_verified` cancela el suspendido (no re-interroga) |
| `test_turn_decision.py` | exhaustividad, 3 capas (§9.2): `TurnResult` exige `verdict`; fixture en `harness.py` que verifica en los **383 tests existentes**; grep de `return {'decision'` |
| `test_contracts.py` | **G3**: la forma real de los 4 contratos coincide con el snapshot en git |
| `test_turn_decision.py` | G1 ortogonalidad + G2 cardinalidad |
| `test_turn_decision.py` | cero PII: ningún campo contiene el cuerpo del mensaje |
| `test_turn_decision.py` | si el registro revienta, el turno responde igual |

### Terminado cuando

- [x] Toda decisión de turno deja fila; se puede reconstruir la conv 13 con un `SELECT`
      (`TurnDecision`, envoltorio único en `planner.handle_inbound`).
- [x] Ningún `pop` de compromiso queda en `policy.py` sin justificar (gate:
      `SuspendNotDestroyGateTests` en `test_policy.py` — suspendido o resolución
      terminal reconocida).
- [x] Handoff resuelto al liberar (`release_conversation`, migración 0010/0011,
      457 tests verdes — 2026-07-30).

### Rollback

Migración **aditiva** (tabla nueva + un choice). Revertir código sin revertir schema; la tabla
queda huérfana sin daño.

---

## 4. Fase 2 · Que el modelo vea la verdad

**Cierra R11, R2 (parcial).**

### 2.1 · Autoría de salientes (R11)

`Message.author_type` ya existe con los 4 valores (`client`/`agent`/`human_staff`/`system`) y
`assemble_messages` **los ignora**: mapea por `direction`. Por eso en conv 13 el modelo se disculpó
por el aviso de fuera-de-horario que escribió el router.

Cambio: etiquetar por autoría. `system` se marca como mensaje del sistema en nombre del agente;
`human_staff` como compañero del equipo (hoy ya entra como `assistant`, y eso está bien — se
conserva, solo se distingue).

### 2.2 · Ventana por turnos, no por mensajes (R2)

`HISTORY_WINDOW = 12` cuenta mensajes crudos. En la conv 13, 6 de los 12 eran plantillas y uno el
"ok" de un humano; los tres hechos centrales quedaron fuera.

**Las ráfagas ya son agrupables sin estado nuevo**: el worker asigna el mismo `available_at` a todos
los entrantes de una ráfaga (verificado: los 7 mensajes de la conv 12 comparten `21:19:06`).
Agrupar por `available_at` da turnos gratis.

Más el **bloque anclado** (P1 mínimo): los hechos de identidad viajan en `DATOS` siempre, así que
salir de la ventana hace perder el fraseo, nunca el hecho.

### 2.3 · `_after_hours_prefix` con oportunidad

Se dispara en el primer `planner_reply` sea cual sea el tema. En conv 13 apareció en medio de una
queja por pérdida de contexto y **causó** el mensaje siguiente. No anteponerlo cuando el turno
resuelve una interrupción o una queja.

### Tests (Fase 2)

| Archivo | Qué afirma |
|---|---|
| `test_prompts.py` | plantilla `system` no se presenta como voz del agente |
| `test_prompts.py` | ráfaga de 7 mensajes = **1 turno** de ventana |
| `test_prompts.py` | con la ventana llena, los hechos de identidad siguen en `DATOS` (el caso exacto de la conv 13) |
| `test_planner.py` | el aviso de horario no se antepone a una respuesta de desvío |

**Corrección al escribir los tests**: el último renglón se ancló en
`test_w1_experience.py::AfterHoursNoticeTests` (donde ya vive el
comportamiento del aviso), no en `test_planner.py`. Y el caso no es "una
respuesta de desvío": un desvío sale por `policy.REPLY` y **nunca** llega a
`_after_hours_prefix`, que solo corre en el camino `planner_reply` — el test
habría pasado sin arreglar nada. El caso real de la conv 13 es una **queja**
(`"¿se te borró el contexto?"`), que sí cae en `RUN_PLANNER`. El test afirma
además que el aviso **no se consume** al suprimirse.

### Terminado cuando

- [x] Reconstruida la ventana de la conv 13 en el turno de las 02:13:39, el hecho *"ya he ido varias
  veces"* **está** disponible (como hecho anclado, aunque el mensaje ya no quepa) —
  `AnchoredIdentityFactsTests.test_returning_client_fact_survives_the_window`.
- [x] Suite del agente verde (**472 tests**, 1 skip preexistente — 2026-07-30).

---

## 5. Fase 3 · Árbitro + compromisos · **ADR p55**

**Cierra R3, R4, R7, R9 (estructural).** Cambio arquitectónico: tablas nuevas + cambio de contrato
de `ToolOutcome` ⇒ **exige ADR** (criterio: contrato interno consumido por varios módulos +
invariante nuevo).

> **[ADR p55](decisions/2026-07-30-p55-turn-authority-and-commitments.md) — ESCRITO Y ACEPTADO
> (2026-07-30), antes de implementar.** Decisión del PO: el ADR va *antes*, porque con cuatro
> contratos cambiando a la vez un ADR posterior no decide, documenta. Contiene solo **autoridad,
> contratos, responsabilidades e invariantes** — ningún detalle de implementación, que es lo que
> envejece. Lo que sigue en esta sección es el **cómo**; la brújula del sprint es el ADR.
>
> Tres decisiones que el ADR fija y este plan no tenía:
> 1. **Propiedad del contrato** (§8 del ADR): *todo cambio semántico del runtime conversacional
>    entra por p55*. Evita que en seis meses "solo agregué un bool" cambie el significado de un
>    compromiso.
> 2. **Retención por UTILIDAD, no por tiempo** (§7): 90 días de `TurnDecision` en crudo porque a
>    los 90 el uso pasa de *reconstruir un caso* a *mirar una tendencia*; el agregado mensual es
>    indefinido. El número se deriva de la razón, no al revés.
> 3. **Disciplina de alcance** (§9): de cada cambio propuesto durante el sprint, *¿es necesario
>    para cerrar R3, R4, R7 o R9?* Si no, queda fuera. La línea base que dejó la Fase 1 pierde
>    valor cuanto más se mezclen los cambios.

### 3.1 · Árbitro (`agent/arbiter.py`, nuevo)

```python
def decide(facts, commitment) -> TurnVerdict:   # PURA. Cero save, cero ORM, cero matchers.
    ...
```

Los cinco mecanismos **en el primer commit**, no después:

| | Mecanismo | Cómo se comprueba |
|---|---|---|
| A1 | 5 veredictos, enum cerrado | test de cardinalidad; un 6º exige ADR |
| A2 | función pura | test: `decide` no toca DB (patch del ORM y falla si se llama) |
| A3 | hechos de entrada, sin cómputo | `decide` no importa `matchers` ni modelos (test de imports) |
| A4 | **presupuesto de ramas** | test que falla si `decide` excede N ramas (`ast` walk) |
| A5 | cero precedencia | las salvaguardas siguen en `policy.evaluate` pasos 0-6 |

Sin A4 en CI, el árbitro es `policy.evaluate` otra vez en seis meses: 203 líneas, 20 pasos, 6
encajados con calzador.

### 3.2 · Compromisos unificados (`agent/commitments.py`)

Los cinco mecanismos de hoy (`identity_triage`, `family_challenge`, `identity_challenge`,
`pending_action`, `ConversationGoal`) pasan a **un** modelo con estados
`activo/desviado/suspendido/bloqueado/completado/abandonado`, **dirección de retorno** y
`Factor(name, why, validator)` — un factor sin `why` no compila (endurece R9).

`ConversationGoal` es la base a extender, no a reemplazar: ya tiene `slots`, `missing`, `asked`,
`stall_turns`, `last_progress_at` y estados. Falta `return_to`, `supplanted_by`, `blocked_reason` y
los dos estados nuevos.

**Migración de datos**: hay conversaciones vivas con `flow['family_challenge']`. Migración que
traduce lo que exista, o —más simple y honesto— cerrar las conversaciones abiertas en la ventana de
despliegue (son unidades, no miles; org 3 es la única con agente).

### 3.3 · Tools a autoridad cero

Salen del contrato de `ToolOutcome`: `reply_text` (1 sitio) y `needs_confirmation` (4 sitios). La
tool **propone** un compromiso y devuelve hechos; el árbitro decide, el planner redacta.

`_soft_error_hint` (una veintena de instrucciones indexadas por código de error de tool) deja de
ser la voz del agente: pasa a ser un hecho de entrada del árbitro.

### 3.4 · Atribución causal por ablación

```python
determinante = {f for f in consultado if decide(facts - f, c) != decide(facts, c)}
```

**Derivada, nunca declarada** — si la reporta quien decide, es coverage y se infla. Posible solo
porque A2 (pura) + A1/A4 (pequeña): ≤12 hechos ⇒ ≤12 reevaluaciones, microsegundos.

Los tres niveles quedan mecánicos, cero anotación humana: `visible` = claves del struct;
`consultado` = proxy que registra accesos; `determinante` = ablación.

### 3.5 · R13 · gate estático de hechos muertos

```python
for fact in FACTS:
    assert any(fact in row.reads for row in ARBITER_TABLE)
```

El gate vinculante es **estático**. El estadístico ("nunca determinante en 30 días") es **reporte,
no gate**: `is_blocked` puede ser determinante el 0.01 % de los turnos y ser irrenunciable — un
gate estadístico borraría la salvaguarda.

### 3.6 · Embudo de compromisos

Terminales que **particionan** los creados, cada uno con dueño: `completado` · `abandonado`
(**producto**, con etapa — aquí caen los que chocan con una restricción deliberada, p.ej. quien no
quiere agendar al darse de alta) · `bloqueado` (**PO**: el dominio no puede, p.ej. `no_vet`) ·
`suplantado sin retomar` (**ingeniería, viola R4**) · `handoff` · `expirado`. Corte por etapa:
*"el 60 % de identidad muere en `digits`"* se ve en días.

### Terminado cuando

- El árbitro cabe en una tabla (métrica de salud de §9.5).
- Las 22 salidas de turno se reducen a 5 veredictos + salvaguardas.
- La conv 13 y la conv 12, **reproducidas desde `TurnDecision`**, dan secuencias de veredictos
  distintas a las de hoy y correctas.

### Riesgo

El más alto del plan. Mitigación: Fase 1 da la línea base; la reproducción de decisiones (no de
texto) es el criterio de aceptación; despliegue con org 3 avisada.

---

## 6. Fase 4 · Guards conversacionales

**Cierra R10, R2 (completa).** Mismo mecanismo que `guards.check_output` (un reintento correctivo,
luego plantilla), aplicado a **conducta**:

1. Misma pregunta 3 veces (R10) — hoy `ya_preguntado_2_veces` se publica al modelo y no hace nada.
2. Contradicción de un hecho anclado (R2) — *"no me lo dijiste aún"* con el hecho en el estado.
3. **Éxito afirmado sin tool ejecutada en el turno** — `BUG-AGENT-001`, abierto desde el piloto
   anterior.

Extender también al camino tier-0: hoy los fallos del router no se validan ni se loguean, y son los
peores de esta auditoría.

**Empezar en modo observación** (`SOFT`, log + reintento). Un guard nuevo en `HARD` escala
conversaciones sanas, y una escalada de más cuesta más que un log.

---

## 7. Fase 5 · Alta sin cita — **CANCELADA** (decisión de producto, 2026-07-30)

**Decisión del PO: dar de alta sin cita NO debe poder hacerse.** El alta va siempre acompañada de
la primera cita, como hoy. Esta fase **no se implementa**.

`register_and_schedule` exige `date`/`time` porque `create-with-patient` es atómico (cliente +
mascota + cita). Yo lo había leído como el corolario de R6 —*si una restricción no se puede
satisfacer sin que el cliente se entere, la restricción es un bug de producto*— y por tanto como
algo a **quitar**. Era una lectura equivocada: la restricción es **política de la clínica**, no
una fuga del schema. Que exista una restricción legítima no es el defecto.

**R6 sigue cerrándose, pero por otra vía.** El defecto real de la conv 12 nunca fue la restricción:
fue **cómo se enunció** y **que no dejara de pedir**.

```
21:22:24  Entiendo, pero el sistema me pide al menos una *fecha y hora* para
          poder registrar a Luna.                    ← habla del schema, no de la clínica
21:24:38  Ah, el sistema me pide una *fecha y hora*… Es solo un requisito del alta
```

Dos correcciones, ambas dentro de **Fase 3**, ninguna requiere fase propia:

1. **Voz de clínica, no de sistema** — el `why` del factor (R9 estructural, [ADR p55
   §5](decisions/2026-07-30-p55-turn-authority-and-commitments.md)) obliga a que el motivo sea
   decible en voz alta: *"el alta la hacemos junto con tu primera cita, así queda todo listo de
   una vez"*. Nunca *"el sistema me pide"*.
2. **Un cliente que se niega no entra en bucle** — el compromiso termina `abandonado` (lo abandonó
   el cliente), que es un terminal legítimo del ciclo de vida. **No** es `bloqueado`: el dominio
   *sí* puede cumplirlo, el cliente es quien no quiere el paso que exige.

**Ajuste al ADR p55 que salió de esta decisión** (§3): `bloqueado` queda reservado para "el dominio
**no puede** cumplirlo" y su productor real es `no_vet` (una clínica sin veterinario activo no
puede agendar) — no el alta sin cita. Sin esta corrección, `bloqueado` habría quedado como un
estado sin ningún productor, es decir código muerto con nombre bonito.

---

## 8. Cambios de schema

| Fase | Migración | Naturaleza | Reversible |
|---|---|---|---|
| 0 | — | ninguna | — |
| 1 | `0010_turndecision` | tabla nueva | sí (aditiva) |
| 1 | `0011_handoff_reason_identity` | choice nuevo, viejo deprecado | sí |
| 3 | `0012_commitments` | tabla nueva + campos en `ConversationGoal` + migración de datos | parcial — requiere plan de datos en el ADR |

Fase 3 es la única que **no** es puramente aditiva. Snapshot de DB antes (el `deploy.sh` ya lo hace).

---

## 9. Gates de CI

### 9.0 · G-GOV · gobernanza de los gates

Un gate de CI tiene **coste de mantenimiento**, igual que un enum. Si cada problema añade uno y
nunca se retira ni se consolida, el pipeline se vuelve ilegible y alguien lo apaga.

> **Todo gate nuevo debe nombrar la clase de bug recurrente que elimina.**

Dos categorías admitidas, y solo dos:

**(a) Reactivo** — elimina una clase de bug con **precedente real**: incidente, hallazgo de
auditoría o regresión. Es el caso por defecto. Sin precedente, no se añade.

**(b) Presupuesto de nacimiento** — acompaña a una capacidad **nueva** en su primer commit, porque
un presupuesto añadido después no se añade nunca (regla 6 de §0). Límite duro: **solo puede
restringir lo que nace en ese mismo PR.** No sirve para meter gates a código existente — eso exige
(a).

Deberes que vienen con cada gate:

1. **Consolidación**: añadir uno obliga a revisar si subsume a otro existente.
2. **Coste declarado**: qué cambio legítimo va a bloquear o molestar.
3. **Un gate que no dispara en 6 meses es señal de REVISIÓN, no de borrado.** Puede estar
   funcionando como disuasión. Es la misma falacia que en R13: *"nunca determinante en 30 días"* no
   autoriza borrar `is_blocked`. Coherencia de razonamiento.

#### Auditoría de mis propios 10 gates contra esta regla

| Gate | Categoría | Precedente |
|---|---|---|
| `looks_like_question` / `is_answer_shaped` | (a) | **conv 13**: `Ana Cruz` bloqueada por preguntar |
| grep: cero `flow.pop` de compromiso | (a) | **conv 13 · S2 / CR-5**: el `4586` correcto cayó al vacío |
| exhaustividad de `TurnDecision` | (a) | **§9.2**: esta auditoría no se pudo hacer con `SELECT` |
| G1/G2 ortogonalidad y cardinalidad | (a) | **`identity_ambiguous` mintió en producción** |
| `TurnDecision` sin PII | (a) | clase ya vista en el repo: `console.log(err)` filtrando JWT |
| A2 · `decide` no toca ORM | (a) | **los 6 `save()` de `policy.evaluate`** |
| A3 · `decide` no importa matchers | (a) | idem: `evaluate` calcula sus propios hechos |
| A4 · presupuesto de ramas | (a) | **203 líneas, 20 pasos, 6 con calzador** |
| **R13 · hecho leído por ≥1 fila** | **(b)** | **⚠ ninguno. El modelo de hechos no existe todavía** |
| reporte de huérfanos/muertos | — | no es gate |

**Nueve pasan por (a). El décimo no pasa** — R13 estático es preventivo, sin precedente. Por eso
existe la categoría (b), y R13 solo se justifica **si nace en el mismo PR que el modelo de
hechos**. Si algún día se intenta añadir suelto, se rechaza.

Aplicar la regla contra mi propio instinto: **quería un gate que impidiera afirmar sobre campos de
diagnóstico** (`duration_ms`, `tools_called`) en los tests. No tiene precedente en este repo — solo
la clase genérica de suites inestables. **Queda como convención documentada, no como gate**
(§9.3). Si pasa una vez, se gana el gate.

### 9.1 · G3 · Contract Freeze (PO)

Cuatro tipos son la **API interna** del sistema: `ToolOutcome`, `TurnDecision`, `PolicyDecision`,
`Commitment`. No pueden cambiar "porque sí".

> Si el PR toca uno de los cuatro, debe contener **exactamente una** de estas dos cosas:
> **un ADR** o **un bump de versión de contrato**.

La calibración es lo que evita que se vuelva burocracia — y es mecánicamente clasificable:

| Cambio | Detección | Requisito |
|---|---|---|
| Campo **añadido** opcional; valor de enum nuevo que pasa G1/G2 | aditivo | **bump menor**. Sin ADR |
| Campo **eliminado**, renombrado, re-tipado; validador cambiado; significado cambiado | rompe/semántico | **ADR** referenciado en el commit |

Mecanismo: un **snapshot del contrato versionado en git** (`agent/contracts.lock` o un test con la
forma esperada literal), y el gate diffea la forma real contra el snapshot. Mismo patrón que
`requirements.lock`, que este repo ya usa como fuente pinneada en CI.

**Coste declarado**: cualquier campo nuevo, aunque sea trivial, obliga a tocar el snapshot. Es el
precio de que Fase 3 no pueda cambiar `ToolOutcome` en silencio — y Fase 3 **le quita dos
capacidades** (`reply_text`, `needs_confirmation`), que es exactamente el cambio semántico que este
gate existe para hacer visible.

### 9.2 · Exhaustividad de `TurnDecision` — tres capas

El PO tiene razón en el modo de fallo: **en instrumentación, el error típico no es registrar mal,
es olvidar una rama.** Y su segunda propuesta es mejor que la primera: un test estático de "todas
las salidas pasan por el wrapper" lo derrota la próxima función que alguien añada. Tres capas, de
la más fuerte a la más débil:

**Capa 1 · Estructural (la mejor: no se puede olvidar).** `_handle_inbound_inner` deja de devolver
un dict pelón y devuelve un `TurnResult`, cuyo constructor **exige** `verdict`. No es "acuérdate de
registrar": es **no se puede volver sin veredicto**. Convierte el gate en imposibilidad.

**Capa 2 · Toda la suite existente lo verifica, gratis.** Un fixture en la base de tests de agente
que, al terminar cada turno, afirme que existe fila. Así los **383 tests actuales** pasan a ser
cobertura de exhaustividad sin escribir un test nuevo por rama.

```python
# tests/harness.py — mixin compartido
def tearDown(self):
    if self._turns_run:
        assert TurnDecision.objects.count() == self._turns_run
```

Matiz importante: la aserción va **al final del turno**, no en `enqueue_outbound`. Una decisión
`SILENT` (bloqueado, humano activo) no manda ningún mensaje y **sí** debe dejar fila. Anclar el
chequeo al mensaje se saltaría justo esas ramas.

**Capa 3 · Grep.** Ningún `return {'decision'` fuera de `_handle_inbound_inner`. Barato, atrapa al
que añade una salida nueva sin pasar por el tipo.

### 9.3 · Tabla de gates

| Gate | Fase | Cat. | Bloquea |
|---|---|---|---|
| `looks_like_question` / `is_answer_shaped` con recall por lema | 0 | a | sí |
| grep: cero `flow.pop` de un compromiso en `policy.py` | 1 | a | sí |
| **exhaustividad `TurnDecision`** (3 capas, §9.2) | 1 | a | sí |
| G1 ortogonalidad + G2 cardinalidad de `because` | 1 | a | sí |
| `TurnDecision` sin PII | 1 | a | sí |
| **G3 · Contract Freeze** (§9.1) | 1 | a | sí |
| A2: `decide` no toca ORM | 3 | a | sí |
| A3: `decide` no importa matchers ni modelos | 3 | a | sí |
| A4: presupuesto de ramas de `decide` | 3 | a | sí |
| R13: todo hecho leído por ≥1 fila del árbitro | 3 | **b** | sí |
| reporte de hechos huérfanos / muertos | 3 | — | **no** (reporte) |

**Convención sin gate** (§9.0): un test puede afirmar sobre campos del **oráculo**; afirmar sobre
`duration_ms`, `tools_called` o `planner_used` es olor a test. Documentado, no gateado — todavía no
tiene precedente aquí.

---

## 10. Decisiones que necesito antes de empezar

**Estado al 2026-07-30**: las cinco resueltas. Ninguna bloquea ya la Fase 3.

1. ✅ **¿Fase 0 se despliega sola, ya?** → **Sí**. Implementada y en `develop` (`8346f1c`). El
   despliegue al VPS quedó pendiente por un problema de credenciales de git en el servidor, ajeno
   al código. Contexto revisado por el PO: las organizaciones activas son **demo y pruebas** — no
   hay usuarios reales todavía, así que la cautela de "una fase, un despliegue avisando a la
   clínica" se relaja mientras eso siga así.
2. ✅ **¿Alta sin cita existe como producto?** → **NO, y no debe poder hacerse.** El alta va
   siempre con la primera cita. **Fase 5 queda CANCELADA** (§7): no hay restricción que quitar —
   es política de la clínica, no una fuga del schema. R6 se cierra igual, dentro de Fase 3: el
   `why` obligatorio del factor impide enunciarla como sistema ("el sistema me pide una fecha") y
   el terminal `abandonado` impide el bucle de pedir. Ojo con el matiz: **no** es `bloqueado` —
   el dominio sí puede cumplirlo, el cliente es quien no quiere el paso que exige.
3. ✅ **Retención de `TurnDecision`** → 90 días en crudo + agregado mensual, **con un principio
   por encima del número**: *se retiene por **utilidad**, no por tiempo*. 90 no es mágico: es
   donde el uso cambia de "reconstruir un caso" (regresión, depuración, incidentes) a "mirar una
   tendencia" (KPIs, producto). Si el uso cambia, cambia el número — y eso es una decisión, no un
   ajuste de configuración. Fijado en [ADR p55 §7](decisions/2026-07-30-p55-turn-authority-and-commitments.md).
4. ✅ **¿ADR p55 antes de Fase 3, o al final?** → **ANTES**, y ya está escrito. Razón del PO: Fase
   3 no es una implementación, es un cambio simultáneo de `ToolOutcome`, `Commitment`, árbitro,
   `TurnResult` y control de flujo. Con eso en juego se toman decenas de microdecisiones; si el
   ADR aparece después deja de ser una decisión y se vuelve documentación histórica. Alcance
   deliberado: **autoridad, contratos, responsabilidades e invariantes** — nada de implementación.
5. ✅ **¿Fase 2 antes o después de Fase 3?** → **Antes**, como estaba planeado. Hecha (`42dd994`).

**Decisión añadida por el PO, que este plan no contemplaba**: *¿quién es dueño del contrato?* Fase
3 introduce `TurnResult`, `ToolOutcome`, `Commitment` y `TurnDecision` — y nadie tenía autoridad
declarada para modificarlos. Regla, en [ADR p55 §8](decisions/2026-07-30-p55-turn-authority-and-commitments.md):
**todo cambio semántico del runtime conversacional entra por el ADR p55**. Sin ella, dentro de seis
meses alguien "solo agrega un bool" y cambia el significado de un compromiso.

---

## 11. Lo que NO entra

- Transcripción de audio (UX-14). Sigue en su propio carril.
- Tocar la detección de urgencia. Se queda en el paso 3 de `policy.evaluate`.
- Sustituir `guards.py`. Se **extiende** en Fase 4; el diseño es correcto, le falta cobertura.
- Reemplazar `ConversationGoal`. Se extiende (Fase 3).
- Tocar la confirmación tier-2. Es lo mejor implementado del sistema y el patrón a imitar.
- Cambiar de proveedor LLM, tocar el prompt más allá de lo que exija el contrato, o mover el
  presupuesto de conversación.
- Migrar `matchers.py` a algo "más inteligente". 349 lemas en 17 listas planas es **crecimiento
  sano**: aditivo, testeable por lema, cero ramas. El destino correcto de la complejidad que A3
  saque del árbitro es justamente ahí.
