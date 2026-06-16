# ADR p44: Mascotas — paginación + búsqueda/filtros server-side (escalabilidad)

**Fecha**: 2026-06-16
**Estado**: Aceptado — implementado
**Supera**: DD-013 (entrada "Pet NO se pagina")
**Documentos relacionados**:
- `docs/modules/patients.md` § Filtros disponibles (GET /api/pets/)
- `docs/modules/frontend.md` § Paginación de listas
- ADR p42 (paginación opt-in por endpoint — precedente), ADR p18 (public_id en URLs)
- ADR p43 (importador — origen del caso: clínica con 1500 mascotas)
- `apps/patients/views.py`, `frontend/src/pages/pets.jsx`

## Contexto

Tras importar (ADR p43) una clínica con ~1500 mascotas, el módulo Mascotas se
volvió lento. Diagnóstico (causa raíz, no superficial):

1. **Sin paginación**: `GET /api/pets/` devolvía **todas** las filas. La página
   las guardaba en memoria y renderizaba ~1500 cards/filas en el DOM.
2. **N+1 de owner**: `PetSerializer` anida `OwnerSerializer` y el queryset no
   tenía `select_related('owner')` → 1 + N queries (1501 con 1500 mascotas).
3. **Búsqueda y filtros client-side**: cada tecla recorría las 1500 en memoria.
4. **Serializer pesado** (owner completo + `extra_data`) en contexto de lista.

DD-013 había diferido la paginación de `Pet` ("filtra/KPI client-side sobre la
lista completa"). Con miles de registros eso dejó de ser viable.

## Decisión

### 1. Paginación **opt-in por `?page`** (no global)

`PetViewSet` gana `pagination_class = StandardResultsPagination` (PageNumber 25,
`page_size` 25/50/100), pero `paginate_queryset` devuelve `None` **salvo que el
request traiga `?page`**. Es la decisión central y la parte no obvia:

| Request | Respuesta | Consumidor |
|---|---|---|
| `?page=N[&filtros]` | Envelope `{count, next, previous, results}` | página Mascotas |
| `?search=…` (sin `page`) | Array plano `[:20]` | dropdowns `SearchSelect` |
| sin `page` ni filtro | Array plano completo | listas client-side |

**Razón**: 6 consumidores dependen del array plano (`.then(ps => ps.map(...))`):
dropdowns de citas (×3), `PrescriptionForm`, POS `CustomerSelector`, y las listas
completas de `prescriptions` y `medicalRecords`. Paginar global los rompería.
Mismo carve-out que el `?search` de `OwnerViewSet` (ADR p42), pero discriminado
por `?page` porque en Mascotas la búsqueda SÍ debe paginar.

### 2. Filtros y búsqueda **server-side**

`get_queryset` aplica, antes de paginar: `search` (nombre · especie · raza ·
`legacy_id` · nombre y teléfono del dueño, `icontains`), `species` (caninos/felinos
vía regex tolerante a datos sucios de importación), `sex`, `age` (traducido a
rangos de `birth_date`, año = 365.25 días para empatar con `getAgeGroup` del
frontend; `birth_date` NULL queda fuera de todo bucket), `owner` (UUID). El orden
es **query completa filtrada → paginación**, nunca filtrar solo la página cargada.
Frontend: búsqueda con debounce 350ms; cualquier cambio de filtro resetea a la
página 1.

### 3. Anti-N+1: `select_related('owner')`

El listado hace `for_organization(org).select_related('owner')` (org SIEMPRE
primero, invariante tenant). El nº de queries deja de escalar con las filas.

### 4. Endpoint agregado `GET /api/pets/stats/`

Al paginar, los stat-cards (Total/Caninos/Felinos) ya no se pueden calcular sobre
la lista completa en memoria. Nuevo `@action(detail=False)` que devuelve
`{total, caninos, felinos}` de **toda la clínica** en UNA query agregada (sin N+1,
sin traer filas). Permiso `patient.list` (lectura agregada = mismo nivel que listar;
sin código RBAC nuevo). El contador "citas de la semana" reusa el endpoint
existente `status-breakdown` (conteo por rango, sin descargar filas) en lugar de
cargar todas las citas.

## Consecuencias

**Positivas**: la página Mascotas escala a 1500 → 20k+ registros (25 filas/request,
N+1 eliminado, búsqueda/filtros en DB con índice GIN trigram en `name`); los
dropdowns y listas client-side existentes quedan intactos (contrato preservado);
los stats representan siempre la clínica completa, no la página.

**Negativas / deuda aceptada**:
- El carve-out por `?page` es **convención implícita**: un futuro dropdown que
  mande `?page` por error recibiría un envelope. Documentado en `patients.md` y
  `frontend.md`; los tests lo blindan.
- `prescriptions`, `medicalRecords` siguen cargando la lista completa de mascotas
  (array plano) — mismo riesgo de escala, **fuera de alcance** de este sprint
  (cada uno necesita su propio rediseño de filtros server-side antes de paginar).
- La mascota genérica ("Paciente Anónimo") sigue contándose en stats y listándose
  (paridad con el comportamiento previo; no se tocó).

**Excluido**: paginación de Products/Prescriptions/Appointments (DD-013 sigue
vigente para ellos); ordenamiento server-side de la tabla de Mascotas (hoy no
expone `?ordering` — el orden es `name, id`).
