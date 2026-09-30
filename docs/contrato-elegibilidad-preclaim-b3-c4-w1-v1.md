# Enmienda B3/C4/W1 v1 — elegibilidad monotónica preclaim

Fecha: 2026-09-30. Estado: **FROZEN**, autorizado por el encargo explícito
«Enmienda B3/C4 + implementación de elegibilidad monotónica pre-claim».
Baseline: `623a80930883fd0473ac6fe4697a417f763dad4c`.
Esta enmienda se congela antes de modificar runtime. Su implementación está
autorizada dentro del mismo encargo; no autoriza activación ni despliegue.

## Autoridad y alcance

Enmienda explícitamente la espera W1 y el tramo anterior al claim de B3/C4
del [plan canónico](plan-implementacion-auditoria-agente-whatsapp-2026-09md),
el [contrato B3](contrato-trabajo-durable-b3.md) y el [módulo agent](modules/agent.md).
Los recibos históricos conservan su política y resultado originales.
Se adopta la decisión de la [auditoría posterior a E4](decisions/2026-09-30-agent-capacity-debounce-next-change.md).
El selector E4 marcado KEEP no se modifica.

## READY y fuente de verdad

READY es un concepto derivado: existe al menos un Message ordinario inbound,
PENDING, sin TurnWork, en la conversación, cuyo `available_at <= db_now`.
El `available_at IS NULL` legado significa elegible, como en B3/E4.
La fuente de verdad es PostgreSQL, bajo el mutex Conversation; no una caché,
un reloj de aplicación, un estado TurnWork nuevo ni un evento de observabilidad.

READY satisface la espera de la ráfaga. No concede ownership, witness, lease,
attempts, admisión LLM, presupuesto B9B, capacidad B9C ni permiso B7/B8.
No fija membership, TurnContext, anchor o cursor. No nace TurnWork por alcanzar
READY. Safety signals conservan el camino y la precedencia B5 existentes.

## W1 y significado único de available_at

Para el conjunto ordinario PENDING sin asignar de una conversación:

1. Antes de la primera elegibilidad, cada inbound puede mover el deadline común
   a `min(db_now + 8 s, oldest.created_at + 25 s)`. Si el cap ya venció, el
   deadline es `db_now`. Se conserva rolling silence y hard cap.
2. En el vencimiento exacto (`<=`, incluida la frontera t=8), READY queda
   satisfecho sin necesidad de que un poller haya observado el vencimiento.
3. Después, un inbound ordinario persistido antes del claim se incorpora al
   conjunto y recibe también un deadline vencido. No puede quedar a `now+8`
   mientras los miembros anteriores siguen elegibles.
4. El deadline común es el menor deadline no nulo ya vencido; cuando únicamente
   NULL expresa READY, es `db_now`. Ningún miembro del conjunto recibe un
   deadline futuro que retire READY. No se exige conservar un timestamp NULL.

`available_at` es el deadline del conjunto, no el instante individual de recepción:
el inbound nuevo puede heredar un deadline anterior a su propio `created_at`.
En diagnósticos, su elegibilidad efectiva individual es
`max(created_at, available_at)` (NULL: `created_at`), evitando duraciones negativas.
La elegibilidad no equivale a un claim ni promete un SLA de planificación.

## Reloj y transacción

Ingest adquiere Conversation, obtiene `statement_timestamp()` PostgreSQL fresco
mediante `durable.db_now`, persiste el Message y actualiza los deadlines dentro
de la misma transacción. El tiempo anterior a esperar el mutex no decide READY.
Un fallo antes del commit revierte Message y deadlines juntos. El recibo causal
B7, capturado antes de los locks, mantiene su frontera y no se mueve.

## Carreras y congelación B1/B3

El orden de adquisición del mutex Conversation decide:

| Ganador | Resultado |
|---|---|
| Ingest B, con A READY | Commit de A+B READY; el claim posterior incluye ambos. |
| Claim A | W1 congela A; B no se anexa y continúa mediante W2 B3. |

El claim conserva Organization → Conversation → TurnWork → Message y B9C N=1.
Membership se asigna exactamente una vez. Orden causal persistido
`(created_at, id)`; anchor = último miembro; cursor = coordenada del primer
miembro, límite exclusivo de `history_before`, no un mensaje previo inventado.
TurnContext se congela únicamente en claim y permanece inmutable después.
Los triggers B3 de scope, causalidad, no reassignment y no append se conservan.
Retry/reclaim recuperan el mismo work y presupuesto, con las reglas B3 existentes.

## Correcciones, seguridad y efectos

«quiero cita mañana» → READY → «mejor el viernes» antes del claim produce un
contexto con ambos mensajes en orden. Fragmentos de intención, mascota, fecha y
corrección persistidos antes del claim se incluyen completos; no se elimina
coherencia para mejorar latencia.
Después del claim, `has_new_input` detecta B y la publicación obsoleta se
difiere/bloquea según B3. B6 revalida binding/revisiones; B7 conserva propuesta,
digest y consentimiento causal; B8 conserva guard final y no ejecuta parámetros
distintos bajo consentimiento antiguo. Safety y takeover conservan precedencia,
invalidación de epoch y reglas de handoff existentes.
B9B conserva 30 calls/work, 18 000 output tokens reservados/work, máximo 600/call,
admisión durable y no refund. READY no consume presupuesto ni reserva N=1.

## Verificación y diagnóstico autorizado

Se exigen W1-MONO-01..10, fronteras 8−ε/8/8+ε controladas sin sleeps,
RACE-01..10 con PostgreSQL y procesos independientes, FI-01..10 y regresión
proporcional B1/B3/B5/B6/B7/B8/B9A/B9B/B9C/B9D/E4/channels/agent/domains.
No se retiran IDs históricos ni se relajan assertions silenciosamente.
Primero se demuestra causalmente la desaparición de la segunda quiet window y
se mide persisted→eligible, eligible→claim y persisted→claim por organización,
calls/work/diálogo y deferrals. Datos sintéticos, métricas de baja cardinalidad,
sin guardar prompt, response, teléfono, owner, pet o texto clínico.
Solo si el residual permite razonablemente el gate existente se autoriza un
único rerun PROFILE-BETA-1 v1 original. Si el residual no cabe, STOP sin gastar
ese intento. No B9E integral, PROFILE-BETA-2 ni nuevo threshold.

## Compatibilidad, rollback y límites

| Writer | Worker | Compatibilidad |
|---|---|---|
| antiguo | antiguo/nuevo | Sigue pudiendo retirar READY; no garantiza v1. |
| nuevo | antiguo | Lee el mismo available_at; claim B3/E4 compatible. |
| nuevo | nuevo | Garantía v1 si todos los writers cumplen esta enmienda. |
| mixtos | cualquiera | No garantiza monotonicidad: requiere corte coordinado de writers. |

Para rollout futuro deben drenarse/cortarse writers antiguos antes de activar
la garantía. No se despliega en este encargo. Rollback restaura el código de
rolling silence sin borrar Messages, TurnWork, membership, AuthorizationEvidence
o effects, sin desasignación ni devolución de presupuesto. Una ráfaga promovida
ya no permite reconstruir mágicamente silencio histórico; permanece durable.
No migration prevista. Si las entidades actuales resultaran insuficientes,
STOP antes de schema nuevo con decisión explícita.

B9A/B9B/B9C/B9D COMPLETED; B9 IN_PROGRESS; B9E FAIL; PROFILE-BETA-1 histórico
FAIL; E4 PARTIAL/ROOT_CAUSE_CONFIRMED. Incluso un rerun verde solo produce un
candidato posterior. B0 cerrado, B7B=False, execution flags={}, release grants
vacío, 0 clínicas activadas, PENDING_ACTIVATION_REQUIREMENTS, sin deploy.
Al finalizar: STOP; no reapertura formal B9E, scheduler nuevo, wake-up, E5 o P-A/P-B.
