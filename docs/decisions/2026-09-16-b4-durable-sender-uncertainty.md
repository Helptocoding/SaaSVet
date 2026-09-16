# ADR — B4: claim de Message y evidencia externa incierta

Fecha: 2026-09-16. Base `5ae6077`. Decisión implementada; activación pendiente.
Complementa el [ADR B3](2026-09-15-b3-durable-turn-ownership-publication.md)
en su frontera de envío, sin modificar procesamiento/publicación local.

## Decisión

Reutilizar Message como único outbox. Claim por fila con UUID y lease durable;
admisión bajo Conversation→Message, HTTP fuera de transacción y finalización CAS
por token del intento. `send_admitted_at` separa claim de inicio lógico externo:
permite distinguir crash preadmisión y garantiza consumo local de un solo uso.
El commit de admisión no es confirmación de socket ni aceptación de Meta.

Ownership vigente es necesario para nueva admisión. Registrar el resultado de
un HTTP ya admitido después de takeover **no ejerce autoridad conversacional**.
Se conserva el token al invalidar ownership; solo SENDING sin admisión se descarta.
Un HTTP en vuelo puede terminar después de takeover y la evidencia debe reflejarlo.

SENT exige ID válido; timeout, 5xx y respuesta 2xx sin evidencia son UNCERTAIN.
Expiración de SENDING nunca autoriza otro HTTP. Solo rechazo explícito temporal
de rate limit recibe retry acotado con backoff. Status usa una función central,
locks y correlación tenant/cuenta/ID; no inventar correlación del wamid perdido.

La reemisión manual conserva original y crea otro Message humano enlazado. Inbox
muestra evidencia de incertidumbre, aceptación, entrega y lectura separadamente.
El sender se ejecuta separado del planner mediante el management command actual.

## Consecuencias

- Migración aditiva 0013; no backfill sintético ni borrado de estados históricos.
- Cutover controlado con pausa/inspección del sender viejo; no rolling mixto.
- Rollback operativo pausa sender y conserva datos; nunca vuelve incertidumbre
  a pending ni borra tokens/IDs/fechas.
- Puede quedar incertidumbre manual permanente. Sin garantía de entrega única.
- No se habilitan business WRITE ni protocolos/ownership de B5/B8.

Contrato completo, clasificación y límites: [B4](../contrato-sender-durable-b4.md).
Evidencia de aceptación: [acta B4](../implementacion-b4-agente-whatsapp-2026-09-16.md).
