# E4 — instrumentación causal optativa

Baseline autorizado: `66702168439b9841a2c988238638a42e6aaee43d`, rama
`codex/e4-capacity-scheduling`. Fecha del encargo: 2026-10-03.
Estado: **INSTRUMENTATION_READY / ROOT_CAUSE_INVESTIGATION_READY**.
Esta carpeta no contiene una aceptación PROFILE ni una aprobación B9E.

## Fronteras de evidencia

1. El runtime `83ee3b24c84b170e22e401cb09a34da5320ae0a3` produjo el FAIL histórico.
   TurnWork 86, inbound 275, Conversation 14, Organization 2, planner-1,
   backend 34424: persisted→claimed_at = 10.015949 s. La auditoría aportada por
   el encargo identifica persisted→eligible = 7.926828 s y estima
   eligible→inicio SELECT ≈ 1.974774 s. Esta última cifra no es una fase medida.
   El recibo SQL conserva 80.767 ms a `2026-10-01 07:27:15.398 UTC`, PID 34424;
   no aporta el vínculo inequívoco de todas las consultas con ese claim.
   Los logs CREATED/CLAIMED tienen resolución de segundos. El EXPLAIN de
   cierre con 9,912 buffers no constituye un plan causal del TurnWork 86.
   No se completan los timestamps históricos ausentes: ROOT_CAUSE_NOT_CONFIRMED.
2. El HEAD autorizado incluye el selector de `38c4d45` y el recibo posterior
   del 02-10 `PROFILE_BETA_1_PASS`. Ambos se preservan. Ese PASS no demuestra
   que el selector sea la solución causal del fallo anterior.
3. Los journals de esta carpeta proceden exclusivamente de pruebas sintéticas
   de instrumentación del runtime actual. No explican TurnWork 86, no ejecutan
   PROFILE-BETA-1 y no reabren B9E. B9E histórico=FAIL, PROFILE histórico=FAIL,
   B9=IN_PROGRESS, threshold=10 s. No activación, grants ni deploy.

## Diseño y puntos de observación

`claim_diagnostics.capture(path, run_id=..., worker=...)` activa el observador
en una conexión Django y contexto de ejecución. Se entra fuera de una
transacción y se sale después de su cierre. Cada proceso/hilo escribe su
propio archivo, abierto con creación exclusiva. El runtime normal no activa
captura por configuración, variable de entorno o importación.

Los tres archivos existentes modificados son `services.py`, `worker.py` y
`durable.py`. Solo contienen hooks; la función del selector es idéntica al
baseline. No se modifican índices, SQL del claim/selector, condiciones,
orden de locks, número de workers, polling, límites, presupuesto, leases,
deadlines, gates, safety o WRITE. La lista de candidatos se evalúa una vez en
el mismo lugar. La instrumentación no hace consultas nuevas en el camino
operativo. El observador de waits utiliza otra conexión readonly.

| Eventos | Frontera |
| --- | --- |
| `ingest_start/end/error` | Ingestión real, incluyendo dedup/errores |
| `message_persisted` | INSERT retornado y campos temporales de Message; aún puede revertirse |
| `deadline_set` | UPDATE existente del conjunto ordinario, deadline y cantidad afectada |
| `db_clock` | Valor real de `statement_timestamp()` y bracket monotónico de su consulta |
| `poll_start/end/error` | Invocación del poll operativo, sin cambiar su pausa |
| `selection_start/result/end/error` | Construcción y evaluación efectiva del queryset, IDs resultantes |
| `claim_start/end/error`, `claim_locked_start/end/error` | Intento de claim normal o primitiva safety |
| `existing_work` | Estado/attempts/deadline/lease previo de un retry o reclaim |
| `membership_candidate` | Miembros ya leídos por el claim, `created_at`, `available_at`, elegibilidad efectiva |
| `claim_bound` | Membresía y lease asignados provisionalmente, timestamp DB del claim |
| `claim_result` | Resultado de la función, expresamente separado del commit |
| `sql_start/end` | Todas las llamadas Django execute/executemany en la captura, incluidas las fallidas |
| `transaction_begin`, `commit_start/end`, `rollback_start/end` | Modo transaccional y llamada real al driver; error preservado |
| `savepoint/release/rollback`, con `_end` | Intento y ACK/error del driver, asociados a los savepoints activos de cada claim |
| `connection_open_start/end` | Apertura/reconexión, separada del SQL de aplicación |
| `turn_start/end/error` | Entrada y salida de procesamiento para identificar ocupación fuera del claim |
| `capture_start/end` | Integridad, contador de consultas, fallos del sink y transacción pendiente |

Las consultas de inicialización internas del driver y su BEGIN implícito no
son llamadas a `execute_wrapper`: su tiempo queda en apertura/primera consulta.
COMMIT/ROLLBACK se cuentan como fronteras propias, no se suman al query count
de execute/executemany. El fetch/materializado queda dentro de la selección;
la duración de execute no se presenta como todo el tiempo del queryset.
Un marcador de rollback a savepoint no confirma su éxito: el reconstructor
exige ACK sin error. En journals de desarrollo anteriores usa el ACK de la
consulta ROLLBACK correlacionada; el marcador aislado no reemplaza un COMMIT.

## Correlación y tiempo

Todo evento lleva versión, run_id, session_id aleatorio, secuencia, PID OS,
hilo, conexión lógica y PID PostgreSQL cuando existe. Poll, selección, span,
intento y transacción tienen IDs distintos y enlaces parentales. El intento
nace antes de conocer TurnWork; `claim_bound` lo enlaza con work/org/conv,
epoch, attempts y SHA-256 del UUID de lease. No se registra el token completo.
El SQL del selector pertenece al conjunto de candidatos; no se imputa como
consulta exclusiva de cada uno. Un miss conserva su intento aunque no cree work.

Los intervalos locales utilizan `perf_counter_ns()`. `time_ns()` conserva UTC
sin depender del formatter de logs. Ambos son lecturas de reloj con representación
en nanosegundos, no promesa de exactitud física de un nanosegundo.
Los campos persistidos y el reloj del claim conservan microsegundos PostgreSQL.
No se reescribe `created_at` ni se lo presenta como instante exacto de commit.

La elegibilidad individual es `max(created_at, available_at)`, o `created_at`
para NULL, conforme al contrato W1. Su timestamp se registra al leer el
miembro, no como si un callback hubiera ocurrido en el instante de vencimiento.
READY continúa siendo derivado. Retry y reclaim llevan además su fuente de
elegibilidad propia (`next_attempt_at` o `lease_expires_at`).

El reporte conserva:

- persisted→eligible por miembro, con los campos observados;
- eligible→poll y eligible→selection como **intervalos acotados** mediante la
  consulta existente de reloj DB, sin restar timestamps de logs redondeados;
- inicio/fin de selección, tiempo por query, huecos entre queries y query count;
- selection_end→claim_start, `claimed_at`, commit ack y resultado final;
- persisted→claimed_at y persisted→commit_ack, diferenciados;
- ingestión/commit original si su journal forma parte de la captura; en otro
  caso `NOT_OBSERVED`, nunca un timestamp fabricado;
- membresía previa para reclaim solo si hay un claim committed en los journals
  de la misma ejecución; si no, `NOT_OBSERVED`.

La conversión DB↔monotónico presupone ausencia de un salto de reloj durante el
intento. Los extremos del bracket conservan la incertidumbre de red/driver;
no se oculta una mala calibración. Entre hosts no se comparan contadores
monotónicos: se necesitan calibraciones independientes. Los percentiles
marginales no se suman y este reporte no calcula un gate de aceptación.

## Waits y bloqueadores

`claim_diagnostic_waits.sample()` consulta únicamente timestamp, PID, inicio
del backend/transacción/query, estado, wait_event_type, wait_event y PIDs
bloqueadores en `pg_stat_activity`. No lee `query`, parámetros, usuarios,
application_name ni lock keys. Usa una conexión independiente autocommit y
readonly; nunca los locks o la transacción del worker.

Las muestras se asocian por run/session/conexión/PID e intersección con el
intervalo SQL. Una muestra que cruza varias consultas queda ambigua. Una
duración SQL incluye espera, ejecución, red y driver: no es lock wait puro.
Muestras vacías no prueban ausencia de esperas; tampoco dos muestras iguales
prueban espera continua entre ellas. `exact_lock_wait_seconds` permanece null.
SKIP LOCKED se registra como propiedad del SQL, sin convertir un miss en una
espera. La cadencia del observador no modifica la cadencia del worker.

## Activación y siguiente diagnóstico

No se ejecutó la siguiente carga. Para un encargo diagnóstico posterior:

1. Crear una ejecución nueva del HEAD instrumentado, con datos sintéticos y
   PostgreSQL aislado; conservar versión y hashes de fuentes. No reutilizar
   IDs de ejecución, recibos o directorios del PROFILE histórico.
2. Envolver el ingreso y cada planner con `capture`; en ingreso multihilo,
   una captura por contexto/conexión que empiece antes de ingestión. Conservar
   los mismos límites, workers, polling y provider de la carga a investigar.
   No cambiar la metodología congelada ni invocar su runner como aceptación.

```python
from apps.agent.claim_diagnostics import capture

with capture("/diagnostic/new-run/planner-1.jsonl",
             run_id="e4-causal-new-run", worker="planner-1"):
    existing_worker_entrypoint()  # La entrada existente de ese proceso.
```

3. Desde otro proceso del mismo host, configurar PGHOST/PGPORT/PGDATABASE/PGUSER
   para la DB diagnóstica (credenciales fuera de recibos), y ejecutar:

```text
rtk proxy python -m apps.agent.claim_diagnostic_waits --run-id e4-causal-new-run --output waits.jsonl --stop observer.stop --interval 0.02 ingress.jsonl planner-1.jsonl planner-2.jsonl
```

4. Detener la carga de forma controlada, cerrar capturas y después crear el
   archivo `observer.stop`. Conservar también `waits.summary.json`. Reconstruir:

```text
rtk proxy python -m apps.agent.claim_diagnostic_report ingress.jsonl planner-1.jsonl planner-2.jsonl --same-host-waits waits.jsonl --output causal-report.json
```

5. Examinar cada intento y su calibración antes de sacar conclusiones. La
   carga nueva solo puede explicar el comportamiento del runtime actual.
   Un diagnóstico con distinta cardinalidad no es reproducción del TurnWork 86.

## Integridad, privacidad y límites operativos

El journal escribe y hace flush por evento; no espera a que termine un LLM.
La secuencia, pares de SQL/spans, contador final y cierre transaccional se
validan offline. Fallos de escritura no alteran ni sustituyen la excepción
operativa, pero invalidan la evidencia. Un crash, kill, disco lleno, write
parcial o footer ausente produce INCOMPLETE. No se promete durabilidad de
fsync por evento ni captura completa después de una pérdida de alimentación.
Se usan archivos distintos por proceso/hilo, sin un lock Python global.

La captura optativa tiene coste de reloj/serialización/flush y puede perturbar
latencias; no se afirma coste cero ni equivalencia temporal ON/OFF. La
equivalencia exigida es funcional: SQL, decisiones y estado durable. Las pruebas
de carga simultáneas de esta carpeta no son mediciones de capacidad/p95.
Los tests que adelantan `available_at` o un reloj lo hacen solo en fixtures.

No se serializan texto de mensajes, prompts, respuestas, teléfonos, SQL,
parámetros ni mensajes de excepción. Solo clases de error y metadatos técnicos
cerrados. IDs son campos de journal, no labels de métricas productivas.
La configuración de journaling debe usar run_id/worker técnicos.

## Verificación

`verify.py` prepara un cluster propio en puerto 35447 con fsync y
synchronous_commit on y clona una base por ejecución. Ejecuta pruebas mediante
el runner existente de IDs, sin ejecutar `b9e_profile`/`e4_profile`.
`source_integrity.py` compara fuentes protegidas y ambos directorios PROFILE
contra el baseline y compara el AST completo del selector.

Incidentes de desarrollo preservados: `targeted-1` detectó un error del
reconstructor que incluía SQL posterior en selección y diferencias de nombres
de savepoint generados por Django en el comparador; `targeted-2` se inició
antes de cerrar la anterior sobre la misma DB. Se detuvieron ambas, no son
evidencia PASS, y las ejecuciones posteriores usan clones diferentes. No se
relajó ninguna aserción de negocio: se normalizan solo IDs de savepoint y
timestamps de parámetros dependientes del reloj; lease, epoch, attempts,
membership, presupuesto y resultado se comparan por separado exactamente.

La interrupción del host dejó las tres regresiones sin un cierre satisfactorio:
`regression-durable` registró timeouts de conexión en dos casos; `regression-e4`
y `regression-b9` quedaron incompletas. El cluster estaba detenido al retomar.
Se recuperó el mismo cluster, manteniendo fsync/synchronous_commit on y sus
archivos. `resume.log` conserva el timeout del cliente pg_ctl mientras PostgreSQL
continuaba su recuperación; `resumed-environment.json` confirma su identidad.
No se atribuye esa interrupción al runtime ni se convierte una suite incompleta
en PASS. Se conservaron 120 recibos por ID satisfactorios y se ejecutaron los
75 IDs restantes en otro clon: `recovery-regression`, 75/75, sin skips/xfail.

`equivalence-process-final` conserva un intento de desarrollo fallido: la
aserción confundía `in_atomic_block` de Django con el estado del driver al
entrar en COMMIT, y el helper de escritura estaba mal colocado. Se corrigieron
solo las pruebas. `equivalence-final` vuelve a ejecutar esos tres casos más
rollback, con resultado 4/4. No se reutiliza el intento fallido como PASS.

| Evidencia satisfactoria | Alcance |
| --- | --- |
| `targeted-3` — 14/14 | Fases, privacidad, safety, errores, clocks, fencing y tres escenarios de procesos |
| `equivalence-2` — 2/2 | SQL/estado exactos en new/retry/reclaim/busy/not-due, presupuesto no cero, reconexión y READY join |
| `equivalence-final` — 4/4 | OFF/ON con locks reales, un solo ganador, LLM bloqueado, otra organización progresando y rollback |
| `savepoint-final` — 6/6 | Fuentes finales: SQL/estado OFF/ON, rollback, error SQL, error COMMIT, on_commit y rollback a savepoint fallido |
| `reporting-unit.log` — 5/5 | Reconstrucción final offline, brackets temporales, waits ambiguos, runs distintos y ACK de rollback |
| Regresiones — 195 IDs únicos satisfactorios | 30 E4/W1, 44 durable/WRITE, 121 B9B/B9C/B9D; 120 previos a interrupción + 75 recuperados |
| `checks-1` | Django check, migraciones pendientes y drift de modelos: exit 0 |
| `source-integrity.json` | 436 archivos protegidos idénticos; selector AST idéntico; los tres AST funcionales idénticos al retirar hooks explícitos |

Son **216 pruebas distintas**: 195 de regresión y 21 diagnósticas. Es evidencia
compuesta por ID y por versión de fuentes, no una ejecución única de 216 tests
sobre un commit final. Cada runner conserva `results.sources.json` e inventario.
`savepoint-final.results.sources.json` coincide con los seis archivos runtime
finales; los tres hooks existentes no cambiaron durante esta verificación.
`closure.json` agrega recibos, hashes finales, pruebas y limpieza del cluster.
Los `.log` conservan los bytes originales de stdout/stderr de Windows; el
atributo Git local evita normalizar sus CR/LF y los presenta como artefactos.
`cleanup.json` confirma cero clientes, cero locks pendientes y puerto cerrado;
se eliminaron únicamente las bases de este cluster y se conservaron sus archivos.

La prueba funcional compara decisiones/candidatos, secuencia y cantidad de SQL,
formas de locks y comportamiento de bloqueadores, membresía, attempts, leases,
epoch/fencing, resultado del claim y contadores B9B. New/retry/reclaim usan el
mismo estado y reloj controlado, con rollback entre OFF/ON; se comparan también
parámetros salvo timestamps generados y nombres de savepoint, cuyos campos de
autoridad se comprueban por separado. Procesos usan barreras OS y espera real
observada antes de liberar el bloqueo. Sus recibos contienen hashes de las
formas SQL, nunca SQL crudo o parámetros. No se exige que las latencias sean
iguales ni que una carrera sin controlar el orden tenga el mismo ganador.

`evidence-validation.json` reconstruye nueve grupos preservados (2.019 eventos).
Siete grupos proceden de ejecuciones satisfactorias (1.498 eventos); los dos
restantes pertenecen al intento de desarrollo fallido y están identificados
como tales. Cero fallos de escritura y cero patrones privados en los journals.
El reporte de waits conserva observaciones y límites `[0, duración SQL]`, nunca
una duración exacta inventada. Un error de rollback a savepoint conserva su
excepción y no reclasifica un COMMIT real; las pruebas final/offline lo cubren.

## Archivos del encargo

- Hooks existentes: `backend/apps/agent/{services,worker,durable}.py`.
- Nuevos módulos: `claim_diagnostics.py`, `claim_diagnostic_report.py`,
  `claim_diagnostic_waits.py` en `backend/apps/agent/`.
- Pruebas: `test_claim_diagnostics.py`, `test_claim_diagnostic_processes.py`,
  `test_claim_diagnostic_reporting.py`, `claim_diagnostic_process.py`,
  `claim_diagnostic_evidence.py` en `backend/apps/agent/tests/`.
- Esta carpeta: protocolo, scripts de verificación/recuperación/cierre, hashes,
  logs, recibos por ID y journals sintéticos. El commit se identifica en Git.

Cambios preexistentes conservados fuera del commit: las eliminaciones de
`DEPLOY_VPS_PLAN.md` y `DEPLOY_VPS_STATUS.md`, la modificación de `skills-lock.json`
y los tres documentos no rastreados de auditoría/discrepancia/bounded-yield.

La siguiente ejecución propuesta es la descrita en “Activación y siguiente
diagnóstico”: captura nueva de ingreso y planners del runtime instrumentado,
con observador readonly separado y reconstrucción por intento. Su clasificación
será DIAGNOSTIC_ONLY; sus conclusiones solo corresponderán a ese runtime y carga.
