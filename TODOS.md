# TODOS

Trabajo identificado y diferido conscientemente durante revisiones. No es un
backlog general — cada entrada tiene contexto suficiente para retomarse sin
tener que reconstruir el razonamiento desde cero.

---

## `unlink_family` debería suprimir el auto-rematch igual que `reset_contact_identity`

**Qué**: aplicar `auto_rematch_blocked=True` también en
`agent/views.py::unlink_family` (líneas 203-227), no solo en
`reset_contact_identity`.

**Por qué**: `unlink_family` deja al contacto en el mismo estado
(`owner=None`, `verification_level=unknown`) que `reset_contact_identity`.
Ambos son vulnerables al mismo mecanismo: `_rematch_owner`
(`agent/services.py`) re-vincula automáticamente cualquier contacto con
`owner_id IS NULL` y `verification_level == unknown` si su teléfono coincide
con exactamente un `Owner.phone`.

**Contexto**: descubierto en la auditoría completa de "todos los caminos que
asignan una identidad confiable" durante la revisión eng del plan
`docs/whatsapp-agent-identity-context-fixes-plan.md` (2026-08-07). El caso
real es más raro que el de `reset_contact_identity`: requiere que el
teléfono **propio** de un contacto secundario (vinculado antes por
`family_challenge`) coincida por casualidad con un `Owner.phone`
**distinto** al titular del que se desvinculó. Se decidió dejarlo fuera del
plan original porque no era uno de los 3 items reportados y el caso es de
menor probabilidad.

**Pros de hacerlo**: cierra la última vía conocida del mismo bug de
raíz; consistencia — mismo estado de datos, mismo comportamiento esperado
en los dos endpoints que lo producen.

**Contras**: superficie adicional a testear; el caso real que protege es
poco frecuente, así que el ROI inmediato es menor que el de
`reset_contact_identity`.

**Depende de**: que el campo `ContactIdentity.auto_rematch_blocked` (Item 1
del plan referido) ya exista — es un `contact.auto_rematch_blocked = True`
más en el `save()` que `unlink_family` ya hace, no una migración nueva.

**Cuándo retomarlo**: junto con o inmediatamente después de implementar
Item 1 del plan referido arriba, mientras el contexto de `auto_rematch_blocked`
sigue fresco.

---

## Investigar por qué el agente re-pregunta datos de identidad ya dados

**Qué**: entender la causa raíz real de que el agente vuelva a pedir
nombre/mascota/últimos-4-dígitos que el cliente ya dio en la misma
conversación (visto en un transcript real de producción, 06-ago-2026).

**Por qué**: el plan original (Item 3 de
`docs/whatsapp-agent-identity-context-fixes-plan.md`) proponía arreglar
`goals.start_identity`/`goals.satisfy` para que no perdieran factores ya
satisfechos de un `ConversationGoal` de identidad. La revisión eng de esa
misma fecha (outside voice + verificación directa en código) encontró que
`goals.start_identity` **no tiene ningún caller en producción** desde que
É-F5 Fase 2 (commit `61dd5cd`, 02-ago-2026) retiró la FSM de identidad que lo
invocaba — arreglar esa función no habría tocado el bug real. El item se
retiró del plan.

**Contexto**: el mecanismo que sí está vivo hoy es `flow['aportado']`
(poblado por `agent/tools.py::identify_client` cuando el modelo la llama,
`agent/prompts.py::anchored_identity_facts` lo publica al modelo cada turno
sin depender de ningún compromiso). Dos hipótesis sin confirmar todavía:

1. El modelo **no llama** `identify_client` con los datos que ya tiene
   cuando arranca un reto de identidad (los datos se dijeron respondiendo
   otra pregunta — p.ej. la del objetivo de agendar — y el modelo no los
   reenvía a la tool de identidad).
2. El modelo **sí llama** la tool, `flow['aportado']` sí tiene el dato,
   `anchored_identity_facts` sí lo publica — pero el modelo ignora ese
   hecho publicado y pregunta de todos modos (falla de instrucción/prompt,
   no de datos).

Son dos causas raíz distintas con dos fixes distintos (capturar mejor vs.
reforzar cómo se usa lo ya capturado). Elegir el fix equivocado repite
exactamente el error que esta investigación busca evitar.

**Cómo investigar**: correr `agent_eval_conversations` o revisar
`ToolExecution`/`TurnDecision` de una conversación real que reproduzca el
patrón, mirando específicamente si `identify_client` se llamó en el turno
donde el cliente dio el nombre/mascota, y qué contenía `flow['aportado']`
en el turno donde se repitió la pregunta.

**Pros de hacerlo**: corrige el "tropiezo" más caro identificado hasta
ahora — el que peor se siente para un cliente real y el que más escaladas
a humano genera por frustración.

**Contras**: requiere datos de una conversación real o reproducir el
escenario contra el modelo real (no basta con `StubLLMClient` — el defecto
original de Item 3 se detectó justo porque los tests con stub no lo
reproducían).

**Depende de**: nada bloqueante — puede investigarse en cualquier momento,
independiente de Item 1/Item 2.

**Cuándo retomarlo**: cuando haya tiempo para una investigación dedicada
(no un fix rápido) — el hallazgo de esta revisión es justamente que
apurar un fix sin esta investigación arriesga arreglar el síntoma
equivocado otra vez.
