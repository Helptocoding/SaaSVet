# SaaSLyVet — conductor de medición D29

Fecha: 2026-10-05. Baseline de aplicación: `825db75df68bf076929fa787e77beefe96803350`.
Encargo: preparar el conductor y acreditar su medición con casos finitos aislados.

**Resultado: núcleo de medición acreditado; automatización y aceptación de la matriz completa todavía no acreditadas.** El [recibo de ejecución](../evals/scheduling-driver-2026-10-05/report.md) conserva resultados, fuentes y limpieza. El [protocolo D29-v1](2026-10-05-scheduling-characterization-protocol.md), su manifiesto y los recibos anteriores permanecen intactos: su estado histórico no se reescribe.

La solicitud posterior «puedes hacer lo que sigue» autoriza este trabajo en el harness y su validación mínima. Se añadieron herramientas de prueba; no se implementó scheduling, no se hizo tuning y no se cambió código existente, configuración persistente o E4. El encargo no se interpretó como permiso para benchmarks ni barrido sostenido.

## Archivos y capacidades

| Archivo | Responsabilidad |
| --- | --- |
| [evidence.py](../../backend/apps/agent/tests/scheduling_characterization/evidence.py) | Reconstruye población desde ingreso committed, conserva pendientes y orígenes desconocidos, agrupa W1/W2, aplica intervalos y separa recovery. |
| [runner.py](../../backend/apps/agent/tests/scheduling_characterization/runner.py) | Valida aislamiento, registra ofertas/cortes/journals, ejecuta acreditación y prueba finita de planners/sender; prepara oferta observable por nivel. |
| [test_scheduling_characterization.py](../../backend/apps/agent/tests/test_scheduling_characterization.py) | 25 pruebas de fronteras, pérdida de población, duplicados, clocks, transacciones, tenants y backlog. |

El conductor registra cada oferta y sus resultados, y concilia las aceptaciones durables con el inventario completo de entradas ordinarias. No utiliza una consulta de claims completados para construir el denominador. Conserva las obligaciones aún no READY, los episodios READY sin claim, el trabajo ya asignado y la recuperación por separado.

El origen proviene de la historia committed del deadline, con monotonía antes del claim; el final es el commit exterior. Los timestamps se calculan como intervalos con reloj DB correlacionado con monotónico, condicionados a ausencia de saltos no observados. Calibraciones incompatibles, transacciones inciertas, cohortes incompletas, mezcla de runs o sesiones duplicadas impiden acreditar cumplimiento. No se añade tolerancia a los 120 s.

Un error de ACK seguido por ROLLBACK no demuestra que COMMIT falló en el servidor. La acreditación incluye un commit real con ACK perdido, resuelto mediante lectura independiente de work, epoch, fingerprint y membership. La cota superior procede de visibilidad durable, no del final del error. Los savepoints se distinguen del commit exterior y los efectos deshechos se excluyen.

Todos los artefactos propios usan IDs técnicos y metadatos, sin texto de mensajes, prompts, contenido clínico, tokens crudos, secretos ni SQL/params. Los procesos reutilizan el provider sintético existente y los comandos reales del baseline; no se invocan el observador ni los gates históricos de E4.

## Comandos y condiciones

Desde `backend`, con RTK:

```powershell
rtk proxy python -X utf8 -m unittest apps.agent.tests.test_scheduling_characterization -v
rtk proxy python -X utf8 -m apps.agent.tests.scheduling_characterization.runner --help
```

Los comandos DB requieren `B3_TEST_DATABASE` explícita en el entorno del proceso, con ENGINE PostgreSQL, HOST local, NAME `test_*`, PORT explícito y durabilidad activada. La configuración efectiva se verifica antes de usar los fixtures. No se documenta ni se conserva una contraseña de la sesión de acreditación: su entorno ya fue cerrado.

| Comando | Propósito y límite |
| --- | --- |
| `accredit` | Casos finitos de pendientes, W1/W2, duplicado, rollback exterior/savepoint y ACK perdido. Claims directos y finalización explícita son fixtures de frontera. |
| `smoke` | Dos entradas ordinarias, dos planners y un sender, con READ público y provider simulado. Comprueba captura concurrente y pipeline; no ofrece una tasa sostenida. |
| `analyze` | Reconstrucción offline; requiere run ID y directorio de un recibo. Crea salida nueva y no sobreescribe el original. |
| `worker` | Participante interno, con captura independiente por proceso/conexión. |
| `level` | Oferta observable de R1-01–R1-06 preparada en código; requiere plan y `--execute-load` explícitos. No se ejecutó ni se acreditó aquí como nivel de carga. |

`accredit`, `smoke` y `level` requieren base nueva sin Message/TurnWork y directorio de salida inexistente. Sellan inventario de fuentes y conservan journals por participante. Se detienen ante preparación o captura insuficiente; un receipt de cohorte no equivale a aceptación de nivel, contrato o E.

El plan de nivel contiene `baseline`, `protocol_version`, `case_id`, `conversations_per_org`, `offered_rates_per_minute` y `offer_seconds`; la ráfaga añade `burst_org_indexes`. Los pares de tasas equilibradas/2:1 se verifican. Los valores de duración admitidos corresponden a la versión D29-v1; cambios prospectivos requieren nueva versión del plan/protocolo y del conductor cuando cambie su interpretación. No se cambian parámetros o resultados anteriores. No hay una tasa clínica predeterminada.

## Acreditación obtenida y trabajo posterior

Pasaron las 25 pruebas del análisis, los 12 controles de acreditación DB y los 7 controles de la prueba concurrente. La prueba de frontera conserva dos episodios READY sin claim al primer corte y W2 READY mientras W1 sigue PROCESSING. La prueba concurrente captura dos claims nuevos, dos trabajos completados y dos aceptaciones del provider simulado. Las dos corridas se reportan como `COHORT_ONLY_NOT_LEVEL_ACCEPTANCE`.

La automatización completa D29 exige todavía un controlador de calibración/barrido/refinamiento/confirmaciones, conciliación de demanda realmente emitida con el perfil pretendido, acreditación de invariantes y ventanas para clasificar niveles, y recetas de escenarios/fallos con sus fronteras verificadas. La captura preparada por `level` no sustituye esos controles. R1-04 necesita demostrar demanda READY coexistente con elegibilidad futura repetida; generar dos orgs por sí solo no acredita ese caso. R1-05/R1-06 dependen de una tasa base confirmada. R2 no está disponible como selección del comando `level`; el guard rechaza esos IDs.

Estas son capacidades técnicas de la fase de pruebas, no decisiones nuevas de SLA. Después corresponde obtener observaciones de caracterización con autorización de carga, proponer E y ratificar las decisiones contractuales pendientes. No se puede declarar la matriz completa lista, capacidad sostenible ni factibilidad del scheduler a partir de esta acreditación.
