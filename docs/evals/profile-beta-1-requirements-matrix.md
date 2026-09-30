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

`READ_PUBLIC` no requiere identidad ni consentimiento y puede atenderse con WRITE cerrado; `READ_PERSONAL` exige identidad vigente, owner/pet y tenant. El release B9D declara qué READ se podría promover, pero no añade un gate de ejecución por READ. Es la decisión explícita de [su contrato](../contrato-beta-release-b9d.md), pendiente de verificación integral. Ninguna fixture convierte la disponibilidad anterior de READ en aprobación operativa.

El perfil canónico modela una llamada LLM de 0,5 s y una READ de 0,1 s por turno básico. El guion público B9A actual usa una llamada de selección de tool y otra para terminar la respuesta. La aceptación deberá registrar llamadas realmente observadas; una desviación no se ocultará atribuyendo una READ inexistente a una respuesta directa.
