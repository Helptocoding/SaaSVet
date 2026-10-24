# B9E — aceptación de 1947726 en WSL2, campaña r5

**Decisión integral: PENDING por recursos del host.** Conforme a la instrucción
«procede con lo disponible actual, no puedo liberar mas aun», esta campaña
retiró el mínimo previo de admisión de 5 GiB y conservó la reserva de ejecución
de 2 GiB. El preflight pasó y el corpus dirigido comenzó con **4,09 GiB libres
en Windows**. Durante las migraciones de su base privada, el host bajó a
**1,61 GiB**, agotando esa reserva. El controlador interrumpió su grupo de
procesos. **Ningún ID de test terminó y ninguna variante PROFILE se ejecutó.**

Candidato: `194772677ca4e9fe1a1dec7f4dafa48396a6c583`. El controlador formal
corrió entre **03:07:06 y 03:08:10 UTC del 12-10-2026**, todavía el
**11-10-2026 en México**. El expediente es independiente de las cinco campañas
anteriores. [STOP original](STOP.json), [clasificación](incident-classification.json),
[decisión R01–R15/I01–I14](candidate-decision.json).

## Condición de recursos autorizada

La [autorización](authorization.json) y la [política](resource-policy.json)
documentan el cambio antes del sello: se permite admitir un bloque con los
recursos actuales si host y guest conservan al menos 2 GiB, manteniendo esa
reserva durante la ejecución. El presupuesto estimado de 3 GiB por suite no
queda garantizado. Se preservan el disco real mínimo de 1 GiB, el monitor
horario original de 1 s, la integridad y la parada ante incidentes invalidantes.
No se afirma que se haya cumplido el prerrequisito original de 5 GiB. La
evidencia pertenece a esta condición de recursos explícitamente modificada.

La orquestación conserva suites secuenciales y concurrencia interna original.
No se modificaron producto, tests, fixtures, tasas, población, proveedores,
duraciones, aserciones ni umbrales de contrato. No se terminaron procesos ajenos
para obtener memoria. No se realizaron cambios después del sello ni reintentos.

## Preparación y preflight

- Las 3.332 fuentes exportadas coinciden con los blobs exactos del candidato.
- Python 3.13.2, con el mismo `requirements.lock` instalado en el venv y en su
  prefijo base privado. Se conserva el `sys._base_executable` original que
  seleccionan los tests antiguos de procesos. Ambas comprobaciones de
  dependencias terminaron con exit 0.
- Ambos intérpretes cargaron Django, durable, worker y psycopg con la misma
  configuración privada. Paridad de paquetes PASS, incluidos Django 6.0.5 y
  psycopg 3.3.4. La validación no ejecutó el entrypoint B3, claims, crashes,
  timeouts ni tests. No acredita PASS del contrato B3.
- Se congelaron hashes de 13.508 archivos de dependencias y 97 archivos de
  evaluador, configuración, diagnósticos y ejecutables. Los controles de
  preflight, anterior y posterior al bloque interrumpido pasaron. La integridad
  final de las 3.332 fuentes también pasó antes del cleanup.
- Node 20.20.2 y pnpm 9.15.9: instalación frontend con `--frozen-lockfile` PASS.
  No se ejecutaron build, tests o smoke frontend.
- PostgreSQL 16.15 local privado, puerto 35479, con `fsync`,
  `synchronous_commit` y `full_page_writes` habilitados. Sin datos productivos.
- Discovery resolvió 87 IDs dirigidos, 3.331 completos, B0 17, B3 42, B4 68 y
  B5 37, sin faltantes, duplicados o errores. Discovery no equivale a ejecución.
- Las tres fuentes del PROFILE siguen idénticas a las del candidato histórico
  0831046. Se conservaron sus cinco variantes y gates originales.

Los diffs y hashes previos están en `adapter-lineage.json` y
`preseal-environment-amendments.json`. Se retiraron únicamente archivos propios
de descarga/extracción ya utilizados antes de sellar, conservando las fuentes y
dependencias instaladas. El recibo es `preseal-preparation-cleanup.json`.

## Ejecución e incidente

El preflight pasó con **3,93 GiB** libres en Windows. El control inmediato
anterior al corpus dirigido registró **4,09 GiB**, por lo que admitió el bloque
conforme a la política modificada. La invocación del bloque duró **29,84 s**,
incluido el control y la terminación, con una sola ejecución formal.

El [monitor](monitor-directed.json) conserva **23 muestras**. El mínimo
observado de Windows fue **1.728.331.776 bytes (1,61 GiB)**, inferior a los
2 GiB retenidos. El mínimo de WSL fue **7.429.480.448 bytes (6,92 GiB)**;
el disco permaneció por encima de 1 GiB. El máximo desfase civil−monotónico fue
**0,000000995 s**, dentro del límite de 1 s. Se agotó la reserva del host, sin
incidente invalidante registrado de reloj o disco. Las muestras no establecen
la causa única de la fluctuación de memoria.

El controlador envió SIGTERM únicamente a su grupo de procesos y registró
exit **-15**. El log del runner termina en las migraciones de la base privada,
en `channels.0014_alter_message_semantic_type`. El inventario de 87 IDs existe,
pero el journal de IDs aprobados está vacío y el recibo final no se produjo.
La migración parcial y un inventario no se convierten en resultado de tests.
No se atribuye un fallo al producto. [Resumen de ejecución](execution-summary.json)
y [estadísticas del monitor](monitor-summary.json).

| Bloque | Estado de r5 |
| --- | --- |
| Preflight y validación de ambos intérpretes | PASS de preparación con admisión modificada |
| Corpus dirigido | INTERRUMPIDO durante migraciones; cero IDs completados |
| Checks Django, drift, migrate y schema Billing | NOT_EXECUTED como bloques independientes |
| B0/B3/B4/B5 y suite completa | NOT_EXECUTED |
| Build, tests, lint y smoke frontend | NOT_EXECUTED |
| Gitleaks y auditorías advisory | NOT_EXECUTED |
| BASE, BLOCKED_LLM, META_SLOW, DUPLICATE y SATURATION | NOT_EXECUTED |

Los resultados de las campañas anteriores permanecen en sus expedientes y no
se transfieren a r5. La parada durable original y todos los recibos se conservan.

## Reloj, conservación y cierre

La pausa temporal autorizada de sincronización de WSL contó con guardián y
restauración al cierre, con concesión máxima de seis horas. Esa concesión no
cambia los tiempos de tests. La observación previa concurrente de 120 s pasó:
máximos civil−monotónico **0,00023 s en Windows** y **0,000168191 s en WSL**.
Es una observación acotada, no una garantía universal.

El [cleanup](cleanup.json) pasó: se conservaron las observaciones SQL y tablas,
se retiraron `test_b8b_b9i_directed` y `test_b9i_control`, se detuvo PostgreSQL,
el puerto quedó cerrado y se eliminó únicamente
`/home/lap/b9i-wsl-1947726-20261011-r5`. La
[restauración del reloj](clock-restoration.json) pasó: WSL volvió a
**active/running/enabled**, como al inicio. W32Time permaneció intacto.

Se comprobaron sin diferencias los **730 archivos de las cinco campañas
anteriores** y los tres cambios ajenos del checkout. El acta recibió un añadido
con su prefijo exacto conservado. El helper `diagnostics/close_campaign.py`
se creó después del STOP únicamente para informes y cierre, sin modificar el
evaluador sellado ni ejecutar tests.

El expediente cuenta con inventario, hashes, paquete propio y restauración
comprobada mediante el restaurador y una invocación real por CLI.
[Procedimiento](README.md). Los logs originales quedan incluidos en el paquete;
la selección Git es explícita, sin modificar las selecciones previas fuera de
los tres archivos compartidos de entrega. No se crearon commits ni se hizo push,
despliegue o activación.

La aceptación integral sigue **PENDING**. R1-04 mantiene PENDING con limitación
aceptada, sin intentos físicos nuevos. Activación **PENDING_ACTIVATION_REQUIREMENTS**,
E/P/UX y aprobaciones operativas/privacidad separados. El expediente queda cerrado,
sin reintentos automáticos después de esta parada.
