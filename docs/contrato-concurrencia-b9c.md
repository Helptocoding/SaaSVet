# B9C — Concurrencia de TurnWork

Baseline verificado: `e9792c09e5830f058e8f143db7f4fcd93eef03fe`.
Estado inicial: contrato previo a implementación; aceptación entonces pendiente.
Cierre: B9C COMPLETED técnico; ver [acta](implementacion-b9c-agente-whatsapp-2026-09-27.md) y recibo final.
Autoridad: [plan canónico](plan-implementacion-auditoria-agente-whatsapp-2026-09md),
leído completo. B9C es el componente R04/R12 del mapa interno; B9 IN_PROGRESS.
No existe contradicción material con el encargo al adaptar «slot» al claim B3.

## Matriz previa de requisitos

Las líneas corresponden al baseline. Los IDs Rxx son del mapa, C/I/SCALE del
plan; las filas sin ID propio conservan su sección, sin inventar IDs canónicos.

| ID/sección/línea | Semántica canónica | Componente / existente | Gap y cambio requerido | Prueba requerida |
| --- | --- | --- | --- | --- |
| R04, §7/B9:717 | Planners con concurrencia fija acotada por procesos; un trabajo activo por conversación y máximo uno por org para ensayo beta | worker secuencial; B3 excluye conversación, no org | Claim serializado por fila Organization; ocupación derivada de TurnWork | N=1: 0/1/2; distintas conversaciones; último cupo multiproceso |
| R04, §7/B9:717 | Claim por org en transacción corta con fila organizativa/AgentSettings e índice TurnWork; sin tabla scheduler | Conversation→TurnWork; FK organization indexada e índice status/lease | Organization antes del claim; reutilizar índices existentes | Error SQL/rollback, competencia PostgreSQL, ningún lock durante HTTP |
| R04/R07, §7/B9:717/721 | Sender separado; dos planners y un sender, polling máximo 1 s en PROFILE-BETA-1; no autoscaling que multiplique límite | Compose tiene un planner/un sender, poll 2 s | Topología fija de dos réplicas planner secuenciales, sender separado, poll 1 s | Configuración y progreso sender mientras LLM bloqueado |
| R04, §7/B9:717 | Timeouts herramientas/proveedor; backoff conocido; safety rápido sin esperar LLM | READ 10 s, LLM B9B 10 s, Meta B4 15 s; backoff B3/B4; safety en recepción | Preservar y probar; no crear otro rate limiter | Timeout, guidance saturada, Meta lento/incierto, B7/B8 cerrados |
| R12, §7/B9:729; §8:913 | Configuración existente o constantes de release; sin estados nuevos, billing ni presupuesto global distribuido | TurnWork PROCESSING/lease/token/epoch | Constante de release 1; ninguna nueva tabla/campo/estado | Sin config opcional ilimitada; schema sin drift |
| C4, §5.3:180–190 | Único trabajo no terminal por conversación; token único; reloj DB; expiry recupera; miembros/cursor fijos; deadline menor a lease | durable.py: 15 min lease, 12 min deadline, 3 intentos, retry 30/60 s | Componer con B3 sin segunda autoridad ni reset de presupuesto | Crash, restart, token viejo, epoch viejo, retry y nuevos inbounds |
| I09/I10/I13, §4:97–104 | Stale no obtiene nueva autoridad local; crash no completa; aislamiento; HTTP admitido puede terminar tarde | witness/guard/publicación B3/B8, sender B4 | Conservar; capacidad es autoridad local, no cancelación remota | Takeover durante LLM, stale finalize/admission/tool, dos tenants |
| R03/R05, §7/B9:716/718 | Admisión LLM durable por turno bajo witness; rollback no devuelve llamadas | B9B 30 llamadas/18.000 salida | Independencia: no tocar contadores ni duplicar witness | Sin claim no budget; agotado finaliza/fallback; timeout conserva admission |
| SCALE-01, §7/B9:727 | Org ruidosa no ocupa todos los planners; sender progresa con LLM bloqueado | Candidatos globales cortados por batch antes de claim | Excluir org ocupada antes de LIMIT; no round-robin nuevo | Backlog mayor que batch y otro tenant; proceso sender independiente |
| SCALE-02, §7/B9:727 | Timeout/Meta lento no pierden guidance ni abren permiso | B3/B4/B5 y harness B9A | Prueba de componente con providers controlados | Guidance durable con org saturada; no blind retry; gates intactos |
| R07/R09/R10, §7/B9:721–727 | 3 orgs, cargas 10 s/1 s, 30 s warmup+300 s; LLM .5/READ .1/Meta .2; timeout 10/Meta 2; p95 claim 10 s/guidance-dispatch 5 s/outbox-dispatch 5 s; cola/muestras/máximos/errores | B9E pendiente | Entregar evidencia SCALE de invariantes; no ejecutar ni aprobar perfil integral | Corpus versionado + journals por ID; latencias integrales quedan B9E |
| §10:1000–1021 | Edad pendiente, expiraciones/reclaims, espera de cuota, stale rejects; sin alta cardinalidad en series; telemetría no es autoridad | Eventos B3; Message/TurnWork y LLMCall | Eventos cerrados de admisión/saturación; snapshot readonly derivado | Observabilidad sin contenido/IDs como labels; evidencia recuperable desde DB |
| §2:25–26; §9:947–996 | PostgreSQL/procesos/conexiones reales; fake registra fuera del proceso/transacción que muere; no producto cartesiano | Harness B9A + runner exacto B8E | Extender pruebas y journals, sin sustituir runtime | PIDs Python/PG, kill, barreras, 2.282 IDs históricos exactos |
| §7/E4:808–821 | Fairness/round-robin, cupo global compartido y breaker solo con reporte de necesidad | Sin reporte E4 | No implementar; evitar bloqueo por lote no crea fairness scheduler | No nuevas dimensiones/quotas/tabla/cursor |
| §8:927–939; §11:1029–1045 | Corte de writers antiguos; ingress durable; rollback conserva datos/fences/sender | Procedimientos B3/B4/B9B | Documentar versión compatible y ocupación preexistente | No deploy; si hay varias leases legacy, no admitir hasta drenar |

## Respuestas previas (17)

1. Recurso: procesamiento ordinario de TurnWork por planners, no solicitudes LLM.
2. Unidad: un TurnWork committed con autoridad PROCESSING y lease vigente.
3. Máximo uno por organización y uno por conversación; dos procesos planner en
   la topología ensayada. No es un semáforo global de DB con límite dos.
4. Scope: org agregado entre procesos, conversación por B3 y proceso secuencial.
5. Adquisición: commit del claim B3, antes de C1/planner/tools/admisión B9B.
6. Liberación: completion/failure/retry/invalidation B3; expiry retira autoridad.
7. Crash: commit ausente no ocupa; claim committed ocupa hasta expiry/invalidation.
8. Restart: lee las mismas filas; no reinicia contadores ni leases.
9. Lease expiry: deja de contar autoridad; reclaim cambia token del mismo trabajo.
10. Stale: no renueva por terminar una llamada; B3/B9B/B8 rechazan progreso nuevo.
11. Saturación: no claim; ninguna mutación de Message, attempts o presupuesto.
12. Se difiere al siguiente polling sobre la cola durable existente. No rechazo HTTP.
13. SCALE exige no monopolizar planners; fairness fuerte/round-robin pertenece E4.
14. No timeout de espera de cola canónico. Los p95 son gates B9E, no TTL de descarte.
15. SCALE necesita exclusión por org, progreso cross-tenant/sender/safety, timeout,
    durabilidad y cero permisos añadidos; B9E necesita además el perfil temporal.
16. Reutilizar TurnWork/Conversation/Organization, token/epoch/cursor/membership,
    Message sender y witness/admisiones/contadores LLMCall B9B.
17. Prohibidos: nueva ownership/state machine, scheduler/broker/Redis semaphore,
    cuotas globales/por provider/READ/WRITE/modelo, rate limiting o billing, force
    release, nuevos thresholds y autonomía por cupo disponible.

## Pipeline, lifecycle y locks

HTTP inbound persiste Message y safety B5 sin adquirir cupo. TurnWork se crea o
recupera en el claim; antes puede existir solo Message pendiente (B3). El claim
admite toda la planificación, TurnContext, roles LLM, tools, B7 y B8 hasta la
publicación/completion atómica. Outbound PENDING libera el cupo del planner.
Sender/provider outbound tienen autoridad independiente B4 y quedan fuera del cupo.

Orden causal: exclusión org + claim B3 → witness → TurnContext → admisión B9B
por llamada → provider HTTP sin locks → finalización B3. Agotamiento B9B usa el
fallback existente y libera al terminar; el consumo B9B nunca se devuelve.
Error/timeout conserva admisiones; retry B3 vuelve a competir por el cupo.

Orden previsto: Organization (NO KEY UPDATE) → Conversation → TurnWork → Message.
El lock organizativo serializa solo adquisiciones; NO KEY permite referencias FK
concurrentes. SKIP LOCKED en Organization/Conversation representa no claim y nuevo
poll, no espera ocupando el planner. Ninguna liberación toma el lock organizativo:
solo reduce ocupación y continúa usando CAS B3. B9B: Conversation→TurnWork→LLMCall.
B8: Conversation→TurnWork→ContactIdentity→Goal→Operation→locks de dominio.
Sender: Conversation→Message. No se añade Organization a esas rutas ni se mantiene
un lock DB mientras ocurre HTTP. Handoff humano no compite por cupo organizativo.

La ocupación exige epoch de TurnWork igual a Conversation; expiry/takeover revocan
autoridad local. Una llamada externa previamente admitida puede seguir en vuelo;
no se promete cancelación remota, simultaneidad física de sockets ni exactly-once.
Requests impone timeout de conexión/lectura, no deadline absoluto ante goteo de
bytes. Se conserva el límite honesto B3/B9B: resultado tardío no concede efectos.

No migración prevista: se reutilizan FK organization indexada, índices status/lease
y retry y unique de trabajo no terminal. No contenido conversacional nuevo.
La constante de release uno no necesita config opcional: ausencia de AgentSettings
no implica infinito; el fallback existente también compite por el mismo cupo.

Producción: B0 cerrado; B7B=False; execution flags={}; cero clínicas activadas;
PENDING_ACTIVATION_REQUIREMENTS. No deploy, B9D/B9E ni PROFILE-BETA-1 integral.

## Integración safety verificada durante implementación

La recepción B5 usaba el claim general bajo Conversation. La primera corrida
detectó que aplicar allí el cupo de planner retrasaba guidance durante saturación.
El [ADR](decisions/2026-09-27-b9c-turnwork-concurrency.md) documenta el ajuste:
se reutiliza la primitiva B3 bajo una sola transacción de safety que crea y
completa el trabajo, caso y plantilla. No confirma un segundo PROCESSING, ni
ejecuta LLM/tools/HTTP. Un error SQL revierte esa transacción; el webhook conserva
el inbound pendiente. No cambia la ruta de una conversación que ya tiene trabajo
no terminal ni sus miembros fijos. El sender mantiene la autorización B5 estrecha.

## Regresión de carreras B8 y estado heredado

Las carreras de dominio B8B/C/D/E preparaban dos claims de planner simultáneos en
una org mediante el API anterior. B9C debe rechazar el segundo. Sus fixtures
ahora verifican ese rechazo y preparan explícitamente dos witnesses heredados
con la primitiva B3, exclusivamente en tests de capa de dominio. Así se conserva
la prueba multiproceso de guards, locks y constraints mientras drenan trabajos
admitidos por versiones anteriores. No se añade una ruta productiva de bypass,
ni se retira ningún ID/aserción. Ese estado heredado no se cuenta como admisión
B9C ni como muestra de su corpus N=1. Se repiten los 118 IDs de procesos afectados
de B8B/C/D/E; los éxitos válidos tras adaptar cada fixture se conservan por ID
si se interrumpe una corrida. Un registro incompleto nunca cuenta como éxito.
