# ADR p43: Importador CSV/Excel — migración de clínicas + datos del sistema anterior

**Fecha**: 2026-06-16
**Estado**: Aceptado — implementado (Fase A + Fase D)
**Documentos relacionados**:
- `docs/modules/imports.md` (módulo completo)
- `docs/modules/patients.md` § Datos del sistema anterior
- ADR p16 (cascade PROTECT), ADR p18 (public_id en superficies externas)
- ADR p33 (UX de wizard — precedente de "una pantalla, no formulario gigante")
- `apps/imports/`, `frontend/src/pages/imports/`

## Contexto

Una clínica que adopta VetCare llega con su padrón en Excel/CSV del sistema viejo
(cientos/miles de clientes y mascotas). Sin importador, la única vía es captura
manual → barrera de adopción. Los archivos reales son **sucios**: encabezados
inconsistentes ("Dueño"/"Cliente"/"Propietario"), especies en texto libre
("Perro"/"PERRO"/"canino"), clientes sin teléfono, fechas en varios formatos, y
**columnas que no existen en nuestro modelo** ("Veterinario favorito", "Última
estética", "Código viejo", "Adeudo anterior").

Dos tensiones de diseño:
1. Validar como en el alta manual (teléfono 10 díg obligatorio, especie del catálogo)
   rechazaría la mayoría de los datos históricos legítimos.
2. Conservar las columnas desconocidas sin convertir VetCare en una hoja de cálculo
   configurable (custom fields / EAV) que erosione el modelo estructurado del SaaS.

## Decisión

### 1. Sesión persistida `ImportJob`, flujo en 3 fases

`ImportJob(PublicIdMixin, OrganizationalModel)` guarda `source_columns` + `rows`
(JSON, sin binario) + `mapping`. Flujo **upload → mapping → validate (dry-run) →
commit (atómico)**. `validate` y `commit` comparten proyección/validación de fila →
el preview no miente. v1 = `entity_type=owner_pet`; **CSV + XLSX** desde el día 1
(parser interface → `CSVParser` | `ExcelParser`, openpyxl). Caps: 5 MB / 2000 filas /
50 columnas.

### 2. El importador escribe por `.save()` directo (boundary), no por serializers

Es la decisión de arquitectura central. El importador vive en su propio dominio
(`apps/imports`) y escribe `Owner`/`Pet` con `.save()`, **saltando**
`OwnerSerializer`/`PetSerializer`. Consecuencia controlada en `patients`:

- `Owner.phone = blank=True` y `Pet.species = blank=True` **a nivel modelo**, pero la
  API manual (serializers) **sigue exigiéndolos**. La relajación vive **solo** en el
  importador. Datos históricos sucios ≠ datos nuevos.
- `legacy_id` en Owner + Pet (`CharField blank=True default=''`, único parcial por org
  cuando está presente). Referencia del expediente viejo, no PK. UI: "Número de
  expediente anterior".
- Una fila inválida **no aborta** el lote: savepoint por fila, con `owner` y `pet` en
  savepoints **separados** (un pet que falla no deja un owner huérfano cacheado).

### 3. Dedup `skip + report`; teléfono y especie opcionales

- Dedup: owner por `(org, phone)`; sin teléfono → dedup interna por nombre normalizado
  en el archivo. Pet por `(owner, normalize(name), species)` (normalizado, no exacto).
  Estrategia `skip` (v1): el duplicado se salta y se reporta, nunca pisa datos.
- Especie no reconocida o ausente → mascota pendiente (`species=''`) con warning; nunca
  bloquea ni asigna un default en masa.

### 4. `extra_data` = DATO HISTÓRICO del sistema anterior (Fase D), NO custom fields

Las columnas sin campo equivalente se conservan en `Owner.extra_data` / `Pet.extra_data`
(`JSONField(default=list)`):

```json
[ { "label": "Veterinario anterior", "value": "Dr Luis",
    "source_column": "Vet Fav", "imported_at": "2026-06-15T10:00:00+00:00" } ]
```

- `source_column` = nombre **original** de la columna; renombrar el `label` (en el
  mapeo) **no** lo cambia → siempre se sabe de dónde vino el dato.
- **Read-only** (read_only en serializers; sin endpoints de edición). **No queryable**:
  solo display en la ficha. **Sin reglas de negocio**: billing/analytics/caja nunca lo
  leen. Caps: 50 entradas, value 500, label/source_column 120. Texto plano, sin bleach
  (React escapa; el origen es Excel).
- **Estrategia de promoción**: si varias clínicas necesitan un dato concreto, se crea
  una feature **real** (modelo + validación + formulario + permisos + writer + migración
  desde `extra_data`). Explícitamente **NO** se introducen EAV, custom fields ni
  formularios generados desde `extra_data`. El SaaS se mantiene estructurado.

### 5. UX de mapeo = import wizard, no herramienta ETL

El mapeo no expone el modelo interno. "VetCare entendió tu Excel, solo revisa unas
cosas":
- Columnas auto-reconocidas → resumen colapsable compacto (grid), no formularios.
- Columnas a revisar → cards compactas; **una decisión** por columna ("¿Qué representa
  esta columna?") vía `DestinationPicker` (modal acordeón: Cliente / Mascota / Datos
  del sistema anterior / No usar; una categoría abierta a la vez). Decisión siempre
  reversible; renombre del label solo para datos históricos.
- Lenguaje de migración en toda la superficie (ficha: "Datos importados del sistema
  anterior 🔒 — no se actualizan automáticamente").

### 6. Acceso ADMIN-only + throttle

Permisos `import.{list,retrieve,create,commit}` asignados a ADMIN (`*.*`). Es operación
de migración, no de uso diario. `ScopedRateThrottle` en upload y commit.

## Consecuencias

**Positivas**: adopción sin captura manual; tolera archivos reales sucios sin perder
registros; preview honesto (validate == commit); sin acoplamiento a otros dominios (no
crea facturas ni stock); las columnas desconocidas no se pierden ni contaminan el
modelo estructurado.

**Negativas / deuda aceptada**:
- **Facturas draft de $0 no aplica aquí** — el importador no toca billing.
- `extra_data` acumula posible basura/PII por columna; mitigado por consentimiento por
  columna (sin default silencioso) + caps + read-only. Es decisión consciente del usuario.
- Bug latente fuera de alcance detectado: `PetSerializer.update` hace
  `validated_data.pop('owner')` → un PATCH de ficha **sin** `owner` daría 500 (el front
  siempre manda `owner`, no se manifiesta). No se corrige en este sprint.

**Excluido de v1** (decisión de producto):
- **Fase B**: estrategia `update` (sobrescribir existentes) + reporte de errores
  descargable.
- **Fase C**: importación de productos/inventario.
- Edición manual de `extra_data`, custom fields, EAV (ver §4 — explícitamente no).
