# Implementación B9A — Harness HTTP/worker/sender

Estado final: **B9A COMPLETED técnico**, cierre de aceptación 2026-09-27.
B9 canónica: **IN_PROGRESS**.
Baseline/HEAD inicial: `55d122bcfb26f41b7f23ce0bb523b464017f3a4c`.
Commit de implementación: `867f7af7f0e716a2b4d5f694054763c268a147e3`.
Aceptación: 45/45 IDs B9A, 2.097/2.097 históricos y 94 adicionales; checks verdes.
No se declara PROFILE-BETA-1 ni EVAL/COST/SCALE aprobado. Activación:
**PENDING_ACTIVATION_REQUIREMENTS**. Ninguna clínica activada por este trabajo.

## Alcance y evidencia

- [Mapa interno B9A–B9E y extracción literal B9](mapa-interno-b9-2026-09-26.md).
- [Contrato del harness](contrato-harness-b9a.md).
- [ADR](decisions/2026-09-26-b9a-application-e2e-harness.md).

R02/R14 pertenecen a B9A. R03/R05/R11 a B9B; R04/R12 a B9C; R13 a B9D;
R01/R06–R10/R15 a B9E. Cada requisito tiene un dueño único. Dependencias internas
A → B → C → D → E; no se enmienda el alcance canónico para ajustar el encargo.
La discrepancia del encargo anterior se conserva como evidencia independiente.

Runtime modificado: durable.py conecta la decisión B7B con el guard B8A;
operation_execution.py construye recibo solo con EffectEvidence exacta;
tools.py conserva observed_at al derivar la disponibilidad comprobada;
operation_proposals.py aclara el significado de confirmar. Los comandos
agent_eval/agent_eval_conversations exponen un modo de aplicación aislado con
selección, ejecución y recibo explícitos. No hay migraciones ni schema nuevo.

Se preservan y excluyen de commits las eliminaciones preexistentes de
DEPLOY_VPS_PLAN.md/DEPLOY_VPS_STATUS.md y la auditoría 2026-09-10 sin seguimiento.
También se conserva sin incorporar el documento local de discrepancia del
encargo anterior. No se restauran, borran ni incorporan como parte de B9A.

## Pruebas

El harness usa HTTP firmado de aplicación, worker B3 y sender B4 reales. READ
pública/personal recorren DRF/RBAC; las cinco operaciones tienen guiones con
consentimiento y efecto de dominio reales. Asistencia y registro requieren las
fixtures de asunto/campo B6 descritas en el contrato; no se presentan como
extractores naturales implementados. Ningún guion llama al guard/adapter como
sustituto del worker. Su caller se observa sin reemplazar funciones.

Escenarios: firma/payload/handshake, duplicates, bursts y turnos consecutivos,
caption/reply/action, retry, accepted/failed/uncertain/status, handoff/safety,
takeover, propuesta pending no confirmable, confirmación causal/contextual,
corrección, tenant cruzado y gates cerrados. Inyección SQL antes de outbox y
después del efecto comprueba el rollback atómico. Los PIDs independientes prueban
duplicate worker/sender/webhook, kill después de claim y antes de publicación,
aceptación externa con respuesta local perdida, retry tras commit, fencing del
worker antiguo y progreso de dos tenants.

Los journals tienen IDs de test, estados/etapas, PIDs de intérprete y backend;
no requieren leer logs libres para afirmar que una etapa se atravesó. Los
threads solo leen stdout. Reconciliation sin wamid local permanece incierta;
con ID previamente observado puede consumir un status firmado. No hay garantía
de delivery Meta ni exactly-once remoto o pérdida eléctrica.

### Entorno y recuperación

Python 3.13/Django 6.0.5 del entorno bloqueado B8B, PostgreSQL 16.15 local.
Primera instancia dedicada B9A: puerto 35434, role b9a, bases test_*.
La interrupción de functional2 dejó su resultado incompleto; PostgreSQL completó
recuperación natural con fsync/synchronous_commit ON. Se preservaron log/journal.
Mientras recuperaba se creó otro cluster vacío en 35435 y se aplicó todo el
schema desde cero. No se resetearon WAL ni se desactivó durabilidad.

functional3 (26 tests) terminó 18 aprobados/8 fallidos por fixtures de asistencia
y observed_at omitido en el resultado real de slot. Se corrigieron sin retirar
preconditions. El diagnóstico dirigido mostró CREATE y CONFIRM con efecto real;
no sustituye la aceptación. processes1 completó 9/9 sin skips ni errores.
functional4 terminó 32/33: la fixture uncertain requería uncertain_at. La corrida
del comando conversacional detectó además una expectativa sent incorrecta tras
un status delivered y una fixture negativa que intentaba editar Operation por
ORM. Se corrigieron respetando B4 y la inmutabilidad: la última usa inyección SQL
explícita para comprobar el rechazo B8A. Ambas correcciones tienen recuperación
dirigida aprobada. El comando rechazó correctamente el recibo fallido.

La repetición multiproceso con la instrumentación final terminó 8/9 por timeout
de arranque de un hijo; PostgreSQL registró un error local CreateProcess en esa
ventana. Su ID exacto se recuperó junto con reconciliación: 2/2. No se amplió el
timeout ni se ignoró el fallo ni se alteró durabilidad. Una repetición conversacional
que había cargado la fixture anterior se detuvo expresamente, preservando sus
artefactos; antes de reiniciar se verificó ausencia de conexiones y se limpió solo
su base sintética local. La corrida vigente usa el prefijo conversations-verified.

Al reanudar el 27 de septiembre se verificaron B8A/B8B 166/166, B8C 146/146,
B8D 117/117, dominios 430/430 y el comando conversacional 30/30. El bloque
Agent/Channels terminó 1.114 IDs aprobados y un timeout PostgreSQL en setUpClass
de GoalQualityTests: sus cuatro IDs no ejecutados se recuperaron exactamente,
4/4, sin cambiar tests ni runtime. B8E terminó 120/120 el 27 de septiembre. Las pruebas
adicionales de Organizations/RBAC terminaron 94/94 tras corregir una expectativa
F2 obsoleta (POST directo AGENT ahora debe ser 403 por B8A, con cero efectos).
Ese ID se conserva; no se cambió runtime de permisos. La consolidación final usa
IDs exactos y conserva corridas fallidas/interrumpidas, sin sumar repeticiones.

Las instantáneas de código de B8B/legacy preceden únicamente la protección del
prefijo de salida del comando nuevo. Ese modo está cubierto por los seis tests
de comandos y las dos invocaciones reales. durable/guard/propuesta/slot coinciden
con el commit de implementación en todas las corridas aceptadas. La repetición
multiproceso usa la instrumentación final; las correcciones posteriores de dos
fixtures negativas no alteran los helpers de proceso que esa suite importa.

El histórico se extrae de la unión de test_ids/passed_ids de la aceptación B8E:
2.097 IDs únicos. Partición sin duplicados: B8A/B8B/guard 166; B8C 146; B8D 117;
B8E 120; resto Agent/Channels 1.118; dominios 430. Bases separadas conservan los
prefijos exigidos por los procesos B8. Organizaciones/RBAC reciben una corrida
complementaria; no se suman como histórico si no estaban en el inventario B8E.

## Resultado final de aceptación

[Recibo versionado por ID](evals/b9a-acceptance-results.json): **2.236 IDs únicos
aceptados**, cero IDs pendientes y cero skips/xfail. Las repeticiones y los tres
READ del comando no incrementan la unión. Se conservan fallos previos, errores de
fixture e interrupciones; los IDs afectados fueron recuperados explícitamente.

| Grupo | Aceptación |
| --- | ---: |
| B9A conversacional READ/WRITE, HTTP/worker/sender | 30/30 |
| B9A comandos | 6/6 |
| B9A procesos independientes | 9/9, incluida recuperación de un arranque |
| Histórico B8A/B8B | 166/166 |
| Histórico B8C | 146/146 |
| Histórico B8D | 117/117 |
| Histórico B8E | 120/120 |
| Histórico restante Agent/Channels | 1.118/1.118, incluidos cuatro IDs recuperados |
| Histórico dominios | 430/430 |
| Organizations/Core/Users adicionales | 94/94 |

El histórico exacto contiene Agent 1.616, Channels 51, Appointments 99, Patients
88, MedicalRecord 102, Dashboard 63 e Imports 78. Los 94 adicionales son
Organizations 51, Core/permissions 17 y Users/RBAC 26.

Ambos comandos reales terminaron correctamente: agent_eval 3/3 y
agent_eval_conversations 30/30. Siguen devolviendo beta_acceptance=PENDING.
Los cinco WRITE verifican propuesta emitida, AuthorizationEvidence, guard único,
adapter/efecto/ledger reales y recibo aceptado por el wire controlado. READ pública
y personal también atraviesan JWT/DRF cuando corresponde.

Se observaron procesos B9A independientes, por ejemplo PID 26320 con backend
PostgreSQL 44012; el recibo conserva todos los pares y etapas. Las carreras
históricas B8C/B8D/B8E registran postgres_wait=Lock con PID por caso. B9A comprueba
leases/admisión/fencing; no presenta threads lectores de pipes como workers.

Checks del 27 de septiembre: Django check sin incidencias, makemigrations
--check --dry-run sin cambios, migrate --check verde, git diff --check verde;
PostgreSQL 16.15, fsync=on, synchronous_commit=on y fuera de recovery. B9A añade
cero migraciones; se verificaron las constraints del ledger de registro y el
schema aplicado desde cero en el cluster alternativo aislado.

Al terminar se apagaron ambos clusters PostgreSQL temporales de la suite. El
cluster principal completó su checkpoint de cierre después del timeout inicial
de espera de pg_ctl; no se forzó su terminación. Se conservan bases, logs y
artefactos locales para reproducción, sin servicios de prueba pendientes.

H16 recibe evidencia de composición del harness; su gate integral permanece
pendiente de B9E. H19 no se cierra. No se declaran resueltos identidad fuerte,
teléfonos compartidos/reciclados, step-up, P-A/P-B ni garantías externas de entrega.

Se recomienda cerrar solo el hito interno B9A. B9B será el siguiente encargo:
contabilidad completa y reserva durable por TurnWork, reutilizando este conductor.
Este trabajo se detiene aquí; no inicia B9B, no activa clínicas ni despliega cambios.

## Reproducción

Desde backend, con DATABASE_URL explícita hacia PostgreSQL local y credenciales
solo de prueba. Artefactos fuera del repositorio, prefijo nuevo por corrida:

```text
rtk proxy python -m apps.agent.tests.run_b9a_acceptance --suite b9a --database test_b8b_b9a_acceptance --output <ruta>/functional
rtk proxy python -m apps.agent.tests.run_b9a_acceptance --suite processes --database test_b8b_b9a_processes --output <ruta>/processes
rtk proxy python -m apps.agent.tests.run_b9a_acceptance --suite targeted --ids-file <ids.json> --database test_b8c_b9a_history --output <ruta>/historical-c
rtk proxy python -m apps.agent.tests.run_b9a_acceptance --suite checks --database test_b8b_b9a_acceptance --output <ruta>/checks
rtk proxy python manage.py agent_eval --application-e2e --e2e-database test_b8b_b9a_command --e2e-output <ruta>/read
rtk proxy python manage.py agent_eval_conversations --application-e2e --e2e-database test_b8b_b9a_command --e2e-output <ruta>/conversations
```

El runner fija DISABLE_SENTRY=True/SENTRY_DSN vacío/REDIS_URL vacío antes de cargar
settings. Para manage.py establecerlos también en el proceso principal, antes
del arranque de Django. Los fakes solo interceptan wire; las pruebas no necesitan proveedores.
No usar `--suite historical` en una sola base para los workers B8: cada grupo
requiere su prefijo correspondiente. Un fallo/skipped/interrupción deja pendiente
el ID; recuperar exactamente esa lista sobre la misma fuente runtime final.

## Gates, límites y siguiente hito

Configuración efectiva inspeccionada: contención B0 de las siete tools WRITE,
AGENT_B7B_CONSENT_ENABLED=False, AGENT_OPERATION_EXECUTION_ENABLED={}.
No se consultaron ni modificaron datos productivos; activaciones efectuadas: 0.
No deploy, B9B–B9E, E1–E5 o P-A/P-B. Sin límites/cupos nuevos ni contabilidad LLM.
El código heredado de LLM mantiene sus limitaciones hasta B9B.

Pendiente operativo original: clínica piloto, responsable Inbox, responsable/
protocolo veterinario, revisión de privacidad y canal alternativo validados.
No se inventan nombres, aprobaciones o canales. Terminar el harness no acredita
readiness ni autoriza tráfico real. Siguen abiertos teléfonos compartidos/
reciclados, step-up, identidad física, cobertura humana y privacidad aplicable.

Rollback: mantener B0/flags cerrados y lector compatible B8E; preservar Operation,
consentimiento, effects y Message. No hay migración que revertir ni compensación
automática de efectos. El hito B9B debe reutilizar este conductor para contabilidad
y reserva de llamadas por TurnWork; se inicia solo en un encargo posterior.

### Pendientes para una futura autorización operacional

- [ ] Completar B9B–B9E y obtener aceptación integral del alcance concreto.
- [ ] Seleccionar clínica/cohorte y lista explícita de READ pública, READ personal
      y cada WRITE permitido; no asumir las cinco operaciones por defecto.
- [ ] Definir responsable humano de Inbox y cobertura operativa.
- [ ] Acreditar responsable/protocolo veterinario de seguridad clínica.
- [ ] Acreditar revisión de privacidad y evidencia P-A/P-B aplicable a las
      categorías/plazos comprometidos por el plan, en sus trabajos correspondientes.
- [ ] Validar el canal alternativo de escalamiento/fallback.
- [ ] Revisar runbook, versión compatible, pruebas de handoff y retiro de capacidad.
- [ ] Obtener aprobación humana separada antes de cualquier activación.

La suite B9A no rellena estos requisitos. No existe aprobación de una clínica
real en esta entrega ni se presenta un fixture como clínica lista para beta.
