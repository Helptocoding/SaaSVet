# Modulo: Importador CSV/Excel

> Orden 4 en curso: importación devuelve `demo_account_restricted` para el 403 del guard demo. El reporte paginado tiene implementación y pruebas parciales; ver [expediente](../remediaciones/orden-4/README.md).

`GET /api/imports/<public_id>/conflicts/` acepta `page_size` 1–100 (50 por defecto), `version` y `cursor` firmado. Responde `version`, `total`, `available`, `complete`, `results`, `next_cursor`; un cursor requiere versión. Un reporte sustituido devuelve 409 `conflict_report_changed`; cursor inválido devuelve 400; job de otra clínica devuelve 404. Resultados legacy se convierten desde su JSON persistido bajo lock sin consultar el catálogo; `complete=false` indica detalles históricos faltantes. `validate` guarda reporte/metadatos del job pero no escribe datos de dominio.

> **Ver también:** [`docs/system-operational-flow.md`](../system-operational-flow.md) — mapa operacional cross-módulo · ADR p43 (decisión de arquitectura).

## Objetivo

Permitir que una clínica nueva **migre sus datos** desde un Excel/CSV de su sistema
anterior sin captura manual. v1 (Fase A) importa **Clientes + Mascotas**
(`entity_type=owner_pet`). Diseñado para archivos reales sucios: encabezados
inconsistentes, especies en texto libre, clientes sin teléfono, columnas que no
existen en el modelo.

Boundary clave: el importador **escribe `Owner`/`Pet` vía `.save()` directo**, NO
pasa por los serializers manuales (`OwnerSerializer`/`PetSerializer`). Es la razón de
`Owner.phone = blank=True`, `Pet.species = blank=True` y de los campos `legacy_id` /
`extra_data` en `patients` (datos históricos ≠ datos nuevos). Ver `modules/patients.md`.

**Orden 2:** el commit de `owner_pet` toma lock compartido de Organization durante
la transacción del job y revalida cada Owner bajo lock antes de insertar Pet. Una
organización desactivada devuelve error y no crea sujetos; archive/deactivate
espera a terminar el commit o el commit encuentra el estado inactivo y no
reutiliza una validación obsoleta. `legacy_id`/`extra_data` no forman parte del
snapshot mínimo de documentos: un sujeto importado con esos metadatos no es
elegible para la API física excepcional hasta que exista conservación específica.

## Modelo: ImportJob

`ImportJob(PublicIdMixin, OrganizationalModel)` — sesión de importación persistida
(filas en JSONField, sin binario).

| Campo | Tipo | Rol |
|---|---|---|
| `public_id` | UUID | expuesto en URLs (ADR p18) |
| `entity_type` | str | `owner_pet` (v1) |
| `status` | str | `pending → validated → committed` |
| `original_filename` | str | solo el nombre (no el binario) |
| `source_columns` | JSON (list) | encabezados crudos del archivo |
| `rows` | JSON (list[list]) | celdas parseadas (string) |
| `mapping` | JSON (dict) | `{ header: target }` — ver Mapeo |
| `dedup_strategy` | str | `skip` (v1) |
| `result` | JSON (dict) | resumen del último validate/commit |

`source_columns`/`rows`/`mapping` declaran `blank=True` (un JSON `[]`/`{}` cuenta como
"blank" para `full_clean`).

## Flujo (3 fases)

```
1. UPLOAD    POST /api/imports/  (multipart: entity_type + file)
             → parsea, guarda source_columns + rows, auto-sugiere mapping. status=pending
2. MAPPING   PATCH /api/imports/<public_id>/mapping/  { mapping }
             → el usuario confirma/ajusta el mapeo columna→campo
3a. VALIDATE POST /api/imports/<public_id>/validate/  (dry-run, NO escribe)
             → predice created/reused/skipped/errores. status=validated
3b. COMMIT   POST /api/imports/<public_id>/commit/  (atómico)
             → despacha por entity_type: crea Owner/Pet ó Product/Presentation
               (+ StockMovement inicial). status=committed. Re-commit → 409
```

`validate` y `commit` comparten la misma proyección y validación de fila, así el
preview **no miente** (incluye predicción de conflictos `legacy_id`).

## Parsers (`parsers.py`)

Interface `parse_file()` → `CSVParser` | `ExcelParser`.

- **CSV**: prueba encoding `utf-8-sig / utf-8 / latin-1`; sniff de delimitador `, ; \t`.
- **XLSX**: `openpyxl` (`read_only=True, data_only=True`). Celdas numéricas enteras se
  emiten sin `.0` ("8112345678", no "8112345678.0").
- **Caps**: `MAX_FILE_BYTES = 5 MB`, `MAX_ROWS = 2000`, `MAX_COLUMNS = 50`.
- Errores de parseo → mensaje **no técnico** ("No pudimos procesar el archivo… guárdalo
  como CSV y vuelve a subirlo"), nunca el stack de openpyxl.

## Normalización + auto-mapeo (`normalization.py`)

- `normalize_text` — clave de comparación (lower, sin acentos, espacios colapsados).
  Usada para dedup por nombre y para matchear alias.
- `normalize_species` — alias libre → catálogo cerrado `SPECIES_CHOICES`, o `None` si
  no se resuelve (NO inventa `'otro'`).
- `normalize_sex` — `{male, female, unknown}`, default `unknown`.
- `suggest_mapping` — heurística por alias de encabezado (NO IA). Nunca asigna dos
  columnas al mismo destino. El usuario siempre confirma.
- `FIELD_CATALOG[entity_type]` — campos destino para la UI: `key`, `label` (humano),
  `group`, `importance ∈ {required, recommended, optional}`, `is_extra` para los
  targets `owner.extra`/`pet.extra`/`product.extra`.
- Normalizadores de inventario: `normalize_category`, `normalize_base_unit`
  (alias → catálogo cerrado de `Product`; no resuelto ⇒ warning + default),
  `parse_decimal` (estricto: `$`/espacios ok; separador decimal `.` o `,`;
  mezclados ⇒ ERROR) y `parse_bool` (sí/no/true/false/1/0/x; ambiguo ⇒ None y el
  caller decide error — nunca False silencioso).

## Reglas de negocio (`owner_pet`)

- `owner.name` **requerido** (NAME_REGEX). `pet.name` **requerido**.
- `owner.phone` **opcional**: con teléfono → dedup `(org, teléfono normalizado)`
  resuelta por el **servicio único de `patients`** (INV-C, ADR p57); sin teléfono → se
  importa igual (warning), dedup interna por nombre normalizado dentro del archivo.
  El importador **no endurece** su regla a `(nombre, teléfono)`: sigue deduplicando
  por teléfono, y un cliente existente se reutiliza aunque el nombre del archivo
  difiera.
- **`owner_ambiguous`** (INV-C): si el teléfono normalizado de una fila tiene
  **dos o más** expedientes en la organización, la fila **no se importa** y se
  reporta como error de fila (`{field: 'owner.phone', code: 'owner_ambiguous'}`).
  Antes el importador hacía `.first()` y **elegía** una de las filas duplicadas —
  exactamente lo que INV-C prohíbe. Ver § Duplicados de teléfono.
- `pet.species` **opcional**: si falta o no se reconoce → se importa pendiente (`''`)
  con warning (nunca bloquea, nunca asigna especie por defecto en masa).
- `pet.birth_date` opcional (formatos `YYYY-MM-DD`, `DD/MM/YYYY`…; inválida → warning,
  se importa sin fecha).
- **Dedup**: `pet` por `(owner, normalize(name), species)` — normalizado, no string
  exacto ("Max" == "MAX"). `dedup_strategy=skip` (v1): duplicado se salta y se reporta,
  nunca pisa datos. El duplicado por nombre se detecta ANTES de crear el owner → no
  genera clientes huérfanos.
- **`legacy_id`** (Owner + Pet): único parcial por org; conflicto → entrada en
  `conflicts[]` (no bloquea, pero la fila se omite). El conflicto se detecta y reporta
  ya en `validate` (preview honesto). UI: "Número de expediente anterior".
- **Fila = unidad lógica**: si la mascota se omite (duplicado por nombre o conflicto
  `legacy_id`), el owner de esa fila NO se crea. Un owner compartido por varias filas
  se materializa con el primer pet que entra. Cero owners huérfanos.
- **`extra_data`** (Fase D, ADR p43): columnas sin campo equivalente → `owner.extra` /
  `pet.extra`. Muchas columnas → una lista `{label, value, source_column, imported_at}`.
  Ver `modules/patients.md` § Datos del sistema anterior.
- **Una fila inválida NO aborta el import**: savepoint por fila (`owner` y `pet` en
  savepoints **separados**). El resto se importa; el reporte trae bloquantes/conflictos/
  avisos por fila.
- **Commit bloqueado con errores bloqueantes**: si `result.blocking` tiene entradas,
  el endpoint `commit` retorna 400 (`import_has_blocking_errors`). Warnings y conflicts
  NO bloquean — solo `blocking[]`.

## Importador de inventario (`entity_type=inventory`)

Implementado según `docs/decisions/2026-08-25-p61-importador-inventario.md`
(plan: `docs/PLAN-importador-inventario.md`). Lógica en
`services_inventory.py`; `validate_job`/`commit_job` despachan por
`entity_type`. El commit recibe `created_by=request.user` para auditar el
movimiento de stock.

### Grano del archivo

**1 fila = 1 Product + su Presentation única** (la principal; igual que el alta
manual). Multi-presentación por producto NO está soportada en esta fase.

### Campos (`FIELD_CATALOG['inventory']`)

- **Required**: `product.name`, `presentation.sale_price` (CHECK DB exige >0;
  sin precio válido la fila es **bloqueante** — nunca se inventan precios).
- **Recommended**: `product.internal_code` (identidad de dedup), `category`,
  `base_unit`, `product.stock` (existencia inicial, unidades de presentación).
- **Optional**: `min_stock`, `presentation.name` (default = nombre del producto),
  `conversion_factor` (default 1), `barcode`, `purchase_price`, `description`,
  `manufacturer`, `requires_prescription` (bool estricto; ambiguo ⇒ ERROR), y
  `product.extra` (many→1 → `Product.extra_data`, patrón Fase D).
- Defaults con warning: categoría no reconocida ⇒ `'other'`; unidad ausente o
  desconocida ⇒ `'unit'`.

### Deduplicación (solo `skip`)

- **Identidad de Product = `internal_code`** (único por org). Conflicto fuerte
  `duplicate_internal_code` (high si el nombre también coincide) contra el
  archivo y contra la org → fila omitida + reportada con `existing.public_id`.
- **Barcode** duplicado (en archivo u org) ⇒ conflicto `duplicate_barcode` high.
- **Nombre sin código ⇒ conflicto UNCERTAIN `duplicate_name`**: los nombres no
  son identidad en inventario; jamás dedup automática silenciosa ni creación
  automática. La fila se omite y se reporta (no bloquea commit); el usuario
  puede agregar códigos al archivo y volver a mapear.
- Sin código interno ⇒ auto-generado `PROD-{org.id}-{pk:04d}` (INSERT temporal
  `__tmp_{uuid}` → UPDATE final dentro del mismo savepoint).

### Stock inicial

Con `stock > 0`, tras crear Product+Presentation dentro del savepoint de fila:

```python
apply_stock_movement(pres, stock × conversion_factor, 'in', org,
                     reason='Stock inicial (importación)', created_by=user)
```

Único escritor del stock (lock de Product, dual-write a `Presentation.stock` en
unidades de presentación, `StockMovement(quantity_unit='base')` auditable).
Estos productos aparecen como `no_baseline` en `audit_stock_integrity`
(informativo, igual que el alta manual). Paridad con el alta manual verificada
por test gate: `Product.stock_quantity == stock×cf` y `Presentation.stock ==
stock` para cualquier `cf > 0`. En importación `Presentation.quantity ==
conversion_factor` SIEMPRE (contrato canónico; el alta manual puede dejar
`quantity=1` — deuda preexistente, ADR p61 §Deuda).

### Result: contadores adicionales (aditivos)

`created_products`, `created_presentations`, `initial_stock_movements` (en
owner_pet quedan en 0). El resto del shape canónico es idéntico. Tipos de
conflicto nuevos: `duplicate_internal_code`, `duplicate_barcode`,
`duplicate_name`.

### Frontend

El MISMO wizard (`pages/imports/`) con selector de tipo en el paso 1
("Clientes y mascotas" / "Productos / Inventario"). Textos, columnas de tabla,
tarjetas de resumen y CTA final vienen de `entityConfig.js` (default =
owner_pet ⇒ comportamiento histórico intacto). Los destinos "extra" del picker
se derivan del catálogo (`is_extra`), sin hardcodear entidades.

## Shape del `result` (contrato)

`ImportJob.result` es un `JSONField` que se escribe al validar y al commit. El shape
actual clasifica las filas en tres categorías + contadores:

```jsonc
{
  // Contadores
  "created_owners": 0,        // owners nuevos (solo si su pet entró)
  "reused_owners": 0,         // owners reutilizados (solo si su pet entró)
  "created_pets": 0,          // mascotas creadas
  "skipped_duplicates": 0,    // omitidos por duplicado de nombre (owner, norm_name, species)
  "skipped_conflicts": 0,     // omitidos por conflicto legacy_id (total)
  "conflicts_high": 0,        // split agregado: conflictos de alta confianza (P1-6C1)
  "conflicts_uncertain": 0,   // split agregado: conflictos inciertos (P1-6C1)
  "blocking_rows": 0,         // filas con datos faltantes/imposibles

  // Categorías
  "blocking": [               // datos faltantes / imposibles
    { "row": 5, "field": "pet.name", "message": "El nombre de la mascota es requerido." }
  ],
  "conflicts": [              // posibles duplicados por legacy_id con contexto
    {
      "row": 26,
      "type": "duplicate_legacy_id",
      "severity": "conflict",
      "scope": "pet",          // "pet" | "owner"
      "match_confidence": "high",  // "high" | "uncertain"
      "message": "Ya existe una mascota con este expediente.",
      "incoming": { "pet_name": "Bella", "owner_name": "Luis Pérez", "legacy_id": "126" },
      "existing": { "pet_name": "Bella", "owner_name": "Luis Pérez", "public_id": "…uuid…" }
    }
  ],
  "warnings": [               // datos opcionales faltantes
    { "row": 12, "field": "owner.phone", "message": "Cliente sin teléfono — se importará igual." }
  ],

  // Vista previa — muestras limitadas con totales reales
  "preview": [                // filas que SÍ se importarán (cap _PREVIEW_MAX=20)
    { "row": 1, "owner_name": "Ana López", "owner_phone": "818…", "pet_name": "Bella", "pet_species": "canino", … }
  ],
  "preview_total": 1500,      // total real de registros importables (puede ser > len(preview))
  "skipped": [                // omitidos por duplicado de nombre (cap _SKIPPED_SAMPLE_MAX=10)
    { "row": 4, "owner_name": "…", "pet_name": "…", "reason": "duplicate", "message": "Ya existe un paciente con el mismo nombre para este cliente." }
  ],
  "skipped_total": 40,        // total real de omitidos por duplicado (puede ser > len(skipped))

  // Aliases backward-compat (derivados de los anteriores)
  "errors":  [],              // = blocking[]
  "error_rows": 0             // = blocking_rows
}
```

### Caps de muestras

Los arrays `preview[]` y `skipped[]` están truncados:
- `preview[]` → máximo 20 filas (`_PREVIEW_MAX`).
- `skipped[]` → máximo 10 filas (`_SKIPPED_SAMPLE_MAX`).

`preview_total` y `skipped_total` contienen el total real sin truncar. La UI debe
mostrar el total real en contadores y "Mostrando N de M" cuando el total exceda
la muestra. Esto aplica tanto para la tabla "SE CREARÁN" como para la sección
"Ya estaban registrados" dentro de omitidos.

### Conteos: fuente única de verdad (P1-6C1)

Los **contadores agregados** (`created_pets`, `skipped_duplicates`,
`skipped_conflicts`, `conflicts_high`, `conflicts_uncertain`, `blocking_rows`)
son la **fuente única de verdad** para todos los números que muestra la UI. Los
arrays (`preview`/`skipped`/`conflicts`) son **muestras** para enseñar ejemplos.

`conflicts[]` hoy NO se capa (a diferencia de `preview`/`skipped`), pero el split
se expone como agregado para que el desglose de "No se importarán" **siempre
cuadre** aunque la muestra sea menor:

```
conflicts_high + conflicts_uncertain == skipped_conflicts           (invariante)
"No se importarán"      = skipped_total + skipped_conflicts
"Ya estaban registrados"= skipped_total + conflicts_high
"Mismo expediente…"     = conflicts_uncertain
→ los hijos SIEMPRE suman al padre
```

El frontend deriva los headers de estos agregados (no de `.length` de las
muestras) y usa los arrays solo para las cards + "Mostrando N de M". Se mantienen
en sync vía el helper `_append_conflict()` en `services.py` (único sitio que toca
`skipped_conflicts`/`conflicts_high`/`conflicts_uncertain`).

### Reglas de `match_confidence`

- `high` → `pet_name` y `owner_name` de `incoming` coinciden (normalizados) con
  `existing`.
- `uncertain` → coincide el `legacy_id` pero algún nombre difiere.

`match_confidence` es solo UI/contexto; no afecta decisiones de importación. Ambos
casos (`high` y `uncertain`) se omiten de la importación por seguridad (no se crea
el registro). La diferencia es solo visual para el usuario:

| `match_confidence` | Grupo en UI | Significado |
|---|---|---|
| `high` | **Ya estaban registrados** | Mismo expediente, mismos nombres → duplicado. Se agrupa con los omitidos por duplicado de nombre (`skipped[]`) bajo un solo motivo humano. |
| `uncertain` | **Mismo expediente con datos diferentes** | Mismo expediente, datos distintos → posible colisión entre clínicas o sistemas. Se muestra como sub-grupo separado dentro de la sección unificada "No se importarán". |

### Reglas de conteo

- `blocking` NO cuenta como conflicto. `conflicts` NO cuenta como blocking.
- `created_owners`/`reused_owners` solo se incrementan cuando el pet de esa fila ENTRA.
- `skipped_duplicates` = omitidos por nombre normalizado duplicado.
- `skipped_conflicts` = omitidos por `legacy_id` duplicado.
- `existing` solo expone `public_id` (UUID), nunca PK entero.

### Bulk fetch

El backend recolecta todos los `legacy_id` del archivo y los busca en DB con
`filter(legacy_id__in=...)` una sola vez (evita N+1). `select_related('owner')` para
pets, trayendo `owner__name` sin queries extra.

## Mapeo (`mapping`)

`mapping = { header: target }`. `target` puede ser:
- `str` — key del sistema (`owner.name`, `pet.species`…) o `''` (no importar).
- `{target, label}` — para `owner.extra`/`pet.extra` con label visible renombrado; la
  **KEY (header)** sigue siendo la referencia para leer la celda (→ `source_column`).

`check_mapping` rechaza: targets desconocidos, dos columnas al **mismo** campo del
sistema (los `*.extra` están exentos — many→1), y faltantes requeridos.

## Endpoints + permisos RBAC

| Método | Ruta | Permiso |
|---|---|---|
| POST | `/api/imports/` (upload, MultiPart) | `import.create` |
| GET | `/api/imports/<public_id>/` | `import.retrieve` |
| GET | `/api/imports/` | `import.list` |
| PATCH | `/api/imports/<public_id>/mapping/` | `import.create` |
| POST | `/api/imports/<public_id>/validate/` | `import.create` |
| POST | `/api/imports/<public_id>/commit/` | `import.commit` |
| POST | `/api/imports/<public_id>/commit/` retorna 400 si `result.blocking` no está vacío (código `import_has_blocking_errors`) | — |

Permisos `import.*` asignados a **ADMIN**. El importador es operación de
migración, no de uso diario. `ImportJobViewSet` usa `PublicIdLookupMixin` +
`TenantQueryMixin` (cross-tenant → 404).

**Throttle** (`ScopedRateThrottle`): `import_upload` (create) e `import_commit`
(commit) para acotar operaciones costosas.

## Frontend (`pages/imports/`, ruta `/imports` — solo ADMIN)

Wizard de pasos: **Subir → Mapear → Validar → Resultado**.

- `UploadStep` — drop zone, pre-check de 5 MB client-side, botón X para limpiar.
- `MappingStep` — "VetCare entendió tu Excel, solo revisa unas cosas":
  - Columnas auto-reconocidas → resumen colapsable compacto (grid).
  - Columnas a revisar → cards compactas (grid 3/2/1); **una decisión** por columna
    vía `DestinationPicker` (modal acordeón: Cliente / Mascota / Datos del sistema
    anterior / No usar). Decisión siempre reversible ("Cambiar"); renombre del label
    solo para datos históricos.
- `ImportedDataSection` (en `petDetail`) muestra `extra_data` read-only con lenguaje de
  migración ("Datos importados del sistema anterior 🔒").
- `ResultStep` — datos incompletos **estrategia C** (ADR p44d): agrega los
  `warnings` del backend (datos OPCIONALES faltantes) en un resumen único al
  terminar ("N mascotas sin fecha de nacimiento / sin especie / N clientes sin
  teléfono"). Informativo, no bloquea, **no** alerta global. El complemento
  **estrategia D** vive en `petDetail` (prompt suave "Completar datos" →
  `/pets?edit=<public_id>`); ver `modules/patients.md`.
- `PreviewStep` — vista previa humana antes de confirmar. Diseñado como revisión
  de producto ("¿qué va a pasar?"), no como reporte técnico:
  - **Barra de estado**: pills con conteos — ✓ "Se crearán N mascotas · asociadas
    a M clientes", ⊘ omitidos, ⚠ en revisión, ! necesitan corrección, ℹ datos
    incompletos.
  - **✓ SE CREARÁN**: tabla con columnas Mascota, Cliente, Especie, Teléfono usando
    `preview[]` (cap 20). "Mostrando 20 de 1500" cuando el total excede la muestra.
    - **⚠ Aviso de datos incompletos**: dentro de la misma sección, como nota
      colapsable ("N registros se importarán con algunos datos faltantes. Puedes
      completarlos después."). Agrupado por campo con `groupImportIssues()`.
  - **Panel de revisión** (inbox con sidebar + detalle): solo para errores
    bloqueantes. Ya no contiene warnings.
  - **⊘ NO SE IMPORTARÁN**: sección unificada que reemplaza los antiguos grupos
    colapsables separados. Agrupa por motivo humano, sin exponer conceptos internos
    (`skipped`, `conflicts`, `match_confidence`):
    - **Ya estaban registrados** (`skipped[]` + `high`-confidence `conflicts[]`):
      cards con nombre, cliente y motivo. "Mostrando 10 de 1500" si el total excede
      la muestra.
    - **Mismo expediente con datos diferentes** (`uncertain`-confidence
      `conflicts[]`): comparación lado a lado (En tu archivo / Ya registrado),
      link "Ver paciente".
  - **⬇ Descargar filas con problemas (CSV)**: genera client-side desde
    `blocking[]` + `warnings[]` con columnas Fila, Campo, Error, Qué hacer.
    BOM UTF-8 para Excel.
  - **CTA**: tres estados — bloqueado (si `blocking.length > 0`), confirmable,
    sin registros. Consecuencia con conteos reales:
    "Al continuar: ✓ se importarán N registros · ⊘ N no se importarán".
  - **`groupImportIssues()`**: helper reutilizable que agrupa ítems por
    `field`, ordena por count, limita a 5 samples por grupo. Usado para
    blocking y warnings.

`api/imports.js` centraliza las llamadas. Errores → `apiError`/toast (nunca códigos
técnicos como `import_parse_error` en un div).

## Boundaries / arquitectura

- Pertenece al dominio de migración; escribe en `patients` vía `.save()` directo
  (modelos, no serializers). Documentado en ADR p43.
- NO toca billing/inventory/appointments. NO crea facturas ni stock.
- `extra_data` es display-only: no entra a analytics, billing ni caja.

## Estrategia futura: múltiples orígenes/sucursales (NO implementado)

### Problema

Actualmente `legacy_id` es único dentro de `organization`. Esto funciona para una
clínica migrando desde un único sistema anterior (ej. Exp 001 → Bella; reimportar
Exp 001 → Bella se detecta como duplicado). Pero **varias clínicas/sucursales**
pueden tener la misma numeración histórica:

```
Sucursal Norte:  Exp 001 → Bella
Sucursal Sur:    Exp 001 → Rocky
```

Ambos son válidos, pero el constraint actual lo rechaza.

### Opciones

**Opción A — `ImportSource`**: agregar concepto `ImportSource` (ej. "Sucursal Norte").
`legacy_id` único por `organization + source + legacy_id`. Mantiene búsqueda clara.

**Opción B — Prefijo automático**: durante import, prefijar según sucursal
(N-001, S-001). Más simple pero modifica identificadores históricos.

**Opción C — Permitir duplicados libremente**: NO recomendado. La búsqueda por
expediente devolvería varios pacientes; recepción no sabría cuál abrir.

### Decisión V1

No implementar multi-source todavía. La mayoría de clínicas pequeñas migran
desde un único sistema. Agregarlo ahora aumenta complejidad antes de validación
real. Mientras tanto, los conflictos de expediente se muestran como
"Mismo expediente con datos diferentes" dentro de la sección unificada
"No se importarán", con explicación de causas posibles.

## Tests

`apps/imports/tests/test_owner_pet_import.py` — parsing CSV+XLSX, normalización,
dry-run sin escritura, commit atómico, dedup skip, multi-tenant 404, permisos
(non-admin 403), `legacy_id` conflict, `extra_data` (orden, labels repetidos,
`source_column`/`imported_at`, rename, cap 500, read-only vía PATCH de ficha),
savepoint anti-huérfano, preview y skipped con caps. Frontend:
`PreviewStep.test.jsx` (33 tests: preview table, omitidos unificados, warnings
como aviso, indicadores "Mostrando N de M", estados vacíos, CTA),
`MappingStep.test.jsx`, `ResultStep.test.jsx`, `UploadStep.test.jsx`,
`ImportedDataSection.test.jsx`, `groupImportIssues.test.js`.

## Duplicados de teléfono (INV-C — ADR p57)

El importador tiene **tres** lecturas por teléfono, no una: la pasada de
validación/preview, la de dry-run y la del commit. Las **tres** usan el mismo
resolvedor (`patients.services`) y el mismo contrato de cuatro desenlaces
(`0` → alta nueva · `1` → reutiliza · `owner_exists` · `owner_ambiguous`).

Cambiar solo la última habría dejado un fallo de producto silencioso: **la vista
previa diría «se reutilizará el cliente X» y el commit rechazaría esa misma fila**.
El usuario aprueba una cosa y obtiene otra. En concreto:

- El preview **no puede mostrar una elección que la escritura rechazaría**. Una
  fila cuyo teléfono normalizado tenga dos o más expedientes aparece **desde el
  principio** como fila con error, dentro del bloque de omitidas que la UI ya
  sabe presentar.
- El `.first()` desaparece de las tres pasadas: **ni el preview elige**.
- El conteo de «se importarán N filas» ya incluye esas exclusiones, así que
  coincide con el resultado real del commit.
- La política de fila **no cambia**: una fila problemática no aborta el import;
  se salta y se reporta.

Consecuencia aceptada: en una clínica con dato sucio, el **conteo de filas
importadas baja** — filas que hoy reutilizan la primera coincidencia pasan a
reportarse. Elegir una fila arbitraria era el bug, no la función.
`audit_owner_phone_duplicates` (ver `modules/patients.md`) lista los duplicados
para que alguien los ordene.

Nota de escala: el lock de deduplicación es a nivel de transacción y el commit
del job es **una** transacción, así que los locks se acumulan hasta el final (uno
por teléfono nuevo). `parsers.MAX_ROWS = 2000` acota el máximo; subir ese tope
obliga a revisar `max_locks_per_transaction` de PostgreSQL.

## Relación con otros módulos

- **patients**: crea `Owner` + `Pet`; razón de `phone`/`species` `blank=True`,
  `legacy_id` y `extra_data`. Desde F1 (ADR p57) **comparte la resolución de
  expediente por teléfono**: `imports/services._resolve_owner` delega en
  `patients.services.resolve_owner_for_phone`, y la normalización converge a
  `core.validators.phone_digits` (conservando su excepción de teléfono vacío).
  Ver `modules/patients.md` § Identidad de expediente por teléfono.
- **inventory**: crea `Product` + `Presentation` + `StockMovement` inicial vía el
  servicio autoritativo `apply_stock_movement` (ADR p31). Ver § Importador de
  inventario y ADR p61.
- Resto de dominios: sin acoplamiento (migración aislada).
