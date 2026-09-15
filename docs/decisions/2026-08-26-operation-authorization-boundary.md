# Frontera de autorización de operaciones conversacionales

> **Enmienda B2 (2026-09-15).** La restricción posterior al recibo se aplica
> a nuevas operaciones WRITE, que además siguen bloqueadas por B0. Las READ
> públicas, incluida disponibilidad, pueden ejecutarse sin un nuevo goal;
> las READ personales conservan identidad vigente y scope. `request_human`
> conserva su política de CONTROL. Consultar no reabre ni autoriza una
> operación. Esta enmienda sustituye únicamente el bloqueo indiscriminado
> de lecturas en los invariantes y ejemplos históricos de este documento.
> [Contrato B2](../contrato-resultados-tools-b2.md).

**Fecha:** 2026-08-26
**Estado:** sustituida en el mecanismo de autorización el 2026-08-27

> La frontera de capacidades y el recibo idempotente de esta decisión siguen
> vigentes. `begin_operation` ya no es el mecanismo de autorización: fue
> sustituido por la evaluación semántica de la ráfaga mediante autorizador y
> verificador independientes. Véase
> [`2026-08-27-semantic-turn-operation-authorization.md`](2026-08-27-semantic-turn-operation-authorization.md).

## Problema observado

Después de crear una cita y notificar el recibo automático, el agente recibió
un agradecimiento y abrió por iniciativa propia otro objetivo de agenda. El
modelo consultó disponibilidad, eligió 09:30 porque 09:00 ya estaba ocupado y
emitió una segunda confirmación. La cita original permanecía correcta; el fallo
fue que una interacción sin operación solicitada obtuvo capacidad de crear una
nueva propuesta.

El recibo ya entraba al contexto del modelo como un hecho y el prompt decía que
no debía repetirse. Eso evita el eco textual, pero no es una frontera de
autoridad: un modelo puede ignorar una instrucción y llamar una herramienta.

## Decisión

Un `operation_receipt` entregado cierra la capacidad de agenda que produjo. A
partir de ese hecho, una herramienta de agenda no puede abrir ni continuar una
operación por sí sola.

La secuencia es:

`mensaje del cliente → evaluación semántica doble → objetivo autorizado → tools acotadas → propuesta → confirmación → commit → recibo`

El planificador no crea, mueve, cancela, consulta disponibilidad ni redacta
una confirmación para iniciar otra operación. Dos roles estructurados analizan
la ráfaga actual antes de que el servidor abra un objetivo tipado; el
planificador no puede autoautorizarse.

No se inspeccionan palabras como "gracias", "sí" o "nos vemos" para decidir.
Esos textos son ejemplos de un turno sin autorización, no reglas del sistema.

## Invariantes

1. Un recibo entregado deja la conversación sin capacidad implícita de agenda.
2. Sin objetivo activo autorizado, no se exponen `create_appointment`, altas,
   cancelaciones, reagendas ni consultas de disponibilidad.
3. `run_tool` vuelve a validar la misma regla. Un catálogo viejo, un retry o
   una llamada errónea del modelo se registra como denegada y no puede crear un
   `pending_action`.
4. Cada objetivo abierto después de un recibo conserva
   `ConversationGoal.authorization_message`, el mensaje entrante causal.
5. Un objetivo solo habilita la herramienta que le corresponde y las lecturas
   de agenda necesarias para completarlo. Cambiar de operación exige una nueva
   evaluación doble de la ráfaga; no ocurre por una tool lateral.
6. El commit sigue emitiendo un único recibo idempotente por `operation_key`.

## Alcance y compatibilidad

La primera atención conserva el flujo ya probado: antes del primer recibo, el
objetivo de alta o agenda puede abrirse desde sus herramientas actuales. La
nueva frontera aplica desde el primer resultado irreversible comunicado al
cliente, que es el punto donde un objetivo anterior debe considerarse cerrado.

Los objetivos históricos quedan con `authorization_message = NULL`; no se
inventan causas para conversaciones pasadas. Las nuevas evaluaciones persisten
su evidencia ordenada y los objetivos autorizados las referencian.

## Observabilidad

- `TurnOperationAssessment` registra la evaluación y su evidencia; `LLMCall`
  registra ambos contratos. Cualquier intento legado de `begin_operation` se
  deniega con `policy_decision=denied`.
- `ConversationGoal.authorization_message` permite reconstruir qué mensaje del
  cliente abrió cada nueva operación posterior a un recibo.
- La respuesta al cliente sigue en manos del planner, pero una denegación no
  deja disponible una confirmación automática ni una escritura de dominio.

## Pruebas de aceptación

- Recibo previo + intento de agenda directo: catálogo sin tools de agenda,
  denegación en profundidad y ningún `pending_action`.
- Recibo previo + petición nueva: autorización y verificación semánticas abren
  el objetivo correcto, guardan la ráfaga causal y revelan únicamente sus
  tools.
- Un modelo de prueba que intenta `create_appointment` después de un recibo no
  puede emitir una confirmación.

Estas pruebas validan una frontera de capacidades, no una lista de frases. La
evaluación semántica doble cubre variantes libres de cortesía, consulta de
estado, despedida y petición auténtica de segunda cita.
