# B9C — Concurrencia de TurnWork por organización

Estado: **COMPLETED técnico del hito interno B9C**. B9 canónica: **IN_PROGRESS**.
Baseline: `e9792c09e5830f058e8f143db7f4fcd93eef03fe`.
Implementación: `14e706685a020cff6113a85bad906f7998af8ecd`. Cierre documental: el commit que contiene esta acta.
Production activation: **PENDING_ACTIVATION_REQUIREMENTS**. No deploy ni activaciones.

## Contrato e implementación

La [matriz previa](contrato-concurrencia-b9c.md) identifica el alcance R04/R12
del plan canónico leído completo. El [ADR](decisions/2026-09-27-b9c-turnwork-concurrency.md)
justifica la exclusión transaccional organizativa sin segunda autoridad ni tablas.
El claim B3 conserva lease, token, epoch, miembros, cursor e intentos; B9B conserva
contabilidad durable. La unidad es autoridad local committed, no sockets remotos.

El selector evita que backlog de una org ocupada esconda otras antes del corte de
lote. Safety detectable en recepción completa trabajo/caso/guidance atómicamente,
sin planner/LLM/tools/HTTP ni segundo PROCESSING committed. SQL rollback conserva
inbound mediante fallback existente; misma conversación con trabajo no terminal
mantiene continuación B5. Sender y takeover tienen autoridad independiente del cupo.

La configuración de Compose fija dos planners secuenciales y un sender con poll
1 s. Es configuración de release, no despliegue realizado ni cupo global en DB.
No scheduler, rate limiting, estado, tabla, campo, migración ni capacidad nuevos.
No autoscaling implícito ni garantía de fairness fuerte; mejoras E4 requieren medición.

## Método y ejecución

PostgreSQL 16.15 local aislado, 127.0.0.1:35437, rol b9c, fsync y
synchronous_commit ON. Python 3.13/Django 6.0.5 del entorno bloqueado B8B.
Runner exacto B8E/B9A con inventories, passed journals, resultados y hashes;
procesos Python/PG independientes, barreras fuera del proceso que muere.
Proveedores fake en fronteras del harness, sin mocks del claim/locks/runtime.
Artefactos: `C:/Users/LAP/AppData/Local/Temp/b9c-evidence`.

Se ejecutó B9C primero, luego B9B exacto y B9A exacto, después particiones
disjuntas de la regresión histórica. Ningún ID se elimina para obtener verde.
El runtime coincide con los hashes registrados. Solo cambió second_operation
en cuatro módulos de pruebas B8; sus hashes anteriores se reconstruyeron exactamente
al invertir el diff conservando CRLF/LF y se comparó el resto del AST. Esos 118 IDs
de procesos se repitieron completos, recuperando por ID las interrupciones. Compose tiene hash propio y prueba de
topología. El recibo no suma repeticiones ni preliminares.

### Incidencias conservadas

functional1: 16/17; detectó el gap de safety bajo saturación, corregido.
functional2: 17/18; la inyección SQL funcionó, pero el test esperaba excepción
hacia HTTP pese al fallback existente. Se corrigió para comprobar rollback,
inbound pendiente y único claim. processes1: 8/8 preliminares, anteriores al
último caso SCALE-02 y a instrumentación final. functional3/processes2 fallaron
antes de tests por clúster detenido; functional4/processes3 quedaron interrumpidas
durante cambio de permisos del entorno. Sus logs/journals y hashes se preservan.
No se intentó eludir sandbox. Al restablecerse el entorno el 28-09, PostgreSQL
recuperó sus datos; se registraron fixtures interrumpidos y se limpiaron las dos
bases sin clientes antes de repetir 27 IDs completos en functional5/processes4.

La primera regresión B8B/C/D registró 23 errores de fixture: segundo claim de
planner en una org ya ocupada. Se conservan todos los IDs/aserciones y se prepara
estado heredado solo para carreras de dominio, comprobando primero el rechazo
del API B9C. Un primer ajuste omitió el claim de consentimiento; esas dos corridas
se detuvieron y conservaron. El ajuste final abarca ambos claims del fixture;
B8E reprodujo el mismo problema y recibió la misma adaptación limitada al fixture.
Los 118 IDs afectados pasan con el fixture definitivo. El runtime no cambia.
Se recuperaron los 8 IDs legacy pendientes. Otra interrupción dejó 23 éxitos
válidos de B8D y un registro final de 119 bytes nulos: ese registro se excluye,
preservando su hash y el archivo original, y se repiten los 4 IDs restantes.
B8E se repite con sus 29 IDs de procesos completos tras adaptar su fixture,
junto a los 536 aún no iniciados de domains/extra/provider. No se redujo ninguna
suite ni se ocultaron errores. El recibo enumera cada registro rechazado.
La corrida domains-completed aprobó 420 IDs, pero dos setUpClass agotaron el
timeout de conexión antes de ejecutar sus 10 tests. Se conservaron ambos errores
y se expandieron a los IDs de cada clase en el recibo; los 10 se recuperaron en
domains-recovered, sin modificar esos tests ni el runtime.

### Aceptación final

| Corrida | IDs aceptados | Fallos/errores/skips/xfail |
| --- | ---: | --- |
| functional5 | 18 | 0/0/0/0 |
| processes4 | 9 | 0/0/0/0 |
| b9b-final | 34 | 0/0/0/0 |
| b9a-final | 45 | 0/0/0/0 |
| legacy-final | 1146 | Interrumpida; pendientes recuperados por ID |
| b8b-final | 108 | Original: 6 errores; IDs afectados recuperados |
| b8c-final | 106 | Original: 11 errores; IDs afectados recuperados |
| b8d-final | 90 | Original: 6 errores; IDs afectados recuperados |
| b8e-final | 91 | Interrumpida; pendientes recuperados por ID |
| b8b-verified | 21 | 0/0/0/0 |
| b8c-verified | 41 | 0/0/0/0 |
| b8d-verified | 23 | Interrumpida; pendientes recuperados por ID |
| legacy-verified | 8 | 0/0/0/0 |
| b8e-verified | 0 | Interrumpida; pendientes recuperados por ID |
| b8d-completed | 4 | 0/0/0/0 |
| b8e-completed | 29 | 0/0/0/0 |
| domains-completed | 420 | Original: 2 errores; IDs afectados recuperados |
| extra-completed | 94 | 0/0/0/0 |
| provider-completed | 12 | 0/0/0/0 |
| domains-recovered | 10 | 0/0/0/0 |

Total: **2.309 únicos**, 2.282 históricos y 27 nuevos; ninguno pendiente.
Recibo: [b9c-acceptance-results.json](evals/b9c-acceptance-results.json).
Corpus: [b9c-concurrency-scale-corpus-v1.json](evals/b9c-concurrency-scale-corpus-v1.json).
Las seis métricas críticas son cero por aserciones identificadas y observaciones
de claim/wire; no se extrapolan a carga/SLO. SCALE-01/02 de componente no significan
aceptación integral de PROFILE-BETA-1. B9E sigue siendo dueño de esa medición.

### Reproducción y limpieza

Con Python bloqueado y PostgreSQL local dedicado, preparar DATABASE_URL de prueba,
SECRET_KEY de prueba, DEBUG=False, ENVIRONMENT=dev; Sentry/Redis/Discord vacíos.
Desde backend, ejecutar el runner con un JSON de IDs exactos y prefijo de salida
nuevo: `python -m apps.agent.tests.run_b9a_acceptance --suite targeted --database
test_b8b_b9c_repro --ids-file IDS.json --output OUTPUT`.
Usar prefijos test_b8c_/test_b8d_/test_b8e_ para las particiones que los requieren.
No reutilizar una base con datos ni tratar un skip como aceptación.

Checks Django/migraciones y schema verdes, sin migración nueva. La limpieza
verificó ausencia de otros clientes y locks en espera, registró filas de fixtures,
eliminó solo bases B9C y detuvo el clúster con pg_ctl. Puerto cerrado,
postmaster.pid ausente; logs y artefactos preservados. No infraestructura de
prueba B9C activa tras el cierre.

## Reporte de cierre (60 puntos)

| # | Punto | Resultado |
| --- | --- | --- |
| 1 | Estado B9C | COMPLETED técnico del hito interno |
| 2 | B9 canónica | IN_PROGRESS; E conserva aceptación integral |
| 3 | Baseline | e9792c09e5830f058e8f143db7f4fcd93eef03fe |
| 4 | SHA implementación | 14e706685a020cff6113a85bad906f7998af8ecd |
| 5 | SHA documental/final | Commit docs(agent) que incorpora esta acta y el recibo; SHA comunicado al cerrar Git |
| 6 | HEAD final | El commit documental de esta entrega será el baseline siguiente; no se autorreferencia un hash en su propio contenido |
| 7 | Cambios preexistentes | Preservados fuera de ambos commits: dos eliminaciones DEPLOY_VPS, auditoría 10-09 y discrepancia B9 26-09; discrepancia B9B sin editar |
| 8 | Requisitos | R04/R12; C4 e I09/I10/I13; SCALE-01/02 de componente. Matriz previa con ubicaciones literales |
| 9 | Unidad | TurnWork committed PROCESSING con tenant/epoch coherentes y lease futura |
| 10 | Límite | Uno por org; uno no terminal por conversación; dos planners secuenciales en topología |
| 11 | Scope | Organización agregado entre procesos, sin cupo global durable dos ni cuotas de provider |
| 12 | Autoridad | TurnWork y witness B3; Organization solo serializa adquisiciones |
| 13 | Reutilización | Organization, Conversation, TurnWork, Message, token/epoch/lease/membership/cursor; LLMCall B9B |
| 14 | Modelos/campos | Ninguno nuevo; constante de release uno |
| 15 | Migraciones | Ninguna; índices FK org/status-lease/retry y unique parcial B3 verificados |
| 16 | Adquisición | Organization NO KEY UPDATE SKIP LOCKED → Conversation → ocupación DB → primitiva B3 → commit |
| 17 | Liberación | Completion/failure/retry/invalidation B3 dejan de contar; sin contador que decrementar |
| 18 | Crash recovery | Sin commit no ocupa; committed ocupa hasta expiry/invalidation; reclaim renueva token conservando trabajo/budget |
| 19 | Restart | Relee filas, no reinicia autoridad ni presupuesto |
| 20 | Lease | 15 min B3; deadline 12 min; reloj DB; retry 30/60 s y máximo tres intentos |
| 21 | Epoch/fencing | Epoch de Conversation/TurnWork y token deben coincidir; guards B3/B9B/B8 |
| 22 | Stale | Sin nueva admisión/finalización/publicación; HTTP ya admitido puede terminar tarde |
| 23 | Saturación | No claim ni cambio de miembros/intentos/budget; inbound permanece pendiente |
| 24 | Backpressure | Polling durable; excluir org ocupada antes de LIMIT; sin nuevo rate limiter/fairness scheduler |
| 25 | Tenants | Límites independientes, claims y consultas tenant-scoped |
| 26 | B9B | Consumo independiente por TurnWork, sin refund por rollback/timeout/reclaim |
| 27 | Orden | Capacidad/claim → witness/contexto → admisión B9B → provider → finalización |
| 28 | Locks | Claim Organization→Conversation→TurnWork→Message; las otras rutas conservan su orden y no toman Organization |
| 29 | HTTP sin locks | Asserts del harness en wire y pruebas de procesos; ninguna transacción de claim cubre red |
| 30 | Handoff/takeover | Safety DB atómica sin planner, ningún segundo PROCESSING committed; takeover no espera cupo; B5 permanece |
| 31 | B7/B8 | Consentimiento/guard atravesados en WRITE real por HTTP/worker; regresiones completas |
| 32 | Sender | Proceso separado, poll 1 s; progreso con LLM bloqueado; Meta lento/incierto conserva durabilidad y no retry ciego |
| 33 | Observabilidad | ADMITTED/SATURATED/DEFERRED y lifecycle B3; snapshot readonly compute_concurrency(org) |
| 34 | Inspector | Nueva CLI/UI no requerida por B9; snapshot y filas B3 para operador autorizado, sin force release |
| 35 | Funcionales | 18/18 nuevos finales, sin skips/xfail |
| 36 | N-1/N/N+1 | N canónico 1: 0/1/2; segunda conversación denegada sin mutación |
| 37 | Multiproceso | 9/9 nuevos finales, PostgreSQL real y procesos/conexiones independientes |
| 38 | PIDs/conexiones | 57456/58040, 56832/42996, 32740/28972 (Python/backend PG en carrera final); journals completos en recibo |
| 39 | Failure injection | FI-01…10 aprobadas; SQL real, kill en fronteras, token stale y restart; sin mocks de locks |
| 40 | E2E B9A | HTTP→Message→claim→worker→B9B→fake provider→outbound→sender; saturación→liberación→procesamiento posterior |
| 41 | Corpus SCALE | 27 IDs; 25 casos del encargo mapeados como B9C-SCALE para distinguir SCALE canónico; FI y proofs versionados |
| 42 | Métricas críticas | Las seis en cero en corpus final: exceso, doble ownership, progreso stale, pérdida en saturación, fuga tras recovery, violación tenant |
| 43 | Evidencia B9E | Corpus, snapshots claim/wire, hashes e IDs/PIDs; no PROFILE-BETA-1 ni p95/throughput integral |
| 44 | Regresión B9B | 34/34 exactos; provider adicional 12/12 |
| 45 | Regresión B9A | 45/45 exactos |
| 46 | Regresión B0–B8E | 2.191/2.191 históricos previos a B9A, incluidos worker/channels/inbox/org/users/RBAC/appointments/patients y dominios |
| 47 | Total único | 2.309 = 2.282 baseline + 27 B9C; 0 pendientes, fallos sin recuperar, skips o xfail finales |
| 48 | Checks | check, makemigrations --check --dry-run, migrate --check, schema y git diff --check verdes |
| 49 | Infra limpia | Sin clientes/locks pendientes; bases B9C eliminadas; clúster 35437 detenido; puerto cerrado y postmaster.pid ausente |
| 50 | Privacidad | Sin contenido conversacional nuevo ni UUID/phone/user/prompt como labels |
| 51 | Seguridad | Tenant/RBAC/witness/fencing/consentimiento/guard y precedencia humana preservados |
| 52 | Documentación | Contrato, ADR, acta, recibo, corpus, mapa, arquitectura, módulo, runbooks y dossier actualizados |
| 53 | Hallazgos | H16/H19 reciben evidencia parcial; cierre integral pendiente B9E |
| 54 | Riesgos | Carga real no medida; fairness fuerte no prometida; drenar writers antiguos; HTTP tardío y timeout de lectura sin deadline absoluto |
| 55 | Gates | B0 cerrado, AGENT_B7B_CONSENT_ENABLED=False, AGENT_OPERATION_EXECUTION_ENABLED={} |
| 56 | Activación | PENDING_ACTIVATION_REQUIREMENTS |
| 57 | Clínicas activadas | 0 |
| 58 | Deploy | No realizado |
| 59 | B9D/B9E | No implementados; PROFILE-BETA-1 no ejecutado |
| 60 | Siguiente hito | B9D según mapa, con encargo posterior. STOP tras B9C |

Los SHA finales se comunican después de crear ambos commits. Los cuatro cambios
preexistentes permanecen fuera; el informe de discrepancia B9B sigue sin editar.
H16/H19 y los gates transversales mantienen cierre integral pendiente. STOP.
