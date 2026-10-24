# E4 / PROFILE-BETA-1 — informe diagnóstico final

Fecha de cierre: 2026-10-03. HEAD auditado: `6e59f6c05514ad6eca0985796e538de4fd749560`.

## 1. Resultado: B — CAUSA NO CONFIRMADA

**`ROOT_CAUSE_NOT_CONFIRMED → STOP`**. Se cierra definitivamente esta línea de investigación de optimización de E4. No se propone otra ronda de medición.

La evidencia permite localizar la mayor parte del intervalo de TurnWork 86 antes del último SELECT, y muestra ocupación previa y una pausa prevista del harness. No permite atribuir causalmente, de forma reproducible, el exceso de **15.949 ms** a un defecto localizado del selector, del claim, del polling o de PostgreSQL. Tampoco acredita que el jitter domine: por eso la clasificación es B.

El dato conservado es **10.015949 s**, no 10015949 segundos; `eligible→claim` es **2.089121 s**. Se mantiene el FAIL histórico, el umbral de 10 s y su denominador completo de 60 muestras.

## 2. Evidencia y alcance de D/H/I/J

Se inspeccionaron los contratos canónicos B9C/B9D, la implementación E4 y los recibos del PROFILE histórico. B9C conserva la autoridad transaccional del claim: Organization → Conversation → TurnWork/Message, aislamiento por tenant, lease/token/epoch y máximo un trabajo activo por organización. El selector E4 es consultivo. B9D exige evidencia del candidato y requisitos operativos; este diagnóstico no aprueba el release.

| Dimensión | Evidencia obtenida | Límite definitivo |
| --- | --- | --- |
| H | IDs, PIDs Python/backend, timestamps durables, duración registrada del último selector y número de selectores observados después de elegibilidad en el backend que reclama; vecinos de rango 56–60 | No sobrevivieron SQL/parámetros completos, plan del evento, buffers/loops del evento, todas las consultas del claim ni sus waits |
| I | Separación histórica de persisted→eligible, eligible→claim y estimación anterior/posterior al último selector; secuencia de ambos planners | No existen marcas subsegundo de fin del turno previo, entrada/salida de sleep, despertar del proceso ni comienzo real del SELECT |
| J | Plan de cierre histórico; captura posterior aislada de pg_stats, páginas, CTID, visibilidad, conexiones, locks/waits y planes | La base histórica se eliminó; no se puede reconstruir su estado físico/estadístico en los instantes relevantes |
| D | Inspección de la alternativa existente en HEAD y comparación de sus predicados con el canónico | Omite la excepción de safety; no demuestra equivalencia. No se ejecutó una comparación de velocidad con esa alternativa |

Recibos históricos: [base-diagnostics.json](C:/Users/LAP/.codex/worktrees/e4-causal-audit-6e59/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/base-diagnostics.json), [sql-observations.jsonl](C:/Users/LAP/.codex/worktrees/e4-causal-audit-6e59/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/sql-observations.jsonl), logs de [planner-1](C:/Users/LAP/.codex/worktrees/e4-causal-audit-6e59/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/base-planner-1.log) y [planner-2](C:/Users/LAP/.codex/worktrees/e4-causal-audit-6e59/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/base-planner-2.log). La unión conserva los cinco vecinos en [final-history.json](C:/Users/LAP/.codex/worktrees/e4-causal-audit-6e59/VeterinariaSaaS/docs/evals/e4-causal-audit-2026-10-03/final-history.json); no elimina ni reemplaza los 60 originales.

La comprobación adicional fue una observación SQL estacionaria sobre una base PostgreSQL aislada: **354 conversaciones, 10.000 mensajes, 3 organizaciones, 50 TurnWork PENDING no elegibles, 3 COMPLETED y 0 TurnWork de retry/lease elegibles**. Tenía 203 mensajes pendientes elegibles respecto al reloj sintético y uno en la ventana futura. Se observó el selector sin modificarlo y un claim real revertido. No hubo carga temporal de workers ni cálculo de un nuevo p95 de PROFILE. El reloj fijo, la distribución sintética y el estado recién creado impiden considerarla una reproducción del FAIL temporal.

Los resultados anteriores de [matrix.json](C:/Users/LAP/.codex/worktrees/e4-causal-audit-6e59/VeterinariaSaaS/docs/evals/e4-causal-audit-2026-10-03/matrix.json) y [layout.json](C:/Users/LAP/.codex/worktrees/e4-causal-audit-6e59/VeterinariaSaaS/docs/evals/e4-causal-audit-2026-10-03/layout.json) se mantienen como antecedentes exploratorios. Su harness hizo ANALYZE por cohorte y VACUUM ANALYZE entre cohortes revertidas. No constituyen una reconstrucción del estado histórico ni una comparación física equivalente con la captura final, que no realizó mantenimiento manual. Ninguna de esas observaciones declara PASS.

## 3. Timeline causal histórico

El percentil canónico usa `ceil(0.95 × (60−1)) = 57`, índice cero: la muestra **58**, TurnWork **86**, Message **275**, Conversation **14**, organización **2** — índice de fixture **1**. Lo reclamó planner-1: PID Python **27968**, backend PostgreSQL **34424**. Planner-2 tenía PID Python **12792**, backend **34276**.

| Hito de TurnWork 86 | UTC | Calidad de evidencia |
| --- | --- | --- |
| persisted | 2026-10-01 07:27:05.415631 | Message.created_at conservado |
| eligible | 07:27:13.342459 | available_at; posterior a created_at en esta muestra |
| Inicio del último SELECT, estimado | 07:27:15.317233 | Timestamp del log menos duración; no es una marca capturada al comenzar |
| Timestamp del registro de duración | 07:27:15.398 | Log PostgreSQL con resolución de milisegundos; próximo al final, no un timestamp exacto de fin |
| claimed_at | 07:27:15.431580 | Reloj DB al entrar en `_claim_turn_locked`; anterior a membresía/CAS/commit |

| Tramo | Duración | Interpretación |
| --- | ---: | --- |
| persisted→eligible | 7.926828 s | Diferencia de timestamps durables |
| eligible→inicio estimado SELECT | ≈1.974774 s | Residuo previo; su precisión aparente de microsegundos no está justificada |
| Último SELECT | 0.080767 s | Duración registrada por PostgreSQL |
| Registro final SELECT→claimed_at | ≈0.033580 s | Incluye retorno al cliente y operaciones previas al reloj de claim; no equivale a toda la transacción |
| eligible→claimed_at | 2.089121 s | Diferencia durable |
| persisted→claimed_at | **10.015949 s** | FAIL, exceso **0.015949 s** |

La suma reconstruida ubica aproximadamente el **94.5 %** de eligible→claim antes del último selector; este último representa aproximadamente el **3.9 %**. Esto descarta atribuir íntegramente los 2.089121 s a esa ejecución. No excluye efectos de selectores anteriores sobre la planificación de turnos posteriores.

Vecinos conservados, ordenados por latencia ascendente. Los selectores indicados son los últimos del backend reclamante antes de claimed_at; no se conservaron sus IDs de resultado:

| Rango / TurnWork | Planner / backend | persisted→eligible (s) | eligible→claim (s) | persisted→claim (s) | Último SELECT (ms) | Pre-SELECT estimado (s) | Post-log→claim (s) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 56 / 153 | 1 / 34424 | 7.946727 | 1.510543 | 9.457270 | 188.663 | 1.285737 | 0.036143 |
| 57 / 143 | 2 / 34276 | 7.939089 | 1.790376 | 9.729465 | 184.245 | 1.579443 | 0.026688 |
| **58 / 86** | **1 / 34424** | **7.926828** | **2.089121** | **10.015949** | **80.767** | **1.974774** | **0.033580** |
| 59 / 115 | 2 / 34276 | 7.931663 | 2.313048 | 10.244711 | 113.688 | 2.164443 | 0.034917 |
| 60 / 66 | 2 / 34276 | 7.889717 | 2.495969 | 10.385686 | 439.520 | 1.883755 | 0.172694 |

Para 86, 115 y 66 se observó **un selector** después de elegibilidad en el backend que reclamó. Esto no es el query count de la transacción ni el número global de consultas mientras esperaban.

El observador usó `%m`, timestamp con milisegundos, y descartó el SQL después de extraer duración/PID. Restar duración al timestamp de emisión introduce incertidumbre de resolución, emisión del log y reloj que no se midió. Los timestamps del worker usan `formatTime` local con una `Z` literal y resolución de segundos. La conversión de seis horas se infiere al cruzarlos con los timestamps DB. No se utilizan como marcas UTC subsegundo. [Documentación PostgreSQL 16 de logging](https://www.postgresql.org/docs/16/runtime-config-logging.html).

## 4. Selector SQL y alternativa D

El selector canónico incluye trabajo PENDING debido o PROCESSING con lease vencida, o inbound pendiente sin TurnWork ya disponible; excluye candidatos intentados y organizaciones ocupadas; toma una conversación por organización; ordena por última admisión, actividad e ID; limita a tres. El forecast de una organización menos recientemente atendida y disponible dentro de un segundo puede diferir selección. Safety conserva su excepción. El claim vuelve a validar tenant, estado, elegibilidad, lease, epoch y fencing bajo locks/CAS.

El histórico contiene **352 registros de selector**, incluyendo warmup y drain: p50 97.497 ms, p95 291.922 ms, máximo 622.632 ms. Esta distribución no tiene el denominador del gate de 60 inbounds y no demuestra cuánto esperó cada Message.

El SQL completo y sus parámetros históricos no se persistieron por diseño del observador. El código congelado permite conocer el mecanismo, pero no recuperar los parámetros ni exclusiones exactos de la llamada histórica. Su último registro se asocia a 86 por backend y proximidad temporal; el observador no capturó sus IDs de salida.

En la captura posterior están los SQL/parámetros enviados al cursor Django y las duraciones individuales con `perf_counter_ns`, junto a marcas UTC de microsegundos. El wrapper mide ejecución del cursor en el cliente; no equivale a un cronómetro puro del executor PostgreSQL y no incluye todo el fetch. Cada evaluación completa del selector tuvo **1 consulta**, devolvió `[1,2,3]` y duró **220.1388, 216.9061 y 168.9552 ms**. No se calcula un p95 con esas tres observaciones. El claim aislado tuvo **33 consultas**, con suma de tiempos de cursor **37.6851 ms**; el conteo incluye el savepoint interno y excluye BEGIN/ROLLBACK externos y lecturas del observador. [Recibo completo](C:/Users/LAP/.codex/worktrees/e4-causal-audit-6e59/VeterinariaSaaS/docs/evals/e4-causal-audit-2026-10-03/final-isolated-postgresql.json).

La función experimental antigua `tests/e4_claim_candidate.py:candidates` carece de `pk__in=pending_safety` en la condición del forecast. Con una organización ya atendida, safety pendiente y otra organización idle menos recientemente atendida próxima a elegibilidad, el canónico conserva el candidato y esa alternativa puede excluirlo. Falla equivalencia de IDs/exclusiones. Una llamada directa a `claim_turn` tampoco conserva el conjunto/orden de candidatos del selector. Ninguno sirve como D equivalente.

No se construyó ni incorporó una consulta alternativa cuya equivalencia completa esté demostrada. No hubo medición de rendimiento de una alternativa semánticamente distinta, cambio de query ni comparación antes/después de una optimización.

## 5. PostgreSQL: planes, buffers y estado J

El **EXPLAIN de cierre histórico**, ejecutado después de la carga, registró Planning Time **8.601 ms** y Execution Time **127.583 ms**. Su Bitmap Heap Scan de Message tenía **354 loops**, **9.912 shared hit**, **0 shared read** y Actual Total Time **0.193 ms por loop**. Aproximadamente **68.322 ms** corresponden a ese nodo en aquella ejecución, incluyendo su descendencia; no deben sumarse nuevamente los tiempos de sus hijos. Los hits son accesos acumulados a buffers, no 9.912 páginas únicas ni lecturas de disco. PostgreSQL informa tiempos/filas como promedios por loop. [Documentación de EXPLAIN](https://www.postgresql.org/docs/16/using-explain.html).

Ese plan **no es el plan del SELECT que precedió a TurnWork 86**. Tampoco hay evidencia de que sus 9.912 hits ocurrieran entonces. Por tanto, no explican causalmente el crecimiento del claim p95. Sí demuestran un coste real de un subplan repetido en la ejecución de cierre.

El antecedente G mantuvo las cardinalidades y mostró 2.816 hits con pendientes agrupados frente a 11.968 con pendientes dispersos, ambos con 352 loops. Los tiempos de dos pares no fueron consistentes: agrupado 40.352/64.277 ms; disperso 68.778/50.942 ms. La disposición física afecta los accesos aun con iguales totales; esas observaciones no aíslan el exceso temporal histórico ni establecen jitter dominante. Las cohortes A/B/C anteriores tampoco reprodujeron el gate persisted→claim.

La captura final J compara únicamente ejecuciones sobre **la misma cohorte estacionaria**, antes de realizar el claim revertido:

| Estado observado | Valor |
| --- | --- |
| Páginas heap reales, bloque de 8 KiB | Conversation 7; Message 206; TurnWork 2 |
| Catálogo relpages / reltuples | 0 / −1 en las tres tablas, aún sin estadísticas de análisis |
| pg_stats para columnas relevantes, antes y después del selector | 0 filas; no equivale a correlación o distribución cero |
| ANALYZE / autoanalyze / vacuum / autovacuum | Ninguno registrado en esas tablas; sin mantenimiento manual |
| Message pendientes / procesados | 204 / 9.796; pendientes en 32 bloques, rango CTID de bloque 0–202 |
| Visibilidad | 0 páginas all-visible / all-frozen en las tres tablas |
| Tuplas muertas observadas antes del selector | Message 53 por asociación de anchors; Conversation/TurnWork 0 |
| Plan posterior sobre ese SQL/cohorte | Index Scan `message_send_ready`; subplan Message 352 loops, 11.968 hits, 0 reads; 0.293 ms por loop |
| EXPLAIN posterior | Planning 9.492 ms; Execution 131.087 ms |
| Muestreo del backend observado | 33 muestras: 14 sin wait registrado; 19 ClientRead; 0 locks no concedidos |

`pg_visibility` se instaló solo en la base desechable para leer su mapa; no creó un índice ni ejecutó mantenimiento. Los planes estimado y ANALYZE completos se conservan en el recibo. Se ejecutaron separadamente después de las tres llamadas observadas; **no son sus planes contemporáneos**, ni evidencia histórica. Las capturas de relaciones/estadísticas/visibilidad anteriores y posteriores permiten comprobar el estado comparable de esa cohorte. El muestreo de waits cada 20 ms puede omitir esperas breves y añade carga del observador.

La diferencia de plan respecto al cierre histórico no se interpreta como mejora, regresión o prueba de estadísticas culpables: las cohortes no son equivalentes. Las estadísticas, visibilidad, páginas, dead tuples, conexiones y waits históricos de 86/115/66 son **no determinables** porque [cleanup.json](C:/Users/LAP/.codex/worktrees/e4-causal-audit-6e59/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/cleanup.json) acredita eliminación de la base y del directorio físico.

## 6. Worker, ocupación y polling

La topología congelada es dos planners secuenciales y un sender independiente, batch 1. El harness ejecuta `run_agent_worker(once=True, poll=1)` y después `time.sleep(1)`. El command no realiza su sleep interno al usar `once=True`; hay una pausa externa prevista de un segundo. Cada planner termina `_run_turn` antes de volver a seleccionar.

En la ventana de 86, planner-1 reclamó el trabajo ruidoso **83** a las 07:27:12 aproximadas; completó y terminó el ciclo en el segundo **14**; comenzó el siguiente en el segundo **15**. Planner-2 comenzó un ciclo en el segundo **13**, reclamó el trabajo sano **84** en el segundo **14** y lo completó en el **16**. Ambos muestran actividad durante parte de la espera de 86.

Esto sustenta que existe ocupación previa y que hay una pausa de polling entre el turno 83 y la selección de 86. No proporciona una partición precisa de los ≈1.975 s entre ejecución ordinaria anterior, pausa prevista, costes de entrada al command y retraso del scheduler. No hay trazas históricas del despertar ni de CPU/IO del host.

El fake LLM hace **0.5 s por llamada**, y el READ ordinario ejecutó **dos llamadas**, además del READ HTTP de 0.1 s. La discrepancia con una descripción de una llamada estaba documentada; no se cambió. Es una variable de ocupación real de la carga artificial. No se aisló un contrafactual equivalente que pruebe que ella explica el exceso de 15.949 ms. No se atribuye el FAIL a la carga artificial como causa confirmada.

## 7. Variables e interpretaciones descartadas

- Los 2.089121 s de 86 no fueron íntegramente el último SELECT: su duración registrada fue 80.767 ms.
- 9.912 hits no representan 9.912 lecturas físicas ni un dato capturado durante el claim de 86.
- El número total de mensajes por sí solo no explica de forma monotónica el crecimiento en los antecedentes A; cambiar conversaciones, ruido o disposición física cambia también el trabajo del selector.
- La alternativa antigua no es una corrección equivalente por su exclusión de safety.
- El FAIL no proviene de redondear, eliminar IDs o de una muestra faltante: n=60, missing=0, rank 58 conservado y comparación estricta con 10 s.
- Los recibos del corpus histórico contienen cero violaciones en sus assertions de aislamiento, presupuesto, capacidad y fencing. Eso no descarta waits transitorios ni demuestra todos los comportamientos posibles en producción.
- No se observó una reextensión de READY en la carga histórica. El recibo advierte que no hubo UPDATE de deadline ni joined-READY en esa carga, por lo que no se usa ese cero como prueba universal.

## 8. Variables no determinables y límites del entorno

No se pueden recuperar el SQL/parámetros y exclusiones completos, salida del selector, planes/buffers/loops, query count integral, waits/locks y estado físico/estadístico **del evento histórico**. Tampoco las marcas subsegundo que separen ocupación, pausa, scheduler y jitter de los planners. Son variables críticas sin registro ni snapshot recuperable; no se propone medirlas en otra ronda para esta línea.

Las marcas nuevas tienen resolución suficiente para consultas nuevas y se conservan íntegramente. No pueden instrumentar retroactivamente los procesos y la base ya eliminados. No se alteró el comportamiento de un worker para intentar obtenerlas; la comprobación final fue SQL aislado y no un replay temporal.

El acceso al Python aislado funcionó y no se encontró `index.lock`. Hubo una incidencia de preparación: el proceso Python esperó al lanzador `rtk proxy pg_ctl ... start` mientras el servidor de prueba estaba disponible. Se verificó el servidor propio y se observó esa misma instancia desde otro proceso, conservando los directorios y sin cambiar permisos. No se contabilizó ninguna medición de ese intento de preparación. No hubo bloqueo ACL, eliminación de index.lock ni un bypass destructivo.

La base de diagnóstico final fue eliminada, las conexiones quedaron en 0, locks pendientes 0, prepared transactions 0 y el servidor quedó detenido con el puerto **35446 cerrado**. Sus directorios de inicialización se conservaron. No se dejó tráfico de prueba en producción.

## 9. Impacto sobre el FAIL histórico y producción

**PROFILE-BETA-1 continúa FAIL** en B9E-LOAD-01-CLAIM. Los 15.949 ms exceden el umbral; la incertidumbre del diagnóstico no invalida el cálculo durable del gate. Las cuatro variantes detenidas no se ejecutaron. No se ejecutó PROFILE formal en esta fase, no se cambió tamaño de muestra/corpus/assertions/criterio y no se declara E4/B9E aprobado.

El checkout de auditoría permaneció en el HEAD indicado, sin diff del runtime, configuración, perfil o corpus contra ese HEAD. La configuración/manifest de release conserva B0 cerrado, `AGENT_B7B_CONSENT_ENABLED=False` por defecto, `AGENT_OPERATION_EXECUTION_ENABLED={}`, grants vacíos y `PENDING_ACTIVATION_REQUIREMENTS`. Esta fase activó **0 clínicas**, realizó **0 deploys** y **0 commits de runtime**. No se accedió al entorno productivo ni se alteraron sus permisos, configuración o datos. Las organizaciones sintéticas fueron exclusivamente fixtures en PostgreSQL local.

## 10. Corrección mínima justificable y conclusión

**No existe una corrección mínima justificable con esta evidencia.** Hay costes observables del selector, ocupación previa y polling previsto. No existe una intervención equivalente que demuestre de forma reproducible cuál de ellos explica el exceso histórico y que su corrección lleve el p95 por debajo de 10 s.

Que 80.767 ms sea mayor que 15.949 ms no prueba que ahorrar ese tiempo produzca PASS: cambiar tiempos de ciclos altera las fases de ambos planners, la ocupación y el orden de admisión. El plan de cierre tampoco demuestra un ahorro en aquel SELECT. No se prescribe tuning de queries, índices, caché, polling, leases, timeouts ni workers.

**Resultado único B. `ROOT_CAUSE_NOT_CONFIRMED → STOP`. FAIL preservado; producción contenida.**
