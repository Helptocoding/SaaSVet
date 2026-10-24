# WA-RPL-06 + WA-RPL-04 — Citas y salto al original

Entrega local del **22-10-2026**. **128 pruebas frontend únicas PASS**: 45 nuevas
y 83 afectadas. Build, lint, diff check y Chromium escritorio/móvil PASS.
[Manifiesto](manifest.json), [runner](run_checks.py), [verificador](verify.py).

Conjunto mínimo inseparable: RPL-06 necesita la cita pulsable de RPL-04 para que
la navegación sea accesible desde el transcript. No se incorpora RPL-07 ni media
nueva; el icono/tipo representa la información ya disponible en la cita.

## Comportamiento entregado

`ReplyQuote` pinta una cita de un nivel en ambas direcciones: autor según las
etiquetas existentes, extracto, icono/tipo de media y «Mensaje no enviado» para
discarded/failed. Target null/ID inválido no genera bloque. HTML se trata como
texto; un extracto vacío usa «Contenido no disponible» sin inventar archivo.
Botón con foco/teclado/táctil, también para lector sin send o hilo archivado.

El salto usa PK independiente de client_message_id. Si está cargado no pide
HTTP; si falta hace un GET around con la misma pareja contacto/cuenta. Fusiona
por ID sin duplicar ni retroceder estados ya recibidos. No adopta metadatos de
sesión de around ni pierde borrador/cita activa del composer. El efecto de
layout centra/enfoca el original y lo resalta dos segundos; respeta movimiento
reducido y no cuenta la ventana histórica como llegada nueva.

La cadena before se conserva cuando around deja un intervalo sin cargar. El
floor firmado solo se amplía hacia atrás: un before intermedio no lo adelanta.
El siguiente delta reconcilia el intervalo ampliado con el contrato existente de
PERF-03; no se crean cursores para rangos disjuntos ni cambia la API. La ventana
around de hasta 50 filas conserva el contrato backend acreditado en HIST-03.

El salto aborta el GET corriente anterior; mientras busca no inicia otro poll
del transcript. Salto posterior, cambio de hilo o unmount invalidan/abortan
respuestas tardías. Un error/404 conserva datos y permite pulsar de nuevo para
reintentar. Ir al final cancela la intención de salto. Durante el resaltado no
dispara scrollback automático ni consume avisos reales; un destino oculto
revelado explícitamente se conserva frente a range_ids operacional, pero una
retirada explícita sigue ganando.

## Evidencia finita

- `new-directed`: **44 PASS**, bloques, IDs cargados/ausentes, descartados/fallidos,
  merge, metadatos, cursor/floor, foco, dos segundos, movimiento reducido,
  permisos/archivo, cancelación/carreras y errores. Sin fallos.
- `affected-directed`: **83 PASS** de HIST-01/02, GTF-01, composer RPL-05 y
  sincronización PERF-03. Son los caminos compartidos modificados por el hook y
  la representación de burbujas; no se ejecutó suite general ni campaña B9.
- `retry-hidden-highlight`: **un caso nuevo PASS**, añadido para acreditar que
  un range_ids operacional no retira el destino oculto mientras dura el
  resaltado, y que removals explícito sí gana. El nombre del recibo usa el modo
  dirigido del runner; no es una repetición de un fallo. Los 127 PASS anteriores
  se conservan: el único cambio posterior acota esa excepción a is_hidden y al
  ID resaltado, combinaciones nuevas probadas en este caso.
- `lint-directed` y `lint-final`: PASS. El último verifica el guard y el caso
  suplementario finales. `build-final`: PASS, con aviso advisory de chunk grande.
- Chromium real **1366×768 y táctil 390×844** con API sintética: original confirmado
  con client key encontrado por PK sin GET; alrededor de 10 y 30 mediante around;
  foco, destino dentro del viewport, cita media descartada, continuidad before=151,
  deduplicación, texto conservado y cambio de hilo. Sin overflow horizontal ni
  errores de página. [Recibo](browser.json), [cleanup](browser-run.json).

Capturas inspeccionadas: [citas escritorio](quotes-desktop.png),
[citas móvil](quotes-mobile.png), [salto escritorio](jump-desktop.png),
[salto móvil](jump-mobile.png). Servidor temporal cerrado y puerto libre.

## Alcance conservado

Sin cambio backend ni migración nueva. Se conservan las fuentes de vista,
serializer y sincronización acreditadas en RPL-03, y el adaptador HTTP de RPL-05;
el verificador contrasta sus hashes con esos manifiestos. M2/M3 no se aplicaron
a bases habitual/preview. Sin commit, push, despliegue, activación ni HTTP a Meta.
El navegador usa API sintética y no acredita un roundtrip real ni recepción/Meta.

Siguiente **WA-RPL-07**: conectar el contexto de cita nativo al proveedor y
completar su matriz de edge cases. Esa conexión sigue siendo implementación
pendiente; la validación real Meta/recepción continúa pospuesta. El FAIL histórico
de seguridad B9 y los pendientes de media no se presentan como resueltos.
