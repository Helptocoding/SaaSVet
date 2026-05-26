# ADR p23: Row-Level Security (RLS) para aislamiento multitenant a nivel DB

**Fecha:** 2026-05-26
**Estado:** **Propuesto** — pendiente de revisión y decisión de timing. NO implementado.
**Impacto:** infra crítica transversal — Postgres, `apps/core` (middleware + connection role), todos los modelos `OrganizationalModel`, deploy (`DEPLOY_VPS_PLAN.md`), jobs (`build_daily_metrics`, `audit_*`, `prune_*`), `apps/platform` (cross-org).
**Sigue a:** ADR p14 (tenant validators — Fase 2B anticipa "DB-level enforce que sobrevive bypass de Python"), ADR p16 (cascade lockdown).
**Origen:** Auditoría arquitectónica 2026-05-26, hallazgo C3 (aislamiento = convención, no estructura). Capa 3 del plan de remediación.

---

## Contexto

### Capas de aislamiento actuales

1. **`TenantManager.get_queryset()` NO filtra organización** (`core/models.py:109-112`). Solo aplica `is_active=True`. El scoping por tenant depende 100% de que cada caller escriba `for_organization(org)`.
2. **`for_organization(org)`** es la convención obligatoria (CLAUDE.md), aplicada manualmente en views/services.
3. **Tenant validators en serializers** (ADR p14) — validan FKs cross-org en write paths → 400.
4. **`HybridPermission.has_object_permission`** — object-level, emite `TENANT_MISMATCH_DETECTED`.
5. **`all_objects`** (manager sin filtros) usado intencionalmente en hot paths (`recalculate_totals`, `apply_stock_movement`) que corren fuera de contexto de request.

### El gap (C3)

**El aislamiento es convención, no estructura.** Un solo `Model.objects.filter(pet=x)` sin `for_organization` en un PR futuro = fuga cross-tenant **sin error, sin log, sin test que lo atrape** (salvo que toque una URL cubierta por `test_url_audit`, que solo cubre URLs/query-params, no el ORM interno).

A escala (más devs, más endpoints, más superficie), la probabilidad de un leak por omisión crece monótonamente. No hay red de seguridad a nivel DB: si el código pide filas de otra org, la DB las entrega.

ADR p14 §99 ya reconoció esto: la validación Python "no sobrevive bypass de Python"; el control real es DB-side.

---

## Decisión propuesta

Activar **PostgreSQL Row-Level Security** sobre todas las tablas tenant, con una política que filtra por `organization_id` contra una variable de sesión (`app.current_org`) seteada por request. La DB rechaza estructuralmente cualquier fila de otra organización, independientemente de que el código haya olvidado `for_organization`.

### Diseño técnico

**1. GUC por request (`SET LOCAL`)**
Middleware en `apps/core` que, dentro de una transacción por request, setea:
```sql
SET LOCAL app.current_org = '<request.user.organization_id>';
```
- `SET LOCAL` (no `SET`): se resetea al fin de la transacción. **Obligatorio** — ver footgun pooling abajo.
- Requiere que cada request corra dentro de una transacción → `ATOMIC_REQUESTS = True` o el middleware abre `transaction.atomic()` explícito antes de setear.

**2. Política RLS por tabla tenant**
```sql
ALTER TABLE <tabla> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <tabla> FORCE ROW LEVEL SECURITY;   -- aplica también al owner del table
CREATE POLICY tenant_isolation ON <tabla>
    USING (organization_id = current_setting('app.current_org')::bigint)
    WITH CHECK (organization_id = current_setting('app.current_org')::bigint);
```
- `USING` filtra SELECT/UPDATE/DELETE; `WITH CHECK` bloquea INSERT/UPDATE que pongan org ajena.
- `FORCE` necesario porque el rol de la app suele ser owner de las tablas (Django migrate las crea) y el owner es exento sin FORCE.

**3. Rol de aplicación NO-superuser, NO-BYPASSRLS**
RLS **no aplica a superusers ni a roles con `BYPASSRLS`**. Hoy el rol `vet` del `docker-compose.prod.yml` es `POSTGRES_USER` → **superuser del cluster → RLS sería ignorada por completo.** Prerequisito duro: la app debe conectarse con un rol normal (sin SUPERUSER, sin BYPASSRLS).

**4. Estrategia de bypass para operaciones legítimas cross-org**
Un rol separado `vet_admin` con `BYPASSRLS` para:
- **Migraciones** (`migrate`) — data migrations tocan todas las orgs.
- **`apps/platform`** — vistas ADMIN_SAAS cross-org legítimas.
- **Superuser bootstrap signal** (`post_migrate`).

Jobs que iteran por org **NO necesitan bypass**: pueden setear `app.current_org` por org dentro de su loop y quedar dentro de RLS:
- `build_daily_metrics` ya itera `Organization.objects.all()` y computa por org → setear GUC por org.
- `audit_anchor_integrity` / `audit_stock_integrity` / `prune_dashboard_snapshot_audit` — o loop-per-org con GUC, o correr con `vet_admin`. (Decisión por job en Fase 3.)

**5. Interacción con `all_objects`**
Con RLS activa, incluso `all_objects` queda sujeto a la política (RLS es DB-side, indiferente al manager Python). Análisis por caller:
- `apply_stock_movement` (`Presentation.all_objects...update`): corre dentro del request con `app.current_org` seteado; la presentation pertenece a esa org → la política la matchea. OK.
- `recalculate_totals` (`Invoice.all_objects...update`): mismo request, misma org. OK.
- El propósito histórico de `all_objects` (saltar el filtro de tenant cuando el contexto se limpió) deja de ser necesario para aislamiento — la GUC de la transacción persiste. **Revisar caso por caso en Fase 3.**

**6. Tablas sin `organization_id`**
- `InvoiceAuditLog` — hoy SIN `organization_id` (ver auditoría C, Capa 4). RLS por org requiere **primero** agregar la columna (Capa 4) o política vía JOIN a `Invoice` (más cara). **Bloqueante: Capa 4 antes que RLS completa en esta tabla.**
- `Permission`, `UserRole` — globales/no-tenant; sin RLS.
- `User` — `organization_id` nullable (ADMIN_SAAS). Política con manejo de NULL.
- `Organization` — raíz del tenant; política `id = current_org` o exenta + scoping por app.

---

## Opciones rechazadas

### A — Mantener solo convención + test AST anti-leak
Un test que escanea el AST por `.objects.filter(` sin `for_organization`. **Útil y barato, pero NO estructural**: no cubre `get()`, `aggregate()`, related managers (`pet.medical_records.all()`), raw, ni código que el linter no parsea. Atrapa el patrón obvio, no el aislamiento real.
→ **No se rechaza del todo: se adopta como control interino** (item separado de Capa 3, sin ADR), porque cierra ~80% del riesgo de regresión hoy a costo cero.

### B — Schema-per-tenant / django-multitenant
Un schema Postgres por org, o librería de routing. **Rechazada pre-beta**: rewrite mayor del data layer, migraciones N×schemas, complejidad operacional alta. RLS es shared-schema (lo que ya tenemos) + una capa de policy — mucho menor blast radius.

### C — Solo CHECK constraints / triggers de consistencia FK
Los CHECK (ya existentes para anchors) y un trigger `invoice.organization = owner.organization` (anticipado en p14 Fase 2B) protegen **integridad de escritura**, pero **no bloquean un SELECT que lea filas de otra org**. RLS cubre lectura Y escritura. Complementarios, no sustitutos.

---

## Riesgos y mitigaciones

| Riesgo | Severidad | Mitigación |
|--------|-----------|------------|
| **Rol `vet` es superuser → RLS ignorada** | CRÍTICO | Prerequisito: rol app no-superuser no-BYPASSRLS. Cambia el setup de `docker-compose.prod.yml`. Documentar en DEPLOY. |
| **PgBouncer transaction-pooling + `SET` (no LOCAL) → GUC leakea al siguiente tenant en la conexión reusada** | CRÍTICO | Usar SIEMPRE `SET LOCAL` dentro de `transaction.atomic()` por request. Nunca `SET` a nivel sesión. Capa 4 planea PgBouncer → este footgun es real, no teórico. |
| **`conn_max_age=60` (conexiones persistentes Django) → GUC de un request sobrevive al siguiente en la misma conexión** | ALTO | `SET LOCAL` + transacción por request resetea al commit. Verificar que ningún path setee la GUC fuera de transacción. |
| **Migraciones filtradas por RLS → data migrations ven 0 filas / fallan** | ALTO | `migrate` corre con rol `vet_admin` (BYPASSRLS). |
| **Jobs cross-org (`audit_*`, analytics) rotos** | MEDIO | Loop-per-org seteando GUC, o correr con `vet_admin`. Decisión por job. |
| **`apps/platform` ADMIN_SAAS cross-org bloqueado** | MEDIO | Rol `vet_admin` para esos endpoints, o conexión dedicada. |
| **Performance: `current_setting()` por fila** | BAJO | Postgres lo optimiza (stable function); el filtro usa el índice `(organization, ...)` igual que `for_organization`. |
| **Debug más difícil (filas "desaparecen" sin error en SELECT)** | BAJO | Logging del GUC en middleware; runbook de troubleshooting. |

---

## Plan de fases (si se aprueba)

**Fase 0 — Prerequisitos**
- Capa 4: agregar `organization_id` a `InvoiceAuditLog`.
- Definir roles: `vet` (app, no-superuser, no-bypass) + `vet_admin` (BYPASSRLS, migraciones/platform).
- Ajustar `docker-compose.prod.yml` + `DATABASE_URL` (app) + conexión admin separada.

**Fase 1 — Infraestructura GUC (sin policies aún)**
- Middleware `SET LOCAL app.current_org` + `ATOMIC_REQUESTS` (o atomic explícito).
- Tests: GUC seteada correctamente por request; reseteada entre requests; manejo de usuario sin org / anónimo.

**Fase 2 — RLS en modo permisivo (shadow)**
- `ENABLE` (sin `FORCE`) en 1-2 tablas piloto (ej. `patients_owner`, `patients_pet`).
- Validar que la app funciona idéntico (owner exento sin FORCE = no rompe nada todavía).

**Fase 3 — `FORCE` + rollout por tabla + auditar `all_objects`**
- `FORCE ROW LEVEL SECURITY` tabla por tabla.
- Revisar cada uso de `all_objects` y cada job cross-org.
- Test de leak: query sin `for_organization` desde una org NO devuelve filas de otra (el test que hoy NO existe).

**Fase 4 — Limpieza**
- Evaluar simplificar `for_organization` (RLS lo hace redundante para aislamiento, pero se mantiene por claridad + performance del índice + defense-in-depth).

---

## Recomendación de timing (honesta)

**RLS es el control correcto a largo plazo, pero NO es pre-beta-urgente** dado:
- Blast radius actual bajo (pocas clínicas, equipo chico).
- El **test AST anti-leak** (Opción A, adoptado como interino) cierra el grueso del riesgo de regresión a costo ~cero y sin riesgo operacional.
- RLS introduce complejidad operacional real (split de roles, footguns de pooling/persistent-conn, bypass para ~3 tipos de jobs) que puede desestabilizar el deploy VPS recién montado.

**Recomendación:** 
1. **Ahora (Capa 3, sin ADR):** implementar el test AST anti-leak + cerrar `id`/`public_id`.
2. **Post-beta (sprint dedicado):** implementar RLS con este ADR como diseño, tras Capa 4 (`organization_id` en `InvoiceAuditLog`) y la decisión de PgBouncer (los footguns están acoplados).

No implementar RLS y PgBouncer en sprints separados sin coordinar — el footgun `SET LOCAL` los une.

---

## Tests requeridos (Fase 3)

- `test_rls_cross_tenant_select_returns_empty` — query SIN `for_organization` desde org A no ve filas de org B (el test que valida el control estructural).
- `test_rls_insert_other_org_rejected` — INSERT con `organization_id` ajeno → error de policy.
- `test_rls_guc_reset_between_requests` — request de org B no hereda GUC de org A (footgun pooling).
- `test_migrations_run_with_bypass_role` — `migrate` funciona con `vet_admin`.
- `test_analytics_job_per_org_within_rls` — `build_daily_metrics` computa correcto con GUC per-org.
- Suite completa sin regresión.

---

## Referencias

- Auditoría arquitectónica 2026-05-26 — hallazgo C3 + plan por capas (Capa 3).
- ADR p14 §92-99 — `Invoice.clean()` legacy residue; Fase 2B anticipa DB-level enforce.
- ADR p16 — cascade lockdown (FK PROTECT a nivel DB, mismo espíritu de defensa estructural).
- `core/models.py:109-112` — `TenantManager.get_queryset()` sin filtro de org.
- `DEPLOY_VPS_PLAN.md` Capa 4 — postgres data layer (donde aterriza el split de roles + PgBouncer).
- PostgreSQL docs — Row Security Policies; nota sobre superuser/BYPASSRLS/FORCE.
- Footgun conocido: PgBouncer transaction pooling + session GUC → usar `SET LOCAL`.
