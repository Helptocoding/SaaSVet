# E4 — diagnóstico y mejora acotada de eligible→claim · 2026-09-30

ROOT_CAUSE_CONFIRMED. Una sola mejora E4 implementada en el selector advisory.
Estado de rendimiento: DIAGNOSTIC_GATE_GREEN. Diagnóstico final base
9.742585 s y blocked 9.798881 s;
márgenes +0.257415 s y +0.201119 s.
Esto habilita considerar un candidato después de verificar regresiones;
no declara PASS integral de PROFILE-BETA-1. No se ejecutó su rerun
formal en este encargo. B9 sigue IN_PROGRESS; B9E y PROFILE histórico siguen FAIL.
STOP después de esta mejora; no segundo tuning, deploy ni activación.

Baseline exacto verificado antes de comenzar:
`f051c27002986193772ced0fb1e00e19822d26ef`. Cambios preexistentes en documentos de
deploy, skills-lock y dos documentos de auditoría se excluyen de ambos commits.
La raíz [e4-claim](evals/e4-claim/) conserva recibos, journals, SQL plans,
inventario por ID, fuentes y hashes. [summary.json](evals/e4-claim/summary.json)
consolida los números; las mediciones crudas permanecen separadas.

## Causa y autoridad

El generador persiste org 0 antes de org 1. Sus deadlines son ligeramente
anteriores. KEEP ordena por último claim durable de la organización, actividad e
ID: la org 0 recibe normalmente el primer planner disponible y vuelve a tener un
claim anterior al de org 1. Ambos planners sirven ambas organizaciones; no hay
afinidad fija por tenant. Cuando el otro planner ya inició noisy poco antes de
READY, su servicio real de aproximadamente dos segundos, seguido de la pausa
externa de aproximadamente un segundo y batch=1, deja a org 1 esperando su
siguiente oportunidad. La consulta ya puede haber observado org 1 junto con org
0: observar no equivale a disponer de otro planner libre.

El gate [root-cause-gate.json](evals/e4-claim/root-cause-gate.json) se escribió
antes del cambio runtime. Se consultó E4 canónico §7/E4, contratos e implementación
B3/B9B/B9C, worker/planner/command, metodología y runner v1, evidencia monotonic
y diagnóstico/capacidad anteriores. La coordinación y selección están en E4;
la autoridad sigue siendo el claim B3 con exclusión B9C en PostgreSQL. No se
cambió contrato, quiet window 8 s, hard cap 25 s, persistencia ni metodología.

## Método y límites de los timestamps

Cada diagnóstico relevante usa 30 s warmup, 300 s medición y 20 s drain; dos
procesos planner y uno sender, batch=1, poll/pausa=1 s, intervalos 10/10/1 s.
LLM fake 0.5 s por llamada, READ HTTP 0.1 s y Meta 0.2 s. La ruta READ ejecuta
las **dos llamadas reales**; no se reemplaza run_turn ni se simula un solo call.
PostgreSQL 16.15 local, fsync=on y synchronous_commit=on. Las regresiones corren
después de terminar las mediciones, en otras bases.

El runner original invoca `call_command(run_agent_worker, once=True, role=...,
batch=1, poll=1)` y después `time.sleep(1)` incondicional externo. Por eso
start→start incluye servicio más pausa; poll no aporta exactamente 1 s de
eligible→claim en cada muestra. Se conservan originales runner, v1 y metodología,
con hashes iguales al baseline en [validation.json](evals/e4-claim/validation.json).
El driver de este estudio reutiliza el harness diagnóstico, sin modificar el
runner formal ni hacer acceptance con ablations.

T0 es Message.created_at, timestamp durable de persistencia contractual, no una
medición independiente del retorno COMMIT del webhook. T1=max(T0, available_at),
NULL→T0; usar max evita deltas negativos cuando un inbound se une a READY previo.
T2 es el siguiente inicio global de planner relevante; se conserva también
winning_planner_start y si una selección ya estaba en curso al llegar T1.
T3 es la primera observación de esa conversación; T4 la selección del intento
ganador. Si el mensaje llegó después de una observación de su READY, se marca
joined_after_candidate_observation, sin inventar un nuevo evento por mensaje.
T6 mide retorno de Atomic.__enter__, inicio del contexto de transacción Django;
no es una captura wire de BEGIN PostgreSQL. T5 es la petición SQL del lock de
Organization y ocurre después de T6. T7 es TurnWork.claimed_at durable. T8 es el
retorno del claim después del bloque atomic, incluidos callbacks/logging: cota
superior del retorno commit, no latencia pura de COMMIT.

Cada analysis.json incluye las **60 timelines sanas**: 40 ordinarias con T0–T8 e
identidad de planner y 20 safety de recepción con T0/T1/T7. Para safety, los
campos de planner/selección T2–T4 no aplican y T5/T6/T8 están en null: el driver
no instrumenta los locks ni la transacción del proceso receptor. Es una
limitación explícita de cobertura de trazas, no timestamps estimados ni ausencia
de transacción safety. Los p95 son higher: índice ceil(.95×(n−1)). El gate global
incluye las 60 muestras contractuales; los desgloses ordinarios usan 20 por org.
No se suman percentiles de componentes para reconstruir el p95 global.

Un primer baseline-base terminó la carga pero falló al cerrar el collector:
QuerySet.explain produjo EXPLAIN anidado en la query Window de Django. No tiene
recibo ni resultado de gate. Se conservan logs/journals y attempts.json; se
corrigió solamente el collector para explicar SELECT compilado con parámetros
y se ejecutó baseline-base-v2 en otra base. No fue una repetición para buscar un
resultado favorable.

Los primeros post-fix (postfix-base/postfix-blocked, 9.456556/9.322675 s)
midieron el prototipo sin exención de safety. No son los resultados finales.
La regresión inicial ejecutó 774 IDs: 773 PASS y YIELD08 FAIL por flag B5
deshabilitado en la fixture. Corregida la fixture, el nuevo YIELD09 expuso un
defecto real: W1 termina deferred_to_new_input y la safety pendiente de W2
queda retenida por el forecast. Se conservan ambos probes fallidos y el probe
posterior PASS. La misma política E4 se acotó eximiendo conversaciones con
safety pendiente; B3/B5 y elegibilidad no se editaron. Esta corrección justifica
dos nuevas mediciones completas (postfix-final-base/postfix-final-blocked) y
la revalidación afectada. No se repiten para escoger un percentil favorable.
[refinement.json](evals/e4-claim/refinement.json) conserva alcance y hashes.

## Timelines reales por organización

Segundos relativos a T0; selección de la muestra con mayor eligible→claim de cada org y escenario.

| Escenario | Org | Message | Work | Planner/poll | T0 | T1 | T2 | T3 | T4 | T5 | T6 | T7 | T8 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline-base-v2 | 0 | 420 | 136 | planner-2/139 | 0.000000 | 7.952787 | 8.922480 | 8.968055 | 8.968062 | 8.978499 | 8.968159 | 9.016070 | 9.123184 |
| baseline-base-v2 | 1 | 523 | 169 | planner-1/174 | 0.000000 | 7.839140 | 8.234346 | 8.344323 | 10.587080 | 10.591443 | 10.587197 | 10.620107 | 10.829572 |
| baseline-blocked | 0 | 471 | 146 | planner-1/162 | 0.000000 | 7.919965 | 8.922012 | 8.951622 | 8.951631 | 8.956365 | 8.951742 | 8.976122 | 9.060006 |
| baseline-blocked | 1 | 421 | 131 | planner-2/141 | 0.000000 | 7.943504 | 8.380070 | 8.401996 | 10.570163 | 10.574007 | 10.570270 | 10.588053 | 10.650657 |
| postfix-final-base | 0 | 309 | 94 | planner-2/104 | 0.000000 | 7.930758 | 8.969404 | 9.127799 | 9.127809 | 9.132591 | 9.127905 | 9.151753 | 9.246970 |
| postfix-final-base | 1 | 455 | 138 | planner-2/146 | 0.000000 | 7.894974 | 9.864719 | 8.221150 | 10.187525 | 10.193882 | 10.187642 | 10.226743 | 10.321153 |
| postfix-final-blocked | 0 | 303 | 88 | planner-1/98 | 0.000000 | 7.929382 | 9.244985 | 9.466829 | 9.466838 | 9.470810 | 9.466947 | 9.496238 | 9.583605 |
| postfix-final-blocked | 1 | 351 | 104 | planner-2/123 | 0.000000 | 7.921937 | 8.279905 | 8.452831 | 11.960734 | 11.967233 | 11.960876 | 11.996844 | 12.157020 |

Ejemplo causal blocked antes del fix, org 1 / Message 421 / Work 131:
T1=7.943504; planner-1 está en pausa externa, arranca T1+0.436566,
observa org 0 y org 1 y toma org 0. Planner-2 está sirviendo noisy hasta
T1+1.598483 y después pausa 1.003681: arranca T1+2.602164. Selecciona
org 1 en 10.570163 y claimed_at=10.588053. Su tramo final T4→T7 es
17.890 ms. Org 1 fue observada antes, pero no había otro planner disponible.
No hubo candidate miss de org 1 en ese ejemplo.

Los intervalos de su espera 2.644549 s se particionan, sin doble conteo:
external_pause+service 0.967515; selection+service 0.100215;
service+service 1.061702; external_pause+external_pause 0.472732;
external_pause+selection 0.042385. Suman 2.644549 s. No equivalen a sumar
percentiles marginales ni separan causalmente todo coste CPU/DB.

Ejemplo base antes del fix, org 1 / Message 523 / Work 169: planner-2
observa ambas healthy en T1+0.505183 y toma org 0; planner-1 acaba noisy
en T1+1.637225, espera 1.014091 y arranca T1+2.651316. Claim de org 1
T1+2.780967. Nuevamente el coste grande está antes de la selección ganadora.
Las tablas incluyen también org 0 y las muestras posteriores, y los journals
conservan todas las oportunidades y fases por mensaje.

El mayor EC final blocked corresponde a Message351/Work104, org1:
T1=7.921937; planner2/poll122 inicia T1+0.357968, observa ambas healthy y
reclama org0. Planner1/poll112 inicia T1+1.604657, observa [org1,noisy],
intenta org1 a T0+9.826194 y retorna miss a T0+9.857030. Su SQL con lock
Organization tarda 3.104 ms y Conversation 4.522 ms, ambos SKIP LOCKED;
no llega a un SQL con lock TurnWork en ese intento. Inmediatamente hace
fallback a noisy. Planner2 termina org0 y pausa 1.024526 s, vuelve en
T0+11.585924 y reclama org1 en T0+11.996844 (EC=4.074907 s).

Message367 se incorpora a la misma conversación en T0+9.920549 y conserva
exactamente el deadline anterior. La cercanía al miss es compatible con el
lock de ingestión; **el holder no se instrumentó**, por lo que no se afirma
como causa demostrada. No había otro work PROCESSING de org1 en los intervalos
durables reconstruidos. La evidencia sí demuestra miss, fallback y servicio+
pausa posteriores: no una espera SQL de cuatro segundos, no abandono de un
Y sano disponible, ni reextensión del deadline. La query más cara y esta cola
residual son riesgos; no se añade una segunda corrección ni se declara que
todo tail por organización mejoró.

## Planners, cadencia y oportunidades

Claims y tiempo dentro de ciclos cubren warmup/medición/drain; las latencias sanas cubren solo el cohort de ingreso de medición. Busy aquí es tiempo dentro de un ciclo, incluida selección, no solo LLM. Idle es intervalo entre ciclos.

| Run | Planner | Ciclos | Claims org0/1/2 | Busy s | Idle s | Start→start p95 s | Completion→next p95 s | T1→siguiente inicio propio p95 s | Misses |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline-base-v2 | planner-1 | 187 | 9/10/60 | 166.366 | 187.590 | 3.360748 | 1.022898 | 2.941755 | 12 |
| baseline-base-v2 | planner-2 | 183 | 13/9/56 | 168.697 | 183.526 | 3.730420 | 1.020574 | 3.216844 | 7 |
| baseline-blocked | planner-1 | 191 | 11/6/60 | 160.458 | 191.283 | 3.353237 | 1.015554 | 2.884051 | 2 |
| baseline-blocked | planner-2 | 185 | 11/9/56 | 167.610 | 185.208 | 3.385534 | 1.015053 | 2.703923 | 5 |
| postfix-final-base | planner-1 | 174 | 9/12/49 | 180.517 | 174.237 | 3.544814 | 1.017223 | 3.186584 | 15 |
| postfix-final-base | planner-2 | 172 | 13/8/49 | 179.016 | 172.131 | 3.481132 | 1.011513 | 3.468487 | 16 |
| postfix-final-blocked | planner-1 | 167 | 8/10/49 | 186.077 | 167.114 | 3.545864 | 1.012859 | 3.173973 | 12 |
| postfix-final-blocked | planner-2 | 175 | 14/9/44 | 177.452 | 175.155 | 3.612319 | 1.012378 | 3.434842 | 14 |

Los PIDs OS y backend PostgreSQL están en cada recibo. Las oportunidades propias de cada planner son su siguiente inicio estricto tras T1. La oportunidad global permite 0 si ya había una selección en curso capaz de observar esa conversación.

| Run | Org | T1→oportunidad global p95 | T1→T3 p95 | T3→T7 p95 | T4→T7 p95 | Ambos busy en T1 /20 |
| --- | --- | --- | --- | --- | --- | --- |
| baseline-base-v2 | 0 | 1.000639 | 1.024458 | 0.049547 | 0.049540 | 0 |
| baseline-base-v2 | 1 | 1.646786 | 1.692085 | 2.275784 | 0.055505 | 0 |
| baseline-blocked | 0 | 1.002047 | 1.031657 | 0.080553 | 0.080544 | 0 |
| baseline-blocked | 1 | 2.476897 | 2.499318 | 2.389400 | 0.052953 | 1 |
| postfix-final-base | 0 | 1.038646 | 1.197041 | 0.056384 | 0.056171 | 0 |
| postfix-final-base | 1 | 1.301279 | 1.501922 | 2.005593 | 0.043298 | 0 |
| postfix-final-blocked | 0 | 1.315603 | 1.537447 | 0.042564 | 0.042557 | 0 |
| postfix-final-blocked | 1 | 1.665375 | 2.040173 | 3.544013 | 0.045782 | 0 |

No existe un coste fijo “poll=1 cuesta 1 s”. En base previo org 1 tuvo
12/20 muestras con dos inicios globales antes de claim; org 0 tuvo 19/20 con
uno. Ambos busy exactamente en T1: base 0/20 y blocked 1/20 para org 1;
no explica solo toda la asimetría. Sí hay periodos con ambos sirviendo después
de que la primera healthy tome un planner, como los 1.061702 s del ejemplo.
El bloqueo inyectado produce un ciclo de 11.524455 s antes del fix y
11.245110 s en el prototipo posterior; no se eliminó ni acortó el timeout real.

## Selector, duplicación e hipótesis

KEEP ya excluye busy antes de limit, toma una conversación por org, ordena recencia durable y devuelve hasta tres candidatos. El loop ya reintenta un miss dentro del mismo poll; batch=1 limita trabajos exitosos, no intentos. Los snapshots completos con orden/selecciones/READY/PROCESSING están en candidate_cases/cycles de cada analysis.json.

| Run | Ambas healthy READY snapshots | Noisy primero con healthy READY | Misses | Miss→claim mismo ciclo | Noisy near-ready aplicable | De éstos con claim noisy |
| --- | --- | --- | --- | --- | --- | --- |
| baseline-base-v2 | 14 | 0 | 19 | 2 | 6 | 3 |
| baseline-blocked | 10 | 0 | 7 | 0 | 10 | 9 |
| postfix-final-base | 19 | 0 | 31 | 5 | 0 | 0 |
| postfix-final-blocked | 21 | 0 | 26 | 7 | 0 | 0 |

En baseline base, dos misses de healthy org 0 terminan tomando org 1 en
el mismo ciclo; los otros 17 misses son noisy sin Y sano disponible. En blocked
previo los siete misses son noisy. Se descarta el patrón “pierde X, ignora Y
ya observado y desperdicia un ciclo”. No se añadió el retry que ya existía.
Tampoco hay noisy primero cuando healthy ya es READY; el residual es iniciar
noisy poco **antes** del deadline sano. Busy elimina una org PROCESSING del
snapshot, y una carrera posterior se revalida bajo claim; snapshot no reserva.

La detección near-ready usa el inicio de petición SQL, persistencia, deadline
≤1 s, org futura idle y recencia menor/null frente a la org seleccionada. Esa
hora es una aproximación cliente al snapshot PostgreSQL, no su timestamp wire.
En el prototipo hubo cero selecciones aplicables. En postfix-base quedó un intento noisy
con deadline a menos de un segundo de T4, pero el SQL tardó 0.251370 s: al
iniciar SQL el deadline estaba fuera del horizonte. Además fue miss, no claim.
No se confunde esa observación tardía con una violación del mecanismo. La
semántica exacta de la query se prueba con relojes controlados en PostgreSQL.

| Hipótesis | Evidencia | Contraevidencia/límite | Contribución y veredicto |
| --- | --- | --- | --- |
| H1 cadence | Pausa externa p95 ≈1.02 s; timeline suma servicio+pausa | T1→siguiente oportunidad varía; no cuesta 1 s fijo | Amplificador directo del tail; confirmado |
| H2 duplicación | 19/7 misses baseline base/blocked; snapshots simultáneos | KEEP hace fallback; 2 healthy misses toman la otra org en mismo poll | Existe carrera pero ciclo perdido con Y disponible descartado |
| H3 batch=1 | Un éxito termina ciclo; segunda org requiere otro planner/oportunidad | Ablation batch3 ayuda pero no es acceptance; batch no limita retries | Restricción/topología contribuye; se conserva |
| H4 noisy HOL residual | 3/9 claims noisy justo antes de READY aplicables; no-noisy reduce EC | 0 noisy primero con healthy ya READY | Preocupación de capacidad previa a READY confirmada; mecanismo elegido |
| H5 ambos busy | Ejemplo 1.061702 s de servicio+servicio tras claim org0 | En T1 casi nunca ambos busy; no explica solo la asimetría | Estado dinámico de disponibilidad confirmado |
| H6 orden | Org0 primero por recencia y fase de llegada; ambas org servidas por ambos PIDs | No afinidad fija ni IDs de healthy/noisy en runtime | Recencia+fase contribuye; se conserva orden al vencer deadline |
| H7 locks | SQL lock p95 de pocos ms; SKIP LOCKED y claims válidos | Final blocked tiene miss tras SQL Conversation y fallback; holder no capturado | Sin cola SQL de segundos demostrada; un miss sí amplifica cadencia; no tuning de locks |
| H8 query | Selector previo 19–27 ms p95; EXPLAIN 2.355/4.741 ms | Prototipo creció a 163/268 ms; coste final íntegro en tabla posterior | Descartada como causa principal previa; riesgo posterior explícito, sin índice |

## Ablations DIAGNOSTIC_ONLY

Cada control usa 30/120/20 s y cambia solo el override indicado; 24 healthy, 16 ordinarias. Son ventanas secuenciales, sin paired randomization: las diferencias de p95 no son efectos aditivos universales. El campo heredado profile_conditions en el subrecibo monotonic no anula e4_overrides ni convierte ablations en v1/acceptance.

| Control | Override explícito | Global persisted→claim p95 s | Org0 EC p95 s | Org1 EC p95 s |
| --- | --- | --- | --- | --- |
| ablation-no-noisy | {'E4_MEASURE_SECONDS': '120', 'E4_NO_NOISY': '1'} | 8.797841 | 0.855869 | 1.034412 |
| ablation-no-pause | {'E4_MEASURE_SECONDS': '120', 'E4_POLL_SECONDS': '0'} | 9.204620 | 0.093819 | 1.439806 |
| ablation-batch-three | {'E4_BATCH': '3', 'E4_MEASURE_SECONDS': '120'} | 9.540039 | 0.809050 | 1.684726 |
| ablation-fast-provider | {'E4_LLM_SECONDS': '.001', 'E4_MEASURE_SECONDS': '120'} | 9.053581 | 0.570864 | 1.430028 |
| candidate-bounded-yield | {'E4_CLAIM_CANDIDATE': 'bounded-yield', 'E4_MEASURE_SECONDS': '120'} | 8.905804 | 0.695957 | 0.964356 |

## Única mejora y fronteras

worker._pending_conversation_candidates añade una observación readonly de
mensajes ordinarios pending de otra org idle, con deadline dentro de la próxima
pausa existente de un segundo y último claim menor/null. En ese caso excluye
temporalmente el candidato de una org ya servida. Nunca excluye por esta regla
a una org nunca reclamada. Al llegar el deadline se restablece la selección
original por recencia. Conversaciones con safety pendiente están exentas de
esa retención, también después de que W1 difiera a nuevo input. Conserva
candidato máximo 3, fallback, batch=1, poll=1,
N=1 y PostgreSQL como autoridad. No reserva planner, TurnWork, capacity, tokens
ni admission. La forecast no adelanta ni escribe available_at. Los retry/due
works mantienen sus rutas originales; safety conserva su disponibilidad
original en el selector y su fastpath receptor. No se añade otra mejora.

El lookahead se limita a un segundo por observación; no garantiza un límite
global de starvation bajo cualquier workload con forecasts sucesivos. No es
fairness fuerte ni un scheduler general. Tampoco promete rendimiento para
topologías/rates que no se midieron. B3 sigue validando ownership, lease,
epoch/token, membership/context, anchor/cursor y fencing bajo la transacción.
Candidate miss no crea admission ni devuelve budget. B9B conserva 30 calls,
18k reserved, output600, request64KiB y timeout10; no cambios de política.
B5 safety/human y sender B4 conservan precedencia e independencia. El test
nuevo READY une inbound después de vencido y verifica deadline inmutable.

No cambios de schema, índices, broker ni servicios nuevos. Solamente 18 líneas
runtime adicionales, más pruebas específicas y tooling/evidencia separados del runtime.

## Coste SQL y locks

Duraciones de SELECT/UPDATE con lock son cotas superiores, que incluyen transporte, ejecución y posible espera; no se publican como lock-wait puro. EXPLAIN ANALYZE se ejecuta al cerrar cada carga y no equivale a la distribución de SQL durante la carga. Los pg_stat_activity waits se muestrean cada 5 s; no prueban ausencia de todo wait transitorio.

| Run | Selector p95 ms | Selector max ms | EXPLAIN execution ms | Org SQL p95 ms | Conv SQL p95 ms | Work SQL p95 ms | Message SQL p95 ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline-base-v2 | 27.261 | 133.498 | 2.355 | 3.064 | 8.064 | 7.471 | 5.499 |
| baseline-blocked | 19.282 | 173.753 | 4.741 | 1.983 | 5.766 | 6.788 | 5.560 |
| postfix-final-base | 327.238 | 514.508 | 233.000 | 2.660 | 7.531 | 4.926 | 5.519 |
| postfix-final-blocked | 341.382 | 599.652 | 243.396 | 3.504 | 7.832 | 5.681 | 5.602 |

El crecimiento de la query es material: de 27.261→327.238 ms base y
19.282→341.382 ms blocked. Máximo final blocked
599.652 ms. El cierre EXPLAIN base pasa de 2.355 a
233.000 ms. No se oculta esta regresión de coste;
el gate healthy final y su margen se muestran íntegros. No se crea índice ni
se encadena un segundo fix. Antes de una promoción hace falta validar el candidato
con el PROFILE integral original y revisar margen/coste bajo su proceso formal.

## Latencias posteriores y denominadores

Los componentes son p95 por cohorte ordinaria (20 por org), medidos separadamente. El gate global contractual (60, incluyendo 20 safety) se muestra aparte.

| Run | Org | Persisted→eligible p95 s | Eligible→claim p95 s | Persisted→claim p95 s | Joined READY |
| --- | --- | --- | --- | --- | --- |
| baseline-base-v2 | 0 | 7.963574 | 1.063283 | 9.016070 | 0 |
| baseline-base-v2 | 1 | 7.967141 | 2.780967 | 10.620107 | 3 |
| baseline-blocked | 0 | 7.951843 | 1.056157 | 8.976122 | 0 |
| baseline-blocked | 1 | 7.951351 | 2.644549 | 10.588053 | 6 |
| postfix-final-base | 0 | 7.934545 | 1.220995 | 9.151753 | 0 |
| postfix-final-base | 1 | 7.947749 | 2.331769 | 10.226743 | 1 |
| postfix-final-blocked | 0 | 7.934014 | 1.566856 | 9.496238 | 0 |
| postfix-final-blocked | 1 | 7.942308 | 4.074907 | 11.996844 | 2 |

| Run | Healthy n | PC p95 s | Max s | Missing | 10−p95 s | Safety p95 s | Outbox p95 s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline-base-v2 | 60 | 10.032213 | 10.620107 | 0 | -0.032213 | 3.243261 | 2.605086 |
| baseline-blocked | 60 | 10.396520 | 10.588053 | 0 | -0.396520 | 3.117009 | 2.543384 |
| postfix-final-base | 60 | 9.742585 | 10.226743 | 0 | 0.257415 | 3.772796 | 3.00554 |
| postfix-final-blocked | 60 | 9.798881 | 11.996844 | 0 | 0.201119 | 3.97304 | 2.65429 |

La desaparición del forecast aplicable no elimina toda la asimetría. En base final, EC org0/org1 es 1.220995/2.331769 s. El p95 ordinario org1=10.226743 s puede superar 10 s aunque el gate global contractual de 60 muestras cumpla. No se sustituye el denominador ni se inventa un gate nuevo por org. Blocked final se conserva con su resultado original, sin una segunda mejora.

Base baseline registra 359 inbound por frontera temporal (60 healthy +
299 noisy); las otras cargas relevantes 360. No se cambiaron tasas ni ventana
para corregir ese borde. Los gates safety/outbox medidos constan en summary.json. Blocked no tiene gate
canónico equivalente de outbox. Cumplir estos gates diagnósticos no prueba las
cinco variantes y corpus/COST/SCALE necesarios para PROFILE integral.

## Calls, deferrals y backlog

Cohorte de works con context_at dentro de ventana, distinta de la cohorte de inbound creada dentro de ventana. Deferrals cuenta exactamente outcome_code=deferred_to_new_input según el collector original, no mensajes perdidos ni reextensión de READY.

| Run | Org | Works | Calls | Calls/work | Calls/dialogue | Deferrals | Inbound sin claim al cierre |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline-base-v2 | 0 | 30 | 40 | 1.333333 | 3.636364 | 8 | 0 |
| baseline-base-v2 | 1 | 27 | 34 | 1.259259 | 3.090909 | 7 | 0 |
| baseline-base-v2 | 2 | 103 | 206 | 2.000000 | 2.000000 | 0 | 213 |
| baseline-blocked | 0 | 30 | 40 | 1.333333 | 3.636364 | 6 | 0 |
| baseline-blocked | 1 | 23 | 26 | 1.130435 | 2.363636 | 3 | 0 |
| baseline-blocked | 2 | 103 | 206 | 2.000000 | 2.000000 | 0 | 214 |
| postfix-final-base | 0 | 30 | 40 | 1.333333 | 3.636364 | 9 | 0 |
| postfix-final-base | 1 | 29 | 38 | 1.310345 | 3.454545 | 9 | 0 |
| postfix-final-base | 2 | 85 | 170 | 2.000000 | 2.000000 | 0 | 233 |
| postfix-final-blocked | 0 | 30 | 40 | 1.333333 | 3.636364 | 10 | 0 |
| postfix-final-blocked | 1 | 28 | 36 | 1.285714 | 3.272727 | 8 | 0 |
| postfix-final-blocked | 2 | 81 | 162 | 2.000000 | 2.000000 | 0 | 238 |

READ completo sigue requiriendo dos calls reales; safety cero. La media
healthy mezcla works safety de cero calls y works READ de dos. Cuando una
cohorte contiene 10 safety y 20 READ resulta 1.333333; las otras medias y
denominadores exactos se muestran en la tabla y en el recibo. La
inyección bloqueada conserva timeout/retry; algún trabajo completo fuera de
la cohorte puede admitir tres calls y otro trabajo observado antes de retry
admite uno. No se deduce “todos los works exactamente dos” de una media.
El backlog final por organización y los missing healthy constan en la tabla.
No se declara drenaje completo ni capacidad
para sostener 1 inbound noisy/s. Máximos de cola son observados cada 5 s.

## Regresión, checks, infraestructura y privacidad

Cobertura acumulada: **775/775 IDs con recibo PASS**, sin IDs faltantes ni fallos pendientes. Primera ejecución: 773/774 PASS, con un FAIL de fixture conservado. La versión final revalidó **124 IDs**, todos PASS; 651 IDs históricos tienen recibo del prototipo. No se afirma que los 775 se ejecutaran sobre el mismo hash final. Hubo 898 ejecuciones de regresión, más tres probes separados. regression-summary.json conserva coverage_by_id con recibo y hash; regression-final-inventory.json enumera la unión exacta. Las once pruebas nuevas se limitan al mecanismo:

- `apps.agent.tests.test_e4_claim_yield.E4ClaimYieldTests.test_e4_yield_01_yields_to_idle_less_recent_org_without_claim_or_budget`
- `apps.agent.tests.test_e4_claim_yield.E4ClaimYieldTests.test_e4_yield_02_deadline_due_restores_original_recency_and_batch_one`
- `apps.agent.tests.test_e4_claim_yield.E4ClaimYieldTests.test_e4_yield_03_far_future_does_not_delay_eligible_org`
- `apps.agent.tests.test_e4_claim_yield.E4ClaimYieldTests.test_e4_yield_04_busy_upcoming_org_does_not_reserve_capacity`
- `apps.agent.tests.test_e4_claim_yield.E4ClaimYieldTests.test_e4_yield_05_never_claimed_org_keeps_original_priority`
- `apps.agent.tests.test_e4_claim_yield.E4ClaimYieldTests.test_e4_yield_06_more_recent_upcoming_org_does_not_delay_older_org`
- `apps.agent.tests.test_e4_claim_yield.E4ClaimYieldTests.test_e4_yield_07_ready_join_stays_monotonic_while_selection_yields`
- `apps.agent.tests.test_e4_claim_yield.E4ClaimYieldTests.test_e4_yield_08_safety_bypasses_forecast_and_occupied_org`
- `apps.agent.tests.test_e4_claim_yield.E4ClaimYieldTests.test_e4_yield_09_pending_safety_after_live_worker_is_not_withheld`
- `apps.agent.tests.test_e4_yield_processes.E4YieldProcessTests.test_e4_yield_proc_01_both_forecasts_reserve_nothing_then_collide_and_fall_through`
- `apps.agent.tests.test_e4_yield_processes.E4YieldProcessTests.test_e4_yield_proc_02_stale_candidate_discarded_and_last_org_slot_revalidated`

| Frontera | IDs ejecutados |
| --- | --- |
| B3 | 47 |
| B5 | 30 |
| B9A | 45 |
| B9B | 34 |
| B9C | 27 |
| E4 | 20 |
| Monotonic | 31 |
| Worker | 12 |
| Planner | 21 |
| Sender B4 | 47 |

Las pruebas nuevas cubren forecast sin claim/capacity/budget, deadline,
horizonte, busy, never-claimed, recencia, READY join, fastpath safety y safety
pendiente después de W1. Dos OS planners
con conexiones PostgreSQL distintas prueban ambos forecasts sin reserva,
colisión y fallback hacia otra org, candidato descartado tras observación y
último slot revalidado. Reloj controlado solo para elegibilidad de la fixture;
claims, locks, leases, ownership y exclusión son PostgreSQL reales. Se pausa
run_turn para coordinar/finalizar la fixture, no para medir performance.
Las suites históricas incluidas aportan takeover/stale witnesses, candidatos
no elegibles, B3/B5/B9A/B9B/B9C, E4 KEEP, worker/planner, monotonic y sender
independence. No reemplazan ni editan pruebas históricas; no skips/xfail nuevos.

Checks: migrate, system check, makemigrations --check y migrate --check pasan;
cero migraciones nuevas. No se modificó la configuración productiva. La
instancia local propia puerto35443 y prefijo test_b8b_e4claim_ usa fuentes
bloqueadas Python3.13/Django6.0.5/PG16.15 y no credenciales productivas.
Cleanup se ejecuta solo cuando no quedan clientes externos, locks en espera ni
prepared transactions; verifica data_directory absoluto, elimina exclusivamente
bases con prefijo propio, detiene cluster y comprueba puerto cerrado antes de
retirar su directorio/log. Binarios y otros clusters/entornos preexistentes quedan
intactos. El recibo cleanup.json conserva conteos y hash del log retirado.

Trazas contienen eventos cerrados y timestamps/IDs técnicos locales, sin payload,
phones, prompts, responses ni secretos. Los nombres response en el vocabulario
de eventos no incluyen contenido. Instrumentación solo en tests; cero labels
productivos nuevos. validation.json documenta scan de sentinels y hashes; no se
presenta una búsqueda regex como prueba universal contra toda PII. Los bytes de
evidencia se conservan por .gitattributes y manifest.sha256.json. No hay consultas
a una DB productiva ni IO externo real. B0 cerrado, B7B=False, flags={}, grants=[],
0 clínicas activadas y PENDING_ACTIVATION_REQUIREMENTS son el estado conservado,
no una activación validada contra producción.

Cleanup verificado: CLEANED; clientes restantes 0, locks en espera 0, prepared 0; puerto cerrado=True, directorio ausente=True, log ausente=True.

## Los 58 campos solicitados

Esta tabla referencia el detalle anterior y los recibos locales. El hash del segundo commit/HEAD final se entrega en la respuesta de cierre, porque un documento no puede incorporar su propio hash Git sin modificarlo.

| # | Campo | Resultado |
| --- | --- | --- |
| 1 | Estado | Una mejora E4; ROOT_CAUSE_CONFIRMED; DIAGNOSTIC_GATE_GREEN; STOP al tuning |
| 2 | Baseline | f051c27002986193772ced0fb1e00e19822d26ef |
| 3 | Commits | 83ee3b24c84b170e22e401cb09a34da5320ae0a3 runtime/tests; segundo docs/evidencia, hash en cierre |
| 4 | HEAD final | Commit docs/evidencia de este informe; hash exacto en respuesta final |
| 5 | Root cause | Recencia/fase favorece org0; servicio noisy iniciado antes de READY + pausa externa + batch1 deja esperar a org1 |
| 6 | Timeline org0 | Tabla T0–T8 y todas las muestras en analysis.json; no p95 usado como timeline |
| 7 | Timeline org1 | Message421/Work131: T1=7.943504, T3=8.401996, T4=10.570163, T7=10.588053 relativo a T0 |
| 8 | Planner identities | Ambos planners reclaman ambas orgs; PIDs OS/PG en los recibos; sin afinidad fija |
| 9 | Planner cadence | Servicio+pausa real; tablas por planner; completion→next p95≈1.0–1.02 s |
| 10 | Eligible→next opportunity | Tabla p95 global y propio por planner; se registra selección ya en curso |
| 11 | Candidate selection | Hasta3, uno/org, busy excluido, recencia intacta al vencer; snapshot advisory |
| 12 | Duplicated planner effort | Carreras existen; descarta abandono de Y observado: fallback mismo poll ya existe |
| 13 | batch=1 impact | Un éxito por ciclo; otro claim espera otro planner; sin cambiar batch |
| 14 | noisy impact | 0 HOL con healthy READY; 3/9 claims previos near-ready aplicables →0/0 posteriores |
| 15 | both-planners-busy impact | Raro exactamente en T1; intervalos posteriores con ambos ocupados explican parte de EC |
| 16 | locks | SQL con locks p95 ms; cotas superiores, no lock-wait puro; sin tuning |
| 17 | query cost | Selector p95 27.261→327.238 ms base, 19.282→341.382 ms blocked; sin índice |
| 18 | Ablations | No-noisy/no-pause/batch3/provider≈0 y candidato; DIAGNOSTIC_ONLY 30/120/20 |
| 19 | Cambio elegido | Yield advisory ante otra org idle menos recientemente servida cuyo deadline llega en ≤1s |
| 20 | Por qué pertenece E4 | Coordina selección/utilización; no autoridad, persistencia ni contrato nuevo |
| 21 | B3 preserved | Claim, contexto, membership, anchor/cursor, lease/epoch/token, fencing sin editar |
| 22 | B5 preserved | Safety/human conservados; B5 histórico revalidado + YIELD08/09; defecto del prototipo corregido |
| 23 | B9B preserved | Admission solo tras claim; candidate observation/miss no reserva ni devuelve budget |
| 24 | B9C preserved | Org SKIP LOCKED + revalidación; N1 probado en PostgreSQL/procesos |
| 25 | monotonic READY preserved | 8/25 y available_at intactos; YIELD07 y suite monotonic |
| 26 | Multiprocess | Dos nuevos tests OS/PG: forecast→colisión/fallback y stale/discard→último slot |
| 27 | max PROCESSING/org | 1 en estados durables observables; intervalos ordinarios, snapshots y pruebas B9C; safety finaliza atómicamente |
| 28 | candidate misses | Final base 31 y blocked 26; advisory, sin admission, fallback donde exista Y |
| 29 | lost work | Healthy missing base/blocked 0/0; backlog noisy 233/238 durable; no drained/lost ficticio |
| 30 | cross-tenant | 0 desajustes org/conversación membership en collector; regresión fencing/scopes |
| 31 | stale progress | Revalidación/fencing intactos, tests históricos takeover + nueva observación descartada |
| 32 | persisted→eligible base | 7.934545/7.947749 s (org0/org1; ordinarios) |
| 33 | eligible→claim base | 1.220995/2.331769 s (org0/org1; ordinarios) |
| 34 | persisted→claim base | 9.151753/10.226743 s (org0/org1; ordinarios); global 9.742585 s, n60 |
| 35 | persisted→eligible blocked | 7.934014/7.942308 s (org0/org1; ordinarios) |
| 36 | eligible→claim blocked | 1.566856/4.074907 s (org0/org1; ordinarios) |
| 37 | persisted→claim blocked | 9.496238/11.996844 s (org0/org1; ordinarios); global 9.798881 s, n60 |
| 38 | margen base | +0.257415 s |
| 39 | margen blocked | +0.201119 s |
| 40 | Calls/work | Healthy base org0/1=1.333333/1.310345; blocked=1.333333/1.285714; READ real2, safety0; distribuciones arriba |
| 41 | Deferrals | Base org0/1=9/9; blocked=10/8; no cambiar calls/READY |
| 42 | PROFILE rerun sí/no | No; opcional habilitado por gates diagnósticos y regresión; evaluación integral posterior |
| 43 | PROFILE result si aplica | NOT_RUN; diagnósticos no son PROFILE integral PASS |
| 44 | Regression | 775/775 PASS |
| 45 | IDs | Inventario exacto + coverage_by_id/recibos por shard; once nuevos IDs listados |
| 46 | skips/xfail | 0 requeridos; resultado exacto en recibos finales |
| 47 | Checks | migrate/check/makemigrations --check/migrate --check PASS, diff --check |
| 48 | Migrations | 0; sin tabla, índice ni persistencia nueva |
| 49 | Infra cleanup | Recibo cleanup.json, solo cluster/bases propios; clientes/locks/prepared0 |
| 50 | Privacy | Eventos cerrados e IDs locales, sin payload/phones/prompts/responses ni nuevos labels runtime |
| 51 | Risks | SQL más caro, margen limitado, backlog noisy, forecasts sucesivos sin fairness fuerte; muestra local única; T5/T6/T8 receptor safety no capturados |
| 52 | Production gates | B0 cerrado; B7B=False; flags={}; release grants=[]; PENDING_ACTIVATION_REQUIREMENTS |
| 53 | Active clinics | 0 |
| 54 | Deploy | No |
| 55 | B9 | IN_PROGRESS |
| 56 | B9E | FAIL histórico |
| 57 | PROFILE histórico | FAIL |
| 58 | Próximo paso | Revisión del candidato y evaluación PROFILE v1 integral posterior; sin alterar contratos ni activar producción |
