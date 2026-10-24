# Garantías B2/WhatsApp y deuda BASE aceptada

Fecha del usuario: **22-10-2026**. Se registró su decisión de aceptar el p95 BASE
como deuda **no bloqueante**, sin modificar el recibo FAIL ni ejecutar B9 otra vez.
[Decisión](../../decisions/2026-10-22-b9-base-latency-accepted-debt.md).

La entrega principal es la
[lista de cierre y garantías](../../compliance/cierre-b2-whatsapp-2026-10-22.md).
Conserva **0/6 cierres completos** y separa avances locales de evidencia real.

## Resultado de la inspección

- La landing declara **Backblaze, Inc., Estados Unidos**, con usos distintos para
  backups y media operativa. No se encontró región técnica ni contrato aceptado
  en los documentos inspeccionados; los archivos `.env`/`.env.example` de landing
  no contienen nombres de claves B2/Backblaze/región. El `us-west-004` de un test
  está expresamente asociado a datos sintéticos y no prueba la ubicación real.
- Timestamp absoluto, autorización por clínica/plazo/estado, purga de versiones y
  reintentos están implementados. La comparación de **16 fuentes relevantes** con
  la evidencia de fase 3 no encontró diferencias; se conservan sus pruebas, sin
  ejecutarlas de nuevo. No acredita B2 real.
- Falta demostrar alerta recibida/atendida y recuperación de una purga fallida.
  Un WARNING estructurado no prueba ese circuito; el comando puede devolver 0
  pese al fallo y el backoff de una hora no cambia la frecuencia del cron diario.
- Restore necesita reaplicar revocaciones desde un registro independiente antes
  de servir archivos o reanudar descargas. Se añadió el gate al runbook general,
  pero no se presenta esa instrucción como simulacro ejecutado.
- Se documentaron spool, archivos locales, blobs/descargas del navegador, backups
  de DB, proveedor y originales Meta. El directorio local de media no existía.
  Se añadieron exclusiones de `private-media/` en Docker y del spool dedicado en
  Git/Docker para evitar incorporar copias privadas al repositorio o la imagen.

## Compilación de la landing

[Build completo](landing-build.json): **PASS, 18 páginas**, exit 0. Se copió el
frontend íntegro y sus dependencias instaladas a un runtime privado ignorado,
se aplicó únicamente el aviso preparado a esa copia y se ejecutó `astro build`
(el script `npm run build` original). No se instalaron/actualizaron dependencias.
El HTML contiene fecha, retención, eliminación, control de acceso y tipos de media.

El SHA del aviso original quedó igual. El repo LandingSaaS no se modificó;
no se publicó ni verificó por HTTPS una versión nueva y no se ejecutó seed legal.
La fecha propuesta del borrador sigue sujeta a la fecha efectiva de publicación.

## Evidencia y límites

[Inventario](source-inventory.json), [resumen](summary.json) y [sello](MANIFEST.json).
La evidencia de la campaña anterior y el expediente legal preparado permanecen
intactos. La guía vigente y las exclusiones son archivos vivos actualizados por
esta decisión; sus hashes nuevos no sustituyen los hashes históricos.

Las fuentes oficiales usadas para región, contrato y subencargados están
enlazadas en la lista de cierre. No se aceptó un DPA ni se eligió una región en
nombre del usuario. No hubo pruebas de proveedor, activación, publicaciones,
commits ni pushes. Las garantías pendientes no se dispensan por aceptar la
deuda de latencia.
