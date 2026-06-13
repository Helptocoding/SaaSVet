# Referencia Operacional

**Fecha**: 2026-05-29
**Estado**: vigente (refleja Sprint A completo + Sprint B + ADR p30)
**Audiencia**: nuevo desarrollador, QA, tester, soporte.

Este documento contiene la **referencia operacional** del sistema: errores
comunes con su diagnóstico, dependencias críticas que no deben romperse,
invariantes del sistema y el resumen ejecutivo del negocio.

> **Índice general**: [`docs/system-operational-flow.md`](system-operational-flow.md) — mapa de módulos y dependencias.
> **Operaciones por módulo**: [`docs/system-module-operations.md`](system-module-operations.md) — acciones con precondiciones, efectos y bloqueos.
> **Flujos completos**: [`docs/system-flows.md`](system-flows.md) — recorridos extremo a extremo.

---

## 1. Errores operativos comunes

| Síntoma | Causa probable | Diagnóstico |
|---------|----------------|-------------|
| "Stock insuficiente" al confirmar factura | Otra venta concurrente consumió el stock. | La validación bajo `select_for_update` es correcta. En UX: recargar la disponibilidad. |
| Botón cobrar deshabilitado | `Σ payment_lines ≠ remaining_balance`. | Verificar el split de pago y el cambio en efectivo (el cambio se capea en UI, no afecta `amount`). |
| Factura no aparece en Cobros tras cerrar consulta | Comportamiento pre-ADR p30 (creación lazy). | A partir de p30 el cierre de consulta garantiza la factura. Verificar versión del backend. |
| "No hay caja abierta" al cobrar | Toggle `require_open_cash_session=True` y el actor no tiene sesión de caja. | Abrir caja con `POST /api/cash/sessions/open/`. |
| 403 al dispensar receta | Falta el permiso `billing.rx_dispense`. | Asignarlo al rol correspondiente (ADMIN/VET) desde la sección de Roles. |
| Factura draft de $0 acumulada | Consulta cerrada sin cargos (comportamiento esperado post-p30). | Trade-off aceptado: toda consulta cerrada aparece en Cobros. |
| Drift de stock detectado por `audit_stock_integrity` | Escritura directa a `stock` sin pasar por `apply_stock_movement`. | Investigar el caller. Se corrige con migración de baseline o `adjustment` manual. |
| `RBAC_FALLBACK_ALLOWED` en logs | Usuario sin `UserRole` en la base de datos. | Ejecutar `seed_permissions` en la organización. |
| 401 en frontend tras login válido | Toggle "Recordarme" e inconsistencia en el almacenamiento del token. | Revisar `auth/tokenStorage.js` (session tiene prioridad sobre local). |
| Cita walk-in con pet genérico no se puede vincular | La cita ya está en estado `done`. | Vincular al paciente real antes de cerrar la cita. |
| Over-refund | La suma de líneas supera el monto ya devuelto disponible. | Revisar el detalle de las notas de crédito emitidas previamente. |
| No se puede dispensar un producto que ya figura como insumo | `unique_together(invoice, presentation)`. | Ajustar manualmente la cantidad del insumo en la consulta. |
| 400 al dispensar: "la receta ampara N…" | Tope clínico (ADR p37): dispensado acumulado + solicitado > recetado (en unidades base). | El mensaje trae amparado/dispensado/restante. Reducir cantidad o corregir la receta (consulta `open`). |
| 400 al agregar producto en cobro de consulta | Ítem manual de presentación en factura `consultation` (no liquidaría stock, ADR p37). | Los productos entran por insumos de la consulta o dispensando la receta; aquí solo servicios. |
| `closed_at` genera log `ANCHOR_LATE_ARRIVAL` | El cierre de consulta cayó en un bucket frozen (>T+2). | Es solo una advertencia (warn-only); revisar la latencia operativa. |
| `RBAC_DENIED` recurrente para el mismo endpoint | El frontend está usando un endpoint que el rol no tiene permitido. | Revisar `can()` antes de mostrar el CTA correspondiente. |

---

## 2. Dependencias críticas (no romper)

- `for_organization()` debe ir **siempre primero** en la cadena del queryset.
- Toda mutación de stock debe pasar por `apply_stock_movement()`, con el lock externo ya adquirido por el caller.
- Toda mutación de `InvoiceItem.quantity` debe usar `apply_invoice_item_quantity_delta()` (basado en F()).
- Los anchors (`paid_at`, `confirmed_at`, `cancelled_at`, `closed_at`) solo se escriben dentro de `services.py`.
- Los eventos financieros (`Payment`, `RefundPayment`, `RefundReversal`) solo se crean en `billing/services.py`.
- El orden global de locks es: `CashSession → MedicalRecord → Invoice → Presentation → InvoiceItem → MedicalRecordProduct`.
- `recalculate_totals()` solo se invoca bajo lock de la Invoice.
- `seed_permissions` se ejecuta en cada deploy (Procfile).
- El frontend usa `public_id` en URLs y deep links; los PKs solo se usan en campos FK del body y en despliegues de pantalla.
- El header `X-Idempotency-Key` debe figurar en `CORS_ALLOW_HEADERS` para que el navegador no bloquee la petición preflight.

---

## 3. Invariantes del sistema (binding)

1. **Multitenancy**: todo acceso cross-tenant retorna 404. Cada fila tiene `organization_id`. El sistema está preparado para RLS (ADR p23).
2. **Anchors inmutables**: `paid_at`, `confirmed_at`, `cancelled_at`, `closed_at` y `closed_snapshot` no se reescriben nunca.
3. **Append-only**: los siguientes modelos son de solo inserción: `Payment`, `RefundPayment`, `RefundReversal`, `CreditNote`, `VitalSigns`, `VaccineRecord`, `ExternalPrescriptionAttestation`, `InvoiceAuditLog`, `AppointmentStatusChange`, `MetricAdjustment`, `DashboardSnapshotAudit`, `OrganizationTimezoneAudit` y `CashMovement` (ADR p39).
4. **`amount > 0`** en todos los eventos financieros. El signo lo determina el tipo de evento, nunca un decimal negativo.
5. **`Invoice.status='paid' ⟺ remaining_balance == 0`**. El estado es una proyección del ledger, no un flag arbitrario.
6. **Los refunds no afectan `remaining_balance`**. La factura en `paid` es terminal.
7. **Los snapshots frozen jamás se reescriben**. Los ajustes posteriores se registran mediante `MetricAdjustment` en el modelo dual-window.
8. **Total exacto**: toda factura se cobra por el monto completo (ADR p30, que reemplaza el modelo de pagos parciales de p27).
9. **`actor` es siempre server-side**: se toma de `request.user`, nunca del body de la petición.
10. **`organization_id` existe desde el día 0** en cada modelo (no se repite la deuda técnica de `InvoiceAuditLog`).
11. **Idempotencia**: la combinación `(org, idempotency_key)` es única; un reintento devuelve el mismo resultado.
12. **Causalidad en DAG**: `Payment → RefundPayment → RefundReversal`. Cada nodo es inmutable. Máximo 1 reversal por refund; el reversal no es reversible.
13. **Una receta no descuenta stock ni genera cobro por sí sola**. El cobro y el descuento de stock ocurren al dispensar y confirmar la factura de la consulta.
14. **Una consulta cerrada siempre tiene factura** (como mínimo una en `draft` por $0, según ADR p30).
15. **Una consulta con factura asociada no se puede eliminar** (403).
16. **Los CHECK constraints en base de datos** bloquean `queryset.update()`, `bulk_update` y SQL directo que dejaría un estado sin su anchor correspondiente.
17. **El día actual (today) nunca se snapshotea** en analytics (siempre se calcula como live).
18. **Caja-efectivo ≠ revenue_paid**: los pagos con tarjeta o transferencia no entran en el conteo del cierre Z.
19. **El administrador de una clínica no puede provisionar otras organizaciones** (no es `ADMIN_SAAS`; el payload no permite escalar privilegios).
20. **`InvoiceItem.dispensed_from_prescription_item`** es el discriminador único para determinar qué ítems descuentan stock en una factura de consulta (no existe una segunda función de stock).
21. **Dispensado ≤ recetado** (ADR p37): por ítem de receta, `Σ(quantity × conversion_factor)` de las líneas dispensadas activas de la factura no excede `PrescriptionItem.quantity` (unidades base). Cubre dispensación, edición de línea (PATCH) y bloquea ítems de presentación manuales en facturas `consultation`. El cliente puede llevar menos; nunca más.

---

## 4. Reglas que nunca deben romperse

- Jamás escribir `Invoice.status` fuera de `billing/services.py`.
- Jamás escribir `Presentation.stock` fuera de `apply_stock_movement()`.
- Jamás mutar `InvoiceItem.quantity` con `+=` seguido de `save()` (debe usarse el helper basado en F()).
- Jamás invertir el orden global de locks.
- Jamás crear un `Payment` fuera de `pay_invoice` o `pay_direct_sale`.
- Jamás admitir pagos parciales en una factura.
- Jamás reabrir una factura que ya está en estado `paid`.
- Jamás editar ni borrar eventos financieros (la corrección se hace mediante contra-asiento).
- Jamás exponer `id` junto con `public_id` en serializers de modelos públicos **nuevos** (los legacy están baselineados).
- Jamás usar el patrón `editing.public_id || editing.id` en el frontend (anti-patrón verificado con grep).
- Jamás llamar a `cache.clear()` de forma masiva dentro de signals.
- Jamás snapshotear el día actual (today).
- Jamás bumpear `METRICS_SCHEMA_VERSION` sin un ADR que lo respalde, con dual-write durante 30 días y aprobación del Product Owner.
- Jamás borrar `Organization`, `Pet`, `Owner` o `MedicalRecord` que tengan dependencias (PROTECT + 409).
- Jamás colocar `for_organization()` después de `select_related()` o `prefetch_related()` en la cadena del queryset.
- Jamás leer `localStorage` directamente para obtener `access_token`, `refresh_token` o `user` fuera de `tokenStorage.js`.

---

## 5. Resumen Ejecutivo

VeterinariaSaaS es un sistema multitenant para clínicas veterinarias en México. Cada
clínica es una **organización** (tenant) con su propio timezone, tax_rate, usuarios
(`ADMIN`/`VET`/`ASSISTANT`), settings, pacientes, inventario y caja. Una capa
**platform** (ADMIN_SAAS) provisiona organizaciones nuevas con su admin inicial
de forma atómica.

El negocio se opera en cinco flujos centrales:

1. **Agenda**: recepción crea citas (o un walk-in, o un registro rápido owner+pet+cita
   atómico). La cita avanza `scheduled → confirmed → in_progress → done` con audit
   trail completo (`AppointmentStatusChange`).

2. **Consulta médica**: el VET abre `MedicalRecord` sobre la mascota, registra
   vitales (append-only), agrega servicios y productos (estos descuentan stock al
   consumirse y sincronizan items en una factura draft creada lazy), opcionalmente
   emite receta (sin stock, sin cobro), y finalmente la cierra. **El cierre
   GARANTIZA la factura en Cobros** (mínimo draft $0, ADR p30) — toda consulta
   finalizada es visible para recepción.

3. **Cobros**: la factura `consultation` tiene flujo `draft → confirmed → paid`
   (cobro total exacto, sin parciales). La factura `direct_sale` (venta de mostrador
   sin consulta) usa `direct-pay` atómico (un solo lock). En consulta, recepción
   puede **dispensar la receta** agregando líneas a la **misma factura** de la
   consulta (FK `dispensed_from_prescription_item` discrimina qué descontar al
   confirmar). En venta directa, productos `requires_prescription` requieren
   **attestation de receta externa** (modelo append-only legal).

4. **Devoluciones** (Sprint B): una factura `paid` NO se cancela; se devuelve vía
   `CreditNote` + `RefundPayment` (append-only, signo `−`). Si fue error, se
   contra-asienta con `RefundReversal`. La factura permanece `paid` (terminal).
   `revenue_paid_net` se ajusta vía `MetricAdjustment` en el día del refund
   (los snapshots frozen NO se reescriben).

5. **Caja**: cada usuario abre 1 sesión (`CashSession`) y al final hace cierre Z
   (`opening_float + Σ cash payments − Σ refunds + Σ reversals = expected_cash`;
   `difference = counted − expected`). El Z legal queda frozen en
   `closed_snapshot`. Cuando el toggle `require_open_cash_session=True`, todo
   cobro exige caja abierta.

**Eventos** (Payment, RefundPayment, RefundReversal) son append-only con `amount > 0`
siempre; el signo lo da el tipo. Los **anchors** (`paid_at`, `confirmed_at`,
`cancelled_at`, `closed_at`) son `editable=False` con CHECK constraints DB y
único writer en `services.py` — la regla autoritativa de analytics y auditoría.

**Analytics** corre nightly (`build_daily_metrics`) por organización con advisory
lock y genera snapshots `DailyOrgMetrics` idempotentes; today es siempre live
calculado con la misma función. El dashboard expone `source` y `lifecycle_state`
por datapoint; nada se sirve silenciosamente.

**Reglas duras**: multitenancy estricto (cross-org = 404, NUNCA `[]`); orden global
de locks `CashSession → MR → Invoice → Presentation → InvoiceItem → MRP`;
toda mutación de stock vía `apply_stock_movement()` + lock externo; toda mutación
contable de `InvoiceItem.quantity` vía F(); IDs públicos UUID (`public_id`) en
URLs, PKs solo en body FK fields. Toda acción crítica deja audit trail (DB o log
JSON estructurado en stdout).

Operativamente, un día típico en una clínica abre con la apertura de caja, recibe
citas + walk-ins, ejecuta consultas que generan facturas, cobra en efectivo o
tarjeta (con dispensación de receta cuando aplica), eventualmente emite
devoluciones por producto vencido / error, y cierra el día con el Z de caja. La
información se refleja inmediatamente en el dashboard live; al siguiente nightly
queda snapshoteada como histórico inmutable.
