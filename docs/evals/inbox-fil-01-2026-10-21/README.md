# WA-FIL-01 — filtros segmentados del Inbox

Corte local del 2026-10-21. Implementación y verificación dirigidas completadas.
Siguiente pendiente del roadmap: **WA-SRCH-01**.

## Resultado y contrato

Los cuatro chips consultan al servidor: «Sin atender» (`unanswered=1`),
«Esperando cliente» (`unanswered=0`), «Urgentes» (`urgent=1`) y «Míos»
(`claimed=me`). Atención es excluyente; urgencia y responsable se combinan AND.
La API también permite el UUID público de otro responsable de la misma clínica.

Se filtra la proyección agrupada después de elegir su cabecera y antes del
offset/cap. Atención conserva la semántica de `has_unanswered`: dirección del
último mensaje operativo visible del hilo, independiente de lectura personal.
Un hilo sin mensajes no está en ninguno de los dos segmentos de atención.
Urgencia y responsable se evalúan sobre el episodio abierto vigente; una sesión
cerrada histórica no puede sustituirlo ni aportar un claim/handoff al filtro.
`archived=1` sigue incluyendo abiertos y cerrados. `urgent=0` desactiva el filtro.
Los booleanos aceptan 0/1 y false/true. Filtro inválido: 400 `invalid_filter`;
UUID ajeno a la clínica o conjunto sin coincidencias: 200 vacío.

Los cursores quedan ligados a los filtros normalizados, org, usuario, archivo y
offset. `me` y el UUID propio son equivalentes. Cambiar de segmento aborta el GET,
invalida su revisión y reinicia páginas/cursores; los polls y páginas siguientes
conservan filtros. Un delta retira el hilo que deja de cumplirlos. La UI muestra
«Sin coincidencias», conserva chat/borrador y permite reintentar errores.
`unread_total` sigue siendo global para los hilos activos del empleado.

Cambios runtime: `backend/apps/agent/views.py`,
`frontend/src/pages/inbox/index.jsx` e `inbox.module.css`. No hay migración,
nueva dependencia, escritura de negocio ni cambio de permisos.

## Evidencia

| Comprobación | Resultado | Recibo |
|---|---|---|
| PostgreSQL: filtros nuevos y regresiones de lista | **52 PASS**, 14 nuevos y 38 afectados; una ejecución | `backend-directed.json` y `.log` |
| Frontend: segmentos nuevos | **10 únicos PASS**, evidencia compuesta | `vitest-new.json`, `vitest-retry-selector.json` |
| Frontend: página y sincronización afectadas | **109 PASS** | `vitest-affected.json` |
| Build | PASS, sin subida a Sentry | `build-final.json`, `.log` |
| Lint dirigido | PASS, cero errores y advertencias | `lint-complete.json`, `lint-report-complete.json` |
| Chromium escritorio y móvil | PASS con API sintética | `browser.json`, `browser-run.json`, capturas |
| Integridad, conteos únicos y limpieza | PASS | `final-checks.json`, `executed-tests.json`, `source-sha256.json` |

La API prueba filtros aislados/combinados, archivados, sin resultados, UUIDs,
permisos, tenant isolation, paginación antes del cap, número de consultas sin
crecer por fila, scope de cursor/equivalencias y retiradas al responder. Conserva
las regresiones existentes de payload/agrupación, urgencia, paginación de 250
hilos y transcript. El runner usa `failfast`: empieza por el módulo nuevo y
se detendría ante un fallo antes de seguir ampliando la ejecución.

La primera pasada frontend obtuvo nueve PASS y un fallo del harness: el test
buscaba «Reintentar», mientras el botón existente se llama «Reintentar ahora».
Se corrigió únicamente ese selector y se repitió solo aquel caso: un PASS y nueve
omitidos. Los nueve PASS iniciales se conservan; omitidos y repeticiones no se
suman. Total frontend: **119 casos únicos PASS**, diez nuevos y 109 afectados.
No se rebajaron assertions, tiempos ni guards y no se modificó el botón del producto.

El primer comando lint terminó con exit 0, pero su runner usó la misma ruta
para el reporte ESLint y el recibo del proceso. Se separaron las rutas y se
repitió solo lint con etiqueta `complete`; el recibo inicial se conserva.

La única ejecución PostgreSQL duró 410,93 s, incluidos preparación/migraciones y
limpieza de su base desechable; los 52 tests tardaron 155,79 s. Durante la espera
se comprobó el avance del log y `pg_stat_activity` en modo de solo lectura,
sin cancelar ni reiniciar la suite. No hubo fallos API ni repeticiones de esa base.
`test_database_remains=false` acredita su limpieza; la base de trabajo no se migró.

Chromium verifica 1366×768 y 390×844: Space con foco visible en escritorio,
tap móvil, tres segmentos AND, archivo conservado, atención excluyente, vacío
explicado y borrador intacto. Los cuatro controles miden 44 px de alto, sin
overflow horizontal ni errores JS. Las capturas `filters-desktop.png` y
`filters-mobile.png` se inspeccionaron visualmente. El Vite oculto pertenece al
harness, se cierra al terminar y deja el puerto 4178 libre.

## Reproducción

Desde la raíz, usar etiquetas nuevas para no sobrescribir recibos:

```powershell
rtk proxy python -X utf8 docs/evals/inbox-fil-01-2026-10-21/run_tests.py frontend reproduction src/pages/inbox/index.filters.test.jsx
rtk proxy python -X utf8 docs/evals/inbox-fil-01-2026-10-21/run_tests.py backend reproduction apps.agent.tests.test_inbox_filters apps.agent.tests.test_inbox_thread_pagination apps.agent.tests.test_inbox_thread_performance apps.agent.tests.test_inbox_threads
```

`run_browser.py`/`check_browser.py` reproducen el ensayo visual con recibos nuevos
en otro directorio de evidencia. `verify_results.py` valida los recibos de este
corte y genera un manifiesto exclusivo; no sobreescribe una verificación previa.

No se ejecutó suite general ni campaña B9. No se aplica M3, despliega o activa el
agente. Recepción real, Meta, media y seguridad/B9 r12 conservan sus pendientes.
El navegador con API sintética no acredita operación integrada real.
