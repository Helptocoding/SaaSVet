# B9: admisión operativa durable por TurnWork

Estado: implementado y aceptado como componente interno; B9 canónica IN_PROGRESS. Fecha: 2026-09-27.
Autoridad: B9 canónica, cambios 2/4 y datos; no es una fase canónica nueva.

El buffer TurnChanges descartaba LLMCall con el rollback de publicación, aunque
el proveedor ya hubiese trabajado. El contador Conversation solo contaba éxitos
del planner. El autorizador/verificador no compartían un límite durable por
trabajo. Ausencia de usage y de precios aparentaban cero.

Se inserta LLMCall e incrementan contadores de TurnWork en una transacción durable
corta bajo OwnershipWitness. Se reutiliza Conversation → TurnWork de B3; no se
modifican locks, consentimiento, LOCAL_ATOMIC ni dominio B8. Se hace HTTP después
del commit y se registra la observación una sola vez en LLMCall. El commit de
admisión es el punto de orden: una revocación posterior no deshace ese intento,
pero cerca nuevas admisiones y publicación. Usage tardío se conserva aunque el
witness haya dejado de autorizar publicación.

Una caída antes de commit no consume; después sí. No existe release ni devolución,
incluso si el proceso murió antes de enviar. Un UUID ya conocido solo devuelve
la fila, sin permiso para repetir HTTP. El adapter no ofrece idempotency keys
remotas ni recuperación de respuestas; no se simula ese soporte. Retry nuevo
significa nueva admisión. retry_of relaciona retries de transporte del planner;
reiniciar el trabajo conserva todos los intentos por la FK TurnWork.

## Migración 0028: justificación de cada campo

| Entidad/campo | Necesidad |
| --- | --- |
| TurnWork.llm_calls_admitted | Cupo de llamadas consumido que sobrevive al rollback del trabajo |
| TurnWork.llm_output_tokens_reserved | Máximo de tokens de salida admitido; no es usage ficticio |
| TurnWork.llm_call_limit | Snapshot fijo del límite de release para ese trabajo |
| TurnWork.llm_output_token_limit | Snapshot del máximo de salida por trabajo |
| LLMCall.turn_work | Correlación nullable exigida explícitamente por B9 |
| LLMCall.admission_id | Identidad unique para observación idempotente de una admisión |
| LLMCall.admitted_at | Evidencia temporal de admisión, distinta de éxito/provider/completion |
| LLMCall.recorded_at | Distingue fila admitida sin observación de una respuesta/error observado |
| LLMCall.admission_lease_token | Procedencia causal al lease que admitió la llamada |
| LLMCall.admission_epoch | Epoch de ownership usado, incluso después de recuperación |
| LLMCall.purpose | Planner/operation_authorizer/operation_verifier, los tres roles existentes |
| LLMCall.reserved_output_tokens | Cupo máximo de esta llamada; reproducir contador sin inferir usage |
| LLMCall.input_tokens/output_tokens nullable | Ausencia o dato malformado no es cero |
| LLMCall.cost_estimate nullable | Sin política monetaria canónica, coste nuevo desconocido |

Los dos contadores se agregan sin default para preservar NULL histórico; después
se fija default Python 0 para nuevos trabajos. No se inventan admissions, usage
o coste históricos. Los límites de release no son cuotas comerciales de clínicas.
Constraints PG impiden contadores mayores al límite; unique impide duplicar UUID;
check exige evidencia completa para una admisión. La coherencia tenant y witness
se valida en el servicio con filas bloqueadas. No nuevas tablas ni estados.

## Límites y consecuencias

30 llamadas/18.000 tokens máximos de salida por trabajo, 600 por llamada y 65.536
bytes UTF-8 por entrada. Los roles semánticos siguen usando 160/120 de salida.
El máximo de llamadas cubre el loop actual (5+2) con hasta tres retries por
llamada, más dos clasificadores; cambiar ese contrato requiere nueva validación.
El input byte cap es control de tamaño, no tokens reportados ni tokenizer supuesto.
El timeout Requests pasa a 10 s; su semántica de lectura no garantiza límite
absoluto frente a un proveedor que entregue datos lentamente. El deadline B3
se mantiene; los límites generales de procesos/herramientas pertenecen a B9C.

En runtime B3, policy consulta TurnWork y la admisión vuelve a comprobar el cupo
atómicamente. El contador de conversación queda como dato legacy, no otra
autoridad de presupuesto B9. Helpers sin witness conservan su comportamiento
diagnóstico y LLMCall sin admisión; no acreditan aceptación de producción.

No se amplía billing ni se inventan precios. El helper de estimación histórica
conserva la fórmula configurada, corrigiendo ausencia a NULL y aritmética Decimal;
las nuevas filas del componente mantienen coste desconocido. Las métricas
exponen subtotales conocidos junto a conteos unknown, nunca un total completo
aparentemente cero. No se almacenan prompts/respuestas ni errores libres.

Rollback funcional: detener nuevas planificaciones o deshabilitar AgentSettings,
mantener sender/fencing y datos. No deshacer 0028 en producción ni desplegar un
writer legacy capaz de ignorar el presupuesto sobre trabajos activos. El ensayo
de migración inversa solo es válido en una base aislada de fixtures.
