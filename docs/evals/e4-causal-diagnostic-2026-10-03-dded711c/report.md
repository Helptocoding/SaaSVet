# DIAGNOSTIC_ONLY — CAUSE_CONFIRMED

El exceso observado en esta ejecución nueva está localizado antes de
`selection_start`, en la cola posterior a elegibilidad y anterior al poll que
admite cada claim. Los 122 inbounds reclamados por encima de 10 s ya habían
superado 10 s antes de que comenzara su selección. El SQL de esa selección,
el claim y su commit consumen milisegundos. La confirmación corresponde a esa
fase; no demuestra una causa histórica ni una corrección única del scheduler.

Resultado estructurado: [causal-report.json](causal-report.json).
Run ID nuevo: `causal-dded711c1ce04cfd8f01af5dc7d62da2`.
La carga empezó el **2026-10-04 05:58:27.769978 UTC**. La carpeta conserva la
fecha de preparación del 03-10. El formatter de los logs operativos no es una
fuente temporal del análisis.

**Baseline y alcance.** Branch `codex/e4-capacity-scheduling`, runtime autorizado
`66702168439b9841a2c988238638a42e6aaee43d`, instrumentado por su hijo directo
`825db75df68bf076929fa787e77beefe96803350`, HEAD exclusivo de esta ejecución.
No hay commits ni cambios de runtime durante este encargo. El FAIL del runtime
histórico `83ee3b24c84b170e22e401cb09a34da5320ae0a3`, su PROFILE y la evaluación
posterior del 02-10 permanecen intactos. No se invocó `b9e_profile` ni
`e4_profile`, no se calculó aceptación, no se declaró PROFILE PASS y B9E no se
reclasificó. El umbral sigue en 10 s. Ninguna medición aquí explica causalmente
el TurnWork 86 histórico.

Se mantuvo la carga documentada: dos planners, un sender, batch 1, pausa entre
polls de 1 s, dos organizaciones a un inbound cada 10 s y una ruidosa a uno por
segundo; 30 s de calentamiento, 300 s de carga y 20 s de drenaje. Provider
simulado de dos llamadas LLM de 500 ms, HTTP de dominio de 100 ms y Meta de
200 ms. Captura desde antes del primer webhook, con ambos planners y sender.
Observador readonly autocommit en otro proceso, PID OS 21236, muestreo
solicitado de 20 ms. PostgreSQL 16.15 aislado, puerto 35449, `fsync=on` y
`synchronous_commit=on`. Véanse [protocolo](PROTOCOL.md),
[carga](load-definition.json), [entorno](environment.json) e
[inventario observado de procesos](process-inventory-observed.json).

| Organización | Ingestados | Reclamados | Safety | Reclamados >10 s | Pendientes sin claimed_at |
|---|---:|---:|---:|---:|---:|
| Sana 1 | 33 | 33 | 11 | 0 | 0 |
| Sana 2 | 33 | 33 | 11 | 0 | 0 |
| Ruidosa 3 | 330 | 123 | 0 | 122 | 207 |

Se registraron 189 claims vinculados y confirmados por commit y 20 intentos
que devolvieron `miss`. Todos los vinculados tienen attempts=1. Los 207
pendientes se conservan como observaciones censuradas: no se fabrican
timestamps finales ni se les asigna una duración hasta claim. Ninguno de los
66 inbounds sanos reclamados superó 10 s; su máximo fue 9,604493 s. Esto no es
un gate de aceptación.

**Casos individuales.** Los 122 casos completos, con IDs, relojes DB, límites
temporales, cada query y hueco, están en [over-10-attempts.csv](over-10-attempts.csv)
y [over-10-attempts.json](over-10-attempts.json). Los 189 claims y 20 misses
están en [per-attempt.json](per-attempt.json); el CSV de los vinculados es
[per-attempt.csv](per-attempt.csv).

| Work / inbound / worker de esta ejecución | persisted→claimed_at, s | persisted→eligible, s | eligible→poll, s, límites | eligible→selection_start, s, límites | Selección, ms | SELECT único, ms | selection_end→claim_start, ms | Claim completo, ms | SQL del claim, ms | COMMIT, ms |
|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| 4 / 6 / planner-1; primer exceso | 10,845758 | 7,958988 | [2,8276171; 2,8281568] | [2,8277182; 2,8282579] | 29,1687 | 6,3579 | 0,0996 | 108,6388 | 50,2307 | 6,8146 |
| 100 / 107 / planner-1 | 119,673126 | 7,945264 | [111,5494700; 111,5501817] | [111,5495851; 111,5502968] | 145,1845 | 119,3806 | 0,1503 | 110,5680 | 43,4034 | 6,4312 |
| 189 / 212 / planner-2; máximo | 226,515086 | 7,964025 | [218,4070058; 218,4083469] | [218,4071979; 218,4085390] | 129,1258 | 99,1063 | 0,0903 | 61,6451 | 21,0169 | 1,1195 |
| 149 / 449 / planner-2; máximo sano | 9,604493 | 7,964361 | [1,5452133; 1,5456516] | [1,5456021; 1,5460404] | 80,5726 | 64,2438 | 0,0796 | 63,3267 | 19,8929 | 5,2589 |

Para Work 189, la descomposición que sí cierra `persisted→claimed_at` es:

- `persisted→eligible`: 7,964025 s, diferencia exacta entre campos DB.
- `eligible→selection_start`: [218,4071979; 218,4085390] s.
- Selección completa: 129,1258 ms; contiene un SELECT de 99,1063 ms,
  29,5986 ms antes de execute y 0,4209 ms después de execute.
- `selection_end→claim_start`: 0,0903 ms.
- `claim_start→claimed_at`: [13,3059; 14,6470] ms.

Los extremos de los límites DB↔monotónico están anticorrelacionados: el límite
inferior antes de selección se suma con el superior después de selección, y
viceversa. Ambos cierran 226,515086 s. No se suman extremos independientes.
El claim completo de 61,6451 ms contiene actividad posterior a `claimed_at`;
por tanto, no debe añadirse entero al intervalo solicitado.

**Resumen por fase de los 122 casos >10 s.** Los mínimos y máximos de distintas
filas no describen necesariamente un mismo intento. [per-phase.json](per-phase.json)
conserva por separado claims ordinarios, safety, todos los vinculados y los
casos >10 s; los datos individuales permiten reconstruir cada uno.

| Fase | Rango observado |
|---|---|
| persisted→eligible | 7,913461–7,966761 s |
| eligible→poll que admite | límites exteriores 2,8276171–218,4083469 s |
| eligible→selection_start | límites exteriores 2,8277182–218,4085390 s |
| persisted→selection_start | límite inferior mínimo **10,7867062 s** |
| Selección completa | 23,6392–195,6108 ms |
| Query del selector | una por selección; 6,3579–157,4671 ms |
| selection_end→claim_start | 0,0775–0,2945 ms |
| Claim completo | 51,1488–151,5177 ms |
| SQL dentro del claim | 17,4396–63,6867 ms |
| COMMIT, execute hasta ACK | 0,7551–30,4316 ms |
| selection_start→claimed_at | límites exteriores 34,2803–224,8114 ms |

La demora anterior al SELECT está observada. Los spans previos del worker que
admite Work 189 cubren aproximadamente **78,975–78,977 s procesando otros
turnos** y **122,408 s entre polls**, dentro de sus 218,407–218,409 s desde
elegibilidad. Work 100 registra unos 43,408–43,409 s procesando turnos y
62,213 s entre polls. El primer exceso registra 2,783 s entre polls en el
worker que lo admite. Estos intervalos usan spans y relojes precisos; no se
reparten por diferencias de logs. El tiempo restante incluye actividad de
otros polls/selecciones/claims y huecos del worker. No se etiqueta todo el
tiempo entre polls como sleep exacto, ni se afirma indisponibilidad global
simultánea de los dos planners. El backlog de 207 confirma acumulación en
esta carga, sin identificar por sí solo una modificación correcta del selector.

**Queries y commits.** Cada una de las 167 selecciones que condujeron a un
claim ordinario ejecutó realmente **una query**; los 20 misses también
conservaron su selección de una query. Safety usa la ruta de ingreso con
claim bajo locks: **cero queries del selector y fases poll/selección N/A**.
Los ordinarios vinculados ejecutaron 31 queries dentro del scope del claim;
safety, 27. Esto incluye las sentencias transaccionales de ese scope, no el
COMMIT del driver ni toda la ejecución posterior del turno.

No hay hueco *entre* queries del selector porque hay una sola. Las arrays
`claim_query_timings_ms` y `claim_inter_query_gaps_ms` conservan cada execute
y cada hueco dentro del claim. [query-timings.jsonl](query-timings.jsonl)
contiene las **75.600 ejecuciones SQL Django** de las cuatro capturas, cada
una identificada por session_id/query_id, tablas, operación, flags de lock,
scope, inicio/fin/error y waits correlacionados. Este total incluye ingress,
turnos y sender; no es el número de queries del selector. Los COMMIT reales
se observan por separado. Duración SQL significa elapsed del cliente,
incluyendo servidor, driver, red y posibles waits; no equivale a CPU SQL pura.

En los 167 claims ordinarios el ACK precede a `claim_result`: el intervalo
firmado `commit_ack − claim_result` es −2,6735 a −0,3896 ms. No existe una
espera posterior al resultado por un commit que ya ocurrió. En Work 189,
el resultado llega 0,6266 ms después del ACK; `claimed_at→commit_ack` es
[46,2918; 47,6329] ms y el execute del COMMIT consume 1,1195 ms.

En safety, `claim_result` precede al commit exterior de ingreso: 186,0156 a
434,8407 ms hasta el ACK; el execute del COMMIT consume 3,2010 a 87,3546 ms.
`claimed_at→commit_ack` tiene límites exteriores 234,5793–503,1639 ms.
`persisted→claimed_at` de safety fue 0,069431–0,133064 s. Esa separación
evita confundir creación del timestamp, retorno de la primitiva y persistencia
confirmada de la transacción.

**Waits observados.** [waits-summary.json](waits-summary.json) conserva los
bloqueadores y la asociación al execute. Hay 47.162 muestras: 4.766 asociadas
de forma única, 158 ambiguas y 42.238 sin query asociada. Se observaron 16
muestras `Lock:transactionid` en cinco queries:

| Worker / query_id | Tabla / contexto | Query completa, ms | Muestras de lock | PID bloqueador / rol |
|---|---|---:|---:|---|
| ingress / 1749 | contactidentity, FOR UPDATE | 77,5338 | 3 | 23224 / planner-2 |
| ingress / 1801 | contactidentity, FOR UPDATE | 71,0230 | 3 | 26316 / planner-1 |
| ingress / 4197 | contactidentity, FOR UPDATE | 103,7480 | 4 | 26316 / planner-1 |
| planner-1 / 4586 | conversation, ejecución Work 59 | 72,3901 | 3 | 28340 / ingress |
| planner-1 / 10324 | conversation, ejecución Work 127 | 78,5588 | 3 | 28340 / ingress |

Estas queries están en ingreso o ejecución del turno, fuera del scope de
claim/selector. Ningún claim vinculado ni su selección tuvo una muestra de
lock asociada. También se observaron ClientRead, WALWrite y DataFileExtend.
El muestreo no demuestra ausencia absoluta de waits ni duración exacta del
lock: se conserva `exact_lock_wait_ms=null` y el límite conservador
[0; duración completa de query]. No se atribuye la duración de una query
entera a lock ni se interpolan muestras.

**Equivalencia, integridad y preservación.** Se ejecutaron los seis escenarios
controlados OFF/ON del mismo HEAD: new/retry/reclaim/busy/not-due, READY join
y reconexión, rollback exterior/savepoint, concurrencia real, wait controlado
y LLM bloqueado con progreso de otra organización. Cero failures, errors,
skips o xfail. Los recibos de concurrencia, locks, rollback y LLM bloqueado
son iguales OFF/ON; los tests verifican secuencia SQL y parámetros normalizados,
membership, attempts, leases, epoch/fencing, presupuesto B9B y resultado.
Véanse [resultados funcionales](functional-results.results.json) y los recibos
en `functional-artifacts`. Esta prueba compara estados/barreras controlados;
no afirma igualdad de calendario o ganador entre cargas concurrentes realizadas
en momentos distintos. El overhead temporal de observación está incluido en
las mediciones.

Las cuatro capturas suman **207.324 eventos**, tienen footer completo,
secuencia continua, cero failed_writes, spans/SQL emparejados y transacciones
cerradas. El observador terminó completo, sin líneas parciales; todos los
procesos terminaron con exit 0. [integrity.json](integrity.json) guarda los
hashes de journals; [protected-sources-before.json](protected-sources-before.json)
y [protected-sources-after.json](protected-sources-after.json) contienen hashes
raw y LF normalizado de **1.239 fuentes protegidas**, idénticas antes/después.
El HEAD y los cambios preexistentes del usuario se conservan. No hay SQL crudo,
parámetros, bodies, prompts ni contenido conversacional en los journals.

El borrador offline tenía una asociación incorrecta: `selection_id=null` y
`span_id=null` incluían SQL de ingreso sin scope como selección de safety.
Los journals originales están íntegros. `finalize.py` exige un ID no nulo y
un span de selección real, validado contra el journal; safety queda en cero
queries del selector. Sólo se corrigió la reconstrucción evaluativa. El módulo
del HEAD no se modificó. `causal-analysis.json`, `attempt-summary.*` y
`phase-summary.json` son borradores **no autoritativos** y no deben usarse para
interpretar safety. Las diferencias de campos DB se recalculan con microsegundos
enteros; las fases entre relojes mantienen brackets. No se inventan timestamps.

**Limpieza y STOP.** [cleanup.json](cleanup.json) confirma las tres bases
eliminadas, cluster detenido, puerto cerrado, cero clientes/locks pendientes/
prepared transactions y directorio de datos propio eliminado. Sólo se conservan
artefactos evaluativos nuevos en esta carpeta. El resultado es exclusivamente
`CAUSE_CONFIRMED` dentro de `DIAGNOSTIC_ONLY`.

La evidencia justifica atribuir el exceso actual a la fase previa a selección.
No permite escoger una corrección mínima de runtime que conserve todas las
decisiones y contratos: aún no distingue de forma única disponibilidad global,
política de servicio entre candidatos y carga admitida. Por el alcance de este
encargo no se propone ni implementa optimización, ni se cambia selector, índices,
query, polling, workers, leases, budgets o umbral. La ejecución se detiene aquí.
