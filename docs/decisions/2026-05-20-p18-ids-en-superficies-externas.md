# ADR p18 — IDs en superficies externas (Día 6)

**Fecha:** 2026-05-20
**Estado:** ✅ Aceptado e implementado
**Branch:** `develop`
**Issues cerrados:** P0 #18, P1 #38, P1 #39, P1 #40

## Contexto

Pre-Día-6:
- 5 endpoints públicos exponían `<int:pk>` (vaccines, prescriptions items, staff, MR/prescriptions by pet).
- 9 query params filtraban por modelos públicos sin tenant scope (`?pet=`, `?owner=`, etc.).
- Frontend mezclaba `editing.public_id || editing.id` (4 sitios) — fallback dual-lookup.
- `appointments.jsx`, `prescriptions.jsx`, `petDetail.jsx`, `pets.jsx`, `inventory.jsx` usaban `.id` en URLs.
- `CreateEmployeeSerializer.organization_id` writable → privilege escalation cross-tenant.
- `MeView` exponía `organization.id` (PK) sin alternativa pública.
- `setActiveRecordId` no declarado → crash al editar consulta (P0 #21).

Apagar `ALLOW_LEGACY_ID_LOOKUP=False` rompe la app entera mientras estos puntos no se cierren.

## Decisión

Política `public_id` UUID para modelos públicos, PK entero para modelos internos y FK body fields. Prohibición de dual-lookup (`editing.public_id || editing.id`) en frontend. Migración aditiva single-shot pre-beta para `Organization`, `User`, `VaccineRecord`.

### Clasificación final

**Públicos (exponen `public_id`):** Pet, Owner, Appointment, MedicalRecord, Invoice, Prescription, Product, Presentation, Service, **VaccineRecord** (nuevo), **User** (nuevo), **Organization** (nuevo).

**Internos (PK only):** InvoiceItem, MedicalRecordProduct, MedicalRecordService, StockMovement, InvoiceAuditLog, AppointmentStatusChange, VitalSigns, Permission, Role, UserRole.

**Trigger de promoción futura:** caso de uso navegable / compartible standalone documentado. Nunca por estética.

### Convenciones cross-layer

| Capa | Convención |
|---|---|
| Backend Python / DB / JSON | `public_id` (snake_case, UUID v4) |
| Frontend JS variables / params | `publicId` (camelCase) |
| URLs / deep links | UUID v4 raw |
| FK body fields (POST/PATCH) | PK entero (`PrimaryKeyRelatedField`) |

### Invariantes obligatorios

1. **Query param resolution:** todo `?<modelo_publico>=<value>` pasa por `resolve_public_id(Model.objects.for_organization(org), value)`. Prohibido `qs.filter(<modelo>_id=raw)`.
2. **Sub-recurso parent-child:** detail view filtra `pk + parent=parent_obj`, ambos en misma query.
3. **404-as-403:** queryset de detail empieza por `for_organization()` (ADR-10). Cross-tenant siempre 404, nunca 403.
4. **List views anidadas:** declaran `required_permission` por método HTTP en `initial()` (ADR-09). Sin esto, `_method_to_action` infiere `retrieve` por presencia de `pk` y rompe RBAC silenciosamente.
5. **CreateEmployeeSerializer.organization_id** es `read_only=True`. Organization siempre derivada de JWT.

## Implementación

### Fase 0 — Audit baseline
- Test introspectivo `apps/core/tests/test_url_audit.py` con 2 guards: cero `<int:pk>` en URLs públicas + cero `filter(<modelo>_id=raw)`.

### Fase 1 — Backend URLs públicos
- `medical_records/urls.py`: `medical-records/pet/<str:pet_public_id>/`.
- `prescriptions/urls.py`: `pet/<str:pet_public_id>/`, `<str:prescription_pk>/items/`, items detail `<str:prescription_pk>/items/<int:pk>/`.
- Views: `MedicalRecordByPetView`, `PrescriptionByPetView`, `PrescriptionItemCreateView`, `PrescriptionItemDeleteView` resuelven via `resolve_public_id`.

### Fase 2 — Frontend
- Eliminado `editing.public_id || editing.id` en 4 sitios (`inventory.jsx` × 3, `OperationalFeed.jsx` × 1).
- `appointments.jsx`: 13 ocurrencias `appt.id` → `appt.public_id`.
- `prescriptions.jsx`: 3 sitios edit/view/delete → `rx.public_id`.
- `petDetail.jsx`: `record.id` + 5 `pet.id` → `public_id`.
- `pets.jsx`: 8 sitios `pet.id` + `editing.id` + `selectedPet?.id` → `public_id`.
- `staff.jsx`: deactivate handler → `member.public_id`.
- `medicalRecords/index.jsx`: eliminada llamada a `setActiveRecordId` no declarado (P0 #21).

### Fase 3 — Query params (BLOCKER)
- 7 vistas con filtros por modelo público migradas a `resolve_public_id`:
  - `appointments/views.py` (?pet)
  - `billing/views.py` (?owner)
  - `inventory/views.py` (?product, ?presentation)
  - `medical_records/views.py` (?pet en MR + VaccineRecord)
  - `patients/views.py` (?owner)
  - `prescriptions/views.py` (?pet)
- Cross-tenant ahora retorna 404 (no `[]`).

### Fase 4 — Organization + Issue #40
- Migración `organizations/0008_day6_add_public_id.py` (aditiva 3 pasos: nullable + backfill + NOT NULL).
- `OrganizationSerializer.fields` incluye `public_id`.
- `MeView` response: `organization_public_id` (str UUID) + `organization` (id PK retrocompat).
- `CreateEmployeeSerializer.organization_id` → `read_only=True`.

### Fase 5 — User + VaccineRecord + Issue #38
- Migración `users/0007_day6_add_public_id.py`.
- Migración `medical_records/0018_day6_vaccine_public_id.py`.
- `User` ahora con `public_id` UUID.
- `VaccineRecord` hereda `PublicIdMixin`.
- `vaccines/<str:pk>/` con `PublicIdLookupMixin`.
- `staff/<str:pk>/` resuelve via `resolve_public_id`.
- `UserSerializer.fields` incluye `public_id`.

### Refactor anti-divergencia
- `apps/core/views.py`: extracción de `_resolve_or_404` privado compartido por `PublicIdLookupMixin.get_object` y `resolve_public_id`. Sin API pública nueva — solo dedup interno.

### Deprecation markers
- Branch `if str(lookup).isdigit() and ALLOW_LEGACY_ID_LOOKUP` marcado `DEPRECATED: remove after 2026-06-19 — see Issue #18`. Cleanup ticket pendiente.

## Resultado de tests

- Suite canónica: **301 tests OK** (2 skip esperados).
- `apps.core.tests.test_url_audit`: ambos guards verdes.
- Cero regresiones en tests existentes.

## Cutover NO ejecutado

`ALLOW_LEGACY_ID_LOOKUP=True` permanece en `settings.py`. El flag flip es decisión operacional separada que requiere:

1. ✅ Suite verde (hecho).
2. ✅ Audit guards verdes (hecho).
3. ⏳ Smoke staging 48h con `ALLOW_LEGACY_ID_LOOKUP=True` (operador).
4. ⏳ Flip a `False` en staging + smoke 48h sobre 10 flujos críticos (operador).
5. ⏳ Aprobación de operador para flip prod (no automatizable).

Backlog: ticket `2026-06-19` cleanup del flag legacy.

## Manual smoke checklist pre-cutover (NO automatizable)

Antes del flip `ALLOW_LEGACY_ID_LOOKUP=False` en staging:

### UI manual con DevTools Network abierto (15 min)

- [ ] Login → `/pets` → click pet → `/pets/<uuid>/` carga. Verificar URL = UUID, no PK.
- [ ] `/pets/<uuid>` → tab Historial → click "Ver consulta" → MR detail abre. Network: `GET /api/medical-records/<uuid>/`.
- [ ] `/medical-records` → click pet en sidebar → carga consultas. Network: `GET /api/medical-records/?pet=<uuid>` (NO `?pet=42`).
- [ ] `/medical-records` → click "Crear Consulta" en stepper → POST exitoso. Network: body `pet: <int>` (PK por ADR p18).
- [ ] `/appointments` → seleccionar cita `done` → "Ver Consulta" → navega a `?record=<uuid>`.
- [ ] `/appointments` → seleccionar cita `done` → "Crear Consulta Médica" → navega a `?pet=<uuid>&appointment=<uuid>`.
- [ ] `/appointments` walk-in → POST exitoso. Network: body `pet: <int>` (PK).
- [ ] `/billing` → seleccionar invoice → confirm → pay → todo OK. Network: `PATCH /api/billing/invoices/<uuid>/confirm/`.
- [ ] `/prescriptions?pet=<uuid>` deep link → filtra correctamente.
- [ ] `/inventory` → editar producto → save OK. Sin fallback `editing.public_id || editing.id`.
- [ ] `/staff` → deactivate → 204. Network: `DELETE /api/staff/<uuid>/`.
- [ ] Bookmark legacy con `<pk>` entero (ej. `/pets/42`) con flag OFF → toast "Recurso no encontrado" + redirect a `/pets`. **NO pantalla blanca.**

### Network tab: zero PK leaks

Buscar en DevTools Network durante navegación normal:
- Cualquier `/api/*/123/` con PK entero → bug pendiente.
- Cualquier `?pet=42`, `?owner=42`, `?record=42` → bug pendiente.
- Cualquier 404 inesperado al navegar UI normal con flag OFF.

### Backend invariantes auto-test

```bash
cd backend && python manage.py test --noinput apps.core.tests.test_day6_invariants apps.core.tests.test_url_audit
```

Debe pasar 100%.

## Out of scope (deferred)

- Eliminar `id` de response JSON → post-beta cleanup.
- Migración UUID v4 → v7 → solo si fragmentation se materializa.
- Índice compuesto `(organization, public_id)` → sólo si EXPLAIN muestra ganancia >20%.
- `username` UNIQUE per-org (P2 #46) → ticket aparte.
- `Service.unique_together` con org (P2 #43) → ticket aparte.
- `VitalSigns.public_id` → diferido hasta caso de uso standalone.
- `InvoiceItem`/`MRP`/`MRS` `public_id` → diferido indefinidamente.

## Convenciones a llevar a CLAUDE.md

Agregar sección "Convenciones de IDs" con las 4 capas (`public_id` Python/DB/JSON, `publicId` JS, UUID raw URL, PK FK body).

## Runbook a documentar

`docs/runbooks/exposing-new-model.md` con los 9 pasos para exponer un modelo nuevo (de plan §4 / anexo code quality §6).
