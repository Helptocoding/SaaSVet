# ADR p42: Paginación opt-in por endpoint para listados de alto volumen (P1-2)

**Fecha**: 2026-06-13
**Estado**: Aceptado — implementado (pre-beta)
**Documentos relacionados**:
- `docs/system-reference.md` §2 (dependencias críticas: `for_organization()` primero en el queryset)
- `docs/system-reference.md` §3 (invariante 1: multitenancy estricto, cross-org = 404)
- `docs/deferred-decisions.md` DD-013 (paginación diferida de páginas con filtro/KPI client-side)
- Código backend: `apps/core/pagination.py`, `apps/core/filters.py`,
  `apps/billing/views.py` (Invoice), `apps/inventory/views.py` (StockMovement),
  `apps/patients/views.py` (Owner), migraciones `billing 0024`, `inventory 0020`
- Código frontend: `frontend/src/utils/toList.js`, `frontend/src/components/Pagination.jsx`,
  `pages/billing.jsx`

## Contexto

Ningún listado estaba paginado salvo `medical_records` (`MedicalRecordPagination`,
PageNumber 10, pre-existente). No había `DEFAULT_PAGINATION_CLASS` global → DRF
devolvía el queryset **completo** como array crudo en `GET /invoices`,
`/appointments`, `/inventory/movements`, `/pets`, `/owners`, etc.

A escala (una clínica con meses/años de operación: ~6k–25k facturas/año, 50k+
movimientos de inventario, miles de citas) esto produce respuestas enormes,
consumo de RAM del backend, queries caras en Postgres y riesgo de **timeout**.

Restricción de esta fase: **no romper compatibilidad frontend** (prioridad #1),
**no sobreingeniería** — diseñar para las primeras 10–50 clínicas, no para
millones de usuarios. Cambios incrementales y reversibles.

## Decisión

Introducir paginación **opt-in por endpoint** (NO global), solo en los listados
de mayor volumen cuyo consumidor frontend es seguro de paginar.

### 1. NO se activa `DEFAULT_PAGINATION_CLASS` global

Un default global envolvería **todos** los listados — incluidos los endpoints
`?search` con slice `[:20]` que alimentan los `SearchSelect` (Pet/Owner/Service)
y los consumidores que hacen `.map()` directo sobre un array. Eso rompería los
dropdowns en masa. La paginación se declara **por view** (`pagination_class`),
dejando catálogos chicos y endpoints de búsqueda como arrays planos.

### 2. Dos clases de paginación

| Clase (`apps/core/pagination.py`) | Tipo | `page_size` / `max` | Usada por |
|---|---|---|---|
| `StandardResultsPagination` | PageNumber | 25 / 100 | Invoices, Owners |
| `StockMovementCursorPagination` | Cursor | 50 / 100, orden `(-created_at, -id)` | StockMovement |

PageNumber para tablas administrativas (offset aceptable a esta escala, soporta
"página N de M"). **Cursor solo para `StockMovement`**: ledger append-only de alto
volumen (50k+) donde el offset profundo degrada y los inserts concurrentes
desplazarían filas; el cursor hace keyset scan estable. No se usa
`LimitOffsetPagination` (PageNumber cubre el caso sin valor añadido).

### 3. Endpoints paginados (lo que sí entró)

| Endpoint | Paginación | Nota |
|---|---|---|
| `GET /billing/invoices/` | PageNumber 25 + `?ordering` server-side | sort movido del cliente al backend |
| `GET /inventory/movements/` | Cursor 50 | sin consumidor UI hoy → cero riesgo frontend |
| `GET /owners/` | PageNumber 25 **con skip-on-search** | `?search` sigue devolviendo array `[:20]` |

`OwnerViewSet.paginate_queryset` devuelve `None` cuando hay `?search` → preserva
el contrato de array plano `[:20]` de los dropdowns `SearchSelect`. El listado
completo (sin search) sí pagina.

### 4. Orden estable obligatorio — tiebreaker `-id`

Toda paginación exige un **orden total** o las filas saltan/duplican entre
páginas. El dominio garantiza empates: `created_at` colisiona (ventas en la misma
transacción) y `total` colisiona masivamente (cada consulta cerrada genera un
draft en $0, ADR p30). Por eso:

- El orden default de Invoices es `('-created_at', '-id')`.
- `apps/core/filters.py::StableOrderingFilter` agrega `-id` a **cualquier**
  `?ordering` que no lo lleve (ej. `?ordering=total` → `total, -id`). Sin esto,
  ordenar por Total en Cobros duplicaba/saltaba facturas entre páginas.
- El cursor de StockMovement ordena por `(-created_at, -id)` (total order).

### 5. Índices de soporte (reversibles)

`Index(organization, -created_at, -id)` en `Invoice` (`billing 0024`) y
`StockMovement` (`inventory 0020`). Sirven el orden paginado por keyset sin sort
en memoria a 25k–50k filas. El índice **lidera con `organization_id`** (multi-tenant:
toda query filtra por org primero). `AddIndex` auto-reversible; sin data migration.

### 6. Compatibilidad frontend — `toList()`

`frontend/src/utils/toList.js`: `toList(data)` devuelve el array tal cual si la
respuesta ya es array, o `data.results` si es el envelope DRF, o `[]`. Idempotente.
Los consumidores de listas paginadas (y por robustez varios no paginados) lo usan
→ array crudo y `{count, next, previous, results}` ambos funcionan. El orden de
deploy seguro es **frontend defensivo primero, backend paginación después**: un
array sigue pasando por `toList()` sin daño. `components/Pagination.jsx` es el
paginador Anterior/Siguiente reusable (Cobros lo monta).

## Alternativas evaluadas

- **`DEFAULT_PAGINATION_CLASS` global**: rechazado. Rompería los endpoints
  `?search` `[:20]` y los `.map()` directos de los dropdowns. Opt-in por view es
  el rollout incremental seguro.
- **`LimitOffsetPagination`**: rechazado. PageNumber cubre las tablas admin sin
  valor extra.
- **Cursor para todo**: rechazado. Cursor no expone `count` (la UI de Cobros
  muestra "N cobros" y "página X de Y") y complica el front. Solo se justifica en
  el ledger de movimientos de alto volumen.
- **Paginar Products / Prescriptions / Appointments / Pets ahora**: rechazado /
  diferido (DD-013). Sus páginas filtran/agregan **client-side sobre la lista
  completa** (KPIs de inventario, filtros especie/sexo/edad de recetas, agenda/
  calendario, KPIs de pacientes). Paginarlas rompería esos filtros (solo verían
  la página actual); hacerlo bien exige filtros/KPIs **server-side** = un cambio
  de UX mayor, fuera del scope incremental de P1-2.
- **Mover el sort de Cobros a client-side bajo paginación**: rechazado. Ordenaría
  solo la página actual (engañoso en un listado financiero). Por eso el sort va
  server-side vía `?ordering` + `StableOrderingFilter`.

## Riesgos aceptados

| Riesgo | Mitigación / por qué se acepta |
|---|---|
| Cambio de contrato: array → `{results}` en invoices/owners/movements | `toList()` absorbe ambas formas; deploy frontend-primero; rollback = quitar `pagination_class` y el array vuelve sin tocar el front. |
| `?ordering=total` no tiene índice dedicado (sort en memoria) | El filtro por org + otros filtros acotan el set; a 6k–25k/año es tolerable. Si la latencia del sort por Total duele a escala → `Index(organization, total, id)` (DD-014). |
| Cobros hace doble fetch en mount (loadAll + efecto debounced) | Pre-existente, no introducido por P1-2; `requestIdRef` aplica solo la última respuesta. Cosmético. |
| Páginas con filtro client-side quedan sin paginar (Prescriptions/Appointments/Pets) | Diferido a propósito (DD-013); el riesgo de timeout real (invoices 25k, movements 50k) sí se ataca. |
| Desfase de filas entre páginas por empates | Resuelto: tiebreaker `-id` en default, `StableOrderingFilter` en `?ordering`, cursor con orden total. Test de paginación bajo `total` empatado. |

## Rollback

Diseñado para revertir **por endpoint, sin tocar el frontend**:

1. Quitar `pagination_class` de una view → ese listado vuelve a array crudo. El
   frontend con `toList()` lo sigue consumiendo igual. Desacoplamiento total.
2. Sin migraciones de datos en la paginación (solo índices). Revertir = `git revert`
   del PR del endpoint.
3. Índices: migración reversible (`RemoveIndex`); no cambian resultados, solo el
   plan → seguro.

## Consecuencias

- ✅ Los dos timeout-killers reales (Invoices ~25k, StockMovement 50k) dejan de
  serializar el dataset completo.
- ✅ Multitenancy preservada: el `count` y los links next/previous se computan
  sobre el queryset `for_organization(org)`; cross-org sigue siendo invisible.
- ✅ Dropdowns `SearchSelect` intactos (Owners skip-on-search).
- ✅ Frontend compatible con array y `{results}`; rollback trivial por endpoint.
- ✅ Orden de paginación estable (sin duplicar/saltar filas) garantizado.
- ⚠️ Contrato de respuesta cambia en 3 endpoints; mitigado por `toList()`.

## Criterio de terminado

1. `StandardResultsPagination` + `StockMovementCursorPagination` en `core/pagination.py`.
2. Invoices (PageNumber + `?ordering` + `StableOrderingFilter`), StockMovement
   (cursor), Owners (PageNumber + skip-on-search).
3. Índices `(organization, -created_at, -id)` en Invoice y StockMovement (reversibles).
4. `toList()` + consumidores crudos migrados; `Pagination.jsx`; Cobros con sort
   server-side + paginador.
5. Sin `DEFAULT_PAGINATION_CLASS` global. Products/Prescriptions/Appointments/Pets
   sin paginar (DD-013).
6. Tests: contrato paginado, aislamiento multi-tenant del `count`, cap de
   `page_size`, orden estable bajo empate, cursor sin duplicados, owners
   skip-on-search, `toList`. Regresión billing/inventory/patients/security verde.

## Fuera de scope (NO en esta fase)

**Infinite scroll**, **virtual tables**, **Elasticsearch**, búsqueda full-text
server-side, paginación de Products/Prescriptions/Appointments/Pets (requiere
filtros/KPIs server-side — DD-013), y cualquier cambio de UX mayor. Se decidirán
en su propio ADR si el negocio los requiere.
