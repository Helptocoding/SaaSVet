# Financial Event Model Contract

Version: 1.0 (frozen)
Owner: Backend
Status: **Frozen — 2026-05-27.** §2 (naming canónico), §3 (invariantes), §4 (naming rules),
§6 (contra-asiento) y §8 (semántica financiera) son **binding**. Editar requiere ADR.
Last updated: 2026-05-27

---

## 0. Scope y autoridad

Este documento es la **única fuente de verdad** del modelo de eventos financieros del
sistema: `Payment`, `RefundPayment`, `RefundReversal` (v1) y el futuro `LedgerEntry`
unificado (diferido — ver `DD-002` en `docs/deferred-decisions.md`).

Es **transversal**: lo consumen `billing`, `analytics`, `cash`, reportes, exports, tests,
serializers, frontend y migraciones. Por eso vive fuera de cualquier ADR individual. Los
ADRs **deciden y justifican**; este contrato **define vocabulario, semántica e
invariantes**. Cualquier desacuerdo entre este documento y la implementación se resuelve
cambiando la implementación, nunca el documento en silencio.

**Editar este contrato requiere ADR.** Lo mismo que `docs/dashboard-metrics-contract.md`.

No cubre (todavía): allocation ledger, anticipos/wallet, PSP/chargebacks, retención WORM,
caja por terminal. Esos son hooks futuros listados en §13 con su `DD-xxx`.

---

## 1. Los eventos financieros de v1

Tres modelos append-only. Conceptualmente son **el mismo tipo de cosa**: un movimiento
monetario firmado, emitido por un service, inmutable. Hoy son tablas separadas; mañana
podrán unificarse en `LedgerEntry` (`DD-002`) sin renombrar columnas — por eso el
vocabulario se congela aquí.

| Evento | Qué representa | Documento dueño | Sprint |
|--------|----------------|-----------------|--------|
| `Payment` | Dinero recibido del cliente | `Invoice` | A |
| `RefundPayment` | Dinero devuelto al cliente | `CreditNote` | B |
| `RefundReversal` | Contra-asiento de un refund emitido por error | el `RefundPayment` que contra-asienta | B |

`Payment` y `RefundPayment` **no** son CRUD de una factura: son hechos financieros.
`RefundReversal` **no** es "void de un refund": es un **counter financial event** (ver §6).

---

## 2. Campos canónicos compartidos

Todos los eventos financieros comparten **exactamente estos nombres y semántica**. Un
evento futuro (`payout`, `fee`, `chargeback`, `cashback`) reusa esta tabla. Divergir de
estos nombres es el error más caro del roadmap.

| Campo | Tipo | Semántica | Mutabilidad |
|-------|------|-----------|-------------|
| `amount` | `Decimal(12,2)` | Monto del evento. **Siempre positivo.** El signo lo define el tipo de evento (§5), nunca un decimal negativo. | Inmutable |
| `method` | `CharField` choices `cash\|card\|transfer\|other` | Medio del movimiento. | Inmutable |
| `occurred_at` | `DateTimeField` (UTC) | Momento financiero real del evento. **NUNCA `paid_at` / `refunded_at` / `reversed_at`.** | Inmutable |
| `actor` | `FK User` (`SET_NULL`) | Usuario responsable. **Server-side only** (`request.user`), jamás del body. | Inmutable |
| `cash_session` | `FK 'cash.CashSession'` (`PROTECT`, nullable) | Contexto operativo de caja. `null` si `require_open_cash_session=False`. | Inmutable una vez seteado |
| `reference` | `CharField(100)` sanitizado | Folio externo (auth de tarjeta, referencia de transferencia). Opcional. | Inmutable |
| `idempotency_key` | `CharField` | Dedupe de reintentos. `unique` por organización. | Inmutable |
| `provenance` | `CharField` choices `service\|legacy` | Origen del registro. `service` para writes nuevos; `legacy` solo en backfill. Espejo de la provenance de anchors (ADR p9). | Inmutable |
| `organization` | `FK Organization` (`OrganizationalModel`) | Tenant. Presente en **todos** los eventos desde día 0 (no repetir la deuda de `InvoiceAuditLog` sin `organization_id`; RLS-ready, ADR p23). | Inmutable |
| `reverses` | `FK` self/cross (nullable) | Solo en contra-asientos: el evento que se contra-asienta (§6). | Inmutable |

**Notas de diseño congeladas:**

- El **monto** vive en el evento. La **clasificación de causa** (`reason_code`) vive en el
  **documento dueño** (`CreditNote.reason_code`, ADR p29), no en el `RefundPayment`. El
  evento mueve dinero; el documento explica por qué. No mezclar.
- `actor` es `SET_NULL` por consistencia con `MedicalRecord.veterinarian` (los usuarios se
  desactivan, no se borran). Snapshot de nombre de actor = endurecimiento futuro (mismo
  espíritu que deuda A7 `vet_name_at_close`).
- `cash_session` es `PROTECT`: no se puede borrar una sesión con eventos colgando.

---

## 3. Invariantes globales

Aplican a **todo** evento financiero, sin excepción. Son la red de seguridad conceptual.

1. **`amount > 0` siempre.** Cero o negativo es inválido. El signo lo da el tipo (§5).
2. **Append-only.** Sin `UPDATE` ni `DELETE` tras la creación. No hay endpoint de edición
   ni de borrado para ningún evento financiero.
3. **`occurred_at` inmutable**, seteado en el service al crear, dentro del `atomic()`.
4. **`actor` server-side only.** Se deriva de `request.user`. Nunca se acepta del payload.
5. **Single authoritative writer en `services.py`.** Extiende ADR p9 (anchors) a todos los
   eventos monetarios. Un write de evento financiero fuera de un service es bug.
6. **Las correcciones son contra-asientos, nunca mutaciones** (§6, `DD-007`).
7. **Idempotencia:** `idempotency_key` único por org; un request reintentado dedupea y
   devuelve el mismo resultado, jamás doble-registra (§9).
8. **Provenance:** `service` para nuevos; `legacy` solo en backfill (no inventar actores ni
   timestamps — misma política que la provenance de anchors).
9. **`cash_session` inmutable** una vez seteada; se ata a la sesión abierta vigente en
   `occurred_at` (§11).
10. **La causalidad es un DAG** de eventos firmados; `reverses` apunta al único evento
    contra-asentado; un refund admite **≤1** reversal; un reversal **no** es reversible (§6).
11. **Tenant:** `for_organization()` siempre primero en la cadena; `organization_id` en
    cada evento. Cross-tenant → 404, nunca `[]` (ADR p18). RLS-ready (p23).
12. **IDs:** los eventos internos (`Payment`, `RefundPayment`, `RefundReversal`) son PK-only
    salvo trigger navegable documentado (runbook `exposing-new-model.md`). Un serializer
    nuevo **no** expone `id`+`public_id` a la vez (ADR p24).

---

## 4. Reglas de naming (congeladas)

| Prohibido | Obligatorio | Razón |
|-----------|-------------|-------|
| `paid_at`, `refunded_at`, `reversed_at` | `occurred_at` | Divergencia eterna en analytics/ledger/exports/tooling genérico. |
| `received_by`, `processed_by`, `created_by` (en eventos) | `actor` | Un solo nombre de responsable cross-evento. |
| `amount` negativo para refund | `amount > 0` + signo por tipo (§5) | Sumas, agregados y reportes se vuelven ambiguos con signos mezclados en el dato. |
| `InvoicePayment` (acoplar el nombre a Invoice) | `Payment` | El evento debe poder desacoplarse de Invoice en el allocation ledger futuro (`DD-006`). |
| `void_refund`, `cancel_refund` | `RefundReversal` (contra-asiento) | "Void/cancel" implican mutación; el modelo es append-only (§6). |

`Invoice.paid_at` (anchor analytics existente, ADR p9) **se conserva con ese nombre** — es
el anchor de `Invoice`, no de un evento. Se relaciona con `occurred_at` en §8.

---

## 5. Signo / dirección por tipo de evento

`amount` es positivo siempre; esta tabla define el **signo financiero** y el flujo de caja.

| Evento | Signo financiero | Flujo de caja | Documento | Referencia |
|--------|:----------------:|---------------|-----------|------------|
| `Payment` | `+` (inflow) | Entra dinero | `Invoice` | `invoice` |
| `RefundPayment` | `−` (outflow) | Sale dinero | `CreditNote` (y vía ella, la `Invoice` original) | `credit_note` |
| `RefundReversal` | `+` (inflow) | Vuelve a entrar | — | `reverses = RefundPayment` |
| *futuro* `payout` / `fee` / `chargeback` / `cashback` | — | — | — | `DD-002` (no diseñar hoy) |

El signo es **derivado del tipo**, no almacenado como decimal negativo. En el
`LedgerEntry` futuro será `kind` + `sign` derivado de `kind`.

---

## 6. Modelo de contra-asiento (causalidad)

Principio: **un evento financiero emitido por error no se edita ni se borra — se
contra-asienta con un evento nuevo de signo opuesto.** Esto preserva append-only,
causalidad y el modelo mental de ledger, y prepara el `LedgerEntry` unificado.

- Cadena causal: `Payment` → `RefundPayment (referencia Invoice/CreditNote)` →
  `RefundReversal (reverses = RefundPayment)`. Cada nodo inmutable. Es un **DAG**, no CRUD.
- En el ledger unificado futuro (`DD-007`): `RefundReversal` = `LedgerEntry(kind=refund_reversal,
  sign=+, reverses=<refund_id>)`. Encaja sin caso especial.
- **Invariantes de la cadena (binding):**
  - Un `RefundPayment` admite **a lo sumo un** `RefundReversal`.
  - Un `RefundReversal` **no** es reversible. La corrección de un reversal es un nuevo
    `RefundPayment` (se cierra el ciclo causal sin loops).
- **Caja:** la contra-entry de un refund en efectivo **suma** a `expected_cash` de la
  **sesión abierta actual** (nunca toca un Z cerrado — dual-window, §12).
- **Analytics:** genera un `MetricAdjustment` positivo que cancela el negativo del refund
  (Sprint B; `dashboard-metrics-contract.md` §2.8).
- **UX:** el botón dice "revertir devolución" y produce trail auditable, jamás un "deshacer"
  silencioso.

---

## 7. Supuestos de allocation (v1)

- **v1 considera todo `Payment` `fully_allocated` a un `Invoice`.** `amount` = monto
  asignado a esa factura. `Payment.invoice` es NOT NULL en v1.
- **Conceptualmente `Payment.invoice` es nullable**: un Payment podrá quedar huérfano
  (anticipo/prepago sin factura), parcialmente aplicado, o repartido entre varias facturas.
  Eso es una `PaymentAllocation(payment, invoice, amount)` M:N futura (`DD-006`).
- **Regla de no-encierro:** reporting y analytics **no** deben asumir que `payment.invoice`
  es la única verdad de a qué aplica el dinero. Hoy lo es trivialmente; mañana no. El
  cálculo de `remaining_balance` (§8) se expresa sobre "pagos aplicados a la factura", que
  hoy es la FK directa y mañana será la allocation.

---

## 8. Semántica financiera de la factura (transversal)

Esta sección es deliberadamente transversal — la consumen billing, analytics, caja y el
ledger futuro. Por eso vive aquí y no en un ADR.

### 8.1 `remaining_balance` (cobranza)

```
remaining_balance(invoice) = invoice.total − Σ(Payment.amount aplicado a la factura)
```

- **Es el invariante financiero real.** `Invoice.status` es una **proyección operacional**
  de él, no un flag arbitrario.
- `Invoice.status = 'paid'  ⟺  remaining_balance == 0`
- `Invoice.status = 'confirmed' (cobrable, no liquidada)  ⟹  remaining_balance > 0`
- **Pagos parciales** (consultation) bajan `remaining_balance`; la factura permanece
  `confirmed` hasta llegar a 0, momento en que el service la transiciona a `paid`.
- v1: `remaining_balance` es **propiedad computada**, no columna almacenada. Almacenarla
  reintroduce el lost-update que se cerró en la auditoría (C2) y exigiría F()/recompute bajo
  lock como `recalculate_totals`. Columna almacenada = `DD-001` (solo si el perf lo pide).

### 8.2 Los refunds NO entran en `remaining_balance`

**Decisión congelada (refina la fórmula combinada `total − ΣPayment + ΣRefund`):** un
refund opera **post-liquidación**, sobre una factura ya `paid`, vía `CreditNote`. **No
reabre** el balance cobrable.

Razón: un `remaining_balance` que sumara refunds forzaría `paid → unpaid` en un refund
parcial, rompiendo:
- el anchor inmutable `Invoice.paid_at` (ADR p9),
- la máquina de estados (cancel no permitido desde `paid`),
- la inmutabilidad de snapshots frozen.

Una factura pagada con nota de crédito parcial **sigue `paid`**; el dinero neto se modela
aparte (§8.4), no reabriendo la cobranza.

**Ejemplo formal — tabla de estados.** `Invoice.total = 100`; secuencia: `Payment 100`,
`RefundPayment 20`, `RefundReversal 20`.

| Paso | Evento | Σ Payment | Σ RefundPayment | Σ RefundReversal | `remaining_balance` | `net_settled` | `Invoice.status` |
|:----:|--------|:---------:|:---------------:|:----------------:|:-------------------:|:-------------:|:----------------:|
| 0 | factura confirmada | 0 | 0 | 0 | **100** | 0 | `confirmed` |
| 1 | `Payment 100` | 100 | 0 | 0 | **0** | 100 | `paid` (`paid_at` seteado) |
| 2 | `RefundPayment 20` | 100 | 20 | 0 | **0** | 80 | `paid` (sin cambio) |
| 3 | `RefundReversal 20` | 100 | 20 | 20 | **0** | 100 | `paid` (sin cambio) |

Lecturas clave del ejemplo:
- `remaining_balance` llega a **0 en el paso 1 y no se mueve más** — refunds/reversals no lo
  tocan. Por eso la factura nunca reabre.
- `Invoice.status='paid'` es **terminal e irreversible** desde el paso 1. Refunds no mutan
  `paid_at` ni el lifecycle.
- `net_settled` es la magnitud que **sí** se mueve con los contra-eventos (80 → 100) y es la
  que alimenta `revenue_paid_net` (analytics) y la conciliación de caja.
- `Payment` / `RefundPayment` / `RefundReversal` son **eventos append-only posteriores**, no
  mutaciones de la factura.

### 8.3 `Invoice.paid_at` vs `occurred_at`

- `Invoice.paid_at` (anchor, ADR p9) = `occurred_at` del `Payment` que lleva
  `remaining_balance` a 0. Inmutable una vez seteado.
- Refunds/reversals posteriores **no** cambian `paid_at` (inmutabilidad de snapshot +
  dual-window).

### 8.4 `net_settled` (caja y analytics)

```
net_settled(invoice) = Σ(Payment.amount) − Σ(RefundPayment.amount) + Σ(RefundReversal.amount)
```

- Magnitud **distinta** de `remaining_balance`. Alimenta `revenue_paid_net` (analytics,
  Sprint B) y la conciliación de caja.
- `revenue_paid` (cash basis, anchor `paid_at`) se mantiene **bruto** en Sprint A; pasa a
  **net of refunds** en Sprint B vía `MetricAdjustments` + bump `METRICS_SCHEMA_VERSION`
  (`dashboard-metrics-contract.md` §3.1.1 / §2.8 / §4.7).

### 8.5 Enforcement

Comando `audit_payment_ledger_integrity` (hermano de `audit_anchor_integrity` /
`audit_stock_integrity`, exit-codes 0/1/2, wireable a cron):
- `status='paid'  ⇒  remaining_balance == 0`
- `status='confirmed'  ⇒  remaining_balance > 0`
- `paid_at` consistente con el `Payment` que liquidó.

Es el ratchet que atrapa la regresión "alguien seteó `paid` sin ledger consistente".

---

## 9. Contrato de idempotencia

- El frontend genera `X-Idempotency-Key` por intento de cobro/refund.
- **Agregar el header a `CORS_ALLOW_HEADERS`** (regla CLAUDE frontend; sin esto el browser
  bloquea el preflight).
- El service hace `get_or_create` sobre `(organization, idempotency_key)`. Un reintento
  devuelve el mismo evento, nunca doble-registra.
- Log estructurado `IDEMPOTENT_PAYMENT_DEDUPED` (logger `billing.events`) con
  `request_id`, `idempotency_key`, `organization_id`.
- Cierra el gap de ADR p11: la atomicidad del modal protege contra duplicados de UI, no
  contra reintento de red.

---

## 10. Provenance

Espejo de la provenance de anchors (ADR p9):
- `service` — write nuevo por un service autoritativo (default).
- `legacy` — backfill de datos preexistentes (ej. 1 `Payment` por invoice `paid` histórica,
  `actor=NULL`). **No inventar** actores ni timestamps.

Futuras fuentes (`psp_webhook`, `import`) se agregan por ADR, no ad-hoc.

---

## 11. Vínculo con `cash.CashSession`

- Si `OrganizationSettings.require_open_cash_session = True` (default `False`): todo evento
  financiero exige una sesión abierta del `actor` y la setea en `cash_session`.
- El `Payment`/`RefundPayment` se ata a la sesión **abierta en `occurred_at`**.
- El cierre Z lockea la sesión; los eventos en vuelo re-leen estado y, si está cerrada,
  devuelven 409 `code='cash_session_closed'` (ningún evento se cuela tras el conteo).
- Orden de locks (extiende ADR p12): `CashSession → MedicalRecord → Invoice → Presentation
  → InvoiceItem → MedicalRecordProduct`. El cierre lockea **solo** `CashSession` (nunca
  Invoice) → sin ABBA.

---

## 12. Relación con contratos / ADRs existentes

- **ADR p9** — anchors: `Invoice.paid_at/confirmed_at/cancelled_at` se conservan; este
  contrato no los reemplaza, los relaciona (§8.3). Writers únicos en `services.py`.
- **ADR p11** — direct-pay: una sola máquina de estados, UX colapsada. `pay_direct_sale`
  ahora emite ≥1 `Payment` en su `atomic()`. Sin bifurcar el dominio.
- **ADR p12 / p13** — lock order + F(): respetados; `CashSession` entra a la cabeza.
- **dashboard-metrics-contract §2.8** — dual-window de reversos: refunds y reversals
  generan `MetricAdjustment`, nunca mutan snapshot frozen. §3.1.1: `revenue_paid` se
  redefine net of refunds (Sprint B).
- **ADR p18 / p24** — IDs: eventos internos PK-only; sin `id`+`public_id` dual.
- **ADR p23** — RLS: `organization_id` en cada evento desde día 0.

---

## 13. Fuera de alcance (hooks futuros)

Cada uno tiene su entrada en `docs/deferred-decisions.md`. Los ADRs referencian el `DD-xxx`,
no re-explican el hook (evita drift documental):

| Hook | `DD` |
|------|------|
| `Invoice.status` como proyección almacenada del ledger | `DD-001` |
| `LedgerEntry` unificado (PSP/payout/fee/chargeback) | `DD-002` |
| Allocation ledger (anticipos/wallet/crédito a favor) | `DD-006` |
| Contra-entry generalizado en el ledger unificado | `DD-007` |
| `revenue_paid` cash-basis por pago (vs factura completa) | `DD-008` |
| Drop de `Invoice.payment_method` | `DD-009` |

---

## 14. Versioning y sign-off

- Patch: aclaraciones sin cambio semántico.
- Minor: campo/evento nuevo sin tocar los existentes.
- Major: cambio de semántica de un campo/invariante existente → ADR + sign-off.

**Freeze 1.0 — 2026-05-27:**
- [x] Nombres canónicos (§2) y reglas de naming (§4) — congelados.
- [x] Separación `remaining_balance` vs `net_settled` (§8) — confirmada; `remaining_balance
  = total − Σ(Payment)`, refunds fuera; ejemplo formal en §8.2.
- [x] Modelo de contra-asiento y sus invariantes (§6) — congelado.
- [ ] **Pendiente (no bloquea freeze):** sign-off de PO para el cambio `revenue_paid` → net
  cuando aterrice Sprint B (es un gate de implementación, no un cambio de contrato).
