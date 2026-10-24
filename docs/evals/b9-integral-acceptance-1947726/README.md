# Campaña integral de `1947726`

Decisión: **PENDING / PREFLIGHT_BLOCKED**. [Reporte y límites](REPORT.md), [estado por bloque](block-status.json), [matriz del candidato](candidate-decision.json).

Los JSON, documentos y fuentes de ensamblaje quedan legibles directamente en Git. Los logs y journals originales se conservan dentro de las partes ZIP bajo `evidence-packages/`; los originales locales también permanecen. [Inventario propio y hashes](preservation-manifest.json), [comprobación de recuperación](preservation-verification.json), [índice](artifact-index.json), [selección Git](git-selection.json).

Para recuperar todos los miembros en una carpeta nueva o vacía, sin importar la aplicación ni conectar bases/proveedores:

```powershell
rtk proxy python -B docs/evals/b9-integral-acceptance-1947726/restore_campaign.py --destination C:/evidence/b9i-1947726
```

Requiere Python 3.9 o posterior y sólo la biblioteca estándar. Verifica hashes, tamaños, partes, ZIP concatenado, inventario exacto y confinamiento antes de escribir miembros; rechaza destinos no vacíos. Una recuperación interrumpida no cuenta como PASS y puede dejar archivos parciales en su destino.

Las fuentes `prepare_campaign.py`, `discover_candidate.py`, `stage_environment.py`, `close_campaign.py` y `finish_cleanup.py` documentan los comandos realmente usados y sus límites. `campaign.py` y `recorded_suite.py` fueron preparación para etapas posteriores **no ejecutadas**; no son autorización ni evidencia de una campaña nueva. Las rutas temporales se retiraron y los scripts rehúsan varios tipos de sobrescritura. Una repetición requiere una decisión y un expediente nuevos.

El empaquetado y la recuperación son operaciones de conservación, no tests del producto. No se reutilizó el inventario congelado ni el empaquetador del expediente histórico B9.
