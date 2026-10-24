# B9E — aceptación de 1947726 en WSL2, campaña r8

**Decisión integral: PENDING por reserva de disco.** El monitor registró
**908.460.032 bytes (0,85 GiB)** libres en `/mnt/c`, por debajo del mínimo
original de 1 GiB, y detuvo el corpus dirigido. Su journal conserva
**53/87 IDs con estado `ok`**, pero falta el recibo final del runner:
**el bloque dirigido no pasa**. Los checks posteriores y las cinco variantes
PROFILE quedan NOT_EXECUTED. No se atribuye un fallo del producto.
[STOP original](STOP.json), [clasificación](incident-classification.json),
[recibo parcial](directed-partial-receipt.json), [decisión R01–R15/I01–I14](candidate-decision.json).

Candidato: `194772677ca4e9fe1a1dec7f4dafa48396a6c583`. La instrucción
«prosigue» autorizó esta nueva campaña, con solicitud temporal propia de
actividad y conservación de las ocho anteriores. El controlador formal corrió
entre **05:40:07 y 05:46:23 UTC del 12-10-2026**, todavía el **11-10-2026
en México**, durante **375,98 s**. Hubo una invocación formal y una corrida
del bloque dirigido, sin reintentos.

## Preparación y sello

La [política autorizada](resource-policy.json) conserva **2 GiB** libres en
Windows y WSL, **1 GiB** en el volumen real de respaldo y el guard de reloj
de **1 s**. El usuario retiró el prerrequisito de 5 GiB. Los 3 GiB estimados
por suite no constituyen una reserva adicional garantizada. Suites
secuenciales y concurrencia interna original.

El [preflight](preflight.json) pasó con unos **4,86 GiB en Windows**,
**7,04 GiB en WSL** y **3,80 GiB en C:**. Se verificaron:

- **3.332 fuentes** exportadas, idénticas a los blobs del candidato.
- Python **3.13.2**, con el mismo `requirements.lock` instalado en venv y
  prefijo base privado, conservando `sys._base_executable`. Ambos intérpretes
  pasaron imports y paridad de paquetes; Django **6.0.5**, psycopg **3.3.4**.
- **13.508 archivos de dependencias** y **106 archivos** sellados de
  evaluador, configuración, diagnósticos y herramientas. Los controles antes
  y después del bloque pasaron; la integridad final de fuentes también pasó.
- Node **20.20.2**, pnpm **9.15.9**, instalación frontend con
  `--frozen-lockfile` PASS de preparación. Los checks frontend no se ejecutaron.
- PostgreSQL **16.15** privado, puerto **35479**, durabilidad habilitada,
  proveedores controlados y bases propias, sin datos productivos.
- Discovery: **87 IDs dirigidos**, **3.331 completos**, B0 **17**, B3 **42**,
  B4 **68**, B5 **37**, sin faltantes, duplicados ni errores. Estos conteos
  describen selección; no acreditan ejecución.
- Compatibilidad de fuentes del PROFILE con el contrato de **0831046**,
  conservando tasas, población, N=1, fixtures, tiempos y gates originales.
  Ninguna métrica histórica se transfiere al candidato actual.

Los cambios de ensamblaje quedaron registrados antes del sello:
[lineage final](adapter-lineage-final.json),
[ajustes previos](preseal-environment-amendments.json) y
[validación de actividad](preseal-awake-validation.json). Se mantuvo el
observador persistente `GlobalMemoryStatusEx`, muestras de un segundo,
antigüedad máxima consultada de 10 s y captura Git sin refresco opcional.
La lectura de actividad propia usa su heartbeat, sin crear procesos Windows
por cada muestra; su indisponibilidad también provoca parada.

No se modificaron producto, tests, fixtures, tasas, población, proveedores,
timings, aserciones ni gates de contrato. No hubo cambios del evaluador
después del sello ni terminación de procesos ajenos para obtener recursos.

## Resultado parcial y parada

| Bloque | Estado |
| --- | --- |
| Preflight y validación de ambos intérpretes | PASS de preparación |
| Corpus dirigido | INTERRUMPIDO; 53/87 registros `ok`, sin PASS del bloque |
| Django check, drift, migrate y schema Billing | NOT_EXECUTED |
| B0/B3/B4/B5 y suite completa | NOT_EXECUTED |
| Build, tests, lint y smoke frontend | NOT_EXECUTED |
| Gitleaks y auditorías advisory | NOT_EXECUTED |
| BASE, BLOCKED_LLM, META_SLOW, DUPLICATE, SATURATION | NOT_EXECUTED |

El [comando dirigido](blocks/directed.command.json) duró **326,39 s**.
El controller envió SIGTERM a su grupo propio al detectar la reserva
incumplida y SIGKILL tras los diez segundos originales de gracia; exit **-9**.
El código de salida no se clasifica como fallo funcional.

Los 53 registros únicos incluyen **39 B2** de resultados/transporte/efectos,
las **dos negativas de asistencia**, la consulta con herramienta equivocada,
seis negativas de autorización de release y otras verificaciones de identidad,
tenant y herramientas. Se conservan los IDs exactos y los **34 restantes**
en el [recibo parcial](directed-partial-receipt.json). El journal carece de
timestamps por ID: no permite demostrar que todas las terminaciones
precedieron a la muestra invalidante. Tampoco permite emitir los totales
finales de fallos, errores, skips o xfail que habría producido el runner.
La decisión por requisito usa estas observaciones parciales con sus límites,
sin otorgar aprobación integral ni trasladar resultados de r6/r7.

Las **307 muestras** del [monitor](monitor-directed.json) registran:

- Windows mínimo **2.228.580.352 bytes (2,08 GiB)**; WSL mínimo
  **7.378.272.256 bytes (6,87 GiB)**. No se agotó la reserva de memoria.
- Disco real mínimo **908.460.032 bytes (0,85 GiB)** a las
  **05:46:01 UTC**, inferior a **1.073.741.824 bytes**.
- Máximo civil−monotónico **0,000002835 s**. No se detectó discontinuidad
  de reloj en el bloque.
- Solicitud propia de actividad **ACTIVE_CONFIRMED** en todas las muestras.

El espacio de `/mnt/c` volvió a **4.069.318.656 bytes (3,79 GiB)** al terminar
el comando. La [consulta posterior de solo lectura](disk-after-stop.json),
tras el cleanup, registró también unos **3,8 GiB** tanto desde Windows como
desde WSL. Esa recuperación posterior no revoca la parada original ni
autoriza un reintento. **No está establecida la causa de la caída temporal**;
no se atribuye a un archivo, proceso, aplicación o mecanismo concreto.
[Resumen del monitor](monitor-summary.json), [estados por bloque](block-status.json),
[resumen de ejecución](execution-summary.json).

## Actividad temporal y reloj

La lectura anterior al sello de los mensajes completos de Kernel-Power 42
confirma **«System Idle»** en las suspensiones de **03:59:22** y
**04:51:58 UTC**, correspondientes a r6/r7. Es evidencia adicional de r8;
los reportes anteriores conservan sus límites originales sin sobrescribirse.
[Mensajes completos](preseal-sleep-event-messages.json).

Se adquirió a las **05:26:16 UTC**, antes de preparar y sellar la campaña,
una solicitud de su propio hilo mediante
`SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)`. Se mantuvo
durante **1.266,12 s**, con **1.261 heartbeats**, y se liberó explícitamente
al cierre, restaurando **0x80000001 → 0x80000000**, el estado original.
[Control](awake-request/control.json), [resumen](awake-request-summary.json),
[liberación](awake-request/closure.json).

La API solicita actividad frente al temporizador de inactividad y permite
liberar la solicitud al terminar. No garantiza impedir suspensión solicitada
por el usuario, tapa, botón o políticas que prevalezcan. La adquisición y
restauración de la API no son por sí solas una garantía universal de prevención
de suspensión. [Documentación de Microsoft](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate).
En esta campaña no se observó discontinuidad de reloj durante el bloque.
No se modificaron el plan de energía, la pantalla ni W32Time.

La pausa temporal autorizada de sincronización de WSL contó con guardián
de seis horas. La observación previa de **120 s** pasó con máximos
civil−monotónico de **0,0005815 s en Windows** y **0,00101225 s en WSL**.
La sincronización se restauró **active/running/enabled**, como al inicio.
[Control de reloj](clock-control.json), [restauración](clock-restoration.json).

## Conservación y cierre

El [cleanup](cleanup.json) pasó: observaciones SQL y tablas guardadas;
retiradas `test_b8b_b9i_directed` y `test_b9i_control`, PostgreSQL detenido,
puerto cerrado y eliminado únicamente
`/home/lap/b9i-wsl-1947726-20261011-r8`. El observador propio se cerró
explícitamente: **1.245 muestras**. La solicitud temporal de actividad y
el guardián de sincronización también terminaron correctamente.

Se comprobaron sin diferencias **1.409 archivos de las ocho campañas
anteriores** y los tres cambios ajenos del checkout. El acta recibió un
añadido con su prefijo exacto conservado. Los scripts de `diagnostics`
documentan el cierre después del STOP y no ejecutan pruebas de aplicación.
[Conservación](preservation-of-prior-work.json), [acta](acta-update.json).

El paquete independiente incluye logs originales, inventario y hashes.
La recuperación se comprueba internamente y por una invocación real de CLI;
la selección Git es explícita y conserva las selecciones anteriores fuera
de los tres archivos compartidos de entrega. [Recuperación](README.md).
Sin commits, push, despliegue ni activación.

R1-04 conserva **PENDING con limitación aceptada**, sin nuevos intentos
físicos; activación **PENDING_ACTIVATION_REQUIREMENTS**, E/P/UX y aprobaciones
operativas/privacidad separados. Esta campaña queda cerrada tras su STOP.
Una nueva corrida requiere una decisión nueva y un volumen de respaldo
que mantenga al menos 1 GiB libre durante la ejecución, conservando los
controles de actividad, memoria y reloj. [Remediación y límite](environment-remediation.json).
