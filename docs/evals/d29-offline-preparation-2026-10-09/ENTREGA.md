# D29 — preparación y validación offline de P01–P05

9 de octubre de 2026. Alcance ejecutado: preparación, verificadores offline y diagnóstico de lectura. **Ningún probe físico, ninguna suite de aplicación ni matriz se ejecutó.**

Se mantienen `CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY` y `CONFIRMED_BASE_ESTABLISHED`. Baseline `825db75df68bf076929fa787e77beefe96803350`; SHA-256 de la base `71c3e58c34decfac1698f9517f39b4d7cbc936c0463e35a4bbfe00ee04920a56`.

Esta entrega responde a la autorización pegada cuyo hash consta en `initial-seal.json`. Los modelos de controles negativos y la aritmética de intervalos acreditan verificadores, **nunca condiciones físicas de carga**. No se convierten las corridas anteriores en PASS. Los planes llevan `execution_authorized=false`.

| Línea | Resultado de esta fase | Límite antes de una ejecución posterior |
|---|---|---|
| P01 / R1-06 | Verificador específico implementado; conciliación causal y controles negativos validados offline. | Integrar los nuevos testigos pasivos en el worker de evaluación y sellar el job prospectivo antes de repetir. Un testigo ausente impide acreditación. |
| P02 / R2-04 | Diagnóstico de lectura y protocolo de restauración preparado. | Este token recibe Access Denied al abrir W32Time con derechos de inicio/parada. Además faltan autorización expresa e instalación/verificación de recuperación independiente. No iniciar. |
| P03 / R1-04 | Geometría condicional posible, ventana física completa **no demostrada**. | Rama detenida; R1-04 continúa pendiente. No se construyó ni ejecutó una fixture con offsets nominales. |
| P04 / R2-09 | Dos planes separados de seis READY iniciales, gates conservadores y controles offline. | Cada variante requiere autorización propia, conexión de la secuencia inicial al harness y evidencia real; no hay garantía de solapamiento. |
| P05 / regresión | Diagnóstico mínimo preservado y plan secuencial de siete suites. | Causa raíz del OOM indeterminada. Autorizar por separado el laboratorio privado, su monitor y la ejecución secuencial. |

## 1. R1-06: verificador y controles negativos

`r106_verifier.py` lee los journals de ingress, dos planners y sender, los ledgers de oferta/población, el calendario, los cortes y el censo durable final. Reconstruye los episodios con `evidence.reconstruct`; no toma el PASS de `job-result.json` como autoridad. Reutiliza sin editar `ClockMap`, `Continuity`, `classify`, `invariant_gate`, `window_gate` y el calendario original.

La única excepción prospectiva al gate genérico es permitir que varios inputs durables compartan un episodio de R1-06. Se retiene el resto de la conciliación: un input aparece exactamente una vez, scope y membership coinciden, todos los slots de oferta existen y fueron aceptados dentro de su pacing, se conocen todos los orígenes y claims, no hay transacciones u ofertas sin resolución. **No se modifica el gate de R1-02 ni el contrato.**

Se verifica separadamente:

1. Ocho inputs/episodios READY naturales distintos en el corte previo; cuatro conversaciones por org sólo en backlog. Sus orígenes se comparan con el corte inicial, sin reset de edad.
2. Oferta ordinaria en tres slots con rotación global original. Cada slot corresponde a la conversación de su org en la fixture; la cuarta conversación no recibe oferta ordinaria.
3. Episodios → works → claims exteriores. Se conserva exactamente el límite de 120 s: superior conocido ≤120 pasa ese bound; inferior >120 es exceso; cruce/ausencia de bounds es indeterminado, sin tolerancia añadida.
4. Por cada work de lectura, dos llamadas LLM completas de ≥0,5 s observados y su ledger durable, admisión y autoridad. Dispatch/result son uno a uno por call_id. Los gates originales siguen comprobando commit anterior al dispatch, N=1, membership inmutable, tenant, contención y ausencia de HTTP dentro de transacción.
5. Por cada outbound real, admisión sender y un dispatch/result Meta correlacionado, ≥0,2 s observado, resultado conocido aceptado y aceptación durable. No se inventa Meta para un work diferido que no creó salida. UNCERTAIN no cuenta como aceptación.
6. Cada diferimiento exige guard nativo verdadero, nuevos inputs posteriores al anchor y committed antes del guard, terminal CAS exitoso en la misma transacción con outer commit resuelto, sucesor de la misma org/conversación reclamado después, y evidencia de que el contexto realmente empaquetado para su primer LLM consumió los inputs anteriores y los nuevos. Las cadenas deben terminar en salidas aceptadas; ni una consulta posterior de historia ni una salida posterior por sí sola descargan la obligación anterior.
7. Conciliación final explícita de inputs, episodios, works, llamadas, salidas, diferimientos y obligaciones. Ventanas, colas, seguimiento completo y drain siguen siendo obligatorios.

Los eventos adicionales preparados son `new_input_guard`, `work_terminal` y `context_consumed`. Deben emitirse **en la frontera nativa**, mediante instrumentación pasiva del worker de evaluación; no se instaló ni activó un observer live. El esquema se especifica en `r106-prospective-policy-v2.json`. El verificador rechaza su ausencia; no llena campos consultando retrospectivamente el censo. Su CLI siempre entrega una evaluación offline, nunca un PASS físico ni una transición de matriz.

La validación final tiene **69 controles offline distintos**, de los cuales 25 cubren conciliación R1-06. Incluye los seis controles negativos solicitados y rechazos adicionales: terminal sin CAS, contexto disponible pero no consumido, input anterior al anchor, claim sucesor anterior al terminal, guard de otra transacción, contexto después del LLM, intervalos que cruzan 120 s, cambios de tenant y dispatch/result duplicados. Ocho controles sobre copias en memoria de la captura prueban que los invariantes originales siguen rechazando corrupción. Receipt: `preparation-tests-attempt-03.json`; se conservan también los intentos anteriores.

La lectura histórica permanece `HISTORICAL_AUDIT_ONLY`: 32 inputs, 31 episodios/works y 30 salidas aceptadas. El work 1 diferido carece de los nuevos testigos nativos, por lo que su enlace no se da por probado. Además, el corte final no cubre definitivamente el extremo superior del seguimiento bajo la intersección temporal estricta (`FOLLOWUP_END_NOT_DEFINITELY_COVERED`); esto es una insuficiencia de acreditación por intervalos, no una afirmación de fallo del runtime. Los receipts históricos se conservan intactos. Auditoría nueva: `r106-historical-read-only-audit-v2.json`.

## 2. W32Time: seguridad, restauración y recuperación independiente

Snapshot de lectura: `host-diagnostic.json`, 2026-10-09 06:45:09 UTC. W32Time está **Running / Automatic**. `w32tm /query /status /verbose` devuelve stratum 0, leap indicator 3 (sin sincronizar), fuente **Local CMOS Clock**, última sincronización válida no especificada y error 1 (sin datos horarios). `/query /source` devuelve Access Denied. La apertura de SCM/W32Time sólo para consultar permisos de QUERY_STATUS/START/STOP también devuelve **error 5**. No se llamó StartService ni ControlService; no se detuvo el servicio.

Detener W32Time suspendería su sincronización para **todo el host**, incluidas aplicaciones y servicios ajenos al laboratorio. Restaurar significa devolver el estado operativo previo, no corregir NTP ni prometer sincronización válida. No se cambian hora, fecha, start type, registro, providers NTP, PostgreSQL ni planes de energía. Windows Time puede ajustar la velocidad o directamente la hora del sistema; por eso el gate DB/monotónico y los eventos del host siguen siendo obligatorios aunque se detuviera W32Time. [Windows Time](https://learn.microsoft.com/en-us/windows-server/networking/windows-time-service/how-the-windows-time-service-works), [derechos de servicios](https://learn.microsoft.com/en-us/windows/win32/services/service-security-and-access-rights).

Procedimiento **preparado, no ejecutado**:

1. Con autorización expresa independiente, registrar service identity, estado estable, start type, fuente/status, PID + creation time del conductor, nonce, manifest de fuentes y duración máxima del probe; guardar un lease de recuperación durable antes de cualquier mutación. Si el estado es transitorio/desconocido, abortar.
2. Preparar un supervisor de restauración independiente con privilegios propios verificados, fuera del job/tree cuya terminación mata al conductor. Debe abrir un handle de identidad/liveness del conductor, leer el lease, confirmar `READY_ACK` y tener un vencimiento monotónico registrado. No basta con arrancar otro hijo susceptible de morir en el mismo job.
3. El supervisor espera la señal de cierre o muerte del proceso identificado. La comparación PID + creation time evita confundir reutilización de PID con un conductor vivo. Ante muerte, interrupción o vencimiento, restaura idempotentemente el estado operativo guardado mediante SCM, verifica el estado estable y escribe un receipt separado. Para cubrir muerte conjunta del conductor y supervisor, antes de detener se necesita además una recuperación con dueño OS, de un solo uso, fuera de ese job y con acceso confirmado. Esa infraestructura aún no está creada ni autorizada; si no puede prepararse de forma temporal y reversible, no se detiene W32Time.
4. Sólo después de verificar los dos caminos de recuperación y sus accesos, permitir la pausa de W32Time, siempre antes de abrir captura/ventanas medidas. Si ya estaba detenido, registrar ese hecho y conservar el estado, sin reclamar que esta acción resolvió el clock.
5. Cerrar primero la medición/captura y sus cortes de host. En camino normal, el conductor solicita restauración y espera el receipt; el supervisor confirma. En error/interrupción, dejar de emitir carga, conservar todos los journals/errores, cerrar la ventana medida y ejecutar el mismo finally de restauración. La muerte inesperada usa el camino independiente del punto 3, sin depender de finally.
6. Verificar servicio/guard restaurados, persistir estado posterior, retirar sólo el supervisor/recovery temporal propio tras confirmar éxito. Si falla restauración, conservar lease/logs, reportar `RECOVERY_FAILED` y no arrancar otro ensayo. Un ajuste ocurrido dentro del ensayo sigue invalidándolo; restaurar fuera del corte no sanea la evidencia previa.

`clock_recovery_protocol.py` es un modelo inactivo de precondiciones y acciones de restauración; se probó offline con estados ficticios para normal, error, interrupción, muerte, timeout, idempotencia y PID reutilizado. **No es un restaurador operativo instalado ni una prueba física de restauración.** Con los permisos actuales, safe-start debe rechazar el probe incluso si luego se aprueba el alcance.

Receta R2-04 intacta: lease **900 s**, **S=L−P** con P del receipt aceptado, pacing original, oferta **360 s**, seguimiento íntegro **240 s**, dos planners y sender. No se mueve S ni se segmenta/reinicia la intersección de clock. El reclaim individual anterior conserva acreditación; una repetición futura sólo cerraría reclaim + oferta concurrente + expiración natural.

## 3. R1-04: tabla temporal y condición que falta

Fuentes: `_extend_quiet_window` actual en `services.py:414`, horizonte nativo del selector y pausas existentes; extracción de fuente con hash en `source-extracts.json`. QUIET_WINDOW=8 s, MAX_WAIT=25 s y H=1 s permanecen intactos. `T=created_at` del primer pending de F +25 s; no se reemplaza por el offset de un calendario.

Para un intervalo X, X−/X+ son sus extremos inferior/superior en clock común. p es el testigo **previo** al poll de yield; y, fin observado del yield; n, DB time nativo de la corrección; c, commit exterior; m, poll real de comprobación de la proyección obsoleta; kF/kW, commits de claim.

| Paso | Relación suficiente sobre intervalos observados | Evidencia causal necesaria / falta actual |
|---|---|---|
| 1. W READY, sin claim | rW+≤p−; rW−≥T+−H; ningún claim de W entre origen y p | Origen por ingress/deadline/commit y journal continuo de ambos planners; no vale consultar después. |
| 2. F futuro dentro de H | p+<d1−; d1+≤p−+H; d1+<T− | Estado/history de A y B, disponibilidad de B y d1 captured antes de la consulta nativa, mismo selection_id. |
| 3. Selección vacía/yield | p+≤y−; selección real `[]`; ausencia de claim_start para esa selección | `selection_result`/fin del yield reales. Esto es yield, **no miss de claim**. |
| 4. Corrección committed | y+<n−≤n+≤c−≤c+<d1− | Emisión ordinaria después del yield; deadline_set/CAS propio y outer commit correlacionado. No hay retención de planners. |
| 5. Forecast viejo obsoleto | n−+8 s≥T+; d2=T; c+<d1−<d2−; d1+≤m−≤m+<T− | Fórmula nativa bajo lock; poll real m con F todavía futuro y d2 dentro de H, witness previo al poll. Una consulta final no prueba este paso. |
| 6. Nueva elegibilidad/claim | d2+≤kF−; kF+≤kW− para esta receta propuesta | READY natural en T, claim exterior de F y luego W; no updates de READY ni calendario como testigo. |
| 7. Origen, edad, obligaciones | mismo rW, miembros y org; kW+−rW−≤120 s | Cohorte completa, límites conservadores y cadena de obligaciones; preparación/correcciones nunca desaparecen. |
| 8. Base y concurrencia | polls de dos planners intersectan la oferta real; todos los slots base y 360/240 completos | Calendario/aceptaciones reales, roles libres y sin holds. Se deben mapear los primeros slots a conversaciones ajenas a W/F. |

La ventana útil antes de la corrección es `d1− − max(rW+, T+−H)`, antes de descontar consulta, emisión del witness, lectura del yield, reacción y commit. Es **estrictamente menor que H=1 s**. El ejemplo antiguo rW≈24 s, d1≈24,5 s, T≈25 s sólo muestra aproximadamente 0,5 s nominales, no un presupuesto acreditado.

La fórmula nativa permite intervalos algebraicos no vacíos cuando n todavía es anterior a d1 y n+8 alcanza T; la corrección queda capped en T en vez de abrir una distancia de ocho segundos. Eso preserva la posibilidad geométrica. Sin embargo, los receipts actuales **no dan cotas superiores** para el tiempo de reacción + commit, ni fases acotadas de ambos planners que aseguren un poll antes de d1 y otro entre d1 y T. Una pausa de 1 s no garantiza un poll en un intervalo menor de 1 s, aun con dos procesos; sus fases pueden coincidir.

Conclusión: **no hay una ventana física completa demostrable con la evidencia disponible**. No se afirma imposibilidad absoluta de que la secuencia suceda; se afirma insuficiencia para prepararla como receta determinista acreditable. `r104_temporal.py` valida sólo restricciones condicionales; sus modelos numéricos son tests del analizador, no replay de carga ni resultados. La rama se detiene en `PENDING_NO_DEMONSTRABLE_PHYSICAL_WINDOW`. No se crean 17 conversaciones, no se cambian pausas/recencia y no se prepara una ejecución automática.

Una siguiente decisión debería resolver cómo observar/acotar esas latencias y fases con infraestructura de evaluación, sin nuevas ofertas de caracterización, holds ni cambios de planner. Un futuro experimento finito para esa observación requeriría autorización específica; no está incluido en esta fase y puede concluir sin receta viable.

## 4. R2-09: ambas variantes separadas

Planes: `r209-uncertain_meta-prepared-plan.json` y `r209-slow_meta-prepared-plan.json`; validación final en `r209-plan-validation-v2.json`. El provider es el archivo de aislamiento existente, referenciado por hash y **sin editar**. Ambos conservan 2×3, tasas aceptadas, dos planners, sender, 360/240, dos llamadas LLM de 0,5 s, dominio 0,1 s y Meta base 0,2 s. `slow_meta` conserva ×2 sólo en Meta objetivo; `uncertain_meta` conserva UNCERTAIN sólo en Meta objetivo. No se añade LLM timeout ni se aumenta multiplicador.

La infraestructura preparada contiene la descripción exacta de fases y gates, no una ejecución acreditada. Cada variante necesita un laboratorio/DB/intento nuevos. La conexión futura al harness debe cambiar sólo la **orquestación de inicio**: el helper histórico arranca planners antes del sender, y no debe reutilizarse sin separar ese orden.

Secuencia inicial preparada: ingress/capture activos; planners ausentes; seis ingresos ordinarios, uno por cada conversación existente; espera del deadline natural sin updates; corte independiente sealed con seis READY sin claim; sender iniciado y su preparación observada; arranque de ambos planners; oferta base original libre y seguimiento completo. La latencia de arranque queda dentro de las edades. Una vez iniciado un planner no se bloquea, retiene ni detiene para producir cola o solapamiento.

Gates de ejecución futura:

| Gate | Evidencia obligatoria |
|---|---|
| READY inicial | Todos los inputs aceptados por ingress, seis orígenes naturales reconstruidos, mismas seis conversaciones; corte anterior a ambos arranques y sin claim. |
| Participantes | PID/creation time y start/ready correlacionados; sender preparado antes del primer planner; dos planners concurrentes; sin holds después del arranque. Un bool del plan no acredita ausencia de hold. |
| Cohortes y pacing | Ledger `INITIAL_READY` separado de `ORDINARY`, pero ambos en censo/edad/obligaciones. Cada aceptación base se cruza con el calendario real; no exigir automáticamente inputs=episodios. |
| Provider/servicio | Dispatch/result por call_id; Meta por message_id/outbox/admisión; fault_id exacto `call_id:uncertain-meta`, org objetivo y frontera Meta; cada claim conserva sus dos testigos LLM y autoridad. |
| Solapamiento | Para un waiter y una llamada afectada: `[max(ready+, dispatch+, oferta_inicio+), min(claim−, result−, oferta_fin−))` no vacío. Debe reconstruirse en clock común. Una intersección meramente posible no pasa. |
| Peer | Oferta/aceptaciones de la otra org y avance físico ordinario durante la ventana del escenario, correlacionado con epochs/claims y servicio; no basta un contador final. |
| Autoridad | Testigos nativos de claim/admisión/completion y sender/outbox, más gates originales de fencing/ownership/tenant. La inyección Meta no debe renovar ni bloquear autoridad de planner ni producir `CLAIMED_WORK_WITHOUT_SERVICE_WITNESS`. |
| No retry ciego | Un dispatch afectado por outbound en esta fixture; inventario y transiciones outbox exhaustivos. Reintentos no autorizados o calls huérfanas fallan. |
| Obligaciones/drain | Toda la cohorte initial+base representada, works y llamadas conciliados, cadenas diferidas demostrables. Outbounds inciertos conservan disposición **incierta**, nunca accepted ni obligación entregada por inferencia; deben quedar explicados según el gate existente de la variante. |
| Clock/integridad | Todos los journals/calibraciones/cortes de host válidos, fuentes originales y base por hash, final íntegro y cleanup. |

`r209_preparation.py` implementa gates suplementarios de plan, cohorte inicial, correlación/aislamiento y solapamiento definido. Los gates originales de peer, autoridad, clocks, reglas de variante y obligaciones completas siguen siendo obligatorios; los suplementos **no son un reemplazo del verificador completo de ejecución**. Los controles offline rechazan sender tardío, claim previo al corte, hold, población ampliada, multiplicador mayor, solapamiento posible o fuera de oferta, outbox no correlacionado, timeout LLM, fault_id ajeno, falta de testigo y retry ciego.

Seis READY iniciales no garantizan intersección física con Meta. Si falta, conservar `NOT_ACCREDITED / PENDING_NATURAL_OVERLAP`, todos los intentos y la incertidumbre. No aumentar backlog, no cambiar provider y no repetir automáticamente. Las dos autorizaciones futuras deben ser independientes.

## 5. OOM y regresión secuencial

El log PostgreSQL preservado identifica el backend **PID 102336**, el 8 de octubre a las **00:42:50.343 CST**, con `out of memory` y petición de **48 bytes** en `MessageContext`. El log sender registra el error psycopg/Django y la cascada operacional posterior. `host-diagnostic.json` conserva paths, hashes, líneas relevantes y hash del statement asociado sin divulgar SQL/payloads. `regression-native-stop-receipt.json` preserva los procesos de regresión detenidos y su cleanup anterior; no se volvió a intervenirlos.

Recursos **actuales**, a la hora del diagnóstico: aproximadamente **15,86 GiB** de RAM física, **6,21 GiB** disponibles; límite de commit reportado por Windows aproximadamente **21,78 GiB**, **8,98 GiB** disponibles. Los valores exactos, working sets/private usage de procesos accesibles, errores de acceso y límites del job actual están en el receipt. Esos datos **no reconstruyen la memoria al momento del OOM** ni son umbrales nuevos de aceptación.

La tabla TCP IPv4 actual muestra un listener PostgreSQL en 5432; no se consultó ni modificó esa DB. No hay listener en los puertos privados históricos 55969/60036. Los clusters privados anteriores fueron removidos, por lo que no existe un `pg_stat_activity` histórico recuperable ni límites del backend fallido. Se registra esta ausencia, no se inventa un censo de conexiones del fallo. Tampoco se declara memoria ilimitada cuando una consulta de límites no es accesible.

Diagnóstico: **ROOT_CAUSE_UNDETERMINED**. Se sabe dónde falló la asignación; no se sabe si el origen fue presión de commit del host, límite de proceso/job, cantidad de conexiones, acumulación local de un backend u otra causa. Ninguna de esas hipótesis se atribuye al runtime ni se da por resuelta. No se modificó PostgreSQL, memoria, tests o configuración de producción.

`regression-sequential-plan.json` prepara, en este orden, `test_b4_sender`, `test_w1_monotonic`, `test_b5_safety`, `test_operation_execution`, `test_b9b_budget`, `test_b9c_concurrency`, `test_b9c_processes`. Una suite por vez, una DB privada nueva por suite, baseline/template y durabilidad originales, mismos tests y script existente de suite individual. El runner antiguo de dos procesos no se usa. Cada comando/entorno de suite queda descrito con los paths privados aún por asignar; no se han asignado ni creado DBs.

Antes de cada suite: recursos/límites actuales, identidades de procesos, ausencia de cargas físicas concurrentes, configuración privada, censo `pg_stat_activity` y watermark de log. Durante: timeline de recursos, conexiones y procesos propios. Después: receipt completo de tests/errores/skips/exit, recursos/logs, ausencia de hijos, archivo de evidencia y cleanup de la DB propia antes de la siguiente. Si reaparece OOM, detener inmediatamente la secuencia, conservar estado y logs **antes** del cleanup controlado y pedir la siguiente decisión con esa evidencia; sin restart/tuning automático. El monitor y bridge al nuevo laboratorio necesitan habilitarse en una fase autorizada, no se ejecutaron aquí.

D29 78 tests distintos y B3 39 tests conservan su evidencia existente. Los 69 controles nuevos son de **infraestructura offline**, no equivalen a esas regresiones ni ejecutan las siete suites pendientes.

## 6. Cambios exactos e integridad

Todos los archivos nuevos están exclusivamente en `docs/evals/d29-offline-preparation-2026-10-09/`. Se añaden verificador R1-06, controles, modelos de reloj/intervalos, planes/gates R2-09, diagnóstico read-only, plan de regresión, utilidades de extracción/sellado y receipts de esta fase. `artifact-index.json` enumera el inventario completo con hashes y `final-phase-receipt.json` resume la entrega.

La propuesta del 9 de octubre, todos los receipts anteriores, los intentos fallidos, runtime, tests de aplicación y contratos quedan sin editar. Los seals offline iniciales se retienen; los archivos `-v2` son la preparación final después de endurecer el verificador, no sobrescrituras de receipts. Los checks anteriores se conservan; el resultado final es `preparation-tests-attempt-03.json`.

`final-integrity.json` comprueba HEAD, base, 3.409 fuentes protegidas y los índices de evidencia previos disponibles. La base sigue exactamente 2×3 y conserva configuración, población, pacing, servicio, concurrencia, clock y ventanas del receipt. El backlog 2×4 sigue siendo exclusivamente fixture de escenario R1-06; los seis READY de R2-09 son condición inicial de escenario, **no nueva base**. No se genera CONFIRMED_BASE, E, máximo ni capacidad comercial. Commits realizados: **0**.

## 7. Qué podría autorizarse después

| Alcance separado | Preparación que existe | Pendiente obligatorio antes/durante el arranque |
|---|---|---|
| R1-06 prospectivo | Verificador y controles aprobables; esquema causal sealed. | Instrumentar pasivamente los tres testigos en harness privado, sellar nuevo job, garantizar corte/seguimiento completo y autorización del probe. Ante testigo ausente, NOT_ACCREDITED. |
| R2-09 `uncertain_meta` | Plan y gates offline preparados. | Autorización propia; conectar orden de inicio y capturas al harness, DB nueva y gates completos. No garantía de overlap. |
| R2-09 `slow_meta` | Plan separado, ×2 intacto. | Autorización propia distinta; otra DB/intento, mismos controles y ninguna ampliación si falta overlap. |
| Siete suites secuenciales | Plan/diagnóstico entregados, tests/script intactos. | Autorización de ejecución y laboratorio privado/monitor, preflight real de recursos/conexiones. Parar y conservar ante OOM. |
| W32Time + R2-04 | Procedimiento y modelo offline. | **No ejecutable en el entorno actual**: permisos denegados, recuperación independiente no instalada/verificada y falta autorización expresa de control host/probe. |
| R1-04 | Análisis temporal completo. | **Sigue pendiente**: demostrar cotas/fases físicas para ventana <1 s. Decidir si se autoriza una investigación finita de observación; no modificar planner ni ofrecer un PASS nominal. |
| Matriz de 17 | Sin nueva preparación de ejecución conjunta. | No autorizada. No se deduce una autorización de matriz a partir de aceptar estas preparaciones. |

No se repiten ahora R1-03, R2-02 ni los ocho adaptadores finitos aceptados. El reclaim individual R2-04 permanece acreditado. R1-06, composición R2-04, R1-04 y ambas condiciones R2-09 son las brechas que requieren evidencia nueva. Ningún resultado de esta entrega declara `FULL_CONTROLLER_ACCREDITED` ni habilita automáticamente una fase posterior.
