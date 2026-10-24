# WA-CPY-01 — copia y enlaces

Estado: **implementada y verificada localmente**. Se puede copiar el cuerpo
original de cada mensaje, copiar el teléfono y abrir su enlace `tel:`. La acción
de mensaje aparece al pasar el ratón o enfocar con teclado y permanece visible
en dispositivos táctiles. La copia funciona también con permiso de sólo lectura;
en hilos archivados el teléfono proviene de la fila seleccionada.

Los enlaces HTTP/HTTPS se construyen con nodos React a partir de texto plano,
validando el protocolo y el host; abren con `noopener noreferrer`. HTML del
mensaje permanece literal. Sin Clipboard API o con permiso denegado se informa
el fallo, sin anunciar éxito ni modificar el mensaje.

| Verificación | Resultado |
|---|---|
| Frontend | **18 casos únicos PASS**: seis de tokenización/teléfono, seis de copia/render y seis regresiones de agrupación/estados/optimista. `test-results-composed.json` identifica cada caso y recibo. |
| Primera ejecución | `vitest-attempt1.json`, `frontend-attempt1.log`: ocho PASS y diez FAIL. Se detectó una colisión de resolución entre `MessageText.jsx` y `messageText.js` en Windows. Se renombró el componente a `MessageBody.jsx`. Fallo de implementación, corregido. |
| Repetición limitada | `vitest.json`, `frontend.log`: los diez afectados PASS; 28 excluidos por filtro. Los ocho PASS previos se conservan. La limpieza posterior de un escape redundante en un literal de prueba no cambia su valor ni las aserciones. No se presenta como una suite continua. |
| Build | PASS; `build-run.json`, `build.log`. Sin subida a Sentry; advertencia de tamaño de chunk existente. |
| Lint | Dos errores previos de polling, advisory; ningún error nuevo. `lint.json`. El recibo inicial conserva un escape redundante del test, corregido. |
| Chromium | PASS: 1366×768 ratón/teclado y 390×844 táctil. Copia real del texto completo y teléfono; enlaces y HTML literal comprobados, cinco grupos preservados, sin desbordamiento horizontal ni errores de página. `browser.json`; capturas `copy-links-desktop.png` y `copy-links-mobile.png` inspeccionadas. |
| Cleanup | Vite temporal propio cerrado y puerto 4178 libre. |

El verificador inicial comparaba LF con el CRLF que devuelve el portapapeles
nativo de Windows. `browser-attempt1.json` y `browser-attempt2.json` conservan
el fallo y la observación exacta. La comprobación final exige igualdad exacta
con los finales de línea del sistema; el test de `writeText` exige el cuerpo
original sin transformación. No se recortan espacios, palabras ni metadatos
para hacer pasar la prueba.

`source-sha256.json` identifica el corte verificado. Las únicas regresiones
repetidas son las afectadas por la nueva representación de cuerpo/metadatos.
No hubo suite completa ni pruebas backend repetidas. Datos API sintéticos,
sin envío a Meta, migración, commit, push, despliegue ni activación. Los gates
reales y el FAIL de seguridad B9 r12 siguen pendientes.
