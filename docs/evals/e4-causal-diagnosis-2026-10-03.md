# E4 — Diagnóstico causal final de PROFILE-BETA-1

Fecha: 2026-10-03. **Resultado único: D. CAUSA NO CONFIRMADA.**

**`ROOT_CAUSE_NOT_CONFIRMED → STOP`.** Se cierra esta investigación de optimización. No se propone una corrección concreta ni otra ronda de medición. No existe evidencia suficiente para atribuir reproduciblemente los **15.949 ms** de exceso histórico a un mecanismo localizado.

**PROFILE-BETA-1 histórico permanece FAIL: p95 persisted→claim = 10.015949 s, umbral 10 s, 60 muestras, cero faltantes, rango 58, TurnWork 86.** E4/B9E siguen sin aprobación. El diagnóstico nuevo tiene instrumentación y ninguna autoridad de aceptación.

## 1. Estado inicial y alcance

Se trabajó en el worktree aislado `e4-causal-audit-6e59/VeterinariaSaaS`, exactamente en `6e59f6c05514ad6eca0985796e538de4fd749560`. El backend productivo coincide con `83ee3b24c84b170e22e401cb09a34da5320ae0a3`; las únicas diferencias de backend entre ambos commits son dos archivos de tests diagnósticos ya existentes: `e4_claim_candidate.py` y `e4_claim_diagnostic.py`.

Antes de escribir evidencia nueva se registraron HEAD, estado literal y hashes del checkout principal en [preflight.json](e4-causal-diagnosis-2026-10-03/preflight.json). Su HEAD era `66702168439b9841a2c988238638a42e6aaee43d` y tenía estas seis entradas:

```text
 D DEPLOY_VPS_PLAN.md
 D DEPLOY_VPS_STATUS.md
 M skills-lock.json
?? docs/auditoria-agente-conversacional-veterinario-2026-09-10.md
?? docs/discrepancia-encargo-b9-2026-09-26.md
?? docs/evals/e4-bounded-yield-sql-audit-2026-10-01.md
```

Las seis quedan excluidas por instrucción explícita del usuario: son cambios preexistentes ajenos a D/H/I/J. Se conservaron sus contenidos y eliminaciones. La ruta del último documento es la registrada por Git. No se infirió ninguna correspondencia con el antiguo listado de «cuatro cambios». El directorio sin seguimiento de la auditoría anterior también quedó fuera del commit nuevo.

Se inspeccionaron el [contrato B9C](../contrato-concurrencia-b9c.md), el [contrato B9D](../contrato-beta-release-b9d.md), E4, la matriz anterior y los recibos del [PROFILE histórico](profile-beta-1-e4-2026-10-01/report.md). La matriz anterior incluía ANALYZE manual y comparaba G por cardinalidades, sin identidad completa de filas; se conservó como antecedente y no se usó como prueba causal de este cierre.

La adquisición de autoridad sigue siendo el claim B3/B9C: un trabajo activo por organización, locks Organization→Conversation→TurnWork→Message, token/epoch/CAS y reloj de PostgreSQL. E4 solo observa candidatos. READY y las fixtures diagnósticas no conceden permisos B9D.

## 2. Hipótesis y conclusión que admite la evidencia

| Hipótesis | Resultado |
| --- | --- |
| El SELECT consume prácticamente los 10 s | Incompatible con las duraciones históricas observadas: 80.767 ms en el SELECT asociado a 86; 7.926828 s ocurrieron antes de elegibilidad. |
| El Bitmap Heap Scan de cierre, con 9,912 hits, causó el cruce | No confirmado: no existe el plan ejecutado para 86; el plan de cierre corresponde a otro instante. |
| Más mensajes, manteniendo conversaciones, basta para explicar el crecimiento | No reproducido de forma monotónica en A; importan los mensajes pendientes, su ubicación y las conversaciones sobre las que se evalúa la subconsulta. |
| Ocupación previa y polling consumen tiempo antes del selector | Medido directamente en la ejecución nueva. La partición exacta del evento histórico no se conserva. |
| Una espera prolongada de lock del planner explica el histórico | No determinable históricamente. En el diagnóstico los dos waits muestreados pertenecen al proceso generador, no a los planners. |
| Estado físico/estadístico modifica el coste | Medido en buffers y planes; no se demuestra que explique el exceso histórico. Una pareja G tiene además autoanálisis, que impide atribuir su tiempo solo a ubicación. |
| El entorno/jitter domina el exceso | No confirmado: el resultado varía, pero no se separó el efecto del observador, PostgreSQL, fase de polling y planificación del sistema operativo. |

Que el pre-select sea la mayor parte de eligible→claim **no prueba cuál de sus componentes causó los 15.949 ms de exceso**. Un SELECT de 80.767 ms también supera esa diferencia; eliminarlo hipotéticamente produciría 9.935182 s, pero ese cálculo no demuestra que exista una transformación válida capaz de ahorrar el tiempo necesario ni preserva por sí mismo el orden temporal entre workers.

## 3. Metodología D/I/J y límites del observador

- PostgreSQL 16.15 y Python 3.13.2, dependencias del entorno aislado, `fsync=on`, `synchronous_commit=on`, índices originales. Instancia propia en puerto 35447 y bases con prefijo `test_e4_dhij2_`.
- No se ejecutaron VACUUM/ANALYZE manuales, no se añadieron índices y no se alteraron consultas, leases, debounce, rates, presupuestos, workers, polling, timeouts, umbrales, assertions ni corpus aceptados. Autovacuum/autoanalyze permanecieron activos con valores normales; sus efectos quedaron registrados.
- A/B/C/G: 16 puntos, 20 ejecuciones completas del selector por punto, una consulta por ejecución. Son mediciones de componente, no una muestra formal reducida. Bases clonadas, tres organizaciones, 53 TurnWork: 50 PENDING no elegibles, tres COMPLETED, cero due y cero PROCESSING. En esta fixture los tres COMPLETED pertenecen a la organización ruidosa; las otras dos no tienen historial de claim. Se midió ese estado real, aunque un comentario antiguo del builder sugería otra distribución.
- A/B/C usan un reloj sintético fijo para elegibilidad y datos artificiales. `created_at` conserva el comportamiento auto_now de la creación. Estas cohortes aíslan coste SQL; no reproducen persisted→claim ni todo el historial READY/safety/fencing del PROFILE. La matriz no contiene contención entre dos planners.
- I usa la orquestación diagnóstica existente, sin overrides E4: 30 s warmup, 300 s de observación y 20 s de drenaje; tres organizaciones, healthy cada 10 s y noisy cada 1 s, dos planners secuenciales `batch=1` y un sender, polling externo de 1 s, LLM .5 s por llamada, READ .1 s y Meta .2 s. Se delegó en el worker congelado con wrappers externos; no se editaron archivos de backend. El harness formal no se ejecutó.
- Los wrappers registran inicio/fin de SELECT, claim, consultas del claim, turno, sleep y commit. `time.time_ns()` sirve para unir fases con timestamps DB y `perf_counter_ns()` para duraciones. Se conserva la resolución declarada por Python: unidad ns no significa exactitud física de un nanosegundo. La mayor diferencia entre duración wall y monotónica del SELECT fue 0.2441 ms.
- Se obtuvo el PID del backend desde la conexión activa, sin añadir consultas por poll. SQL y parámetros completos se guardaron solo para selectors; las consultas de claim conservan placeholders y duraciones, sin valores clínicos. No se persistieron prompts, respuestas LLM, teléfonos ni nombres.
- `auto_explain` capturó ANALYZE, buffers, loops y filas durante cada SELECT, no mediante un replay posterior. También se guardó su SQL real desde PostgreSQL. Hay 702 planes y 702 registros de sentencia: 320 de matriz y 382 temporales; cero errores de parseo. La unión cliente→servidor verifica backend, ordinal, cardinalidad de registros, igualdad del SQL de sentencia y plan, y timestamp dentro del intervalo de ejecución cliente con la tolerancia de precisión del log.
- La instrumentación tiene coste: `auto_explain.log_analyze` con timing mide nodos de **todas** las sentencias y puede alterar su rendimiento; serialización/logging, wrappers y monitor también consumen tiempo. No se presume coste cero ni se resta un valor inventado. [Documentación PostgreSQL 16](https://www.postgresql.org/docs/16/auto-explain.html).
- El monitor externo consultó conexiones/waits y locks, además de snapshots cada 40 sondeos. Los intervalos reales entre sondeos tuvieron mediana 0.501951 s y máximo 1.091310 s; no se presentan como muestreo exacto de 250 ms ni como captura continua de locks. Los snapshots no son atómicos con el selector.

Fuentes reproducibles fuera del runtime: [observador](e4-causal-diagnosis-2026-10-03/diagnostic-observer-source.txt) y [análisis](e4-causal-diagnosis-2026-10-03/analysis-source.txt). No constituyen una implementación productiva.

## 4. H — qué puede reconstruirse del histórico

La evidencia fijada en HEAD permite recuperar PIDs, Message/TurnWork, timestamps DB y duración SQL. El observador histórico descartó SQL y parámetros; no guardó auto_explain por evento, todas las consultas del claim, pg_stats, páginas, visibilidad ni waits/locks. La base histórica fue eliminada y su servidor cerrado según `cleanup.json`.

| Rango | TurnWork | Python PID / backend | persisted→eligible s | eligible→claim s | persisted→claim s | Último SELECT ms | Pre-SELECT estimado s | Log SELECT→claimed_at s |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 56 | 153 | 27968 / 34424 | 7.946727 | 1.510543 | 9.457270 | 188.663 | 1.285737 | .036143 |
| 57 | 143 | 12792 / 34276 | 7.939089 | 1.790376 | 9.729465 | 184.245 | 1.579443 | .026688 |
| 58 | **86** | **27968 / 34424** | **7.926828** | **2.089121** | **10.015949** | **80.767** | **1.974774** | **.033580** |
| 59 | 115 | 12792 / 34276 | 7.931663 | 2.313048 | 10.244711 | 113.688 | 2.164443 | .034917 |
| 60 | 66 | 12792 / 34276 | 7.889717 | 2.495969 | 10.385686 | 439.520 | 1.883755 | .172694 |

Timeline de **Message 275 / Conversation 14 / organización 2 / TurnWork 86**, UTC:

```text
07:27:05.415631  persisted                 [DB, conservado]
07:27:13.342459  eligible                  [DB, conservado]
07:27:15.317233  inicio SELECT estimado    [log de fin menos duración]
07:27:15.398     emisión log SELECT       [PostgreSQL, milisegundos]
07:27:15.431580  claimed_at               [DB, antes de CAS/commit]
```

`1.974774 + .080767 + .033580 = 2.089121 s` es una descomposición **estimada** alrededor de la sentencia asociada, no una traza histórica con resolución de microsegundos. PostgreSQL `%m` marca la emisión del log con precisión de milisegundos; el coste de emisión y error entre relojes no quedó acotado. Los logs Python tienen segundos y hora local etiquetada como Z; el desplazamiento de seis horas se infiere al unirlos con DB. [Formato de logs PostgreSQL](https://www.postgresql.org/docs/16/runtime-config-logging.html).

Para 86, 115 y 66 hay un selector en el backend que reclama después de elegibilidad y antes de claimed_at. Eso no representa el query count total del claim. En el entorno de 86, planner-1 terminó un turno ruidoso 83 en el segundo 14 y volvió al worker en el segundo 15; planner-2 trabajaba en 84. La ocupación y polling son compatibles con esa secuencia, pero sus límites de un segundo impiden asignar exactamente el intervalo previo.

El plan de cierre histórico tuvo ejecución 127.583 ms y planificación 8.601 ms. **No es el plan de 86, 66 ni 115.** Recibos: [reconstrucción histórica](e4-causal-diagnosis-2026-10-03/historical-reconstruction.json) y [EXPLAIN de cierre, etiquetado](e4-causal-diagnosis-2026-10-03/historical-closing-explain.json).

## 5. I — timeline medido en la ejecución nueva

Se conservaron 396 inbounds incluyendo warmup y 170 TurnWork. La ventana canónica contiene 360 inbounds, de los cuales 60 saludables: 40 ordinarios con traza de planner y 20 safety inline. Cero faltantes saludables. Safety permanece en el denominador; su ruta inline no ejecuta el selector del planner y no tiene una traza de commit instrumentada en el generador.

El rango 58 diagnóstico corresponde a **Message 317 / TurnWork 101**, no a TurnWork 86. Planner-2: Python PID 72488, backend 60072.

| Fase | UTC | Intervalo |
| --- | --- | ---: |
| persisted | 15:57:36.256405 | |
| eligible | 15:57:44.201955 | persisted→eligible **7.945550 s** |
| termina turno previo 99 | 15:57:44.505531 | ocupación solapada **.303576 s** |
| empieza polling sleep | 15:57:44.505710 | transición .000179 s |
| termina polling sleep | 15:57:45.505952 | polling **1.000242 s**, solicitado 1 s |
| inicio selector | 15:57:45.548525 | preparación posterior al sleep .042573 s |
| fin selector | 15:57:45.628610 | SELECT cliente **.080085 s** |
| inicio claim_turn | 15:57:45.629016 | orden real: SELECT antes de claim_turn |
| claimed_at / reloj DB | 15:57:45.651068 | fin SELECT→claimed_at **.022458 s** |
| fin commit | 15:57:45.711534 | fin SELECT→commit **.082924 s** |

Para esta muestra:

```text
X pre-SELECT       = 1.346570 s
  turno previo       .303576 s
  polling           1.000242 s
  no clasificado     .042752 s
Y SELECT cliente   =  .080085 s
Z hasta claimed_at =  .022458 s
eligible→claim     = 1.449113 s
persisted→claim    = 9.394663 s
```

La porción no clasificada incluye código Python, instrumentación, transiciones y scheduling; no se renombra como jitter de OS. El exceso de sleep respecto de 1 s tampoco identifica por sí solo una causa de planificación. `claimed_at` es `statement_timestamp()` al entrar en `_claim_turn_locked`, **anterior** a membership/CAS/commit. B9C adquiere autoridad al commit; ambos límites se conservan en la evidencia.

El timestamp de fin de commit instrumentado marca el retorno de `Atomic.__exit__`: incluye el retorno del commit y sus callbacks, y es un límite superior observable al commit efectivo. No se presenta como timestamp de finalización de COMMIT obtenido dentro del servidor.

| Rango diagnóstico | TurnWork | persisted→claim s | Pre-SELECT s | SELECT cliente ms | Post-SELECT→claimed_at ms | Post-SELECT→commit ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 56 | 162 | 9.317588 | 1.209158 | 151.811 | 18.567 | 93.378 |
| 57 | 129 | 9.326610 | 1.269642 | 116.851 | 23.244 | 104.002 |
| 58 | 101 | 9.394663 | 1.346570 | 80.085 | 22.458 | 82.924 |
| 59 | 38 | 9.466277 | 1.484096 | 27.573 | 26.161 | 117.657 |
| 60 | 90 | 9.539737 | 1.511287 | 57.240 | 24.413 | 108.569 |

En 162 y 129, el pre-select incluye otro SELECT anterior y un poll completo; «tiempo anterior al SELECT final» tampoco equivale siempre a «tiempo sin SQL».

Los 40 claims ordinarios instrumentados ejecutaron **31 consultas dentro del claim y una del selector previo**, sin contar COMMIT como consulta del execute wrapper. El cierre de un claim también está medido. Esto no es un antes/después del runtime ni se compara con el count 33 de una fixture anterior distinta.

Los 382 SELECT temporales tuvieron cliente mediana 67.475 ms, p95 237.739 ms y máximo 496.663 ms. El polling medido tuvo mediana 1.000366 s, p95 1.001216 s y máximo 1.019999 s. Estas estadísticas incluyen warmup/drenaje y no reemplazan el gate de 60 muestras.

Recibos con **todos** los IDs, trazas, parámetros, consultas y fases: [temporal-analysis-all-messages.json.gz](e4-causal-diagnosis-2026-10-03/temporal-analysis-all-messages.json.gz), los dos `temporal-planner-*.json.gz`, `temporal-sender.json.gz` y `temporal-diagnostic.json` en el mismo directorio.

## 6. D/J — comparación controlada del selector

Todas las cohortes devolvieron el mismo oracle observado `[1, 2, 3]`, en ese orden, en sus 20 repeticiones. Es un oracle de esos estados concretos, no prueba universal de equivalencia de otra consulta.

Tiempos en ms. «Executor real» es la mediana de auto_explain de los 20 SELECT realmente ejecutados; «EXPLAIN cierre» es **otra ejecución**, con su propio tiempo de planificación. Loops/hits de la tabla se refieren al nodo Message repetido de ese EXPLAIN de cierre, sin sumar descendientes.

| Cohorte | C | M | Ruido pendiente adicional | Cliente mediana | Executor real mediana | EXPLAIN cierre ejecución | Loops / hits | pg_stats antes→después |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| A354 | 354 | 354 | 0 | 39.893 | 9.884 | 13.051 | 352 / 1,056 | 0→0 |
| A708 | 354 | 708 | 0 | 35.289 | 9.332 | 8.367 | 352 / 1,056 | 0→0 |
| A3540 | 354 | 3,540 | 0 | 32.963 | 7.662 | 16.126 | 352 / 1,408 | 0→0 |
| A10000 | 354 | 10,000 | 0 | 46.296 | 13.806 | 13.880 | 352 / 1,408 | 0→0 |
| B100 | 100 | 3,540 | 0 | 29.017 | 2.393 | 3.785 | 98 / 392 | 0→0 |
| B354 | 354 | 3,540 | 0 | 44.272 | 11.024 | 16.069 | 352 / 1,408 | 0→0 |
| B708 | 708 | 3,540 | 0 | 41.473 | 16.144 | 27.195 | 706 / 2,824 | 0→0 |
| B1416 | 1,416 | 3,540 | 0 | 63.603 | 39.653 | 32.069 | 1,414 / 5,656 | 0→0 |
| C0 | 354 | 3,540 | 0 | 43.427 | 11.793 | 25.271 | 352 / 1,408 | 0→0 |
| C30 | 354 | 3,540 | 30 | 39.436 | 13.312 | 24.402 | 352 / 1,408 | 0→0 |
| C100 | 354 | 3,540 | 100 | 63.081 | 31.950 | 37.131 | 352 / 2,112 | 0→0 |
| C200 | 354 | 3,540 | 200 | 67.706 | 40.767 | 55.363 | 352 / 2,816 | 0→0 |
| G cluster 1 | 354 | 10,000 | 200 | 59.081 | 32.472 | 54.584 | 352 / 2,464 | 0→0 |
| G spread 1 | 354 | 10,000 | 200 | 63.210 | 36.991 | 37.419 | 352 / 11,968 | 0→0 |
| G cluster 2 | 354 | 10,000 | 200 | 59.699 | 32.465 | 40.944 | 352 / 2,464 | 5→22 |
| G spread 2 | 354 | 10,000 | 200 | 65.035 | 36.547 | 50.633 | 352 / 11,968 | 0→0 |

«Ruido» en C es cambio de status de filas existentes a pendientes elegibles, no cambio de rate: los totales M/C/org/TurnWork permanecen fijos. Hay tres pendientes iniciales elegibles y un cuarto upcoming; C200 tiene 204 pendientes en total. Las dos organizaciones sin historia permiten cortocircuitar parte del forecast: por eso B tiene `C−2` loops. No se trasladan esos resultados a la distribución histórica de claims de las tres organizaciones.

### Estado físico y estadístico

Los snapshots contienen pg_stats de campos relevantes, null_frac/n_distinct/correlation/MCV/histogramas, cardinalidades exactas, pg_class, bytes de heap/índices, CTID por status, visibilidad y estadísticas de vacuum/analyze. `relpages=0` y `reltuples=-1` en una tabla sin analizar no significan que no tenga páginas físicas: se conservan también `pg_relation_size` y bloques de CTID.

A mantiene cuatro pendientes sobre dos bloques. Al pasar M=354→10,000, el heap Message crece de nueve a 206 páginas, pero el nodo repetido usa 1,056→1,408 hits y los tiempos no crecen monotónicamente. B, con M fijo, aumenta loops y el coste del executor: hay trabajo SQL que escala con conversaciones en estos estados. C aumenta pendientes elegibles y bloques que debe visitar la consulta; su executor también crece. Ningún punto mide directamente el p95 integral ni reproduce el estado histórico exacto.

G preserva **todas las columnas, IDs, relaciones y timestamps** de las tres tablas, verificadas con SHA-256 idéntico antes de medir cada restauración; constraints y triggers permanecieron activos. Las 204 filas pendientes ocupan cinco bloques en cluster y 32 en spread. En la pareja 1, los hits cambian 2,464→11,968 (4.86×), pero la mediana del executor cambia 32.472→36.991 ms (1.14×) y el EXPLAIN de cierre invierte el orden de tiempos. Se confirma que distribución física afecta buffers; no una relación proporcional buffers→latencia ni el mecanismo del FAIL.

En G cluster 2, autoanalyze introdujo estadísticas: el cierre usa Bitmap Heap Scan; G spread 2 sigue con Index Scan y sin pg_stats. **Esta pareja no es una comparación de tiempo con única variable física.** No se desactivó autoanalyze ni se forzó ANALYZE para obtener otro resultado.

Los planes incluyen estimaciones y filas reales. Sin pg_stats, algunos nodos estiman una fila y devuelven 203 en la lectura de incoming de C200; después de autoanalyze G cluster 2 estima 203. El nodo forecast puede devolver cero por loop aunque visite muchos buffers. Los datos completos están en cada `A-*.json.gz`, `B-*.json.gz`, `C-*.json.gz`, `G-*.json.gz`, [matrix-summary.json](e4-causal-diagnosis-2026-10-03/matrix-summary.json) y `matrix-analysis.json.gz`.

### PostgreSQL durante I

El estado evolucionó naturalmente con ingress, turns, outbound y autovacuum/autoanalyze. Los snapshots cercanos al nuevo p95 registran 212/235 conversaciones, 325/362 mensajes y 98/110 TurnWork; **no son la cardinalidad exacta del instante del SELECT**. En ambos ya constan autoanalyze/autovacuum y visibilidad de Message de dos páginas, con un frozen. El plan del evento tiene 216 loops de forecast. Las estadísticas de catálogo pueden estar desactualizadas respecto de la visibility map; ambas se conservan separadas.

Hubo 692 sondeos. Los waits observados fueron ClientRead (2,509 observaciones), WALWrite (6), transactionid (2) y activo sin wait identificado (187). Las dos muestras de lock fueron del backend generador 73428, a 15:55:16 y 15:59:46 UTC, mientras planner-2 estaba en transacción. No se observó un lock wait del planner que fijó el p95; el muestreo no descarta esperas más cortas entre sondeos. No hay evidencia histórica equivalente que permita comparar causalmente las dos ejecuciones.

Fuentes: `temporal-postgresql.json.gz` y [snapshots vecinos del evento](e4-causal-diagnosis-2026-10-03/diagnostic-p95-nearby-snapshots.json).

## 7. Selector SQL y la hipótesis del Bitmap Heap Scan

La consulta es `_pending_conversation_candidates` en `backend/apps/agent/worker.py`. La subconsulta correlacionada `less_served_soon` observa Message upcoming de otras organizaciones, excludes safety y organizaciones ocupadas, y compara su último claim con el de la conversación candidata. Se evalúa dentro del filtro previo a Window/orden/LIMIT; sus loops pueden crecer con conversaciones evaluadas, aunque el selector solo devuelva hasta tres IDs.

El SQL **real** del nuevo p95 está en [diagnostic-p95-selector.sql](e4-causal-diagnosis-2026-10-03/diagnostic-p95-selector.sql), SHA-256 `4d8847d967cd71ca8018ce29ec56da632b8d026ab49801784d3024aeb200047c`. Su fragmento de forecast usa:

```sql
FROM channels_message V0
WHERE V0.available_at > STATEMENT_TIMESTAMP()
  AND V0.available_at <= STATEMENT_TIMESTAMP() + '0:00:01'::interval
  AND V0.direction = 'in' AND V0.status = 'pending'
  AND V0.turn_work_id IS NULL
```

Ese fragmento es ilustrativo: el archivo SQL conserva además is_active, exclusiones por tenant/safety, ocupación, recencia, due, Window y orden completos. No se ejecutó una versión recortada como alternativa.

| Evidencia | Tiempo executor total | Nodo Message forecast | Loops | Hits | Reads | Tiempo nodo × loops |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| Cierre histórico, **no evento 86** | 127.583 ms | Bitmap Heap Scan | 354 | 9,912 | 0 | .193 × 354 ≈ 68.322 ms |
| Evento p95 diagnóstico 101 | 69.037 ms | Bitmap Heap Scan `v0` | 216 | 4,296 | 0 | .185 × 216 ≈ 39.960 ms |

En el evento nuevo, PostgreSQL registró total de sentencia 78.666 ms y cliente 80.085 ms. La diferencia total−executor, 9.629 ms, incluye planificación y otros costes de sentencia/observador; **no es una medición exclusiva de planificación**. Los EXPLAIN de cierre sí registran Planning Time por separado, pero son ejecuciones posteriores. La planificación exacta de cada evento no quedó separada por auto_explain.

El tiempo del nodo incluye hijos, y tiempos/filas son promedios por loop. Los hits son accesos repetidos a buffers compartidos, no 9,912 páginas únicas; no se suman los hits de padres e hijos. [Interpretación de EXPLAIN](https://www.postgresql.org/docs/16/using-explain.html).

El Bitmap aparece en el evento nuevo y consume una parte medible del executor. No sabemos si apareció en 86. A/B/C/G demuestran que el patrón de trabajo y buffers depende de conversaciones, pendientes, ubicación y estadísticas; **no demuestran que ese nodo causó el cruce de 10 s**.

Plan contemporáneo completo: [diagnostic-p95-selector-plan.json](e4-causal-diagnosis-2026-10-03/diagnostic-p95-selector-plan.json). Todos los planes y SQL reales: `server-selectors.json.gz`; los EXPLAIN explícitos posteriores están etiquetados `separate_execution` en cada cohorte.

## 8. D — alternativa y equivalencia

La alternativa preexistente `backend/apps/agent/tests/e4_claim_candidate.py:candidates` omite la rama canónica `pk__in=pending_safety` que permite bypass del forecast. Un candidato safety con historia de claim y `less_served_soon=True` puede ser incluido por el canónico y excluido por esa alternativa. Por inspección de su predicado, no es equivalente para todos los estados permitidos.

No se hizo comparación de velocidad con esa consulta ni se creó otra alternativa. `[1,2,3]` en una fixture sin ese caso no probaría igualdad de exclusiones, tenant isolation, estado, lease, elegibilidad, fencing y orden. Tampoco el selector sustituye las revalidaciones B3/B9C. No existe un cambio experimental de query validado que justifique un «antes/después» ni una propuesta de corrección.

## 9. Variables descartadas y no determinables

Descartado con el alcance indicado:

- Red externa real: proveedores del diagnóstico e histórico son fakes con latencias declaradas. Esto no elimina los costes HTTP internos/DB/Python de los turnos.
- Crecimiento monotónico causado solo por cantidad total de mensajes: no se observó en A manteniendo pendientes y conversaciones.
- Equivalencia de la alternativa existente: el caso safety invalida su uso como corrección general.
- Identidad entre EXPLAIN de cierre y SELECT histórico del p95: no existe evidencia para esa identidad.
- Cambio productivo como explicación de este diagnóstico: backend sin modificaciones; índices/consultas/topología y constantes aceptados conservados.

No determinable en esta fase:

- Plan, buffers, loops, SQL/parametrización exactos y estadísticas físicas **del evento histórico 86/66/115**; los artefactos necesarios no sobrevivieron.
- Descomposición histórica subsegundo de ocupación, poll, selección anterior, preparación, commit y lock wait.
- Contrafactual histórico con una consulta semánticamente equivalente más barata y la misma intercalación entre los dos planners.
- Contribución individual de autoanalyze, caché, IO, observador y planificación del OS a la diferencia entre histórico y ejecución nueva.
- Tiempo de planificación exclusivo por evento, overhead absoluto del observador y esperas DB entre sondeos.
- Commit y tramo interno de safety inline en el generador; sus 20 muestras permanecen incluidas.

Las variables históricas críticas son irrecuperables a partir de los recibos disponibles. No se propone recuperar precisión ejecutando otra carga y presentándola como historia, ni se prolonga la línea con nuevas hipótesis y benchmarks.

## 10. Impacto sobre el FAIL y corrección mínima

Existe evidencia de que **una parte importante del tiempo ocurre antes del SELECT final**. En 86 se estiman 1.974774 s de ese tramo, aproximadamente 94.5% de eligible→claim, frente a 80.767 ms del SELECT asociado. En el nuevo p95 se midieron turno anterior y polling directamente. Son hechos distintos: la primera partición no identifica con exactitud la causa histórica; la segunda explica una muestra diagnóstica que no cruzó 10 s.

El p95 diagnóstico 9.394663 s está 0.621286 s por debajo del histórico, con 60 muestras y sin faltantes. La fase de carga, estado PostgreSQL, intercalación de procesos e instrumentación no son idénticos; esa diferencia no demuestra entorno dominante, PASS ni una mejora productiva.

**Causa del exceso histórico: no confirmada. Corrección mínima localizada justificable: ninguna identificada.** No se atribuye automáticamente el FAIL al selector, al Bitmap, al polling ni a la carga artificial. No se implementa tuning, no se recomienda una optimización concreta y se mantiene `ROOT_CAUSE_NOT_CONFIRMED → STOP`.

## 11. Cierre y preservación

Se verificaron byte a byte contra HEAD los 50 archivos del PROFILE histórico. Se verificaron HEAD, estado y hashes de las seis entradas del checkout principal. [Recibo de inmutabilidad](e4-causal-diagnosis-2026-10-03/immutability-before-documentary-commit.json). El commit de esta fase contiene solo documentos y evidencia nueva; no contiene backend ni modifica el PROFILE histórico.

PostgreSQL aislado fue detenido, puerto 35447 cerrado, bases propias eliminadas, cero conexiones cliente restantes, locks pendientes y transacciones preparadas al cierre. El directorio de datos se conserva detenido. [Recibo de limpieza](e4-causal-diagnosis-2026-10-03/environment-cleanup.json). Python/harness y operaciones Git tuvieron acceso; no se manipularon permisos ni index.lock.

Producción conserva el alcance cerrado: **B0 cerrado; `AGENT_B7B_CONSENT_ENABLED=False`; `AGENT_OPERATION_EXECUTION_ENABLED={}`; grants productivos vacíos; `PENDING_ACTIVATION_REQUIREMENTS`; cero clínicas activadas por esta tarea; sin deploy.** Se comprobó la identidad del código y los gates documentados; no se inspeccionó ni modificó el entorno remoto productivo.

Resultados estructurados y referencia a las mediciones completas: [e4-causal-diagnosis-results.json](e4-causal-diagnosis-results.json).
