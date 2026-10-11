# Preflight diagnóstico de scheduling — 2026-10-05

Estado: **PREFLIGHT_PARTIAL**. El bloqueo de entorno quedó resuelto y se verificaron capturas completas en un alcance reducido. La medición de toda la matriz de caracterización sigue **NOT_ESTABLISHED**.

Baseline: `825db75df68bf076929fa787e77beefe96803350`. La ejecución se limitó al preflight autorizado por el «sí» del usuario y a la preparación temporal solicitada después con «puedes hacerlo?». No se ejecutó un benchmark ni un barrido de carga.

Se creó una copia del baseline y una base nueva `test_scheduling_preflight_20261005` en PostgreSQL local 16.15, con `fsync=on` y `synchronous_commit=on`. Se aplicaron las migraciones existentes únicamente en esa base vacía. La configuración y `B3_TEST_DATABASE` existieron solo en los procesos del diagnóstico; los archivos de entorno del repositorio se conservaron. Un conductor temporal fuera del repositorio reutilizó el harness y el helper existentes, sin modificar la aplicación.

La captura contiene dos organizaciones, cuatro inbounds ordinarios y tres claims nuevos mediante el helper de claim. No ejecuta el selector, un planner ni un sender. La finalización explícita de W1 es una acción de fixture para permitir el claim posterior de W2. Los deadlines vencieron de forma natural, sin adelantar el reloj ni sobrescribirlos desde el fixture.

| Caso | Evidencia observada |
| --- | --- |
| Organización A, W1 | El mensaje inicial y la corrección anterior al claim son miembros del mismo work; la corrección hereda el deadline ya vencido. |
| Organización B, W1 | Su mensaje tiene un claim committed propio, correlacionado con organización y conversación. |
| Organización A, W2 | El inbound posterior al claim no se añade a W1 y queda como único miembro de un nuevo work después de terminar W1. |

Los cuatro journals pasaron la comprobación de secuencia, correlación, footer y cierre transaccional del lector existente. Los tres claims tienen ingreso, membresía, calibración de reloj y commit correlacionados; cada helper usó una conexión PostgreSQL distinta. El ingreso inicial de cada episodio terminó antes de su deadline. En esta historia controlada, READY se reconstruye desde ese deadline y no desde el primer poll. El commit del claim queda acotado por la ejecución del driver y su calibración con el reloj de la base.

Los [intervalos observados](boundary-observations.json) son condicionales a que no haya saltos de reloj. Incluyen la secuenciación y el arranque de procesos del diagnóstico: no describen la cola bajo carga ni sirven para elegir tasas, E o un SLA. No se evaluó el objetivo de dos minutos.

Antes de la caracterización completa faltan:

- Acreditar la cobertura de todos los episodios READY, incluidos los pendientes que nunca obtienen claim.
- Fijar y verificar el criterio de precisión temporal y los supuestos de reloj de D29.
- Delimitar la evidencia para backlog anterior, legado NULL, ownership, rollback, commits inciertos y recovery; estos casos no se ejecutaron aquí.
- Completar el protocolo ejecutable de la matriz y su encargo de ejecución, conservando las decisiones de producto pendientes.

La preparación tuvo un timeout del wrapper de arranque por pipes heredados y un timeout inicial al crear el esquema. Se detuvo la primera instancia, se inició una segunda mediante un proceso oculto con logs a archivos y se completó el esquema existente. Estos incidentes no modificaron parámetros del runtime ni resultados históricos.

Al finalizar se cerraron las instancias temporales, se verificaron ambos puertos cerrados y se eliminaron sus directorios de datos y credenciales temporales. La copia de código y el conductor quedan fuera del repositorio para trazabilidad. La [comprobación de integridad](cleanup-and-integrity.json) confirma **3070 rutas protegidas sin cambios**, incluidos los dos archivos `.env` existentes y los artefactos E4. Los mapas inicial y final tienen SHA-256 `704b852617cd8207ec6f346bef3542e5a00cb30594ad108fb92ba1e1b2cd840a`.

Este recibo es evidencia diagnóstica prospectiva. No congela el contrato, valida capacidad, reabre E4 ni autoriza implementación o release.
