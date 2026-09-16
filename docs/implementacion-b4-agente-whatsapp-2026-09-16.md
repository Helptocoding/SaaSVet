# Acta de implementación — B4 sender durable

Fecha: 2026-09-16. Estado: **COMPLETED — cierre técnico B4**.
Activación: **PENDING_ACTIVATION_REQUIREMENTS**. Sin despliegue.

## Base, alcance y commits

Base exacta `5ae6077ab62432864c4563921d3305b76dad5529`, cierre B3 confirmado.
Solo B4/C5 del [plan canónico](plan-implementacion-auditoria-agente-whatsapp-2026-09md).
No nueva auditoría H01–H20, exploración global ni rediseño B0–B3.
Los hashes de implementación/cierre se registran después de concluir validación.
Los borrados previos de DEPLOY_VPS_PLAN.md / DEPLOY_VPS_STATUS.md y la auditoría
no seguida de 2026-09-10 se excluyen del trabajo y de los commits B4.

Contrato normativo: [sender B4](contrato-sender-durable-b4.md).
Decisión: [ADR B4](decisions/2026-09-16-b4-durable-sender-uncertainty.md),
enmienda explícita del ADR conjunto B3.

## Runtime y migración

| Archivos | Cambio |
| --- | --- |
| agent/sender.py (nuevo), worker.py | Claim individual, admisión, CAS y recuperación; import público compatible |
| agent/durable.py | Descartar claims sin admisión al invalidar ownership; conservar los admitidos |
| channels/models.py | Campos de envío/fechas/supersedes y constraints/índices |
| channels/providers.py | SendResult aceptado/rechazado conocido/incierto |
| channels/delivery.py y status.py (nuevos) | Función central monotónica, scope y locks de webhook |
| channels/views.py, agent/services.py | Parseo defensivo y delegación de status; HMAC/dedup conservados |
| channels/selectors.py, agent/views.py y serializers.py | Visibilidad operacional separada de emisión, timestamps y acceptance_known |
| agent/management/commands/run_agent_worker.py | Modos planner/sender/both, límites y polling acotado |
| agent/management/commands/inspect_agent_outbound.py (nuevo) | Snapshot de counts/edades, solo lectura |
| config/settings.py, docker-compose.prod.yml | Deadman separado y procesos planner/sender con misma imagen |
| frontend/src/pages/inbox/DeliveryTicks.jsx e index.jsx | Labels honestos y legacy desconocido; sin rediseño |

Rutas backend anteriores relativas a `backend/apps/`, salvo `backend/config/settings.py`.
Migración única **channels.0013_b4_durable_sender**. Añade nueve campos nullable:
send_token, send_started_at, send_lease_until, send_admitted_at,
provider_accepted_at, delivered_at, read_at, uncertain_at, supersedes_message.
Reutiliza failure_reason, attempts, next_attempt_at, external_message_id y status.
Tres checks (claim SENDING, evidencia UNCERTAIN, admisión) y tres índices
(ready/retry, expiry, org/cuenta/wamid). No nuevas tablas ni backfills.

## Contrato implementado

Lifecycle normal `PENDING → SENDING → SENT → DELIVERED → READ`, además FAILED,
UNCERTAIN y DISCARDED. Claim UUID propio por intento, distinto de TurnWork;
lease de 120 s con reloj DB. Locks Conversation→Message y commit individual.
Otra transacción verifica epoch/token/lease/scope/ventana y admite una sola vez.
HTTP fuera de DB, timeout explícito 15 s, sin retry de requests/redirecciones.

SENT requiere respuesta 2xx JSON válida con un wamid compatible; ID y fecha de
aceptación se guardan bajo CAS. No se atribuye delivery ni éxito de negocio.
Timeout/conexión/5xx/2xx sin ID/JSON inválido/shape desconocido→UNCERTAIN.
Error local tras aceptación conserva SENDING y recovery lo clasifica incierto.
Todo SENDING vencido→UNCERTAIN, aun sin admisión, jamás replay automático.

Retry únicamente para rechazo temporal explícito `meta_130429` en 4xx:
cinco claims máximo, 30/60/120/240 s, fórmula limitada a 1 h. Requiere token,
lease y epoch vigentes; tras takeover/expiry/recovery no hay retry. Las demás
fallas conocidas terminan FAILED. Flag retryable legacy no acredita seguridad.

Takeover antes de claim descarta pending obsoleto; tras claim sin admisión
descarta y no llama HTTP; después de admisión conserva el resultado externo
(SENT/UNCERTAIN/FAILED) aunque el epoch cambió. Token válido sigue siendo
obligatorio. Registrar esa realidad no concede autoridad conversacional nueva.

Webhook HMAC y org/cuenta/wamid exactos, una única fila, locks y rank monotónico.
Duplicados no cambian fechas; timestamps son primera observación local de cada
evento, sin fabricar etapas. UNCERTAIN puede reconciliar directamente a
DELIVERED/READ conservando uncertain_at. Sin ID persistido no hay correlación
heurística. Fallo downstream no borra aceptación ni lectura.

Reemisión manual crea otro Message humano con supersedes, actor, motivo y clave
idempotente; el original conserva su evidencia. Respeta permisos send/claim, tenant y ventana.
Inbox muestra incertidumbre y `inspect_agent_outbound`/logs registran counts,
edades, latencias, conflictos, expiry, fencing/discard y unmatched. Sin labels
de alta cardinalidad ni payload Meta/PII en logs.

## Failure injection

| ID | Evidencia implementada |
| --- | --- |
| SEND-FI-01 | Kill real después de claim COMMIT; send_admitted_at NULL; expiry incierto, restart sin HTTP |
| SEND-FI-02 | Takeover tras claim, en prueba local y proceso detenido en barrera; cero HTTP |
| SEND-FI-03 | Kill real tras respuesta accepted/pre-finalize; expiry incierto, sin ID inventado ni HTTP de restart |
| SEND-FI-04 | Timeout mediante transporte Meta real con HTTP controlado→UNCERTAIN |
| SEND-FI-05 | 2xx sin wamid válido→UNCERTAIN, incluido sender real |
| SEND-FI-06 | JSON inválido 2xx→UNCERTAIN, incluido sender real |
| SEND-FI-07 | Rechazo explícito 4xx→FAILED; rate limit con retry acotado |
| SEND-FI-08 | Takeover durante HTTP aceptado; otra transacción progresa antes de liberar la barrera, resultado SENT |
| SEND-FI-09 | Takeover durante HTTP incierto→UNCERTAIN |
| SEND-FI-10 | Webhook DELIVERED posterior con ID exacto reconcilia incertidumbre y conserva historia |
| SEND-FI-11 | READ antes de DELIVERED/duplicados tardíos no degrada |
| SEND-FI-12 | Dos intérpretes/conexiones compiten; un claim y un HTTP |

Además: error PostgreSQL real `SELECT 1 / 0` dentro de finalize tras accepted,
token falso, scope falso, conflicto de ID, lote con segundo finalize fallido,
ventana vencida, reemisión y preservación de datos legacy. No llamadas Meta/LLM
reales: proveedor controlado, transacciones/locks/CAS/crashes sí reales.

## Validación

Aceptación local final: **824 tests backend únicos + 44 frontend = 868 únicos**.
**0 fallos, 0 errores, 0 skips, 0 xfail y 0 éxitos inesperados** en las pasadas
completas de aceptación. No se suman subcasos/FI como tests adicionales.

| Pasada completa | Aprobados | Duración | Solapamiento con conjunta |
| --- | ---: | ---: | ---: |
| Conjunta B1–B4 + rutas afectadas | 807/807 | 925.612 s | 0 |
| B4 dedicada (antes del último caso de retry) | 67/67 | 452.843 s | 67 |
| Sender/webhook/Inbox/takeover dirigidos | 153/153 | 140.843 s | 153 |
| B3 crítico y procesos | 42/42 | 267.361 s | 42 |
| B0 crítico sin bypass | 17/17 | 16.327 s | 0 |
| Frontend Inbox/API/ticks, 3 archivos | 44/44 | 53.807 s | 0 |

La pasada conjunta ejecuta **68/68 B4 actuales**: sender/status 42, procesos 5,
comando 4, transporte 8, webhook adversarial 8 y migración 1. La dedicada anterior
tenía 67; el caso adicional impide retry por un flag sin código aprobado y sí
está aprobado en la conjunta. Los 67 + 153 + 42 de pasadas dirigidas son **262
ejecuciones repetidas**, todas incluidas en los 807 de la conjunta; no aumentan
la unión. No hay duplicados dentro de cada pasada. Los 17 B0 son disjuntos.

Regresión heredada: los 708 casos de la conjunta B3 siguen incluidos, además de
17 críticos B0 (baseline acumulado 725 conservado). Desglose de los 807 actuales:

| Grupo de módulos | Casos |
| --- | ---: |
| B1/continuidad: worker, turn_decision, prompts, f2_continuity, policy, arbiter, w0_hardening, w1_experience, f5_fase5; channels.webhook | 246 |
| B2 directo: b2_results | 39 |
| B2 compatibilidad: executor, tools, slots, write_tools, commit_preconditions, planner, w3_quality; patients.pet_list_pagination | 163 |
| B3: b3_durable, b3_processes | 42 |
| Rutas ya incluidas: inbox_api, release_service, identity_evidence, identity_verification, services, w2_goals, identity, intake_capabilities | 218 |
| Inbox threads (incluye dos nuevos casos B4) | 24 |
| channels.providers | 7 |
| B4 actual | 68 |

Cada nombre abreviado equivale a `apps.agent.tests.test_<nombre>`, excepto los
prefijos channels/patients indicados. La conjunta usa todos esos módulos con
`--testrunner apps.agent.tests.harness.CriticalB4Runner --keepdb --noinput
--verbosity 2 --parallel 4`. Los runners B0/B3/B4 rechazan skips/xfail y ejecución
parcial; CI conserva B0/B3 y añade B4. CI remoto no se presenta como ejecutado.

Sender heredado: 6 casos de envío dentro de worker 12/12. Webhook heredado 27/27,
8 adversariales firmados B4 y 11 de monotonicidad/status B4. Release/takeover
25/25 e Inbox API 46/46, además de las fronteras B3/B4. **Cinco pruebas B4 con
procesos PostgreSQL independientes**, más tres B3. SEND-01/02/03/04 y OWN-03,
incluidos los doce SEND-FI, están cubiertos y ejecutados.

Frontend: `src/api/inbox.test.js`, `src/pages/inbox/DeliveryTicks.test.jsx` y
`src/pages/inbox/index.test.jsx`; `rtk npm run build` también pasó (12.49 s).
`makemigrations --check --dry-run`: **No changes detected**.
`showmigrations channels`: **[X] 0013_b4_durable_sender**. Migración aplicada en
base aislada y test; prueba histórica 0012→0013 conserva estados/fechas NULL.
Sintaxis Python/YAML y `git diff --check` sin errores.

Comando del corpus B4 desde backend, con DATABASE_URL de pruebas explícita:

```text
rtk proxy python manage.py test apps.agent.tests.test_b4_sender apps.agent.tests.test_b4_processes apps.agent.tests.test_b4_command apps.channels.tests.test_b4_transport apps.channels.tests.test_b4_webhook apps.channels.tests.test_b4_migration --testrunner apps.agent.tests.harness.CriticalB4Runner --keepdb --noinput --verbosity 2 --parallel 4
```

Para B0: `apps.agent.tests.test_b0_containment` con `CriticalB0Runner`; para B3:
`apps.agent.tests.test_b3_durable apps.agent.tests.test_b3_processes` con
`CriticalB3Runner`. No usar el decorador de componentes WRITE legacy como prueba
de apertura de autonomía: el corpus B0 corre sin ese bypass de test.

Logs locales en `%TEMP%` (SHA-256 de los artefactos completos):

| Artefacto | SHA-256 |
| --- | --- |
| vet_b4_combined_final.log | `02e990d784007b3c24079647392586e163cadfdab357021523d0f7eaf634cae7` |
| vet_b4_dedicated_final.log | `07b7153542da5a4c9ec97e0dc7a9c57490ae1e4aa4541c4171ee8bc3787f579f` |
| vet_b4_affected_final.log | `70ff4df72d86972682237a0d5c5a99f15fc8f5c1520b12ef33dd25324d2f23a1` |
| vet_b3_b4_b3_final.log | `fec2962fa65d724f194dcc70e55edc7f93bda84c23957d43e73eb79cd5b71cf3` |
| vet_b3_b4_b0_final.log | `caddb4115c67f546b9ec96d3b8e22f2777007f06d027b869b7af98b333dbb7fe` |
| vet_b4_frontend.json | `31bb451d3b4f416aeb38937e0e2df1cc5b07b0e691ffd6655d83a68ba1937ed6` |
| vet_b4_check_final.log | `93e6e2d5be3c054add80c0f19101608803f7ca8a7df1fa41f76bbb9a1f570f4a` |
| vet_b4_show_final.log | `7e3dd6289e181a6b04f6e99bf32e2704552dc64190070ed3eac9fa0080bb12a2` |
| vet_b4_migrate_fresh.log | `b2176b7b348f2f9131b076036463bad497366d474ae85139c60f101c585ed1cc` |

Durante desarrollo hubo clasificación inicial roja (8 tests/23 errores de
subcasos contra el transporte anterior), cinco procesos rojos sin migración,
clones B3 de esquema viejo y una pasada interrumpida durante adaptación de
expectativas. También se interrumpió una conjunta sin resumen al detenerse el
entorno; el primer relanzamiento encontró PostgreSQL local no disponible.
Ninguna de esas pasadas cuenta como verde. La recuperación WAL del entorno
anterior se prolongó; se detuvo limpiamente esa instancia y se creó otra
temporal vacía para ejecutar la conjunta completa, sin modificar runtime.
No se ocultó ningún fallo con skips/xfail.

Entorno: Python 3.13.2, Django 6.0.5, PostgreSQL 18.3. Dedicada/dirigida y B0/B3
en instancia aislada 127.0.0.1:55439; conjunta final y migración desde cero en
instancia temporal nueva 127.0.0.1:55440 (b4/test_b4 y clones). B0/B3 críticos
usan test_b3 separado. Datos sintéticos, sin datos productivos, sin llamadas
Meta/LLM reales y sin despliegue.

## Legacy, desviaciones y riesgos residuales

- PENDING sin origin_epoch: política B3 legacy_unverified/DISCARDED sin replay.
  Pending contradictorio con evidencia externa queda UNCERTAIN para inspección.
- SENT con ID conserva evidencia histórica y fechas NULL; SENT sin ID es
  desconocido. DELIVERED/READ conservados; ninguna fecha sintética al migrar.
- `send_admitted_at` adicional a C5 distingue dos fronteras sin otra autoridad.
  Admisión COMMIT es inicio lógico, con intervalo inevitable hasta el socket.
  No se afirma cancelación remota ni entrega exactamente una vez.
- Rechazos se clasifican con lista cerrada; 5xx/errores desconocidos conservan
  incertidumbre aunque algunos puedan no haber causado efecto. Se prioriza no
  duplicar mediante un retry injustificado.
- Un webhook que llega antes de persistir wamid puede quedar unmatched; no se
  agrega buffer/tabla de receipts. La pérdida de ID tras crash puede ser
  irrecuperable automáticamente; revisión o reemisión explícita puede duplicar.
- Requests timeout no es límite total contra un servidor que transmite datos
  continuamente. Un sender bloqueado no habilita otro HTTP al expirar su lease.
- Métricas y procesos separados no son gates/carga/fair scheduling B9.

## Deploy y rollback

[Runbook B4](runbooks/agent-whatsapp.md#b4-cutover-controlado-y-rollback): mantener
containment, pausar sender viejo, drenar/inspeccionar, migrar, desplegar lector
compatible, clasificar legacy/dudosos y arrancar B4. No rolling mixto.
Rollback operativo pausa sender, conserva datos y permite lectura/reconciliación;
no downgrade a sender legacy, no borrar tokens/IDs/fechas ni resetear UNCERTAIN.

Documentos actualizados: contrato/ADR B4; enmiendas contrato/ADR B3, p58, p60;
arquitectura, especificación funcional, módulo agent, runbook, plan y esta acta.

## Alcance de cierre

H07: cerrado técnicamente para sender durable/HTTP/DB e incertidumbre,
con las limitaciones distribuidas documentadas. H08: publicación local
B3 y admisión/dispatch B4; permanecen ownership/handoff B5 y efectos B8 futuros.
H16/H19 solo reciben evidencia incremental y separación operacional.

**WRITE autónomo cerrado. B5–B9, E1–E5 y P-A/P-B no implementados.**
El cierre técnico no autoriza activación ni despliegue.

Recomendación: aceptar el cierre técnico exclusivo de B4. Mantener containment
y activación PENDING_ACTIVATION_REQUIREMENTS; detenerse aquí, sin iniciar B5.
