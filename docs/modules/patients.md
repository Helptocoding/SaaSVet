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
- `phone` — telefono de contacto (10 digitos en alta manual; `blank=True` a nivel modelo — ver excepción del importador abajo)
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
- `species` — especie (valor de `SPECIES_CHOICES`)
- `breed` — raza (texto libre, opcional)
- `birth_date` — fecha de nacimiento (obligatoria en el alta vía `PetSerializer`; **opcional** en el alta rápida vía `create-with-patient/` — ver Validaciones)
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

Regex: `^\d{10}$`

Solo digitos, exactamente 10. No se valida para propietarios con `is_generic = True`.

### Fecha de nacimiento

Obligatoria en `PetSerializer` (alta estándar `/api/pets/`) para registros nuevos.
El modelo mantiene `null=True` para no forzar migracion de datos historicos.

**Divergencia por camino de alta:** el alta rápida `POST /api/appointments/create-with-patient/`
trata `pet_birth_date` como **opcional** (`request.data.get('pet_birth_date') or None`) —
crea la mascota sin fecha si no se envía. El importador (`apps/imports`) tampoco la exige.
Solo el alta estándar vía `PetSerializer` la obliga. (Relevante para flujos de alta rápida
donde el dueño no recuerda la fecha exacta.)

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

## Indices de busqueda

`Owner.name` y `Pet.name` tienen índice GIN trigram (`gin_trgm_ops`, extensión `pg_trgm`) desde Capa 2 (2026-05-26), para que la búsqueda `name__icontains` no haga seq scan por org. Requiere `django.contrib.postgres` en INSTALLED_APPS y la extensión `pg_trgm` en la DB (ver `DEPLOY_VPS_PLAN.md`).

Desde ADR p44b (migración 0017) hay trigram también en **`Owner.phone`**, **`Owner.legacy_id`** y **`Pet.legacy_id`**, porque la búsqueda relacional (clientes por teléfono/expediente; mascotas por expediente) ahora hace `icontains` sobre esos campos. (Antes `phone` no se indexaba: no había búsqueda por teléfono.)

## Aislamiento multitenant

Toda query sobre `Pet` y `Owner` esta limitada a `request.user.organization`.
El serializer valida explicitamente que la organizacion del usuario este asignada antes de crear una mascota.

## Alta rapida desde citas

El endpoint `POST /api/appointments/create-with-patient/` crea owner + pet + cita en una sola
transacción atómica sin pasar por el módulo de mascotas.

- Si el teléfono del dueño ya existe en la organización, se reutiliza el owner (cliente que
  regresa con mascota nueva).
- La mascota siempre se crea nueva.
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

Comportamiento DELETE actual:
- `DELETE /api/owners/<public_id>/` con pets asociadas → **409 Conflict** con shape canonico `{code: 'resource_has_dependencies', message, protected_count, protected_count_truncated, protected_sample}` (handler bounded probe `[:6]`).
- `DELETE /api/pets/<public_id>/` con historial (MR/vaccines/prescriptions/appointments/invoices) → **409 Conflict** mismo shape.
- Pet generico (`is_generic=True`) → **409 Conflict** con `code: 'generic_resource_protected'` (guard explicito antes del PROTECT-bound DB error).
- Owner generico (`is_generic=True`) → **409 Conflict** mismo guard.

Frontend pivotara a "Archivar/Desactivar" usando `is_active=False` (separate PR). Soft-delete real es deuda Fase 2 A5.
