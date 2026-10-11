# D29 — paquete conjunto de decisiones para la siguiente fase

Fecha: 9 de octubre de 2026. **PROPUESTO / NO APROBADO / NO EJECUTADO**.

Estado vigente: `CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY`.
`CONFIRMED_BASE_ESTABLISHED` permanece aceptada y sin cambios.
Baseline: `825db75df68bf076929fa787e77beefe96803350`.
SHA-256 de la base: `71c3e58c34decfac1698f9517f39b4d7cbc936c0463e35a4bbfe00ee04920a56`.

Este paquete propone cinco decisiones para una sola fase de infraestructura de evaluación, probes individuales y regresión. No concede autorización de ejecución. La receta nueva de R1-04 y el inventario inicial de R2-09 son propuestas de diseño derivadas del código y los receipts; no son observaciones físicas ni soluciones ya demostradas.

## Decisiones reunidas

| Decisión | Propuesta concreta | Criterio de cierre | Cambio que debe aprobarse |
|---|---|---|---|
| P01 — R1-06 | Conciliar inputs, episodios, works y obligaciones; evaluar por separado las respuestas diferidas. Mantener 2×4 sólo para backlog y 2×3 para oferta ordinaria. | Ocho READY naturales previos al arranque, todos los inputs representados, origen/edad conservados, costes realmente ejecutados conciliados, obligaciones resueltas y verificadores completos. | Interpretación prospectiva del gate de evaluación de R1-06; ninguna excepción comercial ni cambio de runtime. |
| P02 — reloj / R2-04 | Control temporal y reversible de la sincronización del host de evaluación; repetir una vez la composición postcommit + base, con la receta ya aprobada. | Reloj y captura originales válidos; expiry/reclaim naturales dentro de oferta real; aceptaciones de ambas orgs antes/después; seguimiento íntegro y drain. | Autorizar expresamente el control temporal del servicio de hora del host, además del probe. |
| P03 — R1-04 | Diseñar y probar una corrección ordinaria cerca del límite nativo de agrupación, manteniendo tres conversaciones/org. | Mismo waiter atravesando forecast, yield, corrección committed, miss del forecast antiguo, nueva elegibilidad natural y claim, con toda su edad conservada. | Patrón finito adicional de preparación/corrección, declarado aparte de la oferta base; no población de 17 conversaciones. |
| P04 — R2-09, ambas variantes | Añadir un backlog inicial finito de seis episodios READY naturales dentro de las seis conversaciones existentes; después oferta base intacta. Ejecutar `uncertain_meta` y `slow_meta` por separado. | Solapamiento READY–Meta afectada demostrado por intervalos, progreso peer, autoridad/outbox y provider correctos, sin retry ciego. | Autorizar específicamente backlog inicial y arranque posterior para R2-09, y la variante `slow_meta`. La prohibición anterior de añadir backlog permanece hasta aprobar este punto. |
| P05 — regresión | Diagnóstico mínimo del OutOfMemory y ejecución secuencial de las siete suites sin PASS, con bases privadas nuevas. | Todas las suites completas, sin errores ni omisiones no justificadas; limpieza e integridad verificadas. | Sólo aislamiento/orquestación y captura de recursos de evaluación. Ningún tuning ni cambio de tests/runtime. |

La recomendación es aprobar P01–P05 como alcance de la siguiente fase, conservando sus condiciones de parada. No se promete un PASS futuro: si una receta no alcanza físicamente su frontera, permanece pendiente.

## P01 — R1-06: contar obligaciones, no exigir una respuesta por mensaje

La corrida preservada tiene 32 inputs durables, 31 episodios/works/claims y 30 salidas aceptadas. Dos inputs de una conversación se agruparon antes del claim sin renovar el origen. Un work terminó `deferred_to_new_input`; un episodio posterior de la misma conversación produjo una salida aceptada. El máximo superior observado de READY→claim fue 43,660301 s. Son hechos de esa corrida; no son cantidades que deba reproducir la siguiente.

Propongo adaptar **únicamente el verificador de R1-06** a la unidad que D29 §2 ya describe:

1. Cada input durable debe pertenecer exactamente a un episodio/obligación de su organización y conversación. Varios inputs pueden compartir episodio; no se exige `inputs = episodios`.
2. Cada episodio evaluable conserva su primer READY y su claim exterior. Agrupación, cupo ocupado y correcciones no reinician edad. Se conserva el objetivo vigente de 120 s y la regla completa de incertidumbre.
3. Cada work debe tener testigos del servicio realmente ejecutado. Las duraciones del provider permanecen intactas. No se inventa una llamada Meta para un work que no produjo outbound.
4. Una salida ausente sólo se acepta como diferida si hay evidencia del nuevo input, del desenlace durable y del enlace a la obligación posterior. Una salida posterior aceptada, por sí sola, no demuestra que todas las obligaciones anteriores estén cubiertas. Si el enlace o su disposición contractual no puede acreditarse, no pasa.
5. Se concilian por separado mensajes, episodios, works, salidas creadas, diferimientos y llamadas Meta. Ninguna obligación desaparece para igualar cantidades.
6. Se conserva el gate físico ya acreditado: ocho episodios READY distintos antes del arranque; cuarta conversación exclusiva del backlog; oferta ordinaria posterior en tres slots; clocks, membership, fairness, colas y drain completos.

El ejemplo sencillo es «el usuario corrige su solicitud»: el trabajo anterior puede quedar diferido y el siguiente responder a la solicitud actual. Eso exige una cadena verificable; no permite omitir una respuesta sin explicación.

La futura implementación debe tener controles negativos que rechacen inputs perdidos, edad reiniciada, servicio sin testigo y diferimientos sin sucesor acreditable. Se sellará el gate nuevo antes de una repetición física con la misma fixture. La corrida anterior y sus errores no se reescriben ni se convierten retroactivamente en PASS. No se altera el gate de R1-02 ni el receipt de base.

## P02 — continuidad temporal y repetición de R2-04

El intento 0004 es `INVALID_RUN`: System registró un ajuste del host de +2,1357499 s y el journal ingress perdió la intersección DB/monotónico. No se abrió la oferta base. El problema observado no se resuelve dando tolerancia al gate ni usando sólo un reloj monotónico para reemplazar los deadlines PostgreSQL.

**Procedimiento propuesto sujeto a aprobación expresa:** registrar estado y fuente de sincronización del host; verificar que el entorno puede usarse para esta evaluación; detener temporalmente `W32Time` antes del comienzo de la captura y restaurar su estado operativo anterior después de cerrar la ventana medida. No cambiar fecha/hora, tipo de arranque, registro, configuración NTP ni planes de energía. No detener otros servicios. Si el host no puede permitir ese control temporal, o existen otras fuentes de ajuste que no pueden controlarse dentro de este alcance, no iniciar el probe: queda pendiente la precondición de entorno.

Este control afecta la sincronización automática de Windows en todo el host durante el ensayo, no sólo la DB privada. Por eso P02 incluye esa acción explícita; una aprobación genérica de «repetir R2-04» no basta para introducirla. No se afirma que detener un servicio garantice continuidad: el monitor y el gate original siguen siendo la autoridad.

El guard contra suspensión y los eventos System se mantienen. Todos los participantes usan la relación PostgreSQL/monotónico de la base; las calibraciones se conservan completas. Se registra por separado la restauración del servicio y del guard, también en los caminos de error. Restaurar después del cierre medido no autoriza a excluir un ajuste ocurrido dentro de la ejecución.

Microsoft documenta que W32Time puede ajustar la velocidad o cambiar directamente la hora del sistema; `SetThreadExecutionState` se refiere a suspensión, no al servicio de hora. Fuentes: [Windows Time](https://learn.microsoft.com/en-us/windows-server/networking/windows-time-service/how-the-windows-time-service-works), [SetThreadExecutionState](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate). La pausa temporal es nuestra propuesta operativa; no es una garantía ofrecida por esas fuentes.

**Receta de R2-04 sin cambios:** lease 900 s; `S = L − P`, con P derivado del receipt aceptado; oferta 360 s; seguimiento completo 240 s; dos planners y un sender. El ensayo dura aproximadamente 24 min 29 s desde el claim inicial, más preparación/cierre. Esa duración es del probe, no del tiempo de respuesta prometido.

PASS exige commit/crash y salida del propietario reales, expiry y reclaim naturales, oferta base realmente concurrente, aceptaciones de ambas orgs antes/después, mismo work/history/budget/membership y fencing correcto, clocks estrictos y drain. No se mueve S ni se reduce el lease. Un nuevo salto da `INVALID_RUN` y detención; no habilita reintentos automáticos. El reclaim individual anterior conserva su acreditación.

## P03 — R1-04: alternativa mínima a la población de 17

La propuesta antigua intentaba cubrir un desplazamiento de ocho segundos mediante muchos forecasts. No está aprobada. Hay una alternativa de diseño que esa construcción no aprovechaba: `_extend_quiet_window` limita naturalmente el deadline al primer inbound pendiente +25 s. Una corrección **antes de READY**, cerca de ese límite, puede desplazar el deadline menos de un segundo, sin tocar QUIET_WINDOW=8 s, MAX_WAIT=25 s ni el horizonte H=1 s.

**Inferencia nueva del código, todavía no prueba física:** si el waiter W ya es READY en `T−1 s`, el peer tiene deadline `d1` entre `T−1 s` y T, y una corrección ordinary committed antes de d1 mueve su deadline a T, el forecast corregido puede seguir dentro del horizonte nativo. Ya no hace falta construir un puente de ocho segundos ni ampliar a 17 conversaciones para esa cadena finita.

Receta candidata para diseño y un probe finito:

1. Capturar desde antes de la preparación. Crear por ingress ordinario historia de servicio real de A y completar ese trabajo; B conserva historia menos reciente. No insertar ni modificar historia artificial.
2. Usar una conversación F de B distinta al slot de la primera oferta base. Mantener su conjunto todavía no READY mediante correcciones ordinarias previas a cada deadline. Definir `T = created_at` del primer miembro pendiente + MAX_WAIT nativo, con procedencia y brackets observados.
3. Como ejemplo nominal sellable, ingresos de F en offsets 0, 7, 14 y 16,5 s producen una proyección de d1≈24,5 s y cap T≈25 s. Son offsets nuevos de fixture, no tasas de base ni resultados. Si los commits reales no cumplen esa geometría, no se sustituye por el horario nominal.
4. Crear W en otro slot de A para alcanzar READY aproximadamente en T−1 s. Ejemplo nominal: ingreso en 16 s y QUIET_WINDOW natural de 8 s. Exigir sobre los hechos acotados `rW >= T−H` y `rW < d1 < T`; una cronología que no permita decidir esas relaciones no acredita la receta.
5. Abrir la oferta base sin cambiar su calendario/rotación. Ejemplo candidato: inicio aproximadamente en T−5 s, con los primeros slots distintos de W/F. Esos inputs no deben alterar los deadlines críticos ni crear un READY previo que deshaga la condición de recencia. Esto debe comprobarse en el plan completo y en eventos reales, no darse por supuesto.
6. Observar un poll real: W READY, A libre y más recientemente servida, B libre con F futuro dentro de H; evidencia previa a la consulta, selection_id y selección vacía/yield sin intento de claim.
7. Sólo después del yield observado, emitir una corrección ordinary para F. Su commit debe ser anterior a d1 y su deadline real posterior debe ser T. Todos los planners continúan libres. No se hace esperar a un planner para que quepa el commit.
8. Conservar la evidencia de que la proyección d1 fue reemplazada antes de vencer; al atravesar d1, F aún no es READY y existe el forecast corregido. Acreditar el miss del forecast antiguo por esa cadena causal, separado de cualquier miss de claim.
9. Dejar vencer T naturalmente; observar nueva elegibilidad y claim de B, y claim de W sin origen/edad reiniciados. Conciliar toda la preparación, oferta base y obligaciones hasta el corte, incluido el seguimiento base de 240 s.

**Qué requiere aprobar P03:** patrón adicional finito de llegadas/correcciones y preparación de historia, dentro de las mismas 2×3 conversaciones. La oferta base de 360 s conserva sus tasas, slots y pacing; la oferta total del escenario incluye inputs de preparación/perturbación registrados aparte. No se dice que esa carga total sea idéntica a la base, ni se la confirma como una nueva base.

PASS eventual exige la cadena completa para el mismo W, incluido el solapamiento con la oferta base real. Una prueba causal antes de abrir la oferta no cierra la condición conjunta. Claim temprano de W, ausencia de yield, commit tardío, geometría indeterminada o missing witness ⇒ `NOT_ACCREDITED`; clocks/captura inválidos ⇒ `INVALID_RUN`. No se acorta la cadena para salvarla ni se oculta un intento fallido.

Esta alternativa conserva el rechazo a las 17 conversaciones. Su viabilidad temporal debe verificarse al construir el plan: no está acreditada y no se garantiza que los polls/commits físicos quepan. Si no puede ejecutarse con estas primitivas, se detiene R1-04 y se entrega la incompatibilidad concreta; no se amplía población automáticamente. Si se exige también prohibir todo input adicional respecto del calendario base, P03 no es aceptable y R1-04 permanece pendiente.

Fuentes de la inferencia: [services.py](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/services.py:428), [horizonte y recencia del selector](C:/Users/LAP/Desktop/VeterinariaSaaS/backend/apps/agent/worker.py:59). No se modificaron.

## P04 — R2-09: cola ordinaria natural con inventario inicial declarado

La última variante `uncertain_meta` validó el aislamiento del provider y los testigos LLM de los 24 works. No hubo ningún solapamiento READY–Meta afectada, ni como intervalo posible. No recomiendo repetir a ciegas el mismo patrón esperando una pausa fortuita del host.

Propongo autorizar una **extensión específica de escenario**, distinta de la base inicialmente vacía: seis episodios ordinarios iniciales, uno por cada conversación de la población 2×3. Se ingresan por el camino real, se espera READY natural y se conserva un corte antes de arrancar planners. Después se inicia oferta base de 360 s con su pacing/rotación intactos y seguimiento de 240 s. No se añade una cuarta conversación, no se cambia ninguna tasa ni se fabrica READY con updates.

El sender debe estar listo antes del arranque de planners para poder observar sus salidas; arrancar los planners después del corte es exclusivamente la condición inicial aprobada. Desde su arranque no se retienen, detienen ni bloquean participantes para conservar cola. Se registra el orden y duración reales de arranque; su tiempo permanece en las edades.

Dos planners pueden reclamar a la vez un work por org, dejando otros episodios iniciales en cola. Esa es una condición que hace plausible el solapamiento, **no una observación ni un PASS garantizado**: sólo acredita el probe si el READY pendiente intersecta físicamente una llamada Meta afectada mientras está abierta la oferta base.

Cada variante usa una DB y salida nuevas, sin compartir un backlog ya consumido:

| Variante | Provider que se conserva | Evidencia adicional obligatoria |
|---|---|---|
| `uncertain_meta` | Meta 0,2 s y timeout simulado sólo en Meta de la org objetivo; LLM permanece completo, sin timeout inyectado. | fault_id, call_id, admisión sender, outbox, ownership y no retry ciego; resultado incierto conservado, sin llamarlo aceptación. |
| `slow_meta` | Multiplicador existente ×2 sólo en Meta de la org objetivo: 0,4 s configurados. LLM y dominio permanecen en el coste base. | Duración realmente observada, sender/outbox, independencia de autoridad y progreso ordinario de ambas orgs. No aumentar el multiplicador si falta cola. |

Para ambos, el verificador debe probar solapamiento **definido**, usando los intervalos de READY→claim y dispatch→result, dentro de la oferta base efectivamente abierta. Un solapamiento sólo posible por incertidumbre no basta. Se requiere además progreso/oferta peer real, trazabilidad LLM por claim/work, invariantes, inventario completo, drain ordinario y disposición explícita de cualquier outbound incierto esperado por el caso. No se fuerza la aceptación de un outbound cuyo resultado es incierto.

Los seis inputs iniciales se separan de las emisiones base para medir pacing, pero permanecen en la cohorte completa y sus edades. Las agrupaciones o diferimientos que aparezcan se concilian explícitamente bajo el plan de esta nueva fixture; no se presupone `30 inputs = 30 episodios` ni se excluyen para facilitar el gate.

La aprobación de P04 debe decir expresamente que levanta la prohibición de **backlog inicial sólo para estos dos probes** y autoriza `slow_meta`. El provider no se ralentiza más ni se modifica para favorecerlos. Si no se acepta esa extensión, ambas condiciones continúan pendientes; no se declaran imposibles bajo cualquier condición sólo porque faltaron en un ensayo. Si con seis episodios no aparece solapamiento, conservar `NOT_ACCREDITED / PENDING_NATURAL_OVERLAP`; no aumentar backlog ni repetir automáticamente.

## P05 — regresión y entorno de evaluación

Conservar D29: 78 tests distintos pasados, y B3: 39 tests pasados. El último sender falló con OutOfMemory de PostgreSQL seguido de errores de conexión/setup/teardown; W1 quedó interrumpida y cinco suites no iniciaron. La causa profunda del agotamiento no quedó determinada. No se deduce que baste «dar más memoria», ni se atribuye o descarta una regresión del runtime por ese error.

Antes de reintentar, registrar recursos disponibles y límites del proceso/laboratorio, conexiones y logs del cluster privado. Ejecutar sin ofertas físicas concurrentes, una suite por vez, con copia exacta del baseline y bases privadas nuevas. Si reaparece OutOfMemory, detenerse y diagnosticar la infraestructura/proceso con la evidencia preservada; no ampliar memoria, editar PostgreSQL o cambiar tests automáticamente.

Suites pendientes: `test_b4_sender`, `test_w1_monotonic`, `test_b5_safety`, `test_operation_execution`, `test_b9b_budget`, `test_b9c_concurrency`, `test_b9c_processes`. Conservar las fuentes existentes, configuración de durabilidad, todos los tests y sus receipts/logs/exit codes. No fraccionar un test para eliminar su condición de fallo ni omitir las pruebas difíciles.

Los cambios futuros en verificación/infraestructura tendrán sus checks específicos y regresión D29 correspondiente. B3 y escenarios ya acreditados no se repiten ahora como si carecieran de evidencia; si un nuevo cambio afecta una frontera concreta, se explicita por qué exige repetición.

## Alcance común, parada y matriz posterior

P01–P05 no autorizan E, capacidad máxima/comercial, nueva caracterización, sweep, tuning/PROFILE, scheduler, proveedores reales, commits ni cambios de runtime/contratos D29/B8/B9/E4. La única excepción operacional propuesta es el control temporal del servicio de hora descrito en P02; requiere aprobación explícita y restauración.

Mantener exactamente el receipt de base: tasas por org `[1.9607508002652434, 1.9607508002652434]`, 2×3, dos planners, un sender, batch/poll/pause vigentes, dos llamadas LLM de 0,5 s, dominio de 0,1 s, Meta base de 0,2 s, clocks PostgreSQL/monotónico y ventanas 360/240 s de los probes. Las perturbaciones específicas aprobadas se identifican aparte, nunca como una modificación de CONFIRMED_BASE. Los 120 s continúan siendo el objetivo READY→claim; los parámetros de fixture no son SLAs nuevos.

Orden recomendado: diagnóstico/regresión de aplicación → preparación y verificación de cambios de evaluación → R1-06 → R2-04 → R1-04 → R2-09 `uncertain_meta` → R2-09 `slow_meta` → checks finales aplicables, integridad y cleanup → entrega. Un fallo de infraestructura común detiene la ejecución hasta resolver la precondición; una frontera no observada queda pendiente. No hay bucle de reintentos en busca de un PASS.

En cada receipt separar frontera física, condición completa de carga, base referenciada, prerrequisitos pendientes y evidencia sintética/física. Registrar cohortes, costes, offers/acceptances, claims/outer commits, clocks/System, invariantes, divergencias, cleanup, hashes y todos los intentos fallidos. Las corridas históricas no se sobrescriben; un análisis nuevo no representa una repetición física.

**Matriz posterior, decisión distinta:** sólo después de revisar esos resultados se podrá autorizar la matriz completa: 17 escenarios y las 36 variantes enumeradas por las fuentes actuales. Esta cifra identifica variantes requeridas, no 36 éxitos ya obtenidos. Sólo si todas las variantes y sus condiciones de carga pasan sus verificadores físicos correspondería `FULL_CONTROLLER_ACCREDITED`. Aprobar P01–P05 no autoriza esa ejecución automática. Si cualquier punto queda pendiente, se conserva `FULL_LIVE_MATRIX_NOT_READY`.

Cerrar la infraestructura de acreditación D29 tampoco equivale por sí mismo a cerrar todas las puertas de producto/release de Fase E o a aprobar una capacidad comercial.

## Procedencia del paquete

- [Protocolo D29, §2–§8](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/decisions/2026-10-05-scheduling-characterization-protocol.md).
- [Base confirmada aceptada](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-r102-base-2026-10-07/confirmed-base-receipt.json).
- [Informe final de probes](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-authorized-probes-2026-10-07/INFORME-FINAL.md).
- [Conciliación física R1-06](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-authorized-probes-2026-10-07/r1-06/authorized-r106-2x4-20261007-0002/outcome-reconciliation-v2.json) y [gate completo pendiente](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-authorized-probes-2026-10-07/r1-06/authorized-r106-2x4-20261007-0002/independent-verification.json).
- [Incidente clock R2-04](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-authorized-probes-2026-10-07/r2-04/authorized-r204-postcommit-base-20261007-0004/clock-incident-analysis.json).
- [R2-09: testigos y ausencia de solapamiento](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-authorized-probes-2026-10-07/r2-09/authorized-r209-uncertain-meta-20261007-0002/evidence-audit-v2.json).
- [Regresión de aplicación incompleta](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-authorized-probes-2026-10-07/application-regression.json).
- [Variantes de la última matriz histórica](C:/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/d29-dependent-2026-10-07/report.md).

En este encargo se redactó únicamente este documento nuevo. No se ejecutaron probes, tests, benchmark, replays ni controles de reloj. Las propuestas P03 y P04 requieren validar el diseño físico al implementarse; la lectura de código, la geometría nominal y el número inicial de episodios no acreditan resultados.
