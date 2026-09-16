# ADR — B3: TurnWork, ownership y publicación atómica local

Fecha: 2026-09-15. Estado: aceptada para el corte técnico B3; activación pendiente.
Base: `a06b4f7`. Contrato normativo: [B3](../contrato-trabajo-durable-b3.md).

## Problema

PROCESSED-at-claim perdía trabajo ante crash. El lease de Conversation no
representaba miembros/cursor recuperables ni cercaba a un worker viejo; goal y
respuesta podían persistirse separados. Un takeover no invalidaba causalmente
los pendientes del bot.

## Decisión

Crear solo TurnWork como trabajo operativo, con membership mediante FK Message,
identidad conversation+anchor y máximo un trabajo no terminal por conversación
impuesto en PostgreSQL. Guardar cursor/reloj B1 y reconstruir TurnContext desde
miembros fijos. Conceder un único lease_token UUID con expiración DB; recuperar
el mismo trabajo con token nuevo e intentos limitados.

OwnershipWitness vive en memoria. Captura scope, trabajo, token y epoch monotónico
de Conversation. Validación vigente, locks Conversation→TurnWork→Message y CAS
protegen efectos locales. Takeover/release/reset comparten invalidación de epoch.

Planificar fuera de transacción y consolidar cambios locales/diagnóstico, final
PENDING correlacionado y completion en una sola transacción corta. Ordinales
deterministas y unicidad parcial impiden duplicar publicación local. No hay
borradores persistidos ni tablas auxiliares de leases, membresía o jobs.

Input posterior conserva los miembros originales y concluye W1 como deferred;
se procesa en el siguiente trabajo. Sender actual añade chequeo epoch/scope y
descarta legacy ambiguo como legacy_unverified; no se le exige lifecycle B4.

## Consecuencias y frontera

- Se requieren tres migraciones aditivas y cutover con pausa/drenado; workers
  antiguos y nuevos no pueden coexistir porque el claim antiguo ignora TurnWork.
- Rollback operativo conserva trabajo, epochs, correlaciones y FAILED. No es
  rollback de esquema ni downgrade a un lector que ignore B3.
- Cambios locales en memoria reservan IDs de secuencia sin insertar drafts.
- Deferred conservador también alcanza cortesías; B6 resolverá su semántica.
- B0 WRITE permanece cerrado y TurnDecision/ToolExecution son diagnósticos.
- **B3 garantiza autoridad y publicación local durable. B4 resolverá la
  frontera de dispatch externo y resultados inciertos.** No hay garantía de
  entrega exactamente una vez ni cancelación de un HTTP ya admitido.

Alternativas descartadas: mantener PROCESSED-at-claim; dos autoridades de lease;
tabla genérica de jobs; snapshot/membership duplicados; transacción larga del
planner; incorporar sender durable/B4 en este cambio.

Evidencia y comandos: [acta B3](../implementacion-b3-agente-whatsapp-2026-09-15.md).

## Enmienda B4 — 2026-09-16

La frontera que este ADR dejaba pendiente al cerrar B3 está implementada por
[B4](2026-09-16-b4-durable-sender-uncertainty.md). Prevalece sobre las frases
anteriores en futuro relativas exclusivamente al sender: Message se reclama
individualmente, HTTP ocurre fuera de transacción y la duda queda UNCERTAIN.
Ownership sigue autorizando nuevos efectos/publicación/admisión. Registrar
evidencia de un request ya admitido después de takeover es una excepción
deliberada al fencing de nuevas mutaciones, sin autoridad nueva del bot.
TurnWork, witness y publicación local B3 conservan su contrato. No ledger B8.
