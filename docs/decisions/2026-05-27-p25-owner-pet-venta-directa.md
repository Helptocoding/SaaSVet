# ADR p25: Owner/Pet real en venta directa

**Fecha**: 2026-05-27
**Estado**: Aceptado (diseño) — implementación Sprint A, sin código aún
**Documentos relacionados**:
- ADR `2026-04-28-generic-client-direct-sale.md`, `2026-05-15-p11` (direct-pay), `2026-05-17-p14` (tenant validators), `2026-05-20-p18` (IDs)
- `docs/deferred-decisions.md` — (sin hooks propios; ver nota §customer-assignment)

## Contexto

La venta directa siempre usa el propietario genérico ("Público General"). `Invoice.pet` ya
es nullable y `Invoice.owner` ya acepta cualquier owner — la única barrera es la regla del
`InvoiceSerializer`: *un owner no-genérico obliga `pet`*. Eso bloquea el caso real "cliente
registrado compra alimento sin mascota específica".

## Decisión

### 1. Relajar `pet`-required solo para `direct_sale`

- `invoice_type='direct_sale'`: `pet` **opcional**, independientemente de si el owner es
  genérico o real. `owner` sigue obligatorio (default = genérico).
- `invoice_type='consultation'`: `pet` sigue **obligatorio** (el acto clínico requiere
  paciente). Sin cambio.
- `owner.is_generic=True ⇒ invoice_type` forzado a `direct_sale` (sin cambio).

### 2. Guard de integridad

Si se envía `pet`, validar `pet.owner_id == owner_id` (guard, no constraint de modelo —
mismo patrón que el `owner_id` guard de appointments). Cross-owner mismo org → 400
`code='validation_error'`. Cross-org → ya cubierto por tenant validators (ADR p14,
`TENANT_VALIDATION_REJECTED`). `pet.is_generic` no puede asociarse a un owner real.

### 3. Sin schema, sin migración

`Invoice.pet` ya es nullable; `owner` PROTECT obligatorio se mantiene. Las ventas directas
históricas con genérico siguen válidas (retrocompatible 100%). Cambio = serializer + frontend.

### 4. Frontend

Modal "+ Cobro" (estado local, ADR p11 §4): `Owner` `SearchSelect` opcional (default
genérico vía `GET /owners/?is_generic=true`); `Pet` `SearchSelect` condicional filtrado por
`?owner=<public_id>`. FK body con PK; deep-links/filtros con `public_id` (ADR p18). F11 /
venta anónima intacta si no se elige.

### 5. Customer assignment posterior — diferido

NO en v1, y **nunca sobre una factura `paid`** (reescribiría "ventas por cliente" sin trail;
una factura pagada es hecho contable append-only). Si se necesita: limitar a `draft`
(análogo a `assign-patient` de appointments); para `paid`, vía evento append-only de
re-vinculación auditado, no un swap silencioso de FK. No se crea `DD` porque no hay trigger
de negocio comprometido — se reabre si aparece.

## Alternativas consideradas

1. **Endpoint/flujo "venta con cliente" separado de direct-pay** — descartada. Dual-flow;
   ADR p11 ya rechazó bifurcar por este motivo.
2. **`Invoice.owner` nullable** — descartada (ya rechazada en generic-client ADR): rompe
   reportes por cliente y el FK PROTECT.
3. **Permitir reasignar owner en `paid`** — descartada. Reescribe historia sin auditoría.

## Consecuencias

Positivas:
- Venta directa a cliente registrado (con o sin mascota) con flujo limpio.
- Los filtros `owner=`/`pet=` ahora rinden datos reales.
- Cero impacto analytics (sin bump de `METRICS_SCHEMA_VERSION`).

Costos:
- Ninguno relevante (cambio de validación + UI).

## Relación con otros ADRs

generic-client (owner/pet genérico), p11 (modal direct-pay), p14 (tenant validators), p18
(public_id en frontend). Independiente del financial event model — no toca el contrato.
