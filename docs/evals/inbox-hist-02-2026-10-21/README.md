# WA-HIST-02 — llegadas nuevas sin interrumpir la lectura

Estado: **implementada y verificada localmente** (2026-10-21).

`useThreadHistory` concentra el único efecto de scroll del transcript. Captura
posición, distancia al fondo y primera burbuja visible antes de actualizar
mensajes servidor u optimistas. Si estaba a 80 px o menos del fondo, sigue la
llegada; leyendo arriba conserva el ancla y muestra «N mensajes nuevos».
También coordina inserciones anteriores y poll en el mismo render. Se retiró
el efecto que forzaba el fondo desde `index.jsx`.

El contador usa identidades posteriores a la carga inicial: no suma páginas
históricas, estados de entrega ni mensajes repetidos por el poll. Un optimista
y su confirmación comparten `client_message_id` y cuentan una sola vez. La
pill usa scroll suave, conserva el foco en el historial y limpia el contador;
bajar manualmente al umbral del fondo también lo limpia. Cambiar de hilo
reinicia el seguimiento. Sin novedades conserva «Ir al final» de GTF-01.

| Comprobación | Resultado y recibo |
|---|---|
| Frontend dirigido | **96 casos únicos PASS**: 21 nuevos de HIST-02 y 75 regresiones afectadas de HIST-01, viewport, carga, visibilidad, metadatos, agrupación, envío y borrador. [frontend-composite.json](frontend-composite.json). |
| Ejecuciones | **95 PASS** iniciales, [vitest.json](vitest.json), más **un caso nuevo PASS** de julio→octubre con separadores de día, [vitest-aged.json](vitest-aged.json). Ningún fallo ni repetición de los 95 aprobados. Los casos fuera del filtro no representan una suite general ejecutada. |
| Límites y carreras | 0/80/81 px, ráfaga de cinco, polling repetido, recibos sin incrementar, optimista confirmado/retirado, cambio de hilo, vuelta de pestaña oculta, scrollback con contador pendiente y poll+anteriores agrupados. Incluidos en los 96 PASS. |
| Compilación | PASS, sin subir sourcemaps; advertencia de tamaño de bundle conservada. [build-run.json](build-run.json), [build.log](build.log). |
| Lint | PASS en los seis archivos JavaScript modificados. Tras añadir el caso de tres meses se repitió sólo lint de `index.test.jsx`. [lint-run.json](lint-run.json), [lint-aged-run.json](lint-aged-run.json). |
| Chromium local | Escritorio 1366×768 y móvil 390×844 PASS con API sintética. Historial de **2026-07-21**, llegadas de **2026-10-21**: ráfaga de cinco, ancla sin desplazamiento (**0 px**), contador sin duplicar, click/Enter con scroll suave y foco conservado, seguimiento al fondo y limpieza manual. [browser.json](browser.json), [escritorio](new-messages-desktop.png), [móvil](new-messages-mobile.png), [seguimiento móvil](following-bottom-mobile.png). |
| Control móvil | Altura mínima de 44 px y nueve puntos del área de interacción libres de superposición. Sin overflow horizontal ni errores JavaScript. |
| Regresión de anclaje | El dueño del scroll cambió, por lo que se verificó de nuevo el recorrido de 200 mensajes y cuatro respuestas anteriores por viewport. Sin duplicados, aviso de agotamiento, error/reintento y borrador intactos; variación del ancla inferior a 1 px. |
| Cleanup e integridad | Árbol Vite propio terminado y puerto 4178 libre. No se creó base de datos. API, backend, serializer y CSS se conservan respecto a HIST-01. [source-sha256.json](source-sha256.json), [final-checks.json](final-checks.json). |

El primer ensayo Chromium también aprobó llegadas dentro del mismo día:
[recibo conservado](browser-current-day.json) y
[harness](check_browser-current-day.py). Se añadió el escenario de tres meses
para acreditar literalmente el criterio del plan, sin modificar código de
producto ni umbrales después de los primeros checks aprobados. Los refrescos
se disparan mediante visibilidad controlada en el navegador; no se presentan
como una prueba de pestaña real en segundo plano. Se reutiliza el ejecutor
Windows que termina su árbol Vite, tras haber consultado el helper de la skill.

El contador es local a la lectura actual y a los mensajes incorporados por los
refrescos existentes; no constituye lectura persistente por empleado (UNR).
PERF-03 incremental y el endpoint `around` de HIST-03 siguen pendientes.
No se ejecutaron suites generales, API/backend innecesarios ni otra campaña B9.
Recepción/Meta real y el FAIL de seguridad r12 conservan su estado.
Sin commit, push, despliegue ni activación. Siguiente tarea: **WA-HIST-03**.
