# Experimento final E4 — escalabilidad SQL bounded-yield

**Decisión: `SQL_SCALING_PROBLEM_CONFIRMED`; `ROOT_CAUSE_CONFIRMED`.**
El coste del `EXISTS` forecast correlacionado crece materialmente con las
conversaciones evaluadas y con los mensajes pendientes que inspecciona en
cada repetición. Esta decisión es independiente del FAIL formal de
PROFILE-BETA-1 por 15,949 ms. No se implementó ninguna optimización.

## Estado, baseline y entorno

- Baseline HEAD al medir: `6e59f6c05514ad6eca0985796e538de4fd749560`.
  Runtime E4: `83ee3b24c84b170e22e401cb09a34da5320ae0a3`.
- Python aislado **resuelto**: 3.13.2 con Django 6.0.5 y psycopg 3.3.4.
  Invocación directa, importaciones y subproceso Python funcionaron. El
  `Access denied` histórico no se reprodujo: su causa exacta no puede
  demostrarse con la evidencia conservada. `icacls` no mostró una denegación
  en el ejecutable. No se cambiaron ACL ni permisos globales.
- Git: no había `index.lock` ni proceso Git activo en el preflight; `git
  status` funcionó. No se borró un lock.
- PostgreSQL 16.15 real, local en `127.0.0.1`, con `fsync=on` y
  `synchronous_commit=on`. Windows 11, Intel64 Family 6 Model 142, 8 CPU
  lógicos. Se migró una plantilla aislada y se clonó una base por punto.
  No se usaron credenciales ni datos productivos.
- Hubo una incidencia propia del lanzador `rtk proxy pg_ctl start`: el
  servidor quedó listo pero el wrapper no retornó. Se detuvo y eliminó ese
  primer clúster. Los siguientes arrancaron PostgreSQL directamente, como
  el observador histórico. Otra incidencia fue un `external_id` sintético
  mayor de 32 caracteres antes de B=1000; se acortó el fixture y se ejecutó
  solo ese punto faltante. Los recibos anteriores se conservaron.

## Método y SQL real

Se ejecutó **sin modificarlo** el queryset
`apps.agent.worker._pending_conversation_candidates(now=clock)` sobre cada
base. El SQL compilado exacto con parámetros sintéticos está en
[`compiled-sql.txt`](compiled-sql.txt). Incluye `LEFT OUTER JOIN` con
`agent_turnwork`, `ROW_NUMBER() OVER (PARTITION BY organization_id ORDER BY
last_activity_at,id)`, orden final por último claim (NULL primero), actividad
e id, y `LIMIT 3`. El filtro safety permite `pk IN (pending_safety)`; también
se exime a organizaciones sin claim previo. Se excluye trabajo PROCESSING
vigente mediante `NOT EXISTS`. El forecast es otro `NOT EXISTS` de mensajes
inbound pending sin TurnWork, disponibles en `(clock, clock+1 s]`, de otra
organización, no safety, no busy y con último claim anterior al exterior.
Las subconsultas de último claim están correlacionadas.

`connection.execute_wrapper` rodeó una evaluación `list(queryset)` en cada
fixture: **1 sentencia SQL por invocación, 0 N+1 de Django**. Los `SubPlan`
repetidos dentro de PostgreSQL pertenecen a esa misma sentencia. El conteo
está en [`query-count.json`](query-count.json).

En A/B se fijaron 3 organizaciones, una historia de claim completado por
organización, estados de conversación activos, 0 PROCESSING y 0 safety.
El 80 % de los mensajes pendientes estaba listo y el 20 % disponible en
los siguientes 0,5 s. En A había 8 conversaciones fijas; en B había 2.000
mensajes pendientes fijos. Ningún punto cambió ambas dimensiones a la vez.
El escenario mixto corregido, aparte de A/B, contiene 354 conversaciones:
una organización noisy con 229 pendientes y dos healthy con uno listo cada
una; una señal safety está entre los dos healthy. Los cuerpos son vacíos.

Se hizo `ANALYZE` después de poblar cada clon. Por punto se guardó el primer
`EXPLAIN`, luego 5 warm-ups y 30 mediciones de `EXPLAIN (ANALYZE, BUFFERS,
VERBOSE, FORMAT JSON)` del SQL compilado. Los percentiles usan rango más
cercano; con n=30, p99 coincide con el máximo. El tiempo es **Execution
Time del servidor**, sin RTT ni evaluación Python. El primer plan es solo
*cold-ish*: la inserción y `ANALYZE` ya pueden calentar caché. No se vació
la caché del sistema. Las distribuciones warm están en las matrices y cada
plan íntegro en `explain/`.
Para repetir desde cero, `SQL_SCALING_OUT` debe apuntar a un directorio
nuevo y vacío al ejecutar `benchmark.py` y `run_mixed_ready.py`. Así los
recibos de esta ejecución permanecen inmutables.

## Matriz A — Messages variables, 8 Conversations fijas

Todos los tiempos son milisegundos; n=30 por fila.

| Pending Messages | p50 | p75 | p90 | p95 | p99 | max | Forecast loops | Shared hit raíz |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 0,780 | 0,787 | 0,805 | 0,829 | 1,101 | 1,101 | 11 | 71 |
| 50 | 1,257 | 1,274 | 1,301 | 1,303 | 1,339 | 1,339 | 11 | 112 |
| 100 | 1,655 | 1,692 | 1,744 | 1,893 | 2,733 | 2,733 | 11 | 166 |
| 250 | 3,189 | 3,261 | 3,309 | 3,325 | 3,708 | 3,708 | 11 | 350 |
| 500 | 6,905 | 7,304 | 10,488 | 10,725 | 11,929 | 11,929 | 11 | 656 |
| 1.000 | 11,014 | 11,287 | 13,178 | 13,334 | 13,761 | 13,761 | 11 | 1.276 |
| 2.000 | 35,326 | 39,713 | 41,828 | 43,488 | 44,224 | 44,224 | 11 | 2.495 |

Con los loops fijos, crecen el trabajo de cada scan y los hits. El tramo
250→2.000 mensajes elevó el p50 11,1 veces para 8 veces más mensajes:
aproximadamente lineal, con cambios de plan/caché y ruido. La serie completa
está en [`matrix-messages.json`](matrix-messages.json).

## Matriz B — Conversations variables, 2.000 Messages fijos

Tres organizaciones y 1.600 ready/400 upcoming en todas las filas; n=30.

| Conversations | p50 | p75 | p90 | p95 | p99 | max | Forecast loops | Shared hit raíz |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 24,299 | 24,606 | 27,433 | 27,515 | 28,405 | 28,405 | 13 | 2.944 |
| 25 | 59,089 | 72,544 | 90,838 | 90,887 | 91,954 | 91,954 | 28 | 6.249 |
| 50 | 155,175 | 176,343 | 217,657 | 224,300 | 259,257 | 259,257 | 53 | 11.556 |
| 100 | 346,021 | 375,565 | 390,017 | 398,106 | 418,650 | 418,650 | 103 | 22.389 |
| 250 | 798,228 | 902,934 | 948,389 | 952,656 | 977,692 | 977,692 | 253 | 54.856 |
| 500 | 2.331,945 | 2.448,846 | 2.550,098 | 2.679,216 | 2.697,774 | 2.697,774 | 503 | 108.778 |
| 1.000 | 4.889,216 | 5.118,913 | 5.286,007 | 5.336,076 | 5.408,387 | 5.408,387 | 1.003 | 215.477 |

Los loops = conversaciones medidas + 3 conversaciones de historia de claim
constantes. Por tanto el valor histórico 354 se explica por la cardinalidad
de conversaciones exteriores evaluadas, **no** por tres Organizations ni por
una sentencia Django por Message. El p50 creció 201 veces entre 10 y 1.000
conversaciones para 100 veces más conversaciones: aproximadamente lineal a
moderadamente superlineal en este intervalo, claramente patológico en
tiempo absoluto a 500–1.000. La serie está en
[`matrix-conversations.json`](matrix-conversations.json). B=10/25 se
recuperaron de la salida de la primera ejecución tras una interrupción; sus
planes se conservaron. No se reejecutaron para escoger valores.

## Escenario healthy + noisy y EXPLAIN

El escenario corregido, separado de A/B, dio p50/p75/p90/p95/p99/max
**97,990 / 107,377 / 123,714 / 126,298 / 129,349 / 129,349 ms** (n=30).
Su plan representativo dio planning 8,448 ms, execution 101,214 ms, 356
loops del scan forecast, 2.415 shared hits y 0 shared reads. Está en
[`matrix-mixed-ready.json`](matrix-mixed-ready.json). El primer escenario
mixto, donde los healthy solo tenían trabajo upcoming, quedó como exploratorio
en `matrix-mixed.json` y no fundamenta la decisión.

| Plan representativo | Planning ms | Execution ms | Scan Message loops | Removed/filter por loop | Shared hit scan | Shared hit raíz | Shared read/temp | Sort |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| A 10 | 2,728 | 0,762 | 11 | 12 | 44 | 71 | 0/0 | quicksort 25 kB |
| A 2.000 | 2,896 | 25,267 | 11 | 1.748 | 2.398 | 2.495 | 0/0 | quicksort 25 kB |
| B 10 | 2,729 | 24,036 | 13 | 1.757 | 2.872 | 2.944 | 0/0 | quicksort 25 kB |
| B 100 | 5,833 | 364,579 | 103 | 1.739 | 22.192 | 22.389 | 0/0 | quicksort 25 kB |
| B 500 | 5,767 | 2.434,466 | 503 | 1.737 | 108.158 | 108.778 | 0/0 | quicksort 25 kB |
| B 1.000 | 5,235 | 4.822,758 | 1.003 | 1.737 | 214.332 | 215.477 | 0/0 | quicksort 25 kB |
| Mixto corregido | 8,448 | 101,214 | 356 | 217 | 2.028 | 2.415 | 0/0 | quicksort 25 kB |

El nodo dominante en estos datos sintéticos es `Seq Scan` de
`channels_message` dentro del forecast `EXISTS`, bajo un `Nested Loop`.
En B=1.000, el scan tarda 4,756 ms por loop, aproximadamente 4.770 ms
acumulados de 4.823 ms totales. El plan histórico formal eligió `Bitmap Heap
Scan`/`Bitmap Index Scan` para Message y lo repitió 354 veces: cambia el
método físico, persiste la repetición causal. `WindowAgg` se ejecuta una vez;
los sorts finales son pequeños. No hubo escrituras/lecturas temporales ni
`Heap Fetches` reportados para el scan dominante. Los `Rows Removed by
Filter` de la tabla son el promedio por loop que informa PostgreSQL.

Todos los planes representativos warm registraron **shared read=0**; la
degradación observada corresponde a trabajo repetido de CPU/caché de buffers,
no a nuevas lecturas físicas en esas muestras. Los archivos
[`plan-metrics.json`](plan-metrics.json) y [`plan-nodes.json`](plan-nodes.json)
recogen estos campos por punto. No se cambiaron índices, planner ni
configuración del producto.

## Relación histórica y gate

PROFILE-BETA-1 formal permanece **FAIL**: p50/p95/p99/max de
97,497/291,922/422,705/622,632 ms; su plan del selector fue 127,583 ms y
el `Bitmap Heap Scan` de Message tuvo 354 loops y 9.912 hits. El mixto
corregido se acerca al p50 y al tiempo del plan, pero no reproduce p95/p99/max:
la concurrencia, el dataset y las condiciones del worker formal son distintos.
La matriz controlada explica la dirección y el mecanismo, no esos percentiles
exactos ni una extrapolación de producción.

**Sí corregiríamos la query aunque PROFILE no existiera.** Un único SELECT
de polling tarda p50 ~2,3 s a 500 conversaciones y ~4,9 s a 1.000 con 2.000
pendientes en tres organizaciones. La combinación es una acumulación
posible de backlog noisy; no se afirma que represente la distribución exacta
de una clínica real. El riesgo es retrasar repetidamente el avance de otras
clínicas. Este juicio se mantiene si el threshold formal fuese 12 o 15 s.
La matriz C de Organizations no se ejecutó: A/B ya aislaron ambas dimensiones
y explicaron los loops.

La siguiente tarea, **separada de este encargo**, puede comparar una
agregación por organización del forecast en un solo paso o una vía selectiva
equivalente, conservando exención safety, último claim, exclusión busy,
ventana de 1 s y autoridad B3/B9C. Un índice solo sería candidato tras
medirlo contra estos planes. Aquí no se reescribió query, creó índice,
ejecutó PROFILE/B9E ni modificó umbral, quiet window, scheduler o producto.

## Cierre

Runtime changes **0**; migrations añadidas **0**; PROFILE run **NO**;
B9E run **NO**; sin deploy; sin datos de clientes ni PII en fixtures.
Todos los clústeres de este experimento están detenidos, sus bases y
directorios temporales eliminados; ver `cleanup*.json`. El estado productivo
documentado sigue siendo B0 cerrado, B7B=False, flags={}, grants=[], 0
clínicas activadas, `PENDING_ACTIVATION_REQUIREMENTS`; B9 sigue
`IN_PROGRESS`. No se consultó ni cambió producción para este diagnóstico.
