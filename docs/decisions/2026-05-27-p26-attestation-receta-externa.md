# ADR p26: Attestation de receta externa en caja

**Fecha**: 2026-05-27
**Estado**: Aceptado (diseño) — implementación independiente (Sprint A-adyacente), sin código aún
**Documentos relacionados**:
- ADR `2026-04-26` (receta no es factura), `2026-05-09-p9` (anchor governance), `2026-05-20-p18`/`p24` (IDs)
- `docs/deferred-decisions.md` — `DD-005`
- `docs/modules/medical_records.md` (Prescription), `docs/modules/inventory.md` (`requires_prescription`)

## Contexto

`Product.requires_prescription=True` bloquea la venta salvo vía `MedicalRecordProduct` con
`Prescription` activa en la consulta. En `direct_sale` no hay consulta → bloqueo total. Pero
el retail veterinario a veces vende un producto con receta cuando el cliente **presenta una
receta externa válida**. Hay que permitirlo con **trazabilidad legal**, sin bypass inseguro.

## Decisión

### 1. Modelo `ExternalPrescriptionAttestation` (billing, append-only)

**Público** (`PublicIdMixin`, solo `public_id`, ADR p24). Campos: `invoice` (FK PROTECT),
`presentation` (FK PROTECT), `quantity`, `attested_by` (= `request.user`, **server-side**),
`attested_at`, `prescriber_name` (sanitizado `max_length=255`), `prescription_folio`
(opcional `max_length=100`), `notes` (`max_length=5000`). `organization` desde día 0.
**Sin PATCH/DELETE.**

Por qué un modelo y no un booleano: la trazabilidad regulatoria exige *quién* autorizó,
*cuándo*, y *referencia de la receta presentada*. Un checkbox en el JSON desaparece; una fila
append-only con actor + timestamp es el único registro auditable.

### 2. NO relajar `requires_prescription`, NO fabricar clínica

El flag clínico se mantiene. **No** se crea `MedicalRecord`/`Prescription` placeholder para
satisfacer la validación (basura clínica que contamina `prescriptions_issued`, dashboard
§3.3.6; mismo rationale que generic-client rechazó owners placeholder). La attestation es un
evento de **retail**, separado del dominio clínico (respeta "receta no es factura").

### 3. Gate autoritativo en service

Al agregar un `InvoiceItem` de presentación con `requires_prescription` a una factura
`direct_sale`: el service exige una attestation en el mismo `atomic()` bajo lock de Invoice
(orden global) y Presentation (stock); si falta → **400 `code='prescription_required'`**. El
checkbox del frontend es UX; el gate real vive en el service.

### 4. RBAC

Permiso `billing.rx_dispense` (default ADMIN + VET) — boundary de autorización real
(dispensar controlados). Requiere `seed_permissions` en deploy (regla CLAUDE).

### 5. Retención y datos personales

- **Append-only, sin DELETE** (mismo class legal que `VaccineRecord` 405 / `MedicalRecord.pet`
  PROTECT, NOM-007/046). Retención mínima = periodo NOM aplicable (**confirmar**; ~5 años como
  expediente).
- **LFPDPPP**: `prescriber_name` es PII de un tercero (médico que no es usuario). Base lícita
  = obligación regulatoria de dispensación; la retención debe estar acotada y justificada por
  esa obligación, no "para siempre".
- Estrategia futura archival/WORM = `DD-005`.

### 6. Analytics

Sin anchor en v1. La venta es un `InvoiceItem` normal → `revenue_paid` ya la cuenta. Una
métrica futura ("controlados dispensados/día", anchor `attested_at`) entra por gobernanza
`ANCHOR_REGISTRY` (ADR p17), no ad-hoc.

### 7. Ciclo de vida

La attestation **permanece** si la factura se cancela o se reembolsa (registro legal
append-only); el stock revierte por su cuenta.

## Alternativas consideradas

1. **Flip `requires_prescription=False`** — descartada. Destruye la salvaguarda clínica.
2. **Toggle org "permitir Rx sin receta"** — descartada. Bypass silencioso, destruye
   trazabilidad.
3. **Reusar `Prescription`** — descartada. Es clínico (OneToOne a `MedicalRecord`, requiere
   `pet`); fabricar uno genera basura y contamina métricas clínicas.
4. **Gate solo en frontend** — descartada. El frontend es UX; el backend es autoridad.

## Consecuencias

Positivas:
- Venta de Rx con receta externa legalmente trazable, sin bypass.
- Dominio clínico intacto (sin basura).
- Audit de quién autorizó cada dispensación.

Costos:
- Permiso RBAC nuevo (requiere `seed_permissions`).
- Carga de cumplimiento (retención NOM + LFPDPPP) a documentar y, eventualmente, WORM
  (`DD-005`).

## Relación con otros ADRs

receta-no-es-factura (separación clínica), p9 (anchor governance diferida), p18/p24
(public_id, sin dual `id`+`public_id`). Independiente del financial event model — no toca el
contrato de eventos monetarios. Hook `DD-005` en `deferred-decisions.md`.
