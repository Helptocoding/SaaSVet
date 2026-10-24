# B9E — aceptación de 1947726 en WSL2, campaña r7

**Decisión integral: PENDING por discontinuidad de reloj tras suspensión del
host.** Esta continuación terminó el corpus dirigido **87/87 PASS**, con cero
fallos, errores, skips o xfail. Django check y drift de migraciones también
pasaron. Durante la migración posterior de checks, el monitor detectó
**391,458861 s** de discontinuidad civil−monotónica y detuvo el bloque. Windows
registró una nueva suspensión y un ajuste civil al reactivarse. Los demás
bloques y las cinco variantes PROFILE quedaron NOT_EXECUTED.

Candidato: `194772677ca4e9fe1a1dec7f4dafa48396a6c583`. La instrucción
«continua, estara despierto» autorizó esta campaña independiente, conservando
las siete anteriores y la excepción de memoria ya aprobada. El controlador
formal corrió entre **04:30:12 y 04:58:55 UTC del 12-10-2026**, todavía el
**11-10-2026 en México**. [STOP original](STOP.json),
[incidente](incident-classification.json), [decisión R01–R15/I01–I14](candidate-decision.json).

## Preparación y condición de recursos

Se mantuvo la [política autorizada](resource-policy.json): admisión con los
recursos disponibles, conservando **2 GiB** libres en host y guest, disco real
mínimo de **1 GiB**, límite horario original de **1 s** y parada ante incidentes
invalidantes. El prerrequisito de 5 GiB fue retirado por el usuario; los 3 GiB
estimados por suite no quedan reservados ni garantizados.

El [preflight](preflight.json) pasó con **4,96 GiB en Windows**, **7,04 GiB en
WSL** y **3,88 GiB en el disco real de respaldo**. Se mantuvieron suites
secuenciales y su concurrencia interna original. La política global de energía
de Windows y W32Time no se modificaron.

- Las **3.332 fuentes** exportadas coinciden con los blobs exactos del candidato.
- Python **3.13.2**, con el mismo `requirements.lock` en venv y prefijo base
  privado; `sys._base_executable` original. Ambos intérpretes pasaron validación
  de imports y paridad de paquetes, incluidos Django **6.0.5** y psycopg **3.3.4**.
  Esa validación de preparación no ejecutó el contrato B3.
- Se congelaron **13.508 archivos de dependencias** y **101 archivos** del
  evaluador, configuración, diagnósticos y herramientas. Sus controles
  anteriores y posteriores a los cuatro bloques y la integridad final pasaron.
- Node **20.20.2**, pnpm **9.15.9** e instalación frontend con
  `--frozen-lockfile` PASS; checks frontend de CI no ejecutados.
- PostgreSQL **16.15** privado, puerto **35479**, con durabilidad habilitada y
  bases propias; sin datos productivos.
- Discovery resolvió **87 IDs dirigidos**, **3.331 completos**, B0 **17**,
  B3 **42**, B4 **68** y B5 **37**, sin faltantes, duplicados o errores.
  Discovery no acredita ejecución.
- Las fuentes del PROFILE mantienen compatibilidad con **0831046** y sus cinco
  variantes. No se transfieren sus métricas al candidato actual.

El evaluador conserva las adaptaciones previas de r6: observador persistente
Windows mediante la misma API `GlobalMemoryStatusEx`, muestras cada segundo y
rechazo de observaciones consultadas con antigüedad mayor de 10 s; captura Git
sin refresco opcional del índice; ambos intérpretes con el mismo lock. Las
diferencias de namespace y lineage se registraron antes del sello.
[Lineage inicial](adapter-lineage.json), [lineage final](adapter-lineage-final.json),
[ajustes previos](preseal-environment-amendments.json).

No se cambiaron producto, tests, fixtures, tasas, población, proveedores,
tiempos, aserciones ni gates de contrato. No se terminaron procesos ajenos para
obtener memoria ni hubo reintentos formales o ajustes del evaluador tras el sello.

## Resultados de r7

| Bloque | Estado |
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

El comando dirigido monitoreado duró **1.176,52 s**; su recibo interno registra
**1.172,52 s**, con distinto alcance de medición. Los **87 IDs únicos**,
incluidas las negativas I04/I07, pertenecen exclusivamente a esta campaña.
Django check y drift son comprobaciones, no IDs adicionales. Los resultados
previos no se transfieren a r7. [Recibo dirigido](blocks/directed.results.json),
[resumen de ejecución](execution-summary.json), [estados por bloque](block-status.json).

## Discontinuidad y evidencia del host

El [monitor de migración](monitor-migrate.json) conserva **48 muestras** y un
máximo civil−monotónico de **391,4588610203798 s**, superior al límite de 1 s.
El controlador envió SIGTERM a su grupo propio; exit **-15**. El recibo registra
**49,01 s monotónicos de WSL**: ese tiempo excluye el intervalo de suspensión
detectado y no representa todo el tiempo civil transcurrido. La migración
parcial no se convierte en PASS ni se atribuye un fallo del producto.

La consulta posterior de solo lectura a los [eventos de Windows](windows-clock-power-events.json)
registró:

- Kernel-Power **42** a las **04:51:58,2474581 UTC**, entrada en suspensión.
- Kernel-Power **107**, con metadatos de reactivación, a las **04:52:00,4068982 UTC**
  según la marca civil previa al ajuste conservada en el evento.
- Kernel-General **1** a las **04:58:29,5005220 UTC**, proceso 4: cambio de
  `OldTime` **04:52:00,4066681 UTC** a `NewTime` **04:58:29,5000000 UTC**,
  **389.093 ms** de ajuste civil al reactivarse.

No apareció un par SleepTime/WakeTime de Power-Troubleshooter en esa consulta;
no se inventan esas marcas ni se reutilizan las de r6. No se interpreta el
código numérico de razón ni se identifica quién inició la suspensión.
El observador Windows conserva un hueco de **390,11 s** entre las marcas
**04:52:00 y 04:58:30 UTC**, consistente con este intervalo.

Las **1.229 muestras** de los cuatro bloques no registraron agotamiento de las
reservas: Windows mínimo **2.338.824.192 bytes (2,18 GiB)**, WSL mínimo
**7.228.485.632 bytes (6,73 GiB)** y disco real mínimo **4.154.306.560 bytes
(3,87 GiB)**. El observador conservó **2.156 muestras**. La última muestra
cacheada de host anterior a la suspensión se conserva sin presentarla como
una medición nueva al reactivarse; no existen muestras durante ese hueco.
[Resumen del monitor](monitor-summary.json), [resumen del observador](resource-observer-summary.json).

La pausa temporal autorizada de sincronización de WSL contó con guardián de
seis horas y restauración al cierre. La observación previa de **120 s** pasó:
máximos civil−monotónico **0,0001133 s en Windows** y **0,000089516 s en WSL**.
Esa observación acotada no garantiza continuidad frente a una suspensión del host.

## Preparación concreta para evitar suspensión por inactividad

La [inspección de energía posterior al STOP](power-policy-after-stop.json)
muestra el plan Equilibrado con suspensión tras **900 s (15 minutos) con
corriente alterna** y **600 s (10 minutos) con batería**. Es configuración
observada después del incidente, no prueba del iniciador exacto de esa
suspensión. `powercfg /requests` devolvió exit 1 por requerir elevación; las
otras tres consultas pasaron y no se solicitó ni usó elevación de Windows.

Se preparó [awake_guard.py](diagnostics/awake_guard.py) **después del STOP**
para una futura campaña. Usa una solicitud temporal de su propio hilo mediante
`SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)`, con duración
máxima de seis horas, archivo opcional de cierre y liberación en `finally`.
No cambia el plan de energía, la pantalla ni W32Time. La API permite solicitar
actividad frente al temporizador de suspensión; no impide que el usuario
solicite dormir mediante tapa o botón. La actividad de CPU/disco tampoco se
detecta necesariamente como actividad de usuario. [Documentación de Microsoft](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate).

La [sonda de 2 s](awake-request-probe/closure.json) comprobó adquisición,
confirmación del estado del hilo y restauración de **0x80000001** a
**0x80000000**, sin cambiar políticas globales ni ejecutar tests de aplicación.
Ese resultado acredita la API y su liberación en este contexto; **no acredita
prevención de suspensión durante 15 minutos o durante una campaña completa**.
La protección no se utilizó en la ejecución formal r7 y no repara ni modifica
retroactivamente su resultado. Una futura integración debe adquirirla y
comprobar su vida antes del sello y liberarla al cierre, manteniendo los gates
originales. [Preparación de remediación](environment-remediation.json).

## Conservación y cierre

El [cleanup](cleanup.json) pasó: observaciones SQL y tablas guardadas; retiradas
`test_b8b_b9i_directed`, `test_b9i_checks` y `test_b9i_control`; PostgreSQL detenido,
puerto cerrado y eliminado únicamente `/home/lap/b9i-wsl-1947726-20261011-r7`.
El [observador propio](resource-observer-closure.json) se cerró explícitamente.
La [sincronización de WSL](clock-restoration.json) volvió a
**active/running/enabled**, como al inicio. La solicitud temporal de actividad
de la sonda posterior también quedó liberada.

Se comprobaron sin diferencias **1.163 archivos de las siete campañas
anteriores** y los tres cambios ajenos del checkout. El acta recibió un añadido
con su prefijo exacto conservado. Los scripts posteriores de `diagnostics`
pertenecen al diagnóstico y cierre, fuera del evaluador sellado; no ejecutan
tests de aplicación. [Conservación previa](preservation-of-prior-work.json),
[actualización del acta](acta-update.json).

El paquete propio incluye los logs originales, inventario y hashes; su
restauración se comprueba internamente y mediante una invocación real por CLI.
[Recuperación](README.md). La selección Git es explícita y comprueba las
selecciones previas fuera de los tres archivos compartidos de entrega. Sin
commits, push, despliegue ni activación.

La aceptación integral sigue **PENDING**. R1-04 conserva PENDING con limitación
aceptada y cero intentos físicos nuevos; activación
**PENDING_ACTIVATION_REQUIREMENTS**, E/P/UX y aprobaciones operativas/privacidad
separados. Esta campaña queda cerrada después de su STOP, sin reintentos
automáticos. Una nueva campaña requiere una nueva decisión, la protección
temporal del host y la revalidación de reloj y recursos.
