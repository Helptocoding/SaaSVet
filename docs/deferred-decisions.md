# Deferred Architecture Decisions (DD register)

Status: living document
Owner: Backend / Architecture
Last updated: 2026-05-27

---

## Qué es esto (y qué NO es)

Registro de **decisiones de arquitectura deliberadamente diferidas** durante el diseño del
POS (financial event model, caja, refunds). Cada entrada es una decisión **ya tomada en
principio** pero **no implementada todavía**, con su trigger de activación.

**Esto NO es deuda técnica.** La deuda (`docs/deuda/`) es algo que está mal o incompleto y
hay que arreglar. Esto es lo contrario: decisiones correctas que se difieren **a propósito**
(YAGNI controlado), con la nomenclatura/semántica/invariantes ya alineados hoy para que la
implementación futura sea **mecánica y sin reescritura**.

**Regla de mantenimiento:** los ADRs y contratos **referencian el `DD-xxx`**, no
re-explican el hook. Así el conocimiento no se fragmenta ni se contradice entre documentos.
El mapa consolidado vive aquí; los ADRs deciden, justifican y apuntan.

---

## Registro

| ID | Tema | Estado | Trigger de activación | Referenciado por | Pre-alineado en |
|----|------|--------|-----------------------|------------------|-----------------|
| **DD-001** | `Invoice.status` como proyección **almacenada** derivada del ledger (`remaining_balance` columna materializada) | Deferred | Perf de cálculo de balance duele, o existe allocation ledger | ADR p27 | `financial-event-model-contract.md` §8.1 — hoy es propiedad computada + comando `audit_payment_ledger_integrity` |
| **DD-002** | `LedgerEntry` unificado (`Payment`/`RefundPayment`/`RefundReversal` + `payout`/`fee`/`chargeback`/`cashback`) | Deferred | Integración con PSP (Stripe/Conekta) | ADR p27, p29 | Contrato §1, §2, §5 — nombres de campo idénticos y simétricos; signo por tipo |
| **DD-003** | `CashSession` snapshot **materializado en tabla aparte** (grado fiscal/export) | Deferred | Requerimiento fiscal o de export del Z histórico | ADR p28 | Sprint A ya guarda `closed_snapshot` JSON + `report_schema_version` en la sesión |
| **DD-004** | Caja por **Register/Terminal** (no por `User`) | Deferred | Clínicas multi-terminal / varias recepcionistas en una caja física | ADR p28 | Reportes Z se llavean por `CashSession.public_id`, no por `user_id`; `opened_by/closed_by` quedan como actor de auditoría |
| **DD-005** | Retención **WORM / archival** de `ExternalPrescriptionAttestation` | Deferred | Compliance / retención legal regulatoria post-periodo | ADR p26 | Append-only sin DELETE desde día 0; retención y base lícita LFPDPPP documentadas en p26 |
| **DD-006** | **Allocation ledger** (`PaymentAllocation` M:N; anticipos, wallet, crédito a favor, prepagos) | Deferred | Negocio pide anticipos / saldo a favor / conciliación bancaria | ADR p27 | Contrato §7 — v1 `fully_allocated`; `Payment.invoice` conceptualmente nullable; reporting no asume 1:1 |
| **DD-007** | Contra-entry **generalizado** en el ledger unificado | Deferred | Junto con DD-002 (ledger unificado) | ADR p29 | Contrato §6 — `RefundReversal` ya es counter-event con `reverses` FK; cadena DAG; ≤1 reversal |
| **DD-008** | `revenue_paid` **cash-basis por pago** (Σ pagos/día) en vez de por factura completa | Deferred | Contabilidad exige reconocer parciales el día en que entran | dashboard-metrics-contract | Contrato §8.4 — hoy `paid_at` se setea al completar la factura; cambio = `METRICS_SCHEMA_VERSION` bump + dual-write 30d |
| **DD-009** | Drop de la columna `Invoice.payment_method` | Deferred | Post-beta, tras estabilizar el ledger de `Payment` | ADR p27 | Sprint A: `payment_method` queda como legacy/derivado, no se dropea |
| **DD-010** | Pago **split** en la venta rápida F11 (`NewInvoiceModal`) | Deferred | Cuando se necesite split en el flujo de caja rápido | ADR p27 | Backend ya soporta `payment_lines` en direct-pay; el split aquí requiere conocer el total con IVA **antes** de crear la factura (timing) sin reintroducir draft huérfanos (ADR p11). El split sí está en el modal de detalle. Solución futura: paso de revisión post-creación o cálculo de total client-side espejando `money.invoice_totals` |

---

## Cómo se cierra una entrada

Una `DD` se cierra cuando se implementa:
1. Se escribe un ADR formal con la decisión concreta (referenciando este `DD-xxx`).
2. Se actualiza este registro: `Estado = Implemented (ADR pXX, fecha)`.
3. Si la implementación contradice el pre-alineamiento documentado, **se explica por qué**
   en el ADR — el pre-alineamiento era una apuesta, no un contrato.

---

## Referencias

- `docs/financial-event-model-contract.md` — vocabulario/semántica/invariantes congelados.
- `docs/dashboard-metrics-contract.md` — métricas, dual-window de reversos, schema version.
- `docs/decisions/` — ADRs p25–p29 (financial event model, caja, refunds, attestation,
  owner/pet en venta directa).
- `docs/deuda/` — deuda técnica real (distinta de este registro).
