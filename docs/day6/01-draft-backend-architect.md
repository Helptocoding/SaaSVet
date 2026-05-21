# Plan Día 6 — Endurecimiento de IDs (Draft v1)

## 1. Resumen ejecutivo

**Objetivo:** Eliminar la dependencia del frontend sobre PKs internos en URL paths de endpoints públicos para permitir apagar `ALLOW_LEGACY_ID_LOOKUP` en beta sin romper la app. Cerrar P0 #18 y P1 #38-40.

**Scope dentro:** URL paths de endpoints públicos, frontend `api/*.js` + pages que construyen URLs, `StaffDeactivateView` (#38), endpoint `/me/` (#39), `CreateEmployeeSerializer.organization_id` writable (#40). Apagado controlado del flag legacy.

**Scope fuera:** FK body fields (siguen siendo PK por `PrimaryKeyRelatedField`), joins internos, columnas `id` de modelos internos (InvoiceItem, MRP, MRS, StockMovement), migración UUID global, GraphQL, repositorios genéricos.

**Blast radius esperado:** medio. Cambios concentrados en URL params (`<int:>` → `<str:>`), constructores de URL en frontend y serializadores de respuesta (`organization.id` → `organization.public_id`). RBAC, multitenancy, contratos de body y analytics no se tocan.

**Resultado de éxito:** con `ALLOW_LEGACY_ID_LOOKUP=False` toda navegación, CRUD, deep link y flujo clínico/cobro funciona. Cero 404 atribuibles a IDs.

---

## 2. Ownership de IDs por capa

| Superficie | Modelo público (Pet, Owner, Appointment, MR, Invoice, Prescription, Product, Presentation, Service) | Modelo interno (InvoiceItem, MRP, MRS, StockMovement, VitalSigns, VaccineRecord) | Organization |
|---|---|---|---|
| URL path | `public_id` UUID — `<str:pk>` | parent es `public_id`, hijo es PK entero — `<str:parent_pk>/items/<int:pk>/` | NUNCA en URL. `/api/organizations/me/` |
| FK body field (POST/PATCH) | PK entero (`PrimaryKeyRelatedField`) | PK entero | NO writable (ver #40) |
| Display visual | etiqueta humana (folio, name); UUID solo en debug | hidden o secuencia local ("ítem 1") | nombre de org, nunca id |
| Filtro query param | `?pet=<public_id>` recomendado; ver §6 | no aplica | derivado de JWT |
| Nav frontend (router) | `/pets/:publicId` | no aplica (siempre anidado) | implícito |
| Deep link externo | `public_id` siempre | nunca expuesto | nunca |
| Key React (`<tr key=>`) | `public_id` preferente; `id` aceptable si no sale del componente | `id` interno OK | n/a |

**Regla:** todo identificador que cruza el límite HTTP en `path` o `query` referenciando un modelo público es `public_id`. Body fields siguen siendo PK porque DRF los resuelve internamente sin enumerar.

---

## 3. Boundaries críticos

**Exponen `public_id`:** Pet, Owner, Appointment, MedicalRecord, Invoice, Prescription, Product, Presentation, Service. Justificación: son entidades a las que el frontend navega, comparte por link o referencia en URL.

**NO exponen `public_id` (y no se les agrega en Día 6):**
- `InvoiceItem`, `MedicalRecordProduct`, `MedicalRecordService`: sub-recursos siempre anidados bajo un parent público (`/invoices/<str:pk>/items/<int:pk>/`). El parent UUID actúa de cápsula tenant; el child PK no es enumerable sin conocer el parent. Costo de agregar `public_id`: migración + índice + write path; beneficio: nulo (no se navega standalone, no se comparte). Decisión: NO.
- `StockMovement`, `InvoiceAuditLog`: append-only, jamás expuestos en URL.
- `VitalSigns`, `VaccineRecord`: append-only, anidados bajo `pet` o `medical_record`. Si en futuro requieren PATCH/DELETE standalone (`/vaccines/<id>/`) se promueven a `public_id`. Hoy no.
- `Permission`, `Role`, `UserRole`: catálogo RBAC interno, jamás vía API pública.
- `User`: candidato a `public_id` (P1 #38) — se agrega en Fase 5. Costo bajo (un campo + migración), beneficio alto (URLs `/staff/<uuid>/deactivate/`).
- `Organization`: candidato a `public_id` (P1 #39). Pero hoy el endpoint canónico es `/me/` (singleton). El legacy `/<int:pk>/` ya tiene Sunset 2026-08-17 (ADR-15). Decisión: agregar `public_id` para sustituir `id` en respuestas de `/me/` y otros embeds, pero NO restaurar lookup público por path.

---

## 4. Estrategia de lookup por capa

**URLs (config/urls.py y apps/*/urls.py):**
- Modelos públicos: `path('<str:pk>/', ...)` siempre.
- Sub-recursos: `path('<str:parent_pk>/children/<int:pk>/', ...)` cuando el child es interno. Ejemplo: `apps/billing/urls.py` ya correcto.
- Anidados con child público: ambos `<str:>`. Ejemplo hipotético: `appointments/<str:pk>/medical-record/`.
- Prohibido `<int:pk>` para Pet, Owner, Appointment, MR, Invoice, Prescription, Product, Presentation, Service.

**ViewSets:** heredar `PublicIdLookupMixin` + `lookup_field='public_id'`. Sub-resources usan `lookup_url_kwarg` cuando el kwarg difiere.

**FBVs:** `obj = resolve_public_id(Model.objects.for_organization(org), lookup)`. Patrón ejemplo: `assign_patient` en `apps/appointments/views.py`.

**Sub-recursos con parent público + child interno:**
```
parent = resolve_public_id(Invoice.objects.for_organization(org), invoice_pk)
item = get_object_or_404(InvoiceItem, pk=pk, invoice=parent)
```

**FK body fields:** intactos. `PrimaryKeyRelatedField(queryset=Pet.objects.for_organization(...))` ya valida tenant (ADR-13). No cambia en Día 6.

---

## 5. Estrategia frontend

**`api/*.js` (capa de transporte):** cada función que toma `id` se renombra semánticamente o se documenta para recibir UUID. Ejemplo:
- `getMedicalRecord(token, recordPublicId)` — el caller en `petDetail.jsx:62` cambia de `record.id` a `record.public_id`.
- `updateAppointmentStatus(token, apptPublicId, payload)` — caller en `appointments.jsx` pasa `appt.public_id`.

**Pages afectadas (agrupadas):**
- `pages/appointments.jsx`: todos los handlers de status/assign/history → `appt.public_id`.
- `pages/prescriptions.jsx`: edit/view/delete → `rx.public_id`.
- `pages/petDetail.jsx`: getMedicalRecord → `record.public_id`.
- `pages/inventory.jsx`: eliminar fallback `editing.public_id || editing.id`. Si el objeto en estado no trae `public_id`, es bug de origen (serializer), se arregla allá, no con dual-lookup.
- `pages/pets.jsx`: navegación `/pets/${pet.public_id}` + query `?pet=${pet.public_id}` (ver §6).
- `pages/medical-records/*.jsx`: ya parcialmente correcto, completar.
- `pages/billing.jsx`: `inv.id` solo en `<tr key>` y display "#123" — OK, no cambia.

**Manejo de UUID inválido:** el backend ya responde 404 si el formato no parsea UUID (vía `PublicIdLookupMixin`). Frontend muestra "Recurso no encontrado" — toast + redirect a listado padre. NO pantalla blanca.

**Eliminar `editing.public_id || editing.id`:** lint manual durante PR. Solo `editing.public_id` después de Día 6. Regla: si el grep en pages encuentra `\.id\b` en path template, es smell.

**Keys de React:** se permite `key={x.id}` porque es internal. No se rompe nada al cambiarlo a `public_id`; cambiar oportunisticamente.

---

## 6. Query params y deep links

**Estado actual:** `?pet=<pk>` en filtros (`getMedicalRecords({pet: petId})`). Backend resuelve por PK porque el queryset filter pasa por `PrimaryKeyRelatedField` o equivalente.

**Decisión:** migrar query params de modelos públicos a `public_id`. Razones:
- Consistencia semántica (un mismo modelo, un mismo identificador externo).
- Cierra enumeration: `?pet=1,2,3,4...` es triviable hoy; con UUID no.
- Deep links (`/medical-records?pet=<id>`) deben compartirse sin filtrar PK.

**Cómo:** view-level resuelve `public_id` → instancia → filtra. Patrón:
```
pet_lookup = request.query_params.get('pet')
if pet_lookup:
    pet = resolve_public_id(Pet.objects.for_organization(org), pet_lookup)
    qs = qs.filter(pet=pet)
```
NO aceptar ambos. Dual aceptación es la anti-pattern #4. Se hace en una sola pasada en Fase 3.

**Excepción tolerada Día 6:** filtros internos de frontend sobre arrays ya cargados (ej. `medical-records/index.jsx:81,161,197`) usan `.id` para comparar elementos del mismo array — no cruza HTTP, no cambia.

---

## 7. Plan por fases

**Fase 0 — Auditoría y baseline (0.5 día).** Grep `<int:pk>` en `apps/*/urls.py` + grep `\.id` en frontend rutas/api. Documentar lista exhaustiva. Riesgo: nulo.

**Fase 1 — Backend URLs públicos (1 día).** Cambiar `<int:>` → `<str:>` en `medical_records/urls.py` (vaccines, services items, pet/<id>), `prescriptions/urls.py` (items, pet/<id>), restantes. Verificar que `PublicIdLookupMixin` o `resolve_public_id` esté en cada view tocada. Archivos: `apps/medical_records/urls.py`, `apps/prescriptions/urls.py`, `apps/inventory/urls.py` (validar consistencia). Riesgo: alto si se omite vista — tests E2E críticos.

**Fase 2 — Frontend API layer (1 día).** Renombrar parámetros en `api/*.js` para semántica clara. Actualizar todas las llamadas en pages. Archivos: `src/api/*.js`, `src/pages/{appointments,prescriptions,petDetail,inventory,pets}.jsx`. Riesgo: medio — UI breakage si se omite un caller.

**Fase 3 — Query params (0.5 día).** Migrar `?pet=`, `?appointment=`, `?owner=` a `public_id`. Vistas: lista de MR, lista de invoices, lista de appointments. Riesgo: bajo — error 404 visible.

**Fase 4 — Issue #39 + #40 (0.5 día).** `Organization.public_id` (migración + serializer expone `public_id`, oculta `id`). `CreateEmployeeSerializer.organization_id` → `read_only` o derivado de `request.user.organization`. Riesgo: bajo — endpoint singleton.

**Fase 5 — Issue #38 (0.5 día).** `User.public_id` (migración). `StaffDeactivateView` URL `<int:pk>` → `<str:pk>` + `resolve_public_id`. Throttle scope dedicado. Riesgo: medio — afecta admin.

**Fase 6 — Apagar flag (0.5 día).** `ALLOW_LEGACY_ID_LOOKUP=False` en staging 48h con monitoreo. Si métricas OK → prod. Riesgo: BLOCKER si fases previas incompletas.

---

## 8. Riesgos clasificados

| ID | Descripción | Sev | Capa | Mitigación |
|---|---|---|---|---|
| R1 | Vista pública aún con `<int:pk>` al apagar flag → 404 generalizado | BLOCKER | backend URLs | Grep + checklist por app, smoke E2E pre-cutover |
| R2 | Frontend con `obj.id` no migrado → URL malformada | BLOCKER | frontend pages | Lint manual por PR; staging 48h |
| R3 | Query param `?pet=<pk>` legacy en bookmarks de usuarios | HIGH | query params | Aceptar PK en lectura solo si flag ON; cortar con flag |
| R4 | Serializer aún expone `organization.id` cruda | HIGH | response shape | Tests de contrato sobre `/me/` |
| R5 | `CreateEmployeeSerializer` permite escalar org cross-tenant | HIGH | seguridad | Derivar de JWT; rechazar campo writable |
| R6 | UUID inválido provoca crash en lugar de 404 | MEDIUM | UX | `PublicIdLookupMixin` ya maneja; verificar coverage |
| R7 | Sub-recurso con child PK enumerable bajo parent ajeno | MEDIUM | seguridad | Filtro `parent=parent_obj` siempre con tenant scope |
| R8 | Deep link viejo con PK queda muerto post-cutover | LOW | UX | Comunicado interno; pre-beta, sin usuarios externos |
| R9 | React key duplicada por mezclar `id` y `public_id` | LOW | frontend | Convención: usar `public_id` cuando disponible |

---

## 9. Anti-patterns explícitos

1. **Dual-lookup spaghetti:** `editing.public_id || editing.id` en frontend o backend resolviendo `try uuid except pk`. Prohibido. Un identificador por superficie.
2. **Helper creep en `apps/core/`:** crear `resolve_anything()`, `SmartIdField`, `MagicLookup`. `resolve_public_id` y `PublicIdLookupMixin` son suficientes.
3. **IntelligentResolver / IdentityService:** no se introduce capa de abstracción de identidad.
4. **Query param dual:** aceptar PK y UUID en el mismo endpoint. Cortar limpio con flag.
5. **Backfill UUID en modelos internos sin uso:** agregar `public_id` a InvoiceItem porque "queda lindo". Costo migración real, beneficio cero.
6. **Renombrar `id` a `public_id` en response:** romper contrato. Se agrega `public_id` además, NO se quita `id` para reducir blast radius (frontend usa `public_id` para URLs; backend sigue serializando ambos donde aplica).
7. **Resolver UUID en middleware genérico:** atar lookup a la URL declarada con `<str:>` + mixin de view explícito. Middleware genera magia invisible.
8. **`PrimaryKeyRelatedField` con UUID en body:** rompe contrato DRF, complica clientes. FK body sigue PK.
9. **Mezclar nomenclatura "publicId" vs "uuid" vs "id" en frontend:** convención única: `publicId` en JS, `public_id` en JSON.

---

## 10. Lo que NO se toca pre-beta

- **Columna `id` interna en todos los modelos.** Permanece PK entero, base de joins, FKs internas, índices, ordenamiento.
- **`InvoiceItem.id`, `MRP.id`, `MRS.id`, `StockMovement.id`, `VaccineRecord.id`, `VitalSigns.id`.** Justificación: anidados, no enumerables sin parent, sin caso de uso standalone.
- **FK body fields (`pet`, `owner`, `appointment`, `medical_record`, `product`).** Mantienen PK por DRF. Tenant ya validado vía ADR-13.
- **Joins ORM.** `Invoice.objects.filter(pet_id=...)` sigue funcionando con PK; nada cambia.
- **Analytics anchors / provenance (ADR-11).** Sin relación con identidad pública.
- **`InvoiceAuditLog`, `AppointmentStatusChange`.** Append-only, internos.
- **Display de `id` en UI.** "Factura #123" puede seguir siendo el PK; folio formal se evalúa post-beta.

---

## 11. Rollout strategy

1. Fases 1-5 en `develop` con tests verdes y E2E manual.
2. Deploy a staging con `ALLOW_LEGACY_ID_LOOKUP=True` — comportamiento dual (flag aún tolera PK). Smoke 24h.
3. Flip `ALLOW_LEGACY_ID_LOOKUP=False` en staging. Smoke 48h sobre flujos críticos: cita → MR → invoice → pay; pet → MR → prescription; staff create → deactivate. Monitorear logs por 404 atribuibles a IDs.
4. Si métricas limpias (cero 404 inesperado en endpoints de modelos públicos), merge a `main` + deploy Railway con `ALLOW_LEGACY_ID_LOOKUP=False`.
5. Mantener flag en código 30 días post-cutover como rollback rápido; luego eliminar (cleanup ticket).

**Monitoreo:** dashboard de Railway sobre rate de 404 por endpoint. Sentry para excepciones inesperadas en `resolve_public_id`.

---

## 12. Rollback strategy

- **Si Fase 1-2 rompe staging:** revert PRs por fase (atómicos por app). Backend URLs son cambios localizados; revert no afecta DB.
- **Si Fase 4-5 introducen migración (`Organization.public_id`, `User.public_id`):** migración debe ser aditiva (nuevo campo nullable inicialmente, backfill, NOT NULL en migración posterior). Rollback = no romper schema.
- **Si flag flip rompe prod:** `ALLOW_LEGACY_ID_LOOKUP=True` como env var hot-toggle. Recovery < 1 minuto.
- **Si cambio en serializer rompe frontend:** mantener `id` en respuesta junto a `public_id` durante Día 6. Quitar `id` es tarea separada post-beta.

---

## 13. Deuda técnica permitida temporalmente

- **`id` y `public_id` ambos en response JSON de modelos públicos.** OK pre-beta para reducir blast radius. Cleanup post-beta.
- **Display "#123" usando PK en billing.** OK; folio formal es discusión de producto, no de IDs.
- **Keys React con `.id` en listas internas.** OK; cambiarlas no aporta seguridad.
- **Flag `ALLOW_LEGACY_ID_LOOKUP` permanece en código 30 días post-cutover.** Recovery insurance. Tarea de cleanup explícita en backlog.
- **Sub-recursos child con PK entero (InvoiceItem, MRP, MRS).** OK definitivamente — no es deuda, es decisión.
- **Query params en frontend que aún usan `.id` para state interno no-HTTP.** OK; no cruza boundary.

---

## 14. Ítems candidatos a ADR

- **ADR Día 6 (obligatorio):** "IDs en superficies externas: política `public_id` para modelos públicos, PK para internos y body fields, prohibición de dual-lookup". Afecta contrato externo + invariante cross-team frontend/backend.
- **ADR opcional:** "Sub-recursos child internos usan PK bajo parent UUID — no se promueven a `public_id` sin caso de uso standalone." Sólo si se anticipa presión a agregar `public_id` a InvoiceItem en el futuro.
- **No ADR:** renombres internos de variables, lint frontend, fases del rollout. Son ejecución, no contrato.
