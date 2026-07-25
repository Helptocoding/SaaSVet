# Auditoría del agente conversacional de WhatsApp — producto, conversación y arquitectura

**Fecha**: 2026-07-24
**Alcance auditado**: `apps/agent` + `apps/channels` (10 729 líneas), toda la documentación del subsistema (`whatsapp-agent-architecture.md`, `-implementation-plan.md`, `-functional-spec.md`, `-ux-review.md`, `-epics.md`, `-audit-dossier.md`), ADR p51/p52/p53, `docs/modules/agent.md`, `runbooks/agent-whatsapp.md`, frontend `/inbox`.
**Perspectiva**: Principal AI Engineer + Staff Product Engineer + Conversation Designer.
**Método**: lectura completa del diseño → lectura completa del código → contraste diseño↔implementación → simulación mental de conversaciones reales.
**Sesgo declarado**: esta auditoría asume que **ninguna** decisión previa es correcta hasta que el código la sostenga. Donde el diseño y el código difieren, manda el código: es lo que el cliente va a experimentar.

> **Veredicto de una línea**: la capa de *seguridad y control* es de calidad superior a la media de la industria y no es el problema. El problema es que **la capa conversacional está construida como un ejecutor de reglas, no como una recepcionista**, y que hay **cinco bugs funcionales concretos** que se manifestarán el primer día del piloto — uno de ellos con impacto clínico y otro capaz de tumbar el subsistema completo para todas las clínicas.

---

## Índice

1. [Resumen ejecutivo](#1-resumen-ejecutivo)
2. [Fortalezas del diseño actual](#2-fortalezas-del-diseño-actual)
3. [Debilidades importantes](#3-debilidades-importantes)
4. [Riesgos para el piloto](#4-riesgos-para-el-piloto)
5. [Problemas conversacionales](#5-problemas-conversacionales)
6. [Problemas de UX](#6-problemas-de-ux)
7. [Problemas del System Prompt](#7-problemas-del-system-prompt)
8. [Problemas de arquitectura](#8-problemas-de-arquitectura)
9. [Problemas del Policy Engine](#9-problemas-del-policy-engine)
10. [Problemas del uso de herramientas](#10-problemas-del-uso-de-herramientas)
11. [Problemas de memoria](#11-problemas-de-memoria)
12. [Problemas de handoff](#12-problemas-de-handoff)
13. [Problemas de timing y múltiples mensajes](#13-problemas-de-timing-y-múltiples-mensajes)
14. [Problemas que aún no hemos considerado](#14-problemas-que-aún-no-hemos-considerado)
15. [Quick wins](#15-quick-wins)
16. [Mejoras de mediano plazo](#16-mejoras-de-mediano-plazo)
17. [Mejoras de largo plazo](#17-mejoras-de-largo-plazo)
18. [Cambios que NO recomendaría hacer](#18-cambios-que-no-recomendaría-hacer)
19. [Riesgos de sobreingeniería](#19-riesgos-de-sobreingeniería)
20. [Recomendación priorizada antes del piloto](#20-recomendación-priorizada-antes-del-piloto)

---

## 1. Resumen ejecutivo

### Qué se construyó realmente

Un agente de recepción por WhatsApp con: webhook firmado, cola en Postgres, worker propio, Policy Engine determinista de 13 reglas, identidad de contacto con 4 niveles de verificación, 13 herramientas que consumen la API DRF real por loopback con JWT de una cuenta de servicio, confirmación tier-2 con parafraseo por plantilla, auditoría append-only punto a punto, kill switch por organización y 224 tests en CI bloqueante.

La ingeniería de control es sólida y, en varios puntos (cadena de auditoría `domain_object_public_id` → `ToolExecution` → `Conversation` → `Message` → `LLMCall`; separación `is_service_account` vs `role`; parafraseo por plantilla), está por encima de lo que se ve en producción en la mayoría de productos conversacionales comerciales.

### Dónde está el problema

**El proyecto invirtió su presupuesto de rigor en la mitad equivocada del sistema.** El plan de implementación lo predijo con exactitud (§9.1: *"B20 (calidad conversacional) no tiene precedente interno — único tramo donde la estimación puede fallar ×2"*) y luego el proyecto hizo exactamente lo contrario de lo que ese aviso recomendaba: la infraestructura recibió 5 documentos, 3 ADR y una revisión crítica adversarial; la calidad conversacional recibió **un system prompt de 60 líneas escrito de corrido, sin ejemplos, sin evaluación de tono y sin un solo test que mida naturalidad**.

Los tres síntomas que reportaste no son tres problemas: son **un solo problema con tres caras** — el sistema fue especificado como una máquina de estados que responde mensajes, no como una persona que sostiene una conversación.

| Síntoma reportado | Causa raíz real |
|---|---|
| Responde los 3 mensajes por separado | No existe debounce: `INBOUND_AVAILABLE_DELAY = 3s` fijo (`services.py:29`) no es una ventana de espera, y no hay re-chequeo de entrantes nuevos al terminar el turno |
| Se siente robótico | Prompt de prohibiciones sin ejemplos + 6 plantillas que repiten "te comunico con una persona" + presupuesto que fuerza cierres abruptos |
| Escala demasiado rápido | Presupuesto de 15 llamadas LLM por conversación (se agota en ~5 mensajes reales), reto de identidad que rechaza el nombre de pila del propio cliente, y matcher `wants_human` con falsos positivos |

### Los cinco hallazgos que no pueden llegar al piloto

| # | Hallazgo | Severidad | Evidencia |
|---|---|---|---|
| **H1** | El generador de horarios usa la zona del servidor (`TIME_ZONE='UTC'`), no la de la organización → **a las 10:00 AM en México el agente sólo ofrece horarios de 16:00 en adelante; a la 1:00 PM no ofrece nada para hoy; después de las 18:00 rechaza la fecha de hoy como "pasada"** | 🔴 Crítica (funcional, diaria) | `tools.py:427-428`, `tools.py:500-502`, `settings.py:482` |
| **H2** | El detector de urgencia sólo ve **el último** mensaje de una ráfaga → "mi perro convulsiona" + "ayúdenme por favor" ⇒ la urgencia **no se detecta** | 🔴 Crítica (clínica/legal) | `planner.py:46` (`_last_inbound_text`) + `policy.py:81` |
| **H3** | Una excepción no controlada procesando un mensaje **tumba el worker** de todas las organizaciones; al reiniciar reprocesa el mismo mensaje ⇒ crash-loop indefinido | 🔴 Crítica (disponibilidad multi-tenant) | `worker.py:63-73` sin `try/except`, `run_agent_worker.py:61-81` sin `try/except` |
| **H4** | La urgencia escala a una **cola que nadie vigila**: no hay alerta a ops, y `/inbox` no muestra prioridad ni notifica | 🔴 Crítica (seguridad operativa) | Sin `send_support_report` en `apps/agent`; `frontend/src/pages/inbox/index.jsx` sin `urgent`/sonido/notificación |
| **H5** | Los horarios se calculan por rejilla de 30 min comparando **igualdad exacta de `start_time`** ⇒ el agente ofrece huecos que el dominio después rechaza por solape real (citas de 45 min, o a las 10:15) | 🟠 Alta (ensucia agenda, bucle "se acaba de ocupar") | `tools.py:422-426` (ignora `end_time`) |

Ninguno de los cinco aparece en `whatsapp-agent-audit-dossier.md` §18 "Deuda conocida / riesgos residuales". Eso es, en sí mismo, un hallazgo: **el dossier de auditoría describe el sistema que se diseñó, no el que se construyó**.

---

## 2. Fortalezas del diseño actual

Estas decisiones son correctas y **no deben tocarse** en ninguna de las remediaciones propuestas.

**F1 — "El LLM propone, el sistema dispone" está realmente implementado, no sólo escrito.** El Policy Engine (`policy.py:54-167`) corre antes del modelo, y las tools revalidan verificación (`tools.py:1221`). No es teatro: se puede leer la ruta completa y confirmar que ninguna decisión de autorización pasa por el texto del modelo.

**F2 — El parafraseo por plantilla es la mejor decisión de producto del proyecto.** `confirmations.py:21-34` con args ya resueltos y `_commit_pending` ejecutando exactamente lo staged (`planner.py:221-277`) elimina de raíz la clase de fallo más cara de un agente que escribe: "confirmé una cosa y agendó otra". La invariante TC-SEC-03 es real.

**F3 — Loopback HTTP con JWT del rol AGENT.** Reusar serializers, validadores de tenant, RBAC y sanitización en vez de reimplementarlos es correcto. La crítica del plan (§C12) resistió mi propio intento de derribarla. *(Con una salvedad grave sobre **dónde** se ejecuta ese loopback — ver §8.)*

**F4 — Separación `is_service_account` / `role='AGENT'` (ADR p51).** Es la decisión de identidad correcta y barata. Evita el patrón `exclude(role__in=[...])` que se pudre. Mantener.

**F5 — Cadena de auditoría sin FKs del dominio hacia el agente.** `ToolExecution.domain_object_public_id` indexado permite reconstruir el origen de cualquier cita sin acoplar los dominios. Elegante y correcta.

**F6 — Idempotencia acuñada en la propuesta, no en el commit** (`tools.py:616`, `confirmations.py:48`). La clave nace al parafrasear y sobrevive al reintento. Es sutil y está bien resuelto.

**F7 — Fixture trampa cross-tenant en CI** y aserciones prohibidas globales en el harness (`tests/harness.py:69-78`). Poca gente hace esto. Consérvalo y amplíalo.

**F8 — El kill switch existe, es por organización y es reversible desde la UI.** Requisito no negociable de un piloto; está.

**F9 — La lista negativa de tools es vinculante y doble** (RBAC + inexistencia de la herramienta). Nada financiero ni clínico-escritura es alcanzable. Correcto.

**F10 — La revisión crítica del plan (§7 del implementation-plan) fue honesta y acertada.** Eliminar 4 modelos, 3 estados y 2 tiers antes de escribir código evitó una cantidad enorme de complejidad muerta. El proyecto sabe autocriticarse; esta auditoría es una extensión de esa práctica, no una novedad.

---

## 3. Debilidades importantes

### D1 — La especificación funcional está congelada; la implementación divergió sin enmienda

La spec §1.3 declara que las plantillas tier-0 son **literales y verificadas por igualdad**. En la práctica, con el agente encendido:

- **T0-GREET nunca se emite.** `worker.py:100-106`: si `enabled and agent_user_id`, todo entrante va al planner. `render_first_reply` sólo corre en el fallback F0 (agente apagado o sin provisionar). El saludo institucional — la primera impresión del producto, discutida y decidida por el PO el 2026-07-15 — **lo escribe el LLM libremente**. `TC-INT00-01` pasa en CI porque testea `render_first_reply` en aislamiento (`test_tier0.py:88`), no el flujo real.
- **T0-PRIVACY es código muerto.** `render_privacy` (`tier0.py:156`) no se invoca en ninguna parte; `privacy_notice_sent_at` (`models.py:80`) nunca se escribe. El aviso just-in-time — que la consulta legal A1-1 marcó como bloqueante para F1 — **no existe en producción**.
- **GB-1 (media) no está implementado.** Un audio llega con `body=''` (`channels/views.py:109-110`), ningún matcher aplica, y se invoca al LLM con `'[mensaje sin texto]'` (`prompts.py:154`). La plantilla especificada ("¿Me lo puedes escribir?") no existe. En México esto es entre el 15 % y el 40 % del tráfico entrante.
- **§2.6 anti-flood (>10 msgs/60 s) no está implementado.** No hay ninguna referencia en `policy.py`.
- **UX-02 etapa 2 (clasificación LLM de la afirmativa) no está implementada.** `classify_confirmation` devuelve `'unclear'` y el planner simplemente vuelve al bucle general con tools (`policy.py:130`), donde el modelo puede re-proponer y re-parafrasear.

**El problema no son las divergencias individuales; es que una spec "congelada" que diverge en silencio deja de ser un contrato y se convierte en decoración.** Cualquier auditor externo que compare ambos documentos perderá la confianza en los dos.

### D2 — Cero medición de calidad conversacional

`metrics.py` mide conversión, handoffs y embudo — métricas de negocio, correctas y bien pensadas. No existe **ninguna** métrica de la experiencia: turnos por resolución, tasa de repregunta, tasa de mensajes que el cliente ignora, longitud media de respuesta, tiempo a primera respuesta real, ni muestreo humano de transcripts. `agent_eval` es binario (pasa/no pasa escenarios) y no bloqueante.

Consecuencia: **el piloto no podrá responder "¿esto se siente como una buena recepcionista?" con datos.** Sólo podrá responder "¿agendó?".

### D3 — La verificación de identidad rechaza a clientes legítimos por construcción

Tres defectos compuestos en `identity.py`:

1. `_name_matches` exige igualdad normalizada o distancia de edición ≤1. Para el segundo factor (`T0_CHALLENGE_OWNER`, "¿A nombre de quién está el registro?") el cliente responderá **su nombre de pila**: `"Ana"` vs `"Ana Torres"` registrado → no coincide → handoff (`identity.py:129-136`, `policy.py:213-225`). Un cliente diciendo correctamente quién es, expulsado.
2. `is_verification_current` (`identity.py:76`) — la caducidad de 182 días especificada en §2.3 — **no se llama en ningún lado fuera de los tests**. `_verification_ok` (`tools.py:100-107`) sólo compara niveles. La verificación es eterna.
3. El match teléfono→Owner corre **una sola vez, al crear la `ContactIdentity`** (`services.py:90-94`). Escenario cotidiano: un cliente escribe *antes* de estar registrado (queda `unknown` para siempre), la clínica lo da de alta en mostrador, y la próxima vez que escribe el sistema **sigue diciendo que no está registrado** y lo empuja al alta duplicada. Este es el mismo tipo de bug que la UX review §3 identificó para las familias — y aquí aplica al titular mismo.

### D4 — Dos funciones distintas normalizan teléfonos con reglas distintas

`services.py::normalize_wa_id` (estricta: valida prefijo 52/521, devuelve `''` si no reconoce) y `tools.py::_wa_id_to_local10` (permisiva: últimos 10 dígitos de cualquier cosa con ≥10). La segunda es la que se usa para **registrar al cliente en la base de datos** (`tools.py:851`). Un número no mexicano produciría un `Owner.phone` de 10 dígitos falso. Es exactamente la "segunda forma de resolver algo existente" que `CLAUDE.md` prohíbe.

### D5 — La configuración de la clínica vive en dos lugares con lógica de fallback triplicada

ADR p53 movió los datos de la clínica a `Organization`/`OrganizationSchedule`, pero `AgentSettings.business_hours`/`faq_facts` siguen vivos como legacy. El resultado es lógica de merge repetida en `tools.get_clinic_info` (`tools.py:177-186`), `planner._post_scheduling_info` (`planner.py:298-321`), `find_available_slots` (`tools.py:504-508`) y `suggest_retention_slots` (`tools.py:458-467`). La "deuda contenida N2" del plan ya se cobró.

### D6 — El worker es un punto único de fallo sin aislamiento por tenant ni por mensaje

Ver H3 y §8. No hay contador de intentos en el entrante, ni dead-letter, ni `try/except` por conversación. La decisión C4 del plan ("el inbox ES la cola") es elegante, pero al fusionar *mensaje* y *job* eliminó el lugar natural donde vive `attempts` para el procesamiento entrante — el modelo lo tiene sólo para el envío saliente.

---

## 4. Riesgos para el piloto

Ordenados por probabilidad × daño. "Probabilidad" = probabilidad de ocurrir en las primeras dos semanas con una clínica real.

| # | Riesgo | Prob. | Daño | Detonante realista |
|---|---|---|---|---|
| R-A | **El agente no ofrece horarios** (H1, bug de zona horaria) | ~100 % | Alto: el valor central del producto no funciona; la clínica concluye "no sirve" | Cualquier petición de cita para hoy después de las 09:00 hora local |
| R-B | **Urgencia no detectada en ráfaga** (H2) | Media-alta | **Máximo**: daño clínico + exposición legal + fin del piloto | Cliente angustiado escribiendo en tres mensajes cortos — el patrón *más* probable en pánico |
| R-C | **Worker en crash-loop** (H3) | Media | Alto: todas las clínicas mudas, sin alerta específica (el deadman avisa tarde: cada ~60 ciclos) | Un payload inesperado, un `None` en un campo, una respuesta rara del LLM |
| R-D | **Urgencia detectada pero desatendida** (H4) | Alta | **Máximo** | Escalamiento a las 22:00 con `/inbox` cerrada |
| R-E | **Handoff masivo por presupuesto** (§12) | Alta | Medio-alto: la clínica recibe más trabajo que antes del agente | Cualquier conversación de agendado con 5+ intercambios |
| R-F | **Cliente legítimo expulsado por el reto de identidad** (D3) | Alta | Medio: el peor tipo de fricción ("el sistema no me reconoce *a mí*") | Cliente que responde su nombre de pila, o cuya mascota se llama "Kirita" |
| R-G | **Bucle "ese horario se acaba de ocupar"** (H5 + mapeo 400→`slot_taken`) | Media-alta | Alto: el agente miente y no puede salir del bucle | Clínica con citas de 45–60 min o con horarios fuera de la rejilla :00/:30 |
| R-H | **Audios sin respuesta útil** (D1) | Alta | Medio: segmento >40 años queda fuera | Primer cliente que manda nota de voz |
| R-I | **Duplicación de expedientes** por match único al crear contacto (D3.3) | Media | Alto: ensucia la base de la clínica, que es su activo | Cliente que escribió antes de ser dado de alta |
| R-J | **Cita asignada a un veterinario que no la aceptó** | Media | Medio-alto: conflicto interno en la clínica | `AgentSettings.default_veterinarian` sin configurar → `_resolve_scheduling_vet` (`tools.py:396-400`) toma **el primer VET por pk** silenciosamente |
| R-K | **Amnesia a las 24 h** (§11) | Alta | Bajo-medio: fricción y repetición | Cliente que retoma al día siguiente |
| R-L | **Deriva de calidad del LLM** | Media | Medio | Cambio de versión del modelo del proveedor sin aviso; el eval nightly no es bloqueante |

**Nota sobre el orden**: R-A es el que mata el piloto comercialmente; R-B/R-D son los que lo matan legalmente. Los tres se arreglan en menos de un día de trabajo cada uno.

---

## 5. Problemas conversacionales

### 5.1 El agente no tiene registro; tiene reglas

Un modelo instruido sólo con prohibiciones produce una voz defensiva y plana. El prompt (`prompts.py:18-82`) contiene **once** prohibiciones explícitas (`NUNCA`, `NO`, `JAMÁS`) y **cero** ejemplos de una conversación bien llevada. Ninguna cantidad de "tu tono es cálido, breve y natural" compensa la ausencia de un ejemplo: los modelos imitan muestras, no adjetivos.

Esto es, con diferencia, la palanca individual más grande sobre el síntoma "se siente robótico". Tres a cinco intercambios de referencia en el prompt cambian el registro de salida de forma inmediata y medible.

### 5.2 Las plantillas repiten la misma frase seis veces

`tier0.py` + `planner.py`: "te comunico con una persona del equipo" (o variante casi idéntica) aparece en `T0_BOTQ`, `T0_HANDOFF`, `T0_BUDGET`, `T0_OUT_PAYMENT`, `T0_CHALLENGE_FAILED`, el mensaje de `family_restricted` (`planner.py:163-165`), el de fallo de tool (`planner.py:203`) y el de commit fallido (`planner.py:266`). Además el prompt instruye al LLM a ofrecerlo cuando no sabe algo (`prompts.py:41-42`).

Una recepcionista real dice "déjame checar", "ahorita te confirmo", "eso lo ve el doctor" — tiene *repertorio*. El agente tiene una sola salida y la usa para todo. **El cliente percibe esto como incompetencia, no como prudencia.**

### 5.3 Cierres abruptos que suenan a sistema

`T0_BUDGET`: *"Para darte una mejor atención, dejo que una persona del equipo continúe contigo 🙌"*. Ninguna persona dice esto. Y lo dice justo después de haberte estado ayudando, sin explicación desde el punto de vista del cliente. Es el equivalente conversacional de un `TimeoutError` traducido al español.

### 5.4 El agente no acusa recibo de lo que ya sabe

No hay reformulación de lo entendido antes del parafraseo final. En un flujo de agendado real, la recepcionista devuelve señales continuas ("ok, para Luna...", "vacuna, perfecto"). El agente sólo emite señal en el parafraseo tier-2. Entre medias, el cliente no sabe si lo entendieron.

### 5.5 Formato de WhatsApp inconsistente

Las plantillas usan `*negritas*` (sintaxis WhatsApp, `tier0.py:9`). Al LLM **nunca se le dice**. Un modelo entrenado en markdown emitirá `**negritas**`, que WhatsApp renderiza **con los asteriscos visibles**. En una misma conversación convivirán textos bien formateados (plantillas) y textos con basura visible (LLM). Una línea en el prompt lo arregla.

### 5.6 Emoji ritual

Casi todas las plantillas llevan emoji (🐾, 🙌, 😅, 🙂, ✅). La regla de "máximo 1 emoji por mensaje" se cumple, pero al ser **todas** las plantillas, una conversación de 6 turnos lleva 6 emojis. Deja de leerse como calidez y empieza a leerse como plantilla corporativa.

### 5.7 El reto de identidad llega sin contexto emocional

*"Para proteger tus datos, ¿me confirmas el nombre de tu mascota?"* — correcto en política, frío en ejecución, y **desconectado de lo que el cliente acaba de pedir**. Una recepcionista dice: "Claro, déjame buscarte — ¿cómo se llama tu peludito?". Misma verificación, cero fricción percibida. El diseño de la spec (§2.3) es bueno; el copy lo arruina.

### 5.8 Sin manejo conversacional del silencio ni de la interrupción

El nudge (`policy.py:337-370`) es un texto único y genérico (*"¿Seguimos con tu cita? Aquí sigo para ayudarte 🐾"*) que **sólo se dispara si hay un `pending_action`** — es decir, sólo si el cliente ya llegó hasta el parafraseo final. El abandono típico ocurre antes (tras la oferta de horarios), y ese caso no tiene nudge, contra lo que UX-08 especificó.

---

## 6. Problemas de UX

### 6.1 Para el cliente

- **Silencio durante el proceso.** UX-13 (marcar como leído + indicador de escritura) no está implementado. Entre 3 s de espera + hasta 2 s de ciclo + hasta 30 s de LLM, el cliente puede esperar 15–35 s frente a una pantalla sin ninguna señal. En WhatsApp, la doble palomita azul *es* la señal de servicio.
- **Nunca se usan botones.** WhatsApp soporta quick-reply buttons y listas. El sistema los **lee** (`_extract_body`, `channels/views.py:102-108`) pero **nunca los envía** (`providers.py` sólo tiene `send_text`). Para "elige un horario" y para "¿confirmas?", los botones eliminarían de un golpe: la ambigüedad del matcher es-MX, una llamada al LLM por turno, y la clase entera de errores de confirmación. Es la mejora de UX con mejor relación impacto/costo de todo el sistema.
- **No puede mandar audio.** Ver D1/R-H.
- **Se le pide el nombre de la mascota para saber a qué hora abren.** No: `get_clinic_info` es `min_verification: unknown`. Correcto. Pero si pregunta "¿cuándo es mi cita?" el reto llega antes de cualquier señal de que fue entendido.
- **Pierde el hilo a las 24 h** (§11).

### 6.2 Para la recepcionista

- **La bandeja no grita.** Sin ordenamiento por prioridad, sin contador de no leídos, sin sonido, sin notificación de escritorio, sin badge en la navegación. Polling cada N segundos sobre una página que debe estar abierta. Un handoff urgente por convulsión y una duda de horarios se ven **idénticos** (`inbox/index.jsx:35-41`).
- **No ve lo que el bot hizo.** `ToolExecution` guarda cada acción, pero la bandeja no la muestra. La recepcionista lee el transcript y tiene que *inferir* que se creó una cita. Una línea de sistema en el hilo ("🤖 agendó cita para Luna — martes 21, 4:00 pm") cambiaría por completo la confianza operativa.
- **Cuando toma la conversación, el agente enmudece para siempre.** `HUMAN_ACTIVE` → `SILENT` (`policy.py:76-77`), y devolver el control es un endpoint (`release`) que existe en API pero cuya presencia y semántica en la UI habría que verificar con la clínica. Si la recepcionista responde una duda simple, queda dueña del hilo el resto del día.
- **Los mensajes del humano no entran al contexto del agente.** `assemble_messages` (`prompts.py:151-157`) sólo mapea `AUTHOR_AGENT` y `AUTHOR_SYSTEM`; los de `human_staff` se descartan. Si el agente vuelve a tomar el control, ignora todo lo que dijo su compañera humana.

### 6.3 Para el veterinario

- **Puede recibir citas que nunca aprobó.** `_resolve_scheduling_vet` cae al primer VET activo por `pk` si nadie configuró `default_veterinarian` (`tools.py:396-400`). Silencioso. Debería devolver `no_vet` y obligar a la configuración (el prerequisito ya está en el checklist del dossier §19, pero el código no lo exige).
- **No sabe qué citas vinieron del bot** salvo por la nota en `notes` ("Agendada por asistente virtual · conv ..."). No hay indicador visual en la agenda.

### 6.4 Para el dueño de la clínica

- Métricas de negocio decentes (`metrics.py`), pero sin costo por conversación visible en la UI, sin comparación contra el "antes", y sin la métrica que realmente le importa: **no-shows evitados** (eso es F3).
- El kill switch existe y es de un clic: bien.
- La demo no lleva agente (Q15). Correcto en riesgo, **caro en ventas**: el feature estrella no se puede enseñar. Ver §16.

---

## 7. Problemas del System Prompt

Análisis línea por línea de `prompts.py:18-82` (`PROMPT_VERSION = 'reception-f2-v5'`).

### 7.1 Estructura actual

~700 tokens, 9 bloques, todos en imperativo, 4 de ellos con énfasis en mayúsculas ("REGLA ABSOLUTA DE TURNO", "CLAVE, NO LO IGNORES"). Se envía íntegro en **cada** iteración del bucle de tools, junto con 13 esquemas de herramientas (~1 500 tokens más) y el historial.

### 7.2 Qué eliminaría

| Bloque | Veredicto | Razón |
|---|---|---|
| `REGLA ABSOLUTA DE TURNO` (líneas 23-27) | **Eliminar — y arreglar la causa** | Es un parche a un síntoma: el modelo se auto-responde porque el historial que recibe **no contiene sus propias llamadas a herramientas** ni los resultados como mensajes `tool` (§8.3). Arreglado el ensamblado, la regla sobra. Mientras exista, además, gasta ~90 tokens en cada llamada y empuja al modelo a un registro rígido |
| `GLOSARIO (úsalo)` (29-30) | **Fusionar** | Tres términos; cabe en la línea de tono. El "Cobro" es irrelevante: el agente tiene prohibido hablar de pagos |
| `CLIENTE NUEVO vs REGISTRADO` (48-56) | **Eliminar del prompt** | Es lógica de negocio determinista escrita como instrucción. `numero_registrado` ya está en el contexto y `T0_NEW_CLIENT` ya cubre el caso desde el planner (`planner.py:172-177`). Duplicar la regla en el prompt genera comportamiento inconsistente entre la ruta determinista y la generada |
| `QUÉ NO HACES` (58-62) | **Recortar a la mitad** | "NO borras citas ni registros" es invisible para el modelo (no existe esa tool) y sólo consume atención. "NO inventas datos ni precios" se repite en tres bloques distintos |
| Regla de fecha (65-68) | **Comprimir a una línea** | Cinco líneas para decir "usa `fecha_hoy` del contexto". El dato ya está estructurado |
| `Responde SIEMPRE en español de México` (81) | **Fusionar con el tono** | Redundante con la primera línea |

### 7.3 Contradicciones detectadas

1. **"Máximo 2-4 líneas por mensaje"** vs el flujo INT-20 que exige ofrecer 3 horarios + confirmar. El modelo resuelve la tensión recortando calidez, no información.
2. **"Tu tono es cálido, breve y natural"** vs 11 prohibiciones en mayúsculas. Los modelos calibran el registro por la *densidad* de restricciones, no por el adjetivo declarado. El prompt pide calidez y modela burocracia.
3. **"Si no hay herramienta para algo, dilo con honestidad y ofrece pasar con una persona"** vs el objetivo comercial O1 ("resolver al primer contacto"). Tal como está redactado, el camino de menor resistencia para el modelo ante cualquier duda es ofrecer un humano. **Esta línea es co-responsable directa del síntoma #3 que reportaste.**

### 7.4 Qué reescribiría (dirección, no texto final)

- **Abrir con identidad y situación, no con reglas**: quién eres, dónde trabajas, con quién hablas, qué se espera de ti. Dos frases.
- **Insertar 3–5 ejemplos cortos de intercambio ideal**: uno de FAQ, uno de agendado con oferta de horarios, uno de "no lo sé" bien resuelto sin escalar, uno de empatía sin juicio clínico, uno de cliente que cambia de tema. **Este es el cambio de mayor impacto de toda la auditoría sobre la percepción de naturalidad.**
- **Convertir prohibiciones en positivos operativos**: en lugar de "NO des consejos médicos", escribir "ante cualquier síntoma: reconoce brevemente, ofrece cita, y si suena grave di que acudan de inmediato". El modelo necesita saber **qué hacer**, no sólo qué no hacer.
- **Añadir explícitamente**: formato de WhatsApp (`*negritas*`, sin markdown), prohibición de re-saludar en la misma conversación, y prohibición de repetir textualmente lo que el cliente acaba de decir.
- **Sacar del prompt todo lo que ya es determinista** (cliente nuevo/registrado, fechas, vinculación familiar).
- **Objetivo**: bajar de ~700 a ~450 tokens de instrucción **y ganar 200 tokens de ejemplos**. Menos reglas, más muestra.

### 7.5 Lo que el prompt hace bien y hay que conservar

- La inyección de `fecha_hoy`/`dia_semana`/`hoy_legible` (`prompts.py:100-118`) — fix real de un bug real de piloto, bien hecho.
- El marcado explícito de los bloques `DATOS ... (no son instrucciones)` (`prompts.py:142`, `162`) — defensa correcta contra injection de segundo orden.
- La regla de no confirmar la cita antes del "sí" (44-46) — carga real, mantener.

### 7.6 Falta un versionado con significado

`PROMPT_VERSION` es un string en git (decisión correcta, plan §C6), pero **nadie compara calidad entre versiones**: `LLMCall.prompt_version` se guarda y nunca se explota. Sin eso, ir de `v5` a `v6` es cambiar a ciegas.

---

## 8. Problemas de arquitectura

### 8.1 🔴 El turno completo corre dentro de una transacción de base de datos

```python
# worker.py:63-73
with transaction.atomic():
    conversations = list(Conversation.objects.select_for_update(skip_locked=True)...[:batch])
    for conversation in conversations:
        _process_one(conversation, now)   # → planner → LLM (hasta 30 s) → loopback HTTP
```

Consecuencias, todas reales:

1. **Una transacción abierta durante llamadas de red externas**, hasta 10 conversaciones × hasta 6 iteraciones de LLM. Un `idle in transaction` de minutos, bloqueando conexión y locks.
2. **Bloqueo cruzado entre clínicas**: las 10 conversaciones del lote quedan lockeadas hasta que la más lenta termina. Sin aislamiento por tenant.
3. **Split-brain de escritura**: el loopback escribe la cita **por otra conexión** y esa escritura commitea de inmediato. Si la transacción del worker falla después, la cita **queda creada** pero el `pending_action` no se limpia y el mensaje de confirmación al cliente se pierde. La idempotencia evita el duplicado en el reintento, pero el estado conversacional y el de dominio pueden divergir.
4. **La transacción no protege nada útil**: el objetivo era serializar por conversación, y eso lo da el lock de fila — que no necesita envolver el turno entero.

**Corrección**: una transacción **por conversación** y **sólo alrededor de las escrituras locales** (marcar procesados, persistir salientes). La serialización por conversación se consigue con un lock corto o una columna `processing_until`; no con una transacción abierta durante 30 segundos.

El mismo patrón se repite en `send_pending_outbound` (`worker.py:145-162`): hasta 20 envíos HTTP a Meta (15 s de timeout cada uno) dentro de una sola transacción.

### 8.2 🔴 Sin aislamiento de fallos: un mensaje envenenado tumba el subsistema completo

No hay `try/except` en `_process_one`, ni en `process_pending_conversations`, ni en el loop de `run_agent_worker.py:61-81`. Una excepción cualquiera (un `None` inesperado, un JSON raro del proveedor, un `KeyError` en un `pending` corrupto — hay un guard defensivo para ese caso en `planner.py:241` pero no para los demás) propaga hasta matar el proceso. Docker reinicia. El mensaje volvió a `pending` por el rollback. Se reprocesa. Se vuelve a caer. **Loop infinito, todas las clínicas mudas, y cada vuelta puede gastar una llamada al LLM.**

Faltan las tres piezas estándar: `try/except` por conversación, contador de intentos en el entrante, y dead-letter con escalado a humano al agotar intentos.

### 8.3 🟠 El hilo de herramientas del turno no se le devuelve al modelo

`_run_planner` reconstruye el historial desde la base de datos en cada iteración (`planner.py:101`) y adjunta **sólo el último resultado** de tool como bloque de sistema (`planner.py:213`). El modelo nunca ve:

- su propia llamada a la herramienta (mensaje `assistant` con `tool_calls`),
- los resultados de iteraciones anteriores del mismo turno (`extra_data` se sobreescribe),
- ningún `tool_call_id` de correlación.

Esto produce tres efectos observables: el modelo repite llamadas que ya hizo (gasta presupuesto y dinero), pierde el resultado de la primera tool cuando necesita dos, y — al no ver su propio turno — tiende a **auto-completar el diálogo**, que es precisamente el fallo que el bloque `REGLA ABSOLUTA DE TURNO` intenta parchear con instrucciones.

Es el defecto técnico con mayor impacto sobre la calidad percibida. Y su arreglo elimina un bloque del prompt.

### 8.4 🟠 El presupuesto está mal ubicado

`AGENT_MAX_LLM_TURNS_PER_CONVERSATION = 15` cuenta **llamadas al modelo**, no turnos de conversación, y se acumula durante toda la vida de la conversación (hasta 24 h). Un agendado real consume: intención (1) + tool de slots (2) + propuesta (2 más si hay dos tools)... Un intercambio de cliente rara vez cuesta menos de 2 llamadas. **El presupuesto se agota alrededor del quinto mensaje del cliente** — justo en medio del flujo de agendado, que la propia spec (INT-20) describe con 6 turnos en el caso feliz.

Esto no es un límite de seguridad; es un **generador de handoffs**. El límite correcto es doble: un tope generoso por conversación (40+) y un límite de tasa por contacto por hora.

### 8.5 🟡 Convenciones de tenancy incumplidas en el worker

`nudge_abandoned_flows` (`policy.py:344`) y `close_inactive_conversations` (`policy.py:379`) consultan `Conversation.objects.filter(...)` sin `for_organization()`. Es funcionalmente correcto (el worker es global) pero rompe la convención declarada como invariante en `docs/modules/agent.md` y en el dossier §11. Con RLS diferido (ADR p23), la convención *es* el control. Cualquier excepción debe estar comentada y baselineada, como se hizo bien en `channels/views.py:126`.

### 8.6 🟡 `flow['refs']` crece sin límite y sin invalidación

`_add_ref` (`tools.py:79-88`) acumula handles indefinidamente en el JSON de la conversación. En una conversación larga: crecimiento sin tope, y handles apuntando a citas ya canceladas que siguen resolviendo. El plan (ADR p50) exige whitelist de keys y tope de tamaño para `flow`; `models.py:140-141` lo declara como pendiente ("se enforcen en É-F1") y **no se implementó**.

### 8.7 🟡 Latencia sin presupuesto global

No existe deadline de turno. Peor caso teórico: 3 s de espera + 2 s de ciclo + 6 × 30 s de LLM + 6 × 10 s de loopback = >4 minutos antes de que salga una sola palabra. Sin presupuesto de tiempo ni mensaje de "sigo aquí", el cliente ya se fue.

---

## 9. Problemas del Policy Engine

El orden de reglas (`policy.py:54-167`) es correcto y está bien testeado. Los problemas son de **cobertura** y de **entrada**, no de secuencia.

### 9.1 🔴 Todas las reglas evalúan un solo mensaje

`policy.evaluate(conversation, text)` recibe `_last_inbound_text` (`planner.py:46`): **el último** entrante. Cuando el worker drena una ráfaga, los mensajes anteriores no pasan por ningún matcher. Se pierden:

- **urgencias** (H2 — la consecuencia grave),
- peticiones de humano,
- opt-out,
- confirmaciones ("sí" seguido de "gracias" ⇒ el matcher ve "gracias" y responde `T0_THANKS` en vez de ejecutar el `pending_action`).

**Corrección mínima**: evaluar los matchers de seguridad (urgencia, humano, opt-out) sobre **la concatenación de la ráfaga**, y la confirmación sobre el primer mensaje que decida. No es refactor: es cambiar el argumento que se le pasa.

### 9.2 🟠 Matchers con falsos positivos que escalan

`_HUMAN_LEMMAS` (`matchers.py:47-52`) incluye `'quiero hablar con'` y `'con la clinica'`. Disparan con:

- *"quiero hablar con el doctor sobre la dieta de mi perro"* → escala (podría haberse resuelto ofreciendo cita),
- *"¿cómo me comunico con la clínica los domingos?"* → escala en vez de responder el horario.

Y son **irreversibles**: crean handoff y pasan a `HANDOFF_PENDING`. Cada falso positivo es trabajo humano nuevo generado por el sistema que debía quitarlo.

### 9.3 🟠 Falta la escalera intermedia entre "responder" y "escalar"

El Policy Engine tiene dos salidas ante dificultad: responder o escalar. No tiene **"insistir mejor"**. Un humano intenta reformular dos veces antes de pasar la llamada. Aquí: 2 fallos de tool → escalar (`planner.py:197`), 1 fallo real de reto → escalar, presupuesto → escalar. Es un diseño con sesgo sistemático hacia el handoff.

### 9.4 🟡 Reglas especificadas que no existen

- Anti-flood §2.6: ausente.
- `T0_OUT_MEDICAL` (`tier0.py:113`): definida, **nunca usada**. El consejo médico queda 100 % en manos del LLM, cuando la spec (INT-05) lo especifica como plantilla. Es la segunda superficie clínica del sistema y no tiene red determinista.
- Aviso de privacidad just-in-time: ausente (D1).
- Clasificación etapa 2 de confirmación: ausente (D1).

### 9.5 🟡 El opt-out es más destructivo de lo especificado

`policy.py:100-108` pone `contact.is_blocked = True`. La spec (INT-04) dice que el opt-out bloquea **mensajes proactivos** y que si el cliente vuelve a escribir "se le atiende normal". Con `is_blocked=True`, el siguiente mensaje entrante se persiste como `discarded` (`services.py:206`) y **el cliente queda en silencio permanente**. Un cliente que escribe "stop" molesto un martes queda inalcanzable para siempre. Necesita ser un flag distinto (`proactive_opt_out`).

### 9.6 🟡 `_mentions_payment` intercepta antes de entender

Se dispara con substrings como `'transferencia'` o `'deposito'` en cualquier posición. *"¿Puedo pedir el traslado/transferencia de expediente de otra clínica?"* → plantilla de pagos. Bajo impacto, fácil de acotar exigiendo co-ocurrencia con verbos de pago.

---

## 10. Problemas del uso de herramientas

### 10.1 🔴 `find_available_slots` está roto en producción por zona horaria (H1)

```python
# tools.py:427-428  — dentro de _free_slots_for_day
today = timezone.localdate()                          # ← UTC (settings.TIME_ZONE='UTC')
now_hhmm = timezone.localtime().strftime('%H:%M') if day == today else '00:00'
```

Con la clínica en `America/Mexico_City` (UTC−6):

| Hora local real | `now_hhmm` (UTC) | Efecto |
|---|---|---|
| 09:00 | 15:00 | Sólo ofrece slots ≥ 15:00 |
| 13:00 | 19:00 | **Ningún** slot para hoy (clínica cierra 19:00) |
| 18:30 | 00:30 del día siguiente ⇒ `day != today` | `find_available_slots` (`tools.py:500-502`) devuelve `past_date` para **hoy** |

El mismo defecto en `suggest_retention_slots` (`tools.py:463`). Nota: `_future_or_error` (`tools.py:552-564`) sí usa `local_date_time_to_utc` correctamente — es decir, **el proyecto tiene el helper correcto y el generador de slots no lo usa**.

### 10.2 🟠 La rejilla de slots no modela duración (H5)

`occupied` es un conjunto de `start_time` exactos (`tools.py:422-426`). Una cita de 10:00 a 11:00 sólo bloquea el slot de las 10:00; el agente ofrecerá las 10:30. Una cita creada por staff a las 10:15 no bloquea nada. El dominio valida solape **real** al crear → devuelve 400 → el agente dice *"se acaba de ocupar"* y re-oferta el mismo tipo de hueco inválido. **Bucle.**

### 10.3 🟠 Mapeo de errores que hace mentir al agente

`commit_create_appointment` (`tools.py:636`), `commit_reschedule_appointment` (`tools.py:767`) y `commit_register_new_client_and_pet` (`tools.py:896`) traducen **cualquier** 400 a `slot_taken`. Un motivo vacío, una especie inválida, un teléfono rechazado o un veterinario de otra organización se le comunican al cliente como *"Uy, justo se ocupó ese horario 😅"*. Es falso, no es accionable, y esconde errores de configuración durante el piloto — precisamente cuando más falta hace verlos. El shape de error del backend (`{code, errors}`, ADR p16) está disponible y no se usa.

### 10.4 🟠 Búsqueda por substring en catálogo y productos

`get_service_catalog` (`tools.py:231`) y `check_product_availability` (`tools.py:264`) filtran con `query in nombre_normalizado`. Consecuencias: *"esterilizar"* no encuentra *"Esterilización"*; *"vacuna antirrábica"* no encuentra *"Antirrábica (1 dosis)"*; el orden de palabras invierte el resultado. Y `check_product_availability` con `query` vacía devuelve **lista vacía** en vez de un error (`tools.py:264`), así que el modelo concluye "no lo manejamos". **El agente dirá "no ofrecemos ese servicio" sobre servicios que la clínica sí ofrece.** Para un producto cuyo objetivo O1 es "resolver al primer contacto", esto es grave y es barato de arreglar (match por tokens + normalización de sufijos).

### 10.5 🟡 13 herramientas ofrecidas siempre, sin filtrar por estado

`as_openai_tools()` expone las 13 en cada llamada, incluidas `cancel_appointment`, `link_family_member` y `register_new_client_and_pet` a un contacto sin verificar. El Policy Engine y `run_tool` bloquean la ejecución (bien), pero el modelo **elige mal más seguido** cuando el menú es grande, y cada esquema cuesta tokens en cada iteración. Filtrar el registry por `verification_level` y estado del flujo es barato y mejora precisión y costo simultáneamente.

### 10.6 🟡 Herramienta faltante con caso de uso frecuente

INT-21-bis (mascota nueva de cliente existente) no tiene tool — documentado en el dossier §18.5. Es un caso **muy** común ("adoptamos un gatito, ¿me das cita?"). Hoy termina en handoff o, peor, en el modelo intentando `register_new_client_and_pet` → `already_client` → confusión.

### 10.7 🟡 Granularidad desigual

`get_clinic_info` devuelve un diccionario entero de hechos cuando no hay `topic` (tool "grande"), mientras que consultar vacunas exige encadenar `list_my_pets` → `get_vaccine_status` (dos tools, dos iteraciones, dos llamadas al LLM) para la pregunta más frecuente de F1. Aceptar `pet_name` opcional en `get_vaccine_status` y resolverlo server-side ahorraría un turno completo del modelo en el flujo estrella.

### 10.8 🟡 `find_link_candidates` carga todos los Owners de la organización en Python

`identity.py:158-163` itera **todos** los owners no genéricos y compara en memoria. Una clínica con 5 000 clientes importados (caso real del ADR p43) hace un full scan por cada intento de vinculación familiar. Vector de degradación trivial de provocar.

---

## 11. Problemas de memoria

### 11.1 🔴 El resumen rodante no existe

`Conversation.summary` (`models.py:143`) **nunca se escribe**. La capa 2 de la memoria especificada (arquitectura §10) no está implementada. Lo único que ve el modelo son los **últimos 12 mensajes** (`prompts.py:85`).

En una conversación de agendado con ráfagas, 12 mensajes son ~5 intercambios. Todo lo anterior — incluido lo que el cliente dijo que quería — desaparece **en silencio, sin compresión**. El agente no "olvida gradualmente": olvida de golpe y sin saberlo.

### 11.2 🔴 Amnesia total al cerrar por inactividad

`close_inactive_conversations(idle_hours=24)` cierra el hilo; `get_or_create_open_conversation` (`services.py:140-168`) abre uno **nuevo**; `assemble_messages` filtra por conversación. Resultado: a las 24 h y 1 minuto, el cliente que escribe *"oye, ¿al final quedó lo del martes?"* habla con un agente que **no tiene absolutamente nada** de la conversación anterior. Sólo sobrevive `verification_level`.

Y el propio dominio contiene la respuesta (la cita existe), pero nada le dice al modelo que mire ahí. Un cliente recurrente vive esto como "cada vez que escribo, empiezo de cero".

### 11.3 🟠 Los mensajes del staff humano se descartan del contexto

`prompts.py:155` sólo incluye `AUTHOR_AGENT` y `AUTHOR_SYSTEM`. Tras un handoff y devolución, el agente ignora lo que la recepcionista prometió. Puede contradecirla.

### 11.4 🟠 Los resultados de tools no persisten entre turnos

Si el agente ofreció tres horarios en el turno anterior, en el siguiente turno **sólo los recuerda porque están escritos en su propio mensaje de texto**. Si el cliente responde *"la segunda"*, el modelo debe reparsear su propio texto. Frágil, y explica errores de selección de horario.

### 11.5 🟡 `ClientMemoryFact` no existe (correctamente diferido a F3)

De acuerdo con el diferimiento. Pero conviene notar el costo de producto: el agente **nunca aprende nada** del cliente. "Siempre prefiero por la tarde", dicho cinco veces, se olvida cinco veces.

### 11.6 🟡 Lo que la memoria hace bien

No copia estado de negocio: lee citas y vacunas en vivo. Ese principio (R12) está respetado y es correcto. El problema es la memoria **conversacional**, no la de negocio.

---

## 12. Problemas de handoff

### 12.1 El handoff es la salida por defecto ante cualquier fricción

Rutas que terminan en humano, contadas en el código: presupuesto agotado (`policy.py:149`), reto de identidad fallido (`policy.py:222`), vinculación familiar fallida (`policy.py:286`), 2 fallos de tool (`planner.py:197`), error del LLM (`planner.py:110`), commit fallido (`planner.py:260`), urgencia, petición explícita (matcher con falsos positivos), acceso restringido de familiar, y la instrucción del prompt de ofrecer humano cuando falte una herramienta.

**Diez caminos hacia el humano y cero caminos hacia "intentémoslo de otra forma".**

### 12.2 El presupuesto es el mayor generador de handoffs (§8.4)

Vale repetirlo aquí porque es la respuesta directa a tu síntoma #3: con 15 llamadas al LLM por conversación y 2–4 llamadas por mensaje del cliente, **el sistema escala por diseño alrededor del quinto mensaje**, independientemente de lo bien que vaya la conversación.

### 12.3 Fallo del LLM escala con el mensaje equivocado

`planner.py:107-116`: ante un error del proveedor, escala y envía `T0_BUDGET` — un mensaje sobre presupuesto para un problema de infraestructura. Menor, pero es el tipo de detalle que revela la naturaleza de máquina.

### 12.4 Escala pero no da contexto al humano

`HumanHandoff` guarda `reason_code` y `reason_detail`, y la conversación queda visible. Pero **no hay resumen para el humano** ("quería mover la cita de Luna del martes; falló la verificación") — la arquitectura §6.9 lo especificaba. La recepcionista tiene que leer el hilo entero para retomar. En hora pico, no lo hará.

### 12.5 Lo que sí justifica handoff (y está bien)

Urgencia médica, petición explícita, identidad ambigua real (≥2 owners), cancelar/mover en nombre de otro, queja formal, pagos. Todos correctos. **El problema no es que escale; es que escala por razones administrativas propias del sistema (presupuesto, fallo de tool, reto mal calibrado) y no por razones del negocio.**

### 12.6 Falta el camino de vuelta

Un handoff es terminal en la práctica: `HUMAN_ACTIVE` silencia al agente indefinidamente. Para dudas de 30 segundos ("¿tienen estacionamiento?") que escalaron por falso positivo, el hilo queda humano el resto del día. Necesita una devolución fácil y visible, y probablemente automática tras N minutos de inactividad del staff.

---

## 13. Problemas de timing y múltiples mensajes

### 13.1 Diagnóstico exacto del síntoma que reportaste

Reconstrucción del caso "Hola" / "Quiero agendar una cita" / "Para mañana":

```
t=0.0   "Hola"                 → Message(pending, available_at=3.0)
t=3.0   worker toma la conversación (lock), marca procesado
t=3.1   policy → RUN_PLANNER → LLM (~4 s)
t=5.0   "Quiero agendar una cita"  → pending, available_at=8.0  [la conversación está LOCKEADA]
t=7.2   respuesta 1 encolada; transacción commitea; lock liberado
t=8.0   worker vuelve a tomar la conversación → responde el mensaje 2
t=9.0   "Para mañana"          → pending, available_at=12.0
t=12.5  worker → responde el mensaje 3
```

Tres respuestas. **La causa no es la ausencia de agrupación** — `_process_one` sí drena todos los pendientes elegibles (`worker.py:78-91`) — sino que:

1. **`available_at = now + 3s` no es un debounce.** Un debounce reinicia la espera con cada mensaje nuevo. Aquí cada mensaje tiene su propio vencimiento fijo y corto; sólo se agrupan mensajes separados por menos de ~3 segundos (copiar-pegar), nunca una persona escribiendo.
2. **No hay re-chequeo al terminar el turno.** Mientras el LLM piensa (3–10 s), llegan mensajes nuevos que ya no pueden influir en la respuesta en vuelo, y que garantizan un turno adicional.
3. **Aunque se agrupen, el Policy Engine sólo ve el último** (§9.1) — así que agrupar sin arreglar eso empeora la seguridad.

### 13.2 La corrección correcta (y por qué es barata)

La crítica C9 del plan descartó los timers con razón. Pero eligió mal el reemplazo. El debounce real **no necesita timers**: es una línea en la ingesta.

**Arquitectura propuesta — "quiet window" sobre la columna que ya existe:**

1. Al ingerir un entrante, **empujar hacia adelante** `available_at` de **todos** los pendientes de esa conversación: `available_at = now + QUIET_WINDOW`. Con `QUIET_WINDOW ≈ 8 s`, la ráfaga humana se agrupa sola. Sin timers, sin jobs, sin cancelaciones: una columna y un `UPDATE`.
2. **Cap absoluto**: `hard_deadline = primer_mensaje + 25 s`, para que un cliente que escribe sin parar reciba respuesta igualmente.
3. **Re-chequeo antes de enviar**: al terminar el turno, si llegó un entrante nuevo **posterior** al que lo disparó, descartar el saliente aún `pending` y volver a planear. Barato: los salientes no se envían dentro del turno, se encolan (`outbound.py`) — hay una ventana natural para descartarlos.
4. **Pasar la ráfaga completa al Policy Engine y al modelo** como un solo turno de usuario, no sólo el último mensaje.
5. **Señales de presencia** (UX-13): marcar como leído al ingerir y activar "escribiendo…" al iniciar el turno. Esto es lo que hace que 8 segundos de espera se sientan atención en lugar de silencio.

Con esto, el caso de arriba produce **una** respuesta: *"¡Claro! Para mañana tengo 11:00 am, 12:30 pm o 4:00 pm — ¿cuál te queda?"*. Que es exactamente lo que haría una recepcionista que ve tres burbujas llegar juntas.

### 13.3 Otros problemas de timing

- **Sin deadline de turno** (§8.7).
- **El nudge depende del ciclo del worker** (cada ~60 ciclos): la cadencia real varía con la carga; puede dispararse tarde o dispararse en ráfaga tras un reinicio.
- **`last_activity_at` se actualiza también con los salientes** (`outbound.py:28`), así que el nudge del propio agente pospone el cierre por inactividad. Comportamiento discutible pero menor.
- **El envío ocurre en el mismo ciclo que el procesamiento** (`run_agent_worker.py:62-63`), lo cual es bueno; pero si el lote de procesamiento es lento, los envíos de todas las clínicas esperan.

---

## 14. Problemas que aún no hemos considerado

Los ordeno por probabilidad de aparecer en el piloto. Los marcados con ▲ no están en ningún documento del proyecto.

| # | Escenario | Qué pasa hoy | Severidad |
|---|---|---|---|
| ▲ 1 | **Cliente escribe antes de estar registrado, la clínica lo registra en mostrador, vuelve a escribir** | Sigue siendo `unknown` para siempre (match sólo al crear el contacto, `services.py:90`) → lo empuja a alta duplicada | Alta |
| ▲ 2 | **Cliente responde a un mensaje con "quote" de WhatsApp** | El contexto citado se pierde por completo (no se extrae `context` del payload de Meta); el agente responde a la frase suelta | Media |
| ▲ 3 | **Reacción con emoji a un mensaje del agente** | Llega como tipo no soportado → `body=''` → llamada al LLM inútil y respuesta confusa | Media |
| ▲ 4 | **Cliente reenvía un mensaje de otra clínica / captura de pantalla** | Imagen sin transcripción → LLM con `'[mensaje sin texto]'` | Media |
| ▲ 5 | **Mensaje editado por el cliente** | Meta lo entrega como evento distinto; el dedup por `wamid` puede tratarlo como nuevo o ignorarlo. GB-2 lo especifica; no hay código que lo maneje | Media |
| ▲ 6 | **El mismo teléfono escribe a dos clínicas del SaaS** | Correcto por diseño (`ContactIdentity` es por org). Pero si ambas clínicas comparten el número de WhatsApp del SaaS por error de provisioning, el guard R1 es la única defensa | Baja/Crítica |
| ▲ 7 | **Cliente pide algo para "el 30 de febrero" o "el martes 32"** | `find_available_slots` → `bad_date`; el modelo lo maneja libremente. Sin plantilla | Baja |
| ▲ 8 | **Dos personas de la misma familia escriben en paralelo desde números distintos sobre la misma mascota** | Dos conversaciones independientes, dos flujos de agendado, sin visibilidad cruzada → doble cita para la misma mascota (el dominio no lo impide: el solape es por veterinario) | Media |
| ▲ 9 | **Cliente insiste tras un handoff** ("¿hola? ¿me atienden?") | `SILENT` — silencio absoluto hasta que un humano entre. Fuera de horario puede ser 12 horas de silencio total tras habérsele prometido atención | **Alta** |
| ▲ 10 | **Cliente escribe a las 23:00** | El agente atiende (correcto, INT-03), pero el sufijo de fuera-de-horario sólo vive en `render_first_reply`, que **no se ejecuta con el agente encendido** → nunca se avisa que está cerrado | Media |
| ▲ 11 | **El proveedor LLM cambia la versión del modelo sin aviso** | Nada lo detecta: el eval nightly no es bloqueante y `prompt_version`/`model_id` no se comparan | Media |
| ▲ 12 | **Cliente pega un texto de 4 000 caracteres** | Entra íntegro al prompt; sin truncado. Coste y ruido | Baja |
| ▲ 13 | **Cliente responde "sí" a un mensaje de hace 3 horas** | El `pending_action` expiró → re-parafraseo (correcto y bien hecho). ✅ Este caso sí está resuelto | — |
| ▲ 14 | **Staff responde desde el teléfono físico de la clínica**, no desde `/inbox` | Meta no envía echo de mensajes salientes por otra vía; el agente no se entera y puede contradecir al humano | Media |
| ▲ 15 | **Cliente cambia de tema con un `pending_action` vivo** | La spec §2.4 exige aviso ("Dejo pendiente lo de la cita…"); no está implementado: el pending queda vivo en silencio y puede ejecutarse con un "sí" posterior descontextualizado | Media |
| ▲ 16 | **El número de la clínica se usa también para marketing** | Sin separación; el opt-out permanente (§9.5) mezcla dominios | Baja |
| ▲ 17 | **Cliente pregunta por un servicio que la clínica no ofrece** | Substring vacío → "no lo encontré" (bien) pero sin oferta alternativa ni handoff | Baja |
| ▲ 18 | **Se acumulan `refs` y `flow` en una conversación muy larga** | JSON creciendo sin tope (§8.6) | Baja |
| ▲ 19 | **La organización cambia su horario a mitad de conversación** | GB-8 lo especifica como carrera aceptada; el código lee configuración viva. ✅ Cubierto | — |
| ▲ 20 | **Cliente con `is_ambiguous`** (2 owners mismo teléfono) | Queda `unknown` → cualquier intención personal escala. Correcto, pero **el cliente nunca entiende por qué** y lo vive como rechazo | Media |

**El #9 merece énfasis**: prometer "en un momento te atiende una persona" y luego no responder absolutamente nada a un cliente que insiste es peor, en percepción, que no haber tenido agente. Necesita al menos un acuse único ("sigo aquí, ya avisé al equipo") y expectativa honesta fuera de horario.

---

## 15. Quick wins

Bajo costo, alto impacto, sin cambio arquitectónico. Ordenados por relación impacto/esfuerzo.

| # | Cambio | Esfuerzo | Impacto |
|---|---|---|---|
| QW-1 | **Usar la zona de la organización en el generador de slots** (`org_today_local` ya existe) | ~1 h | Desbloquea el valor central del producto (H1) |
| QW-2 | **Pasar la ráfaga concatenada a los matchers de seguridad** | ~1 h | Cierra el agujero clínico H2 |
| QW-3 | **`try/except` por conversación + contador de intentos + dead-letter** | ~3 h | Elimina el crash-loop multi-tenant H3 |
| QW-4 | **Alerta a ops en handoff urgente** (reusar el webhook Discord de `core/services.py`) | ~1 h | La urgencia deja de morir en una cola (H4) |
| QW-5 | **Subir `AGENT_MAX_LLM_TURNS_PER_CONVERSATION` a 40** (env, sin código) | 5 min | Elimina el mayor generador de handoffs |
| QW-6 | **Debounce real: empujar `available_at` de los pendientes al ingerir** | ~2 h | Resuelve el síntoma #1 reportado |
| QW-7 | **Match por tokens en el reto del titular** (aceptar nombre de pila único) | ~1 h | Deja de expulsar clientes legítimos |
| QW-8 | **Plantilla determinista para media entrante** (audio/imagen/sticker) antes de invocar al LLM | ~1 h | Segmento >40 años + ahorro de llamadas |
| QW-9 | **Añadir 3–5 ejemplos de conversación al system prompt** | ~3 h | La palanca única más grande sobre "se siente robótico" |
| QW-10 | **Una línea en el prompt: formato WhatsApp `*negritas*`, sin markdown** | 5 min | Elimina asteriscos visibles en producción |
| QW-11 | **Mapear los 400 por `code` real** en vez de asumir `slot_taken` | ~2 h | El agente deja de mentir y los errores se ven en el piloto |
| QW-12 | **Reevaluar el match teléfono→Owner** cuando el contacto sigue `unknown` | ~1 h | Evita expedientes duplicados (▲1) |
| QW-13 | **Emitir T0-GREET también con el agente encendido** (primer mensaje de conversación nueva) + sufijo fuera-de-horario | ~2 h | Recupera la primera impresión decidida por el PO y cumple la spec |
| QW-14 | **Emitir el aviso de privacidad just-in-time** (código ya escrito, sólo hay que llamarlo) | ~1 h | Cierra el hueco legal declarado bloqueante |
| QW-15 | **Ordenar `/inbox` por prioridad + badge visual de urgente** | ~2 h | La recepcionista ve lo que importa |
| QW-16 | **`no_vet` cuando no hay `default_veterinarian` configurado** (en vez de elegir el primero) | 15 min | Evita asignar citas a un veterinario que no las aceptó |
| QW-17 | **Separar `is_blocked` de `proactive_opt_out`** | ~1 h | Deja de silenciar clientes para siempre |
| QW-18 | **Variar el copy de escalado** (4–5 variantes según motivo) | ~1 h | Rompe la sensación de bucle robótico |
| QW-19 | **Incluir mensajes de `human_staff` en el contexto** | 15 min | El agente deja de contradecir a su compañera |
| QW-20 | **Acuse único al cliente que insiste en `HANDOFF_PENDING`** | ~1 h | Elimina el silencio absoluto (▲9) |

**Estimación total del bloque: ~4 días de trabajo.** Cubre los cinco hallazgos críticos y los tres síntomas reportados.

---

## 16. Mejoras de mediano plazo

**MP-1 — Reconstruir el hilo del turno para el modelo** (§8.3). Mensajes `assistant` con `tool_calls` + mensajes `tool` con `tool_call_id`, acumulados durante el turno. Elimina llamadas repetidas, arregla los flujos de 2+ tools, y permite **borrar** el bloque `REGLA ABSOLUTA DE TURNO` del prompt. ~2 días.

**MP-2 — Botones interactivos de WhatsApp** para selección de horario y confirmación tier-2. Elimina la ambigüedad del matcher es-MX, ahorra una llamada al LLM por confirmación, y sube drásticamente la tasa de completado. Requiere extender `providers.py` y un tipo de saliente nuevo. ~3 días. **Probablemente la mejora de producto con mayor ROI del backlog.**

**MP-3 — Resumen rodante + continuidad entre conversaciones.** Escribir `Conversation.summary` cuando la ventana se llena, y al abrir una conversación nueva sembrar el contexto con: resumen de la última conversación del contacto (≤7 días) + citas futuras del cliente. Convierte la amnesia de 24 h en continuidad. ~3 días.

**MP-4 — Reescritura completa del system prompt con evaluación A/B.** Versionado real: correr el eval nightly contra `v5` y `v6` y comparar. Sin esto, cada cambio de prompt es fe. ~3 días incluyendo el arnés de comparación.

**MP-5 — Rejilla de disponibilidad correcta** (intervalos con duración, no `start_time` exactos) y **soft-hold de 15 minutos** para el slot propuesto. Elimina el bucle "se acaba de ocupar". El soft-hold es una tabla pequeña con expiración; el dossier lo listó como deuda conocida, y con dos clínicas concurrentes se cobra rápido. ~3 días.

**MP-6 — Transcripción de audio.** El trigger de UX-14 (>15 % de entrantes) se cumplirá casi con certeza. Whisper (o el proveedor equivalente) → texto → router normal, como ya está especificado. ~2 días.

**MP-7 — Métricas de calidad conversacional**: turnos por resolución, tasa de repregunta, tasa de abandono por etapa, longitud media, latencia real p50/p95, y muestreo semanal de 20 transcripts revisados por una persona. Sin esto no hay ciclo de mejora. ~2 días.

**MP-8 — Escalera intermedia antes del handoff**: reformular una vez, ofrecer alternativa concreta, y sólo entonces escalar. Aplicable a fallo de tool, presupuesto y reto de identidad. ~2 días.

**MP-9 — Resumen para el humano en cada handoff** (2 líneas generadas: qué quería, qué se intentó, por qué se escaló). ~1 día.

**MP-10 — Aislamiento operativo del worker**: transacción por conversación, deadline de turno, y separación del envío saliente en su propio ciclo. ~2 días.

**MP-11 — Filtrar el registry de tools por estado y verificación.** Menos errores de selección, menos tokens. ~1 día.

**MP-12 — Unificar la normalización telefónica** en una sola función (D4) y consolidar la configuración de clínica en una sola fuente (D5, completar la migración a ADR p53). ~2 días.

---

## 17. Mejoras de largo plazo

**LP-1 — Router determinista de intención con modelo barato** antes del planner. La spec prometía 40–60 % de mensajes resueltos sin el modelo capaz; hoy se resuelve mucho menos. Un clasificador barato + plantillas cubre saludos, agradecimientos, horarios y ubicación con latencia de décimas de segundo.

**LP-2 — Suite de evaluación conversacional con jueces LLM** sobre dimensiones de tono (calidez, brevedad, naturalidad, ausencia de jerga), corriendo en cada cambio de prompt o de modelo. Es la única forma de que "no suena robótico" sea un criterio verificable y no una opinión.

**LP-3 — Memoria de cliente (`ClientMemoryFact`)** con preferencias declaradas. F3 según el plan; correcto.

**LP-4 — Proactividad (F3)**: recordatorios de cita y de refuerzo de vacuna. **Aquí está el ROI real del producto** (reducción de no-shows, medible con `status-breakdown` ya existente). Todo lo anterior es condición para llegar aquí con credibilidad.

**LP-5 — Segundo canal** (webchat del sitio de la clínica). El núcleo ya es canal-agnóstico; el adaptador es trivial. Buen movimiento comercial de bajo costo.

**LP-6 — RLS en base de datos** (ADR p23). El agente es el primer actor no humano de escritura; sube la prioridad del ítem ya planeado.

**LP-7 — Decisión formal sobre el proveedor LLM y el tratamiento de datos.** Sigue abierta y es la única deuda del piloto que no se resuelve con código.

---

## 18. Cambios que NO recomendaría hacer

Tentaciones razonables que empeorarían el sistema. Las listo porque tras una auditoría como esta, la reacción natural es rediseñar de más.

| # | No hacer | Por qué |
|---|---|---|
| N-1 | **Abandonar el loopback HTTP por llamadas directas a `services.py`** | Perdería validadores de tenant (viven en serializers, ADR p14), RBAC y sanitización. El problema real es *dónde* se ejecuta (dentro de una transacción), no *cómo*. Arregla la transacción, conserva el loopback |
| N-2 | **Introducir Celery/Redis como broker** | ADR p41 lo prohíbe y con razón; el volumen no lo justifica ni de lejos. El worker actual necesita `try/except` y contador de intentos, no un framework |
| N-3 | **Dejar que el LLM genere el parafraseo de confirmación** | Es la protección más valiosa del sistema. No tocar jamás |
| N-4 | **Quitar el reto de identidad para reducir fricción** | Es la única barrera entre un número reciclado y el expediente de otra familia. El problema es la *tolerancia* del match, no su existencia |
| N-5 | **Dar al agente acceso a lectura del expediente clínico (T4)** | Q8 sigue siendo correcta. Identidad débil × PII clínica × proveedor externo = riesgo máximo con demanda marginal |
| N-6 | **Permitir cancelación masiva** | La fricción de una por una es anti-abuso y anti-arrepentimiento. Bien decidido |
| N-7 | **Poner un nombre propio al asistente** ("Soy Coco") | La decisión del PO del 2026-07-15 es correcta: personificar y luego ser descubierto destruye más confianza de la que la calidez gana. La calidez se consigue con ejemplos en el prompt, no con nombre |
| N-8 | **Volver a la FSM de 7 estados o a los tiers 3/4** | La simplificación del plan v1.1 fue acertada. Nada en el uso real los pide |
| N-9 | **Reintroducir una tabla de cola separada** | `Message.status` como cola funciona. Lo que falta es `attempts` en el entrante — una columna, no una tabla |
| N-10 | **Fusionar `apps/agent` y `apps/channels`** | La asimetría de costos sigue vigente (separar después, con datos en producción, es caro; separar de más es gratis) |
| N-11 | **Un modelo más grande como primera respuesta a "suena robótico"** | El registro robótico viene del prompt, del historial mal ensamblado y de las plantillas repetidas. Un modelo mejor sobre el mismo prompt sonará igual de robótico y costará más. Arregla el prompt primero, mide, y sólo entonces evalúa el modelo |
| N-12 | **Bloquear el eval nightly en CI** | Es no determinista; bloquear con él genera flakiness y erosiona la confianza en el CI. Correcto como está: informativo, con gate de piloto |
| N-13 | **Ampliar el alcance del agente antes del piloto** (INT-21-bis, más lecturas) | La lista de arreglos pendientes de lo ya construido es más valiosa que cualquier capacidad nueva |

---

## 19. Riesgos de sobreingeniería

Dónde el proyecto ya construyó de más, y dónde está a punto de hacerlo.

**S-1 — La documentación pesa más que el sistema.** Seis documentos, ~2 800 líneas de diseño para ~10 700 líneas de código, con contradicciones entre ellos (la spec dice que T0-GREET es literal; el código no lo emite). **Documentación que diverge del código es peor que no tener documentación**, porque genera confianza infundada. Recomendación: consolidar en dos documentos vivos (contrato funcional + módulo) y archivar los tres restantes marcados como histórico.

**S-2 — Cuatro niveles de verificación, tres en uso.** `staff_verified` no tiene ninguna ruta que lo produzca. Es un enum con un valor muerto.

**S-3 — El reto triple familiar es el flujo más complejo del sistema para un caso no medido.** Tres factores, dos etapas, candidatos sembrados sin oráculo, anti fuerza bruta, restricción de cancelación, revocación en bandeja. Elegante y probablemente correcto — pero **nadie sabe todavía con qué frecuencia ocurre**, y su presencia hace que `link_family_member` esté en el menú de 13 tools que el modelo ve en cada llamada. Habría sido razonable arrancar con handoff y construirlo con datos.

**S-4 — Métricas de negocio antes del primer usuario.** `metrics.py` calcula embudo, conversión y abandono para un piloto que no ha empezado, mientras que las métricas de calidad conversacional —las que dirán si el producto sirve— no existen. Se midió lo fácil, no lo importante.

**S-5 — Auditoría por tool con redacción y `domain_object_public_id`** es de nivel bancario para un piloto de una clínica. No lo quitaría (es barato de mantener y valioso para el auditor externo), pero es un ejemplo del patrón: **rigor máximo en la capa de control, rigor cero en la capa de experiencia**.

**S-6 — Riesgo prospectivo: reaccionar a esta auditoría con un rediseño.** Ninguno de los cinco hallazgos críticos requiere cambio arquitectónico. Son entre una hora y tres horas de trabajo cada uno. La tentación de "aprovechar para rehacer el pipeline" sería el error más caro que se puede cometer ahora.

---

## 20. Recomendación priorizada antes del piloto

### Puerta 0 — Bloqueantes absolutos (no encender con clientes reales sin esto)

**~2 días de trabajo.**

1. **QW-1** — Zona horaria de la organización en el generador de slots. *Sin esto el producto no hace lo que promete.*
2. **QW-2** — Matchers de seguridad sobre la ráfaga completa. *Sin esto una urgencia puede pasar desapercibida.*
3. **QW-3** — Aislamiento de fallos del worker (try/except + intentos + dead-letter). *Sin esto un mensaje raro deja mudas a todas las clínicas.*
4. **QW-4 + QW-15** — Alerta a ops en urgencia + prioridad visible en `/inbox`. *Sin esto la urgencia detectada no llega a un humano.*
5. **QW-16** — `no_vet` explícito si no hay veterinario configurado. *Sin esto se agendan citas a nombre de quien no aceptó.*
6. **QW-14** — Aviso de privacidad just-in-time (el código ya existe). *Declarado bloqueante por la propia consulta legal A1-1.*

### Puerta 1 — Calidad mínima de experiencia (encender con estos, o el piloto medirá el producto equivocado)

**~3 días.**

7. **QW-6** — Debounce real de ventana silenciosa (+ señales de presencia si el proveedor lo permite). *Resuelve el síntoma #1.*
8. **QW-9 + QW-10 + poda del prompt** (§7.2/7.4). *Resuelve el síntoma #2.*
9. **QW-5 + QW-18 + QW-20** — Presupuesto a 40, copy de escalado variado, acuse al cliente que insiste. *Resuelve el síntoma #3.*
10. **QW-7 + QW-12** — Reto de identidad tolerante + reevaluación del match teléfono→Owner. *Evita expulsar y duplicar clientes.*
11. **QW-8** — Plantilla para audio/imagen. *El primer cliente mayor de 40 va a mandar una nota de voz.*
12. **QW-11** — Mapeo honesto de errores 400. *Para que el piloto muestre los problemas en vez de esconderlos.*
13. **QW-13** — Saludo institucional + aviso de fuera de horario con el agente encendido.
14. **QW-17 + QW-19** — Opt-out no destructivo + contexto del staff humano.

### Puerta 2 — Durante el piloto (primeras dos semanas, con datos reales)

15. **MP-1** (hilo de tools) y **MP-7** (métricas de calidad) — arrancar de inmediato; el resto se prioriza con lo que muestren.
16. Medir sin falta: % de entrantes de audio, distribución de motivos de handoff, turnos por resolución, latencia p50/p95, tasa de "se acaba de ocupar", y **muestreo humano de 20 transcripts por semana**.
17. **MP-5** (rejilla + soft-hold) si la tasa de colisión supera el 5 %; **MP-6** (transcripción) si el audio supera el 15 %; **MP-2** (botones) en cuanto haya un hueco — no esperaría a un trigger para este.

### Criterio de encendido que recomendaría al PO

> Encender con **una** clínica, con `AgentSettings` completamente configurado (horario real, veterinario por defecto, dirección, teléfono), tras **48 h de ensayo con números propios cubriendo los 20 escenarios de §14**, con la recepción vigilando `/inbox` en horario y el kill switch a mano.
>
> **Abortar y apagar** si en las primeras dos semanas ocurre cualquiera de: una urgencia no detectada o no atendida en <15 min, una cita creada con datos distintos a los confirmados, una fuga de datos entre clientes, o una tasa de handoff sostenida >50 %.

### Lo que esta auditoría no puede responder

Tres cosas que sólo el piloto dirá, y que ninguna cantidad de revisión previa sustituye: **si el tono resultante le gusta a un cliente mexicano real**, **cuántos audios llegan de verdad**, y **si la recepcionista confía en el bot lo suficiente para no revisar cada cita**. Todo lo demás de este documento es verificable hoy, en código.

---

## Anexo — Índice de hallazgos por archivo

| Archivo | Líneas | Hallazgo |
|---|---|---|
| `apps/agent/tools.py` | 427-428, 500-502 | H1: zona horaria del servidor en slots |
| `apps/agent/tools.py` | 422-426 | H5: ocupación por igualdad de `start_time`, ignora duración |
| `apps/agent/tools.py` | 636, 767, 896 | 400 → `slot_taken` indiscriminado |
| `apps/agent/tools.py` | 231, 264 | Búsqueda por substring en catálogo/productos |
| `apps/agent/tools.py` | 396-400 | Fallback silencioso al primer VET |
| `apps/agent/tools.py` | 79-88 | `refs` sin poda ni invalidación |
| `apps/agent/tools.py` | 818-823 | Segunda normalización telefónica (permisiva) |
| `apps/agent/planner.py` | 46 | H2: policy evalúa sólo el último mensaje |
| `apps/agent/planner.py` | 101, 189, 209, 213 | Hilo de tools no devuelto al modelo |
| `apps/agent/planner.py` | 107-116 | Error de LLM responde con `T0_BUDGET` |
| `apps/agent/worker.py` | 63-73 | H3: transacción envolviendo el lote + red; sin try/except |
| `apps/agent/worker.py` | 145-162 | Envíos HTTP dentro de una transacción |
| `apps/agent/worker.py` | 100-106 | T0-GREET no se emite con el agente encendido |
| `apps/agent/services.py` | 29 | Falso debounce (`available_at` fijo +3 s) |
| `apps/agent/services.py` | 90-94 | Match teléfono→Owner sólo al crear el contacto |
| `apps/agent/policy.py` | 100-108 | Opt-out bloquea permanentemente al contacto |
| `apps/agent/policy.py` | 149 | Presupuesto como generador principal de handoffs |
| `apps/agent/policy.py` | 213-225 | Escalado tras un solo fallo del segundo factor |
| `apps/agent/policy.py` | 344, 379 | Consultas sin `for_organization()` |
| `apps/agent/policy.py` | 357-359 | Nudge sólo con `pending_action` (no cubre el abandono típico) |
| `apps/agent/identity.py` | 63-73, 129-136 | Match que rechaza el nombre de pila |
| `apps/agent/identity.py` | 76 | `is_verification_current` nunca invocada |
| `apps/agent/identity.py` | 158-163 | Carga de todos los Owners en memoria |
| `apps/agent/prompts.py` | 18-82 | Prompt sin ejemplos, con redundancias y una contradicción de objetivo |
| `apps/agent/prompts.py` | 85, 151-157 | Ventana de 12 mensajes sin resumen; staff humano excluido |
| `apps/agent/tier0.py` | 97, 113, 156 | `T0_PRIVACY` y `T0_OUT_MEDICAL` definidas y nunca usadas |
| `apps/agent/matchers.py` | 47-52 | Falsos positivos de petición de humano |
| `apps/agent/matchers.py` | 149 | `is_bare_greeting` nunca usada (saludo va al LLM) |
| `apps/agent/models.py` | 140-143 | `flow` sin whitelist/tope; `summary` nunca escrito |
| `apps/channels/views.py` | 109-110 | Media sin plantilla determinista |
| `frontend/src/pages/inbox/index.jsx` | 35-41 | Sin prioridad, sin no leídos, sin notificación |
| `backend/config/settings.py` | 482 | `TIME_ZONE='UTC'` (origen de H1) |

---

*Auditoría realizada sobre la rama `develop` el 2026-07-24. Sin cambios de código. Las estimaciones de esfuerzo suponen una persona familiarizada con el código.*
