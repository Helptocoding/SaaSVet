# WA-RPL-03 — Envío API y proyección de citas

Entrega local del **21-10-2026**. **42 pruebas PostgreSQL únicas PASS**:
25 nuevas y 17 regresiones afectadas. Sin fallos ni repeticiones de estos casos.
Drift/Django check y diff check PASS. [Manifiesto](manifest.json),
[runner](run_checks.py), [verificador](verify.py).

## Contrato entregado

POST send acepta `reply_to_id` opcional, entero positivo de 64 bits. El recurso
se resuelve con RBAC/tenant y luego se conserva el replay por key, antes de validar
un nuevo envío. Para una intención nueva, valida clínica/contacto/cuenta del
destino bajo el lock de Conversation y el del destino, antes de takeover/outbox.
Destino inválido: 400 `invalid_reply_target` sin efectos. Recurso ajeno: 404 incluso
con key previa. Los errores de forma usan la validación DRF existente.

La cita es null o `{id, author_type, human_author_name, payload_type, excerpt,
status}`. Un nivel y como máximo 80 caracteres, también vacío/media. Se admiten
otros episodios del mismo hilo y destinos ocultos/fallidos/descartados. La proyección
falla a null ante una FK legada de otro hilo/clínica; un autor ajeno no expone nombre.
Releer el POST tras commit refleja el estado real si el takeover descartó su destino.

Replay mantiene cuerpo/FK originales aunque el request cambie target o la sesión
se haya cerrado. Retry mantiene FK, cuerpo, autor y clave originales. Transcript
reciente, before, around, episodio legado, delta y respuestas cargan la relación
y su autor con select_related, sin una consulta por fila.

El fingerprint incluye la proyección citada. Cambios de excerpt/status/autor
actualizan al mensaje que cita sin escribir en él, incluso si el destino está fuera
del rango cargado. Una edición posterior al carácter 80 no modifica la proyección
del padre. El delta estable continúa sin transferir cuerpos.

## Verificación dirigida

- 24 casos API/proyección nuevos y una carrera real de dos conexiones: misma key
  y distintos targets → una sola fila y ambas respuestas con la cita original.
- Serializer de muchas citas/autores: una consulta. Consultas del endpoint no
  crecen al añadir 20 citas. before/around/legado conservan la misma proyección.
- Casos de scope/permisos, límites Unicode, media/estado vacío, target descartado
  por takeover, claves/replay tras cierre, retry, profundidad y FK legada mal formada.
- Casos de delta estable, target fuera de las últimas 50, rename/status sin write
  del padre y edición fuera del excerpt sin transferencia innecesaria.
- 17 regresiones afectadas: envío, idempotencia/integridad/cierre, transcript,
  delta/scrollback/cache sin PII/cuerpos y retry. No se ejecutó suite general B9.

`backend-new` y `backend-affected` son ejecuciones separadas con cleanup acreditado.
Los resultados se suman por ID, sin duplicarlos. No hubo cambio de producto entre
ellas. `verify.py` exige los 42 veredictos, drift y cleanup, comprueba diff y conserva
hashes finales. No sobrescribe recibos.

La [prueba EXPLAIN](query-plan-affected.json), repetida porque cambió el SELECT de
fingerprints, conservó el índice `channels_me_organiz_c00b67_idx` sobre 6.001 mensajes
con 50 cargados. Consulta medida: 1,49 ms; full 52.804 bytes, delta estable 303 bytes;
13 consultas de dominio en ese fixture con autenticación forzada. Dato local
sintético, no medición de capacidad comercial ni prueba Meta.

## Límites y siguiente paso

Sin nueva migración ni cambios frontend. M2/M3 siguen sin aplicar a bases
habitual/preview; los tests usan bases temporales. Sin commit, push, despliegue,
activación ni HTTP real a Meta. Recepción/Meta reales siguen pospuestos; B9 conserva
su FAIL histórico de seguridad.

Se confirmó en código que `sender.dispatch_claim` llama `send_text(to, body)` y
`MetaWhatsAppProvider.send_text` no construye contexto de cita. Conectar la cita
nativa al payload del proveedor es **implementación pendiente**, registrada como
prerrequisito de RPL-07; no se confunde con la validación real aplazada ni se afirma
resuelta por este roundtrip API. Los guards B4 permanecen bajo su contrato actual.

Siguiente: **WA-RPL-05** composer; después RPL-06 salto y RPL-04 burbujas según las
dependencias del plan. La cadena replies todavía no está acreditada end-to-end.
