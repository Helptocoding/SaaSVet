# B9D — Gates de beta por release y organización

Estado: **COMPLETED técnico del hito interno B9D**.
B9 canónica: **IN_PROGRESS**. PROFILE-BETA-1: **NOT YET EVALUATED**.
Baseline obligatorio verificado antes de modificar:
`4f6d199dc4f8b38e5d48582f9ee289bf8dcfdb17`.
Implementación: `5ab55a1223cd9f66f620c9552bc9ecdd35e84669`. Cierre documental: commit que contiene esta acta.
Production activation: **PENDING_ACTIVATION_REQUIREMENTS**; cero clínicas activadas, sin deploy.

## Contrato y resultado técnico

El [contrato](contrato-beta-release-b9d.md), la [extracción literal](evals/b9d-requirements.json)
y el [ADR](decisions/2026-09-28-b9d-beta-release-gates.md) reconcilian el alcance
R13 con el plan canónico completo. B9D no requiere nueva tabla, activation_revision,
workflow administrativo ni estado ACTIVE. Se conserva esa decisión: una lista
inmutable de release enumera el alcance por organización/capability y evidencia
con procedencia; READY se deriva, sin conceder identidad, consentimiento o ejecución.

El único cambio de frontera runtime añade el gate dentro de B8A, después de
reconciliar y antes de efectos nuevos. Los cinco adapters deben contar con grant
exacto y una operación creada a partir de la fecha de aprobación. No se alteran
sender, fences, dominio, presupuesto B9B ni capacidad B9C. La lista productiva
permanece vacía. Los harness de tests abren explícitamente TEST_EVIDENCE en PG
aislado, junto a sus gates existentes, y ejecutan evaluator/guard/adapters reales.

El inspector readonly informa INSTALLED, READY/pendientes, capacidades del grant,
motivos de bloqueo y comprobaciones que aún corresponden a cada operación. No
crea configuración ni devuelve referencias privadas. No writer administrativo
ni capability de autocertificación; los permisos de Inbox/settings no aprueban
el release. La verdad de la evidencia externa requiere revisión humana real.

La retirada usa pausa/drain/corte de todos los writers. No hay edición concurrente
de aprobación en DB ni hot reload; por ello no se introduce lock/revision de
activación. El guard no consume un snapshot READY anterior. Reaprobación fechada
excluye trabajo creado antes; los ledgers committed permanecen conciliables.
No se afirma que cambiar un archivo cerque procesos anteriores ni cancele HTTP.
READ/CONTROL mantienen política/disponibilidad previas. El alcance
READ de una promoción debe aprobarse operacionalmente; este hito no añade una
barrera runtime indiscriminada a las consultas existentes.

## Método, incidencias y aceptación

PostgreSQL 16.15 aislado en `127.0.0.1:35438`, rol local `b9d`, fsync y
synchronous_commit ON. Python 3.13.2/Django 6.0.5 del entorno bloqueado B8B.
Runner exacto B8E/B9A con inventories, journals por ID, resultados y hashes de
fuentes. Esquema completo migrado desde vacío y bases aisladas por partición;
sin SQLite, proveedores reales ni comunicaciones a personas.
Artefactos locales: `C:/Users/LAP/AppData/Local/Temp/b9d-evidence`.

Se conservaron las corridas preliminares functional1 (58/58) y functional-final
(73/73); no se cuentan porque preceden al conjunto/fuentes definitivos.
functional-verified terminó 75/75, con hashes iguales al código final de ese
momento. La interrupción del límite no produjo un verde histórico: el lanzador
temporal queue.py ocultó el módulo estándar queue y falló antes de arrancar B9C.
Se renombró a run_historical.py; no se modificó producto para corregirlo.
No se elimina ningún ID, assertion o fallo para obtener aceptación.

Las particiones independientes se ejecutan en bases separadas del mismo clúster.
Un lock del lanzador serializa intentos de la misma partición; una cola que llega
después reutiliza únicamente un recibo completo con inventario/journal exactos y
fuentes idénticas. No se suman repeticiones ni se comparten fixtures entre bases.
La topología productiva B9C y el perfil integral no se modifican por esta
paralelización del proceso de regresión.

El [corpus](evals/b9d-corpus.json) mapea 32 casos (incluidas adaptaciones explícitas
de casos no aplicables) a los 75 IDs nuevos y regresiones anteriores. Sus métricas
son invariantes observadas mediante assertions, no telemetría productiva ni SLO.
No se usa ACTIVE como estado inventado; se mide aprobación y efecto autorizado.
La aceptación completa se registra en [el recibo](evals/b9d-acceptance-results.json).

Para reproducir, usar PostgreSQL local aislado y dependencias bloqueadas del
backend, sin credenciales de proveedores. Por cada corrida del recibo, escribir
su `passed_ids` como array JSON y utilizar una DB de pruebas con el mismo prefijo
registrado (`test_b8b_`, `test_b8c_`, `test_b8d_` o `test_b8e_`). Ejecutar desde
backend `python -m apps.agent.tests.run_b9a_acceptance --suite targeted --database
NOMBRE --ids-file ARCHIVO --output PREFIJO`. Para checks usar `--suite checks`
sin `--ids-file`. El runner migra/usa únicamente la DB de pruebas indicada.
No usar `--suite historical`: ese inventario anterior no representa los 2.309
IDs del baseline B9C. Comparar IDs, journals, exit codes y hashes; cero skips
no basta si faltan IDs. Esto reproduce componentes, no PROFILE-BETA-1.

## Aceptación final

| Partición | IDs aceptados | Fallos/errores/skips/xfail |
| --- | ---: | --- |
| functional-verified | 75 | 0/0/0/0 |
| b9c-final | 27 | 0/0/0/0 |
| b9b-final | 46 | 0/0/0/0 |
| b9a-final | 45 | 0/0/0/0 |
| legacy-final | 1154 | 0/0/0/0 |
| b8b-final | 129 | 0/0/0/0 |
| b8c-final | 147 | 0/0/0/0 |
| b8d-final | 117 | 0/0/0/0 |
| b8e-final | 120 | 0/0/0/0 |
| domains-final | 430 | 0/0/0/0 |
| extra-final | 94 | 0/0/0/0 |

**Total: 2.384 IDs únicos; 0 pendientes.** Las fuentes coinciden con los hashes
de todas las corridas aceptadas. Checks Django/migraciones/Git verdes. Los siete
invariantes críticos del corpus tienen cero violaciones en los tests mapeados.
No equivale a una aprobación operativa ni a PROFILE-BETA-1.

Se retiraron únicamente las bases/fixtures y el clúster temporal B9D, tras
comprobar el data_directory exacto, ausencia de otros clientes, locks pendientes
y transacciones preparadas. Puerto 35438 cerrado; procesos de aceptación
finalizados. Se conservan recibos y log del servidor para trazabilidad.

## Respuestas al cierre solicitado

| Nº | Tema | Resultado / evidencia |
| --- | --- | --- |
| 1 | B9D | COMPLETED técnico: todos los IDs/checks aceptados y entrega en dos commits |
| 2 | B9 canónica | IN_PROGRESS |
| 3 | Baseline | 4f6d199dc4f8b38e5d48582f9ee289bf8dcfdb17 |
| 4 | SHA implementación | 5ab55a1223cd9f66f620c9552bc9ecdd35e84669 |
| 5 | SHA documentación | Commit que contiene esta acta; se reporta al entregar |
| 6 | HEAD final | Commit documental, futuro baseline B9E |
| 7 | Preexistentes | D DEPLOY_VPS_PLAN.md; D DEPLOY_VPS_STATUS.md; dos untracked de auditoría/discrepancia B9. Excluidos de ambos commits; discrepancia B9B preservada |
| 8 | Requisitos B9D | R13: lista explícita release/org, intersección de permisos/contrato, cobertura y gates antes de ampliar, retirada compatible |
| 9 | Técnicos | B0–B9C conservados; critical_ci, candidate_eval y profile_beta_1 requeridos como evidencia integral externa a este componente |
| 10 | Operacionales | Piloto/alcance/tasa; Inbox/cobertura; protocolo/corpus veterinario; simulacro; privacidad/retención; fallback; riesgo identidad; cutover/rollback; aprobación humana |
| 11 | Readiness | READY derivado de candidato, scope y todos los registros válidos; no booleano persistido |
| 12 | Activation | Sin ACTIVE nuevo; autonomía efectiva requiere lista aprobada más todos los gates/política/contrato |
| 13 | Autoridad | Fuente inmutable del release revisado y registros humanos externos; vacía en producción |
| 14 | Modelos/campos | Dataclasses frozen Evidence/OrganizationApproval/Release; ningún modelo/campo ORM nuevo |
| 15 | Migraciones | Ninguna necesaria; sin backfill ni approvals por migrate |
| 16 | Legacy | Ausencia de grant cierra WRITE incluso con enabled/FAQ/configuración general previos |
| 17 | Pilot/cohort | Orgs enumeradas y evidencia piloto explícita; selección no habilita; sin tabla cohort |
| 18 | Inbox owner | Registro humano de responsable/cobertura y simulacro; plan no exige nuevo FK User, ausencia requiere retirada operacional |
| 19 | Clinical safety | Presencia/procedencia de revisión humana, sin validación médica sustantiva por software |
| 20 | Privacy | Referencia a P-A/P-B aplicable; no proyecto legal/DSR/retención nuevo |
| 21 | Fallback | Evidencia de ensayo de ruta prevista y ausencia/fallo de aviso, no mera dirección de contacto |
| 22 | Kill switches | B0, disponibilidad AgentSettings.enabled, B7B y flags por kind existentes; ningún switch nuevo |
| 23 | Precedencia | Worker adquiere B9C/B3 y reserva B9B; B8A locks/definición/consent/permiso/reconciliación/autoridad → B0/registry/flags/B7B/adapter/release → dominio/commit |
| 24 | RBAC | Inbox/settings conservados; ninguna API de mutación de readiness. CLI readonly bajo acceso operacional autorizado al host |
| 25 | Audit | Commits/revisión y referencias al registro externo con org/autoridad/fecha/revisión. No historial administrativo mutable nuevo ni PII en eventos |
| 26 | Autocertificación | Catálogo cerrado, sin writer ni tool; llamadas inventadas rechazadas; TEST_EVIDENCE no acredita entorno real |
| 27 | Revocation | Retirar grant/capability mediante pausa/drain/corte; deriva pendiente sin borrar ledger |
| 28 | Reactivation | Nueva aprobación humana fechada y evidencia vigente; exige corte compatible |
| 29 | Operación antigua | created_at anterior a approved_at no inicia efecto; resultado committed conserva reconciliación |
| 30 | TOCTOU | Relectura autoritativa dentro B8A; snapshot inspector no autoriza. Sin mutabilidad concurrente de release en DB |
| 31 | PG concurrency | Cinco adapters en PG real y regresiones existentes de procesos/locks; nuevas carreras administrativas no aplican |
| 32 | Failure injection | Error SQL después de efecto revierte efecto/estado/ToolExecution en los cinco adapters; se conserva corpus anterior |
| 33 | Cinco WRITE | CREATE/RESCHEDULE/CANCEL/CONFIRM_ATTENDANCE/REGISTER_PET bajo gate; prueba positiva, falta/retirada/scope y replay |
| 34 | READ | Rutas públicas/personales y CONTROL previas conservadas; lista READ no concede WRITE ni identidad; promoción de autonomía requiere gate operacional |
| 35 | Handoff/takeover | Autoridad B5/epochs preservada, cubierta por regresión |
| 36 | B7/B8 | Consentimiento causal, permisos, revisiones, preconditions y frontera única siguen obligatorios |
| 37 | B9B | Sin cambios runtime; presupuesto y admissions no se resetean por readiness |
| 38 | B9C | Sin cambios runtime; mismo cupo/claim/topología; aprobación no permite segundo trabajo |
| 39 | Inspector | agent_inspect_beta --organization-id ID; readonly, org explícita y existente, no get_or_create |
| 40 | Observability | execution_gate_closed y tres motivos beta finitos; inspector sin referencias privadas; no labels tenant/PII nuevos |
| 41 | Corpus | b9d-corpus.json: 32 casos y mapa por ID; distingue evidencia sintética y casos no aplicables |
| 42 | Métricas | Siete invariantes del corpus en 0; assertions de componentes, sin métricas inventadas de ACTIVE |
| 43 | Tests B9D | 75/75 en functional-verified; 0 failures/errors/skips/xfail |
| 44 | Regresión B9C | 27/27 exactos, sin fallos/errores/skips/xfail |
| 45 | Regresión B9B | 34/34 exactos + 12/12 provider, sin fallos/errores/skips/xfail |
| 46 | Regresión B9A | 45/45 exactos, sin fallos/errores/skips/xfail |
| 47 | B0–B8E/dominos | Resto de los 2.309 IDs originales; agent/channels/org/users/RBAC/appointments/patients incluidos |
| 48 | Total único | 2.384/2.384 = 2.309 históricos + 75 nuevos; cero pendientes, sin sumar repeticiones |
| 49 | Checks | check, makemigrations --check --dry-run, migrate --check y git diff --check PASS |
| 50 | Infra | Fixtures/DBs de esta tarea eliminadas, cero clientes/locks pendientes; clúster detenido y directorio temporal retirado; recibos/logs conservados |
| 51 | Documentación | Contrato, ADR, matriz literal, acta, corpus, recibo, mapa, arquitectura, módulo, runbooks, dossier y hallazgos |
| 52 | Hallazgos | H16/H19 reciben evidencia parcial; H01/H18 no se declaran cerrados globalmente |
| 53 | Riesgos | Veracidad externa, cobertura humana, identidad débil, deriva/proveedor/otra carga; versiones mixtas no permitidas; no cancelación remota de HTTP |
| 54 | PROFILE-BETA-1 | NOT YET EVALUATED; no ejecución integral en B9D |
| 55 | Gates productivos | B0 cerrado, AGENT_B7B_CONSENT_ENABLED=False, AGENT_OPERATION_EXECUTION_ENABLED={} |
| 56 | Activation status | PENDING_ACTIVATION_REQUIREMENTS |
| 57 | Clínicas activadas | 0 por este trabajo; cero grants reales en código |
| 58 | Deploy | Ninguno; sin cambios a secretos/env productivos |
| 59 | B9E | Pendiente: perfil reproducible y aceptación integral EVAL/COST/SCALE del candidato, evidencia real |
| 60 | Recomendación | Partir del HEAD documental de esta entrega; evaluar el alcance sin abrir producción ni convertir fixtures en approvals |

El siguiente hito no se inicia en esta entrega. B9 y las aprobaciones operativas
siguen pendientes aunque el componente técnico complete su aceptación.
