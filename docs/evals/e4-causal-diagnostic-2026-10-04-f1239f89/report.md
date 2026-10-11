# DIAGNOSTIC_ONLY — CAUSE_CONFIRMED

**Caso sano nuevo, separado del histórico.** En esta ejecución hay 105 excesos
en la organización ruidosa y **uno en la organización sana 2**: Work 165,
inbound 529, planner-2, attempt `d2f6ecfba0cd4554a55c7e945530500c`.
Su persisted→claimed_at es **10,288615 s**. Persisted→eligible consume
7,937639 s; eligible→selection_start, [2,1063966; 2,1072796] s.
Así, ya han transcurrido [10,0440356; 10,0449186] s antes de selección.
La selección completa añade 213,3003 ms, incluidos un SELECT de 182,9794 ms;
selection_end→claim_start añade 0,1587 ms y claim_start→claimed_at,
[30,2374; 31,1204] ms. El claim completo es 124,5552 ms, su SQL 39,6310 ms
y el COMMIT 3,7578 ms. Claimed_at→ACK es [92,5118; 93,3948] ms y
persisted→ACK, [10,3811268; 10,3820098] s. El ACK precede al resultado
del claim en 0,8205 ms. No tiene muestras de lock asociadas.

El presupuesto de 10 s ya estaba agotado en A. **No se atribuyen todos los
288,615 ms de exceso exclusivamente a A**: tras selección se añaden
[243,6964; 244,5794] ms hasta claimed_at, con una contribución SQL medible.
Incluso eliminar ese SELECT completo dejaría el límite ya cruzado antes de
selección; por eso el SELECT no explica por sí solo el incumplimiento.
En el worker que lo admitió, la ventana posterior a elegibilidad contiene
[1.102,5524; 1.103,4354] ms procesando otro turno y 1.003,5921 ms entre polls,
incluida la pausa configurada de 1 s. No se infiere disponibilidad global de
ambos planners a partir de ese worker.

**Corrección mínima candidata, sin implementación.** La evidencia justifica
dirigir una corrección a la espera previa al siguiente poll, especialmente
evitar añadir la pausa fija cuando ya se conoce trabajo elegible pendiente.
Esa es una hipótesis de scheduling; no justifica modificar selector, queries
o índices. No se fija un nuevo valor de polling ni se afirma que esta hipótesis
preserve decisiones y contratos: eso requeriría una propuesta separada y su
prueba de equivalencia. Se confirma la fase y se identifica el coste observado;
no se demuestra una corrección única. El runtime sigue intacto.

In this new run all 106 claimed inbounds above 10 s cross 10 s before selection_start. The excess is localized to the eligible queue before the admitting poll/SELECT, after approximately 7.95 s of the existing eligibility deadline. Selector SQL, claim SQL and commit do not account for the multi-second excess. This confirms the phase, not a historical cause or a uniquely identified tuning change.

Nueva ejecución: `causal-f1239f896754491c8998d56e43356aa1`. HEAD exclusivo: `825db75df68bf076929fa787e77beefe96803350`, rama `codex/e4-capacity-scheduling`, hijo directo de `66702168439b9841a2c988238638a42e6aaee43d`.
Inicio UTC: **2026-10-04T18:15:16.597757+00:00**. No se invocó `b9e_profile` ni `e4_profile`; no es PROFILE-BETA-1 ni aceptación B9E. Umbral intacto de 10 s. El FAIL histórico, su PROFILE y la evaluación posterior del 02-10 permanecen intactos. No se imputan estas mediciones al TurnWork 86 histórico.

La carga conserva dos planners y un sender, batch 1, pausa entre polls de 1 s, dos organizaciones a un inbound cada 10 s y una ruidosa a uno por segundo; 30 s de calentamiento, 300 s de carga y 20 s de drenaje. Provider simulado: dos llamadas LLM de 500 ms, HTTP de dominio 100 ms, Meta 200 ms. Ingreso capturado antes del primer webhook y ambas capturas de planners activas; observador readonly autocommit en proceso separado con intervalo solicitado de 20 ms. PostgreSQL aislado 16.15 con fsync y synchronous_commit on.

| Organización | Ingestados | Reclamados | Safety | >10 s | Pendientes sin claimed_at | Máximo reclamado, s |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 33 | 33 | 11 | 0 | 0 | 9.118616 |
| 2 | 33 | 33 | 11 | 1 | 0 | 10.288615 |
| 3 | 330 | 106 | 0 | 105 | 224 | 243.354657 |

172 claims vinculados y confirmados por commit; 33 intentos sin vínculo. Los pendientes están censurados: no se fabrican claimed_at ni latencias finales. Todos los intentos están en [per-attempt.json](per-attempt.json) y [per-attempt.csv](per-attempt.csv); cada exceso individual está en [over-10-attempts.csv](over-10-attempts.csv) y [over-10-attempts.json](over-10-attempts.json).

**Evidencia por intento.** Los IDs pertenecen exclusivamente a esta DB nueva. Las columnas con límites usan la consulta DB existente como calibración, no logs de segundos.

| Work/inbound/worker | persisted→claimed_at, s | A persisted→eligible, s | A eligible→poll, s | A eligible→selection, s | B selección, ms | B query count / SQL, ms | C, ms | D claim, ms | E COMMIT, ms | persisted→ACK, ms |
|---|---:|---:|---|---|---:|---|---:|---:|---:|---|
| 165/529/planner-2 | 10.288615 | 7.937639 | [2.106263; 2.107146] | [2.106397; 2.107280] | 213.3003 | 1 / 182.9794 | 0.1587 | 124.5552 | 3.7578 | [10381.1268; 10382.0098] |
| 88/86/planner-1 | 121.308616 | 7.946896 | [113.268606; 113.269310] | [113.268727; 113.269431] | 78.3356 | 1 / 51.7820 | 0.1239 | 73.7428 | 1.0964 | [121367.0579; 121367.7618] |
| 172/175/planner-1 | 243.354657 | 7.938961 | [235.207469; 235.208281] | [235.207625; 235.208437] | 184.9388 | 1 / 152.1940 | 0.1570 | 110.5188 | 1.0861 | [243441.3266; 243442.1388] |
| 165/529/planner-2 | 10.288615 | 7.937639 | [2.106263; 2.107146] | [2.106397; 2.107280] | 213.3003 | 1 / 182.9794 | 0.1587 | 124.5552 | 3.7578 | [10381.1268; 10382.0098] |

El máximo es Work 172, inbound 175, org 3, attempt `6e44e12d93f44456b5c502fa5d31481e`: 243.354657 s. El intervalo anterior a selección es [243146.5857; 243147.3979] ms; selección→claimed_at es [207.2591; 208.0713] ms. La separación claim_start→claimed_at es [22.1633; 22.9755] ms, mientras el claim completo es 110.5188 ms. Los extremos de la misma calibración están anticorrelacionados y cierran el total DB; no se suman percentiles ni límites independientes.
En el worker que admite ese intento se observaron estos solapamientos previos: `{"between_polls_including_configured_1s_pause": [124091.6902, 124092.5024], "processing_previous_turn": [86982.8812, 86982.8812]}`. Incluyen spans de otros turnos y tiempo entre polls con la pausa configurada; no se etiqueta todo ese intervalo como sleep ni como indisponibilidad global simultánea de ambos planners.

**Fases A–E y consultas.** [per-phase.json](per-phase.json) separa ordinarios, safety y casos >10 s. A contiene el deadline existente y la espera hasta el poll/selección que admite. B mide selección completa, execute y huecos; C mide el salto a claim; D conserva los locks y todas las queries del intento; E mide la llamada real al COMMIT. D incluye E en el claim ordinario y una parte ocurre después de claimed_at: esos tiempos no deben sumarse íntegros al persisted→claimed_at.
El selector ejecutó 377 queries en 377 selecciones distintas con SQL, incluyendo polls sin admisión; [selector-polls.json](selector-polls.json) conserva sus IDs y timings. Los claims ordinarios tienen una query del selector y safety cero (poll/selección N/A). Todos los execute del run (70318) están en [query-timings.jsonl](query-timings.jsonl), con session/query ID, scope, inicio/fin/error, tablas y flags de locks, sin SQL crudo ni parámetros. La duración SQL de cliente incluye servidor, red, driver y posibles waits; materialización y overhead quedan en selección total.
Cada intento conserva query IDs, duración individual y huecos fin→inicio. El selector de una query no tiene hueco entre queries. Se conserva claim_result, commit_start, commit_end, commit_ack (execute_end_ns), persisted→claimed_at y persisted→commit_ack. En ordinarios el ACK precede al claim_result; el intervalo firmado puede ser negativo. En safety el resultado de la primitiva precede al commit exterior de ingreso. claimed_at no equivale al ACK.

**Waits y bloqueadores.** [waits-summary.json](waits-summary.json) y el journal `waits.jsonl` mantienen asociación por run/session/conexión/PID e intersección con execute. Las muestras ambiguas no se asignan a una query. No se interpolan locks ni se les atribuye toda la duración SQL.
Muestras: 46083; únicas 5803, ambiguas 320, sin query asociada 39960. Queries con lock observado: 10.

| Worker/query | Tabla | Query, ms | Muestras lock | Bloqueadores | Scope |
|---|---|---:|---:|---|---|
| ingress/4199 | agent_conversation | 211.6504 | 9 | {"25060": "planner-2"} | attempt=None, work=None |
| ingress/6645 | agent_contactidentity | 144.6241 | 6 | {"25060": "planner-2"} | attempt=None, work=None |
| ingress/9145 | agent_contactidentity | 91.5595 | 4 | {"25060": "planner-2"} | attempt=None, work=None |
| planner-1/2896 | agent_conversation | 20.7105 | 1 | {"9500": "ingress"} | attempt=None, work=37 |
| planner-1/4201 | agent_conversation | 129.2812 | 4 | {"9500": "ingress"} | attempt=None, work=52 |
| planner-1/10239 | agent_conversation | 55.6591 | 1 | {"9500": "ingress"} | attempt=None, work=132 |
| planner-2/1423 | agent_contactidentity | 25.6356 | 1 | {"9500": "ingress"} | attempt=None, work=20 |
| planner-2/8071 | agent_conversation | 49.4206 | 2 | {"9500": "ingress"} | attempt=None, work=101 |
| planner-2/10671 | agent_conversation | 17.9342 | 1 | {"9500": "ingress"} | attempt=None, work=131 |
| planner-2/11768 | agent_conversation | 16.5295 | 1 | {"9500": "ingress"} | attempt=None, work=145 |

La duración exacta de lock permanece null; el límite conservador es [0; duración completa de query]. Ausencia de muestras no prueba ausencia absoluta de waits. El observador no cambia polling ni ocupa la conexión del worker.

**Integridad, equivalencia y hashes.** Las seis pruebas controladas OFF/ON se ejecutaron nuevamente con IDs prefijados por el UUID nuevo. Cero fallos/errores/skips/xfail; igualdad de decisiones, secuencia SQL, membership, attempts, locks, leases, epoch/fencing, budgets y resultado bajo los estados/barreras controlados. No se promete igualdad temporal ON/OFF ni igualdad de ganador en carreras no controladas. El overhead de captura se incluye en los tiempos.
Las cuatro capturas nuevas suman 193045 eventos, sin failed_writes y con footer, secuencia, SQL/spans y transacciones completos. El observador terminó sin líneas parciales. Todos los procesos terminaron con exit 0. [integrity.json](integrity.json), [functional-results.results.json](functional-results.results.json) y la validación final conservan esa evidencia.
[protected-sources-before.json](protected-sources-before.json) y [protected-sources-after.json](protected-sources-after.json) verifican 1239 fuentes del HEAD y 75 archivos de la primera ejecución diagnóstica sin cambios. No se modificó runtime, selector, índices, SQL, workers, polling, leases, budgets o umbral. Los cambios preexistentes del usuario se conservan. No hay commits nuevos.
La asociación NULL del reconstructor del HEAD para safety se excluye sólo en el adaptador evaluativo: una selección exige selection_id no nulo y span real. Los journals y fuentes no se cambian. Los borradores causal-analysis.json, attempt-summary.* y phase-summary.json no son autoritativos para safety. El informe definitivo y per-attempt/per-phase usan microsegundos DB enteros y brackets locales del reloj; el formatter de logs no interviene.

**Reproducibilidad y corrección mínima.** La localización de la demora previa a selección se confirma por segunda vez en dos cargas independientes del mismo HEAD y límites. La comparación de conclusiones está en [reproducibility.json](reproducibility.json). No se reutilizó ningún journal/recibo de la primera ejecución para reconstruir ésta. La repetición no equivale a una reproducción del FAIL histórico ni garantiza latencias o conteos idénticos.
La evidencia localiza el coste y no identifica una corrección mínima única que preserve los contratos. Ningún cambio del selector/SQL/índices queda justificado por atribuir el exceso a la cola. En particular, la carga ruidosa y el presupuesto de servicio admitido deben distinguirse de una violación del contrato de las organizaciones sanas. La corrección mínima de runtime queda sin definir; no se implementa corrección ni se altera capacidad/polling en este encargo.

**Limpieza y STOP.** [cleanup.json](cleanup.json) confirma las tres bases nuevas eliminadas, cluster detenido, puerto 35451 cerrado, cero clientes/locks pendientes/prepared transactions y directorio de datos propio ausente. [causal-report.json](causal-report.json) es el resultado estructurado autoritativo. Sólo se conservan artefactos nuevos de esta ejecución. La investigación se detiene tras esta clasificación; no hay otra ronda automática.
