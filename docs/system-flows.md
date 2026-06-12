# Flujos Completos del Sistema

**Fecha**: 2026-05-29
**Estado**: vigente (refleja Sprint A completo + Sprint B + ADR p30)
**Audiencia**: nuevo desarrollador, QA, tester, soporte.

Este documento describe los **recorridos extremo a extremo** que cubren los
escenarios operativos más frecuentes en una clínica, el resumen de todos los
flujos válidos y la lista de flujos inválidos rechazados explícitamente por el
sistema.

> **Índice general**: [`docs/system-operational-flow.md`](system-operational-flow.md) — mapa de módulos y dependencias.
> **Operaciones por módulo**: [`docs/system-module-operations.md`](system-module-operations.md) — acciones con precondiciones, efectos y bloqueos.
> **Referencia**: [`docs/system-reference.md`](system-reference.md) — errores, dependencias críticas e invariantes.

---

## 1. Flujos completos

A continuación se presentan los recorridos extremo a extremo que cubren los escenarios
operativos más frecuentes en una clínica. Cada diagrama traza el camino desde la acción
inicial hasta el registro en analytics.

### Flujo A — Consulta agendada, atendida y cobrada

```
Recepción
   ↓
Crear cita (scheduled)
   ↓ (opcional)
Confirmar (confirmed)
   ↓
Iniciar (in_progress)
   ↓
[El veterinario abre la consulta médica]
   ↓
Registrar signos vitales (VitalSigns append-only)
   ↓
Agregar servicios (sincroniza InvoiceItem en factura draft lazy)
   ↓
Agregar productos (descuenta stock, sincroniza InvoiceItem)
   ↓ (opcional)
Emitir receta (medicamentos, sin descuento de stock ni cobro)
   ↓
Cerrar consulta (closed_at + garantiza factura draft)
   ↓
[Recepción abre la sección de Cobros]
   ↓ (opcional)
Dispensar receta (agrega líneas a la MISMA factura con FK dispensed_from_prescription_item)
   ↓
Confirmar factura (confirmed + descuenta stock de ítems dispensados)
   ↓
Cobrar (pay_invoice, total exacto, 1+ Payment, paid_at)
   ↓
Cita pasa a done (manual; CTAs en detalle de cita: Ver Consulta, Ver Factura)
   ↓
Analytics nocturno snapshotea:
   - revenue_paid, revenue_accrual, invoices_paid_count
   - medical_records_closed
   - appointments_done
```

### Flujo B — Venta directa (mostrador / POS)

```
Recepción presiona "+ Cobro" (atajo F11)
   ↓
Modal: selecciona owner (genérico por defecto o real) + pet (opcional)
   ↓
Agrega productos y/o servicios (estado local, sin enviar al backend todavía)
   ↓ (si el producto tiene requires_prescription)
Atestar receta externa (prescriber_name, rx_attested=true)
   ↓
Botón "Cobrar" → secuencia atómica:
   - createInvoice (direct_sale, draft)
   - addItem × N (crea ExternalPrescriptionAttestation si aplica)
   - direct-pay (un solo lock):
       * _confirm_locked_invoice → descuenta stock de TODOS los ítems con presentación + confirmed_at
       * _pay_locked_invoice → registra Payment(s) + paid_at
       * Si el toggle de caja está activo: asigna Payment.cash_session
   ↓
El frontend muestra el cambio en efectivo (solo UI) si el monto recibido > total
   ↓
Analytics nocturno snapshotea:
   - revenue_paid (confirmed_at ≈ paid_at, diferencia de milisegundos)
```

### Flujo C — Walk-in anónimo, atendido

```
Un cliente llega sin cita previa
   ↓
Recepción usa la opción walk-in (allow_anonymous_walkin=True)
   ↓
Se crea la cita en in_progress, walk_in=True, pet=genérica
   ↓
El banner amarillo en la UI indica: "vincular paciente"
   ↓ (en cualquier momento antes de done)
PATCH assign-patient con el pet real
   ↓
Se continúa con el Flujo A normal (consulta → cobro)
```

### Flujo D — Devolución (post-pago, Sprint B)

```
La factura está en paid
   ↓
ADMIN abre el detalle de la factura → botón "Devolver" (can('billing.refund'))
   ↓
Selecciona los conceptos a devolver (cantidad/monto por línea) + disposition (restock/discard)
   ↓
Editor de reembolso: payment_lines exactos = Σ credit_lines
   ↓
Rellena reason_code (tipificado) + notas
   ↓
X-Idempotency-Key + POST refund/
   ↓ (atómico)
Se crean CreditNote + CreditNoteItem[] + RefundPayment[]
   ↓
Si restock: apply_stock_movement('in')
   ↓
Se genera un MetricAdjustment negativo en revenue_paid del DÍA DEL REFUND
   ↓
Si es en efectivo: se resta del expected_cash de la caja abierta actual
   ↓
La Invoice permanece en paid (paid_at inmutable)
   ↓
Si fue un error → botón "Revertir" → RefundReversal + ajuste positivo + suma en caja
```

---

## 2. Flujos válidos (resumen)

1. Cita programada: `scheduled → (confirmed) → in_progress → done` (done es terminal).
2. Cancelación de cita: `scheduled|confirmed → canceled` (se puede reprogramar solo si la fecha original no ha pasado).
3. Consulta médica: `open → closed` (terminal, irreversible y garantiza la existencia de factura).
4. Factura de consulta: `draft → confirmed → paid` (cobro por el total exacto).
5. Venta directa: `draft → paid` de forma atómica mediante `direct-pay`.
6. Cancelación de factura: `draft|confirmed → cancelled` (solo si no tiene Payments registrados).
7. Devolución: `paid → (CreditNote + RefundPayment[])` — la factura permanece en `paid`.
8. Reversión de devolución: `RefundPayment → RefundReversal` (relación 1:1, el reversal no es reversible).
9. Caja: `open → closed` (el cierre Z legal queda congelado).
10. Walk-in anónimo: `pet genérico → assign-patient → pet real` (antes de que la cita llegue a `done`).
11. Dispensación de receta: se agregan ítems a la **misma factura de consulta** (en `draft`); el descuento de stock ocurre al confirmar.
12. Receta externa en venta directa: aplica cuando `requires_prescription=True`, con `rx_attested=true`, `prescriber_name` y permiso `billing.rx_dispense`.

---

## 3. Flujos inválidos (rechazados explícitamente)

- Pagar una factura en `draft` sin haberla confirmado antes (`pay_invoice` exige `confirmed`).
- Pagar un monto inferior al total (ADR p30: no se admiten pagos parciales bajo ningún motivo).
- Cancelar una factura en estado `paid` (para eso existe la nota de crédito).
- Cancelar una factura en `confirmed` que ya tenga Payments registrados.
- Emitir un refund sobre una factura en `draft`, `confirmed` o `cancelled` (solo se permite sobre `paid`).
- Hacer over-refund (cantidad o monto superior al saldo disponible para devolver).
- Editar o borrar una consulta en estado `closed` (ningún rol puede hacerlo).
- Borrar una consulta que tenga una factura asociada → 403.
- Borrar un Owner o Pet que tenga dependencias → 409 `resource_has_dependencies`.
- Borrar el Owner o Pet genérico → 409 `generic_resource_protected`.
- Borrar un `VaccineRecord` → 405 (modelo append-only por cumplimiento NOM-007/046).
- Borrar un `MedicalRecord` con recetas, facturas o signos vitales asociados → 403 (guard) o 409 (PROTECT).
- Crear un walk-in sin `pet` cuando `allow_anonymous_walkin=False` → 400.
- Realizar transiciones de cita inválidas (`scheduled → done`, `done → *`, etc.).
- Confirmar una factura sin ítems activos → 400.
- Agregar dos veces la misma presentación o servicio a la misma factura → unique constraint.
- Dispensar una receta sobre una factura en `confirmed` o `paid` → solo se permite en `draft`.
- Dispensar más de lo recetado (acumulado en unidades base por ítem de receta) → 400; el cliente puede llevar menos de lo recetado, nunca más.
- Vender un producto con `requires_prescription` en venta directa sin `rx_attested` → 400 `prescription_required`.
- Vender un producto con `requires_prescription` sin el permiso `billing.rx_dispense` → 403.
- Abrir una segunda caja para el mismo usuario → UniqueConstraint.
- Pagar cuando `require_open_cash_session=True` y el actor no tiene caja abierta → 400 `cash_session_required`.
- Provisionar una organización con un payload que intente inyectar `role=ADMIN_SAAS` → el sistema aplica fuerza-override silencioso (se asigna `ADMIN`).
- Acceder a recursos de otra organización (cross-tenant) → 404 (nunca se devuelve `[]`).
- Crear un `Payment` con `amount <= 0` → se viola el invariante.
- Mutar `Invoice.status` fuera de `services.py` → bloqueado por CHECK constraints de base de datos y auditoría.
- Cerrar una consulta sin `diagnosis` (siempre obligatorio) o sin `treatment` (obligatorio excepto en `consultation_type=vaccine`).
