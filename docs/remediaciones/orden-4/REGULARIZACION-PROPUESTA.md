# Regularización: propuesta pendiente

Hay diagnóstico preliminar reproducible en `apps.inventory.stock_diagnostics` y comando `prepare_stock_review --organization-public-id UUID --product-public-id UUID`, probado únicamente con fixtures sintéticos; la lectura de datos reales requiere autorización posterior. No hay aprobaciones. `no_baseline` significa cobertura insuficiente, no drift demostrado; un `in` inicial no constituye por sí mismo el adjustment base que busca el auditor actual. Un ajuste por lote no es automáticamente baseline absoluto del producto.

La propuesta incluye hash del ledger, saldos, presentaciones, cobertura, ambigüedades y campos de aprobación vacíos. El hash no sustituye la futura revalidación bajo locks de saldo, organización y lotes. Las pruebas actuales no acreditan todos los casos ambiguos ni la detección transaccional de propuestas obsoletas; preparación todavía parcial.

Desde r2, un adjustment con FK de lote nula pero `lot_number` conservado sigue clasificado como ajuste por lote de delta no verificable; el snapshot participa en el hash. Ver prueba PostgreSQL de SET_NULL en `test_order4_diagnostics.py`.

Pruebas sintéticas adicionales cubren unidades legacy, referencia incompleta, desbalance de lotes y cambio de watermark tras añadir un movimiento. Son pruebas de preparación: no implementan aplicación ni verificación transaccional de aprobación.

`compare_proposal` compara identidad de organización y producto, saldo, unidad, presentaciones, watermark, cobertura, expectativa, suma de lotes y ambigüedades. Cualquier cambio o ambigüedad exige nueva revisión; no crea aprobación ni modifica dominio. Las pruebas son sintéticas; la futura aplicación debe volver a comprobar bajo locks.

La futura propuesta individual debe incluir organización y UUID público, saldo y unidad base observados, presentaciones, watermark de ledger, cobertura, ambigüedades, situación de lotes, acción y efectos esperados; aprobación, actor, fecha y motivo quedan pendientes. Si no se puede reconstruir un delta, clasificar como no verificable.

La eventual reconstrucción desde saldo observado requiere aprobación explícita por producto y revalidación bajo locks de organización, saldo, ledger y lotes; cambios invalidan la propuesta. No volver a sumar el saldo, duplicar aperturas, reparar drift de oficio ni certificar el pasado. No existe una operación apply en esta entrega.

**09-11: sin objeto.** El usuario confirmó que no existen clínicas ni datos reales, así que no hay saldos históricos que regularizar ni aprobaciones que recoger, y la operación apply no se construyó. El diagnóstico se conserva por si algún día se incorpora una base con historia real, y entonces rigen las condiciones de arriba.

Desde el 09-11, `audit_stock_integrity` reconstruye desde 0 los productos sin `adjustment`, así que un producto nuevo con `in` inicial queda auditado. En `diagnose_product`, `no_baseline` conserva su sentido anterior (sin `adjustment` de producto).
