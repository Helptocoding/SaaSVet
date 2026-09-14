"""
test_corpus_conversacional.py — Corpus de regresión conversacional (É-F5 Fase 0).

Las tres conversaciones reales que motivaron el rediseño, reproducidas como
casos ejecutables. Es el sustrato del experimento de la Fase 2: sin corpus, el
cambio no es falsable — y **no hay tráfico real que observar** (todas las orgs
activas son demo, decisión registrada 2026-07-30), así que "mirar producción"
no está disponible.

Filosofía (plan §9 Fase 0, y es la lección de É-F4 Fase 2): **un test que no
puede fallar antes del fix no prueba nada.** Por eso estos casos afirman la
conducta DESEADA y hoy están en rojo, marcados `expectedFailure`:

- CI sigue verde mientras el defecto exista (no bloquea el trabajo en curso).
- El día que la Fase 2 lo corrija, `unittest` reporta **unexpected success** y
  `wasSuccessful()` devuelve False → **CI se pone en rojo** y obliga a quitar
  el decorador. El gate se limpia solo; no depende de que alguien se acuerde.

Las aserciones son de **conducta observable** (qué ve el cliente, qué queda en
la base), nunca de estructura interna: tienen que seguir siendo válidas cuando
la FSM de identidad ya no exista.

Mapa de casos:

| Caso | Origen | Estado hoy | Lo cierra |
|---|---|---|---|
| A · brief | piloto 2026-07-31 | 🔴 rojo | Fase 2 |
| B · conv 12 | `0d56b976` 2026-07-28 | 🔴 rojo | Fase 3 (C7 actúa) |
| C · conv 13 | `85a2a691` 2026-07-30 | 🟢 verde | ya lo cerró É-F4 — aquí protege el fix |
"""
from django.test import TestCase
from django.utils import timezone

from .harness import legacy_write_component
from apps.agent import executor as executor_module
from apps.agent.llm import LLMResult
from apps.agent.models import (
    AgentSettings,
    ContactIdentity,
    Conversation,
    ConversationGoal,
    HumanHandoff,
)
from apps.agent.tests.harness import run_turn
from apps.channels.models import ChannelAccount, Message
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSIONS
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User
from apps.users.services import ensure_agent_user


def _seed_role(org, role_name):
    codes = PERMISSIONS[role_name]
    role, _ = Role.objects.get_or_create(
        name=role_name, organization=org, defaults={"is_system_role": True}
    )
    if "*.*" in codes:
        wildcard, _ = Permission.objects.get_or_create(code="*.*")
        role.permissions.set([wildcard])
    else:
        role.permissions.set(
            [Permission.objects.get_or_create(code=c)[0] for c in codes]
        )
    return role



class CorpusBase(TestCase):
    """Clínica con Ana Cruz (tel …4586) y su perro Oliver — los datos reales
    de la conv 13, reusados por los tres casos."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Corpus Vet", timezone="UTC")
        _seed_role(cls.org, "AGENT")
        vet_role = _seed_role(cls.org, "VET")
        cls.vet = User.objects.create_user(
            username="corpus_vet", password="p", organization=cls.org, role="VET"
        )
        UserRole.objects.get_or_create(user=cls.vet, role=vet_role)
        cls.owner = Owner.objects.create(
            organization=cls.org, name="Ana Cruz", phone="5511994586",
        )
        cls.pet = Pet.objects.create(
            organization=cls.org, owner=cls.owner, name="Oliver",
            species="perro", birth_date="2021-03-10",
        )

    def setUp(self):
        executor_module._token_cache.clear()
        self.agent_user, _ = ensure_agent_user(self.org)
        self.settings = AgentSettings.objects.create(
            organization=self.org, enabled=True, agent_user=self.agent_user,
        )
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="920920920",
        )

    # --- utilidades de aserción, en lenguaje de conducta -------------------

    def _agent_bodies(self, conversation):
        """Todo lo que el cliente REALMENTE recibió, en orden."""
        return list(
            Message.objects.filter(
                conversation=conversation,
                direction=Message.DIRECTION_OUT,
            ).exclude(status=Message.STATUS_DISCARDED)
            .order_by("id").values_list("body", flat=True)
        )

    def assert_no_repeated_message(self, conversation):
        """C7 · repetir es defecto del sistema.

        Proxy mecánico y exacto de «turnos hasta la primera respuesta útil»
        (§9bis.2): dos salientes consecutivos idénticos son, por definición,
        un turno que no aportó nada.
        """
        bodies = self._agent_bodies(conversation)
        for previous, current in zip(bodies, bodies[1:]):
            self.assertNotEqual(
                previous.strip(), current.strip(),
                f"el agente repitió el mismo mensaje palabra por palabra:\n{current}",
            )

    def assert_no_empty_why(self, conversation):
        """C8/R9 · toda petición lleva un motivo decible.

        Ancla del defecto exacto de producción: `T0_WHY_THEN_REASK` con
        `why=''` produjo literalmente «Te lo pido para  🙂» (doble espacio).
        """
        for body in self._agent_bodies(conversation):
            self.assertNotIn(
                "Te lo pido para  ", body,
                f"motivo vacío en un mensaje al cliente:\n{body}",
            )

    def assert_not_escalated_by_identity(self, conversation):
        conversation.refresh_from_db()
        handoff = HumanHandoff.objects.filter(
            conversation=conversation,
            reason_code=HumanHandoff.REASON_IDENTITY,
        ).first()
        self.assertIsNone(
            handoff,
            "la conversación terminó con una persona por un fallo de identidad "
            "que el cliente no cometió",
        )

    def _new_conversation(self, *, external_id, owner=None, verified=False):
        contact = ContactIdentity.objects.create(
            organization=self.org, external_id=external_id, owner=owner,
            verification_level=(
                ContactIdentity.VERIFICATION_CONFIRMED if verified
                else ContactIdentity.VERIFICATION_UNKNOWN
            ),
            verified_at=timezone.now() if verified else None,
        )
        return Conversation.objects.create(
            organization=self.org, channel_account=self.channel, contact=contact,
        )

    def _turn(self, conversation, *, burst, scripted=()):
        return run_turn(
            self, conversation, self.agent_user, burst=list(burst),
            scripted_llm=list(scripted),
        )


# ---------------------------------------------------------------------------
# Caso A — la conversación del brief (piloto 2026-07-31)
# ---------------------------------------------------------------------------

class BriefConversationTests(CorpusBase):
    """Número NO registrado que pide una cita y da su nombre por su cuenta.

    Transcripción original (el PO reportó lo esencial; los límites exactos de
    cada ráfaga no constan, así que se reproduce el CAMINO DE CÓDIGO, no el
    tecleo literal):

        C: hola · quiero una cita para mi mascota
        A: ¿es la primera vez o ya has venido?
        C: ya he ido · mi nombre es Ana
        A: ¿a nombre de quién está el registro?      ← acaba de dárselo
        C: ya te dije · Ana
        A: Te lo pido para  🙂  ¿a nombre de quién…?  ← motivo VACÍO
        C: ¿qué?
        A: Te lo pido para  🙂  ¿a nombre de quién…?  ← idéntico
        C: ¿qué es eso?
        A: No logro validar tus datos…                ← handoff

    Los cuatro turnos del agente son plantillas de `tier0.py`: la conversación
    completa se resolvió con **cero llamadas al modelo**.
    """

    def _play(self):
        """La misma conversación, ya conducida por el modelo (Fase 2).

        El guion NO es la prueba: es el mínimo para que el turno avance. Las
        aserciones miran ESTADO y AUTORÍA, que es lo que el guion no puede
        falsear — afirmar sobre un texto que yo mismo escribo sería circular.
        """
        conversation = self._new_conversation(external_id="5215500001111")
        self._turn(conversation,
                   burst=["hola", "quiero una cita para mi mascota"],
                   scripted=[LLMResult(
                       kind="text",
                       text="¡Claro! ¿Sería su primera visita o ya han "
                            "acudido a la clínica? 🐾")])
        self._turn(conversation, burst=["ya he ido", "mi nombre es Ana"],
                   scripted=[LLMResult(
                       kind="tool_call", tool_name="set_client_path",
                       tool_args={"path": "existing_client"}),
                       LLMResult(
                       kind="tool_call", tool_name="identify_client",
                       tool_args={"owner_name": "Ana"}),
                       LLMResult(kind="text",
                                 text="Gracias, Ana. ¿Cómo se llama tu "
                                      "mascota? Es para abrir su ficha 🙂")])
        self._turn(conversation, burst=["ya te dije", "Ana"],
                   scripted=[LLMResult(
                       kind="text",
                       text="Sí, perdón — me falta el nombre de tu mascota "
                            "para encontrar el expediente 🙂")])
        return conversation

    def test_guarda_el_nombre_que_el_cliente_dio_por_su_cuenta(self):
        """C2 · el dato llegó en la MISMA ráfaga que otra cosa.

        Es el defecto que abrió É-F5: el cliente escribió «ya he ido» y «mi
        nombre es Ana» juntos, el router clasificó bien la primera mitad y la
        segunda **no tenía dónde ir** — `goals.capture` solo se alimentaba de
        argumentos de tool, y ninguna tool se llamó.

        Se afirma sobre el ESTADO, no sobre el texto: el dato quedó guardado.
        """
        conversation = self._play()
        conversation.refresh_from_db()
        self.assertEqual(
            (conversation.flow.get('aportado') or {}).get('owner_name'), "Ana",
            "el cliente dijo su nombre y el sistema no lo guardó",
        )

    def test_ninguna_peticion_sale_sin_motivo(self):
        """R9 · guarda de regresión contra `Te lo pido para  🙂`.

        La plantilla que lo producía ya no existe, así que hoy esto pasa por
        construcción. Se conserva porque lo que protege no es el bug: es que
        no vuelva a introducirse un `format()` con un hueco que pueda quedar
        vacío sin que nadie lo note.
        """
        self.assert_no_empty_why(self._play())

    def test_el_sistema_no_repite_una_plantilla(self):
        """C7 · en la conversación real el agente repitió la MISMA plantilla
        tres veces, carácter por carácter.

        Se mira solo lo que emite el SISTEMA (`author_type='system'`), no lo
        que redacta el modelo: el texto del modelo lo pone el guion y afirmar
        sobre él no probaría nada.
        """
        conversation = self._play()
        plantillas = list(
            Message.objects.filter(
                conversation=conversation,
                direction=Message.DIRECTION_OUT,
                author_type=Message.AUTHOR_SYSTEM,
            ).exclude(status=Message.STATUS_DISCARDED)
            .order_by("id").values_list("body", flat=True)
        )
        for previous, current in zip(plantillas, plantillas[1:]):
            self.assertNotEqual(previous.strip(), current.strip(),
                                f"plantilla repetida verbatim:\n{current}")

    def test_no_termina_con_una_persona_por_culpa_del_cliente(self):
        """El mensaje de cierre mentía: «no logro validar tus datos» cuando
        nada se validó — el cliente nunca dio un dato equivocado. Lo que se
        agotó fue el tope de desvíos, no los intentos fallidos."""
        self.assert_not_escalated_by_identity(self._play())

    def test_la_conversacion_llega_al_modelo(self):
        """La métrica del experimento, invertida respecto de la Fase 0.

        Antes este test afirmaba lo contrario —los cinco turnos se resolvían
        SIN LLM— y su docstring decía que empezar a fallar sería buena
        noticia. Aquí está la buena noticia.
        """
        conversation = self._play()
        from apps.agent.models import TurnDecision
        decisiones = TurnDecision.objects.filter(conversation=conversation)
        self.assertGreater(
            decisiones.filter(planner_used=True).count(), 0,
            "el modelo no vio ni uno de los turnos",
        )


# ---------------------------------------------------------------------------
# Caso B — conv 12 (`0d56b976`, 2026-07-28): el mismo dato, cuatro veces
# ---------------------------------------------------------------------------

@legacy_write_component
class RepeatedAskTests(CorpusBase):
    """Cliente verificado agendando. El modelo llama la herramienta con datos
    parciales una y otra vez; el sistema vuelve a pedir lo mismo.

    Estado real registrado: `asked={'date': 4, 'time': 4, 'reason': 2}` con
    `stall_turns=0` — el detector de estancamiento era ciego justo al bucle
    que existe para cazar.
    """

    def _partial_call(self):
        """Lo que el modelo hizo 4 veces: llamar sin fecha ni hora."""
        return [
            LLMResult(kind="tool_call", tool_name="create_appointment",
                      tool_args={"pet_handle": "mascota_1",
                                 "reason": "vacuna"}),
            LLMResult(kind="text", text="¿Para qué día te late? 🙂"),
        ]

    def test_no_pide_el_mismo_dato_mas_de_dos_veces(self):
        """C7 · a la segunda hay que cambiar de estrategia, no repetir.

        **Cerrado por la Fase 3.** El modelo llama la herramienta cuatro veces
        con los mismos datos incompletos —igual que en el piloto— y el sistema
        deja de pedir a la segunda: `_goal_gate` cambia el código de error a
        `change_approach` y no vuelve a incrementar `asked`, porque a partir de
        ahí ya no está preguntando.

        Se afirma sobre ESTADO (`goal.asked`), no sobre el texto: el texto lo
        escribe el guion del stub y afirmar sobre él sería circular.
        """
        conversation = self._new_conversation(
            external_id="5215511994586", owner=self.owner, verified=True)
        conversation.flow["refs"] = {"mascota_1": str(self.pet.public_id)}
        conversation.save(update_fields=["flow"])

        for _ in range(4):
            self._turn(conversation, burst=["quiero agendar"],
                       scripted=self._partial_call())

        goal = ConversationGoal.objects.filter(
            conversation=conversation, name="schedule_appointment",
        ).first()
        self.assertIsNotNone(goal, "el objetivo debería existir")
        self.assertLessEqual(
            (goal.asked or {}).get("date", 0), 2,
            "el sistema pidió la fecha más de dos veces sin cambiar de "
            "estrategia (R10/C7)",
        )


# ---------------------------------------------------------------------------
# Caso C — conv 13 (`85a2a691`, 2026-07-30): preguntar no es fallar
# ---------------------------------------------------------------------------

class FamilyChallengeInterruptionTests(CorpusBase):
    """Los cuatro factores eran correctos y el cliente acabó con un humano.

    Su único «error» fue preguntar *«¿para qué necesitas eso?»* antes de dar
    los dígitos: se contó como respuesta equivocada, dos veces.

    Lo cerró É-F4 (Fase 0: una no-respuesta no es una respuesta equivocada;
    Fase 1: el reto se suspende en vez de destruirse) y vivía aquí en verde
    como regresión protectora.

    **REESCRITO EN LA FASE 2, y el motivo importa más que el test.** La
    garantía cambió de naturaleza:

        antes:  4 factores correctos → verificado.  Lo garantizaba la FSM.
        ahora:  4 factores correctos → verificado SI el modelo llama a
                `identify_client`.

    No es una regresión de SEGURIDAD —`_verification_ok` sigue impidiendo el
    acceso indebido y nadie entra sin verificar— sino de SERVICIO: un familiar
    legítimo podría no quedar vinculado si el modelo no llama la herramienta.
    Es exactamente el riesgo §11.4 del plan, que ahora tiene un caso concreto
    en vez de ser una hipótesis, y que **ninguna suite con stub puede
    resolver**: el guion de aquí abajo demuestra que la vía FUNCIONA, no que
    el modelo la USE. Eso lo dice el eval con LLM real, midiendo llamadas a
    `identify_client` por conversación.
    """

    def _play(self):
        """El mismo cliente, ahora conducido por el modelo.

        Los cuatro factores llegan igual que en la conversación real —en
        varios turnos y con una pregunta de por medio—; lo que cambia es quién
        los recoge. En el turno 4 el cliente pregunta el porqué en vez de
        contestar: no se penaliza, y el modelo sigue.
        """
        conversation = self._new_conversation(external_id="5215500002222")
        self._turn(conversation, burst=["quiero una cita para Oliver"],
                   scripted=[LLMResult(
                       kind="text",
                       text="¡Claro! ¿Sería su primera visita o ya han "
                            "acudido a la clínica? 🙂")])
        self._turn(conversation, burst=["ya he ido varias veces", "Ana Cruz"],
                   scripted=[LLMResult(
                       kind="tool_call", tool_name="set_client_path",
                       tool_args={"path": "existing_client"}),
                       LLMResult(
                       kind="tool_call", tool_name="identify_client",
                       tool_args={"owner_name": "Ana Cruz",
                                  "pet_name": "Oliver"}),
                       LLMResult(kind="text",
                                 text="Gracias. ¿Me confirmas los últimos 4 "
                                      "dígitos del teléfono registrado? Es "
                                      "para abrir la ficha correcta 🙂")])
        self._turn(conversation, burst=["para que necesitas eso"],
                   scripted=[LLMResult(
                       kind="text",
                       text="Para asegurarme de abrir la ficha correcta y "
                            "proteger los datos del titular 🙂")])
        self._turn(conversation, burst=["4586"],
                   scripted=[LLMResult(
                       kind="tool_call", tool_name="identify_client",
                       tool_args={"owner_name": "Ana Cruz",
                                  "pet_name": "Oliver",
                                  "phone_digits": "4586"}),
                       LLMResult(kind="text",
                                 text="¡Listo! ¿Para qué día te late? 🙂")])
        return conversation

    def test_preguntar_no_rompe_la_verificacion(self):
        """R1 · una no-respuesta nunca es una respuesta equivocada.

        La propiedad que se protege es la MISMA que antes; solo cambió quién
        conduce. Cuatro factores correctos, una pregunta de por medio, y el
        cliente acaba atendido en vez de con un humano.
        """
        conversation = self._play()
        conversation.contact.refresh_from_db()
        self.assertEqual(
            conversation.contact.owner_id, self.owner.pk,
            "los 4 factores eran correctos: el contacto debió quedar vinculado",
        )
        self.assertEqual(
            conversation.contact.verification_level,
            ContactIdentity.VERIFICATION_CONFIRMED,
        )
        self.assert_not_escalated_by_identity(conversation)
        self.assert_no_repeated_message(conversation)

    def test_preguntar_el_porque_no_cuenta_como_atasco(self):
        """C11 · el turno 4 es una pregunta, no un fallo.

        En la conversación real ese turno se contó como respuesta equivocada
        —dos veces— y acabó en handoff. Aquí se comprueba sobre el ESTADO, que
        es lo que no depende del guion: el objetivo no acumula estancamiento
        por haber preguntado.
        """
        conversation = self._play()
        goal = ConversationGoal.objects.filter(
            conversation=conversation).order_by('-id').first()
        if goal is not None:
            self.assertEqual(
                goal.stall_turns, 0,
                "preguntar el porqué no puede acercar al cliente a una escalada",
            )
        self.assert_not_escalated_by_identity(conversation)


# ---------------------------------------------------------------------------
# Línea base — el fixture contra el que se juzgarán las fases siguientes
# ---------------------------------------------------------------------------

class BaselineMetricsTests(CorpusBase):
    """Congela los números de HOY sobre la conversación del brief.

    No es un test de calidad: es el **punto de comparación**. Estos valores
    tienen que cambiar en la Fase 2, y que este test se ponga rojo entonces es
    la señal correcta — se actualiza junto con el resultado del experimento.
    """

    def test_el_agente_redacta_y_el_modelo_ve_los_turnos(self):
        """Mide el efecto de la Fase 2 sobre la métrica insignia.

        La versión de la Fase 0 congelaba los valores de ENTONCES —0.0
        redactado por el agente, 1.0 de turnos sin modelo— y decía que tenían
        que cambiar aquí. Cambiaron.

        Se afirma la DIRECCIÓN, no un número: fijar un objetivo concreto sería
        el Goodhart contra el que este mismo plan advierte (§9bis.1), y el
        techo real depende de cuántas salvaguardas dispare el tráfico.
        """
        from datetime import timedelta

        from apps.agent.metrics import compute_conversation_metrics

        conversation = self._new_conversation(external_id="5215500003333")
        for burst, script in (
            (["hola", "quiero una cita"],
             [LLMResult(kind="text", text="¡Claro! ¿Cómo se llama tu peludo?")]),
            (["se llama Oliver"],
             [LLMResult(kind="text", text="Perfecto. ¿Para qué día lo quieres?")]),
        ):
            self._turn(conversation, burst=burst, scripted=script)

        now = timezone.now()
        metrics = compute_conversation_metrics(
            self.org, now - timedelta(hours=1), now + timedelta(hours=1))

        self.assertGreater(
            metrics['pct_redactado_por_agente'], 0.0,
            "el agente no redactó un solo mensaje: la Fase 2 no movió nada",
        )
        self.assertLess(
            metrics['pct_turnos_sin_modelo'], 1.0,
            "ningún turno llegó al modelo",
        )
        self.assertEqual(metrics['salientes_repetidos'], 0)
        self.assertGreater(
            metrics['palabras_por_mensaje_agente']['muestras'], 0,
            "sin mensajes del agente la métrica de verbosidad no dice nada",
        )
