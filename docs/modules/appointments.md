# Modulo: Citas

> **Ver también:** [`docs/system-operational-flow.md`](../system-operational-flow.md) — mapa operacional cross-módulo (acciones, precondiciones, efectos, invariantes).

## Objetivo

El modulo de citas es el punto de entrada al ciclo clinico completo.
Una cita agendada y atendida es el punto de entrada al flujo clinico, pero ya no crea automaticamente ni el historial clinico ni la factura por defecto.

## Estados y transiciones

```
scheduled → confirmed → in_progress → done
    ↓            ↓            ↓
 canceled     canceled     canceled
    ↓            ↓
 no_show     no_show

scheduled, confirmed  ──→  no_show  (transición directa)
canceled, no_show     ──→  scheduled  (solo si fecha no pasó)
```
(Las flechas bajo `canceled` NO implican `canceled → no_show`; esa transición no existe.)

Transiciones validas:

| Desde        | Hacia                                    |
|--------------|------------------------------------------|
| `scheduled`  | `confirmed`, `in_progress`, `canceled`, `no_show` |
| `confirmed`  | `in_progress`, `canceled`, `no_show`     |
| `in_progress`| `done`, `canceled`                       |
| `done`       | (ninguna — terminal)                     |
| `canceled`   | `scheduled` (solo si la fecha no paso)  |
| `no_show`    | `scheduled` (solo si la fecha no paso)  |

Las transiciones invalidas retornan `400` con mensaje explicito.

`confirmed` es opcional. Las clinicas que no confirman citas pasan directamente de `scheduled` a `in_progress`.

**Trigger automático `in_progress → done` (ADR p34):** además del botón manual "Completar consulta", cerrar la consulta médica vinculada (`close_medical_record`) completa la cita automáticamente. El cierre del expediente clínico ES el acto que termina la atención; el servicio `complete_appointment_on_record_close` aplica la transición dentro del mismo `transaction.atomic()` del cierre. Es idempotente y no-op si la cita no está en `in_progress` (ya `done`/`canceled`) o si la consulta no tiene cita asociada. `done` sigue siendo terminal y el pago sigue viviendo en facturación (`done` ≠ pagado).

## Flujos principales

### Cita normal

1. Recepcion o veterinario crea la cita desde el calendario (`POST /api/appointments/`)
2. La cita nace en `scheduled`
3. Opcionalmente: se confirma (`confirmed`) antes de la atencion
4. Al llegar el paciente: se inicia la consulta (`in_progress`)
5. Al finalizar: se completa (`done`)
6. El modal de detalle permanece abierto y muestra CTAs contextuales:
   - `+ Crear Consulta Médica` si aun no existe historial
   - `Ver Consulta` si ya existe uno vinculado
   - `Ver Factura` solo si ya existe una invoice asociada
7. Desde `done`: el veterinario crea el historial clinico o lo visualiza si ya existe

### Walk-in

El walk-in es para pacientes que llegan sin cita previa.

Endpoint: `POST /api/appointments/walk-in/`

Campos requeridos: `veterinarian`, `reason` (nota: `pet` es condicional — ver toggles)
Campo opcional: `notes`

Comportamiento:
- la cita se crea directamente en `in_progress` con la hora local actual como hora de inicio
- la duracion es de 30 minutos por defecto
- no valida conflictos de horario (es atencion inmediata)
- el veterinario puede abrir el historial clinico inmediatamente
- **`Appointment.walk_in = True`** se setea explicito al crear (campo
  `editable=False`, `db_index=True`). Este flag persistido reemplaza la
  inferencia frágil "no scheduled ancestor en AppointmentStatusChange"
  usada antes. Ver ADR `2026-05-09-p9` y migration `appointments/0010`
  (backfill desde history para appointments preexistentes).

Reglas de negocio específicas para walk-in:
- `reason` se sanitiza y se trunca a 255 caracteres (`sanitize_text(..., max_length=255)`). Si después de sanitizar queda vacío, el endpoint retorna `400` con `reason` en el body.
- `notes` se sanitiza y se trunca a 5000 caracteres (`sanitize_text(..., max_length=5000)`).
- **Deduplicación segura (ADR p12)**: el filtro de reutilización ahora exige `walk_in=True` y `pet=pet` — no recicla cita de otra mascota aunque sea del mismo veterinario en la misma ventana de 10 segundos.

Pet es obligatorio salvo que la organización tenga `allow_anonymous_walkin = True`:

| Caso | Resultado esperado |
|------|-------------------|
| toggle OFF + sin `pet` | ❌ 400 ("Walk-in anónimo no está configurado.") |
| toggle ON + sin `pet`  | ✔  usa paciente genérico de la organización (se asigna `Pet.is_generic=True`) |

Si el campo `pet` se envía, debe pertenecer a la organización del usuario — de lo contrario `404`.

### Registro rápido + cita (alta de paciente en el momento)

Para pacientes nuevos sin registro previo, el formulario "Nueva cita" ofrece el enlace
**"No encuentro la mascota →"** que expande un panel inline (`QuickPatientForm`).

Endpoint: `POST /api/appointments/create-with-patient/`

Campos requeridos:

| Campo | Descripción |
|-------|-------------|
| `owner_name` | Nombre del dueño |
| `owner_phone` | Teléfono del dueño (exactamente 10 dígitos) |
| `pet_name` | Nombre de la mascota |
| `pet_species` | Especie (valor de `SPECIES_CHOICES`) |
| `veterinarian` | ID del veterinario |
| `date` | Fecha de la cita |
| `start_time` | Hora inicio |
| `end_time` | Hora fin |
| `reason` | Motivo |

Campos opcionales: `pet_sex` (default `unknown`), `pet_birth_date`, `notes`.

Lógica interna con `transaction.atomic()`:

1. `Owner.objects.get_or_create(organization=org, phone=owner_phone)` — si el teléfono ya existe en la organización se reutiliza el owner (cliente que regresa con mascota nueva), de lo contrario se crea con el nombre enviado.
2. `Pet.objects.create(...)` — siempre crea una mascota nueva (incluso si el owner ya existía).
3. `AppointmentSerializer(...).is_valid(raise_exception=True)` — reutiliza toda la validación existente: conflictos de horario, fecha pasada, conversión de timezone.

Si cualquier paso falla (validación, conflicto de horario, teléfono inválido), toda la transacción se revierte. No quedan owners ni mascotas huérfanas.

El frontend valida los campos del formulario antes de llamar al backend (owner_name, owner_phone 10 dígitos, pet_name, species). El botón "Guardar cita" es el mismo que el del flujo normal; el formulario bifurca internamente según si está activo el panel de registro rápido.

### No-show

Cuando el paciente no se presenta y la hora de la cita ya paso, recepcion lo marca manualmente.

Desde `scheduled` o `confirmed` se puede transicionar a `no_show`.

No existe marcado automatico en v1. Es una accion manual confirmada desde el detalle de la cita.

### Walk-in anónimo y vinculación de paciente

Cuando `allow_anonymous_walkin = True` y se omite `pet` en el walk-in, el sistema usa la
mascota genérica de la organización (`Pet.is_generic=True`, propietario `Owner.is_generic=True`).

Ambos registros genéricos se crean automáticamente al crear la organización (signal `post_save`).
Existe exactamente uno por organización.

**Vinculación posterior** — una cita con mascota genérica puede vincularse a un paciente real
mientras no esté en estado `done`:

`PATCH /api/appointments/<id>/assign-patient/` con `{ "pet": <id> }`

Comportamiento:
- Solo aplica cuando `appointment.pet.is_generic = True` (retorna `400` en otro caso).
- No se puede vincular al propio paciente genérico.
- Si existe un `MedicalRecord` abierto vinculado a esa cita, también se actualiza su `pet`.
- El cambio queda registrado en `AppointmentStatusChange` con mensaje descriptivo.

La UI muestra un banner amarillo en el detalle de la cita cuando el paciente es genérico y el
estado no es `done`. El banner desaparece al vincular.

## Cancelacion

Se puede cancelar desde `scheduled`, `confirmed` o `in_progress` vía PATCH `/update-status/`. El endpoint DELETE solo acepta `scheduled` o `confirmed`.

Al cancelar se puede enviar un `cancellation_reason` opcional (texto libre).
El motivo queda almacenado en la cita para reportes.

**Event lineage**: cualquier cancelacion — sea via PATCH `/update-status/`
o via DELETE `/api/appointments/<id>/` — DEBE crear una row en
`AppointmentStatusChange`. Antes (pre-ADR `2026-05-09-p9`),
`AppointmentDetailView.destroy()` mutaba `instance.status='canceled';
instance.save()` directo, bypaseando el audit log y destruyendo el
event lineage usado por analytics. Ahora ambos paths crean la row en
mismo `transaction.atomic()`.

**`DELETE` está DEPRECADO** (ADR p57). Sigue funcionando y respeta INV-A, pero
emite cabeceras `Deprecation`/`Sunset` (RFC 8594, Sunset **2026-11-06**) y el log
`DEPRECATED_ENDPOINT_HIT`. El sucesor es `PATCH /<id>/status/` con
`status: "canceled"`. La retirada (`410 endpoint_sunset`) llega cuando el
frontend deje de usarlo.

Reprogramacion:
- si la fecha original no paso: `canceled → scheduled` restaura la cita
- si la fecha ya paso: se debe crear una cita nueva. El sistema retorna `400` con mensaje explicito
- si el hueco original ya se reasignó a otra cita activa del mismo veterinario:
  `400 slot_taken` y la cita **sigue** `canceled`/`no_show` (INV-D, ADR p57).
  Nada se desplaza automáticamente: hay que programarla de nuevo

## Reglas de creacion

- requiere: mascota, veterinario, fecha, hora inicio, hora fin, motivo
- la mascota y el veterinario deben pertenecer a la misma organizacion
- si el frontend envia `owner_id` en el body, el backend valida que la mascota pertenezca a ese propietario (guardia de integridad, no constraint de modelo)
- la hora de inicio no puede ser en el pasado (comparacion de datetime completo en UTC)
- hora fin debe ser mayor a hora inicio (constraint en DB)
- no puede haber dos citas solapadas para el mismo veterinario en estados `scheduled`, `confirmed` o `in_progress` (**INV-D**, garantizado en PostgreSQL — ver § Garantías de agenda)

---

## Garantías de agenda (ADR p57)

Dos invariantes del dominio, no del llamador. Ambos viven en `appointments` y
aplican a **cualquier actor**: frontend, agente de WhatsApp, importador, script
de soporte.

### INV-A — Precondición atómica de estado (`expected_state`)

Toda mutación sobre una cita **existente** acepta `expected_state`: la tupla que
el llamador vio cuando decidió mutar.

```json
{ "expected_state": { "status": "scheduled", "date": "2026-08-12", "start_time": "10:00" } }
```

El dominio la compara contra la fila tomada con `select_for_update()`, **dentro
de la misma transacción que escribe**. Si difiere, `409` y **cero escrituras**
(ni la cita, ni `AppointmentStatusChange`):

```json
{ "code": "appointment_changed",
  "message": "La cita cambió desde que se propuso.",
  "current": { "status": "confirmed", "date": "2026-08-13", "start_time": "16:00" } }
```

`current` viaja siempre: quien reintente lo hace informado. El `409` **no es un
error técnico** — es un resultado de negocio (el mundo cambió). El consumidor
recarga y vuelve a preguntar; **nunca** reintenta sin precondición ni degrada a
último-escritor-gana. Si la cita ya está en el estado deseado (cancelar algo ya
cancelado), `current` permite reconocerlo como éxito idempotente.

**Opt-in hasta F5**: sin `expected_state` el comportamiento es idéntico al
anterior. Cuando el frontend la envíe, pasará a obligatoria
(`400 precondition_required`).

Forma inválida (no es objeto, claves faltantes o desconocidas, estado
inexistente, fecha/hora no parseables) → `400 validation_error`. Enviarla a
**cualquiera** de las tres vías de creación (`POST /`, `create-with-patient`,
`walk-in`) → `400`: no hay estado previo que comparar, y tragársela en silencio
anunciaría una garantía que nadie aplica.

**Omitir la clave ≠ mandarla en `null`.** Omitirla es el opt-in del rollout y
la escritura procede como siempre. `expected_state: null` explícito es
`400 validation_error` con **cero escrituras**, en las siete vías: quien manda
`null` cree que está mandando una precondición, y dejar pasar esa escritura sin
comparar nada es el fail-open que INV-A cierra. Vale igual por JSON que por
form-data — en form-data la clave presente llega como cadena (`""`, `"null"`) y
se rechaza por forma, así que no hay codificación que sirva de puerta trasera.

#### Matriz de mutaciones — no hay categoría implícita

| Mutación | Lock de fila | `expected_state` | INV-D |
|---|---|---|---|
| `PATCH /api/appointments/<public_id>/` | sí | acepta | sí |
| `PATCH /<public_id>/status/` | sí | acepta | sí (reactivación) |
| `DELETE /<public_id>/` | sí | acepta (en el body) | n/a |
| `PATCH /<public_id>/assign-patient/` | sí | acepta | **no** (no mueve la tupla de agenda) |
| `POST /api/appointments/` | n/a | **rechaza (400)** | sí |
| `POST /create-with-patient/` | n/a | **rechaza (400)** | sí |
| `POST /walk-in/` | n/a | **rechaza (400)** | **sí** |
| `services.complete_appointment_on_record_close` | no | **no** (excluida) | no |

`complete_appointment_on_record_close` está **excluida con justificación**: es
una transición interna que ya falla cerrada (UPDATE condicional) y evita a
propósito un orden de locks `Appointment↔MedicalRecord` que generaría ABBA con
`assign-patient`.

**Regla binding**: ninguna vía nueva puede mutar una cita sin lock de fila. Si
aparece una, entra en esta matriz antes de mergear.

### INV-D — Un veterinario no tiene dos citas activas solapadas

Lo garantiza una **restricción de exclusión de PostgreSQL**
(`appointment_no_overlap_per_vet`, migración `appointments/0014` + extensión
`btree_gist`) sobre `(organization, veterinarian, [start_datetime,
end_datetime))` con predicado parcial de estados activos.

Vive en la tabla, no en un endpoint: cubre creación, reprogramación, atención
sin cita y reactivación, y a cualquier actor. `done`/`canceled`/`no_show` quedan
fuera del predicado (una cita cancelada **no** bloquea el hueco), igual que las
citas sin veterinario asignado.

Intervalo semiabierto `[inicio, fin)`: 10:00–10:30 y 10:30–11:00 son contiguas,
**no** solapadas.

**Contrato de error** — el pre-chequeo del serializer se conserva y produce el
mensaje; la restricción es la garantía. Los dos caminos dan el **mismo**
resultado, y el llamador no puede distinguirlos:

```json
{ "code": "slot_taken",
  "message": "Ya existe una cita para este veterinario en ese horario",
  "errors": { "error": ["Ya existe una cita para este veterinario en ese horario"] } }
```

`400`, no `409`: el `409` está reservado a precondiciones vencidas. El cuerpo es
un superset del anterior — ningún consumidor se rompe.

**La garantía tiene dos piezas.** La restricción dice la verdad sobre el cupo;
la **serialización preventiva por veterinario** hace que esa verdad se cobre
como `slot_taken` y no como avería. Toda escritura que pueda entrar o salir del
predicado de INV-D toma antes un `select_for_update()` sobre la fila del
veterinario (`services.lock_veterinarians`); si hay reasignación, sobre **los
dos** veterinarios en orden de PK. Sin eso, dos escrituras simultáneas al mismo
hueco hacen deadlock comprobando la exclusión y el perdedor recibe un 500.

Un `deadlock detected` (SQLSTATE `40P01`) **no** se traduce a `slot_taken`: no
prueba que el hueco esté ocupado. Si aparece, es un bug de cobertura del lock y
debe verse como error.

**Dos comportamientos cambiaron el día 1** (decisión de producto aprobada):

| Camino | Antes | Ahora |
|---|---|---|
| **Atención sin cita** con el veterinario ocupado | creaba en `in_progress` sin comprobar solapes | `400 slot_taken`, **cero** citas creadas → recepción escoge otro veterinario u otro horario |
| **Reactivación** `canceled\|no_show → scheduled` sobre hueco ocupado | resucitaba la cita sobre un hueco reasignado | `400 slot_taken`, la cita sigue en su estado terminal → hay que programar de nuevo |

**No existe bandera de forzado** (`force`, `allow_overlap`, permiso que lo
salte) y nada se desplaza automáticamente. Espera, sobrecupo y múltiples
recursos son feature separada con su propio ADR.

**Antes de desplegar la migración**: correr
`python manage.py audit_appointment_overlaps` (exit 0 limpio / 1 con hallazgos /
2 error), remediar **a mano** por clínica lo que reporte, aplicar la migración
en ventana de deploy y re-auditar. PostgreSQL no admite exclusiones `NOT VALID`:
con un solape histórico vivo, la migración falla. El comando queda como red de
seguridad permanente.

## Visibilidad

- `ADMIN`: ve todas las citas de su organizacion
- `VET`: ve todas las citas de su organizacion; la vista por defecto muestra las propias
- `ASSISTANT`: ve todas las citas de su organizacion (lectura)

## Seleccion de mascota en el frontend

La seleccion de mascota en `SidebarForm` y `WalkInModal` usa el componente `SearchSelect`:
- el usuario escribe y se busca contra `GET /api/pets/?search=<texto>` (debounce 300ms)
- el label muestra `<nombre> – <propietario>` cuando el propietario tiene nombre registrado
- no se carga la lista completa de mascotas al montar la pagina

El veterinario sigue siendo un `<select>` nativo (lista pequena, sin problema de escala).

## Auditoria de transiciones (AppointmentStatusChange)

Cada cambio de estado exitoso crea un registro `AppointmentStatusChange`.

Campos:
- `appointment` — FK a Appointment (CASCADE)
- `from_status` / `to_status` — estados antes y después del cambio
- `changed_by` — FK a User (SET_NULL, puede ser null si el cambio fue automático)
- `reason` — texto libre (se usa para `cancellation_reason` y mensajes de vinculación de paciente)
- `created_at` — timestamp automático

El modelo hereda de `OrganizationalModel` (multitenant). Ordenamiento por `-created_at`.

La transición automática al cerrar la consulta (ADR p34) también crea su row:
`from_status='in_progress'`, `to_status='done'`, `changed_by` = usuario que cerró la
consulta, `reason='Auto-completada al cerrar la consulta médica'`.

Endpoint: `GET /api/appointments/<id>/history/`

La UI consume este endpoint de forma lazy (solo al expandir el panel "Historial de estados")
y solo lo muestra si `show_status_change_history = True` en `OrganizationSettings`.

## Configuracion de flujo por organizacion

El comportamiento automático al completar citas está controlado por `OrganizationSettings`.
Todos los toggles están implementados en backend y frontend.

Ver ADR `2026-04-28-organization-settings-toggles.md`.

| Toggle | Default | Comportamiento |
|--------|---------|----------------|
| `auto_create_invoice_on_done` | `False` | Al pasar a `done`, puede crear factura draft automaticamente via signal si la clinica lo habilita |
| `auto_create_medical_record` | `False` | Al pasar a `done`, puede crear `MedicalRecord` vacio en estado `open` si la clinica lo habilita |
| `require_confirmation_before_start` | `False` | Bloquea cualquier transición a `in_progress` si el estado previo no es `confirmed` |
| `allow_anonymous_walkin` | `False` | Permite walk-in sin mascota; usa paciente genérico (`Pet.is_generic=True`) |
| `allow_emergency_walkin` | `False` | Permite urgencias sin cita previa; toggle separado de `allow_anonymous_walkin` |
| `show_status_change_history` | `True` | Controla visibilidad del panel de historial en la UI de detalle de cita |

Los defaults actuales privilegian un flujo manual y explicito: completar la cita no crea automaticamente artefactos clinicos ni financieros salvo que la organizacion lo habilite.
El fallback cuando no existe registro de settings está en `get_org_setting()` (`apps/organizations/utils.py`).

## Duracion por defecto de slot en el formulario

La duracion por defecto al crear una cita desde el formulario del calendario es el valor
de `default_appointment_duration_minutes` en `OrganizationSettings` (default: **30 minutos**).

Este valor solo afecta citas nuevas; no modifica duraciones de citas existentes ni reorganiza slots.
Se configura desde `/config` → Reglas operativas → "Duración predeterminada de cita".

- Hora inicio: la hora del slot seleccionado (en punto, ej: 10:00)
- Hora fin: `default_appointment_duration_minutes` minutos despues (ej: 10:30), salvo en el ultimo slot del dia (20:00) donde se ajusta automaticamente
- El backend acepta cualquier duracion siempre que `end_time > start_time`

El walk-in tambien usa `default_appointment_duration_minutes` por defecto (comportamiento sin cambio).

## Relacion con otros modulos

- **Historial clinico**: una cita `done` puede tener uno o mas `MedicalRecord` asociados.
  El campo `medical_record_ids` en la respuesta lista los IDs vinculados.
  La consulta clinica se crea desde `/medical-records?pet=<id>&appointment=<id>`.
  El frontend usa esta relacion para mostrar `+ Crear Consulta Médica` o `Ver Consulta` sin depender de estado local.
  **Sincronización de ciclo de vida (ADR p34)**: cerrar la consulta vinculada completa la
  cita (`in_progress → done`) vía `apps.appointments.services.complete_appointment_on_record_close`,
  invocado por `close_medical_record` dentro de su `atomic()`. El acoplamiento es
  cross-domain unidireccional (medical_records → appointments.services); no se muta
  `Appointment` directamente desde medical_records.

- **Facturacion**: una cita puede tener una `Invoice` asociada.
  El campo `invoice_id` en la respuesta expone el ID si existe.
  La factura no se genera por defecto; si la organizacion activa `auto_create_invoice_on_done`, se crea en `draft` al pasar a `done`.

## UX al completar la cita

Hay **dos caminos** para que una cita llegue a `done` (ADR p34):

1. **Vía cierre de consulta (camino esperado)**: cuando se atendió desde "Atender ahora"
   y se abrió una consulta médica, al finalizarla (`close_medical_record`) la cita se
   completa automáticamente. El usuario no necesita volver a Citas a marcarla manualmente.
2. **Botón manual "Completar consulta"** (fallback): para citas sin consulta médica
   (atención trivial, o `in_progress` que se cierra administrativamente). Usa el modal
   compartido `ConfirmDialog` (no `window.confirm`).

Comportamiento del botón manual:
- antes de pasar a `done`, se muestra confirmacion explicita
- al confirmar, el backend retorna la cita serializada actualizada
- el modal de detalle permanece abierto
- los CTAs posteriores se recalculan desde `medical_record_ids` e `invoice_id` devueltos por backend

Esto evita dos problemas:
- errores accidentales al marcar `done`
- CTAs stale que solo existan en memoria del frontend

> El flujo "Atender ahora" ya **no** pre-crea un `MedicalRecord` duplicado. El stepper
> crea el único MR ligado a la cita (PK por router state); ver `docs/modules/frontend.md`
> §"Flujo Atender ahora" y ADR p34.

## Endpoints

| Metodo | URL | Descripcion |
|--------|-----|-------------|
| `GET`    | `/api/appointments/` | Listar citas de la organizacion |
| `POST`   | `/api/appointments/` | Crear cita (mascota ya registrada) |
| `POST`   | `/api/appointments/create-with-patient/` | Crear cita + owner + pet en una sola transaccion |
| `POST`   | `/api/appointments/walk-in/` | Registrar walk-in (crea en `in_progress`) |
| `GET`    | `/api/appointments/<id>/` | Detalle de cita |
| `PUT`    | `/api/appointments/<id>/` | Editar cita (campos clinicos) |
| `DELETE` | `/api/appointments/<id>/` | **DEPRECADO** — cancelar cita (soft cancel, solo desde `scheduled` o `confirmed`). Sucesor: `PATCH /<id>/status/` |
| `PATCH`  | `/api/appointments/<id>/status/` | Cambiar estado con validacion de transicion |
| `GET`    | `/api/appointments/<id>/history/` | Historial de cambios de estado |
| `PATCH`  | `/api/appointments/<id>/assign-patient/` | Vincular paciente real a cita con paciente generico |

### Permisos RBAC de los nuevos endpoints

| Endpoint | Permiso requerido |
|----------|-------------------|
| `POST create-with-patient/` | `appointment.create` |
| `GET <id>/history/` | `appointment.retrieve` |
| `PATCH <id>/assign-patient/` | `appointment.update` |

### Filtros disponibles (GET /api/appointments/)

- `veterinarian=<id>` — filtrar por veterinario
- `date=YYYY-MM-DD` — filtrar por dia (usa timezone de la organizacion)
- `pet=<id>` — filtrar por mascota

### Filtros disponibles (GET /api/pets/)

- `search=<texto>` — busqueda por nombre (icontains, limite 20)
- `owner=<id>` — filtrar por propietario
- Ambos son combinables: `?search=luna&owner=3`

### Filtros disponibles (GET /api/owners/)

- `search=<texto>` — busqueda por nombre (icontains, limite 20)
- `is_generic=true/false` — filtrar propietario generico (para ventas directas)

## Campos de respuesta

```json
{
  "id": 1,
  "public_id": "uuid-v4",
  "pet": 12,
  "pet_public_id": "uuid-v4",
  "pet_name": "Max",
  "pet_is_generic": false,
  "owner_id": 5,
  "owner_public_id": "uuid-v4",
  "owner_name": "Juan Perez",
  "veterinarian": 3,
  "veterinarian_public_id": "uuid-v4",
  "veterinarian_name": "Dr. Garcia",
  "date": "2026-04-28",
  "start_time": "10:00:00",
  "end_time": "10:30:00",
  "reason": "Vacunacion",
  "notes": "",
  "status": "scheduled",
  "cancellation_reason": "",
  "walk_in": false,
  "medical_record_ids": [],
  "medical_record_public_ids": [],
  "invoice_id": null,
  "invoice_public_id": null
}
```

`pet_is_generic` — indica si la mascota asignada es el paciente genérico.
El frontend usa este campo para mostrar el banner de vinculación.

`walk_in` (ADR p35) — `read_only`, expone el flag persistido del modelo
(`editable=False`, ver §Walk-in). Lo consume la Agenda del dashboard
(`TodayAgendaList`) para el marcador `●` walk-in. Solo lectura: el cliente no
puede setearlo (el walk-in lo crea el endpoint `walk-in/`). Sin migración —
campo ya existía en el modelo.

## Permisos RBAC

| Accion                  | Codigo                |
|-------------------------|-----------------------|
| Listar                  | `appointment.list`    |
| Ver detalle             | `appointment.retrieve`|
| Crear                   | `appointment.create`  |
| Editar                  | `appointment.update`  |
| Cancelar (DELETE)       | `appointment.destroy` |
| Cambiar estado          | `appointment.update`  |
| Walk-in                 | `appointment.create`  |
| Registro rapido + cita  | `appointment.create`  |
| Ver historial estados   | `appointment.retrieve`|
| Vincular paciente       | `appointment.update`  |

## Timezone

Las fechas y horas se almacenan en UTC en los campos `start_datetime` y `end_datetime`.
Los campos `date`, `start_time` y `end_time` almacenan los valores locales tal como los envia el cliente.

La conversion local→UTC usa el timezone configurado en la organizacion (`org.timezone`).
Si la organizacion no tiene timezone configurado, usa `UTC` como fallback.

Para que el modulo funcione correctamente en clinicas en Mexico, la organizacion debe tener
`timezone = 'America/Mexico_City'` configurado en `/config`.

## Observabilidad

Los eventos de RBAC (acceso denegado, acceso por fallback) se registran automaticamente
por el sistema de permisos `HybridPermission`.

Las transiciones invalidas retornan `400` con `error` descriptivo que incluye el estado actual
y el estado solicitado.
