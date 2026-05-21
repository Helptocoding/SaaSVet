# Fase 0 — Audit baseline

**Fecha:** 2026-05-20
**Estado:** completo

## Backend — `<int:>` en URLs

### Modelos públicos (DEBEN cambiar)

| Archivo | Línea | URL | Modelo público | Fase target |
|---|---|---|---|---|
| `apps/medical_records/urls.py` | 23 | `medical-records/pet/<int:pet_id>/` | Pet | Fase 1 |
| `apps/medical_records/urls.py` | 27 | `vaccines/<int:pk>/` | VaccineRecord | Fase 5 (requiere migración) |
| `apps/prescriptions/urls.py` | 15 | `prescriptions/pet/<int:pet_id>/` | Pet | Fase 1 |
| `apps/prescriptions/urls.py` | 16 | `prescriptions/<int:prescription_pk>/items/` | Prescription parent | Fase 1 |
| `apps/prescriptions/urls.py` | 17 | `prescriptions/<int:prescription_pk>/items/<int:pk>/` | Prescription parent (child PK OK) | Fase 1 |
| `config/urls.py` | 101 | `api/staff/<int:pk>/` | User | Fase 5 (requiere migración) |

### Child interno (PK OK, no cambia)

| Archivo | Línea | URL | Justificación |
|---|---|---|---|
| `apps/medical_records/urls.py` | 25 | `medical-records/<str:medical_record_pk>/services/<int:pk>/` | MedicalRecordService es child interno (sub-recurso anidado) |
| `apps/prescriptions/urls.py` | 17 | `items/<int:pk>/` | PrescriptionItem es child interno |

### Legacy intencional (no cambia, Sunset 2026-08-17)

| Archivo | Línea | URL | ADR |
|---|---|---|---|
| `config/urls.py` | 93 | `api/organizations/<int:pk>/` | ADR-15 (p16) |

---

## Backend — query params (filtros por modelo público)

### BLOCKER Fase 3 — migrar a `resolve_public_id`

| Archivo | Línea | Param | Modelo |
|---|---|---|---|
| `apps/inventory/views.py` | 192 | `product` | Product |
| `apps/inventory/views.py` | 195 | `presentation` | Presentation |
| `apps/appointments/views.py` | 50 | `veterinarian` | User (post-Fase 5) |
| `apps/appointments/views.py` | 52 | `pet` | Pet |
| `apps/billing/views.py` | 66 | `owner` | Owner |
| `apps/patients/views.py` | 23 | `owner` | Owner |
| `apps/prescriptions/views.py` | 25 | `pet` | Pet |
| `apps/medical_records/views.py` | 90 | `pet` | Pet |
| `apps/medical_records/views.py` | 509 | `pet` | Pet |

**Total: 9 sitios a migrar en Fase 3.**

### Query params no críticos (sin modelo público, OK como están)

`active`, `category`, `stock__gt`, `search`, `status`, `invoice_type`, `created_from`, `created_to`, `paid_from`, `paid_to`, `to`, `from`, `org`, `include_today`, `is_generic`, `role`, `date`, `veterinarian` (numérico interno hasta Fase 5).

---

## Frontend — fallback dual-lookup (zero matches required)

### Hallazgos actuales (DEBEN eliminarse Fase 2)

| Archivo | Línea | Patrón |
|---|---|---|
| `frontend/src/pages/inventory.jsx` | 263 | `editing.public_id \|\| editing.id` |
| `frontend/src/pages/inventory.jsx` | 298 | `adjustingProduct.public_id \|\| adjustingProduct.id` |
| `frontend/src/pages/inventory.jsx` | 600 | `product.public_id \|\| product.id` |
| `frontend/src/components/dashboard/OperationalFeed.jsx` | 51 | `r.public_id \|\| r.id` |

**Total: 4 sitios a eliminar.**

### URL templates con `.id` en API layer

Cero matches en `frontend/src/api/`. Los API functions reciben `id` como parámetro genérico — caller responsable de pasar `public_id`.

---

## Nested list views bajo `<str:pk>` UUID parent

Vistas que DEBEN declarar `required_permission` por método HTTP en `initial()` (ADR-09, BLOCKER Fase 1):

- `VitalSignsListCreateView` (`medical-records/<str:pk>/vitals/`)
- `MedicalRecordSummaryView` (`medical-records/<str:pk>/summary/`)
- `MedicalRecordServiceListCreateView` (`medical-records/<str:medical_record_pk>/services/`)
- `MedicalRecordProductListCreateView` (`medical-records/<str:medical_record_pk>/products/`)
- `InvoiceItemCreateView` (`billing/invoices/<str:invoice_pk>/items/`)
- `InvoiceItemDetailView` (`billing/invoices/<str:invoice_pk>/items/<str:pk>/`)
- `PresentationCreateView` (`inventory/products/<str:product_pk>/presentations/`)
- Post-Fase 1: `PrescriptionItemCreateView` y `PrescriptionItemDeleteView` (nuevas anidadas bajo `<str:prescription_pk>`).

---

## Páginas frontend con alto-riesgo (audit manual Fase 2)

| Página | Líneas con `.id` críticas |
|---|---|
| `appointments.jsx` | 199, 214, 366, 368, 374, 379, 389, 394, 399, 415, 420, 435, 452 |
| `prescriptions.jsx` | 212, 303, 315, 328 |
| `petDetail.jsx` | 62, 117, 123, 191, 313, 320 |
| `inventory.jsx` | 263, 298, 600 |
| `pets.jsx` | 318, 482, 580, 708, 709, 1016, 1043, 1078 |
| `medical-records/index.jsx` | 81, 161, 197, 383 (manual review — algunos OK como state interno) |
| `OperationalFeed.jsx` | 49, 51 |
