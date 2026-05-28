# ADR p28: Turno de caja y cierre Z (`apps/cash`)

**Fecha**: 2026-05-27
**Estado**: Aceptado (diseño) — implementación Sprint A, sin código aún
**Documentos relacionados**:
- `docs/financial-event-model-contract.md` (v1.0 frozen) — §6, §11
- `docs/deferred-decisions.md` — `DD-003`, `DD-004`
- ADR `2026-05-27-p27` (Payment — **prerequisito**), `2026-05-16-p12` (orden global de locks), `2026-05-09-p9` (CHECK + provenance)

## Contexto

No existe concepto de caja. Una clínica necesita: apertura/cierre de turno, ventas del
turno, diferencias de caja, efectivo vs tarjeta vs transferencia, multiusuario, auditoría,
reportes Z, y reglas operativas. El requisito más delicado: **¿qué pasa si una factura
cambia después del cierre?** El Z cerrado es un documento de reconciliación que no debe
mutar retroactivamente.

## Decisión

### 1. Módulo nuevo `apps/cash` (no dentro de billing)

Billing es el dominio del **ciclo de vida de la factura**; caja es **reconciliación del
cajón físico**, un agregado por encima de los pagos. Bounded contexts separados.

- Ciclo de import resuelto: `Payment.cash_session` es FK con **string ref**
  `'cash.CashSession'`; `billing/services.py` consulta el puerto fino
  `cash.services.get_open_session(user)`. Dependencia unidireccional billing→cash, sin ciclo.

### 2. `CashSession`

Modelo **público** (`PublicIdMixin`, solo `public_id`, ADR p24). `opened_by`, `opened_at`,
`opening_float`, `status` (`open → closed` terminal; `force_closed` administrativo),
`closed_by`, `closed_at`, `counted_cash`, `expected_cash`, `difference`, `notes`.

- **CHECK** `status='closed' ⇒ closed_at IS NOT NULL` (espejo del patrón anchor, ADR p9).
- **Unique parcial** `(organization, opened_by, status='open')` → una sola caja abierta por
  usuario (la race la resuelve el `IntegrityError`; validar antes — CLAUDE).
- `opened_at` / `closed_at` con provenance (anchors si más adelante alimentan métrica).

### 3. Orden de locks — `CashSession` a la cabeza

```
CashSession → MedicalRecord → Invoice → Presentation → InvoiceItem → MedicalRecordProduct
```
- **Cerrar** lockea **solo** `CashSession`, agrega Payments vía `Sum()` (no instancia filas),
  escribe `expected/counted/difference/closed_*` en un `atomic()`. **Nunca lockea Invoice** →
  no hay par {Invoice, CashSession} en orden inverso → sin ABBA.
- **Pagar** (si toggle on) lockea `CashSession` (verifica `open`) **antes** de Invoice.
- Invariante: una vez que `close` toma el lock, los `pay` en vuelo re-leen `status` y, si está
  cerrada, devuelven **409 `code='cash_session_closed'`**. Ningún pago se cuela tras el conteo.
- Extiende ADR p12 → re-correr `test_invoice_concurrency` + nueva `test_cash_session_concurrency`.

### 4. Cálculo Z

```
expected_cash = opening_float + Σ(Payment.amount where method='cash' and cash_session=S)
                              [ − Σ(RefundPayment cash en S)  ← término que agrega Sprint B / ADR p29 ]
card_total / transfer_total = informativos (NO entran al conteo de efectivo)
difference = counted_cash − expected_cash   (append-only)
```
La fórmula es **forward-compatible**: en Sprint A el término de refunds es 0; ADR p29 le suma
`− Σ(cash refunds)` sin reestructurar.

### 5. Snapshot legal del cierre (frozen)

Al cerrar, el service escribe `closed_snapshot` (JSON, append-only) con `{ totals_por_método,
operaciones, refunds_breakdown, actor, generated_at }` + `report_schema_version`. **El Z
histórico no se reinterpreta** si cambia el código de reporting o se agregan métodos —
mismo principio que `DailyOrgMetrics` frozen + `metrics_schema_version`. Razón precisa: los
Payments son inmutables, pero las **reglas de reporting** pueden cambiar; el snapshot
protege contra ese **drift de código**. Un Z de Sprint A queda `report_schema_version=1`
(sin línea de refunds); Sprint B = `2`. Tabla materializada aparte = `DD-003`.

### 6. Restricción operativa configurable

Toggle `OrganizationSettings.require_open_cash_session` (**default `False`** →
comportamiento actual intacto). Si `True`: `pay`/`refund` exigen sesión abierta del actor.

### 7. Pertenencia v1 vs v2

v1 = una sesión por `User`. v2 = sesión por `Register/Terminal` (`DD-004`). Para no encerrar:
**reportes y queries del Z se llavean por `CashSession.public_id`, no por `user_id`**;
`opened_by`/`closed_by` quedan como actor de auditoría.

### 8. Analytics — desacoplado de `revenue_paid`

`revenue_paid` ancla en `Invoice.paid_at`, independiente de la sesión: un pago cuenta en
revenue exista o no caja; card/transfer cuentan en revenue pero **no** en el efectivo del Z.
El Z es **reconciliación operativa**, endpoint propio, **no** entra a `DailyOrgMetrics` en
v1. `today` (sesión abierta) nunca se snapshotea. Documentar explícito: **caja-efectivo ≠
`revenue_paid`**.

### 9. Auditoría

Eventos estructurados `cash.events`: `CASH_SESSION_OPENED`, `CASH_SESSION_CLOSED` (con
`difference`), `CASH_SESSION_FORCE_CLOSED`. `organization_id` en todos.

## Alternativas consideradas

1. **Caja dentro de billing** — descartada. Infla la máquina de estados de factura; bounded
   context distinto.
2. **Sesión por terminal ya** — diferida (`DD-004`); v1 per-user es suficiente y responde
   "quién cobró".
3. **Recomputar el Z live siempre** — descartada. El código de reporting puede driftar y
   reinterpretar un Z legal histórico. El snapshot lo congela.
4. **CHECK que sume pagos cross-row** — imposible en SQL. El enforcement es el service de
   cierre + el snapshot frozen + `audit_payment_ledger_integrity` (ADR p27).

## Consecuencias

Positivas:
- Reconciliación de caja con Z imprimible y diferencia auditada.
- Sin pago fantasma post-conteo (lock de sesión en el cierre).
- Caja opcional desde día 0 (toggle off por default — backward compatible).

Costos:
- Lock nuevo en el orden global → re-correr suites de concurrencia.
- Dependencia billing→cash (resuelta vía string FK + puerto).

## Relación con el contrato y otros ADRs

Vínculo caja↔evento financiero en contrato §11 y §6 (contra-asiento en caja). **Depende de
ADR p27** (Payment). Extiende ADR p12 (orden de locks). Hooks `DD-003`/`DD-004` en
`deferred-decisions.md`.
