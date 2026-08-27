# Guiones de prueba manual — agente de WhatsApp

**Uso**: los mensajes los escribe una **persona** al agente real y observa qué
hace. Este documento no ejecuta nada ni declara PASS/FAIL: describe qué enviar,
qué contestar según lo que pregunte el agente, y qué revisar después en el
sistema.

**Estado**: bloque 1 de N. Cubre las familias **Crear cita** y **Gestionar cita
existente**. Los siguientes bloques se añaden a este mismo archivo.

---

## Modalidades

| Modalidad | Cómo se prepara |
|---|---|
| **Cliente conocido** | Escribir desde el teléfono asociado a Andrés. Tiene mascotas, citas y posiblemente vacunas. |
| **Cliente nuevo** | Resetear la identidad del contacto **y** cambiar el teléfono de la ficha de Andrés, o usar otro número. El agente no debe identificarte como Andrés ni revelar sus datos. |

## Marcadores

Sustituir por datos reales del entorno antes de empezar:

`[MASCOTA_ANDRES]` · `[SEGUNDA_MASCOTA_ANDRES]` · `[FECHA_FUTURA]` ·
`[FECHA_PASADA]` · `[HORA_DISPONIBLE]` · `[HORA_OCUPADA]` ·
`[CITA_EXISTENTE_ANDRES]` · `[PRODUCTO_DISPONIBLE]` ·
`[PRODUCTO_SIN_EXISTENCIA]` · `[PRODUCTO_CON_RECETA]` · `[VACUNA_APLICADA]` ·
`[VACUNA_PROXIMA]` · `[DIRECCION_CLINICA]` · `[HORARIO_CLINICA]`

## Datos del entorno que evitan falsos hallazgos

- **Sábado cierra a las 14:00; domingo cerrado.** Pedir domingo, o las 15:00 de
  un sábado, es *fuera de horario* — no es lo mismo que *ocupado*, y conviene
  no confundir los dos casos al interpretar la respuesta.
- Si Koler ya tiene cita el sábado a las 11:00, sirve a la vez como
  `[CITA_EXISTENTE_ANDRES]` y como `[HORA_OCUPADA]` **de la misma mascota**
  (guion C4).

---

# FÁCILES

## C1 — Cita directa, todo claro

**Modalidad**: cliente conocido · **Dificultad**: fácil

**Preparar**: `[MASCOTA_ANDRES]` existe. `[FECHA_FUTURA]` entre semana.
`[HORA_DISPONIBLE]` libre.

**Objetivo**: camino feliz completo, sin fricción.

**Mensajes** (uno por uno):

1. `hola`
2. `quiero agendar una cita para [MASCOTA_ANDRES]`
3. `el [FECHA_FUTURA]`
4. `a las [HORA_DISPONIBLE]`
5. (si pregunta motivo) `es para vacunas`
6. `si`

**Respuestas según pregunte**:

- Nombre de mascota → `[MASCOTA_ANDRES]`
- Tu nombre → `Andrés`
- Motivo → `vacunas`

**Confirmación**: `si` al resumen.

**Verificar en el sistema**: en Citas aparece la cita con mascota, fecha, hora
y motivo correctos, estado *Programada*. El veterinario asignado es uno activo.

**Señal a observar**: que el acuse final diga **qué** quedó agendado (mascota +
día + hora), no solo «listo».

---

## C2 — Falta la hora

**Modalidad**: ambas · **Dificultad**: fácil

**Preparar**: `[FECHA_FUTURA]` con huecos libres.

**Objetivo**: ver si pide el dato faltante en vez de inventarlo.

**Mensajes**:

1. `necesito cita para [MASCOTA_ANDRES] el [FECHA_FUTURA]`
2. (esperar) `cual me recomiendas?`
3. `esa está bien`
4. `revisión general`
5. `si`

**Respuestas**: si ofrece horarios, elegir el primero que mencione.

**Verificar**: la cita quedó en uno de los horarios que él mismo ofreció.

**Señal a observar**: si ofrece horarios fuera del horario de la clínica, o si
ofrece solo dos o tres cuando el día está casi vacío.

---

## G1 — Consultar mis citas

**Modalidad**: cliente conocido · **Dificultad**: fácil

**Preparar**: `[CITA_EXISTENTE_ANDRES]` activa.

**Objetivo**: lectura simple de agenda propia.

**Mensajes**:

1. `hola, tengo una cita agendada?`
2. `cuando es?`
3. `gracias`

**Verificar**: lo que dijo coincide con Citas (mascota, día, hora).

**Señal a observar**: tras `gracias` no debe iniciar ninguna acción nueva. Y no
debe listar citas de mascotas que no sean tuyas.

---

## G2 — Cancelar sin vueltas

**Modalidad**: cliente conocido · **Dificultad**: fácil

**Preparar**: `[CITA_EXISTENTE_ANDRES]` activa — usar una **desechable**, se va
a cancelar de verdad.

**Objetivo**: cancelación limpia con confirmación.

**Mensajes**:

1. `quiero cancelar mi cita`
2. (si pregunta cuál) `la de [MASCOTA_ANDRES]`
3. `si, cancélala`
4. `gracias`

**Confirmación**: `si, cancélala` al resumen.

**Verificar**: la cita queda en *Cancelada*, y su historial registra el cambio
de estado con motivo.

**Señal a observar**: que el hueco quede realmente libre después — se comprueba
con el guion C3.

---

# MEDIOS

## C3 — Horario que ocupa otra mascota

**Modalidad**: cliente conocido · **Dificultad**: media

**Preparar**: **requiere dato existente** — una cita de **otro cliente o
mascota** en `[HORA_OCUPADA]` el `[FECHA_FUTURA]`, con el único veterinario
disponible. Sin esa cita previa el caso no se reproduce.

**Objetivo**: que diga «ocupado» solo cuando es verdad, y ofrezca alternativa.

**Mensajes**:

1. `quiero cita para [MASCOTA_ANDRES] el [FECHA_FUTURA] a las [HORA_OCUPADA]`
2. (si dice que no hay) `y a qué hora si hay?`
3. `ok esa`
4. `baño`
5. `si`

**Verificar**: no se creó nada en `[HORA_OCUPADA]`; la cita nueva quedó en la
hora alterna.

**Señal a observar**: que ofrezca alternativas **concretas** en el mismo
mensaje en que dice que no hay, en vez de solo negar.

---

## C4 — Ya tiene cita a esa hora

**Modalidad**: cliente conocido · **Dificultad**: media

**Preparar**: **requiere dato existente** — la **misma** `[MASCOTA_ANDRES]` con
una cita activa en `[HORA_OCUPADA]`.

**Objetivo**: distinguir «ocupado por otro» de «ya la tienes».

**Mensajes**:

1. `quiero cita para [MASCOTA_ANDRES] el [FECHA_FUTURA] a las [HORA_OCUPADA]`
2. (según responda) `ah ok, entonces déjala así`

**Verificar**: no se creó una segunda cita. Solo debe existir una para esa
mascota a esa hora.

**Señal a observar**: la redacción exacta. Debe decir que **ya tienes** esa
cita, no que «se acaba de ocupar» — son cosas distintas, y la segunda empuja al
cliente a duplicar.

---

## G3 — Reprogramar

**Modalidad**: cliente conocido · **Dificultad**: media

**Preparar**: `[CITA_EXISTENTE_ANDRES]` activa. `[HORA_DISPONIBLE]` libre otro
día.

**Objetivo**: mover una cita existente sin crear otra.

**Mensajes**:

1. `puedo cambiar la cita de [MASCOTA_ANDRES]?`
2. `me queda mejor el [FECHA_FUTURA]`
3. `a las [HORA_DISPONIBLE]`
4. `si`
5. `gracias`

**Verificar**: **una sola** cita para esa mascota, con la fecha y hora nuevas.
La vieja no debe seguir activa en paralelo.

**Señal a observar**: que el resumen previo diga de dónde a dónde se mueve, no
solo la fecha nueva.

---

## G4 — Cancelar algo ya cancelado

**Modalidad**: cliente conocido · **Dificultad**: media

**Preparar**: **requiere dato existente** — una cita ya en estado *Cancelada*
(sirve la de G2).

**Objetivo**: comportamiento ante una operación sin efecto.

**Mensajes**:

1. `cancela mi cita de [MASCOTA_ANDRES]`
2. (si pregunta cuál, o dice que no hay) `la del [FECHA_FUTURA]`
3. `ah bueno, gracias`

**Verificar**: no aparecen registros nuevos de cambio de estado sobre esa cita.
Nada se «re-cancela».

**Señal a observar**: si pasa el caso a una persona por algo que ya estaba
resuelto, o si dice que canceló algo que ya estaba cancelado.

---

# COMPLEJOS

## C5 — Fecha ambigua, luego pasada, luego corrige

**Modalidad**: ambas · **Dificultad**: compleja

**Preparar**: tener a mano una fecha ya pasada (`[FECHA_PASADA]`).

**Objetivo**: manejo de fechas vagas y de una imposible, sin perder lo ya
capturado.

**Mensajes**:

1. `hola quiero una cita`
2. `para [MASCOTA_ANDRES]`
3. `la próxima semana`
4. (si pide día exacto) `el lunes`
5. `no espera, mejor el [FECHA_PASADA]`
6. (cuando lo rechace) `ah verdad, entonces el [FECHA_FUTURA]`
7. `a las [HORA_DISPONIBLE]`
8. `revisión`
9. `si`

**Punto de cambio de idea**: el mensaje 5 introduce una fecha imposible a
propósito; el 6 corrige.

**Verificar**: una sola cita, en `[FECHA_FUTURA]`. Nada creado en la fecha
pasada.

**Señal a observar**: que tras rechazar la fecha pasada **no vuelva a pedir la
mascota ni el motivo** — ya los tenía. Repreguntarlo todo indica que perdió el
contexto.

---

## C6 — Pide, confirma, dice que no, corrige y agradece

**Modalidad**: cliente conocido · **Dificultad**: compleja

**Preparar**: dos horas libres el mismo `[FECHA_FUTURA]`.

**Objetivo**: el «no» en la confirmación debe deshacer la propuesta, no la
conversación.

**Mensajes**:

1. `agenda a [MASCOTA_ANDRES] el [FECHA_FUTURA] a las [HORA_DISPONIBLE]`
2. (si pide motivo) `desparasitación`
3. (al resumen) `no`
4. `mejor una hora más tarde`
5. (al nuevo resumen) `sí, ahora sí`
6. `gracias`

**Punto de cambio de idea**: el mensaje 3 es un **no** explícito sobre una
propuesta correcta.

**Verificar**: existe **una** cita, en la hora corregida. Ninguna en la hora
original.

**Señal a observar**: dos cosas. Que el `no` no dispare un pase a humano; y que
el `gracias` final no dispare **ninguna** acción nueva.

---

## C7 — Cortesía fragmentada después del recibo

**Modalidad**: cliente conocido · **Dificultad**: compleja

**Preparar**: completar una cita real y esperar el mensaje automático de
recibo con fecha, hora y ubicación.

**Objetivo**: confirmar que una despedida transmitida como ráfaga conserva su
significado conversacional y no reutiliza datos de la cita cerrada.

**Mensajes** (enviarlos con menos de 8 segundos entre cada uno):

1. `muchas`
2. `gracias`
3. `por su atención`

**Verificar**: puede responder cordialmente, pero no consulta disponibilidad,
no propone hora, no muestra resumen de cita y no crea `pending_action` ni otra
cita.

**Evidencia técnica**: una sola `TurnOperationAssessment` anclada al mensaje
3, con los tres mensajes fuente ordenados y veredicto `conversational`.

---

## C8 — Nueva cita real en una ráfaga fragmentada

**Modalidad**: cliente conocido · **Dificultad**: compleja

**Preparar**: completar una cita real y esperar su recibo. Tener una segunda
fecha/hora libre.

**Objetivo**: demostrar que la protección no es un filtro de frases: una nueva
solicitud libre, incluso fragmentada, sí abre una operación nueva.

**Mensajes** (enviarlos con menos de 8 segundos entre cada uno):

1. `también`
2. `quiero agendar otra cita`
3. `para [MASCOTA_ANDRES] el [FECHA_FUTURA] a las [HORA_DISPONIBLE]`
4. (al resumen) `sí`

**Verificar**: existe una segunda cita distinta solo tras el `sí`. Antes del
paso 4 hay exactamente una confirmación nueva; no toma fecha, hora o mascota
de la cita cerrada si faltan en esta solicitud.

**Evidencia técnica**: `TurnOperationAssessment` contiene la ráfaga completa,
queda `authorized`, y el `ConversationGoal` nuevo la referencia.

---

## G5 — Cambias la cita desde el panel mientras conversas

**Modalidad**: cliente conocido · **Dificultad**: compleja

**Preparar**: `[CITA_EXISTENTE_ANDRES]` activa. Panel de Citas abierto en otra
pestaña.

**Objetivo**: el caso de dos personas operando a la vez sobre la misma cita.

**Mensajes**:

1. `quiero mover la cita de [MASCOTA_ANDRES]`
2. `al [FECHA_FUTURA] a las [HORA_DISPONIBLE]`
3. **DETENERSE.** Antes de contestar al resumen, ir al panel y **cancelar esa
   misma cita** a mano.
4. Volver al chat y responder: `si`
5. (según lo que diga) `entonces agéndame una nueva a esa hora`

**Punto clave**: el paso 3 cambia el mundo entre la propuesta y el `sí`.

**Verificar**: la cita **sigue cancelada** — no debe haberse movido ni
«revivido». Si después se pidió una nueva, esa sí debe existir, aparte.

**Señal a observar**: que diga **qué cambió** (que la cita ya estaba cancelada)
en vez de un error genérico o un «listo» falso.

Si se pide la nueva cita del paso 5, comprobar además que se inicia como una
operación nueva autorizada por ese turno, no que reusa el objetivo, mascota u
horario de la reprogramación que el panel invalidó.

---

## G6 — Dos intenciones y cambio de mascota a media conversación

**Modalidad**: cliente conocido · **Dificultad**: compleja

**Preparar**: `[MASCOTA_ANDRES]` y `[SEGUNDA_MASCOTA_ANDRES]`, ambas
registradas. Una cita activa de la primera.

**Objetivo**: cambiar de objetivo y de sujeto sin que se enrede.

**Mensajes**:

1. `hola, cuándo es la cita de [MASCOTA_ANDRES]?`
2. `ok, y quiero agendar otra`
3. `el [FECHA_FUTURA]`
4. `a las [HORA_DISPONIBLE]`
5. `ah no, la cita es para [SEGUNDA_MASCOTA_ANDRES], no para [MASCOTA_ANDRES]`
6. (si pide motivo) `es que se está rascando mucho`
7. `si`
8. `gracias`

**Punto de cambio de idea**: el mensaje 5 cambia la mascota **después** de
haber dado fecha y hora.

**Verificar**: la cita nueva es de `[SEGUNDA_MASCOTA_ANDRES]`. La cita original
de la primera mascota sigue intacta. No debe haber una tercera cita fantasma.

**Señal a observar**: que conserve fecha y hora al cambiar de mascota — volver
a pedirlas indica que reinició el objetivo. Y en el motivo se menciona un
síntoma: observar si lo trata como consulta clínica o solo como texto libre.

---

## Cómo reportar

Al reportar algo raro, indicar **el ID del guion y el número de mensaje**
(p. ej. «G5, mensaje 4»). Con eso se localiza la conversación exacta y su
traza de herramientas.

## Bloques pendientes

Registro de mascota/cliente · Vacunas · Productos y compra · Información de la
clínica · Urgencias y límites clínicos · Identidad, privacidad y mala
intención · Conversación compleja.
