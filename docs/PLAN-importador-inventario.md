# PLAN — Importador de Inventario (`entity_type=inventory`)

> **Estado (15-11-2026):** implementado según [ADR p61](decisions/2026-08-25-p61-importador-inventario.md) («Aceptado — implementado») e [imports.md](modules/imports.md). Las casillas del criterio de cierre no se marcaron al terminar y no indican trabajo ausente. El orden 4 corrigió después I02 e I03 sobre este importador ([expediente](remediaciones/orden-4/README.md)).

> **Documento de ejecución autocontenido.** Escrito para un agente/desarrollador
> que **no tiene contexto previo** de esta conversación. Léelo completo antes de
> tocar código. El análisis (ingeniería inversa del importador `owner_pet`) fue
> verificado contra el código real; los archivos y símbolos citados existen.

---

## 0. Reglas duras (NO negociables)

1. **No crear un segundo sistema de importación paralelo.** Reutilizar
   `ImportJob`, parsers, mapping, wizard.
2. **No cambiar el comportamiento observable de `owner_pet`.** La refactorización
   interna de `services.py` (renombrar implementaciones para despachar por
   entity_type) está permitida ÚNICAMENTE si la suite completa demuestra
   equivalencia: mismos endpoints, mismos request/response, mismo `result`,
   misma persistencia. Cero regresión en los tests existentes de `owner_pet`.
3. **Stock SOLO vía `apply_stock_movement()`** (`apps/inventory/services.py`).
   Prohibido escribir `Product.stock_quantity` / `Presentation.stock` directo.
4. **VALIDATE = dry-run real: cero escrituras. COMMIT = una transacción atómica**
   con savepoint por fila. Validate y commit comparten proyección/validación →
   el preview no miente.
5. **Multi-tenant**: toda query va `for_organization(org)` primero. Cross-org
   → 404. Nunca confiar en IDs del cliente. Solo `public_id` expuesto.
6. **Sin IA para mapping**: solo alias deterministas (`suggest_mapping`).
7. **No inventar valores**: "abc" → decimal es ERROR, no 0. Precios no se
   default-ean. Bool ambiguo es ERROR, no False silencioso.
8. **Views delgadas**, lógica en services. Permisos `import.*` (ADMIN),
   `NotDemoAccount`, throttles `import_upload`/`import_commit` intactos.
9. **Frontend**: reutilizar el wizard actual (CSS module, componentes);
   parametrizar, no duplicar ni rediseñar. Errores con `apiError()`.
10. **Actualizar docs** al cambiar contratos: `docs/modules/imports.md`,
    `docs/modules/inventory.md`, ADR nuevo.

---

## 1. Objetivo

Extender el importador CSV/Excel existente (ADR p43) para migrar el catálogo de
inventario de clínicas que adoptan VetCare:

```text
Archivo (.csv/.xlsx)
  → ImportJob(entity_type='inventory')
  → auto-mapping + mapping manual
  → validate (dry-run, sin escrituras)
  → commit atómico
       Product (+ Presentation única)
       └─ StockMovement('in') vía apply_stock_movement  ← ledger auditable
```

## 2. Decisiones aprobadas (cerradas, no reabrir)

| # | Decisión |
|---|---|
| D1 | `entity_type='inventory'` — choice NUEVO. No reutilizar `ENTITY_PRODUCT='product'` (choice muerto preexistente en `ImportJob`, nunca alcanzable por API; se deja intacto). |
| D2 | Agregar `Product.extra_data` (`JSONField(default=list, blank=True)`) para columnas históricas desconocidas — mismo formato/caps que patients: `{label, value, source_column, imported_at}`, máx 50 entradas × 500 chars valor × 120 label. Read-only display. |
| D3 | `presentation.sale_price` **required**: fila sin decimal > 0 válido ⇒ error bloqueante (constraint DB `presentation_sale_price_positive`; billing lo exige). Nunca default monetario. |
| D4 | `product.base_unit` ausente o no reconocida ⇒ **warning + `'unit'`** (Presentation.base_unit es NOT NULL; no existe estado "pendiente" modelado). |
| D5 | **Grano v1: 1 fila = 1 Product + 1 Presentation** (la principal). Multi-presentación por producto queda EXCLUIDA de esta fase — documentar como crecimiento futuro (ADR §Consecuencias). |
| D6 | Frontend **parametrizado** sobre el wizard existente (selector de tipo + config por entidad). Sin pasos paralelos ni rediseño. |
| D7 | Dedup por nombre SIN identificador ⇒ **conflicto uncertain** (`duplicate_name`), no dedup automática silenciosa. Ver §5.2 (revisión post-plan). |

### D2 — Justificación explícita de `Product.extra_data` (exigida por revisión)

**Pregunta**: ¿`extra_data` pertenece al dominio `Product` o es contaminación del
importador?

**Respuesta defendida en ADR p61**: pertenece, porque NO es un concepto del
importador sino del **modelo histórico/migración del SaaS**, ya consolidado:

- Precedente estructural idéntico: `Owner.extra_data` y `Pet.extra_data`
  (`apps/patients/models.py:44,121`, `JSONField(default=list, blank=True)`) —
  definidos por ADR p43 §4 como "DATO HISTÓRICO del sistema anterior, NO custom
  fields". El campo no existe "porque el importador lo necesita": existe porque
  la migración es un caso de uso permanente del producto (cada clínica nueva que
  adopta llega con su padrón) y el dato histórico debe vivir pegado al registro.
- Sin el campo no hay alternativa arquitectónicamente compatible: los extras son
  por-registro; guardarlos solo en `ImportJob.result` rompería la asociación
  registro↔dato una vez commitado el job, y crear un modelo puente sería un EAV
  encubierto (explícitamente prohibido por ADR p43 §4).
- Mismas garantías que patients: read-only (sin endpoints de edición), display
  en ficha, sin reglas de negocio que lo lean (billing/analytics/caja jamás),
  caps idénticos (50 entradas × value 500 × label/source_column 120),
  `source_column` = nombre original inmutable.
- Estrategia de promoción heredada: si varias clínicas necesitan un dato concreto,
  se construye feature real + migración desde `extra_data` — nunca EAV.

**Alternativa considerada y rechazada**: importar inventario v1 sin soporte de
extras → las columnas desconocidas del catálogo viejo ("Proveedor anterior",
"Ubicación en estante") se pierden irrecuperablemente, contradiciendo el
propósito declarado del importador (ADR p43: "las columnas desconocidas no se
pierden").

El ADR p61 DEBE contener esta justificación textualmente (§Decisión).

Dedup strategy: **solo `skip`** (v1 ya rechaza `update`/`create_anyway` en
`views._VALID_DEDUP`). Para inventario skip es correcto: jamás pisar precios/
costos que alimentan billing.

## 3. Arquitectura descubierta (contexto mínimo indispensable)

Flujo actual owner_pet (fuente: código):

```text
POST /api/imports/ (multipart)      views.py:create → parse_file() [parsers.py]
ImportJob(pending, source_columns, rows, mapping={})        [models.py]
PATCH  /imports/<pid>/mapping/      {header: target | {target,label}}
POST   /imports/<pid>/validate/     validate_job() dry-run → status=validated
POST   /imports/<pid>/commit/       commit_job() atomic+savepoints → committed
```

- `services.py` NO despacha por entity_type: toda la lógica es owner_pet inline
  (`_project_row` genérico; `clean_owner_pet_row`, dedup, `_resolve_owner`
  específicos).
- `normalization.py`: `FIELD_CATALOG[entity_type]`, `_COLUMN_ALIASES[entity_type]`,
  `suggest_mapping` (alias exactos sobre `normalize_text`, sin doble asignación),
  extras `*.extra` many→1 exentos del check 1:1.
- Result shape canónico `_base_result()`: contadores agregados autoritativos +
  arrays-muestra capeados (preview 20 / skipped 10); invariante
  `conflicts_high + conflicts_uncertain == skipped_conflicts`;
  commit bloqueado si `result.blocking` ≠ [] (views.py:176); re-commit → 409.
- Tenant/permisos: `TenantQueryMixin` + `PublicIdLookupMixin`,
  `_PERMISSION_BY_ACTION` (`import.list/retrieve/create/commit`),
  `NotDemoAccount`, throttles scoped.
- Frontend `pages/imports/`: wizard dueño del estado/red (`index.jsx`);
  `uploadImport(file, entityType)` YA parametrizado (`api/imports.js:8`);
  `MappingStep`/`DestinationPicker` genéricos salvo constantes
  `EXTRA_OWNER="owner.extra"`/`EXTRA_PET="pet.extra"` hardcodeadas;
  `PreviewStep`/`ResultStep`/`UploadStep` con copy/columnas de mascotas incrustadas.
- Inventario (ADR p31): `Product.stock_quantity` (Decimal 14.4) es fuente
  autoritativa; `Presentation.stock` es copia display;
  `apply_stock_movement(presentation, qty_base, 'in'|'out'|'adjustment', org, …)`
  es el ÚNICO escritor (lock `select_for_update` sobre Product, `F()` expressions,
  dual-write a Presentation.stock, crea `StockMovement(quantity_unit='base')`).
  Caller DEBE estar dentro de `transaction.atomic()`.
  Unicidades relevantes: `(organization, internal_code)` y barcode único parcial
  por org (`WHERE barcode <> ''`, índice `presentation_barcode_org_uniq`).
  `audit_stock_integrity`: baseline = último adjustment base; productos sin
  baseline ⇒ `no_baseline` informativo (no drift).

## 4. Catálogo de campos (`FIELD_CATALOG['inventory']`)

| Target key | Label | Group | importance | Regla |
|---|---|---|---|---|
| `product.name` | Nombre del producto | Producto | required | `PRODUCT_NAME_REGEX` (reusar de `apps/inventory/serializers.py`) |
| `presentation.sale_price` | Precio de venta | Presentación | required | decimal > 0; inválido ⇒ blocking (D3) |
| `product.internal_code` | Código interno | Producto | recommended | identidad dedup; vacío ⇒ auto-generado (algoritmo exacto §5.3) |
| `product.category` | Categoría | Producto | recommended | alias→choices; no reconocida ⇒ warning + `'other'` |
| `product.base_unit` | Unidad base | Producto | recommended | alias→`BASE_UNIT_CHOICES`; vacía/desconocida ⇒ warning + `'unit'` (D4) |
| `product.stock` | Existencia inicial | Producto | recommended | decimal ≥ 0 (unidades de presentación; ×cf→base); vacío ⇒ 0 |
| `product.min_stock` | Stock mínimo | Producto | optional | ≥ 0; se guarda en base (×cf), paridad con alta manual |
| `presentation.name` | Nombre de la presentación | Presentación | optional | vacío ⇒ `product.name` (igual que alta manual) |
| `presentation.conversion_factor` | Factor de conversión | Presentación | optional | decimal > 0; default 1; `quantity = conversion_factor` |
| `presentation.barcode` | Código de barras | Presentación | optional | conflicto (archivo u org) ⇒ conflict → fila omitida |
| `presentation.purchase_price` | Precio de compra | Presentación | optional | ≥ 0 |
| `product.description` | Descripción | Producto | optional | texto |
| `product.manufacturer` | Fabricante | Producto | optional | texto |
| `product.requires_prescription` | Requiere receta | Producto | optional | bool estricto (sí/no/true/false/1/0/x); ambiguo ⇒ ERROR |
| `product.extra` (`is_extra: true`) | Dato del producto | Datos del sistema anterior | optional | many→1, mecánica Fase D intacta |

Alias de encabezados (`_COLUMN_ALIASES['inventory']`, claves normalizadas):
producto/artículo/nombre producto/artículo→name · codigo/código interno/codigo
producto/sku/clave→internal_code · categoria/categoría/tipo/rubro→category ·
unidad/unidad base→base_unit · existencia/stock/existencia inicial/cantidad/
inventario→stock · minimo/mínimo/stock minimo/punto de reorden→min_stock ·
precio/precio venta/precio de venta/pvp→sale_price · precio compra/costo/costo
compra→purchase_price · presentacion/presentación/formato→presentation.name ·
factor/factor de conversión/contenido/piezas por caja→conversion_factor ·
codigo de barras/codigobarras/upc/ean→barcode · descripcion/descripción/detalle→
description · fabricante/laboratorio/marca→manufacturer · receta/requiere receta→
requires_prescription.

## 5. Deduplicación (estrategia final)

### 5.1 Identidad y conflictos fuertes

- **Identidad de Product**: `normalize_text(internal_code)` si viene mapeado y no
  vacío. El código ES la identidad del producto en este dominio (único por org,
  usado por POS/StockEntryModal para lookup).
- Mismo código dos veces EN el archivo ⇒ conflicto `duplicate_internal_code`
  (high si nombre coincide, uncertain si difiere) → fila omitida.
- Código existente en la org ⇒ conflicto con contexto
  `incoming{...}/existing{name, public_id}` (mismo patrón que `legacy_id`,
  bulk fetch previo con `filter(internal_code__in=...)`) → omitida.
- **Barcode**: presente en archivo y (ya visto en el archivo ∨ existe en org) ⇒
  conflicto `duplicate_barcode` → omitida. El índice único parcial respalda en DB;
  el savepoint de fila captura la carrera como red de seguridad.

### 5.2 Nombre sin identificador ⇒ conflicto UNCERTAIN, no dedup automática
(revisión post-plan — punto 4)

Regla anterior ("mismo nombre normalizado sin códigos ⇒ duplicado →
`skipped_duplicates`") queda **REEMPLAZADA**. Tensión detectada: los nombres NO
son únicos por diseño (dos "Paracetamol" pueden ser productos legítimamente
distintos por concentración/presentación), por lo que convertir
`mismo nombre → skip` automático puede descartar un producto real y perder datos
en silencio; y convertirlo a `create` automático puede duplicar catálogo que
alimenta billing/POS.

**Nueva regla**: fila con `internal_code` vacío cuyo `normalize_text(name)`
coincide con otro nombre ya visto EN el archivo o con un Product existente en la
org ⇒ **conflicto `duplicate_name`, `match_confidence='uncertain'`**, con contexto
`incoming{...}/existing{name, public_id}` → **la fila se omite y se reporta**
(cuenta en `conflicts_uncertain`; NO en `skipped_duplicates`). El usuario la ve
en el preview como "posible duplicado" y decide: agrega códigos internos al
archivo para desambiguar y re-mapea, o confirma sabiendo qué se omitió.

**Por qué esto es seguro (documentar en ADR)**:

1. Cero pérdida silenciosa: cada fila afectada aparece en `conflicts[]` con
   nombre/código/contexto y `public_id` del existente — visible antes de commit,
   nunca auto-descartada.
2. Los conflictos uncertain NO bloquean commit (paridad con `legacy_id`
   uncertain de v1): importar sigue siendo posible; solo exige decisión explícita.
3. Evita contaminación irreversible-en-la-práctica: dos "Paracetamol" creados son
   dos SKUs vendibles en POS con stock separado; limpiarlos después (soft delete)
   es propenso a error. Omitir+reportar es reversible (re-importar con código).
4. Coherencia de dominio: en patients el nombre SÍ participa de la identidad
   (`(owner, normalize(name), species)`); en inventario no — la identidad es el
   código. Tratar el nombre como identidad débil (uncertain) y no fuerte (skip)
   refleja exactamente esa diferencia.
5. Determinista y testeable: sin heurísticas; misma máquina de conflictos
   `_append_conflict` existente.

- **Presentation**: siempre se crea bajo el producto nuevo (skip nunca toca
  productos existentes ⇒ nunca hay presentaciones sobre productos reutilizados).

### 5.3 Algoritmo exacto: `internal_code` automático (punto 3)

El modelo define `internal_code = CharField(max_length=100)` NOT NULL con
`unique_together = [['organization', 'internal_code']]` en DB
(`apps/inventory/models.py:35,69`) — no admite NULL ni blank. El patrón tmp→final
YA existe en el alta manual (`ProductSerializer.create`,
`apps/inventory/serializers.py:187-194`); el importador lo replica VERBATIM
dentro del savepoint de fila (que a su vez vive dentro de la transacción única
del job):

```text
1. INSERT  Product.objects.create(..., internal_code=f'__tmp_{uuid4().hex}', ...)
2. UPDATE  product.internal_code = f'PROD-{org.id}-{product.pk:04d}'
           product.save(update_fields=['internal_code'])
```

Garantías:

- **Unicidad**: `uuid4().hex` hace colisional-negligible el INSERT temporal;
  el código final incrusta el PK (único por tabla ⇒ único por org). Dos imports
  concurrentes reciben PKs distintos ⇒ códigos finales distintos.
- **Concurrencia**: la unicidad `(organization, internal_code)` está en DB; ante
  una colisión teórica de tmp, el savepoint de fila captura el `IntegrityError`
  y la fila se reporta (no tumba el job).
- **Atomicidad**: ambos pasos comparten transacción; si algo falla después, el
  rollback del savepoint revierte también el UPDATE.
- **Dedup no depende de códigos generados**: los índices de dedup solo consideran
  códigos PROVENIENTES DEL ARCHIVO; el generado se asigna post-INSERT.
- Preview honesto: en validate, la fila sin código muestra `internal_code: ''` +
  nota "se generará automáticamente"; el valor real depende del PK, que solo
  existe tras el INSERT — así lo maneja también el alta manual.

## 6. Stock inicial (contrato) — semántica VERIFICADA en código (punto 5)

Por fila importada con `stock > 0`, DENTRO del savepoint de fila y de la
transacción única del job:

```python
apply_stock_movement(
    presentation=pres,
    quantity=Decimal(stock) * cf,          # unidades BASE (cf = conversion_factor)
    movement_type='in',
    organization=org,
    reason='Stock inicial (importación)',  # razón fija, filtrable
    created_by=request.user,
)
```

### 6.1 Semántica exacta verificada (`apply_stock_movement`, services.py:17-166)

- `quantity` = unidades BASE (el caller convierte; docstring línea 41-42). Se
  cuantiza a 4 dp ROUND_HALF_UP (línea 58).
- `Product.stock_quantity` += quantity vía `F()` bajo `select_for_update`
  (líneas 108-111).
- **Dual-write en unidades de PRESENTACIÓN** (no base): líneas 116-119 —
  `Presentation.stock += quantity / conversion_factor`. El guard
  `if presentation.conversion_factor:` salta el dual-write si cf es falsy; el
  importador valida `cf > 0`, por lo que siempre aplica.
- Crea `StockMovement(quantity=qty_base, quantity_unit='base')` con FKs
  presentation+product+organization (líneas 153-166).

### 6.2 Paridad manual vs importación — CONTRATO CANÓNICO (decisión de dominio)

**Decisión registrada en ejecución**: el gate NO exige igualdad literal con el
alta manual en `Presentation.quantity`. El importador deja SIEMPRE
`quantity == conversion_factor` (semántica "alias" canónica:
`docs/modules/inventory.md`, dirección de la migración 0018 que backfillea cf
desde quantity). Motivo: el alta manual (`ProductSerializer.create`) deja
`quantity=1` con `cf=3` cuando el caller no manda `quantity` — inconsistencia
preexistente registrada como DEUDA (§9.5), no replicada por el importador.

| Estado final | Alta manual | Importación |
|---|---|---|
| `Product.stock_quantity` | `S × cf` | **idéntico** `0 + (S×cf)` ✓ |
| `Presentation.stock` | `S` | **idéntico** `0 + (S×cf)/cf = S` ✓ |
| `conversion_factor` | valor dado | idéntico ✓ |
| `Presentation.quantity` | ⚠️ `1` si caller no manda quantity (**deuda §9.5**) | `= conversion_factor` (canónico) |
| `StockMovement` | ninguno | UNO `'in'`, qty=`S×cf`, unit='base', reason fija |

La división `/cf` del dual-write cancela exactamente la multiplicación previa ⇒
paridad EXACTA en los campos autoritativos para cualquier `cf > 0` (test con
`cf=1`, `cf=3`, y `cf` no divisor p.ej. `S=1, cf=3`). Única diferencia permitida
entre rutas: la existencia/motivo del movimiento (proveniencia).

- `reason='Stock inicial (importación)'` fijo (paridad con
  `'Entrada de mercancía'` de StockEntryModal).
- `audit_stock_integrity` reportará estos productos como `no_baseline`
  (informativo) — igual que el alta manual, que tampoco genera movimiento.
  NO copiar ese patrón de escritura directa; usar siempre el servicio.
- Sin doble conteo: re-commit imposible (409 por status) y el job completo es UNA
  transacción.
- Nota de escala: lock de Product por fila ≡ lock por teléfono nuevo ya
  documentado en imports.md (tope MAX_ROWS=2000 acota).

## 7. Cambios por archivo

### Backend

| Archivo | Cambio |
|---|---|
| `backend/apps/inventory/models.py` | + `extra_data = models.JSONField(default=list, blank=True)` en `Product` |
| `backend/apps/inventory/migrations/00XX_product_extra_data.py` | Autogenerada (`makemigrations inventory`) |
| `backend/apps/imports/models.py` | + `ENTITY_INVENTORY = 'inventory'` a `ENTITY_CHOICES` (+ migración de choices autogenerada en `apps/imports/migrations/`) |
| `backend/apps/imports/normalization.py` | + entrada `'inventory'` en `FIELD_CATALOG` y `_COLUMN_ALIASES` (§4) · + `normalize_category(raw) -> str|None` · `normalize_base_unit(raw) -> str|None` (aliases: pieza/pza→piece, tableta/tab→tablet, capsula→capsule, ampolla→ampoule, frasco→bottle, bolsa→bag, tubo→tube, kg/g/ml/vial/unit passthrough) · `parse_decimal(raw) -> (Decimal|None, ok)` (acepta `$`, espacios, separador decimal `.` o `,` CONSISTENTE; separadores mixtos/miles ⇒ not-ok) · `parse_bool(raw) -> bool|None` (None = ambiguo ⇒ caller decide error) |
| `backend/apps/imports/services.py` | Refactor pequeño: `validate_job(job)`/`commit_job(job)` pasan a ser dispatchers por `job.entity_type` (inventory → nuevos; resto → implementaciones actuales renombradas `_validate_owner_pet_job`/`_commit_owner_pet_job`). Helpers y lógica owner_pet intactos. `_base_result()` extiende contadores ADITIVOS: `created_products: 0, created_presentations: 0, initial_stock_movements: 0` (owner_pet los deja en 0; aditivo no rompe contrato) |
| `backend/apps/imports/services_inventory.py` (**NUEVO**) | Espejo estructural de owner_pet: `clean_inventory_row(data, org) -> (clean, errors, warnings)` · `_build_existing_index(org, rows, columns, mapping)` bulk fetch products por internal_code + presentations por barcode (values solo public_id) · `_validate_inventory_job(job)` / `_commit_inventory_job(job)` · `_preview_row()` shape: `{row, name, internal_code, category, base_unit, stock, sale_price, barcode}` · commit: transacción global + savepoint por fila → `Product.objects.create(..., extra_data=product_extra)` (sin código ⇒ algoritmo exacto de §5.3) → `Presentation(..., quantity=cf, full_clean())` → `apply_stock_movement(...)` si stock>0 · conflictos `duplicate_internal_code`, `duplicate_barcode`, `duplicate_name`(uncertain, §5.2) · `_CONSTRAINT_MESSAGES`: `presentation_barcode_org_uniq`→msg amigable, unicidad internal_code→msg amigable · `_humanize_exc` análogo |
| `backend/apps/imports/views.py` | `_ALLOWED_ENTITY_TYPES` += `ENTITY_INVENTORY` · `commit()` pasa `created_by=request.user` a `commit_job` para auditar el StockMovement inicial (extensión aprobada en ejecución: el thread-local no se llena bajo `force_authenticate`, y sin esto el ledger perdería el autor). Dispatcher `commit_job(job, created_by=None)` es backward-compatible |

Intactos por diseño: `parsers.py`, `serializers.py`, permisos/throttle,
mixins tenant, `_VALID_DEDUP={'skip'}`, bloqueo de commit con `blocking[]`.

### Frontend

| Archivo | Cambio |
|---|---|
| `frontend/src/pages/imports/entityConfig.js` (**NUEVO**) | Config por entidad: `{ title, subtitle, uploadCopy, previewColumns: [{key,label,value(row)}], counterLabels, fieldHints, confirmNoun }` para `owner_pet` e `inventory` |
| `index.jsx` | Estado `entityType` (default `'owner_pet'`); selector "¿Qué vas a importar?" en paso 1; pasa config; mensaje de confirm usa `created_pets` ó `created_products` según entidad |
| `UploadStep.jsx` | Prop `entityType`/copy desde config |
| `MappingStep.jsx`, `DestinationPicker.jsx` | Des-hardcodear `EXTRA_OWNER`/`EXTRA_PET`: derivar extras de `fieldCatalog.filter(f=>f.is_extra)` (labels desde el catálogo; para owner_pet produce exactamente los valores actuales ⇒ cero regresión) |
| `PreviewStep.jsx`, `ResultStep.jsx` | Reciben config (default = owner_pet ⇒ tests actuales verdes); tabla/textos/ayudas desde config |

### Documentación

- `docs/modules/imports.md`: sección `entity_type=inventory` (grano D5, dedup §5,
  stock §6, contadores nuevos, caps).
- `docs/modules/inventory.md`: nota del importador + `Product.extra_data`.
- `docs/decisions/2026-08-25-p61-importador-inventario.md` (**NUEVO ADR**):
  decisiones D1–D7 · grano 1:N marcado explícitamente como crecimiento futuro ·
  justificación textual de `Product.extra_data` (§2 D2) · racional de
  nombre-como-conflicto-uncertain (§5.2) · algoritmo `internal_code` automático
  (§5.3) · semántica de stock y paridad manual-vs-importación (§6) · deuda
  detectada (§9).

## 8. Tests

Nuevo `backend/apps/imports/tests/test_inventory_import.py` (nivel de cobertura
del existente `test_owner_pet_import.py`, 43 casos):

- **Normalización**: aliases categoría/unidad; decimales válidos ("12.50",
  "12,50", "$12.50"→ok; separadores mixtos "1,234.56"/"1.234.56", "abc", "",
  "-5"→not-ok — el signo parsea, la regla ≥0/>0 es del caller); bools
  ("sí","no","true","0","x" ok; "tal vez"⇒ambiguo).
- **Auto-mapeo**: aliases inventario; sin doble asignación; columna desconocida.
- **Mapping**: destino duplicado rechazado; target desconocido; falta required
  (name/sale_price); `product.extra` many→1 exento.
- **Validación de fila**: nombre requerido/regex; sale_price requerido (>0);
  stock negativo/no numérico ⇒ blocking; factor ≤ 0 ⇒ blocking; categoría/unidad
  desconocida ⇒ warning+default; bool ambiguo ⇒ error; barcode vacío ok.
- **Dedup/conflictos**: producto nuevo; código duplicado en archivo (high);
  código en DB con nombre distinto (uncertain); nombre repetido SIN código en
  archivo y vs DB ⇒ conflicto `duplicate_name` uncertain (omitida+reportada,
  NO `skipped_duplicates`, NO bloqueante); barcode visto-en-archivo y en DB;
  contexto incoming/existing con public_id (nunca PK).
- **Validate**: NO escribe (0 Product/Presentation/StockMovement creados);
  idempotente; preview_total honesto == resultado del commit posterior.
- **Stock / paridad (§6.2, GATE)**: test que reproduce el alta manual equivalente
  vía API y compara estado final con la importación — `Product.stock_quantity`
  y `Presentation.stock` IDÉNTICOS para `cf=1`, `cf=3` entero y `cf` no divisor
  (`S=1, cf=3`); única diferencia permitida: existencia/motivo del
  `StockMovement('in', base)`. Commit: crea Product+Presentation+Movement;
  `quantity == cf`; auto-código según §5.3 (tmp→`PROD-{org}-{pk}`, dos pasos en
  misma transacción); extra_data con source_column/imported_at; created_by.
- **Atomicidad**: fila con barcode duplicado en DB no tumba el resto ni deja
  Product huérfano; rollback total ante error fuera de savepoint.
- **Re-commit → 409; commit bloqueado con blocking[] (crea 0 registros);
  warnings/conflicts no bloquean.**
- **Tenant**: job de otra org → 404; barcode/internal_code de otra org NO
  conflictúan; non-admin 403; demo account bloqueada.
- **Regresión**: suite completa `owner_pet` verde (sin modificaciones).

Frontend: tests actuales verdes con defaults; +render de config inventario
(selector de tipo, columnas de tabla, contadores, confirm noun).

## 9. Deuda detectada (reportar, NO corregir aquí)

1. `ProductSerializer.create` fija `stock_quantity` directamente SIN movimiento
   de ledger (el importador sí genera movimiento — asimetría preexistente;
   documentar en ADR).
2. Acumulación de locks de `Product` en jobs grandes (análoga a la nota de
   teléfonos; tope 2000 filas la acota).
3. `conflicts[]` sigue sin capearse (patrón heredado de v1).
4. Grano 1 fila = 1 presentación: crecimiento futuro obligatorio (D5) cuando
   haya archivos multi-presentación reales.
5. **`ProductSerializer.create` no sincroniza `Presentation.quantity` con
   `conversion_factor`** (deja `quantity=1` con `cf=N` si el caller no manda
   `quantity` explícito). Descubierta por el gate de paridad §6.2. El importador
   usa el contrato canónico (`quantity == cf`, decisión de dominio registrada);
   corregir el serializer es OTRA fase (requiere decidir backfill/migración).

## 10. Orden de ejecución

1. Modelos + migraciones (`extra_data`, choice `inventory`).
2. `normalization.py` (catálogo + normalizadores).
3. Dispatch en `services.py` + `services_inventory.py`.
4. `views.py` allow-list.
5. Tests backend + regresión owner_pet completa.
6. Frontend: `entityConfig.js`, wizard parametrizado, tests.
7. Lint/tests completos backend + frontend; corregir hallazgos.
8. Docs + ADR.

## 11. Criterio de finalización

- [ ] `owner_pet` funciona exactamente igual (suite verde, sin cambios de behavior observable).
- [ ] `inventory` end-to-end: upload → mapping → validate (sin escrituras) → commit atómico.
- [ ] Test de paridad manual-vs-importación verde para cf=1 / cf entero / cf no divisor.
- [ ] Stock SOLO por `apply_stock_movement`, movimientos auditables (`StockMovement`, base units, razón fija).
- [ ] Dedup skip-only; nombre-sin-código ⇒ conflicto uncertain reportado (nunca skip silencioso ni create automático); preview honesto.
- [ ] Sin fugas cross-tenant; solo `public_id` expuesto.
- [ ] Tests nuevos suficientes; suite completa verde.
- [ ] Docs + ADR actualizados.
