**D29 — decisiones metodológicas propuestas y validación mínima del provider**

Estado conservado: `CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY`. `CONFIRMED_BASE_ESTABLISHED` permanece intacta. Ninguna propuesta de este documento está aplicada como cambio contractual ni autoriza automáticamente una ejecución.

La única ejecución física de esta fase fue la validación mínima de infraestructura del provider, expresamente autorizada en el punto 5 del encargo. No se ejecutaron probes de acreditación, matriz, caracterización, sweep ni cálculo de E. Los intentos fallidos de preparación también se conservaron. No hay commits ni cambios de runtime, B8, B9 o E4.

**1. Decisión propuesta para R1-04**

Recomiendo tratarlo como una extensión causal finita independiente del patrón base, con aprobación expresa de su población/patrón y de la cobertura que puede acreditar. Con las restricciones actuales se mantiene `NOT_ACCREDITED`.

La condición adicional no es simplemente «añadir una corrección»: después de corregir al peer, éste sale del horizonte de 1 s y un planner libre puede reclamar al waiter antes de la siguiente elegibilidad. Para conservar el mismo waiter a través de la cadena larga sin detener planners, haría falta una secuencia de futuros reales y correcciones ordinarias que cubra ese intervalo. La [propuesta separada de R1-04](R104-propuesta-metodologica.md) responde las seis preguntas del encargo y hace explícito un ejemplo de fixture con 17 conversaciones en la org de los forecasts, frente a 3 en la base. Es una construcción para estudiar en diseño, no una receta físicamente acreditada ni una ampliación aprobada.

No recomiendo declarar equivalente esa condición a la base. Si se exige mantener exactamente sus tres conversaciones y su pacing de aproximadamente 30,60 s/org, R1-04 debe continuar pendiente. No existe una receta reproducible demostrada bajo esas condiciones. No se implementó la extensión.

**2. Decisión propuesta para R1-06**

Recomiendo **B: una cuarta conversación por organización sólo en la fixture de R1-06**, declarando 2×4 para el backlog y conservando 2×3 como alcance de la base. La cuarta conversación aporta el cuarto episodio previo al arranque; no se incorpora a la rotación de oferta ordinaria base posterior. Todas sus obligaciones y edades permanecen en el inventario/drain del escenario.

Mantener tres conversaciones es válido, pero deja el escenario no realizable bajo esa población. Nueva caracterización sólo sería necesaria si se pretende confirmar la población ampliada como otra base. Reducir el backlog o repartirlo en oleadas no satisface la frontera actual. [Comparación completa A–D](R106-R202-decisiones.md).

**3. Semántica propuesta para R2-02**

Recomiendo una relación explícita: **input para oferta; episodio READY continuo para espera/cola; conversación para población; work para claim, servicio y recovery**. Conservar tres conversaciones/org, pacing y hold existentes. Adaptar prospectivamente sólo el gate del escenario de fallo para permitir agrupación observada, exigiendo conciliación exhaustiva input→episodio→work y la oferta/progreso base de la org no afectada.

No exigir 24 episodios por aceptar 24 inputs. Tampoco fijar de antemano que la siguiente ejecución deba dar 23: se reconstruye su propia cohorte. El resultado histórico **24→23** sigue siendo el resultado observado e inválido para su plan anterior; no se corrige ni se convierte en PASS retroactivo. Los bounds e invariantes aplicables no se relajan. [Semántica y consecuencias](R106-R202-decisiones.md).

**4. Composición temporal final de R2-04**

Propuesta: crash/commit finito capturado, espera natural, y luego ventana base anclada a una cadencia por organización antes del expiry. Si C es el claim inicial, L=C+900 s y P≈30,60052302 s:

| Frontera | Tiempo propuesto desde C |
|---|---|
| Inicio oferta base S=L−P | ≈869,39947698 s |
| Expiry natural | 900 s |
| Fin oferta S+360 | ≈1229,39947698 s |
| Fin seguimiento S+600 | ≈1469,39947698 s |

Dos slots de planner, sin tercero: el proceso muerto se reemplaza después de acreditar su salida. El lease, pacing, 360 s de oferta, 240 s completos de seguimiento, membership, historia, budget y fencing permanecen intactos. El preámbulo añade inventario de fallo y duración total, no oferta sostenida adicional.

El calendario demuestra que el solapamiento **cabe**; no que ocurrió. Esa demostración física sigue pendiente porque no se ha autorizado ejecutar el probe. Para acreditarlo harán falta expiry/commit de reclaim reales, cortes de ventana, oferta emitida y aceptaciones de ambas orgs antes y después, continuidad de pacing y obligaciones concurrentes. Si no cabe según los hechos de preparación, no se inicia la oferta; si en ejecución no ocurre, queda `NOT_ACCREDITED`, sin mover ventanas. [Calendario, precondiciones y gates completos](R204-composicion-temporal.md).

**5. Validación física mínima nueva de R2-09**

Resultado: **`PROVIDER_INFRASTRUCTURE_VALIDATED`**, confirmado por el driver y un verificador independiente que relee los eventos, identidades y testigos DB. No se acreditó R2-09 completo.

| Evidencia nueva | Resultado |
|---|---|
| Ingress/episodios/work | 2 inputs ordinarios aceptados → 2 episodios → 2 works completados. |
| LLM | 4 llamadas admitidas y registradas, dos por work; 4 respuestas ACCEPTED; ninguna excepción/timeout LLM inyectado. |
| HTTP interno de dominio | 2 llamadas reales al endpoint interno contenido; sin excepción del provider. |
| Meta objetivo | Un resultado UNCERTAIN, relacionado con admisión y mensaje outbox de la org objetivo. |
| Meta de la otra org | Una aceptación normal; la inyección no cruzó de organización. |
| Fault ID | `provider-isolation-minimal-03:sender:57812:2:uncertain-meta`, idéntico en dispatch/result y ligado al message_id. |
| Windows | planner_1 PID 50460, planner_2 PID 47436, sender PID 57812. Ambos planners ejecutaron LLM. Los tres cargaron el provider aprobado con el mismo hash; los patches se restauraron al terminar. |
| Servicio sin cambio de parámetros | LLM declarado 0,5 s: observado 0,5026958; 0,5007856; 0,5064735; 0,5017351 s. Dominio declarado 0,1 s: observado 0,100411 y 0,1068808 s. Meta declarado 0,2 s: observado 0,2203232 y 0,2055596 s. |
| Invariantes | 6 testigos de dispatch, sin faltantes ni violaciones de membership, tenant, outer commit, admisión, N=1, HTTP fuera de transacción y contención. |
| Clock/host | Cuatro journals continuos, eventos System sin incidente invalidante en el intervalo y protección temporal restaurada. |

Las duraciones observadas son las esperas físicas del provider, incluido el exceso normal del sleep del host; no son un nuevo SLA ni una afirmación de coste total por turno. Se conservan las duraciones solicitadas y se verifica que ninguna fue acortada. No se estableció una tolerancia para hacerlas pasar.

La fixture mínima sólo ejercita un input por org y no reproduce la carga base: no se usa como medición de tasa, confirmación, condición de carga, ni cambio de población de CONFIRMED_BASE. No se provocó cola READY para `slow_meta`, cuya condición permanece pendiente. El receipt histórico defectuoso no se utilizó como evidencia del provider corregido.

Receipts: [verificación independiente](independent-provider-verification.json), [receipt del driver](provider-validation-03/provider-validation-receipt.json), [testigos DB finales](provider-validation-03/final-durable.json) y [esperas observadas](provider-validation-03/service-delay-observations.json).

Se conservan dos intentos previos sin inputs ni workers: el primero falló por importación de una fixture antes de `django.setup`; el segundo por bloqueo del arranque del recolector Windows. Se corrigió el orden de inicialización y se usó arranque oculto mediante STARTUPINFO. El mismo script System funcionó con ese transporte; el gate no cambió. [Intento 1](attempt01-diagnosis.json), [intento 2](attempt02-diagnosis.json). No se atribuye ninguno de estos errores al runtime.

**6. Impacto exacto sobre la base y preparación R1-03**

| Decisión / trabajo | Cambio propuesto o realizado | Impacto en CONFIRMED_BASE |
|---|---|---|
| R1-03 | Probe listo con protección/monitor aprobados y transporte Windows corregido; no ejecutado. Intersección original, sin muestras excluidas, segmentación ni timestamp corregido. | Ninguno. Un fallo de continuidad sigue dando INVALID_RUN; la repetición anterior sigue inválida. |
| R1-04 | Extensión causal de población/patrón propuesta, no implementada. | No amplía su cobertura. Aprobar la extensión no confirma su carga como base. |
| R1-06 | Cuarta conversación exclusiva del backlog, propuesta B sin aplicar. | Base 2×3 intacta; futuro escenario 2×4 claramente separado si se aprueba. |
| R2-02 | Semántica de demanda de fallo propuesta, sin cambiar generador/runtime. | Ninguno: misma base, población y oferta; otro gate específico aprobado prospectivamente. |
| R2-04 | Preámbulo de fallo y anclaje a expiry, propuestos sin ejecución. | No cambian tasas/ventanas/población; el inventario inicial de fallo se declara aparte. |
| R2-09 | Provider corregido validado físicamente en un laboratorio mínimo aislado. | No se editó el provider/base históricos ni se generó otra confirmación. El overlay conserva el servicio declarado y queda identificado por hash. |

Receipt de base inmutable: SHA-256 `71c3e58c34decfac1698f9517f39b4d7cbc936c0463e35a4bbfe00ee04920a56`. Baseline `825db75df68bf076929fa787e77beefe96803350`. No cambian tasas, población confirmada, número de conversaciones, planners/sender, batch/poll, ventanas, clocks, provider contenido histórico ni sus receipts/hashes.

R1-03 queda preparado en [r103-prepared/prepared_probe.py](r103-prepared/prepared_probe.py), con [manifiesto de preparación](R103-readiness.json). El timeout del comando recolector sólo falla ante infraestructura no disponible; no es una tolerancia temporal del gate. No se ejecutó ese probe ni se alteró PostgreSQL/NTP/plan de energía persistente.

**7–8. Lista exacta de probes autorizables y criterios**

Todos requieren **otra autorización de ejecución**. R1-04 requiere además aprobar su cobertura y cerrar el diseño reproducible; hoy no está listo para arrancar. Aprobar este análisis no ejecuta automáticamente ninguno.

| Probe individual | Decisión previa necesaria | PASS de la frontera de evaluación | NOT_ACCREDITED |
|---|---|---|---|
| R1-03 `unequal` | Autorizar repetición con infraestructura preparada. | 2:1 físico, misma cadencia global, población base, aceptaciones/episodios, concurrencia e invariantes; cuatro clocks y eventos System válidos; cleanup. | Falta de continuidad, carga/población distinta, evidencia incompleta o gate original fallido. Clock inválido conserva INVALID_RUN. |
| R1-04 `forecasts` con extensión declarada | Aprobar patrón/población y alcance de cobertura; cerrar receta antes de ejecutar. | Mismo waiter atravesando la cadena causal completa, pre-query real, yield sin claim miss, corrección committed, nuevo deadline natural, claims y edad original con todos los participantes libres. | Claim intermedio, hueco de forecast, corrección tardía, manipulación de clocks/planners o frontera no observada. No sustituir la carga base por esa fixture sin declarar el alcance. |
| R1-06 `backlog` 2×4 | Aprobar B o escoger otra opción. | Cuatro episodios distintos/org coexistiendo READY antes de arrancar, ocho orígenes completos, oferta base posterior declarada, edad conservada y drain. | Sólo cuatro mensajes en tres episodios, arranque previo al corte, origen desconocido, cambio oculto de rotación o drain no resuelto. |
| R2-02 `blocked`, semántica explícita | Aprobar conciliación de demanda bajo fallo antes de adaptar el gate. | Hold real de 120 s tras admisión, oferta base/progreso peer, todos los inputs asignados a episodios/obligaciones, servicio/claims y edad sin reset, gates aplicables válidos. | Input perdido/no conciliado, igualdad de conteos fabricada, pacing cambiado, falta de liberación/progreso o evidencia temporal inválida. |
| R2-04 `postcommit + base` | Aprobar preámbulo/anclaje y completar composición del conductor. | Expiry natural 900 s y reclaim real dentro de la ventana de oferta 360 s, 240 s de seguimiento íntegro, carga concurrente observada, dos slots planner, historia/budget/fencing y drain. | Solapamiento sólo nominal, reclaim fuera de ventana, tercer planner, lease/budget/historia alterados u obligaciones sin resolver. |
| R2-09 `uncertain_meta` | Autorizar el escenario tras esta validación de infraestructura. | Faults sólo Meta/org objetivo, LLM completo por work, correlación sender/outbox, cola ordinaria concurrente real y ausencia de retry ciego. | Fault fuera de frontera, work sin testigo, cola no observada, autoridad inconsistente o captura insuficiente. |
| R2-09 `slow_meta` | Autorizar observación natural con parámetros intactos. | Meta lento según parámetro existente y solapamiento físico con READY no reclamado; progreso ordinario, autoridad independiente y trazabilidad. | Si la cola no aparece naturalmente, queda pendiente; no aumentar retrasos, añadir backlog ni retener planners para forzarla. |

PASS de una frontera finita no es PASS comercial. Excesos, censuras o incertidumbres se conservan y reciben la disposición del protocolo; ninguna propuesta introduce excepciones comerciales o cambia B_conv. No se declara `FULL_CONTROLLER_ACCREDITED`.

No se propone repetir R1-01, R1-02/confirmaciones, R1-05, R1-07, R2-01, R2-03, R2-05, R2-06, R2-07, R2-08 ni R2-10; tampoco un reclaim individual adicional. Las fronteras finitas previas siguen aceptadas. No hay autorización para una matriz completa, aun si se aprueban todas las decisiones anteriores.

El cierre del laboratorio, integridad y conservación de intentos se registra en `lab-cleanup.json`, `complete-final-integrity.json` y el receipt final de esta fase. La entrega termina aquí, para revisión de estas decisiones.
