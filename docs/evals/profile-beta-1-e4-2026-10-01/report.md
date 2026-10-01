# PROFILE-BETA-1 v1 — primer candidato formal E4 (2026-10-01)

**FAIL** por `B9E-LOAD-01-CLAIM`: p95 healthy global **10.015949 s > 10 s**, n=60, missing=0. Margen **−0.015949 s**. `PRODUCT_FAILURE`; sin rerun, tuning ni cambio de threshold.

El corpus canónico cerró 46/46 PASS. Se ejecutó únicamente base; la regla STOP tras cualquier gate fallido impide ejecutar las otras cuatro variantes. Cada una tiene recibo explícito STOP y percentiles N/A. No se acredita la matriz integral ni se usa el diagnóstico previo como resultado formal.

Runtime, tests, fixtures, runner, metodología, corpus y thresholds permanecen idénticos al HEAD congelado. El histórico PROFILE/B9E FAIL y B9 IN_PROGRESS se conservan.

Un incidente previo de preparación inició la conexión antes de completar startup: cero tests/variantes habían comenzado. Se registró causalidad y se completó la plantilla. No hubo fallo de infraestructura/harness en la variante formal ni repetición del producto FAIL.

| # | Campo requerido | Resultado |
| --- | --- | --- |
| 1 | Estado PROFILE | FAIL — PRODUCT_FAILURE, B9E-LOAD-01-CLAIM |
| 2 | Baseline SHA | a83d7d7eafc8cb7e4c626bee60e79613f62da438 |
| 3 | Runtime SHA | 83ee3b24c84b170e22e401cb09a34da5320ae0a3 |
| 4 | Docs/evidence SHA | E4 documental previo: a83d7d7eafc8cb7e4c626bee60e79613f62da438; el commit único que contiene este informe es el SHA docs/evals final, comunicado en el cierre |
| 5 | HEAD final | Commit docs/evals que contiene este informe; SHA exacto en cierre de chat / Git, sin hash autorreferencial |
| 6 | Hash runner | a09b3318f27f1b2970270a03cb90f46034628d5af39e448b3baceabfdf53da75 |
| 7 | Hash metodología | 48251eca301620a5e9a1f8ce1cbde9cb20d5927b1de9fc77b76b79ba0eea12c0 |
| 8 | Hash profile | ff0834449d1915b395be58e7cdbab09e39917fe0ddf3cc90e3f187fdfdc9f311 |
| 9 | Drift detectado | No; 832 fuentes verificadas al cierre |
| 10 | Variantes ejecutadas | base. blocked_llm/meta_slow/duplicate/saturation: NOT_RUN_STOP_AFTER_PRODUCT_FAILURE; recibo explícito por variante |
| 11 | Base n | 60 healthy global (40 ordinary + 20 safety), missing=0 |
| 12 | Base p50/p75/p90/p95/p99/max | 8.469384 / 8.896047 / 9.407633 / 10.015949 / 10.385686 / 10.385686 s |
| 13 | Base margin | -0.015949 s |
| 14 | Blocked n | N/A — STOP por FAIL base |
| 15 | Blocked percentiles | N/A — no ejecutado; no reutiliza diagnósticos |
| 16 | Blocked margin | N/A |
| 17 | Org0 breakdown | ordinary n=20: PE p95=7.952172; EC p95=1.127489; PC p95/max=8.977227/8.977227; all PC n=30 p95=8.896047; missing=0; joined READY=0; calls/works=40/30 (1.333333); deferrals=10; claims total=33 |
| 18 | Org1 breakdown | ordinary n=20: PE p95=7.946727; EC p95=2.495969; PC p95/max=10.385686/10.385686; all PC n=30 p95=10.244711; missing=0; joined READY=0; calls/works=40/30 (1.333333); deferrals=10; claims total=32 |
| 19 | Noisy breakdown | ordinary n=69: PE p95=7.945335; EC p95=238.127460; PC p95/max=246.050687/251.519508; all PC n=69 p95=246.050687; missing=231; joined READY=0; calls/works=172/86 (2.000000); deferrals=0; claims total=99 |
| 20 | Selector p50/p95/p99/max | 97.497000 / 291.922000 / 422.705000 / 622.632000 ms; n=352, ejecución PostgreSQL, warmup+measure+drain |
| 21 | EXPLAIN | 127.583000 ms, SELECT compilado parametrizado, cierre sin mutación; plan numérico en base-diagnostics.json |
| 22 | ready_reextensions | 0 observado; updates=0, joined READY=0; prueba semántica no trivial existente con misma fuente, no nuevo escenario |
| 23 | bounded-yield behavior | Sin claim/reserva/admisión por forecast; deadline restaura selección, safety y pending safety W1 exentos, busy no reserva, never-claimed preservado, observación advisory. 11 IDs previos en fuente final hash coincidente; ver bounded-yield-and-ready.json |
| 24 | healthy missing | 0 |
| 25 | noisy backlog | 231 pendientes / 300 medidos; max age observado al collector=325.753418 s; máximo global pending sample=237 |
| 26 | calls/work | org0 40/30=1.333333; org1 40/30=1.333333; noisy 172/86=2.0. Ordinary READ=2; safety=0. Cohorte works=context_at, distinta de Message.created_at |
| 27 | deferrals | org0=10; org1=10; noisy=0 |
| 28 | EVAL | PASS corpus canónico controlado; PROFILE FAIL |
| 29 | COST | PASS corpus + SQL base; max calls/work=2, reserved/work=1200; límites 30/18000; sin monetización |
| 30 | SCALE | PASS corpus N−1/N/N+1, budget/witness/capacity compuesto; active/org observado ≤1; matrix temporal incompleta por STOP |
| 31 | SAFETY | PASS corpus/base: n=20 p95=3.661316 s, margen=1.338684 s; caso específico pending-W1 en recibo previo misma fuente |
| 32 | DURABILITY | PASS FI-01–10 del corpus; garantías acotadas de crash/restart/lease/timeout/uncertainty/SQL rollback |
| 33 | TENANT | PASS; cero violaciones corpus y SQL Message→Conversation/TurnWork |
| 34 | READ_PUBLIC | PASS alcance canónico de 3 capabilities; sin aplicar gates WRITE automáticamente |
| 35 | READ_PERSONAL | PASS alcance canónico de 3 capabilities, identidad vigente/owner/pet/tenant |
| 36 | CREATE_APPOINTMENT | PASS B9E-E2E-03, pipeline completo |
| 37 | RESCHEDULE_APPOINTMENT | PASS B9E-E2E-04, pipeline completo |
| 38 | CANCEL_APPOINTMENT | PASS B9E-E2E-05, pipeline completo |
| 39 | CONFIRM_ATTENDANCE | PASS B9E-E2E-06, fixture asunto existente, pipeline completo |
| 40 | REGISTER_PET | PASS B9E-E2E-07, fixture B6 explícita, pipeline completo |
| 41 | unauthorized_writes | 0 — aserciones exactas del corpus / SQL según critical-metrics.json |
| 42 | cross_tenant_effects | 0 — aserciones exactas del corpus / SQL según critical-metrics.json |
| 43 | duplicate_domain_effects | 0 — aserciones exactas del corpus / SQL según critical-metrics.json |
| 44 | stale_worker_progress | 0 — aserciones exactas del corpus / SQL según critical-metrics.json |
| 45 | admissions_over_budget | 0 — aserciones exactas del corpus / SQL según critical-metrics.json |
| 46 | budget_restored_after_failure | 0 — aserciones exactas del corpus / SQL según critical-metrics.json |
| 47 | max_active_above_limit | 0 — aserciones exactas del corpus / SQL según critical-metrics.json |
| 48 | lost_work_on_saturation | 0 — aserciones exactas del corpus / SQL según critical-metrics.json |
| 49 | beta_gate_bypasses | 0 — aserciones exactas del corpus / SQL según critical-metrics.json |
| 50 | corpus | 46 tests únicos, 47 IDs de corpus que los referencian; todos PASS. 5 variantes: base FAIL + 4 STOP explícitos |
| 51 | IDs PASS/FAIL/missing | 46 PASS / 0 FAIL / 0 missing tests, 0 skips/xfail. Timed LOAD-01 FAIL, LOAD-02–05 clasificados STOP; IDs exactos en corpus-decision.json y variant-gates.json |
| 52 | Regression | 46 IDs canónicos exactos en este HEAD. No rerun de 2384 históricos de cierre B9E ni de los 775 diagnósticos |
| 53 | Checks | Django check, makemigrations --check --dry-run, migrate --check y git diff --check: PASS. Migraciones existentes aplicadas únicamente a plantilla propia |
| 54 | Infra cleanup | CLEANED: clientes=0; locks pendientes=0; prepared=0; 3 DB propias retiradas; 35439 cerrado; directorio ausente; observer terminado; sin raw server log |
| 55 | Privacy | IDs técnicos/estados cerrados/métricas/hashes; SQL crudo solo memoria, no persistido. Clave desechable omitida del texto de reproducción. Ver privacy.json |
| 56 | Risks | Residual org1; cola noisy no estable; coste SQL material; 4 variantes detenidas; límites de proveedor/identidad/semántica y de observabilidad READY; ver lista de riesgos |
| 57 | PROFILE candidate status | FAIL |
| 58 | PROFILE histórico | FAIL preservado, sin sobrescritura |
| 59 | B9E | FAIL histórico; no reabierto |
| 60 | B9 | IN_PROGRESS |
| 61 | Production gates | B0 cerrado para cinco WRITE; B7B=False; flags={}; grants productivos vacíos; PENDING_ACTIVATION_REQUIREMENTS |
| 62 | Active clinics | 0 clínicas reales activadas por este encargo; producción no accedida |
| 63 | Deploy | No |
| 64 | Próximo paso | Decidir un encargo posterior a partir de B9E-LOAD-01-CLAIM. STOP; sin tuning/rerun/reapertura B9E/activación/deploy automáticos |

## Fronteras de evidencia

El gate usa los 60 inbounds healthy (incluye safety), timestamps durables y percentil higher. Los desgloses ordinarios excluyen safety; los p95 marginales PE/EC no se suman. Calls/work/deferrals usan context_at; las latencias usan Message.created_at.

El selector mide duración de ejecución SQL en PostgreSQL, excluyendo RTT/compilación/evaluación Python, con logging a pipe consumido en memoria. No se guarda SQL/params ni se cambia la query, el índice o el runtime. El overhead de timing/emisión existe y no se compensa ajustando gates. La comparación con el diagnóstico previo es indicativa por su distinta frontera. EXPLAIN ANALYZE es un SELECT parametrizado tras detener los workers, con plan publicado solo en campos técnicos/números.

Monotonic READY y bounded-yield conservan la prueba previa de fuente final con hash idéntico, incluyendo YIELD07/08/09 y los procesos. No se reejecutaron esos 11 IDs como escenarios nuevos del perfil. En esta carga joined READY=0 y updates observados=0; no se presenta ese cero como stress de la carrera READY. El corpus actual safety/lease/tenant/coste y la base se reportan por su alcance propio.

Las métricas críticas cero se apoyan en aserciones por ID y checks SQL, no en una afirmación universal sobre producción. Grants/test scopes se abrieron solo dentro de las fixtures canónicas; sus context managers no cambian los defaults productivos.

## Riesgos

- Canonical latency FAIL is 15.949 ms over 10 s. It remains PRODUCT_FAILURE; no almost/conditional pass, confidence buffer, tuning or rerun.
- Org1 ordinary p95 10.385686 s and eligible->claim p95 2.495969 s expose the tail; marginal p95 values are not added to compute the gate.
- Noisy is overloaded: 231 measured inbounds have no claim at closure and remain pending; maximum oldest pending age observed at collection is 325.753418 s. No stability/fairness guarantee.
- Selector server execution p95 291.922 ms, p99 422.705 ms, max 622.632 ms retains material SQL cost. Earlier 327-341 ms included client-side measurement, so the boundaries are not identical.
- Single post-run EXPLAIN execution 127.583 ms is a warm closing snapshot, not a selector-tail or causal performance claim.
- Four timed variants stopped after base FAIL. Their gates and blocked percentiles are not measured; prior diagnostic base/blocked values are not formal results.
- No joined-READY inbounds/deadline updates occurred in this timed run. Existing same-source semantic receipts supply the nontrivial monotonic/bounded-yield proof; not all 775 previous tests were reexecuted here.
- Canonical JSON models one LLM call; unchanged documented runner/runtime performs two real calls for ordinary READ. This historical documented discrepancy is retained, not tuned away.
- Controlled provider/Meta, local Django loopback and synthetic fixtures do not certify a commercial LLM, real Meta, clinical universality or physical identity.
- Source defaults and task actions were checked locally; production infrastructure was not accessed. Human activation requirements remain pending.

## Recibos

- [preflight.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/preflight.json)
- [environment.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/environment.json)
- [preparation-incident.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/preparation-incident.json)
- [base.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/base.json)
- [base-diagnostics.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/base-diagnostics.json)
- [variant-gates.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/variant-gates.json)
- [corpus-decision.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/corpus-decision.json)
- [critical-metrics.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/critical-metrics.json)
- [dimensions-and-pipeline.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/dimensions-and-pipeline.json)
- [bounded-yield-and-ready.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/bounded-yield-and-ready.json)
- [checks.exit.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/checks.exit.json)
- [cleanup.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/cleanup.json)
- [production-gates.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/production-gates.json)
- [immutability-closure.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/immutability-closure.json)
- [privacy.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/privacy.json)
- [manifest.sha256.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/manifest.sha256.json)
- [final.json](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/final.json)
- [infrastructure-observer-source.txt](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/profile-beta-1-e4-2026-10-01/infrastructure-observer-source.txt)
