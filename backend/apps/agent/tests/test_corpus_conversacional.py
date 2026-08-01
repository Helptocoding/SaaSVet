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
import unittest

from django.test import TestCase
from django.utils import timezone

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
        conversation = self._new_conversation(external_id="5215500001111")
        self._turn(conversation, burst=["hola", "quiero una cita para mi mascota"])
        self._turn(conversation, burst=["ya he ido", "mi nombre es Ana"])
        self._turn(conversation, burst=["ya te dije", "Ana"])
        self._turn(conversation, burst=["¿qué?"])
        self._turn(conversation, burst=["¿qué es eso?"])
        return conversation

    @unittest.expectedFailure          # ← lo cierra la Fase 2
    def test_no_pide_el_nombre_que_el_cliente_acaba_de_dar(self):
        """C2/C7 · el dato llegó en la MISMA ráfaga y se descartó.

        Hoy `classify_client_triage` solo busca lemas de tamiz; nada en el
        router extrae un nombre. El agente pregunta por «Ana» medio segundo
        después de que el cliente escribiera «mi nombre es Ana».
        """
        conversation = self._new_conversation(external_id="5215500001111")
        self._turn(conversation, burst=["hola", "quiero una cita para mi mascota"])
        self._turn(conversation, burst=["ya he ido", "mi nombre es Ana"])

        self.assertNotIn(
            "¿A nombre de quién está el registro?",
            self._agent_bodies(conversation)[-1],
            "el cliente acaba de decir su nombre y el agente lo vuelve a pedir",
        )

    @unittest.expectedFailure          # ← lo cierra la Fase 2
    def test_ninguna_peticion_sale_sin_motivo(self):
        """R9 · el `why` de la etapa `titular` del tamiz no existe.

        `IDENTITY_SPECS['identity_triage']` declara un solo factor
        (`client_kind`), pero el router avanza a `return_to='titular'`, que no
        es un `Factor` — así que `why_for()` devuelve ''. La garantía «un
        factor sin why no compila» no cubre las etapas que la FSM usa de
        verdad.
        """
        self.assert_no_empty_why(self._play())

    @unittest.expectedFailure          # ← lo cierra la Fase 2
    def test_no_repite_el_mismo_mensaje(self):
        """C7 · dos salientes idénticos carácter por carácter.

        La respuesta al desvío es re-emitir la MISMA plantilla, lo que
        garantiza que el siguiente mensaje del cliente sea otra queja. El
        bucle no es un caso raro: es el punto fijo de la transición.
        """
        self.assert_no_repeated_message(self._play())

    @unittest.expectedFailure          # ← lo cierra la Fase 2
    def test_no_termina_con_una_persona_por_culpa_del_cliente(self):
        """El mensaje de cierre miente: «no logro validar tus datos» cuando
        nada se validó — el cliente nunca dio un dato equivocado. Lo que se
        agotó fue el tope de desvíos, no los intentos fallidos."""
        conversation = self._play()
        self.assert_not_escalated_by_identity(conversation)

    def test_la_conversacion_no_llega_al_modelo(self):
        """Línea base, y **no** es expectedFailure: documenta el hecho que
        motivó É-F5 y tiene que seguir siendo cierto *hasta* la Fase 2.

        Si este test empieza a fallar, es que el modelo ya conduce — buena
        noticia, y toca actualizarlo junto con los cuatro de arriba.
        """
        conversation = self._play()
        from apps.agent.models import TurnDecision
        sin_modelo = TurnDecision.objects.filter(
            conversation=conversation, planner_used=False,
        ).count()
        total = TurnDecision.objects.filter(conversation=conversation).count()
        self.assertEqual(
            sin_modelo, total,
            "línea base É-F5: hoy los 5 turnos se resuelven sin LLM",
        )


# ---------------------------------------------------------------------------
# Caso B — conv 12 (`0d56b976`, 2026-07-28): el mismo dato, cuatro veces
# ---------------------------------------------------------------------------

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

    @unittest.expectedFailure          # ← lo cierra la Fase 3 (C7 actúa)
    def test_no_pide_el_mismo_dato_mas_de_dos_veces(self):
        """C7 · a la segunda hay que cambiar de estrategia, no repetir.

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

    **Este caso ya lo cerró É-F4** (Fase 0: una no-respuesta no es una
    respuesta equivocada; Fase 1: el reto se suspende en vez de destruirse).
    Vive aquí en VERDE para proteger el arreglo — es la mitad del corpus que
    no puede volver a romperse.
    """

    def _play(self):
        conversation = self._new_conversation(external_id="5215500002222")
        self._turn(conversation, burst=["quiero una cita para Oliver"])
        self._turn(conversation, burst=["ya he ido varias veces"])
        self._turn(conversation, burst=["Ana Cruz"])
        self._turn(conversation, burst=["para que necesitas eso"])
        self._turn(
            conversation, burst=["4586"],
            scripted=[LLMResult(kind="text",
                                text="¡Gracias! ¿Para qué día te late? 🙂")],
        )
        return conversation

    def test_preguntar_no_rompe_la_verificacion(self):
        """R1 · una no-respuesta nunca es una respuesta equivocada."""
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

    def test_la_pregunta_recibe_su_motivo(self):
        """R9 · «¿para qué necesitas eso?» tiene que obtener una respuesta.

        Contraste con el caso A: aquí la etapa (`digits` del reto familiar) SÍ
        es un `Factor` declarado, así que el motivo existe y se dice. El
        defecto del brief no es que R9 no exista — es que no cubre las etapas
        que la FSM inventa fuera del catálogo.
        """
        conversation = self._play()
        bodies = self._agent_bodies(conversation)
        self.assertTrue(
            any("proteger los datos del titular" in b for b in bodies),
            "el cliente preguntó el porqué y nadie se lo dijo",
        )
        self.assert_no_empty_why(conversation)


# ---------------------------------------------------------------------------
# Línea base — el fixture contra el que se juzgarán las fases siguientes
# ---------------------------------------------------------------------------

class BaselineMetricsTests(CorpusBase):
    """Congela los números de HOY sobre la conversación del brief.

    No es un test de calidad: es el **punto de comparación**. Estos valores
    tienen que cambiar en la Fase 2, y que este test se ponga rojo entonces es
    la señal correcta — se actualiza junto con el resultado del experimento.
    """

    def test_linea_base_de_la_conversacion_del_brief(self):
        from datetime import timedelta

        from apps.agent.metrics import compute_conversation_metrics

        conversation = self._new_conversation(external_id="5215500003333")
        for burst in (["hola", "quiero una cita para mi mascota"],
                      ["ya he ido", "mi nombre es Ana"],
                      ["ya te dije", "Ana"],
                      ["¿qué?"],
                      ["¿qué es eso?"]):
            self._turn(conversation, burst=burst)

        now = timezone.now()
        metrics = compute_conversation_metrics(
            self.org, now - timedelta(hours=1), now + timedelta(hours=1))

        self.assertEqual(
            metrics['pct_redactado_por_agente'], 0.0,
            "línea base: el agente no redactó UN SOLO mensaje — los cinco son "
            "plantillas de tier0.py",
        )
        self.assertEqual(
            metrics['pct_turnos_sin_modelo'], 1.0,
            "línea base: los cinco turnos se resolvieron sin llamar al modelo",
        )
        self.assertGreaterEqual(
            metrics['salientes_repetidos'], 1,
            "línea base: el agente repitió al menos un mensaje palabra por "
            "palabra",
        )
        # Sin mensajes del agente no hay muestra de palabras: es coherente con
        # un 0 % redactado, y es exactamente por qué esa métrica no dice nada
        # útil hasta que la Fase 2 la levante.
        self.assertEqual(metrics['palabras_por_mensaje_agente']['muestras'], 0)
