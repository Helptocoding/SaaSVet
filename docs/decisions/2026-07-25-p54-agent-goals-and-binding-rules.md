# ADR p54 — Conversación por objetivos y conservación vinculante en el agente

> **Enmienda B0 (2026-09-13), vigente para esta release.** Mientras rige B0, los goals y la confianza de slots no habilitan WRITE. Se conservan sus validadores/lifecycle; la salida insegura cubierta por el corpus deriva a plantilla/humano sin retry de redacción. El filtro temporal no demuestra grounding ni sensibilidad clínica completa. B2/B5 y B6 reemplazarán las fronteras correspondientes; no se introduce un motor de workflows.
> Alcance, pruebas, límites y rollback: [acta B0](../implementacion-b0-agente-whatsapp-2026-09-13.md). El resto del ADR conserva sus decisiones salvo esta contención temporal.

**Fecha**: 2026-07-25
**Estado**: ACEPTADO (implementado en `develop`: `9bce13c`, `0767eb9`, `06e6edc`)
**Contexto de producto**: subsistema del agente WhatsApp, tras la [auditoría conversacional](../whatsapp-agent-auditoria-conversacional-2026-07-24.md) y el plan [É-F3](../whatsapp-agent-epica-f3-conversacion-por-objetivos.md)

---

## Contexto

Con É-F2 el agente ya agendaba, pero la auditoría encontró dos problemas de
fondo que no eran bugs sueltos:

1. **El agente no perseguía objetivos.** Funcionaba como
   `mensaje → intent → tool → respuesta`: cada turno re-derivaba la intención
   desde una ventana de 12 mensajes, y las herramientas de escritura eran
   todo-o-nada. Faltando un dato, el sistema **calculaba qué faltaba y lo
   tiraba**, dejando al modelo dos salidas: no llamar (y re-derivar todo al
   turno siguiente) o inventar lo que faltaba. La capa de objetivos estaba
   diseñada desde el inicio (`whatsapp-agent-architecture.md` §7.3:
   `flow.name` + `flow.slots`) y **nunca se implementó**.

2. **Las reglas duras vivían solo en el prompt.** G1 (no inventar datos), G2
   (cero consejo médico), G3 (no prometer) y G7 (sin datos internos) eran
   instrucciones al modelo. Una instrucción es *advisoria*: el modelo puede
   desobedecerla y nadie se entera. En un dominio clínico eso no basta.

Añadido a lo anterior, la configuración de la clínica tenía **dos superficies
de escritura** para el horario (`OrganizationSchedule` de ADR p53 y
`AgentSettings.business_hours`), con la precedencia aplicada de forma desigual
—la plantilla de urgencia y el aviso de fuera de horario leían solo el legacy—.

## Decisión

### 1. Capa de objetivos persistida (`ConversationGoal`)

Modelo propio, no un blob en `Conversation.flow`: un JSON no se agrega y esto
tiene que servir para analytics (embudo por objetivo y **por slot**). Sigue el
patrón de ciclo de vida de `HumanHandoff`.

- **Estado explícito**: `active | paused | completed | cancelled | handoff`.
  Constraint parcial: **como máximo un objetivo abierto por conversación**
  (espejo de `cashsession_one_open_per_user`).
- **El sistema es dueño del checklist**: `required_slots` y `missing` son
  código. El modelo solo redacta la pregunta.
- **Contrato de slot mínimo: nombre + validador.** Sin extractores: el LLM
  propone el valor y el código lo valida/normaliza.
- **Confianza por slot**: el modelo acompaña cada dato con
  `<slot>_confidence`; por debajo de `AGENT_SLOT_CONFIDENCE_THRESHOLD` (0.70)
  el slot **no se llena** y el agente lo confirma con el cliente. Es un filtro
  **en serie** con el validador, no una alternativa.
- **Catálogo cerrado de 4 objetivos**, solo multi-turno (agendar, alta+agendar,
  cancelar, reagendar). Las lecturas de un turno no llevan objetivo.
- Las herramientas de escritura pasan a `required: []`: aceptan llamadas
  parciales y persisten lo válido.
- **Escalada semántica**: 3 turnos sin llenar un solo slot ⇒ handoff. Sustituye
  al presupuesto contable de llamadas al LLM como disparador principal.

La capa vive **después** del Policy Engine y **antes** de la confirmación
tier-2: no toca ninguna barrera de control existente (parafraseo por plantilla,
ejecución de args staged, TC-SEC-03).

### 2. Conservación vinculante (`agent/guards.py`)

Las reglas verificables en código se mueven del prompt al runtime, sobre el
texto **ya generado** y antes de encolar el saliente:

| Regla | Verificación |
|---|---|
| G1 | Todo importe citado debe aparecer en los resultados de herramientas del turno |
| G2 | Patrones de dosis/diagnóstico/minimización de síntomas |
| G3 | Patrones de promesa (devoluciones, descuentos, gratuidad) |
| G7 | UUIDs y jerga interna del sistema |

Una violación dura dispara **un** reintento con instrucción correctiva; si
persiste, el texto **no sale**: plantilla segura + handoff. Las listas son
fuente única (`guards.py`), y la suite de regresión las importa añadiendo su
propia severidad de test.

**Regla de gobierno**: ningún cambio de prompt puede reducir el conjunto de
comportamientos prohibidos. Si una regla sale del prompt, entra al código con
un test que la ancle.

### 3. Fuente única de configuración de clínica

`AgentSettings.business_hours` se **elimina**. `OrganizationSchedule` (ADR p53)
es la única fuente del horario para los huecos que se ofrecen, el "¿abierto
ahora?" y el aviso de cierre; `Organization` lo es del teléfono (incluida la
plantilla de urgencia), dirección, mapa e indicaciones.

`AgentSettings.faq_facts` sobrevive **solo** para hechos sin campo propio
(estacionamiento, aviso de privacidad…): el serializer rechaza con 400 las
claves reservadas que ya se editan en Configuración.

Semántica deliberada: **sin horario configurado** → `is_open_now` devuelve
`None` y no se antepone aviso (G1: no se inventa nada); **configurado pero
cerrado** → `False`, y el aviso sí se emite.

## Alternativas descartadas

1. **Extractores deterministas por slot** (parsers de fecha/hora es-MX en el
   dominio). Es un pozo sin fondo y el modelo ya hace bien esa tarea; lo que no
   se puede es *confiar* en el resultado — para eso está el validador. Decisión
   del PO: slot = nombre + validador, nada más.
2. **Que el objetivo sepa preguntar** (`question_hint` por slot). En cuanto el
   dominio redacta preguntas se convierte en un motor de diálogo y arrastra
   copy, tono y localización a una capa que debe ser estructural. El objetivo
   publica `missing`; cómo se pregunta es del modelo.
3. **Objetivos en `Conversation.flow` (JSON)**. Más barato de escribir y
   inservible para medir: el embudo por slot —lo más accionable— exige agregar.
4. **Confiar solo en el prompt para las reglas duras.** Rechazado: advisorio ≠
   vinculante. El prompt se acortó *y* el sistema quedó más estricto.
5. **Conservar `business_hours` como fallback.** Mantiene dos superficies de
   escritura del mismo dato. Se retira aprovechando que no hay clínicas reales
   en producción — con datos encima habría exigido migración de horarios.
6. **Un motor de diálogo genérico** (DSL de slots, grafo de estados). YAGNI: 4
   objetivos como dicts de Python, ~200 líneas. Añadir el quinto cuesta una
   tarde; mantener un framework cuesta en cada revisión.

## Consecuencias

- (+) Una interrupción **pausa** el objetivo en vez de destruirlo: la spec §2.7
  pasa de aspiración a comportamiento (era inejecutable sin estado persistido).
- (+) Anti-repetición real (`asked` por slot): el tic más reconociblemente
  robótico deja de ocurrir por olvido.
- (+) El embudo se mide sobre lo que pasó (`ConversationGoal`) y no se infiere
  de nombres de herramienta; `slots_atorados` dice **en qué dato** se pierde la
  gente.
- (+) Cuatro reglas de seguridad dejan de depender de la obediencia del modelo.
- (−) Una tabla nueva y una migración destructiva (`business_hours`). La
  segunda solo es barata **ahora**; documentado en el commit.
- (−) El guard puede bloquear un texto legítimo (falso positivo) y escalar sin
  necesidad. Mitigado calibrando los patrones para producción (p. ej. `dale`
  es un sí en México, no una posología) y dejando la severidad extra en tests.
- (−) Con `required: []` el modelo puede llamar una herramienta sin datos. El
  objetivo lo absorbe (devuelve `missing`) y el tope de tools por turno lo
  acota.

## Evolución prevista (no implementar ahora)

- Quinto objetivo (alta de mascota para cliente existente, INT-21-bis): copiar
  una entrada del catálogo.
- Botones interactivos de WhatsApp para elegir horario y confirmar: eliminarían
  la ambigüedad del matcher es-MX y una llamada al LLM por confirmación.
- `faq_facts` desaparece si `Organization` gana un campo de FAQ libre (decisión
  de p53 Fase 2).
- Reajuste del umbral de confianza con datos del piloto (`agent_quality`).
