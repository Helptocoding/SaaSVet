# Conservación B9 corregido

[Reporte](REPORT.md) · [Decisión](candidate-decision.json) · [Bloques](block-status.json) ·
[Índice](artifact-index.json) · [Manifest](preservation-manifest.json) ·
[Prueba de recuperación](preservation-verification.json) · [Entrega](delivery-verification.json).

El paquete conserva logs originales y el diff sobre la base. Recuperar en una
carpeta ausente o vacía desde este expediente:

```powershell
rtk proxy python -B restore_native.py --destination C:/ruta/nueva/b9-recuperado
```

Se validan SHA-256 de partes, archivo y miembros. El empaquetador verifica
una recuperación interna y otra por CLI. No inicia pruebas ni PostgreSQL.
Las dos correcciones staged coinciden con el árbol evaluado según
[code-selection.json](code-selection.json); los paths de evidencia son explícitos.
Los logs se conservan dentro del ZIP sin normalización Git. No hay commit o push.
