# Modulo: Logs y eventos del sistema

> **Ver también:** [`docs/system-operational-flow.md`](../system-operational-flow.md) — mapa operacional cross-módulo (acciones, precondiciones, efectos, invariantes).

## Descripcion general

El sistema emite eventos estructurados en formato JSON al stdout (visible en Railway como logs del servidor).
Cada evento tiene un campo `event` con el nombre del evento y campos adicionales con contexto.

Hay varios grupos de eventos segun su origen:

- `rbac.events` — acceso y permisos (quien puede hacer que); tambien superuser bootstrap (PR-4A)
- `medical_records.events` — ciclo de vida de consultas medicas
- `apps.tenant_validation` — rechazos de tenant en serializers (PR Dia 3 / ADR p14)
- `core.deprecation` — uso de endpoints deprecados (PR-4B / ADR p16)
- `core.audit_orphan_fks` — mgmt command de integridad referencial (PR-4B)
- `billing.events` — pagos, idempotencia, mutaciones de InvoiceItem (Sprint A / ADR p27, p29)
- `cash.events` — turnos de caja, cierre Z (Sprint A / ADR p28)
- `platform.events` — provisioning cross-tenant (ADR p19)
- `analytics.events` — late arrivals, build de snapshots, anchor governance (ADR p17)

---

## Eventos de acceso y permisos (`rbac.events`)

### `RBAC_ALLOWED_DB` · INFO

El usuario hizo una accion y el sistema verifico en la base de datos que tiene permiso para hacerla. Todo funciono como debe. Este es el estado normal y saludable de la aplicacion.

Campos: `request_id`, `user_id`, `organization_id`, `role`, `endpoint`, `method`, `required_permission`

Accion requerida: ninguna.

---

### `RBAC_FALLBACK_ALLOWED` · WARNING

El usuario hizo una accion y el sistema le dio acceso, pero no porque la base de datos lo diga — sino porque el codigo tiene una lista de respaldo codificada. Ocurre cuando un usuario no tiene rol asignado en la base de datos y el sistema usa la configuracion estatica como plan B.

Por que es un warning: indica que ese usuario aun no esta completamente migrado al sistema nuevo de permisos. Mientras exista este evento, la migracion RBAC no esta terminada.

Campos: `request_id`, `user_id`, `organization_id`, `role`, `endpoint`, `method`, `required_permission`

Accion requerida: verificar que todos los usuarios tienen rol en DB (`python manage.py seed_permissions`). El gate de Fase 4 requiere que este evento desaparezca durante 7 dias consecutivos.

---

### `RBAC_DENIED` · WARNING

El usuario intento hacer algo que su rol no permite. El sistema lo bloqueo y devolvio un error 403. Puede ser algo legitimo (un asistente intentando crear algo que solo el admin puede) o puede indicar un bug en el frontend que esta llamando endpoints que no deberia.

Campos: `request_id`, `user_id`, `organization_id`, `role`, `endpoint`, `method`, `required_permission`

Accion requerida: si aparece frecuentemente para el mismo `endpoint` y `role`, revisar si hay un bug en el frontend o si falta asignar ese permiso al rol.

---

### `TENANT_MISMATCH_DETECTED` · ERROR

Un usuario autenticado intento acceder a un recurso que pertenece a otra clinica. El sistema lo bloqueo. En operacion normal esto nunca deberia ocurrir — si aparece, es un intento de acceso entre organizaciones que puede ser un bug grave o un intento malicioso.

Campos: `request_id`, `user_id`, `organization_id`, `role`, `endpoint`, `method`, `required_permission`, `resource_org` (organizacion del recurso al que se intento acceder)

Accion requerida: investigar de inmediato. Identificar el `user_id`, el `endpoint`, y el `organization_id` de ambos lados.

---

### `SUPERUSER_BOOTSTRAP_CREATED` · INFO

El signal `_create_default_superuser` (PR-4A / ADR p15) creo exitosamente un nuevo superuser de plataforma desde `DJANGO_SUPERUSER_USERNAME`/`PASSWORD`/`EMAIL`. Junto con la organizacion "Vet Care Internal" si no existia.

Campos: `event`, `username`, `user_id`, `org_id`

Accion requerida: ninguna en deploy nuevo. Si aparece en deploys subsecuentes (despues del primero), investigar — el signal deberia ser idempotente.

---

### `SUPERUSER_BOOTSTRAP_SKIPPED` · CRITICAL

Una clinica registro un usuario con el mismo `username` que `DJANGO_SUPERUSER_USERNAME`. El signal detecto que ese usuario NO es el platform-superuser legitimo (no cumple `is_superuser=True AND is_staff=True AND role='ADMIN_SAAS' AND email coincide`) y aborto sin tocar nada. Esto cierra el vector de escalacion CVSS 9.9 que permitia que el signal escalara cualquier usuario a superuser y le reseteara password.

Campos: `event`, `reason` (`username_collision_non_platform_user` o `race_condition_created_unexpected_user`), `username`, `existing_user_id`, `existing_role`, `existing_org_id`, `existing_is_superuser`, `existing_is_staff`

Accion requerida: investigar de inmediato. Cambiar `DJANGO_SUPERUSER_USERNAME` a un valor que NO colisione con usuarios de clinicas, o bien crear el platform-superuser manualmente y remover las env vars.

---

### `SUPERUSER_BOOTSTRAP_RACE_RESOLVED` · WARNING

Race condition multi-worker Railway: dos workers de `post_migrate` ejecutaron el signal en paralelo, uno gano la creacion y el otro recibio `IntegrityError`. El que perdio re-fetch el usuario creado y aplica el mismo predicado de validacion. Comportamiento esperado en deploys multi-worker.

Campos: `event`, `username`, `user_id`

Accion requerida: ninguna salvo que aparezca con frecuencia anormal.

---

### `SUPERUSER_BOOTSTRAP_INCOMPLETE_ENV` · WARNING

Solo `DJANGO_SUPERUSER_USERNAME` o solo `DJANGO_SUPERUSER_PASSWORD` esta seteado. Config Railway probablemente errónea — el signal aborta sin crear nada.

Campos: `event`, `has_username` (bool), `has_password` (bool)

Accion requerida: revisar config Railway. Setear ambas o ninguna.

---

## Eventos de validacion tenant en serializers (`apps.tenant_validation`)

### `TENANT_VALIDATION_REJECTED` · WARNING

Un serializer (PR Dia 3 / ADR p14) detecto que un campo FK referencia un objeto de otra organizacion. Diferente a `TENANT_MISMATCH_DETECTED` que es de `HybridPermission.has_object_permission` (object-level access attack). Este evento es de validacion preventiva en el serializer — un typo de UI o ID stale no debe saturar el evento de seguridad de mayor severidad.

Campos: `event`, `source` (`serializer`), `serializer` (clase), `field`, `user_id`, `user_org_id`, `resource_org_id`, `resource_pk`, `endpoint`, `method`

Accion requerida: investigar si es bug o intento — el cliente recibio 400 "Acceso invalido". Si el evento es frecuente para un mismo `endpoint`+`field`+`user`, revisar el frontend que envia IDs stale o cross-org.

---

## Eventos de endpoints deprecados (`core.deprecation`)

### `DEPRECATED_ENDPOINT_HIT` · WARNING

Un cliente uso un endpoint marcado deprecado via RFC 8594. Hoy el unico es `/api/organizations/<pk>/` (PR-4B / ADR p16) cuyo successor es `/api/organizations/me/`. Post-Sunset (2026-08-17) el endpoint responde 410 Gone automaticamente.

Campos: `event`, `endpoint`, `method`, `user_id`, `org_id`, `successor`, `sunset`

Accion requerida: monitorear adopcion frontend. Gate para corte total: 0 hits durante 7 dias consecutivos antes del Sunset.

---

## Eventos de auditoria de FKs PROTECT (`core.audit_orphan_fks`)

El mgmt command `audit_orphan_fks` (PR-4B / ADR p16) emite eventos estructurados durante el scan. Runbook: `docs/runbooks/audit_orphan_fks.md`.

### `AUDIT_ORPHAN_FKS_STARTED` · INFO

Scan iniciado. Campos: `event`, `audit_run_id`, `org_filter`, `targets`, `schema_version`.

### `AUDIT_ORPHAN_FKS_TARGET_CLEAN` · INFO

Una FK target no tiene orphans. Campos: `event`, `audit_run_id`, `child_model`, `child_fk`.

### `AUDIT_ORPHAN_FKS_TARGET_ORPHANS` · WARNING

Una FK target tiene orphans detectados. Campos: `event`, `audit_run_id`, `child_model`, `child_fk`, `parent_model`, `kind` (`dangling` o `cross_tenant`), `count`, `sample_truncated`.

Accion requerida: ejecutar manualmente con `--json-only` para detalles + seguir runbook por `kind`.

### `AUDIT_ORPHAN_FKS_TARGET_FAILED` · ERROR

Error interno auditando un target. Campos: `event`, `audit_run_id`, `child_model`, `child_fk`, `error_class`. Exit code del proceso es 2.

### `AUDIT_ORPHAN_FKS_COMPLETED` · INFO

Scan completado. Campos: `event`, `audit_run_id`, `total_orphans`, `models_with_orphans`, `scan_duration_ms`, `exit_code`.

---

## Eventos de consultas medicas (`medical_records.events`)

### `MEDICAL_RECORD_CLOSED` · INFO

Una consulta medica fue finalizada correctamente por un usuario autorizado. A partir de este momento queda bloqueada y ya no puede modificarse.

Campos: `user_id`, `organization_id`, `medical_record_id`, `endpoint`, `method`

Accion requerida: ninguna.

---

### `MEDICAL_RECORD_CLOSE_IDEMPOTENT` · INFO

Alguien intento finalizar una consulta que ya estaba cerrada. El sistema lo detecto, no hizo ningun cambio, y respondio con exito igual. Es el comportamiento esperado cuando el frontend llama el endpoint mas de una vez por error.

Campos: `user_id`, `organization_id`, `medical_record_id`, `endpoint`, `method`

Accion requerida: ninguna. Si aparece muy seguido para el mismo registro, revisar si hay un loop en el frontend.

---

### `MEDICAL_RECORD_OWNERSHIP_DENIED` · WARNING

Un veterinario intento agregar o quitar productos/servicios de una consulta que no le pertenece — fue creada por otro veterinario. El sistema lo bloqueo. Los administradores nunca generan este evento porque pueden modificar cualquier consulta.

Campos: `user_id`, `organization_id`, `medical_record_id`, `veterinarian_id` (el vet dueno de la consulta), `endpoint`, `method`

Accion requerida: si aparece seguido para el mismo veterinario, puede indicar un bug en el frontend que no esta filtrando correctamente que consultas puede editar ese vet.

---

### `MEDICAL_RECORD_CLOSED_DENIED` · WARNING

Alguien intento modificar una consulta que ya estaba cerrada. El sistema lo bloqueo. Puede ser que el frontend no actualizo el estado de la consulta en pantalla y el usuario intento editar algo que ya no era editable.

Campos: `user_id`, `organization_id`, `medical_record_id`, `veterinarian_id`, `endpoint`, `method`

Accion requerida: si aparece seguido, revisar si hay una condicion en el frontend que no refleja correctamente el estado `closed` de la consulta.

---

### `MEDICAL_RECORD_DELETED` · INFO

Una consulta medica vacia (sin diagnostico, tratamiento, notas, productos, servicios, vitales ni receta) fue eliminada correctamente. Corresponde al caso de "error de dedo" al abrir una consulta equivocada.

Campos: `user_id`, `organization_id`, `medical_record_id`, `public_id`, `endpoint`, `method`

Accion requerida: ninguna.

---

---

## Eventos de billing (`billing.events`)

### `IDEMPOTENT_PAYMENT_DEDUPED` · INFO

Un reintento de pago con el mismo `X-Idempotency-Key` fue detectado y se devolvio el resultado previo sin doble-registrar. Contrato de idempotencia (ADR p27, contract §9).

Campos: `event`, `request_id`, `idempotency_key`, `organization_id`.

Accion requerida: ninguna. Si frecuente para mismo `idempotency_key`, revisar retry logic del frontend.

---

### `INVOICEITEM_MUTATION_OUTSIDE_ATOMIC` · WARNING

Un `InvoiceItem.save()` o `.delete()` corrio fuera de `transaction.atomic()`. Observabilidad de la regla CLAUDE: toda mutacion concurrente de items debe sostener `select_for_update()` sobre la Invoice.

Campos: `event`, `item_id`, `invoice_id`, `caller`.

Accion requerida: localizar el caller y envolver en `atomic()` + lock de Invoice.

---

## Eventos de caja (`cash.events`)

ADR p28 (`2026-05-27-p28-cash-session-cierre-z.md`).

### `CASH_SESSION_OPENED` · INFO

Un usuario abrio su turno de caja.

Campos: `event`, `session_id`, `organization_id`, `opened_by`, `opening_float`.

---

### `CASH_SESSION_CLOSED` · INFO

Cierre Z normal. Incluye `difference` para reconciliacion.

Campos: `event`, `session_id`, `organization_id`, `closed_by`, `expected_cash`, `counted_cash`, `difference`.

Accion requerida: si `|difference|` excede umbral operativo, investigar.

---

### `CASH_SESSION_FORCE_CLOSED` · WARNING

Cierre administrativo (`force=True`). Usado cuando un cajero no puede cerrar su propio turno.

Campos: `event`, `session_id`, `organization_id`, `closed_by`, `actor_id`, `difference`.

Accion requerida: investigar el motivo del cierre forzado.

---

## Eventos de platform (`platform.events`)

ADR p19 (`2026-05-22-p19-platform-org-provisioning.md`).

### `PLATFORM_ORG_PROVISIONED` · INFO

Provisioning exitoso de organizacion nueva.

Campos: `event`, `request_id`, `actor_id`, `actor_username`, `actor_email`, `actor_role`, `org_id`, `org_public_id`, `org_name`, `admin_user_id`, `admin_user_public_id`, `admin_username`, `duration_ms`.

---

### `PLATFORM_ORG_PROVISION_RACE` · WARNING

`IntegrityError` post-validacion (race condition entre 2 ADMIN_SAAS provisionando la misma org simultaneamente).

Accion requerida: ninguna si esporadico; investigar si frecuente.

---

### `PLATFORM_ORG_PROVISION_RBAC_MISSING` · CRITICAL

Role `ADMIN` ausente tras correr el signal post-Organization-create. Bug en el seed de RBAC.

Accion requerida: investigar de inmediato. Revisar `seed_permissions` y los signals de `organizations`.

---

### `PLATFORM_ORG_PROVISION_POSTCOND_FAILED` · CRITICAL

Post-condicion `UserRole` no satisfecha despues del provisioning. Indica corrupcion del flujo atomic.

Accion requerida: investigar y rollback manual si aplica.

---

### `PLATFORM_ACCESS_DENIED` · WARNING

`IsPlatformOperator` rechazo un request al endpoint `/api/platform/`. Usuario no es ADMIN_SAAS legitimo.

Campos: `event`, `request_id`, `actor_id`, `actor_username`, `actor_email`, `actor_role`.

Accion requerida: si aparece en bursts desde misma IP, investigar (posible escalation attempt).

---

## Eventos de analytics (`analytics.events`)

ADR p9, p17 (`2026-05-09-p9-analytics-anchor-authority.md`, `2026-05-17-p17-analytics-correctness-day5.md`).

### `ANCHOR_LATE_ARRIVAL` · WARNING

Un anchor (`paid_at`, `confirmed_at`, `cancelled_at`, `closed_at`) cayo en un bucket ya frozen (threshold T+2 dias para clase `clinical`/`financial`). Warn-only en Dia 5; hard reject planificado para Dia 7+.

Campos: `event='ANCHOR_LATE_ARRIVAL'`, `anchor_field`, `anchor_value_iso`, `bucket_date_local_iso`, `frozen_threshold_days`, `age_days`, `organization_id`, `writer`, `metric_class`.

Accion requerida: si frecuente, revisar latencia operativa (consultas que se cierran dias despues, pagos retroactivos).

---

### `DASH_BUILD_RUN_STARTED` / `DASH_BUILD_RUN_COMPLETED` · INFO

Ciclo de vida del mgmt command `build_daily_metrics` (cron nightly).

Campos: `event`, `run_id`, `orgs_processed`, `orgs_locked_busy`, `orgs_failed`, `snapshots_built`, `snapshots_skipped_today`, `duration_seconds`.

---

### `DASH_BUILD_ORG_STARTED` / `DASH_BUILD_ORG_COMPLETED` / `DASH_BUILD_ORG_FAILED` · INFO/ERROR

Per-org isolation del build. Un org fallido no aborta otros.

Campos: `event`, `run_id`, `organization_id`, `duration_ms` (en COMPLETED), `error_class`+`stacktrace` (en FAILED).

Accion requerida: investigar cualquier `ORG_FAILED`.

---

### `DASH_BUILD_LOCK_BUSY` · WARNING

PG advisory lock contendido. Otro proceso esta construyendo metrics para esa org. Org saltada en esta corrida.

Campos: `event`, `run_id`, `organization_id`.

Accion requerida: ninguna si esporadico (deploy multi-worker). Investigar si persistente.

---

### `DASH_SNAPSHOT_BUILT` / `DASH_SNAPSHOT_NO_CHANGE` · INFO

Resultado del `apply_snapshot` por (org, date). `NO_CHANGE` confirma idempotencia.

---

### `DASH_SNAPSHOT_CORRUPT` · ERROR

Snapshot con `excluded_anchor_missing > 0`. Persistido como `lifecycle_state='corrupt'`, filtrado en view layer.

Accion requerida: investigar `audit_anchor_integrity` para encontrar el modelo con anchor faltante.

---

## Regla practica para monitorear en Railway

Filtrar el stdout por nombre de evento:

| Que buscar | Frecuencia esperada | Que significa si aparece |
|---|---|---|
| `TENANT_MISMATCH_DETECTED` | Nunca | Prioridad inmediata — posible incidente de seguridad |
| `SUPERUSER_BOOTSTRAP_SKIPPED` | Nunca despues del deploy inicial | Posible colision con usuario de clinica — investigar |
| `RBAC_FALLBACK_ALLOWED` | Decrece hasta cero | Usuarios sin rol en DB — correr `seed_permissions` |
| `RBAC_DENIED` | Bajo, ocasional | Permisos mal configurados o bug en frontend |
| `TENANT_VALIDATION_REJECTED` | Bajo, ocasional | Typo UI / ID stale; si frecuente revisar frontend |
| `DEPRECATED_ENDPOINT_HIT` | Decrece hasta cero antes de 2026-08-17 | Frontend aun usa `/api/organizations/<pk>/`; migrar a `/me/` |
| `AUDIT_ORPHAN_FKS_TARGET_ORPHANS` | Nunca | Integridad referencial rota — seguir runbook |
| `RBAC_ALLOWED_DB` | La mayoria de requests | Estado normal |
| `MEDICAL_RECORD_DELETED` | Bajo, ocasional | Normal — registro vacio eliminado por error |
| `PLATFORM_ORG_PROVISION_*` (CRITICAL) | Nunca | Bug en seed RBAC o atomic flow — investigar de inmediato |
| `PLATFORM_ACCESS_DENIED` | Nunca para ADMIN_SAAS legitimo | Posible escalation attempt si bursts |
| `INVOICEITEM_MUTATION_OUTSIDE_ATOMIC` | Nunca | Caller bypaseo lock de Invoice — localizar y envolver en atomic() |
| `CASH_SESSION_FORCE_CLOSED` | Bajo | Cierre administrativo — investigar motivo |
| `ANCHOR_LATE_ARRIVAL` | Bajo | Anchor en bucket frozen; warn-only Dia 5 |
| `DASH_SNAPSHOT_CORRUPT` | Nunca | excluded_anchor_missing > 0 — correr audit_anchor_integrity |
| `IDEMPOTENT_PAYMENT_DEDUPED` | Bajo | Retry de cobro funcionando como debe |

El `request_id` presente en todos los eventos de `rbac.events` permite agrupar multiples eventos del mismo request HTTP para reconstruir que paso exactamente en una solicitud especifica.
