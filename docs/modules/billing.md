# Modulo: Cobros

> **Ver también:** [`docs/system-operational-flow.md`](../system-operational-flow.md) — mapa operacional cross-módulo (acciones, precondiciones, efectos, invariantes).

## Objetivo

El modulo de cobros gestiona las facturas generadas por consultas y ventas directas.
Es el dominio financiero del sistema. Opera de forma independiente del dominio clinico.

## Modelos

### Invoice

Campos clave:
- `invoice_type` — `consultation` o `direct_sale`
- `owner` — FK a Owner (PROTECT, obligatorio)
- `pet` — FK a Pet (PROTECT, nullable si `owner.is_generic = True`)
- `status` — `draft`, `confirmed`, `paid`, `cancelled`
- `medical_record` — OneToOneField SET_NULL (opcional)
- `appointment` — OneToOneField SET_NULL (opcional)
- `tax_rate` — heredado de la organizacion al crear, no editable despues
- `payment_method` — `cash`, `card`, `transfer`, `other`
- `subtotal`, `tax_amount`, `total` — calculados automaticamente en backend; `read_only` en el serializer; el cliente nunca puede sobreescribirlos

### Analytics anchors (event authority)

Tres timestamps `editable=False` cuyo unico writer autoritativo vive en
`billing/services.py` (ver ADR `2026-05-09-p9`):

- `paid_at` — set por `pay_invoice()` y `pay_direct_sale()`
- `confirmed_at` — set por `confirm_invoice()` y `pay_direct_sale()`
- `cancelled_at` — set por `cancel_invoice()`

Cada uno tiene su `*_source` (CharField con choices `service|audit_log|fallback|unresolved|legacy`) para auditar provenance.

CHECK constraints DB:
- `invoice_paid_status_requires_paid_at`
- `invoice_confirmed_status_requires_confirmed_at`
- `invoice_cancelled_status_requires_cancelled_at`

Los CHECK bloquean `queryset.update()`, `bulk_update()`, raw SQL y admin
que dejarian status='X' con anchor NULL (corromperia analytics).

Reglas duras:
- NUNCA setear `status` directamente fuera de `services.py`.
- `InvoiceAdmin.readonly_fields` incluye `status`, `payment_method`, todos
  los anchors, totales y `created_at/updated_at`. Admin no puede mutar
  estado — debe usar la API.

### InvoiceItem

Un item es un servicio o una presentacion de inventario (nunca ambos — constraint XOR en DB).

Campos:
- `service` — FK a Service (nullable, SET_NULL)
- `presentation` — FK a Presentation (nullable, PROTECT)
- `quantity` — decimal > 0
- `unit_price` — copiado al crear desde `service.base_price` o `presentation.sale_price`; NO se recalcula al editar el precio del producto
- `discount_type` — `percentage` o `fixed` (nullable)
- `discount_value` — decimal (default 0)
- `subtotal` — calculado en `save()`

Restricciones de unicidad en DB:
- `unique_together = [('invoice', 'presentation')]` — sin presentaciones duplicadas por factura
- `UniqueConstraint(invoice, service, WHERE service IS NOT NULL)` — sin servicios duplicados por factura

## Creacion automatica de facturas

La factura se puede crear de dos formas:

1. **Via signal al completar cita**: cuando una cita pasa a `done`, se puede crear una factura `draft` vinculada a la cita **y** a la consulta médica (si existe). Controlado por el toggle `auto_create_invoice_on_done` en `OrganizationSettings`. El default actual es `False`.

2. **Creación lazy al agregar cargos**: cuando se agrega el primer servicio o producto a una consulta walk-in (sin cita) o a una consulta creada manualmente desde una cita ya completada, se crea una factura `draft` vinculada a la consulta vía `get_or_create_invoice_for_medical_record()`. **No hay señal ni toggle** — es creación automática por demanda.

3. **Garantizada al cerrar la consulta (ADR p30)**: `close_medical_record` llama `get_or_create_invoice_for_medical_record()` dentro de su `atomic()` (MR ya lockeado → Invoice; orden canónico). Así, finalizar **siempre** deja la consulta en Cobros, aunque no tenga cargos (factura `draft` $0). **Supera la creación lazy de ADR p7 en el camino de cierre**: ese camino deja de ser puramente lazy.

**Nota**: La creación automática via señal para consultas walk-in fue eliminada (ADR `2026-05-05-p7-lazy-invoice-creation.md`) para evitar facturas vacías acumuladas. ADR p30 la reintroduce **solo en el cierre** (decisión de producto: la consulta finalizada debe verse en Cobros). Para citas normales, la señal `auto_create_invoice_on_done` sigue existiendo pero queda desactivada por default a nivel de organización.

Ambas creaciones son idempotentes (`get_or_create`).

## Default operativo actual

Configuracion recomendada y aplicada por defecto:
- `auto_create_invoice_on_done = False`
- la factura nace cuando realmente aparece el primer cargo clinico

Razon:
- evitar facturas `draft` vacias en `/billing`
- separar con mas claridad el cierre operativo de la cita del inicio del flujo de cobro
- permitir que el veterinario complete la atencion y luego cree la consulta si realmente se necesitara documentar

## Ventas directas sin cliente registrado

Para ventas a personas sin mascota registrada se usa el propietario generico.

Ver ADR `2026-04-28-generic-client-direct-sale.md`.

**Cliente real en venta directa (ADR p25):** desde p25, una `direct_sale` puede
asociarse a un `owner` registrado y, opcionalmente, a un `pet` de ese owner. El
genérico sigue siendo el default (venta rápida anónima). Reglas:
- `direct_sale`: `pet` **opcional** (con owner real o genérico).
- `consultation`: `pet` **obligatorio** (sin cambio).
- Si se envía `pet`, debe pertenecer al `owner` (guard de integridad, solo cuando
  `pet` está en el payload — no rompe PATCH que solo cambian owner).
- El paciente genérico no puede asignarse a un owner real.
- Sin cambio de schema ni migración (`Invoice.pet` ya era nullable). Sin impacto
  analytics. El frontend manda `invoice_type='direct_sale'` explícito al elegir
  owner real (si no, el default `consultation` exigiría pet).

### Receta externa en venta directa (ADR p26)

Un producto `requires_prescription` ahora **sí** puede venderse en una
`direct_sale`, mediante atestación explícita de receta externa. El gate vive en
`InvoiceItemCreateView.perform_create` (NO en el serializer):
- Exige permiso `billing.rx_dispense` (ADMIN + VET) — si falta → **403**.
- Exige atestación en el body al agregar el item: `rx_attested=true` +
  `prescriber_name`. Si falta → **400** `code='prescription_required'`.
- Crea un `ExternalPrescriptionAttestation` (append-only, modelo legal) en el
  mismo `atomic()` bajo lock de la Invoice, luego el `InvoiceItem`.
- La atestación **sobrevive** cancelación/refund (registro legal). NO se reutiliza
  `Prescription` (clínico) — evita basura clínica. Retención NOM + LFPDPPP (DD-005).

El frontend (POS — `components/pos/Cart.jsx`) muestra un panel de atestación
(checkbox "cliente presentó receta" + médico + folio) cuando el producto tiene
`requires_prescription` (expuesto por `PresentationSerializer`), y manda los
campos con `addInvoiceItem`.

Flujo en frontend (ADR p38 — pantalla dedicada `/pos`, reemplaza al modal "Nuevo Cobro"):
1. "+ Cobro" en `/billing` (o atajo **F11**) navega a `/pos`
2. El propietario generico se asigna automaticamente (cliente real opcional, ADR p25)
3. El frontend manda `invoice_type='direct_sale'` explicito
4. Se agregan productos (escáner de barcode o búsqueda) y/o servicios en estado local
5. "Cobrar" crea el draft real: `createInvoice → addItem × N → getInvoice` — el panel
   pasa a modo pago con subtotal/IVA/total **del backend** (sin replicar `invoice_totals`)
6. "Confirmar cobro" → `direct-pay` con `payment_lines` + `X-Idempotency-Key`
   (mismo `PaymentLinesEditor` que Registrar Pago: split, total exacto, cambio)
7. Si el pago falla, se conservan draft + idempotency key para reintentar (anti doble cobro)
8. "Volver al carrito" / abandonar la página en modo pago → `cancelInvoice` del draft
   (auditable vía `InvoiceAuditLog`; no quedan borradores huerfanos)

**Control de acceso**: la página `/pos`, el boton "+ Cobro" y el atajo F11 usan
`can("invoice.create")` — verifica el permiso real del usuario via la lista de permisos
retornada por `/api/me/`, no compara `user.role`. Esto soporta roles dinamicos donde dos
usuarios con el mismo nombre de rol pueden tener distintos permisos. El "Volver al
carrito" usa `invoice.cancel` (presente en los 3 roles del sistema).

## Estados de la factura

```
              ┌─ direct_sale: pay_direct_sale() ─────────────────────────────┐
              │  (internamente: _confirm_locked + _pay_locked, un solo lock) │
              │                                                               │
draft ────────┼── confirm_invoice() ──→ confirmed ── pay_invoice() ──→ paid  │
  │           │                                                               │
  ├── cancel_invoice() ──────────────────────────────────→ cancelled          │
  └── cancel_invoice() ──────────────────────────────────→ cancelled          │
              (confirmed también puede cancelarse)                            │
```

**Dos caminos para llegar a `paid`:**

| Camino | Tipo de factura | UX | Interno |
|--------|----------------|----|---------|
| `confirm → pay` (2 pasos) | `consultation` | Vet define cargos → Recepción cobra | `confirm_invoice()` + `pay_invoice()` (2 locks) |
| `direct-pay` (1 paso) | `direct_sale` | Cajero agrega items → Cobrar | `pay_direct_sale()`: un solo lock, llama `_confirm_locked_invoice()` + `_pay_locked_invoice()` atómicamente |

Reglas:
- Solo facturas en `draft` son editables (PATCH sobre cualquier otro estado retorna 400)
- Solo se pueden agregar o quitar items en estado `draft`
- Confirmar requiere al menos un item activo — factura vacia retorna 400
- Pagar requiere estado `confirmed` y `payment_method` en el body — no se puede saltar a `paid` desde `draft` en consultation
- Direct-pay requiere `invoice_type='direct_sale'`, estado `draft`, y `payment_method` — aplica solo a ventas directas
- El `tax_rate` se hereda de la organizacion al crear y no cambia aunque la organizacion cambie su tasa
- Ambos anchors (`confirmed_at`, `paid_at`) se escriben con `_source='service'` y se generan ambos audit logs incluso en direct-pay

**Implicacion analytics**: para `direct_sale`, `confirmed_at` y `paid_at` tienen valores casi identicos
(diferencia de milisegundos). Las curvas de accrual y cash coinciden para este tipo de factura —
comportamiento esperado y distinto al de `consultation` donde puede haber horas/dias entre confirmacion y pago.
Ver ADR `2026-05-15-p11-pay-direct-sale.md`.

### Arquitectura interna de services

Para evitar double-lock en `pay_direct_sale`, los services se estructuran en dos capas:

```python
# Funciones internas — asumen invoice YA lockeada con select_for_update()
_confirm_locked_invoice(invoice, user)   # sin @transaction.atomic
_pay_locked_invoice(invoice, user, pm)   # sin @transaction.atomic

# Wrappers públicos — lockean + delegan a internals
confirm_invoice(invoice, user)           # @transaction.atomic + select_for_update
pay_invoice(invoice, user, pm)           # @transaction.atomic + select_for_update
cancel_invoice(invoice, user, notes)     # @transaction.atomic (sin cambios)

# Direct sale atómico — lockea UNA vez, llama ambos internals
pay_direct_sale(invoice, user, pm)       # @transaction.atomic + select_for_update
```

Esto reduce 3 locks (wrapper confirm + wrapper pay + cada uno internamente)
a 1 solo lock, eliminando riesgo de deadlocks y queries innecesarias.

## Ledger de pagos (ADR p27)

Desde ADR p27, los pagos viven en un modelo append-only `Payment` (interno,
PK-only). Una factura tiene 0..N pagos. Contrato completo de campos/invariantes:
`docs/financial-event-model-contract.md`.

Semántica (contrato §8):
- `remaining_balance = total − Σ(Payment.amount)` (propiedad computada).
- `Invoice.status='paid' ⟺ remaining_balance == 0`. El estado es **proyección**
  del ledger, no un flag arbitrario.
- `paid_at` se setea cuando `remaining_balance` llega a 0 (writer único en
  `services.py`, sin cambio respecto a ADR p9).
- Los refunds **no** entran en `remaining_balance` (operan post-pago vía nota de
  crédito, ADR p29).

Pagos split y total exacto (ADR p30 rev, 2026-05-29 — supera el parcial de ADR p27):
- `pay_invoice` / `pay_direct_sale` aceptan `payment_lines=[{method, amount[, reference]}]`
  **o** el legacy `payment_method` (una sola línea por el saldo).
- **Toda factura** (consulta y venta directa) exige el **total exacto**: la suma de
  `payment_lines` debe igualar `remaining_balance`. **Sin parciales bajo ningún motivo.**
  Split sigue válido (efectivo+tarjeta sumando el total). Backend: ambos paths corren
  con `require_full=True`.
- **Cambio en efectivo (universal)**: el frontend admite que el efectivo recibido
  **supere** el total; muestra el cambio (`recibido − total`) y registra **solo el total**
  (`payment_lines` capeado). El cambio es UI: **no se persiste** (no es `Payment`, no
  afecta `remaining_balance` ni caja). Aplica a todo cobro (venta directa y consulta,
  incluida la consulta con dispensación). Frontend: `allowChange={true}` siempre,
  `payAllowPartial = false` siempre; `submitPayment` capea en cualquier sobrepago.
- `invoice.payment_method` queda como legacy/derivado: método único si todos los
  pagos coinciden, `NULL` si es mixto. Drop futuro = `DD-009`.

Idempotencia (contrato §9):
- Header `X-Idempotency-Key` (en `CORS_ALLOW_HEADERS`). El service dedupea por
  `(organization, idempotency_key)`; un reintento devuelve el mismo resultado sin
  doble-registrar. Log `IDEMPOTENT_PAYMENT_DEDUPED`.

Cancelación con pagos:
- `cancel_invoice` **rechaza** una factura con pagos registrados (dejaría dinero
  sin devolver). La devolución va por nota de crédito (ADR p29). Las facturas
  `paid` siguen bloqueadas para cancelación directa.

Enforcement:
- `python manage.py audit_payment_ledger_integrity [--org N] [--verbose] [--json]`
  (exit 0/1/2): asserta `paid ⇒ remaining==0`, `confirmed ⇒ remaining>0`,
  `draft|cancelled ⇒ sin pagos`. Hermano de `audit_anchor_integrity` /
  `audit_stock_integrity`. Wireable a cron.

Migración: `0019_payment` + backfill legacy (1 Payment `legacy` por factura `paid`
con `total>0`, `actor=NULL`, `occurred_at=paid_at`).

## Devoluciones / notas de crédito (ADR p29 — Sprint B)

`cancelar` ≠ `devolver`. Cancel es pre-pago (draft/confirmed). Una factura **paid**
no se cancela; su dinero se devuelve vía **nota de crédito** (la factura permanece
`paid`, contrato §8.2 — no reabre, no muta `paid_at`).

Modelos (append-only): `CreditNote` (público, anchor `issued_at`+CHECK, `reason_code`
tipificado), `CreditNoteItem` (referencia al `InvoiceItem` original; `disposition`
`restock|discard`), `RefundPayment` (signo −, campos canónicos contrato §2),
`RefundReversal` (contra-asiento, ≤1 por refund).

Service `process_refund(invoice, user, credit_lines, refund_lines, reason_code, ...)`:
- Solo facturas `paid`. Valida cantidades/montos contra lo ya devuelto (no over-refund).
- `Σ refund_lines == Σ credit_lines` (el dinero devuelto iguala el crédito).
- `disposition=restock` → `apply_stock_movement('in')` bajo lock; `discard` → sin stock.
- Escribe `MetricAdjustment` negativo en `revenue_paid` del **día del reembolso**
  (dual-window §2.8 — snapshots frozen intactos). Idempotente (`X-Idempotency-Key`).
- Lock order: `CashSession → Invoice → Presentation → CreditNote/items/refund`.

Service `reverse_credit_note(credit_note, user, reason_code, ...)`: contra-asiento de
una NC emitida por error. Emite `RefundReversal` por cada `RefundPayment` (≤1 c/u) +
`MetricAdjustment` positivo que cancela el negativo. No es void/edit (contrato §6).

Caja: refund/reversal en efectivo entran al cierre Z de la **sesión abierta actual**
(refund resta, reversal suma — ver `cash.md`). Una sesión cerrada no cambia.

Endpoints (RBAC `billing.refund`, solo ADMIN por default):
- `POST /api/billing/invoices/<uuid>/refund/`
- `POST /api/billing/credit-notes/<uuid>/reverse/`

Analytics: `revenue_paid` (gross) NO cambia; el dashboard financiero expone además
`revenue_paid_net = gross + Σ MetricAdjustment` (dual-expose, sin flip — ver `analytics.md`).

### Frontend

`InvoiceSerializer` expone `credit_notes` **solo en el detalle** (flag de context
`with_credit_notes` en `InvoiceDetailView` + prefetch `credit_notes__refund_payments__reversals`)
para no incurrir N+1 en la lista. Cada NC trae `{public_id, total_refunded,
reason_code, reason_notes, issued_at, reversed}` (`reversed` = todos sus
`RefundPayment` tienen contra-asiento).

UI en `pages/billing.jsx` (`RefundModal`, gateada por `can('billing.refund')`):
- Botón **Devolver** en el detalle de una factura `paid`.
- Por concepto: cantidad/monto a devolver + destino (`restock|discard`, solo para
  presentaciones de inventario). Total a devolver = Σ montos seleccionados.
- Editor de reembolso (`PaymentLinesEditor`, exacto) que debe igualar el total.
- `reason_code` (debe coincidir con `CREDIT_NOTE_REASON_CODES`) + notas.
- `X-Idempotency-Key` por intento (anti doble-reembolso en reintento de red).
- Las NC emitidas se listan en el detalle con acción **Revertir** (contra-asiento;
  no se borran). El backend valida over-refund y responde con mensaje claro.

API: `refundInvoice` / `reverseCreditNote` en `api/billing.js`.

## Calculo de totales

El total se calcula siempre en backend. El flujo es:

```
InvoiceItem.save() → self.invoice.recalculate_totals()
```

`recalculate_totals()` usa `all_objects` (bypass de tenant filter) porque puede correr desde signals.
Suma los subtotales vía agregado SQL (`aggregate(Sum('subtotal'))`), no iterando/instanciando filas en Python — recalc se llama una vez por `InvoiceItem.save()`, evita O(n) objetos por llamada. El `.update()` setea `updated_at` explícito (auto_now no aplica en `queryset.update()`).
Los campos `subtotal`, `tax_amount` y `total` son `read_only` en el serializer — el cliente no puede enviar estos valores.

`InvoiceItem.save()/.delete()` emiten warn `INVOICEITEM_MUTATION_OUTSIDE_ATOMIC` si corren fuera de `transaction.atomic()` (observabilidad, no bloqueante). Toda mutación concurrente de ítems debe sostener `select_for_update()` sobre la Invoice — verificado por `test_invoice_concurrency` (assert del valor del total, no solo del count).

## Concurrencia y atomicidad

Al agregar un `InvoiceItem` con presentacion de inventario:

```python
with transaction.atomic():
    locked_pres = Presentation.objects.select_for_update().get(pk=presentation.pk)
    if locked_pres.stock < quantity:
        raise ValidationError("Stock insuficiente")
    serializer.save(...)  # InvoiceItem.save() → recalculate_totals() dentro del mismo atomic
```

El `unit_price` se copia en este mismo momento desde `locked_pres.sale_price`.

Al agregar un item de servicio, tambien corre dentro de `transaction.atomic()` para garantizar que `recalculate_totals()` no quede desincronizado si falla.

`pay_invoice`, `confirm_invoice`, `cancel_invoice` y `pay_direct_sale` viven en
`billing/services.py` y usan `select_for_update()` + `@transaction.atomic`
para evitar transiciones concurrentes. La view `pay_invoice` y `direct_pay_invoice`
son solo wrappers delgados al service respectivo (single authoritative writer
del anchor `paid_at`, ver ADR p9 y ADR p11).

### Orden global de locks (ADR p12)

Para prevenir deadlocks en operaciones que tocan múltiples tablas, se estableció un orden estricto:

```
MedicalRecord → Invoice → Presentation → InvoiceItem → MedicalRecordProduct
```

Reglas:
- Si un flujo no toca alguno, empieza en el primero que sí necesita.
- No se permiten inversiones de orden bajo ninguna circunstancia.
- Los locks se mantienen hasta el commit/rollback de la transacción.

**Implementación en `cancel_invoice()`:**

```python
@transaction.atomic
def cancel_invoice(invoice, user, notes=''):
    # Re-fetch con lock para evitar doble cancelación
    invoice = Invoice.objects.for_organization(
        invoice.organization
    ).select_for_update().get(pk=invoice.pk)
    
    if invoice.status == 'paid':
        raise ValidationError(...)
    
    # Lockear Presentations en orden estable por pk antes de reversar stock
    locked_presentations = _lock_presentations(
        item.presentation_id for item in items if item.presentation_id
    )
    for item in items:
        if item.presentation_id:
            apply_stock_movement(
                presentation=locked_presentations[item.presentation_id],
                quantity=item.quantity,
                movement_type='in',
                ...
            )
```

**Implementación en `get_or_create_invoice_for_medical_record()`:**

```python
@transaction.atomic
def get_or_create_invoice_for_medical_record(medical_record):
    # Re-fetch MR con lock — este helper es ahora la autoridad central
    medical_record = MedicalRecord.objects.for_organization(
        medical_record.organization
    ).select_for_update().get(pk=medical_record.pk)
    
    # ... lógica de get_or_create ...
    
    # Retornar invoice ya lockeada
    return Invoice.objects.for_organization(org).select_for_update().get(pk=invoice.pk)
```

Ver ADR `2026-05-16-p12-concurrency-lock-order-hardening.md` para detalles completos.

### Convención de mutación de `InvoiceItem.quantity` (ADR p13)

**Regla:** TODA mutación numérica contable de `InvoiceItem` (actualmente `quantity`) DEBE usar `F('field') ± delta` vía `update()`, **incluso cuando el caller posee `select_for_update()` sobre el item**. Está prohibido `item.quantity += delta; item.save()`.

Razones:
- Consistencia con `apply_stock_movement` para `Presentation.stock` (mismo tipo de campo numérico contable).
- Defense-in-depth: si un bug futuro pierde el lock, F() sigue siendo atómico a nivel SQL.
- Single round-trip a la DB para la mutación core (subtotal/total se recomputan después).

**Helper único:** `apps.billing.services.apply_invoice_item_quantity_delta(item, delta)`.

```python
from apps.billing.services import apply_invoice_item_quantity_delta

# Incremento (item ya lockeado con select_for_update())
apply_invoice_item_quantity_delta(item, +quantity)

# Decremento — proyección previa para decidir delete vs update
projected = item.quantity - decrement_amount
if projected <= 0:
    item.delete()
else:
    apply_invoice_item_quantity_delta(item, -decrement_amount)
```

El helper internamente:
1. `InvoiceItem.all_objects.filter(pk=...).update(quantity=F('quantity') + delta)`
2. `refresh_from_db(fields=['quantity'])`
3. Recompute `subtotal` reutilizando `money`, `discount_amount`, `line_subtotal` (mismos helpers que `InvoiceItem.save()` — no diverge del cálculo canónico)
4. `update(subtotal=...)` + `recalculate_totals()` sobre la invoice

Lanza `ValidationError` si la cantidad resultante es `<= 0` (caller debe usar `item.delete()` directamente en ese caso). Ver ADR `2026-05-16-p13-day12-concurrency-remediation.md`.

### Tenant filter en re-fetch de services públicos (ADR p13)

Los 4 services públicos (`confirm_invoice`, `cancel_invoice`, `pay_invoice`, `pay_direct_sale`) re-lockean la invoice al inicio con `for_organization()` aplicado:

```python
invoice = Invoice.objects.for_organization(
    invoice.organization
).select_for_update().get(pk=invoice.pk)
```

Defense-in-depth: incluso si un caller futuro pasa una `Invoice` resuelta sin tenant filter (e.g. mgmt command, webhook), el service aplica el filtro de organización antes de mutar estado/anchors.

### Tenant validators en `InvoiceSerializer` (ADR p14 — Día 3)

`InvoiceSerializer` valida que los 4 FKs (`owner`, `pet`, `appointment`, `medical_record`) pertenezcan a la organización del `request.user`. Antes de Día 3, un FK cross-org provocaba HTTP 500 (la única defensa era `Invoice.clean()` que levanta `django.core.exceptions.ValidationError`, no mapeada por DRF).

```python
def validate_pet(self, pet):
    return _validate_same_org(pet, self._get_request(), 'pet', 'InvoiceSerializer')
```

**Helper local `_validate_same_org`** (no promovido a `apps/core/` — ver [deuda A1](../deuda/fase2-prioridad-alta.md#a1)):
- Centraliza el chequeo `obj.organization_id != request.user.organization_id`.
- Emite `TENANT_VALIDATION_REJECTED` (WARNING, logger `apps.tenant_validation`) — evento separado de `TENANT_MISMATCH_DETECTED` (ERROR, object-level attacks) para no saturar la señal operacional.
- Maneja `None` (FKs opcionales).
- Acceso defensivo a `request` via `_get_request()` (patrón `.get('request') + assert` — ver memoria `feedback-serializer-context-access`).

**`Invoice.clean()` se mantiene como app-side defense-in-depth** (legacy residue). Migración futura → service-layer + DB CHECK constraint, ver [deuda A2](../deuda/fase2-prioridad-alta.md#a2).

### PATCH parcial corregido (Fix 4 ADR p14)

`InvoiceSerializer.validate()` ahora resuelve `owner`/`pet` con fallback al `self.instance` cuando el field no está en el payload:

```python
owner = data.get('owner', getattr(self.instance, 'owner', None))
pet = data.get('pet', getattr(self.instance, 'pet', None))
```

Antes de Día 3, PATCH minimalistas como `{"notes": "x"}` retornaban 400 "La mascota es requerida" aunque la invoice tuviera `pet` cargado.

**Comportamiento preservado / actualizado (ADR p25):**
- CREATE `consultation` sin `pet` → **400** (el acto clínico exige paciente).
- CREATE `direct_sale` sin `pet` → **201** (ADR p25; mascota opcional). Antes era
  400 para owner no-genérico.
- CREATE con `owner` generic → sigue forzando `direct_sale`.
- CREATE `direct_sale` con `pet` cuyo owner ≠ owner de la factura → **400** (guard
  de integridad p25, solo cuando `pet` está en el payload).
- PATCH `{"pet": null}` explícito sobre `consultation` → 400.
- PATCH `{"notes": "x"}` sobre invoice con pet → 200 (Fix 4).

## Validacion de stock en serializer

Antes de intentar crear el item se valida en el serializer:
- `presentation.stock <= 0` → error inmediato
- `quantity > presentation.stock` → error inmediato con mensaje descriptivo

Esto evita que el error llegue hasta `confirm_invoice` cuando ya se habian hecho otras operaciones.

## Relacion con historial clinico

La consulta y la factura son dominios distintos.
Ver ADR `2026-04-25-cierre-consulta-explicito.md` y `2026-04-26-receta-no-es-factura.md`.

Regla critica: **una consulta con factura asociada no puede eliminarse**.
`MedicalRecordDetailView.destroy` verifica `Invoice.objects.filter(medical_record=instance).exists()` y retorna `403` si existe.

## Servicios

Los servicios son el catalogo de procedimientos cobrados en consulta (Consulta, Vacuna, Cirugia, etc.).

Reglas:
- gestionados desde `/config` por administradores
- el nombre se normaliza a `title case` al guardar
- un servicio en uso en una `MedicalRecordService` esta protegido con PROTECT (no puede eliminarse)

## Sugerencias de receta y dispensación (ADR p30)

Ver ADR `2026-04-26-receta-no-es-factura.md` y `2026-05-28-p30-receta-dispensacion-venta-directa.md`.

Reglas base (sin cambio):
- una receta médica NO descuenta stock por sí misma
- una sugerencia NO implica venta automática
- recepción decide qué dispensa según lo que el cliente efectivamente lleva

**Exposición (`InvoiceSerializer`, solo en detalle vía flag `with_prescription_suggestions`
— `InvoiceDetailView`, NO en la lista para evitar N+1):**
- `prescription_public_id` — receta de la consulta vinculada (para dispensar).
- `prescription_suggestions` — por ítem recetado: `prescription_item_id`, `product_name`,
  `dose`, `prescribed_quantity` (= `suggested_quantity`, legacy), `dispensed_quantity`,
  `remaining_quantity`, `base_unit` (display) y `presentations[]` (`id`, `name`,
  `sale_price`, `stock`, `conversion_factor`). Las cantidades de receta están en
  **unidades base** del producto (ADR p31); `dispensed_quantity` suma las líneas
  activas de ESTA factura con FK de dispensación (`quantity × conversion_factor`).
  Recepción **elige** la presentación de venta (Product puede tener varias).
- `InvoiceItem.dispensed` (bool) — `True` si la línea es un producto dispensado de la
  receta (la UI la etiqueta "para llevar").

**Dispensación = líneas en la MISMA factura de consulta (no se crea factura aparte):**
lo que el cliente decide llevar se agrega como `InvoiceItem` a la factura `consultation`,
marcado con `InvoiceItem.dispensed_from_prescription_item`. Ese FK es el **discriminador
de la ruta única de stock**: al **confirmar** la consulta, `_confirm_locked_invoice`
(vía `_items_settling_stock`) descuenta SOLO los ítems dispensados; los insumos
sincronizados desde `MedicalRecordProduct` ya descontaron al consumirse. No hay segunda
función de stock.
- Endpoint `POST /api/billing/prescriptions/<uuid>/dispense/`, body
  `{lines:[{presentation, quantity, prescription_item}]}` (recepción elige; "quitar" =
  no incluir, no-op). Devuelve la factura de consulta actualizada (200).
- Service `billing.services.dispense_prescription_into_invoice`: resuelve la factura de
  consulta (debe estar `draft`), agrega/acumula cantidades por presentación
  (`unique_together(invoice, presentation)`), **no mueve stock** — eso ocurre al confirmar.
  Si la presentación ya existe como insumo (sin FK), rechaza (recepción ajusta a mano).
- **Tope clínico (`_enforce_prescribed_quantity_cap`, ADR p37)**: por ítem de receta,
  `dispensado acumulado + solicitado ≤ PrescriptionItem.quantity`, comparado en
  **unidades base** (`quantity × presentation.conversion_factor`, ADR p31). Aplica por
  llamada y acumulado entre llamadas mientras la factura siga `draft`; agrega entre
  presentaciones del mismo ítem. Exceder → 400 con amparado/dispensado/restante.
  Eliminar una línea dispensada (hard delete del draft) libera el cupo. El cliente
  puede llevar menos de lo recetado; nunca más. El frontend muestra restante y capea
  el input (`máx N` por formato), pero la validación autoritativa es la del service.
- **El cap cubre TODAS las rutas de mutación** (ADR p37):
  - `dispense/` — la cantidad solicitada se **suma** al acumulado.
  - `PATCH items/<pk>/` de una línea dispensada — la cantidad nueva **reemplaza** a la
    vieja: `enforce_dispensed_item_quantity_cap` excluye al propio ítem del acumulado
    (`exclude_item_id`). Sin esto, editar la línea bypaseaba el tope.
  - `POST items/` en factura `consultation` **rechaza ítems de presentación** (400):
    los productos solo entran por insumos (MedicalRecordProduct) o dispensación; un
    ítem manual no liquidaría stock al confirmar (`_items_settling_stock` lo ignora)
    → se cobraría sin descontar inventario. Servicios sí se permiten manualmente.
- Producto `requires_prescription`: la receta interna ES el respaldo legal → NO
  crea `ExternalPrescriptionAttestation` (ADR p26, que cubre venta SIN receta
  previa). Gate de permiso `billing.rx_dispense` en la view.
- Frontend: panel "Receta — dispensar" en el detalle del cobro (`PrescriptionDispensePanel`),
  solo visible mientras la factura está en `draft`; al dispensar refresca esa misma factura.

## Frontend — IDs en llamadas a la API

Los endpoints de facturas usan `public_id` (UUID) en las URLs. El frontend debe usar siempre `invoice.public_id`, no `invoice.id` (entero), al construir llamadas a la API:

```javascript
// Correcto
confirmInvoice(invoice.public_id)
addInvoiceItem(invoice.public_id, payload)

// Incorrecto — falla cuando ALLOW_LEGACY_ID_LOOKUP=False
confirmInvoice(invoice.id)
```

El campo `invoice.id` (entero) puede mostrarse en la UI como numero de referencia ("Cobro #123") pero no debe usarse en URLs de API.

## Frontend — página de Cobros (auditoría 2026-06-11, Fases 2-3)

`frontend/src/pages/billing.jsx` quedó alineada al design system (ver
`frontend/design-system.md`):

- **Tabla**: clases globales `.table-wrap` + `.table` + `.table-footer` con conteo.
  `.tableCompact` (anti-patrón §6) fue eliminado — no reintroducir tablas por módulo.
- **Orden**: client-side por Fecha/Total con `components/SortHeader.jsx` (compartido;
  el listado no está paginado y el backend ordena `-created_at` por defecto).
- **Filtros**: selects `.select-input` canon; "Limpiar" solo visible con filtros
  activos. **Regla**: un evento que actualiza varias claves de filtro (DateRangePicker
  → `created_from` + `created_to`) usa UN solo setState con patch (`updateFilters({})`)
  — dos llamadas consecutivas a un setter por clave leen estado stale y la segunda
  pisa a la primera (bug corregido en `42836f3`).
- **Feedback de fetch**: estado `fetching` (guard con `requestIdRef`) atenúa la tabla,
  el footer muestra "Actualizando..." y el empty-state "Buscando cobros...". El catch
  de `loadInvoices` no es silencioso (toast con `apiError`).
- **Caja**: chip compacto en el page-header (`CajaBar variant="compact"`); la sesión
  llega vía `onSession` — la página NO hace su propio `getCurrentSession`. La alerta
  bloqueante (`require_open_cash_session` + caja cerrada) se conserva como aviso, sin
  CTA duplicado.
- **Panel de dispensación**: refleja el tope clínico (ADR p37) — "Recetado X · en
  cobro Y · restante Z", `máx N` por formato elegido (`remaining / conversion_factor`),
  filas agotadas deshabilitadas. La validación autoritativa es la del backend.

## Endpoints

Los IDs de invoice e items usan `<uuid>` (public_id), no el PK entero.

| Metodo   | URL                                          | Descripcion                       |
|----------|----------------------------------------------|-----------------------------------|
| `GET`    | `/api/billing/invoices/`                     | Listar facturas                   |
| `POST`   | `/api/billing/invoices/`                     | Crear factura                     |
| `GET`    | `/api/billing/invoices/<uuid>/`              | Detalle con items                 |
| `PATCH`  | `/api/billing/invoices/<uuid>/`              | Editar (solo draft)               |
| `POST`   | `/api/billing/invoices/<uuid>/confirm/`      | Confirmar borrador                |
| `POST`   | `/api/billing/invoices/<uuid>/pay/`          | Registrar pago (requiere confirmed) |
| `POST`   | `/api/billing/invoices/<uuid>/direct-pay/`   | Cobrar venta directa (draft → paid atómico) |
| `POST`   | `/api/billing/invoices/<uuid>/cancel/`       | Cancelar (no aplica a paid)       |
| `POST`   | `/api/billing/prescriptions/<uuid>/dispense/`| Dispensar receta → agrega ítems a la factura de consulta (ADR p30) |
| `GET`    | `/api/billing/invoices/<uuid>/pdf/`          | PDF del cobro (todos los estados) |
| `POST`   | `/api/billing/invoices/<uuid>/items/`        | Agregar item                      |
| `PATCH`  | `/api/billing/invoices/<uuid>/items/<id>/`   | Editar item (solo draft)          |
| `DELETE` | `/api/billing/invoices/<uuid>/items/<id>/`   | Eliminar item (solo draft)        |
| `GET`    | `/api/billing/services/`                     | Listar servicios                  |
| `POST`   | `/api/billing/services/`                     | Crear servicio                    |
| `PATCH`  | `/api/billing/services/<uuid>/`              | Editar servicio                   |
| `DELETE` | `/api/billing/services/<uuid>/`              | Eliminar servicio                 |
| `GET`    | `/api/organizations/settings/`               | Ver configuracion de flujo        |
| `PATCH`  | `/api/organizations/settings/`               | Editar toggles de flujo (ADMIN)   |

## PDF del cobro (ADR p36)

`GET /api/billing/invoices/<uuid>/pdf/` — permiso `invoice.retrieve`, disponible en
todos los estados (incluido `draft`). Generado con la capa compartida `apps/core/pdf/`
(membrete, "Página N de M", tabla de ítems y bloque de totales con el tema del sistema).

- **Watermark por estado**: `draft` → "BORRADOR", `cancelled` → "CANCELADO" (diagonal,
  alpha bajo). Un borrador impreso no debe poder pasar por comprobante final. `confirmed`
  y `paid` no llevan marca.
- **Fechas** (creado/confirmado/pagado/cancelado) en timezone de la org.
- **Nombre de descarga**: `factura_<id>_<mascota>_<YYYY-MM-DD>.pdf` (sin mascota →
  `sin-mascota`). Depende de `CORS_EXPOSE_HEADERS=['content-disposition']`.
- El restyle no agrega queries: el test N+1 del endpoint usa `assertNumQueries`
  estricto — `get_theme_for_organization()` debe seguir sin tocar DB.

## Filtros disponibles (GET /api/billing/invoices/)

- `owner=<id>` — por propietario
- `pet=<id>` — por mascota
- `status=<estado>` — por estado
- `paid_on=YYYY-MM-DD` — facturas pagadas ese dia (ajustado a timezone de la org)
- `created_on=YYYY-MM-DD` — facturas creadas ese dia (ajustado a timezone de la org)

**Orden**: la lista ordena por `-created_at` (más reciente primero) vía
`.order_by('-created_at')` **explícito** en el queryset. Es obligatorio: el
`.annotate(Sum('payments__amount'))` del ledger (ADR p27) descarta el
`Meta.ordering` del modelo (`query.order_by` queda vacío → orden de heap del DB).
No quitar el `order_by` sin reemplazo.

## Audit log

Cada cambio de estado genera un `InvoiceAuditLog` con:
- `previous_status` / `new_status`
- `changed_by`
- `notes` — campo opcional sanitizado (max 255 caracteres)

## Atajos de teclado

| Atajo | Acción | Contexto |
|-------|--------|----------|
| `F11` | Navegar al Punto de Venta (`/pos`, ADR p38) | En `/billing`, sin el detalle abierto, si el usuario tiene `invoice.create` |
| `Shift+F11` | Idéntico a F11 (`e.key === 'F11'` no distingue Shift) | Misma funcionalidad |

El atajo bloquea el comportamiento nativo del navegador (fullscreen) via `preventDefault()`.
El botón "+ Cobro" muestra un badge `F11` como recordatorio visual.
