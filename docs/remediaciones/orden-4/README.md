# Orden 4 — expediente

**Estado (15-11):** cerrado. I01, I02, I03, B7 e I05 implementados y verificados; I07 no aplica sin datos reales; I04 e I06 aplazados ([MATRIZ](MATRIZ.md)). Integrado en `develop` por el [PR #3](https://github.com/Helptocoding/SaaSVet/pull/3) (`a7dbdaf`, 11-11), junto con el orden 5, con CI en verde ([corridas](../orden-5/EVIDENCIA.md#integración-en-develop-y-ci-11-11-2026)); sin despliegue. El 15-11 el directorio del cluster exclusivo `orden4_pg18_20261031` ya no existía en `Temp/opencode`, aunque la evidencia del 09-11 lo dejó conservado. Los párrafos siguientes son el registro de avance de cada sesión.

Contrato: [plan acordado](../../plan-remediacion-orden-4-2026-10-30.md). Al abrirse, este expediente registraba un avance parcial, sin cierre del orden. La revisión inicial era `8886604` en `codex/e4-capacity-scheduling`, con numerosos cambios previos staged, unstaged y sin seguimiento, incluidos cambios de imports, inventory y orden 2; conservarlos.

Continuación del 31-10: implementación parcial de alta manual, alias y diagnóstico, código demo específico y pruebas dirigidas. Las migraciones nuevas solo se aplicaron en PostgreSQL exclusivo y sintético de orden 4. El reporte paginado y varias verificaciones siguen pendientes: véanse [matriz](MATRIZ.md) y [evidencia](EVIDENCIA.md). No se regularizaron saldos.

Continuación r2: se corrigió la interpretación de ajustes por lote con FK nula y se implementó una primera versión del reporte paginado y su UI. La cobertura de aceptación completa sigue pendiente; consultar la matriz antes de usar esta implementación.

Continuación posterior: puente de rollback del reporte, lectura concurrente versionada y alta de presentación adicional mediante el writer. El alcance sigue sujeto a las verificaciones pendientes de la matriz.

Continuación 01-11: ciclo de rollback/upgrade de reporte probado con lectura paginada; recepción con identidad persistida en servidor y reintento desde el wizard. Véase evidencia y límites de almacenamiento local en la matriz.

Continuación 06-11: recuperación de recepciones sin estado local. El servidor guarda la intención antes de tocar stock y la app la descubre sin UUID; una persona concilia las candidatas. Decisión en [DECISIONES](DECISIONES.md#i01-recuperación-sin-estado-local-06-11), pruebas en [EVIDENCIA](EVIDENCIA.md#continuación-06-11-i01) y aplicación en [APLICACION-Y-ROLLBACK](APLICACION-Y-ROLLBACK.md). Las migraciones siguen aplicadas solo en el destino sintético.

Continuación 08-11: suite global local sin fallos atribuibles a I01, pasos de CI de frontend en verde y migraciones de I01 aplicadas a la base habitual local con respaldo. Véase [evidencia](EVIDENCIA.md#cierre-08-11).

Integración 08-11: I01, I02 e I03 rebasados sobre `develop`, subidos a `codex/e4-capacity-scheduling` y con CI real en verde. Véase [evidencia](EVIDENCIA.md#integración-en-develop-y-ci-08-11).

Continuación 09-11: confirmado que no existen datos reales, I07 deja de aplicar; el importador bloquea factores que perderían valor y se midió I04 en su tope. I04 e I06 siguen aplazados. Véase [evidencia](EVIDENCIA.md#decisiones-09-11).
