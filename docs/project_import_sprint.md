# Sprint: Importador CSV/Excel (migración de clínicas)

> **Estado (15-11-2026):** implementado. El importador de clientes y mascotas existe desde `c0ff207` (14-06, Fase A); lo describen [ADR p43](decisions/2026-06-16-p43-importador-csv-excel.md) y [imports.md](modules/imports.md). Este documento es el plan original: sus estados internos («sin implementar», «PLAN») son los de su fecha.

**Fecha**: 2026-06-14
**Estado**: PLAN — investigación cerrada, sin implementar.
**Audiencia**: dev que implemente el importador, QA, PO.
**Alcance**: permitir que una clínica nueva migre clientes + mascotas desde Excel/CSV
sin captura manual. Pre-beta.

> Modo de la sesión que generó esto: **investigación únicamente**. Este documento es
> spec, no código. No crear modelos/migraciones/endpoints hasta aprobar Fase A.

---

## 0. Decisiones finales (cerradas con el PO)

| # | Decisión | Elegido | Razón |
|---|---|---|---|
| D1 | Sesión de import | **`ImportJob` persistido** (filas en JSONField, sin binario) | Auditoría, no reenvía miles de filas, reanudable. Encaja con cultura audit-trail. |
| D2 | Alcance v1 (Fase A) | **Clientes + Mascotas** (`entity_type=owner_pet`) | Las clínicas migran ambos juntos; un archivo trae dueño y mascota. |
| D3 | Duplicados v1 | **Saltar + reportar** (`skip`); `update` diferido a Fase B | Cero riesgo de pisar datos buenos. |
| D4 | Cliente sin teléfono | **Permitido** (no es error). Ver Ajuste #1. | Excels reales vienen incompletos; "sin tel = error" arruina la primera experiencia. |
| D5 | Formatos en Fase A | **CSV + XLSX desde el inicio** (`openpyxl`). Ver Ajuste #2. | El usuario dice "te mando mi Excel", no "mi CSV". |
| D6 | Nombre de archivo | **Guardar `original_filename`** en `ImportJob` (NO el binario). Ver Ajuste #3. | Trazabilidad: "¿cuál archivo subieron?". |
| D7 | `legacy_id` | **SÍ — Fase A.** Campos en `Owner`/`Pet`. Ver §11. | El importador existe para migrar clínicas; meterlo después obliga a re-importar/actualizar miles de pacientes para recuperar los IDs viejos. UI lo muestra como "Número de expediente anterior", no como `legacy_id`. |

---

## Estado de implementación

**Fase A IMPLEMENTADA 2026-06-14 (sin commit).** Backend 17 tests verdes + 18
patients/appointments sin regresión; frontend 128 tests verdes (16 nuevos). Pasó
code-review (1 BLOCKER + 2 HIGH + 2 MEDIUM corregidos).

- Backend: app `apps/imports/` (ImportJob, parsers CSV+XLSX, normalization,
  services validate/commit, ImportJobViewSet, router `imports`). `legacy_id` en
  Owner+Pet (unique parcial per-org). `Owner.phone` → `blank=True`.
  `import.{list,retrieve,create,commit}` (ADMIN only). `openpyxl` añadido.
- Frontend: `pages/imports/` (wizard 4 pasos) + `api/imports.js` + ruta `/imports`
  ADMIN-only + nav en Sidebar.
- **Decisión tomada en implementación**: `OwnerSerializer.validate_phone` ahora
  acepta teléfono vacío (coherente con phone opcional) → el alta/edición manual de
  cliente en la UI ya NO exige teléfono. Si se prefiere mantenerlo obligatorio en
  el alta manual, revertir solo ese serializer.
- Review fixes: savepoints owner/pet separados (no huérfanos), `validate` predice
  conflictos `legacy_id` (preview honesto), mensajes de error no filtran el nombre
  del constraint, `check_mapping` rechaza dos columnas al mismo campo, dedup v1
  restringido a `skip`.
- Deuda v1 aceptada (LOW): fecha DD/MM asumida (warning si no parsea), CSV se
  materializa en memoria (acotado por cap 5 MB), `validate`/`mapping` sin throttle
  dedicado (ADMIN only).

---

## 1. Estado actual del proyecto

**No existe infraestructura de import.** Confirmado por inspección:

- Sin libs de parsing: `requirements.txt` solo trae `reportlab`/`pypdf` (PDFs). No `csv` config, no `openpyxl`, no `pandas`.
- Sin `ImportJob`, sin `FileField`, sin `MEDIA_ROOT`/`MEDIA_URL`, sin `MultiPartParser` global.

**Precedente reutilizable (el patrón ya está inventado):**

| Pieza | Ubicación | Qué aporta |
|---|---|---|
| `create_with_patient` (FBV atómico) | `apps/appointments/views.py:270` | Plantilla exacta: `Owner.objects.get_or_create(org, phone)` + `Pet.create` en `transaction.atomic`, reusa serializers, rollback total si falla. |
| `OwnerSerializer` / `PetSerializer` | `apps/patients/serializers.py` | Validación lista: `NAME_REGEX`, `PHONE_REGEX` (10 díg), `SPECIES_CHOICES`. |
| `OrganizationalModel.save()` | `apps/core/models.py:168` | `full_clean()` centralizado + auditoría `created_by`. **`bulk_create` lo bypasea** (descartado, ver §7). |
| Exception handler | `apps/core/exceptions.py` | Shape canónico `{code, message}` / `{code:'validation_error', errors:{}}`, meta vía prefijo `__`. |
| Throttle scoped | `apps/core/throttling.py` + `settings.py` (`platform_org_create: 20/hour`) | Patrón para operación cara. |
| RBAC | `apps/core/permissions_codes.py` | Códigos `resource.action`; `seed_permissions` corre en cada deploy. |
| Partial `UniqueConstraint` | `apps/patients/models.py:21,63` | Precedente para uniques condicionales (usado por `legacy_id` §11). |

**Campos / unicidad / relaciones (de modelos + serializers):**

- **Owner**: `name` req (regex), `phone` req-en-serializer (10 díg). Dedup de facto = `(org, phone)` vía `get_or_create`. **NO existe `UniqueConstraint(org, phone)` en DB** (relevante §6/§7).
- **Pet**: `name` req (regex), `species` req (∈ `SPECIES_CHOICES`, minúsculas), `owner` FK **PROTECT** req. `birth_date`: el **modelo permite `null`**, pero `PetSerializer.validate_birth_date` lo **exige** → discrepancia a relajar en el path de import.
- **Product**: stock NO se setea por campo directo (ADR p31: `apply_stock_movement` bajo lock, unidades base, multi-presentación) → import de productos es Fase C, mínimo.

---

## 2. Arquitectura recomendada

Síncrono, sin workers, con `ImportJob` como sesión persistida. Para clínicas
pequeñas/medianas (cientos a ~2000 filas) no se justifica Celery ni storage externo.

Flujo de 3 fases sobre un `ImportJob`:

```
POST /api/imports/                       (multipart: archivo + entity_type)
   → parsea headers + filas → ImportJob.rows (JSONField)
   → guarda ImportJob.original_filename
   → auto-detecta mapping sugerido (heurística por alias, NO IA)
   → { public_id, columns, sample_rows, suggested_mapping }
   status: pending

PATCH /api/imports/<public_id>/mapping/  (mapping confirmado por el usuario)

POST  /api/imports/<public_id>/validate/ (DRY-RUN: valida fila×fila, NO escribe)
   → { would_create, duplicates[], warnings[], errors:[{row, field, message}] }
   status: validated

POST  /api/imports/<public_id>/commit/   (escribe en transaction.atomic)
   → { created, skipped, errors }
   status: committed   (idempotente: re-commit → 409)
```

**Por qué `ImportJob` y no stateless:** evita reenviar miles de filas 3 veces, da
auditoría, reanudable. **No se persiste el binario** — solo las filas parseadas en
`JSONField` + el `original_filename`.

**Parsing — interfaz de parser (clave para Ajuste #2):**

```
ParserBase.parse(file) -> (columns: list[str], rows: list[list])
├── CSVParser     (csv stdlib; detecta separador , vs ; y encoding UTF-8/BOM/Latin-1)
└── ExcelParser   (openpyxl, read_only=True; .xlsx)
```

Selección por extensión + content-type. Caps duros: tamaño ≤ 5 MB, filas ≤ 2000,
columnas ≤ 50. Validar MIME antes de procesar.

**Commit fila×fila (no `bulk_create`):** reusa `serializer.save()` → `full_clean()` →
validación tenant. Más lento pero seguro; a cientos de filas es aceptable.

---

## 3. Modelos nuevos

Uno: **`ImportJob`** (app nueva `apps/imports/`).

```
ImportJob(PublicIdMixin, OrganizationalModel)
  entity_type       CharField  choices: owner_pet | owner | product
  status            CharField  choices: pending | validated | committed | failed
  original_filename CharField  # D6 — ej. "clientes_veterinaria_junio.xlsx" (NO el binario)
  source_columns    JSONField  # headers crudos
  rows              JSONField  # filas parseadas (cap 2000)
  mapping           JSONField  # { "Dueño": "owner.name", "WhatsApp": "owner.phone" }
  dedup_strategy    CharField  choices: skip (default) | update | create_anyway
  result            JSONField  # { created, skipped, errors[] } tras commit
  # organization (PROTECT), created_by (SET_NULL), created_at heredados
```

**Migración**: modelo nuevo, **cero impacto en datos existentes**, sin FK riesgosas.
`JSONField` nativo Postgres. Sin backfill.

---

## 4. Endpoints

| Método | Ruta | Permiso | Throttle |
|---|---|---|---|
| `POST` | `/api/imports/` | `import.create` | scoped `import_upload: 20/hour` |
| `GET` | `/api/imports/` · `/api/imports/<public_id>/` | `import.list` · `import.retrieve` | default |
| `PATCH` | `/api/imports/<public_id>/mapping/` | `import.create` | default |
| `POST` | `/api/imports/<public_id>/validate/` | `import.create` | default |
| `POST` | `/api/imports/<public_id>/commit/` | `import.commit` | scoped + `X-Idempotency-Key` |

- `ViewSet` con `PublicIdLookupMixin` + `TenantQueryMixin` → lookup por `public_id`
  dentro del queryset de la org (cross-org = 404 automático).
- Códigos nuevos en `permissions_codes.py`: `import.create`, `import.list`,
  `import.retrieve`, `import.commit`. **Solo `ADMIN` en v1.** `seed_permissions` corre en cada deploy.
- `MultiPartParser` solo en el endpoint de upload (no global).

---

## 5. Cambios frontend

Wizard nuevo, **ADMIN only**, en `/config` o ruta `/imports`. Referencia: `inventory.jsx`.

```
pages/imports/
├── index.jsx        — stepper (estado + ImportJob public_id)
├── UploadStep.jsx   — drag-drop archivo (.csv/.xlsx) + selector entity_type
├── MappingStep.jsx  — tabla columna→campo (agrupado Cliente | Mascota) + preview filas
├── PreviewStep.jsx  — dry-run: "X se crearán · Y duplicados · errores/warnings por fila"
└── ResultStep.jsx   — creados/saltados/errores + link a ver registros
api/imports.js       — uploadImport / setMapping / validateImport / commitImport
```

Reusar (no duplicar): `apiError`, `handleFormError`, `toast.promise`, `useConfirm`
(commit = acción de peso), `Pagination` (preview grande). Cero matemática/validación de
negocio en React — backend es la fuente de verdad.

---

## 6. Multi-tenant + Duplicados

**Multi-tenant:**
- `organization` SIEMPRE de `request.user.organization`, nunca del archivo/payload.
- `ImportJob.objects.for_organization(org)`; commit fuerza `organization=org` en cada Owner/Pet.
- Reusar serializers con `context={'request': request}` → validación tenant ya aplica.

**Duplicados v1 = `skip` + reportar (D3 + Ajuste #1):**

| Caso | Comportamiento |
|---|---|
| Owner con `phone` válido (10 díg) | Dedup por `(org, phone)`. Existe ⇒ se **reusa** (no se salta; se liga la mascota nueva), como `create_with_patient`. |
| Owner **sin** `phone` | **Se importa** (no es error). `dedup_key = null`. Dedup solo por nombre normalizado dentro del MISMO archivo (Ajuste #1). |
| Pet `(owner, normalize(name), species)` ya existe | Se **salta** esa fila + se reporta. Dedup por nombre **normalizado**, no string exacto: `"Max" == "MAX" == "max "`. Evita duplicar en re-imports y por mayúsculas del sistema viejo. |

---

## 7. Riesgos

1. **Sin workers → archivo grande bloquea worker gunicorn.** Mitigación: caps duros (5 MB / 2000 filas), validar antes de procesar.
2. **Owner dedup sin `UniqueConstraint(org, phone)` en DB.** App-level; race posible. En import de un solo actor el riesgo es bajo. Documentar; no agregar constraint en este sprint.
3. **`birth_date`**: `PetSerializer` lo exige, modelo no. El path de import valida con regla propia relajada.
4. **Productos = trampa de complejidad** (ADR p31): stock vía `apply_stock_movement`, multi-presentación, `internal_code` único. Stock inicial = ajuste, no set directo. → Fase C mínimo.
5. **`bulk_create` bypasea `full_clean()`** → descartado; `save()` fila×fila.
6. **CSV injection / HTML en celdas**: `bleach` (ya disponible) antes de persistir; prefijar celdas que empiezan con `= + - @` si se re-exporta.
7. **Encoding/separador es-MX**: Excel mexicano exporta `;` y Latin-1 → detección robusta o el archivo se parsea como una sola columna.

---

## 8. Qué NO hacer en v1

- Workers async / Celery / colas.
- IA para detección de columnas (heurística por alias basta).
- Import de productos con stock/multi-presentación completo (Fase C, mínimo).
- Millones de filas / streaming / chunking.
- Undo / rollback selectivo post-commit.
- Merge "inteligente" de duplicados (solo `skip` v1; `update` Fase B).
- Import de historiales médicos / facturas / citas (inmutables, FK complejas).
- Múltiples archivos / ZIP / plantilla de mapping reutilizable.

---

## 9. Tests necesarios

**Backend** (prioridad: lo que escribe datos / cruza tenant):
- Parsing CSV (`;`, BOM, Latin-1, celdas vacías) + XLSX (openpyxl) + archivo corrupto → error limpio.
- Auto-map alias ("Dueño"/"Cliente"→`owner.name`, "WhatsApp"/"Celular"→`owner.phone`, "Perro"→species).
- `validate` (dry-run): **no escribe nada** (assert count DB sin cambios), errores/warnings por fila.
- `commit`: atómico (rollback), dedup `skip`, owner con/sin phone, species normalizada,
  pet dedup por `(owner, normalize(name), species)` (`"Max"=="MAX"`).
- `legacy_id`: unicidad per-org cuando presente (dos `"123"` en la org → error; muchos
  `""` → OK); cross-org mismo `legacy_id` permitido; importable + buscable.
- Multi-tenant: job de otra org → 404; registros con `organization` correcta.
- Permisos: no-ADMIN → 403. Límites: archivo > cap, > 2000 filas → 400. Idempotencia: doble commit → 409.

**Frontend** (Vitest+RTL, gate CI bloqueante):
- MappingStep: cambiar `<select>` actualiza mapping observable.
- PreviewStep: render de duplicados/errores/warnings desde dry-run.
- Gating por `can('import.commit')`.

---

## 10. Fases + esfuerzo

| Fase | Contenido | Esfuerzo (1 dev) |
|---|---|---|
| **A** | `ImportJob` + parser CSV **+ XLSX** + 3 endpoints + `owner_pet` (owner dedup por phone, owner sin phone permitido, pet ligada, normalización species, dedup pet por nombre normalizado) + **`legacy_id` en Owner/Pet** + dedup `skip` + permisos ADMIN + wizard 4 pantallas + `original_filename` + tests | **~1.5–2 sem** |
| **B** | Estrategia `update` + descarga de reporte de errores + dedup contra owners existentes sin phone (cross-archivo) | **~3–4 d** |
| **C** | Productos mínimo (sin multi-presentación, stock vía ajuste) + historial de imports UI + mejoras auto-map | **~1 sem** |

Total **~3 semanas**.

---

## Ajustes del PO sobre el plan original

### Ajuste #1 — Cliente sin teléfono permitido (con cuidado)

Plan original: "fila sin phone ⇒ error". **Rechazado.** Excels reales vienen
incompletos (ej. `Juan Pérez | <vacío>`); "sin tel = error" produce 120/500 errores y
mala primera experiencia.

**Comportamiento v1:**
- Con teléfono → dedup por `(org, phone)`.
- Sin teléfono → **importar**, `dedup_key = null`.
- Evitar duplicados internos por **nombre normalizado dentro del mismo archivo**:
  `normalize(name)` = lower + trim + colapsar espacios + quitar acentos.
  `"Juan Pérez" == "juan perez" == "JUAN PEREZ"` → agrupar/avisar (warning, no error).
- **No** requiere DB constraint todavía — es comportamiento del importador.

### Ajuste #2 — XLSX desde Fase A (no Fase B)

Plan original: CSV en A, XLSX en B. **Cambiado.** El usuario promedio dice "te mando mi
Excel", no sabe qué es CSV. `openpyxl` no agrega mucha complejidad si el parser ya es
una interfaz (`ParserBase` → `CSVParser` | `ExcelParser`). Hacerlo ahora.
Fase A: ✅ CSV ✅ XLSX.

### Ajuste #3 — Guardar nombre original del archivo

`ImportJob.original_filename` (CharField). **No** guardar el binario. Solo el nombre
(ej. `clientes_veterinaria_junio.xlsx`) para responder "¿cuál archivo subieron?".

---

## 11. `legacy_id` — confirmado en Fase A (D7)

**Decisión del PO: SÍ, desde Fase A.** Razón: el importador existe precisamente para
migrar clínicas que vienen de otro software / Excel viejo / libretas digitalizadas. Esos
sistemas traen su propio número de expediente:

```
Expediente | Paciente | Dueño
00231      | Max      | Juan
00232      | Luna     | Ana
```

Al migrar, la DB genera `Pet(id=99384, public_id=pet_8x71s, name="Max")` — correcto
internamente, pero el veterinario pregunta *"búscame el expediente 231"*. Sin `legacy_id`
ese vínculo se pierde. Meterlo **después** es peor: importas 5000 pacientes en Fase A y
luego, para recuperar los IDs viejos, tienes que re-importar o actualizar todo. Se hace
ahora.

**Objetivo**: preservar el identificador antiguo. **NO** es PK, **NO** reemplaza
`id`/`public_id`. Solo dato de referencia importable y buscable.

**Campos**: `Owner.legacy_id`, `Pet.legacy_id`.

**Requisitos**: opcional · único dentro de la organización cuando presente · importable
desde Excel · visible/buscable si existe.

**Impacto de schema (reportado ANTES de implementar, según regla de migraciones):**

- **Cambio**: `legacy_id = CharField(max_length=64, blank=True, default="")` en `Owner` y
  `Pet` (`apps/patients/models.py`). **`default=""`, NO `null=True`** (confirmado por PO).
- **Unicidad condicional**: `UniqueConstraint(fields=['organization','legacy_id'],
  condition=~Q(legacy_id=''), name='owner_legacy_id_unique_per_org')` (ídem Pet).
  Permite muchos `legacy_id=""` coexistiendo (Max="" y Luna="" OK), pero bloquea dos
  `legacy_id="123"` en la misma org. **Precedente directo**: `patients/models.py:21,63`
  ya usa partial `UniqueConstraint` con `condition=Q(...)`.
- **Migración**: columna con `default=""` (constante → fast en Postgres, sin reescritura) +
  índice único parcial. Tablas pequeñas por tenant → bloqueo despreciable. Filas
  existentes → `""` (compatibles).
- **Serializers/Views**: `legacy_id` a `OwnerSerializer`/`PetSerializer` (read+write
  opcional). Búsqueda: extender `?search` o `?legacy_id=` exacto (el índice único ya sirve
  el lookup exacto; substring necesitaría índice propio — evaluar si hace falta).
- **UI (ajuste del PO)**: **NUNCA** mostrar el label "legacy_id" — el usuario normal no
  sabe qué es. Mostrar **"Número de expediente anterior"** (o "Código anterior").
  Internamente el campo se llama `legacy_id`; es solo el label visible y el alias de
  auto-mapping de columnas ("Expediente", "No. Cliente", "Código" → `*.legacy_id`).
- **Riesgo**: bajo. Aditivo y compatible. Toca 2 modelos core (`patients`) → registrar
  una mini-decisión (no ADR formal completo; calibración de governance del proyecto).

---

## Fase D — Información del sistema anterior (`extra_data`) + rediseño del mapeo

**Estado**: PLAN aprobado por el PO (2026-06-15). Se implementa como **paquete
completo** (backend + display + rediseño UX juntos). Razón del PO: implementar
`extra_data` con el selector actual reforzaría un flujo ya comprobado como confuso.

**Problema**: las clínicas traen columnas que no existen en el modelo (Fecha Alta,
Última vacuna, Observaciones, Comentarios, Código antiguo). Hoy solo se pueden mapear a
campos del sistema o ignorar → pérdida de información histórica.

### D.1 Modelo / Backend

- `Owner.extra_data` y `Pet.extra_data` = `JSONField(default=list, blank=True)`.
- **Shape = LISTA de objetos** (ajuste #2 del PO), NO dict:
  ```json
  [ {"label": "Fecha Alta", "value": "2018"},
    {"label": "Comentario", "value": "A"},
    {"label": "Comentario", "value": "B"} ]
  ```
  Razón: es para **mostrar, no consultar** (ficha del paciente, no `WHERE extra_data->>...`).
  La lista preserva el **orden original** de las columnas y admite **labels repetidos**
  de forma natural (dos "Comentario" conviven sin inventar sufijos).
- **Sin EAV, sin columnas dinámicas.** No indexado/queryable en v1 (solo display). Si en
  el futuro hace falta buscar por "Última vacuna" → rediseño aparte (no v1).
- **Caps** (anti-basura): máx. ~30 entradas por registro, `value` truncado a ~500 chars.
- **Sin `bleach`** (ajuste #4 del PO): se guarda **texto plano**; React escapa al
  renderizar y un Excel no debería generar HTML. No se procesa HTML ni se añade lógica de
  sanitización extra (más allá de trim + cap de longitud).

`normalization.FIELD_CATALOG` — dos targets nuevos (`isExtra: true`):
- `owner.extra` → "Dato del cliente" · group Cliente · optional.
- `pet.extra` → "Dato de la mascota" · group Mascota · optional.

**Reglas de mapeo:**
- Campos del sistema → **1:1** (`check_mapping` rechaza duplicados, como hoy).
- `*.extra` → **muchas columnas → un target** (exentos del dedup); cada columna aporta una
  entrada `{label, value}` a la lista del registro.
- `""` = no importar.
- **NO hay default automático a `pet.extra`** (ajuste #1 del PO — rechazado el default que
  proponía el plan original). Una columna desconocida queda **"Pendiente de decidir"**: el
  usuario elige explícitamente Cliente / Mascota / No importar. El frontend **bloquea
  continuar** mientras haya columnas pendientes — no por ser obligatorias, sino por
  **consentimiento** (evita meter "Facebook" o "Adeudo" en la mascota por inercia). El
  backend no necesita estado "pendiente": el mapping que llega ya trae cada columna
  decidida u omitida.

`services` (validate/commit): columnas → `owner.extra`/`pet.extra` se acumulan en la lista
`extra_data` del registro respectivo, en orden, con `{label: <columna>, value: <celda>}`
(trim + cap). `validate` lo previsualiza sin escribir.

`serializers`: exponer `extra_data` (read-only) en `OwnerSerializer` + `PetSerializer`.
Edición manual de `extra_data` = fuera de v1.

### D.2 Migración
- `patients/00XX`: add `Owner.extra_data` + `Pet.extra_data` (`JSONField`, `default=list`,
  `blank=True`). Aditiva, sin backfill, filas existentes → `[]`. Mismo perfil que 0013–0015.

### D.3 Display en ficha (`petDetail.jsx`, tab "Información")
- Nueva sección **"Datos importados"** (ajuste #3 del PO — NO "Información adicional", que
  suena genérico; alterna "Información del sistema anterior"). Se renderiza como filas
  label/value (`.info-row`) bajo la card de mascota (`pet.extra_data`) y bajo la de
  propietario (`owner.extra_data` vía `pet.owner.extra_data`). Oculta si vacío.
  ```
  Información del sistema anterior
    Fecha Alta       12/01/2017
    Última vacuna    Rabia 2023
    Notas            Nervioso
  ```

### D.4 Rediseño del mapeo (UX) — VA EN ESTE PAQUETE (ajuste #5 del PO)
Eliminar el `<select>` gigante y el lenguaje técnico. Dos tratos visuales por columna:

- **Columna reconocida** → línea confirmada + cambiar:
  ```
  Dueño   ✓ Se importará como «Nombre del cliente»   [ Cambiar ]
  ```
- **Columna desconocida** → pregunta con lenguaje humano (NO "Campo del sistema /
  Información adicional / No importar"):
  ```
  ¿Qué hacemos con «Fecha Alta»?   (ej: 12/01/2017, 15/03/2019)
    ○ Guardarlo como dato del cliente
    ○ Guardarlo como dato de la mascota
    ○ No necesito esta columna
  ```
- "Cambiar" en una reconocida abre el **picker compacto con búsqueda** (solo campos del
  sistema, agrupados Cliente/Mascota) — reemplaza el select largo; también permite mandarla
  a dato del cliente/mascota o no importar.
- **Bloqueo de continuar**: si hay columnas desconocidas sin decidir (○ ninguna marcada) o
  falta un campo obligatorio (Nombre del cliente / Nombre de la mascota).
- Header de resumen: "8 columnas · 5 reconocidas · 3 por decidir".

### D.5 Tests
**Backend:**
- Varias columnas → `extra_data` como **lista ordenada** de `{label, value}`; labels
  repetidos conviven; orden preservado.
- `*.extra` many-to-one permitido; campos del sistema siguen 1:1 (dedup).
- Caps: nº de entradas + truncado de `value`; texto plano (sin procesar HTML).
- `commit` persiste; `validate` previsualiza sin escribir.
- Serializer expone `extra_data`.
**Frontend:**
- Mapeo: reconocida muestra confirmación + "Cambiar"; desconocida muestra la pregunta de
  3 opciones; **continuar bloqueado** mientras haya desconocidas sin decidir.
- petDetail: sección "Datos importados" visible con datos, oculta si vacío.

### D.6 Riesgos
- **Basura/PII** en `extra_data` → mitigado por el **consentimiento por columna** (no hay
  default silencioso) + caps. Es decisión consciente del usuario.
- **Texto plano sin bleach**: aceptable porque React escapa y el origen es Excel (texto).
  Si algún día se renderiza `extra_data` como HTML (no previsto), reevaluar.
- **No queryable** (solo display) — explícito.
- **UX**: no reintroducir el dropdown gigante ni el lenguaje técnico por módulo.
- Multi-tenant: `extra_data` viaja en el propio Owner/Pet de la org → sin superficie nueva.

### D.7 Esfuerzo (1 dev, paquete completo)
Backend+migración+serializers ~1.5 d · display ~0.5 d · rediseño mapeo+tests ~2.5–3 d →
**~1 semana**. No se parte: el rediseño UX entra junto con `extra_data`.

### D.8 Decisión final de producto (2026-06-15) — `extra_data` = DATO HISTÓRICO

Ajuste de producto sobre lo ya implementado (commits `06a2f7b`…`3bc7648`). **No** son
custom fields, ni datos editables, ni extensiones dinámicas del modelo. Son **datos
históricos importados de un sistema anterior**: referencia de migración, congelada.
Si en el futuro muchas clínicas necesitan uno de esos datos → se promueve a **feature
oficial** (modelo real, validación, formulario, permisos, writer, migración desde
`extra_data`). NO crear ahora EAV / custom fields / formularios generados.

**Cambio de shape** — cada entrada pasa de `{label, value}` a:
```json
[ {"label": "Veterinario anterior", "value": "Dr Luis",
   "source_column": "Vet Fav", "imported_at": "2026-06-15T10:00:00+00:00"} ]
```
- `label` — nombre visible elegido durante la importación (renombrable).
- `value` — valor importado (trim + cap 500).
- `source_column` — nombre **ORIGINAL** de la columna del Excel/CSV. **Renombrar el
  label NO lo cambia** → siempre se sabe de dónde vino el dato (clave para promover a
  feature oficial después).
- `imported_at` — fecha del proceso de importación (ISO, una sola marca por job).

Reglas (binding): read-only tras importar · sin endpoints de edición · no editable
desde la ficha (`read_only_fields` en ambos serializers) · NO usar en búsquedas /
reportes / reglas de negocio (billing, analytics, caja **nunca** leen `extra_data`).

**Lenguaje (mapeo + ficha) = migración, no campo vivo:**
- Mapeo, columna sin equivalente: explicación "No encontramos un campo del sistema…
  Puedes conservar la información como **referencia del sistema anterior**, o no
  importarla." Selector por tarjeta: **Histórico cliente / Histórico mascota / No
  importar** + enlace **"Relacionar con un campo existente"**. (Reemplaza el viejo
  "Cliente/Mascota" + "¿Es un campo del sistema?".)
- Ficha: encabezado **"Datos importados del sistema anterior" 🔒** + aviso "Estos datos
  vienen de una migración y no se actualizan automáticamente". Oculto si vacío.

Caps finales: 50 entradas/registro, value 500, label 120, source_column 120.
