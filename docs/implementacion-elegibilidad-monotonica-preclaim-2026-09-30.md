# B3/C4/W1 v1 — acta de implementación y diagnóstico

2026-09-30. PERFORMANCE_STOP. B9 IN_PROGRESS; B9E FAIL; producción cerrada.

| # | Campo | Resultado |
|---|---|---|
| 1 | Estado del cambio | IMPLEMENTED / VERIFIED_SEMANTICS. PERFORMANCE_STOP |
| 2 | Baseline | `623a80930883fd0473ac6fe4697a417f763dad4c` |
| 3 | SHA enmienda | `2f259f4d21802d00e705c3f7fc71e7e26f5694fa` |
| 4 | SHA runtime/tests | `83285eb096a568dbeb1d67a5c98001dc0bee8352` |
| 5 | SHA docs/evidencia | Commit que contiene esta acta y los recibos; SHA exacto remitido en la entrega final. |
| 6 | HEAD final | Commit docs/evidencia de la entrega final. No hay commits de despliegue. |
| 7 | Enmienda B3/C4 | [v1 FROZEN](contrato-elegibilidad-preclaim-b3-c4-w1-v1.md), anterior al runtime. |
| 8 | Nueva W1 | Rolling 8 s / cap 25 s hasta primera elegibilidad; después no se reinicia silencio antes del claim. |
| 9 | READY | Derivado de pendiente ordinario sin asignar y deadline vencido/NULL. Sin autoridad, lease, presupuesto, capacidad o contexto congelado. |
| 10 | Fuente de verdad | Message.available_at en PostgreSQL, serializado por Conversation. |
| 11 | Reloj | durable.db_now → statement_timestamp(), después de adquirir Conversation; receipt B7 conserva captura previa. |
| 12 | available_at | Deadline común de ráfaga. Heredado ya vencido también para B. NULL legado = READY; puede normalizarse a DB now. |
| 13 | Antes de READY | Cada inbound extiende min(now+8, oldest.created_at+25), limitado inferiormente a now cuando cap vencido. |
| 14 | Después de READY | Deadline común vencido; A+B elegibles para el mismo claim. No puede retirarse READY. |
| 15 | Ingest gana | A+B mismo work; orden persistido, lock real y claim inmediato verificados. |
| 16 | Claim gana | W1 mantiene A; B entra W2 y has_new_input difiere publicación obsoleta. |
| 17 | TurnContext | Inmutable desde claim; READY permite crecimiento previo y no congela contexto. |
| 18 | Membership | Exactamente una asignación; no duplication/reassignment/append postclaim; triggers B3 intactos. |
| 19 | Anchor | Último miembro por (created_at,id), sin cambio B3. |
| 20 | Cursor | Coordenada del primer miembro; historial estrictamente anterior/exclusivo, sin cursor alternativo. |
| 21 | Correcciones | Mañana → READY → viernes aparece en contexto completo y B6 termina con viernes. |
| 22 | Fragmentos | Intención, mascota, fecha y corrección se ordenan por (created_at,id), incluidos empates por ID. |
| 23 | Safety | Precedencia/fast path B5 preservados; señales no entran al UPDATE ordinario y no esperan capacidad ordinaria cuando B5 lo evita. |
| 24 | Takeover | Epoch/autoridad invalidados; worker viejo no publica. Gates humanos preservados. |
| 25 | B6 | Binding/revisión/invalidation conservados; corrección preclaim completa y regresión de binding verde. |
| 26 | B7 | Consentimiento causal/digest/receipt conservados; confirmación READY + corrección no autoriza propuesta vieja. |
| 27 | B8 | Corrección postclaim bloquea efecto sin alterar historia de autorización; ningún parámetro nuevo ejecuta bajo digest antiguo. |
| 28 | B9B | 30 calls/work, 18000 output tokens reservados/work, máximo 600/call, durable admission, no refund; código intacto. |
| 29 | B9C | N=1 PROCESSING con lease/epoch válidos por org; Organization → Conversation y SKIP LOCKED conservados. READY no reserva slot. |
| 30 | Selector E4 | KEEP, worker.py idéntico al baseline; E4-SEL-01..07 y E4-PROC-01..02 verdes. |
| 31 | Tests W1 | W1-MONO-01..10 verdes; 33 IDs nuevos únicos contando controles, causales y procesos. |
| 32 | 8−ε / 8 / 8+ε | Reloj controlado, sin sleeps para fronteras. Además reloj app stale bajo espera real de mutex PG. |
| 33 | PostgreSQL multiprocess | RACE-01..10 y FI-01..10 verdes, procesos OS/conexiones PG independientes. |
| 34 | PIDs/locks | 41 PIDs OS y 43 backends en journals MONO; pg_locks y pg_blocking_pids observados, sin mutex Python como autoridad. |
| 35 | FI-01..10 | Rollback de ingest antes/después de persist/deadlines, claim crash, lost commit response, death/expiry/reclaim/retry, takeover y safety. IDs combinados trazados en corpus.json. |
| 36 | Reextensión observada | ELIMINADA: fronteras causales y 7 B del diagnóstico bloqueado comparten deadline vencido/work con A, sin segundo silencio. |
| 37 | persisted→eligible | Tabla por organización abajo; elegibilidad individual = max(created_at, available_at), NULL = created_at. |
| 38 | eligible→claim | Tabla por organización abajo, sin nuevo threshold; residual evaluado contra el gate original 10 s. |
| 39 | persisted→claim | Tabla por organización abajo; recibos conservan p95, máximos, denominadores y faltantes originales. |
| 40 | Calls/work | Distribución/calls por work y diálogo por org en recibos; READ ordinaria conserva dos llamadas, safety cero. No ahorro supuesto. |
| 41 | Deferrals | Conteos por organización abajo; continuación postclaim permanece vigente. |
| 42 | PROFILE-BETA-1 ejecutado | No. Reextensión eliminada. Base: p95 sano 9.429650 s (60/60, missing=0). LLM bloqueado: p95 sano 10.381673 s (60/60, missing=0), superior al mismo gate original de 10 s; máximo 10.611348 s. En org sana 1, persisted→eligible p95=7.974574 s y eligible→claim p95=2.663415 s. El tramo residual no ofrece margen razonable en estas condiciones. STOP sin gastar un rerun de acceptance; no se suman p95 marginales para decidir el gate. |
| 43 | Resultado exacto PROFILE | No hay intento de acceptance ni resultado nuevo de PROFILE; diagnóstico solo. |
| 44 | Regresión | 641 IDs históricos del alcance proporcional más 84 B9D/E4; recuperación exacta de 107 pendientes en 3 DBs aisladas, sin alterar assertions. |
| 45 | Total IDs | 758 únicos aceptados: 33 nuevos + 725 de regresión. Inventarios/journals y hashes por fuente conservados. |
| 46 | Skips/xfail/pending | 0 / 0 / 0 en el conjunto requerido completado. Intentos de launcher/setup/harness excluidos explícitamente. |
| 47 | Checks | Django check, makemigrations --check --dry-run, migrate --check y git diff --check verdes. |
| 48 | Migraciones | Ninguna. Message.available_at y mutex actual bastan. |
| 49 | Compatibilidad rollout | Workers baseline/nuevo compatibles con deadlines; writers antiguos pueden retirar READY. Garantía exige corte coordinado de todos los writers. |
| 50 | Rollback | Revertir runtime, conservando Messages/TurnWork/membership/AuthorizationEvidence/effects y presupuesto. No reconstruye silencio histórico de ráfagas promovidas. |
| 51 | Observabilidad/privacy | Diagnóstico local test-only con tipos de evento cerrados, scalars técnicos; no prompt/response/teléfono/owner/pet/clinical text nuevos para READY. |
| 52 | Riesgos residuales | Reextensión eliminada. Base: p95 sano 9.429650 s (60/60, missing=0). LLM bloqueado: p95 sano 10.381673 s (60/60, missing=0), superior al mismo gate original de 10 s; máximo 10.611348 s. En org sana 1, persisted→eligible p95=7.974574 s y eligible→claim p95=2.663415 s. El tramo residual no ofrece margen razonable en estas condiciones. STOP sin gastar un rerun de acceptance; no se suman p95 marginales para decidir el gate. Sin fairness fuerte ni extrapolación de proveedor fake a producción. |
| 53 | B9 | IN_PROGRESS; B9A/B9B/B9C/B9D conservan COMPLETED. |
| 54 | B9E | FAIL; no reapertura formal dentro del encargo. |
| 55 | PROFILE histórico | FAIL intacto. Ningún recibo histórico sobrescrito. |
| 56 | Gates productivos | B0 CLOSED; B7B=False; execution flags={}; release grants vacío; PENDING_ACTIVATION_REQUIREMENTS. |
| 57 | Clínicas activadas | 0 reales activadas por este encargo; fixtures aislados retirados al cerrar. |
| 58 | Deploy | No realizado; sin cambios de env productivo/secrets. |
| 59 | Commits | Enmienda → runtime/tests → esta acta/evidencia, con SHAs exactos en entrega. Cambios preexistentes excluidos. |
| 60 | Próximo paso | Un encargo separado debe evaluar un mecanismo E4 adicional sobre el tramo residual eligible→claim, con la evidencia actual. B9E solo puede reabrirse mediante autorización explícita posterior. STOP: no scheduler nuevo, wake-up, E5, P-A/P-B, activación o deploy. |

## Medición temporal — DIAGNOSTIC_ONLY

Mismas condiciones PROFILE-BETA-1 v1: dos planners/sender, N=1, batch/poll 1, tasas 10/10/1 s, dos LLM de 0.5 s, READ 0.1 s, Meta 0.2 s, warmup 30 s, medición 300 s, drain 20 s. Cada escenario usa una DB vacía distinta. Instrumentación E4 local en memoria; no altera el selector. p95 método higher. Org 0/1 sanas, 2 ruidosa. Deltas ordinarios excluyen safety; el gate sano original incluye su denominador original completo (60, incluyendo safety). Works/calls/diálogos/deferrals usan TurnWork.context_at dentro de la ventana; los tiempos usan Message.created_at dentro de la ventana. Son cohortes distintas: no se debe inferir una correspondencia uno a uno entre sus conteos. Missing de org ruidosa representa backlog persistido sin claim al observar, no pérdida de inbound; no se oculta ni se atribuye éxito a ese backlog. Los recibos guardan p50/máximos y distribuciones completas. Comparar estos dos escenarios no demuestra ahorro de calls ni mejoría causal por sí solo.

| Escenario | Org | n ordinarios | persisted→eligible p95 | eligible→claim p95 | persisted→claim p95 | Missing | Joined READY | Works | Calls | Calls/work | Calls/diálogo | Deferrals |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base | 0 | 20 | 7.96102 | 1.100595 | 9.053096 | 0 | 0 | 30 | 40 | 1.333333 | 3.636364 | 6 |
| base | 1 | 20 | 7.964723 | 2.506953 | 10.456949 | 0 | 0 | 29 | 38 | 1.310345 | 3.454545 | 9 |
| base | 2 | 300 | 7.960432 | 214.41308 | 222.342486 | 207 | 0 | 108 | 216 | 2.0 | 2.0 | 0 |
| blocked | 0 | 20 | 7.976448 | 0.912744 | 8.870397 | 0 | 0 | 30 | 40 | 1.333333 | 3.636364 | 5 |
| blocked | 1 | 20 | 7.974574 | 2.663415 | 10.611348 | 0 | 7 | 24 | 28 | 1.166667 | 2.545455 | 3 |
| blocked | 2 | 300 | 7.973032 | 185.245827 | 193.217287 | 178 | 0 | 134 | 268 | 2.0 | 2.0 | 0 |

Gate original diagnostic-base: {"count": 60, "p95_seconds": 9.42965, "max_seconds": 10.456949, "missing": 0}; gates {"healthy_claim_p95_le_10": true, "safety_dispatch_p95_le_5": true, "outbox_dispatch_p95_le_5": true}.


Gate original diagnostic-blocked: {"count": 60, "p95_seconds": 10.381673, "max_seconds": 10.611348, "missing": 0}; gates {"healthy_claim_p95_le_10": false, "safety_dispatch_p95_le_5": true}.

## Evidencia y límites

[Recibo consolidado](evals/w1-mono/acceptance-results.json), [corpus/traceability](evals/w1-mono/corpus.json), [decisión posterior al diagnóstico](evals/w1-mono/diagnostic-decision.json), [fuentes protegidas](evals/w1-mono/validation.json), [fuentes de dominio sin cambios](evals/w1-mono/domain-source-validation.json), [limpieza local](evals/w1-mono/cleanup.json), [causalidad bajo condiciones de perfil](evals/w1-mono/ready-profile-causality.json).

La regresión original se interrumpió para repartir su cola: 534 IDs ya terminados, 107 recuperados exactamente, incluido el caso en curso repetido; fuentes verificadas contra los hashes de cada recibo para el árbol agent; los tests de dominio externos a ese árbol se verifican sin cambios frente a baseline y commit runtime, con SHA normalizado LF. No se atribuye PASS al run original incompleto. El conjunto final sí completa todos los 641 IDs. Los incidentes anteriores de reloj mock/discovery/launcher/clone están excluidos; no fueron intentos PROFILE ni cambios de assertions para acomodar runtime.

PIDs OS MONO: `31132, 33464, 37464, 38284, 39552, 40048, 40184, 40408, 40428, 41080, 41184, 43308, 43400, 43660, 44972, 45348, 45512, 46264, 47116, 47520, 48592, 48752, 48784, 49652, 49656, 50244, 50480, 50536, 51188, 51308, 51336, 51348, 51616, 51868, 52020, 52036, 52140, 52196, 52408, 52452, 53204`.

Backends PG MONO: `25428, 33640, 36228, 36960, 38980, 39968, 40096, 40184, 40612, 40936, 41676, 43556, 43888, 44916, 46144, 46420, 46576, 46724, 47260, 47356, 47624, 48072, 48260, 48520, 49180, 49240, 50052, 50560, 50784, 50812, 50876, 50980, 51244, 51716, 51840, 51912, 51916, 52516, 52592, 52792, 52804, 52864, 53540`.

Los 7 B medidos bajo LLM bloqueado comparten con A el deadline ya vencido y el work; la lectura final de PostgreSQL verifica scope, members, anchor y cursor sin leer payload. La causalidad directa registrada incluye stale app time, deadline vencido, fresh DB time posterior al mutex, dos miembros y segundo silencio=False. Los perfiles son fixtures fake locales, sin IO real Meta/modelo; aceptación simulated sent no prueba delivered/read.

Reproducción: `rtk proxy python -X utf8 docs/evals/w1-mono-run.py --suite targeted --receipt NUEVO --database test_b8b_w1_mono_targeted --labels targeted-labels.json`. Requiere clonar bases propias de plantilla migrada vacía en la instancia local descrita; el runner limita nombres/host y no puede usarse como deploy.
