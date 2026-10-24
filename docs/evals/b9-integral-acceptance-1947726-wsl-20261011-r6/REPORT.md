# B9E — aceptación de 1947726 en WSL2, campaña r6

**Decisión integral: PENDING por discontinuidad de reloj tras suspensión del
host.** Esta reanudación terminó el corpus dirigido **87/87 PASS**, con cero
fallos, errores, skips o xfail. Django check y drift de migraciones también
pasaron. Durante la migración posterior de checks, el monitor detectó
**121,912111 s** de discontinuidad civil−monotónica y detuvo el bloque. Los
eventos de Windows confirman una suspensión y reactivación en ese intervalo.
Los bloques restantes y las cinco variantes PROFILE quedaron NOT_EXECUTED.

Candidato: `194772677ca4e9fe1a1dec7f4dafa48396a6c583`. La instrucción
«reanuda» autorizó una campaña independiente, conservando las seis anteriores
y la excepción de memoria ya aprobada. El controlador formal corrió entre
**03:37:10 y 04:01:47 UTC del 12-10-2026**, todavía el **11-10-2026 en México**.
[STOP original](STOP.json), [clasificación del incidente](incident-classification.json),
[decisión R01–R15/I01–I14](candidate-decision.json).

## Condición de recursos y preparación

La [autorización](authorization.json) y la [política](resource-policy.json)
conservan el cambio solicitado por el usuario: admisión con los recursos
disponibles, manteniendo **2 GiB** libres en host y guest, disco real mínimo de
**1 GiB**, límite horario original de **1 s** y parada ante incidentes
invalidantes. El prerrequisito de 5 GiB fue retirado expresamente; el presupuesto
estimado de 3 GiB por suite no queda reservado ni garantizado.

El [preflight](preflight.json) pasó con **4,84 GiB en Windows**, **7,04 GiB en
WSL** y **3,95 GiB en el disco real de respaldo**. El control inmediato anterior
al corpus dirigido registró **2,42 GiB en Windows**, suficiente para la
política modificada. Las suites conservaron su orden secuencial y la
concurrencia interna original.

Antes del sello, la sonda Windows pasó a un proceso privado persistente que
consulta la misma API `GlobalMemoryStatusEx`, registra muestras cada segundo y
rechaza observaciones con antigüedad mayor de 10 s al consultarlas. Se redujeron
los arranques de intérpretes sin atribuirles la causa de la fluctuación de
memoria. El estado Git se capturó con `--no-optional-locks`.
Las adaptaciones y sus hashes están en [lineage](adapter-lineage.json) y
[ajustes previos al sello](preseal-environment-amendments.json).

- Las **3.332 fuentes** exportadas coinciden con los blobs exactos del candidato.
- Python **3.13.2**, con el mismo `requirements.lock` en el venv y el prefijo
  base privado. Se conserva el `sys._base_executable` que seleccionan los tests
  antiguos de procesos. Ambos intérpretes validaron dependencias e imports,
  incluidos Django **6.0.5** y psycopg **3.3.4**. Esta preparación no ejecutó B3.
- Se congelaron **13.508 archivos de dependencias** y **99 archivos** del
  evaluador, configuración, diagnósticos y herramientas. Los controles
  anteriores y posteriores a los cuatro bloques y la integridad final pasaron.
- Node **20.20.2**, pnpm **9.15.9** e instalación frontend con
  `--frozen-lockfile` PASS. Sus checks de CI no llegaron a ejecutarse.
- PostgreSQL **16.15** privado, puerto **35479**, con durabilidad habilitada y
  bases propias; sin datos productivos.
- Discovery resolvió **87 IDs dirigidos**, **3.331 completos**, B0 **17**,
  B3 **42**, B4 **68** y B5 **37**, sin faltantes, duplicados o errores.
  Discovery no acredita ejecución.
- Las fuentes originales del PROFILE mantienen compatibilidad con el
  candidato histórico **0831046** y sus cinco variantes. Sus métricas no se
  transfieren al candidato actual.

No se cambiaron producto, tests, fixtures, tasas, población, proveedores,
tiempos, aserciones ni gates de contrato. No se terminaron procesos ajenos
para obtener memoria. No hubo ajustes del evaluador después del sello ni
reintentos formales.

## Resultados de esta campaña

| Bloque | Estado de r6 |
| --- | --- |
| Preflight y validación de ambos intérpretes | PASS de preparación con admisión modificada |
| Corpus dirigido | **87/87 PASS**; cero fallos, errores, skips o xfail |
| Django check | PASS |
| Drift de migraciones | PASS |
| Migración en base privada de checks | INTERRUMPIDA; PENDING por entorno/reloj |
| Schema Billing | NOT_EXECUTED |
| B0/B3/B4/B5 y suite completa | NOT_EXECUTED |
| Build, tests, lint y smoke frontend | NOT_EXECUTED |
| Gitleaks y auditorías advisory | NOT_EXECUTED |
| BASE, BLOCKED_LLM, META_SLOW, DUPLICATE y SATURATION | NOT_EXECUTED |

El corpus dirigido duró **1.183,15 s** según el recibo de comando monitoreado;
su recibo interno registra **1.179,53 s**. Son alcances de medición distintos.
Los **87 IDs únicos completados** corresponden exclusivamente a esta campaña,
incluidas las negativas I04/I07. Django check y drift son comprobaciones, no
IDs adicionales. La migración parcial posterior no se convierte en PASS.
[Recibo dirigido](blocks/directed.results.json),
[resumen de ejecución](execution-summary.json) y [estados por bloque](block-status.json).

## Incidente confirmado y límites de observación

El [monitor de migración](monitor-migrate.json) contiene **83 muestras** y
registra un máximo civil−monotónico de **121,91211131459704 s**, superior al
límite original de **1 s**. El controlador envió SIGTERM únicamente a su grupo
de procesos; el comando terminó con exit **-15**. La parada durable conserva
`PENDING`, fase `migrate`, causa `Clock discontinuity` y `no_rerun: true`.

El diagnóstico posterior al STOP fue de solo lectura. Los
[eventos de Windows](windows-clock-power-events.json) conservan:

- Kernel-Power 42, entrada en suspensión a las **03:59:22,5216413 UTC**.
- Power-Troubleshooter 1, con `SleepTime` **03:59:21,1775343 UTC** y `WakeTime`
  **04:01:24,4712272 UTC**: unos **123,29 s** entre ambas marcas.
- Kernel-General 1 al reactivarse, con cambio civil de **117.696 ms**.

No se interpreta la razón numérica de suspensión ni se atribuye quién la
provocó. La suspensión/reactivación confirmada coincide con la discontinuidad
detectada en WSL. No se atribuye un fallo del producto.

Las **1.259 muestras** de los cuatro bloques no registraron agotamiento de las
reservas de memoria o disco: mínimo de Windows **2.368.262.144 bytes
(2,21 GiB)**, WSL **7.225.163.776 bytes (6,73 GiB)** y disco real
**4.222.058.496 bytes (3,93 GiB)**. El observador Windows conservó **2.248
muestras**, con un hueco de **118,73 s** durante la suspensión. Las últimas
observaciones cacheadas del monitor se conservan sin presentarlas como
muestras nuevas durante ese hueco. Estas mediciones tampoco establecen la
causa única de fluctuaciones de memoria.
[Estadísticas del monitor](monitor-summary.json),
[resumen del observador](resource-observer-summary.json).

La pausa temporal autorizada de sincronización de WSL contó con guardián de
seis horas y restauración al cierre. La observación previa de **120 s** pasó:
máximo civil−monotónico de **0,00004 s en Windows** y **0,000050479 s en WSL**.
Es una observación acotada: pausar NTP de WSL no impide la suspensión del host.
No se modificaron W32Time ni la política global de energía de Windows.

## Conservación y cierre

El [cleanup](cleanup.json) pasó. Se conservaron las observaciones SQL y tablas
antes de retirar `test_b8b_b9i_directed`, `test_b9i_checks` y `test_b9i_control`.
PostgreSQL se detuvo, el puerto quedó cerrado y se eliminó únicamente
`/home/lap/b9i-wsl-1947726-20261011-r6`. El
[observador propio de Windows](resource-observer-closure.json) recibió una
petición explícita de cierre y terminó. La
[restauración del reloj](clock-restoration.json) pasó: WSL volvió a
**active/running/enabled**, como al inicio.

Se comprobaron sin diferencias **925 archivos de las seis campañas anteriores**
y los tres cambios ajenos del checkout. El acta recibió un añadido conservando
su prefijo exacto. Los scripts de `diagnostics` creados después del STOP se
limitan al diagnóstico y cierre; no modifican el evaluador sellado ni ejecutan
tests. [Conservación previa](preservation-of-prior-work.json),
[actualización del acta](acta-update.json).

El expediente tiene inventario y paquete propio, con todos los logs originales
y hashes, comprobado mediante restauración interna y una invocación real por
CLI. [Procedimiento de recuperación](README.md). La selección Git es explícita,
con comprobación de las selecciones anteriores fuera de los tres archivos
compartidos de entrega. No se crearon commits ni se hizo push, despliegue o
activación.

La aceptación integral sigue **PENDING**. R1-04 mantiene PENDING con limitación
aceptada y cero intentos físicos nuevos; activación
**PENDING_ACTIVATION_REQUIREMENTS**, E/P/UX y aprobaciones operativas/privacidad
permanecen separados. La campaña queda cerrada tras su STOP. Una futura
ejecución necesita una nueva decisión y mantener el host despierto, además de
revalidar reloj y recursos; no hay reintento automático.
