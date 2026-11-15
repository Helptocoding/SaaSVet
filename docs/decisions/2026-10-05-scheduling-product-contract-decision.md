# SaaSLyVet — decisión de producto sobre garantías de scheduling

Fecha: **2026-10-05**. Estado: **PROPUESTA DE DECISIÓN / CONTRATO NUEVO NO APROBADO**.

Baseline/HEAD: `825db75df68bf076929fa787e77beefe96803350`. Rama: `codex/e4-capacity-scheduling`.

Este documento decide qué garantía convendría definir antes de una futura implementación. No enmienda los contratos vigentes, no aprueba un SLA, no autoriza código ni tuning y no reabre E4. Su recomendación es **B: crear un contrato explícito de progreso y espera acotados, condicionado a una envolvente de operación sostenible**. Sus parámetros y su aprobación quedan pendientes.

## 1. Base de la decisión y separación de E4

Se utilizan exclusivamente contratos y evidencia existentes del proyecto:

| Ref. | Fuente | Qué fundamenta |
| --- | --- | --- |
| C1 | [Contrato B9C](../contrato-concurrencia-b9c.md) (l. 33) | Cupo organizativo, claim, locks, recuperación y alcance limitado de SCALE. |
| C2 | [Elegibilidad B3/C4/W1 v1](../contrato-elegibilidad-preclaim-b3-c4-w1-v1.md) (l. 18) | READY monotónico derivado de PostgreSQL; elegibilidad distinta de autoridad y de SLA. |
| C3 | [Contrato B9D](../contrato-beta-release-b9d.md) (l. 33) | Alcance/tasa del piloto, cobertura humana, gates y aprobación por organización/capacidad. |
| C4 | [Contrato B8A](../contrato-execution-guard-b8amd) (l. 13) | Witness, fencing, tenant, consentimiento, TTL y autoridad antes de efectos. |
| C5 | [Contrato B5](../contrato-safety-handoff-b5md) | Safety/handoff independientes; orientación sin prometer atención, disponibilidad ni SLA clínico. |
| P1 | [Plan canónico, principios](../plan-implementacion-auditoria-agente-whatsapp-2026-09md) (l. 13), [B9](../plan-implementacion-auditoria-agente-whatsapp-2026-09md) (l. 710) | Beta acotada, servicio multi-tenant, latencia de activación medida y ampliación por alcance/tasa aprobados. |
| E1 | [Cierre formal de E4](../evals/e4-preclaim-scheduling-2026-10-04/report.md) | Capacidad, tiempos preclaim y límites de la evidencia causal del HEAD posterior. |
| E2 | [Estado congelado](../evals/e4-preclaim-scheduling-2026-10-04/closure.json) y [manifiesto](../evals/e4-preclaim-scheduling-2026-10-04/manifest.sha256.json) | E4 cerrado; no violación contractual demostrada; integridad del expediente. |
| H1 | [Recibo histórico PROFILE/B9E](../evals/profile-beta-1-e4-2026-10-01/final.json) | FAIL histórico separado del diagnóstico posterior. |

E4 queda `CLOSED / CAPACITY_LIMIT_CONFIRMED / STOP_BEFORE_TUNING`. El análisis posterior verificó que, con N=1, los providers controlados requieren al menos 1,1 s de servicio secuencial por turno frente a la entrada ruidosa de un turno/s. Esa carga excede incluso su capacidad ideal. Los tres diagnósticos terminaron con 207, 224 y 201 pendientes de org3. Estas cifras describen esa carga controlada; no son capacidad universal de producción ni un nuevo compromiso de throughput [E1, §§2–3].

También hay espera con cupo libre. W195/org3 tiene 213,7624154 s conservadores entre elegibilidad y selección: 118,4581902 s con cupo ocupado, 94,7844987 s con cupo libre y 0,5197265 s de incertidumbre de commit. W165/org2 esperó con cupo libre mientras intervenían trabajo síncrono previo, otro candidato atendido con batch=1 y la pausa del planner. La selección efectiva y los commits no explican por sí solos esos intervalos [E1, §3].

De ello no se deriva un bug ni un algoritmo a adoptar. Todas las organizaciones progresaron; no se demostró starvation infinita, monopolización contractual indebida ni violación de B9C/B9D/B8A. El dictamen congelado es `CURRENT_CONTRACT → NO_VIOLATION`, limitado a la evidencia analizada [E1, §4].

El FAIL histórico conserva runtime `83ee3b24c84b170e22e401cb09a34da5320ae0a3`, TurnWork 86, p95 persisted→claim de **10.015949 s**, B9E/PROFILE-BETA-1 FAIL y causa `ROOT_CAUSE_NOT_CONFIRMED`. El análisis del HEAD posterior no lo explica causalmente. La evaluación posterior del 02-10 que reportó PASS tampoco se modifica ni reclasifica aquel FAIL [E1, §5; H1].

## 2. Qué garantiza actualmente el scheduler

| Garantía vigente | Frontera y alcance | Límite de interpretación |
| --- | --- | --- |
| Elegibilidad estable | READY existe cuando hay inbound ordinario pendiente, sin asignar, con deadline vencido según DB. Nuevo input no retira READY ya satisfecho [C2]. | READY no fija membership ni concede ownership, prioridad temporal o permiso. |
| Exclusión por organización y conversación | Como máximo un TurnWork ordinario committed con PROCESSING, lease vigente y epoch válido por org, agregado entre procesos; exclusión por conversación [C1]. | Es un límite de autoridad/concurrencia; no una reserva de CPU, una tasa de servicio ni cancelación física de HTTP antiguo. |
| Claim autoritativo y recuperación | Cupo adquirido al commit del claim, orden de locks definido, revalidación bajo lock; completion/failure/retry/invalidation o expiry retiran ocupación/autoridad conforme a B3 [C1]. | Una selección advisory no reserva cupo; puede terminar en miss. Un reclaim cambia token sin crear presupuesto nuevo. |
| Saturación sin consumo indebido | Al no haber cupo no se mutan Message, attempts ni presupuesto; el pendiente conserva su ruta durable para competir después [C1]. | Persistir el trabajo no fija un tiempo máximo para procesarlo. |
| Protección limitada frente al ruido | Exclusión de org ocupada antes de LIMIT; un candidato por org, recencia y fallback. SCALE exige progreso cross-tenant y que una org ruidosa no ocupe todos los planners [C1; E1, §§3–4]. | No garantiza reparto igual, turno alternado ni aislamiento absoluto de latencia/recursos. |
| Yield documentado | Puede ceder ante futura elegibilidad cercana de otra org idle menos recientemente atendida [E1, §4]. | El horizonte está acotado por observación. Repetir observaciones no tiene un bound global de espera contratado. |
| Sender/safety independientes del cupo ordinario | Sender B4 progresa fuera del cupo; safety B5 conserva su vía y precedencia, sin LLM en su circuito determinista [C1; C5]. | Claim ordinario, dispatch, aceptación Meta y atención humana son fronteras diferentes. |
| Seguridad y contabilidad preservadas | Scheduling no amplía permisos, no renueva consentimiento/TTL, no elimina fencing ni restablece budget tras retry/restart [C1; C3; C4]. | Rapidez no habilita WRITE ni acredita release. |

Las reglas actuales de ranking, batch, polling y yield describen una implementación y algunos comportamientos verificados. Su existencia no las convierte en un contrato de fairness temporal [E1].

## 3. Qué NO garantiza

No existe un máximo global desde READY hasta claim, ni desde cada inbound persistido hasta claim. Tampoco hay bounded starvation global de organización o conversación, FIFO por mensaje, reparto igual o ponderado de servicio entre organizaciones, throughput mínimo por clínica, estabilidad bajo toda carga sostenida, ni un plazo de vaciado de cualquier backlog [C1; C2; E1].

No se reserva un planner a una organización. Tener cupo libre no implica que exista un proceso disponible o que se obtenga el siguiente claim. Una org que recibe muchos turnos no obtiene más candidatos por poll [E1, §3].

El p95 persisted→claim de **10 s** es un gate existente de PROFILE-BETA-1 para su cohorte/carga definida. No es un máximo por mensaje, un SLA READY→claim, un TTL de descarte ni una garantía frente a toda distribución de tráfico. El gate sigue vigente y no se sustituye por este documento [C1; P1, B9].

Los timeouts de llamadas, leases y deadlines de trabajos reclamados no acotan por sí mismos la cola anterior al claim. B9C además advierte que timeout de conexión/lectura no equivale a un deadline absoluto ante goteo de bytes. No puede deducirse una cota total de servicio a partir de esos parámetros [C1].

No hay promesa de entrega remota, atención clínica o acuse humano dentro de la latencia del scheduler. B5 distingue caso visible, aviso, acuse y atención [C5].

## 4. Qué requisito de producto justificaría cada garantía nueva

Estos requisitos son **candidatos a decisión**, no compromisos ya aprobados ni demandas de clientes demostradas por las fuentes consultadas.

| Posible requisito de producto | Contrato técnico que lo expresaría | Qué debe decidirse antes de exigirlo |
| --- | --- | --- |
| Una consulta ordinaria de una clínica no permanece indefinidamente esperando cuando el servicio opera dentro de su alcance admitido. | Espera acotada de la conversación ordinaria continuamente READY hasta un claim committed que incluya su conjunto elegible. | Unidad, reloj, bound, carga/burst/backlog admitidos, coste de turno, recuperación y excepciones. No hay un valor aprobado. |
| Una clínica con trabajo ejecutable no queda pospuesta indefinidamente por tráfico o forecasts de otras. | Bounded starvation por organización y regla de progreso entre organizaciones. | Qué significa ejecutable, cuándo empieza la obligación, cómo cuentan capacidad propia y oportunidades, y cómo se evita renovar el inicio por cada forecast. |
| Las clínicas admitidas conservan un servicio predecible aunque otro tenant se sobrecargue. | Fairness definida como protección de progreso/espera entre organizaciones dentro de la envolvente. | Si se requiere solo progreso o además participación de servicio; unidad de coste si se eligieran cuotas. No hay evidencia para imponer reparto igual o pesos comerciales. |
| Se necesita procesar un volumen contratado por clínica. | Throughput mínimo de trabajo útil bajo un mix y una ventana definidos. | Qué es trabajo útil, tipo/coste de turno, disponibilidad de providers, demanda y alcance comercial. Claims, safety y retries no pueden contarse indistintamente como servicio entregado. |
| Una tasa sostenida admitida no acumula deuda de procesamiento indefinidamente. | Estabilidad de backlog y recuperación de bursts dentro de la envolvente acordada. | Tasas y ráfagas admitidas, mix de llamadas, coste/capacidad efectiva, margen, fallos y criterio de recuperación. Nada de esto se fija numéricamente aquí. |

La fairness entre organizaciones no basta para proteger cada conversación dentro de una org. Una organización puede seguir recibiendo claims y dejar una conversación esperando. A la inversa, exigir el mismo número de claims a clínicas con costes distintos no equivale a proteger la experiencia de sus usuarios. Deben decidirse ambas unidades sin confundirlas [E1, §3].

## 5. Qué importa para SaaSLyVet y por qué

La prioridad recomendada es **que una clínica dentro del alcance admitido conserve progreso y que sus conversaciones ordinarias READY tengan una espera acotada bajo condiciones sostenibles**. El motivo es la continuidad del servicio multi-tenant: un pendiente durable puede no perderse y, aun así, no proporcionar una experiencia predecible a quien espera. SCALE ya protege el progreso cross-tenant y B9 ya trata la latencia del inbound sano como condición de activación; B9D exige acordar alcance/tasa y cobertura antes de promover una clínica [C1; C3; P1].

Esta es una recomendación de producto derivada de esas prioridades, no una afirmación de que el contrato actual ya deba esa garantía. Las fuentes no fijan el máximo de espera deseado ni validan una promesa comercial de fairness fuerte.

Bounded starvation por org es una protección necesaria para esa prioridad. La espera acotada por conversación expresa la experiencia individual; no debe quedar sustituida por un promedio de la clínica. La estabilidad bajo la carga admitida es una condición de factibilidad de ambas. Un mínimo de throughput independiente o un reparto igual entre tenants no aparece como necesidad aprobada: no se recomienda convertirlos ahora en compromisos comerciales.

No se propone garantizar estabilidad de la entrada ruidosa ya analizada conservando cualquier demanda. Su demanda supera la capacidad bajo las condiciones congeladas. Una garantía de espera necesita una envolvente factible y una respuesta de producto explícita fuera de ella. El plan ya contempla reducir alcance/carga y ampliar solo tras gates; este documento no elige un mecanismo adicional de admisión, rechazo o descarte [E1; C3; P1].

Safety y atención humana conservan prioridad y contratos separados. Mejorar la espera ordinaria no autoriza prometer atención veterinaria ni ocupar/redefinir el circuito B5 [C5].

## 6. Alcance propuesto del contrato que habría que aprobar

La propuesta para una futura redacción contractual tiene dos obligaciones:

1. **Progreso de organización:** dentro de la envolvente admitida, una org con trabajo ordinario continuamente ejecutable no puede ser postergada indefinidamente por las decisiones de scheduling de otras organizaciones, incluyendo forecasts sucesivos.
2. **Espera de conversación:** dentro de esa misma envolvente, el conjunto ordinario continuamente READY de una conversación debe alcanzar un claim committed dentro de un límite explícito aprobado. El inicio no se reinicia por nuevos inputs que conservan READY, por un miss ni por una nueva evaluación del selector.

No se determina aquí el límite, un timeout, un peso ni una tasa. Estas cláusulas todavía no son ejecutables como gate temporal. Antes de congelarlas, producto y responsables del release deben resolver:

| Decisión pendiente | Qué debe quedar escrito |
| --- | --- |
| Unidad cubierta | Org, conversación, conjunto READY y relación con membership; tratamiento separado de inputs que llegan después del claim. |
| Envolvente soportada | Alcance de capacidades, tenants concurrentes, demanda sostenida, ráfagas, backlog inicial y mix/coste de turnos/providers. La factibilidad no puede basarse solo en la media de llegadas o en el mínimo de servicio observado. |
| Fuerza de la promesa | Máximo individual frente a objetivo estadístico; regla de bounded starvation y relación entre org y conversación. Un p95 no satisface una obligación universal. |
| Fronteras y reloj | Inicio de READY continuo según DB; final en claim committed. Separar `claimed_at`, visibilidad de commit y ACK del driver. |
| Fallos y recuperación | Condiciones de disponibilidad, provider bloqueado/lento, crash/restart, retry/reclaim, DB/locks y política de recuperación. El SLA no se puede fundamentar en un timeout que no es deadline total. |
| Fuera de la envolvente | Qué se informa/ofrece y qué obligación permanece cuando hay sobrecarga; quién limita o retira alcance conforme a B9D. No introducir pérdida, TTL o rechazo implícitos. |
| Exclusiones legítimas | Safety/humano, capacidad retirada por release, inputs revocados/invalidados y trabajo no ejecutable. Definirlas antes del ensayo, con motivo trazable. |
| Propiedad y aprobación | Responsable del compromiso de producto, versión del contrato, matriz de gates y procedimiento de promoción/retirada. |

El reloj total READY→claim no se pausa silenciosamente mientras el cupo propio esté ocupado o mientras otro tenant sea atendido. Esas condiciones explican fases y restringen la factibilidad, pero siguen formando parte de la espera que experimenta el usuario. Cualquier exclusión de la obligación debe ser contractual y visible, no añadida después de observar un incumplimiento.

Retries/backoff y reclaims necesitan una cláusula específica; no se incorporan a la cohorte inicial READY sin decidir sus fronteras. Takeover y revocación siguen pudiendo hacer que el resultado correcto sea no reclamar o no ejecutar [C1; C2; C4].

## 7. Requisito, contrato, métrica, implementación y tuning

| Nivel | Ejemplo en esta decisión | Autoridad que NO aporta |
| --- | --- | --- |
| Requisito de producto | La clínica admitida conserva un servicio predecible ante el ruido de otros tenants. | No elige algoritmo ni fija automáticamente un SLA. |
| Contrato técnico | Obligación de progreso por org y espera acotada del conjunto READY, con envolvente y excepciones aprobadas. | No concede WRITE ni sustituye fencing, N, safety o budgets. |
| Métrica de aceptación | Distribución y máximo READY→claim committed por conversación/org; pendientes censurados, carga y coste de servicio documentados. | Una métrica no es el objetivo hasta que existe criterio contractual. |
| Implementación | Mecanismo futuro que demostraría esas obligaciones conservando los contratos existentes. | No está seleccionado ni autorizado por este documento. |
| Tuning | Ajuste posterior de una implementación válida para una carga concreta, dentro de su contrato. | No crea fairness, no redefine el bound ni convierte CAPACITY_LIMIT_CONFIRMED en defecto. |

El orden de decisión debe ser **necesidad de producto → contrato aprobado → escenarios/gates definidos → diseño autorizado → implementación y aceptación → tuning, si procede**. No se salta del backlog a un cambio de parámetros.

## 8. Consecuencias de convertir la propuesta en contrato

La garantía obligaría a publicar qué carga/coste soporta el alcance del release y qué ocurre fuera de ese alcance. No bastaría con afirmar que ningún Message se pierde ni con mostrar promedios rápidos. También habría que evaluar las conversaciones pendientes, no únicamente los claims completados.

La obligación podría restringir las decisiones actuales que reiteran una postergación: conservarlas o cambiarlas dependería de demostrar el contrato futuro. Esto no invalida retroactivamente reglas, recibos o resultados de E4.

Una espera acotada requeriría un argumento de factibilidad del servicio y su recuperación, además de pruebas finitas. Ningún ensayo de duración finita demuestra ausencia de starvation para todo tráfico, ni una cola drenada demuestra estabilidad bajo cualquier carga. La promesa debe ser comprobable bajo supuestos explícitos.

La prioridad de una conversación nunca debe ejecutarse con witness vencido, permisos retirados o consentimiento expirado para cumplir una latencia. El resultado contractual correcto ante invalidación debe quedar definido preservando B3/B5/B8A/B9D. La espera no renueva el TTL [C4].

La adopción sería prospectiva, versionada y separada de E4. Solo después de aprobar y completar el contrato podría autorizarse una fase de diseño. Este documento no modifica grants, gates, configuración ni la lista de capacidades activadas.

## 9. Métricas y gates que se derivarían

Todos los criterios siguientes son **especificaciones para un encargo futuro**, sin umbrales nuevos y sin ejecución en esta tarea.

| Obligación | Evidencia/métrica necesaria | Gate derivado |
| --- | --- | --- |
| Espera de conversación READY | READY continuo→commit del claim por conversación/conjunto; cola inicial y pendiente final; cohortes por org y mix de servicio. | Si se aprueba máximo: evaluar cada caso cubierto y pendientes que ya lo excedan. Si se aprueba objetivo estadístico: definir cohorte/cobertura y reportar además cola y extremos. |
| Progreso de org / bounded starvation | Intervalos con READY ejecutable, cupo propio ocupado/libre, disponibilidad de planners, polls, candidaturas, misses y siguientes claims. | Detectar org cubierta sin progreso más allá de la condición aprobada. Un bound de oportunidades exige acotar también el intervalo entre oportunidades para prometer tiempo. |
| Protección cross-tenant | Espera, progreso y servicio por org con ruido ajeno, frente al escenario de referencia definido. | Verificar el criterio de protección aprobado; no asumir reparto igual ni usar proporciones observadas como pesos. |
| Estabilidad / bursts | Trabajo ofrecido y completado con coste/mix; tamaño y edad del backlog; recuperación tras burst; pendientes censurados. | Demostrar sostenibilidad y recuperación bajo la envolvente aprobada, con ventanas y tolerancias por definir; no exigir backlog cero en cada instante. |
| Throughput, solo si se aprueba | Trabajo útil completado por org/capacidad y ventana; retries/safety separados; error y uso de provider. | Aplicar solo a la mezcla y condiciones contratadas. Claim count no acredita respuesta o entrega. |
| Invariantes actuales | Cupo N, autoridad por conversación, membership, lease/epoch, attempts/budget, locks, safety/sender, permisos y tenant isolation. | Conservar los criterios críticos vigentes. Un resultado temporal rápido con autoridad o datos incorrectos no es aceptable. |
| Calidad de evidencia | Journal completo, clocks/brackets, commit/rollback, IDs y fuente exacta; razones de exclusión para las obligaciones que las necesitan. | Captura inválida no produce aceptación. Incertidumbre que cruza la frontera del gate no se convierte en cumplimiento. |

La descomposición necesaria seguirá separando persisted→eligible, espera preselector, selección/SQL, post-selection, claim/locks y commit. No se suman percentiles de cohortes distintas ni tiempos solapados de planners. DB `claimed_at` precede al commit; el ACK del driver aporta una cota/observación, no el instante exacto del commit en servidor [E1].

La edad del pendiente más antiguo y los casos sin claim deben acompañar los percentiles para no ocultar starvation en la cola censurada. La cardinalidad por intento pertenece a recibos diagnósticos; las métricas operativas siguen la restricción de cardinalidad del plan/B9C. Ningún evento observacional adquiere autoridad [C1; P1].

El gate histórico de 10 s conserva método, cohorte y estado. Los gates del contrato nuevo serían adicionales y versionados; no una reinterpretación de PROFILE-BETA-1.

## 10. Escenarios de aceptación que deben definirse antes de cambiar runtime

No se ejecuta ni se escribe código de pruebas en esta tarea. La matriz futura debe fijar entradas, supuestos, reloj, resultados esperados y criterio contractual antes de diseñar un candidato.

| Escenario a especificar | Pregunta contractual / criterio que debe tener |
| --- | --- |
| Una org y varias conversaciones continuamente READY | ¿Progresa cada conjunto dentro de su bound, sin esconder espera individual en claims de otras conversaciones de la misma org? |
| Varias orgs dentro de la envolvente; una con backlog | ¿Mantienen progreso y espera las demás sin exigir igualdad de número de turnos? |
| Org saturada y otra con cupo libre | ¿Se preservan la exclusión antes de LIMIT y el progreso cross-tenant? Separar cupo ocupado de falta de oportunidad de planner. |
| Org READY con cupo libre y forecasts sucesivos de otras | ¿Puede reiterarse la cesión más allá de la obligación futura? READY/misses/forecast no deben reiniciar la antigüedad de la cohorte. No presupone un fallo actual. |
| Candidato incluido pero no ejecutado; selección vacía; misses/colisión de planners | ¿Se demuestra la obligación global por org/conversación a través de varios polls, sin tratar selección como claim ni reservar capacidad ficticia? |
| Burst admitido y carga sostenida factible con costes heterogéneos | ¿Se absorbe/recupera la carga dentro del criterio aprobado? Incluir coste completo y providers lentos dentro de los supuestos, no solo turnos cortos. |
| Sobrecarga fuera de la envolvente | ¿Se cumple la política de producto aprobada sin pérdida o permiso nuevo? Reportar backlog; no exigir a esa carga estabilidad o bounds que no se le concedieron. |
| LLM bloqueado/lento, sender/Meta lento y safety detectable | ¿Se conserva progreso y durabilidad donde aplica, distinguiendo scheduling ordinario, dispatch y atención humana? Mantener B5 y límites honestos de provider. |
| Crash antes/después de commit, rollback, restart, retry/reclaim, expiry y lock controlado | ¿Se preservan autoridad, lease/fencing, cupo agregado, membership y budgets, y se aplica la cláusula de recuperación de espera? |
| Ingest sobre READY, nueva entrada tras claim, takeover humano y consentimiento vencido | ¿Se conserva monotonicidad/membership y el resultado de seguridad correcto, aunque reclamar o ejecutar deje de estar permitido? |
| Gates/capacidades cerrados y aislamiento tenant | ¿La garantía temporal deja intacta la autorización B9D/B8A y la separación de datos/efectos? Rapidez no acredita activación. |

Los escenarios de liveness deben incluir historia adversa finita y un argumento sobre por qué la obligación no admite postergación ilimitada dentro de sus supuestos. Medir durante un intervalo y encontrar todos los claims no sustituye ese argumento. Las condiciones fuera de la envolvente deben estar fijadas antes del ensayo, sin exclusiones retrospectivas.

## 11. Consecuencias arquitectónicas únicamente después de aprobar el contrato

No se recomienda un algoritmo ni un cambio de topología. La arquitectura futura solo tendría que evaluarse contra estas necesidades, si el contrato las exigiera:

| Necesidad que podría aparecer | Decisión arquitectónica posterior, todavía sin resolver |
| --- | --- |
| Obligación que sobreviva a varios procesos y restart | Determinar qué hechos canónicos deben sostener la garantía y si las primitivas durables actuales bastan. Observabilidad/advisory no puede convertirse por accidente en ownership. |
| Cota temporal de servicio y oportunidades | Demostrar si la topología y los límites existentes pueden sostener la envolvente aprobada. Si no, debe decidirse explícitamente alcance/capacidad/contrato antes de cualquier cambio. |
| Fairness y espera individual comprobables | Poder explicar elegibilidad, oportunidad, decisión, miss y progresión por org/conversación bajo concurrencia, preservando claim autoritativo y revalidaciones. |
| Política frente a sobrecarga | Definir su coherencia con persistencia inbound, B9D, privacidad y recuperación; no introducir implícitamente descarte, nuevas cuotas o rechazo. |
| Cambio incompatible con invariantes existentes | Identificar la enmienda/ADR y pruebas necesarias antes del diseño. El contrato nuevo no deroga N, leases, fencing, budgets ni permisos por sí solo. |

La evaluación deberá respetar el monolito y las prohibiciones de plataforma/ownership adicionales de los contratos actuales salvo enmienda explícitamente aprobada [C1; P1]. Esta lista es de capacidades y decisiones a evaluar, no de implementaciones elegidas. No habilita cambiar workers, polling, batch, fairness, N, SQL o índices.

## 12. Integridad y estado conservado

La verificación documental inicial confirmó HEAD/rama y comprobó los cuatro manifiestos existentes: **257 entradas válidas**, correspondientes a 243 archivos de diagnósticos originales y 14 del análisis cerrado. No se reejecutan derivadores, validadores que escriban, suites, providers, PostgreSQL, benchmarks, diagnósticos ni PROFILE.

Se tomó un inventario SHA-256 de **3067 rutas versionadas o no ignoradas**, incluidos archivos preexistentes y rutas eliminadas registradas con valor nulo. El documento nuevo queda excluido de ese inventario para comparar antes/después. Digest del inventario canónico: `8704f55ce64c9ba255a48322ba0a642979bc833706244c30ef2886e9025ce027`. No se modifica ninguna de esas rutas.

La comparación final confirmó el mismo digest y las mismas 3067 rutas, HEAD/rama idénticos, todos los hashes protegidos iguales y las 257 entradas de manifiestos válidas. El único archivo añadido por esta tarea es este documento; los cambios preexistentes permanecen intactos.

| Fuente protegida | SHA-256 de bytes |
| --- | --- |
| Contrato B9C | `a7942c4dfb55de35b2c7980dc0f11254d46d87324e273cfedf4751e1876cd03c` |
| READY v1 | `f39ab337f53bdb08f5d3be73f00fc9d8710188f138b04e79eb7bbbf4fb6d316b` |
| Contrato B9D | `60990d9b6ca4eaf9a4c285aa8846a9abd427dc3bbd18d3a1a5f46df3eb93e8b6` |
| Informe cerrado E4 | `17cfa588a2bafb94e364a73a6eb7a255ea9ff476b020914ca7521acca37b2dc6` |
| closure.json E4 | `edcefa5f027ef4934ea389a1ac46416f13548bcd7d6ad71fd1a8572bfb673e5a` |
| Manifiesto E4 cerrado | `c047b0adbc7dfd38acdb08ae2c2fe5bd4de1f7e456f52558d8e6e47b5ca1106e` |
| services.py | `f25b1944f6072232bc5ebb194c03750a169899a9955c4d1b13feb614fe9234e9` |
| worker.py | `4942405258d316a10d3bcca37190b862617c4ab651b2acde440cca113f75a17c` |
| durable.py | `e6ffc70f90b53dab5c52193f4d743af83d1166a33e9278b21bd5b7d7155e7844` |

Estado preservado: **E4=CLOSED; E4_DECISION=CAPACITY_LIMIT_CONFIRMED; NEXT_ACTION=STOP_BEFORE_TUNING; B9E=FAIL; PROFILE-BETA-1=FAIL; B9=IN_PROGRESS**. Producción cerrada, cero clínicas activadas, sin deploy ni activación; threshold de 10 s intacto. No se crean commits ni infraestructura temporal. La evidencia de limpieza previa permanece en el expediente E4; esta tarea no inicia infraestructura que requiera limpieza nueva.

## 13. Recomendación concreta

**B) Crear un nuevo contrato de fairness/bounded-wait y, únicamente después de aprobarlo, diseñar una fase de implementación separada.**

El contrato recomendado debe proteger el progreso por organización y acotar la espera de conversaciones ordinarias continuamente READY **dentro de una envolvente sostenible de carga, servicio y recuperación aprobada**. Debe declarar qué sucede fuera de ella. No se recomienda prometer reparto igual, throughput mínimo independiente ni estabilidad bajo demanda ilimitada.

A sería coherente si producto acepta expresamente mantener solo las garantías actuales, sin nueva promesa de espera. Se prefiere B porque el plan ya prioriza progreso cross-tenant y latencia del servicio sano, y la evidencia cerrada muestra que persistencia/cupo correcto no bastan para definir una experiencia predecible. Esta preferencia no demuestra incumplimiento actual.

**El siguiente paso recomendado es aprobar el requisito y completar sus decisiones pendientes, sin inventar un SLA numérico. No autoriza implementar ni tunear. E4 permanece cerrado: CAPACITY_LIMIT_CONFIRMED → STOP_BEFORE_TUNING.**

