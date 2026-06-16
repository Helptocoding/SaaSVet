# ADR p44b/c/d: Búsqueda relacional escalable + datos incompletos de importación

**Fecha**: 2026-06-16
**Estado**: Aceptado — implementado
**Contexto previo**: ADR p43 (importador), ADR p44 (paginación de Mascotas)
**Documentos relacionados**:
- `docs/modules/frontend.md` § EntitySearch, § Paginación de listas
- `docs/modules/patients.md` § Filtros (GET /api/owners/)
- `components/EntitySearch.jsx`, `api/lookups.js`, `components/lookupOptions.jsx`

## Contexto

Tras importar una clínica real (~1500 mascotas, muchos homónimos: clientes y
mascotas con el mismo nombre, teléfonos parecidos, datos parciales) aparecieron
problemas que con datos demo no existían:

1. **Selectores relacionales**: usaban `SearchSelect` crudo con `maxSuggestions=5`
   (re-slice client-side sobre el `[:20]` del backend) y renderizaban **solo el
   nombre**. "Buscar Luis" mostraba 5 y el resto desaparecía sin forma de cargar
   más; "Bella / Bella / Bella" era indistinguible.
2. **Historial clínico**: cargaba **todas** las mascotas (`getPets()` completo) +
   **todos** los medical records (`page_size:9999`) solo para contar consultas por
   mascota → no escalaba.
3. **Datos incompletos**: el importador deja campos opcionales vacíos (fecha de
   nacimiento, especie, teléfono). ¿Cómo señalarlo sin una alerta global molesta
   durante meses?

## Decisión

### EntitySearch — combobox relacional reusable (patrón único)

`components/EntitySearch.jsx` reemplaza el uso crudo de `SearchSelect` para
entidades con muchos registros. Reusa el patrón probado (debounce 250ms, race con
`reqId`, loading) pero su API soporta lo que faltaba:

- **Render rico** (`renderItem`): cada opción muestra contexto para diferenciar
  homónimos (dueño · teléfono · expediente), no un string.
- **Paginación incremental** (`fetchPage({query,page}) → {items, hasMore}` +
  "Ver más"): inicial **8**, carga más bajo demanda. **Sin tope invisible.**

Piezas compartidas (no rearmar por módulo): `api/lookups.js`
(`searchPets`/`searchOwners` → `{items,hasMore}` sobre los endpoints paginados) y
`components/lookupOptions.jsx` (`renderPetOption`/`renderOwnerOption` + labels).
`SearchSelect` se conserva para selects simples (no relacionales).

Migrados (prioridad acordada): **Citas** (3 pickers) → **Historial** →
**POS** → **Recetas**.

### p44b — Búsqueda de clientes por teléfono y expediente

`OwnerViewSet ?search` filtra ahora **nombre · teléfono · `legacy_id`**
(icontains). Paginación **opt-in por `?page`** también en el path de búsqueda
(habilita "Ver más"); sin `?page` conserva el array plano `[:20]` legacy. Índices
GIN trigram nuevos (migración 0017): `Owner.phone`, `Owner.legacy_id`,
`Pet.legacy_id`. (Pets ya buscaba por estos campos desde p44.)

### p44c — Historial clínico server-side

`PetSidebar` se reescribe a búsqueda server-side (`searchPets`, debounce +
"Ver más", inicial 12) con filas ricas (dueño · tel · exp). `index.jsx` deja de
cargar la lista completa de mascotas y el `getMedicalRecords(9999)`. La mascota
seleccionada se resuelve por `public_id` (`selectedPetObj`): el sidebar entrega el
objeto al elegir; los deep-links (`?pet=`/`?record=`) lo piden con `getPet()`. Se
elimina el badge de conteo por mascota (requería traer todos los MR).

### p44d — Datos incompletos: estrategia C + D (no alertas globales)

Se distingue **requerido-para-operar** (nombre — ya garantizado por el importador)
de **deseable** (fecha nac., especie, raza, sexo, color, teléfono — normal en
veterinaria). Nunca se tratan igual.

- **C (resumen al importar)**: `ResultStep` agrega los `warnings` del backend en
  "N mascotas sin fecha de nacimiento / sin especie / N clientes sin teléfono".
  Informativo, una sola vez.
- **D (prompt suave en la ficha)**: `petDetail` muestra un botón discreto
  "Completar datos (…)" cuando faltan campos opcionales → abre la edición vía
  `/pets?edit=<public_id>` (que carga la mascota por id y abre el modal). Sin
  alerta global.

Descartadas: **A** (alertas permanentes — ruido por meses) y un **score de
completitud** global como protagonista.

## Consecuencias

**Positivas**: los selectores escalan a miles de registros con contexto suficiente
para elegir bien; el historial ya no carga toda la clínica a memoria; los datos
incompletos se comunican sin fricción permanente. El patrón `EntitySearch` es
único y reusable.

**Negativas / deuda aceptada**:
- El carve-out "paginar solo con `?page`" (pets y owners) es convención implícita;
  un dropdown que mande `?page` por error recibiría un envelope. Documentado y
  testeado.
- `prescriptions.jsx` (página) aún carga la lista completa de mascotas para otros
  usos; solo se migró su **selector**. Fuera de alcance.
- El historial perdió el badge de "N consultas" por mascota en el sidebar (el
  conteo del pet seleccionado lo da el timeline). Trade-off por no traer todos los
  MR.
- `petDetail` arrastra deuda react-hooks preexistente (`calcAge`/`Date.now`,
  `loadAll` deps) — no tocada.
