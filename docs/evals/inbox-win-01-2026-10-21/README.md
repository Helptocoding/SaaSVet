# WA-WIN-01 — cierre local, 2026-10-21

**PASS local**. Ventana visible y composer bloqueado al vencer. Se conservan la
aceptación Meta/recepción/media pendiente y el FAIL de seguridad de B9 r12.
Sin migración nueva ni aplicar M3 a la base de trabajo. Sin commit, push,
despliegue, activación ni tráfico real a WhatsApp.

## Entrega

La sesión vigente del transcript añade `session_window_open` y
`session_window_expires_at`, campos read-only. Usa las 24 horas transcurridas
B4 desde `last_inbound_at`, sin sumar días de calendario ni introducir DST.
Ventana desconocida: false/null; episodio cerrado: false/null; hilo archivado:
conversation=null. La igualdad exacta de tiempo conserva la frontera inclusiva
del sender; después vence. Una página histórica conserva la ventana vigente.

El composer avisa con menos de 12 horas, cuenta minutos, actualiza al recuperar
visibilidad y dispone de timer para el vencimiento entre ticks. Si falta metadata
válida, bloquea con explicación. Al vencer deshabilita textarea/Enviar y conserva
el borrador; sugiere esperar un nuevo mensaje o llamar mediante tel: válido.
El handler de clic/Enter comprueba el reloj aunque un timer haya sido demorado.
Una ventana renovada por la ingesta existente vuelve a habilitarlo con el mismo
borrador. No muestra composer/banda para archivados o usuarios sin send.

Se reutiliza `usePollingWhenVisible` para el único reloj compartido del Inbox;
fecha, contador y aviso no necesitan nuevas consultas ni librerías. B4 mantiene
su validación final: un texto que expire mientras está en cola todavía puede ser
rechazado antes del HTTP. El aviso preventivo no acredita entrega Meta.

## Pruebas dirigidas

| Comprobación | Resultado | Recibos |
|---|---|---|
| API PostgreSQL desechable | **19 PASS**, nueve nuevos y diez afectados | [runner](run_backend_tests.py), [resultado](backend.json), [log](backend.log) |
| Frontend, evidencia compuesta | **84 casos únicos PASS**, 18 nuevos y 66 regresiones | [inicial](vitest.json), [cap corregido](vitest-cap-fixed.json), [verificación](final-checks.json) |
| Build final | PASS, advertencias advisory de chunk/plugins conservadas | [log](build.log), [recibo](build-run.json) |
| Lint final, JS afectado | PASS, sin mensajes | [salida](lint.json), [recibo](lint-run.json) |
| Chromium escritorio 1366×768 y móvil táctil 390×844 | PASS, API/reloj/visibilidad sintéticos controlados | [mediciones](browser.json), [cleanup](browser-run.json) |

Los casos API prueban ventanas reciente/expirando/cerrada/desconocida, frontera
exacta, cambio DST de Tijuana, atributos read-only, archivado, endpoint legacy,
ventana vigente al leer históricos, dos ingestas reales locales (renovación de un
episodio y nueva sesión tras archivo), GET sin mutaciones y tenant scoping.
Las regresiones afectan proyección de turno, archivado, shape/consultas del
transcript y guard de ventana del retry/sender. La base temporal se destruyó y el
runner confirmó su ausencia; no se migró la base de trabajo.

Los 18 casos UI nuevos prueban apertura, umbral de 12 h, 7 h 12→7 h 11 min,
vencimiento entre ticks, guard de Enter sin timer, false de servidor, metadata
ausente/inválida, payload ya vencido al llegar, renovación, regreso de pestaña
oculta, archivado, permisos, cambio de hilo, GET tardío y cleanup de timers.
Se repitieron sólo composer/envío optimista, scroll/historial, visibilidad y
retry afectados. Las fixtures de envío anteriores incorporan la nueva ventana
válida; los casos nuevos verifican expresamente el bloqueo de metadata ausente.

Chromium verificó en ambos tamaños: aviso 7 h 12, cuenta 7 h 11 al avanzar el
reloj, cierre por timeout sin esperar un minuto, textarea/Enviar deshabilitados,
borrador conservado, enlace de llamada, actualización al recuperar visibilidad,
reapertura y un único POST válido después de renovar. Cero envíos mientras estaba
cerrada, key de idempotencia no vacía y cero overflow horizontal o errores de página.
Son fixtures de API, no operación real de recepción ni de Meta.

Capturas inspeccionadas: [aviso escritorio](warning-desktop.png),
[cierre móvil](closed-mobile.png); también se conservan aviso móvil/cierre escritorio.
El runner sólo cerró su propio proceso temporal; puerto 4178 libre al terminar.

## Incidencias preservadas

La ejecución inicial frontend terminó con 83 PASS, un timeout y 52 casos excluidos
por selección. El caso existente `aplica el cap global de 20 intentos entre sesiones`
agotó sus cinco segundos también al aislarlo: [recibo inicial](frontend-run.json),
[log inicial](frontend.log), [repetición aislada](frontend-cap.log),
[JSON aislado](vitest-cap.json). No se presenta como PASS de aquella ejecución.

Se corrigió el coste del harness conservando la referencia al mismo botón Enviar
durante cada bucle. Evita 21 búsquedas globales repetidas del árbol accesible; no
agrupa eventos, omite esperas ni cambia las 21 peticiones, los conteos, la expulsión
del intento más antiguo, los dos hilos, las aserciones finales o el timeout de 5 s.
El caso pasó en 4822 ms: [runner](run_cap_fixed.py), [log](frontend-cap-fixed.log),
[recibo](frontend-cap-fixed-run.json). Los otros 83 PASS no requieren repetición:
el producto no cambió después de aquella ejecución. El verificador conserva los
dos fallos y combina por ID sólo los casos ejecutados, sin sumar repeticiones/skips.
La evidencia de 84 PASS es compuesta, no una ejecución continua.

Los primeros comandos de lectura encontraron errores de sandbox/RTK (acceso
denegado y directorio de configuración). Se repitieron mediante escalación
revisada; no fueron fallos de producto ni se eludió la aprobación. Un parche del
harness informó una línea ya cambiada: se inspeccionó el estado y se añadió sólo
el runner faltante. No se modificaron evidencias históricas.

Los contratos de agente/frontend, CHANGELOG, plan y guía registran este corte.
Siguiente tarea funcional: WA-CTX-01. No se repitieron suites generales ni B9.
