# Modulo: Mascotas y Propietarios

> **Ver también:** [`docs/system-operational-flow.md`](../system-operational-flow.md) — mapa operacional cross-módulo (acciones, precondiciones, efectos, invariantes).

## Objetivo

El modulo gestiona propietarios y sus mascotas.
Es el punto de entrada a todos los flujos clinicos del sistema.

## Modelos

### Owner (Propietario)

Campos:
- `public_id` — UUID v4 expuesto en URLs y deep links (ADR p18 Día 6)
- `name` — nombre del propietario
- `phone` — telefono de contacto (10 digitos en alta manual; `blank=True` a nivel modelo — ver excepción del importador abajo). **Texto libre**: se guarda como lo tecleó cada quien (`"55 1234 5678"`, `"(55) 1234-5678"`)
- `phone_normalized` — **clave de identidad y deduplicación** (INV-C, ADR p57). 10 dígitos o `NULL`. La deriva **siempre** el dominio en `Owner.save()`, nunca el cliente (`editable=False`, fuera de los serializers). Ver § Identidad de expediente por teléfono
- `is_generic` — marca al propietario sintetico "Publico General" creado por organizacion
- `legacy_id` — identificador del sistema/clínica de origen (nº de cliente del software viejo), agregado en el Sprint import. `blank=True, default=''`. Único por organización **solo cuando está presente** (constraint parcial que excluye `''`). NO es PK ni reemplaza `public_id` — solo referencia. La UI lo muestra como "Número de expediente anterior", nunca "legacy_id".
- `extra_data` — `JSONField(default=list, blank=True)`: datos históricos del sistema anterior (Sprint import Fase D, ADR p43). Lista de `{label, value, source_column, imported_at}`. **Read-only** (lo escribe solo el importador; `read_only` en el serializer). Ver § Datos del sistema anterior.

Reglas de negocio:
- telefono debe tener exactamente 10 digitos en el alta/edición **manual** (validacion en `OwnerSerializer`)
- **Excepción del importador (Sprint import):** el modelo declara `phone = blank=True`; el importador CSV/Excel (`apps/imports`) crea owners vía `Owner.save()` directo y puede dejar el teléfono vacío (archivos viejos sin teléfono). El `OwnerSerializer` sigue exigiendo 10 dígitos — la relajación vive **solo** en el importador, no en la API manual. Datos históricos sucios ≠ datos nuevos.
- la validacion de telefono se omite cuando `is_generic = True`
- existe un unico propietario generico por organizacion (constraint parcial en DB)
- el propietario generico se crea automaticamente al crear la organizacion via signal

### Pet (Mascota)

Campos:
- `public_id` — UUID v4 expuesto en URLs y deep links (ADR p18 Día 6)
- `name` — nombre de la mascota
- `species` — especie (`SPECIES_CHOICES`). **Opcional** en captura manual: `''` = "pendiente" (la mascota sí tiene especie, solo no se capturó). Si se captura, debe ser válida. UI muestra "Pendiente". Ver Validaciones.
- `breed` — raza (texto libre, opcional)
- `birth_date` — fecha de nacimiento **opcional** en todos los caminos de alta (estándar, alta rápida e importador) — ver Validaciones
- `sex` — choices: `male`, `female`, `unknown`
- `color` — color (opcional, seleccion en frontend)
- `owner` — FK a Owner (**PROTECT** desde PR-4B / ADR p16 — antes CASCADE)
- `is_generic` — marca a la mascota genérica "Paciente Anónimo" de la organización
- `legacy_id` — nº de expediente del sistema viejo (Sprint import). Mismo contrato que `Owner.legacy_id`: `blank=True, default=''`, único parcial por organización cuando está presente
- `extra_data` — `JSONField(default=list, blank=True)`: datos históricos del sistema anterior (Sprint import Fase D, ADR p43). Mismo contrato que `Owner.extra_data` (lista read-only de `{label, value, source_column, imported_at}`). Ver § Datos del sistema anterior

Existe exactamente una mascota genérica por organización (creada via signal junto al owner genérico).
Se usa en walk-ins anónimos cuando `allow_anonymous_walkin = True` y no se envía `pet`.
No aparece en búsquedas normales (el frontend la filtra).
No puede ser objetivo de `assign-patient` (sería reasignar de genérico a genérico).

## Validaciones de backend

### Nombre (mascota y propietario)

Regex: `^[A-Za-z0-9ÁÉÍÓÚáéíóúñÑ' \-]+$`

Permite: letras, numeros, espacios, acentos, apostrofe, guion.
Rechaza: signos de puntuacion, caracteres especiales, emojis.

### Especie

Lista cerrada definida como constante `SPECIES_CHOICES` en `apps/patients/models.py`:

```python
SPECIES_CHOICES = ['canino', 'felino', 'equino', 'ave', 'reptil', 'exotico', 'otro']
```

La misma lista se usa en serializer y en el dropdown del frontend.
No se almacena como `choices` en el campo del modelo para evitar migraciones al agregar especies.

### Telefono

Regla **única** del dominio: `apps.core.validators.validate_mx_phone` — 10
dígitos MX + rechazo de relleno evidente (`0000000000`, `1234567890`). No se
valida para propietarios con `is_generic = True`.

Desde F1 (ADR p57) **no queda ninguna segunda regla de forma**: el
`PHONE_REGEX` local de `patients/serializers.py` —que la escritura anidada de
`PetSerializer` usaba y que **aceptaba rellenos**— se retiró. El alta de mascota
valida el teléfono con la misma regla que el alta de cliente.

## Identidad de expediente por teléfono (INV-C — ADR p57)

> **INV-C** — Un teléfono normalizado identifica **como máximo un expediente**
> dentro de una organización. Si hay más de uno, el resultado es
> `owner_ambiguous` y el caso escala a una persona. El sistema **nunca** fusiona
> registros ni elige uno automáticamente.

> **INV-B** — El teléfono **localiza**, no autoriza. Que un número coincida no
> habilita escribir sobre el expediente que encontró.

### El servicio único (`apps/patients/services.py`)

Todo camino que resuelva un expediente a partir de un teléfono pasa por aquí.
Tres operaciones, una sola verdad:

| Operación | Lock | Para qué |
|---|---|---|
| `lookup_owner_by_phone(org, phone)` | **no** | Modo lectura: saber sin decidir. Lo usan los lectores de identidad del agente y las pasadas de preview/dry-run del importador |
| `resolve_owner_for_phone(org, …)` | sí | Resolver para escribir. **Debe llamarse dentro de la transacción que escribe** |
| `change_owner_phone(owner, phone)` | sí (dos claves) | Mover la clave: bloquea la anterior y la nueva en **orden total**, comprueba y guarda sin ventana |

**Desenlaces de `resolve_owner_for_phone`** (exhaustivos — no existe una rama
que «elija»):

| Expedientes con la clave | `require_new` | `match_name` | Resultado |
|---|---|---|---|
| sin clave (vacío o < 10 dígitos) | — | — | `created` |
| 0 | cualquiera | — | `created` |
| 1 | `False` | nombre coincide, o `False` | `reused` |
| 1 | `False` | nombre distinto | **`409 owner_exists`** con el candidato |
| 1 | `True` | — | **`409 owner_exists`** |
| ≥ 2 | cualquiera | — | **`409 owner_ambiguous`**, cero escrituras |

`owner_ambiguous` **no es opt-in**: aplica también a recepción. Si el dominio no
sabe cuál es el expediente, ningún actor puede fingir que sí.

**Por qué un lock de aviso y no `UNIQUE (organization, phone)`**: la restricción
única exigiría limpiar o fusionar los duplicados históricos, y eso es justo lo
que INV-C prohíbe. El lock (`core.db_locks.advisory_xact_lock`, a nivel de
transacción) cubre además el caso que un lock de fila no puede cubrir: **la fila
todavía no existe**. Es **PostgreSQL-only y ruidoso**: en otro motor lanza
`AdvisoryLockUnsupported` en vez de degradarse a no-op, y exige transacción
abierta (en autocommit el lock se soltaría en la misma sentencia).

### Inventario de vías (contrato del módulo — §4.7.4 de la decisión)

Toda vía **usa el servicio** o queda **excluida con evidencia**. No hay
categoría implícita, y «cualquier vía futura» **no** es cobertura válida: una
vía nueva entra en esta tabla antes de mergear. El gate
`patients/tests/test_owner_phone_identity.py::InventoryStaticGateTests` lo hace
cumplir enumerando cada sitio que construye un `Owner`.

| Vía | Familia | Estado |
|---|---|---|
| `POST /api/owners/` | A2 | usa el servicio (`match_name=True`) |
| `POST /api/pets/` | A3·B1 | usa el servicio — contrato nuevo abajo |
| `PATCH/PUT /api/owners/<id>/` | C1 | `change_owner_phone` |
| `PATCH/PUT /api/pets/<id>/` (teléfono anidado) | C2 | `change_owner_phone` |
| Importador (commit) | A4·B3 | usa el servicio, por fila |
| Importador (preview / dry-run) | E3 | modo lectura, mismo contrato |
| `agent/services` — creación de `ContactIdentity` | E1 | modo lectura sobre `phone_normalized` |
| `agent/services._rematch_owner` | E2 | modo lectura sobre `phone_normalized` |
| `POST /api/appointments/create-with-patient/` | A1·B2 | usa el servicio + `require_new_owner` (opt-in) — ver § Alta rápida desde citas |
| `OwnerViewSet ?search` | E4 | excluida: búsqueda para que una **persona** elija (ya filtra `is_generic=False`) |
| `patients.utils`, `organizations.signals` | A5 | excluidas: `Owner` genérico, clave `NULL`, fuera del conteo |
| `seed_demo_clinic`, `agent_eval` | A6 | excluidas: siembra single-writer sobre tenants propios |
| `PATCH /api/appointments/<id>/assign-patient/` | B5 | excluida: cambia `Appointment.pet`, no `Pet.owner` |
| Django admin | C4 | excluida: `Owner` **no está registrado**. Registrarlo lo devuelve a C1 |

### `POST /api/pets/` — dos modos explícitos

El alta de mascota **ya no infiere identidad por teléfono**. Antes resolvía el
cliente con `get_or_create(name, phone, organization)`: una segunda regla de
deduplicación que colgaba mascotas de expedientes localizados solo por
coincidencia de número (INV-B) y **fabricaba** un segundo `Owner` cuando el
teléfono coincidía pero el nombre no ("Ana López" vs "Ana Lopez").

| Modo | Cómo se pide | Qué hace |
|---|---|---|
| **referencia** | `owner_public_id` (UUID) | asocia la mascota a **ese** expediente. Elegirlo es un acto del staff, no una inferencia |
| **alta** | `owner: {name, phone}` | pasa por el servicio, bajo el lock |

Enviar ambos o ninguno → `400`. Un `owner_public_id` de otra organización →
`400` (no existe para este endpoint). En **edición** (`PATCH /api/pets/<id>/`)
`owner_public_id` está prohibido: mover una mascota de cliente es otra
operación.

Desenlaces del modo alta: 0 → crea · 1 con nombre coincidente (comparado sin
acentos ni mayúsculas) → reutiliza, **igual que hoy** · 1 con nombre distinto →
`409 owner_exists` con el candidato · ≥2 → `409 owner_ambiguous`.

La resolución del `Owner` y la creación de la `Pet` son **una sola
transacción**: no existe el estado «cliente creado, mascota no».

### Cambiar el teléfono

Mueve la clave de deduplicación. Bloquea la anterior y la nueva en orden total
—sin ese orden, dos cambios cruzados (A→B y B→A) se abortan por deadlock— y
comprueba y guarda en el mismo bloque. Con la clave nueva ocupada por 1 →
`409 owner_exists`; por ≥2 → `409 owner_ambiguous`.

Un `409` en la vía anidada (`PATCH /api/pets/`) **no deja ni el teléfono
cambiado ni los campos de la mascota guardados**: antes eran dos `save()`
sueltos.

Reformatear el mismo número (`"5512345678"` → `"55 1234 5678"`) no mueve la
clave: es una edición corriente.

### El `Owner` genérico

| Aspecto | Regla |
|---|---|
| `phone_normalized` | **`NULL`**, siempre. Nunca `''` ni `'0000000000'` |
| Deduplicación y conteo | excluido de las cuatro decisiones |
| Locks | no participa (sin clave no hay clave que bloquear) |
| Lectores de identidad | excluido: un contacto de WhatsApp jamás puede quedar vinculado al genérico por teléfono |
| Búsqueda `?search` | excluido (sigue accesible por `?is_generic=true`, venta directa / ADR p25) |
| Su `phone` de texto | se conserva tal cual |

**El teléfono del `Owner` genérico nunca es identidad.**

### Duplicados históricos

INV-C los convierte en un caso **soportado**, no en un error a erradicar.

- `python manage.py audit_owner_phone_duplicates [--org N] [--json]` los lista
  por organización (exit 0 limpio / 1 con hallazgos / 2 error). **Diagnóstico,
  no remediación**: no fusiona, no borra, no elige y no propone.
- **Ninguna migración fusiona ni borra duplicados**, ni ahora ni después. Los
  ordena una persona de la clínica con las herramientas que ya existen.
- Consecuencia aceptada: una clínica con duplicados verá `owner_ambiguous` en
  las altas contra esos teléfonos —también en su alta manual— hasta que ordene
  el dato. Mezclar dos expedientes clínicos es peor que pedir una decisión
  humana.
- **No se añade una restricción única** en ningún momento del plan.

### Datos mínimos en captura manual (regla de producto piloto)

Para que recepción capture tan rápido como en papel, el alta manual conserva solo
los datos **necesarios para operar y contactar**; el resto es opcional y se
completa después (misma filosofía que el importador: dato faltante ≠ error).

| Campo | Alta estándar `/api/pets/` | Alta rápida `create-with-patient/` | Importador |
|---|---|---|---|
| `owner.name` | requerido | requerido | requerido |
| `owner.phone` | **requerido** (10 díg) | **requerido** (10 díg) | opcional |
| `pet.name` | requerido | requerido | requerido |
| `pet.species` | opcional (`''`=pendiente) | opcional (`''`=pendiente) | opcional |
| `pet.birth_date` | opcional | opcional | opcional |
| `sex`, `breed`, `color` | opcionales | opcionales | opcionales |

- **Especie**: `PetSerializer.validate_species` y `create-with-patient/` aceptan
  vacío (`''`) → "pendiente"; si se envía un valor, debe pertenecer a
  `SPECIES_CHOICES`. Los filtros/stats ya toleran especie vacía (la produce el
  importador): `species=caninos|felinos` la excluyen; cuenta en `total`. UI
  muestra "Pendiente" (no "Sin especie").
- **Fecha de nacimiento**: opcional en los tres caminos. `PetSerializer.validate_birth_date`
  acepta `None`; si viene, no puede ser futura. El modelo mantiene `null=True`.
- **Teléfono — NO se relaja**: sigue requerido (10 díg) en ambos caminos manuales
  (`OwnerSerializer.validate_phone`). Es la identificación del cliente
  (recordatorios, WhatsApp futuro) y evita mezclar clientes homónimos en el dedup
  `get_or_create(name, phone)`. La excepción de teléfono opcional vive **solo** en
  el importador. Datos históricos sucios ≠ datos nuevos.

### Captura por WhatsApp

El asistente solo añade `pet_birth_date` como dato opcional al alta. Pregunta si
la persona conoce una fecha de nacimiento exacta o aproximada; persiste únicamente
una fecha concreta `YYYY-MM-DD` que no sea futura. Si no se conoce una fecha
concreta, el campo queda vacío: no se convierte una edad textual en una fecha
inventada. Peso y alergias quedan fuera del flujo de WhatsApp.

## Filtros disponibles (GET /api/pets/)

Todos **server-side** (la página Mascotas escala a miles de registros sin
descargar la tabla a memoria — ADR p44):

- `search=<texto>` — nombre · especie · raza · `legacy_id` (nº expediente) ·
  nombre del dueño · teléfono del dueño (todos `icontains`).
- `species=caninos|felinos` — grupo de especie (regex tolerante a datos sucios de
  importación: `perro|canino|dog` / `gato|felino|cat`).
- `sex=male|female|unknown`.
- `age=cachorro|joven|adulto|senior` — traducido a rangos de `birth_date`
  (año = 365.25 días, coherente con `getAgeGroup` del frontend; `birth_date` NULL
  queda fuera de todo bucket).
- `owner=<public_id>` — filtrar por propietario (resuelto por UUID).
- Combinables: `?search=luna&species=caninos&page=1`.

### Paginación opt-in por `?page` (ADR p44)

`PetViewSet` pagina **solo cuando el request trae `?page`** (PageNumber 25,
`page_size` 25/50/100). Sin `?page` conserva el **contrato legacy de array
plano** que consumen los dropdowns `SearchSelect` (citas, recetas, POS) y las
listas client-side (`prescriptions`, `medicalRecords`) vía
`.then(ps => ps.map(...))`:

| Request | Respuesta |
|---|---|
| `GET /pets/?page=1[&filtros]` | Envelope `{count, next, previous, results}` (vista Mascotas) |
| `GET /pets/?search=max` (sin page) | Array plano `[:20]` (dropdown) |
| `GET /pets/` (sin page, sin filtro) | Array plano completo (listas client-side) |

Romper este carve-out (paginar global) rompería 6 consumidores — mismo patrón
que el `?search` de `OwnerViewSet`.

### `GET /api/pets/stats/`

Conteos agregados de **toda la clínica** (no de la página): `{total, caninos,
felinos}` en UNA query agregada (sin N+1, sin traer filas). Alimenta los
stat-cards de la página Mascotas cuando la lista pasa a paginada. Permiso
`patient.list`. Tenant-scoped.

### Anti-N+1

El listado usa `select_related('owner')`: `PetSerializer` anida `OwnerSerializer`,
así que sin el join serializar N mascotas costaría 1 + N queries. El nº de queries
ya no escala con las filas (blindado en `test_pet_list_pagination.py`).

## Filtros disponibles (GET /api/owners/)

- `search=<texto>` — busqueda por **nombre · teléfono · `legacy_id`** (icontains;
  ADR p44b). Con clínicas importadas un cliente se diferencia por su teléfono o nº
  de expediente, no solo el nombre (homónimos). Sin `?page` → array plano `[:20]`
  (dropdown legacy); con `?page` → envelope paginado (habilita el "Ver más" de
  `EntitySearch`). Misma lógica opt-in que `Pet` (ADR p44).
- `is_generic=true/false` — filtrar propietario generico

El frontend usa `?is_generic=true` para obtener el propietario "Publico General" al cargar la vista de cobros.
El frontend usa `?is_generic=false` en el buscador de propietarios para excluir el generico de los resultados.

Desde F1 (ADR p57, E4 del inventario) el backend **también** excluye al genérico
de `?search` por su cuenta, salvo que el llamador lo pida por su condición
(`?is_generic=true`). La búsqueda existe para que una **persona** elija un
cliente; el genérico no es un cliente al que se le pueda colgar una mascota, y
su teléfono de relleno no es identidad de nadie.

### Paginación (ADR p42)

`OwnerViewSet` pagina el **listado completo** (PageNumber 25 → envelope
`{count, next, previous, results}`). Pero el path **`?search` NO se pagina**:
`paginate_queryset` devuelve `None` cuando hay `search` → respuesta array plano
`[:20]`, preservando el contrato de los dropdowns `SearchSelect` (que hacen
`.map()` directo). Orden de paginación: `name, id`. **`Pet` ahora también pagina
(opt-in por `?page`, ADR p44)** — esto **supera** DD-013 ("Pet NO se pagina"),
tomado tras importar una clínica con 1500 mascotas: el listado descargaba todo +
N+1 de owner + filtraba en memoria. Ver § Filtros disponibles (GET /api/pets/).

## Permisos RBAC

| Accion         | Codigo             |
|----------------|--------------------|
| Listar         | `patient.list`     |
| Ver detalle    | `patient.retrieve` |
| Crear          | `patient.create`   |
| Editar         | `patient.update`   |
| Eliminar       | `patient.destroy`  |

`PUT` y `PATCH` exigen el mismo código `*.update`: `_resolve_required` resuelve `partial_update` como `update`, tanto en mascotas como en clientes. No existe un código `*.partial_update`.

## Indices de busqueda

`Owner.name` y `Pet.name` tienen índice GIN trigram (`gin_trgm_ops`, extensión `pg_trgm`) desde Capa 2 (2026-05-26), para que la búsqueda `name__icontains` no haga seq scan por org. Requiere `django.contrib.postgres` en INSTALLED_APPS y la extensión `pg_trgm` en la DB (ver `DEPLOY_VPS_PLAN.md`).

Desde ADR p44b (migración 0017) hay trigram también en **`Owner.phone`**, **`Owner.legacy_id`** y **`Pet.legacy_id`**, porque la búsqueda relacional (clientes por teléfono/expediente; mascotas por expediente) ahora hace `icontains` sobre esos campos. (Antes `phone` no se indexaba: no había búsqueda por teléfono.)

## Aislamiento multitenant

Toda query sobre `Pet` y `Owner` esta limitada a `request.user.organization`.
El serializer valida explicitamente que la organizacion del usuario este asignada antes de crear una mascota.

## Alta rapida desde citas

El endpoint `POST /api/appointments/create-with-patient/` crea owner + pet + cita en una sola
transacción atómica sin pasar por el módulo de mascotas.

- El expediente lo resuelve el **servicio único** (A1·B2 del inventario), bajo el
  lock de deduplicación y dentro de la misma transacción que crea la cita.
- Si el teléfono ya tiene **un** expediente en la organización se reutiliza
  (cliente que regresa con mascota nueva) — salvo que el llamador envíe
  `require_new_owner`.
- La mascota siempre se crea nueva.
- **`require_new_owner`** (bool, opt-in, default `false`): INV-B aplicado. Lo
  envía quien **no** tiene identidad verificada —el agente— para que el dominio
  se niegue a colgar una mascota nueva de un expediente ajeno. Con un
  expediente existente responde `409 owner_exists` **con el candidato** y cero
  escrituras. Un valor que no sea `true`/`false` es `400`: interpretarlo como
  `false` relajaría la protección justo para quien la necesita, y en silencio.
- **`409 owner_ambiguous`** con dos o más expedientes, **con o sin el flag**.
- Los dos 409 no dejan **nada**: ni `Owner`, ni `Pet`, ni `Appointment`, y no
  modifican el expediente que encontraron.
- Toda la validación de la cita (conflictos, fecha pasada, timezone) se delega al
  `AppointmentSerializer` existente dentro del mismo `transaction.atomic()`.

Esto no reemplaza el módulo Mascotas para altas completas (raza, color, historial previo).
Es un flujo de mínimo viable para no interrumpir la agenda.

## Relacion con otros modulos

- **Citas**: `Appointment.pet` es FK obligatoria PROTECT (puede ser genérica en walk-in anónimo)
- **Historial clinico**: `MedicalRecord.pet` es FK obligatoria **PROTECT** (PR-4B)
- **Cobros**: `Invoice.owner` PROTECT obligatoria; `Invoice.pet` PROTECT nullable cuando `owner.is_generic = True`
- **Vacunas**: `VaccineRecord.pet` es FK **PROTECT** (PR-4B) — ver modulo de historial clinico
- **Recetas**: `Prescription.pet` es FK **PROTECT** (PR-4B) — ver modulo de prescripciones
- **Importador** (`apps/imports`, Sprint import): crea `Owner` + `Pet` por lote desde CSV/Excel vía `.save()` directo (no pasa por los serializers manuales). Es la razón de `phone = blank=True` y de los campos `legacy_id`. Dedup por teléfono (owner) y por nombre normalizado (pet); teléfono y fecha de nacimiento opcionales en este camino.

## Datos del sistema anterior (`extra_data`, Sprint import Fase D — ADR p43)

`Owner.extra_data` y `Pet.extra_data` preservan las columnas del Excel/CSV que **no
tienen un campo equivalente** en el modelo (ej. "Veterinario favorito", "Última
estética", "Código viejo"). Es **dato histórico de migración**, NO custom fields:

- **Forma**: lista ordenada de `{label, value, source_column, imported_at}`.
  - `label` — nombre visible elegido durante la importación (renombrable en el mapeo).
  - `value` — valor importado (texto plano; trim + cap 500 chars).
  - `source_column` — nombre **original** de la columna del archivo. Renombrar el
    `label` NO lo cambia → siempre se sabe de dónde vino el dato.
  - `imported_at` — fecha del proceso de importación (ISO, una marca por job).
- **Caps**: 50 entradas/registro, value 500, label 120, source_column 120.
- **Read-only**: `read_only` en `OwnerSerializer`/`PetSerializer`. Lo escribe **solo**
  el importador (`apps/imports`); la edición manual de la ficha lo ignora. Sin
  endpoints de edición.
- **No es queryable**: solo display (ficha del paciente, sección "Datos importados
  del sistema anterior"). NO se usa en búsquedas, reportes ni reglas de negocio
  (billing/analytics/caja nunca lo leen).
- **Promoción a feature**: si varias clínicas necesitan un dato concreto, se crea una
  feature real (modelo + validación + writer + migración desde `extra_data`); no se
  introducen EAV ni campos dinámicos. Ver ADR p43.

Sin `bleach`: texto plano + cap de longitud (React escapa al renderizar; el origen
es Excel, no HTML).

### Datos opcionales incompletos (post-importación, ADR p44d)

Distinto de `extra_data`. Tras importar, una mascota puede quedar sin campos
**opcionales** del modelo (fecha de nacimiento, especie, raza, sexo, color;
teléfono del dueño). NO son errores ni bloquean — son normales en veterinaria.
Estrategia **C+D**, sin alertas globales:

- **C — resumen al importar** (`ResultStep`): agrega los warnings ("N mascotas sin
  fecha de nacimiento", etc.), una sola vez.
- **D — prompt suave en la ficha** (`petDetail`): botón discreto "Completar datos
  (…)" cuando faltan opcionales → abre la edición vía `/pets?edit=<public_id>`
  (la página Mascotas resuelve el `?edit` cargando la mascota por `public_id` y
  abriendo el modal). Sin contador global ni "score de completitud".

Requerido-para-operar (nombre) ≠ deseable (lo demás): nunca se tratan igual.

## Cascade lockdown (PR-4B / ADR p16)

`Pet.owner` paso de CASCADE a PROTECT. Justificacion: borrar un Owner cascadeaba todas sus Pets → MedicalRecords → todo el historial clinico (violacion NOM-046, retencion 5 anos).

Las FK PROTECT siguen vigentes, pero desde el orden 2 (A5, 28-10-2026) `DELETE` ya no borra: **archiva**. Antes respondía `409 resource_has_dependencies` cuando había mascotas o historial.

## Archivo y restauración de clientes y mascotas (orden 2, A5)

Un único servicio, `apps/patients/archive.py::change_archive_state`, para la clínica y para plataforma. Nunca borra físicamente.

| Ruta | Efecto |
|---|---|
| `DELETE /api/owners/<public_id>/` o `POST .../archive/` | Archiva el cliente y todas sus mascotas → `204` (o `200` con el cliente en `archive`). |
| `DELETE /api/pets/<public_id>/` o `POST .../archive/` | Archiva la mascota. |
| `POST /api/owners/<public_id>/restore/` y `POST /api/pets/<public_id>/restore/` | Restaura. Las mascotas del cliente no se restauran con él: se restauran una a una. |
| `GET /api/pets/?archived=true` y `GET /api/owners/?archived=true` | Lista los archivados. |

Reglas:

- Solo el ADMIN de la clínica, o un operador de plataforma. Los demás roles reciben `403`, también al listar archivados.
- `409 archive_blocked` si alguna mascota afectada tiene citas `scheduled`, `confirmed` o `in_progress`, o consultas `open`; si la organización está desactivada; o si el sujeto es genérico. El `DELETE` de un genérico sigue respondiendo `409 generic_resource_protected`.
- Restaurar una mascota exige que su cliente esté activo.
- Archivar libera el teléfono del cliente para INV-C, porque el resolvedor solo ve clientes activos. Restaurarlo lo vuelve a ocupar: si otro cliente lo tomó mientras tanto, responde `409 owner_exists` u `owner_ambiguous`, igual que al cambiar el teléfono.
- Los listados normales y el manager por defecto solo ven activos (`is_active=True`); `all_objects` ve todo.
- Cada archivo guarda `archived_at` y `archived_by` (`patients.0020`).

El borrado físico existe solo como operación excepcional de plataforma, sobre sujetos ya archivados ([platform.md](platform.md)). Facturas, expedientes y recetas conservan la identidad del sujeto en `subject_snapshot`.

En el frontend, Mascotas tiene «Ver archivadas», «Restaurar», «Archivar cliente» y una lista paginada de clientes archivados para quien tiene `owner.destroy`. Pruebas: `patients.tests.test_order2_archive` y `pets.test.jsx`. Expediente: [orden 2](../remediaciones/orden-2/README.md).
## Registro individual autorizado B8E (2026-09-25)

El POST humano de mascotas y REGISTER_PET comparten `apps.patients.creation`:
nombre validado/recortado, especie opcional de catálogo normalizada, nacimiento
opcional no futuro según fecha local, full_clean, tenant y auditoría del modelo.
El servicio recibe owner exacto; el modo humano de alta anidada conserva su
resolución explícita previa. Bloquea Organization y Owner FOR SHARE, en ese orden.
La precondition del agente usa Owner NOWAIT para evitar un ciclo con el signal
humano de cambio de teléfono, que puede revocar ContactIdentity bajo lock de Owner.
Una edición concurrente causa rechazo temporal antes del INSERT; las altas de
mascotas distintas mantienen locks compartidos compatibles.
No hay deduplicación global por nombre/especie. Dos mascotas homónimas son válidas.

El adapter requiere binding/identidad/consentimiento persistidos y solo admite
owner_id/name, species/birth_date opcionales. Los campos omitidos conservan los
defaults reales: species='', birth_date=NULL, sex=unknown, breed/color='',
is_generic=False, is_active=True, legacy_id='', extra_data=[]. No infiere datos
clínicos ni crea owner/cita/historial/vacuna/factura. El alta Pet no tiene signals
que generen esos registros; auto_create_medical_record=False se conserva.

`PetRegistrationEffect` guarda operación UUID única, Pet exacto único, owner,
tenant, digest, definición original y fecha transaccional. El trigger protege
inmutabilidad y concordancia al insertar. El Pet sigue editable: un retry reconoce
su creación histórica sin restaurar valores anteriores. Humanos, importadores y
legacy siguen sin evidencia del agente; no hay backfill ni cambios en sus reglas
específicas de importación. Rollback funcional cierra el adapter sin borrar negocio.

Producción OFF, B0 cerrado, PENDING_ACTIVATION_REQUIREMENTS. Véase
[contrato B8E](../contrato-register-pet-b8e.md) y
[aceptación](../implementacion-b8e-agente-whatsapp-2026-09-25.md).
