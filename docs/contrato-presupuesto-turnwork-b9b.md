# B9 — Componente interno de presupuesto operativo (B9B)

Baseline: `ccd49844e6e777395517a0527f564faf7fc5b0f2`. Estado: COMPLETED técnico del componente interno; B9 IN_PROGRESS.
La continuación del 27-09-2026 resuelve el bloqueo anterior; ambos informes de
discrepancia se conservan. Autoridad: §7/B9 de
`plan-implementacion-auditoria-agente-whatsapp-2026-09md` (nombre real del archivo).
B9 canónica sigue IN_PROGRESS. R03/R05/R11, respetando R12. Sin billing,
periodos, state machine nueva, scheduler, activación ni PROFILE-BETA-1.

## Matriz previa a implementación

| Requisito literal | Línea baseline | Existente | Cambio requerido | Prueba |
| --- | --- | --- | --- | --- |
| registrar todas las llamadas/roles/retries y límites de timeout/calls/tokens máximos por turno | 714 | Tres call sites: planner y dos clasificadores; retries del planner; timeout 30 s y salida 600/160/120 | Admisión común antes de cada complete; límites de release compartidos por trabajo | Roles, retry, timeout, agotamiento sin proveedor |
| Coste/usage desconocido no es cero | 714 | Adapter usa 0 por ausencia y coste sin precio 0 | Campos nullable; preservar usage válido incluso con respuesta inválida; coste desconocido null | Usage ausente/malformado y error de contrato |
| Reusar LLMCall; correlación a TurnWork nullable se introduce con este consumidor | 714 | LLMCall sin FK; escritura diferida en TurnChanges | FK nullable y evidencia de admisión en la misma fila | E2E y scope cruzado |
| Un intento recuperado cuenta llamadas anteriores del mismo trabajo al aplicar presupuesto; no otorgar cupo infinito por restart | 714 | Contador conversación se aplica solo a éxitos y se difiere | Contadores acumulados en TurnWork | Restart y último slot |
| Presupuesto por turno con reserva de llamadas/cupo máximo antes de llamar, actualizada bajo witness | 716 | OwnershipWitness B3; sin reserva LLM | Conversation → TurnWork; validar token/epoch/lease/deadline; commit antes de HTTP | Carrera de procesos y witness stale |
| rollback de intento no repone llamadas ya admitidas | 716 | LLMCall en buffer volátil, desaparece con crash | Transacción durable independiente de finalize_turn; no devolución | Kill antes/después de admisión; rollback posterior |
| No reservas distribuidas de gasto diario ni cuotas globales de urgencias ahora | 716 | No existen | Conservar frontera | Inspección de migración y código |
| COST-01: planner+authorizer+verifier+retry+timeout contados; restart no reinicia presupuesto | 725 | Cobertura parcial | Evidencia por llamada admitida, rol y retry_of | Corpus COST y E2E |
| contadores de llamadas/cupo reservado por trabajo solo para presupuesto operativo (default 0 para nuevos; legacy desconocido no inventado) | 727 | Sin campos | Migración nullable para filas previas; default Python 0 solo para nuevas | Migración y legacy fail-closed |
| Reusar configuración existente o constantes de release para límites fijos; no nuevos estados, tabla de billing ni presupuesto global distribuido | 727 | Límite conversación 40; loop 5 tools + 2; hasta 3 retries | Constantes de release por turno; ninguna tabla/estado nuevo | Schema/checks |
| Uso desconocido se expone y admite fallback conservador | 727 | Ausencia aparenta 0 | Reserva máxima de salida nunca se devuelve; usage null | Unknown y timeout |
| retirar capacidad/reducir carga para rollback, conservando sender, fencing, contabilidad y datos | 729 | Gates cerrados | Mantener gates; rollback compatible con columnas y evidencia | Defaults y regresión |

## Contrato y decisiones mínimas

La unidad de admisión es **una llamada a complete**, incluidos intentos que fallen,
timeouts y retries de transporte. No es dinero ni una respuesta exitosa. Cada nueva
llamada requiere UUID distinto y consume un slot y su máximo de tokens de salida.
Observar una admisión ya persistida no permite volver a hacer HTTP; el UUID tiene
constraint unique. Sin resultado conversacional almacenado no hay replay de la
respuesta: un restart que vuelve a llamar consume otra admisión.

Constantes de release: máximo 30 llamadas por trabajo, derivado del loop existente
(5 tools + 2) × (1 + máximo 3 retries) + authorizer + verifier; máximo 600 tokens
de salida por llamada, 18.000 reservados por trabajo. Los clasificadores conservan
160/120. Entrada limitada a 65.536 bytes UTF-8 de JSON canónico de messages/tools;
es un límite de tamaño de contexto, no una estimación de tokens reportados. Los
tokens de entrada/salida reales solo provienen de usage del proveedor. No se
inventa tokenizador para un proveedor todavía no elegido. Timeout HTTP de 10 s,
además del deadline B3. Requests limita conexión/espera de lectura; no garantiza
un plazo absoluto frente a un servidor que gotee bytes. No se amplía B9C aquí.

OwnershipWitness contiene organization_id, conversation_id, turn_work_id,
lease_token y ownership_epoch. La DB exige PROCESSING, lease no vencida, epoch
coincidente con Conversation y deadline B3. Un ID aislado no basta. El orden es
Conversation → TurnWork → LLMCall; no se toman ContactIdentity/Goal/Operation
durante admisión. Commit durable antes de complete; finalize_turn mantiene su
transacción LOCAL_ATOMIC existente. Se rechaza admisión dentro de otra transacción
de aplicación. El wrapping especial de Django TestCase no acredita durabilidad:
esa garantía se prueba con TransactionTestCase y procesos PostgreSQL reales.

Legacy sin contadores queda desconocido y no obtiene nuevas admisiones. Nuevo
TurnWork empieza en cero. Límites se guardan con el trabajo para inspección y
estabilidad durante restart. Ni error, timeout, rollback ni cierre devuelven slots
o tokens máximos reservados. Esto conserva cupo operativo, no atribuye tokens
facturados ficticios.

## Inventario

| Sitio | Purpose cerrado | Witness/TurnWork | Adapter | Usage | Retry |
| --- | --- | --- | --- | --- | --- |
| planner._complete_with_retry | planner | current_changes().witness en worker | OpenAICompatibleClient.complete, POST no streaming | prompt_tokens/completion_tokens | Cada retry obtiene nueva admisión; retry_of liga intentos |
| operation_authorization._classify | operation_authorizer | mismo buffer B3 | mismo adapter; modelo por rol | mismo usage | Sin retry automático propio |
| operation_authorization._verify | operation_verifier | mismo buffer B3 | mismo adapter; modelo por rol | mismo usage | Sin retry automático propio |

No hay responder/summarizer/extractor ni fallback HTTP adicional. La selección de
modelo por rol tiene fallback de configuración al router/planner, no otro intento
de proveedor. Las tools y respuestas pasan por el planner. Los comandos EVAL
históricos llaman helpers sin TurnWork y son diagnóstico; registran LLMCall sin
admisión de producción. El modo application-e2e recorre worker y sí consume cupo.
Los tres call sites se identificaron por grafo y búsqueda textual de respaldo
(search_code devolvió insuficientes resultados). Ningún prompt o respuesta se
añade a LLMCall. El proveedor se identifica por vocabulario fijo, no URL con secretos.
