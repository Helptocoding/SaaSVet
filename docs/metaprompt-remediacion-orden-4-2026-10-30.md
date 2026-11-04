# Metaprompt ejecutor — Orden 4: inventario e importaciones

Preparado el **30-10-2026**. Entregar el bloque siguiente al agente implementador. Este archivo prepara el trabajo; no lo ejecuta ni acredita remediación.

---

Actúa como agente implementador de SaaslyVet en `C:/Users/LAP/Desktop/VeterinariaSaaS`. Implementa el alcance local acordado del orden 4 mediante entregas pequeñas, migraciones preparadas y evidencia reproducible. No te detengas tras repetir un plan.

Lee completo `C:/Users/LAP/Desktop/VeterinariaSaaS/docs/plan-remediacion-orden-4-2026-10-30.md`: es el contrato detallado de decisiones, pruebas y límites. El usuario ya resolvió las preguntas de producto. Registra instrucciones posteriores si modifican ese contrato.

## Decisiones cerradas

- Cubrir **I01, I02, B7, I03 e I05**; **I07** solo diagnóstico y preparación de regularización; mantener **I04 e I06** aplazados. No añadir importación multi-presentación, lotes ni múltiples orígenes/sucursales. Preservar funciones manuales existentes.
- Mantener captura de stock inicial manual; el movimiento auditable se registra automáticamente dentro de la misma operación. El writer autoritativo sigue siendo `apply_stock_movement` en unidades base.
- `Presentation.quantity` es alias de `conversion_factor`. Ambos explícitos y distintos: 400. Solo uno: normalizar ambos a ese valor. En alta sin ambos: default 1; PATCH sin ambos conserva valores. No tratar un default inyectado como dato explícito ni aceptar inválidos silenciosamente.
- Preparar corrección determinista del alias antiguo desde factor válido, con validación en bases aisladas; sin cambiar factor, stock, base_unit, precios, lotes, ledger o snapshots. Esto es distinto de regularizar stock.
- Conflictos: muestra acotada y detalle completo paginado, con totales exactos y sin cambiar filas aceptadas/omitidas. No se eligió solo una muestra ni exigir una descarga completa.
- Código específico de demo: propagar `demo_account_restricted` conservando HTTP 403, bloqueo y otros errores.
- Históricos sin baseline: diagnosticar y preparar propuesta con **aprobación explícita por producto**. No emitir movimientos automáticamente, fabricar fechas/aprobaciones ni certificar el pasado.
- Puedes modificar código local y preparar migraciones. **Aplicación y validación solo en bases aisladas y sintéticas.** Base habitual intacta, aunque tenga demos. VPS excluido: sin SSH, pagos, reactivación, pruebas o despliegue.
- Sin commit, push, PR, merge, publicación ni despliegue automáticos. No reabrir WhatsApp, privacidad de landing, otros órdenes o deudas B9/D29 aceptadas.

## Preflight

1. Lee instrucciones del repositorio y RTK. Usa grafo MCP para descubrimiento y traza de llamadas; contrasta fuente actual cuando sea insuficiente o el índice no refleje cambios locales. No copies una versión vieja del grafo sobre trabajo nuevo.
2. Registra revisión y estado inicial. Hay cambios ajenos en imports, inventory y otros módulos; consérvalos, incluidos tests de commit concurrente, parsing perezoso y conservación de orden 2. No resetear ni limpiar el checkout.
3. Inventaría writers/readers de stock y de ambos nombres del factor, contratos del wizard/serializer, reportes y permisos. No leas ni muestres valores de secretos, filas reales o dumps para este trabajo.
4. Prepara conexión de prueba aislada explícita con allowlist de host/puerto/base y fixtures; no heredes ciegamente la conexión habitual. Reutiliza runtime/locks compatibles sin upgrades de dependencias de otros órdenes. Si una limitación impide una prueba, declárala; no cambies el destino a la base habitual.
5. Revalida las fuentes del plan, los ADR p31/p61 y módulos actuales. El plan raíz del importador contiene cortes históricos: casillas antiguas no prueban que toda la función falte.

## Puntos de partida e implementación

Sigue E0–E6 del plan. E1/B7 es una entrega acotada que puede avanzar primero. Coordina E2/I02 y E3/I01 para compartir contrato, sin una reescritura general del módulo.

### B7: orden de inventario

`frontend/src/pages/inventory.jsx` muestra stock/valor con `productStockQty` y `productStockValue`, pero compara fuentes legacy distintas. Usa los mismos helpers al ordenar. Precio por stock de presentación no es siempre matemáticamente incorrecto cuando la sombra está sincronizada: la prueba debe demostrar divergencia real frente a lo renderizado, no inventar un error por multiplicación.

Caso: A stock base 12, factor 12, precio 120 y sombra legacy 12; valor mostrado 120. B stock base 6, factor 1, precio 50 y sombra 6; valor mostrado 300. Ascendente debe ordenar A/B pese a que el comparador viejo ordena 1440/300. Añade orden inverso, stock, cero, sombras coherentes y empates. No cambies valoración comercial por costo contable ni rediseñes la pantalla.

### I02: alias, precisión y datos antiguos

Reutiliza `backend/apps/inventory/units.py`. Normaliza presencia/valores antes de defaults en altas y PATCH, cubriendo alta/edición de producto/presentación, serializer anidado, importador y writers pertinentes. Diferencias explícitas son errores; nunca corregirlas en silencio. Un cambio de factor comercial sigue sus guards vigentes y no reescribe documentos ni movimientos pasados.

`Presentation.quantity` tiene 2 decimales y factor 4. Prepara ampliación que represente exactamente todos los factores válidos y preserve rango entero previo cuando corresponda (el plan contempla 12/4 como opción a verificar). No redondees factor para adaptarlo al alias ni reduzcas capacidad entera sin diagnóstico. No confundas este alias con cantidades clínicas/financieras o con stock.

Migraciones nuevas: schema compatible, backfill idempotente de **quantity desde factor válido**, validación y constraint si procede después de adaptar writers. Factores inválidos se reportan y detienen la parte dependiente, sin asumir 1. No editar/repetir 0018: recalcula stock y no es el mecanismo de esta corrección. Demuestra que el backfill conserva saldo, factor, mínimo, unidad, precios, lotes, ledger y snapshots. Evita efectos de `save()` no deseados.

### I01: stock inicial manual

`ProductSerializer.create` actualmente asigna saldo directo. Sustituye ese camino por creación con Product/Presentation a cero, metadatos preparados y **una entrada positiva** por el writer dentro del mismo atomic. Convertir stock/min_stock de presentación a base una sola vez, cuantizar según contrato y validar rangos. No asignar el saldo y además sumar la entrada.

Actor/organización desde contexto confiable, no payload/thread-local como única prueba. Motivo distingue alta manual/import; conserva código interno automático, precio/barcode y objeto de respuesta actualizado. Si falla algo, rollback de producto/presentación/saldo/movimiento. Cero no exige inventar una entrada positiva ni apertura histórica.

El importador ya usa entrada inicial desde cero: conserva resultados, dedup skip y savepoints. Actualiza `test_stock_parity_manual_vs_import`, que hoy fija alias manual 1 y ausencia de movimiento como deuda; ahora debe comprobar el contrato corregido, no borrarse ni debilitarse.

Mantén el flujo manual de lotes. `tracks_lots` no puede recibir stock positivo sin lotes identificados. El wizard crea a cero y recibe después: dos peticiones no son una transacción. Conserva resultado parcial honesto si falla recepción y evita duplicar stock al reintentar; no borres ledger/productos para simular rollback remoto. No implementes importación de lotes.

### I03: reporte de conflictos

Mantén muestra `result.conflicts` de máximo 100 y agregados exactos (`high + uncertain == skipped_conflicts`). Añade metadatos de total/muestra/truncamiento/versión y lectura de detalle paginado, default 50/máximo 100. Endpoint de acción por job/public_id según las convenciones existentes; documenta contrato y errores.

Persiste un reporte estable por ejecución/mapping/etapa de preview o commit, con detalles mínimos y procesamiento/escritura por lotes acotados. Puedes usar un modelo relacionado con ImportJob si es la solución mínima. No crees otro importador ni acumules todos los conflictos para cortarlos solo al responder. No regeneres páginas consultando un catálogo que cambió.

Publica detalle, agregados y versión atómicamente, conservando locks de job. Pagina en orden estable por fila/ordinal, validando versión/cursor del servidor. Por defecto, reemplazar reporte invalida versión antigua con 409 y pide refrescar; no mezclar páginas de ejecuciones distintas. Mantén RBAC de lectura, tenant, demo, estado de organización y UUID públicos, sin filtraciones cross-tenant.

Un validate puede guardar metadatos/reportes del job, como ya hace; su cálculo no escribe Product/Presentation, Owner/Pet, stock, lotes ni ledger. Distingue ambas cosas en tests. Preserva el commit una sola vez en servicio y mapping/validate coordinados: no pagines ni fragmente las escrituras del job por haber paginado sus lecturas.

Compatibilidad: convertir reportes antiguos desde su resultado persistido sin reimportar/revalidar contra el catálogo actual. No truncar detalle antes de asegurar su persistencia accesible ni inventar filas perdidas. Mantener formato legacy visible o transición compatible y explicar rollback. Minimiza PII y liga ciclo de vida al job, sin política global nueva.

Wizard preview/resultado: totales reales, «Mostrando N de M», páginas completas y grupos high/uncertain coherentes. Nunca `.length` de una muestra como total o decisión de commit. No cambies qué filas se aceptan, dedup skip, campos obligatorios, errores bloqueantes o CSV de errores/avisos existente. Ese CSV no es descarga completa de conflictos.

### I05: demo

`NotDemoAccount` ya declara `demo_account_restricted`. Propágalo acotadamente a la respuesta normalizada 403 de importación. Conserva otros errores y revisa consumidores compartidos (p. ej. contraseña demo) sin alterar sus contratos inadvertidamente. No ampliar permisos, retirar throttles o dar a un operador sin organización un tenant implícito. Probar backend directo, no solo botón oculto.

### I07: preparar, sin regularizar automáticamente

El auditor busca adjustment base; un `in` inicial no es automáticamente baseline para ese algoritmo. `no_baseline` es cobertura insuficiente, no drift demostrado. No insertar ajustes para ponerlo verde ni sumar de nuevo el saldo.

Diagnostica por categoría y propone por producto: tenant/public_id, saldo/unidad, watermark del ledger, cobertura/ambigüedades/lotes, acción y efectos, aprobación individual/actor/fecha/motivo pendientes. Reporte sin escrituras de dominio; datos sintéticos durante esta entrega. Contrasta ajustes absolutos de Product frente a ajustes por lote: saldo final del lote no es baseline del Product. Si no puedes reconstruir un delta, marca no verificable.

Documenta la futura regularización como reconstrucción desde saldo observado, con aprobación explícita por producto, revalidación bajo locks y rechazo si cambió saldo/ledger/organización/lotes; sin duplicar apertura, corregir drift de oficio o certificar el pasado. No se requiere una API apply en esta entrega ni ejecutar propuestas. No incluir apertura de stock en migraciones, seed, post_migrate o deploy. El backfill autorizado de alias sí se prepara y valida aisladamente.

## Verificación obligatoria

- PostgreSQL aislado, datos sintéticos, migración fresh y upgrade. Checks y drift de migraciones, ratchets pertinentes. No afirmar aplicación en habitual/producción.
- Unidades: factor solo, alias solo, ambos, contradictorios, ausentes, PATCH parcial, cero/negativos/nulos/NaN/infinitos/rangos, 0.125 y 1.2345, reload DB sin pérdida de escala. Backfill repetido no cambia nada adicional y mantiene snapshots/saldos.
- Alta/import: factor 1, 3, 12 y fracciones válidas; cantidad/min_stock, actor y movimiento único. Fallo inyectado revierte todo. Stock cero y recepción por lotes sin doble contabilización.
- Conflictos: 0/100/101/2000, high/uncertain, todas las páginas sin omisiones/duplicados, tamaño inválido/excesivo, mapping/revalidate/commit y reporte legacy. Catálogo cambiado no altera reporte. Cross-tenant/versión/cursor sin fugas. Fallo al persistir reporte no publica una mezcla.
- Concurrencia real: dos commits del mismo job solo un efecto, validate/mapping no rehabilitan committed y páginas no mezclan versiones. Preservar tests de `test_import_commit_concurrency.py` y `test_parser_streaming_caps.py`. SQLite/mocks no acreditan locks PostgreSQL.
- Demo: 403 específico y denegaciones no autenticado/no ADMIN/cross-tenant conservadas. Organización desactivada y protecciones del orden 2 permanecen.
- I07: clasificación, diagnóstico sin cambios y propuestas ambiguas/obsoletas/repetidas simuladas. No generar aprobaciones ni mover stock de datos existentes.
- Suites dirigidas de inventario/imports y consumidores de unidades tocados; tests frontend de helper/orden/wizard, lint de archivos tocados y build. Verificación visual local si hay UI. No arreglar todo el lint, optimizar I04, subir MAX_ROWS ni introducir workers.
- Procesos propios en loopback y puertos libres, integraciones externas desactivadas; no parar servicios ajenos, usar dumps reales, conectar VPS, ejecutar campañas B9/D29 ni nuevos escaneos de seguridad. Registra entorno/revisión/comandos/resultados honestos y límites.

## Entregables y cierre

Crea `docs/remediaciones/orden-4/` con README, DECISIONES, MATRIZ de ocho IDs, EVIDENCIA, REGULARIZACION-PROPUESTA y APLICACION-Y-ROLLBACK conforme al plan. Actualiza módulos inventory/imports y referencias posteriores de p31/p61 sin borrar recibos históricos. Incluye compatibilidad de reportes, migraciones y pérdida de reversibilidad al reducir precisión; rollback nunca elimina ledger ni restaura saldos arbitrarios.

Estados: I01/I02/B7/I03/I05 **IMPLEMENTADOS_Y_VERIFICADOS_LOCALMENTE** solo si están probados; I07 **PREPARADO_PENDIENTE_DE_APROBACION_POR_PRODUCTO**; I04/I06 **APLAZADOS_POR_ALCANCE**. Si una parte falla o no se acredita, déjala pendiente con evidencia; no cierres por tener código o mocks.

Termina con cambios, pruebas, límites concretos y trabajo pendiente. No pidas de nuevo decisiones resueltas. Presenta cualquier aprobación realmente necesaria sobre una propuesta concreta, continuando lo independiente. No commit/push/PR, despliegue ni modificación de la base habitual/VPS.

---

Contrato detallado: [plan del orden 4](plan-remediacion-orden-4-2026-10-30.md).
