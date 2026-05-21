# Anexo de Persistencia/DB — Plan Día 6

## 1. Veredicto

**Parcial-sólido.** La división `public_id` (modelos públicos) vs PK interno (sub-recursos / FK body / joins) del draft es correcta a nivel DB y no introduce regresiones de performance medibles en escala pre-beta. Los hallazgos del anexo de seguridad que promueven `VaccineRecord` y `User`/`Organization` a `public_id` son compatibles con el modelo de datos sin reescritura. Los gaps reales son: (a) ausencia de índices compuestos `(organization, public_id)` que acelerarían la query canónica, (b) decisión no documentada sobre UUID v4 vs v7 para los nuevos campos de Fase 4-5, (c) estrategia de migración aditiva no explícita en términos DB. Ninguno bloquea Día 6 si se incorporan las adiciones de §3.

## 2. Hallazgos

**H1 — División pk/public_id (LOW).** Correcta. `InvoiceItem`/`MRP`/`MRS`/`StockMovement` no necesitan `public_id` — son hijos siempre nested. `VaccineRecord` SÍ requiere promoción (anexo seguridad lo cubre). `VitalSigns` puede quedar interno porque solo se lista bajo `medical-records/<uuid>/vitals/` y es append-only.

**H2 — Índices (MEDIUM).** `PublicIdMixin` declara `unique=True, db_index=True`. El UNIQUE genera un índice B-tree global sobre `public_id`. La query canónica `for_organization(org).filter(public_id=uuid)` resuelve por el índice UNIQUE (1 lookup) y luego aplica el filtro `organization_id` en memoria sobre 1 fila — costo O(1). El índice global es suficiente. Un compuesto `(organization, public_id)` sería marginalmente mejor para list endpoints con paginación por org pero introduce un segundo índice por modelo que paga write-cost en cada INSERT. **Decisión: no agregar compuesto en Día 6** salvo en modelos con queries de listado caliente (Invoice, Appointment, MedicalRecord) — y solo si EXPLAIN ANALYZE en staging muestra ganancia.

**H3 — Uniqueness global vs per-org (LOW).** UUID v4 colisión efectiva es 2^-122; enumeration cross-tenant via collision attack no es realista. UNIQUE global simplifica `resolve_public_id` (un solo `WHERE public_id=...`), evita carrying-org en cada lookup interno, y es consistente con cómo el frontend trata el UUID como opaque token global. `unique_together=('organization','public_id')` añadiría complejidad cero beneficio. **Mantener UNIQUE global.**

**H4 — Query patterns (LOW).** `for_organization(org).filter(public_id=uuid)` en PostgreSQL usa el índice UNIQUE de `public_id` primero (selectividad máxima), no hace table scan. Validar con EXPLAIN antes de cutover. Riesgo real: el TenantManager devuelve QuerySet estándar — encadenar en orden incorrecto rompe (ADR-10).

**H5 — UUID v4 fragmentation (LOW para v1).** UUID v4 random fragmenta B-tree en inserts masivos. Con volumen pre-beta (decenas de orgs, miles de filas) el impacto es invisible. A 100x growth (millones de filas/tabla) empieza a importar para write throughput de Invoice y Appointment. **Recomendación: NO migrar v4 existentes. Para Organization.public_id y User.public_id NUEVOS de Fase 4-5, considerar UUID v7 (time-ordered) si Python 3.12+ o `uuid6`/`uuid-utils` está disponible. Si requiere dependencia nueva, quedarse en v4 — la diferencia no justifica el costo de Día 6.**

**H6 — Migración aditiva 2-pasos vs single-shot (MEDIUM).** Pre-beta, sin tráfico productivo, sin filas en escala. Single-shot con `default=uuid4` + `unique=True` corre en una sola migración. El draft propone aditiva nullable + backfill + NOT NULL como rollback insurance. **Recomendación: single-shot para `Organization` y `User` (tablas pequeñas, sin volumen)**. El argumento del draft (rollback safety) es válido en producción con datos, no aquí. Riesgo de duplicate UUIDs en backfill: nulo con `default=uuid4` aplicado fila por fila. Lock de tabla: ACCESS EXCLUSIVE breve, irrelevante en pre-beta.

**H7 — Joins internos (LOW).** El draft es explícito en §10 — FKs internas (`presentation_id`, `pet_id`, `invoice_id`) permanecen PK entero. Confirmado en código: `MedicalRecordProduct.presentation` es FK por PK, no UUID. No se toca. **Validar en code review que ningún PR de Día 6 cambie FK numéricas a UUID por error.**

**H8 — Soft-delete + public_id (LOW).** `TenantManager.get_queryset()` filtra `is_active=True`. Un objeto soft-deleted retiene `public_id` UNIQUE; nuevas filas no colisionan porque `default=uuid4` genera fresh. Queries vía UUID a objeto soft-deleted retornan 404 (esperado). Edge case: si alguien intenta "restaurar" un objeto soft-deleted vía `is_active=True` directo en DB, su `public_id` sigue siendo el original — OK. **No hay edge case bloqueante.**

**H9 — Costo de `resolve_public_id` en query params (LOW).** Cada query param resuelto es 1 SELECT por UNIQUE index, sub-milisegundo. Sin caché. Si una vista lista MR con `?pet=<uuid>&owner=<uuid>` son 2 SELECTs + el queryset principal — total 3, aceptable. **No cachear.** Cache invalidation en soft-delete sería pesadilla.

**H10 — VaccineRecord promoción (LOW).** Migración aditiva simple (campo + índice). Sin filas en escala, single-shot OK. Mismo patrón que `Organization.public_id`.

**H11 — User.username UNIQUE global (P2 #46) (informativo).** Deuda DB conocida; no scope Día 6. Si Fase 5 toca `User`, el PR puede oportunisticamente añadir constraint per-org `unique_together=('organization','username')` — **NO incluir en Día 6**, abrir ticket separado. Tocar UNIQUE de `username` requiere coordinar con SimpleJWT login que asume `username` global.

**H12 — Service.unique_together=('product','name') sin org (P2 #43) (informativo).** Mismo: deuda. Día 6 no toca Service salvo si la fase de query params lo cubre — no rompe nada.

## 3. Adiciones al plan

- **Índices**: NO agregar compuestos `(organization, public_id)` por default. Sólo si EXPLAIN ANALYZE en staging sobre `Invoice`/`Appointment`/`MedicalRecord` muestra ganancia >20% en queries con `for_organization + filter(public_id)`. Probable: no se agregan.
- **UUID version**: `Organization.public_id` y `User.public_id` (Fase 4-5) y `VaccineRecord.public_id` (refuerzo seguridad) usan `uuid.uuid4` por consistencia con el resto del codebase. UUID v7 no se adopta en Día 6 — abrir ADR separado post-beta si se materializa el problema de fragmentation.
- **Migración**: single-shot `AddField(default=uuid4) + unique=True + db_index=True` aplicado a `Organization`, `User`, `VaccineRecord`. Justificado por estado pre-beta sin datos productivos. Rollback = revert migration; sin riesgo de pérdida.
- **Uniqueness**: UNIQUE global para `public_id`. NO `unique_together` con org. Coste/beneficio negativo.
- **Validación de orden de queryset**: agregar a checklist de code review: `for_organization()` siempre primero (ADR-10), confirmar en cada vista tocada.

## 4. Lo que NO se toca pre-beta

- **PKs enteros** en todas las tablas — base de joins, FKs internas, secuencias, ordering.
- **FKs body** (`pet`, `owner`, `appointment`, `medical_record`, `product`, `presentation`) — siguen PK por `PrimaryKeyRelatedField`.
- **Migración UUID v4 → v7** retroactiva en `Pet`, `Owner`, `Appointment`, `MedicalRecord`, `Invoice`, `Prescription`, `Product`, `Presentation`, `Service` — coste alto, beneficio invisible a esta escala.
- **Reindexación masiva**, particionado, sharding, read replicas — todo fuera de scope.
- **`username` global UNIQUE** — deuda conocida, ticket aparte.
- **`Service.unique_together` sin org** — deuda conocida, ticket aparte.

## 5. Riesgos DB temporales aceptables

- **UUID v4 fragmentation** en B-tree de modelos con escritura caliente (`Invoice`, `Appointment`, `MedicalRecordProduct` si se promoviera — no se promueve). Invisible a escala v1; reevaluar a 10x growth con métricas de `pg_stat_user_indexes.idx_blks_hit`.
- **Doble identificador en response** (`id` + `public_id`) — costo serialización marginal, OK pre-beta.
- **Sin índice compuesto `(organization, public_id)`** — query plan actual es óptimo para detail lookup; sólo defer si los list endpoints muestran latencia.
- **`Organization.id` PK entero sigue visible en algunas respuestas embedidas** hasta Fase 4 — riesgo de info-leak ya cubierto por `OrganizationLegacyView` (404 si no match a JWT org).

## 6. Validación pre-cutover

Antes del flip `ALLOW_LEGACY_ID_LOOKUP=False`:

1. **EXPLAIN ANALYZE en staging** sobre las 9 queries canónicas:
   ```sql
   EXPLAIN (ANALYZE, BUFFERS)
   SELECT ... FROM <table>
   WHERE organization_id = <jwt_org> AND public_id = '<uuid>';
   ```
   Esperado: `Index Scan using <table>_public_id_key`, `Rows Removed by Filter: 0` (1 fila ya filtrada por UNIQUE), buffers shared hit < 10. Si aparece `Seq Scan` o `Filter` removiendo filas, hay regresión — abrir ticket de índice compuesto.

2. **Smoke de write-path** sobre `Invoice`, `Appointment`, `Pet` con 1000 inserts secuenciales en staging, medir tiempo promedio. Comparar con baseline pre-Día-6 (debería ser idéntico — `public_id` ya existe en estos modelos hoy).

3. **Migración de Fase 4-5 en staging** con timing: `Organization` y `User` deben completar en <1 segundo (tablas pequeñas). Si supera 10s, investigar lock contention.

4. **Verificación de duplicates post-backfill**:
   ```sql
   SELECT public_id, COUNT(*) FROM organizations_organization
   GROUP BY public_id HAVING COUNT(*) > 1;
   ```
   Esperado: 0 filas. Repetir para `auth_user` y `medical_records_vaccinerecord`.

5. **Test de regresión performance**: la suite de tests (`apps.billing.tests.test_invoice_state_machine`, `apps.medical_records.tests.test_close`) debe correr en ±10% del baseline. Una regresión de 30%+ indica problema de índice o query plan.
