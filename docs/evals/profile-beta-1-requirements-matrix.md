# B9E — matriz previa de requisitos canónicos

Congelada antes del primer ensayo de `PROFILE-BETA-1` sobre `21cf91c0ae0242f83675dc9691c600bf4d63e5ab`. Autoridad: [plan canónico](../plan-implementacion-auditoria-agente-whatsapp-2026-09md), especialmente líneas 710–734; asignación [R01–R15](../mapa-interno-b9-2026-09-26.md). El estado `FAILED` identifica evidencia técnica aún ausente, no un fallo observado de un ensayo. Las filas B9E se actualizarán solo con recibos de ejecución, conservando el primer resultado.

| ID y autoridad | Dueño | Implementación concreta | Prueba y evidencia durable | Estado previo al primer run |
| --- | --- | --- | --- | --- |
| R01, §4 I01–I14, §7:710–712 | B9E | B2–B8E componen autoridad, causalidad, resultado, safety, ownership, tenant y binding | Corpus B9A–D y aceptación integral por perfil aún ausente | FAILED |
| R02, §7:715 | B9A | `ApplicationHarness`, HTTP firmado, `TurnWork`, planner, sender y wire controlado | `test_b9a_e2e`, `test_b9a_processes`; `b9a-acceptance-results.json` 45/45 | IMPLEMENTED_AND_PROVEN |
| R03, §7:716 | B9B | `llm_budget.complete` y `LLMCall` por planner/authorizer/verifier | `test_b9b_budget`, `test_b9b_processes`; recibo B9B 46/46 nuevos | IMPLEMENTED_AND_PROVEN |
| R04, §7:717 | B9C | `durable.claim_turn`, fila Organization, límite uno; dos planners/sender en Compose | `test_b9c_concurrency`, `test_b9c_processes`; recibo B9C 27/27 | IMPLEMENTED_AND_PROVEN |
| R05, §7:718 | B9B | Reserva durable bajo witness antes del proveedor; sin refund | Corpus COST B9B y recibo por ID | IMPLEMENTED_AND_PROVEN |
| R06, §7:719; §9:984–996 | B9E | Job CI crítico ya existe; falta artefacto candidato y regla explícita de eval real al promover | Inspección CI + test de gate candidato; recibo B9E pendiente | FAILED |
| R07, §7:721 | B9E | Perfil versionado `profile-beta-1-v1.json`: 3 orgs, 2 planners, 1 sender, 30+300 s, cargas y proveedor controlado | Ensayo temporal PostgreSQL con muestras por frontera pendiente | FAILED |
| R08, §7:723 | B9E | Separación de aceptación técnica y activación real | Recibo B9E y reporte de decisión pendientes | FAILED |
| R09, §7:725 | B9E | Medir p95, máximos, colas, muestras, errores y fallos separados sin omisiones | Ensayo base, LLM bloqueado, Meta lento, duplicado y safety pendientes | FAILED |
| R10, §7:727 | B9E | EVAL/COST/SCALE y corpus acotado E2E compuesto | Cinco WRITE B9A y componentes B9B/C/D existen; aceptación integral pendiente | FAILED |
| R11, §7:729; §8:913 | B9B | Migración `agent.0028_b9_operational_budget`, FK/counters y NULL legacy | Tests de constraints/migración B9B; recibo B9B | IMPLEMENTED_AND_PROVEN |
| R12, §7:729 | B9C | Constante de release y estado B3 existente, sin scheduler/billing | Tests y schema B9C; recibo B9C | IMPLEMENTED_AND_PROVEN |
| R13, §7:731 | B9D | `beta_release.py` con grants por org/capability; B8A gate WRITE; READ conserva política anterior | `test_b9d_release`, corpus y recibo B9D 75/75; aprobación READ real externa pendiente | IMPLEMENTED_AND_PROVEN |
| R14, §7:733 | B9A | Contrato/ADR, arquitectura y runbook del harness | Documentación y recibo B9A | IMPLEMENTED_AND_PROVEN |
| R15, §7:733 | B9E | Documentar perfil, CI/evals, alcance y versión compatible | Acta y recibo B9E pendientes; P-A/P-B reales externos | FAILED |
| Identidad/consentimiento/tenant, §5.5:228–243, §4 I01–I05/I12–I14 | B6/B7/B8; B9E verifica | `ContactIdentity`, revisiones, binding, B7B, guard B8A, cinco adapters | Regresiones históricas; READ_PERSONAL y composición B9E pendientes | FAILED |
| READ pública/personal, §5.2:119–131, §12:1053–1056, §14:1129–1145 | B2/B9D; B9E verifica | Manifiesto de efectos y política actual; release READ exige aprobación operacional | B9A READ E2E; matriz de gates e identidad B9E pendiente | FAILED |
| Safety/handoff, §4 I08–I09, §7:725–727 | B5/B9C; B9E verifica | Recepción safety, caso/guía, sender y epoch | B9C SCALE-02; perfil temporal y FI integral pendientes | FAILED |
| Privacidad aplicable, §7:710/733, §12:1061, P-A/P-B | Externo | Política profesional, mecanismo por categoría y restore sujeto a alcance real | Ningún fixture satisface aprobación real | OPERATIONAL_REQUIREMENT_PENDING |
| Piloto, Inbox, protocolo veterinario, simulacro y fallback, §5.5:243, §7:731, §12:1053–1063 | Externo | Evidencia humana por organización/capability, revisión y corte | No hay grants reales ni evidencia humana aprobada | OPERATIONAL_REQUIREMENT_PENDING |
| E1–E5 y fairness fuerte, §7:736–840, §12:1057–1061 | Entregas separadas condicionadas | Fuera del alcance del perfil de un asunto y la carga inicial | Derivación segura/limitación documentada | OUT_OF_SCOPE_BY_CANONICAL_PLAN |

La fila R01 se descompone en todas las invariantes aplicables del §4 del plan. `FAILED` en esta fase significa que falta la **evidencia integral B9E**, aunque el componente citado tenga regresión histórica verde. El corpus versionado de B9E asigna IDs estables y conserva la distinción entre E2E y prueba de componente.

| Invariante y línea canónica | Dueño B9E / implementación que compone | Prueba concreta o FI | Evidencia final necesaria | Estado previo |
| --- | --- | --- | --- | --- |
| I01 §4:89, WRITE exacta autorizada | B9E sobre B7B/B8A/B9D y cinco adapters | B9E-E2E-03–07, B9E-GATE-01–05 | Operation, AuthorizationEvidence, ToolExecution y efecto único por kind | FAILED |
| I02 §4:90, alcance no transferible | B9E sobre B6/B7A/B7B | B9E-E2E-13, B9E-FI-05 | Digest, scope y ausencia de efecto tras cambio | FAILED |
| I03 §4:91, propuesta emitida | B9E sobre B4/B7B | B9E-E2E-01/15 | `provider_accepted_at`, causalidad y no autorización de pending | FAILED |
| I04 §4:92, pregunta no muta | B9E sobre B2/B8D | B9E-E2E-02/06 y regresión ATT | Estado de asistencia sin PATCH por consulta | FAILED |
| I05 §4:93, contenido no amplía permisos | B9E sobre catálogo/B0/RBAC | B9E-GATE-01–05, B9E-E2E-09 | No efecto ni provider call prohibida | FAILED |
| I06 §4:94, efecto solo con evidencia | B9E sobre B2/B8A/B4 | B9E-E2E-01/03–07/11 | Outcome tipado, receipt y estado outbound distinto | FAILED |
| I07 §4:95, parcial/error no es ausencia | B9E sobre contratos READ/B2 | B9A EVAL y regresión RESULT | Separación de `completeness`, error y vacío | FAILED |
| I08 §4:96, safety prioritario | B9E sobre B5/B9C | B9E-E2E-14, B9E-SCALE-02, B9E-LOAD-05 | Guidance detectada en recepción, dispatch y no LLM obligatorio | FAILED |
| I09 §4:97, takeover cerca autoridad vieja | B9E sobre B3/B4/B5/B8A | B9E-FI-04/07, B9E-E2E-10 | Sin stale publication/effect; HTTP admitido clasificado | FAILED |
| I10 §4:98, crash no completa falsamente | B9E sobre TurnWork/B9B/B9C | B9E-FI-01/02/10 | Lease, budget y recovery durable | FAILED |
| I11 §4:99, externo incierto | B9E sobre B4 sender | B9E-FI-03, B9E-E2E-11, B9E-LOAD-03 | `UNCERTAIN`, no retry ciego | FAILED |
| I12 §4:100, binding mascota | B9E sobre B6 | B9E-E2E-13 y regresión B6 | Revisión/binding y ausencia de efecto cruzado | FAILED |
| I13 §4:101, aislamiento tenant | B9E sobre canal/API/B8 | B9E-E2E-09, B9A-E2E-20, B9E-SCALE-01 | Dos orgs independientes, cero efecto cruzado | FAILED |
| I14 §4:102, corrección invalida derivados | B9E sobre B6/B7A | B9E-E2E-13, B9E-FI-05 | Propuesta vieja inválida, cero efecto | FAILED |

El §7:721–725 se evalúa como cinco variantes temporales independientes: base, LLM bloqueado, Meta lento, webhook duplicado y saturación con safety. `p95` se calcula sobre **todos** los mensajes elegibles del intervalo de medición, con faltantes como fallo; se reportan muestras y máximos. La pérdida de una muestra, un proceso o una variante no se convierte en verde. La prueba temporal no sustituye los guiones de WRITE ni los FI acotados; estos deben tener recibos de ID exacto en el candidato.

`READ_PUBLIC` no requiere identidad ni consentimiento y puede atenderse con WRITE cerrado; `READ_PERSONAL` exige identidad vigente, owner/pet y tenant. El release B9D declara qué READ se podría promover, pero no añade un gate de ejecución por READ. Es la decisión explícita de [su contrato](../contrato-beta-release-b9d.md), pendiente de verificación integral. Ninguna fixture convierte la disponibilidad anterior de READ en aprobación operativa.

El perfil canónico modela una llamada LLM de 0,5 s y una READ de 0,1 s por turno básico. El guion público B9A actual usa una llamada de selección de tool y otra para terminar la respuesta. La aceptación deberá registrar llamadas realmente observadas; una desviación no se ocultará atribuyendo una READ inexistente a una respuesta directa.

## Estado final del candidato (cierre 2026-09-30)

Se conserva la matriz anterior como estado previo. R01–R15 se congelaron en
`9147928` antes de carga; la descomposición detallada I01–I14 se añadió después
del primer run. No se presenta esa ampliación como freeze granular previo.
Los 46 IDs dirigidos terminaron `ok`: 43 con journal antes de una interrupción
PostgreSQL y tres recuperados por ID exacto. Recibo combinado:
[`b9e-corpus-final.json`](b9e-corpus-final.json). No se ejecutó la regresión
histórica completa condicionada a un perfil verde. `FAILED` final distingue
fallo temporal o falta de evidencia actual, sin borrar procedencia histórica.

| Requisito | Evidencia final y límite | Categoría final |
| --- | --- | --- |
| R01 | Corpus dirigido verde; gate integral de carga falla, I04/I07 no tienen rerun exacto actual | FAILED |
| R02 | E2E READ/cinco WRITE y procesos B9A en los 46 IDs; queued/accepted/delivered separados | IMPLEMENTED_AND_PROVEN |
| R03 | COST-01 y usage desconocido/timeout admitido; LLMCall durable en cinco cargas | IMPLEMENTED_AND_PROVEN |
| R04 | SCALE N=1, procesos independientes y sender; máximo observado=1, sin fairness fuerte | IMPLEMENTED_AND_PROVEN |
| R05 | Boundary/exhaustion/no refund y recovery FI-01/02 | IMPLEMENTED_AND_PROVEN |
| R06 técnico | CI existente mantiene corpus crítico/full suite; corpus candidato determinista con ID/hash. CI remoto completo no ejecutado en B9E | IMPLEMENTED_AND_PROVEN |
| R06 promoción real | Eval real al cambiar modelo/prompt/semántica o promover autonomía, responsable y acción | OPERATIONAL_REQUIREMENT_PENDING |
| R07 | Perfil versionado y medido; p95 sano base/bloqueado >10 s, una llamada modelada frente a dos reales | FAILED |
| R08 | Decisión técnica FAIL y activación PENDING_ACTIVATION_REQUIREMENTS separadas | IMPLEMENTED_AND_PROVEN |
| R09 | Cinco cargas con denominadores, máximos, p95, faltantes, cola, errores y hashes | IMPLEMENTED_AND_PROVEN |
| R10 | Guiones dirigidos EVAL/COST/SCALE y diez FI verdes; no se infiere full regression del candidato | IMPLEMENTED_AND_PROVEN |
| R11 | Contadores/LLMCall probados en COST; migraciones sin drift y checks PostgreSQL | IMPLEMENTED_AND_PROVEN |
| R12 | Capacidad derivada y N−1/N/N+1; sin scheduler ni billing nuevos | IMPLEMENTED_AND_PROVEN |
| R13 técnico | Cinco gates de organización no aprobada y retirada READY stale en IDs exactos; READ sin gate B9D adicional según contrato | IMPLEMENTED_AND_PROVEN |
| R13 operacional | Lista real de release/readiness y aprobación por clínica/capability ausentes | OPERATIONAL_REQUIREMENT_PENDING |
| R14 | Harness/contratos B9A existentes, método de aceptación y fuentes en recibos | IMPLEMENTED_AND_PROVEN |
| R15 técnico | Reporte, arquitectura, módulo, runbooks, alcance y versión mínima compatible baseline B9D | IMPLEMENTED_AND_PROVEN |
| R15 operacional | P-A revisada y mecanismo P-B por categorías/plazos comprometidos | OPERATIONAL_REQUIREMENT_PENDING |
| I01/I02/I03/I05/I06 | Cinco WRITE reales, corrección, causalidad, tenant y gates en corpus dirigido | IMPLEMENTED_AND_PROVEN |
| I04 | Históricos ATT demuestran pregunta sin mutación; ID exacto de esa negativa no rerun en candidato fallido | FAILED |
| I07 | Históricos RESULT demuestran error/parcial/vacío; no rerun exacto actual de todas esas negativas | FAILED |
| I08/I09/I10/I11 | Safety temporal, takeover/worker stale, crash/recovery y sender UNCERTAIN FI | IMPLEMENTED_AND_PROVEN |
| I12/I13/I14 | READ owner/pet/tenant y corrección que retira propuesta antes del efecto | IMPLEMENTED_AND_PROVEN |
| READ pública/personal técnica | Inventario de diez tools; seis seleccionadas E2E y negativos de verificación/expiry/reset | IMPLEMENTED_AND_PROVEN |
| Safety/handoff técnica | Guidance en carga y FI takeover/LLM tardío, sin autoridad nueva | IMPLEMENTED_AND_PROVEN |
| Piloto/Inbox/seguridad clínica/privacidad/simulacro/fallback | Cero requisitos SATISFIED_REAL; lista accionable en readiness | OPERATIONAL_REQUIREMENT_PENDING |
| E1–E5 y fairness fuerte | Entregas separadas; la medición puede justificar E4, B9E no lo implementa | OUT_OF_SCOPE_BY_CANONICAL_PLAN |

La matriz no acredita seguridad universal ni sustituye el gate fallido por
subconjuntos verdes. No hay requisito clasificado por mera suposición de PASS.
