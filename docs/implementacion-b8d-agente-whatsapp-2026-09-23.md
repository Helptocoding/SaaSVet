# Implementación B8D — CONFIRM_ATTENDANCE

Estado: **PARTIAL — aceptación técnica B8D completa; regresión histórica incompleta**.
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

## Cierre de aceptación y bloqueo residual

La cobertura única de B8D está completa: 64/64 funcionales, 26/26 corpus y
27/27 procesos PostgreSQL/failure injection. B8C quedó en 147/147. La regresión
B0–B8B, Agenda, Dashboard y signals alcanzó 1.447/1.462 IDs únicos; quedan 15
IDs sin ejecución final: 1 lock de Agenda, 13 escenarios multiproceso históricos de
B8A y 1 migración B4. Las repeticiones quedaron preparadas, pero PostgreSQL local
volvió a interrumpirse durante su recovery y rechazó conexiones; los runners fueron
detenidos sin ejecutar esos casos. No se cuentan como aprobados ni como fallos de
producto. El JSON conserva cada ID pendiente, journals, logs, hashes y la causa de
infraestructura. Por el criterio de cierre, B8D permanece PARTIAL y no se marca
COMPLETED hasta ejecutar esos 15 IDs y validar la regresión completa.

Las seis métricas críticas del corpus permanecen en cero. Checks Django, migraciones,
triggers/constraints y `git diff --check` terminaron limpios antes de la última
interrupción del servidor. No hubo despliegue ni cambios de configuración productiva.

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
