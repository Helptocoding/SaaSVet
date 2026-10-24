# B9E — aceptación de 1947726 en WSL2, campaña r3

**Decisión técnica integral: PENDING.** Pasaron el corpus dirigido **87/87**,
B0 **17/17**, los checks de Django, drift, migraciones y schema Billing.
B3 terminó con **39 PASS y tres FAIL del runner**: los tres casos de procesos
no alcanzaron `B3_READY`. El diagnóstico posterior confirmó que el Python base
seleccionado por esos tests no puede importar Django, instalado solamente en
el entorno virtual. Es una incompatibilidad del ensamblaje evaluativo que impide
evaluar esos contratos; no se atribuye una violación al producto.

Candidato: `194772677ca4e9fe1a1dec7f4dafa48396a6c583`.
Autorización: «procede», con pausa temporal de la sincronización de WSL,
comprobación del reloj y campaña nueva condicionada a reloj estable y recursos.
La ejecución formal comenzó el **11-10-2026 en México**, a las
**01:23:19 UTC del 12-10-2026**. Expediente independiente de las tres campañas
anteriores. [Decisión](candidate-decision.json),
[clasificación](incident-classification.json) y [parada original](STOP.json).

## Preparación y condiciones

- Los 3.332 archivos del árbol aislado coinciden con los blobs exactos del SHA.
- Python 3.13.2, dependencias de `requirements.lock` y `pip check` satisfactorio.
- Node 20.20.2 y pnpm 9.15.9: instalación frontend con `--frozen-lockfile` PASS
  en Linux, sin cambiar locks ni privilegios de Windows.
- PostgreSQL 16.15 privado, puerto 35479, con `fsync`, `synchronous_commit`
  y `full_page_writes` habilitados. No se usaron bases ni proveedores productivos.
- Discovery sin ausentes, duplicados ni errores: dirigido 87, completo 3.331,
  B0 17, B3 42, B4 68 y B5 37. Discovery no acredita ejecución.
- Bootstrap y resolución de los cinco runners validados antes del sello.
  Esa validación no comprobó la visibilidad de dependencias desde el intérprete
  base que seleccionan los tres casos antiguos de B3; esa omisión del ensamblaje
  explica el bloqueo identificado posteriormente.
- Las tres fuentes del PROFILE siguen idénticas a las del candidato histórico
  0831046. No se cambiaron fixtures, cargas, tiempos, población, concurrencia,
  proveedores, aserciones ni umbrales. Ninguna variante PROFILE llegó a ejecutarse.

El [sello](evaluation-seal.json) cubre **91 archivos** evaluativos, configuraciones,
diagnósticos previos y ejecutables, además del manifiesto de las 3.332 fuentes.
Todos sus controles posteriores a los bloques pasaron. La integridad final antes
del cleanup también pasó. Los adaptadores y diferencias previas están en
`adapter-lineage.json` y `receipt-adapter.diff`; el adaptador solo registra recibos
y conserva los guards críticos mediante sus métodos originales.

## Reloj y recursos

Con el servicio de sincronización de WSL activo, la observación previa de dos
minutos registró un desfase civil−monotónico máximo de **1,511376911 s**.
Con el servicio temporalmente pausado, dos observaciones independientes de dos
minutos registraron máximos de **0,0000762 s** y **0,0001225 s** en WSL.
Son observaciones acotadas; no demuestran por sí solas una causa sistémica única
ni estabilidad universal. Las fuentes y muestras están en `clock-diagnostics/`.

Se esperó a disponer de recursos antes de iniciar. El [preflight](preflight.json)
pasó con aproximadamente **5,99 GiB** disponibles en Windows, **7,05 GiB** en WSL
y **4,24 GiB** reales de disco de respaldo. Se conservaron los requisitos de
5 GiB antes de cada bloque, reserva de 2 GiB durante la ejecución y 1 GiB de disco.
No se terminaron procesos ajenos. El usuario indicó después que no podía liberar
más memoria; para entonces la campaña ya había comenzado con margen comprobado.

Los siete bloques produjeron **1.492 muestras** de monitor. El desfase máximo
observado durante la ejecución fue **0,000037986 s**, dentro del límite original
de 1 s. Los mínimos observados fueron **3,38 GiB** disponibles en Windows,
**6,74 GiB** en WSL y **4,08 GiB** de disco real. No se detectó un incidente
invalidante de reloj o recursos. No se modificó W32Time ni la configuración
del reloj de Windows.

## Resultados y bloqueo B3

| Bloque | Resultado acreditado |
| --- | --- |
| Corpus dirigido | PASS, 87/87; cero fallos, errores, skips y xfail |
| Django check, drift, migrate, schema Billing | PASS, cuatro comandos con exit 0 |
| B0 | PASS, 17/17; cero omisiones |
| B3 | PENDING del contrato; runner: 42 casos, 39 PASS y 3 FAIL de arranque |
| B4, B5 y suite completa de 3.331 IDs | NOT_EXECUTED |
| Build, Vitest, lint y smoke frontend | NOT_EXECUTED |
| Gitleaks y auditorías advisory | NOT_EXECUTED |
| BASE, BLOCKED_LLM, META_SLOW, DUPLICATE, SATURATION | NOT_EXECUTED |

Hay **146 observaciones de IDs únicos**, sin solapes entre los tres jobs ejecutados:
**143 PASS y tres FAIL brutos del runner**, clasificados como incompatibilidad del
entorno antes de evaluar el contrato. No se convierten los tres fallos en PASS.
Las negativas I04 e I07 incluidas en los 87 IDs dirigidos sí terminaron PASS.
Los solapes previstos con la suite completa siguen siendo selección, pues esa
suite no se ejecutó. [Conteo y denominadores](execution-summary.json),
[estados por bloque](block-status.json) y [disposición R01–R15/I01–I14](candidate-decision.json).

Los tres casos afectados son `test_dup_01_two_processes_compete_for_one_lease`,
`test_dur_01_killed_process_restarted_worker_recovers_same_work` y
`test_llm_timeout_runs_outside_transaction_and_commits_fallback`, de `B3ProcessTests`.
Los tres fallaron en `ready()` con `AssertionError: '' != 'B3_READY'`.
El candidato selecciona `sys._base_executable` para esos hijos y requiere importar
Django antes de emitir la marca y antes de ejecutar claim, crash o timeout.

El [diagnóstico posterior](base-interpreter-diagnostic.json), realizado tras la
parada, comprobó que el venv resuelve Django y psycopg, mientras el intérprete base
no resuelve ninguno. Un import aislado de Django en ese intérprete produjo
`ModuleNotFoundError: No module named 'django'`. No ejecutó tests, el entrypoint
B3, `django.setup()` ni acceso a base de datos, y no instaló dependencias.
El stderr original de los hijos fue descartado por el cleanup del test del
candidato: el diagnóstico conservado es evidencia separada, no ese traceback original.

La parada durable original conserva `PENDING_CLASSIFICATION`; la clasificación
final separada determina **PENDING por entorno/harness**. No se sobrescribieron
el STOP, el gate bruto ni los recibos. No se corrigió el entorno para repetir
la suite dentro de esta campaña. Los bloques restantes no se iniciaron.

## Conservación y cierre

El [cleanup](cleanup.json) pasó: se guardaron observaciones SQL y tablas de las
bases aún existentes, sin conexiones ajenas ni transacciones preparadas; se
retiraron las tres bases propias restantes, PostgreSQL y únicamente
`/home/lap/b9i-wsl-1947726-20261011-r3`. El puerto quedó cerrado. Los runners
Django ya habían destruido sus bases B0/B3 conforme a su operación original.

La [restauración del reloj](clock-restoration.json) pasó: `systemd-timesyncd`
volvió a **active/running/enabled**, coincidiendo con el estado original.
La pausa no quedó aplicada al terminar; W32Time permaneció intacto.

Los **319 archivos de las tres campañas anteriores** y los tres cambios ajenos
del checkout se conservaron sin diferencias; ver `preservation-of-prior-work.json`.
Este expediente tiene inventario, hashes, paquete propio, restaurador y prueba de
recuperación real por CLI. [Procedimiento](README.md). Los logs mantienen sus
bytes originales dentro del paquete. La selección Git es explícita, en la misma
rama; no se crearon commits ni se hizo push, despliegue o activación.

R1-04 conserva PENDING con limitación aceptada y cero intentos físicos nuevos.
La activación sigue **PENDING_ACTIVATION_REQUIREMENTS**; E/P/UX y aprobaciones
operativas/privacidad permanecen separados. Otra campaña requeriría una decisión
nueva y resolver, antes del sello, la compatibilidad del intérprete usado por los
subprocesos. Este expediente queda cerrado sin reintentos automáticos.
