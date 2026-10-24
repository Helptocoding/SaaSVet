# Evidencia B9E — WSL2 r8

Campaña **PENDING por reserva de disco**. El monitor de `/mnt/c` registró
0,85 GiB libres, por debajo del mínimo de 1 GiB. El journal conserva
**53/87 IDs `ok`**, sin recibo final ni aprobación del bloque dirigido.
Checks posteriores y cinco PROFILE NOT_EXECUTED.
[Reporte](REPORT.md), [decisión](candidate-decision.json), [STOP original](STOP.json),
[recibo parcial](directed-partial-receipt.json).
No repetir esta campaña mediante los scripts conservados.

`artifact-index.json` inventaría los artefactos anteriores al empaquetado.
`preservation-manifest.json` define miembros recuperables, tamaños y hashes
SHA-256 de archivos, partes y ZIP completo. El paquete independiente incluye
los logs originales completos. Las ocho campañas anteriores se conservan.

`preservation-verification.json` acredita restauración interna y otra mediante
invocación real de CLI. El restaurador comprueba todos los hashes y requiere
un destino ausente o vacío. Desde la raíz del repositorio:

```powershell
rtk proxy python -B docs/evals/b9-integral-acceptance-1947726-wsl-20261011-r8/restore_wsl.py --destination C:/ruta/nueva/b9i-r8-restored
```

`git-selection.json` conserva la selección explícita y
`delivery-verification.json` acredita blobs Git, conservación de selecciones
previas y control del diff. Los recibos de recuperación y entrega son
posteriores al paquete y se versionan directamente. Sin commits ni push.

`cleanup.json`, `resource-observer-closure.json`, `awake-request/closure.json`
y `clock-restoration.json` acreditan el cierre de recursos propios, liberación
de la solicitud temporal de actividad y restauración de sincronización de WSL.
`acta-update.json` acredita el prefijo exacto conservado del acta.

`diagnostics/close_campaign.py` documenta y clasifica resultados después del
STOP; está fuera del evaluador sellado y no ejecuta pruebas de aplicación.
La recuperación posterior del espacio libre no valida retroactivamente el
bloque ni establece la causa de la caída temporal. Otra campaña requiere una
nueva decisión y margen estable en el disco real de respaldo.
