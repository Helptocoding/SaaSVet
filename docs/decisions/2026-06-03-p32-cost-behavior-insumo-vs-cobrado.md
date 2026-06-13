# ADR p32: MedicalRecordProduct.cost_behavior — separar consumo clínico de cobro

**Fecha**: 2026-06-03  
**Estado**: Aceptado — implementado  
**Documentos relacionados**:
- ADR p31 (stock en unidades base) — sprint paralelo
- `docs/modules/inventory.md`
- `docs/modules/medical_records.md`
- `backend/apps/inventory/migrations/0017_medicalrecordproduct_cost_behavior.py`

## Contexto

En una clínica veterinaria, ciertos productos se **consumen durante la consulta** (jeringas, gasas, solución fisiológica) pero **no se le cobran al cliente**. Sin embargo, sí descontaban stock.

El sistema anterior solo tenía la dimensión "agregado al InvoiceItem" vs "no agregado", pero no modelaba explícitamente la intención de "consumido como insumo" vs "cobrado al cliente".

Síntomas antes del cambio:
- La recepcionista tenía que eliminar jeringas del cobro manualmente después de que el médico las registraba en la consulta.
- El médico a veces no registraba insumos para evitar que se cobraran, perdiendo trazabilidad.
- No había forma de auditar qué se consumió clínicamente vs qué se cobró.

## Decisión

Agregar campo `cost_behavior` a `MedicalRecordProduct`:

```python
COST_BEHAVIOR_CHOICES = [
    ('charge', 'Cobrar al cliente'),
    ('included', 'Insumo incluido (no cobrar)'),
]
cost_behavior = models.CharField(max_length=20, default='charge')
```

### Reglas de negocio

- `'charge'`: el producto se refleja en `InvoiceItem` (comportamiento anterior)
- `'included'`: el producto descuenta stock (consumo real) pero NO se refleja en `InvoiceItem`
- Una vez guardado, `cost_behavior` es **inmutable** — si ya hay una factura draft con ese ítem, cambiar comportamiento retroactivo causaría inconsistencias
- Default en el stepper de consulta: `'included'` — así el médico puede agregar insumos sin riesgo de cobrarlos accidentalmente. Si quiere cobrar, activa explícitamente.

### Gate en la view

```python
effective_cost_behavior = existing_mrp.cost_behavior or request_cost_behavior
if invoice.status == 'draft' and effective_cost_behavior == 'charge':
    _sync_invoice_item(...)   # solo para 'charge'
```

### Frontend: toggle en ConsultationStepper

Botones `[Insumo | Cobrar]` en la línea de cada producto, con default `'included'`.  
`prodsTotal` filtra solo `cost_behavior !== 'included'` para el total de cobro.

### Backend: CheckConstraint

```python
models.CheckConstraint(
    condition=models.Q(cost_behavior__in=['charge', 'included']),
    name='medicalrecordproduct_cost_behavior_valid'
)
```

## Consecuencias

**Positivas:**
- Médico registra todos los insumos sin miedo a cobros accidentales
- Trazabilidad completa: qué se usó (stock) vs qué se cobró (factura)
- TimelineCard muestra badge `insumo` / `cobrado` por producto

**Invariante crítico:**
Stock siempre se descuenta al agregar el MRP, independientemente de `cost_behavior`.  
`cost_behavior` solo controla si se genera `InvoiceItem`, no el movimiento de stock.
