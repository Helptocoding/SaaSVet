# WA-VIS-01 — pausa de polling por visibilidad

Estado: **implementada y verificada localmente** (2026-10-21). El hook compartido
`usePollingWhenVisible` sustituye los dos intervalos del Inbox. Ocultar limpia
intervalos; volver refresca lista/hilo inmediatamente y restaura cadencias de
20/10 segundos. Montar oculto no consulta esos endpoints. Cambiar de filtro o
hilo sustituye el callback y desmontar retira intervalos/listeners.

La carga inicial conserva su indicador; los refresh posteriores son silenciosos.
Se preservan las defensas existentes frente a respuestas de hilos anteriores y
la deduplicación del overlay. Una petición iniciada antes de ocultar puede terminar;
no se inicia ningún poll mientras `document.hidden` sea verdadero. Las acciones
explícitas, las métricas de carga única y el reloj local no cambian.

| Verificación | Resultado |
|---|---|
| Tests dirigidos | **17 PASS**, 32 excluidos: siete nuevos del hook, tres de integración y siete regresiones afectadas de título, navegación/POST tardío, deduplicación y medianoche. `vitest.json`, `frontend.log`, `run_frontend_tests.py`. |
| Build | PASS; `build-run.json` / `build.log`. Sin publicación a Sentry. Advertencia existente de chunk grande. |
| Lint dirigido | PASS, cero errores/advertencias en hook, Inbox y sus tests. Los dos efectos sustituidos eran los que originaban los errores previos; no se añadieron supresiones. `lint.json`. |
| Chromium / red | PASS, `browser.json` / `check_browser.py`: 21,01 s oculto con **cero** polls; al volver, ambos GET en menos de 47 ms; luego el poll de hilo vuelve a los 10 s. Sin errores de página. |
| Cleanup | Navegador cerrado, árbol propio de Vite terminado y puerto 4178 libre. |

La prueba de red usa frontend real, API sintética y `document.hidden`/evento de
visibilidad controlados por el harness, con reloj real. No simula respuestas
del hook ni usa temporizadores acelerados. No acredita una sesión operativa con
un usuario cambiando pestañas del navegador. `source-sha256.json` fija este corte.

No se repitieron suites generales ni casos visuales de CMP/GRP/CPY sin cambios.
No hubo cambios de backend, migraciones, commit, push, despliegue ni activación.
PERF-03 incremental sigue pendiente; los gates reales y el FAIL B9 r12 se conservan.
