# B9E — aceptación integral de B9 / PROFILE-BETA-1

Primeros ensayos: 2026-09-29; cierre y recuperación de infraestructura:
2026-09-30 (America/Mexico_City). Baseline obligatorio y runtime evaluado:
`21cf91c0ae0242f83675dc9691c600bf4d63e5ab`. Los thresholds se congelaron
antes de la primera carga en `9147928` y
[`profile-beta-1-v1.json`](evals/profile-beta-1-v1.json). No hubo fix de runtime,
despliegue, proveedor real ni clínica activada.

| Plano | Decisión |
| --- | --- |
| B9E | Aceptación ejecutada con resultado **FAIL**; evidencia y límites documentados |
| PROFILE-BETA-1 técnico | **FAIL**: `B9E-LOAD-01-CLAIM` y `B9E-LOAD-02-CLAIM` exceden 10 s; el turno básico real usa dos llamadas LLM frente a una modelada |
| B9 canónico | **IN_PROGRESS**: no se declara cierre integral ni se confunde el reporte de contención permitido por §7:723 con un perfil verde |
| Activación operacional | **PENDING_ACTIVATION_REQUIREMENTS**; 0 clínicas, 0 grants productivos, WRITE autónomo OFF |

## Contrato, alcance y decisión de carga

La autoridad es el [plan canónico](plan-implementacion-auditoria-agente-whatsapp-2026-09md),
§7:710–734 y las invariantes §4 I01–I14. La
[matriz](evals/profile-beta-1-requirements-matrix.md) asigna R01–R15 a B9A–D
o B9E y documenta prueba, frontera y estado. El
[corpus versionado](evals/profile-beta-1-corpus-v1.json) asigna IDs estables a
READ, las cinco WRITE, gate B9D, presupuesto, concurrencia, safety y FI. Los
recibos históricos B9A/B/C/D dan procedencia; la selección exacta de 46 IDs
del candidato está en [`b9e-corpus-selected.json`](evals/b9e-corpus-selected.json).

El perfil congelado fija PostgreSQL aislado (`fsync=on`,
`synchronous_commit=on`), dos planners de batch 1, un sender y polling máximo
1 s. Tras 30 s de warmup mide 300 s: dos organizaciones sanas reciben un
inbound/10 s cada una; la ruidosa uno/s en conversaciones diferentes. El
proveedor controlado modela una llamada LLM de 0,5 s, READ de 0,1 s y Meta de
0,2 s por turno básico. Las inyecciones independientes son LLM ruidoso bloqueado
10 s, Meta de 2 s, webhook duplicado y saturación con guidance detectable en
recepción. El método, reloj, denominadores, manejo de faltantes y alcance del
fake están en la [metodología](evals/profile-beta-1-methodology.md).

Los gates fijados **antes de mirar resultados** son: en base y LLM bloqueado,
p95 inbound sano persistido→claim ≤10 s y guidance persistida→admisión de
dispatch ≤5 s; en base, p95 outbox committed→admisión de dispatch ≤5 s. Meta
lento exige durabilidad, concurrencia acotada y cero retry ciego, sin heredar el
SLO base. Cero violación crítica en corpus/FI; ningún gate omitido/skipped es
verde. B9B mantiene máximo 30 llamadas y 18.000 tokens de salida reservados por
TurnWork, 600 por llamada; B9C máximo un TurnWork PROCESSING por organización.
El uso desconocido se contabiliza como desconocido, no cero. No hay pricing
monetario ni extrapolación a carga o modelo reales.

## Primer ensayo y causa

El primer run base se ejecutó contra B9D sin cambio de runtime. Se conserva
íntegro en [`b9e-first-base.json`](evals/b9e-first-base.json), logs por proceso
y [análisis escrito antes de un eventual fix](evals/b9e-first-run-analysis.md).
Su runner tenía SHA-256
`9244e6500f28f76d080267a2986adf8420eaa51e94b360c3435e0cf6c237ee1a`.
No se hizo fix de runtime; las otras variantes ajustaron solo sus gates de
inyección y cadencia de safety. Por ello el primer run sigue siendo el run final
de este candidato fallido, y **no existe recibo de rerun verde**.

| Variante | Gate y observación | Resultado |
| --- | --- | --- |
| Base | Claim sano n=60, p95 **21,725759 s**, máximo 22,371192 s, 0 faltantes (límite 10 s); safety n=20, p95 2,778290 s (≤5); outbox n=171, p95 2,386334 s (≤5) | **FAIL** claim |
| LLM bloqueado | Claim sano n=60, p95 **22,048948 s**, máximo 22,920572 s (≤10); safety n=20, p95 2,936003 s (≤5); un timeout ruidoso admitido, usage desconocido=1, fallo=1, retry=1 | **FAIL** claim |
| Meta lento | 360 inbound, 65 outbounds pending + 1 sending al cierre de observación, sin pérdida; máximo un intento y una admisión activa por org. La latencia de 114 s safety es diagnóstica, sin SLO de esta variante | PASS del gate propio |
| Webhook duplicado | 17 duplicados firmados devolvieron la misma fila, sin error ni efecto duplicado | PASS del gate propio |
| Saturación safety | 60 guidance durante medición; p95 dispatch 2,172611 s, máximo 2,374721 s, con cola observada de 184 inbound pending | PASS del gate propio |

Los [cinco recibos y sus hashes](evals/b9e-load-summary.json) conservan muestras,
máximos, errores, colas y PIDs. Hubo 360 inbound por variante, max activo por
organización observado=1, 0 filas de mensaje cross-tenant, 0 violaciones de
presupuesto y máximo dos llamadas/1.200 tokens por TurnWork. Los 354 `LLMCall`
del base para 177 trabajos READ terminados muestran la desviación: el planner
real llama primero para escoger tool y otra vez para responder tras la READ.
El fake no saltó el planner ni inventó una READ. Esta ejecución mide una ruta
real más costosa que el modelo de una llamada, y no acredita reproducir
exactamente esa hipótesis; tampoco autoriza convertir 21–22 s en PASS.

La cola ruidosa llegó a 198–200 pending en base/bloqueado. Los planners
seleccionan trabajo por antigüedad global en batch 1; el límite B9C impide dos
trabajos activos simultáneos de la misma organización, pero no promete fairness
fuerte. Esta combinación de tasa fijada, carga efectiva de dos LLM y orden de
cola es consistente con el retraso observado; no aísla por sí sola una causa
que autorice un patch de scheduler. No se demostró un defecto de autorización,
durabilidad o límite B9A–D que habilite un fix mínimo de runtime en B9E. La vía
canónica §7:718/723 es decidir y versionar otro alcance/carga permitido, o
encargar E4 por esta medición y repetir la aceptación. B9E no implementa E4 ni
rebaja el umbral congelado.

## READ, WRITE, EVAL, COST, SCALE y seguridad

[La revisión de las diez READ](evals/profile-beta-1-read-scope.md) distingue
las tres públicas y tres personales del candidato de cuatro fuera de él. READ
pública usa tenant y fuente de dominio sin identidad/consentimiento, y debe
funcionar con WRITE cerrado; READ personal exige `confirmed_in_chat` vigente,
owner/pet binding, revisión, conversación y tenant. Un teléfono compartido o
reciclado no equivale a identidad física fuerte. El release B9D declara el
alcance READ que se podría aprobar, pero su gate de ejecución se aplica a
WRITE; no se trasladó por intuición a READ. B0/AgentSettings/política previa
siguen vigentes. Aprobar READ real también requiere evidencia operacional.

Las cinco WRITE candidatas son CREATE_APPOINTMENT, RESCHEDULE_APPOINTMENT,
CANCEL_APPOINTMENT, CONFIRM_ATTENDANCE y REGISTER_PET. El corpus seleccionado
usa el harness B9A para webhook firmado→Message→TurnWork→worker/planner→
propuesta/outbox→respuesta causal→B7B→B8A→servicio de dominio→ledger/receipt→
outbound. Los tests de componente B9B/C/D son soporte, nunca reemplazo del
camino E2E. Para negativa se exigen ausencia de efecto/provider prohibido,
motivo y evidencia durable, no solo HTTP 200 o una excepción. Los cinco gates
B9D se prueban con otras condiciones test abiertas y organización legacy no
aprobada. Estas fixtures son `TEST_EVIDENCE`, no grants reales.

EVAL determinista utiliza proveedor y Meta controlados, no LLM/WhatsApp reales.
El corpus cubre selección/grounding acotados, causalidad de confirmación,
rechazo/defer, handoff, tenant, efectos y orden de eventos. COST mide admisiones,
reservas, usage desconocido, retry y agotamiento bajo witness; no convierte
NULL en cero ni reembolsa un timeout. SCALE comprueba N−1/N/N+1 para N=1,
organizaciones independientes, sender separado, guidance durante bloqueo y
Meta lento. Las métricas temporales y el corpus prueban solamente los ejemplos
medidos, no exactitud clínica universal. La [matriz FI](evals/profile-beta-1-failure-injection.md)
cubre diez cruces, incluidos crash, HTTP tardío, lease stale, gate revocado,
takeover, duplicados y rollback SQL. Una respuesta externa tardía no adquiere
autoridad nueva de publicación/operación; el socket ya admitido puede terminar
tarde y no hay exactly-once externo.

Los eventos existentes de worker, sender, budget, concurrencia, autorización,
ejecución, beta gate y handoff permiten investigar con TurnWork, outbox,
ConversationOperation, AuthorizationEvidence, ToolExecution, LLMCall y
los inspectores readonly de B4/B7/B8/B9B/B9D. Los logs B9E se examinaron por
prompt, texto clínico, teléfono y secretos, sin coincidencias en los patrones
de la carga. No se añadieron labels con PII ni plataforma de observabilidad.

## Activación, riesgos y preservación

La [lista operativa](evals/profile-beta-1-operational-readiness.md) tiene cero
`SATISFIED_REAL`. Antes de considerar una clínica real faltan: seleccionar y
aprobar piloto, capacidades y tasa; responsable/cobertura de Inbox; revisión
veterinaria del protocolo/corpus y simulacro de recepción/claim/resolución;
responsable clínico; revisión P-A y mecanismo P-B para categorías/plazos
comprometidos; fallback/escalamiento alterno probado; aceptación del riesgo de
teléfono compartido/reciclado; evaluación real del candidato al promover
autonomía; cutover/rollback por capability y, primero, un perfil técnico verde.
E3/E4/E5 no son requisitos universales del alcance actual, aunque E4 es una
opción posterior justificada por el fallo medido. Ninguna aprobación humana se
fabricó mediante fixture.

H01/H02/H05/H06/H08/H12/H13/H18/H20 tienen mitigación técnica acotada a las
rutas y tests del corpus, sin cierre universal de consentimiento, semántica,
identidad o referencias libres. H03 y H04 conservan dependencia de protocolo,
supervisión y simulacro real; H17 depende de P-A/P-B. H07 conserva incertidumbre
externa, H09–H11/H14/H15 sus límites de beta, y H16/H19 quedan **OPEN** para
el perfil por el gate de latencia fallido. No se atribuye a B9E cierre de E1–E5,
P-A/P-B, fairness fuerte, autenticación física, delivery remoto ni RLS.

El rollback tras una eventual promoción debe retirar/reducir grant con pausa y
drain compatible; cerrar B0/B7B/flags del alcance; identificar trabajos y HTTP
admitidos; esperar o clasificar incertidumbre; conservar sender y fencing;
reconciliar efectos ya committed antes de reabrir. Preservar Message, TurnWork,
LLMCall, ConversationOperation, AuthorizationEvidence, ToolExecution, efectos
de dominio y outbox. Nunca reintentar ciegamente un envío incierto. No se
ejecutó rollback productivo porque no hubo promoción.

## Reproducibilidad y límites del cierre

El [perfil](evals/profile-beta-1-v1.json) fija fuente/thresholds/inputs y el
[corpus](evals/profile-beta-1-corpus-v1.json) enlaza tests históricos por ID;
[`b9e_profile.py`](../backend/apps/agent/tests/b9e_profile.py) y
[`b9e_collect.py`](../backend/apps/agent/tests/b9e_collect.py) son runner y
colector. PostgreSQL 16.15 ejecutó workers/DB independientes; recibos por
variante guardan PIDs de sistema y backend, versiones, parámetros y hashes.
`DEBUG=False`, sin Sentry, Redis ni URLs de proveedores reales; `SECRET_KEY`
de test local. El candidato no altera schema ni defaults. `check`,
`makemigrations --check --dry-run` y `migrate --check` pasaron contra la DB
aislada, y `git diff --check` no encontró whitespace defectuoso.

La regresión histórica B9D (2384/2384 IDs únicos, cero pending) pertenece al
baseline `21cf91c`; **no** se presenta como rerun de este candidato. El plan
del encargo condiciona B9D/B9C/B9B/B9A/B0–B8E exactos y cero pending a que
PROFILE-BETA-1 esté verde. Como está FAIL, no se afirma que esas suites se
re-ejecutaron ni que los 2384 IDs están aceptados ahora. El corpus dirigido B9E
se reporta con su recibo separado. Los cuatro cambios preexistentes del usuario
(dos `DEPLOY_VPS_*` borrados y dos notas de auditoría/discrepancia untracked)
se preservan fuera de los commits B9E.

Decisión posterior: rechazar promoción de PROFILE-BETA-1; conservar el fallo y
proponer una nueva decisión de alcance/carga o trabajo E4 separado. Toda nueva
candidatura requiere perfil y thresholds versionados antes del run, repetición
completa y requisitos humanos reales. B0 productivo cerrado,
`AGENT_B7B_CONSENT_ENABLED=False`, `AGENT_OPERATION_EXECUTION_ENABLED={}`,
release vacío, cero clínicas y sin deploy.

El [corpus final dirigido](evals/b9e-corpus-final.json) contiene 46/46 IDs únicos
(42 históricos + 4 nuevos). El primer proceso dejó 43 `ok` durables y terminó
sin resumen final al perder PostgreSQL; los tres IDs pendientes se ejecutaron
exactamente en [`b9e-corpus-recovery.results.json`](evals/b9e-corpus-recovery.results.json),
3/3 verdes, cero failures/errors/skips/xfail. El corpus dirigido final tiene
cero pending; **2342 IDs históricos no se rerun** en este candidato. Se conserva
el error de infraestructura, sin reclasificar el primer proceso como íntegro.
Los diez FI están probados por sus IDs exactos; esto no repara la carga fallida.

La limpieza está registrada en [`b9e-cleanup.json`](evals/b9e-cleanup.json): ocho
bases test eliminadas, cero conexiones cliente/transacciones preparadas/locks en
espera antes del drop, cluster detenido, puerto 35439 cerrado y directorio
absoluto temporal validado y retirado. Los recibos/logs quedan en el repositorio.
R01–R15 se congelaron antes de carga; la tabla detallada I01–I14 se amplió después.
El hash del runner base original se conserva, pero no una copia byte a byte de
su fuente anterior a los ajustes de inyección. Son límites de procedencia que
también impiden atribuir al candidato un cierre integral reproducible perfecto.
La fuente final reproduce la ruta base y las cinco variantes documentadas.

## Reevaluación H01–H20 en el alcance demostrado

Los estados siguientes describen la evidencia acotada B9E y respetan los límites
del dossier. `PARTIALLY_MITIGATED` no revoca cierres técnicos históricos de una
subfase ni los convierte en cierre universal. Las referencias históricas que no
están en los 46 IDs siguen sin rerun en este candidato.

| Hallazgo | Estado B9E | Evidencia y residual |
| --- | --- | --- |
| H01 | PARTIALLY_MITIGATED | Cinco WRITE y corrección/causalidad reales; consentimiento estricto, sin autorización libre universal |
| H02 | PARTIALLY_MITIGATED | Pending no autorizable, proposal emitida y reply causal; aceptación Meta simulada, sin delivery externo garantizado |
| H03 | PARTIALLY_MITIGATED | Guidance prioritaria y rápida en corpus detectable; revisión veterinaria/protocolo real pendientes |
| H04 | PARTIALLY_MITIGATED | Handoff/takeover y evidencia honesta; cobertura, simulacro y fallback reales pendientes, E3 separado |
| H05 | PARTIALLY_MITIGATED | Éxito de cinco WRITE con evidencia propia y outbound; sin grounding o consejo clínico universal |
| H06 | PARTIALLY_MITIGATED | Crash/rollback/retry no duplican efecto local; sin exactly-once externo ni ensayo eléctrico |
| H07 | PARTIALLY_MITIGATED | Sender UNCERTAIN tras aceptación perdida y reconciliación; HTTP admitido puede terminar tarde |
| H08 | PARTIALLY_MITIGATED | Worker/epoch stale y takeover no adquieren autoridad nueva; no cancelación remota de socket |
| H09 | PARTIALLY_MITIGATED | READ pública con WRITE cerrado y personal sin verificar bloqueada; continuidad E1 fuera de alcance |
| H10 | PARTIALLY_MITIGATED | Contexto real recibido en harness; no nueva auditoría de todas las ramas de DTO B1 |
| H11 | PARTIALLY_MITIGATED | Causalidad y pending no visible; historia/referencias amplias no re-evaluadas completamente |
| H12 | PARTIALLY_MITIGATED | Binding/revisión y corrección en beta de un asunto; cierre B6 histórico acotado, E2 pendiente |
| H13 | PARTIALLY_MITIGATED | Operación exacta y referencias stale del corpus; referencias libres/históricas generales requieren E1 |
| H14 | PARTIALLY_MITIGATED | READ/API y outcome del corpus; RESULT parcial/error/vacío histórico no rerun completo |
| H15 | PARTIALLY_MITIGATED | Reply/action causal en pipeline; captions/media conservan límites B1/B5 históricos |
| H16 | OPEN | Harness y reporte evitan falso verde; perfil y regresión integral actual no están aceptados |
| H17 | OPEN | P-A/P-B aplicables y evidencia operacional real pendientes; B9E no los implementa |
| H18 | PARTIALLY_MITIGATED | Owner/pet/tenant/revisiones y gates actuales; teléfono compartido/reciclado e identidad física siguen residuales |
| H19 | OPEN | Presupuesto, N=1 y sender probados; carga fija incumple claim sano y modelo de una llamada |
| H20 | PARTIALLY_MITIGATED | Asistencia exacta E2E y ledger; negativa de pregunta/RESULT históricos no rerun completo |

## Índice de los 64 puntos de entrega solicitados

| Nº | Campo | Resultado o referencia |
| --- | --- | --- |
| 1 | Estado B9E | FAIL; aceptación terminada y evidencia preservada |
| 2 | B9 canónico | IN_PROGRESS |
| 3 | PROFILE-BETA-1 técnico | FAIL |
| 4 | Operational activation | PENDING_ACTIVATION_REQUIREMENTS |
| 5 | Baseline | `21cf91c0ae0242f83675dc9691c600bf4d63e5ab` verificado exacto antes de cambios |
| 6 | Runtime/fixes SHA | Mismo baseline; no fixes ni commit de implementación vacío |
| 7 | Docs/acceptance SHA | Commit que contiene este reporte/recibo; SHA entregado en respuesta final, como en B9D |
| 8 | HEAD final | Commit documental/eval entregado; verificable con `rtk git rev-parse HEAD` |
| 9 | Preexistentes | Dos `DEPLOY_VPS_*` borrados y dos notas untracked, preservados y excluidos |
| 10 | Matriz B9 | `profile-beta-1-requirements-matrix.md`, categorías finales por R/I |
| 11 | Gaps antes del run | Falta de perfil/corpus integral, revisión READ/readiness y artefacto candidato; dos LLM reales ya identificadas |
| 12 | Definición del perfil | `profile-beta-1-v1.json`, autoridad §7:721–725 |
| 13 | Thresholds | Freeze `9147928`, sin cambio tras resultados |
| 14 | READ_PUBLIC | Tres candidatas E2E; tres fuera; política/gates en READ scope |
| 15 | READ_PERSONAL | Tres candidatas E2E, una fuera; verificación, owner/pet, conversación y tenant |
| 16 | WRITE scope | Cinco kinds B8 adaptados; ninguna WRITE nueva |
| 17 | Cinco WRITE | CREATE/RESCHEDULE/CANCEL/ATTENDANCE/REGISTER E2E `ok` |
| 18 | B0 | Default WRITE cerrado; fixtures solo test |
| 19 | B7 | Consentimiento causal y proposal emitida preservados en IDs exactos |
| 20 | B8 | Guard, adapter, dominio y evidencia en cinco WRITE; flags default `{}` |
| 21 | B9A/EVAL | Corpus dirigido por HTTP/worker/sender, sin atajos ni Meta/LLM reales |
| 22 | B9B/COST | Boundary/exhaustion/timeout/unknown/recovery `ok`; carga máximo 2 llamadas/1200 reservados por trabajo |
| 23 | B9C/SCALE | N−1/N/N+1, dos planners y sender; máximo observado/org=1 |
| 24 | B9D/gates | Cinco WRITE no aprobadas denegadas y READY retirado no reusable |
| 25 | First run | `b9e-first-base.json` y logs inmutables |
| 26 | Fallos first | Claim sano 21,725759 s >10 y workload dos llamadas frente a una |
| 27 | Root causes | Capacidad/orden de cola y carga real más costosa; inferencia acotada, sin bug B9A–D demostrado |
| 28 | Fixes | Ninguno de runtime; no E1–E5/P-A/P-B |
| 29 | Final run | Mismo candidato fallido; cinco variantes completas, sin rerun tras fix inexistente |
| 30 | EVAL metrics | 46 IDs dirigidos `ok`; sin violación crítica en sus aserciones, sin score semántico universal |
| 31 | COST metrics | `b9e-load-summary.json`: todas admisiones/usage/retries/reservas; unknown=1 en timeout, no cero |
| 32 | SCALE metrics | P95/cola/máximos/denominadores por variante en resumen; claim base/bloqueado FAIL |
| 33 | Safety metrics | P95 base 2,778290 s, bloqueo 2,936003 s; saturación 2,172611 s, corpus acotado |
| 34 | Tenant metrics | Cero filas mensaje cross-tenant en cargas; negativo WRITE y READ scoped `ok` |
| 35 | Failure injection | FI-01–10 por tests exactos en corpus combinado |
| 36 | HTTP tardío | Lease vieja/takeover fenced, sin autoridad local nueva; socket no cancelado físicamente |
| 37 | Handoff/takeover | Silencio human_active y takeover antes de efecto/durante LLM `ok` |
| 38 | Sender uncertainty | Kill después de aceptación, UNCERTAIN y ausencia de retry ciego `ok` |
| 39 | Duplicates | Dos procesos HTTP, confirmación/efecto y 17 webhooks de carga deduplicados |
| 40 | Corpus final | `profile-beta-1-corpus-v1.json` y `b9e-corpus-final.json` |
| 41 | Reproducibilidad | Config/inputs/hashes, fuente final, comandos; límites de snapshot primero/matriz detallada declarados |
| 42 | PostgreSQL/PIDs | 16.15, fsync/sync on, tres procesos por carga y backend PIDs en recibos; lifecycle recuperado |
| 43 | B9D regression | Seis IDs dirigidos; 75/75 histórico referenciado, full exact actual no ejecutado por perfil FAIL |
| 44 | B9C regression | Siete IDs dirigidos; 27/27 histórico referenciado, full actual no declarado |
| 45 | B9B regression | Cuatro IDs dirigidos; 46/46 histórico referenciado, full actual no declarado |
| 46 | B9A regression | Veinte IDs E2E/processes dirigidos; 45/45 histórico, full actual no declarado |
| 47 | B0–B8E regression | Cinco negativos dirigidos previos; full exact condicionado a perfil verde no ejecutado |
| 48 | IDs únicos | 46 tests exactos actuales (42 históricos +4 nuevos), además cinco IDs de carga; no se suman aliases FI |
| 49 | Pending/skips/xfail | Corpus dirigido pending=0, skips=0, xfail=0; 2342 históricos sin rerun, no zero-pending integral |
| 50 | Checks | Django check, makemigrations check/dry-run, migrate check y diff check verdes |
| 51 | Infra limpia | `b9e-cleanup.json`, ocho DBs borradas, cluster/directory retirados y puerto cerrado |
| 52 | Observabilidad | Eventos worker/sender/budget/concurrency/auth/execution/beta/handoff existentes, sin labels PII nuevos |
| 53 | Inspectores | B4 outbound, B7/B8 admin readonly, B9B budget, B9C snapshot y B9D beta; ninguna mutación de emergencia |
| 54 | Security/privacy | Proveedores controlados, scan de logs sin patrones PII/secretos; no cambios de accounting productivo |
| 55 | H01–H20 | Tabla anterior, cierre solo dentro de evidencia, H16/H19 OPEN |
| 56 | Residuales | Otra carga/modelo, deriva, identidad débil, clínica, proveedor, cobertura, fairness, snapshot primero |
| 57 | Operacional satisfecho | Cero SATISFIED_REAL |
| 58 | Operacional pendiente | Lista readiness con evidencia real/owner/acción requerida |
| 59 | Clínicas | 0 activadas |
| 60 | Gates productivos | B0 cerrado, B7B False, execution flags `{}`, release grants vacío; no consulta a producción |
| 61 | Rollback | Pausa/drain/corte compatible, conservar ledger/outbox/contabilidad, reconciliar incertidumbre |
| 62 | Deploy | Ninguno |
| 63 | Commits | Freeze `9147928`; commit documental/eval final. Cuatro preexistentes excluidos |
| 64 | Recomendación | Rechazar promoción del perfil; nueva decisión de alcance/carga o E4 separado y gate repetido |
