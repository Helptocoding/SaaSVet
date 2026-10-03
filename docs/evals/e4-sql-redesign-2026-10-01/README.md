# E4 — Rediseño estructural SQL: cierre

Fecha de inicio: 2026-10-01. Cierre: 2026-10-02 (America/Mexico_City).

## Resultado

**OPTIMIZATION_VERIFIED**. Se eliminó la repetición del scan de Message por Conversation con una sola reescritura ORM, sin esquema ni persistencia nueva. Los recibos finales validan equivalencia, planes, regresión y concurrencia.

## Reporte solicitado — 60 campos

| # | Campo | Resultado / evidencia |
|---:|---|---|
| 1 | Estado | **OPTIMIZATION_VERIFIED**; una única optimización de consulta. |
| 2 | Baseline | `1d04e72f69e9c1576ac1be901624db127b879bf4`; HEAD verificado antes del diseño y sin mezclar cambios previos. |
| 3 | Runtime anterior | `83ee3b24c84b170e22e401cb09a34da5320ae0a3`; selector congelado en el oracle de tests. |
| 4 | Commits | Runtime/tests: `38c4d458996435d6df56b1b337aeb8987fa1045a`. Docs/evidencia: commit que contiene este informe; SHA exacto en el cierre del chat. |
| 5 | HEAD final | El commit de documentación que contiene este informe. Resolver con `git rev-parse HEAD`; se informa el SHA exacto en el chat para evitar una referencia circular. |
| 6 | Alternativas | A: relación no correlacionada de orgs futuras en una sentencia. B: materialización previa en Python, dos sentencias. CTE materializado, forecast sobre <=3 candidatos e índice específico también considerados, con STOP documentado. |
| 7 | SQL OLD | [SQL congelado](sql-old.json); [SQL OLD de la comparación final](sql-post-old.json). Parámetros separados. |
| 8 | SQL candidatos | [A](sql-A.json), [B, dos sentencias](sql-B.json), [NEW final](sql-post-new.json). |
| 9 | Query count OLD | 1 statement por invocación; sin N+1 de Django. |
| 10 | Query count NEW | 1 statement por invocación; alternativa B evaluada con 2. |
| 11 | Índices actuales | 42 índices inventariados en las tres tablas; [DDL](indexes.json) idéntico al [post-fix](indexes-post.json). Message: direction/status, org/conversation/created, conversation/semantic/created y FKs. TurnWork: org/conversation, lease/retry y unicidad. Conversation: org/state/activity, FKs y PK. |
| 12 | Índice nuevo | NO; 0. |
| 13 | Persistencia nueva | NO; sin estado derivado ni counters. |
| 14 | DESIGN_DECISION | [Decisión previa al cambio de runtime](DESIGN_DECISION.md). |
| 15 | Elegida | A, preagregar organizaciones con ordinary pending Message en `(clock, clock+1s]` y correlacionar los predicados de org. |
| 16 | Por qué | Elimina los scans repetidos, mantiene la QuerySet lazy y una sola instantánea SQL; A/B con mejora material comparable. B agrega una lista proporcional a orgs futuras y una segunda instantánea. |
| 17 | Oracle states | Diseño: 320 estados, 640 evaluaciones A/B. Post-fix inicial: 320. Cierre con no-eligible explícito: 321 estados (21 manuales + 300 generados). |
| 18 | Generated states | 300 por ejecución de oracle, seed 20261001; mismas combinaciones comparables. Otros 160 estados en el test unitario de NULL, límites, retries, leases y exclusiones. |
| 19 | Decision mismatches | **0** en diseño, post-fix y cierre; igualdad de IDs de conversaciones/orgs en orden y yield/no-yield. |
| 20 | OLD loops | Conversations 10/25/50/100/250/500/1000: máximo Message 13/28/53/103/253/503/1003. |
| 21 | NEW loops | Máximo Message = **1 en los 14 puntos**. Tres scans de Message, cada uno una vez. Continúan correlaciones sobre org/claims pequeños. |
| 22 | OLD buffers | Stress: raíz 215477 shared hits; Message forecast 214332; shared reads 0; temp read/write 0. |
| 23 | NEW buffers | Stress: raíz 7867 shared hits; tres scans Message de 39 hits cada uno; shared reads 0; temp read/write 0. |
| 24 | Matrix Messages OLD | [Matriz paired completa](matrix-post-messages.json); tabla Messages debajo. |
| 25 | Matrix Messages NEW | [Misma matriz/dataset](matrix-post-messages.json); 8 conversaciones controladas. |
| 26 | Matrix Conversations OLD | [Matriz paired completa](matrix-post-conversations.json); tabla Conversations debajo. Evidencia histórica anterior preservada. |
| 27 | Matrix Conversations NEW | [Misma matriz/dataset](matrix-post-conversations.json); 2000 pending Messages controlados. |
| 28 | p50 before/after | Stress: 5748.761 → 152.606 ms. |
| 29 | p95 before/after | Stress: 7113.485 → 269.216 ms; 26.42x. |
| 30 | p99 before/after | Stress: 7351.682 → 338.031 ms. |
| 31 | max before/after | Stress: 7351.682 → 338.031 ms. |
| 32 | EXPLAIN before | [Plan JSON OLD](explain/post/OLD-conversations-1000.json): ejecución representativa 5557.344 ms; planning 5.818 ms. |
| 33 | EXPLAIN after | [Plan JSON NEW](explain/post/NEW-conversations-1000.json): ejecución representativa 115.546 ms; planning 10.441 ms. |
| 34 | Nodo dominante before | Causa: Seq Scan channels_message forecast, 1003 loops, tiempo inclusivo × loops 5497.443 ms, 1737 filas removidas/loop (promedio redondeado PG). |
| 35 | Nodo dominante after | Trabajo residual forecast: Seq Scan organizations_organization, 1003 loops sobre 3 orgs, 64.192 ms inclusivos. Scan Message futuro: 1 loop, 1.617 ms, 1603 filas removidas. |
| 36 | Scaling before | Trabajo grande de Message repetido aproximadamente por Conversation: crecimiento multiplicativo; hay una sentencia SQL, pero correlación patológica. |
| 37 | Scaling after | Trabajo sobre Message independiente de Conversations en las matrices. Org/recencia/ranking aún escalan con Conversations; no se afirma coste total constante ni escalabilidad universal. |
| 38 | Safety | PASS: bypass explícito de forecast y safety después de W1; suites históricas B5/planner/worker conservadas. |
| 39 | Monotonic READY | PASS: ordinary inbound preclaim hereda el deadline READY y ambos Messages entran en membership; suites W1 monotonic intactas. |
| 40 | B3 | PASS; claim, anchor, cursor, membership, lease/epoch/token/fencing sin cambios. |
| 41 | B9B | PASS; observation/miss con 0 admission; forecast 0 reservation; el presupuesto conserva su autoridad existente tras claim válido. |
| 42 | B9C | PASS; máximo PROCESSING/org observado = 1, sin capacidad/counters derivados del forecast. |
| 43 | Multiprocess | 5 tests nuevos PASS con OS PIDs y PostgreSQL backend PIDs distintos; mismos candidatos, miss/fallback, slot ocupado, desaparición, deadline, safety y ordinary join. [Journal](repair-processes.results.b9c-processes.jsonl). |
| 44 | Regression | **775 históricos + 3 nuevos de selector + 5 nuevos de procesos = 783 IDs únicos PASS**. Expectativas históricas sin editar; B3/B5/B6/B7/B8/B9A/B9B/B9C, E4, W1, planner, worker, B4 sender y módulos afectados incluidos. |
| 45 | IDs | [Inventario único aprobado](passed-ids.json); históricos: [659 aprobados retenidos](regression-partial.json) + [continuación 0](regression-resume-0.results.json)/[continuación 1](regression-resume-1.results.json); unitarios [journal](new-final.results.passed.jsonl), procesos [recibo](repair-processes.results.json). |
| 46 | skips/xfail | 0 skips, 0 xfail; 0 fallos y 0 errores en los gates finales. |
| 47 | Checks | PASS: migrate, check, makemigrations --check --dry-run y migrate --check. [Recibo](checks.exit.json). |
| 48 | Migrations | 0 nuevas; esquema y DDL de índices iguales. |
| 49 | Rollback | Revertir únicamente el commit runtime/tests indicado en campo 4 mediante git revert. Sin migración inversa ni transformación de datos; selector OLD disponible como referencia de tests. No se ejecutó rollback. |
| 50 | Privacy | Datos sintéticos aislados; artefactos SQL/oracle/plans guardan estados/IDs/tiempos, sin cuerpos, prompts/responses, phones o names reales. Logs funcionales crudos descartados después de extraer recibos; [registro con hashes](privacy.json). Sin instrumentación productiva. |
| 51 | Infra cleanup | PASS: bases propias eliminadas, PG del experimento detenido y directorio de datos ausente; binarios/venv compartidos preservados. [Recibo](cleanup.json). |
| 52 | PROFILE run | NO; no se ejecutó PROFILE-BETA-1. |
| 53 | B9E run | NO; sin ejecutar una suite B9E formal ni modificar sus umbrales. |
| 54 | PROFILE histórico | FAIL / PRODUCT_FAILURE, runtime 83ee3b2, B9E-LOAD-01-CLAIM p95=10.015949 s contra 10 s. No actualizado por estos resultados SQL. |
| 55 | B9E status | FAIL histórico, intacto. |
| 56 | B9 | IN_PROGRESS. |
| 57 | Production gates | B0 cerrado; B7B=False; flags={}; release grants=[]; PENDING_ACTIVATION_REQUIREMENTS. Configuración/contratos del repo conservados; no hubo consulta ni operación sobre un servicio de producción. |
| 58 | Active clinics | 0 activadas por este encargo; estado documental requerido = 0. |
| 59 | Deploy | NO. |
| 60 | Próximo paso | STOP tras una optimización verificada. PROFILE-BETA-1 será un encargo separado sobre el runtime congelado. Sin segundo tuning ni cambios de quiet/hard cap/N/batch/poll/LLM calls. |

## Método y límites

PostgreSQL 16.15 real aislado, fsync=on y synchronous_commit=on. Una base recién clonada del template migrado por punto; OLD y NEW se ejecutaron sobre exactamente el mismo dataset, con cinco warmups independientes y 30 repeticiones por variante. Métrica: Execution Time de EXPLAIN ANALYZE en ms, excluye planning y red. No se vació la caché del SO. OLD se ejecutó primero. Proporción pending READY/future=80/20, tres organizaciones controladas y tres Conversations históricas adicionales para recencia.

Los percentiles usan el índice `ceil(q/100*(n-1))` del vector ordenado, fijado en benchmark.py. Son mediciones sintéticas con ruido de scheduling del host; no crean un SLO SQL. En Messages=10 hay ocho READY y dos future, con ocho Conversations controladas; las tres históricas se reportan aparte. La cardinalidad de organizaciones y el historial durable no se escalaron independientemente.

Los tiempos y buffers de un nodo EXPLAIN son inclusivos de sus subplanes; no deben sumarse para inferir tiempo propio. El Index Scan externo de Conversation domina el tiempo inclusivo en ambos planes: 5550.628 ms OLD y 109.217 ms NEW. El diagnóstico causal es el forecast Message repetido dentro de ese nodo. La sustitución deja un scan de la pequeña relación de organizaciones por Conversation. Ranking y recencia siguen teniendo trabajo proporcional a Conversations.

La auditoría congelada tenía p95=5336.076 ms para C=1000. La comparación paired adicional midió OLD=7113.485 ms; se conservan ambos recibos y no se reemplaza la evidencia histórica por la nueva.

## Matriz Messages — 8 Conversations controladas

| Cardinalidad | OLD p50 | NEW p50 | OLD p95 | NEW p95 | OLD p99 | NEW p99 | OLD max | NEW max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 0.968 | 1.012 | 1.658 | 1.444 | 1.717 | 1.551 | 1.717 | 1.551 |
| 50 | 1.813 | 1.474 | 2.665 | 1.911 | 3.319 | 1.959 | 3.319 | 1.959 |
| 100 | 2.692 | 1.247 | 4.163 | 2.534 | 4.208 | 2.599 | 4.208 | 2.599 |
| 250 | 4.409 | 1.319 | 5.750 | 2.139 | 6.527 | 2.238 | 6.527 | 2.238 |
| 500 | 11.242 | 1.762 | 14.271 | 3.684 | 14.781 | 3.797 | 14.781 | 3.797 |
| 1000 | 19.397 | 2.348 | 29.954 | 4.859 | 31.213 | 7.347 | 31.213 | 7.347 |
| 2000 | 61.065 | 16.523 | 109.847 | 32.218 | 161.266 | 38.330 | 161.266 | 38.330 |

## Matriz Conversations — 2000 pending Messages

| Cardinalidad | OLD p50 | NEW p50 | OLD p95 | NEW p95 | OLD p99 | NEW p99 | OLD max | NEW max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 64.403 | 6.515 | 95.909 | 7.527 | 98.567 | 13.942 | 98.567 | 13.942 |
| 25 | 142.398 | 13.005 | 170.353 | 35.029 | 191.462 | 44.083 | 191.462 | 44.083 |
| 50 | 346.847 | 16.238 | 452.898 | 31.690 | 508.768 | 45.719 | 508.768 | 45.719 |
| 100 | 532.825 | 16.801 | 639.611 | 25.905 | 698.929 | 26.366 | 698.929 | 26.366 |
| 250 | 1062.549 | 30.983 | 2115.235 | 114.223 | 2198.859 | 122.333 | 2198.859 | 122.333 |
| 500 | 2794.719 | 75.515 | 3042.628 | 103.868 | 3087.395 | 104.776 | 3087.395 | 104.776 |
| 1000 | 5748.761 | 152.606 | 7113.485 | 269.216 | 7351.682 | 338.031 | 7351.682 | 338.031 |

## Diseño medido antes de implementar

Matrices A/B completas: [Messages](matrix-full-messages.json) y [Conversations](matrix-full-conversations.json). Incluyen query count, p50/p95/p99/max, planning, nodos, loops, shared hit/read, filas removidas, temp buffers y sorts. B suma Execution Time/planning de sus dos statements. [Planes completos](explain/full/). A fue elegida antes de editar worker.py; el registro de decisión conserva sus STOPs y límites.

En el stress final todos los temp buffers son cero; sorts quicksort de 25 KB. Los JSON de planes conservan las métricas por nodo para todos los puntos. Ningún índice fue añadido para obtener esta mejora.

## Cobertura de estados y procesos

[Oracle final](oracle-final.json) y [clasificación explícita de yield](oracle-classified.json): healthy READY, dos healthy, noisy/near/far, busy current/upcoming, never-claimed, recencia menor/mayor/igual, safety/W1, READY join, candidato desaparecido/busy, deadline crossed, múltiples Conversations/org, múltiples orgs, stale observation y no eligible. Los estados de observación se comparan en orden con OLD; las transiciones de claim y membership se verifican además con procesos reales. La clasificación adicional repite los mismos 321 estados, sin contarlos como cobertura independiente. Distingue una selección vacía de un yield comparando contra el mismo selector con una relación futura vacía; no-eligible tiene yield=False. Los recibos anteriores conservan su bandera histórica de vacío/no-vacío.

Los procesos observan ambos antes del primer claim y permanecen vivos para observar el efecto del segundo claim/miss. Los PIDs independientes constan en el journal. El clock controlado permite cruzar el límite de deadline de manera determinista; no representa una medición temporal del poll productivo. El claim transaccional no fue modificado.

Los generadores combinan el estado observado por el selector sobre fixtures sintéticos con FKs y ámbitos consistentes. No cambian las FKs ni los campos de anchor/cursor/context; conservan unicidad, completed/outcome y los requisitos de token/lease/attempts para PROCESSING. PostgreSQL aplica los constraints durante las mutaciones. No son un replay completo de cada historia durable: ese contrato se prueba por separado con claims reales y las suites B3/B9C.

## Incidentes del harness

Se conservan los recibos de intentos anteriores como diagnósticos, fuera del conjunto de aprobación final: descubrimiento inicial de clases importadas duplicó selección (35 frente a 8) y se detuvo solo ese árbol de procesos; imports convertidos a aliases de módulo. Después, cuatro failures y un error de procesos se debieron al keyword erróneo now en el harness nuevo. Se corrigió a eligible_at sin cambiar durable.claim_turn; los cinco procesos se repitieron y aprobaron. Los tres unitarios ya aprobados se aceptan por IDs y hashes de fuentes finales, sin contar los fallos históricos como éxitos.

La interrupción inicial del host ocurrió después de migraciones y antes de recibos de matrices. Se recuperó el template aislado. Una colisión de nombres SQL por el filesystem Windows ocurrió antes de medir el primer punto post-fix: se cambiaron los nombres a sql-post-old/new y se recreó solo el punto incompleto. Ningún recibo exitoso de benchmark fue sobrescrito. [Registro de incidentes](incidents.json).

Una segunda interrupción dejó las dos tandas históricas sin recibo final, después de 659 éxitos por ID escritos al journal. Se verificaron todos los hashes de fuentes y la ausencia de fallos en sus logs; se retuvieron solo los IDs con status=ok y se ejecutaron los 116 pendientes en bases nuevas clonadas del mismo template. El inventario final prueba 775 IDs históricos únicos, sin duplicar ni declarar completo el run interrumpido. [Recuperación](environment-regression-resume.json).

## Reproducción y trazabilidad

Scripts locales: benchmark.py (pilot/full/resume/post), candidates.py, oracle.py, verify.py, recover.py, analyze.py, cleanup.py, sanitize.py y report.py. La reproducción requiere los binarios PG16 y el entorno Python de aceptación existentes; sus rutas están en environment-*.json. Los guards de HEAD del driver conservan la baseline histórica: una nueva reproducción debe fijar explícitamente su SHA auditado y usar un directorio de salida nuevo. benchmark.py rechaza sobrescribir recibos exitosos. Este run utilizó full interrumpido, resume con template retenido y después post; una corrida full normal limpia su cluster al terminar y debe preparar de nuevo un template aislado antes de post.

[Resumen de verificación](verification-summary.json), [resumen de métricas](metrics-summary.json), [hashes de fuentes](regression-0.results.sources.json) y [manifest de artefactos](artifact-manifest.json). Los hashes de fuentes/recibos son de bytes del working tree auditado en Windows; el manifest incluye además SHA256 normalizado a LF para verificar artefactos tras otro checkout Git. Commit docs identificado por pertenencia para evitar hashes autorreferenciales.
