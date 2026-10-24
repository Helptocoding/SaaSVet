# Evidencia r9 — candidato 1947726

[Reporte y límites](REPORT.md) · [Decisión](candidate-decision.json) ·
[Estado por bloque](block-status.json) · [Incidente](incident-classification.json) ·
[Índice de archivos](artifact-index.json) · [Inventario del paquete](preservation-manifest.json) ·
[Prueba de recuperación](preservation-verification.json) · [Verificación de entrega](delivery-verification.json).

El paquete conserva también logs originales y recibos dañados. Los hashes prueban
la conservación de esos bytes; no convierten JSON inválido en evidencia válida.
`artifact-index.json` enumera el núcleo antes del paquete; los recibos de entrega
son posteriores y se conservan como archivos Git independientes.

Para recuperar en una carpeta nueva, ejecutar desde este expediente:

```powershell
rtk proxy python -B restore_wsl.py --destination C:/ruta/nueva/recuperacion-r9
```

El comando comprueba SHA-256 de las partes, del ZIP y de cada miembro; rechaza
un destino no vacío. No inicia PostgreSQL ni pruebas. El empaquetador ejecuta
una recuperación interna y otra por el CLI real en destinos temporales distintos.

Solo se preparan los paths explícitos de `git-selection.json` en la rama original.
Se preservan los blobs previamente staged fuera de los tres archivos compartidos
de entrega. Los logs están dentro del ZIP sin normalización; no se agregan sueltos
al índice Git. No hay commit ni push.
