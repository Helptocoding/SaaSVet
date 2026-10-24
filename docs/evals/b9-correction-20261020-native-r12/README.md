# Conservación B9 r12

[Reporte](REPORT.md) · [Decisión](candidate-decision.json) · [Bloques](block-status.json) ·
[Índice](artifact-index.json) · [Manifest](preservation-manifest.json) ·
[Recuperación](preservation-verification.json) · [Entrega](delivery-verification.json).

El intento r10 de cero casos se preserva bajo referenced-selector-evidence/r10/,
con su manifest y la decisión de reparar solo el selector; no aporta PASS ni skips de aceptación.
El paquete contiene la referencia completa de r9 bajo referenced-completed-evidence/r9/,
con sus referencias anidadas y los fallos/timeout originales. No son ejecuciones r12.
El prefijo r11 está bajo referenced-prefix-evidence/r11/; conserva frontend 355 PASS
(354 r9 y uno r11), smoke PASS y lint advisory. Su seguridad quedó PENDING antes
del scanner, sin hallazgos atribuidos, y se exige una ejecución actual completa.
El resultado frontend lógico conserva 355 PASS sin casos nuevos en r12;
el exit del ensamblador no representa un exit 0 de la ejecución Vitest original.
La limitación histórica de disco/reloj r6 permanece explícitamente aceptada.

Recuperar en una carpeta ausente o vacía:

```powershell
rtk proxy python -B restore_native.py --destination C:/ruta/nueva/b9-recuperado
```

Se verifican SHA-256 de partes, archivo y miembros, con restauración interna y por CLI.
No inicia pruebas ni PostgreSQL. Los seis archivos de tests corregidos y la evidencia
staged se comprueban contra el candidato evaluado. Los logs se archivan sin normalización
Git. Sin commit ni push.
