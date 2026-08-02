"""
agent/situation.py — Hechos de SITUACIÓN (ADR p56 §2, É-F5 Fase 1).

Junto a los hechos de CONTROL (qué se prometió, qué falta, quién está
verificado) el sistema necesita saber **qué está haciendo esta persona con este
mensaje y cómo llega**. Nada de esto llama a una herramienta ni cambia un
permiso; todo esto cambia **cómo se habla**, que es la mayor parte de lo que el
cliente percibe como calidad.

Antes de este módulo, el sistema ya sabía detectar que el cliente estaba
molesto (`matchers.is_complaint_or_meta`) y su único consumidor era decidir si
se anteponía un aviso de fuera de horario. Se detectaba y no se representaba.

CONTRATO (ADR p56, invariantes 1, 2 y 2-bis):

1. **Ninguna función de decisión lee esto.** `arbiter.py` y las salvaguardas de
   `policy.evaluate` no pueden importar este módulo — hay un gate estático que
   pone CI en rojo si ocurre. Es el simétrico del gate de R13: un hecho de
   control que el árbitro no lee es código muerto; un hecho de situación que una
   decisión lee **es un bug**.
2. **No gatea nada** — ninguna capacidad, tool, escalada ni permiso — **y
   tampoco obliga al modelo**: es información disponible, no una obligación de
   respuesta. Si obligara, el gate se reconstruiría socialmente y el resultado
   sería el tic del asistente ansioso (tres líneas empáticas donde sobraban
   cuatro palabras).
3. **Nunca compite con una salvaguarda.** «Estoy desesperada, mi perro no
   respira» es urgencia, primero, siempre, sin pasar por el modelo. Este módulo
   corre DESPUÉS de los cortacircuitos, jamás antes.

Por qué no se valida nada de lo que produce: **equivocarse leyendo el ánimo de
alguien no rompe nada.** Todo el aparato de validadores y umbrales existe porque
un dato mal capturado sí rompe cosas. No validar es aceptable *precisamente
porque* esto no puede alcanzar una decisión — y no dejarlo alcanzar una decisión
es lo que hace innecesario validarlo. Quitar una mitad obliga a añadir la otra.

Coste: **cero llamadas al modelo.** Todo sale de matchers que ya existen y de
señales derivables sin leer lenguaje.
"""
from . import matchers

# Se disculpa o admite que se explicó mal. Un humano contesta «no te
# preocupes» y sigue; hoy el sistema no tiene dónde registrarlo.
_APOLOGY_LEMMAS = (
    'perdon', 'perdona', 'disculpa', 'disculpame', 'sorry', 'mi culpa',
    'me explique mal', 'no me explique bien', 'creo que me explique mal',
    'perdon por preguntar', 'perdon por tanta pregunta',
    'perdon por preguntar tanto', 'lo siento',
)

# Pregunta por el PROCESO, no por la clínica. Es la señal de la conv 13:
# «¿para qué necesitas eso?» merece una respuesta, no un contador de desvíos.
_PROCESS_QUESTION_LEMMAS = (
    'para que', 'pa que', 'por que necesitas', 'para que necesitas',
    'para que lo quieres', 'para que sirve', 'es necesario', 'es seguro',
    'tengo que darte', 'y eso para que', 'que van a hacer con',
)

# Insiste: repite la petición porque no obtuvo lo que pedía.
_INSISTENCE_LEMMAS = (
    'ya te dije', 'te lo dije', 'ya te habia dicho', 'otra vez lo mismo',
    'te estoy preguntando', 'te estoy diciendo', 'ya te lo dije',
    'sigo esperando', 'ya lo pregunte',
)


def read(conversation, burst_text, *, goal=None, first_contact=None):
    """Qué está haciendo esta persona con este mensaje. **Función PURA.**

    No escribe estado, no decide nada, no llama a nadie. Devuelve un dict
    ESPARSO —solo lo que es cierto— en español semántico, para que viaje al
    modelo como dato legible y no como clave interna.

    `goal` y `first_contact` se reciben **ya calculados** por quien sabe
    calcularlos, igual que hace el árbitro con sus hechos (p55 A3): así este
    módulo no toca el ORM y el gate estático de pureza es trivial de sostener.
    """
    text = burst_text or ''
    normalized = matchers.normalize(text)
    facts = {}

    if matchers.is_complaint_or_meta(text):
        facts['se_queja_o_habla_de_la_conversacion'] = True
    if _has_any(normalized, _APOLOGY_LEMMAS):
        facts['se_disculpa'] = True
    if _has_any(normalized, _PROCESS_QUESTION_LEMMAS):
        facts['pregunta_por_que_le_pedimos_esto'] = True
    if _has_any(normalized, _INSISTENCE_LEMMAS):
        facts['insiste_porque_ya_lo_habia_dicho'] = True
    if matchers.is_thanks(text):
        facts['agradece'] = True

    if first_contact:
        facts['es_su_primer_mensaje_con_nosotros'] = True

    # Señales derivadas, sin leer lenguaje: cuánto lleva sin llegar a nada y
    # qué le hemos pedido de más. `stall_turns` mide turnos sin avance del
    # compromiso; `asked` cuenta cuántas veces se pidió cada dato.
    if goal is not None:
        if goal.stall_turns >= 2:
            facts['lleva_varios_turnos_sin_obtener_lo_que_pidio'] = True
        repetidos = sorted(
            slot for slot, veces in (goal.asked or {}).items() if veces >= 2)
        if repetidos:
            facts['datos_que_ya_le_pedimos_mas_de_una_vez'] = repetidos

    return facts


def _has_any(normalized, lemmas):
    return any(lemma in normalized for lemma in lemmas)
