# Decisiones y transición

Rigen las decisiones cerradas del [plan](../../plan-remediacion-orden-4-2026-10-30.md). B7 compara las mismas cantidades y valoración comercial que muestra la tabla. Los empates conservan el orden de entrada.

En curso: serializers normalizan presencia explícita; 0028 amplía alias a 12/4 y 0029 copia exclusivamente desde factores válidos, deteniendo la migración ante inválidos. El alta manual positiva usa el writer en la transacción y se rechaza stock inicial sin lote para productos que los requieren. Importación propaga solo el código demo específico. No se acredita aún cobertura de todos los writers ni de todas las regresiones. Las decisiones y límites detallados permanecen en el plan.

Continuación r2: se agregó `ImportConflict`, relacionado al job y sustituido bajo su lock; escrituras por lotes de 100, muestra máxima 100 y publicación de metadatos en la misma transacción. Un mapping invalida el reporte anterior y mantiene errores bloqueantes previos. Lecturas usan cursor firmado asociado a job, versión y tamaño. Un resultado legacy se convierte desde su JSON al solicitarlo y se marca incompleto si su contador supera los detalles disponibles; nunca se recalcula desde el catálogo. La UI expone páginas para preview y resultado. Está pendiente probar todos los casos de aceptación y la transición de rollback.

Continuación posterior: `imports.0004` proporciona puente inverso al JSON legacy antes de revertir 0003 y comprueba integridad del conteo disponible. El servicio de commit vuelve a comprobar bloqueantes tras adquirir el lock. El alta de presentación adicional con stock positivo utiliza el writer; el PATCH no asigna stock.

Si falla o se pierde la respuesta de recepción inicial de lotes, el wizard no afirma que falló la escritura remota ni reenvía automáticamente; pide revisar movimientos y lotes. Esto no convierte el endpoint de recepción en idempotente.

## Continuación 01-11

`imports.0005` rehidrata desde el JSON restaurado por 0004 cuando la tabla se recreó vacía, mantiene `complete` y acuña nueva versión. Rechaza estados parciales inconsistentes sin consultar catálogo. `inventory.0030` agrega receipt por organización/UUID de operación, vinculado a actor, presentación y hash del payload validado. Con `X-Idempotency-Key`, una repetición idéntica devuelve el resultado confirmado; contenido u objetivo/actor distinto devuelve 409. Las llamadas sin clave conservan el contrato anterior. Receipt y movimiento se escriben en una transacción. El wizard guarda localmente el UUID, producto, presentación y payload antes de enviar y reintenta esa identidad tras recarga. Queda pendiente verificar la recuperación si se pierde por completo el almacenamiento local y la comprobación visual.

### Writers de producción contrastados

| Ruta | Operación | Regla | Evidencia |
|---|---|---|---|
| `inventory/serializers.py::ProductSerializer.create` | Alta manual | stock cero y entrada por writer; alias normalizado | gate paridad y factores en `test_inventory_import.py` |
| `inventory/serializers.py::PresentationCreateSerializer` | Alta/PATCH | un alias normaliza ambos; contradicción rechazada; PATCH no asigna stock | `test_order4_alias.py`, test de presentación en `test_inventory_import.py` |
| `inventory/views.py::PresentationCreateView` | Nueva presentación | entrada positiva por writer, lotes requieren recepción | dos tests de presentación en `test_inventory_import.py` |
| `inventory/admin.py::PresentationAdmin` | Edición | alias solo lectura y sincronizado al cambiar factor | `test_order4_alias.py` |
| `imports/services_inventory.py::_create_product_with_presentation` | Importación/bulk | alias igual a factor, stock cero; writer aplica entrada | gate paridad y suite inventory import |
| `inventory/services.py::apply_stock_movement` | Movimiento | lock de producto, unidades base, ledger y sombra | suite recepción/stock y tests del writer |
| `inventory/views.py::receive_presentation_stock` y `services.py::receive_stock` | Recepción de lotes | identidad opcional, receipt atómico, writer por lote | `ReceptionIdempotencyTests`, `test_order4_reception_concurrency.py` |
| `core/management/commands/seed_demo_clinic.py` | Seed explícito demo | envía ambos aliases iguales y usa writer | inspección estática; no ejecutado en esta entrega |
