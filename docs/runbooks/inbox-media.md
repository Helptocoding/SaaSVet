# Inbox: media entrante privada (fase 3)

Implementación local de RPL-07 y MED-01..05; evidencia en
[fase 3](../evals/inbox-phase3-2026-10-22/README.md). **No implica activación ni
validación real Meta/B2/recepción.** MED-06 saliente es opcional y queda pendiente.

## Contrato y configuración

El webhook guarda caption, payload crudo y `MessageMedia.pending` dentro de la
misma transacción del mensaje. No descarga archivos. Los cinco tipos soportados
son imagen, audio, video, documento y sticker. Un ID malformado no descarta el
mensaje/caption; un ID repetido por cuenta reutiliza la referencia original sin
reasignarla a otro mensaje. Otra cuenta puede usar el mismo ID.

`INBOX_MEDIA_ENABLED=False` desactiva el procesamiento y mantenimiento por
defecto. La captura de referencias no depende de esta bandera. Para desarrollo
local: `MEDIA_BACKEND=local`, `INBOX_MEDIA_ALLOW_LOCAL=True`, raíz privada fuera
de static y rutas públicas (`INBOX_MEDIA_ROOT`). Los archivos no se incluyen en
Git. El spool temporal usa un directorio dedicado cuyo último componente debe
ser `saaslyvet-inbox-media-spool`; nunca apuntar a `/tmp` completo.

Producción requiere `MEDIA_BACKEND=b2`, `INBOX_MEDIA_PRODUCTION_APPROVED=True` y
las seis variables `MEDIA_B2_ENDPOINT_URL`, `MEDIA_B2_REGION_NAME`,
`MEDIA_B2_BUCKET`, `MEDIA_B2_ACCESS_KEY_ID`, `MEDIA_B2_SECRET_ACCESS_KEY` y la
bandera de procesamiento. Endpoint HTTPS regional oficial de Backblaze;
Application Key dedicada y restringida al bucket/prefijo `inbox-media/`, con
lectura/escritura/listado de versiones y borrado. No reutilizar la key de backups.
No se genera URL pública ni presigned. SDK boto3 con SigV4 y cifrado AES256
gestionado por B2. No es zero-knowledge; p40/age sigue intacto.

Límites implementados (MiB): imagen 5, sticker 0.49 (500 KiB), audio/video 16,
documento 25. Son límites conservadores de aplicación, inferiores o iguales al
techo general del plan. MIME por tipo en `media_policy.py`; HTML/SVG/ejecutables
no se aceptan. Tamaño real y anunciado, MIME y SHA256 se comprueban antes de
publicar `ready`. Hash esperado de Meta se compara cuando existe; siempre se
calcula el hash real. Archivos sin tamaño/dimensiones válidos no inventan datos.

## Worker y operación

El worker existente acepta `--mode media` o incluye media con `--mode both`.
Planner/sender conservan sus modos. Cada vuelta procesa un archivo, con claims
PostgreSQL, token y lease de 180 s, HTTP fuera de transacciones y fencing de
resultados tardíos. Cada intento pide una URL nueva a Meta. No sigue redirects;
solo descarga de HTTPS oficial `lookaside.fbsbx.com` o subdominios `fbcdn.net`.
Spool de 64 KiB por bloque, límite de bytes y plazo de descarga de 60 s; se borra
en `finally`. Los timeouts de red son acotados. B2 no aplica reintentos ocultos
del SDK: los controla la fila durable.

Hasta cinco intentos: red, 429/5xx y URL binaria vencida usan backoff exponencial;
404/410 al consultar metadata, MIME/hash inválido o tamaño excesivo terminan en
`failed`. El mensaje permanece visible. Una referencia a mensaje descartado se
descarga igual. No interpretar el binario con el agente ni cambiar safety B5.

`maintain_inbox_media --batch 100 --max-batches 10` usa el mecanismo de jobs ya
existente (Procfile y plantilla cron, 06:45 Monterrey). No se ha instalado cron.
Con la bandera apagada es inerte. Ajustar el número de lotes si el volumen supera
1,000 filas por ejecución, y revisar backlog; no crear otro scheduler.

El proxy deja de servir al cumplir **180 días naturales desde `persisted_at`**,
usando el reloj UTC de PostgreSQL (`clock_timestamp()`), igual que el worker y
los umbrales. Las lecturas y restauraciones no renuevan el vencimiento persistido.
El mantenimiento marca `expired`, elimina versiones y delete markers del key
exacto, vuelve a enumerarlos para verificar ausencia y solo entonces limpia
`file` y registra `purge_verified_at`. La purga operativa debe terminar en hasta
**siete días naturales tras el vencimiento**; no es una promesa sobre los bloques
físicos internos de B2. Un fallo conserva el key y programa backoff de **23 horas**,
para ser elegible en el cron del día siguiente; programar no acredita ejecutar.
El proxy ya devuelve 410. El tombstone y caption permanecen. Un objeto desaparecido
antes del plazo produce `MEDIA_OBJECT_INCONSISTENT` a nivel ERROR y `failed`,
sin fingir expiración. Una caída temporal del storage conserva `ready` y registra
el fallo de reconciliación. El scavenger solo borra `wa-*.spool` de más de una
hora en el directorio dedicado, sin recursión ni symlinks.

Monitorear `MEDIA_DOWNLOAD_FAILED`, `MEDIA_PURGE_FAILED`,
`MEDIA_RECONCILE_FAILED`, `MEDIA_OBJECT_INCONSISTENT`, `MEDIA_OBJECT_MISSING` y
`MEDIA_STORAGE_UNAVAILABLE`. Eventos incluyen IDs internos/UUID y códigos
genéricos; no incluir filename, caption, token, URL firmada ni excepciones crudas.
Una descarga agotada requiere diagnóstico antes de reencolarla. Los errores de
purga requieren corregir permisos/disponibilidad y reejecutar al vencer backoff.

## API y frontend

GET `/api/inbox/media/<public_id>/` requiere autenticación y `agentinbox.view`.
404 para otra clínica/ID desconocido; 410 `media_expired` por plazo o tombstone;
409 si no está listo; objeto inesperadamente ausente 404 + ERROR; caída 503.
Streaming FileResponse con MIME almacenado, nombre saneado, inline para
imagen/audio/video/pdf y attachment para otros documentos; `private, no-store`,
`nosniff`, CSP sandbox y Vary Authorization/Cookie. No publicar el directorio
privado en Caddy ni incluirlo en static. Optimización del proxy queda futura.

Message DTO expone solo UUID, estado, MIME, tamaño, nombre, vencimiento y
dimensiones/duración opcionales. Sin provider ID, object key, hash ni tokens.
Joins acotados evitan N+1; fingerprints detectan cambios de media y vencimientos
sin modificar el mensaje. La lista añade `last_message_type`/`last_message_filename`.

La UI usa Axios autenticado → blob → objectURL, caché compartida por clínica,
usuario y UUID, con refcount, abort/revoke al salir/cambiar de sesión. Imágenes
pequeñas se cargan al acercarse al viewport; imagen grande/audio/video/documento
requieren clic y muestran peso antes de descargar. Sin autoplay. Caption se
renderiza una vez; lightbox accesible con Escape y retorno del foco. 410/expired
no ofrece retry; los fallos de red permiten reintento explícito. No es un
antivirus ni un intérprete de documentos; respetar los formatos admitidos.

## Antes de producción y después de restaurar

1. M2/M3/M4 **aplicadas a la base habitual local el 22-10-2026**, con backup
   previo y doce prerrequisitos de agent/channels. Ver
   [recibo local](../evals/inbox-readiness-2026-10-22/migrations-local.json).
   Preview/producción siguen sin tocar: aplicar allí mediante el release
   autorizado, con su propio backup y comprobación de writers/worker.
2. Verificar bucket privado dedicado, key mínima, cifrado y ausencia de Object
   Lock. Validar lifecycle independiente que elimine versiones/hide markers y
   multipart incompleto al plazo; la política debe basarse en la fecha del
   objeto, sin reiniciar retención por copias. Probar purga real en bucket de
   prueba. El simulador SDK no acredita configuración real del proveedor.
3. Revisar el [expediente preparado de privacidad/DPA/ARCO](../compliance/inbox-privacy-review-2026-10-22/README.md)
   y la [configuración B2 preparada](../compliance/inbox-privacy-review-2026-10-22/b2-preparacion.md).
   No hay aún credenciales B2 dedicadas; el usuario aplazó la provisión real.
   Lifecycle nativo es respaldo por lotes y no garantiza por sí solo borrado
   físico exacto al día 180. El usuario definió el máximo operativo de siete
   días posteriores; acreditar su cumplimiento real antes de activar.
   Archivar DPA aplicable y evidencias de tratamiento internacional; publicar aviso
   actualizado y versión privacy/re-consentimiento conforme a
   [legal-version-sync](legal-version-sync.md). Confirmar proceso ARCO/borrado
   anticipado. Estos gates siguen pendientes.
4. Tras restore, mantener tráfico cerrado, reaplicar purgas/anonimizaciones y
   ejecutar mantenimiento/reconciliación hasta agotar backlog. Los backups DB
   no contienen binarios; no resucitar referencias borradas por ARCO.
5. Verificar Meta real con los cinco tipos/citas y recepción real. Confirmar que
   la imagen aparece tras un poll del estado ready. Solo después activar las
   banderas mediante el procedimiento de despliegue autorizado.

Rollback: para bloquear acceso y nuevas descargas manteniendo la purga, usar
`INBOX_MEDIA_ACCESS_HOLD=True` y conservar el mantenimiento habilitado. Apagar
procesamiento detiene también sus jobs, pero no borra
archivos ya conservados ni revoca el proxy. Mantener la purga operativa por el
procedimiento autorizado/lifecycle B2 y nunca abrir una ruta pública como
workaround. No revertir M4 eliminando datos; rollback de esquema requiere plan
explícito. B9 BASE conserva su deuda no bloqueante aceptada; los demás gates reales permanecen.

## Respuestas nativas

El sender incorpora `context.message_id` después de la admisión B4 cuando el
original de la misma clínica/contacto/cuenta tiene un wamid utilizable; salientes
deben tener evidencia sent/delivered/read. Sin ella conserva la cita interna y
envía texto sin contexto nativo. No fabrica IDs ni aceptación; timeout/resultado
ambiguo sigue `uncertain`, sin resend automático. Retry humano conserva la cita
y la idempotencia original.


## Incidentes persistentes y deuda operativa de avisos (23-10-2026)

Migración `channels.0018_media_retention_policy` aplicada a desarrollo local
con respaldo verificado el 23-10; preview/producción pendientes de release.
`MediaPurgeIncident`
conserva primer/último fallo, número de fallos, deadline absoluto, escalamiento,
incumplimiento, recibos de transporte, reconocimiento y evidencia de cierre.
Una ejecución no cierra el incidente. `purge_verified_at` acredita únicamente
la ausencia comprobada mediante el adaptador configurado.

La alerta se encola al primer fallo. `maintain_inbox_media` evalúa la escalada
cuando han pasado **24h desde el primer fallo sin resolver**, aunque el siguiente
intento de borrado aún no toque. Al superar siete días se abre un incidente de
cumplimiento, incluso si no hubo intentos por backlog. No desaparece al purgar:
requiere reconocimiento y referencia verificable para cerrar.

El comando devuelve JSON con intentos/fallos/purgas y conteos de incidentes;
sale con error ante fallos de la ejecución, purgas sin resolver, incidentes de
cumplimiento abiertos o backlog elegible restante al agotar lotes. `--alerts-only`
no considera capacidad de purga porque deliberadamente no borra objetos.
Los fallos consumen lote y ceden al siguiente candidato. Priorizar expiraciones
antiguas y ajustar `--batch`/`--max-batches` a llegadas, backlog y tiempo real de
API; los máximos sintéticos no acreditan capacidad de B2. Si se agota el límite,
registrar backlog y aumentar capacidad sin ignorar el deadline.

La plantilla añade `--alerts-only` cada 15min en el **mismo cron**; no hace I/O
binario ni reintenta purgas. El umbral es 24h y se observa en el siguiente tick:
la plantilla no acredita aviso exacto al instante, cron instalado ni capacidad
de operación. Si se necesita un compromiso más estricto, validar frecuencia y
latencia reales antes de afirmarlo. Ningún cron se instaló durante esta entrega.

**Responsable y canal de avisos: pendiente operativo NO BLOQUEANTE**, por
[excepción explícita del usuario](../decisions/2026-10-23-inbox-media-alert-ops-deferred.md).
No hay destinatario inventado ni envío real de prueba. Cuando se designe,
configurar `INBOX_MEDIA_OPS_OWNER` y el `DISCORD_WEBHOOK_URL` ya usado para ops.
El transporte lleva solo IDs internos; no filenames, provider IDs ni URLs de
objetos. HTTP 2xx se conserva como aceptación del transporte, **no** lectura ni
atención humana. Sin ambos valores, el JSON indica configuración pendiente y
no envía. Reintentos de transporte separados de la purga: 15min, con claim/lease.

Comandos para el operador (IDs/ref de expediente, sin datos de pacientes):

```bash
rtk proxy python manage.py inbox_media_ops status --organization 1 --limit 100
rtk proxy python manage.py inbox_media_ops ack --organization 1 --incident UUID --operator operador
rtk proxy python manage.py inbox_media_ops close --organization 1 --incident UUID --operator operador --evidence expediente:recibo-ausencia
```

`close` rechaza la operación si hay key o falta `purge_verified_at`/evidencia.
No cerrar un incidente con el log de que se ejecutó el cron.

## Revocaciones independientes y restore obligatorio

Configurar `INBOX_MEDIA_REVOCATION_ROOT` con una ruta absoluta cuyo último
componente sea `inbox-media-revocations`, en un volumen **independiente del dump**,
privado, con custodia y backup propios. No ubicarlo en static, el repo, imágenes
Docker, una carpeta temporal o un volumen que se revierta con PostgreSQL.
El despliegue debe montarlo en todas las réplicas de API/worker y mantener la
misma identidad de organización/cuenta para el linaje de backups restaurado.

```bash
rtk proxy python manage.py inbox_media_ops init-ledger
rtk proxy python manage.py inbox_media_ops revoke --organization 1 --media UUID --operator operador
```

La revocación escribe primero un registro exclusivo y sincronizado a disco,
después cambia el estado y cancela el claim en DB. Se identifica por clínica,
cuenta y referencia de medio del proveedor (digest en el nombre); así también
bloquea un job recuperado con otro UUID de fila. El registro guarda únicamente
IDs internos, key técnico y fecha/motivo; protegerlo como metadato privado.
Las lecturas y la publicación de descargas consultan este registro. B2 sin
ledger configurado, ledger ilegible/corrupto o `INBOX_MEDIA_ACCESS_HOLD=True`
impiden servir contenido. Local sin ledger se permite solo para desarrollo.

Los archivos son exclusivos y no se sobrescriben por la aplicación; **no** se
afirma inmutabilidad frente al administrador del volumen. Probar permisos,
fsync/custodia, backup independiente e integridad. No hay limpieza automática
del ledger: definir su plazo jurídico sin permitir que reaparezcan revocaciones
desde backups aún restaurables. Un marcador `.ready` no acredita integridad de
un volumen recuperado; comparar inventario independiente en el simulacro.

Antes de restaurar: mantener proxy/webhooks/workers cerrados y configurar
`INBOX_MEDIA_ACCESS_HOLD=True`. Con DB restaurada y ledger vigente montado:

```bash
rtk proxy python manage.py inbox_media_ops restore-check --workers-stopped --limit 1000
rtk proxy python manage.py maintain_inbox_media --batch 100 --max-batches 10
rtk proxy python manage.py inbox_media_ops status
```

`restore-check` exige hold y constancia de workers parados; reaplica revocaciones,
vence referencias antiguas y **congela trabajos pendientes/descargando/fallidos
que no tenían persistencia acreditada**. Evita que un dump previo a la persistencia
reinicie 180 días. Esos jobs no se reencolan automáticamente; revisar el impacto
de pérdida de contenido aún no descargado en el expediente de recuperación.
Verifica keys del ledger incluso cuando no sobreviven en la DB. No cambia
`persisted_at`/`expires_at`. Si excede `--limit`, falla y mantiene el gate cerrado.

El comando emite recibo y **nunca levanta hold ni abre tráfico**. Todavía exige
inventario real del proveedor: objetos no revocados creados después del dump
pueden no estar referenciados en la DB restaurada. Contrastar claves/versiones,
fechas originales y réplicas; purgarlos/reconciliarlos sin renovar retención.
Resolver incidencias, ejecutar pruebas 410/aislamiento y autorizar reapertura
según RUNBOOK-RESTORE. Una restauración ajena al procedimiento no queda cubierta
por una detección mágica dentro de PostgreSQL.

## Copias y publicación

Spool: cleanup en finally y scavenger de huérfanos de más de 1h al ejecutar el
mantenimiento. Caché HTTP: private/no-store; blobs: solo memoria, revoke al salir,
cambiar scope o vencer. No se borran remotamente bytes ya recibidos/guardados
en equipos de la clínica. Dumps: metadata/referencias, no binarios; reaplicar
ledger y conservar timestamps. Meta y réplicas internas del proveedor requieren
su propia verificación contractual y técnica; purgar B2 no prueba su borrado.

El aviso de revisión vigente es el [borrador del 23-10](../compliance/inbox-privacy-review-2026-10-23/README.md).
Compilarlo no lo publica. Publicar con fecha efectiva, verificar HTTPS, promover
privacy con seed y validar reaceptación de cuentas de prueba. B2 real, región,
contrato, Meta/recepción y activación conservan su estado pendiente.
