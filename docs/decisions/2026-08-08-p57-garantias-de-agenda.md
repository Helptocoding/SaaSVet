# ADR p57 — Garantías de agenda e identidad: precondición atómica (INV-A), no-solapamiento (INV-D) e identidad de expediente (INV-B/INV-C)

**Fecha**: 2026-08-08 (rev. 2026-08-11 — F1 añade INV-B e INV-C)
**Estado**: ACEPTADO. F0–F4 implementadas y **INV-A cerrado**: la precondición
de estado es **obligatoria** para toda mutación de cita (`400
precondition_required`), en las cuatro vías de §3.3. Lo único que resta de la
Fase 3 es la **retirada** de `DELETE /appointments/<id>/` a `410
endpoint_sunset`, que no puede adelantarse al Sunset publicado a los clientes
(**2026-11-06**, RFC 8594). Mientras tanto ese endpoint sigue vivo pero **ya no
exento**: también exige la precondición, para que la vía deprecada no sea la
puerta trasera del gate.
**Decisión de origen**: [`item-2-decision.md`](item-2-decision.md) §3.2, §3.3,
§3.4, §4.7–§4.12, §5.1, §9.14, §9.15. Plan de ejecución:
[`item-2-implementation-plan.md`](item-2-implementation-plan.md) §3 (F0) y §4 (F1).
**Alcance de este ADR**: F0 (agenda), F1 (identidad de expediente por
teléfono) y F4 (FLUJO-C, verificación humana). F2 y F3 son consumo de estas
garantías por parte del agente y no cambian el contrato del dominio.

---

## Contexto

Dos escrituras de agenda podían pisarse sin que el dominio se enterara.

**1. Nadie declaraba lo que esperaba encontrar.** `PATCH /appointments/<id>/`,
`PATCH /<id>/status/`, `DELETE /<id>/` y `assign-patient` mutaban la cita sin
lock de fila y sin comparar contra el estado que el llamador había visto. Dos
actores sobre la misma cita = último escritor gana, en silencio. Con el agente
de WhatsApp escribiendo en paralelo con recepción, eso deja de ser teórico: el
cliente confirma «muévela al martes», mientras tanto el staff la cancela, y el
agente la reagenda igual — resucitando una cita que alguien decidió cancelar.

**2. La disponibilidad era un mensaje, no una garantía.** El cupo se decidía con
`conflicts.exists()` en `AppointmentSerializer.validate` y se escribía después.
Dos creaciones (o dos reprogramaciones) podían validar a la vez el mismo
veterinario y el mismo intervalo y **ambas persistir**. Y dos caminos ni
siquiera pasaban por esa validación: la **atención sin cita** (`walk-in`, que
crea directo en `in_progress`) y la **reactivación** `canceled|no_show →
scheduled` vía `/status/`.

---

## Decisión

### INV-A — La precondición atómica de estado

Toda mutación sobre una cita existente acepta `expected_state`: la tupla
semántica vigente cuando se decidió mutar.

```
expected_state = { "status": ..., "date": "YYYY-MM-DD", "start_time": "HH:MM" }
```

El dominio la compara contra la fila **bloqueada con `select_for_update()`**,
dentro de la **misma transacción que escribe**. Si difiere:

```json
{ "code": "appointment_changed",
  "message": "La cita cambió desde que se propuso.",
  "current": { "status": "confirmed", "date": "2026-08-13", "start_time": "16:00" } }
```

Cuatro propiedades que la hacen una garantía y no una decoración:

1. **El campo va DECLARADO en `AppointmentSerializer`.** DRF descarta en
   silencio las claves desconocidas: un `expected_state` no declarado se
   perdería y el `PATCH` pasaría **incondicionalmente**. Es un fail-open
   perfecto e invisible, y tiene prueba propia (P0-4).
2. **La comparación va bajo lock.** Fuera de la transacción que escribe sería
   una lectura optimista, no compare-and-swap (P1-14 lo prueba con dos
   conexiones reales).
3. **Es capacidad del DOMINIO, no del agente.** Cualquier actor autenticado que
   la envíe recibe el mismo 409 (P0-7).
4. **El 409 no es un error técnico.** Es un resultado de negocio: el mundo
   cambió. No es 5xx, no es `tool_failure`, no genera hand-off por avería.

**Obligatoria desde la Fase 3** (2026-08-13). Omitir `expected_state` en una
mutación de cita es `400 precondition_required` y cero escrituras, en las
cuatro vías de §3.3 — incluido el `DELETE` deprecado, para que la vía en
sunset no sea la puerta trasera del gate.

Fue opt-in mientras duró el rollout (P2-4, la regresión que blindaba «sin
`expected_state`, nada cambia»), y ese contrato queda **sustituido**: era del
rollout, no del diseño. Mientras la precondición fue opcional, la garantía
dependía de que cada llamador se acordara — y el que se olvida nunca es el que
ya existe, sino el que se escribe con prisa.

Que esa dependencia era real lo demostró el propio gate al activarse: encontró
**dos** llamadores que escribían a ciegas y que nadie había advertido —
`confirm_appointment` del agente (confirmaba una cita sin comprobar si alguien
acababa de cancelarla, mientras `cancel`/`reschedule` sí lo hacían) y el botón
«▶ Atender ahora» del frontend. Ninguno de los dos habría fallado nunca: solo
habrían sobrescrito en silencio.

Una precondición **mal formada** (no es objeto, claves faltantes o
desconocidas, estado inexistente, fecha u hora no parseables) es `400
validation_error`. Aceptar una tupla que no se puede comparar sería el mismo
fail-open del punto 1. Enviarla a cualquiera de las **tres** vías de creación
también es `400`: no hay estado previo que comparar. Las tres, no solo la
obvia — `create-with-patient` y `walk-in` arman su payload a mano, así que sin
un rechazo explícito el campo se perdía sin ruido.

**Ausencia de la clave ≠ `null` explícito.** Desde la Fase 3 ambas fallan, pero
con `code` distinto y a propósito: la ausencia es `precondition_required` (no
sabía que hacía falta) y `expected_state: null` es `validation_error` (la mandó
mal), con cero escrituras en las siete vías. El motivo es el mismo fail-closed
del punto 1:
quien manda `null` cree que está mandando una precondición, y si el dominio lo
lee como «no vino», la escritura pasa **sin comparar nada** — con la etiqueta
de estar protegida. Los dos casos no pueden compartir representación, así que
el dominio los distingue con un centinela (`MISSING`) en vez de con `None`:
`data.get(campo)` devuelve `None` para ambos y era exactamente ahí donde se
perdía la diferencia. Aplica igual a JSON, form-data y `QueryDict` — en
form-data la clave presente llega como cadena y se rechaza por forma, así que
ninguna codificación sirve de puerta trasera.

#### Matriz de mutaciones (no hay categoría implícita)

| Mutación | Lock de fila | `expected_state` | INV-D |
|---|---|---|---|
| `PATCH /api/appointments/<public_id>/` | sí | acepta | sí |
| `PATCH /api/appointments/<public_id>/status/` | sí | acepta | sí (reactivación) |
| `DELETE /api/appointments/<public_id>/` | sí | acepta | n/a (solo cancela) |
| `PATCH /api/appointments/<public_id>/assign-patient/` | sí | acepta | **no** |
| `POST /api/appointments/` | n/a (crea) | **rechaza (400)** | sí |
| `POST /api/appointments/create-with-patient/` | n/a (crea) | **rechaza (400)** | sí |
| `POST /api/appointments/walk-in/` | n/a (crea) | **rechaza (400)** | **sí** (§9.14) |
| `services.complete_appointment_on_record_close` | no | **no** | no |

`assign-patient` **entra** aunque no mueva la tupla de agenda: muta la cita y
escribe `AppointmentStatusChange`, así que sin lock competiría con un `PATCH`
condicionado y ganaría el último. Queda fuera de INV-D porque no toca
`veterinarian`, `date`, `start_time` ni `end_time`.

`complete_appointment_on_record_close` queda **excluida con justificación**: no
es un llamador externo con una expectativa que declarar, sino una transición
interna `in_progress → done` que **ya falla cerrada** (UPDATE condicional que no
aplica si el estado cambió) y que evita a propósito un orden de locks
`Appointment↔MedicalRecord` que generaría ABBA con `assign-patient`.

**Regla derivada, binding**: ninguna vía nueva puede mutar una cita sin lock de
fila. Si aparece una, entra en esta matriz **antes** de mergear.

#### `DELETE` entra al contrato **y** queda deprecado

`DELETE /api/appointments/<id>/` cancela la cita y escribe auditoría, así que
mientras exista no puede ser una vía último-escritor-gana ni producir una
segunda `AppointmentStatusChange` bajo conflicto (P1-23). Pero una segunda vía
de cancelación con su propia semántica es deuda: emite `Deprecation`/`Sunset`
(RFC 8594, Sunset **2026-11-06**) + el log `DEPRECATED_ENDPOINT_HIT` que el
proyecto ya usa, con `PATCH /<id>/status/` como sucesor. La retirada
(`410 endpoint_sunset`) y el corte del consumidor en el frontend son F5.

#### `appointments.services.create_appointment` se retira

Helper legacy sin llamadores de producción y roto de hecho (filtraba por un
campo `datetime` que el modelo ya no tiene), pero conservaba el patrón
`exists()` + `create()` que INV-D prohíbe. Dejarlo vivo era dejar una vía
read-then-write lista para reutilizarse por error.

### INV-D — El no-solapamiento lo garantiza PostgreSQL

Restricción de exclusión sobre la tabla de citas:

| Elemento | Contenido |
|---|---|
| Clave de igualdad | `organization_id`, `veterinarian_id` |
| Clave de solape | `tstzrange(start_datetime, end_datetime, '[)')` con `&&` |
| Predicado parcial | estados **activos** (`scheduled`, `confirmed`, `in_progress`), `veterinarian` no nulo, instantes no nulos |
| Requisito | extensión `btree_gist` (los componentes de igualdad no son indexables por GiST sin ella), creada en `appointments/0014` |
| Nombre | `appointment_no_overlap_per_vet` |

Vive en la **tabla**, no en un endpoint: cubre creación, reprogramación,
atención sin cita y reactivación, y a cualquier actor presente o futuro
(frontend, importador, script de soporte, integración), sin rollout por fases.

Intervalo **semiabierto** `[inicio, fin)`: 10:00–10:30 y 10:30–11:00 son
contiguas, no solapadas — el mismo criterio del pre-chequeo del serializer, para
que la garantía y el mensaje legible no puedan discrepar.

Fuera del predicado, a propósito: `done`/`canceled`/`no_show` (una cita
cancelada no bloquea el hueco — regla de negocio vigente) y las citas **sin
veterinario** (no hay recurso que reservar).

**`is_active` NO entra en el predicado** (así lo fija §3.4: el predicado es de
*estado*, no de soft delete). Una restricción de la base no sabe nada del
soft delete que aplica `TenantManager`, así que cubre todas las filas de la
tabla. Dos consecuencias que conviene tener escritas:

- El comando de auditoría **tampoco** filtra `is_active`, a propósito: tiene que
  mirar exactamente lo mismo que mira PostgreSQL, o podría reportar «limpio» y
  la migración fallar igual.
- Una cita soft-deleted en estado activo ocuparía el hueco siendo invisible para
  el ORM y para el pre-chequeo → un `slot_taken` sin cita visible detrás. **Hoy
  es inalcanzable**: nada soft-deletea citas (`Appointment` no está registrado
  en el admin de Django y cancelar escribe `status`, no `is_active`). Queda
  anotado porque el día que alguien registre `Appointment` en el admin, o escriba
  un script de limpieza, el síntoma sería desconcertante y la causa no obvia.

#### Contrato de error: compatibilidad deliberada

El pre-chequeo del serializer **se conserva**. Lo que cambia es que perder la
carrera ya no significa escribir.

| Camino | Respuesta |
|---|---|
| El pre-chequeo detecta el solape | `400` con el mensaje de siempre **+ `code: 'slot_taken'`** |
| La restricción de la base rechaza (perdió la carrera) | **el mismo `400 slot_taken`** |
| Cualquier otro error de integridad | se propaga |

El llamador no puede —ni debe— distinguir «ya estaba ocupado» de «lo ocuparon
hace 3 ms»: la acción a tomar es idéntica. El cuerpo es un **superset** del que
este caso devolvía antes (`errors: {error: [...]}`), así que `map_domain_400`
del agente y `apiError` del frontend siguen encontrando el mensaje.

Se descartó `409` para el solape: el `409` de este Item está reservado a
**precondiciones vencidas**, donde el cliente debe releer y volver a decidir. Un
horario ocupado es una validación del payload propuesto, y ya tiene un contrato
en producción que funciona.

La violación se traduce **por nombre de restricción**, nunca capturando
`IntegrityError` a ciegas — capturar todo convertiría un bug en un `slot_taken`
mentiroso. Llega por **dos** caminos y los dos se traducen:

1. `ValidationError` de modelo (`full_clean()` → `ExclusionConstraint.validate()`,
   un pre-chequeo más).
2. `IntegrityError` de la base — la garantía, la única que cubre la carrera.

### La garantía tiene dos piezas: exclusión **más** serialización preventiva

Medir la carrera real destapó un tercer desenlace que no estaba previsto: dos
`INSERT` simultáneos sobre el mismo hueco **se esperan mutuamente** mientras
PostgreSQL comprueba la exclusión, y el motor rompe el ciclo abortando a uno con
`OperationalError` **SQLSTATE `40P01`** (`deadlock detected`,
`CONTEXT: while checking exclusion constraint`). El perdedor recibía un
`500 server_error` en vez de `slot_taken`: contención de negocio normal
disfrazada de avería, con su alerta de Sentry por cada vez, justo en el
escenario para el que existe INV-D.

**Un `40P01` NO se traduce a `slot_taken`, y esa es la decisión.** Un deadlock
dice «PostgreSQL rompió un ciclo de esperas», no «el hueco está ocupado»: no
prueba nada sobre el cupo. Se intentó traducirlo re-consultando el hueco tras el
rollback y la idea era falsa por diseño — el re-chequeo puede correr **antes**
de que el competidor confirme (y ver el hueco libre) o después de que lo
cancele. Medido: con esa traducción, la suite en paralelo seguía devolviendo
500 en ~1 de cada 10 corridas.

La solución es **prevenir el deadlock, no interpretarlo**: toda escritura que
pueda entrar o salir del predicado de INV-D toma antes un
`select_for_update()` sobre la fila del **veterinario**
(`services.lock_veterinarians`). Con la agenda serializada por veterinario, el
segundo escritor entra cuando el primero ya confirmó, su pre-chequeo ve el hueco
ocupado y responde `slot_taken` por la vía normal. La restricción sigue siendo
la garantía; el lock solo evita que se cobre en forma de avería.

- **Dos veterinarios en juego** (un `PATCH` que reasigna la cita): se bloquean
  **ambos, en orden de PK**. Dos peticiones cruzadas (A→B y B→A) los pedirían en
  orden opuesto y volverían a hacer ABBA; ordenando por PK, la segunda espera.
  Se bloquea de uno en uno y explícitamente: un `filter(pk__in=…)` delega el
  orden al plan de ejecución, que no es un contrato.
- **Si un `40P01` reaparece, sale como error visible.** Es la señal de que la
  prevención tiene un agujero, y disfrazarla de resultado de negocio la
  volvería indiagnosticable.

**Orden global de locks**: `User (veterinario) → Appointment → MedicalRecord`.
El lock de `Appointment` se mantiene donde protege `expected_state` (INV-A); lo
que cambia es que el del veterinario va **antes**, y ninguna vía lo invierte.
`assign-patient` queda fuera de la serialización porque solo cambia `pet`: no
toca veterinario, fecha, horas ni estado, así que no puede entrar ni salir del
predicado — hay prueba que lo comprueba campo por campo, no es una afirmación.
`complete_appointment_on_record_close` también queda fuera: `in_progress → done`
solo **saca** la cita del índice parcial y sigue usando su UPDATE condicional
para no invertir el orden con el lock del `MedicalRecord`.

#### Los dos comportamientos que cambian el día 1 (aprobados)

| Camino | Antes | Con INV-D | Qué hace el usuario |
|---|---|---|---|
| **Atención sin cita** con el veterinario ocupado | creaba en `in_progress` sin comprobar solapes | `400 slot_taken`; **cero** citas creadas | escoge alternativa: otro veterinario u otro horario |
| **Reactivación** `canceled\|no_show → scheduled` sobre hueco ocupado | no validaba cupo: resucitaba sobre un hueco reasignado | `400 slot_taken`; la cita sigue en su estado terminal | programar de nuevo |

Reglas que acompañan a esa aprobación:

- **No hay bandera de forzado.** Ni `force`, ni `allow_overlap`, ni un permiso
  que lo salte. Un invariante con puerta trasera es un aviso. Hay prueba que lo
  ancla (P0-20).
- **Nada se desplaza automáticamente.** La reactivación no reubica ninguna cita:
  rechaza y pide una decisión.
- **Espera, sobrecupo y múltiples recursos** (dos consultorios, agendas
  paralelas) son **feature separada** con su propio diseño y ADR, no una
  extensión de este.

#### Secuencia de despliegue (no negociable)

PostgreSQL **no** admite añadir una restricción de exclusión `NOT VALID`: si
existe un solape previo, la migración **falla**. Es el comportamiento correcto
(fail-closed) y por eso:

1. `python manage.py audit_appointment_overlaps` en **cada** entorno, incluida
   producción. Lista por organización los pares solapados con su `public_id`.
   Exit 0 limpio / 1 con hallazgos / 2 error — patrón `audit_stock_integrity`.
2. **Remediación humana** por clínica. No se corrige solo: cancelar o mover una
   cita real sin que nadie lo decida es peor que el solape.
3. Aplicar `appointments/0014` en ventana de deploy — construir el índice GiST
   toma un lock fuerte de la tabla (segundos con el volumen del piloto).
4. Volver a correr la auditoría post-deploy.

Correr la auditoría el **mismo día** del deploy, no una semana antes: una cita
creada en medio hace fallar la migración. El comando **queda** en el repositorio
como red de seguridad permanente.

**Tarea de comunicación previa al deploy**: avisar a recepción de los dos
comportamientos nuevos y del gesto siguiente (escoger otro veterinario u otro
horario; programar de nuevo). El primer rechazo en mostrador no puede ser la
forma en que se enteran.

---

## Consecuencias

**A favor**

- Ninguna cita se sobrescribe a ciegas cuando el llamador declara qué esperaba.
- El cupo pasa de mensaje a garantía, para todos los actores a la vez y sin
  rollout por fases.
- Los dos agujeros históricos (atención sin cita y reactivación) quedan
  cerrados.
- `assign-patient` deja de ser un 500 permanente: `for_organization` encadenado
  **después** de `select_related()` lanzaba `AttributeError` en cada llamada
  (bug preexistente encontrado al escribir P0-7).

**En contra / aceptado**

- Envolver `update()` en una transacción con lock cambia el perfil de
  concurrencia de un endpoint que usa el frontend. El lock es de una fila y dura
  lo que el request.
- La migración falla si la limpieza quedó incompleta (fail-closed deliberado).
- Los solapes históricos bloquean el deploy hasta que cada clínica los ordene.
- INV-A no es universal hasta F5: entre sí, dos escrituras del frontend siguen
  en último-escritor-gana.
- El cuerpo de error de dominio se compone con un `error_payload` opcional en
  `custom_exception_handler` (mismo espíritu que el 409 de `ProtectedError`, que
  ya devuelve `protected_count`/`protected_sample`).
- **El lock de `Appointment` pasa a ser explícito**, así que el orden de locks
  del proyecto tiene que nombrarlo: `Appointment` precede a `MedicalRecord`
  (`assign-patient` y `/status/ → done` lo tocan en ese orden). El único camino
  inverso es `complete_appointment_on_record_close`, que corre con el lock del
  `MedicalRecord` tomado y usa un UPDATE condicional precisamente para no
  invertirlo. Ese UPDATE toma igualmente el row lock implícito, así que la
  ventana cruzada `assign-patient` ↔ `close_medical_record` sobre el mismo par
  existe: es **preexistente** (antes el lock se adquiría en el `save()` en vez
  de al abrir la transacción, unos milisegundos después), exige vincular
  paciente y cerrar consulta en el mismo instante, y PostgreSQL la resuelve
  abortando una de las dos. Queda declarada, no resuelta: ponerle
  `select_for_update` a `complete_appointment_on_record_close` la convertiría en
  un ABBA garantizado en vez de una carrera improbable.

---

## INV-B / INV-C — La identidad de expediente por teléfono (F1)

### Contexto

La misma pregunta tenía cuatro respuestas distintas.

**1. Cada vía deduplicaba a su manera.** `create-with-patient` resolvía por
teléfono; `POST /api/pets/` por `(nombre, teléfono)` —una segunda regla de
identidad, propia y no documentada—; el importador tomaba `.first()` sobre los
duplicados; y `POST /api/owners/` no deduplicaba en absoluto. Ninguna tomaba un
lock: dos altas concurrentes del mismo número creaban dos expedientes, porque
nada en la base lo impedía.

**2. `POST /api/pets/` fabricaba los duplicados que el sistema debía tratar como
ambiguos.** Si el teléfono coincidía pero el nombre no ("Ana López" vs "Ana
Lopez"), creaba un **segundo** `Owner` con el mismo número. Y si coincidían
ambos, colgaba la mascota nueva de ese expediente: un vínculo de identidad
decidido por coincidencia de cadena.

**3. Cambiar el teléfono no era una operación de identidad.** `PATCH
/api/owners/` y la escritura anidada de `PATCH /api/pets/` movían la clave sin
lock ni comprobación — y la segunda, desde una pantalla que parece de mascota.

**4. Leer también era decidir, y ahí estaba el bypass.** Los dos lectores de
identidad del agente comparaban un valor **normalizado** (el del `wa_id`) contra
`Owner.phone` **en crudo**. Un expediente guardado como `"55 1234 5678"` y otro
como `"5512345678"` son la misma clave, pero la igualdad cruda solo encontraba
el segundo: el lector veía **una** coincidencia donde hay **dos** y vinculaba el
contacto a esa fila. Una elección automática entre duplicados históricos, por
una puerta que un inventario de escrituras no mira.

### Decisión

> **INV-B — El teléfono localiza, no autoriza.** Cualquier modificación sobre un
> `Owner` existente requiere identidad verificada por el mecanismo que
> corresponda al actor. Si no está verificada, el flujo escala a humano o
> rechaza la operación de forma segura.

> **INV-C — Un teléfono normalizado identifica como máximo un expediente dentro
> de una organización.** Con dos o más: `owner_ambiguous` y escalada. El sistema
> **nunca** fusiona registros ni elige uno automáticamente.

**Un servicio único** (`apps/patients/services.py`) con tres operaciones que
comparten normalización, conteo, exclusión del genérico y desenlaces: resolver
para escribir (con lock), **cambiar el teléfono** (dos claves en orden total) y
**modo lectura** (sin lock, sin escribir). Separarlas volvería a producir dos
verdades, que es justo lo que la revisión encontró.

**El teléfono normalizado, persistido.** `Owner.phone_normalized` (10 dígitos o
`NULL`) lo deriva **siempre** el dominio en `Owner.save()`, nunca el cliente.
Es la **clave de lectura y de escritura**: toda comparación va normalizado ↔
normalizado. `ContactIdentity.phone_normalized` ya existía desde el día 1; lo que
faltaba era el lado del expediente.

**Cuatro desenlaces exhaustivos**, sin rama que elija:

| Expedientes con la clave | `require_new` | `match_name` | Resultado |
|---|---|---|---|
| sin clave | — | — | `created` |
| 0 | cualquiera | — | `created` |
| 1 | `False` | coincide o `False` | `reused` |
| 1 | `False` | distinto | `409 owner_exists` **con el candidato** |
| 1 | `True` | — | `409 owner_exists` |
| ≥ 2 | cualquiera | — | `409 owner_ambiguous`, cero escrituras |

`owner_ambiguous` **no es opt-in**: aplica también a recepción y al importador.

### Un lock de aviso, no una restricción única

`UNIQUE (organization, phone)` está **descartada, no aplazada**: aplicarla
exigiría limpiar o fusionar los duplicados históricos, y INV-C prohíbe
exactamente eso. Crearla «solo para filas nuevas» exigiría un estado implícito
—qué fila está dentro del índice y cuál no— que nadie podría razonar seis meses
después.

El lock de aviso a nivel de **transacción** sobre `(organización, clave)` cubre
además lo que un lock de fila no puede cubrir: **la fila todavía no existe**. Se
libera con el commit o el rollback; no hay que acordarse de soltarlo.

Dos guardas, ambas ruidosas y ambas deliberadas: es **PostgreSQL-only** (en otro
motor lanza en vez de devolver «adquirido», porque un no-op aquí convierte la
garantía en decoración) y **exige transacción abierta** (en autocommit
`pg_advisory_xact_lock` toma y suelta el lock dentro de su propia sentencia: el
llamador cree estar serializado y no lo está — el mismo fail-open con otra cara).

No altera el orden global de locks: precede a cualquier lock de fila del alta.
En el **cambio de teléfono** se bloquean las dos claves en **orden total** por su
valor normalizado; sin ese orden, dos cambios cruzados (A→B y B→A) se abortan
por deadlock.

### El inventario cerrado por familias

El fallo de la primera versión fue **de método**: enumeraba tres caminos y
añadía «cualquier vía futura». No bastaba — dos vías *actuales* eludían el
servicio. La cobertura de una garantía vale lo que valga su camino más débil.

Toda vía **usa el servicio** o queda **excluida con evidencia** de que no puede
alterar identidad. La tabla vive en
[`modules/patients.md`](../modules/patients.md) como contrato del módulo, y una
prueba estática enumera cada sitio que construye un `Owner` y falla si aparece
uno sin clasificar. Regla de proceso: una vía nueva entra en la tabla **antes de
mergear**.

**El registro rápido cierra la familia A1·B2.**
`POST /api/appointments/create-with-patient/` resuelve el expediente con el
servicio, bajo el lock, dentro de la misma transacción que crea la cita, y gana
`require_new_owner` (opt-in, default `false`) como aplicación de INV-B. El lock
de aviso se toma **antes** del lock de fila del veterinario, según el orden
global; no introduce un ABBA porque ninguna otra vía toma ambos recursos.

`require_new_owner` se parsea **fail-closed**: solo `true`/`false`, cualquier
otro valor es `400`. Aceptar `"yes"` o `1` como «falso» relajaría la protección
justo para el llamador que la pide —quien no tiene identidad verificada— y el
fallo sería invisible: la mascota quedaría colgada de un expediente ajeno sin
que nadie viera un error.

### El `Owner` genérico

`phone_normalized = NULL` **siempre** (nunca `''` ni `'0000000000'`), backfill
incluido. `NULL` es la representación de «no tiene clave de cliente» y lo deja
fuera de todo índice parcial y de toda comparación por igualdad sin que haya que
recordarlo en cada consulta. Excluido de conteo, locks, búsqueda de identidad y
de los lectores del agente. **El teléfono del `Owner` genérico nunca es
identidad.**

### Duplicados históricos: se ven, no se tocan

Migración **aditiva y derivada** (columna + índice + backfill por lotes desde
`phone`); no toca `phone`, no añade restricción única, no fusiona ni borra nada.
`audit_owner_phone_duplicates` los lista (exit 0/1/2) como **diagnóstico, no
remediación**. Los ordena una persona de la clínica con las herramientas que ya
existen.

### Consecuencias (F1)

**A favor**

- Una sola definición de «este teléfono ya tiene expediente», compartida por
  `patients`, el importador y el agente.
- El alta de mascota deja de fabricar duplicados y de vincular por coincidencia.
- El cambio de teléfono deja de ser una escritura ciega, también desde la ficha
  de la mascota.
- El preview del importador dice lo mismo que el commit.
- Un `Owner` creado por cualquier vía —incluidas las excluidas— tiene su clave
  correcta, porque la derivación vive en `save()` y no en el servicio.

**En contra / aceptado**

- Una clínica con duplicados verá `owner_ambiguous` en altas que hoy «funcionan»
  reutilizando un expediente arbitrario, y su conteo de filas importadas bajará.
  Es el resultado pedido: mezclar dos expedientes clínicos es peor.
- Un contacto vinculado hoy puede quedar ambiguo cuando dos expedientes
  coincidan tras normalizar. El vínculo actual apunta a un expediente elegido a
  ciegas; dejarlo sería mantener el bypass.
- **El modo lectura no toma el lock**: un alta concurrente puede volver ambiguo
  lo que se acaba de leer como único. Aceptado — un `phone_match` no autoriza
  nada por sí solo y el siguiente mensaje reevalúa. Lo que se cierra no es la
  carrera: es la **elección**.
- El lock del importador se acumula durante todo el commit (una transacción).
  `MAX_ROWS = 2000` lo acota; subir ese tope obliga a revisar
  `max_locks_per_transaction`.
- El alta de mascota **pregunta donde antes inventaba**: teléfono conocido con
  otro nombre → `409` con candidato. El caso «mismo cliente, mismo nombre» sigue
  siendo silencioso.
- `Owner` no está registrado en el admin de Django: la exclusión C4 vale
  mientras nadie lo registre. Registrarlo es un cambio de una línea que reabre el
  vector.

---

## FLUJO-C — la salida del `owner_exists` (F4)

### Contexto

INV-B cierra un vector, pero el `409 owner_exists` que produce era un callejón
sin salida operativo: **`LINKED_STAFF` existía en el enum de `ContactIdentity`
desde el día 1 sin ningún escritor**. No había forma de que una persona del
equipo verificara manualmente a un contacto, así que el caso terminaba en un
hand-off que el staff resolvía fuera del sistema — o no resolvía.

### Decisión

> **Ningún `phone_match` habilita la acción por sí solo, y nada de la
> verificación de identidad se automatiza.** El sistema **registra** el juicio
> humano; no lo valida, no lo puntúa y no lo sustituye.

**Verificar y autorizar son dos actos distintos**, con dos endpoints. El primero
registra lo que una persona comprobó; el segundo ejecuta la consecuencia.
Unificarlos en uno con un booleano haría que un solo clic hiciera las dos cosas
sin dejar constancia de la primera.

**El caso no es un modelo nuevo**: es el `HumanHandoff` existente con
`reason_code='identity'` y un `reason_detail` discriminador. Lo nuevo es
`ContactIdentityVerification`, **append-only**, porque `ContactIdentity` no
guarda quién verificó y no puede representar un rechazo.

**La evidencia es externa al teléfono.** El número ya se sabe que coincide —es
lo que creó el caso—, así que reutilizarlo como prueba sería circular. Ninguna
opción de `evidence_kind` se basa en el número que escribe.

**Enlace estricto**: tener cuatro FKs no prueba que apunten al mismo caso. Todo
se deriva del servidor (organización y contacto desde la conversación, candidato
re-scopeado a esa organización, actor desde `request.user`), y autorizar exige
que el **último** registro sea `approved` **de este mismo hand-off**. Frescura
acotada por el caso, no por reloj: ni TTL arbitrario, ni aprobaciones de hace
tres meses habilitando acciones de hoy. El invariante de organización se valida
también **en el modelo**, para que una vía futura no pueda saltárselo.

**Permiso propio `agentinbox.identity_verify`**, no `agentinbox.config`:
verificar identidad es una función de mostrador, no de administración del canal
— delegarla no debe entregar también el kill switch. Y simetría con
`reset_contact_identity`: vincular es la operación inversa de desvincular y no
puede ser menos exigente.

`link_staff_verified` es la **cuarta** vía de promoción y la única forma
legítima de deshacer un reset: por eso limpia `auto_rematch_blocked`. Ese flag
apaga el auto-enlace porque nadie había verificado nada; aquí alguien lo hizo,
con nombre y evidencia.

### Consecuencias (F4)

**A favor**

- El `409 owner_exists` deja de ser un callejón sin salida: tiene resolución
  dentro del sistema, auditada y con RBAC.
- Toda vinculación a un expediente existente tiene nombre, caso y fecha.
- `LINKED_STAFF` deja de ser un valor muerto en el enum.

**En contra / aceptado**

- **Trabajo manual nuevo**: un cliente conocido que escribe con una mascota
  nueva ya no tiene ruta automatizada (§4.6). Lo resuelve el staff creando la
  mascota; recuperar la automatización sería una tool nueva gateada a
  `confirmed_in_chat`, fuera de este Item.
- **La verificación vale lo que valga la persona.** Automatizar el juicio es
  justo lo que §5.5.6 prohíbe; la mitigación es la trazabilidad.
- Con `owner_ambiguous` **no hay candidato** que ofrecer: el caso se resuelve
  ordenando los expedientes, no eligiendo desde la bandeja.

## Alternativas descartadas

- **Un endpoint con `approve: true/false`** en vez de dos: haría invisible el
  juicio cuando nadie llega a autorizar, y convierte dos decisiones en un clic.
- **TTL de la aprobación por reloj** (24 h, 7 días…): número arbitrario que no
  describe nada. El caso abierto es la unidad natural de frescura.
- **OTP/SMS al número del contacto** como evidencia: circular — ese número es
  precisamente lo que está en disputa.
- **Restricción única de teléfono por organización**: incompatible con INV-C
  (exigiría fusionar duplicados históricos). Descartada, no aplazada.
- **Fusión de expedientes duplicados**, automática o asistida: es una decisión de
  producto contraria a INV-C, no una mejora pendiente.
- **Deduplicar por `(nombre, teléfono)`** (la regla que tenía `/api/pets/`): dos
  capturas del mismo nombre con acento distinto producen dos expedientes con el
  mismo número — fabrica el problema que INV-C obliga a tratar.
- **Poner la comprobación del cambio de teléfono en `Serializer.validate`**: DRF
  valida y guarda en pasos separados; el chequeo allí y el `save()` después es
  precisamente la ventana que el servicio elimina.
- **Derivar la clave solo en el servicio**: dejaría a las vías excluidas
  (siembras, genérico, `create-with-patient`) escribiendo un `phone` sin clave
  consistente. La deduplicación es del servicio; la **consistencia del dato** es
  del modelo.
- **`updated_at` como token de versión**: `auto_now` se dispara con cualquier
  `save()` (una nota, un cambio de motivo) y produciría conflictos donde no hubo
  ninguno.
- **Restricción única sobre `(vet, start_datetime)`**: no modela solape, solo
  coincidencia exacta de inicio.
- **Detectar el solape solo con `exists()` + `select_for_update` del
  veterinario**: serializa por veterinario y penaliza toda la agenda para
  resolver lo que la base resuelve sin bloquear a nadie.
- **`409` para el solape**: rompe el contrato en producción y confunde dos cosas
  distintas (payload inválido vs. estado obsoleto).

## Verificación

| Prueba | Archivo | Qué acredita |
|---|---|---|
| P0-4 | `appointments/tests/test_preconditions.py` | el campo está declarado; `expected_state` desfasado → 409 en `PATCH` detalle **y** en `/status/` |
| P0-7 | ídem | el 409 no es privilegio del agente (ADMIN y VET) |
| P0-9ᵃ | ídem | cero escrituras parciales bajo conflicto, ni siquiera auditoría |
| P1-14 | ídem (`TransactionTestCase`, **PostgreSQL**) | hay lock, no solo comparación |
| P1-23 | ídem | `DELETE` respeta la precondición, sin 2ª `AppointmentStatusChange`, con cabeceras de deprecación |
| P2-4 | ídem (*iron rule*) | sin `expected_state`, comportamiento idéntico |
| P0-18 | `appointments/tests/test_no_overlap.py` (`TransactionTestCase`, **PostgreSQL**) | dos creaciones / dos reprogramaciones / reactivación+creación concurrentes → una sola cita activa |
| P0-20 | ídem | atención sin cita y reactivación sobre hueco ocupado → `slot_taken`, cero escrituras; con hueco libre siguen funcionando; **ninguna bandera de forzado** |
| — | `appointments/tests/test_audit_overlaps.py` | el comando detecta, no corrige, y respeta el criterio exacto de la restricción |

### F1 — identidad de expediente

| Prueba | Archivo | Qué acredita |
|---|---|---|
| P0-16 | `patients/tests/test_owner_phone_identity.py` (`TransactionTestCase`, **PostgreSQL**) | dos conexiones, misma org y teléfono → exactamente **un** expediente o un 409 cerrado. Repetido mezclando actor agente (`require_new`) y recepción |
| P0-17 | ídem | dos expedientes históricos con la misma clave → `owner_ambiguous` para **todos** los actores; cero escrituras; jamás se elige uno |
| P0-21 | ídem | `POST /api/pets/` contra `POST /api/owners/`, mismo teléfono, dos conexiones → ningún duplicado fabricado por la vía de mascotas |
| P0-22 | ídem | dos cambios de teléfono al mismo número nuevo (gana uno) **y** el caso cruzado A→B / B→A → **ningún deadlock**, gracias al orden total de claves |
| P0-23 | ídem | cambio de teléfono contra alta nueva sobre el mismo número → exactamente una operación persiste |
| P0-24 | ídem + `imports/tests/test_owner_phone_ambiguity.py` | duplicado histórico frente a **todas** las vías del inventario; ninguna elige una fila |
| P0-25 | `patients/tests/test_owner_phone_identity.py` | aislamiento por tenant (el mismo teléfono en otra org ni cuenta, ni bloquea, ni aparece) y **cero escrituras parciales** ante 409, tampoco los campos de la mascota en la vía anidada |
| P0-26 | `agent/tests/test_identity_readers.py` | los lectores del agente con un duplicado **distinguible solo tras normalizar**: cero vínculo, `is_ambiguous`, nivel sin subir, `auto_rematch_blocked` intacto. Con un único candidato de formato distinto → `phone_match` |
| P0-27 | `imports/tests/test_owner_phone_ambiguity.py` | preview y commit coinciden en `owner_ambiguous`; el conteo de importables ya excluye la fila; ninguna pasada usa `.first()` |
| P0-28 | `patients/tests/test_owner_phone_identity.py` | `Owner` genérico creado por el signal y por `patients.utils` → `phone_normalized = NULL`; no cuenta, no bloquea, ningún contacto puede vincularse a él por teléfono |
| A1·B2 | `appointments/tests/test_create_with_patient_identity.py` | registro rápido: 0 → crea · 1 sin flag → reutiliza (iron rule) · 1 con `require_new_owner` → `owner_exists` con candidato · ≥2 → `owner_ambiguous` con y sin flag · cero escrituras en ambos 409 · el expediente encontrado **no** se modifica · parseo fail-closed del flag |
| A1·B2 (carrera) | ídem (`TransactionTestCase`, **PostgreSQL**) | dos registros rápidos simultáneos con el mismo teléfono normalizado → **un** expediente y dos mascotas (horas distintas, para que el único punto de contención sea el teléfono y no el cupo) |
| P2-12 | ídem (`InventoryStaticGateTests`) | gate **doble**: funcional (todas las vías producen los desenlaces del servicio) y **estático** (todo sitio que construya un `Owner` está en el inventario, y nadie asigna `.phone` fuera del servicio) |
| P2-14 | ídem (*iron rule*) | el flujo aprobado de staff **no cambia**: cliente nuevo → crea; mismo cliente → reutiliza (incluso con acentos distintos) |
| P2-15 | ídem | el relleno del genérico no colisiona con un cliente real que tenga ese mismo número |

### F4 — FLUJO-C

| Prueba | Archivo | Qué acredita |
|---|---|---|
| Verificar no autoriza | `agent/tests/test_identity_verification.py` | registrar el juicio no toca `ContactIdentity`, ni el `Owner`, ni resuelve el caso |
| Autorizar exige evidencia del mismo caso | ídem | sin verificación, con aprobación de **otro candidato**, tras un **rechazo** posterior, o con la aprobación de un caso ya cerrado → `409 verification_required`, cero vínculo |
| Enlace estricto y tenant | ídem | actor y organización del **servidor** (se ignoran los del body); candidato ajeno → `owner_changed`; conversación ajena → **404 sin auditoría ni vínculo**; el **modelo** rechaza FKs cross-tenant |
| RBAC propio | ídem | ASSISTANT (con `agentinbox.claim`) recibe 403 en ambas acciones |
| Liberar no autoriza | ídem | el release restaura la intención vencida y el contacto sigue sin vincular |
| Append-only | ídem | no hay ruta de mutación; corregir es registrar otro; el original queda intacto. `Owner` con verificaciones no se puede borrar (PROTECT) |
| Enum de evidencia | ídem | lista blanca de las cuatro opciones aprobadas: una nueva basada en el número tiene que romper el test, no colarse |
| El caso en la bandeja | ídem | expone qué pidió el cliente y si la última verificación **aplica a este caso**; la nota (PII) no viaja |

Las pruebas de concurrencia **no valen en SQLite**: sin la restricción de
exclusión ni los locks de aviso, toda la suite pasaría sin probar nada.
