# Evidencia B9E — WSL2 r4

La campaña de `1947726` termina PENDING por memoria disponible de Windows
antes del primer bloque. La corrección de dependencias y la validación de los
dos intérpretes pasaron; no se ejecutó ningún test.
[Reporte](REPORT.md), [decisión](candidate-decision.json),
[clasificación](incident-classification.json) y [STOP original](STOP.json).
No repetir la campaña mediante los scripts conservados.

`artifact-index.json` inventaría los artefactos previos al empaquetado.
`preservation-manifest.json` define los miembros recuperables, tamaños y
hashes SHA-256 de cada archivo, parte y ZIP completo. Es un paquete independiente
que incluye los logs originales completos. Las cuatro campañas anteriores se
conservan en sus expedientes.

`preservation-verification.json` acredita una restauración interna y otra
mediante una invocación real por CLI. El restaurador comprueba todos los hashes
y exige un destino ausente o vacío. Desde la raíz del repositorio:

```powershell
rtk proxy python -B docs/evals/b9-integral-acceptance-1947726-wsl-20261011-r4/restore_wsl.py --destination C:/ruta/nueva/b9i-r4-restored
```

`git-selection.json` contiene la selección explícita y
`delivery-verification.json` acredita su correspondencia con los blobs Git,
la ausencia de cambios en los archivos previamente staged y el control del diff.
Los recibos de recuperación y entrega son posteriores al paquete y se versionan
directamente. No se crearon commits ni se hizo push.

`cleanup.json` y `clock-restoration.json` acreditan la retirada de los recursos
propios y la restauración de la sincronización de WSL. `acta-update.json`
comprueba que se conservó el prefijo exacto del acta. El helper
`diagnostics/close_campaign.py` se creó tras el STOP para documentar el cierre,
sin modificar el evaluador sellado ni ejecutar tests.
