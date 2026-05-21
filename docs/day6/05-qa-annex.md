# Anexo QA — Plan Día 6

## 1. Veredicto

**Testable con gaps críticos.** El draft + 3 anexos definen claramente boundaries (`public_id` vs PK), invariantes de seguridad y migraciones, pero **no declaran una sola suite de tests bloqueante**. El draft §11 confía en "smoke 48h" como gate; insuficiente. Los tres riesgos de QA no cubiertos: (a) ningún test verifica `flag OFF + PK entero → 404` por endpoint, (b) ningún test prueba el invariante "tenant mismatch siempre 404, nunca 403" del anexo seguridad §3, (c) ningún test bloquea la regresión `_method_to_action` en list views anidadas tras cambio a `<str:pk>`. Pre-merge la coverage debe ser explícita por fase; sin esto, el flag flip de Fase 6 descubre fallos en staging por casualidad.

## 2. Tests obligatorios pre-merge por fase

| Fase | Archivo de test | Escenario | Expected |
|---|---|---|---|
| 0 | `apps/core/tests/test_url_audit.py::test_no_int_pk_in_public_urls` | Scan AST/regex de `apps/*/urls.py` busca `<int:pk>` en modelos públicos | 0 ocurrencias en Pet/Owner/Appointment/MR/Invoice/Prescription/Product/Presentation/Service |
| 1 | `apps/core/tests/test_public_id_lookup.py::test_str_kwarg_resolves_uuid` | GET `/api/<endpoint>/<uuid>/` con flag ON y OFF | 200 en ambos |
| 1 | `apps/core/tests/test_public_id_lookup.py::test_str_kwarg_rejects_pk_when_flag_off` | GET `/api/<endpoint>/<pk_int>/` con flag OFF | 404 con shape `{detail: "..."}` |
| 1 | `apps/medical_records/tests/test_vaccines_lookup.py::test_vaccine_detail_uses_public_id` | GET `/api/vaccines/<uuid>/` post-promoción (anexo seg) | 200; PK entero → 404 |
| 1 | `apps/medical_records/tests/test_pet_endpoints.py::test_mr_by_pet_public_id` | GET `/medical-records/pet/<pet_public_id>/` resuelve Pet vía `resolve_public_id` ANTES de filtrar | 200; PK entero → 404 (con flag OFF) |
| 2 | `frontend/__smoke__/url_construction.test.js` (o grep gate) | Ninguna page construye URL con `.id` para modelo público | grep retorna 0 matches en `src/pages/{appointments,prescriptions,petDetail,inventory,pets}.jsx` |
| 3 | `apps/medical_records/tests/test_query_param_pet.py::test_pet_query_param_resolves_uuid` | GET `/medical-records/?pet=<uuid>` filtra correctamente | 200 con resultados de ese pet |
| 3 | `apps/medical_records/tests/test_query_param_pet.py::test_pet_query_param_cross_tenant` | GET con `?pet=<uuid-otra-org>` | 404 (no `[]` — el anexo seg lo deja ambiguo; QA decide 404 por consistencia con detail) |
| 3 | `apps/medical_records/tests/test_query_param_pet.py::test_pet_query_param_pk_rejected_flag_off` | GET `?pet=42` flag OFF | 404 |
| 4 | `apps/organizations/tests/test_me_public_id.py::test_me_exposes_public_id` | GET `/api/organizations/me/` | Response contiene `public_id` UUID; `id` aún presente pre-beta |
| 4 | `apps/users/tests/test_create_staff_org_immutable.py::test_organization_id_not_writable` | POST `/api/staff/create/` con body `{organization_id: 999, ...}` | `organization` resuelto desde JWT, body field ignorado/rechazado |
| 4 | `apps/organizations/tests/test_legacy_view_org_id_writable.py::test_patch_org_id_ignored` | PATCH `/organizations/<pk>/` con `{id: 999}` | DB no cambia |
| 5 | `apps/users/tests/test_staff_deactivate_uuid.py::test_deactivate_by_public_id` | POST `/staff/<user_public_id>/deactivate/` | 200; PK entero → 404 con flag OFF |
| 5 | `apps/users/tests/test_staff_deactivate_uuid.py::test_deactivate_cross_tenant` | POST con UUID de user de otra org | 404 (no 403) |
| 6 | `apps/core/tests/test_flag_cutover.py::test_all_public_endpoints_404_on_pk_with_flag_off` | Loop sobre los 9 endpoints públicos con PK entero y flag OFF | 404 en todos |
| 6 | `apps/core/tests/test_flag_cutover.py::test_all_public_endpoints_200_on_uuid_with_flag_off` | Loop con UUID válido y flag OFF | 200 en todos |

## 3. Regression suite mínima (CI siempre)

- `apps.core.tests.test_public_id_lookup` — invariantes de mixin y `resolve_public_id`.
- `apps.core.tests.test_url_audit` — guard contra reintroducir `<int:pk>` en URL pública.
- `apps.core.tests.test_flag_cutover` — comportamiento dual flag ON/OFF por endpoint + flip roundtrip.
- `apps.core.tests.test_tenant_404_invariant` — cross-tenant siempre 404, nunca 403, por cada detail endpoint.
- Suite existente (294 tests del CLAUDE.md) — no debe perder un solo test.
- `apps.billing.tests.test_subresource_parent_child` — InvoiceItem/MRP/MRS detail filtran `pk + parent=parent_obj` y devuelven 404 cuando el child pertenece a otra invoice del mismo tenant.

## 4. Edge cases requeridos

| Caso | Test | Expected |
|---|---|---|
| UUID malformado `"not-a-uuid"` | `test_public_id_lookup.py::test_invalid_uuid_returns_404` | 404 con `{detail: "No encontrado."}`, no 500 |
| UUID válido inexistente | `test_public_id_lookup.py::test_valid_uuid_not_found_returns_404` | 404, sin SQL error |
| UUID de otra org | `test_tenant_404_invariant.py::test_cross_tenant_returns_404` | 404 por cada detail endpoint público |
| UUID con mayúsculas | `test_public_id_lookup.py::test_uppercase_uuid_normalizes` | 200 (Python `uuid.UUID` es case-insensitive) |
| UUID sin hyphens | `test_public_id_lookup.py::test_uuid_no_hyphens_accepted` | 200 (acepta ambos formatos) |
| UUID url-encoded en query string | `test_query_param_pet.py::test_url_encoded_uuid` | 200 |
| Path malformado `/api/pets/foo-bar/` | `test_public_id_lookup.py::test_garbage_path_returns_404` | 404 limpio, no 500 |
| Path con `-` solo `/api/invoices/-/items/1/` | `test_subresource_parent_child.py::test_dash_parent_returns_404` | 404 |
| Sub-recurso parent UUID válido + child PK de OTRA invoice mismo tenant | `test_subresource_parent_child.py::test_child_pk_wrong_parent` | 404 (no leakea) |
| Soft-deleted con UUID conocido | `test_public_id_lookup.py::test_soft_deleted_returns_404` | 404 |
| Cita `done` cuyo MR no existe (corrupción) | `apps.appointments.tests.test_done_without_mr` | Endpoint defensivo: no 500, retorna estado consistente o 404 documentado |
| 2 windows: 1 borra, 2 edita | smoke staging checklist §6 | Toast "Recurso no encontrado", redirect, no pantalla blanca |
| Payload UUID de 10MB en path | bloqueado por nginx/Django ~8KB cap — no test (cubierto por infra) | — |

## 5. Rollback validation

1. **Pre-cutover**: en CI ejecutar `test_flag_cutover` con `ALLOW_LEGACY_ID_LOOKUP=True` y luego con `False`. Ambos modos deben pasar la suite completa.
2. **Test de flip en CI**: `apps.core.tests.test_flag_cutover.py::test_flag_flip_roundtrip` — flip OFF, request con PK → 404; flip ON, mismo request → 200. Verificar sin restart del proceso (el flag es leído por request).
3. **Migraciones de Fase 4-5 reversibles**: `python manage.py migrate organizations <N-1>` y `migrate auth <N-1>` deben correr sin `IrreversibleMigration`. Test: `apps.core.tests.test_migrations.py::test_phase4_5_migrations_reversible`.
4. **Smoke post-rollback staging**: con flag re-encendido tras hipotético breakage, ejecutar la lista de 9 endpoints canónicos con UUID — todos 200. Tiempo de recovery objetivo: <60s (env var hot-toggle).
5. **Datos seed restaurables**: `python manage.py loaddata <seed>` post-migración Fase 4-5 produce orgs/users con `public_id` poblado vía `default=uuid4`. Test: `apps.organizations.tests.test_seed_with_public_id`.

## 6. Frontend crash prevention

No hay E2E framework. Mitigación: **smoke manual checklist obligatorio** pre-merge de Fase 2, y **error boundary verification**.

Checklist staging (operador humano, 15 min):

- [ ] Login → /pets → click un pet → /pets/:uuid carga sin pantalla blanca
- [ ] /pets/:uuid → tab historial clínico → MR detalle → no crash si `record.public_id` undefined (debe mostrar fallback UI)
- [ ] /appointments → status change (`start`/`done`/`cancel`) → 200 + UI actualizada
- [ ] /appointments → crear cita walk-in → factura draft generada
- [ ] /medical-records/:uuid/close → status `closed` → prescription create desde botón
- [ ] /billing → invoice draft → add item → confirm → pay
- [ ] /inventory → editar presentation (sin fallback `editing.public_id || editing.id`) → save OK
- [ ] /prescriptions → listado con UUID, PDF abre
- [ ] /staff → create → list → deactivate (Fase 5)
- [ ] Bookmark con PK entero (`/pets/42`) con flag OFF → toast "Recurso no encontrado" + redirect a `/pets` — **NO pantalla blanca**

Tests de UI prevención crashes (los pocos automatizables):

- `frontend/__smoke__/error_boundary.test.jsx::renders_fallback_on_undefined_public_id` — componente recibe prop con `public_id: undefined` → renderiza ErrorBoundary fallback, no white screen.
- Grep gate: `grep -rE "\.public_id\s*\|\|\s*\w+\.id" frontend/src/` retorna 0 (anexo code quality §2).

## 7. Performance gates

Cumplir antes del flag flip (Fase 6):

1. **EXPLAIN ANALYZE de las 9 queries canónicas** (anexo DB §6) — captura baseline + post. Test: `apps.core.tests.test_query_plan.py::test_public_id_lookup_uses_index` parsea EXPLAIN y assertea `Index Scan` (no `Seq Scan`), buffers `shared hit < 10`.
2. **Benchmark numérico de regresión**: suite `apps.billing.tests.test_invoice_state_machine` y `apps.medical_records.tests.test_close` tiempos ±10% vs baseline pre-Día-6. Test: `apps.core.tests.test_performance_regression.py::test_suite_within_tolerance`. Si supera 30%, fail.
3. **Write smoke**: 1000 inserts secuenciales en `Invoice`, `Appointment`, `Pet` en staging — tiempo idéntico al baseline (los modelos ya tienen `public_id`, no debe cambiar). Test manual + log.
4. **Migración Fase 4-5 timing**: `Organization.public_id` y `User.public_id` migrations completan <1s en staging. Test: `apps.core.tests.test_migrations.py::test_phase4_5_migration_timing` con assertion.

## 8. Gaps reconocidos

| Gap | Mitigación |
|---|---|
| No hay E2E framework (Cypress/Playwright) en el repo | Smoke staging checklist manual (§6) + grep gates frontend. Documentar en runbook. |
| Performance regression real solo medible con datos productivos | Alerta Sentry post-cutover para p95 de detail endpoints; threshold +50% vs baseline → page on-call |
| Concurrent windows (window-1 borra, window-2 edita) | Smoke manual + Sentry alert para `IntegrityError`/`DoesNotExist` post-cutover |
| Bookmark de usuarios con `?pet=<pk>` post-flag-off | Pre-beta: no aplica. Post-beta: blast email + redirect server-side por 30 días (no scope Día 6, documentar en backlog) |
| Cobertura cross-tenant en TODOS los endpoints (no solo los 9 públicos) | Test paramétrico `test_tenant_404_invariant` itera sobre URL conf; pierde si futuras URLs no se registran. Mitigación: el test es parte de regression CI, descubre nuevas URLs vía introspección |
| Bug latente en `MedicalRecordServiceDeleteView` (anexo seg §2) | Test explícito `apps.medical_records.tests.test_service_delete_tenant.py::test_service_org_revalidated` |
| Drift naming `publicId`/`public_id`/`uuid` | Sin enforcement automatizable más allá del lint propuesto en anexo code quality §3. Aceptar smoke periódico |
| `_method_to_action` regression en list views anidadas tras `<str:pk>` | Test: `apps.core.tests.test_hybrid_permission_nested.py::test_list_view_under_uuid_parent_requires_list_permission` — POST/GET sobre `/medical-records/<uuid>/vitals/` con role que tiene `list` pero NO `retrieve` debe pasar |

## 9. Test files canónicos sugeridos

Nuevos archivos a crear en Día 6:

- `apps/core/tests/test_public_id_lookup.py` — invariantes mixin + `resolve_public_id` (UUID válido, inválido, soft-deleted, mayúsculas, sin hyphens, cross-tenant).
- `apps/core/tests/test_url_audit.py` — guard introspectivo contra `<int:pk>` en URL pública.
- `apps/core/tests/test_flag_cutover.py` — comportamiento dual flag ON/OFF por endpoint + flip roundtrip.
- `apps/core/tests/test_tenant_404_invariant.py` — cross-tenant siempre 404 (parametrizado por los 9 endpoints públicos).
- `apps/core/tests/test_query_plan.py` — EXPLAIN ANALYZE assertions.
- `apps/core/tests/test_performance_regression.py` — tiempos suite ±10%.
- `apps/core/tests/test_migrations.py` — reversibilidad + timing migraciones Fase 4-5.
- `apps/core/tests/test_hybrid_permission_nested.py` — guard contra ADR-09 regression.
- `apps/billing/tests/test_invoice_id_cutover.py` — flag ON/OFF en Invoice endpoints + subresource parent-child invariante.
- `apps/billing/tests/test_subresource_parent_child.py` — InvoiceItem child PK con parent ajeno → 404.
- `apps/medical_records/tests/test_vaccines_lookup.py` — VaccineRecord post-promoción a `public_id`.
- `apps/medical_records/tests/test_pet_endpoints.py` — `medical-records/pet/<uuid>/` y `prescriptions/pet/<uuid>/`.
- `apps/medical_records/tests/test_query_param_pet.py` — query param resolution con tenant.
- `apps/medical_records/tests/test_service_delete_tenant.py` — anexo seg §2 (revalidar `service.organization`).
- `apps/appointments/tests/test_done_without_mr.py` — endpoint defensivo cita `done` sin MR.
- `apps/organizations/tests/test_me_public_id.py` — `/me/` expone `public_id`.
- `apps/organizations/tests/test_legacy_view_org_id_writable.py` — PATCH `id` ignorado.
- `apps/organizations/tests/test_seed_with_public_id.py` — loaddata post-migración.
- `apps/users/tests/test_create_staff_org_immutable.py` — Issue #40.
- `apps/users/tests/test_staff_deactivate_uuid.py` — Issue #38 + cross-tenant.
- `frontend/__smoke__/error_boundary.test.jsx` — fallback UI cuando `public_id` undefined.
- `frontend/__smoke__/url_construction.test.js` — grep gate `\.public_id\s*\|\|\s*\w+\.id` retorna 0.

Total: 21 archivos nuevos. Ningún framework nuevo — todo pytest + DRF `APITestCase` + grep gates en CI.
