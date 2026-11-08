# Orden 4 — expediente local en curso

Contrato: [plan acordado](../../plan-remediacion-orden-4-2026-10-30.md). Este expediente registra un avance parcial, no acredita cierre del orden. La revisión inicial era `8886604` en `codex/e4-capacity-scheduling`, con numerosos cambios previos staged, unstaged y sin seguimiento, incluidos cambios de imports, inventory y orden 2; conservarlos.

Continuación del 31-10: implementación parcial de alta manual, alias y diagnóstico, código demo específico y pruebas dirigidas. Las migraciones nuevas solo se aplicaron en PostgreSQL exclusivo y sintético de orden 4. El reporte paginado y varias verificaciones siguen pendientes: véanse [matriz](MATRIZ.md) y [evidencia](EVIDENCIA.md). No se regularizaron saldos.

Continuación r2: se corrigió la interpretación de ajustes por lote con FK nula y se implementó una primera versión del reporte paginado y su UI. La cobertura de aceptación completa sigue pendiente; consultar la matriz antes de usar esta implementación.

Continuación posterior: puente de rollback del reporte, lectura concurrente versionada y alta de presentación adicional mediante el writer. El alcance sigue sujeto a las verificaciones pendientes de la matriz.

Continuación 01-11: ciclo de rollback/upgrade de reporte probado con lectura paginada; recepción con identidad persistida en servidor y reintento desde el wizard. Véase evidencia y límites de almacenamiento local en la matriz.

Continuación 06-11: recuperación de recepciones sin estado local. El servidor guarda la intención antes de tocar stock y la app la descubre sin UUID; una persona concilia las candidatas. Decisión en [DECISIONES](DECISIONES.md#i01-recuperación-sin-estado-local-06-11), pruebas en [EVIDENCIA](EVIDENCIA.md#continuación-06-11-i01) y aplicación en [APLICACION-Y-ROLLBACK](APLICACION-Y-ROLLBACK.md). Las migraciones siguen aplicadas solo en el destino sintético.

Continuación 08-11: suite global local sin fallos atribuibles a I01, pasos de CI de frontend en verde y migraciones de I01 aplicadas a la base habitual local con respaldo. Véase [evidencia](EVIDENCIA.md#cierre-08-11).
