# D29 — Entrega de ejecución autorizada, 10 de octubre de 2026

Se implementó el harness y se completaron las ejecuciones autorizadas en el orden
del [plan rector](PLAN-RECTOR.md). Cuatro escenarios físicos están ACCREDITED;
R1-04 permanece PENDING con una limitación medida. El plan completo no está
cerrado: falta decidir sobre esa limitación. No se inicia otro intento ni la matriz.

| Escenario | Estado final | Resultado autoritativo |
|---|---|---|
| R1-06 backlog | ACCREDITED | [scenario-result.json](r106-prospective-01/scenario-result.json) |
| R2-09 uncertain_meta | ACCREDITED | [scenario-result.json](r209-uncertain-01/scenario-result.json) |
| R2-09 slow_meta | ACCREDITED | [scenario-result.json](r209-slow-01/scenario-result.json) |
| R1-04 forecasts | PENDING | [scenario-result.json](r104-passive-01/scenario-result.json) |
| R2-04 reclaim | ACCREDITED | [scenario-result.json](r204-intact-01/scenario-result.json) |

El código nuevo y la evidencia están sólo en este directorio. `native_witnesses.py`
captura el guard desde su SELECT nativo, el terminal desde su CAS transaccional y
el contexto realmente renderizado antes del primer LLM del sucesor.
`scenario_entry.py`, `launch_bridge.py` y `evaluation_provider.py` conectan las
variantes Meta separadas. `forecast_observer.py` observa antes de la selección
nativa, sin retener workers ni insertar correcciones. Los fuentes exactos de cada
ejecución y de las verificaciones reparadas están archivados con SHA-256.

Validación del harness: **97 controles distintos exitosos** en
[offline-validation-10.json](offline-validation-10.json) y **4 pruebas PostgreSQL
exitosas** en [adapter-02](adapter-02/execution-receipt.json). Estas validaciones
son controles de infraestructura; la acreditación física procede de las capturas
de cada escenario. Se conserva `adapter-01`, incluido el error inicial de firma
del mock HTTP, corregido únicamente en el test.

## R1-06 — seis puntos de cierre

1. **ACCREDITED**: todos los gates aplicables cumplidos.
2. Un intento prospectivo, oferta 360 s y seguimiento completo 240 s, 32 inputs
   (8 iniciales y 24 ordinarios), 31 episodios/works, 62 llamadas LLM y 30 Meta aceptadas.
3. Un diferimiento nativo y un sucesor causal demostrados mediante los tres
   testigos. Demanda, invariantes, ventanas, reloj y host válidos.
4. La conexión inicial del verificador invertía los argumentos de rollback y
   comparaba representaciones distintas del mismo instante. El bridge adapta
   argumentos y UTC exacto, con cinco controles; conserva criterios y fuentes
   originales. Se concilió la misma captura, sin repetir la prueba física.
5. Base, contratos y artefactos protegidos intactos; workers exit 0, DB retirada
   sin clientes. Fallo provisional y reparación v2 preservados.
6. Siguiente paso ejecutado: las siete suites de regresión secuenciales.

## Siete regresiones — seis puntos de cierre

1. **ACCREDITED como regresiones**, 192/192, cero skips, fallos o errores.
2. Cada suite original se ejecutó sola en una DB privada nueva:

   | Suite | Pruebas |
   |---|---:|
   | test_b4_sender | 42 |
   | test_w1_monotonic | 12 |
   | test_b5_safety | 30 |
   | test_operation_execution | 53 |
   | test_b9b_budget | 28 |
   | test_b9c_concurrency | 18 |
   | test_b9c_processes | 9 |

3. [sequential-regressions.json](sequential-regressions.json) enlaza todos los
   receipts. Monitorización antes/durante/después; no se observó OOM.
4. Ninguna corrección del runtime ni de las suites fue necesaria.
5. Fuentes preservadas, siete DB retiradas, cero clientes remanentes.
6. Siguiente paso ejecutado: uncertain_meta. La causa del OOM histórico continúa
   **sin resolver**; el éxito de estas ejecuciones no la explica.

## R2-09 uncertain_meta — seis puntos de cierre

1. **ACCREDITED** por [verificación v3](r209-uncertain-01/physical-verification-v3.json).
2. Un intento independiente 360/240, cohorte inicial natural 2×3, 30 inputs,
   28 episodios/works, 56 LLM y 28 Meta: 14 ACCEPTED y 14 UNCERTAIN.
3. Un solapamiento natural definido y 12 progresos ordinarios de la organización
   par; todos los gates y el guard estricto de reloj pasan.
4. El launcher Windows introduce un intérprete intermedio. Se verificaron las
   cadenas nativas realmente capturadas, repetidas en snapshots contemporáneos,
   con siete controles. El censo independiente sellado sustituyó únicamente la
   lectura de la DB ya retirada, con tres controles de exactitud. El resto de
   gates se conservó; no hubo nueva ejecución física ni reconstrucción de estado.
5. Receipt provisional, captura, fuentes y conciliaciones preservados; workers
   exit 0, DB retirada sin clientes. Verificadores originales protegidos intactos.
6. Siguiente paso ejecutado después de revisar este resultado: slow_meta separado.

## R2-09 slow_meta — seis puntos de cierre

1. **ACCREDITED** por [verificación física](r209-slow-01/physical-verification.json).
2. Un intento independiente 360/240, 30 inputs, 29 episodios/works, 58 LLM,
   28 Meta ACCEPTED y cero UNCERTAIN.
3. Dos solapamientos naturales, 12 progresos ordinarios de la organización par,
   un diferimiento con sucesor causal; todos los gates y reloj/host válidos.
4. Sin reparación adicional de esta ejecución; usa las adaptaciones verificadas.
5. Fuentes protegidas intactas; workers exit 0 y DB retirada sin clientes.
6. Siguiente paso ejecutado: investigación física finita de R1-04.

## R1-04 — seis puntos de cierre

1. **PENDING**: falta demostrar la secuencia forecast → selección vacía/yield →
   corrección comprometida posterior → forecast obsoleto → nueva elegibilidad/claim.
2. Un único intento 360/240 con los 24 inputs ordinarios del calendario base,
   dos planners libres, 24 episodios/works, 48 LLM y 24 Meta ACCEPTED. El fixture
   concentrado preliminar se descartó antes de ejecutarlo; no se añadieron inputs,
   holds ni cambios al planner/deadlines.
3. 1.082 preconsultas y 1.058 selecciones vacías nativas; estas últimas fueron
   polling inactivo y no acreditan forecast-yield. Hubo siete coexistencias
   READY/futuro dentro del horizonte en organizaciones distintas: seis carecían
   de la recencia requerida y una tenía waiter sin claim previo. Sus selecciones
   devolvieron candidatos. Demanda, invariantes, ventanas, preparación y reloj/host
   pasan; la secuencia especial no se observó. Véanse
   [limitación](r104-passive-01/observed-window-limitation.json) y
   [predicados físicos](r104-passive-01/observed-predicate-blockers.json).
4. Se corrigió el cableado del receipt de cleanup usando salidas, procesos AFTER
   y clientes realmente capturados; cuatro controles. La
   [verificación v2](r104-passive-01/physical-verification-v2.json) conserva los
   gates y elimina ese error de conexión; el resultado físico sigue PENDING.
5. Fuentes protegidas intactas, workers exit 0, DB retirada sin clientes; captura
   y resultado provisional conservados. No se infiere imposibilidad universal.
6. **Decisión mínima pendiente**: aceptar esta limitación medida o decidir un
   fixture temporal compatible con las restricciones. La limitación todavía no
   ha sido aceptada. No hay repetición automática ni ampliación del alcance.

## R2-04 — seis puntos de cierre

1. **ACCREDITED** por el verificador original byte intacto, PASS con cero errores.
2. Un intento con prelude comprometido, muerte real de su worker, ausencia del
   backend y reemplazo libre. Expiración natural de lease de 900 s; oferta 360 s
   y seguimiento 240,6099271 s. W32Time permaneció Running/Automatic.
3. 25 inputs/episodios/works (1 prelude +24 ordinarios), 26 claims; un reclaim
   causal del mismo work, attempt 2 y nuevo lease, durante la oferta. Ambas
   organizaciones aceptaron antes/después. Historial, presupuesto, membresía,
   fencing, demanda, servicio, ventanas, reloj y host cumplen los gates originales.
4. Sin correcciones del verificador, fixture ni ejecutor original; no se precisó
   intervención sobre el servicio del host.
5. Fuentes y evidencia protegidas intactas; workers de reemplazo exit 0, muerte
   del prelude documentada y DB retirada sin clientes.
6. Siguiente paso: revisión de esta entrega y decisión pendiente de R1-04.

## Integridad y retiro del laboratorio

[precleanup-integrity.json](precleanup-integrity.json) documenta el sellado de
14 expedientes antes de limpiar. [final-integrity.json](final-integrity.json)
confirma las 3.409 fuentes protegidas, evidencia histórica y HEAD
`825db75df68bf076929fa787e77beefe96803350` intactos.
[lab-cleanup.json](lab-cleanup.json) confirma retiro del temporal privado, sus
credenciales y bases, y puerto cerrado. Los cambios previos del usuario permanecen.

No se modificaron runtime de producción, contratos, base confirmada, verificadores
originales ni W32Time. No se hicieron commits, tuning, caracterización, estimaciones
E ni matriz completa. [STATUS.md](STATUS.md) mantiene el registro acumulativo;
[execution-summary.json](execution-summary.json) distingue resultados y pendiente;
[resources-summary.json](resources-summary.json) conserva la monitorización de
los 14 intentos. `final-phase-receipt.json` referencia el índice SHA-256 final.
