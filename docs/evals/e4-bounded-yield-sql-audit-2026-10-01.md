# E4 — auditoría SQL bounded-yield

Baseline: `6e59f6c05514ad6eca0985796e538de4fd749560`.
Runtime candidato: `83ee3b24c84b170e22e401cb09a34da5320ae0a3`.

**ROOT_CAUSE_NOT_CONFIRMED para implementación. STOP.**

E4 canónico (§7:806–823) permite corregir selección justa cuando la medición
demuestra necesidad. B3/B9C conservan la autoridad del claim y N=1; B5
conserva la exención safety y B9B exige cero admisión por observación.
El commit `83ee3b2` añadió `pending_safety` y `EXISTS(upcoming)` a
`_pending_conversation_candidates`. La subconsulta busca Message inbound
pending sin TurnWork, con `available_at` en `(clock, clock+1 s]`, de otra
organización, no safety, no busy y con último claim menor que la organización
exterior. El KEEP ya filtraba trabajo vencido/inbound disponible y org busy,
calculaba último claim, hacía `ROW_NUMBER()` por org, ordenaba por claim,
actividad y PK, y aplicaba LIMIT 3. El nuevo filtro se aplica antes de la
window/limit. Safety pendiente y org nunca reclamada quedan exentas.

Esto describe el ORM; **no es SQL compilado**. No se obtuvo SQL real con
parámetros before/after ni se instrumentó query count con `execute_wrapper`.
El código evalúa el queryset una vez por ciclo y reevalúa después de un claim
exitoso; no se presenta como medición de statements o prueba de no N+1.

## EXPLAIN históricos PostgreSQL 16

| Recibo | Conversations | Message scan global | Execution | Shared hits | Forecast Bitmap Heap Scan loops |
| --- | ---: | ---: | ---: | ---: | ---: |
| `e4-claim/candidate-bounded-yield.json` | 162 | 87 | 32.867 ms | 3,306 | 162 |
| `e4-claim/postfix-final-base.json` | 354 | 233 | 233.000 ms | 13,332 | 354 |
| `e4-claim/postfix-final-blocked.json` | 354 | 238 | 243.396 ms | 14,031 | 354 |
| `profile-beta-1-e4-2026-10-01/base-diagnostics.json` | 354 | 231 | 127.583 ms | 12,983 | 354 |

Son cierres históricos con distinta carga, no una serie controlada.
El cierre formal tiene planning=8.601 ms, shared read=0, temp written=0.
Su Index Scan Conversation tarda 122.363 ms. Dentro, último claim sobre
TurnWork se recorre/sortea 354 veces (2,478 hits); el nested loop forecast
se ejecuta 354 veces y su Bitmap Heap Scan Message acumula 9,912 hits.
Cada BitmapAnd vuelve a leer aproximadamente 292 entradas de
`message_send_ready` y 254 de `channels_message_turn_work_id_20ce3041`.
Los subplanes internos busy/último claim tienen cero loops en ese corte;
no se les imputa tiempo. Safety pending es un subplan hash calculado una vez:
Seq Scan 0.389 ms. Sort final y WindowAgg tienen poco tiempo local.

El plan E4 base registra 233 rows removed por cada uno de 354 Bitmap Heap
Scans; el plan formal fue saneado y no retiene `Rows Removed by Filter`,
`Output` ni `Sort Method`. No hubo temp written en los planes citados.
El comparador KEEP histórico reportó 1.456 ms base y 3.065 ms bloqueado
en `docs/diagnostico-e4-capacidad-scheduling-2026-09-30.md`, sin A/B de
iguales cardinalidades/concurrencia. PROFILE formal: n=352, p50/p95/p99/max
97.497/291.922/422.705/622.632 ms; 231 noisy pending al cierre.

La evidencia muestra repetición por Conversation y trabajo Message en cada
iteración. PROFILE creó una conversación distinta por inbound noisy, así
que ambos tamaños crecieron juntos. No se midió cómo cambia el coste con
Messages fijos y más orgs/conversaciones, o al revés. Tampoco se ejecutaron
los backlog controlados 0/10/50/100/250/500/1000. Por eso el nodo
correlacionado es una hipótesis fuerte, pero el root cause gate requerido
para decidir una optimización queda **NOT_CONFIRMED**.

Cardinalidades de cierre: tres org, 354 conversaciones, 231 noisy inbound
pending y 231 filas pre-window. READY, PROCESSING y forecast elegible no
se midieron por etapa en el mismo snapshot. El forecast aparece por
Conversation, no como statement cliente por Message.

Índices usados: `agent_conversation_organization_id_1ef62d10`,
`message_send_ready` (`direction,status,next_attempt_at`),
`channels_message_turn_work_id_20ce3041`, `turnwork_poll_retry`
(`status,next_attempt_at`), `agent_turnwork_conversation_id_e15ceb51`
y PK Conversation. Los modelos también declaran índices de Conversation
(`organization,state,-last_activity_at`; `contact,-created_at`), Message
(`direction,status`; `organization,conversation,created_at`;
`conversation,semantic_type,created_at`; sender y contacto), TurnWork
(`status,lease_expires_at`) y Organization (PK, `public_id` único,
`is_demo`). Existen uniques parciales de dedup, outbox y TurnWork no
terminal. No se extrajo `pg_indexes`; el inventario no es exhaustivo.

El Python aislado del harness recibe `Acceso denegado` al invocar su
intérprete base fuera del workspace. El binario PostgreSQL 16.15 sí
respondió, pero sin Django/migrations/fixtures no se compiló SQL ni
se ejecutó el corpus controlado. No se creó infraestructura.

## Campos pendientes

No obtenidos: SQL compilado before/after, query count, cardinalidad por
etapa, series controladas, EXPLAIN nuevo `VERBOSE`, índice A/B, oracle
diferencial, mismatches, multiproceso, percentiles before/after, reducción
y persisted→claim diagnóstico nuevo. No se implementó rewrite o índice.

Runtime, semantics, safety exemption, locks, B9B y B9C permanecen intactos.
No se ejecutó regresión ni checks Django: no hubo cambio de runtime y falta
Python ejecutable. IDs, expectations, skips y xfail no cambiaron.
Sin migration, rollback o infraestructura nueva. Sin PII nueva.
PROFILE-BETA-1 y B9E siguen FAIL; B9 sigue IN_PROGRESS. B0 cerrado,
B7B=False, flags={}, grants=[], PENDING_ACTIVATION_REQUIREMENTS,
0 clínicas activas y sin deploy. No se ejecutó PROFILE ni se reabrió B9E.
Próximo paso: habilitar el Python del harness aislado y completar SQL,
planes y escalado controlados antes de decidir una optimización E4.
