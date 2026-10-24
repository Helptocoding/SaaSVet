# WA-RPL-05 — Composer de respuesta citada

Entrega local del **21-10-2026**. **61 pruebas frontend únicas PASS**: 27 nuevas y
34 afectadas. Evidencia compuesta por ID; build, lint y Chromium escritorio/móvil
PASS. [Manifiesto](manifest.json), [runner](run_checks.py), [verificador](verify.py).

## Contrato entregado

Responder acompaña a Copiar en las burbujas, accesible por hover/foco o táctil.
Una cita activa con autor y extracto de 80 puntos Unicode aparece sobre el campo,
en una línea con elipsis. Elegir otra sustituye la anterior y enfoca el campo sin
scroll intencional ni borrar texto. Escape/× cancelan; Enter o Enviar incluyen
`reply_to_id`. Shift+Enter y composición IME no envían. Vacío no consume la cita.

Selección requiere send, sesión vigente y ventana abierta. IDs temporales no
permiten responder; al llegar el PK confirmado se habilitan aunque se conserve
client_message_id. Media sin texto utiliza su tipo como extracto de respaldo.

Cambio de persona/cuenta o episodio cancela; poll del mismo episodio y pulsar la
misma fila conservan. Cada intento captura su ID de cita junto a cuerpo/key;
retry usa los originales sin consumir una cita siguiente. Un POST tardío no
retira la cita ni el borrador del hilo nuevo. El optimista conserva `reply_to`
para la futura representación en burbuja.

`sendInboxMessage(sessionId, body, key, {signal, replyToId})` amplía las opciones
actuales, conservando la llamada previa con AbortSignal. La cita ausente se omite
del JSON. No se añade un cuarto argumento posicional que rompa la cancelación.
La autorización definitiva permanece en la API ya acreditada en RPL-03.

## Verificación dirigida

- `new-directed`: 29 PASS y un fallo de fixture. Incluye 24 casos UI nuevos y seis
  API (tres nuevos, tres previos afectados). El fixture avanzaba temporizadores
  pero no Date; el vencimiento no había ocurrido para el guard de envío.
- `boundary-corrected`: únicamente ese caso, tras incluir Date en el reloj falso,
  PASS. Sin modificar el producto ni rebajar la aserción; se conservan los 29 PASS
  iniciales. La unión contiene 30 IDs únicos, todos aprobados.
- `affected-directed`: 31 PASS de aislamiento del borrador/envío optimista,
  reintentos/idempotencia, copia/enlaces y altura/contador del composer. No suite
  general ni pruebas backend repetidas para un cambio solo frontend.
- `lint-directed`: PASS de los cuatro archivos JS/JSX modificados. El único cambio
  posterior fue el reloj de un fixture; `lint-fixture-final` acredita ese archivo
  final por separado. `build-final`: PASS, con aviso advisory de tamaño de chunk.
- Chromium real 1366×768 y táctil 390×844, API sintética: selección por Space o tap,
  autor/una sola cita, Escape/×, borrador conservado, POST con referencia y key,
  tmp deshabilitado y confirmado habilitado, cambio de hilo y sin overflow
  horizontal ni errores de página. Servidor temporal cerrado y puerto libre.

Capturas inspeccionadas: [escritorio](composer-desktop.png), [móvil](composer-mobile.png).
[Recibo Chromium](browser.json), [cleanup](browser-run.json). El navegador intercepta
las llamadas API y no sustituye un roundtrip con backend ni validación real Meta.

## Límites y siguiente paso

Sin cambio backend ni migración nueva; M2/M3 siguen sin aplicar a bases
habitual/preview. Sin commit, push, despliegue ni activación. Recepción/Meta reales
siguen pospuestos; la conexión del contexto de cita al payload nativo Meta sigue
siendo implementación pendiente como prerrequisito de RPL-07. B9 mantiene su FAIL
histórico de seguridad.

Siguiente: **WA-RPL-06**, jump al original cargado o mediante around. Después
RPL-04 para representar citas en burbujas y RPL-07 para completar la cadena.
