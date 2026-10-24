# WA-GTF-01 — Ir al final

Estado: **implementada y verificada localmente** (2026-10-21). El botón flotante
«↓ Ir al final» aparece cuando el transcript está a más de 200 px del fondo.
Vuelve al final del panel sin desplazar la página y deja el foco en el historial.
Funciona con teclado y puntero, también en hilos archivados. Cambiar de hilo
reinicia su estado. En móvil el transcript tiene altura acotada para permitir
scroll interno y mantener el botón accesible junto al área de lectura.

| Check | Resultado |
|---|---|
| Tests dirigidos | **25 PASS**: diez nuevos (ocho de contenedor, dos de integración) y quince afectados de agrupación, composer y carga/reconexión. 47 excluidos. `vitest.json`, `frontend.log`. |
| Build y lint | PASS, cero errores/advertencias lint. `build-run.json`, `build.log`, `lint.json`; advertencia de chunk grande preexistente, sin publicación a Sentry. |
| Chromium | PASS con 40 mensajes sintéticos. Escritorio 1366×768 y móvil 390×844: botón de 44 px, distancia final 0 px, último mensaje completamente visible, foco conservado, sin salto de página ni desbordamiento horizontal. Capturas `go-to-end-desktop.png` y `go-to-end-mobile.png` inspeccionadas; `browser.json`. |
| Correcciones verificadas | `browser-attempt1.json` y `check_browser-attempt1.py` conservan el fallo original del selector exacto: el cuerpo comparte nodo con hora/estado. Se corrigió y se añadió comprobación de visibilidad completa. La inspección detectó además superposición con Ayuda en móvil: el botón se centró y el smoke exige nueve puntos de interacción libres. Recibos y captura anteriores conservados con sufijo `before-mobile-fix`; se repitieron solo build y navegador por el cambio CSS. |
| Cleanup | Navegador y Vite propio cerrados; puerto 4178 libre. |

`source-sha256.json` identifica el corte. Se conserva el salto automático existente
al cambiar la cantidad de mensajes: anclaje, scrollback y aviso de mensajes nuevos
pertenecen a HIST-01/02/03. Sin cambios backend, suites generales, commit, push,
despliegue ni activación. Los gates operativos y el FAIL B9 r12 siguen pendientes.
