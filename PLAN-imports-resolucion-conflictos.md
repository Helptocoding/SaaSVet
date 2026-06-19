# PLAN — Resolución de errores/conflictos en importación de clientes y mascotas

> **Documento de ejecución autocontenido.** Escrito para un agente/desarrollador
> que **no tiene contexto previo** de esta conversación. Léelo completo antes de
> tocar código. No asumas comportamiento: los archivos y líneas citados son el
> estado real al momento de redactar (rama `feat/importador-csv-excel`).

---

## 0. Reglas duras (NO negociables)

1. **Multi-tenant**: toda query va `for_organization(org)` **primero** en la cadena.
   Cross-org devuelve 404, nunca `[]`. Nunca confíes en IDs del cliente.
2. **IDs públicos**: en URLs/links/deep-links del frontend usa `public_id` (UUID).
   Los PK enteros solo viven en FKs del body. **Prohibido** exponer PK en el
   `result` o en links.
3. **Services, no views gordas**: la lógica de import vive en
   `backend/apps/imports/services.py`. Las views solo orquestan.
4. **Errores frontend**: usar `apiError`/`handleFormError`; nunca mostrar `code`
   técnico (`legacy_id`, `unique constraint`) crudo al usuario.
5. **Confirmaciones**: `useConfirm`, nunca `window.confirm`.
6. **Permisos**: `can("...")`, nunca `user.role === ...`.
7. **CSS Modules** (no estilos inline salvo casos mínimos ya presentes).
8. **Tests obligatorios** en cambios de regla de negocio. No borrar tests para
   pasar la suite.
9. **Commits**: uno por fase, mensaje claro, terminando con
   `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. **NUNCA hacer push**
   ni abrir PR salvo que el usuario lo pida explícitamente.
10. **Actualizar docs** cuando cambie el contrato (`docs/modules/imports.md`,
    `docs/modules/patients.md` si aplica). ADR si el cambio de shape del `result`
    se considera contrato externo.

---

## 1. Objetivo

Convertir errores técnicos de importación en **decisiones claras** para usuarios
no técnicos. Hoy, importar un archivo histórico cuyas mascotas ya existían produce:

```
Vista previa:
  40 clientes nuevos
  0 mascotas nuevas
  40 filas con error
  Campo: Nº expediente anterior · Error: El nº expediente anterior "126" ya existe.
```

El usuario no sabe: si ya importó ese archivo, qué paciente existente choca, qué
pasará si continúa, si las filas buenas entran, ni cómo resolverlo. Además —ver
§3— **confirmar crearía 40 clientes huérfanos** (sin mascota).

**V1 = detectar → mostrar → omitir seguro.** Sin merge, sin actualizar
existentes, sin "crear como nuevo".

---

## 2. Mapa de archivos (estado actual)

### Backend (`backend/apps/imports/`)
| Archivo | Rol | Símbolos clave (líneas aprox.) |
|---|---|---|
| `services.py` | núcleo: validación + commit | `clean_owner_pet_row` (145-214), `validate_job` (261-364), `commit_job` (370-457), `_resolve_owner` (460-487), `_create_owner` (490-499), `_pet_exists` (502-508), `_humanize_exc` (519-538), `_base_result` (246-255), `_project_row` (86-118) |
| `views.py` | endpoints | acción `validate` (146-159), acción `commit` (162-175). Ambas guardan `job.result = result` y avanzan `status`. |
| `serializers.py` | lectura del job | `ImportJobSerializer` expone `result` **verbatim** (JSONField passthrough) y `sample_rows` = **solo primeras 10 filas** (`_SAMPLE_LIMIT`). |
| `models.py` | `ImportJob` | `result` JSONField; `status` `pending→validated→committed`. |
| `tests/test_owner_pet_import.py` | tests existentes | helpers `_seed_roles`, `_csv`, `MAPPING` (incluye `Expediente→pet.legacy_id`). |

### Frontend (`frontend/src/pages/imports/`)
| Archivo | Rol |
|---|---|
| `index.jsx` | orquestador del wizard (Subir→Columnas→Vista previa→Resultado). Dueño del `job` y de toda la red. `handleConfirm` (117-141) tiene el `useConfirm` antes de commit. |
| `PreviewStep.jsx` | **paso a rediseñar**. Hoy: resumen + grid + 2 tablas técnicas `Fila/Campo/Error` (`IssuesTable`). Botón "Confirmar importación" habilitado aunque haya errores (solo lo gobierna `canCommit`). |
| `ResultStep.jsx` | resultado post-commit (estrategia C: agrega warnings de datos opcionales). |
| `api/imports.js` (en `frontend/src/api/`) | `uploadImport`, `setMapping`, `validateImport`, `commitImport`. |

---

## 3. Comportamiento actual EXACTO (no cambiar sin querer)

### 3.1 Validate (`validate_job`, dry-run, NO escribe)
- Modelo de error = **lista plana** `result.errors[] = {row, field, message}` + `result.warnings[]`. Sin tipos ni severidad.
- legacy_id se detecta con `.exists()`:
  - owner: `services.py:313-322`.
  - pet: `services.py:348-358` → mensaje `El nº de expediente anterior "X" ya existe.`
- **NO trae el registro existente** (solo `.exists()`): no hay `public_id`, ni nombre del paciente/cliente con que choca.
- **Conteo deshonesto**: `created_owners` se incrementa en `:328` **antes** del check de pet-legacy (`:348`). Por eso el preview dice "40 clientes nuevos" aunque esas filas terminen en error.

### 3.2 Commit (`commit_job`) — import PARCIAL + bug de owners huérfanos
- **Import parcial confirmado**: 100 filas / 90 válidas / 10 error → **90 importadas, 10 omitidas**. `transaction.atomic` envuelve el loop pero **cada owner y cada pet van en savepoint propio**; fila mala → `continue`.
- **Bug**: orden por fila = `owner (savepoint → se crea) → dedup pet → pet (savepoint)`. Si el pet falla por `legacy_id`, **el owner ya se creó y commiteó** (`services.py:411-426` crea owner; `:435-455` crea pet y solo ahí revienta). Re-importar el archivo histórico ⇒ **40 clientes nuevos, 0 mascotas**. Clientes duplicados/huérfanos.
- `views.py:commit` deja `status=committed` aunque haya errores; re-commit → 409 (`import_already_committed`). No hay "reintentar".

### 3.3 Frontend
- `PreviewStep.jsx` solo recibe `{row, field, message}`; **no tiene las filas completas** (`sample_rows` son 10). El contexto del existente debe venir del backend en `result`.
- El CTA "Confirmar importación" no se bloquea por errores.

---

## 4. Shape objetivo de `result` (contrato nuevo)

```jsonc
{
  // contadores honestos (solo cuentan cuando el pet de la fila ENTRA)
  "created_owners": 0,
  "reused_owners": 0,
  "created_pets": 0,
  "skipped_duplicates": 0,     // pet duplicado por (owner, nombre norm., especie)
  "skipped_conflicts": 0,      // NUEVO: filas omitidas por legacy_id duplicado
  "blocking_rows": 0,          // NUEVO: filas que NO pueden importarse (faltan datos)

  // categorías (reemplazan al viejo errors[] plano)
  "blocking": [                // datos faltantes / imposibles
    { "row": 100, "field": "pet.name", "message": "Falta el nombre de la mascota." }
  ],
  "conflicts": [               // resolubles: posible duplicado
    {
      "row": 26,
      "type": "duplicate_legacy_id",
      "severity": "conflict",
      "scope": "pet",          // "pet" | "owner" (cuál legacy_id chocó)
      "match_confidence": "high",   // "high" | "uncertain"
      "message": "Ya existe una mascota con este expediente.",
      "incoming": { "pet_name": "Bella", "owner_name": "Luis Pérez", "legacy_id": "126" },
      "existing": { "pet_name": "Bella", "owner_name": "Luis Pérez", "public_id": "…uuid…" }
    }
  ],
  "warnings": [                // opcionales faltantes (igual que hoy)
    { "row": 12, "field": "owner.phone", "message": "Cliente sin teléfono — se importará igual." }
  ],

  // back-compat (derivados, NO eliminar hasta Fase 4): aliases para no romper
  // consumidores viejos durante la transición
  "errors": [ /* = blocking[] */ ],
  "error_rows": 0              // = blocking_rows
}
```

### Reglas de `match_confidence` (calculado en backend, normalizando nombres con `normalize_text`)
- `high` → `pet_name` **y** `owner_name` de `incoming` coinciden (normalizados) con `existing`.
- `uncertain` → coincide el `legacy_id` pero **algún** nombre difiere ("mismo expediente, datos distintos").

### Reglas de conteo
- `blocking` NO cuenta como conflicto. `conflicts` NO cuenta como blocking.
- Una fila con pet duplicado por nombre → `skipped_duplicates` (no es conflicto legacy).
- Una fila con legacy_id duplicado → `skipped_conflicts` + entrada en `conflicts[]`.
- `created_owners`/`reused_owners` solo se incrementan cuando el pet de esa fila **entra** (ver Fase 1).

---

## 5. FASES (ejecutar EN ESTE ORDEN, commit por fase)

### FASE 1 — Integridad del commit (PRIMERO)

**Meta**: la **fila del archivo es la unidad lógica**.
- Si la mascota entra → crear/reusar owner.
- Si la mascota se omite (duplicado por nombre **o** conflicto legacy_id) → **no
  crear owner nuevo**.
- Un owner usado por **otra** fila válida **sí** sobrevive (1 solo, sin duplicar).
- Sin estados con clientes huérfanos.

**Mecanismo (aplica a `commit_job` Y a `validate_job` — el preview debe predecir
lo mismo):** reordenar la decisión **dentro de cada fila**:

1. `clean_owner_pet_row`. Si hay errores blocking → registrar en `blocking`,
   `continue` (no se resuelve owner).
2. Calcular `owner_key` (`('phone', phone)` o `('name', normalize_text(name))`)
   **sin crear ni contar** el owner todavía.
3. Resolver la **identidad** del owner solo por lectura (lookup, sin INSERT) para
   obtener su `pk` si ya existe → necesario para el dedup de pet por
   `(owner_pk, nombre_norm, especie)`.
4. Decidir el pet **antes** de materializar el owner:
   - dedup por nombre (within-file `seen_pet_keys` + DB `_pet_exists`) →
     `skipped_duplicates++`, `continue` (no crear owner).
   - conflicto `pet.legacy_id` (within-file `seen_pet_legacy` + DB) →
     `skipped_conflicts++` + `conflicts[]`, `continue` (no crear owner).
5. El pet **entra**: ahora sí **materializar/reusar el owner** (savepoint) y
   contar `created_owners`/`reused_owners`; luego crear el pet (savepoint).
   Cachear el owner por su key (`owners_by_phone`/`owners_by_name`) para que una
   fila posterior lo reúse → **orden de filas irrelevante**: el owner se crea con
   el primer pet que entra, no antes.

> Nota: el conflicto de `owner.legacy_id` (`services.py:313-322`) se mantiene como
> hoy en su semántica, pero su conteo de owner también debe diferirse a cuando el
> pet entra (consistencia). Si el owner-legacy choca, la fila no puede crear ese
> owner → tratar como conflicto de owner (`scope:"owner"`) o blocking según
> corresponda; en Fase 1 basta con NO crear owner huérfano. El detalle de
> clasificación fina va en Fase 2.

**Archivos**: `backend/apps/imports/services.py` (`validate_job`, `commit_job`,
posibles helpers nuevos `_resolve_owner_readonly`/`_owner_lookup`). No tocar
views ni serializers en esta fase.

**Tests (extender `tests/test_owner_pet_import.py`)** — backend, obligatorios:
- **Idempotencia (clave)**: subir+mapear+commit un archivo; **re-subir el mismo
  archivo** y commit → `created_owners == 0`, `created_pets == 0`,
  `skipped_duplicates`/`skipped_conflicts == N`. **Cero owners nuevos en DB**
  (assert `Owner.objects.count()` igual antes/después del segundo commit).
- **Owner compartido**: archivo con fila A (pet nuevo, owner X) + fila B (pet con
  legacy_id duplicado, mismo owner X) → tras commit: owner X existe **una sola
  vez**, pet A creado, pet B omitido, **sin owner huérfano**.
- **No huérfanos**: archivo donde **todas** las filas tienen pet conflictivo →
  `created_owners == 0` y `Owner.objects.filter(...).count()` sin incremento.
- **Preview honesto**: `validate_job` sobre el archivo re-importado predice
  `created_owners == 0` (no 40).

**Comando**:
`python manage.py test apps.imports.tests.test_owner_pet_import -v 1`
(ejecutar por ruta de módulo explícita; el app-label suelto puede fallar la
discovery en este entorno Windows).

**Commit**: `fix(imports): la fila es unidad lógica — sin clientes huérfanos al omitir mascota`

---

### FASE 2 — Clasificación + contexto del existente

**Meta**: poblar el shape de §4 (`blocking`/`conflicts`/`warnings` + `incoming`/
`existing`/`match_confidence`), manteniendo aliases `errors[]`/`error_rows`.

**Backend** (`services.py`):
- **Bulk fetch del existente** (evitar N+1): antes del loop de `validate_job`,
  recolectar todos los `pet.legacy_id` y `owner.legacy_id` presentes en el archivo
  → **una** query cada uno:
  - `Pet.objects.for_organization(org).filter(legacy_id__in=set).select_related('owner').values('legacy_id','name','public_id','owner__name')`
  - idem owners.
  → construir dict `legacy_id -> {pet_name, owner_name, public_id}`.
- Al detectar `duplicate_legacy_id`, en vez de `errors.append(...)`, hacer
  `conflicts.append({type, severity:"conflict", scope, message_humano, incoming, existing, match_confidence})`.
  - `incoming` sale de la fila ya `clean`.
  - `existing` sale del dict bulk (incluye `public_id`, **nunca** PK).
  - `match_confidence` por las reglas de §4.
- Mensajes humanos: "Ya existe una mascota con este expediente." /
  "Ya existe un cliente con este número." (no "legacy_id…").
- Mantener `blocking[]` (faltan nombre/teléfono inválido/datos imposibles) y
  `warnings[]` (sin teléfono/especie/fecha) tal cual hoy, solo renombrando el
  cubo `errors`→`blocking` y dejando `errors`/`error_rows` como **alias derivado**.
- `commit_job` usa la **misma** detección (puede reusar el dict bulk o el check
  por fila); su `result` debe traer las mismas categorías para que `ResultStep`
  las muestre post-commit.

**Tests** (backend): 
- `conflicts[]` trae `incoming` + `existing.public_id` + `existing.pet_name`/`owner_name`.
- `match_confidence == "high"` cuando nombres coinciden; `"uncertain"` cuando el
  expediente coincide pero el nombre difiere.
- `duplicate_legacy_id` cae en `conflicts`, **no** en `blocking`.
- dry-run sigue sin escribir (assert counts DB sin cambios).
- No se expone ningún PK en `result` (assert que `existing` no trae `id`).

**Docs**: actualizar `docs/modules/imports.md` (§ Reglas de negocio + § Frontend
ResultStep) con el nuevo shape. Considerar ADR si se trata como contrato.

**Commit**: `feat(imports): clasifica blocking/conflicts/warnings + contexto del paciente existente`

---

### FASE 3 — Frontend: preview humano

**Meta**: reemplazar la tabla técnica por **decisiones agrupadas**.

**Archivo**: `frontend/src/pages/imports/PreviewStep.jsx` (+ `imports.module.css`
para estilos; + ajustar copy del `useConfirm` en `index.jsx:handleConfirm`).

**Resumen humano** (arriba): 
```
✓ {created_pets} pacientes listos para importar
⚠ {skipped_conflicts} necesitan revisión (posibles duplicados)
✗ {blocking_rows} no se pueden importar (faltan datos)   ← solo si > 0
```
(Evitar el "40 / 0 / 40" técnico.)

**Tres grupos colapsables** (en este orden):
1. **⚠ Posibles duplicados ({skipped_conflicts})** — "Puede que estos pacientes
   ya estén registrados. Suele pasar si este archivo ya se importó antes."
   Por ítem, comparación lado a lado:
   - **En tu archivo**: `incoming.pet_name` · `incoming.owner_name`
   - **Ya registrado**: `existing.pet_name` · `existing.owner_name`
   - Copy según `match_confidence`:
     - `high` → "Parece el mismo paciente."
     - `uncertain` → "Mismo expediente, datos distintos — revísalo."
   - **Botón "Ver paciente"**: `<a href={`/pets/${existing.public_id}`}
     target="_blank" rel="noopener noreferrer">`. No saca al usuario del wizard.
     Usa **public_id**, nunca PK.
2. **✗ Requieren corrección ({blocking_rows})** — lista `blocking[]`
   (`Fila N: Falta el nombre de la mascota`).
3. **Avisos ({warnings.length})** — datos opcionales faltantes (ya existe la
   lógica; mantener tono informativo).

**Explicar consecuencia antes de confirmar** (encima del CTA):
- Si hay algo importable: "Al continuar: ✓ se importarán {created_pets}
  registros · ⚠ {skipped_conflicts} posibles duplicados se omitirán."
- Si **no** hay nada importable (solo blocking): cambiar CTA a estado guía
  ("Corrige los errores para poder importar"), no permitir confirmar en vacío.
- Actualizar el mensaje de `useConfirm` en `index.jsx` (hoy dice "los duplicados
  se omitirán") para reflejar conteos reales.

**Tests** (`PreviewStep.test.jsx`, Vitest + RTL):
- Muestra los duplicados de forma humana (nombre mascota + cliente, no
  "legacy_id"). Verificar que **no** aparece texto técnico (`legacy_id`,
  `constraint`).
- "Ver paciente" apunta a `/pets/<public_id>` con `target="_blank"` y
  `rel` con `noopener`.
- Explica qué ocurrirá (texto de consecuencia con los conteos).
- Muchos errores no rompen la UI (render con 200 conflicts no crashea; usar el
  paginador existente si aplica).
- Si solo hay blocking sin importables → el CTA de confirmar no está disponible.

**Comando**: `npx vitest run --pool=threads src/pages/imports/PreviewStep.test.jsx`
(usar `--pool=threads`; el pool `forks` es inestable en este entorno Windows).

**Commit**: `feat(imports): vista previa humana — duplicados, correcciones y consecuencias`

---

### FASE 4 — Docs + cierre

- `docs/modules/imports.md`: shape final de `result`, categorías, regla de
  "fila = unidad lógica", skip de duplicados, `match_confidence`, deep-link.
- `docs/modules/patients.md`: si se documenta el deep-link `/pets/<public_id>`
  desde import.
- Decidir si los aliases `errors`/`error_rows` se eliminan (solo si ningún
  consumidor los usa ya) o se conservan documentados como legacy.
- ADR si el cambio de shape de `result` se considera contrato externo
  (`docs/decisions/`), referenciando ADR p43 (importador) y p44b/c/d.

**Commit**: `docs(imports): contrato de result con categorías + resolución de conflictos`

---

## 6. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| **Owner compartido borrado por error** al diferir creación | Cache de owner por key; se materializa con el **primer** pet que entra; test de owner compartido obligatorio (Fase 1). |
| **N+1** al traer el existente en archivos de 2000 filas | Bulk `filter(legacy_id__in=...)` una sola vez (Fase 2), nunca por fila. |
| **Romper consumidores** del `result` viejo (`PreviewStep`/`ResultStep`/tests) | Mantener aliases `errors`/`error_rows` = `blocking`/`blocking_rows` hasta Fase 4. |
| **Cambiar dedup de pet por nombre** sin querer al reordenar | No tocar la regla de dedup `(owner, normalize(name), species)`; solo cambia **cuándo** se materializa el owner. Tests de dedup existentes deben seguir verdes. |
| **Exponer PK** en `existing` o en el link | `existing` solo `public_id`; link a `/pets/<public_id>`. Test que asegure ausencia de `id`. |
| **Preview mentiroso** persiste | Fase 1 obliga a que `validate_job` use el mismo orden → `created_owners` honesto; test de preview. |

---

## 7. Fuera de alcance (NO implementar en V1)

- Merge de registros / actualizar el paciente existente / sobrescribir datos
  clínicos.
- Radio "es el mismo paciente → actualizar / crear nuevo / ignorar".
- Deduplicación avanzada / fuzzy más allá de `normalize_text`.
- Cambiar el modelo `ImportJob`, `dedup_strategy` (sigue `skip`), o agregar
  estados nuevos.

**V1 = detectar, mostrar el conflicto con contexto, y omitir de forma segura.**

---

## 8. Criterios de aceptación (checklist final)

- [ ] Re-importar el mismo archivo → 0 clientes nuevos, 0 mascotas nuevas, N
      duplicados omitidos. Cero owners huérfanos en DB.
- [ ] Owner usado por una fila válida sobrevive aunque otra fila del mismo owner
      sea conflicto.
- [ ] `result` trae `blocking[]`, `conflicts[]` (con `incoming`/`existing.public_id`/
      `match_confidence`), `warnings[]`.
- [ ] Ningún PK interno en `result` ni en links.
- [ ] Preview muestra duplicados en lenguaje humano + comparación + "Ver paciente"
      (`target="_blank"`, `rel="noopener noreferrer"`, `public_id`).
- [ ] Antes de confirmar se explica la consecuencia con conteos reales.
- [ ] Import parcial se mantiene (filas buenas entran).
- [ ] Tests backend + frontend verdes. Lint limpio en archivos tocados.
- [ ] Docs actualizados. Commits separados por fase. **Sin push.**

---

## 9. Comandos útiles

```bash
# Backend (rutas de módulo explícitas)
python manage.py test apps.imports.tests.test_owner_pet_import -v 1

# Frontend (pool de threads obligatorio en este entorno)
cd frontend
npx vitest run --pool=threads src/pages/imports/PreviewStep.test.jsx
npx eslint src/pages/imports/PreviewStep.jsx

# Estado / commit (NO push)
git add <archivos-de-la-fase>
git commit -m "<mensaje de la fase>"
```
