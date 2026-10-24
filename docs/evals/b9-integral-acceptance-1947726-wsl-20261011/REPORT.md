# B9E — resultado de la campaña WSL2 de 1947726

Fecha: 2026-10-11. Decisión técnica integral: **PENDING**.
Candidato: `194772677ca4e9fe1a1dec7f4dafa48396a6c583`. Campaña: `b9-integral-acceptance-1947726-wsl-20261011`.

## Resultado y causa

La alternativa Linux permitió completar `pnpm install --frozen-lockfile` con Node
20.20.2 y pnpm 9.15.9, sin EPERM ni cambios al lockfile. Se verificaron los 3.332
blobs Git del candidato, se instalaron las dependencias bloqueadas con Python
3.13.2 y se preparó PostgreSQL 16.15 privado y durable en el puerto 35479.

El controlador preparado por el agente omitió cargar su entorno de prueba antes
de importar Django al validar el adapter. Falló con
`UndefinedValueError: SECRET_KEY not found. Declare it as envvar or define a default value.`
Es un error del lanzador evaluativo, no evidencia de un defecto del producto.
Ocurrió antes de crear el sello, completar el preflight o iniciar el bloque 1.
`STOP.json` se conserva; no se borró la parada ni se reintentó la campaña.

`run_campaign.py` conserva los bytes usados. La corrección está separada en
`launch_campaign.py`: carga el entorno aislado antes del import. Su validación
de configuración y resolución de cinco runners pasó sin ejecutar tests. El
camino completo de ejecución sigue sin validación de extremo a extremo.

## Preparación acreditada

- Exportación Git exacta con LF, SHA-1 de blobs y SHA-256 por archivo: 3.332/3.332.
- Discovery sin ejecución: 87 IDs dirigidos y 3.331 de suite completa; B0=17,
  B3=42, B4=68 y B5=37. Cero IDs ausentes, errores de import o duplicados.
- Python 3.13.2; instalación del lock y `pip check` satisfactorios.
- Node 20.20.2/pnpm 9.15.9; instalación congelada satisfactoria en Linux en 19,63 s.
- PostgreSQL 16.15: fsync, synchronous_commit y full_page_writes en `on`.
  Solo se creó `test_b9i_control`, sin tablas de aplicación ni fixtures clínicos.
- PROFILE: las tres fuentes base son idénticas a 0831046. Se conservaron los
  cinco escenarios, 30/300/20 s, los gates de SATURATION y las dos llamadas LLM READ.
- Gitleaks 8.18.4 y clon independiente con historial completo preparados;
  **scan no ejecutado**. Auditorías advisory preparadas, **no ejecutadas**.

La consulta inicial a `Packages.xz` devolvió 404. Durante la preparación se
comprobó el índice oficial y se usó el `Packages.gz` publicado, conservando el
incidente y su resolución. No se cambió una dependencia, lock, fixture o gate
del candidato para resolverlo. La adaptación de recibos está en archivos separados.

## Ejecuciones y recursos

**Cero tests de aplicación, cero bloques formales y cero variantes PROFILE.**
Build, Vitest, smoke, checks Django/migraciones/Billing, corpus, regresiones,
seguridad y auditorías están NOT_EXECUTED; instalar dependencias no los sustituye.
No se ejecutaron escenarios físicos D29/R1-04 ni llamadas reales de proveedores.

El presupuesto conserva 3 GiB por suite, 2 GiB de reserva física y 1 GiB de
reserva en el disco Windows que respalda WSL. El espacio virtual ext4 no se
confundió con el espacio real disponible del host. Al cierre se observaron
2.46 GiB libres de RAM en Windows y
4.39 GiB libres en el disco de respaldo. El fallo
del bootstrap impidió llegar al gate formal de recursos. Estos datos no acreditan
un preflight completo ni autorizan iniciar suites sin verificar otra vez el margen.

## Conservación y cierre

Integridad final: 3.332 archivos intactos. Se guardaron las observaciones SQL
antes de eliminar la única base propia; no había conexiones ajenas ni transacciones
preparadas. PostgreSQL se detuvo, el puerto quedó cerrado y se retiró la carpeta
propia `/home/lap/b9i-wsl-1947726-20261011`. Se conservaron los entornos Windows reutilizados y procesos ajenos.

Los 70 archivos comprobados de la campaña Windows previa permanecen byte por byte
sin cambios. También se conservaron las dos eliminaciones ajenas y `skills-lock.json`.
Se entrega inventario propio, paquete y recuperación comprobada; la selección Git
es explícita. No se crearon commits ni se hizo push, despliegue o activación.

R01–R15/I01–I14: ver `candidate-decision.json`; los requisitos pendientes no se
consideran cubiertos por la preparación. R1-04 mantiene PENDING con limitación
aceptada; activación conserva PENDING_ACTIVATION_REQUIREMENTS; E/P/UX siguen separados.

Una nueva ejecución requiere una decisión nueva conforme al límite del plan,
empleando el bootstrap corregido, un expediente nuevo y preflight íntegro. Esta
campaña detenida no se sobrescribe ni se presenta como una campaña aprobada.
