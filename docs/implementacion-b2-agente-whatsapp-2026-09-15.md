# Acta de implementación — Fase B2 del agente WhatsApp

Inicio: 2026-09-14. Cierre de validación: 2026-09-15.
Estado: **COMPLETED — cierre técnico limitado al alcance B2**.
Activación real: **PENDING_ACTIVATION_REQUIREMENTS**. Sin despliegue.

## Base y commits

- B0: `ecd7912`, ya cerrada técnicamente.
- Base exacta B2/B1: `2b6c9ce8f6c80c2d49df13a69346e4fd44f54600`
  (`implement-whatsapp-agent-b1-turn-context-and-channel-evidence`). Los cambios
  B1 previamente validados se fijaron en ese commit antes de modificar B2.
- Commit final técnico B2: `9ccc31a02765dd4d8b712f4b40b8efd2692ab284`
  (`Implement WhatsApp agent B2 typed outcomes and evidence-backed responses`).
- Esta acta se cierra en un commit documental posterior para registrar el hash
  técnico real sin intentar incluir un hash autorreferente en su propio contenido.

Los borrados preexistentes de `DEPLOY_VPS_PLAN.md` / `DEPLOY_VPS_STATUS.md` y el
archivo no seguido `docs/auditoria-agente-conversacional-veterinario-2026-09-10.md`
quedan fuera de B2 y de sus commits.

## Alcance implementado

Exclusivamente B2/C3 del [plan canónico](plan-implementacion-auditoria-agente-whatsapp-2026-09md),
tomando como antecedentes las actas [B0](implementacion-b0-agente-whatsapp-2026-09-13.md)
y [B1](implementacion-b1-agente-whatsapp-2026-09-14.md). No se repitió la auditoría
H01–H20 ni se exploró de forma general el módulo. Descubrimiento dirigido por
grafo y lectura de símbolos/dependencias inmediatas; snippets desfasados del
índice se contrastaron con los archivos actuales.

La frontera implementada es HTTP/parseo → validación estructural → ToolOutcome
→ respuesta compatible. El catálogo estático separa lectura pública/personal,
escritura y control. Se preservan RBAC/JWT/tenant, identidad vigente y containment.

## Archivos modificados

Runtime, bajo `backend/apps/agent/`:

- `executor.py`: transporte explícito, logs sin detail arbitrario, defensa HTTP
  contra mutaciones de READ y WRITE contenidas; diagnóstico `_outcome_v1`.
- `tools.py`: único `ToolOutcome` C3, adaptadores de lecturas/efectos, scope y
  completitud, clasificación del registro y validación de argumentos declarados.
- `endpoint_contracts.py` (nuevo): schemas mínimos de endpoints existentes.
- `capabilities.py` (nuevo): clasificación estática inmutable de las 21 tools.
- `result_renderers.py` (nuevo): rendering determinista acotado y fallbacks.
- `intake.py`: público/control humano sin funnel obligatorio.
- `planner.py`: consume los resultados tipados del mismo turno C1, excluye prosa
  libre de recibos sensibles y valida evidencia antes de declarar commits.
- `guards.py`: sin grounding por coincidencia numérica o ejecución de tool;
  afirmaciones libres de efecto/ausencia/disponibilidad no respaldadas son HARD.
- `prompts.py`: enmienda mínima de acceso/resultados, versión `reception-b2-v17`.
- `management/commands/agent_eval.py`: parser de transporte compartido.

Tests, bajo `backend/apps/agent/tests/`:

- `test_b2_results.py` (nuevo): corpus RESULT de transporte, shapes, cobertura,
  tenant, precios, disponibilidad, errores, efectos, preguntas y PII.
- `harness.py`, `test_tools.py`, `test_planner.py`, `test_w0_hardening.py`,
  `test_write_tools.py`: transportes de API real conservan errores de parseo.
- `test_write_tools.py`: recibos exigen EFFECT validado y alternativa respaldada.
- `test_commit_preconditions.py`: GET fresco después de conflicto y wording
  del estado observado, sin volver a ejecutar PATCH.
- `test_w1_experience.py`: las antiguas equivalencias número/JSON y tool/éxito
  pasan a regresiones negativas del contrato B2.
- `test_prompts.py`: versión de prompt; se mantienen las aserciones causales B1.

Documentación: este acta, `contrato-resultados-tools-b2.md`, enmiendas p52/p54/p57/p59
y ADRs de frontera posterior al recibo del 26/27 de agosto (requeridas por §5.2
del plan), `modules/agent.md`, `whatsapp-agent-architecture.md` y estado B2 del plan.

Inventario documental exacto, bajo `docs/`:

- `contrato-resultados-tools-b2.md` (nuevo).
- `implementacion-b2-agente-whatsapp-2026-09-15.md` (nuevo).
- `decisions/2026-07-19-p52-appointment-idempotency.md`.
- `decisions/2026-07-25-p54-agent-goals-and-binding-rules.md`.
- `decisions/2026-08-08-p57-garantias-de-agenda.md`.
- `decisions/2026-08-17-p59-interpretacion-al-modelo.md`.
- `decisions/2026-08-26-operation-authorization-boundary.md`.
- `decisions/2026-08-27-semantic-turn-operation-authorization.md`.
- `modules/agent.md`.
- `whatsapp-agent-architecture.md`.
- `plan-implementacion-auditoria-agente-whatsapp-2026-09md`.

Total B2: **30 archivos** (10 runtime, 9 tests/harness, 11 documentos).

## Contratos y endpoints

La especificación completa de campos, límites, clasificación de las 21
capacidades y matriz de endpoints está en [Contrato B2](contrato-resultados-tools-b2.md).

- `TransportResponse`: status real, body/data, parse_valid, error de transporte,
  timeout y aceptación incierta. Parseo inválido nunca se vuelve `{}` válido.
- `ToolOutcome`: READ/EFFECT/ERROR. READ conserva scope y complete/truncated/unknown;
  empty exige colección vacía válida y completa. Sin timestamp de observación
  del endpoint, observed_at sigue ausente. No se inventan has_more ni cursor.
- EFFECT conserva entidad/referencia/acción/estado; success/already_done solo
  con evidencia compatible. Clave de operación/idempotencia opcional cuando ya existe.
- ERROR distingue los ocho códigos canónicos; el compuesto supervisado puede
  conservar únicamente el efecto parcial de mascota. No se afirma la cita.
- `ok` es compatibilidad derivada. El constructor legacy no establece evidencia
  validada y no alimenta los renderers de precio/efectos.
- `_outcome_v1` en `ToolExecution.result_summary_redacted`: kind/validated/
  completeness/error_kind. Sin bodies, transcript, datos clínicos, labels,
  importes o referencias de entidades. Solo diagnóstico, sin backfill.

Resultados validados: mascotas por owner; citas por mascota/día y cita exacta;
vacunas administrativas por mascota; servicios; productos y presentaciones;
respuestas supervisadas de crear cita, cambiar estado, reprogramar, alta de
mascota y create-with-patient. No se ampliaron endpoints ni se cambiaron sus permisos.

Las seis READ públicas pueden ejecutarse sin onboarding. Las cuatro personales
conservan vínculo vigente. Las siete WRITE siguen contenidas. Los cuatro CONTROL
conservan su política; request_human solo acredita solicitud persistida.

## Respuestas protegidas

Precio = concepto/servicio o presentación + Decimal + moneda configurada y
compatible. UUID/id/duración/teléfono coincidentes no acreditan precio.
Disponibilidad = agenda validada completa + intervalo solicitado y horario
local de clínica; una lista parcial no prueba huecos libres.

Citas y vacunas administrativas usan campos validados. Los recortes se indican;
unknown/error no se convierten en ausencia. Los errores de READ, incluidos los
de configuración, tienen fallback determinista. La prosa libre del modelo no
puede reinterpretar esos resultados.

Los recibos de operación exigen EFFECT compatible. Un 409 de asistencia no
confirma nada. Already_done exige GET fresco compatible o replay p52 con clave
y entidad válida. Timeout de escritura no afirma éxito ni fallo definitivo.
Una solicitud humana local no prueba aviso, entrega ni atención.

## Tests y resultados

Validación aislada local: PostgreSQL 18.3 en `127.0.0.1:55439`, rol de pruebas
`b0_test`, base Django `test_b1`; Python 3.13.2 / Django 6.0.3. Proveedores LLM,
Meta y avisos externos stub/no configurados. No se utilizó producción.

El wrapper temporal únicamente fija configuración local y redirige logs; cada
comando se ejecutó mediante RTK. La ejecución conjunta final pasó **448/448**
en **580.324 s**, con **0 fallos, 0 errores y 0 skips**, exit code 0. Desglose:

| Conjunto incluido | Tests | Resultado |
| --- | ---: | --- |
| Corpus dedicado B2 `test_b2_results` | 39 | 39 aprobados |
| Compatibilidad B2 y endpoint de paginación de mascotas | 163 | 163 aprobados |
| Regresión B1/continuidad/policy/guards | 246 | 246 aprobados |

Log local: `%TEMP%/vet_b2_final_combined.log`, SHA-256
`a7b148916a658e3e4832d395622129c99ce1dd98058c03984a7eb30062340634`.
Los logs temporales no se incorporan al repositorio. Django system check:
0 incidencias. Se observó únicamente el aviso local de directorio `staticfiles`
ausente; no altera estas pruebas de backend.

B0 crítico final, ejecutado después sobre el mismo código: **17/17** en
**16.974 s**, **0 fallos, 0 errores, 0 skips**, exit code 0, con
`CriticalB0Runner`. Log `%TEMP%/vet_b2_b0_final.log`, SHA-256
`d674d2f3f2177d5f382e17947640eb42930eaf4c659adb8ecff7d965176788e4`.
Total de aceptación final: **465 tests aprobados** (448 + 17).
`git diff --check` y parseo AST de los 19 archivos Python modificados/nuevos
también finalizaron sin errores.

Comando equivalente desde `backend/`, con la base local aislada y proveedores
externos deshabilitados descritos arriba:

```powershell
rtk proxy python -X utf8 manage.py test `
  apps.agent.tests.test_b2_results `
  apps.agent.tests.test_executor `
  apps.agent.tests.test_tools `
  apps.agent.tests.test_slots `
  apps.agent.tests.test_write_tools `
  apps.agent.tests.test_commit_preconditions `
  apps.agent.tests.test_planner `
  apps.agent.tests.test_w3_quality `
  apps.patients.tests.test_pet_list_pagination `
  apps.agent.tests.test_worker `
  apps.agent.tests.test_turn_decision `
  apps.agent.tests.test_prompts `
  apps.channels.tests.test_webhook `
  apps.agent.tests.test_f2_continuity `
  apps.agent.tests.test_policy `
  apps.agent.tests.test_arbiter `
  apps.agent.tests.test_w0_hardening `
  apps.agent.tests.test_w1_experience `
  apps.agent.tests.test_f5_fase5 `
  --keepdb --noinput --verbosity 1

rtk proxy python -X utf8 manage.py test apps.agent.tests.test_b0_containment `
  --testrunner apps.agent.tests.harness.CriticalB0Runner `
  --keepdb --noinput --verbosity 1

rtk proxy python -X utf8 manage.py makemigrations --check --dry-run
```

RESULT-01–04 se cubren conjuntamente: la numeración del pedido agrupa
transporte/completitud/grounding/efectos, y la del plan incluye PII en RESULT-04.
El corpus prueba ambos conjuntos sin cambiar el significado del plan.

Evidencia intermedia registrada:

- B0 crítico: 17 tests, 0 fallos, 0 errores, 0 skips (CriticalB0Runner).
- B1/continuidad/guards: 246 tests, 0 fallos, 0 errores, 0 skips después de
  adaptar dos expectativas históricas incompatibles con C3.
- Iteración B2/compatibilidad/endpoints de 200 tests: 1 fallo de wording heredado
  («ya estaba» frente al estado acreditado por GET: «ya está»), corregido.
- Primera ejecución conjunta de 448 tests: 2 fallos en expectativas antiguas
  de `rows_read=0` como ausencia y guard SOFT, corregidas como regresiones
  negativas de B2. No hubo errores ni skips.
- Las primeras iteraciones detectaron ubicación de moneda y expectativas de
  recibos/ausencia ahora reemplazadas; los fallos no se ocultaron con skips.

El corpus dedicado B2 tiene 39 métodos: 4 transporte, 23 API/resultados,
5 contrato/guards y 7 efectos. Incluye subcasos de 403/404/409/500, timeout,
conexión, JSON/body/shape inválidos, paginación/recortes, múltiples precios,
moneda, tenant/owner, solapamiento, preguntas con tool mutadora forzada, efecto
parcial, already_done, replay y scrub de errores. Los overrides WRITE solo se
aplican a métodos supervisados existentes; las regresiones de containment no los usan.

## Migraciones y compatibilidad B0/B1

No se modificaron modelos ni se creó archivo de migración. El comando final
`makemigrations --check --dry-run`, ejecutado después de ambas suites, terminó
con **exit code 0: `No changes detected`**. Log local `%TEMP%/vet_b2_checks.log`.

`TurnContext` permanece inmutable y causal; no se modificaron su módulo,
normalizador de eventos, selectors del canal, worker o contrato de media.
Captions/replies/actions, cursor exclusivo e identidad vigente se conservan.
Ninguna clasificación del modelo, pregunta o control abre WRITE. La defensa
adicional del executor deniega incluso un commit directo contenido o un HTTP
mutador presentado bajo nombre READ.

## Despliegue y rollback

No se desplegó ni se activó el agente. La futura publicación debe mover
adaptador, tools y planner/guards como una versión compatible; no mezclar
workers que interpreten `ok` de forma distinta. Un rollback operativo mantiene
containment y restringe la salida a plantillas/lectura supervisada; no recupera
grounding por coincidencias ni interpreta summaries antiguos como efectos.
Las proyecciones diagnósticas versionadas pueden conservarse sin backfill.

## Desviaciones y contradicciones concretas

| ID | Hallazgo concreto, impacto y corrección mínima |
| --- | --- |
| B2-D01 / C | PetViewSet aplica corte 20 en owner sin paginar, además del corte 10 de la tool. Se preserva el endpoint y se propaga truncated/unknown; no se recorre paginación ni se afirma exhaustividad. |
| B2-D02 / A | Moneda vive en OrganizationSettings, no en Organization ni en ServiceSerializer. Se usa get_org_setting y su default documentado existente; no se añade campo/endpoint. DRF envía decimales como strings: wire los parsea estrictamente; la proyección tipada exige Decimal. |
| B2-D03 / C | No hay timestamp de observación ni cursor en varios endpoints. Permanecen ausentes; un envelope no probatorio queda unknown. No se fabrican filtros ni metadata temporal. |
| B2-D04 / E | Un caller directo de commit podía llegar al HTTP sin pasar por run_tool. Se añade el bloqueo mínimo del executor según effect y containment; no es autorización B7 ni execution guard transaccional B8. |
| B2-D05 / C | La disponibilidad comparaba horas de inicio, ignorando intervalos más largos. El renderer no podía afirmar un slot bajo esa condición: la proyección de ocupación ahora conserva intervalos y solo acepta cobertura completa. No cambia el modelo de agenda ni sus locks. |
| B2-D06 / B | Los tests legacy autorizaban precios por coincidencia numérica, éxito por tool_ran y ausencia por rows_read=0, con negación SOFT. Se adaptan para negar esas equivalencias; los casos positivos usan EFFECT/READ validado. p59 §6 recibe enmienda explícita. No se rediseña B1. |
| B2-D07 | Se concentra el nuevo corpus en test_b2_results.py reutilizando fixtures de test_tools y transportes existentes, para separar supervisión explícita de las pruebas de containment. No se añade framework de evaluación. |

## Riesgos residuales y fases no implementadas

- H05/H14/H20: mitigación técnica y cierre limitado a rutas C3 migradas,
  respaldado por el corpus de aceptación. No se declara garantía end-to-end para
  futuras escrituras que dependan de B7/B8/B9.
- H04: wording acotado a evidencia local; atención humana durable, cobertura,
  aviso/acuse/SLA/reintentos siguen en B5. Meta aceptado/entregado y recuperación
  durable siguen fuera de B2.
- Guard léxico es defensa adicional acotada, no verificador semántico universal.
  El containment clínico B0 permanece; no se incorporó detector clínico nuevo.
- JWT/RBAC/tenant del endpoint siguen siendo autoridad de origen cuando el
  serializer no publica org. Cambios futuros de schema/filtros/paginación deben
  adaptar C3 antes de ampliar la capability; una respuesta insuficiente falla segura.
- Los recortes pueden impedir resolver referencias antiguas; la búsqueda o
  paginación adicional corresponde a E1, no se implementó aquí.
- No se introducen TurnWork, leases, ownership epochs, sender durable,
  ConversationOperation, consentimiento persistente, ledger, scheduler,
  multi-goal ni saga. No se implementan B3–B9/E1–E5/P-A/P-B.
- Activación sigue PENDING_ACTIVATION_REQUIREMENTS por clínicas/responsables/
  canal alternativo no definidos. Esta implementación no activa tráfico real.

## Recomendación

B2 está lista para cierre técnico: contratos y corpus de aceptación aprobados,
B0/B1 compatibles y sin migraciones. Este cierre no equivale a activación,
cierre completo de los hallazgos ni permiso para WRITE autónomo. No avanzar B3.
