# B9E — aceptación de 1947726 en WSL2, campaña r4

**Decisión integral: PENDING por recursos del host.** Se corrigió y validó la
visibilidad de las dependencias en los dos intérpretes privados. El preflight
pasó, pero Windows bajó de **5,70 GiB** libres a **3,60 GiB** en el control
inmediato anterior al corpus dirigido. El plan exige 5 GiB antes de cada bloque.
La campaña se detuvo antes de iniciar el primer test: **cero tests, checks de
aplicación y variantes PROFILE ejecutados**. No se atribuye fallo al producto.

Candidato: `194772677ca4e9fe1a1dec7f4dafa48396a6c583`.
Autorización: «hazlo», para preparar ambos intérpretes con el mismo lock,
validarlos antes del sello y ejecutar una campaña nueva conservando los gates.
El intento formal ocurrió el **11-10-2026 en México**, entre las
**02:43:59 y 02:44:34 UTC del 12-10-2026**.
[Parada original](STOP.json), [clasificación](incident-classification.json)
y [decisión R01–R15/I01–I14](candidate-decision.json).

## Corrección y preparación acreditadas

- Las 3.332 fuentes exportadas coinciden con los blobs exactos del candidato.
- Python 3.13.2: el mismo `requirements.lock` se instaló en el venv y en su
  prefijo base privado, que seleccionan los tests antiguos mediante
  `sys._base_executable`. No se redirigió ese atributo ni se modificaron tests.
- Ambos intérpretes cargaron Django y los módulos durable, worker y psycopg
  con la misma configuración de base privada. La paridad de paquetes pasó:
  Django 6.0.5 y psycopg 3.3.4, entre las dependencias congeladas. Las dos
  comprobaciones de compatibilidad de dependencias terminaron con exit 0.
- Esa validación fue de imports y configuración: no ejecutó el entrypoint B3,
  tests, claims, crashes, timeouts ni fixtures de aplicación. No demuestra
  que el contrato B3 pase; sí comprueba la preparación que faltaba en r3.
- Se registraron hashes de 13.508 archivos de dependencias de ambos entornos.
  Sus controles de preflight y anterior al bloque dirigido no tuvieron diferencias.
- Node 20.20.2 y pnpm 9.15.9: instalación frontend con `--frozen-lockfile` PASS
  en Linux, conservando el lock. No se ejecutaron build, Vitest o smoke.
- PostgreSQL 16.15 local privado, puerto 35479, con `fsync`,
  `synchronous_commit` y `full_page_writes` habilitados, sin datos productivos.
- Discovery sin IDs ausentes, duplicados o errores: dirigido 87, completo
  3.331, B0 17, B3 42, B4 68 y B5 37. Son denominadores, no resultados ejecutados.
- Las tres fuentes del PROFILE siguen idénticas a las de 0831046. Se preservaron
  fixtures, tasas, población, concurrencia, proveedores, tiempos y gates.

El [sello](evaluation-seal.json) cubre 96 archivos evaluativos, configuraciones,
diagnósticos y ejecutables, además de los manifiestos de fuentes y dependencias.
Sus dos controles pasaron. Las fuentes también pasaron la integridad final antes
del cleanup. Los diffs y hashes previos quedan en `adapter-lineage*.json` y
`preseal-environment-amendments.json`. El helper `diagnostics/close_campaign.py`
se añadió después del STOP únicamente para informes y cierre; no pertenece al
evaluador sellado ni ejecuta tests.

## Reloj y recursos

La sincronización de WSL se pausó temporalmente con el guardián autorizado,
restauración al cierre y concesión máxima de seis horas. Esa concesión solo
limita la pausa del servicio si desaparece el controlador; no cambia las
duraciones de tests ni el límite original de discontinuidad de un segundo.
La observación concurrente de 120 segundos pasó: máximo civil−monotónico
**0,0001397 s en Windows** y **0,000066158 s en WSL**. No acredita estabilidad
universal. No hubo bloques ejecutados ni monitor de rendimiento de aplicación.

Durante la preparación se observaron fluctuaciones de memoria del host y se
esperó a disponer de margen. La ruta de la sonda Windows se adaptó al Python
3.13.2 actualmente usado por las herramientas; sigue consultando el mismo
`GlobalMemoryStatusEx`, con el mismo usuario y umbral. Las muestras tomadas en
momentos diferentes no establecen la causa de las fluctuaciones. La adaptación
se documentó antes del sello en `preseal-resource-observer.json`.

También se retiraron 122.412.400 bytes de descargas y extracciones ya utilizadas
dentro del workspace privado. No se retiraron fuentes ni dependencias instaladas
y no se terminaron procesos ajenos. El recibo es `preseal-preparation-cleanup.json`.
La mejora de memoria posterior no se atribuye exclusivamente a esa operación.

La observación previa al intento registró **6,07 GiB** disponibles en Windows.
El preflight formal pasó a las **02:44:17 UTC** con **5,70 GiB** en Windows,
**7,07 GiB** en WSL y **4,03 GiB** de disco real de respaldo. A las
**02:44:33 UTC**, antes del primer bloque, Windows tenía **3,60 GiB**,
WSL **7,06 GiB** y el disco **4,03 GiB**. El gate de memoria del host no pasó.
Se conservaron los mínimos de 5 GiB antes de cada bloque, 2 GiB de reserva
durante la ejecución y 1 GiB de disco. No se rebajó ningún requisito.

## Estado de ejecución

| Bloque | Estado de esta campaña |
| --- | --- |
| Preflight, resolución de runners y ambos intérpretes | PASS de preparación |
| Corpus dirigido, 87 IDs | NOT_EXECUTED por parada previa de recursos |
| Checks Django, drift, migración y schema Billing | NOT_EXECUTED |
| B0/B3/B4/B5 y suite completa de 3.331 IDs | NOT_EXECUTED |
| Build, tests, lint y smoke frontend | NOT_EXECUTED |
| Gitleaks y auditorías advisory | NOT_EXECUTED |
| BASE, BLOCKED_LLM, META_SLOW, DUPLICATE y SATURATION | NOT_EXECUTED |

Hubo una invocación del controlador formal, cero bloques iniciados y cero
observaciones de IDs ejecutados. Los resultados de r3 siguen en su expediente;
no se transfieren como resultados de r4. La parada durable original se conserva
sin modificación y no hubo ajustes después del sello ni reintentos.
[Conteos](execution-summary.json) y [estados por bloque](block-status.json).

## Conservación y cierre

El [cleanup](cleanup.json) pasó: se guardó el estado SQL, se retiró únicamente
`test_b9i_control`, se detuvo PostgreSQL, el puerto quedó cerrado y se eliminó
solo `/home/lap/b9i-wsl-1947726-20261011-r4`. La
[restauración del reloj](clock-restoration.json) pasó: WSL volvió a
**active/running/enabled**, coincidiendo con su estado inicial. W32Time y la
configuración horaria de Windows permanecieron intactos.

Se verificaron sin diferencias los **550 archivos de las cuatro campañas
anteriores** y los tres cambios ajenos del checkout. El acta recibió únicamente
un añadido, conservando su prefijo exacto. El expediente tiene inventario,
paquete propio, hashes y recuperación comprobada mediante el restaurador y
una invocación real por CLI. [Procedimiento](README.md). Los logs originales
quedan dentro del paquete. La selección Git es explícita en la misma rama;
no se crearon commits ni se hizo push, despliegue o activación.

R1-04 mantiene PENDING con limitación aceptada, sin intentos físicos nuevos.
La activación sigue **PENDING_ACTIVATION_REQUIREMENTS**, con E/P/UX y las
aprobaciones operativas/privacidad separados. El expediente queda cerrado.
Otra campaña requiere una decisión nueva y recursos suficientes antes de cada
bloque; el preflight satisfactorio de r4 no sustituye esos controles.
