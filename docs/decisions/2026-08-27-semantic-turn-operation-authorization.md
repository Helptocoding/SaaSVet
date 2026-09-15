# Autorización semántica del turno posterior a un recibo

> **Enmienda B2 (2026-09-15).** READ y solicitud humana no dependen de que
> la evaluación semántica abra un nuevo objetivo después del recibo. El
> manifiesto/dispatch distingue acceso público, personal con vínculo vigente,
> WRITE contenido y CONTROL. La evaluación existente puede interpretar nuevas
> operaciones, pero no autoriza una mutación. Se levanta únicamente el bloqueo
> de READ señalado como pendiente por la enmienda B0; no cambian sus garantías
> de consentimiento ni se implementa B7/B8.
> [Contrato B2](../contrato-resultados-tools-b2.md).

> **Enmienda B0 (2026-09-13), vigente para esta release.** La evaluación semántica puede interpretar una intención y abrir un objetivo, pero no acredita consentimiento para modificar negocio. B0 contiene todos los WRITE, incluso tras evaluación accept o pendiente heredado. C2/B7 y cada adaptador B8 definirán la autoridad de la operación exacta; no se implementan aquí. Se mantiene por ahora la restricción de READ posterior al recibo, cuya modificación pertenece a B2.
> Alcance, pruebas, límites y rollback: [acta B0](../implementacion-b0-agente-whatsapp-2026-09-13.md). El resto del ADR conserva sus decisiones salvo esta contención temporal.

**Fecha:** 2026-08-27
**Estado:** aceptada e implementada
**Sustituye:** el mecanismo `begin_operation` de
[`2026-08-26-operation-authorization-boundary.md`](2026-08-26-operation-authorization-boundary.md)

## Contexto

Un recibo de operación cerraba correctamente la cita que lo produjo, pero el
planificador todavía podía declarar por sí solo que un mensaje posterior abría
una segunda operación. En producción, una reacción social al recibo abrió una
cita nueva, reutilizó mascota y hora que pertenecían a la operación cerrada y
presentó otra confirmación.

Que el prompt diga que no lo haga no es una frontera de autoridad. Tampoco lo
es una lista de expresiones como “gracias”: el cliente puede escribir una
cortesía en varios mensajes o volver a pedir una cita con lenguaje libre.

## Decisión

Después de un `operation_receipt`, mientras no haya un objetivo o confirmación
activos, el planificador no recibe capacidad para iniciar operaciones. El
orquestador evalúa la ráfaga entrante completa en dos pasos estructurados:

1. Un **autorizador** clasifica el turno como `conversational`, `operation` o
   `ambiguous`, con las únicas operaciones permitidas por la ruta de atención.
2. Si propuso una operación, un **verificador independiente** recibe la misma
   ráfaga y la operación propuesta; solo `accept` crea el objetivo tipado.

La secuencia vinculante es:

`ráfaga entrante → autorizador → verificador → objetivo nuevo → tools acotadas → propuesta → confirmación → commit → recibo`

`begin_operation` deja de formar parte del catálogo del modelo y `run_tool` lo
rechaza incluso ante una llamada atrasada o defectuosa. Ninguna de las dos
etapas recibe transcript previo, citas, mascotas, horarios, ni slots de una
operación terminada; el único dato evaluado es la ráfaga actual, enumerada en
orden de llegada.

El objetivo autorizado es nuevo. Sus valores se capturan en su propio estado;
un recibo anterior solo puede aparecer como el hecho compacto de que ya fue
notificado, nunca como autorización ni como datos para completar otra cita.

## Persistencia y auditoría

`TurnOperationAssessment` conserva para cada ráfaga:

- conversación y mensaje ancla idempotente;
- veredicto, operación propuesta y código de fallo;
- modelo y versión de prompt del autorizador y verificador;
- los `Message` fuente, con ordinal preservado.

Cuando una decisión es autorizada, `ConversationGoal.operation_assessment`
la referencia; `authorization_message` se conserva como vínculo compatible al
último mensaje causal. Las decisiones conversacionales, ambiguas, rechazadas o
no disponibles también se guardan para diagnóstico. `LLMCall` registra ambas
llamadas de modelo y los eventos `AGENT_OPERATION_ASSESSED` y
`AGENT_OPERATION_AUTHORIZED` permiten correlacionar el turno completo.

Una ejecución repetida para el mismo mensaje ancla retorna la evaluación ya
persistida y no abre otro objetivo.

## Fallo seguro

Un contrato inválido, timeout, error de proveedor, operación fuera de la ruta
permitida o veredicto ambiguo/rechazado no habilita tools de agenda y no crea
`pending_action`. El planificador puede responder de manera conversacional,
pero no puede improvisar una confirmación ni escribir agenda.

Esto no es un feature flag ni un filtro silencioso: es la frontera de capacidad
del orquestador. Las cortesías, despedidas, reacciones, consultas de estado y
solicitudes reales se distinguen por evaluación semántica sobre el turno
completo, no por texto coincidente.

## Casos de aceptación

- Un mensaje social posterior al recibo permanece conversacional y no expone
  agenda.
- Una cortesía partida en varios mensajes se evalúa como una única ráfaga y no
  abre objetivo ni confirmación.
- Una petición libre y auténtica de nueva operación debe ser aceptada dos veces
  y abrir solamente el objetivo compatible con su ruta.
- Si el autorizador se equivoca y propone agenda para un mensaje social, el
  verificador la rechaza y el estado sigue sin operación activa.
- Una repetición del worker no duplica evaluación, objetivo ni recibo.
