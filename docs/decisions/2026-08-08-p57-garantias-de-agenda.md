# ADR p57 — Garantías de agenda: precondición atómica (INV-A) y no-solapamiento (INV-D)

**Fecha**: 2026-08-08
**Estado**: ACEPTADO (F0 implementado; INV-A queda opt-in hasta F5)
**Decisión de origen**: [`item-2-decision.md`](item-2-decision.md) §3.2, §3.3,
§3.4, §5.1, §9.14, §9.15. Plan de ejecución:
[`item-2-implementation-plan.md`](item-2-implementation-plan.md) §3 (F0).
**Alcance de este ADR**: F0. Los invariantes de identidad (INV-B, INV-C) y el
caso de verificación (FLUJO-C) llegan en F1 y F4 y **amplían** este documento.

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

**Opt-in hasta F5.** Sin `expected_state`, el comportamiento es idéntico al
actual (P2-4, regresión *iron rule*). F5 la vuelve obligatoria
(`400 precondition_required`) una vez que el frontend la envíe; hasta entonces
INV-A protege al agente y a cualquier llamador que la adopte, no a dos pestañas
del frontend entre sí. Es una limitación declarada, no un olvido.

Una precondición **mal formada** (no es objeto, claves faltantes o
desconocidas, estado inexistente, fecha u hora no parseables) es `400
validation_error`. Aceptar una tupla que no se puede comparar sería el mismo
fail-open del punto 1. Enviarla a cualquiera de las **tres** vías de creación
también es `400`: no hay estado previo que comparar. Las tres, no solo la
obvia — `create-with-patient` y `walk-in` arman su payload a mano, así que sin
un rechazo explícito el campo se perdía sin ruido.

**Ausencia de la clave ≠ `null` explícito.** Solo la **ausencia** es el opt-in
del rollout. `expected_state: null` es `400 validation_error` con cero
escrituras, en las siete vías. El motivo es el mismo fail-closed del punto 1:
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
mentiroso. Llega por dos caminos y ambos se traducen: `ValidationError` de
modelo (`full_clean()` → `ExclusionConstraint.validate()`, un pre-chequeo más) e
`IntegrityError` de la base (la garantía, la única que cubre la carrera).

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

## Alternativas descartadas

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

Las pruebas de concurrencia **no valen en SQLite**: sin la restricción de
exclusión toda la suite pasaría sin probar nada.
