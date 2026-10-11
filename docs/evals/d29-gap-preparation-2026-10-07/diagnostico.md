**D29 — diagnóstico y preparación de las cinco brechas, antes de ejecutar**

Se conserva `CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY` y la base `CONFIRMED_BASE_ESTABLISHED`. Esta entrega no acredita nuevos escenarios ni reinterpreta intentos anteriores como resultados del runtime. Se preparó infraestructura de evaluación en este directorio; no se abrió PostgreSQL, no se iniciaron workers, no se activó la protección de energía y no se ejecutó otra matriz. No hay commits.

Baseline: `825db75df68bf076929fa787e77beefe96803350`. Receipt de la base: [confirmed-base-receipt.json](../d29-r102-base-2026-10-07/confirmed-base-receipt.json), SHA-256 `71c3e58c34decfac1698f9517f39b4d7cbc936c0463e35a4bbfe00ee04920a56`.

| Línea | Causa / conclusión | Preparación entregada | Estado antes de una repetición |
|---|---|---|---|
| R1-03 | Suspensión del host y resincronización de hora durante el intento; la relación DB↔monotónico dejó de admitir un offset común. | Protección temporal contra suspensión por inactividad, monitor estricto de capturas, cortes de eventos del host y envoltorio de un único probe. | Corrección de infraestructura comprobada offline; continuidad física pendiente. |
| R1-04 | La oferta base y los planners libres no produjeron el yield requerido. La receta finita previa sí controlaba los polls. | Receta causal, requisitos de evidencia y análisis de incompatibilidad del patrón actual. | No hay receta garantizada que cumpla simultáneamente todas las restricciones actuales; decisión metodológica pendiente. |
| R1-06 / R2-02 | Cuatro episodios simultáneos frente a tres conversaciones; en R2-02 cuatro inputs llegaron durante un bloqueo sin posibilidad de nuevo claim en esa org. | Análisis separado de población, episodios y opciones A–D, con referencias a los inputs reales. | Ninguna opción elegida ni aplicada. |
| R2-04 | El reclaim finito ya pasó, pero no estaba acompañado por la ventana base. El lease natural es de 900 s. | Fixture de preámbulo que reutiliza el crash acreditado, cálculo de anclaje y gate adicional de solapamiento real. | Preparada como componente; composición final con el conductor pendiente de revisar el diseño de fases. |
| R2-09 | La condición `UNCERTAIN` carecía del filtro `boundary == meta`. | Provider corregido, correlación por llamada, entry point de evaluación y verificador adicional. | Aislamiento comprobado offline; acreditación física Meta y cola ordinaria pendientes. |

**1. R1-03: qué se contradijo y qué se corrige**

El reloj DB observado es `clock_timestamp()` de PostgreSQL; los brackets del journal usan `time.perf_counter_ns()` del mismo host. `ClockMap` exige la intersección de todos los intervalos `[DB − fin_monotónico, DB − inicio_monotónico]`. La intersección quedó vacía en ingress, planner_1, planner_2 y sender. No se trata de un simple orden de escritura de archivos.

La primera contradicción ya detectable en ingress está en `ingress.jsonl:1901`, muestra DB `2026-10-07T21:26:45.139593+00:00`. Las primeras contradicciones de planner_1, planner_2 y sender están en las líneas 4029, 3991 y 4366 de sus journals. La reconstrucción final lanzó `Reversed temporal interval`; el diagnóstico original también señaló `INVALID_CLOCK_RELATION`. El residuo final de ingress es 55,2024 ms; los cuatro participantes muestran el mismo problema de relación entre relojes. [Detalle y hashes](clock-diagnosis.json).

La nueva consulta histórica del host encontró:

- Kernel-Power 42, registro 317125: suspensión por `System Idle`.
- Kernel-Power 107, registro 317126: reanudación.
- Kernel-General 1, registro 317127, conservado en la entrega anterior: ajuste de hora de 17.519 ms al sincronizar con el hardware.
- Power-Troubleshooter 1, registro 317132: suspensión `21:26:22.8424723Z`, reactivación `21:26:45.4620241Z`, origen `Power Button`.

Los 17,519 s de ajuste del reloj de pared no son los 55,2024 ms de contradicción residual DB↔monotónico. Los registros prueban el incidente del host durante la corrida; no aíslan un defecto de PostgreSQL, QPC o del runtime. La inferencia sustentada es una pérdida de continuidad por suspensión/reanudación del entorno, expuesta por la captura. [Eventos originales del host](host-power-events.json).

La corrección preparada en [clock_guard.py](clock_guard.py) conserva exactamente la intersección matemática, sin tolerancias añadidas, exclusión de muestras, cambio de origen, segmentación o corrección de timestamps. Detecta la contradicción durante la captura, registra `INVALID_RUN` y solicita detener el intento mediante el mecanismo de stop del harness. El conductor revisa ese estado en sus checks de salud. También comprueba identidad de proceso/sesión, secuencia, monotónico no regresivo y cierre completo.

El envoltorio [prepared_probe.py](prepared_probe.py) prepara solamente R1-03: toma cortes del registro System por **RecordId**, rodea el intento con una solicitud temporal `ES_SYSTEM_REQUIRED`, instala el monitor, conserva la oferta 2:1 y restaura el estado de energía al terminar. No cambia NTP, PostgreSQL, el plan de energía persistente ni los clocks del runtime. La API no impide suspensión manual o cierre de tapa; cualquier evento de suspensión/ajuste o pérdida de cobertura del log invalida el intento. [Límite de la API documentado por Microsoft](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate).

La garantía ofrecida es **no aceptar una corrida sin continuidad demostrada**. No se promete impedir cualquier cambio de reloj del host. Para demostrar resolución física hacen falta un nuevo run ID, cuatro journals completos con intersecciones válidas, cortes del host sin incidentes, receipt de adquisición/restauración de la protección y el verificador original de R1-03 con oferta y aceptaciones reales. El [manifiesto del probe](R103-probe-preparation.json) no es una autorización ni un resultado de ejecución. El intento anterior permanece inválido.

**2. R1-04: receta causal propuesta y condición nueva**

El contrato §6 requiere READY más elegibilidad futura repetida y conservación de edad. El selector existente mira una ventana futura de 1 s (`worker.py:65–75`); el debounce ordinario es de 8 s y su límite de 25 s (`services.py:44–45`). Ninguno se modifica.

La receta debe observar esta cadena, identificando orgs A/B, waiter W, mensaje futuro F, corrección C, selección S y ambos planners:

1. Capturar el commit que origina W y su READY natural `rW`. Mantener identidad de episodio, miembros y edad desde `rW`. A debe tener historia real de servicio más reciente que B; B debe estar libre. Esa historia también entra en el inventario, nunca se fabrica con UPDATE.
2. Persistir F por ingreso ordinario y capturar su deadline natural `d1`. Antes de S, una conexión independiente observa W READY no reclamado, B libre, historia de ambas orgs y `d1` dentro del horizonte nativo. Vincular el snapshot **previo** al `selection_id` real.
3. Registrar la selección real vacía y el retorno/yield del poll. Debe verificarse que no hubo candidato seleccionado ni llamada a claim para W en ese poll. Un claim que devuelve `None` es otro evento y no satisface esta frontera.
4. Sólo después de ese yield, una corrección ordinaria C de la conversación de F debe completar su outer commit **antes de `d1`**, desplazando naturalmente F a `d2 > d1`. Capturar la transacción y el cambio de deadline; no utilizar una consulta posterior para inventar la relación causal con S.
5. Cruzar `d1` con DB real y observar la ausencia de la elegibilidad pronosticada, causada por C. Esto es miss del forecast, no miss de claim. Una consulta posterior corrobora el estado; su causa la prueban los eventos anteriores.
6. Observar una segunda elegibilidad futura y su transición natural a READY, seguida por selección/claim/outer commit reales. Si se exige el mismo waiter aún pendiente hasta esta segunda frontera, demostrarlo en todos los journals; no esconder un claim intermedio. La edad de W nunca se reinicia y su claim definitivo conserva `rW`.

**Condición nueva:** una corrección de la conversación futura causalmente posterior al yield y anterior a su deadline, con dos planners libres y el patrón base completo. La receta finita acreditada usaba comandos de poll, otros participantes detenidos y una conversación de historia adicional; ese control no constituye esta nueva condición concurrente. La repetición con base observó 629 selecciones y ninguna vacía, aunque sí hubo coexistencias READY/futuro. [Resumen causal anterior](../d29-dependent-2026-10-07/matrix-existing/matrix-existing-R104-forecasts/causal-observation-summary.json).

**Restricción de realizabilidad:** el pacing base por org es `60 / 1,9607508002652434 ≈ 30,60052302 s`. No incluye dos llegadas de la misma org dentro de los 8 s que permiten una corrección pre-READY. Además, después de desplazar un deadline mediante una corrección tardía, la elegibilidad suele quedar fuera del horizonte de 1 s; un planner libre puede reclamar W en el poll siguiente. Mantenerlo artificialmente esperando hasta `d2` exigiría otra condición no incluida en la oferta actual. Una pausa accidental del host/emisor no es una receta reproducible.

Por ello, esta cadena es una **especificación física verificable**, pero no presento una receta ejecutable garantizada bajo todas las restricciones vigentes. No inyecté correcciones extra, no retuve planners y no cambié el pacing. Antes de implementarla hay que resolver si se autoriza un patrón causal de evaluación adicional, cómo se contabiliza C y si W debe seguir sin claim hasta la segunda elegibilidad. Si se mantiene literalmente el patrón actual, debe continuar `NOT_ACCREDITED`. La frontera finita previamente aceptada se conserva, sin sumarla artificialmente a una corrida de carga separada.

**3. Población: R1-06 y R2-02 son problemas distintos**

La base física tiene 2 organizaciones × 3 conversaciones = 6 conversaciones, con rotación de tres slots por organización. No establece cobertura para 4 conversaciones por organización. [Análisis reproducible con ledgers y hashes](population-analysis.json).

| Aspecto | Base aceptada | R1-06 | R2-02 observado |
|---|---|---|---|
| Población | 3 conversaciones/org | `ceil(1,9607508002652434 × 2) = 4` episodios READY distintos/org al corte previo al arranque | Se mantuvieron 3 conversaciones/org |
| Diferencia | 6 conversaciones totales | 8 en total: +1/org, +33,33% de población | No aumentó población; cambió la relación entre inputs y episodios bajo bloqueo |
| Oferta / episodio | La confirmación observó demanda sin esa retención | Con workers detenidos, 4 inputs repartidos en 3 conversaciones no crean 4 episodios simultáneos distintos | 24 aceptaciones durables → 23 episodios: 11 en org afectada y 12 en la otra |
| Evidencia | Receipt de R1-02 | Rechazo antes del primer ingreso del backlog; no se ejecutó esa condición | Inputs 4 y 13 comparten conversación 3 y work 9; se conserva el origen READY del input 4 |

R2-02 retuvo una llamada durante **120,009126 s**. Los inputs 4, 7, 10 y 13 de la org afectada llegaron a los 21,069858; 51,668145; 82,268919 y 112,868271 s desde el inicio del bloqueo. Son cuatro ingresos mientras N=1 impide otro claim de esa org. Con tres conversaciones sólo hay tres grupos nuevos no reclamados posibles; rotar de otra manera no garantiza cuatro episodios distintos. Esto explica el coalescing observado sin atribuirlo a pérdida de mensajes ni a fallo de runtime. El generador y el gate habían supuesto 1 input = 1 episodio para una condición que no lo conserva.

| Opción solicitada | Compatibilidad R1-06 | Compatibilidad R2-02 |
|---|---|---|
| A. Fixture compatible con la base | No satisface cuatro episodios simultáneos usando sólo tres conversaciones. Cuatro mensajes no resuelven esa diferencia. | La población actual admite físicamente coalescing. No satisface por sí sola el gate actual de 24 episodios; requiere declarar la semántica de demanda del caso. |
| B. Extensión metodológica explícita | Autorizar una cuarta conversación exclusivamente para el desafío de backlog, con población ampliada etiquetada aparte y sin ampliar la cobertura de la base. | Autorizar demanda de fallo con inputs/episodios separados y base de la org no afectada intacta; o autorizar otro patrón/población del desafío. Es una decisión prospectiva, no un PASS retroactivo. |
| C. Nueva caracterización/base | Necesaria si se exige que cuatro conversaciones sean parte de una nueva población confirmada. No autorizada en esta fase. | Sólo si se exige confirmar como base una población/patrón distinto. No es una consecuencia obligatoria de observar coalescing. |
| D. Corrección de generador/coalescing | Cambiar la rotación no crea una cuarta conversación. Cambiar el coalescing del runtime está fuera de alcance. | Corregir la suposición del generador/evaluador puede ser parte de una solución aprobada. No basta cambiar `% 3`, retrasar inputs hasta un claim o contar dos veces el mismo episodio: eso altera pacing o unidad protegida. |

No se seleccionó A, B, C ni D. Recomiendo decidir primero qué población y semántica de demanda debe acreditar **cada** caso. Ninguna opción autoriza modificar la base o el runtime de forma implícita.

**4. R2-04: sólo la combinación que falta**

El reclaim individual sigue acreditado. La nueva prueba debe añadir oferta base concurrente alrededor de su expiración natural. La infraestructura en [reclaim_fixture.py](reclaim_fixture.py) reutiliza `crash_committed`, el testigo de outer commit, la muerte real del hijo y su salida de PostgreSQL; no crea otra implementación de reclaim.

Hay un conflicto temporal que un adapter correcto debe explicitar: lease de 900 s, frente a una oferta de 360 s y seguimiento de 240 s. Un crash al principio y una espera natural no caben en esa ventana. Acortar el lease o prolongar oferta base automáticamente está prohibido.

Propuesta de fases para revisar:

1. Preámbulo finito capturado desde antes del input: un work de una de las tres conversaciones de la org afectada, claim/commit/reserva reales y crash. Este input y toda su historia se conservan como cohorte de fallo, distinta de la ventana de oferta base.
2. Esperar naturalmente. Anclar el inicio de la ventana base a **una cadencia por org antes del expiry observado**, aproximadamente 30,60052302 s. Es una fase calculada desde la base existente, no una tasa nueva ni tuning. El deadline de 900 s permanece intacto.
3. Tener dos slots de planner y un sender preparados para la oferta base. El hijo muerto ocupa un slot previo y debe estar confirmado como terminado antes de su reemplazo; no añadir un tercer planner. Mantener rates, rotación, provider, batch, poll y los 360 s de oferta/240 s de seguimiento existentes.
4. Observar expiry y reclaim reales durante esa oferta; conservar las aceptaciones de ambas orgs antes y después, progreso ordinario concurrente y drain. Si la realidad no solapa las fronteras, no acredita aunque el calendario lo prevea.

El nuevo gate rechaza un calendario sin cortes DB observados, reclaim temprano/fuera de ventana, falta de aceptaciones que lo rodeen o mezcla del input del preámbulo con la oferta base. Es un **gate adicional**, no un verificador completo de R2-04. Debe combinarse con los verificadores existentes de mismo work, membership, contexto, budget, fencing, concurrencia, clocks, demanda y cleanup. No se obliga a que el work recuperado emita otra llamada LLM: mantiene el deadline de turno original de 720 s; su resolución natural debe observarse sin reiniciar presupuesto o historia.

La condición nueva es un work fallido previo y una fase de oferta anclada al expiry. La población de conversaciones y la ventana de oferta base se conservan; cambian el inventario inicial y la duración total del intento. Esto requiere revisar la composición propuesta antes de conectar y ejecutar el conductor. No se extendió la base ni se implementó un sweep. [Manifiesto preparado](R204-fixture-preparation.json).

**5. R2-09: provider de evaluación corregido**

La versión histórica inyectó 9 resultados `UNCERTAIN` en LLM además de los resultados Meta y dejó 9 works sin testigo de servicio LLM en la reconstrucción. Esa corrida no es evidencia positiva ni negativa del runtime. Se preservaron los archivos originales. [Diagnóstico histórico](../d29-dependent-2026-10-07/closing-diagnostics.json).

[evaluation_provider.py](evaluation_provider.py) restringe el fallo a `R2-09 + uncertain_meta + org objetivo + boundary meta`. Las ramas LLM y HTTP interno conservan el servicio contenido ordinario. Mantiene 0,5 s por llamada LLM, 0,1 s HTTP interno y 0,2 s Meta; `slow_meta` conserva el multiplicador ya declarado. No se consume ningún proveedor real.

Cada dispatch/result incorpora `run_id`, rol/PID, `call_id`, frontera, revisión del provider y `fault_id`. Meta exige admisión de sender y `message_id`; LLM conserva work/epoch/fingerprint, ordinal de llamada, admisión durable y N=1. El verificador adicional comprueba correlación, scope, tiempos y presencia de servicio para los works reclamados; no crea testigos faltantes ni modifica `CLAIMED_WORK_WITHOUT_SERVICE_WITNESS`. La prueba offline ejecuta el método corregido con dependencias falsas y comprueba dos respuestas LLM normales seguidas de incertidumbre sólo en Meta, además del aislamiento por org/frontera y casos negativos.

El overlay se instala explícitamente en **cada proceso** mediante [worker_entry.py](worker_entry.py); cambiar sólo una clase en el padre no basta con procesos Windows. El provider histórico queda intacto por procedencia y no debe usarse para una nueva prueba `uncertain_meta`. El overlay debe congelarse y hashearse en el próximo laboratorio autorizado.

Esto demuestra aislamiento lógico de la inyección. La ausencia física de works sin servicio debe comprobarse nuevamente con todas las admisiones/claims y los logs reales; no la doy por demostrada con mocks. También sigue pendiente el solapamiento Meta↔cola ordinaria en `slow_meta`: el intento anterior no mostró READY no reclamado durante las 12 llamadas afectadas. No se alargaron llamadas ni se añadió backlog para forzarlo.

**6. Qué cambia y qué se conserva de CONFIRMED_BASE**

Se añaden archivos de evaluación, diagnóstico del host, captura de continuidad, correlación de fault y preparación de fases. No se modifica ningún archivo previo, contrato, runtime ni receipt de base. Se mantienen 2 orgs, 3 conversaciones/org, las tasas exactas del receipt, patrón/pacing declarado, 2 planners + 1 sender, batch=1/poll=1 s, servicio contenido, PostgreSQL durable, clocks correlacionados, ventanas y bound existentes.

R1-04 requiere una decisión sobre un patrón causal adicional. R1-06 requiere una decisión de población. R2-02 requiere una decisión de demanda durante fallo. R2-04 propone un inventario inicial y anclaje temporal de fallo declarados. Ninguno se incorpora silenciosamente a la base. El resultado no es E, capacidad máxima, capacidad comercial ni nueva caracterización.

**7–9. Repeticiones propuestas y evidencia nueva necesaria**

No hay repeticiones autorizadas automáticamente en esta entrega. Después de revisar las decisiones, el alcance mínimo sería:

| Caso / variante | Qué repetir | Evidencia nueva indispensable |
|---|---|---|
| R1-03 unequal | Sólo el intento de carga final invalidado por clock. | Base/job/overlay con hashes, oferta 2:1 con cadencia global común, aceptaciones, cuatro journals continuos, eventos de host y restauración de la protección, verificadores de carga e invariantes. |
| R1-04 forecasts | Condición concurrente completa, sólo tras resolver la receta. | Cadena de seis pasos con pre-query/selection_id/commits reales, todos los planners, origen y edad de W, correcciones declaradas y conciliación de pacing/episodios. |
| R1-06 backlog | Primera ejecución física válida, tras decisión de población. | Población autorizada, ledger previo al arranque, workers detenidos, cuatro episodios/org si ésa sigue siendo la exigencia, READY natural, corte de arranque, edades y drain completo. |
| R2-02 blocked | Demanda de fallo con semántica aprobada. | Inputs y membership reconciliados por episodio, hold real tras admisión, progreso de la org no afectada, liberación, edad original y resolución; sin asumir 24=24. |
| R2-04 postcommit + base | Sólo la combinación nueva; no reabrir la acreditación individual. | Preámbulo declarado, exit OS/DB, lease original, misma historia/budget/fencing, cortes y aceptaciones base que rodeen reclaim, dos slots planner, obligaciones y cleanup. |
| R2-09 uncertain_meta | Corrida nueva con provider corregido. | Fault IDs únicamente Meta, admisiones/outbox correlacionados, servicio LLM completo, cola ordinaria concurrente, autoridad sender y ausencia de retry ciego. |
| R2-09 slow_meta | Sólo la condición de cola que faltó. | Intervalos que demuestren READY no reclamado solapando dispatch→result Meta, progreso ordinario y evidencia sender. Una cola consultada después no satisface el requisito. |

**No necesitan repetirse ahora:** R1-01; R1-02 y sus confirmaciones de base; ambas variantes de R1-05; R1-07; R2-01; R2-03; R2-05; R2-06; todas las variantes de R2-07, R2-08 y R2-10. El reclaim finito de R2-04 y las fronteras finitas aceptadas de R1-03/R1-04 siguen aceptados. Sus receipts son referencias; no se combinan para inventar una acreditación de carga faltante. Tampoco se repite la matriz completa de 17.

Las decisiones previas a ejecutar son: (i) condición causal adicional/semántica de W para R1-04; (ii) opción de población para R1-06; (iii) semántica de inputs/episodios bajo bloqueo en R2-02; (iv) composición de preámbulo/ventana propuesta para R2-04; (v) autorización de probes individuales con la instrumentación corregida. Para `slow_meta`, si el patrón exacto no produce solapamiento con cola, se conserva pendiente; no hay autorización implícita para forzarlo. Ninguna decisión está preseleccionada ni habilita una matriz automática.

**Validación de esta preparación y límites de la entrega**

[Pruebas offline](offline-tests-02/receipt.json): 16/16 pasan, sin DB ni llamadas a la API de energía. Verifican aislamiento del provider, preservación de tiempos, controles negativos de correlación/servicio, rechazo de clocks históricos inválidos, captura íntegra, restauración de mocks y rechazo de calendario como prueba de reclaim. El [primer intento](offline-tests-01/receipt.json) se conserva: falló un stub de respuesta HTTP al que faltaba `headers`; se corrigió el stub, sin cambiar el resultado histórico del runtime.

No se reejecutó la regresión física D29 ni la de aplicación en esta fase: los 78/78 y 231/231 de la entrega anterior siguen siendo resultados históricos, no resultados nuevos. Los componentes nuevos requieren integración y validación física en el laboratorio privado después de esta revisión. Un test offline, un manifiesto o un gate adicional que pasa nunca produce `PHYSICALLY_ACCREDITED`.

La integridad inicial verificó 3.409 fuentes protegidas y 3.966 artefactos históricos, incluidos los intentos fallidos. La auditoría final y el índice de esta entrega se conservan en `final-integrity.json` y `artifact-index.json`. Todo cambio de esta fase queda dentro de este directorio; ningún cambio previo del usuario se restaura ni se descarta.
