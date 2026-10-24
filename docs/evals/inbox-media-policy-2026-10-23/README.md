# Retención y cierre Inbox — 23-10-2026

**PASS local**; decisión de parámetros registrada. Operación real no certificada.

Implementado: reloj PostgreSQL compartido, bloqueo por vencimiento/revocación,
verificación posterior de todas las versiones/markers, incidentes persistentes,
umbrales 24h/7d, reintentos diarios y resultados operativos visibles. Ledger
independiente del dump, hold de acceso y reconciliación sin reabrir tráfico.
Trabajos recuperados sin persistencia acreditada se congelan.

Validación: `summary.json` y `test-cases.json` recogen las ejecuciones dirigidas.
La primera conservó 45 PASS y un error por mock de reporte antiguo; se corrigió
ese mock y se repitió ese caso junto con los controles afectados por los ajustes
finales. No se repitieron los otros PASS, B9 ni suites completas.
`restore-drill.json` acredita pg_dump/pg_restore de
una DB desechable con referencias antiguas; ledger sobreviviente, acceso
revocado/expirado bloqueado, timestamps conservados y jobs cancelados. Los
binarios fueron sintéticos en almacenamiento privado local: **no es una prueba
de B2**, su volumen/custodia, clocks operativos, cron o inventario de réplicas.

El aviso nuevo compila en las **18 páginas** de la landing de revisión. El repo
original conserva su hash. No hubo publicación, seed legal ni activación.
0018 se aplicó solo a la base de desarrollo habitual tras dump privado verificado;
recibos migration-local*.json. Preview/producción sin tocar.

Responsable y canal de alertas pendientes **no bloqueantes**, por excepción
expresa del usuario. Los recibos HTTP simulados no prueban atención humana.
La plantilla observa umbrales cada 15min: no promete entrega exacta a las 24h.
Persisten pendientes B2 real/región/contrato, capacidad y operación del cron,
inventario de objetos posteriores al dump, publicación/seed/reaceptación y
Meta/recepción a cargo del usuario. La activación requiere sus gates y autorización.

Los manifiestos anteriores conservan sus recibos; fuentes vivas modificadas
por esta decisión se sellan aquí. `runtime/` y ledger se excluyen de Git/Docker.
MANIFEST.json registra los hashes de fuentes, documentos y recibos de esta entrega.
