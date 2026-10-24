# WA-LDE-01 — carga, error y reconexión

Estado: **implementada y verificada localmente** (2026-10-21). Lista y transcript
tienen skeleton de carga inicial, error persistente con reintento y banner
«Sin conexión — reintentando…» tras dos fallos consecutivos. Cada panel conserva
sus datos y el borrador durante la caída; el éxito reinicia el contador y retira
el banner. El reintento manual se deshabilita mientras se resuelve. Las respuestas
tardías de otro filtro o conversación no contaminan el panel vigente.

| Check | Resultado |
|---|---|
| Tests dirigidos | **18 PASS**: nueve nuevos y nueve regresiones afectadas de visibilidad, título, selección y reconciliación. 39 excluidos. `vitest.json`, `frontend.log`. |
| Build y lint | PASS, cero errores/advertencias lint. `build-run.json`, `build.log`, `lint.json`; sin publicación a Sentry, advertencia de chunk grande preexistente. |
| Chromium | PASS con API sintética y requests abortados: dos banners tras fallos consecutivos, siete mensajes y borrador conservados, recuperación automática en 19,18 s tras restablecer respuestas. `browser.json`, `check_browser.py`. |
| Inspección visual | Escritorio 1366×768 y móvil 390×844 sin desbordamiento horizontal; capturas `reconnection-desktop.png` y `reconnection-mobile.png` inspeccionadas. Sin errores de página. |
| Cleanup | Vite temporal propio y navegador cerrados; puerto 4178 libre. |

`source-sha256.json` identifica el corte. La caída se simula abortando peticiones
en Chromium; no se detuvo un backend real. El comportamiento local queda probado;
el ensayo operativo de backend/recepción real del plan sigue pendiente.
Sin cambios de API ni repetición de suites generales. FAIL B9 r12 conservado.
No hubo commit, push, despliegue ni activación.
