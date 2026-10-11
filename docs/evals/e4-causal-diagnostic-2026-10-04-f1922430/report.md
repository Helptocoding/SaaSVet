# DIAGNOSTIC_ONLY — CAUSE_CONFIRMED

All 128 bound messages above 10 s had already crossed 10 s before selection_start. This confirms preselection threshold crossing on this new runtime. Selector/claim SQL and commit add the individually recorded costs; not every millisecond of excess is attributed to the queue. Worker occupancy and noisy backlog observations do not isolate a unique mechanism. Historical ROOT_CAUSE_NOT_CONFIRMED; no runtime correction is proposed.

Nueva ejecución: `causal-f1922430c60348e8adce24196c02bf5a`. HEAD exclusivo: `825db75df68bf076929fa787e77beefe96803350`, rama `codex/e4-capacity-scheduling`, hijo directo de `66702168439b9841a2c988238638a42e6aaee43d`.
Inicio UTC: **2026-10-04T18:59:15.042285+00:00**. No se invocó `b9e_profile` ni `e4_profile`; no es PROFILE-BETA-1 ni aceptación B9E. Umbral intacto de 10 s. El FAIL histórico, su PROFILE y la evaluación posterior del 02-10 permanecen intactos. No se imputan estas mediciones al TurnWork 86 histórico.

La carga conserva dos planners y un sender, batch 1, pausa entre polls de 1 s, dos organizaciones a un inbound cada 10 s y una ruidosa a uno por segundo; 30 s de calentamiento, 300 s de carga y 20 s de drenaje. Provider simulado: dos llamadas LLM de 500 ms, HTTP de dominio 100 ms, Meta 200 ms. Ingreso capturado antes del primer webhook y ambas capturas de planners activas; observador readonly autocommit en proceso separado con intervalo solicitado de 20 ms. PostgreSQL aislado 16.15 con fsync y synchronous_commit on.

| Organización | Ingestados | Reclamados | Safety | >10 s | Pendientes sin claimed_at | Máximo reclamado, s |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 33 | 33 | 11 | 0 | 0 | 8.898121 |
| 2 | 33 | 33 | 11 | 0 | 0 | 9.472716 |
| 3 | 330 | 129 | 0 | 128 | 201 | 221.810544 |

195 claims vinculados y confirmados por commit; 26 intentos sin vínculo. Los pendientes están censurados: no se fabrican claimed_at ni latencias finales. Todos los intentos están en [per-attempt.json](per-attempt.json) y [per-attempt.csv](per-attempt.csv); cada exceso individual está en [over-10-attempts.csv](over-10-attempts.csv) y [over-10-attempts.json](over-10-attempts.json).

**Evidencia por intento.** Los IDs pertenecen exclusivamente a esta DB nueva. Las columnas con límites usan la consulta DB existente como calibración, no logs de segundos.

| Work/inbound/worker | persisted→claimed_at, s | A persisted→eligible, s | A eligible→poll, s | A eligible→selection, s | B selección, ms | B query count / SQL, ms | C, ms | D claim, ms | E COMMIT, ms | persisted→ACK, ms |
|---|---:|---:|---|---|---:|---|---:|---:|---:|---|
| 4/6/planner-2 | 12.339541 | 7.923980 | [4.353488; 4.353975] | [4.353597; 4.354085] | 26.8258 | 1 / 4.7732 | 0.0808 | 112.1447 | 4.1808 | [12415.9771; 12416.4648] |
| 104/107/planner-2 | 129.730810 | 7.930131 | [121.748556; 121.749058] | [121.748660; 121.749162] | 41.8494 | 1 / 28.8071 | 0.0799 | 45.7285 | 1.2315 | [129765.9655; 129766.4670] |
| 195/217/planner-2 | 221.810544 | 7.966577 | [213.762338; 213.762944] | [213.762415; 213.763021] | 70.1903 | 1 / 54.9091 | 0.0968 | 50.8951 | 0.8364 | [221849.7277; 221850.3335] |
| 125/377/planner-2 | 9.472716 | 7.965408 | [1.412435; 1.413095] | [1.412529; 1.413190] | 79.7484 | 1 / 57.4221 | 0.1102 | 64.6619 | 1.0224 | [9521.7018; 9522.3621] |

El máximo es Work 195, inbound 217, org 3, attempt `7b442945856244e2b4f92bdd31961306`: 221.810544 s. El intervalo anterior a selección es [221728.9924; 221729.5982] ms; selección→claimed_at es [80.9458; 81.5516] ms. La separación claim_start→claimed_at es [10.6587; 11.2645] ms, mientras el claim completo es 50.8951 ms. Los extremos de la misma calibración están anticorrelacionados y cierran el total DB; no se suman percentiles ni límites independientes.
En el worker que admite ese intento se observaron estos solapamientos previos: `{"between_polls_including_configured_1s_pause": [124298.0089, 124298.0089], "processing_previous_turn": [78305.0139, 78305.6197]}`. Incluyen spans de otros turnos y tiempo entre polls con la pausa configurada; no se etiqueta todo ese intervalo como sleep ni como indisponibilidad global simultánea de ambos planners.

**Fases A–E y consultas.** [per-phase.json](per-phase.json) separa ordinarios, safety y casos >10 s. A contiene el deadline existente y la espera hasta el poll/selección que admite. B mide selección completa, execute y huecos; C mide el salto a claim; D conserva los locks y todas las queries del intento; E mide la llamada real al COMMIT. D incluye E en el claim ordinario y una parte ocurre después de claimed_at: esos tiempos no deben sumarse íntegros al persisted→claimed_at.
El selector ejecutó 412 queries en 412 selecciones distintas con SQL, incluyendo polls sin admisión; [selector-polls.json](selector-polls.json) conserva sus IDs y timings. Los claims ordinarios tienen una query del selector y safety cero (poll/selección N/A). Todos los execute del run (77725) están en [query-timings.jsonl](query-timings.jsonl), con session/query ID, scope, inicio/fin/error, tablas y flags de locks, sin SQL crudo ni parámetros. La duración SQL de cliente incluye servidor, red, driver y posibles waits; materialización y overhead quedan en selección total.
Cada intento conserva query IDs, duración individual y huecos fin→inicio. El selector de una query no tiene hueco entre queries. Se conserva claim_result, commit_start, commit_end, commit_ack (execute_end_ns), persisted→claimed_at y persisted→commit_ack. En ordinarios el ACK precede al claim_result; el intervalo firmado puede ser negativo. En safety el resultado de la primitiva precede al commit exterior de ingreso. claimed_at no equivale al ACK.

**Waits y bloqueadores.** [waits-summary.json](waits-summary.json) y el journal `waits.jsonl` mantienen asociación por run/session/conexión/PID e intersección con execute. Las muestras ambiguas no se asignan a una query. No se interpolan locks ni se les atribuye toda la duración SQL.
Muestras: 48148; únicas 4036, ambiguas 142, sin query asociada 43970. Queries con lock observado: 6.

| Worker/query | Tabla | Query, ms | Muestras lock | Bloqueadores | Scope |
|---|---|---:|---:|---|---|
| ingress/6647 | agent_conversation | 110.5130 | 5 | {"21408": "planner-1"} | attempt=None, work=None |
| ingress/14043 | agent_conversation | 97.2993 | 4 | {"19148": "planner-2"} | attempt=None, work=None |
| ingress/21385 | agent_contactidentity | 24.0640 | 1 | {"19148": "planner-2"} | attempt=None, work=None |
| planner-1/4383 | agent_conversation | 14.8360 | 1 | {"13648": "ingress"} | attempt=None, work=55 |
| planner-1/7161 | agent_conversation | 57.3075 | 3 | {"13648": "ingress"} | attempt=None, work=89 |
| planner-2/4363 | agent_conversation | 32.7839 | 1 | {"13648": "ingress"} | attempt=None, work=56 |

La duración exacta de lock permanece null; el límite conservador es [0; duración completa de query]. Ausencia de muestras no prueba ausencia absoluta de waits. El observador no cambia polling ni ocupa la conexión del worker.

**Integridad, equivalencia y hashes.** Las seis pruebas controladas OFF/ON se ejecutaron nuevamente con IDs prefijados por el UUID nuevo. Cero fallos/errores/skips/xfail; igualdad de decisiones, secuencia SQL, membership, attempts, locks, leases, epoch/fencing, budgets y resultado bajo los estados/barreras controlados. No se promete igualdad temporal ON/OFF ni igualdad de ganador en carreras no controladas. El overhead de captura se incluye en los tiempos.
Las cuatro capturas nuevas suman 213238 eventos, sin failed_writes y con footer, secuencia, SQL/spans y transacciones completos. El observador terminó sin líneas parciales. Todos los procesos terminaron con exit 0. [integrity.json](integrity.json), [functional-results.results.json](functional-results.results.json) y la validación final conservan esa evidencia.
[protected-sources-before.json](protected-sources-before.json) y [protected-sources-after.json](protected-sources-after.json) verifican 1239 fuentes del HEAD y 156 archivos de las dos ejecuciones diagnósticas anteriores sin cambios. No se modificó runtime, selector, índices, SQL, workers, polling, leases, budgets o umbral. Los cambios preexistentes del usuario se conservan. No hay commits nuevos.
La asociación NULL del reconstructor del HEAD para safety se excluye sólo en el adaptador evaluativo: una selección exige selection_id no nulo y span real. Los journals y fuentes no se cambian. Los borradores causal-analysis.json, attempt-summary.* y phase-summary.json no son autoritativos para safety. El informe definitivo y per-attempt/per-phase usan microsegundos DB enteros y brackets locales del reloj; el formatter de logs no interviene.

**Reproducibilidad y corrección mínima.** La localización de la demora previa a selección se confirma en esta tercera carga independiente del mismo HEAD y límites. La comparación de conclusiones está en [reproducibility.json](reproducibility.json). No se reutilizó ningún journal/recibo de la primera ejecución para reconstruir ésta. La repetición no equivale a una reproducción del FAIL histórico ni garantiza latencias o conteos idénticos.
La evidencia localiza el coste y no identifica una corrección mínima única que preserve los contratos. Ningún cambio del selector/SQL/índices queda justificado por atribuir el exceso a la cola. En particular, la carga ruidosa y el presupuesto de servicio admitido deben distinguirse de una violación del contrato de las organizaciones sanas. La corrección mínima de runtime queda sin definir; no se implementa corrección ni se altera capacidad/polling en este encargo.

**Limpieza y STOP.** [cleanup.json](cleanup.json) confirma las tres bases nuevas eliminadas, cluster detenido, puerto 35453 cerrado, cero clientes/locks pendientes/prepared transactions y directorio de datos propio ausente. [causal-report.json](causal-report.json) es el resultado estructurado autoritativo. Sólo se conservan artefactos nuevos de esta ejecución. La causa histórica permanece ROOT_CAUSE_NOT_CONFIRMED. La investigación se detiene tras esta clasificación; no hay otra ronda automática.
