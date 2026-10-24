# B9E — continuación del 12-10-2026: preparación pendiente

**PENDING de preparación por margen de disco insuficiente.** La instrucción
«prosige» autorizó continuar el plan del candidato
`194772677ca4e9fe1a1dec7f4dafa48396a6c583`. Se comprobaron recursos y
alternativas antes de reinstalar dependencias o iniciar otra ejecución formal.
**No se ejecutaron pruebas, PROFILE ni instalaciones en esta continuación.**

Las consultas de solo lectura mostraron un único volumen fijo, C:, y espacio
libre decreciente:

| Consulta | Bytes libres | GiB aproximados |
| --- | ---: | ---: |
| Windows, consulta inicial | 1.970.233.344 | 1,83 |
| Inventario de volúmenes Windows | 1.252.372.480 | 1,17 |
| Consulta posterior de WSL sobre `/mnt/c` | 1.090.555.904 | 1,02 |

El mínimo original es **1.073.741.824 bytes (1 GiB)**. La última consulta
deja solo **16.814.080 bytes, unos 16 MiB**, por encima de ese mínimo.
El ensamblaje anterior declara un presupuesto de preparación de 1 GiB;
el espacio disponible no permite consumir ese presupuesto conservando
la reserva. No se rebaja el guard de disco ni se inicia una campaña destinada
a perder ese margen al preparar el entorno.

WSL confirmó aproximadamente **949 GiB libres dentro de su disco virtual**,
pero el límite que vigila el plan es el espacio real de C:. Su directorio
`/home/lap` no mostró workspaces residuales `b9i-wsl-*`.
La consulta de WSL y otras lecturas locales tardaron en devolver resultado;
no se ha determinado la causa de esa lentitud.

Windows informó un archivo de paginación de **5.356 MiB** asignados,
**444 MiB** en uso y **1.368 MiB** de pico. Esa observación no demuestra
que la paginación causara la caída de espacio de r8 ni la de esta continuación.
No se modificó paginación, hibernación, políticas de energía, W32Time ni
configuración de WSL. No se borraron archivos del usuario, caches compartidas
ni evidencia histórica.

La preparación queda pendiente hasta disponer de más espacio real en C: o
de otro volumen apto para alojar el entorno aislado y su evidencia. Conviene
liberar varios GiB adicionales para dejar margen a preparación y fluctuaciones;
el umbral contractual continúa siendo 1 GiB durante toda la ejecución.
Después deben volver a comprobarse recursos, reloj, fuentes y solicitud
temporal de actividad antes de ejecutar el mismo alcance.

La [campaña r8](../b9-integral-acceptance-1947726-wsl-20261011-r8/REPORT.md)
permanece cerrada y conservada: 53/87 registros `ok`, bloque incompleto,
PENDING por disco, cleanup y recuperación PASS. Esta continuación no cambia
sus recibos ni transfiere sus resultados a otra campaña. No hubo commits,
push, despliegue ni activación.

`diagnostics/probe_environment.py` contiene únicamente consultas de lectura
y captura de resultados. Las mediciones anteriores se obtuvieron también por
consultas individuales; el recibo agregado, si termina de producirse, queda
en `environment-readiness.json`. Este reporte no afirma que ese recibo
agregado haya terminado ni que exista un sello evaluativo o preflight formal.
