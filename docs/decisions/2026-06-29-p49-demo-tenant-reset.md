# ADR p49 — Reset automático del tenant DEMO (tenant-scoped, no pg_dump global)

**Fecha:** 2026-06-29
**Estado:** ✅ **Implementado** (2026-06-29, branch `develop`). Diseño aprobado +
implementación completa: 8/8 tests verde (`apps.core.tests.test_demo_reset`),
`manage.py check` limpio, sin migraciones. Este documento es la referencia.
**Branch:** `develop`
**Origen:** La demo del SaaS (una `Organization` real marcada `is_demo=True`) será
usada por visitantes de la landing y debe volver a su estado inicial cada 30 minutos.
La idea inicial —restaurar un `pg_dump` completo cada 30 min— es **inaceptable** en un
multi-tenant en producción: revertiría TODAS las organizaciones, con pérdida de datos de
clínicas reales. Este ADR define un **reset acotado al tenant demo**, reutilizando el
mecanismo ya existente (`seed_demo_clinic --reset`) en lugar de crear un sistema paralelo.

> Investigación de soporte: análisis de arquitectura multitenant + grafo de dependencias
> FK + clasificación de modelos (sesión de diseño 2026-06-29). El propio runbook ya preveía
> esto: `docs/runbooks/demo-seed.md` §8 — *"Reset automático … (cron) = post-beta, cuando el
> seed esté rodado."*

---

## 1. Decisión

Resetear **solo** el tenant `is_demo=True` mediante el comando existente
`python manage.py seed_demo_clinic --reset --yes`, **endurecido** con: (a) cierre del hueco
P0 de analytics en el orden de purge, (b) exclusión mutua por advisory lock, (c) una sola
transacción purge+rebuild, (d) ventana de mantenimiento solo-escritura para visitantes,
(e) verificación automática post-reset reutilizando las auditorías existentes, y (f) un
procedimiento operativo de recuperación.

**Alcance: una sola demo.** No se introduce `demo_slug` ni soporte multi-demo. **Cero
cambios de esquema** (sin migraciones): todo el diseño es lógica de purge, runtime
(advisory lock), cache (flag de mantenimiento), permiso, cron y ops.

La autoridad de destrucción es exclusivamente `Organization.is_demo`
(`backend/apps/organizations/models.py:32`), **nunca** el nombre. El guard existente aborta
si hay 0 o >1 organizaciones demo (`seed_demo_clinic.py:121`) y exige `--yes`.

---

## 2. Contexto (hallazgos de investigación)

### 2.1 Multitenancy
- Todos los modelos de dominio heredan `OrganizationalModel`
  (`backend/apps/core/models.py:125`) → **todos llevan `organization` FK** (`PROTECT`) →
  todos son filtrables por tenant.
- `objects` (TenantManager) filtra `is_active=True`; `for_organization(org)` añade el filtro
  de tenant. `TenantQuerySet.delete()` está **bloqueado** por defecto (`core/models.py:83`)
  → el borrado físico usa `all_objects` (Manager plano), cuyo `.delete()` ejecuta el
  cascade + enforcement de `PROTECT` estándar de Django.
- **No hay RLS activo** (ADR p23 diferido). El aislamiento es a nivel aplicación: cada
  `.delete()` del purge filtra `organization=demo_org`.

### 2.2 La demo NO es read-only
El único guard demo, `NotDemoAccount` (`backend/apps/core/permissions.py:567`), bloquea
**solo** cambio de contraseña e importación. Todo lo demás (pagos, devoluciones, caja,
consultas) es **escribible** por los usuarios demo (credenciales compartidas). Implica
concurrencia real de escritura durante el reset y la posibilidad de que un visitante emita
una devolución.

### 2.3 Mecanismo existente
`seed_demo_clinic` (`backend/apps/core/management/commands/seed_demo_clinic.py`) ya:
- crea la demo vía `provision_organization` (org + admin + settings + genéricos + roles);
- reconstruye reusando servicios autoritativos (`apply_stock_movement`, `billing.services`,
  `MedicalRecordProduct.save`), con backdating de fechas como única escritura directa;
- purga en `_purge` (`:564`) en orden FK-seguro, conservando org/usuarios/genéricos en
  `--reset` (`full=False`).

### 2.4 Hueco P0 confirmado
`_purge` **no borra `analytics.MetricAdjustment`**, cuyo campo `source_invoice` es
`on_delete=PROTECT` (`backend/apps/analytics/models.py:164`). Lo crea `process_refund`
(`backend/apps/billing/services.py:553`, `_write_metric_adjustment(..., source_invoice=invoice)`).
Si un visitante demo emite una devolución, el `DELETE` de `Invoice` lanzará `ProtectedError`
→ rollback total → **la demo deja de resetearse**. En una demo pública escribible es cuestión
de tiempo. Este ADR lo cierra (§5).

---

## 3. Alcance y no-objetivos

**En alcance:** reset de la única org `is_demo=True` cada 30 min, sin afectar a ninguna otra
organización; recuperación ante fallo; comportamiento definido para visitantes.

**Fuera de alcance (futuro, §13):** múltiples demos (ES/EN/Enterprise/LATAM); blue-green sin
ventana; exclusión de `is_demo` de los analytics SaaS-wide; auto-login/botón "Entrar a la demo".

**No-objetivo explícito:** no se diseña hoy para N demos. Si surgen, se evaluará una evolución
específica. No se introducen campos de esquema especulativos.

---

## 4. Qué se elimina y qué se conserva

### 4.1 SE CONSERVA (identidad del tenant — no se toca en `--reset`)
- `organizations.Organization` (la fila demo), `OrganizationSettings`, `OrganizationTimezoneAudit`.
- Los 3 `users.User` demo + sus `core.Role` / `core.UserRole` / `legal.LegalAcceptance`.
- `patients.Owner` y `patients.Pet` **genéricos** (`is_generic=True`) — constraint único
  parcial por org (`patients/models.py:38`).
- Catálogos globales: `core.Permission`, `legal.LegalDocument`.

### 4.2 SE ELIMINA (datos operativos)
patients no-genéricos · appointments (+`AppointmentStatusChange`) · medical_records
(+services/products/`VitalSigns`/`VaccineRecord`) · prescriptions (+items) · inventory
(`Product`/`Presentation`/`StockMovement`) · billing completo (`Service`/`Invoice`/
`InvoiceItem`/`Payment`/`InvoiceAuditLog`†/`ExternalPrescriptionAttestation`/`CreditNote`/
`CreditNoteItem`/`RefundPayment`/`RefundReversal`) · cash (`CashSession`/`CashMovement`) ·
**analytics (`DailyOrgMetrics`, `DashboardSnapshotAudit`, `MetricAdjustment`)** ‡ ·
`imports.ImportJob` ‡.

† `InvoiceAuditLog` no es `OrganizationalModel` (sin `organization`); se borra por **cascade**
al borrar `Invoice` (FK `CASCADE`, `billing/models.py:373`).
‡ **Adiciones de este ADR** respecto al `_purge` actual (ver §5, cierre del P0).

> Append-only no bloquea el borrado: la inmutabilidad de `Payment`, `VitalSigns`, etc. se
> enforce en la capa de API/servicios (sin endpoint DELETE), **no** en el modelo ni en la DB.
> `all_objects.delete()` los borra físicamente; el reset destruye el subgrafo operativo
> completo del tenant, no edita ni "des-asienta" eventos → no viola el invariante append-only.

---

## 5. Orden definitivo del purge (con cierre del P0)

Verificado contra los `on_delete` reales del código. Lo nuevo respecto al `_purge` actual va
marcado ★. Todo dentro de la transacción única (§6), con `all_objects.filter(organization=demo_org)`:

```
 1. Payment                              (PROTECT → Invoice, CashSession)
 2. RefundReversal → RefundPayment → CreditNoteItem → CreditNote
 3. ExternalPrescriptionAttestation      (PROTECT → Invoice, Presentation)
 4. ★ MetricAdjustment                   (PROTECT → Invoice)  ← cierra P0; DEBE ir antes de Invoice
 5. StockMovement
 6. MedicalRecordProduct                 (PROTECT → Presentation)
 7. InvoiceItem → Invoice                (cascade borra InvoiceAuditLog)
 8. MedicalRecordService                 (PROTECT → Service)
 9. VitalSigns / VaccineRecord
10. PrescriptionItem → Prescription
11. MedicalRecord                        (PROTECT → Pet)
12. AppointmentStatusChange → Appointment (PROTECT → Pet)
13. CashMovement → CashSession
14. ★ DailyOrgMetrics, DashboardSnapshotAudit   ← limpieza analytics (evita snapshots fantasma)
15. ★ ImportJob
16. Presentation → Product → Service
17. Pet(is_generic=False) → Owner(is_generic=False)

REBUILD (misma transacción): catálogo → personas → operaciones, reusando los servicios
autoritativos + backdating de fechas (única escritura directa permitida).
```

**Invariante de regresión (§12.7):** todo modelo `OrganizationalModel` con FK al subgrafo
operativo demo debe estar cubierto por este orden. Un modelo nuevo no cubierto reintroduce el
patrón del P0.

---

## 6. Estrategia transaccional (decisión aprobada: una sola transacción; tiempos = estimación, validación posterior)

### 6.1 Tiempos — estimación analítica + medición real (prod)
No se exige benchmark como requisito bloqueante: hoy no hay un entorno representativo para
medir con la carga real de producción sin riesgo. Se documenta explícitamente:

- **Los tiempos aquí son estimaciones analíticas**, derivadas del conteo de operaciones del
  comando, no mediciones reales.
- **Deberán validarse posteriormente** cuando exista un entorno adecuado de medición.
- **Si durante la implementación o las primeras ejecuciones se detectan tiempos
  significativamente superiores a lo esperado, la estrategia transaccional podrá
  reevaluarse** (ver §6.4).

Conteo (de `seed_demo_clinic.py`): purge ≈ 20 `DELETE` masivos (no por-fila) → **< 1 s**;
rebuild ≈ **1.8–2k** round-trips (≈50 con `select_for_update`, mayoría con `full_clean`) →
**~3–30 s** estimado; **proceso completo estimado < ~30 s**.

**Medición real (prod, 2026-06-30):** purge **369 ms** · rebuild **12.8 s** · total
**~13.2 s** (`seed_demo_clinic --reset`, org demo id=2 en el VPS). Confirma la
estimación y valida la transacción única: ~13 s vs ventana de 30 min (1800 s) =
**~135× de margen**, y el TTL del flag de mantenimiento (120 s) queda holgado sobre
los 13 s. **Benchmark cerrado** — no requiere reevaluación (§6.4).

**La arquitectura no depende de si el reset tarda 4, 8 o 15 segundos.** Lo relevante es que
permanezca dentro de un orden de magnitud razonable para una ejecución cada 30 min (margen
de ~60–600×). La decisión de diseño es robusta en todo ese rango.

### 6.2 Decisión (aprobada): una sola `transaction.atomic` (purge + rebuild)

Es la estrategia **elegida** para este ADR, no una recomendación pendiente. Razones:
1. **MVCC oculta el estado intermedio:** otras conexiones ven el estado **pre-reset** hasta
   el `COMMIT` y el **post-reset** después. Los visitantes nunca ven una clínica vacía o a
   medio poblar. Elimina la "ventana parcial" sin maquinaria extra.
2. **Crash-safety:** muerte a mitad → `ROLLBACK` total → demo intacta en su último estado
   bueno. Imposible un estado a medio borrar. (La alternativa por fases —purge atómico +
   rebuild fuera— NO da esto: una muerte entre fases deja la demo vacía hasta el siguiente
   ciclo.)
3. **Compatibilidad verificada:** los `transaction.atomic` internos del seed se vuelven
   savepoints anidados; `apply_stock_movement` y `MedicalRecordProduct.save` exigen
   `connection.in_atomic_block` → satisfecho por la transacción externa.
4. **Costo aceptable:** una transacción de orden de segundos cada 30 min → bloat MVCC
   despreciable (autovacuum lo absorbe).

Los `DELETE` de analytics añadidos (§5) y el wrap externo son delta despreciable de tiempo.

**Decisión consciente, no absoluta:** la estrategia de una única transacción se considera
adecuada para el tamaño esperado de la demo y la cadencia de 30 minutos. Si durante la
operación se observan tiempos significativamente superiores a los esperados o contención
relevante, este ADR podrá revisarse (§6.4) **sin invalidar el resto del diseño**.

### 6.3 Instrumentación para la validación posterior (parte del diseño)
El comando debe **loguear su propia duración** (purge, rebuild, total) en cada corrida. Así
las primeras ejecuciones en producción aportan los números reales sin necesidad de un
benchmark dedicado, y alimentan el trigger de reevaluación.

### 6.4 Trigger de reevaluación
Reabrir la estrategia transaccional si, con datos reales, el reset:
- se acerca a una fracción no trivial de la ventana de 30 min (p. ej. > ~2–3 min sostenido), o
- provoca síntomas de contención (deadlocks, `lock_timeout`, errores 503 de mantenimiento
  más allá del TTL), o
- excede de forma significativa y sostenida la estimación de §6.1.
Caminos de escalada: dividir en fases con la ventana de mantenimiento como cobertura, o
blue-green de tenant (§13).

---

## 7. Exclusión mutua

`pg_try_advisory_xact_lock(<NS>, <DEMO_KEY>)` como **primera** sentencia de la transacción del
reset:
- **`xact`** (transaccional): se libera automáticamente al terminar la transacción —commit,
  rollback **o caída del proceso/conexión**. Resuelve "el proceso muere a mitad".
- **`try_`** (no bloqueante): si otro reset tiene el lock → devuelve `false` → el comando sale
  limpio (exit 0, log `DEMO_RESET_SKIPPED_LOCKED`). **No se encolan resets.**
- **Clave constante** (una sola demo). Si en el futuro hay varias demos, la clave se
  parametriza entonces (§13) — no ahora.

Garantía: **≤ 1 reset a la vez**. Cubre los tres escenarios:
- **Dos cron casi simultáneos** → el segundo hace skip.
- **Manual mientras corre el cron** → el manual hace skip (o el operador confirma que no hay
  cron activo antes de forzar).
- **Retry tras fallo** → el rollback ya liberó el lock → el retry adquiere limpio y
  reconstruye desde cero (idempotente por reconstrucción total determinística,
  `random.Random(1808)` + claves `legacy_id`/`internal_code`).

El advisory lock serializa resets **entre sí**; no protege contra escrituras de visitantes —
eso lo cubre §9.

---

## 8. Recuperación ante fallo (nivel transacción)

`ROLLBACK` automático → demo en su último estado bueno, jamás a medio borrar. Advisory lock
`xact` liberado al abortar → el siguiente cron reintenta limpio. Reconstrucción total
determinística ⇒ idempotente: no hay estado acumulado entre intentos. (Procedimiento
operativo cuando el fallo es recurrente: §12.)

---

## 9. Comportamiento de visitantes durante el reset — decisión explícita

**Decisión: ventana de mantenimiento acotada, solo-escritura, scoped a la demo. Las lecturas
no se afectan.** No es un "error transitorio implícito"; es un contrato definido.

| Aspecto | Comportamiento |
|---|---|
| **Lecturas (GET/HEAD)** de la demo | **Pasan normal.** Vía MVCC ven pre-reset hasta el commit, luego post-reset. La demo nunca "se cae" visualmente. |
| **Escrituras (POST/PATCH/PUT/DELETE)** de la demo durante la ventana | **`503` + header `Retry-After`**, body `{code:'demo_resetting', message:'La demo se está reiniciando, vuelve a intentar en unos segundos.'}`. No se encolan ni bloquean en locks. |
| **Tenants reales** | **Jamás afectados** (gate `is_demo`). Sin `503`, sin ventana. |

**Mecanismo (sin esquema):**
- Flag en cache (Redis, ADR p41): `demo_reset:in_progress`, con **TTL = duración máxima
  esperada del reset + margen** (estimación inicial ~90 s; se ajusta con los datos reales de
  §6.3). El TTL es la red de seguridad: si el proceso muere, el flag expira solo → la demo
  nunca queda permanentemente en mantenimiento.
- Se **setea** tras adquirir el advisory lock, antes del purge; se **limpia** al terminar
  (`transaction.on_commit` + `finally`).
- Guard liviano: `is_demo` + método unsafe + flag presente → `503`. Reutiliza el patrón de
  `NotDemoAccount` (`core/permissions.py:567`); no inventa otro mecanismo.
- Frontend: el `503 + Retry-After` ya es autoexplicativo; mostrar el mensaje en el interceptor
  axios es opcional (no requerido para v1).

**Por qué esta y no otras:** *esperar locks* → tiempos impredecibles, riesgo de
`lock_timeout`/deadlock en la transacción del visitante; *reintento client-side puro* →
trabajo de frontend que no resuelve el conflicto de raíz; *blue-green* → futuro, complejidad
innecesaria a este volumen.

---

## 10. Comportamiento del cron

- Invocación: `seed_demo_clinic --reset --yes` vía `docker compose ... run --rm backend ...`
  (patrón de `docs/runbooks/cron-jobs.md` §8).
- Cadencia: cada 30 min, **programado fuera** de la ventana de backup (21:00 MX,
  `cron-jobs.md` 6.1) y del snapshot nightly (06:30 MX, 6.3).
- Si el advisory lock está tomado → exit 0 "skipped" (no es error, no dispara alerta).
- **Deadman check propio en Healthchecks.io** (ping solo en éxito): si la demo deja de
  resetearse, alerta. (Patrón `cron-jobs.md` §6.)
- **No** encadenar `build_daily_metrics` cada 30 min (solo procesa días pasados; hoy es live).
  El histórico de analytics de la demo se trata como decisión aparte (§13 / abierto).

---

## 11. Validación posterior, criterios de éxito y verificación automática

### 11.1 Validación inline (pre-commit, barata)
Conteos esperados dentro de tolerancia (referencia `docs/runbooks/demo-seed.md`):
`owners=40, pets=65, services=8, products=18, appointments≈80, medical_records≈50,
invoices≈65, payments≈49, cash_sessions=1`. Si no cuadran → `raise` → `ROLLBACK` (reset
fallido, demo intacta).

### 11.2 Verificación automática post-commit (reutilizar auditorías existentes)
Las tres auditorías aceptan `--org=<id>` con exit-code gate (confirmado en código; diseñadas
para fan-out por tenant en cron):
- `python manage.py audit_stock_integrity --org=<demo_id>`
- `python manage.py audit_anchor_integrity --org=<demo_id> --json`
- `python manage.py audit_payment_ledger_integrity --org=<demo_id>`

`exit 0` en las tres = demo consistente. **Decisión endosada por el Product Owner: reutilizar
estas auditorías en lugar de crear nuevos mecanismos de validación.**

> Nota de plataforma: `audit_anchor_integrity` en modo no-json puede lanzar
> `UnicodeEncodeError` al imprimir `✓` en consolas Windows cp1252 (no es fallo de datos);
> usar `--json` o `PYTHONIOENCODING=utf-8`. En el VPS (UTF-8) no ocurre.

### 11.3 Criterios de "reset exitoso"
`COMMIT` aplicado **Y** advisory lock fue adquirido (no skip) **Y** conteos inline dentro de
tolerancia **Y** las 3 auditorías `--org` salen exit 0. Solo entonces el cron hace ping al
deadman. Cualquier auditoría ≠ 0 → alerta: la demo quedó commiteada pero inconsistente
(incidente a revisar; el siguiente ciclo intenta corregir).

---

## 12. Procedimiento operativo de recuperación (runbook)

**Severidad: baja.** El gate `is_demo` garantiza que **ninguna clínica real se ve afectada**.
Una demo congelada (sin resetear) no pone en riesgo datos reales mientras se diagnostica.

**Disparadores:** deadman de Healthchecks.io sin ping de éxito, o auditoría `--org` con exit ≠ 0.

1. **Deshabilitar el cron del reset.** `crontab -e` → comentar la línea del reset demo;
   verificar con `crontab -l`. (Detiene el bucle de fallos cada 30 min.)
2. **Limpiar flag de mantenimiento huérfano** si quedó puesto (corrida muerta antes del TTL):
   borrar la clave `demo_reset:in_progress` en Redis → la demo deja de rechazar escrituras.
3. **Reset manual con salida capturada:**
   `docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend python manage.py seed_demo_clinic --reset --yes`
   Leer el error. Sospechoso #1: `ProtectedError` por un modelo nuevo con FK a algo purgado no
   incluido en el orden (§5) — el patrón del P0.
4. **Si el reset manual tiene éxito → verificar consistencia** con las 3 auditorías `--org`
   (§11.2) y confirmar conteos (§11.1).
5. **Si el reset manual falla →** la transacción hizo `ROLLBACK` (demo intacta). Triar el
   bloqueador, corregir el orden de purge, **probar en staging** antes de tocar prod. La demo
   queda congelada hasta el fix (severidad baja, sin impacto real).
6. **Rehabilitar el cron.** Restaurar la línea; confirmar que el siguiente disparo hace ping al
   deadman.
7. **Post-incidente.** Registrar en el log de incidentes. Si faltaba un modelo en el purge,
   añadir la verificación de regresión del §12.7.

---

## 13. Riesgos y su tratamiento

| ID | Riesgo | Tratamiento en este ADR |
|---|---|---|
| P0-1 | `MetricAdjustment` no purgado → `ProtectedError` bloquea el reset | **Resuelto** — añadido al orden (§5, paso 4). |
| P1-1 | `pg_dump restore` global revierte tenants reales | **Evitado por diseño** — reset acotado a `is_demo`. |
| P1-2 | Resolver la demo por nombre en vez del flag | **Invariante** — solo `is_demo`; abort si ≠ 1 (§1). |
| P2-1 | Ventana de demo parcial visible | **Resuelto** — transacción única + MVCC (§6.2). |
| P2-2 | Escritura de visitante choca durante el reset | **Definido** — ventana de mantenimiento solo-escritura (§9). |
| P2-3 | Snapshots de analytics fantasma | **Mitigado** — purga de `DailyOrgMetrics`/`DashboardSnapshotAudit` (§5). Histórico = §13.fut. |
| P2-4 | Disparos solapados sin serializar | **Resuelto** — advisory lock `xact` no bloqueante (§7). |
| P2-6 | Falta deadman para el nuevo cron | **Resuelto** — Healthchecks propio (§10). |
| P3-1 | `--delete` (full) roto por PROTECT (`LegalAcceptance`/analytics) | **Fuera de alcance** — el cron usa `--reset`, no `--delete`. Latente; corregir aparte. |
| P3-2 | `ImportJob` no purgado | **Resuelto** — añadido (§5, paso 15). Riesgo base bajo (import deshabilitado en demo). |

### Futuro (no se implementa ahora)
- **Blue-green de tenant:** construir la nueva demo en un tenant aparte y voltear el puntero
  atómicamente → cero contención y cero ventana de mantenimiento. Requiere un selector que
  tolere 2 orgs transitorias y resolver el constraint de correo único global
  (`user_email_ci_unique`, ADR p48). Escalada si el volumen de escritura concurrente lo exige.
- **Multi-demo (ES/EN/Enterprise/LATAM):** parametrizar la clave del advisory lock + el dataset
  por variante. Evolución específica cuando exista el requerimiento.
- **Exclusión de `is_demo` de analytics SaaS-wide** (`demo-seed.md` §8) — decisión aparte.

---

## 14. Checklist de implementación (guía; sin código en este ADR)

1. **Purge:** añadir `MetricAdjustment` (antes de `Invoice`), `DailyOrgMetrics`,
   `DashboardSnapshotAudit`, `ImportJob` al orden de `_purge` (§5).
2. **Exclusión mutua:** `pg_try_advisory_xact_lock` al inicio de la transacción del reset;
   skip limpio + log si no se adquiere (§7).
3. **Transacción única:** envolver purge + rebuild en una sola `transaction.atomic` (§6.2);
   loguear duración de purge/rebuild/total (§6.3).
4. **Ventana de mantenimiento:** flag de cache `demo_reset:in_progress` con TTL; guard
   `is_demo` + método unsafe + flag → `503 + Retry-After` (§9).
5. **Validación:** conteos inline pre-commit (§11.1); wrapper del cron que encadena las 3
   auditorías `--org=<demo_id>` y trata exit ≠ 0 como fallo de verificación (§11.2).
6. **Cron + alerting:** entrada de crontab cada 30 min fuera de ventanas; deadman de
   Healthchecks con ping solo en éxito (§10).
7. **Regresión:** test que falle si un modelo `OrganizationalModel` con FK al subgrafo
   operativo demo no está cubierto por el orden de purge (§5 invariante).
8. **Tests de negocio:** reset idempotente; guard `is_demo` (no toca orgs reales); reset tras
   una devolución (no `ProtectedError`); ventana de mantenimiento (503 en write demo / 200 en
   read demo / sin efecto en tenant real).
9. **Docs:** actualizar `docs/runbooks/demo-seed.md` (sección de reset automático) y
   `docs/runbooks/cron-jobs.md` (nuevo job 6.x + su deadman).

---

## 15. Consecuencias

**Positivas:** la demo vuelve a su estado inicial cada 30 min sin tocar a ninguna clínica
real; un reset roto es incidente de baja severidad y recuperable por runbook; sin esquema
nuevo; reutiliza el comando, los servicios y las auditorías existentes (no hay segundo
sistema). 

**Costos / trade-offs:** una transacción de orden de segundos cada 30 min (bloat MVCC
despreciable); una breve ventana de mantenimiento solo-escritura para visitantes de la demo
(lecturas intactas); el histórico de analytics de la demo se simplifica (se purgan snapshots;
la curva histórica se trata como decisión aparte). La estrategia transaccional es robusta al
rango de tiempos estimado y se reevaluará solo si los datos reales se salen del orden de
magnitud previsto (§6.4).
