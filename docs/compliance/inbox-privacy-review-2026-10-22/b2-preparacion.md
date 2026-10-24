# B2 operativo: configuración preparada, provisión aplazada

Estado **PENDIENTE POR INDICACIÓN DEL USUARIO**: no hay cuenta/key dedicadas para
media. Este documento no crea recursos ni acredita pruebas del proveedor.

Crear un bucket dedicado privado en la región que apruebe el expediente DPA.
Mantener Object Lock deshabilitado desde su creación. Configurar SSE-B2 AES256,
sin URLs públicas/CDN ni presigned GET. Separar de los backups p40/age y sus keys.

La key de ejecución se restringe al bucket y prefijo `inbox-media/`, con permisos
para leer/escribir/listar y borrar **versiones**, suficientes para el adaptador
S3 de la aplicación. No usar la master key ni permisos para administrar cuentas,
keys o buckets. Las verificaciones administrativas de bucket/lifecycle pueden
necesitar otra identidad de operador: no ampliar por ello la key del worker.

Variables que se cargarán en el almacén de secretos del entorno autorizado:

```dotenv
MEDIA_BACKEND=b2
MEDIA_B2_ENDPOINT_URL=
MEDIA_B2_REGION_NAME=
MEDIA_B2_BUCKET=
MEDIA_B2_ACCESS_KEY_ID=
MEDIA_B2_SECRET_ACCESS_KEY=
INBOX_MEDIA_ENABLED=False
INBOX_MEDIA_PRODUCTION_APPROVED=False
```

Completar el endpoint HTTPS S3 oficial correspondiente a la región. No guardar
los valores de keys en este documento, Git ni logs. Ambas banderas siguen apagadas
hasta terminar los gates y aprobar el despliegue/activación por separado.

## Lifecycle de respaldo propuesto

Para revisión con el operador, este JSON corresponde a `lifecycleRules` del API
nativo B2 y aplica solo al prefijo operativo:

```json
[
  {
    "fileNamePrefix": "inbox-media/",
    "daysFromUploadingToHiding": 180,
    "daysFromHidingToDeleting": 1,
    "daysFromStartingToCancelingUnfinishedLargeFiles": 1
  }
]
```

**No acredita purga física exacta al día 180.** Las
[reglas oficiales](https://www.backblaze.com/docs/en/cloud-storage-lifecycle-rules)
se ejecutan diariamente y el borrado se cuenta desde ocultación. Un archivo puede
persistir físicamente después de su vencimiento; no representar `180 + 1` como
un máximo de 180. El mecanismo primario es el bloqueo por `expires_at` y la purga
de todas las versiones por la aplicación; lifecycle es respaldo independiente.
Resolver y aprobar el plazo efectivo de borrado, frecuencia de mantenimiento y
tratamiento de incidencias antes de activar o prometer borrado físico estricto.
No adelantar ocultación a 179 días: rompería la disponibilidad comprometida.

Al actualizar lifecycle, preservar o revisar expresamente todas las reglas del
bucket: una actualización puede sustituir el conjunto. Inspeccionar versiones,
hide/delete markers y cargas incompletas. No copiar objetos para reiniciar su
antigüedad ni habilitar retención inmutable incompatible con ARCO.

## Recibo real que falta

Con el bucket de prueba dedicado y archivos sintéticos sin datos personales:

1. Registrar región, privacidad, cifrado, Object Lock deshabilitado y reglas
   efectivas. Conservar identificación de key/capacidades, nunca su secreto.
2. Subir dos versiones del mismo key dentro de un prefijo de prueba; leer usando
   la key del worker y comprobar AES256 y ausencia de acceso anónimo.
3. Ejecutar el borrado del adaptador y listar versiones/markers del key exacto;
   verificar que no queda ninguna. Probar un fallo de permisos y su recibo.
4. Comprobar mantenimiento, 410 a partir del vencimiento y reintento de purga sin
   exposición del binario. Verificar una solicitud ARCO anticipada y un restore.
5. Acreditar lifecycle independientemente con evidencia del proveedor y su
   frecuencia real. No esperar 180 días ni afirmar que una simulación lo prueba;
   una regla corta requiere un bucket de prueba separado y aprobación del operador.

El resultado seguirá pendiente hasta aportar ese recibo. La aplicación local no
ha enviado archivos reales ni contactado B2 con credenciales de producción.
