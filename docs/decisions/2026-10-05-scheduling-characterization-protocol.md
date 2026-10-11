# SaaSLyVet — D29: protocolo de caracterización de scheduling

Versión: **D29-v1**, 2026-10-05. Estado: **SPECIFIED / NOT EXECUTED**.
Contrato de referencia: [borrador técnico](2026-10-05-scheduling-bounded-wait-contract-draftmd).
Baseline: `825db75df68bf076929fa787e77beefe96803350`.
Plan estructurado: [manifiesto D29-v1](2026-10-05-scheduling-characterization-protocol.json).

Este encargo cierra la especificación de seguimiento, incertidumbre, ventanas, escenarios y disposición de resultados de D29. No congela el contrato comercial ni define E. Los parámetros ya aprobados se conservan; los valores operativos añadidos son propuestas iniciales adaptativas, identificadas en §7. La ejecución del barrido y los cambios de código siguen fuera de este encargo.

**Estado de preparación:** especificación completa para construir/verificar el conductor; **MEASUREMENT_DRIVER_REQUIRED** para iniciar el barrido. El manifiesto no es un programa ejecutor. La inspección encontró que el ejecutor histórico usa tres organizaciones/tasas fijas y calcula persistencia→`claimed_at`, con gates históricos. El helper del preflight captura un claim directo. Ninguno, por sí solo, ejecuta D29-v1 con cohortes completas, carga adaptativa y frontera exterior committed. No se ofrece un comando de carga que aparente cumplir estos requisitos.

## 1. Alcance y entorno

La caracterización será prospectiva, aislada, con datos sintéticos y copia del baseline. Cada corrida identifica versión del protocolo, fuente, conductor, fixtures, topología, provider simulado, plan de oferta, fallos y condiciones iniciales. La referencia experimental conserva dos planners, un sender separado, batch 1 y pausa de 1 s entre ciclos, como el harness existente; se registran explícitamente y no se extrapolan a otras topologías. N=1, debounce, caps, leases, attempts, backoffs, budgets, guards y comportamiento del selector conservan el baseline.

La primera ronda usa conversaciones ordinarias y READ público de coste controlado. El provider simulado de referencia conserva el fixture existente: dos llamadas LLM de 500 ms, HTTP de dominio de 100 ms y Meta de 200 ms. Son condiciones de laboratorio, no límites de servicio. READ personal, WRITE y costes distintos no quedan cubiertos por esta referencia; su caracterización requiere un plan separado con los guards y grants que correspondan. No se activan clínicas ni efectos de producción.

Toda captura comienza antes del primer inbound y del backlog del fixture. Todos los participantes deben estar listos antes de iniciar la oferta ordinaria, salvo la pausa de arranque deliberada del caso de backlog. Los intervalos de arranque reales, si afectan un episodio ya durable, permanecen en su edad. No se elimina una cohorte de calentamiento para mejorar las muestras.

Antes de ejecutar: comprobar baseline/hash, ausencia de modificaciones de fuentes, base nueva `test_*` en PostgreSQL local, destinos externos contenidos por el harness, configuración transitoria y salida nueva que no sobrescriba recibos. La autorización de preflight anterior no autoriza este barrido. El entorno temporal anterior fue cerrado; una futura ejecución deberá recrearlo y validarlo.

## 2. Cohorte completa y unidad de observación

El registro de entrada nace de **todas las ofertas y aceptaciones**, no de una lista de claims. Cada intento de inbound tiene resultado durable confirmado, duplicado técnico confirmado, rechazo confirmado o resultado incierto. HTTP aceptado sin evidencia durable suficiente queda incierto. Se concilian los intentos del generador, los commits de ingreso y el estado durable; no se descartan errores ni inputs sin claim.

La unidad temporal es el episodio ordinario READY continuo de una organización y conversación. Su identidad de recibo incorpora run, org, conversación, primer inbound durable de ese conjunto y ordinal del episodio. Es una identidad de análisis, no una tabla/campo ni autoridad runtime nuevos. Varios mensajes antes del corte pertenecen a un episodio; su edad no se reinicia. Un inbound postclaim abre una obligación posterior W2, agrupable hasta su propio corte. Retry/reclaim del work anterior no cierran W2 ni constituyen un episodio nuevo para los mismos miembros.

El registro mantiene también obligaciones que aún no son READY. El episodio empieza en la primera elegibilidad sobre estado committed: deadline que vence después del commit de ingreso, o commit que hace visible un conjunto ya elegible. Debe reconstruirse el historial de deadlines y commits efectivos. Un timestamp final de fila, `created_at`, primer poll o `claimed_at` actual no bastan.

Cada episodio conserva, como mínimo:

| Información | Contenido verificable |
| --- | --- |
| Identidad y población | Run, org, conversación, episodio, clase, IDs de miembros y relación con W1/W2. |
| Origen | Transacciones de ingreso resueltas, historial de deadline y límites inferior/superior de `t_ready`; fuente y motivo de incertidumbre. |
| Continuidad | Cambios durables que mantienen o alteran READY, asignación, interrupción/ownership y condiciones del fixture. Cupo ocupado, misses y ausencia de planner no reinician la edad. |
| Fin | Claim nuevo, membership, work/epoch, resolución de transacción exterior y límites de commit. Selección, intento y savepoint son fases distintas. |
| Pendientes | Estado a cada corte, edad mínima/máxima demostrable, último hecho observado y siguiente deadline conocido. |
| Recovery | Work, intento, retry-due/expiry, nuevo token mediante fingerprint, miembros y presupuesto; cohorte distinta de primer claim. |
| Disposición | Servido, pendiente, interrumpido, fuera de condiciones experimentales o indeterminado, con evidencia y criterio previo. |

Los IDs de recibo sirven para correlación; no son labels de métricas operativas. Se excluyen texto de mensajes, prompts, respuestas, teléfonos, contenido clínico, secretos, tokens crudos y SQL/params crudos.

**Conservación:** toda aceptación ordinaria durable debe estar asociada a un episodio/obligación registrada, incluso si termina interrumpida o sin claim. Cada claim contado debe pertenecer a un episodio registrado y a su organización. Ningún episodio se cuenta dos veces por tener varios mensajes o ser recuperado. Una obligación cuyo primer READY todavía no se conoce permanece en el inventario como origen indeterminado; no desaparece del denominador.

La captura de ingreso y claims debe cubrir todos los procesos/conexiones participantes. Los cortes de estado durable concilian asignados, sin asignar, pendientes, completados e interrumpidos. El muestreo de snapshots por sí solo no prueba que no hubo un episodio entre muestras; si falta una transición necesaria, se conserva una incertidumbre, no una historia inventada. Los episodios previos a la captura no empiezan de nuevo: se conserva su origen conocido o una cota/estado desconocido.

## 3. Regla completa de incertidumbre temporal

Se representará `t_ready ∈ [r_lo, r_hi]` y `t_claim_commit ∈ [c_lo, c_hi]`. Una frontera desconocida conserva su extremo abierto; no recibe la hora del primer observador. Bajo orden causal consistente, `W_lo = max(0, c_lo − r_hi)` y `W_hi = c_hi − r_lo`. Un intervalo imposible, invertido o sin correlación válida produce evidencia inválida.

Los brackets de COMMIT exitoso incluyen el intervalo de ejecución del driver, calibrado contra el reloj DB; el ACK no se usa como instante exacto del servidor. Una transacción exterior envolvente desplaza la frontera a su propio commit. Savepoint y callback no son commits exteriores. Ante ACK perdido/error no se presume rollback ni se usa el final del error como cota superior: hace falta resolver el resultado durable y acotar la visibilidad. Si eso no alcanza, el fin queda indeterminado. La ausencia momentánea de un row tampoco prueba rollback de una transacción aún no resuelta.

Cada segmento temporal conserva calibraciones, límites y supuestos de reloj. Relojes de hosts distintos no se restan sin correlación demostrada. Saltos observados o contradicciones DB/monotónico invalidan la relación afectada y se reportan; no se reinicia la edad. Si el supuesto de reloj necesario no puede sostenerse, esa muestra no acredita cumplimiento.

No se añade otro número de SLA ni una tolerancia que amplíe los dos minutos. **Precisión suficiente significa que el intervalo permite decidir la relación con 120 s**:

| Evidencia | Disposición de la muestra |
| --- | --- |
| Claim exterior confirmado, continuidad acreditada y `W_hi <= 120 s` | Dentro del objetivo observado para esa muestra. |
| `W_lo > 120 s`, con claim o todavía pendiente | Exceso observado. El claim tardío no borra el exceso. |
| El intervalo cruza 120 s o falta una frontera/continuidad decisiva | Indeterminado; no es éxito. |
| Sin claim y todavía no hay exceso demostrable | Pendiente/censurado; no es éxito aunque su edad superior sea pequeña. |
| Datos incompletos, secuencia rota, transacción/clock contradictorios | Evidencia inválida; no es éxito. |

Ejemplos ilustrativos: `[119.6,119.9] s` permite decidir dentro; `[120.1,120.4] s` permite decidir exceso; `[119.8,120.2] s` queda indeterminado. Son ejemplos de la regla, no resultados de carga ni nuevos umbrales.

Para un pendiente al corte `q ∈ [q_lo,q_hi]`, la edad mínima es `max(0,q_lo−r_hi)` y la máxima es `q_hi−r_lo`. Si la mínima supera 120 s se registra el exceso aunque nunca haya claim. Si no puede decidirse, se conserva pendiente/indeterminado. La evaluación organizativa usa intervalos y claims ordinarios nuevos de la misma org; safety/retry/reclaim se contabilizan aparte.

## 4. Ventanas, seguimiento y backlog

Toda corrida tiene ventana de oferta `[inicio,fin)`, cortes alineados, inventario inicial y seguimiento posterior. Sus participantes y clocks están identificados antes del comienzo. Se incluyen todos los episodios nacidos durante la oferta y el backlog declarado; los miembros posteriores a un corte de W1 se asocian a W2. El seguimiento no sigue generando oferta ordinaria nueva. Se conservan cambios causados por servicio, safety o fallos.

El filtro de nivel dura **6 minutos**, dividido en tres ventanas de **2 minutos**. La confirmación dura **15 minutos**: siete ventanas completas de 2 minutos y un resto final de 1 minuto que se conserva en la evidencia. Esas duraciones son parámetros de prueba ya aprobados, no prueba de sostenibilidad universal.

`Q_org(t)` cuenta episodios ordinarios READY aún sin claim nuevo committed; no cuenta simplemente todos los Message PENDING, porque los asignados a un work pueden seguir PENDING. Se reportan además obligaciones todavía no READY, trabajos en servicio, recuperación y mensajes, todos por org y globalmente.

Regla inicial de backlog:

1. Tres ventanas completas consecutivas con aumento neto de Q constituyen crecimiento observado; un promedio global no compensa el crecimiento de una organización.
2. Sin ese patrón, si Q al cierre es mayor que Q al inicio, la tendencia queda indeterminada y el nivel no se marca compatible. Se propone otra corrida con ventana mayor, declarada de antemano.
3. Q final no mayor que Q inicial y ausencia del patrón anterior permiten describir «sin crecimiento observado en esta ventana». No prueban estabilidad a plazo ilimitado.
4. Si los cortes de Q están acotados por intervalos, solo se afirma aumento cuando el mínimo final supera el máximo inicial. Solapamiento que impide decidir la tendencia produce indeterminado.

Los episodios pendientes al fin se siguen hasta claim resuelto o exceso demostrable; el resto se conserva censurado. El horizonte operativo inicial de cierre es `fin de oferta + 2×B_conv` (4 minutos), ajustable prospectivamente. Si al llegar a ese corte aún hay obligaciones con READY futuro/desconocido, commit incierto o clocks no resolubles, la corrida queda indeterminada, nunca compatible. Este corte limita el ensayo; no concede cuatro minutos de espera ni sustituye el bound de dos minutos.

Recovery se observa hasta el desenlace o el corte declarado del caso, que no puede anticiparse a su frontera de retry/lease si se pretende evaluar esa recuperación. Las leases/backoffs vigentes no se reducen para acelerar pruebas. Si una recuperación permanece sin resolución al corte, se reporta censurada y no se certifica un bound de recovery.

## 5. Secuencia de oferta y disposición de cada nivel

Antes del barrido, calibración con un episodio nuevo a la vez por org: esperar su claim antes de ofrecer el siguiente. El primer conjunto contiene **10 episodios por org** como propuesta operativa inicial. Para cada org se registra `R_ref = 60 × episodios READY servidos / duración desde su primer READY hasta el último claim`, junto con mensajes, coste, pendientes e incertidumbre. Es una referencia del fixture y del pacing con debounce natural; no es capacidad máxima. Una calibración con exceso o evidencia indeterminada no acredita una referencia compatible.

El barrido parte de **50% de la referencia observada**, incrementa oferta **50% por nivel**, y refina por puntos medios tras la primera incompatibilidad hasta un intervalo relativo no mayor que **25% del último compatible**. Se reportan tasa planificada, oferta efectivamente emitida, ingresos committed y episodios que realmente alcanzaron READY por org/globalmente. No se fuerza READY ni se alteran deadlines para cumplir la tasa nominal. La desviación del generador impide atribuir un resultado a una carga que no llegó a ofrecerse.

El presupuesto inicial propuesto es **8 niveles por serie**. Si todos resultan compatibles y no aparece frontera, se informa «frontera no localizada»; no se declara que el mayor nivel sea una capacidad máxima. Extender o refinar requiere un plan de corrida posterior registrado, sin cambiar el recibo ya producido.

El mayor nivel compatible se confirma durante 15 minutos **tres veces**, con estado inicial y salida nuevos en cada repetición. Si alguna repetición resulta incompatible, no se promedian los resultados para salvar ese nivel: se baja al siguiente candidato inferior y se confirma en nuevas corridas. Si alguna es indeterminada, la candidatura no queda confirmada; primero se resuelve la causa y se repite con un plan nuevo.

Un nivel se marca **OBSERVED_COMPATIBLE** únicamente cuando:

- La cohorte está conciliada y todos sus episodios ordinarios evaluables tienen claim y cota superior de espera dentro de dos minutos.
- No quedan pendientes, censurados, interrupciones sin regla aplicable o indeterminados que impidan evaluar esa cohorte.
- No se observa crecimiento de backlog según §4 y su tendencia puede decidirse por org y globalmente.
- El coste/servicio y carga reales corresponden al plan declarado; los invariantes aplicables se mantienen y la evidencia es íntegra.

Cualquier exceso demostrado produce **OBSERVED_INCOMPATIBLE_WITH_TARGET**. Crecimiento de Q produce **OBSERVED_BACKLOG_GROWTH**. Evidencia o tendencia insuficientes producen **INDETERMINATE**. Una violación de invariantes detiene la serie con **INVARIANT_FAILURE**. Incumplimiento del plan de oferta o preparación produce **INVALID_RUN**. Estos rótulos caracterizan observaciones; no convierten E no definida en una exención ni certifican el contrato comercial.

## 6. Matriz de ejecución especificada

La carga principal usa conversaciones distintas para producir episodios nuevos; las agrupaciones y continuaciones se prueban aparte. Propuesta inicial: **3 conversaciones por org**, rotadas con identidad causal preservada; si la tasa pretendida necesita más conversaciones, el plan siguiente declara el cambio. El conductor debe informar demanda insuficiente y coalescing; no sustituir episodios por número de mensajes.

| ID | Escenario y condición de ejecución | Correspondencia / evidencia principal |
| --- | --- | --- |
| R1-01 | Una org y varias conversaciones: calibración, barrido y confirmación. | A01/A05/A06/A07/A10; espera individual, pendientes y ocupación propia. |
| R1-02 | Dos orgs equilibradas; misma oferta por org dentro de un plan global declarado. | A02/A08/A10/A23; claims por tenant y competencia real entre planners. |
| R1-03 | Dos orgs con oferta 2:1; conservar tasa global para comparar con R1-02. | A03/A10/A23; evaluar también la org ruidosa, sin excluirla del denominador. |
| R1-04 | Demanda READY y llegadas de otras orgs que generan elegibilidad futura repetida. | A04/A05/A07; preservar edad durante forecasts y misses. No afirmar causalidad del selector si la captura no la distingue. |
| R1-05 | Ráfaga 2× tasa confirmada por 2 min, primero simultánea y luego concentrada en una org; retorno al nivel base y seguimiento. | A09; tamaño real, backlog, edades y drenaje. Es condición exploratoria, no E_burst aprobada. |
| R1-06 | Backlog antes del arranque: cantidad inicial por org `ceil(R_base_org × 2 min)`, edad reconstruida desde ingreso capturado; arrancar workers sin reset. | A06/A09/A10/A18 y entrada/reentrada; no prometer bound para un backlog comercial aún no aprobado. |
| R1-07 | Corrección después de READY y antes del claim; nuevos inbounds durante W1 no terminal; agrupación de W2 y duplicado técnico. | Fronteras W1/W2/READY; membership y episodios distintos. Legado NULL se declara como caso de frontera separado, no para acelerar el barrido. |
| R2-01 | Servicio lento de una org: 2× duración del fixture normal, con carga base confirmada. | A12/A06; colas por org/global y coste real. No presume fallo cubierto por E. |
| R2-02 | Una llamada LLM retenida tras admisión durante 2 min y luego liberada; otras orgs mantienen oferta base. | A13/A05; autoridad, proceso ocupado y progreso de las demás. El bloqueo de 2 min es una condición experimental, no un presupuesto de fallo aprobado. |
| R2-03 | Crash antes del commit exterior del claim; ingreso previo ya durable. | A14/A08; rollback/resultado incierto resuelto, misma edad y siguiente claim real. |
| R2-04 | Crash después del commit; esperar expiry natural y observar reclaim con la carga base. | A15/A16; mismo work/membership, fencing y budget. Recovery separado de O-C. |
| R2-05 | Error recuperable de provider y retry natural; rama de agotamiento de attempts. | A17; next_attempt_at, backoff, consumos y desenlace, sin reset de W2. |
| R2-06 | Restart con pendientes y work en curso, preservando journals e inventario inicial/final. | A18; edad, lease, epoch y clocks antes/después. |
| R2-07 | Contención DB/locks y rollback exterior/savepoint; variante de ACK perdido. Condiciones de liberación y cierre descritas debajo de la matriz. | A07/A08/A14/A15; resultado durable y brackets. Se conserva el tiempo efectivo; nunca se descuenta después por observar latencia alta. |
| R2-08 | Safety y takeover antes/después del claim, con y sin W1 no terminal. | A19/A21; precedencia, interrupciones descriptivas y witnesses stale. No inventar excepciones comerciales ni SLA clínico. |
| R2-09 | Sender concurrente con aceptación incierta o Meta lento mientras hay cola ordinaria. | A20; autoridad independiente, outbox y ausencia de retry ciego. Dispatch/entrega no se convierten en O-C. |
| R2-10 | Consentimiento/autoridad expirados, referencias cross-tenant y gates cerrados. | A22/A23; denegación segura y scopes. Ninguna condición de carga autoriza WRITE. |

A11 (fuera de E) no puede aceptarse comercialmente antes de definir E y la política correspondiente. Una tasa superior a la compatible observada se etiqueta «por encima del rango observado», sin declararla retrospectivamente fuera de contrato. A12–A18 aportan observaciones de fallo/recovery; su inclusión en los dos minutos y cualquier bound de recovery siguen siendo decisiones de producto posteriores.

Cada caso de la segunda ronda fija, antes de iniciar: frontera de inyección, proceso/tenant afectado, duración o condición de liberación, carga concurrente y corte de observación. Su resultado nunca recibe PASS contractual mientras no esté aprobada esa cobertura.

R2-07 se divide en variantes con condiciones observables: lock de organización/conversación retenido hasta el primer miss acreditado y luego liberado; lock de Message retenido hasta acreditar espera real de la transacción y luego liberado; rollback después de preparar membership pero antes del commit exterior; rollback de savepoint distinguiendo el desenlace de la transacción exterior; y ACK perdido resuelto desde otra conexión mediante evidencia durable y límites de visibilidad. El límite inicial para esperar el evento de liberación es B_conv; si no aparece, se libera el fixture y se marca la variante indeterminada. Ese límite contiene el ensayo y no es un timeout runtime. Se registra la duración real desde adquisición/inyección hasta liberación, incluida en la edad del episodio. El conductor debe acreditar cada frontera; una inyección aproximada no cuenta como el caso pretendido.

## 7. Parámetros y cambios prospectivos

| Parámetro | Valor inicial / estado |
| --- | --- |
| Objetivo por conversación | 120 s; aprobado por producto. Cambiarlo requiere otra decisión explícita de producto. |
| Inicio e incremento de oferta | 50% de calibración; ×1.5 por nivel; aprobados, adaptativos entre corridas. |
| Refinamiento | Puntos medios; intervalo relativo <=25% del último compatible; aprobado, adaptativo. |
| Filtro/confirmación/repeticiones | 360 s / 900 s / 3; aprobados como prueba, adaptativos. |
| Ráfaga / desequilibrio | ×2 por 120 s / razón 2:1; aprobados como prueba, adaptativos. |
| Cohorte completa y comparación por intervalos | Especificadas aquí como desarrollo del método aprobado; no añaden un SLA. |
| Cortes de backlog | Ventanas de B_conv; tres aumentos consecutivos o tendencia indeterminada según §4; regla operativa propuesta. |
| Calibración / conversaciones / máximo de niveles | 10 episodios por org / 3 conversaciones por org / 8 niveles por serie; propuestas operativas iniciales, adaptativas. |
| Seguimiento ordinario máximo | 2×B_conv después de fin de oferta; propuesta operativa de cierre, adaptativa; pendientes no pasan. |
| Lentitud/bloqueo exploratorios | ×2 del fixture / 120 s; propuestas experimentales; no cobertura de fallos aprobada. |

Cada corrida sella sus parámetros, cobertura, criterio de interpretación, conductor/hash y salida antes de la primera oferta. Una modificación por resultados produce otra versión/plan y nuevos run IDs, con motivo y evidencia. No se cambian los parámetros, cohortes ni rótulos originales de corridas anteriores. Si se quiere otro análisis de una evidencia anterior, se identifica como análisis nuevo, conservando intacto el recibo original y sin usarlo como repetición de un plan distinto.

La adaptación de números de prueba no determina un scheduler nuevo ni cambia automáticamente el objetivo de producto, E, contrato, flags o release. La propuesta final de E debe citar escenarios, condiciones reales, fallos, incertidumbres y rango compatible confirmado; no convertir el mayor throughput observado en garantía universal. O-BS y sostenibilidad requieren además un argumento bajo los supuestos propuestos, separado del ensayo finito.

## 8. Requisitos del conductor y orden operativo

El conductor necesita ejecutar la oferta configurable, preservar capturas completas de todos los participantes, conciliar el registro de episodios/pendientes y resolver las fronteras con §3. Es capacidad de prueba; no un mecanismo de scheduling. **Su adaptación no se implementa en este encargo**, que conserva la restricción de no cambiar código. La existencia del manifiesto no acredita esa capacidad.

Orden especificado para una futura ejecución:

1. Sellar plan, defaults operativos aceptados, fuentes, fixtures y salida; comprobar permiso de ejecución y aislamiento.
2. Preparar el esquema existente en base nueva y arrancar los participantes con captures antes de ofrecer inputs.
3. Ejecutar comprobación mínima de cohortes: incluir un episodio deliberadamente pendiente al corte, W1/W2, duplicado, rollback y resolución de commit. Acreditar que no se pierde población al cerrar ni que se confunde primer poll con READY.
4. Si la evidencia no soporta una frontera/cohorte del caso, detener esa rama con su límite. No suplirla con el gate histórico ni un snapshot final.
5. Ejecutar calibración y primera ronda por casos/versiones declarados; clasificar filtros y confirmar candidatos según §5.
6. Ejecutar segunda ronda sobre carga base observada, con fallos ya declarados y recuperación natural. Reportar cobertura contractual todavía pendiente por separado.
7. Cerrar la oferta y observar cada obligación hasta resolución o corte; conciliar pendientes, censurados y transacciones inciertas.
8. Emitir recibos por org/global, verificar invariantes y conservar datos/hash del plan; parar participantes y DB temporal, retirar credenciales y verificar fuentes/E4 íntegros.
9. Entregar aproximaciones y propuesta de E para decisión de producto. No tunear, implementar, activar o desplegar como consecuencia automática.

Cada recibo contiene plan/hash, clocks/brackets, entradas/episodios, claims/membership, colas/cortes, recovery, errores/indeterminados, invariantes y limpieza. Estadísticas de episodios con claim se etiquetan como condicionadas a tener claim y acompañadas de la población completa/pendientes; no sustituyen la comparación individual. No se aprueba un porcentaje de éxito ni un percentil nuevo.

## 9. Puertas y decisiones que permanecen

| Puerta | Estado al emitir D29-v1 |
| --- | --- |
| Cohortes, incertidumbre, ventanas, disposición y matriz de caracterización | Especificadas en este documento. |
| Defaults operativos añadidos en §7 | Propuesta consolidada, ajustable prospectivamente; no aprobaciones comerciales implícitas. |
| Conductor D29-v1 con población completa y fronteras requeridas | `MEASUREMENT_DRIVER_REQUIRED`; no existe un entrypoint verificado para la matriz completa. |
| Captura mínima nueva que acredita el conductor | No ejecutada. El preflight reducido anterior conserva `PREFLIGHT_PARTIAL`. |
| Autorización de barrido/benchmarks | No otorgada por este encargo documental. |
| E, cobertura temporal contractual/fallos, recovery, fuera de E y propiedad/release | Conservan sus decisiones pendientes en el contrato. |

La definición de D29 queda concentrada aquí: no hace falta escoger una tolerancia de reloj o un porcentaje de indeterminados para poder especificarla. Indeterminados impiden un rótulo compatible. Antes de cargar el sistema deben existir el conductor, su acreditación mínima y el encargo de ejecución. Aprobar esta definición tampoco certifica factibilidad, cierra el contrato técnico ni cambia E4.
