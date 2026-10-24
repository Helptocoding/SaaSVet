# Evidencia B9E — WSL2 r5

Campaña PENDING por agotamiento de la reserva de memoria de Windows durante
el arranque del corpus dirigido. El mínimo de admisión de 5 GiB fue retirado
por instrucción explícita del usuario; la reserva retenida de 2 GiB se agotó.
Cero IDs completados. [Reporte](REPORT.md), [decisión](candidate-decision.json),
[política autorizada](resource-policy.json), [STOP original](STOP.json).
No repetir la campaña mediante los scripts conservados.

`artifact-index.json` inventaría los artefactos anteriores al empaquetado.
`preservation-manifest.json` define los miembros recuperables, tamaños y hashes
SHA-256 de archivos, partes y ZIP completo. El paquete es independiente e
incluye los logs originales completos. Las cinco campañas anteriores se conservan.

`preservation-verification.json` acredita una restauración interna y otra
mediante invocación real por CLI. El restaurador comprueba todos los hashes y
requiere un destino ausente o vacío. Desde la raíz del repositorio:

```powershell
rtk proxy python -B docs/evals/b9-integral-acceptance-1947726-wsl-20261011-r5/restore_wsl.py --destination C:/ruta/nueva/b9i-r5-restored
```

`git-selection.json` conserva la selección explícita y
`delivery-verification.json` acredita los blobs Git, la preservación de las
selecciones previas y el control del diff. Los recibos de recuperación y entrega
son posteriores al paquete y se versionan directamente. Sin commits ni push.

`cleanup.json` y `clock-restoration.json` acreditan la retirada de los recursos
propios y la restauración de la sincronización de WSL. `acta-update.json`
verifica que el acta conservó su prefijo exacto. El helper de informes posterior
al STOP no pertenece al evaluador sellado ni ejecuta tests.
