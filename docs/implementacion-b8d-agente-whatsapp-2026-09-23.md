# Implementación B8D — CONFIRM_ATTENDANCE

Estado: **COMPLETED técnico — aceptación B8D y regresión histórica completa**.
No autoriza activación. Implementación iniciada 2026-09-23; aceptación continuada
hasta 2026-09-25.
Baseline y HEAD inicial: `b0d2d347ecb3b50ec0637122ec2460480b81dced`, cierre documental
B8C verificado. El plan canónico real tiene sufijo `2026-09md`; §7 confirma B8D
asistencia. No se repitió auditoría H01–H20 ni se avanzó a B8E.

Cambios ajenos preservados: eliminaciones de DEPLOY_VPS_PLAN.md y
DEPLOY_VPS_STATUS.md; auditoría del 2026-09-10 sin seguimiento.

Commit de implementación, contrato, migraciones, corpus y pruebas:
`5a308c6e29174056ddce15cd14b2eebfbe776489`.

## Contrato y frontera

[Contrato congelado](contrato-confirm-attendance-b8d.md) y
[ADR](decisions/2026-09-23-b8d-confirm-attendance.md).
confirmed declara intención de asistir a una cita futura; no registra llegada,
inicio de consulta, done/no_show, MedicalRecord, Invoice, Payment ni inventario.
Human /status/ y adapter comparten confirm_locked/ALLOWED_TRANSITIONS y auditoría.
La política humana de fechas se conserva. B8D restringe a scheduled futura y activa,
sin MedicalRecord asociado. Walk-in normal in_progress no es elegible.

Parámetros B7A v1 intactos; preconditions 3 incorpora snapshot B8C y
attendance_contract=1 al digest. La propuesta muestra cita pública exacta, mascota,
fecha/extremos/zona/veterinario. CONTEXTUAL_DECLARATION solo en definiciones nuevas,
con emisión B4 y causalidad B7B: reply-to con declaración completa cerrada o token
exacto. Policy 2 no reinterpreta policy 1 ni amplía paráfrasis por LLM.

Locks B8A, seguidos de Organization FOR SHARE, vet por PK, Appointment FOR UPDATE,
owner/pet FOR SHARE. Snapshot comparado después del lock. El guard vuelve a comprobar
permiso, binding/identity/ownership, evidencia, TTL, safety/handoff, takeover y input.
La transacción incluye transición, auditoría, ledger, ToolExecution y resultado.

Evidencia histórica: AppointmentMutationEffect único por operation_key y digest,
FK exacta, before/after y committed_at DB; OneToOne a la auditoría, PROTECT e
inmutabilidad por trigger. No source_operation B8B. Reconcile consulta antes de
ejecutar y en replay terminal: ausencia comprobada permite validar, exactitud produce
SUCCEEDED, contradicción produce UNCERTAIN sin retry ciego. No regresa estados
posteriores a confirmed ni atribuye confirmaciones humanas al agente.

Side effects: una auditoría y una invalidación dashboard on_commit robusta.
Notificaciones de cita son derivadas por consulta, sin envío remoto en la transición.
Los replays no repiten save ni auditoría. Consentimiento registrado no afirma ejecución.

## Migraciones y rollback

- agent.0027_attendance_consent_policy: extiende constraint de evidencia de decisión
  únicamente a policy 2 de asistencia con schema 3/contract 1.
- appointments.0018_confirm_attendance_effect: nuevo kind permitido y OneToOne nullable
  a auditoría, con trigger de confirmación; mantiene evidencia B8C sin backfill.

Rollback funcional: cerrar flag CONFIRM_ATTENDANCE y conservar B0 cerrado; no borrar
evidencia ni devolver citas a scheduled. Mantener lector compatible con schema 3.
No migración inversa sobre datos B8D.

## Aceptación y reproducción

Evidencia por corrida en [JSON](evals/b8d-acceptance-results.json); corpus versionado
separado en [corpus v1](evals/b8d-confirm-attendance-corpus-v1.json).
Runner: backend/apps/agent/tests/run_b8d_acceptance.py. DATABASE_URL explícita a
PostgreSQL local; bases test_b8d_ para B8D y test_b8b_ para inventario B0–B8B.
La regresión B8C conserva su runner y prefijo test_b8c_. No producción ni proveedores.

```text
python -m apps.agent.tests.run_b8d_acceptance --suite unit --database test_b8d_acceptance --output <prefijo-unit>
python -m apps.agent.tests.run_b8d_acceptance --suite corpus --database test_b8d_corpus --output <prefijo-corpus>
python -m apps.agent.tests.run_b8d_acceptance --suite processes --database test_b8d_acceptance --output <prefijo-processes>
python -m apps.agent.tests.run_b8d_acceptance --suite baseline --database test_b8b_b8d_baseline --output <prefijo-baseline>
python -m apps.agent.tests.run_b8c_acceptance --suite b8c --database test_b8c_b8d_regression --output <prefijo-b8c>
python -m apps.agent.tests.run_b8d_acceptance --suite checks --database test_b8d_acceptance --output <prefijo-checks>
```

Entorno: PostgreSQL 16.15 local puerto 25432, Python 3.13.2, Django 6.0.5,
dependencias conservadas de B8B. Hash MD5 exclusivamente para passwords sintéticos
de fixtures. El servidor hizo recovery al iniciar; quedó ready antes de tests.

La primera suite funcional ejecutó 56 IDs: 10 aprobados y 46 errores por constraint
de consentimiento todavía restringida a policy 1. Se conserva el fallo y se incorpora
la migración agent.0027; la corrida posterior es independiente. No se presentan
corridas parciales o repetidas como una única ejecución ininterrumpida.
La segunda corrida ejecutó 63 IDs: 62 aprobados y un error de fixture que cambiaba
el modo dejando policy 2, lo que correctamente violaba la constraint nueva. La
fixture cambia ambos campos y el guard rechaza la definición; reparación dirigida
de ese caso y nueva prueba del inspector: 2/2. Total funcional único aprobado: 64.

Corpus independiente: 26/26. Multiproceso B8D: 27 IDs únicos, incluyendo revocación
real de ContactIdentity en ambos órdenes. La primera corrida de 25 tuvo 23 aprobados
y dos casos sin aprobación por timeout de conexión, con cuatro errores contando
teardown; los dos casos de takeover se repitieron y aprobaron 2/2. La ampliación
de revocación de identidad se ejecutó por separado y aprobó 2/2.

La regresión secuencial B0–B8B/Agenda se interrumpió deliberadamente tras registrar
547 IDs aprobados y se repartieron los 915 pendientes en tres bases independientes.
Después, el PostgreSQL local dejó de aceptar conexiones; también afectó la corrida
B8C. No se atribuyen esos errores a una violación del contrato ni se cuentan como
aprobados. Los journals y hashes conservan la evidencia; las ejecuciones de recuperación
usan nuevas bases clonadas del esquema final y únicamente IDs sin aprobación.
Las corridas originales B0–B8B/B8C comenzaron antes de añadir agent.0027; se conserva
la cobertura policy 1, y los casos pendientes B7B/B8A, las recuperaciones y los checks
finales se ejecutan con ambas migraciones B8D. No se modificó lógica productiva para
eludir un fallo de infraestructura.

Las pruebas históricas que declaraban CONFIRM_ATTENDANCE sin adapter se actualizan
al contrato B8D, conservando sus IDs; REGISTER_PET sigue probado DISABLED. Las pruebas
de contextual legacy usan explícitamente el schema previo con su digest original.

## Primer cierre PARTIAL y bloqueo histórico preservado

En el primer cierre, la cobertura única de B8D estaba completa: 64/64 funcionales, 26/26 corpus y
27/27 procesos PostgreSQL/failure injection. B8C quedó en 147/147. La regresión
B0–B8B, Agenda, Dashboard y signals alcanzó 1.447/1.462 IDs únicos; quedaron 15
IDs sin ejecución final: 1 lock de Agenda, un grupo de 13 escenarios históricos de
concurrencia (11 B8A, 1 Inbox y 1 Agenda) y 1 migración B4. Las repeticiones quedaron preparadas, pero PostgreSQL local
volvió a interrumpirse durante su recovery y rechazó conexiones; los runners fueron
detenidos sin ejecutar esos casos. No se cuentan como aprobados ni como fallos de
producto. El JSON conserva cada ID pendiente, journals, logs, hashes y la causa de
infraestructura. Por el criterio de cierre, B8D se mantuvo PARTIAL en ese
commit; la recuperación posterior se acredita por separado a continuación.

Las seis métricas críticas del corpus permanecen en cero. Checks Django, migraciones,
triggers/constraints y `git diff --check` terminaron limpios antes de la última
interrupción del servidor. No hubo despliegue ni cambios de configuración productiva.

### Cierre recuperado del 2026-09-25: COMPLETED técnico

HEAD inicial: `0e57b0faace7f29f85f28d8ec20d134143fc5d11`.
**15/15 IDs originales recuperados, regresión histórica 1.462/1.462**.
No hubo cambios runtime, de tests, fixtures o migraciones históricas. El hash
de fuentes agent/appointments coincide con la aceptación anterior. Las 117 pruebas
B8D y las 147 B8C mantienen su aceptación previa, sin repetición innecesaria.

El primer preflight de esta continuación quedó BLOCKED por recovery incompleto:
`pg_controldata` mostraba `in crash recovery`, `postmaster.pid` estaba en `starting`
y las conexiones nuevas eran rechazadas. No se ejecutó ninguna prueba en ese estado.
Mientras se registraba esa evidencia, PostgreSQL terminó naturalmente redo y el
checkpoint de fin de recovery; el log registra `ready to accept connections` a
las **00:41:27.029 CST**. Se repitió el preflight completo antes de ejecutar tests:
PostgreSQL **16.15**, `pg_is_in_recovery() = false`, conexiones nuevas aceptadas,
sin sesiones cliente de suites anteriores, sin locks en espera ni transacciones
preparadas. No se demostró corrupción ni se aplicó reset, reinicio forzado o borrado
para superar el bloqueo. La duración previa del recovery no se atribuye al producto.

Se verificaron directorio y cluster esperados: proceso 25944,
`C:/Users/LAP/AppData/Local/Temp/vet-b8b-pg16-data`, loopback puerto 25432,
identificador **7688148963531070156**. No se intervino otro árbol PostgreSQL
cuya línea de comando era inaccesible. La base `test_b8d_acceptance` tenía ambas
migraciones B8D; la base archivada `test_b8b_b8d_baseline` aún carecía de agent.0027,
coherente con el inicio de aquella corrida antes de esa migración. Se conservó
intacta y se creó **test_b8b_b8d_closure_20260925**, vacía y con todas las migraciones
aplicadas antes del primer caso recuperado.

Cada ID se ejecutó en una invocación independiente del runner existente, en serie,
con el ID y las assertions originales. Se comprobó una conexión SQL nueva, esquema,
sesiones y locks después de cada caso. La columna de tiempo corresponde a `Ran 1
test in ...` del runner, incluyendo setup/teardown; el JSON conserva además la
duración total de la invocación. No hubo fallos de producto, fixture, timeout o
infraestructura durante estas 15 ejecuciones. Los fallos de preflight y las corridas
anteriores siguen separados de estos resultados.

| # | ID original | Resultado | Segundos | Procesos secundarios del test | PostgreSQL posterior |
| --- | --- | --- | ---: | ---: | --- |
| 1 | `apps.appointments.tests.test_vet_lock_race.LockAppointmentAndVeterinariansServiceTests.test_retry_recovers_and_locks_the_real_veterinarian` | PASSED | 23.125 | 0 | Operativo |
| 2 | `apps.agent.tests.test_b8a_processes.B8AProcessTests.test_fi01_crash_before_locks` | PASSED | 30.740 | 1 | Operativo |
| 3 | `apps.agent.tests.test_b8a_processes.B8AProcessTests.test_race01_fi08_two_executors_one_effect` | PASSED | 30.938 | 2 | Operativo |
| 4 | `apps.agent.tests.test_b8a_processes.B8AProcessTests.test_race02_fi07_correction_wins` | PASSED | 29.425 | 2 | Operativo |
| 5 | `apps.agent.tests.test_b8a_processes.B8AProcessTests.test_race03_effect_before_correction_is_not_undone` | PASSED | 31.021 | 2 | Operativo |
| 6 | `apps.agent.tests.test_b8a_processes.B8AProcessTests.test_race04_fi06_takeover_wins` | PASSED | 29.181 | 2 | Operativo |
| 7 | `apps.agent.tests.test_b8a_processes.B8AProcessTests.test_race05_effect_before_takeover_is_not_undone` | PASSED | 36.110 | 2 | Operativo |
| 8 | `apps.agent.tests.test_b8a_processes.B8AProcessTests.test_race06_revocation_committed_before_effect` | PASSED | 31.642 | 2 | Operativo |
| 9 | `apps.agent.tests.test_b8a_processes.B8AProcessTests.test_race07_fi03_independent_commit_before_ledger_reconciles` | PASSED | 29.925 | 2 | Operativo |
| 10 | `apps.agent.tests.test_b8a_processes.B8AProcessTests.test_race08_fi02_crash_after_authorization_before_effect` | PASSED | 25.552 | 1 | Operativo |
| 11 | `apps.agent.tests.test_b8a_processes.B8AProcessTests.test_race09_retry_uncertain_has_no_blind_effect` | PASSED | 31.697 | 2 | Operativo |
| 12 | `apps.agent.tests.test_b8a_processes.B8AProcessTests.test_race10_replacement_during_preparation_cannot_execute_old_definition` | PASSED | 26.259 | 1 | Operativo |
| 13 | `apps.agent.tests.test_inbox_api.InboxSendIdempotencyRaceTests.test_two_real_concurrent_sends_replay_single_winner` | PASSED | 22.280 | 0 | Operativo |
| 14 | `apps.appointments.tests.test_no_overlap.RepeatedConcurrentCreationTests.test_five_hundred_races_never_produce_a_500` | PASSED | 84.986 | 0 | Operativo |
| 15 | `apps.channels.tests.test_b4_migration.B4MigrationTests.test_legacy_rows_keep_states_ids_and_null_evidence` | PASSED | 152.026 | 0 | Operativo |

El grupo antes denominado «13 B8A multiproceso» contiene **11** IDs de
`B8AProcessTests`, uno de Inbox y uno de Agenda. Los 11 B8A usan los procesos
independientes originales y PostgreSQL real; sus assertions verifican bloqueo,
fencing, ownership, guard final, atomicidad, reconciliación y precedencia de
corrección/revocación/takeover según cada escenario. Inbox y las 500 carreras de
Agenda conservan sus threads históricos con conexiones PostgreSQL independientes;
no se presentan como pruebas multiproceso ni se sustituyen los tests originales.
El lock de Agenda conserva su carrera controlada y prueba el retry sobre el
veterinario real. B4 conserva IDs/estados/evidencia nula de filas legacy y restaura
el esquema final, incluidas las dos migraciones B8D. Los cinco archivos históricos
de tests y appointments/services.py no difieren del baseline B8C.

El JSON registra cada ID, suite, tiempos, salida del runner, subprocess audit,
workers PostgreSQL observados, salud posterior y hashes de artifacts. Hubo
**19 procesos secundarios B8A**. Las seis carreras race01–race06 aprobaron la
assertion histórica `blocked()`, que consulta `pg_stat_activity` y exige una espera
`Lock` antes de liberar al primer worker. El observador externo cada 50 ms no
capturó esas ventanas breves; se registra cero en ese muestreo, sin sustituir la
evidencia de las assertions originales. El audit hook contó lanzamientos; su
prefijo argv quedó limitado en Windows y no se usa para identificar workers:
los identifica `application_name=b8a_<PID>` observado en PostgreSQL.
Ambos observadores solo registran ejecución; no cambian decisiones, mocks,
fixtures o assertions. Los workers terminados por
failure injection pertenecen a los tests originales; no se mataron procesos para
recuperar infraestructura.

Checks finales: **django check**, **makemigrations --check --dry-run**,
**migrate --check**, plan de migraciones completo y **git diff --check** aprobados.
PostgreSQL quedó operativo, fuera de recovery, sin sesiones cliente ajenas al
chequeo y sin locks en espera. `closure_acceptance` conserva el primer preflight
bloqueado, su recuperación natural, el inventario previo 1.447/1.462 y las 15
invocaciones nuevas. Los `runs` y `checks` anteriores permanecen intactos; el cierre
no representa una única ejecución ininterrumpida desde la primera aceptación.

**B8D COMPLETED no autoriza activación.** B0 continúa cerrado,
`AGENT_OPERATION_EXECUTION_ENABLED={}`, `AGENT_B7B_CONSENT_ENABLED=False`,
REGISTER_PET sin adapter y deshabilitado. Las comprobaciones corresponden al
repositorio y al entorno local; no hubo intervención productiva.
PENDING_ACTIVATION_REQUIREMENTS permanece, no hubo deploy y B8E no se inició.

## Matriz de evidencia B8D

| Invariante | Evidencia específica |
| --- | --- |
| Cita exacta, tenant y snapshot | CONF-01/02/03/04, FK frente a parámetro, cambio de vet/UTC/walk_in y propietario |
| Intención futura, sin atención clínica | CONF-01/07/11/12, consulta asociada bloqueada; filas clínicas, financieras e inventario intactas |
| Autoridad humana compartida | /status/ real para confirmación/reprogramación, prueba de fechas pasadas humanas; API AGENT 403 |
| Consentimiento causal vigente | 22 rechazos parametrizados B8A; declaración exacta referenciada, token, legacy cerrado, safety signal |
| Confirmación humana previa no atribuida | CONF-08 mediante endpoint real; carrera humana/agent en ambos órdenes |
| Efecto durable único | Ledger y OneToOne a auditoría, trigger inmutable, dos workers de la misma operación |
| Historia sin reversión | CONF-09/10; kill después del commit y retry tras confirmed/in_progress/done |
| LOCAL_ATOMIC | Kill antes de locks, después de lock, después de UPDATE y después de evidencia; SQL division-by-zero al persistir evidencia |
| Precedencia de cambios | Dos operaciones sobre la misma cita, confirmación contra cancelación/reprogramación y corrección/revocación/takeover, ambos órdenes |
| Identidad actual | Revocación real ContactIdentity→Operation, ambos órdenes, sin invertir lock de Conversation |
| Evidencia contradictoria | Corrupción SQL controlada del ledger o auditoría → UNCERTAIN; ninguna repetición ciega |
| Side effects sin repetición | Una auditoría y una invalidación de dashboard por efecto; retry no guarda Appointment |
| Gates y capacidad prohibida | CONF-15, flag estrictamente True, falta de adapter, B0, REGISTER_PET con flag accidental |

Los workers son procesos Python independientes con conexiones PostgreSQL propias;
pg_stat_activity acredita esperas Lock. Los hooks de prueba solo fijan barreras o
inyectan el error SQL: las transiciones, locks, commit y terminación de procesos son
reales. Los threads auxiliares únicamente leen stdout. Las pruebas humanas históricas
que usan threads se reportan como regresión humana, sin sustituir este multiproceso.

## Desviaciones y riesgos residuales

- Se conserva el nombre real del plan canónico con sufijo `2026-09md`; no se crea
  una fuente de verdad paralela con el nombre del prompt.
- El contrato contextual y su constraint versionada eran necesarios para B8D según
  el plan. Las operaciones legacy no adquieren autorización retrospectiva.
- La restricción de cita futura y ausencia de MedicalRecord pertenece al comando
  autónomo; Agenda humana conserva su política preexistente.
- Ante SQL/error de adapter se mantiene UNCERTAIN aunque el test pueda observar el
  rollback local; la recuperación no convierte ausencia en permiso de reejecución.
- No se ensayó tráfico productivo, entrega WhatsApp real ni activación clínica/Inbox.
  Los gates existentes de identidad, semántica, privacidad y operación siguen vigentes.

## Gates y readiness

CREATE_APPOINTMENT B8B, RESCHEDULE_APPOINTMENT/CANCEL_APPOINTMENT B8C y
CONFIRM_ATTENDANCE B8D tienen adapter; todos permanecen OFF para producción.
REGISTER_PET sin adapter y DISABLED incluso con flags accidentales.
B0 sigue cerrando todas las WRITE_BUSINESS, AGENT_OPERATION_EXECUTION_ENABLED={}
y AGENT_B7B_CONSENT_ENABLED=False por defecto. No se editó configuración productiva.
**PENDING_ACTIVATION_REQUIREMENTS permanece; no hubo despliegue.**
B8E no está implementada ni habilitada; B8D no constituye aprobación de B8E o B9.
Riesgos operativos de identidad compartida/reciclada y validación clínica/Inbox de
activación conservan sus gates. Ninguna prueba local acredita exactly-once externo.
