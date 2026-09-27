# B9 — Componente interno de presupuesto y contabilidad (B9B)

Estado: **COMPLETED técnico del hito interno B9B**. B9 canónica: **IN_PROGRESS**.
Baseline/HEAD inicial verificado: `ccd49844e6e777395517a0527f564faf7fc5b0f2`.
No se declara PROFILE-BETA-1/EVAL/COST/SCALE aprobado.

## Autoridad, alcance y trazabilidad

El encargo inicial se detuvo antes de implementar por contradicciones de alcance;
se conserva [su informe](discrepancia-encargo-b9b-2026-09-27.md), junto al
[informe previo B9](discrepancia-encargo-b9-2026-09-26.md). La continuación retiró
presupuestos monetarios, periodos, rollover, billing y estados nuevos. Se relee
B9 canónica completa y su mapa interno. El nombre real del plan termina en
`2026-09md`, sin punto antes de md; no se creó otra autoridad.

La [matriz previa de requisitos](contrato-presupuesto-turnwork-b9b.md) cita
literalmente B9 y relaciona cada requisito con código y prueba. R03/R05/R11
pertenecen al hito interno; R12 limita su diseño. El
[ADR](decisions/2026-09-27-b9b-turnwork-budget.md) justifica cada campo.

## Implementación

Las tres llamadas reales son planner._complete_with_retry,
operation_authorization._classify y _verify. Cada una usa llm_budget.complete:
admisión durable bajo OwnershipWitness, HTTP sin locks y observación de usage.
El cliente es OpenAICompatibleClient con POST no streaming; modelos por rol,
sin fallback de red ni idempotency key remota. Herramientas/respuestas usan el
planner. EVAL histórico sin TurnWork se identifica como diagnóstico y registra
LLMCall sin admisión B9; application-e2e recorre el worker real.

TurnWork conserva llamadas admitidas y máximo de tokens de salida reservado;
límites fijos 30/18.000, 600 por llamada (160/120 en clasificadores), entrada
65.536 bytes de JSON UTF-8 y timeout Requests 10 s. El límite de bytes no se
presenta como tokenización del proveedor. Sin nueva dimensión monetaria.
El límite de llamadas deriva del loop existente (5 tools + 2) × 4 intentos + 2
clasificadores. B9C sigue siendo dueño de concurrencia general y timeouts de
herramientas; aquí solo se protege la integridad del presupuesto.

Conversation → TurnWork es el orden de locks. La admisión valida tenant, token,
epoch de ambas filas, estado PROCESSING, lease y deadline. UUID unique identifica
la admisión; una repetición de su observación no concede HTTP nuevo. Insertar
LLMCall e incrementar contadores comparten commit durable antes de llamar. No se
admite dentro de otra transacción de aplicación. LLMCall deja el buffer volátil
TurnChanges en los tres call sites; finalización B3/B8 LOCAL_ATOMIC no cambia.

Rollback del trabajo, crash, timeout, fallo del proveedor o de persistencia
posterior no restituyen cupo. Un nuevo HTTP necesita otra admisión; retry_of
relaciona los retries del planner. Un restart con otro lease conserva los
contadores del mismo trabajo. Un nuevo TurnWork tiene su propio presupuesto.
Observar usage tardío no concede ownership ni autorización de negocio.

Usage reportado válido se conserva en input_tokens/output_tokens. Ausencia,
negativo, booleano, dato malformado o fuera de rango son NULL; cero explícito
del proveedor es cero. Argumentos tool inválidos no descartan usage reportado.
recorded_at distingue intento sin observación y respuesta/error registrado;
la actualización condicional es idempotente. No se agregan estados. Coste
nuevo desconocido queda NULL; no precios inventados ni cálculo de billing.

## Datos, privacidad, observabilidad e inspección

Migración aditiva agent.0028_b9_operational_budget: FK nullable LLMCall→TurnWork,
campos de evidencia/usage y contadores/límites. Los contadores históricos se
añaden NULL y luego reciben default Python 0 para filas nuevas; no backfill de
admisiones/usage. Constraints PG acotan contadores y exigen evidencia; UUID unique.
Se conservan todas las migraciones históricas.

Eventos cerrados: llm_budget_admitted/rejected/exhausted y
llm_usage_recorded/unavailable, con purpose cerrado. El logging puede faltar
tras crash; las filas son autoridad. No prompts/respuestas/teléfonos/nombres
ni argumentos completos en accounting. Error y finish_reason son vocabularios
cerrados; provider no copia URL con credenciales. Modelo procede de configuración.

metrics.compute_llm_usage recibe organización y filtro opcional TurnWork;
expone roles/retries/errores/unknown y subtotales conocidos separados. Inspector
`agent_inspect_llm_budget` requiere organization-id y turn-work-id; readonly,
sin contenido conversacional, sin mutación/release. Incluye coherencia de filas
con contadores y admisiones aún sin observación. Un ID de otro tenant no revela
su evidencia. Se usa por operadores con acceso autorizado al management CLI.

Ante agotamiento se reutilizan REASON_BUDGET/T0_BUDGET. El runtime B3 consulta
TurnWork en policy; la admisión vuelve a verificar atómicamente antes de HTTP.
El contador legacy de conversación no sustituye esa autoridad. El fallback
determinista nunca hace una llamada para explicar que no queda presupuesto.

## Pruebas y evidencia de ejecución

Aceptación completada sobre PostgreSQL 16 aislado, puerto 35436, usuario local de
prueba b9b. fsync/synchronous_commit no se desactivan. Python 3.13/Django 6.0.5
del entorno bloqueado B8B. Sentry/Redis/healthchecks externos desactivados en el
runner; wire B9A restringido a hosts .invalid y loopback Django/DRF.
Artefactos locales: `C:/Users/LAP/AppData/Local/Temp/b9b-evidence`.

Se usan el runner por IDs exactos B8E/B9A y bases separadas según los prefijos
exigidos por procesos históricos. El inventario de 2.236 IDs se extrae de
b9a-acceptance-results.json, sin sumar repeticiones. Tests nuevos en
test_b9b_budget y test_b9b_processes; corpus versionado
`evals/b9b-turnwork-budget-corpus-v1.json`.

La primera corrida functional1 importó casos B9A adicionales por un import de
TestCase; se corrigió a import de módulo y se interrumpió esa corrida redundante
sin borrar sus journals. La aceptación usa suites separadas. Las corridas
preliminares no constituyen aceptación de fuente final por sí solas.

### Reproducción

Usar el entorno bloqueado del backend y PostgreSQL local dedicado, con
fsync/synchronous_commit activados. DATABASE_URL debe apuntar a ese servidor;
no reutilizar una base de desarrollo con datos ni una conexión productiva.
El runner cierra Sentry/Redis; el wrapper local también fija SECRET_KEY de
prueba, DEBUG=False, ENVIRONMENT=dev y DISCORD_WEBHOOK_URL vacío.

Desde backend, con un JSON array de IDs exactos y un prefijo nuevo de salida:

```text
python -m apps.agent.tests.run_b9a_acceptance --suite targeted --database test_b8b_b9b_repro --ids-file ids.json --output evidencia/corpus
python -m apps.agent.tests.run_b9a_acceptance --suite checks --database test_b8b_b9b_repro --output evidencia/checks
```

Para el corpus, usar test_ids del JSON versionado; para procesos, process_test_ids.
Para el histórico, extraer la unión de passed_ids de b9a-acceptance-results.json
y exigir exactamente 2.236. **No usar --suite historical de ese runner para B9B**:
su inventario heredado contiene solo los 2.097 del corte B8E. Ejecutar las
particiones por IDs como en el recibo de este hito; B8C/B8D/B8E requieren sus
prefijos test_b8c_/test_b8d_/test_b8e_ para los guards de procesos. Cada partición
usa una base aislada con migraciones aplicadas; nunca compartir base entre jobs.
El harness usa fixtures y proveedores controlados, sin credenciales de clínica.

Conservar *.results.json, *.passed.jsonl, *.inventory.json, *.sources.json,
*.b9b-corpus.jsonl y journals multiproceso. Una interrupción requiere recuperar
los IDs exactos pendientes y mantener el estado PARTIAL hasta conciliación.

Las pruebas de procesos ya ejecutadas incluyen kill antes del commit, kill
después del commit y reclaim, UUID duplicado, último slot con wait_event_type=Lock
y pg_blocking_pids real, witness stale e independencia tenant. Se conservan
PIDs del intérprete y backend en JSONL. Los lectores de pipes no se presentan
como workers. No certifican exactamente-una-vez remoto ni pérdida eléctrica.

Los tests funcionales ejercitan error SQL antes de commit (sin consumo), error
SQL después del proveedor (retiene unknown), rollback posterior, timeout/retry,
roles compartiendo cupo, usage ausente/malformado/cero, scope tenant, inspector,
constraints, idempotencia, input cap, migración y privacidad. E2E READ recorre
HTTP→worker→admisión→wire→usage→outbound→sender. WRITE atraviesa B7B y B8A y
rechaza una definición inactiva sin crear efecto. El harness exige evidencia
de admisión antes del wire y conserva la aserción de ausencia de HTTP en atomic.

## Producción, rollback y pendientes

No se consultaron ni cambiaron datos productivos. Cero clínicas activadas;
sin deploy. B0/flags permanecen sin cambios: B7B=False, execution flags={} y
PENDING_ACTIVATION_REQUIREMENTS. No se ejecutó PROFILE-BETA-1 ni se implementaron
B9C/B9D/B9E. H16/H19 no se cierran con evidencia de este componente.

Rollback funcional: detener planners/deshabilitar AgentSettings conservando
sender, fencing, columnas, admissions y usage. No deshacer 0028 en producción,
reponer contadores o desplegar writers legacy que ignoren el cupo. Reversión
de migración solo en test aislado para verificar legacy.

Riesgos residuales: unknown tras crash/timeouts no reconciliable automáticamente,
presupuesto conservador consumido incluso si no llegó a haber HTTP, límites de
release aún no validados con carga PROFILE-BETA-1, y timeout de lectura Requests
sin plazo absoluto ante un proveedor que gotee bytes. Tokens de entrada reales
dependen de usage; bytes de entrada limitan tamaño sin inventar estimación.
Identidad, privacidad y cobertura humana pendientes mantienen los gates originales.

La aceptación de este componente está cerrada. Corresponde B9C según el mapa
como encargo posterior; este trabajo se detiene aquí, sin activación automática.

## Reporte trazable de los 49 puntos del encargo

Los resultados se cerraron después de terminar las corridas, conciliar sus IDs
exactos y limpiar el clúster aislado. El corpus final
ya pasó 28/28; procesos 6/6 y provider 12/12. Sus seis métricas críticas son cero.
Los backends de las carreras finales fueron 11528→26036 (UUID duplicado) y
26728→23900 (último slot); en ambos se observó bloqueo real. Las diferencias de
docstrings de llm.py/models.py se reconstruyeron contra SHA-256 de las corridas
y su AST ejecutable se comprobó equivalente; no se ocultan diferencias de bytes.
La corrida legacy también precedía al campo de coherencia del inspector:
reconstruir sus bytes contra el hash acredita que solo cambió inspect_turn en
llm_budget.py y que admit/complete/record eran idénticos. El corpus final valida
ese inspector y la aserción de admisión antes del wire.

| # | Punto | Resultado/evidencia |
| --- | --- | --- |
| 1 | Estado del hito | COMPLETED técnico del componente interno |
| 2 | B9 canónica | IN_PROGRESS |
| 3 | Baseline | ccd49844e6e777395517a0527f564faf7fc5b0f2 |
| 4 | Commits | Implementación: 11349c684fbefa7b9af3be9aca9f130b0833d632. Cierre documental: el commit que incorpora esta acta actualizada y el recibo de aceptación |
| 5 | Cambios preexistentes | Se preservan las eliminaciones de DEPLOY_VPS_PLAN.md y DEPLOY_VPS_STATUS.md, el informe de auditoría del 10-09 y ambos informes de discrepancia |
| 6 | Requisitos literales | Matriz previa: líneas baseline 714, 716, 725, 727 y 729; R03/R05/R11 bajo restricción R12 |
| 7 | Budget | Llamadas admitidas y máximo de salida reservado antes de HTTP |
| 8 | Unidad | Una llamada y sus tokens máximos de salida; sin dinero ni periodo |
| 9 | TurnWork | Autoridad y contadores durables del mismo trabajo, incluso después de reclaim |
| 10 | Witness | Organization, Conversation, TurnWork, lease_token y ownership_epoch; PROCESSING, lease y deadline válidos |
| 11 | Admission | UUID unique, fila LLMCall y aumento atómico de contadores |
| 12 | Durability boundary | Commit durable independiente antes de provider; rechaza anidación de aplicación |
| 13 | Rollback | Rollback de trabajo/publicación no devuelve cupo |
| 14 | Restart | Nuevo lease del mismo trabajo conserva consumo; legacy NULL no admite |
| 15 | Retry | Otro HTTP obtiene otra admisión; retry_of liga intentos del planner |
| 16 | Fallo del provider | Admisión permanece; error cerrado, usage válido si está disponible |
| 17 | Timeout | Consume admisión; retry requiere cupo adicional; timeout Requests 10 s no equivale a plazo absoluto |
| 18 | Usage | input_tokens/output_tokens, latency, finish_reason cerrado, recorded_at; totales derivados |
| 19 | Usage ausente | NULL, conteo unknown y totales incompletos NULL; cero explícito válido se conserva |
| 20 | Modelos/campos | TurnWork y LLMCall; justificación campo por campo en ADR |
| 21 | Migración | 0028 aditiva; NULL histórico, default 0 nuevo, sin backfill inventado |
| 22 | Billing table | Ninguna tabla nueva |
| 23 | State machine | Ningún estado nuevo |
| 24 | Lock order | Conversation → TurnWork → LLMCall; HTTP fuera de atomic |
| 25 | Concurrencia PG | Último slot, UUID duplicado, stale witness, crash/restart y tenants independientes |
| 26 | PIDs/locks | Journals con PID/backend, wait_event_type=Lock y pg_blocking_pids. Sin sesiones ajenas al verificador ni locks en espera al limpiar; bases de fixtures eliminadas y clúster detenido |
| 27 | E2E B9A | READ por HTTP/worker/wire/usage/sender y WRITE rechazado por B8A; fixture B7B real |
| 28 | Funcionales | 28/28 IDs nuevos en corpus final; 6/6 procesos y 12/12 provider |
| 29 | Failure injection | FI-01…10: commit, kill, rollback, reclaim, timeout, duplicate, carrera, stale, unknown y SQL |
| 30 | Corpus | evals/b9b-turnwork-budget-corpus-v1.json, 28 observaciones y journals de seis tests multiproceso |
| 31 | Métricas | Las seis métricas críticas son cero en el corpus ejecutado, sin extrapolación |
| 32 | COST | Roles, admitted, retries, failures, unknown y subtotales conocidos; sin pricing ni PROFILE-BETA-1 PASS |
| 33 | Regresión B9A | 45/45 IDs exactos aceptados |
| 34 | Regresión B0–B8E | 2.191/2.191 IDs históricos anteriores a B9A, incluidos dominios y adicionales del baseline |
| 35 | Total único | 2.282 = 2.236 históricos + 34 nuevos + 12 provider; 0 pendientes, 0 skips/xfail y 0 fallos sin recuperar |
| 36 | Checks | check, makemigrations --check --dry-run, migrate --check, constraints/índices PG y git diff --check verdes |
| 37 | Observabilidad | Eventos cerrados de admisión/rechazo/agotamiento/usage; sin IDs ni contenido en labels |
| 38 | Inspector | CLI readonly por organización y TurnWork, límites/consumo/restante/usage/coherencia |
| 39 | Privacy | No copia prompt, respuesta, texto clínico, teléfono, nombre ni argumentos; vocabulario de error cerrado |
| 40 | Rollback funcional | Retirar capacidad y conservar sender/fencing/contabilidad; no revertir 0028 ni liberar cupo |
| 41 | Documentación | Matriz, ADR, mapa, plan de progreso, arquitectura, runbooks, módulo, harness, corpus y acta |
| 42 | Hallazgos | H16/H19 con evidencia parcial del componente; no cierre integral |
| 43 | Riesgos | Unknown tras crash; consumo conservador; límites aún sin validación integral de carga; lectura HTTP sin plazo absoluto |
| 44 | Gates | Defaults efectivos verificados: B7B=False y execution flags={}; B0 cerrado |
| 45 | Activación | PENDING_ACTIVATION_REQUIREMENTS |
| 46 | Clínicas activadas | 0 |
| 47 | Deploy | No realizado |
| 48 | B9 pendiente | B9C concurrencia general, B9D readiness/activation, B9E aceptación integral |
| 49 | Siguiente hito | B9C después del cierre de este componente y de un encargo posterior; detenerse aquí |

## Aceptación final por IDs

| Corrida | IDs aceptados | Fallos/errores/skips/xfail |
| --- | ---: | --- |
| legacy-final | 1154 | 0/0/0/0 |
| domains-final | 430 | 0/0/0/0 |
| b8b-final | 129 | 0/0/0/0 |
| b8c-final | 147 | 0/0/0/0 |
| b8d-final | 117 | 0/0/0/0 |
| b8e-final | 120 | 0/0/0/0 |
| b9a-final | 45 | 0/0/0/0 |
| extra-final | 94 | 0/0/0/0 |
| corpus-verified | 28 | 0/0/0/0 |
| processes-verified | 6 | 0/0/0/0 |
| provider-verified | 12 | 0/0/0/0 |

Recibo versionado: [b9b-acceptance-results.json](evals/b9b-acceptance-results.json), con IDs, hashes, observaciones, locks, schema, cleanup y pruebas de equivalencia de docstrings. No suma corridas repetidas.

El clúster aislado de puerto 35436 se detuvo con pg_ctl; puerto cerrado y postmaster.pid ausente. Se eliminaron solo sus bases test_b*_b9b_* después de verificar ausencia de clientes. La base plantilla no conservaba TurnWork/LLMCall. Las filas de la corrida preliminar interrumpida quedaron registradas antes de eliminar su base. Los artefactos de evidencia se conservan.

## Cierre formal en Git

Implementación/runtime/migración/tests se registran en
`11349c684fbefa7b9af3be9aca9f130b0833d632`, siguiendo la convención feat(agent).
El commit docs(agent) que contiene esta sección cierra documentación, corpus y
aceptación; su HEAD final será el baseline obligatorio del siguiente encargo B9C.
No se modificó comportamiento ni tests durante este cierre: los 14 archivos de
implementación coinciden con los hashes aceptados. git diff --check y el check
del índice pasan.

El informe discrepancia-encargo-b9b-2026-09-27.md se incorpora como evidencia
histórica de B9B, sin editarlo. Permanecen fuera los cuatro cambios originales:
las eliminaciones de DEPLOY_VPS_PLAN.md y DEPLOY_VPS_STATUS.md, el informe de
auditoría del 10-09 y discrepancia-encargo-b9-2026-09-26.md. Ambos informes de
discrepancia se conservan. B0 cerrado, B7B=False, execution flags={} y
PENDING_ACTIVATION_REQUIREMENTS; sin B9C, apertura de gates ni deploy.
