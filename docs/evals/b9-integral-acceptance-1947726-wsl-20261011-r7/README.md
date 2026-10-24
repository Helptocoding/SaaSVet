# Evidencia B9E — WSL2 r7

Campaña **PENDING por discontinuidad de reloj tras suspensión del host**.
Corpus dirigido **87/87 PASS**, Django check y drift PASS; migración posterior
interrumpida. Demás bloques y cinco PROFILE NOT_EXECUTED. No se registró
agotamiento de las reservas de memoria o disco.
[Reporte](REPORT.md), [decisión](candidate-decision.json), [STOP original](STOP.json),
[eventos del host](windows-clock-power-events.json).
No repetir esta campaña mediante los scripts conservados.

`artifact-index.json` inventaría los artefactos anteriores al empaquetado.
`preservation-manifest.json` define miembros recuperables, tamaños y hashes
SHA-256 de archivos, partes y ZIP completo. El paquete independiente incluye
los logs originales completos. Las siete campañas anteriores se conservan.

`preservation-verification.json` acredita restauración interna y otra mediante
invocación real por CLI. El restaurador comprueba todos los hashes y requiere
un destino ausente o vacío. Desde la raíz del repositorio:

```powershell
rtk proxy python -B docs/evals/b9-integral-acceptance-1947726-wsl-20261011-r7/restore_wsl.py --destination C:/ruta/nueva/b9i-r7-restored
```

`git-selection.json` conserva la selección explícita y
`delivery-verification.json` acredita blobs Git, conservación de selecciones
previas y control del diff. Los recibos de recuperación y entrega son
posteriores al paquete y se versionan directamente. Sin commits ni push.

`cleanup.json`, `resource-observer-closure.json` y `clock-restoration.json`
acreditan el cierre de recursos propios y la restauración de sincronización de
WSL. `acta-update.json` acredita la conservación del prefijo exacto del acta.

`diagnostics/awake_guard.py` se preparó después del STOP para una futura
campaña, fuera del evaluador sellado de r7. `awake-request-probe` acredita una
solicitud de actividad y su restauración durante 2 s; no acredita evitar una
suspensión durante toda una campaña. No se utilizó en las pruebas de r7 y no
inicia tests. Su integración futura debe conservar todos los gates originales.
