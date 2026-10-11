# Ejecución causal nueva — DIAGNOSTIC_ONLY

HEAD exclusivo: `825db75df68bf076929fa787e77beefe96803350`.
ID: `causal-f1922430c60348e8adce24196c02bf5a`.
Preparación iniciada el 04-10; los timestamps precisos de inicio/cierre de la
carga están en los recibos de esta ejecución. No se toma el formatter del log
operativo como reloj UTC ni como fuente de intervalos.

El adaptador `run.py` invoca el comando operativo existente, ingestión real
mediante webhook firmado y las fixtures existentes. No importa ni invoca
`b9e_profile` o `e4_profile`; no calcula gates. Las fuentes de esos runners se
leyeron únicamente para conservar la carga diagnóstica ya definida:

- Dos planners y un sender; batch 1 y pausa después de cada poll de 1 s.
- Tres organizaciones: dos a un inbound cada 10 s y una ruidosa a uno por s.
- Patrón original de safety en las sanas: serial múltiplo de tres; los
  ordinarios reutilizan conversación/identidad sintética como la fixture.
- LLM simulado: tool pública en la primera llamada y respuesta en la segunda,
  500 ms cada llamada. HTTP de dominio 100 ms y Meta 200 ms. Destinos externos
  rechazados. No proveedor real, WRITE productivo ni grants productivos.
- 30 s de calentamiento, 300 s de carga y 20 s de drenaje. La investigación
  conserva todos los intentos registrados, sin convertir la ventana en gate.
- No overrides de selector, query, índices, lease, budget, workers o polling.

`infra.py` comprueba hashes antes/después y utiliza un cluster nuevo en puerto
35453. PostgreSQL tiene fsync y synchronous_commit on. Cada planner y sender
usa su propia captura; ingress comienza su captura antes del primer webhook.
El observador del módulo ya instrumentado se lanza en otro proceso, con
conexión autocommit readonly y muestra de 20 ms; observa ingress y ambos
planners. Su tiempo y su actividad no se atribuyen al SQL de los workers.

Antes de la carga se ejecuta comparación funcional de seis escenarios del
mismo HEAD: new/retry/reclaim/busy/not-due, READY join y reconexión, rollback,
concurrencia con locks reales, waits controlados y LLM bloqueado. Los run IDs
de sus capturas se prefijan con el nuevo UUID, incluidos los hijos de proceso.
No se reutilizan journals ni recibos anteriores. Se normalizan únicamente
relojes/IDs de savepoint según la prueba existente; autoridad, presupuesto,
membership, attempts y resultado se comparan por separado.

La comparación es OFF/ON bajo estado y barreras controlados. No afirma que
dos cargas temporales concurrentes en momentos distintos tengan idéntico
calendario o ganador. Una discrepancia funcional detectada invalida la
ejecución; ninguna pérdida/integridad fallida permite interpretar causalidad.

El análisis usa timestamps durables y brackets DB↔monotónico de consultas de
reloj que ya ejecuta el runtime. `eligible→poll` significa el poll que contiene
ese intento, no un instante hipotético en que despertó el scheduler.
`eligible→selection_start` y `claimed_at→commit_ack` conservan límites de
calibración. Los huecos entre consultas usan fin/inicio de execute. La selección
es compartida por candidatos y no se cobra como exclusiva de cada inbound.
La duración SQL de cliente incluye servidor, espera, red y driver; una muestra
de lock confirma observación, sin inventar su duración exacta.

El claim ordinario retorna su resultado después del COMMIT; safety retorna
desde la primitiva dentro de la transacción de ingreso. El intervalo firmado
resultado→ACK y su orden se conservan, sin convertir uno en una fase posterior
que no existe. Los inbounds aún pendientes carecen de claimed_at: se muestran
como backlog, sin duración final fabricada.

Los scripts y artefactos de esta carpeta son evaluativos. Las fuentes protegidas
y las dos evaluaciones históricas quedan intactas. Estas mediciones jamás se
imputan al TurnWork 86 del runtime anterior. La investigación termina tras
clasificación y limpieza; no implementa ni propone tuning en esta ejecución.

Esta es otra ejecución completamente nueva, autorizada el 04-10. La carpeta diagnóstica anterior se protege por sus hashes y no aporta journals/recibos a esta reconstrucción. Las clasificaciones se derivan de los nuevos datos, sin exigir los conteos ni el resultado anterior.

Esta tercera corrida tiene identidad propia. Las dos corridas anteriores se verifican y protegen por hash, sin importar sus journals a esta reconstrucción. El objetivo histórico conserva ROOT_CAUSE_NOT_CONFIRMED: el HEAD actual no es el runtime histórico. No se propone una modificación del runtime.
