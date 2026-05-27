# Remediación de auditoría arquitectónica — estado

**Fecha:** 2026-05-26
**Origen:** auditoría arquitectónica profunda (modelado, concurrencia, multitenancy, escalabilidad, índices, analytics).
**Branch:** `develop` (10 commits, sin push al cierre).
**Estado:** Capas 0–3 (do-now) cerradas. Capa 3 (RLS), 4 y 5 diferidas con rationale.

---

## Resumen ejecutivo de la auditoría

- **Madurez alta** para pre-beta: CHECK constraints como contrato, provenance de anchors, advisory locks per-org, lock contracts documentados.
- Los 2 hallazgos "críticos" iniciales (**C1 deadlock ABBA**, **C2 lost-update `Invoice.total`**) fueron **DESCARTADOS con tests concurrentes reales** (Postgres + threads). El código ya enforza orden global de locks y lockea la Invoice en toda mutación de ítems.
- **Riesgo real = regresión futura**, no bug activo. La estrategia: blindar con tests permanentes + ratchets, no refactorizar lo que funciona.

---

## Plan por capas — estado

| Capa | Tema | Estado |
|------|------|--------|
| 0 | Verificación (C1/C2/drift) | ✅ Cerrada |
| 1 | Integridad (locks, recalc, reconciliación stock) | ✅ Cerrada |
| 2 | Quick wins (índices, retención) | ✅ Cerrada |
| 3 | Seguridad estructural — do-now (AST anti-leak, contención id/public_id) | ✅ Cerrada |
| 3 | RLS DB-side | ⏸️ Diferida → post-beta (ADR p23) |
| 4 | Escala (particionado, `org_id` en InvoiceAuditLog, PgBouncer, SET_NULL/PROTECT) | ⏳ Pendiente (requiere ADR) |
| 5 | Largo plazo (read-replica, late-arrival hard-reject, warehouse, peso v2) | ⏳ Pendiente |

---

## HECHO

### Capa 0 — Verificación
- **C1 (deadlock ABBA Invoice↔Presentation): NO existe.** Orden global consistente `MedicalRecord → Invoice → Presentation → InvoiceItem`; `_lock_presentations` ordena por PK. Suite `test_invoice_concurrency` (7 tests, Postgres+threads) verde sin deadlock.
- **C2 (lost-update `Invoice.total`): NO existe.** Toda mutación de `InvoiceItem` corre con `select_for_update()` sobre la Invoice en todo el `atomic()`. Las mutaciones concurrentes serializan en el row-lock.
- **Drift de stock:** `audit_stock_integrity` corrido en dev DB → 0 drift; 63 presentaciones `no_baseline` (creadas por data migration `0005` sin movimiento de apertura — esperado, no es bug).

### Capa 1 — Integridad
- `d320be6` — assert del `total` (no solo count) en el test concurrente; guard warn-only `INVOICEITEM_MUTATION_OUTSIDE_ATOMIC` en `InvoiceItem.save/delete`; comando `audit_stock_integrity` (reconcilia stock vs ledger desde último `adjustment`).
- `c64564c` — orden global de locks documentado en `CLAUDE.md`.
- `15dc718` — `recalculate_totals` vía `Sum()` agregado (evita O(n) objetos por llamada) + `updated_at` explícito en el `.update()`.

### Capa 2 — Quick wins
- `3f4e926` — drop de índices muertos: `Presentation.product/stock`, `Appointment.start/end_datetime` lone, `Product.internal_code` lone. (Verificado que no son load-bearing: conflict-detection se apoya en FK `veterinarian_id` + composite `(org, start_datetime, status)`.)
- `b692409` — índices GIN trigram (`pg_trgm`) en `Owner.name` y `Pet.name` (búsqueda usa `icontains`). + `django.contrib.postgres` en INSTALLED_APPS.
- `15de886` — comando `prune_dashboard_snapshot_audit` (retención, borrado físico en lotes).
- `b061b0b` — requisito de extensión `pg_trgm` documentado en `DEPLOY_VPS_PLAN.md`.
- **Saltado deliberadamente:** índice `InvoiceAuditLog.created_at` (N chico por invoice → sort gratis; agregar = write amplification sin beneficio).

### Capa 3 — Seguridad estructural (do-now)
- `e89d0e1` — **ratchet AST anti-leak de tenant isolation**: escanea `views/services/serializers` por `<Model>.objects.<read>` sin `for_organization`; baseline de 21 accesos existentes; nuevo no-baselineado → falla.
- `34d6954` — **ratchet de contención `id`/`public_id`** (ADR p24): baseline de 12 serializers que exponen `id`+`public_id`; nuevo serializer con ambos → falla. Regla añadida a `CLAUDE.md`.

### Controles permanentes nuevos (resumen)
- 2 ratchets `SimpleTestCase` (<0.5s, sin DB): tenant-leak + dual-exposure.
- 2 comandos de auditoría wireables a cron: `audit_stock_integrity`, `prune_dashboard_snapshot_audit`.
- Orden de locks canónico en `CLAUDE.md`.
- ADRs: **p23** (RLS, Propuesto), **p24** (deuda id/public_id, Aceptado).

---

## PENDIENTE

### Capa 3 — RLS (Row-Level Security) — DIFERIDA a post-beta
**ADR p23 (Propuesto).** Aislamiento DB-side estructural por `organization_id`.
- **Por qué no ahora:** blast radius actual bajo; el ratchet AST cubre el grueso del riesgo de regresión a costo ~0; RLS añade complejidad operacional real.
- **2 footguns críticos documentados:** rol `vet` es superuser (ignora RLS) → requiere split de roles; PgBouncer transaction-pooling + conn persistente leakea la GUC sin `SET LOCAL`.
- **Bloqueante de orden:** requiere `organization_id` en `InvoiceAuditLog` (Capa 4) primero.
- **Exit criteria para retomar:** beta estable + varias clínicas reales + decisión de pool/conexiones (junto a PgBouncer).

### Capa 4 — Escala (requiere ADR antes de implementar)
- **Particionar tablas append-only** (`StockMovement`, `AppointmentStatusChange`, `InvoiceAuditLog`) por rango mensual + retención. Antes de ~10M filas.
- **Agregar `organization_id` a `InvoiceAuditLog`** (hoy sin tenant directo; bloqueante de RLS completa).
- **PgBouncer** transaction pooling (acoplado al footgun `SET LOCAL` de RLS).
- **Decidir `SET_NULL` vs `PROTECT`** en `Invoice.medical_record`/`appointment` (factura es registro contable; ¿debe quedar huérfana de origen?).

### Capa 5 — Largo plazo (cuando métricas lo pidan)
- Read-replica para analytics (hoy corre sobre OLTP).
- Hard-reject de late arrivals (`LateAnchorError`, Día 7+ ya previsto; hoy warn-only).
- Warehouse columnar (CDC) si analytics sobre OLTP duele.
- Migración v2 de peso (`MedicalRecord.weight` → `VitalSigns` única fuente).
- Sharding por tenant si un Postgres topa.

### Deuda menor surgida en la sesión
- **Cobertura de `audit_stock_integrity`:** limitada a ventanas post-`adjustment` (las presentaciones sin adjustment = `no_baseline`, no verificables). Opción futura (toca ledger, decisión consciente): comando one-shot que emita `adjustment` de apertura para las `no_baseline`.

---

## Scores de la auditoría (referencia)

Modelado 8.0 · Escalabilidad 5.5 · Integridad 8.5 · Seguridad 7.0 · Mantenibilidad 8.0 · Concurrencia 7.0 · Analytics-readiness 7.5 · Enterprise-readiness 6.0. **Global ~7.2/10.**

Bloqueadores para "escala enterprise" (no pre-beta): (1) RLS, (2) particionado+retención de append-only, (3) read-replica analytics.

---

## Referencias

- `docs/decisions/2026-05-26-p23-rls-tenant-isolation.md`
- `docs/decisions/2026-05-26-p24-id-public-id-dual-exposure-containment.md`
- `CLAUDE.md` — orden de locks; anti-pattern serializer `id`+`public_id`.
- `backend/apps/core/tests/test_tenant_scoping_audit.py`, `test_public_id_dual_exposure_audit.py`
- `backend/apps/inventory/management/commands/audit_stock_integrity.py`
- `backend/apps/analytics/management/commands/prune_dashboard_snapshot_audit.py`
- `DEPLOY_VPS_PLAN.md` — requisito `pg_trgm`.
