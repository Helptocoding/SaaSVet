# Evidencia B9E — WSL2 r3

La campaña de `1947726` termina PENDING por la visibilidad de dependencias desde
el intérprete base de tres casos B3. [Reporte y límites](REPORT.md),
[decisión](candidate-decision.json), [clasificación](incident-classification.json).
El STOP y los resultados originales permanecen intactos. No repetir los bloques
mediante los scripts conservados ni interpretar discovery como ejecución.

`artifact-index.json` inventaría los artefactos previos al empaquetado.
`preservation-manifest.json` añade hashes SHA-256 y tamaños por miembro, por parte
y del ZIP completo. El paquete es propio de esta campaña; incluye los logs
originales completos y no reutiliza inventarios congelados anteriores.

`preservation-verification.json` acredita dos restauraciones independientes,
incluida una invocación real por CLI. Se verifican todos los miembros antes y
después de escribirlos. El destino debe ser nuevo; no se sobrescriben archivos.
Desde la raíz del repositorio, con Python disponible y un destino absoluto nuevo:

```powershell
rtk proxy python -B docs/evals/b9-integral-acceptance-1947726-wsl-20261011-r3/restore_wsl.py --destination C:/ruta/nueva/b9i-r3-restored
```

Se conserva la selección explícita en `git-selection.json` y su verificación en
`delivery-verification.json`. Los logs quedan dentro del paquete, con hashes y
bytes originales; las copias locales siguen presentes. El diff del adaptador
conserva sus espacios legítimos de contexto mediante un atributo limitado a ese
archivo. No se modifican producto, locks ni las campañas previas.

`cleanup.json` y `clock-restoration.json` acreditan la retirada de los recursos
propios y la restauración de la sincronización de WSL. `clock-diagnostics/`
contiene las observaciones previas; `clock-closure/` conserva la orden de cierre.
`diagnostics/base_interpreter_probe.py` se creó tras el STOP únicamente para
diagnosticar imports: no pertenece al evaluador sellado ni ejecuta tests.

Los informes de recuperación y entrega son recibos posteriores al paquete,
versionados directamente. `preservation-manifest.json` define el alcance exacto
recuperable. La entrega no crea commits ni hace push o activación.
