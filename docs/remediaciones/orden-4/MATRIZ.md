# Estado de los ocho IDs

| ID | Estado local | Falta |
|---|---|---|
| I01 | IMPLEMENTACIÓN PARCIALMENTE VERIFICADA | Alta y receipt idempotente probados en PostgreSQL, retry y recarga simulados en frontend; falta garantizar recuperación autoritativa si se pierde totalmente el almacenamiento local. |
| I02 | IMPLEMENTACIÓN PARCIALMENTE VERIFICADA | Serializers, admin y migraciones 0028/0029; upgrade PostgreSQL con snapshots y preflight inválido simulado pasan. Faltan verificar todos los writers y regresiones completas. |
| B7 | IMPLEMENTADOS_Y_VERIFICADOS_LOCALMENTE | Helper y prueba de integración de tabla con ambas direcciones pasan; lint de pantalla conserva errores previos documentados. |
| I03 | IMPLEMENTACIÓN PARCIALMENTE VERIFICADA | Persistencia, UI, rollback/upgrade 0004–0005 y lectura paginada probados; falta comprobación visual local de preview/resultado. |
| I04 | APLAZADOS_POR_ALCANCE | Preservar límites y locks existentes. |
| I05 | IMPLEMENTADOS_Y_VERIFICADOS_LOCALMENTE | `imports/views.py`: pruebas directas demo, tenant real, no ADMIN, no autenticado, otro tenant, JWT con organización desactivada y contraseña demo pasan. |
| I06 | APLAZADOS_POR_ALCANCE | Sin ampliación de importación. |
| I07 | PREPARADO_PENDIENTE_DE_APROBACION_POR_PRODUCTO | Diagnóstico y comparación de vigencia probados sintéticamente, incluida FK nula, ambigüedad y evidencia ausente o modificada. Aplicación futura bajo locks no implementada ni autorizada. |
