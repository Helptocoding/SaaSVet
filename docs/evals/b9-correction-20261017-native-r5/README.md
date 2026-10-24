# Conservación B9 compuesto

[Reporte](REPORT.md) · [Decisión](candidate-decision.json) · [Bloques](block-status.json) ·
[Índice](artifact-index.json) · [Manifest](preservation-manifest.json) ·
[Prueba de recuperación](preservation-verification.json) · [Entrega](delivery-verification.json).

El paquete conserva logs nuevos, el diff sobre la base y las copias originales
referenciadas bajo `referenced-evidence/`. El [manifiesto](reuse-manifest.json)
identifica su procedencia y SHA-256; esas copias no son ejecuciones nuevas.
Los recibos que sustentan este cierre se recuperan dentro del mismo paquete.
Recuperar en una
carpeta ausente o vacía desde este expediente:

```powershell
rtk proxy python -B restore_native.py --destination C:/ruta/nueva/b9-recuperado
```

Se validan SHA-256 de partes, archivo y miembros. El empaquetador verifica
una recuperación interna y otra por CLI. No inicia pruebas ni PostgreSQL.
Las dos correcciones staged coinciden con el árbol evaluado según
[code-selection.json](code-selection.json); los paths de evidencia son explícitos.
Los logs se conservan dentro del ZIP sin normalización Git. No hay commit o push.
