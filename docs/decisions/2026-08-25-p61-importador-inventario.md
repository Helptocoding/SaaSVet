# ADR p61: Importador de inventario (`entity_type=inventory`)

> Continuación de orden 4 en curso: [expediente y estado](../remediaciones/orden-4/README.md); las deudas de este recibo describen el corte histórico.

**Fecha**: 2026-08-25
**Estado**: Aceptado — implementado
**Documentos relacionados**:
- `docs/PLAN-importador-inventario.md` (plan de ejecución, decisiones D1–D7)
- `docs/modules/imports.md` § Importador de inventario
- `docs/modules/inventory.md` (ADR p31 stock; `Product.extra_data`)
- ADR p43 (importador CSV/Excel — patrón base), ADR p31 (stock en unidades base)

## Contexto

El importador v1 (ADR p43) migraba solo clientes+mascotas. Las clínicas que
adoptan VetCare también llegan con su **catálogo de inventario** en Excel/CSV
(nombre, código interno, categoría, unidad, existencia, precios, barcode…).
Sin importador, capturar cientos de productos a mano es barrera de adopción.
El archivo real es sucio y el stock tiene un contrato fuerte: ledger
`StockMovement` + `apply_stock_movement()` como único escritor (ADR p31).

## Decisión

### D1 · `entity_type='inventory'` (choice nuevo)

No se reutiliza `ENTITY_PRODUCT='product'` (choice muerto preexistente, nunca
alcanzable por API): "inventario" describe lo que importa (producto +
presentación + stock). `validate_job`/`commit_job` despachan por entity_type;
la lógica vive en `services_inventory.py`.

### D2 · `Product.extra_data` pertenece al dominio, no al importador

Pregunta de revisión: ¿contaminación del modelo o necesidad del dominio?
**Es del dominio histórico/migración**, ya consolidado por ADR p43 §4:
`Owner.extra_data`/`Pet.extra_data` existen con exactamente el mismo formato y
caps ({label, value, source_column, imported_at}; 50×500×120), read-only,
sin reglas que lo lean. Sin este campo no hay alternativa compatible: los
extras son por-registro y guardarlos solo en `ImportJob.result` rompería la
asociación tras el commit; un modelo puente sería EAV encubierto (prohibido).
Estrategia de promoción heredada: dato recurrente ⇒ feature real + migración
desde `extra_data`. **Alternativa rechazada**: v1 sin extras → las columnas
desconocidas del catálogo viejo se pierden, contradiciendo el propósito del
importador.

### D3 · `sale_price` required y bloqueante

`presentation_sale_price_positive` (CHECK >0) + billing exigen precio. Fila sin
decimal >0 válido ⇒ error bloqueante visible desde validate. Nunca se inventa
dinero (se descartó default $0.01).

### D4 · Unidad ausente/desconocida ⇒ warning + `'unit'`

`Presentation.base_unit` es NOT NULL y no existe estado "pendiente" modelado.
El default es neutral, visible en preview y warnings.

### D5 · Grano: 1 fila = Product + Presentation única

Igual al alta manual (`presentation_input`). **Crecimiento futuro obligatorio**:
multi-presentación por producto cuando haya archivos reales así (hoy no existe
evidencia); el diseño de dedup skip-only no lo soporta todavía.

### D6 · Frontend parametrizado

Un solo wizard; `entityConfig.js` concentra diferencias (textos, columnas,
tarjetas, CTA). Defaults = owner_pet ⇒ cero regresión (69/69 tests). Los destinos
extra del picker se derivan de `is_extra`, sin hardcodear entidades.

### D7 · Nombre-sin-código ⇒ conflicto UNCERTAIN, no dedup automática

Los nombres NO son identidad en inventario (a diferencia de mascotas). Dos
"Paracetamol" pueden ser productos distintos por concentración. Regla: fila sin
código cuyo nombre normalizado coincide (en archivo o catálogo) ⇒ conflicto
`duplicate_name / uncertain`, fila omitida Y reportada con `existing.public_id`.
Seguro porque: (1) cero pérdida silenciosa — todo aparece en preview;
(2) conflicts no bloquean commit (paridad legacy_id-uncertain);
(3) evita duplicar SKUs vendibles en POS (limpieza posterior propensa a error);
(4) coherente: la identidad aquí es el código;
(5) determinista, misma máquina `_append_conflict`.

### Stock inicial: único escritor + gate de paridad canónico

Siempre `apply_stock_movement(pres, stock×cf, 'in', reason='Stock inicial
(importación)', created_by=request.user)` dentro del savepoint de fila. El
dual-write divide entre `conversion_factor`: paridad EXACTA con el alta manual
en campos autoritativos (`Product.stock_quantity = S×cf`,
`Presentation.stock = S`) para cualquier cf>0 — verificada por test gate.
`created_by` viaja desde la view (`commit_job(job, created_by=...)`,
backward-compatible) porque el thread-local no se llena bajo
`force_authenticate`; sin esto el ledger perdería el autor.

**Decisión de dominio registrada**: el importador deja SIEMPRE
`Presentation.quantity == conversion_factor` (semántica "alias" canónica,
dirección de la migración 0018). El gate de paridad compara el CONTRATO
CANÓNICO, no igualdad literal con el alta manual (ver Deuda #1).

### `internal_code` automático

Modelo NOT NULL + `unique_together(org, code)`. Sin código: INSERT con
`__tmp_{uuid4().hex}` → UPDATE a `PROD-{org.id}-{pk:04d}` dentro del mismo
savepoint (verbatim de `ProductSerializer.create`). Unicidad garantizada por PK
incrustado; dedup solo considera códigos provenientes del archivo.

### Rangos validados en CLEAN (preview honesto)

Topes max_digits (`money < 10^8`, `cf < 10^6`) se rechazan en validate, nunca
llegan a reventar en full_clean durante commit — validate==commit se mantiene.

## Consecuencias

**Positivas**: adopción sin captura manual del catálogo; ledger auditable desde
el día 1 (todo stock inicial trazable con razón fija filtrable); preview honesto
(validate==commit compartido); cero acoplamiento nuevo entre dominios
(imports→inventory solo consume modelos + servicio autoritativo).

**Negativas / deuda aceptada**:
1. **`ProductSerializer.create` no sincroniza `Presentation.quantity` con
   `conversion_factor`** (deja `quantity=1` con `cf=N` si el caller no manda
   `quantity`). Descubierta por el gate de paridad. El importador usa el
   contrato canónico; corregir el serializer requiere decidir backfill — OTRA
   fase.
2. Locks de Product acumulados por fila en jobs grandes (análogo a teléfonos;
   MAX_ROWS=2000 acota).
3. `conflicts[]` sigue sin capearse (heredado de v1).
4. Multi-presentación excluida (D5) — crecimiento futuro obligatorio.
5. Bloqueo demo: el handler global canóniza PermissionDenied a
   `permission_denied` (`apps/core/exceptions.py`), así que NotDemoAccount no
   expone su código específico en la respuesta (403 genérico). Contrato
   observado y documentado en tests; cambiarlo es decisión aparte.

**Excluido**: estrategia update/create_anyway para duplicados (Fase B global),
multi-presentación (D5), importación de lotes (`tracks_lots` products quedan
con stock a nivel Product; recepción multi-lote sigue siendo flujo manual B1).
