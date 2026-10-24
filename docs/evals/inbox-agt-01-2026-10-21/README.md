# WA-AGT-01 — indicador de turno del asistente

Estado: **implementada y verificada localmente** (2026-10-21). La lista y la
conversación del transcript publican `agent_processing`, calculado sobre la
proyección existente `processing_until > timezone.now()`. Nunca se publica el
timestamp. Sesiones cerradas, lease ausente, vencido o exactamente al límite
devuelven false; el historial no presta su turno a una sesión nueva.

La cabecera muestra «El asistente está respondiendo…» y deshabilita Tomar/Acusar
recibo y Liberar con explicación. El siguiente poll exitoso retira el indicador
y habilita las acciones según permisos. TurnWork conserva la autoridad; no se
cambian guards, worker, estados ni migraciones.

| Check | Resultado |
|---|---|
| API PostgreSQL local | **6 PASS**: tres pruebas nuevas (incluyen cuatro límites temporales) y tres regresiones de archivo, aislamiento entre organizaciones y agrupación. `backend.json`, `backend.log`, `run_backend_tests.py`. |
| Frontend dirigido | **9 PASS**: cinco nuevas y cuatro regresiones de acuse, selección y respuestas tardías. 53 excluidas. `vitest.json`, `frontend.log`. |
| Build y lint | PASS, cero errores/advertencias lint en archivos cambiados. `build-run.json`, `build.log`, `lint.json`; sin publicación a Sentry. Advertencia de chunk grande preexistente. |
| Chromium | PASS con API sintética: indicador, explicación y Tomar deshabilitado en escritorio 1366×768; Liberar deshabilitado en móvil 390×844; ambos habilitados tras poll con false. Sin errores de página ni desbordamiento horizontal. `browser.json`; capturas `processing-desktop.png` y `processing-mobile.png` inspeccionadas. |
| Cleanup | Base PostgreSQL temporal con nombre único eliminada, comprobado en catálogo; Vite propio y navegador cerrados, puerto 4178 libre. |

`source-sha256.json` identifica el corte. El indicador refleja la última lectura
(cadencia de 10 s), no un evento en tiempo real ni un acuse de Meta. No acredita
aceptación operativa real ni cambia el FAIL de B9 r12. Sin suites generales,
commit, push, despliegue o activación.
