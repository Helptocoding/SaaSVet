# D29 — acreditación física finita

Estado final: **CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY**. Baseline `825db75df68bf076929fa787e77beefe96803350` conservado. E continúa sin definir. No se ejecutó caracterización, benchmark, búsqueda del máximo, tuning ni scheduling de producción.

## Ocho adaptadores solicitados

| Escenario | Frontera física | Individual | Matriz completa |
| --- | --- | --- | --- |
| R1-07 | Ingest, READY y deadline natural; COMMIT exterior; membresía W1/W2; duplicado; legacy NULL separado. | 6/6 | 6/6 |
| R2-03 | Terminación real del proceso antes de COMMIT; rollback físico y claim posterior. | 1/1 | 1/1 |
| R2-04 | Terminación después de COMMIT, lease natural, reclaim del mismo work y fencing. | 1/1 | 1/1 |
| R2-05 | Error LLM contenido después de admisión durable, backoff natural, retry y agotamiento. | 2/2 | 2/2 |
| R2-06 | Parada y nuevos procesos con pending/PROCESSING; recuperación y presupuesto conservados. | 1/1 | 1/1 |
| R2-07 | Locks PostgreSQL de org/Message, espera real, rollback exterior/savepoint y ACK perdido. | 5/5 | 5/5 |
| R2-08 | Ingest safety y endpoint humano real; epoch, fencing e inventario de interrupciones. | 5/5 | 5/5 |
| R2-10 | Propuesta/emisión/consentimiento causales; TTL/lease naturales; scope ajeno y gate cerrado. | 4/4 | 4/4 |

Los ocho tienen 25/25 variantes acreditadas individualmente. En la matriz se ejecutaron los 17 escenarios y sus 36 variantes: 12/17 escenarios completos y 30/36 variantes. Estos resultados acreditan fronteras finitas; no aceptan niveles de carga ni capacidad comercial.

## Escenarios que no se acreditan

| Escenario | Causa y clasificación | Evidencia |
| --- | --- | --- |
| R1-01 | El probe finito ofrece una conversación por organización y no acredita múltiples conversaciones ordinarias. Clasificación: cobertura de implementación/observación del adaptador existente; no se ha demostrado una primitiva PostgreSQL inexistente. Códigos: `SCENARIO_BOUNDARY_NOT_OBSERVED:multiple_conversations`. | [ordinary](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-physical-2026-10-06/full-matrix-01/matrix01-R101-ordinary/existing-adapter-verification.json) |
| R1-03 | No conserva evidencia de la geometría 2:1 con la misma cadencia global; no se inventa una tasa. Clasificación: cobertura de implementación/observación del adaptador existente; no se ha demostrado una primitiva PostgreSQL inexistente. Códigos: `SCENARIO_BOUNDARY_NOT_OBSERVED:concurrent_planners, SCENARIO_BOUNDARY_NOT_OBSERVED:same_global_2_to_1`. | [unequal](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-physical-2026-10-06/full-matrix-01/matrix01-R103-unequal/existing-adapter-verification.json) |
| R1-04 | No acredita toda la secuencia READY waiter → forecast futuro → miss/yield físico → siguiente elegibilidad; el extractor anterior requiere un miss de claim y no observa la selección vacía previa. Clasificación: cobertura de implementación/observación del adaptador existente; no se ha demostrado una primitiva PostgreSQL inexistente. Códigos: `SCENARIO_BOUNDARY_NOT_OBSERVED:forecast_miss, SCENARIO_BOUNDARY_NOT_OBSERVED:future_eligibility, SCENARIO_BOUNDARY_NOT_OBSERVED:future_eligibility_again, SCENARIO_BOUNDARY_NOT_OBSERVED:ready_waiter`. | [forecasts](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-physical-2026-10-06/full-matrix-01/matrix01-R104-forecasts/existing-adapter-verification.json) |
| R1-05 | No acredita burst simultáneo/concentrado de duración declarada, retorno a base confirmada y corte de drain. CONFIRMED_BASE sigue sin existir. Clasificación: cobertura de implementación/observación del adaptador existente y fixture de base confirmada no disponible; no se ha demostrado una primitiva PostgreSQL inexistente. Códigos: `SCENARIO_BOUNDARY_NOT_OBSERVED:base_return, SCENARIO_BOUNDARY_NOT_OBSERVED:burst_begin, SCENARIO_BOUNDARY_NOT_OBSERVED:burst_end, SCENARIO_BOUNDARY_NOT_OBSERVED:drain_cut`. | [concentrated](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-physical-2026-10-06/full-matrix-01/matrix01-R105-concentrated/existing-adapter-verification.json); [simultaneous](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-physical-2026-10-06/full-matrix-01/matrix01-R105-simultaneous/existing-adapter-verification.json) |
| R1-06 | El probe finito no construye ni captura la población de backlog anterior al arranque, su READY natural y corte de drain. CONFIRMED_BASE sigue pendiente. Clasificación: cobertura de implementación/observación del adaptador existente y fixture de base confirmada no disponible; no se ha demostrado una primitiva PostgreSQL inexistente. Códigos: `SCENARIO_BOUNDARY_NOT_OBSERVED:captured_backlog, SCENARIO_BOUNDARY_NOT_OBSERVED:drain_cut, SCENARIO_BOUNDARY_NOT_OBSERVED:natural_ready, SCENARIO_BOUNDARY_NOT_OBSERVED:workers_start`. | [backlog](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-physical-2026-10-06/full-matrix-01/matrix01-R106-backlog/existing-adapter-verification.json) |

Las recetas, verificadores y contratos previamente acreditados siguen intactos. Implementar otros adaptadores o generar una base de carga excede los ocho autorizados y esta fase; no se sustituyeron los requisitos faltantes con replay ni PASS declarados.

## Regresión, evidencia y limpieza

Regresión D29: 63 pruebas, OK (55 existentes + 8 del verificador físico). Regresión de aplicación: 231 pruebas, 0 fallos, 0 errores, 0 omitidas; estado PASS. Estas pruebas de regresión no sustituyen receipts físicos.

La primera regresión aprobó 230 pruebas y encontró un error de preparación: faltaba docker-compose.prod.yml en la copia de fuentes. Se conservó el resultado inicial, se copió el archivo exacto del baseline al clon y se repitió únicamente el test de topología afectado. Resultado combinado: 231 pruebas únicas aprobadas, 232 ejecuciones; ninguna fuente de aplicación ni archivo del repositorio se modificó para resolverlo. [Primer run](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-physical-2026-10-06/application-regression-initial.json), [test repetido](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-physical-2026-10-06/application-topology-rerun.json).

[Resultados individuales seleccionados](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-physical-2026-10-06/individual-selected-result.json), [matriz completa](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-physical-2026-10-06/full-matrix-01/matrix-result.json), [verificación offline de 50 receipts](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-physical-2026-10-06/offline-final-audit.json), [regresión D29](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-physical-2026-10-06/unit-regression-final.log), [regresión aplicación](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-physical-2026-10-06/application-regression-final.json), [integridad](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-physical-2026-10-06/final-integrity.json) y [cleanup](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-physical-2026-10-06/final-cleanup.json). Cada variante conserva journal, census independiente, checks, fuente/hash, receipt y verification; los clones tienen receipt de eliminación.

La captura inicial de consentimiento expirado quedó interrumpida con el cluster detenido. Se preservó incompleta, se eliminó únicamente su clon inventariado y se repitió en una base nueva con TTL original. Los intentos fallidos anteriores se conservan como evidencia histórica y no acreditan escenarios. [Reanudación y rollback](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-physical-2026-10-06/resume-cleanup.json).

Integridad: 3400 archivos protegidos comprobados; única modificación previa permitida: execution.py en el seguimiento finito de R2-02 y la disposición UNCERTAIN de R2-09. Runtime, .env, E4, B8/B9 y contratos sin cambios. Cleanup: 0 clones, 0 sesiones y 0 procesos participantes restantes. Plantilla vacía, cluster privado detenido, listener cerrado y pgdata/credencial temporal retirados. Los servicios PostgreSQL ajenos permanecen intactos.

## Archivos y commits

Cambios de esta fase:

- [physical.py](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/tests/scheduling_characterization/physical.py)
- [physical_cases.py](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/tests/scheduling_characterization/physical_cases.py)
- [physical_guards.py](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/tests/scheduling_characterization/physical_guards.py)
- [physical_matrix.py](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/tests/scheduling_characterization/physical_matrix.py)
- [PHYSICAL.md](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/tests/scheduling_characterization/PHYSICAL.md)
- [execution.py](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/tests/scheduling_characterization/execution.py)
- [test_d29_physical.py](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/tests/test_d29_physical.py)
- [Inspección previa de adaptadores](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/decisions/2026-10-06-d29-physical-adapters.md)
- Evidencia y receipts en docs/evals/d29-physical-2026-10-06, con índice de hashes y versiones congeladas de herramientas por ejecución.

Se añadieron cuatro módulos físicos, ocho tests del verificador y documentación/evidencia. execution.py conserva la ejecución de carga; sus dos cambios están limitados al probe finito. Los demás archivos D29 untracked ya existían. Se preservaron las dos eliminaciones DEPLOY_VPS y skills-lock.json modificado anteriores a esta tarea.

Commits realizados: **0**. HEAD sigue en el baseline obligatorio. No se avanzó a caracterización.
