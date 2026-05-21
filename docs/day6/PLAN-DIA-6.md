# Plan Día 6 — Endurecimiento de IDs en superficies externas

**Versión:** Final v1.1 (consolidada de 5 fases de auditoría + post-review fixes)
**Fecha:** 2026-05-20 (plan) / 2026-05-21 (cierre implementación)
**Branch:** `develop`
**Estado:** ✅ **Implementado y testeado** (suite 184 tests OK, audit guards verde, 13 tests Día 6 invariantes verde). Cutover `ALLOW_LEGACY_ID_LOOKUP=False` pendiente de aprobación operacional + smoke staging 48h.
**Objetivo:** apagar `ALLOW_LEGACY_ID_LOOKUP` sin romper la app, cerrar P0 #18 y P1 #38-40, eliminar IDOR/enumeration latente en superficies con PK entero.

**Pipeline de auditoría aplicado:**
1. `01-draft-backend-architect.md` — draft arquitectónico inicial.
2. `02-security-annex.md` — anexo de seguridad (7 hallazgos absorbidos).
3. `03-db-annex.md` — anexo de persistencia (índices + migración + UUID version).
4. `04-code-quality-annex.md` — anexo anti-deuda (7 fixes absorbidos).
5. `05-qa-annex.md` — anexo QA (21 test files + smoke checklist).

Este documento es la fuente de verdad. Los 5 anexos quedan como traza de razonamiento.

---

## 1. Resumen ejecutivo

**Scope dentro:** URL paths de endpoints públicos, frontend `api/*.js` + pages, query params de modelos públicos, `StaffDeactivateView` (#38), `MeView`/`/organizations/me/` (#39), `CreateEmployeeSerializer.organization_id` writable (#40), promoción de `VaccineRecord` a `public_id` (hallazgo seguridad), apagado controlado de `ALLOW_LEGACY_ID_LOOKUP`.

**Scope fuera (no se toca):** PKs internos en joins, FKs body fields (`pet`, `owner`, `medical_record`, `product`, `presentation` → `PrimaryKeyRelatedField`), `InvoiceItem.id`, `MRP.id`, `MRS.id`, `StockMovement.id`, `VitalSigns.id`, `username` UNIQUE global (deuda conocida P2 #46), `Service.unique_together` sin org (P2 #43), migración UUID v4 → v7 de modelos existentes.

**Blast radius:** medio. Cambios concentrados en URL kwargs (`<int:>` → `<str:>`), constructores de URL en frontend, serializadores de respuesta y 3 migraciones aditivas (`Organization`, `User`, `VaccineRecord`).

**Resultado de éxito:** con `ALLOW_LEGACY_ID_LOOKUP=False` toda navegación, CRUD, deep link y flujo clínico/cobro funciona. Cero 404 atribuibles a IDs. Suite de tests verde + smoke staging 48h.

---

## 2. Convenciones de IDs (nuevas — llevar a CLAUDE.md)

| Capa | Convención |
|---|---|
| Backend Python / DB / JSON | `public_id` (snake_case, UUID v4) |
| Frontend JS variables / params | `publicId` (camelCase) |
| URLs / deep links | UUID v4 raw, sin prefijo |
| React keys | `obj.public_id` preferente; `obj.id` solo si el array no sale del componente |
| Body FK fields | PK entero (`PrimaryKeyRelatedField`) — no se cambia |

**Drift prevention:** anexo code quality §3 obliga sección "Convenciones de IDs" en CLAUDE.md al cerrar Día 6. Sin esto, en 6 meses devs nuevos reintroducen `pet.id` en URLs.

---

## 3. Ownership de IDs por capa

| Superficie | Modelo público (Pet, Owner, Appointment, MR, Invoice, Prescription, Product, Presentation, Service, **VaccineRecord**, **User**, **Organization**) | Modelo interno (InvoiceItem, MRP, MRS, StockMovement, VitalSigns) | Organization (FK base tenant) |
|---|---|---|---|
| URL path | `<str:pk>` (UUID) | `<str:parent_pk>/items/<int:pk>/` | NUNCA en URL — `/api/organizations/me/` |
| FK body field | PK entero | PK entero | NO writable (derivado de JWT) |
| Display visual | etiqueta humana (folio, name); UUID solo debug | hidden o "ítem 1" | nombre, nunca id |
| Filtro query param | `?pet=<public_id>` → resuelve via `resolve_public_id` | no aplica | derivado de JWT |
| Nav frontend | `/pets/:publicId` | nunca standalone | implícito |
| Deep link externo | `public_id` siempre | nunca | nunca |
| React key | `public_id` preferente | `id` OK | n/a |

**Regla maestra:** identificador que cruza el límite HTTP en `path` o `query` referenciando un modelo público es `public_id`. FK body siguen PK porque DRF los resuelve internamente sin enumerar (tenant ya validado vía ADR-13).

---

## 4. Boundaries por modelo (clasificación final)

**Modelos PÚBLICOS (exponen `public_id`):**
- Existentes con `public_id`: Pet, Owner, Appointment, MedicalRecord, Invoice, Prescription, Product, Presentation, Service.
- Nuevos en Día 6 (migración Fase 4-5): **Organization** (#39), **User** (#38), **VaccineRecord** (hallazgo seguridad).

**Modelos INTERNOS (NO `public_id`, child siempre nested):**
- `InvoiceItem`, `MedicalRecordProduct`, `MedicalRecordService`, `StockMovement`, `InvoiceAuditLog`, `AppointmentStatusChange`.
- `VitalSigns` — append-only, siempre listado bajo `medical-records/<uuid>/vitals/`. Promoción se difiere a futuro caso de uso standalone documentado.
- `Permission`, `Role`, `UserRole` — catálogo RBAC, jamás expuesto.

**Trigger explícito para promoción futura:** un modelo interno se promueve a `public_id` cuando hay caso de uso navegable / compartible standalone documentado. NUNCA por estética.

---

## 5. Estrategia de lookup por capa

### Backend URLs

- Modelos públicos: `path('<str:pk>/', ...)` siempre.
- Sub-recursos: `path('<str:parent_pk>/children/<int:pk>/', ...)` cuando child es interno.
- **Prohibido `<int:pk>` para los 12 modelos públicos** (incluyendo los 3 nuevos).

### ViewSets

Heredar `PublicIdLookupMixin` + `lookup_field='public_id'`. Sub-resources usan `lookup_url_kwarg` cuando el kwarg difiere.

### FBVs

```python
obj = resolve_public_id(Model.objects.for_organization(org), lookup)
```

### Sub-recursos parent-child (invariante de seguridad)

Sub-recurso detail DEBE filtrar `pk + parent=parent_obj` en la misma query:

```python
parent = resolve_public_id(Invoice.objects.for_organization(org), invoice_pk)
item = get_object_or_404(InvoiceItem, pk=pk, invoice=parent)
```

Sub-recurso que referencia FK a tercer modelo (service, presentation, product) revalida `obj.organization == request.user.organization` después del lookup (defense-in-depth, patrón canónico de `MedicalRecordServiceListCreateView.perform_create`).

### Query params (anexo seg §3 — obligación)

Todo `?<modelo_publico>=<value>` resuelve vía:

```python
pet = resolve_public_id(Pet.objects.for_organization(org), value)
qs = qs.filter(pet=pet)
```

**Prohibido** `qs.filter(pet_id=raw_value)`. Cross-tenant retorna 404, no `[]`.

### Invariante 404-as-403 (anexo seg)

Queryset de detail SIEMPRE empieza por `for_organization()` (ADR-10). Tenant mismatch siempre 404, nunca 403. Esto colapsa cross-tenant antes que `check_object_permissions` vea el objeto.

### List views anidadas — `required_permission` explícito (ADR-09) — **BLOCKER del cutover**

List view bajo URL con `<str:pk>` (parent UUID) DEBE declarar `required_permission` por método HTTP en `initial()`. El mapping automático de `_method_to_action` infiere `retrieve` por presencia de `pk` y rompe RBAC list/create silenciosamente.

**Grep gate obligatorio Fase 1 (CI bloqueante):**

```bash
# Toda nested list/create view bajo <str:pk> debe declarar required_permission
grep -rnE "path\(['\"][^'\"]*<str:[a-z_]+>/[^'\"]*['\"]" backend/apps/*/urls.py
```

Cada match cuyo view sea `*ListCreateView` o `*ListView` debe:
1. Declarar `required_permission` por método HTTP en `initial()`.
2. Tener test que verifique permisos `list`/`create` separados de `retrieve`.

**Vistas conocidas afectadas (anidadas bajo `<str:pk>` UUID parent):**

- `VitalSignsListCreateView` (bajo `medical-records/<str:pk>/vitals/`)
- `MedicalRecordSummaryView` (bajo `medical-records/<str:pk>/summary/`)
- `MedicalRecordServiceListCreateView` (bajo `medical-records/<str:medical_record_pk>/services/`)
- `MedicalRecordProductListCreateView` (bajo `medical-records/<str:medical_record_pk>/products/`)
- `InvoiceItemCreateView` (bajo `billing/invoices/<str:invoice_pk>/items/`)
- `PresentationCreateView` (bajo `inventory/products/<str:product_pk>/presentations/`)
- Cualquier nueva creada en Fase 1 al cambiar `<int:>` → `<str:>`.

**Verificación manual obligatoria Fase 1 (checklist):**

Cada vista listada arriba debe contener algo equivalente a:

```python
def initial(self, request, *args, **kwargs):
    if request.method == 'GET':
        self.required_permission = 'medicalrecord.vitals.list'
    elif request.method == 'POST':
        self.required_permission = 'medicalrecord.vitals.create'
    super().initial(request, *args, **kwargs)
```

Sin esta declaración, `HybridPermission` infiere `retrieve` (por `pk` en kwargs) y aplica el permiso equivocado. Resultado: VET con `list` permission pero sin `retrieve` recibe 403 incorrecto; o peor — ASSISTANT con `retrieve` accidental pasa donde debería 403.

**Test obligatorio:** `apps/core/tests/test_hybrid_permission_nested.py::test_list_view_under_uuid_parent_requires_list_permission` — POST/GET sobre `/medical-records/<uuid>/vitals/` con role que tiene `list` pero NO `retrieve` debe pasar GET; role con `retrieve` pero NO `list` debe recibir 403.

### Extracción interna anti-divergencia (anexo code quality)

`PublicIdLookupMixin.get_object` y `resolve_public_id` (`apps/core/views.py`) comparten lógica duplicada. Día 6 extrae a `_resolve_or_404(queryset, lookup)` privado en el mismo archivo. Sin API nueva. Sin ADR. Elimina posibilidad de divergencia futura.

### Deprecation marker del flag (anexo code quality)

Agregar `# DEPRECATED: remove after 2026-06-19 — see Issue #18` encima del branch `if str(lookup).isdigit() and ALLOW_LEGACY_ID_LOOKUP` en `PublicIdLookupMixin.get_object` y `resolve_public_id`. Crear ticket de backlog con fecha dura.

---

## 6. Estrategia frontend

### `api/*.js` — capa de transporte

**Obligatorio (no opcional):** renombrar parámetros a `<resource>PublicId`. JSDoc:

```javascript
/**
 * @param {string} petPublicId UUID v4 — never accept integer PK
 */
export const getPet = (petPublicId) => api.get(`pets/${petPublicId}/`)...
```

### Pages afectadas (lista exhaustiva)

| Archivo | Cambio |
|---|---|
| `pages/appointments.jsx` | Todos los handlers de status/assign/history → `appt.public_id` (líneas 199, 214, 366, 368, 374, 379, 389, 394, 399, 415, 420, 435, 452) |
| `pages/prescriptions.jsx` | edit/view/delete (líneas 212, 303, 315, 328) → `rx.public_id` |
| `pages/petDetail.jsx` | `getMedicalRecord(token, record.id)` → `record.public_id` (línea 62); nav a `/pets/${pet.public_id}` (117, 123, 191, 313, 320) |
| `pages/inventory.jsx` | Eliminar `editing.public_id \|\| editing.id` (líneas 263, 298, 600). Causa raíz: objeto en estado debe traer `public_id` desde serializer — arreglar allá, no con dual-lookup |
| `pages/pets.jsx` | Nav `/pets/${pet.public_id}`, query `?pet=${pet.public_id}` (líneas 318, 482, 580, 708, 709, 1016, 1043, 1078) |
| `pages/medical-records/*.jsx` | Completar parcial (ya usa `record.public_id` en algunos; revisar `index.jsx:179`, `:383`) |
| `pages/billing.jsx` | `inv.id` solo en `<tr key>` y display "#123" — OK, no cambia |
| `components/dashboard/OperationalFeed.jsx` | Eliminar fallback `.public_id \|\| .id` (líneas 49, 51) |

### Anti-pattern enforcement (BLOCKER del cutover)

Frontend silent regressions son el mayor riesgo real del Día 6. Backend rompe ruidosamente (404 visible); frontend rompe en silencio (botón no funciona, redirect a URL mala, modal con id undefined, optimistic update con id viejo). Los grep gates son **bloqueantes**, no aspiracionales.

**Gate 1 — Fallback dual-lookup (zero matches):**

```bash
! grep -rnE "\.public_id\s*\|\|\s*\w+\.id\b" frontend/src/
```

**Gate 2 — URL templates con `.id` en API layer (zero matches):**

```bash
# Detecta URL constructions con .id en lugar de .public_id en api/*.js
! grep -rnE "['\"][^'\"]*/\$\{[a-zA-Z_]+\.id\}" frontend/src/api/
! grep -rnE "['\"][^'\"]*['\"]\s*\+\s*\w+\.id\b" frontend/src/api/
```

**Gate 3 — Navegación con `.id` (audit manual + grep):**

```bash
# navigate("/pets/<id>"), navigate(`/medical-records/${x.id}`), Link to=, history.push
grep -rnE "navigate\(['\"`][^'\"`]*/\$\{[a-zA-Z_]+\.id\}" frontend/src/
grep -rnE "(navigate|push|replace)\(['\"`]/(pets|appointments|medical-records|invoices|prescriptions|inventory|staff)/" frontend/src/
```

Cada match: verificar manualmente que el ID embebido es `public_id`, no `id`. Documentar en PR description.

**Gate 4 — Deep links / URL params (querystring):**

```bash
# ?pet=${x.id}, ?appointment=${x.id}, etc.
grep -rnE "\?(pet|owner|appointment|medical_record|invoice|prescription)=\$\{[a-zA-Z_]+\.id\}" frontend/src/
grep -rnE "searchParams\.(get|set)\(['\"](pet|owner|appointment|medical_record|invoice|prescription)['\"]" frontend/src/
```

Cada match: verificar valor que se setea es `public_id`. `searchParams.get('pet')` está OK (lectura); peligro es `set('pet', x.id)`.

**Gate 5 — Modals + optimistic updates (audit manual):**

Modals reciben prop `editing` o `selected` que llega de listas paginadas. Optimistic updates re-renderizan con el objeto local antes del refetch. Si el listado se carga con `id` y el modal pasa `editing.id` al endpoint, queda silently broken hasta que alguien intenta editar y nada pasa (la request va a `/pets/42/` mientras el real es `/pets/<uuid>/`).

Patrón a buscar manualmente en cada modal/edit handler:

- `onClick={() => setEditing(item)}` → ¿`item` viene con `public_id` desde el listado?
- `await updateX(editing.id, ...)` → debe ser `editing.public_id`.
- Optimistic: `setItems(prev => prev.map(x => x.id === updated.id ? updated : x))` → OK para keys de matching local, NO para enviar al backend.

**Páginas con alto riesgo (auditar exhaustivamente Fase 2):**

| Página | Vector específico |
|---|---|
| `pages/appointments.jsx` | 12+ handlers de status/assign/history con `appt.id` (líneas 199, 214, 366, 368, 374, 379, 389, 394, 399, 415, 420, 435, 452) |
| `pages/prescriptions.jsx` | Edit/view/delete (212, 303, 315, 328) |
| `pages/petDetail.jsx` | `getMedicalRecord(token, record.id)` (62) + nav `/pets/${pet.id}` (117, 123, 191, 313, 320) |
| `pages/inventory.jsx` | Fallback `editing.public_id \|\| editing.id` (263, 298, 600) |
| `pages/pets.jsx` | Nav + query (318, 482, 580, 708, 709, 1016, 1043, 1078) |
| `pages/medical-records/index.jsx` | `setActiveRecordId` (383) + filtros |
| `pages/medical-records/ConsultationStepperV2.jsx` | `pet.id` en body OK; `record.public_id` en URL — verificar mezcla |
| `components/dashboard/OperationalFeed.jsx` | Fallback `.public_id \|\| .id` (49, 51) |
| Cualquier `<Link to=>` o `navigate()` apuntando a recursos | Manual audit |

**CI configuration:**

Los 5 gates corren en `frontend/__smoke__/url_construction.test.js` y en GH Actions pre-merge. Cualquier exit-code != 0 bloquea el merge. Lint manual queda como complemento, no reemplazo.

**Smoke staging post-Fase-2 (operador humano, no automatizable):**

Recorrer las 10 páginas principales con DevTools Network abierto. Cada request a `/api/*` que contenga un ID en path debe usar UUID (formato `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`). Cualquier `/api/pets/42/` o similar = bug pendiente. Documentar hallazgos en checklist PR.

### Manejo de UUID inválido / 404 / pantalla blanca

Backend ya responde 404 vía `PublicIdLookupMixin`. Frontend debe:

1. Catch 404 en `api/client.js` o caller.
2. Toast: "Recurso no encontrado".
3. Redirect a listado padre (no pantalla blanca).
4. ErrorBoundary opcional para `public_id: undefined` en props.

---

## 7. Query params y deep links

**Decisión:** migrar query params de modelos públicos a `public_id` con resolución vía `resolve_public_id`.

**Patrón canónico:**

```python
pet_lookup = request.query_params.get('pet')
if pet_lookup:
    pet = resolve_public_id(Pet.objects.for_organization(org), pet_lookup)
    qs = qs.filter(pet=pet)
```

**NO aceptar ambos identificadores en el mismo endpoint.** Cortar limpio con flag flip.

**Excepción tolerada:** filtros internos de frontend sobre arrays ya cargados (ej. `medical-records/index.jsx:81,161,197`) usan `.id` para comparar elementos del mismo array — no cruza HTTP, OK.

---

## 8. Plan por fases

### Fase 0 — Auditoría y baseline (0.5 día)

- Grep `<int:pk>` en `apps/*/urls.py` + grep `\.id` en `frontend/src/{api,pages}/`.
- Documentar lista exhaustiva en PR description.
- Test introspectivo: `apps/core/tests/test_url_audit.py::test_no_int_pk_in_public_urls`.
- Riesgo: nulo.

### Fase 1 — Backend URLs públicos (1 día)

**Cambios:**

- `medical_records/urls.py`:
  - `medical-records/pet/<int:pet_id>/` → `medical-records/pet/<str:pet_public_id>/` + `resolve_public_id(Pet.objects.for_organization(...))` ANTES del filtro de MRs.
  - `vaccines/<int:pk>/` → `vaccines/<str:pk>/` (requiere `VaccineRecord.public_id` — ver Fase 5).
  - `medical-records/<str:medical_record_pk>/services/<int:pk>/` → mantener (sub-recurso interno).
- `prescriptions/urls.py`:
  - `prescriptions/<int:prescription_pk>/items/<int:pk>/` → `prescriptions/<str:prescription_pk>/items/<int:pk>/` (child interno sigue PK).
  - `prescriptions/pet/<int:pet_id>/` → `prescriptions/pet/<str:pet_public_id>/`.
- `inventory/urls.py`: revisar consistencia (ya en `<str:>` mayoritariamente).
- `billing/urls.py`: ya OK.
- `appointments/urls.py`: ya OK.

**Verificar:** que `PublicIdLookupMixin` o `resolve_public_id` esté en cada view tocada. Que `for_organization()` venga PRIMERO en cada queryset (ADR-10). Que list views anidadas declaren `required_permission` por método HTTP (ADR-09).

**Tests:** `test_public_id_lookup.py`, `test_vaccines_lookup.py`, `test_pet_endpoints.py`.

**Riesgo:** ALTO si se omite vista. Smoke E2E crítico.

### Fase 2 — Frontend API layer (1 día)

- Renombrar params en `api/*.js` a `<resource>PublicId`. JSDoc `@param {string}`.
- Actualizar callers en `src/pages/{appointments,prescriptions,petDetail,inventory,pets,medical-records}.jsx` + `components/dashboard/OperationalFeed.jsx`.
- Eliminar `editing.public_id || editing.id` (3 sitios `inventory.jsx`, 2 sitios `OperationalFeed.jsx`).
- Agregar grep gate en CI.
- ErrorBoundary smoke verification.

**Tests:** smoke staging checklist + `frontend/__smoke__/url_construction.test.js`.

**Riesgo:** MEDIO. UI breakage si se omite caller.

### Fase 3 — Query params (0.5 día) — **BLOCKER ABSOLUTO DEL CUTOVER**

> **Nota crítica:** los query params son el vector más fácil de olvidar. Arreglar URLs es visible
> (las páginas rompen); arreglar filtros es invisible (devuelven `[]` silenciosamente o leakean
> data). Esta fase es BLOCKER duro: si UNA sola vista de las listadas no migra, el cutover NO
> procede. No hay degradación parcial aceptable aquí.

Migrar `?pet=`, `?owner=`, `?appointment=` (y cualquier otro filtro por modelo público) a `public_id` vía `resolve_public_id`.

**Inventario obligatorio pre-fase (grep gate):**

```bash
grep -rnE "request\.query_params\.get\(['\"](pet|owner|appointment|medical_record|invoice|prescription|product|presentation|service)['\"]\)" backend/apps/
grep -rnE "filter\((pet|owner|appointment|medical_record|invoice|prescription|product|presentation|service)_id=" backend/apps/
```

Cada match debe aparecer en el checklist Fase 3 con su archivo + línea + estado (migrado/pendiente). Sin checklist completo y verde, **no se mergea Fase 3**.

**Vistas tocadas (lista no exhaustiva, completar con grep):**

- `MedicalRecordListCreateView` (`?pet=`, `?owner=`, `?appointment=`)
- `InvoiceListCreateView` (`?pet=`, `?owner=`, `?medical_record=`, `?appointment=`)
- `AppointmentListCreateView` (`?pet=`)
- `PrescriptionListCreateView` (`?pet=`, `?medical_record=`)
- `VaccineRecordListCreateView` (`?pet=`)
- `PetViewSet` (`?owner=`)
- `MedicalRecordByPetView` (`pet_id` URL kwarg — ya cubierto en Fase 1)
- `PrescriptionByPetView` (`pet_id` URL kwarg — ya cubierto en Fase 1)

**Patrón obligatorio (sin excepción):**

```python
pet_lookup = request.query_params.get('pet')
if pet_lookup:
    pet = resolve_public_id(Pet.objects.for_organization(org), pet_lookup)
    qs = qs.filter(pet=pet)
```

Prohibido absolutamente:
- `qs.filter(pet_id=pet_lookup)` — bypasea tenant scope.
- `qs.filter(pet__public_id=pet_lookup)` — funciona pero no valida tenant antes; opaca el invariante.
- Aceptar PK Y UUID simultáneamente — corta limpio con flag.

**Tests obligatorios (todos verdes para mergear Fase 3):**

- `test_query_param_pet.py::test_pet_query_param_resolves_uuid` — UUID válido propio → 200 con resultados.
- `test_query_param_pet.py::test_pet_query_param_cross_tenant` — UUID otra org → 404 (no `[]`).
- `test_query_param_pet.py::test_pet_query_param_pk_rejected_flag_off` — PK entero + flag OFF → 404.
- `test_query_param_pet.py::test_pet_query_param_invalid_uuid` — `"not-a-uuid"` → 404.
- `test_query_param_pet.py::test_pet_query_param_url_encoded` — UUID url-encoded → 200.
- Equivalentes para `?owner=`, `?appointment=`, `?medical_record=`, `?invoice=`, `?prescription=`.

**Riesgo:** BLOCKER. Un filtro olvidado = leak silencioso post-cutover.

### Fase 4 — Issues #39 + #40 (0.5 día)

**Pre-fase obligatoria:** grep exhaustivo `grep -rn "organization\.id\|organization_id" backend/apps/*/serializers.py` y enumerar en PR description.

- Migración single-shot `Organization.public_id` (`default=uuid4`, `unique=True`, `db_index=True`).
- `OrganizationSerializer` expone `public_id`. Mantiene `id` pre-beta (no romper contrato).
- `MeView` response incluye `organization.public_id` junto a `organization.id`.
- `CreateEmployeeSerializer.organization_id` → `read_only=True` o eliminar campo; derivar siempre de `request.user.organization`.
- `OrganizationLegacyView` PATCH: confirmar que `id` no es writable (DRF lo bloquea por ser PK, pero documentar).
- Audit de serializers con FK `organization` writable — bloquear cualquier futuro.

**Tests:** `test_me_public_id.py`, `test_create_staff_org_immutable.py`, `test_legacy_view_org_id_writable.py`, `test_seed_with_public_id.py`.

**Riesgo:** BAJO — endpoint singleton.

### Fase 5 — Issue #38 + VaccineRecord (0.5 día)

- Migración single-shot `User.public_id` (`default=uuid4`, `unique=True`, `db_index=True`).
- Migración single-shot `VaccineRecord.public_id`.
- `StaffDeactivateView` URL `<int:pk>` → `<str:pk>` + `resolve_public_id`. Throttle scope dedicado.
- `StaffListView` response incluye `public_id`.
- `VaccineRecordListCreateView`, `VaccineRecordDetailView` adoptan `PublicIdLookupMixin`.

**Tests:** `test_staff_deactivate_uuid.py`, `test_vaccines_lookup.py`, `test_migrations.py::test_phase4_5_migrations_reversible`, `test_migrations.py::test_phase4_5_migration_timing`.

**Riesgo:** MEDIO. Afecta admin + módulo clínico.

### Fase 6 — Flag flip cutover (0.5 día)

**Pre-cutover gates (los 3 deben pasar; si falla 1, NO se procede al flip):**

1. **Query params** — Fase 3 cerrada con checklist verde. Grep `request.query_params.get` y `filter(<modelo>_id=` muestra 0 sitios sin migrar. Test suite `test_query_param_*` 100% verde.
2. **`required_permission` en nested list views** — grep `<str:` en `apps/*/urls.py` + verificación manual que cada `*ListCreateView` / `*ListView` bajo URL con parent UUID declara `required_permission` por método HTTP en `initial()`. Test `test_hybrid_permission_nested` verde.
3. **Frontend silent regressions** — los 5 grep gates de §6 retornan 0 matches. Smoke staging con DevTools Network: cero requests a `/api/*` con PK entero en path.

Si los 3 gates verdes:

1. CI con `ALLOW_LEGACY_ID_LOOKUP=True` y `False` ambos verdes.
2. Deploy staging con `ALLOW_LEGACY_ID_LOOKUP=True`. Smoke 24h.
3. Flip a `False` en staging. Smoke 48h sobre 10 flujos críticos del checklist QA §6.
4. EXPLAIN ANALYZE post-cutover (anexo DB §6) — 0 regresiones de `Index Scan`.
5. Merge a `main` + deploy Railway con `ALLOW_LEGACY_ID_LOOKUP=False`.
6. Mantener flag en código 30 días post-cutover (vencimiento `2026-06-19`). Cleanup ticket con fecha dura.

**Riesgo:** BLOCKER si gates pre-cutover fallan. MEDIO si todo verde.

---

## 9. Riesgos clasificados

| ID | Descripción | Sev | Capa | Mitigación |
|---|---|---|---|---|
| R1 | Vista pública aún con `<int:pk>` al apagar flag → 404 generalizado | BLOCKER | backend URLs | `test_url_audit` + checklist Fase 0 + smoke E2E |
| R2 | Frontend silent regression: caller con `.id` no migrado en nav/redirect/modal/optimistic update → botón no responde, URL malformada, edit a registro equivocado | **BLOCKER (silent)** | frontend pages | 5 grep gates CI (§6) + smoke staging con DevTools Network + audit modals/nav |
| R3 | `?pet=<pk>` u otro filtro de modelo público ignora tenant antes del filtro → leak silencioso o lista vacía sin error | **BLOCKER ABSOLUTO** | query params | Patrón obligatorio `resolve_public_id` antes de filter (Fase 3 BLOCKER §8). Una vista olvidada = leak silencioso post-cutover. Grep gate `request.query_params.get` cubre inventario completo |
| R4 | `VaccineRecord` con `<int:pk>` enumera cross-org | HIGH | backend URLs | Promoción a `public_id` en Fase 5 |
| R5 | `prescriptions/<int:prescription_pk>/items/` enumera | HIGH | backend URLs | Cambio a `<str:prescription_pk>` en Fase 1 |
| R6 | Sub-recurso child PK enumerable bajo parent ajeno | HIGH | seguridad | Patrón obligatorio `pk + parent=parent_obj` |
| R7 | `CreateEmployeeSerializer.organization_id` writable → escalation | HIGH | privilege | Eliminar campo writable Fase 4 |
| R8 | Serializer expone `organization.id` cruda en respuestas embed | HIGH | response | `public_id` en serializers + grep exhaustivo Fase 4 |
| R9 | `_method_to_action` regression en list views anidadas — RBAC roto silenciosamente: list/create deniega o sobreautoriza por mapping a `retrieve` | **BLOCKER** | RBAC | Grep obligatorio `required_permission` en TODAS las nested list views tocadas (§5 nuevo). Sin declaración explícita por método HTTP en `initial()`, el cutover NO procede. Test `test_hybrid_permission_nested` obligatorio |
| R10 | UUID inválido provoca 500 en lugar de 404 | MEDIUM | UX | `PublicIdLookupMixin` ya maneja; test edge cases |
| R11 | `MedicalRecordServiceDeleteView` no revalida `service.organization` | MEDIUM | tenant leak latente | Test explícito + patrón defense-in-depth |
| R12 | Deep link viejo con PK queda muerto post-cutover | LOW | UX | Pre-beta, sin usuarios. Post-beta: blast email |
| R13 | React key duplicada por mezclar `id` y `public_id` | LOW | frontend | Convención: usar `public_id` preferente |
| R14 | UUID payload de 10MB en path | LOW | DoS | nginx/Django cap ~8KB — cubierto por infra |
| R15 | Branch del flag legacy queda en código indefinido | LOW | maintainability | Deprecation marker + fecha dura `2026-06-19` |

---

## 10. Anti-patterns explícitos (consolidados)

1. **Dual-lookup spaghetti:** `editing.public_id || editing.id` (frontend) o `try uuid except pk` (backend). Prohibido. Un identificador por superficie.
2. **Helper creep en `apps/core/`:** crear `resolve_anything()`, `SmartIdField`, `MagicLookup`, `IdentityResolverFactory`. Solo `resolve_public_id` y `PublicIdLookupMixin` permitidos.
3. **Repetición permitida hasta 6 ocurrencias por app:** `resolve_public_id(Model.objects.for_organization(org), value)` inline es OK hasta 6 sitios. Promoción a helper > 6 requiere ADR.
4. **Query param dual-aceptación:** aceptar PK y UUID en el mismo endpoint. Cortar limpio con flag.
5. **Backfill UUID en modelos internos sin uso:** agregar `public_id` a InvoiceItem "por estética". Migración paga costo, beneficio cero.
6. **Renombrar `id` a `public_id` en response (eliminar `id`):** rompe contrato. Se agrega `public_id` además, NO se quita `id` pre-beta.
7. **Middleware genérico de IDs:** atar lookup a la URL declarada con `<str:>` + mixin de view explícito. Middleware = magia invisible.
8. **`PrimaryKeyRelatedField` con UUID en body:** rompe contrato DRF. FK body sigue PK.
9. **Naming drift:** mezclar `publicId` / `public_id` / `uuid` sin convención. Documentar en CLAUDE.md (§2 de este plan).
10. **`IntelligentResolver` / `IdentityService` / `BasePublicResourceViewSet`:** abstracciones prematuras YAGNI. No introducir.

---

## 11. Lo que NO se toca pre-beta

- **Columna `id` interna en todos los modelos.** PK entero, base de joins, FKs internas, índices, ordering.
- **`InvoiceItem.id`, `MRP.id`, `MRS.id`, `StockMovement.id`, `VitalSigns.id`.** Sub-recursos siempre anidados, no enumerables sin parent.
- **FK body fields (`pet`, `owner`, `appointment`, `medical_record`, `product`).** Mantienen PK por DRF. Tenant validado vía ADR-13.
- **Joins ORM.** `Invoice.objects.filter(pet_id=...)` sigue PK.
- **Analytics anchors / provenance (ADR-11).** Sin relación con identidad pública.
- **`InvoiceAuditLog`, `AppointmentStatusChange`.** Append-only internos.
- **Display de `id` en UI (#123).** Folio formal es discusión de producto, no de IDs.
- **Migración UUID v4 → v7** retroactiva en modelos existentes.
- **Índices compuestos `(organization, public_id)`** — sólo si EXPLAIN muestra ganancia >20% (anexo DB §3).
- **`username` UNIQUE global** (P2 #46). Deuda conocida, ticket aparte.
- **`Service.unique_together` sin org** (P2 #43). Deuda conocida, ticket aparte.

---

## 12. Rollout strategy

1. Fases 1-5 en `develop` con suite verde (294 tests + 21 nuevos) + EXPLAIN ANALYZE limpio.
2. Deploy staging con `ALLOW_LEGACY_ID_LOOKUP=True` — comportamiento dual. Smoke 24h.
3. Flip `ALLOW_LEGACY_ID_LOOKUP=False` staging. Smoke 48h sobre 10 flujos críticos:
   - Login → /pets → /pets/:uuid
   - Cita → start → done → invoice → pay
   - Pet → MR → close → prescription PDF
   - Walk-in appointment → factura draft
   - Staff create → list → deactivate
   - Bookmark legacy `/pets/42` con flag OFF → toast + redirect, sin pantalla blanca
4. Métricas limpias (cero 404 atribuible a IDs, p95 detail endpoint ±10%) → merge a `main` + deploy Railway con `ALLOW_LEGACY_ID_LOOKUP=False`.
5. Flag permanece en código 30 días post-cutover (rollback insurance). Eliminar en cleanup ticket `2026-06-19`.

**Monitoreo:**
- Dashboard Railway: rate 404 por endpoint, p95 latency detail endpoints.
- Sentry: alerta `IntegrityError`/`DoesNotExist`/`AttributeError` en `resolve_public_id`. Threshold p95 +50% vs baseline → page on-call.

---

## 13. Rollback strategy

- **Fase 1-2 rompe staging:** revert PRs atómicos por app. URLs son cambios localizados, revert no afecta DB.
- **Fase 4-5 migraciones:** single-shot reversibles. `python manage.py migrate <app> <N-1>` debe correr sin `IrreversibleMigration`. Test: `test_phase4_5_migrations_reversible`.
- **Flag flip rompe prod:** `ALLOW_LEGACY_ID_LOOKUP=True` como env var hot-toggle. Recovery <60s sin restart del proceso (flag leído por request).
- **Cambio en serializer rompe frontend:** mantener `id` en respuesta junto a `public_id` durante Día 6. Quitar `id` es tarea separada post-beta.
- **Test gate de rollback:** `test_flag_cutover.py::test_flag_flip_roundtrip` valida que flip OFF→ON restaura comportamiento.

---

## 14. Deuda técnica permitida temporalmente (con fechas)

| Item | Vencimiento | Justificación |
|---|---|---|
| `id` y `public_id` ambos en response JSON | post-beta cleanup ticket | Reducir blast radius. No romper contrato pre-beta |
| Display "#123" usando PK en billing | indefinido | Folio formal es discusión de producto |
| Keys React con `.id` en listas internas | indefinido | No cruza HTTP boundary |
| Flag `ALLOW_LEGACY_ID_LOOKUP` en código | **2026-06-19** | Rollback insurance 30 días. Cleanup ticket con fecha dura |
| Sub-recursos child con PK entero | indefinido — NO es deuda, es decisión | Trigger de promoción: caso de uso standalone documentado |
| Query params frontend `.id` para state interno | indefinido | No cruza boundary |
| UUID v4 (no v7) en modelos existentes | indefinido | Reevaluar a 10x growth con métricas `pg_stat_user_indexes` |
| Branch `if str(lookup).isdigit() and ALLOW_LEGACY_ID_LOOKUP` | **2026-06-19** | Junto con flag, deprecation marker en código |

---

## 15. Tests obligatorios (resumen — detalle en anexo QA §9)

**21 archivos nuevos. Sin frameworks nuevos. Pytest + DRF APITestCase + grep gates.**

| Área | Archivos clave |
|---|---|
| Core | `test_public_id_lookup.py`, `test_url_audit.py`, `test_flag_cutover.py`, `test_tenant_404_invariant.py`, `test_query_plan.py`, `test_performance_regression.py`, `test_migrations.py`, `test_hybrid_permission_nested.py` |
| Billing | `test_invoice_id_cutover.py`, `test_subresource_parent_child.py` |
| Medical Records | `test_vaccines_lookup.py`, `test_pet_endpoints.py`, `test_query_param_pet.py`, `test_service_delete_tenant.py` |
| Appointments | `test_done_without_mr.py` |
| Organizations | `test_me_public_id.py`, `test_legacy_view_org_id_writable.py`, `test_seed_with_public_id.py` |
| Users | `test_create_staff_org_immutable.py`, `test_staff_deactivate_uuid.py` |
| Frontend | `frontend/__smoke__/error_boundary.test.jsx`, `frontend/__smoke__/url_construction.test.js` (grep gate) |

**Performance gates (Fase 6 obligatorio):**
- EXPLAIN ANALYZE de 9 queries canónicas → `Index Scan`, `buffers shared hit < 10`.
- Suite tiempo ±10% vs baseline pre-Día-6 (fail si >30%).
- Migración Fase 4-5 <1s en staging.

**Smoke staging checklist:** 10 ítems en anexo QA §6 (operador humano, 15 min, pre-flag-flip).

---

## 16. Ownership por capa

| Capa | Responsable | Documentos guía |
|---|---|---|
| Arquitectura general | Backend-architect (este plan) | §3-§4 |
| Seguridad endpoints / IDOR | Security review pre-merge por PR | Anexo `02-security-annex.md` |
| Migraciones DB / índices | DB review pre-merge Fase 4-5 | Anexo `03-db-annex.md` |
| Code quality / anti-debt | Code review en todos los PRs | Anexo `04-code-quality-annex.md` |
| QA / regression / cutover | QA gate en Fase 6 | Anexo `05-qa-annex.md` |
| Cutover decision | Operador humano post-smoke 48h | §12 + smoke checklist |

---

## 17. ADRs producidos por Día 6

**ADR obligatorio (al cerrar Día 6):**

**`2026-05-2X-p18-ids-en-superficies-externas.md`** — IDs en superficies externas: política `public_id` para modelos públicos, PK para internos y body fields, prohibición de dual-lookup. Promoción de `Organization`, `User`, `VaccineRecord` a `public_id`. Afecta contrato externo + invariante cross-team frontend/backend.

**Documentación adicional (no ADR, pero obligatoria al cerrar Día 6):**

- `CLAUDE.md` — agregar sección "Convenciones de IDs" (§2 de este plan).
- `docs/runbooks/exposing-new-model.md` — runbook nuevo (10 pasos, anexo code quality §6).

---

## 18. Out of scope explícito (no se hace en Día 6)

- Migración `username` a UNIQUE per-org (P2 #46) → ticket aparte post-beta.
- Migración `Service.unique_together` con org (P2 #43) → ticket aparte post-beta.
- UUID v7 para modelos existentes → ADR separado si fragmentation se materializa.
- Índice compuesto `(organization, public_id)` → sólo si EXPLAIN muestra ganancia >20%.
- E2E framework (Cypress/Playwright) → fuera de scope, mitigado con smoke manual.
- `VitalSigns.public_id` → diferido hasta caso de uso standalone.
- `InvoiceItem`/`MRP`/`MRS` `public_id` → diferido indefinidamente. Trigger: caso de uso standalone documentado.
- Eliminar `id` de response JSON → post-beta cleanup.
- Blast email a usuarios con bookmarks legacy → post-beta.

---

## 19. Time budget consolidado

| Fase | Duración | Bloqueante |
|---|---|---|
| Fase 0 — Auditoría baseline | 0.5 día | Fase 1 |
| Fase 1 — Backend URLs públicos | 1 día | Fase 2 + Fase 6 |
| Fase 2 — Frontend API + pages | 1 día | Fase 6 |
| Fase 3 — Query params | 0.5 día | Fase 6 |
| Fase 4 — Organization + CreateEmployee | 0.5 día | Fase 6 |
| Fase 5 — User + VaccineRecord | 0.5 día | Fase 6 |
| Fase 6 — Flag flip cutover | 0.5 día (+ smoke 48h staging) | — |
| **Total** | **4.5 días + 48h staging** | — |

Cabe holgadamente en 1 sprint de 7 días con buffer para tests y smoke.

---

## 20. Cierre — invariantes que deben quedar verdaderas post-Día-6

1. `ALLOW_LEGACY_ID_LOOKUP=False` en prod.
2. Cero `<int:pk>` en URLs de modelos públicos (test `test_url_audit` lo verifica).
3. Cero `editing.public_id || editing.id` en frontend (grep gate CI).
4. `for_organization()` antes de `select_related()` en todo queryset de detail (ADR-10 enforced).
5. Sub-recurso detail filtra `pk + parent=parent_obj` (test `test_subresource_parent_child`).
6. Cross-tenant retorna 404, nunca 403 (test `test_tenant_404_invariant`).
7. Query param de modelo público pasa por `resolve_public_id` antes de filter.
8. List views anidadas declaran `required_permission` por método HTTP en `initial()`.
9. Organization / User / VaccineRecord tienen `public_id` UUID.
10. CLAUDE.md tiene sección "Convenciones de IDs".
11. `docs/runbooks/exposing-new-model.md` existe.
12. ADR `2026-05-2X-p18` mergeado.

**Si alguna falla post-Día-6 → el cutover no está completo.**

---

## 21. Tres BLOCKERs absolutos del cutover (resumen ejecutivo)

Por encima de todas las demás reglas del plan, **estos 3 deben estar 100% cerrados** antes del flag flip:

1. **Query params migrados** (Fase 3) — TODO `?pet=`, `?owner=`, `?appointment=`, `?medical_record=`, `?invoice=`, `?prescription=` resuelto vía `resolve_public_id(Model.objects.for_organization(org), value)`. Cero `filter(<modelo>_id=raw)`. Grep gate verde. Tests `test_query_param_*` verdes. **Razón:** un filtro olvidado leakea sin error visible.

2. **`required_permission` declarado en TODAS las nested list views** (Fase 1) — `_method_to_action` infiere `retrieve` por presencia de `pk` y rompe permisos silenciosamente. Grep manual de `required_permission` en cada vista anidada bajo `<str:pk>` UUID. Test `test_hybrid_permission_nested` verde. **Razón:** RBAC roto sin error visible.

3. **Frontend grep gates verdes + smoke DevTools Network** (Fase 2) — los 5 grep gates de §6 (fallback dual, URL templates, navegación, deep links, modals/optimistic) retornan 0 matches. Smoke staging: cero requests `/api/*` con PK entero en path. **Razón:** caller perdido en nav/redirect/modal/optimistic update rompe en silencio.

Sin estos 3 verdes, **el flip NO procede**. No hay degradación parcial aceptable.
