# B9 — Mapa de implementación interno

Baseline: `55d122bcfb26f41b7f23ce0bb523b464017f3a4c`. Fecha: 2026-09-26.
Autoridad: §7/B9 del [plan canónico](plan-implementacion-auditoria-agente-whatsapp-2026-09md).
B9A–B9E son hitos internos, **no fases canónicas independientes**. Se interpreta
la frase aislada del encargo que dice lo contrario conforme a su instrucción
principal explícita. No se cambia alcance, dependencias ni criterios del plan.

La [discrepancia anterior](discrepancia-encargo-b9-2026-09-26.md) se conserva como
historia. Este encargo resuelve la elección de alcance: prevalece B9 canónica.

## Asignación única

Cada fila tiene un solo dueño de entrega/aceptación. Los consumidores reutilizan
su evidencia sin contarla como otra entrega. La extracción literal completa de
B9 se conserva al final para contrastar cobertura, incluidas sus restricciones.

| ID | Requisito canónico (ubicación dentro de B9) | Dueño | Dependencia interna |
| --- | --- | --- | --- |
| R01 | Objetivo, invariantes I01–I14, dependencias B2–B8/P aplicable y acta reproducible del alcance | B9E | A/B/C/D |
| R02 | Cambio 1 completo: guiones multi-turn por worker/HTTP/sender, Meta controlado, cliente responde solo a emitidos, etapas separadas y alias sent | B9A | Baseline B0–B8E |
| R03 | Cambio 2 completo: todas las llamadas/roles/retries, límites LLM por turno, usage desconocido, correlación y presupuesto tras recuperación | B9B | A como consumidor de prueba |
| R04 | Cambio 3 completo: procesos acotados, exclusión conversación/org, claim con fila existente, sender separado, timeouts herramientas/proveedor, backoff y safety rápido | B9C | A/B |
| R05 | Cambio 4 completo: reserva durable antes de llamada bajo witness, rollback no repone cupo, sin gasto diario distribuido; reporte de insuficiencia para E4 | B9B | A; E medirá insuficiencia |
| R06 | Cambio 5 completo: CI crítico requerido, eval real al promover modelo/prompt/semántica/autonomía, nightly no sustituye candidato, reportes con destinatario/acción | B9E | A/B/C/D |
| R07 | PROFILE-BETA-1 completo: topología, fixtures, carga, tiempos, calentamiento/medición y ensayos separados | B9E | A/B/C |
| R08 | Cierre técnico separado del gate operativo; resultado rechazado y eventual entrada a E4, repetición del gate | B9E | R07/R09 |
| R09 | Medición/gate completo: p95, colas, muestras, máximos, errores, durabilidad con Meta lento, cero violaciones, no skipped verde, repetición con carga real | B9E | A/B/C/D |
| R10 | Aceptación EVAL-01/02, COST-01, SCALE-01/02 y conjunto E2E acotado; sin producto cartesiano | B9E | Pruebas de componentes A/B/C/D |
| R11 | Datos: FK LLMCall→TurnWork, contadores de presupuesto, default nuevo 0 y legacy desconocido, fallback conservador de usage | B9B | R03/R05 |
| R12 | Datos: reutilizar configuración/constantes para límites fijos; sin nuevos estados, billing ni presupuesto global distribuido | B9C | R04; B respeta la misma restricción |
| R13 | Deploy/rollback: lista explícita READ pública/personal/WRITE; intersección release/política/identidad/contrato; cohorte con gates/cobertura; retirar capacidad preservando garantías | B9D | A/B/C y evidencia E antes de activación |
| R14 | Documentación: arquitectura y runbook de las fronteras del harness | B9A | R02 |
| R15 | Documentación: CI/evals, acta de perfil/capacidades/versión mínima compatible, evidencia de privacidad aplicable y límites/riesgos de B9 | B9E | A/B/C/D y aprobaciones externas |

R03/R05 implementan contabilidad y reserva; R11 entrega su migración, sin duplicar
la funcionalidad. R12 no autoriza crear un scheduler. R13 asigna a D el mecanismo
mínimo compatible con el plan; **no incorpora automáticamente el ledger/revision/
comandos del encargo anterior**. R01/R15 no implementan P-A/P-B: su evidencia es
dependencia de activación según categoría/plazo. H16/H19 no se cierran en A.

## Dependencias y límites

Seguimiento 2026-09-27: la continuación corregida autoriza R03/R05/R11 de B9B,
respetando R12. Presupuesto por TurnWork y contabilidad: **COMPLETED técnico**
del componente interno. Regresión: 2.236/2.236 históricos, 34/34 nuevos y
12/12 adicionales de provider (2.282 únicos); corpus crítico en cero y checks
verdes. B9 canónica permanece IN_PROGRESS; B9C/B9D/B9E pendientes. Ver [contrato](contrato-presupuesto-turnwork-b9b.md)
y [acta](implementacion-b9b-agente-whatsapp-2026-09-27.md). Los dos informes de
discrepancia permanecen como historia. B9 canónica sigue IN_PROGRESS; B9C/B9D/B9E
no se adelantan. El párrafo «Solo A» siguiente describe la entrega B9A original.

Orden de trabajo: A → B → C → D → E. A aporta las interfaces reutilizadas por los
demás; E es dueño de aceptación integral. D puede quedar cerrado mientras falta
el reporte E; esto no exige una dependencia circular de implementación.

Solo A está autorizado en esta entrega. Sus pruebas distinguen encolado,
aceptación y señales simuladas de delivery y prueban el guion causal; no son una
declaración de EVAL-01/02 aprobado para promoción. No se ejecuta PROFILE-BETA-1,
no se modifica presupuesto/cupos y no se implementa readiness/activación.

El baseline corta el flujo conversacional B7B en AUTHORIZED con respuesta
«pendiente de ejecución»; las llamadas al guard B8A están en pruebas de adapters.
Para un guion WRITE completo hace falta conectar ese resultado al guard existente
y su recibo durable, conservando B0/flags cerrados. Esa integración mínima se
considera parte de R02, no una nueva operación ni un gate de activación. La suite
debe recorrerla desde HTTP y worker, sin invocar guard/adapters desde el harness.

## Extracción literal de §7/B9

El texto siguiente se copia sin enmendar del baseline. La asignación superior
incluye entregables, aceptación, perfil, métricas, dependencias y restricciones.

### Fase B9 — Evaluación y límites mínimos para activar beta

**Objetivo.** Autorizar un alcance concreto con evidencia operativa; no construir al final el harness que necesitaban las fases anteriores. **Hallazgos:** H16/H19 y cierre de gates transversales. **Invariantes:** I01–I14 aplicables al alcance, sin prometer perfección clínica/semántica. **Dependencias:** B2/B3/B4/B5; para WRITE B6/B7B y cada B8 seleccionado; P-A y mecanismo P-B de las categorías/plazos comprometidos.

**Actual → objetivo.** Los helpers/evals actuales no representan todas las etapas; B0/B3/B4/B8 ya incorporaron sus integraciones al harness. Esta fase compone guiones, comprueba contabilidad/límites y produce acta reproducible de activación por capacidad.

**Cambios técnicos.**
1. tests/harness.py y management/commands/agent_eval.py/agent_eval_conversations.py: guiones multi-turn por worker/HTTP/sender reales con Meta controlado; cliente responde solo a Message emitido. Separar response_generated, outbound_queued, provider_accepted y delivered con señal. “Sent” se define como alias de aceptación cuando esa sea la señal disponible, no nueva evidencia.
2. metrics.py, llm.py y operation_authorization.py::_classify/_verify/_persist_llm_call: registrar todas las llamadas/roles/retries y límites de timeout/calls/tokens máximos por turno. Coste/usage desconocido no es cero. Reusar LLMCall; correlación a TurnWork nullable se introduce con este consumidor. Un intento recuperado cuenta llamadas anteriores del mismo trabajo al aplicar presupuesto; no otorgar cupo infinito por restart.
3. worker.py/run_agent_worker.py y docker-compose.prod.yml: planners con concurrencia fija acotada por procesos, un trabajo activo por conversación y como máximo uno por org para ensayo beta; sender separado. Claim por org protegido en transacción corta usando fila organizativa/AgentSettings existente e índice de TurnWork, sin nueva tabla de scheduler. No autoscaling que multiplique el límite sin cambiar el contrato. Timeouts de herramientas/proveedor; backoff conocido y safety rápido sin esperar LLM.
4. Presupuesto por turno con reserva de llamadas/cupo máximo antes de llamar, actualizada bajo witness; rollback de intento no repone llamadas ya admitidas. No reservas distribuidas de gasto diario ni cuotas globales de urgencias ahora. Si los límites fijos no pasan el perfil, reducir alcance o ejecutar el mecanismo concreto E4 justificado por medición.
5. CI mantiene suites deterministas críticas requeridas; eval real al cambiar modelo/prompt/semántica o promover autonomía. Nightly ayuda a detectar deriva, no sustituye el artefacto candidato. Agregar solo reportes con responsable/acción de §10.

**Perfil reproducible inicial PROFILE-BETA-1.** DB PostgreSQL aislada y fixtures committeados; dos planners y un sender con polling máximo 1 s; tres orgs, 300 s de medición tras 30 s de calentamiento. Dos orgs sanas: un inbound cada 10 s; org ruidosa: uno por segundo distribuido en conversaciones. Proveedor simulado: una llamada LLM de 0,5 s, READ de 0,1 s y aceptación Meta de 0,2 s por turno básico; respuestas/uso deterministas. Ensayos separados: bloquear una llamada LLM de org ruidosa hasta timeout de 10 s; Meta a 2 s por envío; duplicate webhook; saturación con guidance safety ya detectable en recepción. No extrapolar este perfil a todo diálogo real.

**Cierre técnico y gate operativo separados.** B9 entrega harness, contabilidad/límites y reporte reproducible bajo contención. Si el perfil falla, la activación queda rechazada; ese reporte puede habilitar el trabajo E4 sin fingir aprobación ni reimplementar B9. Repetir el ensayo tras E4 es verificación del gate, no dependencia circular de código.

**Medición/gate de activación.** En perfil base y bloqueo de una llamada LLM: p95 desde persistencia inbound sano a claim ≤10 s; p95 desde persistencia de guidance detectable a admisión de dispatch ≤5 s; p95 desde outbox committed a dispatch ≤5 s con proveedor base. En Meta lento se exige estado durable, concurrencia acotada y ausencia de retry ciego; no el mismo SLO de latencia. Incluir cola en la medición, cantidad de muestras, máximos y errores. Cero violación crítica en corpus/inyección; gates fallidos/skipped nunca verde. Perfil es ensayo técnico, no promesa pública; la clínica fija alcance/tasa permitidos y se repite con distribución real de llamadas antes de superar la carga ensayada. No criterio abstracto de “dos rondas”.

**Tests.** EVAL-01/02: fila queued no delivered, stub no responde a pending, release incompleto no aprobado. COST-01: planner+authorizer+verifier+retry+timeout contados; restart no reinicia presupuesto. SCALE-01: org ruidosa no ocupa todos los planners y sender progresa con LLM bloqueado; SCALE-02: timeout/Meta lento no pierden guidance ni abren permiso. Archivos test_metrics.py, test_llm.py, test_worker.py, test_regression_suite.py y test_corpus_conversacional.py; escenario de carga nuevo propuesto en tests del agente. Contratos se prueban por capa y un conjunto acotado E2E, no producto cartesiano de todos los fallos/tools.

**Datos/migración.** FK LLMCall→TurnWork si falta; contadores de llamadas/cupo reservado por trabajo solo para presupuesto operativo (default 0 para nuevos; legacy desconocido no inventado). Reusar configuración existente o constantes de release para límites fijos; no nuevos estados, tabla de billing ni presupuesto global distribuido. Uso desconocido se expone y admite fallback conservador.

**Deploy/rollback.** Aprobar lista explícita: READs públicas, READs personales y cada WRITE adaptado. Por org, autonomía efectiva = lista del release ∩ política/identidad ∩ capacidades del contrato desplegado. Terminar B8A no abre las demás. Ampliar cohortes solo tras gates técnicos y cobertura humana; retirar capacidad/reducir carga para rollback, conservando sender, fencing, contabilidad y datos. Fallo en E2/E3/E4 no cierra por sí solo una capacidad básica ya validada.

**Documentación.** Runbook de agente, arquitectura, CI/evals y acta de perfil/capacidades/versión mínima compatible. P-A aporta política revisada; P-B demuestra el mecanismo de retención aplicable.
**Riesgos eliminados:** falso verde por row/skip y contador parcial en rutas migradas. **Reducidos:** saturación/coste dentro del perfil. **Abiertos:** otra carga, deriva LLM, proveedor, identidad débil y cobertura humana; ampliar alcance requiere repetir gates pertinentes.

## Seguimiento B9C — 2026-09-27

R04/R12 implementados: límite de un TurnWork con autoridad por organización,
claim atómico sobre Organization existente, dos planners secuenciales fijos,
sender separado y safety de recepción independiente del LLM. El selector
excluye orgs ocupadas antes de cortar el lote. Se reutilizan B3 y B9B, sin tabla,
estado, contador de concurrencia ni migración nuevos. La regresión y aceptación
se registran en el [acta B9C](implementacion-b9c-agente-whatsapp-2026-09-27.md).

B9C: **COMPLETED técnico**, 2.309 IDs únicos aceptados (2.282 históricos + 27 nuevos), cero pendientes y seis métricas críticas en cero. B9 canónica: **IN_PROGRESS**. Los estados anteriores
son historia de sus respectivos hitos. B9D conserva R13; B9E conserva R01/R06–R10/
R15 y PROFILE-BETA-1. Las pruebas SCALE de componente no aprueban el perfil
integral ni cierran H16/H19. Siguiente componente pendiente: B9D, sin iniciarlo
en esta entrega. B0 cerrado; PENDING_ACTIVATION_REQUIREMENTS; cero activaciones.

## Seguimiento B9D — 2026-09-29

B9D **COMPLETED técnico**: 2.384/2.384 IDs únicos, cero pendientes, corpus
crítico y checks verdes. Siguiente hito: B9E, sin iniciarlo en esta entrega.

R13 se implementa como aprobación inmutable por release/org/capability y gate
adicional en la frontera B8A. No se añaden tabla de cohorts, activation_revision,
workflow ni estado ACTIVE. READY se deriva de evidencia con procedencia; la lista
productiva está vacía. El [contrato](contrato-beta-release-b9d.md), la
[extracción literal](evals/b9d-requirements.json) y el
[ADR](decisions/2026-09-28-b9d-beta-release-gates.md) separan software, aprobación
operativa y ejecución efectiva. El [acta](implementacion-b9d-agente-whatsapp-2026-09-29.md)
registra la aceptación y el baseline para B9E.

B9 permanece IN_PROGRESS. B9E conserva R01/R06–R10/R15, PROFILE-BETA-1,
CI/eval del candidato y aceptación integral EVAL/COST/SCALE. La validación de
estructura de esos recibos no los fabrica ni ejecuta. P-A/P-B, revisión
veterinaria, piloto y cobertura/fallback humanos conservan autoridad externa.
B0 cerrado, B7B=False, execution flags={}, PENDING_ACTIVATION_REQUIREMENTS,
cero clínicas activadas, sin deploy.
