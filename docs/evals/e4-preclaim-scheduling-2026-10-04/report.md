# E4 — cierre formal del análisis causal de scheduling preclaim

## 1. Decision

**E4 = CLOSED. Decisión formal: `CAPACITY_LIMIT_CONFIRMED → STOP_BEFORE_TUNING`.**

Baseline obligatorio y HEAD conservado: `825db75df68bf076929fa787e77beefe96803350`, rama `codex/e4-capacity-scheduling`. Este cierre es documental y de estado, sobre la evidencia ya generada. No reabre la investigación ni constituye una carga nueva, PROFILE, benchmark, aceptación B9E o E4 formal.

Se actualiza este informe existente y sus estados JSON; no se crea otro expediente equivalente. Se conserva el identificador `preclaim-analysis-f530e7f0cabb41c7be084045db3bcde8`.

## 2. Evidence

Se reutilizan como fuentes inmutables los diagnósticos autorizados previamente, sin reutilizar sus IDs para una carga nueva:

| Fuente | Inputs org 1/2/3 | Claims ordinarios org 3 | Pending al cierre org 3 | Máximo sano | Máximo ruidoso |
| --- | --- | ---: | ---: | ---: | ---: |
| `dded711c1ce04cfd8f01af5dc7d62da2` | 33/33/330 | 123 | 207 | 9,604493 s | 226,515086 s |
| `f1239f896754491c8998d56e43356aa1` | 33/33/330 | 106 | 224 | 10,288615 s | 243,354657 s |
| `f1922430c60348e8adce24196c02bf5a` | 33/33/330 | 129 | 201 | 9,472716 s | 221,810544 s |

Los 33 inputs de cada organización sana incluyen 11 safety inline y 22 turnos ordinarios. El último diagnóstico tiene 195 claims totales: 173 ordinarios y 22 safety. **Los diagnósticos primero y tercero tuvieron todos los claims sanos por debajo de 10 s**; el segundo contiene un claim sano de 10,288615 s. Este máximo tampoco basta para decidir un gate de p95 del PROFILE.

Los tres usaron dos planners secuenciales, batch=1, pausa de 1 s después de cada ciclo, sender independiente, cargas sanas cada 10 s y ruido cada 1 s; 30 s warmup, 300 s carga y 20 s drain. Se conservaron PostgreSQL aislado, fsync=on y synchronous_commit=on. Esta tarea no inicia PostgreSQL, providers, planners, otro diagnóstico ni pruebas sintéticas.

Los manifiestos originales validan **74 + 80 + 89 = 243 archivos**. Se releen los 12 journals de carga con el validador del HEAD: secuencia, digest/footer, cero failed_writes y ninguna transacción abierta al cierre. Los recibos de equivalencia originales permanecen intactos: seis pruebas por diagnóstico, cero failures/errors/skips/xfail, con rollback, concurrencia, waits controlados, READY/reconnect y LLM bloqueado. Son pruebas controladas ON/OFF, no una afirmación de igualdad temporal o del ganador entre cargas concurrentes independientes.

Reproducción offline: [derive.py](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/e4-preclaim-scheduling-2026-10-04/derive.py). Datos completos: [scheduling-evidence.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/e4-preclaim-scheduling-2026-10-04/scheduling-evidence.json), [CSV por intento](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/e4-preclaim-scheduling-2026-10-04/per-attempt-scheduling.csv), [intervalos de capacidad](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/e4-preclaim-scheduling-2026-10-04/capacity-intervals.json), [candidatos e intentos por selección](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/e4-preclaim-scheduling-2026-10-04/selector-observations.json) y [prueba de providers secuenciales](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/e4-preclaim-scheduling-2026-10-04/provider-proof.json).

## 3. Causal findings

La organización ruidosa ofrece un turno ordinario por segundo en conversaciones distintas. El cupo agregado B9C es **N=1**, retenido durante dos llamadas LLM secuenciales y un READ, hasta la finalización committed. Los proveedores controlados imponen al menos **1,1 s de servicio por turno**: incluso un scheduler sin pausas no podría sostener esa entrada con este cupo. Además, la cola se sirve por conversación, con un candidato por organización; READY no concede prioridad sobre conversaciones anteriores. La ocupación, las pausas después de cada ciclo, batch=1 y la prioridad entre organizaciones amplifican la espera observada. No hay evidencia de una violación de B9C/B9D que justifique una corrección del runtime.

Esto no atribuye toda la latencia a saturación. En el caso extremo del último diagnóstico, de **213,7624154 s** entre elegibilidad y selección, **118,4581902 s** corresponden a cupo organizativo ocupado y **94,7844987 s** a cupo libre; **0,5197265 s** quedan en ventanas de incertidumbre de commit. La organización puede estar libre y aun así no recibir el siguiente claim. La regla de yield permite esto intencionalmente y el contrato no promete starvation global acotada.

### Modelo causal y reglas actuales

La cadena propuesta necesita una precisión: hay una **observación advisory de capacidad antes de seleccionar**, pero la **adquisición autoritativa ocurre después de la selección, en el commit del claim**.

```mermaid
flowchart LR
    P[Message persisted] --> E[Deadline satisfecho / READY]
    E --> O[Oportunidad de un planner]
    O --> L[Poll]
    L --> S[SQL: capacidad advisory, ranking, yield, LIMIT 3]
    S --> C[Claim: locks y revalidación B9C]
    C --> A[Commit: capacidad adquirida]
    A --> T[Turno secuencial]
    T --> F[Finalización committed: capacidad liberada]
    F --> W[Pausa 1 s]
    W --> L
```

| Frontera | Condición para avanzar | Qué permite esperar | Timeout/prioridad y efecto del ruido |
| --- | --- | --- | --- |
| Persisted → eligible | Pendiente ordinario durable y deadline vencido según DB. | Debounce anterior a READY. Ingest usa lock Conversation y DB clock fresco. | Rolling 8 s/cap 25 s antes de READY; otra org no cambia este deadline. READY latched no se retira para perseguir tráfico nuevo. |
| Eligible → oportunidad de planner | Un proceso llega al siguiente ciclo. | `_run_turn` es síncrono: LLM, READ y finalización retienen ese proceso; después siempre hay pausa. | No hay wakeup por READY ni SLA preclaim. Si ambos procesan orgs distintas, una tercera espera; ruido puede ocupar uno y contribuir a la espera residual del otro. |
| Oportunidad → poll | Terminar el ciclo/pausa y volver al loop. | Pausa de 1 s también después de éxito, misses o lista vacía. | No hay tick común ni planner asignado a una org; los dos observan la misma cola global. |
| Poll → org considerada/selección | Conversación con inbound elegible o retry/reclaim due; org sin trabajo activo; pasar yield/ranking/LIMIT. | Org busy se excluye **antes** del límite. READY de una org libre puede quedar fuera por forecast o por preferir otra conversación de la misma org. | Preferencia por último claimed_at menor, NULL primero. Dentro de org: last_activity_at e ID ascendentes; máximo tres orgs. No es round-robin ni garantía temporal de conversación. |
| Selección → claim/capacidad | Revalidación bajo locks Organization NO KEY UPDATE SKIP LOCKED → Conversation SKIP LOCKED → TurnWork/Message. | Otro planner puede ganar; lock omitido o capacidad ocupada producen miss sin claim. | Fallback a otra org del mismo resultado; no reservar cupo, crear trabajo, incrementar attempts ni consumir B9B al saturarse. |
| Claim → commit_ack | Persistir membership fijo, token/epoch, attempts y lease; commit real. | SQL/locks/rollback posibles; selected no equivale a admitted. | Solo el commit adquiere cupo. Commit ausente no ocupa. Selector readonly y snapshot previo no autorizan N+1. |
| Commit → siguiente claim de la org | Liberación committed por completion/failure/retry, invalidación o expiry. | Un turno retiene N=1 durante toda la planificación y efectos locales. | Lease 15 min/deadline de ejecución 12 min corresponden al trabajo reclamado; no son TTL preclaim. Retry tiene backoff y vuelve a competir. Sender queda fuera del cupo. |

Implementación verificada en [worker.py](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/worker.py:37), [poll secuencial](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/worker.py:93), [pausa incondicional](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/management/commands/run_agent_worker.py:85), [predicado de cupo](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/durable.py:101), [adquisición](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/durable.py:128) y [liberación](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/durable.py:263). Se verificaron los rangos sobre fuente actual; el índice del grafo tiene algunos rangos anteriores a la instrumentación.

### Asignación, batch y fairness

Ningún planner tiene afinidad fija a una organización. Gana el proceso que obtiene los locks y la autoridad B3/B9C. Ambos pueden seleccionar la misma org con snapshots anteriores, pero solo uno adquiere su cupo. En estas cargas hubo un attempt por trabajo, epoch=0, sin reclaim/expiry: no pueden mantener simultáneamente dos turnos ordinarios con autoridad de la misma org. B9C sí admite la limitación honesta de que, después de expiry, una llamada externa antigua continúe físicamente mientras el worker pierde autoridad; eso no ocurrió aquí.

`LIMIT 3` devuelve candidatos, **no tres ejecuciones con batch=1**. Tras el primer claim exitoso el planner ejecuta ese turno y devuelve el ciclo; los restantes candidatos esperan otro planner/poll. Un miss sí cae al candidato siguiente. Si todos fallan, vuelve al loop sin perder inputs. El siguiente poll recompone capacidad, deadlines y recencia, sin cursor ni reserva durable.

La recencia se deriva del último claim de **cualquier TurnWork de la org**, incluido safety inline. No cuenta mensajes servidos, peso, backlog ni déficit de capacidad. La organización con mayor backlog no obtiene más candidatos por poll. Puede recibir mucho servicio cuando otras orgs están ausentes/futuras, pero queda excluida mientras está ocupada. Dentro de la org no se promete FIFO por mensaje: se ordenan conversaciones por last_activity_at/ID. En el ruido de estos diagnósticos cada input usa una conversación distinta, de modo que las conversaciones anteriores explican la precedencia observada.

No hay prueba de starvation infinita: las tres orgs progresaron y los 201 pendientes finales del último diagnóstico son una cola **censurada al cierre**, no un abandono demostrado. Tampoco hay garantía que permita descartar starvation para cualquier tráfico futuro; el yield puede repetirse y last_activity puede cambiar con nuevos inputs. El requisito SCALE es progreso y no monopolizar todos los planners; no aislamiento absoluto de CPU, DB o latencia.

### Ocupación y fases por intento

Método: los timestamps DB de elegibilidad se trasladan al reloj monotónico mediante los brackets del DB clock original. Se usa la elegibilidad más tardía posible para un intervalo conservador hasta `selection_start`. Un cupo está **seguramente ocupado** entre ACK del claim y comienzo del commit de finalización; **posiblemente ocupado** desde comienzo del commit de claim hasta ACK de finalización. La diferencia se publica como incertidumbre de visibilidad del commit. No se usa `completed_at` como timestamp de commit: se genera con `Now()` en el UPDATE, antes del commit.

Los estados siguientes son disjuntos dentro del mismo intervalo, no percentiles sumados ni tiempos de ambos workers añadidos entre sí. “Fuera de turn” incluye SQL de poll/claim, pausa y overhead; no significa proceso listo para aceptar otro trabajo instantáneamente.

| Intento | Eligible → selection, s (cota inferior) | Cupo org ocupado | Cupo org libre, ambos en turn | Cupo libre, uno en turn | Cupo libre, ambos entre polls | Cupo libre, ninguno en turn y al menos uno en poll/claim | Commit incierto |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| f192 / W4 / org3 | 4,3535974 | 3,1745061 | 0 | 0,0003844 | 0,9439655 | 0,2248328 | 0,0099086 |
| f192 / W125 / org2 | 1,4125292 | 0 | 0 | 0,9256486 | 0,3787365 | 0,1081441 | 0 |
| f192 / W195 / org3 | 213,7624154 | 118,4581902 | 14,8583438 | 11,0715231 | 56,4514873 | 12,4031445 | 0,5197265 |
| f123 / W165 / org2 | 2,1063966 | 0 | 0,2223096 | 1,8840870 | 0 | 0 | 0 |

La incertidumbre adicional de la frontera eligible es respectivamente 0,4877 / 0,6603 / 0,6058 / 0,8830 ms. Las sumas de cada fila son su intervalo conservador. Las conversiones heredan la hipótesis original de ausencia de un salto del reloj DB; no se dispone de una prueba independiente del sistema operativo de que nunca lo hubo.

**W195, mensaje 217, org3, planner-2.** Durante la espera se ejecutaron 244 selecciones de ambos planners, 121 vacías, y se admitieron **82 turnos de mensajes anteriores de la misma org**. Su conversación no figuró en esos candidatos anteriores; figuró al llegar su selección efectiva. La demora no es un único intervalo de polling ni un SELECT ejecutándose durante 213 s. El cupo estuvo libre 94,7844987 s; de ellos, 56,4514873 s coincidieron con ambos procesos entre polls. Otros 14,8583438 s coinciden con ambos atendiendo otras organizaciones. Esto demuestra varias reglas actuando, no monopolización de ambos planners por org3.

**W4, mensaje 6, org3.** Esperó un solo mensaje anterior admitido durante su intervalo: ocupación 3,1745061 s más intervalos entre polls y evaluación. Un planner no procesó ningún turno durante esa espera, pero no podía adquirir N+1 mientras el otro retenía el único cupo de org3. Un planner libre no crea un cupo libre para esa org.

**W165 sano, mensaje 529, org2, segundo diagnóstico.** Su cupo estuvo libre durante toda la espera. Planner-2 terminó W163/org3 y después pausó. Planner-1 seleccionó `[conv13/org1, conv14/org2]` en selección `300d06789d47421cb963091ef006b665`; comenzó un claim solo de conv13 y procesó W164/org1. Batch=1 impidió procesar también conv14 en ese ciclo. Esta asociación está en los eventos, no se deduce por cercanía de logs. Org2 finalmente fue reclamada por planner-2. **Aquí sí están demostradas la ocupación de otro trabajo, la prioridad de otro candidato y la pausa, con capacidad organizativa libre.** No lo explica una espera de cuota de org2 ni una retención de forecast de ese candidato, que sí apareció en la lista anterior.

### Qué parte se puede atribuir estrictamente al polling

En la espera de W195, planner-2 tiene **124 pausas completas configuradas de 1 s** y 124,2980089 s medidos entre polls. Procesó turnos anteriores durante 78,3050139 s. Planner-1 tiene 120 pausas completas y dos fragmentos: el tiempo de pausa configurada solapado con la espera queda en [121,0664597; 121,0719960] s; sus gaps suman 121,3638925 s y sus turns 81,1798744 s.

Estas duraciones por proceso **se solapan** con la ocupación de org3 y entre ellas. No se suman 124 + 121 s ni se afirma que quitar la pausa ahorraría 124 s al mensaje. El dato disjunto útil es 56,4514873 s de cupo libre con ambos entre polls; el gap incluye el segundo configurado más pequeño overhead, sin eventos que ubiquen por separado cada entrada/salida de `sleep`.

En W165, planner-2 consumió 1,1025524 s del turno anterior y una pausa completa de 1 s, medida como gap de 1,0035921 s. El resto del intervalo preselection es overhead de poll/claim previo y la frontera eligible. Reducir polling podría cambiar el margen de este caso, pero no elimina la precedencia por batch/recencia ni demuestra estabilidad para org3. No se hace ese cambio ni se ofrece una predicción contrafactual.

### Cota de servicio y reproducibilidad

Los 167/150/173 turnos ordinarios de los tres diagnósticos tienen exactamente **dos llamadas LLM secuenciales**, ambas dentro del cupo. Los journals registran start/end de cada llamada. Los resultados cerrados de cada planner registran un READ por turno. El adapter preservado duerme 0,5 s por LLM y 0,1 s por READ; el READ de catálogo se ejecuta entre la respuesta tool de la primera llamada y la segunda llamada. La cota **1,1 s** viene del adapter y la secuencia confirmada, no de timestamps inventados para READ.

Con N=1, demanda mínima de org3: 330 × 1,1 = **363 s** de cupo, superior incluso a los 350 s completos warmup+carga+drain, antes de descontar elegibilidad inicial o servicio de otras orgs. En régimen, entrada 1/s > capacidad ideal <=1/1,1 = **0,9091/s**. Por tanto, agregar planners conservando N=1 o eliminar solo pausas no puede hacer estable esta carga idéntica.

| Diagnóstico | Hold seguro org3 mínimo / mediana / máximo | Serial LLM total mediana | Pending org3 |
| --- | --- | --- | ---: |
| dded | 1,466349 / 1,586849 / 2,383457 s | 1,000921 s | 207 |
| f123 | 1,529278 / 1,714826 / 4,824769 s | 1,000982 s | 224 |
| f192 | 1,397628 / 1,441222 / 3,174506 s | 1,000856 s | 201 |

Los mínimos observados permiten calcular tasas optimistas de 0,6820/0,6539/0,7155 por segundo **si todos los turnos fueran como el más corto observado**; no se publican como límites físicos universales ni como una extrapolación de producción. La cota estructural de 0,9091/s corresponde únicamente a los providers controlados de esta carga. La recurrencia de backlog y de espera preselection es reproducible en estos tres recibos, no necesariamente en sus timings exactos.

En f192 org3 recibe 129/173 = 74,57% de los turnos ordinarios, frente a 330/374 = 88,24% de los inputs ordinarios ofrecidos. Org1 y org2 completan sus 22 ordinarios y 11 safety cada una. Ambos planners procesan org3 (65/64) y ambos procesan orgs sanas. No hay evidencia de que org3 adquiera más de su N=1 ni de que oculte orgs sanas mediante una lista del mismo tenant. Estas proporciones describen la carga; no son una cuota de fairness contractual ni una medida causal suficiente por sí solas.

### SQL, commits y waits

| Intento | Persisted → eligible | Eligible → poll, s | Eligible → selection, s | Selection total / SQL | Claim completo | Commit de claim | Persisted → claimed_at | Persisted → commit_ack, s |
| --- | ---: | --- | --- | --- | ---: | ---: | ---: | --- |
| f192 W4 | 7,923980 s | [4,353488; 4,353975] | [4,353597; 4,354085] | 26,826 / 4,773 ms | 112,145 ms | 4,181 ms | 12,339541 s | [12,415977; 12,416465] |
| f192 W125 | 7,965408 s | [1,412435; 1,413095] | [1,412529; 1,413190] | 79,748 / 57,422 ms | 64,662 ms | 1,022 ms | 9,472716 s | [9,521702; 9,522362] |
| f192 W195 | 7,966577 s | [213,762338; 213,762944] | [213,762415; 213,763021] | 70,190 / 54,909 ms | 50,895 ms | 0,836 ms | 221,810544 s | [221,849728; 221,850334] |
| f123 W165 | 7,937639 s | [2,106263; 2,107146] | [2,106397; 2,107280] | 213,300 / 182,979 ms | 124,555 ms | 3,758 ms | 10,288615 s | [10,381127; 10,382010] |

Cada selección efectiva ejecuta **una consulta**: 390/377/412 evaluaciones en los tres recibos. No hay huecos entre queries dentro de un selector de una sola query. Selection también incluye construcción/materialización/overhead fuera del driver; claim completo **incluye commit** y no debe sumarse con la columna commit. `claimed_at` se toma antes del commit; en W195 el ACK llega [39,1837; 39,7895] ms después. No son la misma frontera.

En f192 se observaron 15 muestras Lock/transactionid sobre seis queries, repartidas entre ingest y procesamiento del turno; ninguna se asoció al selector o claim. En f123 fueron 30 muestras sobre diez queries, también fuera de selector/claim. El observador readonly y su muestreo no demuestran ausencia de locks breves ni duración exacta del wait. Saturación lógica B9C no es una espera PostgreSQL de lock: produce exclusión/miss y próximo poll. SQL rápido del HEAD actual tampoco explica el FAIL del HEAD anterior.

Los recibos originales conservan por-query durations, IDs, brackets, correlación y muestras: `query-timings.jsonl`, `per-phase.json`, `waits-summary.json` y `selector-polls.json` de cada directorio original. El análisis no altera ninguno. Los borradores `causal-analysis.json`/`attempt-summary.json` de esos directorios no sustituyen los recibos finales: se conoce la asociación errónea NULL=NULL de SQL sin scope a safety en el reporter preliminar. Los recibos finales la corrigen offline, con safety sin selector; no se reinterpreta SQL ordinario a partir de esos borradores.

### Niveles de evidencia de las causas

| Causa candidata | Nivel | Evidencia y alcance | ¿Violación actual? |
| --- | --- | --- | --- |
| Demanda org3 superior a servicio con N=1 | **CONFIRMED** | Dos LLM seriales + READ, cota 1,1 s, entrada 1/s; backlog en tres recibos. | Ninguna: el cupo es concurrencia, no una promesa de throughput para ruido. |
| Precedencia de conversaciones anteriores bajo ese cupo | **CONFIRMED** | Fuente: un candidato/org, last_activity/ID; 82 mensajes anteriores admitidos durante espera de W195. | Ninguna garantía individual READY o FIFO por mensaje violada. |
| Ocupación síncrona + batch=1 + pausa después de éxito | **CONFIRMED** | Gaps medidos, turns correlacionados y W165 sano incluido pero no procesado en el poll de planner-1. | Comportamiento de la topología definida; no todos los excesos son cuota ocupada. |
| Yield puede dejar capacidad libre | **CONFIRMED** para la regla; **LIKELY** como parte no cuantificada de los gaps libres de esta carga | Tests controlados con READY/cupo libre y ambos planners devolviendo cero; implementación readonly. No se captura la razón de exclusión por org en cada snapshot real. | La documentación limita el horizonte por observación, no la espera global. |
| Starvation indebida / monopolización noisy de ambos planners | **NOT_SUPPORTED** en estas cargas | Todas las orgs progresan, N=1, saneados no ocultos por LIMIT; pendientes censurados. | No se demuestra infracción SCALE ni fairness documentada. |
| Dos planners insuficientes como causa remediable por más workers | **NOT_SUPPORTED** como explicación única/corrección | Un planner adicional no añade cupo org3; existen tiempos con cupo libre y ambos fuera de turn. | No habilita cambiar la topología. |
| SQL_SELECTOR o LOCK_WAIT explican los minutos | **NOT_SUPPORTED** para estos recibos | Decenas de ms frente a 213 s; ningún wait selector/claim observado. SQL sí aporta margen relevante en W165. | No se demuestra SQL/lock defectuoso ni ausencia absoluta de waits breves. |
| Gating B9D/B8A, WRITE o budget B9B bloquea la cola | **NOT_SUPPORTED** | READ controlado, gates preservados, presupuesto solo tras claim, epochs válidos. | No evidencia de violación B9D/B8A/tenant isolation. |
| Otros forecasts sucesivos causan starvation global bajo otra carga | **POSSIBLE** | La regla no garantiza bound global; no se observó un abandono infinito aquí. | Sería necesario definir la garantía antes de denominarlo bug. |

B9C dispone de evidencia histórica N−1/N/N+1 (0/1/2), saturación sin pérdida, tres procesos disputando el último slot, noisy >batch con otro tenant, sender/safety independientes y LLM bloqueado: [b9c-acceptance-results.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/b9c-acceptance-results.json). Sus seis métricas críticas son cero en los tests aceptados; no son telemetría de producción. B9D conserva 75 pruebas nuevas aceptadas y 2384 IDs totales, gates cerrados y cero aprobaciones reales: [b9d-acceptance-results.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/b9d-acceptance-results.json).

Se inspeccionaron también los tests actuales: [N−1/N/N+1 y saturación](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/tests/test_b9c_concurrency.py:54), [otro planner con LLM bloqueado](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/tests/test_b9c_processes.py:161), [tres procesos/un slot](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/tests/test_b9c_processes.py:56), [READY yield con cupo libre](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/tests/test_e4_claim_yield.py:33), [dos planners yield, colisión/fallback](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/tests/test_e4_yield_processes.py:55) y [selección, batch y misses](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/tests/test_e4_selection.py:28). Esta tarea no los ejecuta de nuevo ni afirma una reaceptación completa del HEAD a partir de recibos de componentes anteriores. Los seis casos ON/OFF de cada diagnóstico aportan la verificación controlada reciente.

`SATURATED/DEFERRED` es una condición normal de B9C. No crea TurnWork nuevo, no consume attempts/budget ni pierde Message; el mensaje vuelve a competir al liberarse el cupo. Puede prolongarse sin bound de cola bajo sobrecarga persistente. No es una prueba de starvation por sí mismo. La lista vacía advisory puede evitar incluso que se emita un intento SATURATED, por lo que ausencia de ese evento no significa ausencia de saturación.

## 4. Contract assessment

| Contrato vigente | Garantía relevante | Garantía que no concede |
| --- | --- | --- |
| B3/C4/W1 v1, enmienda explícita del 30-09 | READY derivado de pendiente ordinario, sin asignar, deadline <= DB now; READY queda latched. Antes: debounce rolling 8 s, cap 25 s. | READY no es ownership, lease, contexto, presupuesto ni SLA de planificación. El debounce satisfecho no garantiza claim inmediato. |
| B9C | Un trabajo ordinario committed con PROCESSING, lease futuro y epoch vigente por organización, agregado entre procesos; no monopolizar todos los planners; progreso cross-tenant/sender/safety. | No hay timeout canónico de cola, cuota por período, semáforo global durable de dos, round-robin ni fairness fuerte. Los p95 son gates B9E, no TTL de descarte. |
| E4, comportamiento documentado y tests del selector | Excluir org ocupada antes de ranking/LIMIT; un candidato por org; recencia; fallback máximo tres; yield ante futura elegibilidad <=1 s de otra org idle menos recientemente atendida. | Un segundo es horizonte **por observación**, no máximo global de espera. Forecasts sucesivos pueden reiterar el yield. No hay reserva de planner ni promesa de bounded starvation. |
| B9D | Gates y aprobación exacta de tenant/capability antes de efectos, con producción cerrada. | No define orden de cola, deadline preclaim ni nueva capacidad. No reemplaza B9C/B9B/B8A ni convierte un componente en aceptación integral. |
| B8A | Revalidación de witness, tenant, autorización, TTL e idempotencia antes de efectos; resultados atómicos bajo fencing. | Una espera no renueva consentimiento ni habilita WRITE. El TTL de operaciones no es un timeout de esta cola READY. |

Fuentes: [B9C, respuestas 3–14 y lifecycle](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/contrato-concurrencia-b9c.md:33), [ADR B9C](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/decisions/2026-09-27-b9c-turnwork-concurrency.md), [READY v1](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/contrato-elegibilidad-preclaim-b3-c4-w1-v1.md:26), [límite explícito del yield](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/diagnostico-e4-eligible-claim-2026-09-30.md:254), [B9D](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/contrato-beta-release-b9d.md), [ADR B9D](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/decisions/2026-09-28-b9d-beta-release-gates.md) y [B8A](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/contrato-execution-guard-b8amd:13).

**Dictamen: `CURRENT_CONTRACT → NO_VIOLATION`.** No se demostró una violación de B9C, B9D, B8A, tenant isolation, fairness documentada o bounded yield. Este dictamen se limita a la evidencia existente analizada; no afirma cumplimiento universal bajo cualquier carga.

El backlog y las esperas preclaim son compatibles con la limitación de capacidad y las reglas vigentes. No se demostró starvation infinita ni monopolización contractual indebida. El contrato actual no establece un SLA global de tiempo máximo desde READY hasta claim.

## 5. Historical PROFILE/B9E separation

| Aspecto | PROFILE-BETA-1 / B9E histórico | E4 diagnóstico posterior |
| --- | --- | --- |
| Runtime / baseline | `83ee3b24c84b170e22e401cb09a34da5320ae0a3` | `825db75df68bf076929fa787e77beefe96803350` |
| Evidencia | TurnWork 86; p95 persisted→claim = **10.015949 s** | Tres recibos DIAGNOSTIC_ONLY; selector posterior incluido en este HEAD |
| Estado | `B9E = FAIL`; `PROFILE-BETA-1 = FAIL` | `CAPACITY_LIMIT_CONFIRMED` |
| Causalidad | `ROOT_CAUSE_NOT_CONFIRMED` | Capacidad y scheduling preclaim de este runtime posterior |
| Transferencia entre versiones | No permitida | No explica causalmente el TurnWork 86 histórico |

**El TurnWork 86 histórico sigue `ROOT_CAUSE_NOT_CONFIRMED`.** Pertenece al runtime `83ee3b24c84b170e22e401cb09a34da5320ae0a3`; este análisis describe el HEAD instrumentado posterior, que incluye el selector de `38c4d45`. No se transfieren causalidad, recibos ni conclusiones entre versiones. Tampoco se modifica la evaluación posterior del 02-10 que reportó `PROFILE_BETA_1_PASS`.

La cifra histórica se conserva tal como aparece en el recibo de aceptación congelado; no se recalcula ni se reparte por fases. Fuente: [final.json histórico](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/final.json). El diagnóstico posterior no borra, reclasifica ni explica causalmente aquel FAIL. La evaluación posterior del 02-10 también permanece intacta.

## 6. Why no tuning is authorized

> No existe actualmente una corrección mínima justificable contra un contrato existente.

El cierre no autoriza aumentar workers, reducir polling, cambiar batch, modificar fairness, aumentar N, reescribir SQL, modificar índices ni eliminar límites por organización. Estas opciones pueden ser mejoras futuras, pero no son fixes demostrados de una violación contractual.

**No hay una corrección del runtime justificable contra un contrato existente en esta evidencia.** No se propone ni implementa un parche. La limitación estructural demostrada y la interacción esperada de cola/cadencia requieren separar objetivo de capacidad de garantías temporales antes de cualquier tuning. Se conserva `STOP_BEFORE_TUNING`.

| Alternativa | Por qué no se recomienda como respuesta automática |
| --- | --- |
| Aumentar workers | No cambia N=1 por org; no resuelve la cota de servicio org3. Falta un contrafactual que pruebe beneficio sano y descarte más contención/colisiones. |
| Reducir polling | La pausa contribuye y podría mejorar un margen concreto, pero no elimina demanda >servicio, batch ni prioridad. Los gaps no equivalen a ahorro contrafactual; parámetros del protocolo están congelados. |
| Modificar índices | El selector efectivo es una query de decenas de ms en el caso extremo. No existe evidencia que atribuya los minutos a su plan. |
| Reescribir SQL | Cambiaría decisiones/yield/ranking antes de probar una infracción. Un EXPLAIN independiente no prueba la causa histórica ni elimina la cota de servicio. |
| Eliminar el límite de organización | Viola explícitamente B9C y cambia aislamiento/concurrencia; necesita un contrato nuevo y pruebas de fencing, N+1, locks, presupuesto y recuperación. |
| Aumentar capacidad indiscriminadamente | Cambia varias variables y no distingue capacidad, cadencia o fairness; no establece qué SLA se quiere garantizar ni qué carga es sostenible. |

No se ha seleccionado candidato, por lo que no hay evaluación de un parche inventado ni rollback de deploy. En el resultado entregado B8A/B9B/B9C/B9D, losses/duplicates, tenant isolation, crash/restart, locks y budget permanecen sin cambios: la actividad es lectura y derivación offline. Los hashes lo comprueban. Un candidato futuro exigiría demostrar la regla contractual que viola, la cohorte/frontera afectada y pruebas del mismo escenario bajo barreras y los contratos preservados; no se autoriza esa fase desde este reporte.

## 7. Potential future contract gap

`POTENTIAL_PRODUCT_REQUIREMENT → FAIRNESS / BOUNDED_WAIT`

Si el producto exige un máximo global de espera desde READY o fairness/bounded starvation entre organizaciones, primero debe definir explícitamente ese contrato, en trabajo separado de E4. No se inventa un SLA ni se propone un valor de timeout. Esa decisión futura no se registra como un defecto demostrado ni como permiso de tuning.

No aparece una ambigüedad contractual que impida este análisis: los documentos dicen expresamente que no existe el SLA individual ni fairness fuerte. **Si se exige que toda organización READY, también la sobrecargada, tenga un máximo global de espera o estabilidad a 1 turno/s, falta definir ese nuevo contrato.** No se lo atribuye al contrato actual ni se introduce como corrección implícita.

## 8. Final state

| Campo | Estado final |
| --- | --- |
| E4 | `CLOSED` |
| E4_DECISION | `CAPACITY_LIMIT_CONFIRMED` |
| NEXT_ACTION | `STOP_BEFORE_TUNING` |
| B9E | `FAIL` |
| PROFILE-BETA-1 | `FAIL` |
| B9 | `IN_PROGRESS` |
| Producción | Cerrada |
| Clínicas activadas | **0** |
| Deploy | Ninguno |
| Threshold persisted→claim | **10 s, intacto** |
| Runtime / selector / SQL / índices | Sin cambios |
| Workers / polling / batch / leases / deadlines / N | Sin cambios |
| Safety / gates / budgets / WRITE | Sin cambios |
| Nuevos commits de código | Ninguno |

Los estados de producción cerrada y cero clínicas se conservan del expediente existente; no se realiza una consulta nueva a producción ni una activación. El cierre de E4 no aprueba B9E ni cambia B9 a COMPLETED.

## 9. Evidence integrity / cleanup

La verificación estrictamente necesaria de este cierre encontró:

- **1239 archivos protegidos** y los seis estados/hashes de cambios preexistentes sin deriva.
- **243 artefactos de los tres diagnósticos originales** y sus manifiestos intactos.
- Los **14 archivos del expediente de análisis** coincidían con su manifiesto anterior antes de editar los documentos de cierre.
- Los 12 journals de carga y 15 funcionales mantienen sus hashes; se conserva su validación de integridad previa, sin nuevas ejecuciones ni reconstrucción de intentos.
- HEAD y rama sin cambios; ningún commit nuevo de código.
- Puertos **35449, 35451 y 35453 cerrados**, y los tres directorios DATA ausentes. No se abre infraestructura temporal.

Solo se actualizan `report.md`, `closure.json`, `preclaim-analysis.json` y el manifiesto del propio análisis. Los restantes once artefactos analíticos conservan sus hashes anteriores. El nuevo manifiesto registra el SHA-256 del anterior para conservar la continuidad documental; no se reescribe ningún manifiesto diagnóstico original.

Las verificaciones y estados se registran en [closure.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/e4-preclaim-scheduling-2026-10-04/closure.json), campo `formal_e4_closure`. Los resultados causales previos permanecen en [preclaim-analysis.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/e4-preclaim-scheduling-2026-10-04/preclaim-analysis.json).

### Límites de evidencia conservados

Para cuantificar exactamente el yield dentro de los 94,7844987 s libres de W195 faltan, por cada SELECT real, los valores bajo su mismo snapshot de `org_busy`, `org_last_claim`, forecast menos-servido/próximo-deadline y razón de exclusión/rank/cutoff para cada organización. Los journals guardan la consulta y su lista materializada, pero no toda la evaluación de predicados excluidos. También faltan eventos explícitos sleep_start/end si se quiere separar el overhead de los gaps. **No se diseña ni ejecuta otra ronda automática de instrumentación/pruebas.** Esta carencia limita la repartición exacta del tiempo libre, no la cota de capacidad, los intervalos occupied/free ni el caso de batch demostrado.

Para confirmar la causa del FAIL histórico harían falta esas fronteras y la ocupación de ambos planners **en aquella ejecución del runtime anterior**. Los recibos del HEAD posterior no pueden suplirlas. Un timestamp estimado eligible→SQL o un log de segundos no constituye esa evidencia.

Se verifican hashes de las seis fuentes instrumentadas y de **1239 archivos protegidos del HEAD**, incluidos contratos y fuentes históricas protegidas, además de los tres manifiestos diagnósticos y los seis estados/hashes de cambios preexistentes. [input-integrity.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/e4-preclaim-scheduling-2026-10-04/input-integrity.json) conserva los hashes exactos. Los checks de cierre están en [closure.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/e4-preclaim-scheduling-2026-10-04/closure.json); la fuente estática adicional queda enumerada en [contract-evidence.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/e4-preclaim-scheduling-2026-10-04/contract-evidence.json).

No se abrió infraestructura temporal en este análisis. La limpieza de los tres PostgreSQL previos sigue acreditada por sus recibos; se comprueba nuevamente DATA ausente y puertos 35449/35451/35453 cerrados. No se toca producción ni se ejecuta `b9e_profile`/`e4_profile`.

**B9E histórico FAIL; PROFILE-BETA-1 histórico FAIL; B9 IN_PROGRESS.** Sin deploy, activación, cambio de threshold, runtime, selector, SQL, índices, workers, polling, leases, deadlines, safety, gates, WRITE o budgets. Baseline instrumentado exacto y HEAD final iguales. Ningún commit nuevo. Solo se crean los artefactos de este análisis; cambios y evidencias preexistentes quedan intactos.
