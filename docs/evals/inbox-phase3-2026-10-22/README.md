# Fase 3 obligatoria: RPL-07 y MED-01..05 — cierre local 22-10-2026

**Implementada y verificada localmente.** RPL-01..06 se conservan; esta ejecución
conecta la cita nativa Meta y completa el pipeline de media entrante. No despliega
ni activa procesamiento. MED-06 (envío de archivos) es opcional y queda pendiente.

## Resultado comprobable

| Comprobación | Resultado compuesto |
|---|---|
| Backend PostgreSQL | **170 casos únicos PASS**: 56 nuevos y 114 afectados |
| Frontend Vitest | **257 casos únicos PASS**: 24 nuevos y 233 afectados |
| Vite build / ESLint dirigido | PASS (`build-final`, `lint-final`) |
| M4 / drift / Django check | M4 aplicada en bases temporales; sin drift; 0 issues |
| Chromium 1366×768 y 390×844 táctil | PASS; Bearer en cada archivo; sin pageerror/overflow horizontal |
| Dependencias SDK | Closure boto3 instalada y pins comprobados sin refrescar ajenos |
| Limpieza | Bases temporales destruidas, servidor propio apagado y cero binarios runtime |

`summary.json` y `cases.json` componen por identidad de caso, conservando PASS
anteriores y reemplazando únicamente resultados afectados/corregidos. No se
presenta la suma de reejecuciones como pruebas distintas ni una suite integral
completamente verde. Los recibos y fallos originales permanecen sin sobrescribir.
`manifest.json` sella fuentes actuales y evidencia SHA256.

## Implementación

- **RPL-07:** `context.message_id` solo para el original de la misma clínica,
  cuenta y contacto con wamid utilizable, después de admisión B4. Para salientes,
  exige estado sent/delivered/read. Sin evidencia se mantiene la cita interna y
  se omite contexto nativo. No cambia ventana, idempotencia, takeover,
  clasificación de rechazo ni incertidumbre/replay.
- **MED-01:** MessageMedia con scope validado, dedup cuenta/provider ID, claims,
  evidencias ready/expired, UUID y migración aditiva
  `channels/0017_message_media.py` (M4). Storage local privado para dev/CI y
  adaptador B2 SigV4/AES256, claves opacas y sin URL pública/presigned.
- **MED-02:** captura atómica sin HTTP, tipos image/audio/video/document/sticker,
  caption preservada y payload raw completo en DB. IDs inválidos no pierden el
  Message; dedup y carrera de provider ID no reasignan la referencia original.
  La proyección B1 sigue sin duplicar body ni inventar comprensión binaria.
- **MED-03:** descarga por worker existente, URL Meta fresca por intento,
  allowlist HTTPS sin redirects, límites de bytes/tiempo, MIME/tamaño/SHA256,
  spool privado con finally/scavenger. Hasta cinco intentos, backoff y fencing.
  Purga/reconciliación nocturna idempotente y concurrente, retención de 180 días,
  borrado de versiones y markers B2 exactos. Una ausencia prematura es ERROR,
  no expiración inventada. Fallos de purga conservan el key para reintentar.
- **MED-04:** proxy GET auth + `agentinbox.view`, scope por clínica y validación
  de relaciones. Streaming privado, MIME almacenado y nombre saneado; estados
  403/404/409/410/503. Sin provider IDs/keys/hash/tokens en DTO.
- **MED-05:** joins sin N+1, cambios/expiry detectados en delta sin tocar Message,
  previews por tipo/nombre; thumbnail lazy, lightbox con Escape/foco, controles
  nativos y descarga documental bajo clic. Carga pesada explícita, peso previo,
  sin autoplay. Caché blob por usuario/clínica/UUID con refcount, abort/revoke;
  caption una vez y estados fallido/expirado sin bucle automático.

## Matriz RPL-07

| Caso mínimo | Cobertura conservada/revalidada |
|---|---|
| Cita a mensaje cargado | ReplyQuote / index.jump / native context |
| Cita antigua fuera de 50 | around / merge / useThreadHistory.jump |
| Cita a media | tipo/placeholder/caption y wamid nativo válido |
| Original discarded | «Mensaje no enviado»; sin contexto nativo outbound |
| Original failed | estado no enviado y retry original preservado |
| Wamid inexistente | FK null sin bloque ni pérdida del entrante |
| Cross-hilo/clínica | API scoped; rechazo antes de HTTP |
| Doble envío, misma key | una intención/relación aun con citas distintas |
| Webhook duplicado | un mensaje y una relación; carreras reales PostgreSQL |

Pruebas nuevas: `test_media_pipeline.py`, `test_media_integration.py`,
`test_inbox_media.py`, `MediaBubble.test.jsx`, seis casos de integración en
`index.replies.test.jsx` y un caso del cliente API. Afectadas: replies/webhook,
transporte, cuatro guards B4, modo worker, sync/PERF-01, B1 y lectura/saltos UI.
La fixture histórica PERF-01 no se reescribió: se comprueban y retiran únicamente
los campos DTO aditivos antes de comparar el resto del payload congelado.

## Evidencia de navegador

Resultado final: [browser-retained/browser.json](browser-retained/browser.json).
Se inspeccionaron las capturas de estados de escritorio y móvil. Comprueba
imagen/caption/cita, lightbox Escape y foco, audio manual, documento descargable,
video sin descarga automática, estados pendientes/fallidos, 410 solicitado una
vez y retry explícito de un 503. Solo recursos sintéticos: no prueba códecs
reales de Meta, red B2 ni aceptación operativa por recepción.

[Captura de estados en escritorio](browser-retained/media-states-desktop.png).

Capturas adicionales: [móvil](browser-retained/media-states-mobile.png),
[lightbox escritorio](browser-retained/media-lightbox-desktop.png) y
[lightbox móvil](browser-retained/media-lightbox-mobile.png).

## Incidencias resueltas y repetición acotada

1. Lint inicial: Date.now durante render; cálculo movido al estado/timer.
2. Vitest inicial: jsdom carece de showModal/close; mock de las APIs nativas.
   Chromium detectó después dos problemas reales: foco antes de cerrar dialog
   y liberación de imagen durante el modal. Se corrigieron y el smoke final pasa.
3. Backend inicial: FileField normalizaba separadores a Windows y la key privada
   los rechazaba. Se corrigió generate_filename a POSIX con validación estricta.
   La prueba de unicidad se ajustó para probar el constraint DB, además de clean.
4. Fixtures del sender: corrupción de cita es rechazada por validación existente
   antes de claim; se prueba sin cambiar B4. Un código Meta no clasificado seguía
   uncertain correctamente; el caso de rechazo conocido usa el código 100.
5. Fixture streaming: cierre manual doble de FileResponse disparaba request_finished
   y cerraba la conexión de APITestCase. Se consume mediante el wrapper del cliente
   de pruebas; los 13 casos del proxy pasan en `backend-proxy-final`.
6. Tres casos históricos UI agotaron tiempos bajo carga. Dos pasan al aislarlos;
   el caso de 21 envíos pasa con timeout del runner de 15 s, todas sus aserciones
   intactas. No se aumentó el timeout global ni se editó ese test.
7. B1 anterior esperaba raw recortado: MED-02 exige raw completo. Se añadió la
   comprobación explícita del raw y se mantuvo ausencia de body en la proyección
   B1, captions únicas en prompts y límites de comprensión. El pase inicial ya
   había importado la prueba previa al editarla; sus trazas pueden mostrar líneas
   del archivo actualizado. Solo se repitieron los dos métodos afectados.

## Reproducción y límites

Desde la raíz, usar `rtk proxy python -X utf8` con `run_checks.py` y una etiqueta
nueva: backend seguido de labels Django, frontend seguido de paths Vitest, o
build/lint/drift. Nunca reutilizar tags: el runner rechaza sobrescribir recibos.
Backend exige PostgreSQL local, usa DB `test_inbox_phase3_<uuid>` y comprueba su
destrucción. HTTP Meta/B2 está mockeado. `run_browser.py <tag-nuevo>` crea Vite
temporal oculto en 4178, lo cierra y registra limpieza; no reutiliza servicios.

`verify_evidence.py --verify` vuelve a comprobar el manifiesto. El seal se crea
una sola vez tras conciliar todos los resultados. SDK closure insertada en el
lock con versiones instaladas comprobadas; no se afirma haber regenerado todos
los pins mediante pip-compile.

**Pendientes reales:** aplicar M2/M3/M4 mediante release autorizado; bucket/key
dedicados y lifecycle físico B2; DPA, transferencia internacional, aviso/ARCO y
versión privacy; validación recepción/Meta. `INBOX_MEDIA_ENABLED` y aprobación B2
siguen false por defecto. Nada acredita activación, merge o despliegue.
El FAIL B9/security previo continúa vigente; no se ejecutó una nueva campaña B9.
MED-06 opcional y fase 5 no forman parte de esta entrega.

Contratos externos consultados: [respuestas Meta](https://www.postman.com/meta/whatsapp-business-platform/request/lwfz6gb/send-reply-to-document-message-by-id),
[URL de media](https://www.postman.com/meta/whatsapp-business-platform/request/ptjyi84/retrieve-media-url),
[versiones B2](https://www.backblaze.com/docs/cloud-storage-s3-compatible-api-bucket-versions)
y [lifecycle B2](https://www.backblaze.com/docs/en/cloud-storage-lifecycle-rules).
Contrato interno y operación: [runbook media](../../runbooks/inbox-media.md).
