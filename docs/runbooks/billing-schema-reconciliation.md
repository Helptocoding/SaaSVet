# Runbook — reconciliación de schema Checkout/Billing

## Alcance

Este procedimiento converge una instalación nueva y una base existente que haya
registrado la segunda `billing.0026` sin ejecutar todo su DDL. No usa `--fake` y
no agrega datos dummy. Las migrations contractuales son:

- `billing.0033`: preflight, reparación de anchors e índices/UNIQUE faltantes.
- `billing.0034`: retiro forward-only de `confirmed_at*` e índice legacy.
- `inventory.0025`: factor comercial positivo y representable.
- `inventory.0026` y `billing.0035`: snapshots inmutables de conversión y retornos
  por cada asignación física multi-lote.

## Antes del despliegue

1. Tomar backup verificable y registrar el identificador del snapshot.
2. Ejecutar `python manage.py showmigrations billing inventory`.
3. Ejecutar `python manage.py audit_billing_schema --json`. En una base todavía
   divergente puede fallar; conservar el JSON como evidencia pre-fix.
4. Confirmar que no existan duplicados para los UNIQUE que `0033` instalará. La
   propia migration vuelve a comprobarlo y aborta sin deduplicar.
5. Programar la migration contract `0034` sólo después de validar el backup. Su
   reverse falla deliberadamente: recrear columnas vacías no restaura provenance.

## Ejecución

```text
python manage.py migrate --no-input
python manage.py audit_billing_schema --json
python manage.py makemigrations --check --dry-run
```

Resultado requerido del gate:

```json
{"violations": 0, "ok": true}
```

`0033` es `atomic=False` para permitir índices concurrentes en instalaciones ya
existentes. Sus preflights terminan antes del contract destructivo. Si detecta
anchors, sources o duplicados no reconciliables, detener el despliegue y corregir
la evidencia de dominio explícitamente; no marcar la migration como aplicada.

## Validación

- Verificar que `billing_invoice` no contenga `confirmed_at` ni
  `confirmed_at_source` y que no exista `idx_inv_org_status_conf`.
- Verificar `idx_inv_org_status_post` y los tres UNIQUE de hijos de
  `CommandReceipt`.
- Verificar los snapshots y CHECKs de `CheckoutItem`, `InvoiceItem` y
  `MedicalRecordProduct`.
- Verificar los UNIQUE `(credit_note_item, allocation)` de devoluciones multi-lote.
- Ejecutar el smoke `Checkout ready -> pay -> Invoice/Payment/stock` y las pruebas
  de disponibilidad/FEFO/refund/void.

## Rollback

- Antes de `0034`, una falla de `0033` es recuperable corrigiendo datos y
  reintentando; sus operaciones son idempotentes.
- Después de `0034`, el rollback es restaurar el backup completo o desplegar una
  nueva migration forward. No ejecutar el reverse de `0034` ni reconstruir
  `confirmed_at_source` con valores inventados.
- `0035` conserva snapshots derivados de la evidencia física cuando existen
  `StockAllocation`; no deben recalcularse desde el catálogo durante un rollback.

## Regla operativa permanente

No se reemplaza ni elimina una migration ya desplegada. Cualquier uso excepcional
de `--fake` requiere ticket, DDL equivalente demostrado, inventario de entornos y
el gate de schema verde antes y después.
