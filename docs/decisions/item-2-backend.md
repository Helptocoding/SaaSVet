# Análisis de arquitectura — Item 2: retomar `pending_action` tras liberar conversación

**Fecha**: 2026-08-08
**Estado**: ANÁLISIS — no implementado, no bloquea ni reemplaza la revisión eng ya
cerrada en `docs/whatsapp-agent-identity-context-fixes-plan.md` §Item 2. Este
documento es una segunda pasada, hecha desde cero contra el código real
(`agent/policy.py`, `agent/confirmations.py`, `agent/views.py`, `agent/planner.py`,
`agent/tools.py`), para verificar el diseño del plan y endurecerlo donde hacía
falta. Donde coincide con el plan lo dice explícitamente; donde propone algo
distinto, explica por qué.
**Alcance**: solo diseño. No se tocó ningún archivo de producción.

---

## 1. Resumen ejecutivo

`release_conversation` (`agent/views.py:362-422`) hoy **no toca en absoluto**
`flow['suspended']` ni `flow['pending_action']`. Verificado leyendo la función
completa: solo cambia `state`/`claimed_by`, abandona el compromiso de identidad
si el contacto ya quedó verificado, y resuelve el `HumanHandoff`. Una propuesta
de cita suspendida por una escalada (`policy.escalate_to_human`,
`policy.py:352-364`) queda **huérfana para siempre** tras liberar: nunca vuelve
a `flow['pending_action']`, así que ni la confirmación normal
(`policy.py:179-199`) ni el nudge (`policy.py:398-440`, que exige
`flow.get('pending_action')` truthy) la recogen jamás. Este es el bug real que
Item 2 cierra.

La propuesta de este documento coincide con el plan en el mecanismo general
(verificar contra dominio → descartar si ya se resolvió, restaurar si no) y en
las dos simplificaciones DRY de la revisión eng (sin revalidación de
disponibilidad, sin envío síncrono). Se aparta en un punto concreto y con
justificación de código: **el `pending_action` restaurado no debe conservar su
`expires_at` original** — debe restaurarse ya vencido. Esto es lo que responde
con más solidez a la pregunta "cómo impedir que un 'sí' nuevo ejecute una
confirmación antigua", reutilizando el mecanismo de re-parafraseo que YA existe
(`confirmations.EXPIRED_REPARAPHRASE`, `planner.py:607-619`) sin abrir una ruta
de envío nueva — sigue cumpliendo la decisión eng #2 al pie de la letra.

---

## 2. Mecanismo real, trazado en código

### 2.1 Qué es un `pending_action`

`agent/confirmations.py:39-52` (`stage_pending`) persiste en
`Conversation.flow['pending_action']`:

```python
{
    'tool': tool,                 # 'create_appointment' | 'cancel_appointment' |
                                   # 'reschedule_appointment' | 'register_new_client_and_pet'
    'args': args,                 # YA resueltos a PK/public_id — nunca handles
    'paraphrase': paraphrase,     # plantilla literal, nunca generada por el LLM
    'idempotency_key': ...,       # uuid4 si el caller no trajo uno
    'expires_at': iso datetime,   # ahora + 30 min (PENDING_TTL)
}
```

Los cuatro tools que lo generan (`tools.py:783-991`, `1063-1127`) ya resuelven
`args` a PKs/public_ids **en el momento de proponer**, no en el momento de
confirmar — es la garantía TC-SEC-03 (la afirmativa nunca amplía el alcance de
lo parafraseado).

### 2.2 Cómo se ejecuta una confirmación

`policy.evaluate()` paso 7 (`policy.py:179-199`): si hay `pending_action` y el
burst clasifica `'affirmative'` (`matchers.classify_confirmation`,
`matchers.py:135-160`), devuelve `RUN_PLANNER` con
`meta={'confirm': 'affirmative'}`. `planner.py:309-311` lo intercepta antes de
llamar al LLM y ejecuta `_commit_pending` (`planner.py:601-628`) directamente.

`_commit_pending` **primero revisa el TTL** (`confirmations.is_expired`,
`confirmations.py:59-69`):

- **Vencido** → NO ejecuta nada. Re-arma el pending con un TTL fresco
  (`stage_pending` de nuevo, mismos `tool`/`args`/`paraphrase`) y envía
  `EXPIRED_REPARAPHRASE` ("Pasó un rato — te confirmo de nuevo: {paraphrase}").
  El cliente tiene que volver a decir "sí" viendo el contexto completo
  restated.
- **Vigente** → ejecuta `COMMIT_HANDLERS[tool]` con los `args` staged, vía
  `executor.call(...)` (loopback HTTP con JWT propio del agente,
  `executor.py:43-171`), pasando `idempotency_key` cuando el handler lo trae.

Este mecanismo **ya existe y ya tiene tests** (`test_write_tools.py`,
`test_f5_fase1.py`). Es el que se debe reutilizar, no reconstruir.

### 2.3 Qué pasa al escalar (SUSPEND, ya implementado)

`policy.escalate_to_human` (`policy.py:352-364`):

```python
if flow.get('pending_action'):
    flow['suspended'] = {'kind': 'pending_action', 'state': flow['pending_action']}
    flow.pop('pending_action', None)
```

Suspende, no destruye. No toca `expires_at` dentro de `state` — el reloj del
TTL original sigue corriendo (o ya venció) mientras la conversación está en
manos de un humano, que puede durar minutos u horas.

### 2.4 Qué pasa al liberar (RESTORE, no existe hoy)

`release_conversation` (`views.py:362-422`) resuelve el `HumanHandoff` y
gestiona el compromiso de identidad suspendido (`goals.close(parked, ...)` si
ya está verificado) — pero no lee ni escribe `flow['suspended']` ni
`flow['pending_action']` en ningún punto de la función. Confirmado con lectura
completa del código, no por inferencia del plan.

### 2.5 El nudge no depende de la liberación

`nudge_abandoned_flows` (`policy.py:398-440`) corre en cron sobre
`Conversation.objects.filter(state=STATE_ACTIVE, last_inbound_at__...)`. Su
disparador es `last_inbound_at` (último mensaje del **cliente**), no el
momento de `release_conversation`. Coincide con lo que ya corrigió la revisión
eng del plan (2026-08-07): si el hand-off duró 3 horas, el nudge puede saltar
segundos después de liberar. También respeta `flow.get('nudge_sent')` (una
vez por conversación) y `flow.get('deferred_at')` (promesa de "te aviso" no se
contradice).

### 2.6 Idempotencia existente — no uniforme entre los 4 tools

Verificado en los 4 `commit_*` handlers (`tools.py:845-1181`):

| tool | `idempotency_key` en `staged` | Se pasa al `executor.call` en el commit |
|---|---|---|
| `create_appointment` | sí (`tools.py:836`) | sí (`tools.py:853`) |
| `register_new_client_and_pet` | sí (`tools.py:1121`) | sí (`tools.py:1141`) |
| `cancel_appointment` | **no** | **no** |
| `reschedule_appointment` | **no** | **no** |

Los dos primeros son `POST` contra endpoints con `UniqueConstraint(org,
idempotency_key)` (ADR p52). Los dos últimos son `PATCH` sobre un
`appointment_public_id` ya conocido — su propia naturaleza (mutar un recurso
existente por PK) los hace idempotentes-de-facto en la mayoría de los casos,
pero **no hay protección explícita contra doble-ejecución concurrente**
(p.ej. nudge + respuesta del cliente llegando casi al mismo tiempo). Es una
brecha preexistente, fuera del alcance de Item 2 (no la introduce, no la
agrava) — se deja anotada en §9.

### 2.7 Boundary de arquitectura que ya respeta el plan

`agent/executor.py:1-21` documenta la decisión de arquitectura vigente: las
tools consumen la API DRF real por HTTP (loopback, JWT propio del agente),
**nunca ORM directo contra otros dominios**. Cualquier verificación contra el
dominio real en `release_conversation` tiene que usar el mismo canal
(`ToolExecutor` o un cliente equivalente), no importar `apps.appointments`
directamente — igual que hace cada tool hoy. El plan ya lo dice
correctamente; se confirma aquí porque es una regla dura de
`docs/system-operational-flow.md` §Reglas de boundary y de
`backend/CLAUDE.md`.

---

## 3. Propuesta — estado que se guardaría

El objeto que hoy vive en `flow['suspended']` (`{'kind', 'state'}`) es
insuficiente para auditar y para las validaciones de §4. Se propone
ampliarlo:

```python
flow['suspended'] = {
    'kind': 'pending_action',
    'state': flow['pending_action'],       # como hoy, tal cual — TC-SEC-03 intacto
    'suspended_at': timezone.now().isoformat(),   # NUEVO
    'handoff_reason': reason_code,                # NUEVO — trazabilidad
}
```

- **`suspended_at`**: necesario para decidir si vale la pena restaurar en
  absoluto (§9, decisión de producto sobre un tope duro de antigüedad) y para
  que los logs de `release_conversation` puedan reportar cuánto duró el
  hand-off sin tener que correlacionar con `HumanHandoff.created_at` a mano.
- **`handoff_reason`**: para que un log `AGENT_RELEASE_PENDING_RESTORED` (o
  `_DISCARDED`) sea autocontenido — hoy ese dato existe en el `HumanHandoff`
  resuelto en la misma función, así que es gratis incluirlo.

**Caso especial — `reschedule_appointment`**: el `staged` actual
(`tools.py:983-986`) solo guarda el destino (`appointment_public_id`, `date`,
`start_time`, `end_time`) — **no guarda el origen** (la fecha/hora que tenía
la cita al momento de proponer el cambio, aunque `reschedule_appointment` la
lee vía GET para armar el parafraseo, `tools.py:968-981`). Sin el origen, el
chequeo de dominio de §4 no puede distinguir "el humano ya la movió a donde
proponía el bot" de "el humano la movió a un tercer horario distinto" — ambos
casos hoy se ven igual (`GET` devuelve algo ≠ estado que el bot conocía). Se
propone añadir `'from_date'` / `'from_start_time'` al `staged` de
`reschedule_appointment` — cambio de una línea en `tools.py`, útil
específicamente para que Item 2 pueda implementarse con precisión en este
tool. Sin este dato, la validación de reschedule queda forzada a ser
conservadora (ver §4.3).

---

## 4. Validación contra el dominio real — por tipo de tool

Principio general (coincide con el plan): la llamada ocurre **una sola vez**,
dentro de `release_conversation`, vía el mismo canal HTTP loopback que usan
las tools (`ToolExecutor`, con el JWT del agente — no un cliente nuevo, no
ORM directo). Cualquier resultado que no sea una confirmación **exacta** de
resolución cuenta como "no resuelto" — sesgo deliberado hacia restaurar de
más, nunca hacia perder una propuesta real en silencio (mismo principio que
la falla segura de red que ya decidió el plan).

### 4.1 `create_appointment` — match exacto, alta confianza

`staged['pet']` es un PK de `Pet` ya existente (`tools.py:832`). Chequeo:
`GET /api/appointments/?date=<staged.date>&pet=<staged.pet>` (el endpoint ya
soporta ambos filtros — `appointments/views.py:51,73`, confirmado leyendo el
código, no solo el plan) y comparar `start_time` contra `staged.start_time`
sobre citas en estado activo (`scheduled`/`confirmed`/`in_progress`/`done` —
no `canceled`). Match exacto de pet+fecha+hora → **resuelto**, descartar en
silencio. Cualquier otra cosa (sin match, match parcial, varias citas ese
día) → no resuelto, restaurar.

### 4.2 `cancel_appointment` — match exacto, alta confianza

`staged['appointment_public_id']` referencia una cita real y específica.
Chequeo: `GET /api/appointments/<appointment_public_id>/` → si
`status == 'canceled'` → **resuelto** (alguien ya la canceló durante el
hand-off, por cualquier vía — recepción manual, otro canal). Si sigue
`scheduled`/`confirmed`/`in_progress` → no resuelto, restaurar. `done` es un
caso raro pero real (la cita ya se atendió durante el hand-off) — tratar como
resuelto: cancelar una consulta ya completada no tiene sentido y el dominio
lo rechazaría en el commit de todos modos (aunque preferible descartarlo
limpio aquí y no dejar que el cliente reciba un error de sistema).

### 4.3 `reschedule_appointment` — match exacto solo si se guarda el origen

Con `from_date`/`from_start_time` añadidos (§3): `GET
/api/appointments/<appointment_public_id>/` →

- Si `(date, start_time)` actuales == `(staged.date, staged.start_time)`
  (destino propuesto) → **resuelto**, alguien ya la movió exactamente ahí.
- Si `(date, start_time)` actuales == `(from_date, from_start_time)`
  (origen) y `status` sigue activo → **no resuelto**, nadie la tocó, restaurar.
- Si `(date, start_time)` actuales son un **tercer valor** distinto de ambos,
  o `status == 'canceled'` → un humano ya intervino esa cita de otra forma.
  Tratar como **resuelto** (descartar el reschedule del bot) — reofrecer un
  movimiento sobre una cita que un humano ya reubicó o canceló por su cuenta
  arriesga pelear contra una decisión humana reciente. Es una llamada de
  producto razonable por defecto, pero se anota en §9 porque hay lecturas
  opuestas válidas.

Sin `from_date`/`from_start_time` (si no se hace el cambio de §3), el único
chequeo seguro es el primer caso (match contra el destino propuesto); el
tercer caso no se puede distinguir del segundo y hay que tratar ambos como
"no resuelto" — funcionalmente correcto pero pierde la protección contra
pelear con una edición humana.

### 4.4 `register_new_client_and_pet` — sin PK estable, chequeo heurístico

Este es el caso genuinamente distinto de los otros tres: en el momento de
suspender, **ni el `Owner` ni el `Pet` existen todavía** — `staged` solo
tiene `owner_name`, `owner_phone`, `pet_name`, `pet_species`, fecha/hora
(`tools.py:1115-1122`). No hay un PK contra el cual preguntar "¿ya se
resolvió?" — hay que buscar por coincidencia.

`staged['owner_phone']` es el mismo teléfono que `commit_register_new_client_and_pet`
usa después para el auto-vínculo de identidad (`tools.py:1093`,
`_wa_id_to_local10`) — es la señal más confiable disponible. Chequeo
propuesto: `GET /api/owners/?search=<owner_phone>` (o el endpoint equivalente
de owners por teléfono) → si existe un `Owner` con ese teléfono exacto **y**
tiene una `Pet` con `name` case-insensitive-igual a `staged.pet_name` **y**
existe una cita para esa mascota en `staged.date`/`staged.start_time` →
**resuelto**.

Esto es deliberadamente estricto (match en las tres dimensiones: teléfono
exacto + nombre de mascota + fecha/hora exacta) porque una coincidencia
parcial equivocada aquí es el peor escenario posible: descartar en silencio
la ÚNICA vía de alta de un cliente que en realidad nunca se registró. Si
cualquiera de las tres señales no calza exactamente, tratar como no
resuelto y restaurar — el costo de restaurar de más es una repregunta
("¿seguimos con tu registro?"), tolerable; el costo de un falso positivo es
un cliente nuevo que nunca recibe su cita y no hay rastro del error. Esta
asimetría de costos es la razón por la que este tool, a diferencia de los
otros tres, merece una decisión de producto explícita (§9.1) antes de
implementarse tal cual.

---

## 5. Vencimiento (expiración)

El TTL actual (`PENDING_TTL = 30 minutos`, `confirmations.py:18`) se diseñó
para el ida-y-vuelta normal de una confirmación ("¿es correcto? — sí"), no
para sobrevivir un hand-off que puede durar minutos o hasta un día. Dos
decisiones distintas conviven aquí:

**5.1 — Al restaurar, el `pending_action` se marca como YA VENCIDO,
independientemente del tiempo real transcurrido.**

En vez de restaurar `flow['pending_action'] = flow['suspended']['state']` tal
cual (que preserva el `expires_at` original, posiblemente todavía vigente si
el hand-off fue corto), se propone sobrescribir `expires_at` con un valor ya
pasado antes de restaurar:

```python
state = flow['suspended']['state']
state['expires_at'] = (timezone.now() - timedelta(seconds=1)).isoformat()
flow['pending_action'] = state
```

Efecto: la primera vez que el cliente confirme (con lo que sea — un "sí"
suelto, o tras el nudge genérico), `_commit_pending` (`planner.py:607-619`)
entra por la rama de TTL vencido: **no ejecuta nada**, re-arma el pending con
un TTL fresco y envía `EXPIRED_REPARAPHRASE` ("Pasó un rato — te confirmo de
nuevo: {paraphrase}") — el cliente ve el contexto completo restated (mascota,
fecha, motivo) antes de que cualquier cosa se ejecute. Recién en el turno
siguiente, con una confirmación explícita sobre la propuesta re-mostrada, se
ejecuta el commit.

Esto es exactamente el mecanismo que la sección 7 necesita, y **no abre
ninguna ruta de envío nueva**: reutiliza `EXPIRED_REPARAPHRASE`, que ya existe
y ya se dispara desde `_commit_pending` sin intervención de este cambio. Sigue
cumpliendo la decisión eng #2 del plan ("sin envío inmediato al liberar") al
pie de la letra — el envío del re-parafraseo no ocurre en `release_conversation`,
ocurre en el turno normal cuando el cliente responde, como cualquier otro TTL
vencido del sistema hoy.

Es una desviación explícita del texto del plan ("restaurarlo tal cual"), que
se justifica en la §7.

**5.2 — Tope duro de antigüedad de la suspensión (decisión de producto, no de
arquitectura).**

Con `suspended_at` disponible (§3), es técnicamente trivial descartar sin
restaurar si `now - suspended_at` excede un umbral (24h, 48h — a definir). El
argumento a favor: una propuesta de cita para "mañana a las 9am" hecha hace
tres días ya no es una propuesta razonable aunque el dominio no la haya
"resuelto" en el sentido estricto de §4 — el cliente probablemente ya
resolvió su necesidad por otra vía sin que quede huella en el sistema, o
simplemente el contexto ya no aplica. El argumento en contra: es exactamente
el tipo de pérdida silenciosa que Item 2 busca eliminar, solo que ahora la
decide un timeout en vez de una escalada mal cerrada.

No se implementa por defecto en esta propuesta — el fail-safe correcto ante
la duda es restaurar, no descartar. Se deja como pregunta abierta en §9.2.

---

## 6. Qué ocurre ante conflicto

| Situación | Resultado propuesto | Por qué |
|---|---|---|
| Dominio confirma resuelto (match exacto §4.1/4.2/4.3) | Descartar `flow['suspended']` en silencio, sin mensaje | El cliente ya tiene lo que pidió; reofrecerlo sería ruido |
| Dominio confirma resuelto por heurística (§4.4, register) | Descartar solo si las 3 señales calzan exacto; si no, tratar como no resuelto | Asimetría de costo: falso positivo = cliente perdido sin rastro |
| Dominio dice no resuelto | Restaurar con TTL pre-vencido (§5.1) | Fuerza reconfirmación explícita antes de ejecutar nada |
| Chequeo de dominio falla/timeout | Restaurar (ya decidido en el plan; se confirma aquí) | Falla segura — peor caso es una re-oferta redundante |
| Match ambiguo/parcial (ninguna de las condiciones exactas de §4 se cumple limpio) | Tratar como no resuelto, restaurar | Mismo sesgo de fail-safe que el resto del diseño |
| El commit finalmente se ejecuta y el dominio rechaza (slot ocupado, fecha pasada, dato inválido) | Ya cubierto por `_commit_pending` (`planner.py:631-664`) — `slot_taken`, `past_date`, `invalid_data` | Cero código nuevo; el chequeo de disponibilidad y de fecha futura del dominio ya corre en cada `create_appointment`/`reschedule_appointment` |
| Dos escaladas consecutivas sin liberar en medio, con una propuesta NUEVA staged entre ambas | La segunda escalada pisa `flow['suspended']` con la propuesta nueva; la primera propuesta suspendida se pierde | `flow['suspended']` es un slot único, no una pila — limitación preexistente de `escalate_to_human` (`policy.py:362-364`), no introducida por Item 2. Solo se manifiesta si el modelo alcanza a proponer algo nuevo entre dos escaladas sin que medie un `release`, un caso operativamente raro (implica que el handoff nunca se resolvió antes de la segunda urgencia) |

---

## 7. Cómo impedir que un "sí" nuevo ejecute una confirmación antigua

Este es el riesgo central de Item 2 y merece razonarse aparte del resto.

**El riesgo no es solo el TTL.** Incluso si el chequeo de dominio de §4 dice
"no resuelto" correctamente, existe un escenario que ningún chequeo contra el
dominio puede cubrir: el humano resolvió la situación **fuera de banda**
(una llamada telefónica, algo dicho en persona) sin dejar huella en
`Appointment`/`Owner`/`Pet`. `release_conversation` restaura el
`pending_action` porque, desde el dominio, nada cambió. El cliente escribe
de vuelta — y su "sí" puede estar respondiendo a lo que el humano le dijo por
teléfono, no a la propuesta original del bot. Si el sistema ejecutara ese
"sí" directo contra el `pending_action` restaurado (como hace hoy con
cualquier "sí" sobre un pending vigente), ejecutaría una confirmación que el
cliente nunca dio para *esa* propuesta específica.

La mitigación de §5.1 (restaurar ya vencido) resuelve esto sin necesitar
detectar la resolución fuera de banda, que es indetectable por definición:
**ningún "sí" ejecuta nada directamente después de un release**. El primer
"sí" (o cualquier mensaje) tras la restauración siempre cae en la rama de TTL
vencido de `_commit_pending`, que:

1. No ejecuta nada.
2. Le muestra al cliente el parafraseo completo de nuevo (mascota, fecha,
   motivo) — no un "¿confirmas?" desnudo que dependa de que el cliente
   recuerde de qué se trataba.
3. Solo tras un segundo "sí", ahora sobre una propuesta que el cliente
   **acaba de ver en el mismo intercambio**, se ejecuta el commit.

Esto convierte "impedir que un sí viejo ejecute algo" en "nunca hay un sí
viejo que pueda ejecutar algo" — no hace falta distinguir semánticamente un
"sí" legítimo de uno fuera de contexto, porque estructuralmente ningún "sí"
inmediatamente posterior a un release dispara una ejecución. Es el mismo
patrón que ya usa el sistema para el caso "pasaron 30 minutos" — Item 2 solo
lo activa también para "pasó un hand-off", sin escribir un mecanismo nuevo.

El `flow.pop('nudge_sent', None)` que ya especifica el plan sigue siendo
necesario y compatible con esto: el nudge (`NUDGE_TEXT`, genérico, no es el
parafraseo) puede volver a dispararse si el cliente no escribe primero; el
`pending_action` que ese nudge referencia sigue pre-vencido, así que aunque
el cliente responda directamente al nudge con un "sí", cae en la misma rama
de re-confirmación explícita.

---

## 8. Qué NO hace falta tocar (reafirmado independientemente)

Verificado contra el código, no solo contra el texto del plan:

- **Revalidación de disponibilidad en `release_conversation`**: innecesaria.
  `_commit_pending` ya delega el conflicto de horario al dominio
  (`map_domain_400` → `slot_taken`, `planner.py:632-639`) en el momento del
  commit real, que es cuando importa.
- **Validación de fecha futura en `release_conversation`**: innecesaria por
  el mismo motivo — el dominio ya rechaza fechas pasadas en creación y en
  update (ADR p52, cambio colateral), y `_commit_pending` ya tiene la rama
  `past_date` (`planner.py:640-646`) para traducirlo a un mensaje amigable.
  Esto refuerza, no solo repite, la decisión DRY del plan: ambas
  validaciones de negocio (slot y fecha) que importarían al restaurar ya
  están cubiertas en el punto de commit, no hace falta duplicar ninguna.
- **Envío síncrono / re-ofrecimiento dentro del endpoint de liberar**:
  innecesario y ahora además contraindicado por §5.1 — no hay nada que
  ofrecer sincrónicamente si el primer contacto tras el release siempre pasa
  por el re-parafraseo asíncrono existente.
- **`nudge_abandoned_flows`**: se reusa sin cambios; solo depende de que
  `flow.pop('nudge_sent', None)` se ejecute al restaurar (ya en el plan).

---

## 9. Decisiones que aún requieren producto

**9.1 — Política de descarte heurístico para `register_new_client_and_pet`
(§4.4).** ¿Se acepta el chequeo de tres señales (teléfono + nombre de
mascota + fecha/hora exactos) como suficientemente seguro para descartar en
silencio, o se prefiere que este tool **nunca** se descarte automáticamente
(siempre restaurar, dejando que el propio flujo del tool —que ya rechaza con
`already_client` si el contacto quedó vinculado mientras tanto,
`tools.py:1074-1075`— absorba el caso "ya se registró")? Esta segunda opción
es más simple y elimina el riesgo de falso positivo por completo, al costo
de una repregunta ocasional a alguien que ya se registró por otra vía.

**9.2 — Tope duro de antigüedad de la suspensión (§5.2).** ¿Existe un umbral
de horas más allá del cual `release_conversation` debería descartar el
`pending_action` sin restaurarlo, asumiendo que el contexto ya caducó
independientemente de lo que diga el chequeo de dominio? Si sí, ¿cuánto
(24h, alineado con `NUDGE_WINDOW`/`close_inactive_conversations`; 48h; otro)?

**9.3 — `reschedule_appointment` cuando el humano movió la cita a un tercer
horario (§4.3, tercer caso).** ¿Tratar como resuelto/superado (no pelear con
la decisión del humano, que es lo que propone este documento) o como no
resuelto (el bot debería seguir intentando cumplir el pedido original del
cliente, aunque el humano haya hecho algo distinto mientras tanto)?

**9.4 — Visibilidad del `pending_action` suspendido en `/inbox` durante el
hand-off.** Hoy el staff que atiende una conversación escalada no ve en la UI
que hay una propuesta de cita congelada esperando. Si el chequeo automático
de §4 tiene margen de error conocido (particularmente 9.1), ¿vale la pena
exponerlo en el panel de conversación para que el staff pueda resolverlo
explícitamente antes de liberar (p.ej. un botón "descartar propuesta
pendiente"), en vez de depender solo de la heurística? Esto es trabajo de
frontend + un endpoint nuevo — fuera del alcance de Item 2 tal como está
planteado, pero relevante para decidir cuánto peso poner en la heurística
automática versus dar control manual.

**9.5 — Notificación proactiva cuando se descarta por "ya resuelto".** El
plan (y este documento) asumen descarte silencioso. ¿Confirma producto que
nunca hace falta un mensaje tipo "veo que tu cita ya quedó agendada ✅" al
descartar, incluso para dar cierre explícito al cliente? (El cliente puede
igualmente preguntar "¿ya quedó mi cita?" en cualquier momento y el bot
responde con `list_upcoming_appointments`, así que la información no se
pierde — es una cuestión de proactividad, no de disponibilidad del dato.)

---

## 10. Riesgos residuales aceptados (no se eliminan con este diseño)

- **Resolución fuera de banda sin huella en el dominio** (llamada
  telefónica, conversación en persona): ningún chequeo contra
  `Appointment`/`Owner`/`Pet` puede detectarla. Mitigado, no eliminado, por
  §7 (el "sí" nunca ejecuta directo tras un release) y potencialmente por
  9.4 (visibilidad manual para el staff).
- **`flow['suspended']` como slot único** (§6, última fila): una segunda
  escalada con una propuesta nueva de por medio pisa la anterior. Preexistente
  a Item 2, no lo agrava, pero tampoco lo arregla.
- **Falta de `idempotency_key` en los commits de `cancel_appointment` y
  `reschedule_appointment`** (§2.6): no introducido por Item 2, pero relevante
  porque una restauración + reconfirmación aumenta el número de turnos en los
  que un commit de este tipo puede dispararse (nudge + respuesta casi
  simultánea, doble mensaje del cliente). Vale la pena una entrada en
  `TODOS.md` si no la tiene ya — no se resuelve aquí porque está fuera del
  alcance de "retomar la propuesta pendiente" y tocaría `tools.py` en
  funciones que Item 2 no toca.

---

## 11. Referencias (archivo:línea, verificadas por lectura directa)

- `agent/confirmations.py:18,39-52,55-56,59-69,72-75` — `stage_pending`,
  `PENDING_TTL`, `is_expired`, `clear_pending`.
- `agent/policy.py:179-199` — confirmación de `pending_action` (paso 7).
- `agent/policy.py:352-364` — suspensión en `escalate_to_human`.
- `agent/policy.py:398-440` — `nudge_abandoned_flows`.
- `agent/views.py:362-422` — `release_conversation` actual, sin manejo de
  `pending_action`.
- `agent/planner.py:303-311` — intercepción de `confirm=affirmative` antes
  del LLM.
- `agent/planner.py:601-628` — `_commit_pending`, rama TTL vencido vs. commit.
- `agent/planner.py:631-664` — manejo de `slot_taken`/`past_date`/`invalid_data`.
- `agent/tools.py:783-843,845-866` — `create_appointment` / `commit_create_appointment`.
- `agent/tools.py:888-943` — `cancel_appointment` / `commit_cancel_appointment`.
- `agent/tools.py:946-1010` — `reschedule_appointment` / `commit_reschedule_appointment`.
- `agent/tools.py:1063-1181` — `register_new_client_and_pet` / `commit_register_new_client_and_pet`.
- `agent/tools.py:1185-1190` — `COMMIT_HANDLERS`.
- `agent/executor.py:1-21,43-171` — boundary HTTP loopback, `ToolExecutor`.
- `appointments/views.py:51,73` — filtros `?date=` y `pet=` ya existentes.
- `docs/system-module-operations.md` §3 — bloqueo de conflicto de horario en
  `create_appointment` (dominio).
- `docs/decisions/2026-07-19-p52-appointment-idempotency.md` — idempotencia
  de creación de citas y guard de fecha pasada en update.
- `docs/whatsapp-agent-identity-context-fixes-plan.md` §Item 2 — diseño
  original y decisiones de la revisión eng (2026-08-07), punto de partida de
  este análisis.
