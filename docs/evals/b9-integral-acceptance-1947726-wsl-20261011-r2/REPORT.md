# B9E — aceptación de 1947726 en WSL2, campaña autorizada r2

**Decisión técnica integral: PENDING.** El preflight pasó y comenzó una única
ejecución formal del corpus dirigido. Se interrumpió durante las migraciones de
su base de pruebas por una discontinuidad del reloj. No hay IDs completados,
recibo final de suite ni variantes PROFILE ejecutadas. No se atribuye un fallo al producto.

Candidato: `194772677ca4e9fe1a1dec7f4dafa48396a6c583`. Autorización: «procede»,
después de explicar la necesidad de una campaña nueva con el bootstrap corregido.
Expediente independiente de las dos campañas previas, que permanecen preservadas.
La ejecución comenzó a las **00:32:17 UTC del 12-10-2026**, todavía 11-10 en México.
Fuentes de la decisión: [incidente](incident-classification.json),
[parada durable](STOP.json), [monitor original](monitor-directed.json) y
[recibo del bloque](blocks/directed.command.json).

## Preflight y ensamblaje

- Los 3.332 archivos exportados coinciden con los blobs del candidato.
- Python 3.13.2 y dependencias de `requirements.lock`; `pip check` satisfactorio.
- Node 20.20.2 y pnpm 9.15.9; instalación con `--frozen-lockfile` satisfactoria en Linux.
- PostgreSQL 16.15 local privado, puerto 35479, durabilidad habilitada.
- Discovery sin IDs ausentes, duplicados ni errores: dirigido 87, completo 3.331,
  B0 17, B3 42, B4 68 y B5 37. Son selecciones, no pruebas aprobadas.
- Gitleaks 8.18.4 y clon independiente con historial completo preparados; scan no ejecutado.
- Bootstrap corregido validado antes del sello: Django y los cinco runners resuelven
  correctamente. No se repitió el fallo de SECRET_KEY de la campaña anterior.
- Las tres fuentes del PROFILE son idénticas a las del candidato histórico 0831046.
  Cargas, tiempos, fixtures, proveedores y gates permanecen originales.

El [preflight](preflight.json) dejó constancia de recursos suficientes y PASS:
aproximadamente 5,91 GiB disponibles en Windows, 7,08 GiB en Linux y 4,35 GiB
reales de disco de respaldo. Se mantuvieron 3 GiB por suite, 2 GiB de reserva
física y 1 GiB de disco. Las fluctuaciones previas de RAM se resolvieron antes
de iniciar. El [sello](evaluation-seal.json) cubre 70 archivos evaluativos,
configuraciones y ejecutables; el manifiesto adicional cubre las 3.332 fuentes.
Los diffs y hashes del ensamblaje están en `adapter-lineage.json` y `receipt-adapter.diff`.

## Incidente y ejecuciones

El monitor tomó 27 muestras. A los **45,196 segundos monotónicos** observó una
desviación acumulada civil−monotónico de **+1,723597891 segundos**, superando
el límite congelado de 1 segundo del controlador. La muestra anterior registraba
+0,846841426 segundos. Esta evidencia identifica la discrepancia; su causa
sistémica concreta no está determinada. No se alteraron W32Time ni el reloj del host.

El controlador terminó únicamente su grupo de procesos propio con SIGTERM
(exit −15) y escribió PENDING/parada. Las migraciones internas de preparación
de la base estaban en curso. El journal de IDs completados está vacío y falta
el recibo final de la suite: **ninguna prueba se acredita como PASS o FAIL**.
No se reintentó el bloque ni se modificaron fuentes, fixtures, tiempos o gates.

La RAM mínima observada durante el bloque fue 3,72 GiB en Windows y 6,94 GiB
en Linux; el disco real mínimo fue 4,32 GiB. Ninguna reserva de 2 GiB de RAM
o 1 GiB de disco se agotó. La causa de la parada fue el reloj.

| Bloque | Estado |
| --- | --- |
| Corpus dirigido, 87 IDs | PENDING; una ejecución interrumpida antes de completar IDs |
| Checks Django, drift, migrate y Billing | NOT_EXECUTED |
| B0/B3/B4/B5 y suite completa | NOT_EXECUTED |
| Build, Vitest, lint y smoke frontend | NOT_EXECUTED |
| Gitleaks y auditorías advisory | NOT_EXECUTED |
| BASE, BLOCKED_LLM, META_SLOW, DUPLICATE, SATURATION | NOT_EXECUTED |

Instalar dependencias, descubrir IDs o aplicar parcialmente migraciones para crear
la base de tests no sustituye ninguno de los gates pendientes. No se realizaron
nuevos intentos físicos D29/R1-04 ni llamadas a proveedores reales.

## Conservación y cierre

Integridad posterior al bloque y al cierre: **3.332 fuentes sin diferencias**.
Los **70 archivos del sello** también permanecieron intactos después del incidente.
Se guardaron observaciones SQL y listas de tablas antes de retirar las dos bases
propias. No había conexiones ajenas ni transacciones preparadas. PostgreSQL se
detuvo, el puerto quedó cerrado y se retiró exclusivamente
`/home/lap/b9i-wsl-1947726-20261011-r2`; [cleanup](cleanup.json): PASS.

`preservation-of-prior-work.json` registra la comparación de ambas campañas
anteriores y los tres cambios ajenos del checkout. La evidencia dispone de
inventario propio, hashes, paquete y restaurador; los resultados de recuperación
están en `preservation-verification.json`. Los logs conservan sus bytes originales
dentro del paquete. La selección Git es explícita y permanece en la misma rama.
No se crearon commits ni se hizo push, despliegue o activación.

R01–R15 e I01–I14 conservan los pendientes que no se llegaron a verificar;
ver `candidate-decision.json`. R1-04 sigue PENDING con limitación aceptada,
la activación sigue PENDING_ACTIVATION_REQUIREMENTS y E/P/UX siguen separados.
La campaña queda cerrada conforme a la regla de parada. Antes de otra ejecución
habría que investigar la discrepancia temporal y tomar una decisión nueva;
este expediente y sus recibos no se sobrescriben.
