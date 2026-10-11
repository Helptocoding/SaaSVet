# Límites de la acreditación dependiente

Este documento registra obstáculos de evaluación. No modifica D29 ni la base
aceptada y no autoriza cambios de población, oferta o runtime.

## R1-03: ejecución final con relación temporal inválida

El intento individual acreditó la oferta física 2:1. La repetición de la matriz
final `matrix-existing-R103-unequal` emitió y aceptó 24 inputs, pero no pudo
terminar la reconstrucción temporal: `ValueError: Reversed temporal interval`.
Las calibraciones conservadas de los cuatro participantes contradicen la
hipótesis de offset constante entre el reloj DB y el monotónico. Para ingress,
la intersección resulta invertida por 55.202.400 ns; no se aplica tolerancia,
ni se elimina ninguna muestra ni se sustituye la corrida por el PASS individual.

Es un fallo de validez de la evidencia temporal de esta ejecución, no evidencia
de exceso del bound ni demostración de una regresión del scheduler. Los datos
por sí solos no identifican qué ajustó el reloj del host. La consulta posterior
del registro System encontró el evento Kernel-General 1, record 317127, a las
21:26:44.5005053 UTC, dentro de la corrida: Windows informa sincronización con
el reloj de hardware y un cambio de 17.519 ms del reloj del sistema. Esto
documenta una discontinuidad real del host; no se equipara ese delta con los
55,2024 ms de contradicción entre DB y monotónico, ni se intenta corregirlos.
El registro se conserva en `host-clock-events.json`. El diagnóstico de
calibraciones, con líneas y hashes originales, queda en `clock-capture-audit.json`.
Una repetición futura debe conservar exactamente la base y todos los intentos;
si requiere modificar el modelo de clock o el host, primero debe autorizarse
esa modificación metodológica. No se cambia el clock durante esta fase.

## R1-06: preparación incompatible con la población aceptada

D29 §6 exige `ceil(R_base_org × 2 min)` episodios iniciales. La base aceptada
fija R_base_org=1.9607508002652434 y tres conversaciones por organización.
La receta física exige conversaciones distintas: el resultado es cuatro,
superior a los tres slots aceptados. `execution.execute_job` rechaza esa
preparación antes de la primera oferta y del arranque de workers.

No faltan primitivas de ingreso, READY natural, arranque ni drain. Falta una
decisión metodológica que permita ejecutar la condición con una población
suficiente sin atribuir la configuración modificada a la base anterior.
Cuatro mensajes coalescidos en tres conversaciones no satisfacen cuatro
episodios coexistentes. Reducir la cantidad o la tasa tampoco es admisible.

El receipt del intento conserva el rechazo de preparación, la población
requerida/aceptada y el cleanup. No se presenta como ejecución física del
backlog. Recomendación pendiente: aprobar explícitamente un plan de fixture
R1-06 con cuatro conversaciones por organización y definir el alcance de la
referencia a la base; no ejecutarlo bajo la autorización actual.

## R1-04: carga ordinaria no acredita la secuencia causal

La frontera finita aceptada tiene un testigo independiente anterior a la
selección real, un yield sin intento de claim, ingreso ordinario comprometido
que supersede el deadline futuro, nueva elegibilidad y claim del mismo waiter
sin reiniciar su origen. Sus gates mantienen otros participantes detenidos.
Ese control finito no preserva la concurrencia y pausa de la carga base.

El observador del ejecutor de series usa estado posterior y busca un miss de
claim. No demuestra el forecast previo ni un yield de selección y no puede
sustituir la secuencia anterior. La corrida de carga conserva sus ingresos,
journals, clocks y resultados, pero el receipt mantiene ausentes los testigos
causales que no fueron capturados durante esa misma corrida.

La infraestructura v3 añade, para la matriz final, lecturas independientes
anteriores y posteriores a cada selección real de ambos planners. Correlaciona
PID, selection_id, resultado nativo y clocks; comprueba cobertura y orden. No
retiene participantes, no añade ingresos y no cambia el loop ni la pausa del
worker. Los tests negativos rechazan una captura ordinaria sin esos testigos y
una consulta posterior presentada como testigo previo. Incluso con esas
lecturas, la coexistencia READY/futuro y una selección vacía por sí solas no
prueban el predicado de forecast ni una supersesión y elegibilidad posterior
del mismo waiter. Esa limitación permanece explícita en su receipt.

Resultado de la matriz final: 315 selecciones del planner 1 y 314 del planner 2,
con cobertura completa de testigos y sin errores de correlación. Cada planner
observó dos coexistencias READY/futuro entre organizaciones; ninguna produjo
selección vacía. Los 24 episodios quedaron resueltos y los 72 testigos de
invariantes pasaron, pero solo `ready_waiter` quedó acreditado en la receta.
`future_eligibility`, `forecast_miss` y `future_eligibility_again` permanecen
sin observar. Esta es la causa del rechazo, no un exceso temporal detectado.

No basta combinar la prueba finita anterior con una corrida ordinaria aparte.
Tampoco se añaden correcciones fuera del calendario aceptado ni se retienen
workers para forzar el resultado. Recomendación pendiente: especificar una
receta concurrente con testigos anteriores a la consulta, conciliación de
todos los commits que puedan cambiar su predicado y una inyección causal
declarada que preserve la oferta base. Si esa inyección altera el patrón
aceptado, requiere autorización metodológica expresa antes de ejecutarse.

## R2-02: frontera observada y condición de demanda no acreditada

La matriz final observó admisión LLM, bloqueo, progreso de la otra organización
durante el bloqueo y liberación tras 120,009126 s. El gate de la frontera física
pasó. Sin embargo, 24 aceptaciones durables produjeron 23 episodios: 11 en la
organización afectada y 12 en la otra. El gate de demanda conserva la violación
`COALESCED_DEMAND_NOT_DECLARED_READY_EPISODE_LOAD` y el resultado `INVALID_RUN`.
Los 24 miembros están conciliados, los 23 episodios se resolvieron dentro del
objetivo observado, no quedaron obligaciones pendientes ni violaciones de
invariantes observadas. Eso no convierte 23 episodios en la carga de 24
episodios declarada por el conductor.

Es un conflicto entre la condición de carga de la fixture, la población fija
de tres conversaciones por organización y la agrupación real durante el
bloqueo. No falta la primitiva de bloqueo/liberación, ni se demostró un fallo
de protección de edad. No se modifica el runtime para impedir la agrupación,
ni se reduce la oferta, ni se amplía la población de la base en esta fase.
Debe decidirse un plan posterior de fixture/carga que produzca la demanda
exigida y declare su relación con la base aceptada, o una revisión metodológica
explícita del requisito de demanda. No se aprueba ninguno automáticamente.

## R2-09: progreso posterior no demuestra cola concurrente

D29 §6 pide sender lento/incierto mientras hay cola ordinaria; §4 define la
cola Q como episodios READY aún sin claim nuevo committed. El verificador
original acredita admisión, dispatch, resultado y progreso ordinario posterior,
pero no comprueba la coexistencia de esa cola con el envío afectado. Se añade
una verificación física suplementaria por intervalos sobre los journals y
wire originales, sin consultas posteriores a DB ni ejecución/replay nuevos.

Para cada llamada Meta afectada se correlacionan comienzo/fin reales con el
clock del sender y los intervalos READY/commit de todos los episodios. Solo una
intersección demostrable entre servicio Meta y episodio definitivamente READY
y todavía sin claim satisface esta condición. No se exige un nuevo bound de
sender ni se convierte la entrega en O-C.

En la variante Meta lento, sus 12 llamadas afectadas no tienen tal
intersección demostrable. Su receipt original conserva PASS para sus checks;
la condición completa queda NOT_ACCREDITED en la evaluación suplementaria.
La variante incierta se examina con el mismo criterio al terminar. Los
resultados completos están en `sender-queue-overlap-verification.json`.

Falta una condición de carga/control que haga coexistir la cola ordinaria y
el sender afectado conservando la base, o una decisión explícita de alcance
metodológico si se pretende otro significado de concurrencia. No se alarga
Meta ni se retienen planners ni se altera el pacing para forzar esa condición
bajo esta autorización. El PASS de un verificador incompleto no cierra la matriz.

## Matriz y alcance de los adapters finitos

Cada variante ejecutada registra por separado su frontera física finita y su
condición de carga. Adjuntar la CONFIRMED_BASE a un adapter no ejecuta carga
base. Una variante puede conservar la frontera finita acreditada y tener la
condición de carga sin ejecutar. Para R2-04, D29 §6 exige explícitamente reclaim
con carga base; el adapter finito existente no satisface esa condición por
asociación. El estado global permanece FULL_LIVE_MATRIX_NOT_READY mientras
falte cualquier requisito físico. Los resultados definitivos se referencian
en el informe final y no se anticipan en este documento.
