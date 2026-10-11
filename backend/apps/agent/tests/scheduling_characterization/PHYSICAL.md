# Acreditación física finita D29

`physical.py` registra únicamente R1-07, R2-03, R2-04, R2-05, R2-06, R2-07,
R2-08 y R2-10: 25 variantes. No importa ni ejecuta Controller.run, calibración,
series, niveles, búsqueda de máximo ni E. Las primitivas de aplicación se leen
del baseline `825db75df68bf076929fa787e77beefe96803350` sin modificarlas.

Desde backend, sobre una copia de ese baseline con estas herramientas añadidas:

```text
rtk proxy python -m apps.agent.tests.scheduling_characterization.physical run --case R2-03 --variant precommit --run-id physical-example --output <directorio-nuevo>
rtk proxy python -m apps.agent.tests.scheduling_characterization.physical verify --output <directorio-con-receipt>
rtk proxy python -m apps.agent.tests.scheduling_characterization.physical_matrix eight --template <test_schema_vacio> --run-id eight-example --output <directorio-nuevo>
rtk proxy python -m apps.agent.tests.scheduling_characterization.physical_matrix full --template <test_schema_vacio> --run-id matrix-example --output <directorio-nuevo>
```

La ejecución exige B3_TEST_DATABASE explícito (JSON PostgreSQL, test_*, loopback,
puerto explícito) y fsync/synchronous_commit activados. SECRET_KEY y todas las
credenciales de prueba pertenecen solo al entorno del proceso. No usar .env real.
Si la copia no tiene .git, D29_ARCHIVE_REPOSITORY apunta al repositorio original
solo para comparar las fuentes con git archive. Cada variante recibe un clon
nuevo; nunca se reutiliza ni elimina una DB preexistente. El template debe estar
vacío y sin conexiones. El comando run trabaja exclusivamente sobre una DB
privada que el llamador elimina; eight/full gestionan los clones en finally.

verify funciona sin DB ni credenciales y comprueba hashes, procedencia, evidencia
referenciada, invariantes, cobertura ordenada, recuperación natural y cleanup.
Un PASS escrito en un modelo, un journal incompleto no resuelto o una frontera
ausente no acreditan el escenario. receipt.json identifica cualquier error;
verification.json conserva missing/violations. Los journals de crash no se
reparan: exit.json y el census independiente resuelven el resultado físico.

Los clocks son los de PostgreSQL. La lease de 15 minutos, backoffs de 30/60
segundos y TTL de operación de 30 minutos son los valores originales del
baseline; no son SLA propuestos ni ajustes de esta fase. No se adelantan.
deadline_at prepara el proceso antes del deadline y bloquea la recepción con un
mutex real: conserva un intervalo que cruza D, nunca inventa igualdad exacta.
legacy_null es un fixture histórico independiente con origen declarado UNKNOWN.

Las recetas conservan sus requisitos CONFIRMED_BASE. full ejecuta los nueve
adaptadores anteriores en modo finite-probe y conserva explícitamente los
requisitos o fronteras que el probe no demuestra. Ninguna tasa sintética ni un
probe de dos inputs sustituyen una base confirmada. Una cobertura física parcial
mantiene FULL_LIVE_MATRIX_NOT_READY; estos comandos no habilitan caracterización
ni aceptan niveles aunque los ocho adaptadores nuevos queden acreditados.

Los proveedores son el wire contenido B9A, el cliente HTTP Django local y un
error LLM contenido después de admisión real. Los gates WRITE permanecen
cerrados. El guard negativo usa la propuesta, emisión y consentimiento reales;
no usa LocalTestAdapter para fabricar un efecto ni parchea la autoridad.

execution.py conserva su comportamiento de carga. Solo el seguimiento del probe
finito espera el hold declarado de R2-02 y conserva el resultado UNCERTAIN de
R2-09 como incertidumbre, sin contarlo como aceptación del proveedor. No se ha
extendido el backend de series: los nuevos adaptadores acreditan fronteras
finitas y todavía no producen aceptación de carga.
