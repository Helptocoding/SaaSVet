# WA-PERF-02 — lista completa mediante paginación

Estado: **implementada y verificada localmente** (2026-10-21).

La API devuelve `{results, has_more, next_offset}` en páginas de 100 hilos,
incluida la petición sin `offset`. El desplazamiento inválido devuelve 400.
Obtiene una cabecera adicional para detectar otra página, sin COUNT ni consultas
por fila. Mantiene urgencia, actividad del mensaje y actividad del bucket;
contacto/cuenta desempatan de forma determinista. No requiere migraciones.

La bandeja anuncia cuántas conversaciones ha cargado y si quedan más. «Cargar
más» añade filas, deduplica por contacto/cuenta y bloquea clics simultáneos.
El refresco de 20 s vuelve a pedir todas las páginas cargadas y las publica
juntas: un fallo parcial conserva la lista previa. Mantiene selección/borrador,
reinicia el desplazamiento al cambiar de filtro e ignora respuestas antiguas.
No inicia páginas adicionales del refresco al ocultarse o desmontarse.

| Comprobación | Resultado y recibo |
|---|---|
| API PostgreSQL | **21 PASS**: siete casos nuevos y 14 regresiones afectadas. 250 hilos → 100/100/50; cursor, empates, urgencia, archivados, cuentas distintas, tenant, autenticación, desplazamientos inválidos y agotamiento. [backend.json](backend.json), [backend.log](backend.log). |
| Regresión PERF-01 | Fixture de filas congelada sin cambios, comparación dentro de `results`; número constante de consultas con 30 hilos adicionales y ausencia de materialización del historial. Incluida en los 21 PASS, sin afirmar latencia constante. |
| React | **29 casos únicos PASS**: 16 nuevos de paginación y 13 de carga/reconexión, visibilidad y título afectados por `loadList`. [frontend-composite.json](frontend-composite.json). |
| Compilación y lint | Build PASS, sin subir sourcemaps; advertencias de tamaño de bundle/plugin conservadas. Lint de componente y tests PASS; tras corregir selectores se repitió sólo lint del test. [build-run.json](build-run.json), [build.log](build.log), [lint-run.json](lint-run.json), [lint-final-run.json](lint-final-run.json). |
| Chromium local | Escritorio 1366×768 y móvil 390×844 PASS, API sintética: 250 filas accesibles en orden, teclado, aviso explícito, reset de filtro, error/reintento con filas y borrador intactos. Botón de 44 px, área libre de superposiciones, sin overflow horizontal ni errores JS. [browser.json](browser.json), [escritorio](pagination-desktop.png), [móvil](pagination-mobile.png). |
| Cleanup e integridad | Base temporal eliminada comprobando `pg_database`; árbol Vite propio terminado y puerto libre. [source-sha256.json](source-sha256.json), [final-checks.json](final-checks.json). |

El intento inicial de frontend tuvo **27 PASS y dos fallos del harness**:
un selector `/Beto/` también coincidía con un preview heredado por la fixture
de Caro, y las búsquedas globales de roles sobre 250 filas agotaban el timeout
de 5 s. Se conservaron los recibos [iniciales](vitest-attempt1.json).
La búsqueda de 250 filas se acotó al footer y al texto exacto, manteniendo las
aserciones de cantidad, orden y botones y el mismo timeout. [Dos casos corregidos](vitest-repaired.json)
pasaron; después se restauró la fixture compartida original y se acotó únicamente
el selector del caso ambiguo a `/^Beto/`, [verificado de nuevo](vitest-selector-final.json).
Los 27 PASS iniciales siguen aplicando a sus mismas fixtures. No se cambió código
de producto para resolver estos fallos.

Limitaciones: paginación por offset sobre una lista viva, sin snapshot entre
peticiones; la deduplicación y el refresco completo de las páginas cargadas
reconcilian cambios de posición. El coste del refresco crece con las páginas
abiertas; PERF-03 incremental sigue pendiente. El título conserva la señal
`has_unanswered` de los hilos cargados, sin prometer un conteo global por usuario.

No se ejecutaron suites generales ni B9. Esta evidencia local con datos sintéticos
no sustituye recepción/Meta real ni revoca el FAIL de seguridad r12.
Sin commit, push, despliegue ni activación. Siguiente tarea: **WA-HIST-01**.
