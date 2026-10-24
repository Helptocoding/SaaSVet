# Conservación del diagnóstico

[Reporte](REPORT.md) · [Inventario](artifact-index.json) ·
[Manifest del paquete](preservation-manifest.json) · [Recuperación comprobada](preservation-verification.json) ·
[Entrega Git](delivery-verification.json).

Los logs originales están dentro del ZIP sin normalización. Para recuperar en
una carpeta ausente o vacía, desde este expediente:

```powershell
rtk proxy python -B restore_wsl.py --destination C:/ruta/nueva/diagnostico-recuperado
```

Se verifican hashes de partes, archivo y miembros, y una recuperación interna
más otra mediante el CLI real. El índice Git contiene únicamente los paths
explícitos del diagnóstico y las dos reglas compartidas de entrega; no se cambia
el acta ni la decisión de r9. No se crea commit ni se hace push.
