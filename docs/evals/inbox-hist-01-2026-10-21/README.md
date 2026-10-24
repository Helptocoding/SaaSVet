# WA-HIST-01 — historial disponible con scrollback

Estado: **implementada y verificada localmente** (2026-10-21).

`useThreadHistory` separa metadatos de sesión y mensajes acumulados. Consume el
cursor `next_before` del endpoint existente al subir a menos de 160 px del
inicio. Fusiona por ID, ordena por fecha/ID y conserva las páginas anteriores
durante el poll. La página histórica no sustituye metadatos de sesión vigentes
ni estados de mensajes más recientes. El envío conserva su reconciliación por
`client_message_id` y su idempotencia.

La inserción mide altura y posición al recibir la respuesta y compensa la
diferencia antes de pintar. El navegador usa ese anclaje explícito. Doble
disparo en vuelo se ignora; cambiar de hilo o desmontar aborta y descarta la
respuesta, incluido A→B→A. Error de cursor conserva mensajes/cursor/borrador y
ofrece reintento explícito. Página vacía o cursor repetido detienen la carga.

Desde 500 mensajes se detiene la carga automática y se continúa manualmente
con «Cargar anteriores», conservando los mensajes leídos. No hay expulsión ni
virtualización del buffer. Al agotarse muestra «Inicio del historial disponible»:
se refiere al historial conservado por el sistema, no al histórico previo de
WhatsApp. `getThreadMessages` añade `{signal}` como cuarto argumento opcional.
No cambia backend ni esquema.

| Comprobación | Resultado y recibo |
|---|---|
| Frontend dirigido | **77 casos únicos PASS**: 27 nuevos (15 hook, siete Inbox, dos transporte, tres umbrales) y 50 regresiones afectadas de transcript, agrupación, metadatos, viewport, carga, visibilidad, envío y borrador. [frontend-composite.json](frontend-composite.json). |
| Casos de historial | 10/51/500 mensajes, páginas de 50, solapamientos, empates por ID numérico, mismo texto en mensajes distintos, cursor 400, reintento, respuesta vacía/repetida, cancelación y carreras poll/scrollback. Incluidos en los 77, sin suite general. |
| Compilación | PASS; sin subida de sourcemaps. Advertencias de tamaño de bundle/plugin conservadas. [build-run.json](build-run.json), [build.log](build.log). |
| Lint | PASS en los nueve archivos JS nuevos/afectados; tras arreglar fixtures se repitió sólo lint de los tres tests modificados. [lint-run.json](lint-run.json), [lint-final-run.json](lint-final-run.json). |
| Chromium local | Escritorio 1366×768 y móvil 390×844 PASS con API sintética: 200 mensajes completos y ordenados, sin duplicados, aviso de agotamiento, error/reintento con borrador intacto y sin overflow horizontal. [browser.json](browser.json), [escritorio](history-desktop.png), [móvil](history-mobile.png), [error móvil](history-error-mobile.png). |
| Anclaje real | Cuatro respuestas por viewport: tres inserciones y una página vacía. Diferencia de scrollTop igual al aumento de scrollHeight; variación visual máxima del mensaje anclado **0.625 px**, dentro del umbral de 2 px. Sin errores JavaScript. |
| Cleanup e integridad | Árbol Vite propio terminado y puerto 4178 libre. No se creó base de datos. Backend y serializer sin cambios respecto a PERF-02. [source-sha256.json](source-sha256.json), [final-checks.json](final-checks.json). |

Se conserva la ejecución inicial con **64 PASS y diez fallos** en
[vitest.json](vitest.json) y [frontend.log](frontend.log). Los fallos del harness:

- Dos casos AGT usaban un selector `role=status` ambiguo desde que PERF-02
  añadió el contador. Se acotó al texto exacto, conservando la aserción de rol y
  todas las de permisos, bloqueo y habilitación.
- En el test aislado, `beforeEach` devolvía el propio mock, que Vitest trataba
  como cleanup; la parametrización expandía arrays y la altura simulada leía
  un resultado anterior al layout effect. Se corrigieron las fixtures y la
  medición simulada, sin cambiar el código de producto ni los umbrales.

Se repitieron esos 15 casos del hook completos, dos AGT y tres nuevos límites
del viewport: **20 PASS**, [vitest-repaired.json](vitest-repaired.json). La
evidencia compuesta excluye todos los resultados iniciales del hook y combina
57 PASS iniciales aplicables con esos 20. Ningún fallo inicial se convirtió
retrospectivamente en PASS.

El primer ensayo visual falló por el selector de texto completo del ancla,
antes de medir posición. [Recibo](browser-attempt1.json) y
[harness](check_browser-attempt1.py) conservados, con cleanup PASS. Se localizó
la burbuja por el ID visible y se mantuvieron las mismas aserciones geométricas.
La preparación inicial de runners quedó interrumpida; dos intentos no arrancaron
por archivo aún ausente y no ejecutaron pruebas. Luego se escribieron y usaron
los runners guardados en este directorio.

**Límite pendiente HIST-02:** los mensajes nuevos del poll ya se fusionan, pero
su llegada aún fuerza el fondo y no ofrece contador/pill. Este cierre acredita
anclaje de inserciones anteriores, no el de llegadas nuevas. HIST-03 `around`
también sigue pendiente. Siguiente tarea: **WA-HIST-02**.

No se ejecutaron suites generales ni B9. Recepción/Meta real y el FAIL de
seguridad r12 conservan su estado. Sin commit, push, despliegue ni activación.
