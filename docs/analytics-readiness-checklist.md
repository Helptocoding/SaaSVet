# Analytics readiness checklist

Version: 1.0
Owner: Backend / Data
Status: Activo
Última actualización: 2026-09-07
Contratos relacionados: [modelo de eventos financieros](financial-event-model-contract.md), [Billing](modules/billing.md) y [auditoría de regresión Checkout/Billing](audits/2026-09-05-checkout-billing-regression-audit.md).

Este documento es el gate operativo entre los writers transaccionales y los snapshots de Analytics. Sustituye el borrador de mayo de 2026 que todavía dependía del lifecycle `draft/confirmed/cancelled` de Invoice.

## 1. Anchors autoritativos

Analytics debe agrupar por el instante del evento de dominio, nunca por `created_at` o `updated_at` como fallback silencioso.

| Métrica | Anchor | Filtro de dominio | Writer autoritativo |
|---|---|---|---|
| `revenue_paid` | `Invoice.paid_at` | `status = paid` | `post_checkout(..., pay=True)` o `pay_invoice` |
| `invoices_paid_count` | `Invoice.paid_at` | `status = paid` | los mismos writers de pago |
| `revenue_accrual` | `Invoice.posted_at` | `status IN (posted, paid)` | `post_checkout` |
| Procedencia de void | `Invoice.voided_at` | `status = voided` | `void_invoice_terminal` / reemplazo protegido |
| `appointments_*` | `Appointment.start_datetime` | según status operativo | flujo de Appointment |
| `medical_records_closed` | `MedicalRecord.closed_at` | `status = closed` | cierre autoritativo de MedicalRecord |

El runtime no reconoce `Invoice.confirmed_at`, `Invoice.confirmed_at_source`, `Invoice.cancelled_at` ni los estados `confirmed`/`cancelled`. Ninguna consulta, snapshot, exportación o KPI nuevo puede reintroducirlos como anchors.

## 2. Invariantes de integridad

Antes de construir o servir métricas financieras se debe comprobar:

- toda Invoice tiene `posted_at` y `posted_at_source` resoluble;
- `status = paid` implica `paid_at IS NOT NULL`;
- `status = voided` implica `voided_at IS NOT NULL`;
- `MedicalRecord.status = closed` implica `closed_at IS NOT NULL`;
- no existen columnas, constraints, defaults o índices del lifecycle legacy en `billing_invoice`;
- el estado de migrations de Django y el schema físico de PostgreSQL convergen.

Gates ejecutables:

```powershell
python manage.py audit_billing_schema --json
python manage.py audit_anchor_integrity --json
```

Para un despliegue sano, `audit_billing_schema` debe reportar `ok: true` y cero violaciones. `audit_anchor_integrity` debe terminar con código `0`; código `1` indica procedencia sin resolver y código `2`, violación de invariantes.

La reconciliación y el procedimiento de diagnóstico están documentados en [Billing schema reconciliation](runbooks/billing-schema-reconciliation.md).

## 3. Índices mínimos

Verificar en PostgreSQL, no solamente en el state de Django:

| Tabla | Índice lógico requerido | Uso |
|---|---|---|
| `billing_invoice` | `(organization_id, status, paid_at)` | cash basis |
| `billing_invoice` | `(organization_id, status, posted_at)` | accrual basis |
| `billing_invoice` | `(organization_id, appointment_id)` | conversión por cita |
| `billing_invoice` | `(organization_id, medical_record_id)` | conversión clínica |
| `appointments_appointment` | `(organization_id, start_datetime)` | actividad operativa |
| `medical_records_medicalrecord` | `(organization_id, status, closed_at)` | cierres clínicos |
| `analytics_dailyorgmetrics` | unicidad `(organization_id, date)` | snapshot diario |

Las tuplas se validan por columnas y orden; el nombre físico puede variar entre una migración histórica y una instalación limpia.

## 4. Contrato de snapshots

`DailyOrgMetrics` contiene los siete KPI de v1:

- `revenue_paid`;
- `revenue_accrual`;
- `invoices_paid_count`;
- `appointments_total`;
- `appointments_done`;
- `appointments_no_show`;
- `medical_records_closed`.

Cada fila también conserva:

- `org_timezone_at_snapshot`;
- `metrics_schema_version`;
- `lifecycle_state` (`provisional`, `frozen`, `rebuilt` o `corrupt`);
- `built_at`;
- `excluded_anchor_missing`;
- `build_warnings_count`;
- `provenance_mix` con claves `paid_at`, `posted_at` y `closed_at`.

`compute_daily_metrics` sólo calcula; `apply_snapshot` persiste el resultado y su auditoría. `DashboardSnapshotAudit` registra la transición y `MetricAdjustment` representa ajustes fuera de la ventana mutable. No se debe mutar una fila congelada sin el flujo explícito de rebuild/adjustment.

## 5. Bucketing, procedencia y late arrivals

- El día se calcula en la zona horaria de la organización y se traduce a límites UTC.
- La zona utilizada se congela en `org_timezone_at_snapshot`; cambiar la configuración futura no debe reinterpretar snapshots pasados.
- Los campos `*_at_source` son trazabilidad, no sustitutos del anchor.
- Un anchor ausente se excluye y se contabiliza en `excluded_anchor_missing`; nunca se rellena silenciosamente con `created_at`.
- Un evento tardío contra un bucket congelado requiere el flujo explícito de adjustment/rebuild y evidencia en `DashboardSnapshotAudit`.

## 6. Aislamiento y visibilidad

- Toda consulta y todo job se filtran por `organization_id`.
- Los tests deben usar al menos dos organizaciones y demostrar que no hay lectura ni escritura cruzada.
- Toda cache key incluye organización. La cache actual de summary se limita a
  `SUMMARY_CACHE_PREFIX:{org_id}`; si se cachean series/rangos en el futuro,
  también deberán incluir zona horaria, rango, versión del schema y variante.
- Analytics puede incluir evidencia histórica soft-deleted cuando el contrato de la métrica lo requiera; las APIs operativas continúan usando la visibilidad normal. Esta excepción debe quedar centralizada en el queryset de Analytics.

## 7. Gate de release

Antes de desplegar cambios en Billing, Analytics o Dashboard:

1. Migrar una base PostgreSQL vacía hasta `leaf`.
2. Migrar un snapshot del estado anterior relevante y comprobar que termina con el mismo schema contractual.
3. Ejecutar `audit_billing_schema --json` y `audit_anchor_integrity --json`.
4. Ejecutar las suites de schema, anchors, snapshots, late arrivals, consistencia y dashboard financiero.
5. Construir al menos un snapshot con `build_daily_metrics` y verificar `provenance_mix` y `excluded_anchor_missing`.
6. Confirmar aislamiento multi-tenant y estabilidad frente a cambios de timezone.

Suite mínima sugerida:

```powershell
python manage.py test apps.billing.tests.test_schema_contract apps.analytics.tests.test_snapshot_v1 apps.analytics.tests.test_late_arrival_observability apps.dashboard.tests.test_consistency apps.dashboard.tests.test_revenue_net
```

## 8. Condición de bloqueo

El release se bloquea si ocurre cualquiera de estas condiciones:

- schema drift en Billing;
- anchor obligatorio nulo;
- procedencia `unresolved` sin decisión documentada;
- referencia activa a `confirmed` o `cancelled` como lifecycle de Invoice;
- snapshot congelado modificado sin audit/adjustment;
- diferencia de resultados entre instalación limpia y upgrade;
- fuga de datos entre organizaciones.

La evidencia reproducible del incidente que motivó estos gates se conserva en la [auditoría Checkout/Billing](audits/2026-09-05-checkout-billing-regression-audit.md).
