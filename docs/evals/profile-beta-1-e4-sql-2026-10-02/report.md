# PROFILE-BETA-1 v1 — evaluación formal del runtime E4 SQL optimizado

**Resultado del candidato: `PROFILE_BETA_1_PASS`.** El corpus canónico completo pasó 46/46 pruebas y las cinco variantes temporales canónicas pasaron sus gates propios, en orden, con el runner y la metodología congelados. El gate principal de BASE usa los 60 inbounds sanos globales, incluidos los de safety: persisted→claim p95 **9.819540 s ≤ 10 s**, missing **0**, margen **+0.180460 s**. Este PASS es de la nueva evaluación local; no reabre B9E ni cambia su FAIL histórico.

El PROFILE anterior sobre `83ee3b24c84b170e22e401cb09a34da5320ae0a3` conserva **FAIL** (`B9E-LOAD-01-CLAIM`, p95 10.015949 s, n=60, missing=0, margen −0.015949 s). La optimización SQL sigue `OPTIMIZATION_VERIFIED`; la evidencia de equivalencia anterior registra 321 estados de oracle sin diferencias y 783 IDs únicos PASS. Entre ese runtime optimizado y el HEAD congelado para esta corrida solo hubo un commit de documentación/evidencia. No se cambió código de runtime durante el PROFILE.

## Reporte requerido

Las latencias están en segundos salvo el selector SQL, que está en milisegundos. Los p95 usan el método *higher* del contrato. `org0` y `org1` son diagnósticos; el gate se aplica a la distribución global, sin promediar los p95 por organización.

| # | Campo | Resultado |
| ---: | --- | --- |
| 1 | Estado | Evaluación formal cerrada; cinco variantes canónicas y corpus completos |
| 2 | PROFILE result | `PROFILE_BETA_1_PASS` candidato sobre E4 SQL |
| 3 | PROFILE baseline SHA | `08310461337a284386299ec47c54125f2139bf7f` |
| 4 | E4 SQL runtime SHA | `38c4d458996435d6df56b1b337aeb8987fa1045a` |
| 5 | E4 SQL docs SHA | `08310461337a284386299ec47c54125f2139bf7f` |
| 6 | HEAD inicial | `08310461337a284386299ec47c54125f2139bf7f` |
| 7 | HEAD final | Commit único docs/evals que contiene este informe; SHA exacto en Git y en el cierre del encargo, sin hash autorreferencial |
| 8 | Drift check | PASS: 832 fuentes comparadas; seis archivos congelados con SHA-256 coincidente; única fuente productiva distinta del PROFILE anterior: `backend/apps/agent/worker.py`, optimización SQL verificada; topología y tiempos congelados |
| 9 | Runtime changes | 0 durante este encargo; el commit E4 SQL ya era ancestro del HEAD inicial |
| 10 | Migrations | 0 nuevas; `makemigrations --check --dry-run` y `migrate --check` PASS; migraciones existentes solo en plantilla PostgreSQL aislada |
| 11 | PROFILE methodology hash | `48251eca301620a5e9a1f8ce1cbde9cb20d5927b1de9fc77b76b79ba0eea12c0` |
| 12 | Runner hash | `a09b3318f27f1b2970270a03cb90f46034628d5af39e448b3baceabfdf53da75` |
| 13 | Corpus hash | `d2c5cc67ff651654dafb19b2c1eebf52aba08c55cb5fd9c2c76cf334d792330a`; selección `8eb3013b81d6a3d984113c588a5642652ec4fa5b3dcddf465b95f44360f21409` |
| 14 | Base n | 60 healthy global, 40 ordinarios + 20 safety |
| 15 | Base missing | 0 |
| 16 | Base p50 | 8.404651 s |
| 17 | Base p75 | 9.045888 s |
| 18 | Base p90 | 9.576117 s |
| 19 | Base p95 | 9.819540 s; gate ≤10 s PASS |
| 20 | Base p99 | 9.924789 s |
| 21 | Base max | 9.924789 s |
| 22 | Base margin | `10 − 9.819540 = +0.180460 s`, diagnóstico sin gate adicional |
| 23 | Org0 metrics | n=30, missing=0; p50=8.298721, p95=9.207705, p99=max=9.595953 s; `DIAGNOSTIC_ONLY` |
| 24 | Org1 metrics | n=30, missing=0; p50=8.827065, p95=9.906248, p99=max=9.924789 s; `DIAGNOSTIC_ONLY` |
| 25 | persisted→eligible | Ordinarios BASE, n=20/org: org0 p95=7.944088 s; org1 p95=7.950742 s |
| 26 | eligible→claim | Ordinarios BASE, n=20/org: org0 p95=1.680556 s; org1 p95=1.984548 s. Los p95 marginales no se suman para calcular el gate; persisted→claim ordinario p95=9.595953/9.924789 s |
| 27 | Selector SQL p50 | BASE 85.013 ms, n=359 |
| 28 | Selector SQL p95 | BASE 292.493 ms |
| 29 | Selector SQL p99 | BASE 449.055 ms |
| 30 | Selector SQL max | BASE 603.593 ms; EXPLAIN de cierre 81.146 ms, solo diagnóstico |
| 31 | Repeated Message scan | No reapareció el *large* `channels_message` scan por conversación en los cinco EXPLAIN de cierre: Seq Scan de 215–235 filas, `Actual Loops=1` en cada variante. Hay Bitmap Heap Scans de 354/396 loops con `Actual Rows=0`, que no equivalen al large scan anterior. Esta observación de cierre complementa la equivalencia previa; no es un gate temporal nuevo |
| 32 | Safety p95 | BASE n=20, p95=3.135105 s |
| 33 | Safety gate | BASE y BLOCKED_LLM PASS ≤5 s; BLOCKED_LLM n=20 p95=3.047379 s. SATURATION admite safety con n=60 p95=2.851365 s; mantiene precedencia según el gate propio |
| 34 | Outbox p95 | BASE n=135, missing=0, p95=2.697785 s; p50=0.848359, p75=1.410830, p90=2.106646, p99=3.310450, max=3.387943 s |
| 35 | Outbox gate | BASE PASS ≤5 s, sender independiente. Los p95 de las otras variantes son diagnósticos sin este gate adicional |
| 36 | Blocked LLM status/metrics | PASS: healthy n=60, missing=0; p50/p75/p90/p95/p99/max=8.344942/8.998442/9.395545/9.717606/9.975090/9.975090 s; margen +0.282394 s; safety p95=3.047379 s. Timeout controlado de la ruidosa, sin reducción de las dos llamadas LLM reales en READ |
| 37 | Meta slow status/metrics | PASS en estado durable, concurrencia acotada y ausencia de retry ciego; max active/org=1, max outbound attempts=1. Healthy p95=9.661690 s, safety p95=76.663536 s, outbox p95=73.727401 s y missing outbox=21 son diagnósticos: el contrato no les impone SLO de 5/10 s en esta variante |
| 38 | Duplicate status | PASS: 17 webhooks firmados duplicados emitidos, sin errores; deduplicación canónica; healthy p95=9.635552 s diagnóstico; efectos de dominio duplicados prohibidos=0 según corpus |
| 39 | Saturation status | PASS: safety admitida bajo saturación, concurrencia acotada y saturación observada; healthy safety n=60, missing=0, claim p95=0.295114 s; safety dispatch p95=2.851365 s; max active/org=1 |
| 40 | Noisy backlog | BASE 227 pendientes al cierre, máximo muestreado 232; SATURATION 215 pendientes al cierre, máximo muestreado 219. La cola ruidosa no fue estable ni se reclama fairness |
| 41 | Noisy max age | BASE 316.401680 s; SATURATION 374.167670 s del pending más antiguo al collector; cohortes y cierres distintos |
| 42 | COST/B9B | PASS IDs `B9E-COST-01..04`, SCALE-04 y FI-01/02. Límite congelado 30 calls/TurnWork, 18k tokens reservados y 600 output/call; BASE max 2 calls y 1200 reservados/work; SQL `admissions_over_budget=0` en las cinco variantes; timeout/uso desconocido sin refund indebido |
| 43 | SCALE/B9C | PASS IDs `B9E-SCALE-01..04`, N−1/N/N+1 y procesos independientes; N=1; max active/org observado=1 en cada variante; trabajo pendiente duradero bajo saturación, sin afirmar estabilidad de la cola ruidosa |
| 44 | Durability | PASS `B9E-FI-01..10`: lease, crash/restart, fencing, admisión durable, incertidumbre sin retry ciego y rollback/evidencia de operación/efecto; alcance de fixtures canónicas |
| 45 | Tenant | PASS corpus READ/WRITE/cross-component; SQL en las cinco variantes: 0 Message→Conversation cross-tenant y 0 membresías cross-tenant |
| 46 | CREATE_APPOINTMENT | PASS `B9E-E2E-03`, pipeline completo TurnWork→planning→authorization→execution→frontier→evidence |
| 47 | RESCHEDULE_APPOINTMENT | PASS `B9E-E2E-04`, pipeline completo |
| 48 | CANCEL_APPOINTMENT | PASS `B9E-E2E-05`, pipeline completo |
| 49 | CONFIRM_ATTENDANCE | PASS `B9E-E2E-06`, fixture de asunto existente, pipeline completo |
| 50 | REGISTER_PET | PASS `B9E-E2E-07`, fixture B6 explícita, pipeline completo |
| 51 | READ | PASS público y personal: `B9E-E2E-00A..00D`, `01`, `02` y `B9E-READ-01..04`; alcance/identidad/owner/pet/tenant; runner conservó dos llamadas LLM reales por READ ordinario |
| 52 | Corpus PASS | 46 tests únicos, 47 referencias de ID canónico, todos PASS |
| 53 | Corpus FAIL | 0 |
| 54 | Corpus missing | 0 |
| 55 | skips | 0 |
| 56 | xfail | 0 |
| 57 | unauthorized_writes | 0 resultados prohibidos en aserciones canónicas `E2E-09/10/15`, `GATE-01`, `FI-05` |
| 58 | cross_tenant_effects | 0 en aserciones canónicas `E2E-09`, `SCALE-01`, `READ-04` y checks SQL por variante |
| 59 | duplicate_domain_effects | 0 en `E2E-08`, `FI-08/09/10`; 17 webhooks duplicados emitidos en variante temporal |
| 60 | stale_worker_progress | 0 en `FI-04/07` |
| 61 | admissions_over_budget | 0 en `COST-01/02`, `SCALE-04` y checks SQL en las cinco variantes |
| 62 | budget_restored_after_failure | 0 en `COST-03`, `FI-01/02` |
| 63 | max_active_above_limit | 0 en `SCALE-01/03`; max active/org observado=1 en las cinco variantes |
| 64 | lost_work_on_saturation | 0 violaciones en `SCALE-03`, `FI-01`; pending ruidoso sigue duradero, sin confundirlo con throughput suficiente |
| 65 | beta_gate_bypasses | 0 en `GATE-01..05`, `FI-06` |
| 66 | ready_reextensions | 0 observado en las cinco variantes; 0 availability updates y 0 joined-READY inbounds en la carga temporal. Evidencia semántica no trivial se mantiene en recibos E4/monotonic de la misma fuente; este cero tiene alcance limitado |
| 67 | Infra/harness incidents | Tres de preparación: wrapper PostgreSQL con pipe heredado; nombre de DB rechazado antes de tests; corpus parcial detenido tras 14 PASS por discrepancia `DATABASE_URL` de plantilla. Causas y recibos en `incidents.json`; sin PRODUCT_FAILURE atribuido a ellos |
| 68 | Reruns | Una corrida formal completa del corpus y una por cada variante; 0 reruns de variante completa o de cola selectiva. El corpus parcial de preparación no se usa como aceptación; la corrida formal empezó desde clone nuevo y ejecutó los 46 IDs |
| 69 | Checks | Django `check`, `makemigrations --check --dry-run`, `migrate --check`, checks canónicos y `git diff --check`: PASS; salidas y exit codes 0 |
| 70 | Privacy | Fixtures sintéticos; archivos JSON/JSONL/log/MD del directorio inspeccionados por patrón de credencial, 0 hits (recuento en `privacy.json`). Observer guardó solo duraciones numéricas, no SQL crudo; sin prompts/responses/teléfonos/secretos productivos en recibos |
| 71 | Infra cleanup | `CLEANED`: PostgreSQL 16.15 aislado, fsync/synchronous_commit on; clientes=0, locks pendientes=0, prepared=0; 10 DB propias retiradas, data dir ausente, observer exit=0, puerto 35443 cerrado |
| 72 | Production gates | B0 cerrado en cinco WRITE; B7B=False; flags={}; grants productivos=[]; `PENDING_ACTIVATION_REQUIREMENTS`; fuentes por defecto iguales a la evaluación anterior salvo SQL del selector y tests gate actuales PASS |
| 73 | Active clinics | 0 activadas por este encargo; producción no inspeccionada |
| 74 | Deploy | No |
| 75 | Historical PROFILE status | FAIL sobre `83ee3b24…`; p95 10.015949 s, n=60, missing=0, margen −0.015949 s, preservado |
| 76 | B9E status | FAIL histórico; ninguna reapertura formal en este encargo |
| 77 | B9 status | IN_PROGRESS; B9A/B9B/B9C/B9D conservan COMPLETED |
| 78 | Evidence commit | Un único commit `docs/evals` que contiene este informe; SHA exacto después de crear el commit, comunicado en el cierre |
| 79 | Próximo paso | Encargo separado de reapertura formal B9E/cierre de aceptación; sin acción de runtime, tuning, threshold, activación ni deploy aquí |

## Alcance y lectura de los recibos

La topología fue dos planners independientes, un sender, batch 1, pausa/poll 1 s, B9C N=1, quiet W1 8 s/hard cap 25 s monotónicos, warmup 30 s, medición 300 s, drain 20 s, dos organizaciones sanas a un inbound/10 s cada una y una ruidosa a un inbound/s en conversaciones distintas. El proveedor controlado duró 0.5 s por llamada LLM, READ HTTP 0.1 s y Meta base 0.2 s (slow 2 s). El JSON v1 modela una llamada básica, pero el runner y la ruta READ congelados ejecutan dos llamadas reales; la discrepancia ya estaba documentada antes de esta evaluación y no se ajustó.

La medición del selector es ejecución PostgreSQL de todos los polls capturados, incluidos warmup y drain; excluye red y evaluación Python. Los EXPLAIN son SELECT parametrizados tras detener workers y no prueban por sí solos ausencia de una regresión en cada instante del ensayo. La prueba de equivalencia de 321 estados del commit E4 SQL es la evidencia complementaria del cambio estructural. La observación READY no ejercitó una reextensión, por lo que no se presenta como una prueba de carrera de deadline. Los ceros de seguridad y coste son resultados de aserciones de las fixtures exactas, no contadores universales de producción.

El noisy genera más entradas que las que el sistema termina durante esta ventana; los pending al cierre y las edades se reportan sin gate de estabilidad inventado. El sender Meta lento conserva estados pendientes/sending durables al cierre y el contrato de esa variante no aplica el SLO de BASE. `sent` en el proveedor simulado significa aceptación, no delivery/read real. Ninguna corrida local certifica Meta real, un LLM comercial o clínica productiva.

## Evidencia

- [preflight.json](preflight.json), [evaluation-summary.json](evaluation-summary.json), [corpus-decision.json](corpus-decision.json), [critical-metrics.json](critical-metrics.json).
- [base.json](base.json), [blocked_llm.json](blocked_llm.json), [meta_slow.json](meta_slow.json), [duplicate.json](duplicate.json), [saturation.json](saturation.json) y sus `*-diagnostics.json`.
- [incidents.json](incidents.json), [privacy.json](privacy.json), [production-gates.json](production-gates.json), [cleanup.json](cleanup.json), [server-exit.json](server-exit.json).
- Fuentes de reproducción solo evaluativas: [execute.py](execute.py), [diagnostics.py](diagnostics.py), [audit.py](audit.py), [infra.py](infra.py), [observer.py](observer.py), [corpus_decision.py](corpus_decision.py).
