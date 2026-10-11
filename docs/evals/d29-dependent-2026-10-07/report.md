# D29: resultado del consumo de CONFIRMED_BASE

**CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY**. Base aceptada íntegra; no se generó ni recalibró otra base.

| Primeros intentos individuales | Resultado | Causa / evidencia |
| --- | --- | --- |
| R1-03 unequal | PHYSICALLY_ACCREDITED | ; `individual\individual-R103-unequal` |
| R1-04 forecasts | NOT_ACCREDITED | CONCURRENT_PRE_QUERY_FORECAST_YIELD_AND_SUPERSESSION_WITNESSES_MISSING; INDETERMINATE; OBSERVATION_GATES_NOT_SATISFIED; `individual\individual-R104-forecasts` |
| R1-05 simultaneous | NOT_ACCREDITED | INDETERMINATE; OBSERVATION_GATES_NOT_SATISFIED; `individual\individual-R105-simultaneous` |
| R1-05 concentrated | PHYSICALLY_ACCREDITED | ; `individual\individual-R105-concentrated` |
| R1-06 backlog | NOT_ACCREDITED | EXECUTOR_REJECTED_SCENARIO; `individual/individual-R106-backlog` |

El primer burst simultáneo conserva su fallo de captura. El observador v2 registra la activación antes del inicio monotónico real de la ventana; las tasas, duración, oferta y procesos permanecen intactos. Los resultados de cierre proceden de la matriz con las fuentes finales, sin sobrescribir el intento anterior.

La revisión v3 añade testigos previos/posteriores de R1-04. La revisión v4 corrige exclusivamente la inicialización de Django en el verificador de R2-09 antes de su ejecución; no cambia la ejecución física de los demás casos. Cada intento conserva los hashes de la revisión que realmente ejecutó.

La matriz intentó 36 variantes requeridas de 17 escenarios. 30 verificaciones físicas recientes pasaron. 11 escenarios satisfacen sus requisitos completos en estas fuentes. No se confunde la frontera finita con la condición completa de carga.

| Escenario | Variantes intentadas | Frontera física reciente | Condición completa |
| --- | --- | --- | --- |
| R1-01 | 1/1 | PASÓ | ACREDITADA |
| R1-02 | 1/1 | PASÓ | ACREDITADA |
| R1-03 | 1/1 | NOT_ACCREDITED | NOT_ACCREDITED |
| R1-04 | 1/1 | NOT_ACCREDITED | NOT_ACCREDITED |
| R1-05 | 2/2 | PASÓ | ACREDITADA |
| R1-06 | 1/1 | NOT_ACCREDITED | NOT_ACCREDITED |
| R1-07 | 6/6 | PASÓ | ACREDITADA |
| R2-01 | 1/1 | PASÓ | ACREDITADA |
| R2-02 | 1/1 | PASÓ | NOT_ACCREDITED |
| R2-03 | 1/1 | PASÓ | ACREDITADA |
| R2-04 | 1/1 | PASÓ | NOT_ACCREDITED |
| R2-05 | 2/2 | PASÓ | ACREDITADA |
| R2-06 | 1/1 | PASÓ | ACREDITADA |
| R2-07 | 5/5 | PASÓ | ACREDITADA |
| R2-08 | 5/5 | PASÓ | ACREDITADA |
| R2-09 | 2/2 | PASÓ | NOT_ACCREDITED |
| R2-10 | 4/4 | PASÓ | ACREDITADA |

Requisitos que siguen pendientes:

| Escenario / variante | Motivo observado | Receipt |
| --- | --- | --- |
| R1-03 unequal | EXECUTOR_REJECTED_SCENARIO; {'exception_class': 'ValueError', 'message': 'Reversed temporal interval', 'kind': 'PHYSICAL_SCENARIO_NOT_ACCREDITED'} | `matrix-existing\matrix-existing-R103-unequal` |
| R1-04 forecasts | COMPLETE_FORECAST_YIELD_SUPERSESSION_NEXT_ELIGIBILITY_SEQUENCE_NOT_ACCREDITED; INDETERMINATE; OBSERVATION_GATES_NOT_SATISFIED; scenario: SCENARIO_BOUNDARY_NOT_OBSERVED:forecast_miss; scenario: SCENARIO_BOUNDARY_NOT_OBSERVED:future_eligibility; scenario: SCENARIO_BOUNDARY_NOT_OBSERVED:future_eligibility_again | `matrix-existing\matrix-existing-R104-forecasts` |
| R1-06 backlog | EXECUTOR_REJECTED_SCENARIO; {'exception_class': 'ValueError', 'message': 'Backlog needs distinct conversations; seal a new plan with sufficient fixture size', 'kind': 'PHYSICAL_SCENARIO_NOT_ACCREDITED'} | `matrix-existing\matrix-existing-R106-backlog` |
| R2-02 blocked | INVALID_RUN; OBSERVATION_GATES_NOT_SATISFIED; demand: COALESCED_DEMAND_NOT_DECLARED_READY_EPISODE_LOAD | `matrix-existing\matrix-existing-R202-blocked` |
| R2-04 postcommit | FINITE_ADAPTER_DOES_NOT_EXECUTE_CONFIRMED_BASE_LOAD | `matrix-physical\matrix-physical-R204-postcommit` |
| R2-09 slow_meta | ORDINARY_READY_QUEUE_DURING_AFFECTED_META_NOT_OBSERVED | `matrix-existing\matrix-existing-R209-slowmeta` |
| R2-09 uncertain_meta | INDETERMINATE; INVARIANTS_NOT_DECIDABLE_OR_FAILED; OBSERVATION_GATES_NOT_SATISFIED; ORIGINAL_CAPTURE_OR_VERIFICATION_NOT_VALID; invariants: CLAIMED_WORK_WITHOUT_SERVICE_WITNESS | `matrix-existing\matrix-existing-R209-uncertainmeta` |

Regresión D29 final: 78 tests, 0 omitidos; exit 0. Se conserva también la regresión inicial: 78 tests, 9 omitidos inicialmente; los 9 checks físicos omitidos se ejecutaron después contra receipts preservados. Exit codes: 0/0.

Regresión de aplicación: `PASS`; resultado completo en `application-regression.json`.

Cleanup privado e integridad verificados. Baseline, 3409 fuentes protegidas y todos los artefactos históricos sellados permanecen íntegros. Cero commits.

Todos los intentos, incluidos fallos y rechazos de preparación, se conservan. Los detalles causales y decisiones propuestas están en [blockers-and-decisions.md](blockers-and-decisions.md). No se inicia una fase posterior ni se calcula E.

Receipt completo: [final-receipt.json](final-receipt.json). Índice de hashes: [artifact-index.json](artifact-index.json).
