# Continuación r2 — Completar el alcance local del orden 4

Fecha: **31-10-2026**. Entregar al agente ejecutor. No autoriza una regularización real ni inicia automáticamente otro chat.

---

Continúa desde el checkout actual de `C:/Users/LAP/Desktop/VeterinariaSaaS` hasta completar el alcance local autorizado del orden 4. Hay dos avances parciales; conserva el código y evidencia válidos. No vuelvas a entregar únicamente un inventario de lo pendiente cuando puedes continuar implementando.

Lee completos:

- `docs/plan-remediacion-orden-4-2026-10-30.md`: contrato de producto, entregas y aceptación.
- `docs/metaprompt-remediacion-orden-4-2026-10-30.md`: ejecución original.
- `docs/remediaciones/orden-4/REVISION-2026-10-31-r2.md`: hallazgo nuevo y límites del contraste.
- El expediente vigente en `docs/remediaciones/orden-4/` y las instrucciones aplicables AGENTS/RTK.

No repitas preguntas ya respondidas. La base habitual, clusters ajenos y VPS siguen excluidos. Solo pruebas/migraciones en PostgreSQL aislado con datos sintéticos. Sin commit/push/PR, despliegue, regularización real o trabajo de otros órdenes. I04/I06 aplazados; I07 requiere aprobación futura por producto para cualquier aplicación real.

## Orden de continuación

### 1. Corregir la clasificación errónea de I07

En `inventory/stock_diagnostics.py`, no deduzcas un adjustment global solo de `lot_id is None`. StockMovement conserva `lot_number` tras SET_NULL de la referencia de lote. Un ajuste por lote con snapshot y FK nula se está clasificando como `absolute_product_baseline` sin ambigüedad.

Añade una regresión significativa que represente ese estado, corrige la interpretación y el watermark pertinente y confirma que no se escribe nada ni se inventan deltas. Un ajuste de lote sin evidencia suficiente debe conservar su condición no verificable; no convertirlo en apertura del producto. La revisión reprodujo la rama con la función real y adaptadores en memoria, no con un test DB de eliminación: completa esa cobertura en PostgreSQL aislado. No amplíes esto a un rediseño del ledger.

### 2. Implementar I03 ahora

I03 no está implementado y no hay un bloqueo técnico acreditado. Entrega código de backend, migraciones justificadas, API y UI del wizard, además de pruebas:

- `result.conflicts` muestra máxima 100; agregados exactos; high + uncertain == skipped_conflicts. Nunca usar `.length` de la muestra como total o para decidir commit.
- Reporte completo estable/versionado por job y ejecución (mapping/preview/commit), detalle mínimo persistido con procesamiento acotado. No acumular todo para cortarlo al responder, perder filas ni recomputar páginas contra el catálogo actual.
- Lectura paginada por public_id/versión, default 50 y máximo 100, orden estable; validación de cursor/versión/tenant/RBAC, sin filtraciones. Publicación atómica de detalle/agregados/versión, invalidación coherente al reemplazar reporte según el contrato.
- Transición legacy desde resultados persistidos sin reimportar, revalidar ni truncar datos antes de conservar detalle accesible. Si falta evidencia histórica, marcarla como tal.
- Preview y resultado con «Mostrando N de M», navegación real al detalle, grupos y totales correctos. No presentar el CSV existente de errores/avisos como reporte completo de conflictos.
- Preservar resultados de importación: dedup skip, filas aceptadas/omitidas, errores bloqueantes, metadatos, atomicidad/savepoints, guards y commit una sola vez. Paginación de lectura no autoriza commits por lote.
- Pruebas: 0/100/101/2000 conflictos, todas las páginas sin pérdida/duplicación, catálogo modificado, errores de tamaño/versión/cursor, cruce de tenant, revalidate/mapping contra commit, legacy y rollback de publicación. Mantener conteos/outcomes owner_pet e inventory excepto los cambios de formato aprobados.

Divide el código en entregas revisables si lo necesitas, pero continúa con las siguientes; no declares I03 terminado con stubs, TODOs o solo tests de un componente.

### 3. Completar I01/I02 y sus pruebas de transición

Conserva el writer inicial atómico y el contrato de alias ya implementados. Inventaría y adapta/comprueba writers pertinentes, incluido admin y caminos directos/bulk del dominio que deban mantener el par; no basta validar dos serializers. Si un writer legítimo puede producir quantity distinto del factor después del backfill, I02 no está cerrado.

Prueba recepción/reintentos y fallos del flujo de lotes sin duplicar stock ni inventar atomicidad entre peticiones. Completa regresiones de consumidores de unidades tocados. No alteres snapshots o ledger históricos para corregir el alias.

Prueba upgrade real mediante estados históricos de migración y datos sintéticos con snapshots clínicos/financieros. Invocar la función de backfill con apps actuales acredita una unidad, no sustituye MigrationExecutor/upgrade. Verifica idempotencia, invariantes y comportamiento ante factores inválidos; conserva rollback honesto de precisión y reverso noop documentado. No apliques nada en habitual/VPS ni reedites 0018.

### 4. Completar los criterios restantes

- I05: no autenticado, permisos, demo, otra organización y organización desactivada; mismo 403/código específico solo donde corresponde y contratos ajenos intactos.
- I07: baseline absoluto válido, no baseline, legacy/unidades mixtas, referencias incompletas, ajustes por lote (incluida FK nula), balances de lotes, datos ambiguos y propuesta obsoleta. Diagnóstico sin escrituras y sin aprobación inventada; la propuesta sigue sin aplicar.
- B7: prueba de integración de página o comprobación visual local de dirección/columna mostrada, conservando helper/tests. No convertir deuda previa de lint en una limpieza global. Separa regresiones reales de fallos preexistentes comprobados.

## Entorno y tiempos de ejecución

Ya existe un cluster exclusivo de orden 4 reportado en EVIDENCIA y su runner. Verifica directorio absoluto, proceso, puerto libre y allowlist efectivos antes de arrancarlo. Usa solo ese destino propio o un nuevo cluster de prueba inequívocamente separado si necesitas una base fresh; no uses la base habitual ni el cluster de orden 2. No elimines su directorio ni cambies restricciones para pasar pruebas.

Una primera migración fresh excedió timeout y una segunda completó pendientes. Documenta esa secuencia como tal; no afirmes una ejecución ininterrumpida o un upgrade histórico no probado. Si necesitas otro ensayo fresh, utiliza otra base descartable propia con tiempo suficiente, sin borrar evidencia ni destinos anteriores.

Ante timeout, comprueba si tu comando/proceso sigue ejecutándose antes de lanzarlo otra vez. Ajusta tiempos o divide suites independientes para obtener resultados verificables, manteniendo transacciones de dominio intactas. No trates un timeout como PASS ni como bloqueo general de código. Desactiva efectos externos e identifica procesos propios antes de detenerlos. Mantén comunicación breve de avances reales durante el trabajo.

## Criterio de terminación

Continúa mientras haya trabajo autorizado que puedas realizar. El final esperado es:

- I01/I02/B7/I03/I05 implementados y suficientemente verificados localmente.
- I07 diagnóstico reproducible y propuesta preparada; ejecución real pendiente de aprobación por producto.
- I04/I06 aplazados y límites de entorno preservados.

Actualiza los seis documentos del expediente con código, comando/revisión, resultados y límites por criterio. No marques PASS por existir un archivo o por una prueba parcial. Si hay un bloqueo concreto e inevitable, identifica su error y alcance, completa lo independiente y especifica la intervención mínima requerida. No cambies de tema ni repitas una nueva ronda de planificación como sustituto de implementación.

---

Referencias: [plan original](plan-remediacion-orden-4-2026-10-30.md), [revisión r2](remediaciones/orden-4/REVISION-2026-10-31-r2.md).
