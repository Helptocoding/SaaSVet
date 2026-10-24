# WA-RETRY-01 — cierre local, 2026-10-21

Estado: **PASS local**. Se conserva la aceptación real pendiente del Inbox y el
FAIL de seguridad de B9 r12. No hay migración nueva, commit, push, despliegue,
activación ni envío a Meta. M3 de UNR-01 sigue sin aplicarse a la base de trabajo.

## Resultado implementado

- POST `conversations/{uuid}/messages/{id}/retry/`, permiso `agentinbox.send`.
  Servicio con locks Conversation → Message, organización del request y guards B4.
  Sólo admite outbound FAILED sin evidencia de aceptación o incertidumbre, de
  sesión abierta y con epoch/cuenta/TurnWork todavía autorizados.
- Reutiliza fila, cuerpo, autor, fecha, correlación y clave; reinicia estado,
  intentos y planificación. Otro empleado puede reintentar sin reasignar el claim.
  Evento estructurado con IDs, actor, autor original y resultado, sin cuerpo/key.
- El sender existente toma PENDING, vuelve a validar y crea otro token. El
  finalizador del intento anterior no modifica PENDING ni el claim posterior.
  Nunca convierte UNCERTAIN en FAILED/PENDING ni borra evidencia externa.
- La UI ofrece acción sólo para un FAILED del episodio vigente con send, impide
  doble clic, conserva borrador/autor y reconcilia sin duplicar. El UUID por mensaje
  evita apuntar un histórico al episodio actual. No altera el reintento failed-local.
  Acuses más avanzados prevalecen; respuestas antiguas no contaminan otro hilo.
- Fallo de ventana o 400 `window_closed` ofrece llamada mediante tel:. La banda
  preventiva general y countdown siguen pendientes de WA-WIN-01.

El criterio previo a B4 de «fallo por red» se limita a rechazo conocido. Timeout,
desconexión, 5xx o aceptación no demostrada siguen siendo UNCERTAIN y requieren el
procedimiento B4 separado, sin botón de reintento ordinario.

## Validación y recibos

| Comprobación | Resultado | Evidencia |
|---|---|---|
| API PostgreSQL temporal | 29 PASS: 18 nuevos, 4 autor/DTO, 2 transcript y 5 guards B4 | [runner](run_backend_tests.py), [recibo](backend.json), [log](backend.log) |
| Frontend, evidencia compuesta | 106 IDs únicos PASS: 27 nuevos y 79 afectados; no es una ejecución continua | [inicial](vitest-initial.json), [repetición dirigida](vitest.json), [verificación](final-checks.json) |
| Última ejecución dirigida | 31 PASS, 96 excluidos por nombre: 25 UI nuevos, 2 API nuevos y 4 regresiones | [runner](run_frontend_tests.py), [log](frontend.log), [recibo](frontend-run.json) |
| Build final | PASS; advertencias advisory de tamaño de chunk/plugins conservadas | [log](build.log), [recibo](build-run.json) |
| Lint final de JS afectado | PASS, sin mensajes | [salida](lint.json), [recibo](lint-run.json) |
| Chromium escritorio 1366×768 y móvil táctil 390×844 | PASS con API sintética | [mediciones/red](browser.json), [runner/cleanup](browser-run.json) |

La API acredita permisos, autor distinto, contenido/key inmutables, ventana
desconocida/cerrada, cambio de ventana antes del dispatch, estados no reenviables,
todos los tipos de evidencia externa, acuse tardío forward-only, epoch legacy/
invalidado, sesión cerrada, cuenta pausada, claves distintas/ausentes, payload no
editable, scope por hilo/cuenta/organización y una carrera real con dos conexiones:
un 200 y un 400, una sola fila PENDING. El sender envía exactamente una vez al
proveedor simulado; token anterior y finalizador tardío no alteran el envío nuevo.
Esto no acredita exactly-once externo ni entrega real WhatsApp.

Los casos UI cubren autor distinto, borrador, doble clic, errores y llamada,
estados/evidencias excluidos, permisos, históricos, navegación/desmontaje,
acuse READ durante POST y GET anterior al retry. Chromium comprueba request vacío
con key original, estado ocupado, misma burbuja, borrador, llamada sin toast,
ausencia de retry UNCERTAIN, teclado/táctil y ausencia de overflow horizontal.
La variación vertical de la burbuja al confirmar fue **0 px** en ambos tamaños.

Capturas inspeccionadas: [escritorio ocupado](retrying-desktop.png),
[móvil con llamada](window-mobile.png). El servidor temporal propio se cerró;
el recibo confirma puerto libre. La base temporal se destruyó y el runner confirmó
su ausencia. No se detuvieron procesos ajenos.

## Incidencias conservadas

1. Ejecución frontend inicial: 105 PASS, un timeout de 5 s en el caso existente
   `aplica el cap global de 20 intentos entre sesiones`, 57 excluidos por selección.
   [Log original](frontend-initial.log), [recibo](frontend-run-initial.json) y
   [runner original](run_frontend_tests_initial.py). Coincidió con PostgreSQL,
   build y lint ejecutándose; la carga como causa es una inferencia, no un hecho
   medido. Se evitó montar el componente de retry en mensajes ajenos a FAILED y
   se repitieron la nueva rama y las regresiones directamente afectadas. El cap
   pasó en 3956 ms sin cambiar timeout, assertions ni umbral de 20 intentos.
   Los otros PASS iniciales conservados no dependen de esa rama FAILED; 31 casos
   dirigidos verifican el código final. El verificador combina sólo ejecutados,
   no cuenta skips como fallos ni como PASS, y no suma repeticiones como IDs nuevos.
2. Primer ensayo Chromium: selector de texto exacto incompatible con el DOM del
   cuerpo, que es un nodo de texto junto al bloque de metadatos. La captura
   mostraba el texto; no hubo error de página. [Log](browser-initial.log),
   [recibo](browser-run-initial.json), [detalle](browser-initial.json) y
   [harness original](check_browser_initial.py). Se cambió a la burbuja identificada
   por data-message-id y conteo de burbujas que contienen ese cuerpo; se mantuvo
   el requisito de texto intacto y una sola burbuja. Repetición escritorio/móvil PASS.
3. La copia inicial del runner de navegador no se ejecutó porque el revisor
   automático de permisos agotó su cuota. Fue un fallo de disponibilidad del
   revisor, no una determinación de inseguridad. Tras la continuación del usuario,
   los comandos pasaron por el mismo mecanismo de aprobación; no se eludió.

No se ejecutaron suites generales ni otra campaña B9. Los contratos de agente y
frontend, CHANGELOG, plan original y guía de cierre registran este corte y
mantienen los gates operativos/Meta/media y seguridad pendientes.
