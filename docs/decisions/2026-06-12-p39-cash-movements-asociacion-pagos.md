# ADR p39: Caja para POS — asociación incondicional de pagos y movimientos manuales

**Fecha**: 2026-06-12
**Estado**: Aceptado — implementado (FASE 0 del plan Caja/POS)
**Documentos relacionados**:
- ADR p28 (CashSession / cierre Z)
- ADR p29 (refunds en el cuadre de efectivo, snapshot v2)
- ADR p38 (POS pantalla dedicada)
- DD-003 (versionado del Z), DD-004 (Register/Terminal, sigue diferida)
- `docs/system-module-operations.md` §8

## Contexto

La auditoría Caja/POS (2026-06-12) encontró dos gaps críticos para operar un
POS real:

1. **Asociación pago→sesión condicionada al toggle.**
   `_resolve_cash_session_for_payment` retornaba `None` sin buscar la sesión
   cuando `require_open_cash_session=False` (el default). Resultado: con caja
   abierta y toggle apagado, todo `Payment` quedaba `cash_session=NULL` → el
   cierre Z reportaba $0 ventas y una diferencia falsa por el total vendido.

2. **Sin movimientos manuales del cajón.** Un retiro a banco a mitad de turno
   (caja $1000 + ventas $3000 − retiro $2000) producía un faltante falso de
   $2000 en el Z: el sistema esperaba $4000 contra $2000 contados.

## Decisión

### 1. Asociación ≠ obligatoriedad

```
¿Actor tiene caja abierta?  → el pago/refund/reversal se asocia SIEMPRE.
¿No tiene caja abierta?     → toggle ON: 400; toggle OFF: pago sin sesión.
```

El toggle `require_open_cash_session` queda solo como regla de **bloqueo**, no
de asociación. El lock de CashSession sigue siendo la cabeza del orden global
(sin ABBA con el cierre). Aplica a `pay_invoice`, `pay_direct_sale`,
`process_refund` y `reverse_credit_note` (todos pasan por el mismo resolver).

Para la clínica beta, además, el toggle se activa (`True`) — decisión operativa,
ya aplicada en dev; en producción se activa vía `/config` (toggle de ADMIN).

### 2. `CashMovement` — entrada / retiro / gasto

Modelo nuevo (`apps/cash/models.py`), consistente con los invariantes:

- `movement_type ∈ {deposit, withdrawal, expense}`; **`amount > 0` siempre**
  (CHECK en DB + full_clean) — el signo lo da el tipo (invariante #4).
- **Append-only** (invariante #3): sin PATCH/DELETE; corrección =
  contra-movimiento. `occurred_at` `editable=False`; `actor` server-side.
- FK `cash_session` PROTECT; solo efectivo por definición (es el cajón físico).
- Writer único `register_cash_movement()` en `cash/services.py`: lockea la
  CashSession → serializado contra el cierre Z (ningún movimiento se cuela
  después del conteo, mismo mecanismo que los pagos).
- Permisos nuevos `cashmovement.create` / `cashmovement.list` (ADMIN, VET,
  ASSISTANT — mismo criterio que `cashsession.*`).
- Endpoint: `GET|POST /api/cash/movements/` (GET sin params = caja abierta del
  actor; `?session=<public_id>` = histórico por sesión).

### 3. Cierre Z v3 (`REPORT_SCHEMA_VERSION = 3`)

```
expected = opening_float
         + Σ Payment cash            (del turno)
         − Σ RefundPayment cash
         + Σ RefundReversal cash
         + manual_in   (deposits)
         − manual_out  (withdrawals + expenses)
```

El `closed_snapshot` agrega: `manual_in`, `manual_out`, `movements_by_type`,
`movements_count`. Los Z v1/v2 congelados **no se reinterpretan** (DD-003); el
frontend solo muestra las líneas nuevas cuando existen en el snapshot.

### 4. UI mínima

`CajaBar` (full y compact): botón **Movimiento** con caja abierta → modal
tipo `(+) Entrada | (−) Retiro | (−) Gasto` + monto + motivo (obligatorio).
`ZReport` (/cash): líneas "Entradas manuales" / "Salidas manuales" antes del
esperado.

## Consecuencias

- El Z cuadra con la operación real (toggle on u off) y soporta retiros
  intra-turno — desbloquea el POS para beta.
- Migración `cash.0002_cashmovement`: tabla nueva, aditiva, sin tocar datos.
- Tests: 30/30 cash (incluye el escenario 1000+3000−2000=2000, snapshot v3,
  rechazo post-cierre, CHECK en DB, cross-tenant) + 134/135 billing (el fallo
  restante es preexistente en walk-in/appointments, ajeno a este cambio).
- Pendiente (sin cambio): DD-004 Register/Terminal para cajón compartido
  multi-usuario; gate "solo efectivo" (Opción B) como refinamiento post-beta.
