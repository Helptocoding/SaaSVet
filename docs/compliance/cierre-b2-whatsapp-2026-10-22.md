# Cierre B2 y WhatsApp: evidencia y seis puntos pendientes

Actualización local: **2026-10-23**. Decisión de parámetros definida: **1 de 6**.
Los otros cinco puntos conservan su evidencia final pendiente. Hay implementación y
preparación acreditadas; todavía no hay provisión/prueba real B2, publicación
del aviso ni aprobación contractual. Esta lista incorpora las garantías pedidas
por el usuario. [B9 BASE queda como deuda aceptada no bloqueante](../decisions/2026-10-22-b9-base-latency-accepted-debt.md).

## Lo localizado en la landing y el proyecto

La landing actual declara **Backblaze, Inc., Estados Unidos** en
`LandingSaaS/frontend/src/pages/aviso-de-privacidad.astro`, sección 6. Distingue
backups cifrados con age y almacenamiento operativo de adjuntos con cifrado del
proveedor. La sección 3.5 ya contempla WhatsApp y la retención de 180 días. El
registro `docs/compliance/vendors.md` también declara EE.UU. y DPA pendiente.

Esto acredita el **país declarado en los documentos**, no la región real del
bucket. No aparecen claves B2/Backblaze/región en `.env` o `.env.example` de la
landing; tampoco se encontró una región de media configurada en el `.env` local ni un
contrato aceptado que cierre ese punto. `us-west-004` aparece en un test con
bucket/key expresamente sintéticos: no es prueba de la ubicación del servicio.
La ubicación de Hetzner indicada en la landing tampoco demuestra la de B2.

Backblaze documenta que la región se elige por cuenta; debe contrastarse con el
endpoint y una consulta autenticada `GetBucketLocation` del bucket operativo.
Si se emplea la cuenta de backups, confirmar su región real; no trasladar al
bucket nuevo una conclusión contractual por el mero uso previo de backups.
Fuentes: [regiones](https://www.backblaze.com/docs/cloud-storage-data-regions) y
[consulta de ubicación](https://www.backblaze.com/apidocs/s3-get-bucket-location).

## Lista de cierre 1/6 (decisión de política definida; operación no certificada)

- [ ] **1. Decisión jurídica — región, tratamiento internacional y contrato.**
  País declarado localizado: EE.UU. Faltan cuenta/tipo, región real y endpoint,
  instrumento aplicable y adhesión acreditada, subencargados pertinentes y
  clasificación jurídica del tratamiento. Responsable: titular autorizado del
  contrato con la revisión jurídica correspondiente. Evidencia: ficha completa,
  versión/fecha del contrato y aceptación real, sin claves en Git.
- [x] **1. Decisión de producto/operación — parámetros de retención definidos.**
  [Documento del usuario incorporado](../decisions/2026-10-22-inbox-media-retention-policy.md):
  180 días naturales desde persistencia, purga operativa verificada en siete días,
  reintentos diarios, primer fallo con alerta, escalamiento a las 24 horas y restore
  sin reactivación. Esto cierra la elección de parámetros; firma nominal, revisión
  jurídica y cumplimiento operativo no se inventan y siguen registrados pendientes.
  Responsable/canal de avisos: [deuda no bloqueante aceptada](../decisions/2026-10-23-inbox-media-alert-ops-deferred.md).
- [ ] **2. Validación técnica — almacenamiento, autorización y eliminación.**
  Evidencia de fase 3 conservada; los controles nuevos se registran en
  [el expediente de política](../evals/inbox-media-policy-2026-10-23/README.md).
  La comparación de 16 hashes correspondía al corte del 22: parte del código
  ahora cambió de forma autorizada para cumplir esta decisión. 0018 ya aplicada
  a desarrollo local con respaldo. Falta proveedor real, capacidad/cron, custodia
  del ledger y restore con inventario de objetos/versiones del servicio real.
  El simulacro local no sustituye esas pruebas ni reabre tráfico.
- [ ] **3. Publicación — revisar y publicar el aviso.**
  [Aviso completo y parche vigentes](inbox-privacy-review-2026-10-23/README.md):
  180 días y máximo operativo verificado de siete días, con límites de copias.
  **Build íntegro de revisión PASS, 18 páginas**, en
  [landing-build.json](../evals/inbox-media-policy-2026-10-23/landing-build.json).
  Original de la landing intacto. Faltan revisión final, fecha efectiva, release
  y comprobación del contenido público por HTTPS.
- [ ] **3. Publicación — sincronizar la versión legal.**
  Comando preparado en el expediente anterior. Ejecutarlo solo con la fecha/URL
  efectivamente publicadas; verificar el gate con cuentas de prueba ADMIN/VET/
  ASSISTANT y conservar las aceptaciones anteriores. Ningún seed/promoción ni
  aceptación por usuarios reales se ejecutó durante esta inspección.
- [ ] **4. Activación — revalidar los gates de WhatsApp.**
  Confirmar B2, Meta/recepción, contratos/aviso, mantenimiento,
  restauración y demás requisitos aplicables. Responsable/canal de avisos quedan
  como deuda no bloqueante aceptada; no se exigen como gate por sí solos. Meta/recepción sigue a
  cargo del usuario; B2 real continúa aplazado. Registrar aprobadores y recibos
  reales antes de cambiar banderas. La deuda BASE aceptada no bloquea este paso.

Un punto se marca completo únicamente con su evidencia final. Build o pruebas
mockeadas son avances parciales, no publicación ni validación del proveedor.


## Cambios posteriores del 23 de octubre

El expediente de esta entrega añade verificación posterior al borrado, incidentes
persistentes, umbrales de 24h/7d, resultado no exitoso ante purgas fallidas o
incidentes de cumplimiento abiertos, y ledger de revocaciones independiente del
dump. Los reintentos se programan con 23h de backoff para quedar elegibles al
siguiente cron diario. Los intentos fallidos consumen lote y no ocultan el resto.
Se prepara observación de umbrales cada 15min con el mismo cron: registra el
umbral al primer tick posterior, no garantiza entrega exactamente a las 24h.

Responsable y canal pendientes son **no bloqueantes por decisión expresa del
usuario**. No se exigen para cerrar el plan como deuda aceptada; la entrega y
atención no se convierten en PASS. Se conserva el gate por incumplimiento real de
purga. La tabla histórica inferior describe la inspección del 22; los cambios y
pruebas posteriores se detallan en el expediente nuevo y runbook vigente.

El [aviso de revisión vigente](inbox-privacy-review-2026-10-23/README.md) incorpora
el máximo operativo aprobado; el build anterior de 18 páginas no valida ese
nuevo texto. Publicación HTTPS, seed y reaceptación siguen pendientes.

## Garantías técnicas solicitadas (corte histórico 22-10)

| Garantía | Evidencia existente | Qué falta antes de activar B2 |
|---|---|---|
| Timestamp persistido y confiable | `process_media_claim` guarda juntos `persisted_at` y `expires_at = persisted_at + 180 días` al completar la persistencia. El GET no recalcula la fecha. Test `test_durable_success_retention_and_single_claim_for_discarded_inbound`. | Acreditar reloj operativo y conservar los timestamps originales en restore; no renovar el plazo por una relectura o copia. |
| Autorización comprueba vigencia/eliminación | `inbox_media_view` exige permiso y clínica; rechaza `expired` o plazo vencido con 410 antes de acceder a storage, y estados no ready con 409. Pruebas de scope, permiso y vencimiento antes de purga conservadas. | Validación end-to-end con bucket y cuentas reales de prueba. Una bandera de descarga apagada no sustituye revocar el acceso. |
| Fallos visibles y reintentos controlados | Se conserva key, estado expired, `error=purge_failed`, evento WARNING `MEDIA_PURGE_FAILED` con IDs internos y `next_attempt_at` una hora después. Logging JSON envía el evento a stdout. | Acreditar alerta, destinatario, atención y recuperación. El comando puede terminar exit 0 aunque una purga haya fallado: no monitorizar solo su exit code. El cron es diario; una hora de backoff no equivale a ejecutar al cabo de una hora. |
| Eliminar todas las versiones pertinentes | `B2MediaStorage.delete` pagina versiones y delete markers, filtra key exacto y borra en lotes; errores parciales se propagan. Tests de versiones, vecino no borrado y fallo de permisos conservados. | Demostrar listado vacío tras purga real y validar Object Lock/lifecycle; no basta ocultar la versión actual. |
| Restore no reactiva revocaciones ni expirados | Timestamps absolutos impiden que un objeto ya vencido vuelva a servirse por el mero paso del tiempo. ARCO y p60 exigen reaplicar purgas antes del tráfico. | Acreditar registro de revocaciones independiente del dump y simulacro. Una DB antigua podría recuperar una referencia revocada o un job pendiente que intente descargar otra vez: reconciliar por existencia no sustituye esa revocación. |
| Temporales, cachés y réplicas documentados | Inventario inferior; spool con cleanup/finally y scavenger; blobs por usuario/clínica; HTTP `private, no-store`; sin URL pública/presigned en v1. | Acreditar operación del scavenger, política del dispositivo de la clínica y configuración real de replicación/retención del proveedor. |

El mantenimiento previsto en `scripts/crontab.example` es a las 06:45 diarias,
en la zona indicada por la plantilla. Procesa lotes acotados (100 × hasta 10) y
es inerte con `INBOX_MEDIA_ENABLED=False`. No hay un cron instalado acreditado
por esta revisión. Sin frecuencia, capacidad y escalamiento definidos, no se
puede prometer una purga máxima ni para el caso de fallo persistente.

## Copias y réplicas que hay que contemplar

| Copia / ubicación | Comportamiento y límite |
|---|---|
| Objeto canónico B2 y sus versiones | Backend de producción previsto; todavía sin provisión real de media. Borrado del key con todas sus versiones/markers. Confirmar replicación del proveedor y su eliminación contractual, sin equiparar confirmación del API con prueba de borrado de bloques físicos internos. |
| Spool del worker | Directorio dedicado `saaslyvet-inbox-media-spool`, `wa-*.spool`, límites de transferencia y borrado en finally. Tras una caída abrupta, scavenger elimina los de más de una hora cuando se ejecuta; no garantiza eliminación exactamente al cumplir una hora. |
| Backend local de desarrollo | `backend/private-media` por defecto; no existía al inspeccionar. No se usa en producción B2. Se excluye de Git y ahora también del contexto Docker. El spool dedicado también queda excluido de Git/Docker si se ubica dentro del proyecto. |
| Respuesta y memoria del navegador | Proxy sin caché HTTP; blobs/object URLs en memoria por usuario/clínica/archivo, refcount y abort/revoke al desmontar/cambiar scope o vencer. No es borrado remoto de bytes que ya recibió un dispositivo. |
| Documento descargado o copia del usuario | El usuario autorizado puede guardar un archivo. Su copia queda en el dispositivo/sistema de la clínica y requiere su propia política ARCO/retención; borrar B2 no elimina esa copia. |
| Backups Postgres p40 | Contienen texto/captions, metadata y referencias; no el binario B2. Ciclo documentado: local 14 días, daily 30 días, monthly 12 meses. Mantener dump plano temporal, cifrado age y limpieza conforme al runbook; reaplicar revocaciones al restaurar. |
| Archivos originales en Meta | Su conservación es independiente del objeto operativo B2 y queda sujeta al contrato/políticas del canal. Una purga B2 no acredita eliminación en Meta. |
| CDN/caché persistente adicional | No se identificó configuración de CDN/caché de binarios en el flujo revisado. No se da por inexistente una réplica creada fuera del repo: verificar configuración real del bucket/infra al provisionar. |

## Contrato y subencargados: ficha que debe completarse

Términos oficiales consultados: [ToS, efectivos 16-04-2026](https://www.backblaze.com/company/policy/terms-of-service).
La aplicabilidad a la cuenta concreta y su aceptación deben acreditarse. El
[DPA EEA/EU](https://www.backblaze.com/company/policy/dpa-for-eea-eu-residents)
declara ámbito GDPR; no se presume suficiente para la operación mexicana.

La [lista oficial de subencargados](https://www.backblaze.com/company/policy/subprocessors)
(fecha indicada 03-12-2025) distingue archivos de clientes y datos de cuenta.
Para almacenamiento enumera operadores por región; también distingue cuentas
individuales y de organización. Completar la región/modalidad de cuenta y
seleccionar los proveedores aplicables, en vez de incorporar indiscriminadamente
todos los proveedores de datos comerciales de la cuenta a la cadena de adjuntos.
Clasificar jurídicamente remisión/encargo/transferencia y el alcance de accesos
internacionales con esa información; la sede del proveedor no resuelve por sí
sola la clasificación ni acredita la ubicación del bucket.

## Verificación de esta entrega

[Inventario sin secretos y comparación de fuentes](../evals/inbox-b2-guarantees-2026-10-22/source-inventory.json).
Se reutiliza la evidencia local existente; no se ejecutaron B9 ni cargas de
producto, no se contactó almacenamiento con credenciales y no se promovió ninguna
versión legal. El build de revisión y las exclusiones de artefactos no cierran
los gates externos. Los recibos históricos permanecen intactos.
