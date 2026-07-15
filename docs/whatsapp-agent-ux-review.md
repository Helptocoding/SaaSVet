# Revisión UX / ventas / operación de la especificación funcional del agente

**Fecha**: 2026-07-14
**Revisa**: [`whatsapp-agent-functional-spec.md`](whatsapp-agent-functional-spec.md) (v1.1)
**Perspectiva**: cliente de clínica veterinaria mexicana + dueño de clínica (conversión y percepción de servicio) + operación real de recepción. **No** se revisa código ni arquitectura; solo comportamiento funcional.
**Resultado**: 16 propuestas de cambio funcional (UX-01..16) + 4 decisiones defendidas que NO deben cambiarse (§5).

> **Resolución 2026-07-15 (Product Owner)** — P0 ratificadas y **aplicadas a la spec** (que quedó CONGELADA para F1), con tres ajustes del PO:
> 1. **UX-01 sin nombre propio**: saludo institucional ("¡Hola! 🐾 Bienvenido a Clínica X…"); personificar ("Soy Coco") induce a asumir persona y decepciona al descubrirse. "Asistente virtual" se revela al preguntar (nuevo INT-06).
> 2. **UX-04 endurecida**: reto **triple** para vinculación familiar (titular + mascota + últimos 4 dígitos del teléfono registrado) — un vínculo permanente merece un factor más. Queda diseñada en la spec (§2.3) para activarse en F2, con revocación en bandeja y notificación al titular cuando existan plantillas (F3).
> 3. **UX-14 con matiz**: la transcripción alimenta el **router normal** — audio con pregunta tier-0 se resuelve sin LLM (Whisper → texto → flujo idéntico).
> Además la spec ganó **§0 Objetivos comerciales** (7 objetivos que gobiernan toda decisión posterior). P1 → F2; UX-10 → F3. Suite F1: 63 casos congelados (93 totales con F2 en borrador).

---

## 0. Veredicto general

La spec es sólida en seguridad y control, pero en varios puntos **suena a sistema, no a recepcionista**: saludo con menú de capacidades y link legal, pregunta abierta de fecha en vez de ofrecer horarios, reto de identidad frágil ante apodos y typos, y un hueco grande de la vida real — **las familias**: hoy el esposo que escribe desde su número no registrado termina creando un expediente duplicado de la misma mascota. Los dos hallazgos con mayor impacto de negocio son **UX-04 (vinculación familiar)** y **UX-06 (oferta proactiva de horarios)**; el de mayor impacto de percepción es **UX-14 (notas de voz)**.

---

## 1. Presentación del agente: transparente, pero cálido

### Hallazgos

1. **T0-GREET actual es un formulario, no un saludo.** "Puedo ayudarte a agendar citas y resolver dudas de horarios y precios" = menú de capacidades (nadie que llama a una clínica escucha eso de una recepcionista). El link del aviso de privacidad **en el primer mensaje** enfría la conversación y, desde un número nuevo para el cliente, un saludo-con-link parece spam (también es mala señal para la calidad de cuenta en Meta, §5 abajo).
2. **Transparencia: mantenerla.** Fingir humano está descartado con razón: la política de mensajería de negocios de Meta exige revelar el uso de automatización, y ser "cachado" destruye la confianza justo con los clientes más valiosos (los que escriben mucho). La transparencia no es el problema; la **frialdad** sí.
3. La spec ya tiene el campo de nombre del asistente (`AgentSettings`, plan §7-C7) pero las plantillas no lo usan.

### Propuestas

**UX-01 — Reescribir T0-GREET (P0, antes de F1).**
- Con nombre propio configurable por clínica, sin menú de capacidades, sin link legal en el saludo:
  > "¡Hola! 🐾 Soy **[[Coco]]**, asistente virtual de **[[Clínica X]]**. Cuéntame, ¿en qué te ayudo?"
- El aviso de privacidad pasa a **just-in-time**: se envía la primera vez que la conversación va a tratar datos personales (antes de un alta INT-21 o antes del primer reto de identidad), en una línea corta + link. Es además mejor práctica LFPDPPP (informar en el momento de la recolección) que un link ritual que nadie abre. ⚠️ Condicionado a la consulta legal (A1-1): si legal exige aviso en primer contacto, se mantiene pero en segunda línea corta, nunca como bloque central.
- Si el primer mensaje del cliente ya trae intención, el saludo se reduce a una línea y se atiende de inmediato (ya especificado — conservar).

**UX-16 — Plantilla "¿eres un robot?" (P0).** Respuesta honesta y simpática + puente: *"¡Sí! Soy el asistente virtual de la clínica 🤖 Puedo agendarte y resolver dudas al momento — y si prefieres, te paso con una persona del equipo."* Nunca evasivas. Test: `TC-UX-16`.

---

## 2. Tolerancia a ortografía, abreviaciones y lenguaje coloquial

### Hallazgos

1. **El matcher de confirmación es demasiado corto para es-MX real.** Faltan afirmativas frecuentísimas ("sale", "sale pues", "simón", "arre", "de una", "está bien", "perfecto", "oki", "sip", "siii", "andale") y — más peligroso — no cataloga las **falsas afirmativas mexicanas**: "ahorita" (≠ ahora), "déjame ver", "luego te digo", "yo te aviso" — ninguna debe ejecutar ni cerrar el flujo.
2. **El reto de identidad es frágil ante la vida real**: la mascota se registró como "Kira" y el cliente escribe "kirita" / "la kira" / "kyra". Match estricto normalizado → 2 "fallos" → handoff. Resultado: cliente legítimo expulsado del autoservicio por un diminutivo. Ese handoff es el peor de todos: el cliente siente que "el sistema no me reconoce **a mí**".
3. Fechas/horas coloquiales sin especificar: "tipo 4", "después de las 5", "en la tarde", "el martes que viene", "cuando puedan".

### Propuestas

**UX-02 — Confirmación en dos etapas (P0).** Matcher ampliado es-MX (lista mantenida de afirmativas y de **no-afirmativas explícitas**: ahorita/déjame ver/luego/yo te aviso → responder "va, aquí queda pendiente — me dices 🙌" sin ejecutar y sin insistir). Sin match → el LLM clasifica {afirmativa | negativa | modificación | otro}; una afirmativa clasificada ejecuta el `pending_action` **tal cual fue parafraseado** (la protección de TC-SEC-03 no cambia: la afirmativa nunca amplía el alcance). Tests: `TC-UX-02a` ("sale pues" ejecuta), `TC-UX-02b` ("ahorita" NO ejecuta ni cierra), `TC-UX-02c` ("va, pero mejor a las 5" = modificación).

**UX-03 — Reto de identidad tolerante (P0).** (a) Normalización fuerte: mayúsculas/acentos + artículos ("la Kira") + typo de distancia 1 en nombres ≥4 letras. (b) Un no-match pide repetición **sin contar como fallo** ("¿me lo repites tal como lo registraron?"). (c) **Segundo factor alternativo**: si la mascota no coincide, aceptar el nombre del titular registrado ("¿a nombre de quién está el registro?") — sigue siendo "el cliente aporta, el sistema verifica" (G4 intacto). (d) Solo 2 fallos **reales** (datos que no coinciden con nada) → E-06. Tests: `TC-UX-03a` (diminutivo simple pasa vía repetición), `TC-UX-03b` (titular como segundo factor), `TC-UX-03c` (2 fallos reales → handoff sin pistas).

**UX-07 — Franjas horarias coloquiales (P1, con F2).** "En la tarde" → filtrar T9 a 12:00–18:00 (buckets mañana/tarde/noche definidos en spec); "tipo 4" → 15:30–16:30; "después de las 5" → ≥17:00; "cuando puedan" / "cualquier hora" → los 3 slots más próximos. Test: `TC-UX-07`.

---

## 3. Familias: varios teléfonos, varias personas por mascota

### Hallazgos — **el hueco más grave de la spec**

1. Caso cotidiano: la señora registró a Luna con su número; **el esposo escribe desde el suyo** → T1 = 0 matches → la spec lo trata como cliente nuevo → INT-21 → se crea **otro Owner y otra "Luna"**. Consecuencia operativa seria: **expediente clínico fragmentado** (historial de vacunas partido en dos mascotas), exactamente el tipo de suciedad de datos que la clínica más resiente. La spec hoy *fabrica* este problema.
2. El flujo INT-21 nunca pregunta si ya son clientes — va directo al alta.
3. No existe noción de "contacto autorizado adicional" — pero la operación real de una clínica funciona así todos los días (mamá, papá, hijos llevan a la misma mascota).

### Propuestas

**UX-05 — Pregunta de tamiz antes de toda alta (P0).** INT-21 arranca con: *"¿Es la primera vez que traen a [[mascota]] con nosotros?"* — barata, natural (una recepcionista la hace siempre), y desvía a UX-04 el caso familiar antes de crear duplicados. Test: `TC-UX-05` (contesta "ya los han atendido" → cero altas).

**UX-04 — Vinculación familiar por reto doble (P1, antes del piloto F2; lectura puede ir en F1).** Desde un número no registrado, si el cliente afirma que la mascota ya es paciente: reto de **dos datos** — nombre del titular registrado **+** nombre de la mascota (ambos aportados por el cliente, nada enumerado — G4 intacto). Ambos coinciden → el número queda vinculado al Owner como **contacto secundario** con `confirmed_in_chat`: puede agendar, confirmar, cancelar, reagendar y consultar citas/vacunas de esa familia.
- **Visibilidad operativa**: el vínculo nuevo aparece señalado en la bandeja (línea "nuevo número vinculado a [[titular]]") y el staff puede revocarlo — el humano conserva la última palabra.
- **Riesgo asumido**: quien conozca titular + mascota puede operar la agenda de esa familia. Amenaza realista = conocidos cercanos; el daño posible (mover/cancelar citas, ver fechas de vacuna) es acotado y auditado. La alternativa (handoff para todo familiar) mata el caso de uso más frecuente después del titular mismo.
- Tests: `TC-UX-04a` (esposo vincula y agenda), `TC-UX-04b` (un dato mal → no vincula, reintento), `TC-UX-04c` (vínculo visible/revocable), `TC-UX-04d` (revocado → vuelve a unknown).

---

## 4. Conversión a citas y servicios (sin ser invasivo)

### Hallazgos

1. **"¿Qué día te queda bien?" es una pregunta abierta que pierde clientes.** Cada turno extra en el flujo de agendado es una fuga. Una buena recepcionista ofrece: "tengo mañana a las 11 o el jueves a las 4".
2. La retención en cancelación ofrece "¿reagendamos?" sin horarios — invita a un "luego te digo".
3. Un flujo de agendado abandonado a la mitad muere en silencio — dinero sobre la mesa dentro de la ventana gratuita de 24 h.
4. El mensaje post-agendado no aprovecha para reducir no-show ni fricción de llegada (dirección, indicaciones).
5. INT-14 (vacuna vencida/próxima) ofrece "¿agendamos?" — bien — pero sin horarios concretos.

### Propuestas

**UX-06 — Ofrecer, no preguntar (P1, con F2).** En INT-20/21, si el cliente no fijó fecha: ofrecer directamente los 2–3 slots más próximos ("¿Te queda bien **mañana jueves 11:00 am** o el **viernes 4:00 pm**?"). Si fijó día pero no hora → directo a slots de ese día (ya especificado). Cambia el paso 3 del flujo INT-20. Test: modifica `TC-INT20-01`.

**UX-11 — Retención con horarios concretos (P1).** INT-23, tras cancelar: *"¿Te propongo fecha nueva de una vez? Tengo [[slot1]] o [[slot2]]"* (T9 en el mismo turno). Test: modifica `TC-INT23-01`.

**UX-08 — Nudge único de flujo abandonado (P1).** Flujo de agendado con slots ya ofrecidos + silencio de 3 h + dentro de la ventana de 24 h → **un** mensaje de recuperación (*"¿Seguimos con la cita de [[Luna]]? Sigue libre el [[jueves 11:00 am]] 🙂"*), máximo 1 por conversación, jamás tras opt-out ni tras negativa. Es mensaje de sesión (iniciada por el cliente), no plantilla pagada, y de bajo riesgo para la calidad de cuenta por su cadencia mínima. Test: `TC-UX-08a` (se envía 1 vez), `TC-UX-08b` (jamás segundo nudge / jamás tras "luego te digo").

**UX-09 — Post-agendado útil (P1).** Tras crear la cita, añadir 1–2 líneas de `faq_facts`: dirección/referencia + indicación de llegada si existe. Reduce no-show y preguntas repetidas. Test: modifica `TC-INT20-01` (elementos obligatorios).

**UX-12 — Guía de tono "recepcionista excelente" (P0, barata).** Añadir a §2.1 de la spec: (a) empatía breve **sin juicio clínico** permitida y deseable ("qué lata, vamos a que la revisen" ✅ / "seguro no es nada" ❌ G2); (b) usar nombre del cliente y de la mascota una vez verificado ("¡Listo, Ana!"); (c) artículo por sexo de la mascota (`Pet.sex`: "la" Kira / "el" Rocky); (d) máx. 1 emoji por mensaje; (e) prohibido el tono de menú/robot ("opción inválida", "no entiendo su solicitud").

---

## 5. Cumplimiento y calidad de cuenta en Meta

### Hallazgos

1. La spec cubre bien: ventana 24 h, opt-out, dedup. Lo que falta es **doctrina de plantillas y frecuencia** para F3 — donde se juega el rating de calidad.
2. Link en primer mensaje (UX-01) — señal de spam evitable.
3. Venta de medicamentos: la política de comercio de Meta restringe la venta de fármacos con receta; INT-12 ya se limita a disponibilidad, pero conviene blindarlo como regla.

### Propuestas

**UX-15 — Doctrina Meta (P1/F3, escribirla ya).**
- **Plantillas F3 estrictamente utility**: copy 100 % transaccional (cita, fecha, mascota, confirmar/mover), cero lenguaje promocional — evita la reclasificación a marketing (costo mayor y daño de rating).
- **Frecuencia**: máx. 1 recordatorio por cita (24 h antes) + los recordatorios de vacuna respetan opt-out y un cap mensual por contacto (propuesto: 2 proactivos/mes).
- **Medicamentos**: el agente nunca cotiza, aparta ni "vende" productos con receta por chat; solo disponibilidad + "requiere receta" (refuerzo de G7/INT-12).
- **Respuesta a todo mensaje entrante** dentro de minutos (el agente lo garantiza) — el tiempo de respuesta alimenta la calidad de cuenta.
- **Nota ops/ventas** (fuera de la spec): display name verificado = nombre real de la clínica; promover entrada por **QR/wa.me** en mostrador y redes (las conversaciones iniciadas por el cliente son la base sana del rating y abren la ventana de servicio).

---

## 6. Otras oportunidades "recepcionista > chatbot"

**UX-13 — Señales de presencia (P1).** Marcar como leído de inmediato y activar el indicador de escritura si el proveedor lo soporta durante el procesamiento. Elimina el "¿me habrá leído?" en los segundos del LLM. (Capacidad del canal, comportamiento funcional — sin cambio de arquitectura.)

**UX-14 — Notas de voz (P1-medible, la brecha de percepción #1).** En México una fracción grande de clientes — sobre todo mayores de 40 — **manda audios por default**. El "¿me lo escribes?" de GB-1 es el momento más chatbot de toda la spec y para ese segmento es fricción real en cada interacción. Propuesta funcional: (a) F0/F1 mantienen GB-1 pero **miden** (`payload_type` ya registra el % de audio entrante); (b) si el piloto muestra >15 % de mensajes de audio, la transcripción de audios entrantes se **re-prioriza como requisito del gate F2** (hoy está pospuesta como C-N4 del plan). El trigger queda escrito y con número — no se decide por intuición.

**UX-10 — Respuesta a recordatorio sin reto (P2/F3, diseñarlo desde ya).** El recordatorio de F3 se envía **al número registrado** sobre **una cita concreta** → la respuesta "sí voy" / "no puedo" trae contexto implícito: INT-22/23/24 operan sobre esa cita **sin reto de identidad** (el reto ahí sería absurdo: el sistema inició la conversación). Test futuro: `TC-UX-10`.

---

## 7. Qué NO cambiar (fricción deliberada — defendida)

| Decisión de la spec | Queja UX aparente | Por qué se queda |
|---|---|---|
| Reto de identidad antes de listar citas/vacunas | "Me pide datos para todo" | Es la única barrera entre un número reciclado y el expediente de otra familia. Con UX-03/UX-04 el reto se vuelve tolerante y natural; eliminarlo es regalar PII. La verificación implícita ya hace que el 80 % de los casos ni lo noten |
| Confirmación con parafraseo antes de toda escritura | "Un paso extra" | Ese paso es el producto: cita mal agendada = cliente que llega en balde = daño real. El parafraseo con fecha absoluta atrapa los malentendidos de "el martes". Un turno extra aquí **gana** confianza, no la pierde |
| Cancelación una por una | "Déjame cancelar todo de un jalón" | Anti-abuso/anti-injection (R7) y anti-arrepentimiento. Caso legítimo de cancelación masiva = raro; el costo son 2 turnos más |
| Transparencia de bot | "Neutral convierte más" | Política de Meta + el costo de ser descubierto >> el beneficio marginal. La calidez se gana con UX-01/12, no con opacidad |

---

## 8. Resumen priorizado

| Prioridad | Propuestas | Cuándo |
|---|---|---|
| **P0** (antes del piloto F1) | UX-01 saludo, UX-02 confirmación es-MX, UX-03 reto tolerante, UX-05 tamiz de alta*, UX-12 guía de tono, UX-16 "¿eres robot?" | Copys + matcher + reglas de spec |
| **P1** (con F2) | UX-04 vinculación familiar, UX-06 ofrecer slots, UX-07 franjas coloquiales, UX-08 nudge único, UX-09 post-agendado, UX-11 retención, UX-13 presencia, UX-14 audio (trigger medible), UX-15 doctrina Meta | La mayoría toca INT-20..24 |
| **P2** (F3) | UX-10 recordatorio sin reto | Al especificar F3 |

\* UX-05 aplica a INT-21 (F2), pero la **pregunta** de tamiz conviene especificarla desde F1 para el puente de INT-13 ("número no registrado").

**Impacto en la suite**: +14 casos nuevos (`TC-UX-*`) y 4 modificados (`TC-INT20-01`, `TC-INT21-01`, `TC-INT23-01`, matchers) → suite v1 pasa de 83 a ~97 casos. La sección §2.3 de la spec (identificación) es la más tocada (UX-03/04/05); §2.4 (confirmación) absorbe UX-02.

**Cambio de modelo de datos implícito**: UX-04 requiere que un Owner pueda tener **varios** contactos (`ContactIdentity` ya es N:1 hacia Owner en el diseño v1.1 — la relación lo soporta; solo se añade el flag de contacto secundario y su visibilidad en bandeja). Ningún otro cambio estructural.

---

*Siguiente paso sugerido: ratificar UX-01..16 y aplicar las P0 como enmienda a la spec funcional antes de congelar el contrato de F1.*
