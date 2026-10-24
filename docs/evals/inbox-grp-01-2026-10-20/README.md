# WA-GRP-01 — agrupación visual

Estado: **implementada y verificada localmente**. Criterio: auditoría original
§16.6 y roadmap UX-01 → SEP-01 → GRP-01. Consecutivos del mismo autor, intervalo
estrictamente menor a cinco minutos y sin cruzar el día de la clínica.

- Separación compacta de 2 px y esquinas continuadas en cada ráfaga. Cada mensaje
  conserva cuerpo, hora, ticks y reintento individual; no se deduplican registros.
- Humanos identificados por UUID público de sólo lectura, no por nombre. Agente
  y sistema se distinguen. Humanos legacy/optimistas sin UUID quedan separados
  hasta que el servidor confirme su identidad. No hay migración.

| Verificación | Resultado / evidencia |
|---|---|
| Backend nuevo, sin DB | 4/4 PASS; `backend.log`, `backend.json`. Homónimos, identidad estable, null para otros autores y campo de sólo lectura. No se preparó ninguna base de datos. |
| Frontend dirigido | 19 PASS y 21 excluidos por filtro: 8 casos nuevos del agrupador, 2 de integración y 9 regresiones afectadas. `vitest.json`, `frontend.log`, `run_frontend_tests.py`. No se repitió la suite completa. |
| Build | PASS; `build.json`, `build.log`. Carga a Sentry deshabilitada. Advertencia de tamaño de chunk preexistente. |
| Lint | Advisory: dos errores previos `react-hooks/set-state-in-effect` en efectos de polling. Los helpers/tests nuevos no agregan errores. `lint.json`. |
| Chromium | PASS con API sintética, escritorio 1366×768 y móvil 390×844. Siete mensajes y cinco grupos conservados; gap 2 px, sin desbordamiento horizontal ni errores de página. `browser.json`, `check_browser.py`, `grouping-desktop.png`, `grouping-mobile.png`. Capturas inspeccionadas. |
| Cleanup | Servidor Vite temporal propio terminado; puerto 4178 libre al finalizar. |

Se repiten sólo regresiones de render, fecha y overlay optimista porque cambió
el contenedor de cada mensaje. Se conservan las pruebas CMP-01 previas. Los hashes
en `source-sha256.json` identifican este corte, previo a tareas posteriores.

Incidencias de harness conservadas: `frontend-attempt1.json` registra que
`pnpm exec` quedó detenido por el escape de argumentos en Windows antes de iniciar
Vitest; se verificó y cerró su árbol propio y se ejecutó el mismo filtro usando
Node directamente. `browser-attempt1.json` registra un selector exacto que incluía
metadatos de la burbuja; se corrigió la búsqueda del cuerpo manteniendo la exigencia
de una aparición por mensaje. No se rebajaron aserciones del producto.

No hubo backend/Meta real, envío externo, migración, commit, push, despliegue ni
activación. No acredita DoD de recepción ni gates Meta/media. Se conserva el FAIL
de seguridad B9 r12 y no se abrió otra campaña integral.
