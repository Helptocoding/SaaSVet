# WA-UNR-02 — contador, divisor y lectura automática (2026-10-21)

Implementado y verificado localmente: **125 pruebas frontend y 41 API PASS**,
build y lint PASS, Chromium escritorio/móvil PASS. El flujo llegada → contador →
apertura/divisor → POST confirmado → contador menor está cubierto.

## Contrato implementado

- Badge numérico por hilo y total del servidor junto a Activas. El total incluye
  los hilos fuera de la página cargada; no se calcula solo sumando filas visibles.
- El transcript proyecta marcador propio, contador y primer/último inbound
  pertinente incluido en la página actual. No revive sesiones cerradas como
  unread ni marca como destino un mensaje que no se envió a la UI.
- Debounce 1,5 s, solo con visibilidad visible y document.hasFocus(), comprobados
  de nuevo al vencer. Blur, ocultación, cambio de hilo/cuenta y desmontaje cancelan
  el timer y abortan la petición en vuelo. A→B→A ignora respuestas anteriores.
- Un solo POST en vuelo. Id confirmado no se repite; una llegada posterior se
  conserva. Error de POST: contador/divisor permanecen, sin toast; el siguiente
  poll reintenta. View basta, sin send/claim.
- El acuse invalida GETs iniciados antes y refresca las páginas de lista cargadas.
  El divisor desaparece tras confirmación. Su inserción/retirada participa en el
  efecto único de scroll de HIST-02, con ancla conservada.

La API añade unread_total a lista y POST read, y cuatro metadatos al transcript:
last_read_message_id, unread_count, first_unread_message_id,
latest_visible_inbound_id. Comparte el selector operacional y la semántica D-3
de UNR-01; el total usa cabeceras vigentes como subconsulta SQL. Se preservan
el presupuesto previo <=4 consultas, la paginación y el payload anterior salvo
los campos aditivos documentados.

## Validación

Vitest dirigido: **125 PASS, 41 omitidos por selección**. Son 27 casos nuevos
(17 hook, 8 página y 2 transporte API) y 98 regresiones afectadas de historial,
polling, carga, agrupación, navegación y envío. No se ejecutó la suite general.
Los omitidos no se acreditan como nuevos PASS.
Build conserva la advertencia advisory de tamaño del bundle; no bloqueó la compilación.

PostgreSQL: **41/41 PASS**, cuatro proyecciones nuevas y 37 regresiones afectadas
de UNR-01, rendimiento, paginación y shape/ventana de HIST-03. Incluye las dos
carreras reales de creación/avance. Base test_inbox_unr02_* eliminada.
Las aserciones actualizadas distinguen el conteo global y por página; la fixture
congelada PERF-01 permanece intacta y todos sus campos previos siguen comparados.

Chromium con API sintética separada por empleado y foco/visibilidad controlados:

| Comprobación | Escritorio 1366×768 | Móvil 390×844 |
|---|---|---|
| View-only puede marcar, sin composer | PASS | PASS |
| Blur y pestaña oculta no envían marcado | PASS | PASS |
| Fallo silencioso y siguiente poll reintenta | PASS | PASS |
| Lectura propia no limpia al segundo empleado | PASS | PASS |
| Retirar divisor conserva ancla | 0 px | 0 px |
| Total incluye páginas no cargadas / sin overflow | PASS | PASS |

Se inspeccionaron capturas de ambos tamaños. La API en esta prueba es sintética;
la semántica y aislamiento reales se verifican en los tests PostgreSQL. Esto no
es un acta operativa de recepción ni acredita acuses Meta reales.

## Incidencias de harness conservadas

Una preparación inline del runner quedó interrumpida y dos lanzamientos no
encontraron aún sus archivos. No ejecutaron Vitest/build; se escribieron runners
independientes y se esperó su terminación antes de lanzarlos.

Primer intento Chromium: callback con segundo parámetro default recibió Request
en lugar de actor; KeyError antes de probar el producto. Se conserva
browser-initial.log, browser-run-initial.json y check_browser-initial.py.
Segundo: token sintético con expiración en 2100 disparó el refresh inmediato;
la sesión dejó de mostrar Inbox. Se conserva browser-token-initial.json/log,
browser-run-token-initial.json y check_browser-token-initial.py. Se reutilizó la
expiración now+3600 del fixture histórico validado. No cambió autenticación.

Solo se repitió Chromium al corregir esos fixtures. Los 125 Vitest y 41 API ya
válidos se conservaron; no hubo fallos de producto en esas corridas. El servidor
temporal se cerró en todos los intentos y el puerto 4178 quedó libre.

## Recibos y límites

[Vitest](vitest.json), [API](backend.json), [build](build-run.json),
[lint](lint-run.json), [Chromium](browser.json), [limpieza de servidor](browser-run.json),
[checks finales](final-checks.json), [hashes de fuentes](source-sha256.json).

No hay nueva migración: M3 de UNR-01 sigue siendo requisito y no se aplicó a la
base de trabajo. No se desplegó ni activó el subsistema. Recepción, Meta real y
seguridad B9 r12 FAIL conservan sus requisitos. No se lanzó otra campaña B9.
