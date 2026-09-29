# B9C: concurrencia derivada del claim B3

Estado: aceptado; B9C COMPLETED técnico. Ver acta y recibo final. B9 canónica IN_PROGRESS.
Fuente: §7/B9 cambio 3 y datos, R04/R12 del mapa interno.

El worker tenía exclusión por conversación pero dos procesos podían reclamar
conversaciones de la misma organización. El lote global de candidatos también
podía quedar lleno de conversaciones de una org ya ocupada. B9 exige como máximo
un trabajo activo por org, planners secuenciales acotados por topología y sender
separado. No exige cupo global durable, semáforo de provider ni rate limiting.

## Decisión

`durable.claim_turn` toma Organization con `FOR NO KEY UPDATE SKIP LOCKED`, después
Conversation con el `SKIP LOCKED` de B3. Comprueba TurnWork PROCESSING, lease futura
y epoch igual a Conversation. Solo entonces usa la misma primitiva B3 de membresía,
cursor, intentos, token y claim. Commit del claim adquiere la capacidad. La fila
organizativa es exclusión transaccional, no un contador ni un slot persistido.
Se conservan el índice FK organization, los índices de lease/retry y el unique
parcial por conversación. No se necesita migración ni backfill.

No hay check-then-start fuera de frontera atómica: todos los claimers de la misma
org toman la misma fila. Release/fail/takeover solo reducen ocupación y conservan
sus locks/CAS B3. Expiry no se renueva al regresar un LLM: la fila vieja pierde
autoridad y una recuperación cambia el token. SQL rollback no deja claim parcial.
Restart consulta las mismas filas y B9B conserva su consumo histórico.

NO KEY UPDATE permite comprobaciones FK entrantes sin bloquear recepción de otras
conversaciones. SKIP LOCKED significa no claim y siguiente poll sobre los mismos
Messages; evita gastar un planner esperando al otro y conserva la semántica B3.
Conversation se omite si está bloqueada: no se espera una fila que pueda necesitar
una FK organizativa. Las rutas de finalización, B7/B8, sender e Inbox no adquieren
el nuevo lock. La red ocurre después del commit, sin locks PostgreSQL.

El selector excluye organizaciones con ocupación vigente antes de cortar el lote.
La comprobación es orientativa; el claim vuelve a verificarla. Orden por actividad
existente, sin cursor round-robin, prioridades nuevas ni garantías de fairness
fuerte. Esas mejoras siguen en E4 si las mediciones las justifican.

Compose declara dos réplicas planner secuenciales, batch 1 y poll 1 s; sender
independiente con poll 1 s. Es definición de topología, no ejecución de deploy.
No se puede multiplicar réplicas y seguir afirmando PROFILE-BETA-1. Este cambio
no convierte dos en un límite global en PostgreSQL.

## Safety B5 durante saturación

La primera corrida detectó que `receive_safety` también llamaba al claim general
mientras sostenía Conversation. Imponerle el cupo retrasaba guidance detectable
hasta terminar el LLM de otra conversación; tomar Organization después de
Conversation tampoco respeta el nuevo orden. Es un gap de integración, no una
contradicción del plan: C5/§7/B9 separan sistema safety y procesamiento ordinario.

Se extrae `_claim_turn_locked`, la misma primitiva B3, sin nueva autoridad. La
recepción safety toma Conversation y conserva una sola transacción para detectar,
crear membresía/witness, consolidar caso/plantilla, completar TurnWork y publicar
guidance. Comprueba COMPLETED/safety_handoff antes de salir. Nunca confirma un
segundo PROCESSING, no ejecuta planner, LLM ni tools y no adquiere cupo de planner.
Una excepción SQL revierte la transacción safety completa; el webhook conserva
el inbound pendiente mediante su fallback existente, sin claim parcial ni fuga.
El sender conserva la validación estrecha de `guidance_authorized`, epoch causal,
enlace exacto del handoff y precedencia humana de B5. Si la misma conversación
ya tiene trabajo no terminal, permanece la conducta B5 de señal pendiente y
continuación, sin cambiar miembros de ese trabajo ni crear otro.

## Límites y operación

Una llamada admitida antes de expiry/takeover puede terminar tarde. Se acota la
autoridad local, no el número físico de sockets remotos. B9B conserva el witness
y la admisión durable, y los guards B3/B8 impiden nuevos efectos/publicación stale.
Timeouts Requests 10 s (LLM/READ) y 15 s (Meta) conservan su semántica de lectura,
no un deadline absoluto ante goteo de bytes. Deadline B3 12 min < lease 15 min;
retry B3 30/60 s, máximo tres intentos. No se rediseña B9B.

Eventos cerrados ADMITTED/SATURATED/DEFERRED se agregan a los eventos B3 de
expiry/reclaim/fencing/completion/failure. `compute_concurrency(org)` es snapshot
readonly, no autorización ni historial de máximos. No nueva UI/CLI force-release;
el operador usa las filas B3 y las métricas existentes. No datos conversacionales
adicionales, etiquetas tenant/conversación ni tasas por minuto.

Corte futuro: drenar writers antiguos; si hay varias leases anteriores por org,
el lector observa la saturación y no admite más hasta drain/expiry/recovery.
Rollback funcional conserva sender, leases/epochs, admissions B9B y pendientes;
reducir planners/pausar autonomía, nunca resetear tokens/contadores ni revivir
consentimiento. H16/H19 y PROFILE-BETA-1 continúan pendientes de B9E.

B0 cerrado, B7B=False, execution flags={}, PENDING_ACTIVATION_REQUIREMENTS.
Cero clínicas activadas. No deploy, B9D/B9E ni aceptación integral.

## Compatibilidad de fixtures de dominio

La regresión histórica detectó 23 errores al preparar un segundo planner en la
misma org en tests B8B/C/D; B8E reprodujo el mismo problema de fixture durante
la recuperación posterior. La admisión nueva rechaza correctamente ese estado.
`tests/b9c_legacy_fixture.py` comprueba el rechazo real y prepara un witness
heredado para conservar carreras de dominio, no para simular un planner admitido
por B9C. Los procesos y todas sus aserciones de negocio/locks permanecen reales.
Solo cambia `second_operation` en cuatro módulos; los 118 IDs de procesos se repiten.
La comparación AST y reconstrucción byte a byte de los hashes registrados
prueban que las demás funciones/tests y el runtime no cambiaron. Los éxitos
durables de módulos no afectados se conservan por ID y los pendientes tras
interrupción se recuperan exactamente, con los fallos originales visibles.
Un registro final con bytes nulos tras una interrupción se excluye, preservando
archivo, longitud y hash; sus IDs sin evidencia válida se vuelven a ejecutar.
