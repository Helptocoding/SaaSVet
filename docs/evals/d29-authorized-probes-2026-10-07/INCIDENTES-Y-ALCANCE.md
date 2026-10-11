# Registro de correcciones de la fase autorizada

Estado conservado: `CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY`.
La base aceptada conserva el SHA-256
`71c3e58c34decfac1698f9517f39b4d7cbc936c0463e35a4bbfe00ee04920a56`.
No hay matriz completa ni autorización implícita para R1-04, slow_meta o caracterización.

## Intentos anteriores y calificación vinculante

Los archivos históricos se conservan con sus estados originales. Un PASS escrito por un conductor antiguo no prevalece sobre esta revisión ni sobre la verificación independiente final.

| Intento | Calificación de esta revisión | Causa / limitación |
|---|---|---|
| R1-03 0001 | INVALID_RUN de preparación | La base privada no tenía `channels_message`. No acredita comportamiento del runtime. |
| R1-03 0002 | Verificación física y clock aprobados | Se conserva su propia evidencia. No repara la repetición histórica con discontinuidad temporal. |
| R1-06 0001 | NOT_ACCREDITED; receta inválida | La oferta ordinaria rotó entre cuatro slots. La cuarta debía recibir sólo backlog. |
| R1-06 0002 | Consultar receipt v2 | La rotación se corrigió prospectivamente; se conservan los resultados de todos los gates. |
| R2-02 0001 | NOT_ACCREDITED de infraestructura | La lista permitida del entrypoint no incluía R2-02. No hubo oferta acreditable. |
| R2-02 0002 | Consultar evidence-audit-v2.json | Conciliación nueva bajo semántica autorizada; no rehabilita el resultado de una fase anterior. |
| R2-09 0001 | NOT_ACCREDITED de verificación | El verificador dependía de Django/DB y se ejecutó sin bootstrap; una consulta posterior a una DB vacía no puede recuperarlo. |
| R2-09 0002 | NOT_ACCREDITED / PENDING_NATURAL_READY_QUEUE_OVERLAP | El proveedor corregido tiene testigos de los 24 works, pero no hay solapamiento READY con las llamadas Meta afectadas. |
| R2-04 0001 | NOT_ACCREDITED de infraestructura | AppRegistryNotReady antes de la frontera. |
| R2-04 0002 | NOT_ACCREDITED de infraestructura | Crash real, luego falta `burst_seconds` al construir el calendario. No oferta base completa. |
| R2-04 0003 | NOT_ACCREDITED; receta inválida | Se usó P=240 s en lugar del período de la base; además faltaban gates de pacing/commit. Su `PHYSICALLY_ACCREDITED` autodeclarado no acredita la composición autorizada. |
| R2-04 0004 | INVALID_RUN | Calendario S=L−P sellado; Windows ajustó el reloj antes de abrir oferta. Intersección DB/monotonic imposible y evento System de cambio de hora. Sin reclaim/carga/seguimiento acreditados. |

## Defectos de evaluación corregidos

`revision2/r106_entry.py` aplica `n % 3` únicamente a la oferta ordinaria; el backlog conserva slots 0–3. No cambia el generador del runtime, las tasas ni la base. Un ledger separado identifica la población exclusiva del escenario.

`revision2/r204_entry_v2.py` obtiene P del receipt aceptado mediante el helper preparado: 30,600523019 s truncados a nanosegundos por el helper original. No usa los 240 s de seguimiento como P. Prepara los dos planners y un sender después de demostrar la salida del child del preámbulo y antes de S. Fija una vez el calendario a partir de una calibración DB/monotonic registrada; conserva sus incertidumbres y registra el inicio realmente observado. No reancla el calendario si la oferta llega tarde. El criterio de pacing sigue siendo el slot original semiabierto.

`audit_existing_v2.py` corrige dos defectos del suplemento anterior de R2-09: la lista de works se deriva de commits de claim, no de una clave `works` ausente en job-result; el solapamiento se decide con intervalos de cada episodio y llamada Meta, no mediante cortes de cola separados por 120 s. No modifica sus datos crudos ni su condición ejecutada.

El primer preflight sintético de revision2 esperaba un período redondeado de 30.600.523.020 ns. El helper preservado trunca a 30.600.523.019 ns. Se corrigió sólo el literal del test antes de ejecutar R2-04; ambos resultados se conservan. Es un test de verificador, no una prueba física ni una recalibración de la base.

## Límites de procedencia e incidentes de preparación

La inicialización previa de esta misma fase se lanzó dos veces y se eliminó/recreó prematuramente el directorio de salida mientras una inicialización seguía activa. Quedó un segundo laboratorio privado abierto. No se afirma conservación completa de esos primeros logs de inicialización. Los directorios de intentos físicos inventariados aquí se conservan; el incidente no autoriza reconstruir archivos perdidos como si fueran originales.

`orchestration-seal.json` quedó vacío durante aquella preparación. No se presenta como un sello previo válido. Los manifiestos de fuentes backend de cada intento sí se conservan; la copia del harness anterior archivada al cierre demuestra los bytes recuperados al cierre, no su existencia sellada antes de cada intento. A partir de revision2, cada plan incluye hashes de los scripts existentes antes de lanzar el probe.

R2-09 se ejecutó antes del R2-04 corregido. El orden pedido era preferente; las ofertas de escenarios diferentes no se ejecutaron simultáneamente. La revisión offline de receipts mientras transcurre la espera natural no emite carga.

R2-02 0002 y R2-09 0002 no tienen cortes System prospectivos. Sus intersecciones originales de clocks se verifican sin tolerancias. Se informa esa ausencia; no se inventa una captura de host retroactiva. R1-03 0002 y los probes revision2 sí tienen protección temporal y cortes por RecordId.

Los cambios ajenos ya presentes en `DEPLOY_VPS_PLAN.md`, `DEPLOY_VPS_STATUS.md` y `skills-lock.json` se dejan intactos. Las copias accidentales de helpers en la raíz se archivarán antes de retirarlas, comprobando origen y hashes. El cierre final registrará el estado efectivo de ambos laboratorios privados.

## Incidente temporal de R2-04 0004

El primer conflicto quedó en `ingress.jsonl`, seq 11081: su intersección previa de offsets era `[1791401830891965500, 1791401830892672400]` ns; la nueva calibración exige `[1791401833026944000, 1791401833029214200]` ns. No hay intersección. Los otros journals y todas las muestras permanecen disponibles.

System registra Kernel-General 1, RecordId 317254, salto de `2026-10-08T04:46:38.0166177Z` a `2026-10-08T04:46:40.1523676Z` (+2,1357499 s), junto a Time-Service 37/35 y una segunda corrección de +0,0005084 s. Es evidencia directa de un ajuste del host; no se deduce de una consulta tardía. No se infiere un defecto del runtime a partir de esta corrida inválida.

El receipt del guard guarda el error System que se produjo durante el cierre y `clock-invalid.json` conserva el primer error de intersección. Ambos motivos se exponen en `clock-incident-analysis.json`; ninguno se suprime. La protección contra suspensión estaba adquirida. Su restauración corre en `finally`; el camino excepcional del receipt omitió el marcador de restauración exitosa, por lo que no se inventa ese marcador a posteriori. Los procesos se cerraron y el cleanup global comprueba que no quedan participantes.

Las auditorías de integridad v2/v3 se conservan como intentos diagnósticos: comparaban bytes de finales de línea con supuestos incompletos. La autoridad final es `integrity-audit-v4.json`: los 789 archivos ejecutados coinciden exactamente con el archive; las 365 diferencias del checkout son exclusivamente CRLF/LF ya presentes, verificadas normalizando ambos lados sólo en memoria. No se reescribió ningún archivo del runtime.

## Regresión y fallo de infraestructura al cierre

La regresión D29 ejecutó 78 tests inicialmente (69 ejecutados y 9 omitidos por faltar `D29_FRONTIER_RECEIPTS`). La segunda ejecución proporcionó los receipts físicos preservados y pasó los 9 tests faltantes: 78 tests distintos ejecutados, ninguna omisión restante. Estas regresiones no ejecutan una matriz ni producen nueva capacidad física.

La regresión monolítica de aplicación quedó interrumpida sin receipt final. Se conservó su log y se retiró su base privada antes del nuevo intento. El nuevo conductor lanzó las ocho suites existentes en bases nuevas por suite, con un máximo de dos procesos de regresión; no coexistió con oferta de probes. B3 pasó 39 tests.

La suite `test_b4_sender` registró `psycopg.errors.OutOfMemory` en `test_meta_failure_matrix_through_real_sender(index=3)`: fallo al solicitar 48 bytes en `MessageContext`, seguido de cierre inesperado de la conexión y errores en cascada de setup/teardown. Su receipt contabiliza 42 tests y 53 errores; no se trata de 53 fallos independientes de producto. No se conoce un resultado válido de la suite completa. No se atribuye cuantitativamente el agotamiento a una única causa ni se afirma una capacidad de memoria del runtime.

Se detuvo el árbol de procesos del conductor propio y se conservó `regression-native-stop-receipt.json`; W1 quedó incompleta y cinco suites no iniciaron. La observación WMI de cleanup se demoró; el transporte nativo verificó el comando del único padre propio y sus descendientes antes de detenerlos. No se detuvieron aplicaciones ajenas ni se cambió PostgreSQL, clocks o planes de energía para favorecer el resultado.

`application-regression.json` queda `INCOMPLETE_INFRASTRUCTURE`, no PASS. El resultado de B3 se conserva; el resto requiere repetición en condiciones de evaluación con recursos disponibles. El cierre de los clusters se realiza sin nuevas consultas DB después del timeout: se verifican sus rutas absolutas, se para cada servidor privado, se comprueba puerto cerrado y se retira su directorio, incluyendo las bases de regresión interrumpidas. Los logs se copian después de la parada; los secretos de sesión nunca se archivan.

## Cleanup verificado al terminar

El primer conductor de cleanup excedió su timeout de 60 s mientras `Remove-Item` retiraba el primer laboratorio. No se presentó ese timeout como eliminación fallida o exitosa sin comprobarlo: la inspección posterior verificó que el directorio ya no existía, su puerto estaba cerrado y no quedaba su helper. El status PostgreSQL preservado indica `no server running`.

El segundo laboratorio se retiró mediante una operación de filesystem Python, después de validar su ruta absoluta, sesión de propiedad, layout y puerto. Su status también indicó servidor detenido. No se eliminó ninguna ruta ajena a los dos directorios privados identificados. Los siete helpers accidentales de la raíz se archivaron y retiraron sólo al coincidir sus hashes con copias de procedencia conocida.

`lab-cleanup-v2.json` conserva el resultado completo: ambos directorios y credenciales ausentes, ambos puertos cerrados y ningún proceso propio de probes/regresión/cleanup activo. No se afirma un DROP SQL final para las bases interrumpidas: la evidencia es la ausencia del cluster privado completo. `closure-integrity-v6.json` revalida el baseline, la base, fuentes protegidas y receipts históricos después de esta limpieza; conserva como referencia la comprobación exacta de las 789 fuentes ejecutadas realizada antes de retirar el laboratorio.
