"""Bring live operations docs in line with the approved policy and new controls."""
from pathlib import Path

root = Path(__file__).resolve().parents[3]
p = root/'docs/runbooks/inbox-media.md'
text = p.read_text(encoding='utf-8')
text = text.replace('El mantenimiento deja de servir al cumplir 180 días desde `persisted_at`, marca\n`expired`, borra físicamente todas las versiones y delete markers del key exacto\ny limpia `file`. Un fallo de purga conserva el key para reintentar en una hora;\nel proxy ya devuelve 410.', '''El proxy deja de servir al cumplir **180 días naturales desde `persisted_at`**,
usando el reloj UTC de PostgreSQL (`clock_timestamp()`), igual que el worker y
los umbrales. Las lecturas y restauraciones no renuevan el vencimiento persistido.
El mantenimiento marca `expired`, elimina versiones y delete markers del key
exacto, vuelve a enumerarlos para verificar ausencia y solo entonces limpia
`file` y registra `purge_verified_at`. La purga operativa debe terminar en hasta
**siete días naturales tras el vencimiento**; no es una promesa sobre los bloques
físicos internos de B2. Un fallo conserva el key y programa backoff de **23 horas**,
para ser elegible en el cron del día siguiente; programar no acredita ejecutar.
El proxy ya devuelve 410.''')
text = text.replace('físico exacto al día 180; resolver el plazo efectivo antes de activar.',
    'físico exacto al día 180. El usuario definió el máximo operativo de siete\n   días posteriores; acreditar su cumplimiento real antes de activar.')
text = text.replace('B9/security y los gates históricos no cambian por este cierre local.',
    'B9 BASE conserva su deuda no bloqueante aceptada; los demás gates reales permanecen.')
text += '''

## Incidentes persistentes y deuda operativa de avisos (23-10-2026)

Requiere migración `channels.0018_media_retention_policy`. `MediaPurgeIncident`
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
sale con error ante fallos de la ejecución o incidentes de cumplimiento abiertos.
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
rtk proxy python manage.py inbox_media_ops status
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
'''
p.write_text(text, encoding='utf-8')
for filename in ('docs/runbooks/RUNBOOK-RESTORE.md', 'docs/compliance/arco.md'):
    p = root/filename
    text = p.read_text(encoding='utf-8')
    text += '''

### Actualización 23-10-2026: política y herramientas de medios

La [política definida por el usuario](../decisions/2026-10-22-inbox-media-retention-policy.md)
fija 180 días y purga operativa verificada en hasta siete días tras expirar.
Usar el [procedimiento vigente de medios](../runbooks/inbox-media.md), con ledger
independiente del dump, `INBOX_MEDIA_ACCESS_HOLD=True`, workers/webhooks detenidos,
`inbox_media_ops restore-check --workers-stopped`, mantenimiento y comprobación
de inventario del proveedor antes de autorizar tráfico. El comando no reabre
tráfico. ARCO anticipado usa `inbox_media_ops revoke`: ledger duradero primero,
fencing/estado DB después; no borrar la key antes de verificar la purga.

Responsable y canal de alertas quedan pendientes operativos no bloqueantes por
decisión expresa del usuario; no registrar entrega/atención como comprobadas.
Los incidentes de purga que superan siete días sí mantienen el cierre pendiente.
'''
    p.write_text(text, encoding='utf-8')
print('Live runbooks updated; old receipts preserved')
