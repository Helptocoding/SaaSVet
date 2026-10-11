# Cierre de probes individuales D29

Entrega final: 8 de octubre de 2026. La carpeta conserva la fecha de apertura de esta fase.

`CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY`
`CONFIRMED_BASE_ESTABLISHED` conservada. No se ejecutó matriz completa ni se creó un commit.

| Probe | Resultado | Inputs | Episodios | Works | Claims observados | Commits outer exitosos |
|---|---|---:|---:|---:|---:|---:|
| R1-03 | PASS | 24 | 24 | 24 | 24 | 279 |
| R1-06 | NOT_ACCREDITED | 32 | 31 | 31 | 31 | 361 |
| R2-02 | PASS | 24 | 23 | 23 | 23 | 265 |
| R2-04 | INVALID_RUN | 1 | No acreditable | 1 | 1 | 7 |
| R2-09 | NOT_ACCREDITED | 24 | 24 | 24 | 24 | 278 |

Los commits de esta tabla son los eventos outer `commit_end` exitosos de todos los journals. Los receipts de reconstrucción también cuentan por separado los commits con efectos de población (ingreso/claim); no son el mismo denominador.

## Condición ejecutada y evidencia

- **R1-03:** población 2×3, 2:1 sobre los mismos instantes de la cadencia global de la base; 16/8 aceptaciones reales, 24 episodios/works. Dos planners concurrentes y un sender; clocks originales y cortes System pasan.
- **R1-06:** ocho inputs de backlog, cuatro conversaciones/org, READY natural antes del primer claim; después 24 inputs ordinarios con rotación de tres slots. La cuarta no recibe oferta ordinaria. La frontera de backlog/origen/edad/drain pasa; el gate completo queda pendiente por coalescing (32→31) y por la conciliación de una salida suprimida mediante `deferred_to_new_input` ante input posterior. No se extiende automáticamente la excepción aprobada sólo para R2-02.
- **R2-02:** 2×3, pacing base, hold LLM de 120 s, 24 inputs→23 episodios/works con partición causal completa. La agrupación ocurre en la organización afectada; el peer recibe ofertas y progresa durante el hold. Intersecciones de clock válidas. No hubo captura System prospectiva en ese intento.
- **R2-04:** intento 0004 **INVALID_RUN**. El preámbulo tuvo commit/crash real y lease intacto de 900 s; el calendario quedó fijado S=L−P (P≈30,600523019 s). Antes de abrir oferta, Windows ajustó la hora +2,1357499 s (Kernel-General, RecordId 317254), seguido de +0,0005084 s. Ingress detectó intersección imposible en seq 11081; System también registra Time-Service. El monitor detuvo la corrida. **No hubo oferta base, reclaim acreditado ni los 240 s de seguimiento**. El único input/work de la tabla es del preámbulo; no se presenta como prueba de carga. No se corrige ni segmenta el reloj y no se cambia la hora del host.
- **R2-09 uncertain_meta:** 2×3, 24 inputs/episodios/works. Los 12 faults afectan sólo a Meta en la organización objetivo; todos los works tienen dos llamadas LLM completas. No se observa intersección READY–Meta afectada, ni siquiera como intervalo posible. No se añade cola ni retraso para forzarla. No hubo captura System prospectiva en ese intento.

Las tasas son las referencias físicas del receipt aceptado, no una afirmación de capacidad: base [1,9607508002652434; 1,9607508002652434] inputs/min; R1-03 reasigna el calendario global 2:1 sin recalibración. Se conservan costes de servicio, dos planners, un sender, batch/poll, y ventanas. El detalle de pacing usa emisiones/aceptaciones físicas por slot, nunca replay como evidencia.

## Receipts y hashes

- [R1-03 — authorized-r103-unequal-20261007-0002](r1-03\authorized-r103-unequal-20261007-0002\evidence-audit-v2.json): `e98ee7aa24195df5aa8a5c76fc2d866d2855b852e7e9a9a0caed2d90f0ebc982`. Errores: ninguno.
- [R1-06 — authorized-r106-2x4-20261007-0002](r1-06\authorized-r106-2x4-20261007-0002\authorized-verification-v2.json): `a773d020598349e4895af571a99f3deb663c829552e5d5df57ade237ea885341`. Errores: BASE_META_COST_NOT_COMPLETELY_OBSERVED, INVALID_RUN, OBSERVATION_GATES_NOT_SATISFIED.
- [R2-02 — authorized-r202-blocked-20261007-0002](r2-02\authorized-r202-blocked-20261007-0002\evidence-audit-v2.json): `6fdfe9ffb5539a2a2a7f535f52930f4e7bfcd6cb9e6f63c4fb8406cd1da01eb2`. Errores: ninguno.
- [R2-04 — authorized-r204-postcommit-base-20261007-0004](r2-04\authorized-r204-postcommit-base-20261007-0004\authorized-verification-v2.json): `010ac7fe48ae84d6ec191135a7de7e9b66cb5954ef115ae190c69597630a1d5b`. Errores: CLOCK_OR_CAPTURE_INVALID.
- [R2-09 — authorized-r209-uncertain-meta-20261007-0002](r2-09\authorized-r209-uncertain-meta-20261007-0002\evidence-audit-v2.json): `421da1461d7a2bec908670d19d8b012aab3242c0b77a7693c5572c915272d605`. Errores: PENDING_NATURAL_READY_QUEUE_OVERLAP.

Los manifests capturados de los cinco probes incluyen los mismos 809 archivos backend esperados (789 del baseline y 20 de infraestructura de evaluación); ningún hash difiere. R1-06 0002 y R2-04 0004 incluyen además el sello prospectivo de los scripts de revision2, verificado sin cambios. Los límites del sello vacío previo permanecen documentados.

Pacing real por intento, commits de aceptación y lateness respecto al slot: [pacing-audit.json](pacing-audit.json). Inventarios de fuentes y hashes: [probe-source-audit.json](probe-source-audit.json). Un PASS de pacing o fuentes no constituye PASS del escenario completo.

## Integridad, regresión y cleanup

Integridad de runtime/históricos: True. Los 789 Python del archivo ejecutado son idénticos al baseline; el checkout conserva sus diferencias previas de finales de línea. La base mantiene SHA-256 `71c3e58c34decfac1698f9517f39b4d7cbc936c0463e35a4bbfe00ee04920a56`.
Regresión D29: PASS, 78 tests distintos ejecutados, 0 omisiones restantes. El primer run omitió 9; la segunda ejecución completó esos 9 con receipts preservados. Aplicación: **INCOMPLETE_INFRASTRUCTURE**. B3 pasó 39 tests; el sender reportó 42 tests y 53 errores operacionales/setup/teardown después de `psycopg.errors.OutOfMemory`. W1 quedó interrumpida y las otras cinco suites no corrieron. No se demostró la regresión completa de aplicación. El intento monolítico previo quedó incompleto y se conserva.
Los dos laboratorios privados se cerraron; puertos, directorios de cluster, todas sus bases y credenciales fueron retirados. Tras OutOfMemory no se pudo inventariar las bases de regresión por SQL: la prueba de cleanup es la parada del servidor, puerto cerrado y eliminación verificada del cluster privado completo. Los DROP individuales ya registrados se conservan. Se preservan los logs y fuentes recuperables sin copiar credenciales. Los cambios de documentos/skills ajenos a esta fase se dejaron intactos.

Comprobación final posterior a regresión: PASS; [final-integrity-v5.json](final-integrity-v5.json).

Comprobación posterior al cleanup: PASS; [closure-integrity-v6.json](closure-integrity-v6.json). La verificación de fuentes ejecutadas se conserva del corte previo al cleanup; los históricos, fuentes protegidas, base, HEAD, ausencia de procesos y puertos se vuelven a comprobar después.

Los límites de procedencia, la preparación inicial fallida, los errores de conductores y todos los intentos anteriores están documentados en [INCIDENTES-Y-ALCANCE.md](INCIDENTES-Y-ALCANCE.md). El intento R2-04 0003 no es PASS válido aunque su conductor lo hubiera declarado así.

## Decisiones antes de otra fase

1. R1-06: revisar prospectivamente la conciliación input→episodio y las obligaciones de respuesta cuando `deferred_to_new_input` suprime una salida obsoleta. La evidencia física no muestra pérdida de inputs ni drain pendiente; el gate de carga actual no pasa.
2. R2-09: decidir si se conserva pendiente la condición de solapamiento natural o se autoriza una propuesta metodológica distinta. No se aumenta delay, backlog ni retención de planners en esta fase.
3. R2-04: autorizar previamente un procedimiento de continuidad del reloj para el host de evaluación y después una repetición individual con la misma receta. El guard contra suspensión no impide que el servicio de hora ajuste el reloj. Se conserva el gate original y no se cambia runtime ni configuración de producción.
4. Completar las siete suites de aplicación que no tienen PASS en un entorno de evaluación con recursos disponibles. El error OutOfMemory y el cierre de conexión son evidencia de infraestructura; no permiten atribuir ni descartar una regresión del runtime. No se modificaron tests, durabilidad o configuración para facilitar el resultado.
5. R1-04 y slow_meta permanecen fuera del alcance autorizado. No se ejecutará la matriz completa sin revisión del resultado.

La carpeta de esta fase contiene únicamente infraestructura de evaluación, evidencia y documentación. No se editaron contratos D29/B8/B9/E4 ni runtime de producción. Los archivos nuevos/modificados de esta continuación se enumeran en el índice de artefactos; el estado general del repositorio incluye además trabajo previo no perteneciente a esta fase.
