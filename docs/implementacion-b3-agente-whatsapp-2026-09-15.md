# Acta de implementación — Fase B3 del agente WhatsApp

Fecha: 2026-09-15. Estado B3: **COMPLETED — cierre técnico recomendado**.
Activación real: **PENDING_ACTIVATION_REQUIREMENTS**. Sin despliegue.

## Base y commits

Base exacta: `a06b4f79faa0366c25f3a9f15c93ce1e2ff93eb5` (`a06b4f7`),
baseline B2 indicado por el usuario. Actas previas:
[B0](implementacion-b0-agente-whatsapp-2026-09-13.md),
[B1](implementacion-b1-agente-whatsapp-2026-09-14.md),
[B2](implementacion-b2-agente-whatsapp-2026-09-15.md).

El hash técnico se registra después de crear el commit; el cierre de acta va
en un commit documental posterior para evitar autorreferencia.
Los borrados preexistentes de `DEPLOY_VPS_PLAN.md` y `DEPLOY_VPS_STATUS.md`, y
el archivo no seguido `docs/auditoria-agente-conversacional-veterinario-2026-09-10.md`
quedan fuera de B3 y sus commits.

## Alcance y contratos finales

Exclusivamente B3/C4/C5 del
[plan canónico](plan-implementacion-auditoria-agente-whatsapp-2026-09md).
No se repitió la auditoría H01–H20 ni se rediseñaron B0/B1/B2. Descubrimiento
dirigido por el grafo del repositorio y lecturas de los símbolos afectados;
fallback de búsqueda cuando el índice estaba desfasado.

Contrato completo: [trabajo durable B3](contrato-trabajo-durable-b3.md).
Decisión combinada: [ADR B3](decisions/2026-09-15-b3-durable-turn-ownership-publication.md).

| Frontera | Contrato implementado |
| --- | --- |
| Trabajo | TurnWork, cuatro estados, identidad conversación+anchor, máximo un no terminal impuesto en PostgreSQL |
| Membership | FK Message.turn_work; miembros/evidencia causales fijos, sin tabla intermedia ni snapshot |
| Causalidad | Cursor exclusivo B1 `(created_at,id)`, anchor y reloj contextual persistidos; recuperación del mismo TurnContext |
| Claim | Transacción corta, reloj DB, único lease_token UUID, CAS, lease 15 min, deadline local 12 min |
| Recuperación | Mismo W1, nuevo token, attempts+1, token anterior sin autoridad; polling existente |
| Retry | Máximo 3 intentos; backoff 30/60 s; FAILED con causa, inbound pendiente asignado y sin replay implícito |
| Ownership | Epoch monotónico, legacy 0; takeover/release/reset/cierre invalidan bajo lock común |
| Witness | VO inmutable org/conv/work/token/epoch, consulta vigente y CAS al mutar/finalizar |
| Publicación | Cambios locales y diagnóstico + outbound final PENDING + completion en un commit; ordinal determinista |
| Input posterior | W1 termina deferred_to_new_input sin outbound; W2 toma el input nuevo, sin reiniciar W1 |
| Sender | Selección/dispatch actual comprueba epoch/scope/work; conserva transporte sin lifecycle B4 |
| Legacy | Campos nuevos nullable, sin backfill ficticio; pending sin epoch se descarta como legacy_unverified |
| Autoridad B2 | COMPLETED no acredita efecto de negocio; ToolOutcome/manifiesto y containment permanecen vigentes |

## Archivos runtime modificados

Bajo `backend/apps/agent/`:

- `models.py`: Conversation.ownership_epoch y TurnWork.
- `durable.py` (nuevo): claim/reclaim, witness, CAS, finalización, retries y
  helper común de invalidación de ownership.
- `turn_changes.py` (nuevo): cambios locales y texto exclusivamente en memoria;
  referencias de secuencia reservadas sin filas hasta el commit final.
- `worker.py`: polling durable, TurnContext desde trabajo, commit final y
  selección sender compatible con epoch/legacy; conserva HTTP legacy.
- `outbound.py`: acumulación del output final y publicaciones locales fuera
  de turno bajo lock/epoch vigente.
- `planner.py`, `goals.py`, `confirmations.py`, `identity.py`,
  `identity_evidence.py`, `policy.py`, `tools.py`, `executor.py`,
  `operation_authorization.py`: escritores/lectores locales usan el buffer del
  turno; LLM/HTTP fuera de la transacción final; diagnóstico correlacionado.
- `prompts.py`: solo lectura de identidad suspendida desde estado local en
  memoria; no se cambia texto/version de prompts ni semántica B1/B2.
- `services.py`: inbound bajo lock, miembros no retroactivos, release basado
  en TurnWork/epoch, reparación de duplicados con orden de locks compatible.
- `views.py`: takeover/send/close/reset/unlink con invalidación común.
- `management/commands/remediate_identity_f0.py`: reset operativo existente
  invalida autoridad bajo locks de Conversation antes de modificar identidad.

`backend/apps/channels/models.py`: FK TurnWork, output_ordinal, origin_epoch,
constraints de correlación/ordinal. Se conservan estados y campos legacy.

Tests/harness: `test_b3_durable.py`, `test_b3_processes.py`, `b3_process.py`
(nuevos), `harness.py`, `test_worker.py`, `test_w0_hardening.py`,
`test_w1_experience.py`, `test_release_service.py`, `test_intake_capabilities.py`.
CI: `.github/workflows/ci.yml`, gate obligatorio PostgreSQL con CriticalB3Runner
que no acepta skips/xfail ni ausencia de las fronteras críticas.

## Migraciones, constraints e índices

1. `agent.0022_conversation_ownership_epoch_turnwork`.
2. `channels.0011_message_origin_epoch_message_output_ordinal_and_more`.
3. `channels.0012_b3_scope_and_membership`.

Todas aditivas. Orden sin ciclo: anchor de TurnWork referencia Message existente;
la migración channels siguiente añade la FK inversa. No se borran campos ni datos.

Constraints: `turnwork_unique_anchor`, `turnwork_one_nonterminal` (parcial),
`turnwork_processing_lease`, `turnwork_completed_outcome`,
`message_unique_turn_output` (parcial), `message_turn_output_evidence`.
Índices: `turnwork_poll_retry`, `turnwork_poll_lease`, más FK/org implícitos.
Triggers PostgreSQL: `b3_turnwork_scope`, `b3_message_scope`,
`b3_conversation_epoch`; protegen scope, identidad causal, evidencia fija,
membership una vez reclamado y monotonía del epoch. Las pruebas comprueban
también el nombre real de las constraints parciales violadas.

Legacy Conversation recibe 0 como generación inicial, nunca evidencia de un
Message histórico. Inbound PROCESSED no recibe trabajo ficticio. Outbound
conserva origin_epoch NULL. processing_until/process_attempts quedan como
proyecciones; claim/release nuevos ya no los usan como autoridad.

## Failure injection ejecutada

| Frontera | Ejecución y aserción |
| --- | --- |
| Kill tras claim | Proceso independiente hace claim COMMIT y os._exit(17); inbound sigue PENDING |
| Lease expiry/restart | Se expira lease en DB; proceso nuevo ejecuta worker real sobre el mismo W1, nuevo UUID, attempts=2 |
| Worker viejo reaparece | Token antiguo no puede publicar, completar ni liberar trabajo recuperado |
| LLM timeout | Stub falla dentro del planner real en otro proceso; verifica ausencia de transacción durante LLM; fallback/handoff/completion coherentes |
| Antes de publicación | Buffer tiene goal/slots/decision/texto, DB no tiene esos cambios ni completion; recuperable |
| DB durante consolidación | PostgreSQL ejecuta división por cero tras insertar output y cambios locales; rollback de output, goal, decision y completion |
| Takeover durante planning | Cambio de epoch dentro de llamada controlada LLM; toda persistencia posterior rechazada |
| Nuevo inbound durante planning | M3 fuera de W1, cursor/members conservados, W1 deferred; siguiente trabajo procesa nuevo input |
| Webhook duplicado | Antes y durante trabajo no duplica Message ni crea otro turno lógico |
| Dos workers | Dos intérpretes independientes y conexiones reales compiten; solo un ganador/token/trabajo |
| Entrada continua | Cinco entradas sucesivas concluyen seis trabajos fijos; cada intento único, continuidad de slots y un output final |

No se ejecutaron escenarios Meta accepted/crash, timeout post-HTTP, 2xx sin wamid
ni expired SENDING: pertenecen a B4. Proveedores externos no invocados.

## Entorno y trazabilidad de validación

PostgreSQL **18.3** local aislado en `127.0.0.1:55439`, rol `b0_test`, base de
pruebas `test_b3` y clones `test_b3_1`..`test_b3_4`. Base de migraciones local
`b3`. Python **3.13.2**, Django **6.0.5** (B2 se validó en 6.0.3; esta es la
versión instalada actualmente). No se usan credenciales ni datos de producción.
LLM/Meta controlados mediante doubles; las transacciones, constraints, leases,
CAS, conexiones y procesos son reales. El gate CI existente usa PostgreSQL 16;
su ejecución remota no se presenta como evidencia local.

El wrapper temporal solo fija configuración de prueba y captura logs. La
migración de triggers aún no publicada se refinó durante implementación y se
reaplicó transaccionalmente únicamente en fixtures locales `b3/test_b3` y sus
clones; no es una instrucción de rollback de producción. Una ejecución con
`--keepdb --parallel` detectó que los clones conservaban el trigger anterior:
la comprobación de payload_type falló. Se confirmó por introspección, se
actualizaron también los clones y se repitió la suite. Esa pasada no se cuenta
como verde. `migrate` aplica las tres migraciones y `showmigrations`
las muestra [X]. Introspección PostgreSQL confirma cuatro constraints de
tabla B3, cinco índices explícitos/únicos y tres triggers con los nombres
documentados. `makemigrations --check --dry-run`: sin cambios detectados.

Ejecuciones de desarrollo no aceptadas como verde: corpus inicial falló al
importar TurnWork ausente; fixtures/adaptadores parciales produjeron errores
corregidos; regresión dirigida 215 tests detectó una referencia de Conversation
desactualizada al devolver ingestión; primera conjunta 691 detectó cuatro
expectativas legacy de draft y una ruta de diagnóstico fuera del worker.
No se ocultaron mediante skips/xfail. La pasada dirigida posterior pasó **56/56**
en **169.007 s**, incluidos los 41 escenarios B3 de ese punto y esas regresiones.
Al ampliar la regresión a intake aparecieron tres expectativas anteriores a B2
que negaban READ públicas antes del onboarding/después de un recibo. Se alinearon
con las seis READ públicas del baseline confirmado; no se cambió la política
runtime B2 ni se habilitó ninguna WRITE. La protección de membership se reforzó
también durante PENDING de retry, añadiendo su regresión explícita.

Durante una pausa la instancia PostgreSQL aislada se interrumpió; dos comandos
posteriores encontraron timeout de conexión. Se recuperó la misma instancia
por WAL y se repitió la validación. Esos timeouts de harness no cuentan como
tests aprobados ni como simulación de las fronteras B3.

### Resultados finales de aceptación

| Ejecución | Resultado | Duración |
| --- | --- | --- |
| Dirigida B3 + intake, CriticalB3Runner | **55/55**, incluidos 42 B3 y 13 intake | 181.317 s |
| Conjunta PostgreSQL, CriticalB3Runner, 4 procesos de suite | **708/708** | 560.974 s |
| B0 crítico separado, CriticalB0Runner, containment sin opt-in WRITE | **17/17** | 23.675 s |
| makemigrations --check --dry-run | **No changes detected** | n/a |
| showmigrations agent channels | **3 migraciones nuevas [X]** | n/a |
| Sintaxis de los Python afectados / YAML CI / enlaces relativos | **31 válidos / válido / 0 rotos** | n/a |

**0 fallos, 0 errores, 0 skips, 0 xfail.** Los procesos aislados B3 están
incluidos en ambas pasadas B3, no se simula la concurrencia con SQLite o mocks.
Total de aceptación sin sumar repeticiones: **725 casos únicos** (708 + 17).
El desglose de la conjunta es:

- **42 B3**: 39 durable/integración y 3 de procesos independientes.
- **39 B2**: resultados, transporte y capabilities.
- **163 compatibilidad/endpoints B2**: executor, tools, slots, WRITE legacy
  contenidos por opt-in exclusivo de test, precondiciones, planner, calidad
  y paginación de pacientes.
- **246 B1/continuidad**: worker, decisiones, prompts, webhook, continuidad,
  policy, arbiter, hardening, experiencia y F5.
- **218 rutas adicionales afectadas**: Inbox 46, release 25, evidencia de
  identidad 46, verificación 25, servicios 18, goals W2 34, identidad 11,
  intake 13.

Logs completos locales en `%TEMP%`, fuera del repositorio. Se registran hashes
SHA-256 para identificar exactamente las pasadas aceptadas; los logs no son
evidencia de llamadas reales a Meta/LLM ni de ejecución de CI remoto.

| Log | SHA-256 |
| --- | --- |
| vet_b3_dedicated_final.log | `b8796b45e3b4715b9145c611fe542bf5bad6fd2772ac6c75d44d1e0660b143ee` |
| vet_b3_release_final.log | `7f81d7371968a6f1b417403a7f826ed95a3aa1bb71ad89b4d45176337197bd2e` |
| vet_b3_b0_final.log | `a000171a6ccf6e9b13dc6799437c262a29ee86445d31c7e5c2a1a97996d90555` |
| vet_b3_migration_release.log | `93e6e2d5be3c054add80c0f19101608803f7ca8a7df1fa41f76bbb9a1f570f4a` |
| vet_b3_show_release.log | `41e16f2df44e272b6b4a8cf49a082bf89b20b05c7c56a84619093bd532d003af` |

### Comandos reproducibles

Desde `backend/`, con dependencias instaladas y PostgreSQL de prueba aislado.
La base del ejemplo es exclusivamente local; nunca apuntar estos comandos a
producción. El wrapper usado en la ejecución equivale a estas variables y
comandos, capturando stdout/stderr en los logs indicados en los resultados.

```powershell
$env:DATABASE_URL = 'postgresql://b0_test@127.0.0.1:55439/b3'
$env:SECRET_KEY = 'b3-local-test-only-key-longer-than-32-characters'
$env:ENVIRONMENT = 'dev'
$env:DEBUG = 'False'
$env:DISABLE_SENTRY = 'True'
$env:SENTRY_DSN = ''
$env:DISCORD_WEBHOOK_URL = ''
$env:OPENAI_API_KEY = ''

rtk proxy python manage.py test apps.agent.tests.test_b3_durable apps.agent.tests.test_b3_processes apps.agent.tests.test_intake_capabilities --testrunner apps.agent.tests.harness.CriticalB3Runner --keepdb --noinput --verbosity 2

$agentModules = @(
    'test_b2_results', 'test_executor', 'test_tools', 'test_slots',
    'test_write_tools', 'test_commit_preconditions', 'test_planner',
    'test_w3_quality', 'test_worker', 'test_turn_decision', 'test_prompts',
    'test_f2_continuity', 'test_policy', 'test_arbiter', 'test_w0_hardening',
    'test_w1_experience', 'test_f5_fase5', 'test_b3_durable', 'test_b3_processes',
    'test_inbox_api', 'test_release_service', 'test_identity_evidence',
    'test_identity_verification', 'test_services', 'test_w2_goals',
    'test_identity', 'test_intake_capabilities'
)
$suite = @($agentModules | ForEach-Object { "apps.agent.tests.$_" }) + @(
    'apps.patients.tests.test_pet_list_pagination',
    'apps.channels.tests.test_webhook'
)
rtk proxy python manage.py test @suite --testrunner apps.agent.tests.harness.CriticalB3Runner --keepdb --noinput --verbosity 2 --parallel 4
rtk proxy python manage.py test apps.agent.tests.test_b0_containment --testrunner apps.agent.tests.harness.CriticalB0Runner --keepdb --noinput --verbosity 2
rtk proxy python manage.py makemigrations --check --dry-run
rtk proxy python manage.py showmigrations agent channels
```

El runner B3 exige escenarios de proceso, recuperación, atomicidad y fencing;
ambos runners críticos rechazan skips, expected failures, ejecuciones vacías o
menos casos de los descubiertos. El gate CI ejecuta B3 sobre PostgreSQL antes de
la suite completa. La suite conjunta anterior conserva las pruebas de
componentes WRITE legacy con su opt-in de test preexistente; el gate B0 separado
verifica contención sin ese opt-in. Ninguna opción de aplicación abre WRITE.

## Desviaciones y decisiones acotadas

- **Tipo A:** el archivo canónico existente termina `2026-09md`, sin punto antes
  de md; se usa su ruta real. Harness B3 vive en tests/probe dedicados más gate
  de harness existente; no se crea infraestructura distribuida genérica.
- **Tipo C:** PROCESSED-at-claim y processing_until como autoridad se sustituyen
  por TurnWork; se conservan campos/proyecciones y lectores compatibles.
- **Tipo D:** sender mantiene HTTP/transacción de lote y riesgos de aceptación
  incierta; B3 añade selección epoch/legacy y no depende de B4 para operar.
- **Tipo E:** cualquier input posterior difiere la publicación. No se interpreta
  courtesy/correction ni se añade binding revision; slots locales válidos se
  conservan para continuidad. La semántica profunda pertenece a B6.
- No se añade heartbeat/renewal: deadline 12 min y lease 15 min, reloj DB y
  comprobaciones entre pasos/final. Exceder el deadline no concede autoridad.
- Estado local se prepara con un adaptador explícito de escritores existentes,
  no con interception global del ORM. Las secuencias reservadas pueden dejar
  huecos al abortar, sin filas durables ni evidencia ficticia.
- Cierre periódico y nudge existentes adquieren Conversation y omiten trabajo
  activo; cierre invalida epoch. No se rediseña proactividad ni HumanHandoff.
- Fixtures legacy de sender ahora distinguen un mensaje nuevo con epoch real de
  legacy unverified; pruebas antiguas de respuesta obsoleta exigen que nunca se
  persista, sin relajar la comprobación de ausencia de dispatch.
- Las tres expectativas de catálogo en tests de intake se actualizan al
  contrato B2 ya vigente; se mantienen denegación personal y WRITE contenidas.

## Observabilidad

Eventos de creado, claimed, reclaimed, expirado, completed, failed, retry,
fencing reject, deferred y cambio de ownership en logger JSON existente.
Attempts, work/conversation/org/request IDs y edad del pending más antiguo del
grupo al claim. Sin token completo, transcript/PII adicional ni labels de alta
cardinalidad. Transiciones se registran al commit; rechazos sobreviven rollback.

## Deploy, rollback y riesgos residuales

[Runbook B3](runbooks/agent-whatsapp.md#b3-despliegue-controlado-y-rollback):
pausar/drenar todas las réplicas viejas y sender; migrar; desplegar lector/API,
worker y selector compatibles; observar; no mezclar workers legacy con B3.
Rollback operativo pausa autonomía, conserva DB/epochs/trabajos/correlaciones,
usa lector compatible y reconcilia antes de reanudar. B0 sigue como kill switch.
No borrar TurnWork, bajar epochs, resucitar FAILED ni reinterpretar Messages.

**B3 garantiza autoridad y publicación local durable. B4 resolverá la frontera
de dispatch externo y resultados inciertos.** HTTP ya admitido puede terminar
después de takeover. H07 sigue abierto; H08 y H19 no se declaran totalmente
resueltos. H06 y la exclusión/recuperación local de H19 mejoran; H11 conserva la
frontera causal B1. No hay promesa de entrega exactamente una vez.

Retención de evidencia causal requerirá coordinar futuras políticas de borrado
con las nuevas FKs/guards. Observabilidad de llamadas fallidas antes del commit
permanece en logs; no se introduce journal B9. Alertas opcionales post-commit
siguen best effort; B5 resolverá durabilidad de atención humana.

## Documentación actualizada

Contrato B3 y ADR combinado nuevos; enmiendas p52, p55, p56, p58, p60;
`modules/agent.md`, arquitectura, especificación funcional, runbook worker/deploy,
seguimiento B3 del plan y esta acta. Documentos históricos conservan su alcance,
con enmiendas explícitas que prevalecen en las fronteras modificadas.

**WRITE autónomo continúa cerrado. B4–B9, E1–E5 y P-A/P-B no implementados.**
No se desplegó ni se amplió beta; cierre técnico no equivale a activación.
