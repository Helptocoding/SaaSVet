# E4 — diagnóstico de capacidad y selección tras PROFILE-BETA-1 FAIL

Estado final de este encargo: **E4 PARTIAL, candidato insuficiente; STOP §36**.
Base post-fix PASS (p95 9.844989 s); LLM bloqueado FAIL (p95 10.497891 s).
Las otras tres variantes del candidato quedan NOT_EVALUATED por STOP.
ROOT_CAUSE_CONFIRMED; B9 IN_PROGRESS, B9E y PROFILE-BETA-1 integral FAIL.
Baseline exacto verificado antes de cambios:
`52e1663881653efe6dcaf1d264aaac224c89a7ac`. Fecha local: 2026-09-30.

Autoridad: plan canónico completo, §7/E4:806–823; B9:703–734; contratos
B3, B9B y B9C y sus ADRs. E4 permite corregir selección por organización
únicamente después de demostrar necesidad. No autoriza cambiar N=1, el
presupuesto ni las fronteras de autorización. El encargo concreta el perfil
de entrada y exige diagnóstico antes de elegir un mecanismo. No hay
discrepancia de alcance que obligue a bloquear el diagnóstico.

## Reproducción sin cambios

Runner original `b9e_profile.py`, PostgreSQL 16.15 local en puerto 35440,
`fsync=on`, `synchronous_commit=on`, Python/lock del ensayo B9E. Dos planners,
un sender, batch 1, pausa 1 s, 30 s de warmup y 300 s de medición; fixtures,
tasas y proveedores originales. DB `test_e4_reproduction` independiente.
No se cambió código productivo ni el runner/perfil B9E.

E4-REPRO-01: `evals/e4-reproduction-base.json` y colección readonly
`evals/e4-reproduction-base.analysis.json`.

| Persistido → claimed_at, sano | Segundos |
| --- | ---: |
| n | 60 |
| p50 | 8.540524 |
| p75 | 11.526504 |
| p90 | 21.482832 |
| p95 | 22.141079 |
| p99 | 22.585115 |
| máximo | 22.585115 |

Compatible con p95 histórico 21.725759 s; FAIL ≤10 s reproducido. Cero sanos
sin claim, cero violaciones de presupuesto/cross-tenant en la colección,
máximo activo observado por organización 1. El percentil conserva el método
`higher` y los 60 mensajes, incluidos los 20 safety; también se publican
los 40 ordinarios por separado, sin sustituir el denominador del gate.

Primer dato causal: algunos inbounds ordinarios pierden su primera ventana
de selección y un nuevo inbound de la misma conversación extiende
`available_at` de aproximadamente 8 a 18 s desde el primer mensaje.
El p95 de elegibilidad final es 18.051778 s. La causa de perder esa primera
ventana aún requiere ablación; no se atribuye automáticamente a locks,
índices, starvation o dos llamadas.

## Instrumentación y experimentos

`e4_profile.py`, `e4_timing.py`, `e4_collect.py` son tooling de eval,
etiquetado DIAGNOSTIC_ONLY. El runner original y el perfil congelado se
preservan. Los journals en memoria usan eventos cerrados, duraciones e IDs
técnicos de fixtures; nunca prompt, response, teléfono o texto clínico.
El observer añade consultas readonly, sin locks, y publica su coste para
comparar la distribución instrumentada con la reproducción sin observer.

T0 es `Message.created_at`, conforme al gate, no un timestamp inventado de
commit de ingreso. T1 es la elegibilidad final `available_at`; la creación
de TurnWork ocurre en el claim, por lo que antes existe Message pendiente.
T2 es el primer poll diagnóstico que observa ese inbound elegible. T3 es
entrada a la primitiva de claim después de selección real; T4 comienza
la adquisición Organization; T5 termina el último SQL que adquiere locks
del claim; T6 es el retorno tras el commit. `claimed_at` se registra antes
del commit B3 y se mantiene como reloj contractual; T6 es diagnóstico.
Los safety usan la transacción B5 inmediata y no tienen polling ordinario.

La duración de SQL es una cota superior de espera por locks, nunca una
medición exacta de `Lock` wait. El reporte conservará esa distinción.
Los percentiles de componentes no se suman para inventar un p95 total.

Matriz prevista: baseline instrumentado 30/300 s; no-noisy, provider .001 s,
batch 3 y polling .1 s con 30/120 s, todas DIAGNOSTIC_ONLY. Esas variantes
no aprueban acceptance ni cambian PROFILE-BETA-1. La comparación temporal
de los controles se declara como diagnóstico de una ventana menor.

## Estados y límites

El diagnóstico confirmó ROOT_CAUSE_CONFIRMED antes del cambio. El candidato
de runtime quedó implementado y validado, pero resultó insuficiente al
ejecutar el perfil original con LLM bloqueado. B9A/B/C/D conservan
COMPLETED, B9E/PROFILE-BETA-1 FAIL y B9 IN_PROGRESS. No rerun formal B9E.

Los cuatro cambios preexistentes permanecen fuera de E4:
DEPLOY_VPS_PLAN.md y DEPLOY_VPS_STATUS.md borrados; las dos notas
`docs/auditoria-agente-conversacional-veterinario-2026-09-10.md` y
`docs/discrepancia-encargo-b9-2026-09-26.md` untracked.

B0 cerrado, B7B=False, execution flags={}, grants productivos vacíos,
PENDING_ACTIVATION_REQUIREMENTS, cero clínicas activadas y sin deploy.
Estas afirmaciones conservan el estado autorizado del repositorio; no
representan una consulta a producción.

## Hipótesis previas a una decisión de runtime

| ID | A favor | En contra / límite | Contribución observada o cota | Experimento |
| --- | --- | --- | --- | --- |
| H1 selector global/batch 1 | Espera poll→candidato p95 3.454857 s; una segunda entrada puede retirar elegibilidad antes de selección | B9C ya excluye org ocupada antes de LIMIT; no equivale por sí solo a starvation | Retraso inicial + extensión de elegibilidad de ~10 s en parte del cohort | Batch 3 y selección eficiente/fair separadas |
| H2 dos LLM | Servicio READ p95 2.032245 s; dos dispatch reales de ~.5 s | Provider .001 s aún da p95 sano 20.255919 s | Amplifica ocupación; no es causa suficiente aislada | E4-ABL-02 fast-provider |
| H3 polling | Pausa 1 s después del servicio; start→start p95 3.050742 s | Noisy ausente pasa sin reducir pausa | Fase de polling/servicio consume el margen entre debounce 8 s e inbound siguiente 10 s | Poll .1 s diagnóstico |
| H4 locks | Claim necesita locks Organization→Conversation→TurnWork→Message | SQL de claim máximo observado .033030 s; SKIP LOCKED no espera los locks de selección | SQL da cota superior de waits, muy inferior a 22 s; categorías de SELECT con joins se agrupan en el journal inicial | PostgreSQL real, ejecución SQL y muestras de waits en variantes |
| H5 query/index | Plan contiene scans, hash aggregate y sort | EXPLAIN ANALYZE del backlog tarda 1.109 ms; top-N usa 25 KiB, sin spill | Query online p95 9.375 ms; no justifica índice nuevo | Plan e índices conservados en colección |
| H6 B9C N=1 | Noisy recibe 1/s y servicio mínimo de dos LLM+READ es 1.1 s, antes del coste local/pausa | El gate es latencia sana; no exige que toda la cola noisy drene; no-noisy pasa | Backlog noisy es inevitable: incluso cota ideal μ≤.9091/s < λ=1/s; no demuestra imposibilidad del SLO sano | No-noisy y selector DIAGNOSTIC_ONLY; conservar N=1 |
| H7 combinación | First eligible observation→claim p95 13.398059 s y T1 final p95 18.028940 s | Percentiles de componentes no son aditivos; ventanas de ablación menores | Interacción selección/servicio/polling/debounce; falta separar eficiencia de fairness | Matriz mínima y trazas por mensaje técnico |

Baseline instrumentado: claim sano p95 21.843496 s, compatible con reproducción
sin observer 22.141079 s. Coste del observer readonly p95 .026936 s, máximo
.325583 s; no se utiliza para acceptance. Las cifras de SQL incluyen costes
de ejecución/IO, no solo espera de locks.

El planner itera después de recibir una tool call, ejecuta READ y vuelve a
`_complete_with_retry` con el resultado para generar respuesta. El fake no
ejecuta tools ni sintetiza completion: el journal registra dispatch→respuesta
primera, tool completada y dispatch→respuesta segunda. En el loop/contrato
vigente son las dos etapas efectivas de esta ruta. No se demostró equivalencia
semántica que permita retirar la segunda dentro de E4.

## Decisión causal previa a implementación

**ROOT_CAUSE_CONFIRMED** en el perfil medido. Confianza alta para la
interacción concreta selección/servicio/polling/debounce; no garantía
universal de fairness ni de latencia fuera de esta topología.

El orden global `Conversation.last_activity_at, pk` favorece backlog noisy
antiguo cada vez que esa org queda disponible. Excluir la org ocupada evita
monopolizar ambos planners simultáneamente, pero no prioriza una org sana
que lleva más tiempo sin turno. De 57 polls con inbound sano observado
claimable, 24 seleccionaron noisy; 3 terminaron sin progreso y hubo 9 misses
de claim en total. Es snapshot diagnóstico anterior al selector, no prueba
de autoridad en ese instante. Los 60 sanos finalmente obtienen claim: no se
demostró starvation total ni universal.

En 12 de los 40 inbounds sanos ordinarios se observó elegibilidad antes de
que un inbound posterior la extendiera. Perder la ventana 8→10 s activa
otra espera de aproximadamente 10 s y mueve la cola alta a ~22 s. Sin noisy
no hubo extensiones y p95=9.033531 s. Con LLM casi instantáneo hubo cuatro
extensiones y p95=20.255919 s. Batch 3 conservó dos y p95=20.395026 s;
poll .1 conservó una y p95=10.121223 s. Estos controles no cambian acceptance.

No se elige índice: el plan y la cota de SQL no lo justifican. Tampoco se
elige N>1, otra llamada LLM, otro provider latency, debounce diferente,
topología/batch/polling de acceptance ni otro presupuesto.

Las dos variantes finales separan selección eficiente entre orgs (un
candidato por org y continuar tras miss) de prioridad explícita a la org
menos recientemente reclamada, derivada readonly de TurnWork existente.
Solo después de su resultado se elegirá, si corresponde, un mecanismo
canónico mínimo. Este experimento pertenece a §7/E4, primera fila, porque
la selección observada deja a organizaciones sanas sin progreso en su
primera ventana bajo carga ampliada. No agrega persistencia o autoridad,
por lo que no necesita un contrato de una nueva entidad/cursor durable.

### Resultado de las variantes de selección

La selección eficiente con orden global original, un candidato por org y
fallback acotado tras miss dio p95=21.773134 s (24 sanos, 30/120 s). La
prioridad a la organización menos recientemente reclamada, con el resto
idéntico, dio p95=9.289224 s y máximo=9.767543 s (24 sanos); los 16
ordinarios conservaron elegibilidad final ~7.946 s. Ambas son
DIAGNOSTIC_ONLY, no acceptance. Recibos y colecciones:
`evals/e4-diagnostic-efficient.*` y `evals/e4-diagnostic-fair.*`.

Esto justifica como candidato mínimo ordenar por último `TurnWork.claimed_at`
de la organización, seleccionar un candidato por organización y continuar
tras un miss dentro de un límite pequeño. El claim atómico existente seguirá
siendo la única autoridad. Antes de promoverlo se requieren pruebas del
selector, procesos PostgreSQL y medición con el runner original congelado.

La ejecución local dejó de responder al iniciar el control adicional
30/120 s. Su sesión 61323 no entregó recibo verificado; se solicitó
interrupción, sin confirmación de cierre. También quedaron sin respuesta
lecturas y diagnósticos del host. No se considera ese control válido ni se
implementó runtime. La ausencia de recibo impide afirmar cleanup o commits.
E4 permanece PARTIAL hasta recuperar las herramientas locales y completar
implementación, regresión, perfil y limpieza. Este párrafo registra el punto
de interrupción anterior; la continuación y el cierre constan abajo.
La causa confirmada no equivale
a un fix aceptado; B9E conserva FAIL y no se reabre.

### Decisión al recuperar ejecución, antes del cambio de runtime

La instancia propia recuperó WAL en puerto 35441 (35440 rechazaba bind).
El intento interrumpido no creó `test_e4_baseline_120`; no se rescatan datos
parciales. Un nuevo control completo 30/120 s conservando runtime original
dio p95=21.371626 s, máximo=22.106390 s, n=24, sin violaciones críticas:
`evals/e4-diagnostic-baseline-120.*`. Confirma la diferencia con fair en
ventana comparable, aunque son ejecuciones secuenciales, no pareadas.

**ROOT_CAUSE_CONFIRMED; candidato elegido:** último claim durable por org,
un candidato elegible por org y hasta tres candidatos de orgs distintas por
intento de progreso. Batch sigue siendo máximo de trabajos procesados; para
batch>1 se reselecciona tras cada éxito y no se repite conversación dentro
del poll. Tras tres misses sin progreso se vuelve al loop existente. El
lookahead no aumenta batch ni N: absorbe la colisión de los dos planners.
La fecha deriva de TurnWork, sin cursor, tabla ni autoridad nuevos. El claim
revalida tenant/capacidad bajo Organization, conserva lock order B9C y B3.
La prioridad pertenece a E4: necesidad medida de progreso de organizaciones
sanas bajo carga ampliada. No introduce fairness fuerte ni un scheduler
general. Eficiencia sola, batch/poll/provider tuning e índice quedan
descartados por los controles ya registrados. Se implementa ahora únicamente
este candidato, sujeto a regresión y PROFILE-BETA-1 v1 original.

## Métricas diagnósticas consolidadas

Resumen de la matriz: `evals/e4-final-summary.json`, clasificado
DIAGNOSTIC_ONLY. Su sección de hashes es una fotografía al generarse;
la validación final usará un manifest posterior, con los logs ya cerrados.

| Variante | Ventana medición | n sano | p95 s | Extensiones ordinarias |
| --- | ---: | ---: | ---: | ---: |
| Baseline instrumentado | 300 s | 60 | 21.843496 | 12/40 |
| Control baseline v2 | 120 s | 24 | 21.371626 | 4/16 |
| Sin noisy | 120 s | 24 | 9.033531 | 0/16 |
| LLM .001 s | 120 s | 24 | 20.255919 | 4/16 |
| Batch 3 | 120 s | 24 | 20.395026 | 2/16 |
| Poll .1 s | 120 s | 24 | 10.121223 | 1/16 |
| Eficiencia sin prioridad | 120 s | 24 | 21.773134 | 3/16 |
| Prioridad por último claim | 120 s | 24 | 9.289224 | 0/16 |

Warmup 30 s en todas. No se agregan las muestras de ventanas distintas ni
se usan los controles para acceptance. El descenso baseline v2→fair es
12.082402 s de p95, descriptivo de ejecuciones secuenciales, sin convertirlo
en un efecto causal aditivo universal. El control sin noisy y las trazas
por inbound confirman la interacción; no basta comparar dos percentiles.

Breakdown ordinario instrumentado original (n=40, segundos):

| Componente | p95 |
| --- | ---: |
| T1−T0 elegibilidad final | 18.028940 |
| T2−T1 siguiente observación | 2.824882 |
| T3−T2 selección | 3.454857 |
| T4−T3 inicio Organization | .008279 |
| T5−T4 tramo con adquisiciones | .139043 |
| T6−T5 retorno tras commit | .014638 |
| T6−T0 | 22.060689 |
| candidato→retorno tras commit | .146599 |

No sumar esos p95. Los siete componentes completos están por mensaje y
en distribuciones en `e4-diagnostic-baseline.analysis.json`. En poll .1 hay
dos observaciones T2 ausentes (n=14/16): se conservan null, sin imputación.
Las demás métricas contractuales conservan denominador n=24 o n=60.

Servicio READ original instrumentado, n=166 completados sobre todo el run,
incluyendo warmup/drain: claim registrado→primera admission p95 .357633 s;
dispatch1→respuesta1 .501604; respuesta1→tool completada .277151;
tool→admission2 .063536; dispatch2→respuesta2 .501009;
respuesta2→completed_at .336568. Claim registrado→completed_at p50 1.813074,
p95 2.032245, máximo 3.512549 s. Son relojes durables de claim/completion,
no una medición exacta desde el instante de commit. El servicio conserva
dos calls por READ; el journal T6 muestra el retorno después del commit.

Polling original: pausa configurada 1 s tras cada ciclo; intervalo real
start→start p95 3.050742 s, máximo 4.621660 s, incluyendo servicio. Hubo
379 polls, 213 sin progreso, 166 con progreso, 9 misses. Polls sin progreso
no son todos capacidad: el snapshot permite distinguir vacío, ineligible y
bloqueo; los conteos por rol y decisión están en el resumen.

Queue depth global, sumando orgs en cada uno de los 379 snapshots originales:
pending p50=110, p95=200, máximo=206; eligible p50=102, p95=197,
máximo=201; blocked p50=30, p95=192, máximo=200; claimable p50=0,
p95=181, máximo=201. La serie temporal derivada, sin otro ensayo, está en
`evals/e4-queue-global.analysis.json`. Es DIAGNOSTIC_ONLY y abarca warmup/drain.

Queue depth del observer: máximos por org sana pending/eligible/claimable
2/2/2; org noisy pending 204, eligible 201, blocked 200, claimable 201.
Son máximos en instantes distintos, no columnas que se puedan sumar como
un único snapshot. Cada poll publica la serie por org; sumar filas de un
mismo instante proporciona profundidad global. La exclusión B9C alterna
blocked/claimable mientras crece noisy. Sin starvation total: 60/60 sanos
tuvieron claim. No se exige drenar el backlog noisy en 20 s.

Lock waits: journal v1 mezcla SELECT Organization/Conversation con joins.
V2 separa tablas; en el control 120 s las cotas máximas de ejecución SQL son
Organization .013629 s, Conversation .047224, TurnWork .016644 y Message
.028332. Incluyen ejecución/IO; no son tiempos exactos de espera. Muestras
`pg_stat_activity` cada 5 s registran categorías reales de wait, publicadas
en cada colección v2; no detectan necesariamente waits breves entre muestras.
No se atribuye a locks el retraso de 22 s. Claim usa NO KEY UPDATE SKIP
LOCKED en Organization y UPDATE SKIP LOCKED en Conversation, más locks
TurnWork/Message del contrato; selección advisory no adquiere esos locks.

SQL anterior: OR de retries/lease recovery e inbound pending elegible,
NOT EXISTS org ocupada antes del LIMIT, DISTINCT, last_activity_at/pk,
batch 1. EXPLAIN sobre backlog original: 1.109 ms, top-N 25 KiB, hash
aggregate 195 filas, sin spill. Query online p95 9.375 ms. Índices
existentes y plan completo quedan en colección; no se añadió índice.
El plan fair diagnóstico tardó 2.119 ms; también usa WindowAgg por org,
subquery de último claim y límite tres. El plan del runtime se recogerá
después del perfil exacto; no se presenta el plan diagnóstico como producción.

## Validación E4 y límites de alcance

Nueve IDs nuevos `E4-SEL-01..07`, `E4-PROC-01..02`, con PostgreSQL real.
Las barreras alinean snapshots de dos procesos y sostienen autoridad tras
claim: uno falla ante org ocupada y reclama otra en el mismo poll; con una
sola org el segundo no crea TurnWork. También se prueba recuperación con
misma membership/work, token nuevo, intentos incrementados y fencing stale.
B9C se repite completo para crash/restart/expiry/último slot/safety.

Se seleccionaron 424 IDs adicionales por impacto: B9A, B9B y B9D completos
del histórico, clases de ownership/recovery B3, sender B4, safety B5,
consentimiento B7 y execution guard B8, más corpus B9E pertinente. Tres
shards usan bases independientes, sin ensayo temporal simultáneo. No es el
rerun integral B9E ni la regresión completa de sus 2384 IDs; estos quedan
como referencia congelada para la siguiente decisión formal. La unión de
IDs y resultados debe verificarse al cerrar, sin skips aceptados como verdes.

Los checks Django, makemigrations --check y migrate --check pasaron en
`evals/e4-checks.exit.json`; no hay migración E4. Resultado de perfil y
regresiones aún pendiente en este punto de la bitácora.

## Operación, rollback y riesgos

El selector no mantiene cupos en memoria ni reserva autoridad: la lista de
candidatos es advisory y cada claim sigue bajo Organization→Conversation→
TurnWork→Message. La historia `claimed_at` existente ordena orgs, y un
WindowAgg conserva antigüedad/pk dentro de cada una. No se cambia la ruta
inmediata B5 de guidance/takeover, ni admission B9B, ni publicación B3/B4.

Suplemento readonly de servicio: `evals/e4-diagnostic-baseline-commit-return.analysis.json`
reusa las mismas trazas y DB, sin repetir ni alterar el ensayo. Desde T6
retorno tras commit hasta la primera admission durable: n=166, p50 .189539,
p95 .271456, máximo .479892 s. T6→completed_at: p50 1.742013,
p95 1.943854, máximo 3.396954 s. Estos son los tramos pedidos desde commit,
separados de los deltas históricos desde `claimed_at`. Retorno es una
observación posterior al commit, no un hook del instante interno de PostgreSQL.

La herramienta de timing y los prototipos permanecen exclusivamente en
tests/eval; runtime no importa ninguno ni añade telemetry/labels.

El límite tres se aplica a intentos de candidatos de organizaciones
distintas sin progreso; con dos planners permite abandonar el primer
candidato perdido y mirar otras dos orgs en este perfil. Batch 1 sigue
ejecutando un máximo de un trabajo. En batches mayores se vuelve a consultar
después de cada éxito, se actualiza recencia durable y no se repite una
conversación en el mismo poll. Los misses terminan el ciclo tras ese límite,
sin busy loop. El límite no asegura progreso universal con más tenants,
locks prolongados ni bajo otra topología.

Rollback funcional: revertir solo el commit de runtime E4 recupera el
selector anterior, manteniendo TurnWork, lease/token/epoch, membership,
presupuesto admitido y outbox existentes. No borrar/recrear work, no
reembolsar calls ni resetting counters. No hay schema/cursor nuevo que
retirar ni backfill. El rollback restaura también la limitación de latencia
demostrada; conservar el límite N=1. La documentación/evidencia permanece.
Este encargo no hace rollout ni altera réplicas productivas.

Riesgos abiertos: margen del gate depende de fase de polling, debounce,
servicio y jitter del host; el p95 contractual no acota todos los máximos.
Noisy recibe más trabajo del que N=1 puede drenar; el backlog es durable,
no un throughput prometido. El subquery de recencia y WindowAgg deben
volver a medirse si crece el dataset/topología; no se autoriza un índice
anticipado. No se promete fairness fuerte ni starvation imposible fuera
del perfil. Las dos llamadas del loop, límite 30/18000/600, no-refund,
consentimiento y guard siguen siendo condiciones de cualquier promoción.
La fuente congelada declara una llamada básica en su JSON pero el runner
histórico y la metodología registran dos reales para READ: se mantiene la
desviación conocida y no se reescribe el perfil para ocultarla.

La activación sigue PENDING_ACTIVATION_REQUIREMENTS. B0 cerrado, B7B=False,
execution flags={}, grants productivos vacíos y cero clínicas activadas son
estado autorizado/configuración del repositorio; no una inspección remota
de producción. Las organizaciones creadas por seed_domain son fixtures.
No hay deploy, acceso a Meta real ni trabajo E1/E2/E3/E5 o P-A/P-B.

## Cierre de regresión del candidato

Runtime y tests: commit `7e5aa9e8cec4f6fa08ecd92870c19560c91bb469`, rama
`codex/e4-capacity-scheduling`. Checks: exit 0. Targeted: 36/36 (9 nuevos,
27 B9C); shards adicionales 115/115, 174/174 y 135/135. Unión 460 IDs,
cero fallos, errores, skips o xfail. Cada inventario/resultado/per-ID
passed journal y source hashes está versionado con prefijo `evals/e4-*`.
La secuencia temporal post-fix comienza únicamente tras ese cierre.

## Recibos post-fix del candidato, sin reapertura B9E

Runner original congelado `b9e_profile.py`, código de runtime en commit
`7e5aa9e`, PostgreSQL propio puerto 35441, sin observer diagnóstico durante
acceptance. Las colecciones readonly se realizan después de cerrar cada
run. Se preservan 30/300 s, dos planners, sender, batch 1/poll 1 s, las
latencias y todos los fixtures/denominadores originales. No se usa smoke.

Base `E4-LOAD-01`, `evals/e4-postfix-base.json`:
n=60, p50=8.532017, p75=8.994736, p90=9.702353, p95=9.844989,
p99=máximo=10.387972 s, missing=0. Claim PASS con margen .155011 s
(1.55011% del threshold): estrecho, sin inventar un buffer obligatorio.
Safety dispatch n=20, p95=máximo=3.366502 s; outbox n=158,
p95=2.578890 s, máximo=3.366502, missing=0. Todos los gates base verdes.
Los 40 ordinarios separados tienen p95=10.104683 s: se publica ese
subgrupo sin sustituir el gate congelado de los 60 sanos, que incluye safety.
No se garantiza máximo ≤10 s. Elegibilidad final ordinaria p95=7.973035 s:
ya no aparece la extensión de ~10 s en la cola alta de este run.

Colección base: cero cross-tenant Message/TurnWork/LLMCall, cero presupuesto
excedido, cero FAILED y cero sanos sin claim, máximo activo observado 1.
READ completados n=170 (todo el run): dos calls por trabajo; servicio desde
claimed_at p50=1.686061, p95=2.146376, máximo=3.168214 s.
Plan real del selector nuevo sobre backlog: EXPLAIN ANALYZE 1.456 ms;
SQL e índices existentes conservados en la colección, sin índice nuevo.
Este PASS de base no es PASS integral de PROFILE-BETA-1 ni cierre B9E.

LLM bloqueado `E4-LOAD-02`, `evals/e4-postfix-blocked_llm.json`:
n=60, p50=8.512117, p75=8.967759, p90=9.901110, p95=10.497891,
p99=máximo=18.011877 s, missing=0. **Claim FAIL**, exceso .497891 s.
Los 40 ordinarios tienen p95=10.572319 s, máximo=18.011877 s;
elegibilidad final ordinaria p95=7.972231, máximo=17.941190 s.
Safety dispatch n=20, p95=máximo=3.751851 s: PASS ≤5 s.
Outbox n=149, p95=2.705151, máximo=3.751851 s, missing=0:
descriptivo, sin inventar un gate de outbox en esta variante.

La colección bloqueada registra cero violaciones cross-tenant en
Message/TurnWork/LLMCall, cero budget violations, cero FAILED y cero sanos
sin claim; máximo activo observado por org=1. READ completados n=165,
dos calls por trabajo: servicio desde claimed_at p50=1.748513,
p95=2.436325, máximo=11.043208 s. Primera admission p95=.479492 s.
EXPLAIN ANALYZE del selector actual=3.065 ms, sin índice nuevo.

Cada variante post-fix tuvo una sola corrida completa, sin observer
diagnóstico, con tres procesos OS y tres backends PostgreSQL distintos.
Las ventanas de medición son base 18:39:58.694565–18:44:58.694565 UTC y
bloqueado 18:46:25.488849–18:51:25.488849 UTC del 2026-09-30.
No se buscaron repeticiones favorables después del FAIL.

El wrapper detuvo automáticamente la secuencia tras cerrar receipt y
colección bloqueados. `E4-LOAD-03` meta_slow, `E4-LOAD-04` duplicate y
`E4-LOAD-05` saturation no se ejecutaron ni tienen recibo del candidato.
Los PASS históricos de esas variantes no se atribuyen al código E4.
La validación `evals/e4-candidate-validation.json` devuelve exit 1/PARTIAL
exactamente por blocked_llm FAIL y esas tres ausencias; inventarios,
hashes de las fuentes ejecutadas, checks, privacidad e histórico pasaron.
Los 46 IDs del corpus B9E pertinente están cubiertos dentro de los 460.

## Decisión final y capacidad

**E4 no se acepta como solución suficiente. STOP para nueva decisión, según
§36 del encargo.** La prioridad elegida mejora la distribución frente a los
FAIL históricos, pero el gate bloqueado sigue >10 s. No se encadena otro
mecanismo, no se cambia el perfil ni se reabre formalmente B9E.

La cota μ≤.9091/s frente a λ=1/s demuestra crecimiento de backlog noisy
con N=1 y las dos llamadas de esta ruta. No demuestra imposibilidad del
SLO sano para toda solución permitida. Tampoco este único candidato fallido
prueba que sea necesario cambiar arquitectura o contrato. La siguiente
decisión debe evaluar el resultado sin asumir esa conclusión; cualquier
cambio de perfil/requisito requiere autoridad explícita. Un rerun formal
B9E desde este candidato no se recomienda como vía de aceptación.

No se observó starvation sana completa: 60/60 sanos reclamados en cada
perfil post-fix. Lost work se mide aquí como sanos sin claim y outbound
sin dispatch del denominador: ambos cero. La recuperación, membership y
rechazo de progreso stale se verificaron en regresión, no como un contador
general de pérdidas. Los receipts retienen un PROCESSING al corte y el
backlog noisy durable; el runner termina procesos en una ventana acotada.
No se presenta ese corte como drain completo ni como prueba universal de
ausencia de pérdidas. El test E4-SEL-05 verifica durabilidad tras misses.

## Limpieza y preservación

`evals/e4-cleanup.json` confirma cero bases de prueba propias restantes,
servidor propio detenido, pg_isready exit 2 en 35441, directorio E4 y log
raw eliminados, y cero procesos Python E4 restantes. Antes del stop, el
script verificó cero prepared transactions, cero clientes de pruebas y
ausencia de procesos de su árbol después de detener PostgreSQL. No hubo
drop forzado ni terminación de clientes ajenos. Los procesos de la otra
instancia local (incluido PID 7136) permanecieron vivos y se registran.
Se preservan runtime Python y binarios PostgreSQL previos; no eran propios.

La primera limpieza llegó al paso de hash después de verificar/drop de las
bases permitidas y stop, y terminó exit 1 por `Get-FileHash` no disponible.
La reanudación offline `evals/e4-cleanup-resume.ps1` usa SHA256 .NET,
revalida instancia detenida y la ruta absoluta antes de Remove-Item, y
cierra el recibo con exit 0. El preflight original no se había persistido:
no se inventa su lista de nombres/PIDs. El wrapper principal quedó corregido
para guardar preflight antes de drop en usos futuros.

SHA256 del log raw propio cerrado, antes de borrarlo:
`2d33271fc50dda2a28c313816691f5b0e383adc91c88f485c4409bf933957542`.
Solo el lifecycle técnico filtrado se conserva en
`evals/e4-postgresql-lifecycle.json`; SQL de casos negativos podría contener
contenido de fixtures y no se versiona. El manifest final, generado con
artefactos cerrados, atestigua hashes y bytes históricos; no incluye su
propio hash ni pretende certificar un PASS.

El manifest v2 conserva SHA256 de cada fuente ejecutada y del blob en el
commit de runtime. `worker.py` se ejecutó con CRLF y Git lo almacena con LF;
la única diferencia es esa normalización de saltos, verificada byte a byte.
No se alteró la fuente entre las 460 pruebas y los perfiles. Los tres otros
archivos del commit de runtime coinciden exactamente. Todos los artefactos
de eval mantienen sus bytes en Git. El manifest worktree y el integrity
precommit se conservan como snapshots anteriores a esta aclaración;
el manifest v2 y el integrity final son las autoridades de cierre.

Se preservaron los cuatro cambios preexistentes y, al cierre, se detectó
también una modificación externa de `skills-lock.json`, excluida de E4.
No se restauró ni incluyó ninguno en los dos commits del encargo.

## Reporte final: los 45 campos solicitados

| # | Campo | Resultado |
| ---: | --- | --- |
| 1 | Estado E4 | PARTIAL; diagnóstico confirmado, candidato insuficiente, tres variantes sin evaluar por STOP. |
| 2 | B9/B9E | B9 IN_PROGRESS; B9E FAIL; PROFILE-BETA-1 integral FAIL; B9A/B/C/D COMPLETED. |
| 3 | Baseline | 52e1663881653efe6dcaf1d264aaac224c89a7ac, exacto antes de modificar runtime. |
| 4 | Commits | Runtime/tests 7e5aa9e8cec4f6fa08ecd92870c19560c91bb469; segundo commit documental/eval que contiene este reporte. Ambos en codex/e4-capacity-scheduling. |
| 5 | Reproducción | E4-REPRO-01, original 30/300 s: p95 22.141079 s, compatible con 21.725759 histórico; FAIL reproducido. |
| 6 | Distribución claim | Repro p50/p75/p90/p95/p99/max: 8.540524/11.526504/21.482832/22.141079/22.585115/22.585115 s, n=60. Base y bloqueado exactos arriba, n=60 cada uno. |
| 7 | Breakdown | p95 T1−T0/T2−T1/T3−T2/T4−T3/T5−T4/T6−T5: 18.028940/2.824882/3.454857/.008279/.139043/.014638 s; T6−T0=22.060689 s; no sumar p95. |
| 8 | Servicio | T6→admission p95 .271456 s, T6→completion 1.943854 s; dispatch1/response1→tool/tool→admission2/dispatch2/response2→completion: .501604/.277151/.063536/.501009/.336568 s. Dos relojes diferenciados arriba. |
| 9 | Queue | Serie global 379 polls y por org; global pending p95/max 200/206, eligible 197/201, blocked 192/200, claimable 181/201. Org sana max pending/eligible/claimable 2/2/2; noisy 204/201/201. |
| 10 | Calls/work | Exactamente 2 por READ completado medido: selección tool y generación de respuesta; no retirar segunda llamada. |
| 11 | Selector actual | Org menos recientemente reclamada; un candidato por org; busy exclusion antes del límite; hasta tres orgs tras misses; reselección tras éxito; claim durable original. |
| 12 | Plan SQL | Original 1.109 ms; runtime post-fix base 1.456 ms, bloqueado 3.065 ms. WindowAgg/Subquery; índices existentes; sin migración. |
| 13 | Polling | Pausa 1 s conservada; baseline start→start p95 3.050742 s, max 4.621660; 213/379 sin progreso, 166 con progreso. |
| 14 | Lock waits | Categorías PG muestreadas cada 5 s; SQL como cota, no espera exacta. V2 máximos Organization/Conversation/TurnWork/Message .013629/.047224/.016644/.028332 s. No evidencia de causa de 22 s por locks. |
| 15 | Hipótesis | H1–H7 con evidencia, límites, contribución y experimento en tabla anterior. Interacción H7 confirmada; H2/H3/H6 amplifican; H4/H5 no justifican tuning. |
| 16 | Ablations | No noisy, LLM .001, batch 3, poll .1, selección eficiente, recencia fair y control baseline v2; DIAGNOSTIC_ONLY, no acceptance. |
| 17 | Root cause | ROOT_CAUSE_CONFIRMED: preferencia global noisy + servicio/polling pierde ventana 8→10 y nuevo inbound extiende elegibilidad a ~18 s. |
| 18 | Confianza | Alta para esta interacción y topología; no garantía universal ni prueba de imposibilidad del SLO sano. |
| 19 | Fix | Prioridad por claim durable y fallback acotado dentro de E4; implementado como candidato, no aceptado como suficiente. |
| 20 | Alternativas | Eficiencia sola, batch/poll/provider tuning no resolvieron controles; índice sin evidencia; N>1, eliminar call o cambiar contrato no autorizados. |
| 21 | B3 | Ownership, lease, epoch, fencing, membership/cursor y primitiva atómica conservados; recuperación y stale verificadas. |
| 22 | B5 | Precedencia humana y ruta inmediata safety/takeover conservadas y cubiertas por regresión. |
| 23 | B9B | 30 calls, 18000 tokens reservados, 600/call, admission durable y no refunds; corpus completo pertinente aprobado, budget violations 0. |
| 24 | B9C | N=1; lock order original; máximo activo observado 1; tests B9C completos, último slot y colisiones aprobados. |
| 25 | B7/B8 | Consentimiento, execution guard, domain service y evidence conservados; tests afectados aprobados. |
| 26 | Tenant isolation | Cross-tenant Message/TurnWork/LLMCall 0 en ambos post-fix; regresión multiproceso explícita. |
| 27 | Multiprocess | Dos planners OS/PG distintos con barreras en E4-PROC; perfiles exactos tres procesos/backends distintos incluyendo sender. |
| 28 | Crash/restart | B9C crash, expiry, stale, restart y slot repetidos; E4-SEL-06 conserva work/membership y renueva token; no afirmación universal fuera del corpus. |
| 29 | Perfil exacto | Runner original y v1 congelados, 30/300, batch 1, pausa 1, dos planners/sender, latencias y denominadores intactos; base y bloqueado solamente. |
| 30 | Base p95 | 9.844989 s PASS ≤10; margen .155011 s; max 10.387972 s; subgrupo ordinario p95 10.104683 s publicado. |
| 31 | Bloqueado p95 | 10.497891 s FAIL ≤10; exceso .497891; máximo 18.011877 s; STOP. |
| 32 | Otros gates | Safety base 3.366502/bloqueado 3.751851 s PASS ≤5; outbox base 2.578890 PASS ≤5. Meta lento/duplicate/saturation NOT_EVALUATED. |
| 33 | Repeticiones | Una corrida exacta por variante post-fix; no repetición tras FAIL. Controles diagnósticos secuenciales/ventanas distintas no se agregan. |
| 34 | Corpus E4 | IDs E4-REPRO, DIAG/ABL, CAUSE, FIX, SEL, PROC, REG, LOAD y STOP; e4-corpus.json y recibos separados. |
| 35 | Regresión | 460 únicos, todos aprobados: 36 targeted + 115/174/135; sin skips/xfail/errores/fallos. 46 heredados pertinentes cubiertos. 2384 históricos no rerun formal. |
| 36 | Checks | Django/check, makemigrations --check y migrate --check exit 0; compile de tooling y diff --check; sin schema nuevo. |
| 37 | Infra limpia | DBs propias restantes 0, prepared/clientes 0 verificados antes de stop, PG propio detenido, puerto sin respuesta, data/log borrados; recibo v2 detalla reparación offline. |
| 38 | Privacy | Timing sin prompt/response/phone/pet/owner/clinical text; escaneo de artefactos cerrados sin hallazgos del corpus; solo metadatos técnicos. |
| 39 | Observability | Permanece en tests/eval; runtime no importa tooling ni incorpora labels de alta cardinalidad. |
| 40 | Riesgos | Gate bloqueado fallido, margen base estrecho, jitter/debounce, backlog noisy inevitable, coste del selector a escala no medido, waits breves no observables por muestreo. |
| 41 | Preexisting | Cuatro cambios iniciales preservados/excluidos y skills-lock.json externo excluido; ningún restore ajeno. |
| 42 | Production gates | B0 cerrado, B7B=False, execution flags={}, release grants vacío, PENDING_ACTIVATION_REQUIREMENTS; estado autorizado del repo, sin consulta remota. |
| 43 | Active clinics | 0 clínicas activadas; solo fixtures locales. |
| 44 | No deploy | Sin deploy, sin Meta real, sin E1/E2/E3/E5 ni P-A/P-B. |
| 45 | Recomendación | STOP para nueva decisión; no rerun formal B9E como aceptación de este candidato, no cambio de perfil/arquitectura/contrato dentro de este encargo. |
