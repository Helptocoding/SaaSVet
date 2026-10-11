**Dos decisiones independientes; ninguna aplicada ni ejecutada**

`CONFIRMED_BASE_ESTABLISHED` continúa con dos organizaciones y tres conversaciones por organización. No se cambia su receipt, hashes, tasas, pacing, coste, concurrencia, clocks ni ventanas. Los resultados históricos permanecen exactamente como fueron emitidos.

**R1-06 — recomiendo B: población explícita del escenario**

El requisito de backlog previo al arranque es `ceil(R_base_org × 2 min) = ceil(1,9607508002652434 × 2) = 4` episodios simultáneos por org. Antes de cualquier claim, cuatro mensajes en tres conversaciones no crean cuatro episodios distintos. El arranque tardío, la agrupación y W2 tampoco permiten fabricar el cuarto episodio sin cambiar la condición de workers inicialmente detenidos.

| Opción | Qué permite | Consecuencia para acreditación | Recomendación |
|---|---|---|---|
| A. Mantener 3 conversaciones/org | Conservar exactamente la población base | R1-06 permanece `NOT_ACCREDITED / NOT_REALIZABLE_UNDER_CURRENT_BASE_POPULATION`. No reducir el backlog exigido ni contar mensajes como episodios. | Correcta si se prioriza identidad total de población; no cierra la brecha. |
| B. Añadir una cuarta conversación sólo en R1-06 | Crear físicamente los 4 episodios/org antes del arranque | Puede acreditar ese desafío de backlog si se aprueba prospectivamente como extensión específica. El receipt declara 2×4 y referencia 2×3 como origen de R_base; no confirma la población ampliada como base. | **Recomendada para cerrar esta frontera sin nueva caracterización.** |
| C. Nueva caracterización/base | Confirmar explícitamente una población nueva | Requiere autorización separada para caracterizar y confirmar; produciría otra base con otra procedencia. No es necesaria para observar el desafío finito si se aprueba B. | Fuera de esta fase. |
| D. Tres conversaciones y menos episodios, o backlog repartido en oleadas | Medir una condición distinta | No satisface cuatro episodios coexistentes antes de arrancar. Puede servir como control adicional, pero no sustituye R1-06. Cambiar el requisito requeriría otra decisión. | No usar para declarar cierre. |

Con B, usar 8 conversaciones totales exclusivamente en el namespace del escenario. La cuarta de cada org sirve al backlog; las tres originales conservan la rotación/pacing de la oferta ordinaria base posterior. No se distribuye silenciosamente la oferta ordinaria entre cuatro slots. La cuarta conversación y su episodio permanecen en el denominador del escenario y del drain, aunque no reciban nuevos inputs después del arranque. Se declara esa asimetría prospectivamente.

Antes del arranque: capturar 8 aceptaciones durables, cuatro conversaciones distintas por org, READY natural e identidad/edad de cada episodio, sin workers activos ni primer claim. Después: iniciar dos planners y un sender, conservar oferta base y seguimiento, registrar todos los claims y obligaciones hasta drain/corte. No resetear edad al arrancar.

PASS de la frontera específica requiere población ampliada aprobada, ocho episodios realmente coexistentes en el corte, clocks válidos, arranque posterior observado, oferta base declarada, cobertura completa y drain. Si sólo existen tres episodios/org, falta un origen, hubo un claim antes del corte o se cambió la rotación base, `NOT_ACCREDITED`. Cualquier exceso de espera se informa: la extensión no autoriza un nuevo bound de backlog ni una excepción comercial.

Impacto exacto: cambia únicamente la población del desafío y su inventario inicial, +1 conversación/org (+33,33%). La base permanece inmutable y su alcance sigue siendo 2×3. Un futuro reporte dirá «R1-06, fixture 2×4 derivada de la tasa de la base 2×3», nunca «base ampliada confirmada».

**R2-02 — recomiendo una relación explícita de unidades**

La unidad de **oferta** es el input; la unidad de **espera/progreso y cola READY** es el episodio; la conversación delimita la identidad/población; el work representa el claim durable y sus intentos/servicio. Ninguna de estas unidades sustituye a todas las demás.

| Unidad | Uso propuesto | Lo que no demuestra por sí sola |
|---|---|---|
| Input / intento | Pacing real, emisión, aceptación durable, duplicado, rechazo o incertidumbre. Se conserva el ledger completo. | Cada input no garantiza un episodio nuevo. |
| Episodio READY continuo | Denominador de edad/claim/pendientes. Identidad por run, org, conversación, primer miembro y ordinal. | No prueba por sí solo que el emisor ofreció la carga prevista. |
| Conversación | Población y ámbito de agrupación; tres slots/org en esta propuesta. | No cuenta un work por mensaje ni una sola obligación para toda su vida. |
| Work | Membership fijado, ownership, N=1, servicio admitido y recuperación. | Retry/reclaim no son inputs ni episodios nuevos; completion no reemplaza la frontera de claim. |
| Relación entre ellas | Cada aceptación se asigna a un episodio u obligación conservada; cada claim nuevo apunta a sus miembros reales y a su org; W2 postclaim queda separado. | Un cociente global no permite esconder episodios perdidos o sin claim. |

La propuesta conserva **el mismo generador y pacing** en ambas orgs, las tres conversaciones por org y el hold LLM real de 120 s después de admisión. No modifica `% 3`, no espera claims para emitir, no añade conversaciones y no acorta el bloqueo para producir una igualdad de conteos.

La extensión metodológica que requiere aprobación es específica de R2-02: durante el fallo, declarar desde el plan que la org afectada puede agrupar varios inputs en un episodio; reemplazar exclusivamente la exigencia universal `inputs aceptados == episodios READY` por conciliación causal exhaustiva. Conservar la condición base y sus gates de oferta/progreso en la org no afectada. La regla de D29 §2 que permite varios mensajes por episodio ya existe; la adaptación aclara cómo aplicarla en este caso de fallo frente al supuesto de demanda principal de §6. No se edita el contrato ni el gate en esta entrega.

La conciliación futura debe probar:

1. Todos los intentos tienen resultado explícito. Ninguna aceptación durable desaparece por no haber claim.
2. Los miembros de los episodios y obligaciones forman una partición de los inputs durables de la cohorte, sin doble conteo. Un input pre-READY o preclaim puede agruparse; uno postclaim abre W2 según el corte real. Duplicados técnicos se identifican aparte.
3. El origen de cada episodio es el primer READY continuo observado. Un segundo miembro no reinicia su edad. Cada claim contado tiene membership y outer commit; las recuperaciones no duplican episodios.
4. La llamada objetivo tiene admisión durable antes de ser retenida; el hold y su liberación se observan. La otra org conserva oferta base real y tiene progreso durante el hold; los clocks, N=1 y autoridad siguen válidos.
5. Al corte, claims, pendientes, edades, servicio y obligaciones están conciliados por org. Los mismos gates temporales/invariantes aplicables siguen siendo exigibles: esta decisión no vuelve aceptable un exceso ni fabrica una excepción de E.

**El resultado histórico sigue siendo 24 inputs → 23 episodios**, con los inputs 4 y 13 en la misma conversación/episodio. Sigue invalidado para el plan que exigía otra demanda; no se actualiza su estado ni se utiliza como acreditación nueva. Tampoco se prescribe que la siguiente corrida tenga 23 episodios: el conteo se reconstruye de sus propios eventos.

Una futura ejecución puede acreditar la frontera de R2-02 con 24 inputs y 23 episodios si todos los miembros, edades, claims/pendientes y gates aprobados se conservan y el plan prospectivo autoriza esa semántica. No puede afirmar que ofreció 24 episodios independientes. Si falta un miembro/testigo, se altera pacing, no hay progreso de la otra org o el hold no queda observado, `NOT_ACCREDITED`; si captura/clock/plan son inválidos, además `INVALID_RUN`.

Impacto exacto: **ninguno sobre CONFIRMED_BASE**. Cambia una regla de evaluación del escenario de fallo, no la población, generación, tasas ni unidad temporal protegida. No requiere una nueva base porque no se afirma compatibilidad de una carga nueva. Requiere aprobación antes de implementar el gate específico o ejecutar la repetición.

Estas recomendaciones son independientes: se puede aprobar B para R1-06 y rechazar la propuesta de R2-02, o al revés. No se ha aplicado ninguna ni se ejecutarán automáticamente.
