# Evidencia B9E — WSL2 r6

Campaña **PENDING por discontinuidad de reloj tras suspensión del host**.
Corpus dirigido **87/87 PASS**, Django check y drift PASS; migración posterior
interrumpida. Los bloques restantes y las cinco variantes PROFILE no se
ejecutaron. Se conservó la excepción de admisión solicitada por el usuario y
la reserva de 2 GiB, sin agotamiento registrado.
[Reporte](REPORT.md), [decisión](candidate-decision.json),
[STOP original](STOP.json), [eventos del host](windows-clock-power-events.json).
No repetir la campaña mediante los scripts conservados.

`artifact-index.json` inventaría los artefactos anteriores al empaquetado.
`preservation-manifest.json` define los miembros recuperables, tamaños y hashes
SHA-256 de archivos, partes y ZIP completo. El paquete es independiente e
incluye los logs originales completos. Las seis campañas anteriores se conservan.

`preservation-verification.json` acredita una restauración interna y otra
mediante invocación real por CLI. El restaurador comprueba todos los hashes y
requiere un destino ausente o vacío. Desde la raíz del repositorio:

```powershell
rtk proxy python -B docs/evals/b9-integral-acceptance-1947726-wsl-20261011-r6/restore_wsl.py --destination C:/ruta/nueva/b9i-r6-restored
```

`git-selection.json` conserva la selección explícita y
`delivery-verification.json` acredita los blobs Git, la preservación de las
selecciones previas y el control del diff. Los recibos de recuperación y entrega
son posteriores al paquete y se versionan directamente. Sin commits ni push.

`cleanup.json`, `resource-observer-closure.json` y `clock-restoration.json`
acreditan la retirada de los recursos propios, el cierre del observador Windows
y la restauración de sincronización de WSL. `acta-update.json` verifica que el
acta conservó su prefijo exacto. Los diagnósticos e informes posteriores al STOP
no pertenecen al evaluador sellado ni ejecutan tests.
