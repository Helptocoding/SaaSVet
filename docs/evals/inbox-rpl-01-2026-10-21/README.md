# WA-RPL-01 — Modelo de respuestas citadas

Entrega local del **21-10-2026**, limitada al modelo, validación compartida y M2.
Resultado: **19 pruebas PostgreSQL únicas PASS** (14 nuevas y cinco de transporte
afectadas), drift/Django check PASS. [Manifiesto verificable](manifest.json).

## Implementación

- Message añade `reply_to` nullable/blank, FK a sí mismo, `on_delete=PROTECT`,
  reverse `direct_replies`. Un índice explícito `message_reply_target` evita
  duplicar el índice automático (`db_index=False`).
- `channels.replies.resolve_reply_target` resuelve solo la misma clínica,
  contacto y cuenta. Message.clean lo aplica al save normal. Permite episodios
  distintos del mismo hilo e historia oculta/descartada. El error del campo
  `reply_to` tiene código `invalid_reply_target`, sin cuerpo ni datos personales.
- M2, `0016_message_reply_to`, generada con Django: AddField + AddIndex, columna
  nullable sin default ni backfill. [SQL generado](migration-initial.sql).

## Verificación

[Runner](run_checks.py), recibos `generate-initial.json`, `backend-new.json`,
`backend-compat.json` y `drift-final.json`, con sus logs preservados. El verificador
`rtk proxy python -X utf8 docs/evals/inbox-rpl-01-2026-10-21/verify.py` comprueba
IDs/veredictos, SQL aditivo, cleanup, diff check y hashes del código/documentación.
No sobrescribe el manifiesto ni los recibos.

Las 13 pruebas nuevas del modelo cubren null, ambos sentidos de mensaje, relación
inversa, PROTECT, episodios distintos, historia oculta/descartada, clínica/cuenta/
contacto ajenos, target inexistente/malformado, scope desconocido y esquema real
con una sola FK y un solo índice de cita. Una prueba demuestra que la self-FK
solo comprueba existencia: un cruce mediante bypass cabe en la DB, mientras el
servicio/save normal lo rechazan. La escritura inválida se revierte dentro del test.
Otra prueba fuerza la comprobación de FK y rechaza un destino inexistente en DB.

El ensayo M2 (una prueba nueva) baja al estado channels.0015 únicamente en la base
temporal. Crea siete mensajes históricos con distintos estados, aplica M2 y compara
**todas** sus columnas previas, incluidos IDs, timestamps y metadata. Todos quedan
sin cita. Escribe con el modelo antiguo sobre el nuevo esquema y comprueba lectura
de un mensaje nuevo desde el modelo antiguo. Restaura el grafo al terminar.

Se conservan los 19 PASS iniciales. Se repitió solo el ensayo M2 con el prefijo
`test_channels_compat_`, tras generalizar su guard a `test_` como los ensayos
existentes, para que funcione también en el test runner habitual de CI.
No hubo fallos de producto ni cambios de umbrales. Ambos recibos acreditan borrado
de la base temporal; no se migraron ni alteraron la base habitual o la preview.

## Alcance pendiente

M2 permanece sin aplicar a las bases habituales y de demostración. Se acredita
compatibilidad local; la aplicación sin interrupción durante una release real
sigue sin validar. La estrategia de rollback del plan conserva columnas y revierte
el código; no se eliminan las citas de una base con datos reales.

Webhook/ingesta corresponde a **WA-RPL-02**. API/serializer/composer/citas/salto
continúan en RPL-03..07; esta entrega no acredita replies end-to-end. No hubo cambio
de frontend que requiera recompilarlo o repetir su suite. Sin commit, push,
despliegue ni activación. Recepción y Meta siguen pospuestos y B9 conserva su
FAIL histórico de seguridad.
