# SaaSLyVet — validación finita del controlador D29

Fecha del encargo: 2026-10-06. Baseline de aplicación: `825db75df68bf076929fa787e77beefe96803350`.

**CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY.** Se implementaron la secuencia adaptativa, los gates de evaluación, las recetas/verificadores de los 17 escenarios y un adaptador aislado de ejecución. La lógica del controlador está validada; quedan ocho adaptadores específicos de inyección para completar la matriz real. No se declara preparado el barrido completo.

## Evidencia

| Comprobación | Resultado | Recibo |
| --- | --- | --- |
| Regresión del instrumento y pruebas nuevas del controlador | **55 PASS**: 25 anteriores y 30 nuevas, sobre copia aislada final | [Log](unit-tests-final.log) |
| Secuencia de calibración, exploración, refinamiento, confirmaciones y variantes | **48 jobs de replay**, 17 escenarios, 36 variantes; reloj virtual | [Plan sellado](final-replay-plan.json), [resultado](replay-final/series-result.json) |
| Pipeline real, dos inputs ordinarios, dos planners y un sender | **5 controles PASS** en PostgreSQL local, provider simulado, capturas completas | [Plan](final-finite-probe-plan.json), [resultado](finite-probe-final/job-result.json), [log](finite-probe-final.log) |
| Primer probe de desarrollo | 5 controles PASS, conservado como evidencia separada de una versión anterior | [Resultado](finite-probe-01/job-result.json) |
| Fuentes que se validaron | Baseline verificado contra archive; overlay exclusivo de herramientas de prueba | [Hashes finales](validated-sources.json), [entorno](environment.json) |
| Limpieza e integridad | Instancia temporal cerrada, datos/credenciales retirados, fuentes y E4 anteriores preservados | [Recibo](cleanup-and-integrity.json) |
| Verificación de entrega | Coincidencia de fuentes validadas, enlaces y población de recibos | [Validación](delivery-validation.json) |

El replay está marcado `SYNTHETIC_REPLAY`: sus tasas son inventadas para comprobar decisiones y no observaciones de capacidad. El recibo real está marcado `FINITE_PIPELINE_PROBE_NOT_LEVEL_ACCEPTANCE` y no deriva una tasa de referencia ni E. Son evidencias distintas y no se mezclan para dar aceptación de carga.

Las pruebas cubren fallos de confirmación y descenso a un nivel inferior, conservación de pendientes, coalescing, crecimiento de una organización oculto por el agregado global, última ventana parcial, fuentes/planes alterados, mezcla de procedencias, recuperación adelantada, presupuesto reiniciado, testigo stale y fronteras de fallo ausentes. Un plan real con adaptadores faltantes se rechaza antes de asignar una base o ofrecer inputs.

La copia limpia del baseline inicialmente no contenía `SECRET_KEY`. Se aportó un valor sintético exclusivamente al entorno del proceso y se reanudó el esquema; se conserva el diagnóstico original. Para el probe final se creó otro clon privado del esquema, se retiraron sus organizaciones sintéticas clonadas antes de la oferta y se comprobó población Message/TurnWork vacía. Se mantuvieron esquema, migraciones y durabilidad. Ese clon fue eliminado al cerrar la prueba, con [recibo propio](final-probe-database-cleanup.json).

## Alcance y límites

Se añadieron seis módulos de herramientas de prueba y una suite nueva; no se cambió ningún archivo anterior. Runtime, configuración persistente, contratos, D29-v1, preflight anterior y E4 permanecen intactos. No hubo commits, benchmarks, barrido sostenido, PROFILE, tuning, efectos externos ni implementación de scheduling.

El [documento del controlador](../../decisions/2026-10-06-scheduling-controller.md) detalla las capacidades y comandos. La oferta/captura para R1-01–R1-06 y provider de R2-01/R2-02/R2-09 están implementados, pero no se ejecutaron niveles ni sus inyecciones reales. R1-07 y R2-03–R2-08/R2-10 necesitan adaptadores específicos de inyección/integración y acreditación real. Las recetas de los 17 escenarios se verificaron en el modelo; eso no acredita su reproducción física.

La continuación consiste en cerrar esa integración, acreditar sus fronteras con pruebas aisladas y, posteriormente, ejecutar la caracterización autorizada para proponer E. El contrato sigue propuesto, los dos minutos siguen siendo objetivo de producto y la cobertura de fallos/recovery y aceptación comercial permanecen pendientes.
