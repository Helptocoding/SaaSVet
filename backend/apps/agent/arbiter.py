"""
agent/arbiter.py — Desenlace del compromiso (É-F4 Fase 3 · enmienda p56 §5-bis).

Responde UNA pregunta: ***¿qué le pasó al compromiso en este turno?*** No
clasifica el mensaje (eso es un insumo), no redacta (eso es el planner/LLM) y
no aplica los efectos (eso es del planner — ver al final).

**CLASIFICA, no gobierna** (precisión del PO, É-F5 Fase 4). «Gobernar» implica
autoridad; lo que hace es INTERPRETAR el desenlace. Aplicar lo que se deriva de
esa interpretación es del ejecutor — la misma separación que p55 A6 ya exigía.

**Corre AL FINAL del turno, no antes.** Hasta É-F5 Fase 2 era una puerta:
`policy._check_interruption` lo consultaba a mitad de camino y su veredicto
decidía qué leía el cliente. Ahora corre cuando el saliente ya está encolado, y
eso lo vuelve **incapaz por construcción** de afectar lo que el cliente lee.

Dos propiedades que salen de ahí y que antes eran imposibles:

- **Los efectos tocan solo el estado persistente del compromiso**, jamás el
  mensaje ya emitido (invariante de p56 §5-bis). Un `SUPPLANT` no reemplaza la
  respuesta: anota que la promesa quedó suspendida para el turno siguiente.
- **Los veredictos se pueden RECALCULAR sobre conversaciones históricas** sin
  volver a llamar al LLM: comparar versiones del árbitro, validar una regla
  nueva contra tráfico real, medir un cambio arquitectónico. Antes era
  imposible porque el árbitro intervenía — recalcularlo habría cambiado la
  conversación que se pretendía medir.

**El árbitro nunca decide contenido, solo control de flujo.** Prueba para
distinguirlos: ¿se puede renderizar el veredicto en otro idioma, otro tono u
otro canal sin tocar este módulo? Si sí, es control.

    ✗ CONTENIDO   {"action": "ask", "slot": "digits", "text": "¿los 4 dígitos?"}
    ✓ CONTROL     {"verdict": "desviar", "commitment": "family_challenge",
                   "return_to": "digits"}

Los cinco mecanismos que lo mantienen pequeño (`tests/test_arbiter.py` los
hace vinculantes; sin ellos esto es `policy.evaluate` otra vez en seis meses —
203 líneas, 20 pasos, seis metidos con calzador):

    A1  Conjunto de veredictos CERRADO. Un sexto exige ADR.
    A2  Función PURA: cero DB, cero red, cero efectos.
    A3  Recibe hechos YA calculados; no llama matchers ni al ORM.
    A4  Presupuesto de ramas con test que bloquea.
    A5  Cero precedencia interna: la única del sistema (urgencia primero)
        vive ARRIBA, en las salvaguardas de `policy.evaluate`.

Lo que este módulo NO decide, a propósito:

- **Escalar a un humano.** Es una salvaguarda, y las salvaguardas preemptan
  al árbitro (§9.4a): si el árbitro pudiera razonar sobre la urgencia, la
  urgencia pasaría a ser una cuestión de política discutible.
- **El tope de desvíos.** El árbitro juzga UN mensaje ("esto interrumpe");
  que tres desvíos seguidos justifiquen una persona es un juicio sobre el
  PATRÓN, y ese vive en el ejecutor.
"""
from dataclasses import dataclass

# --- A1 · veredictos, conjunto cerrado -------------------------------------
CONTINUE = 'continuar'    # el mensaje avanza el compromiso en curso
DEVIATE = 'desviar'       # interrumpe: se atiende y se vuelve al punto exacto
SUPPLANT = 'suplantar'    # otro compromiso toma el frente; este se ofrece luego
ABORT = 'abortar'         # el cliente lo abandona
ANSWER = 'responder'      # no hay compromiso en juego: se contesta y ya

VERDICTS = (CONTINUE, DEVIATE, SUPPLANT, ABORT, ANSWER)


@dataclass(frozen=True)
class CommitmentView:
    """Foto del compromiso, NO la fila del ORM (A2).

    El árbitro recibe coordenadas, no un objeto con `.save()`: un paso que
    muta estado esconde una decisión dentro de un efecto secundario, y es
    exactamente lo que le quitó la tabulabilidad a `policy.evaluate`.
    """
    name: str
    return_to: str = ''


@dataclass(frozen=True)
class TurnFacts:
    """Hechos del turno, YA calculados por quien sabe calcularlos (A3).

    Que estos tres hechos existan es lo que permite que el cuerpo de `decide`
    sea una tabla y no una cadena de `if`. Cuando aparezca un caso nuevo, lo
    que crece es esta lista de hechos —y los matchers que los producen—, no
    las ramas del árbitro: la complejidad tiene que caer en la capa más plana
    que pueda absorberla.
    """
    # Otro compromiso quiere el frente (el cliente cambió de tema a algo que
    # el sistema sí sabe hacer).
    proposes_other_commitment: bool = False
    # El cliente dijo que no a lo que estaba en curso.
    client_declined: bool = False
    # El mensaje interroga y NO trae la respuesta que el compromiso esperaba.
    interrupts: bool = False


@dataclass(frozen=True)
class TurnVerdict:
    """Qué pasa, sobre qué compromiso y dónde se retoma. Nada más — el cómo
    se dice pertenece al planner."""
    verdict: str
    commitment: str = ''
    return_to: str = ''


def decide(facts, commitment):
    """`(hechos, compromiso) → veredicto`. PURA.

    Cuatro reglas disjuntas por construcción; el orden no es una jerarquía de
    prioridades sino el hecho de que un mensaje no puede ser a la vez una
    negativa y una pregunta sin respuesta (los matchers que producen los
    hechos ya los hacen excluyentes). Si algún día hiciera falta ordenar dos
    veredictos, la señal es que un hecho está mal modelado — no que falte una
    regla (A5).
    """
    if commitment is None:
        return TurnVerdict(ANSWER)
    if facts.proposes_other_commitment:
        return TurnVerdict(SUPPLANT, commitment.name, commitment.return_to)
    if facts.client_declined:
        return TurnVerdict(ABORT, commitment.name, commitment.return_to)
    if facts.interrupts:
        return TurnVerdict(DEVIATE, commitment.name, commitment.return_to)
    return TurnVerdict(CONTINUE, commitment.name, commitment.return_to)


# ---------------------------------------------------------------------------
# Lo que NO vive aquí, y por qué
# ---------------------------------------------------------------------------
# La producción de hechos (`_observe_turn_facts`) y la aplicación de efectos
# (`_apply_verdict`) viven en `planner.py`, no en este módulo.
#
# Se escribieron aquí primero y los gates A2/A3 los rechazaron en la primera
# corrida: producir hechos exige llamar matchers, y aplicar efectos exige tocar
# el ORM. Las dos cosas romperían lo que hace valioso a este módulo — la pureza
# es lo que permite recalcular veredictos sobre conversaciones históricas sin
# base de datos ni proveedor (p56 §5-bis).
#
# El árbitro recibe hechos ya calculados y devuelve un veredicto. Nada más.
