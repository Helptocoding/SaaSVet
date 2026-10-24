# WA-RPL-02 — Citas entrantes: webhook e ingesta

Entrega local del **21-10-2026**. **40 pruebas PostgreSQL únicas PASS**, en evidencia
compuesta: 21 nuevas y 19 regresiones afectadas. Drift y Django check PASS.
[Manifiesto verificable](manifest.json), [runner](run_checks.py), [verificador](verify.py).

## Comportamiento

El webhook firmado usa el `context.id` ya normalizado en ChannelEvent por B1.
`provider_reply_target` busca como máximo dos candidatos del mismo ID externo en
la clínica/cuenta receptora, cualquier dirección e historia oculta. Solo un destino
inequívoco pasa a la ingesta como Message. No convierte objetos a texto, trunca IDs
largos ni busca en otras cuentas para completar una cita.

La firma nueva `ingest_inbound_message(..., reply_to=None)` conserva llamadas previas.
El precheck dedup sigue antes del contacto/episodio. Bajo el lock de Conversation,
revalida clínica/contacto/cuenta con `resolve_reply_target(lock=True)`, conservando
el lock del destino hasta insertar. Un destino desaparecido o cambiado deja la
cita nula y conserva el entrante. Se admite historia de otros episodios del mismo
hilo, referencias entrantes/salientes, mensajes pendientes/fallidos/descartados y
media sin pipeline binario.

Solo un entrante nuevo con referencia declarada y sin FK emite
`INBOUND_REPLY_UNRESOLVED`. El evento contiene UUID de clínica/cuenta, PK del
entrante y motivo genérico. No contiene body, teléfono, nombre ni IDs del proveedor.
Redelivery no cambia la cita original, no hace backfill cuando el destino aparece
después y no repite el aviso. La relación FK no sustituye ni amplía las comprobaciones
del selector del agente sobre emisión, episodio y cursor; B1 conserva su autoridad.

## Evidencia y selección finita

- 20 casos nuevos de webhook/ingesta: firma, ambos sentidos, episodios, estados,
  media, historial oculto, destino ausente/ambiguo/malformado/largo, clínica/cuenta/
  persona ajenas, ID de evidencia original, servicio con destino cambiado,
  desaparición entre lookup/ingesta, redelivery sin reescritura ni backfill y batch.
- Una carrera nueva con dos POST firmados y conexiones PostgreSQL distintas.
  La barrera fuerza que ambas entregas pasen el precheck antes de persistir;
  el lock/unique permiten una fila con su cita y una sola llamada a persisted.
- 19 regresiones directamente afectadas: nueve de firma/routing/dedup/status,
  siete de evidencia B1/referencia sin autorización y tres de scope/historia RPL-01.
  No se repiten suites generales ni los ensayos de migración ya válidos.

`backend-directed` obtuvo 39 PASS y un error de fixture. El test de desaparición
usaba QuerySet.delete(), que el manager bloquea por diseño. Se cambió a borrado de
la instancia sintética, como los tests existentes; no se alteró esa protección ni
se rebajó la aserción. `backend-target-removal` repitió solo ese caso. Ambos recibos
y logs se conservan, con cleanup de las bases temporales acreditado.

El verificador reconstruye los IDs de la selección original, exige su último
veredicto PASS, comprueba cleanup/drift/diff y captura hashes finales. No se
sobrescriben recibos. No hubo fallo de producto, migración nueva ni cambio de
frontend que requiera recompilar o repetir sus tests.

## Pendientes y entorno

Los POST se ejecutaron en tests Django con HMAC sintético y PostgreSQL temporal.
Sin HTTP a Meta, worker/sender, LLM, commit, push, despliegue ni activación.
M2/M3 siguen sin aplicar a las bases habituales/preview. Recepción y Meta reales
siguen pospuestos y B9 mantiene el FAIL histórico de seguridad.

Siguiente: **WA-RPL-03**, envío con `reply_to_id` y cita en serializer. La cadena
API/composer/render/salto sigue pendiente; esta entrega acredita persistencia
entrante local, no replies end-to-end de recepción.
