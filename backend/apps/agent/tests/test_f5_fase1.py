"""
test_f5_fase1.py — Percepción, situación y verificación como herramienta.

Gates de ADR p56 para É-F5 Fase 1. Dos familias:

- **Estáticos**: se leen los fuentes y se afirma sobre ellos. Son los que
  impiden que la capa de situación se convierta en la tercera máquina de
  estados del subsistema, y los que anclan quién puede escribir el nivel de
  verificación. Un gate de conducta no los sustituye: aquí lo que se protege
  es una FRONTERA, y una frontera se rompe con un `import`.
- **De conducta**: lo que el cliente ve y lo que queda en la base.

Fase 1 es ADITIVA: la FSM de identidad sigue corriendo y las dos vías
coexisten. El corpus de la Fase 0 debe seguir ROJO al terminar — si algún caso
del brief se pusiera verde aquí, se habría colado comportamiento de Fase 2.
"""
import pathlib
import re

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.agent import executor as executor_module
from apps.agent import policy, situation
from apps.agent.executor import ToolExecutor
from apps.agent.models import (
    AgentSettings,
    ContactIdentity,
    Conversation,
    ConversationGoal,
    HumanHandoff,
)
from apps.agent.tests.harness import RealApiTransport
from apps.channels.models import ChannelAccount, Message
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSIONS
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User
from apps.users.services import ensure_agent_user

_AGENT_DIR = pathlib.Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Gates ESTÁTICOS — fronteras, no conducta
# ---------------------------------------------------------------------------

class StaticBoundaryTests(SimpleTestCase):

    def test_ninguna_funcion_de_decision_lee_la_situacion(self):
        """ADR p56 invariante 1 — el gate anti-FSM#3.

        Simétrico al de R13: un hecho de control que el árbitro no lee es
        código muerto; un hecho de SITUACIÓN que una función de decisión lee
        **es un bug**. Si esto se rompe, la empatía se convirtió en un gate y
        el subsistema ganó su tercera máquina de estados — que es exactamente
        lo que É-F5 viene a desmontar.

        **Si esto falla por el camino PROACTIVO, el arreglo no es relajar el
        gate.** La enmienda de p56 permite que un automatismo iniciado por el
        sistema consulte la situación *solo para cancelarse*; lo que no puede
        es vivir dentro de `policy.py`, que es el camino reactivo. Ese fallo es
        la señal de que toca sacar el camino proactivo a su propio módulo —
        deliberadamente diferido hasta que haya más de un consumidor, para no
        diseñar su API alrededor del único que existe hoy
        (`nudge_abandoned_flows`).
        """
        prohibidos = ('arbiter.py', 'policy.py', 'guards.py')
        for nombre in prohibidos:
            source = (_AGENT_DIR / nombre).read_text(encoding='utf-8')
            with self.subTest(modulo=nombre):
                self.assertNotRegex(
                    source, r'^\s*(from\s+\.\s+import\s+.*\bsituation\b'
                            r'|import\s+.*\bsituation\b)',
                    f"{nombre} importa `situation`: una función de decisión no "
                    f"puede leer hechos de situación (ADR p56 inv. 1)",
                )

    def test_solo_identity_eleva_el_nivel_de_verificacion(self):
        """ADR p56 invariante 5 — frontera de SEGURIDAD.

        El modelo aporta el candidato; el código dictamina contra la base. Si
        se pudiera **elevar** el nivel desde otro sitio, bastaría con que el
        modelo *afirmara* haber verificado para abrir el expediente de un
        tercero.

        Lo que se vigila es **subir a `confirmed_in_chat`**, no cualquier
        escritura del campo, y la distinción es de dirección:

        - `phone_match` (`services.py`, al resolver el teléfono) **no es una
          afirmación de identidad**: no habilita ninguna tool personal —
          `_verification_ok` exige `confirmed_in_chat`.
        - Bajar a `unknown` (`views.py`, staff revocando un vínculo) va en la
          dirección segura.

        Este gate encontró en su primera corrida un tercer sitio que SÍ elevaba
        —el auto-vínculo del alta en `tools.py`— y se movió a `identity.py`
        en vez de añadirle una excepción: la idea es cerrar el hueco, no
        silenciar el gate que lo detecta.
        """
        elevadores = []
        for ruta in sorted(_AGENT_DIR.glob('*.py')):
            source = ruta.read_text(encoding='utf-8')
            for linea in source.splitlines():
                if re.search(r'\.verification_level\s*=(?!=)', linea) and \
                        'VERIFICATION_CONFIRMED' in linea:
                    elevadores.append(ruta.name)
                    break
        self.assertEqual(
            elevadores, ['identity.py'],
            f"se eleva a confirmed_in_chat fuera de identity.py: {elevadores}",
        )


class SituationPurityTests(SimpleTestCase):

    def test_la_situacion_es_esparsa_y_no_inventa(self):
        """Sin señales, dict vacío: el bloque no viaja y no gasta tokens."""
        self.assertEqual(situation.read(None, "quiero una cita"), {})

    def test_lee_disculpa_pregunta_de_proceso_e_insistencia(self):
        self.assertIn('se_disculpa',
                      situation.read(None, "perdón por preguntar tanto"))
        self.assertIn('pregunta_por_que_le_pedimos_esto',
                      situation.read(None, "¿para qué necesitas eso?"))
        self.assertIn('insiste_porque_ya_lo_habia_dicho',
                      situation.read(None, "ya te dije, Ana"))


# ---------------------------------------------------------------------------
# Conducta
# ---------------------------------------------------------------------------

def _seed_role(org, role_name):
    codes = PERMISSIONS[role_name]
    role, _ = Role.objects.get_or_create(
        name=role_name, organization=org, defaults={"is_system_role": True})
    if "*.*" in codes:
        role.permissions.set([Permission.objects.get_or_create(code="*.*")[0]])
    else:
        role.permissions.set(
            [Permission.objects.get_or_create(code=c)[0] for c in codes])
    return role


class Fase1Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="F1 Vet", timezone="UTC")
        _seed_role(cls.org, "AGENT")
        vet_role = _seed_role(cls.org, "VET")
        vet = User.objects.create_user(username="f1_vet", password="p",
                                       organization=cls.org, role="VET")
        UserRole.objects.get_or_create(user=vet, role=vet_role)
        cls.owner = Owner.objects.create(
            organization=cls.org, name="Ana Cruz", phone="5511994586")
        cls.pet = Pet.objects.create(
            organization=cls.org, owner=cls.owner, name="Oliver",
            species="perro", birth_date="2021-03-10")

    def setUp(self):
        executor_module._token_cache.clear()
        self.agent_user, _ = ensure_agent_user(self.org)
        AgentSettings.objects.create(organization=self.org, enabled=True,
                                     agent_user=self.agent_user)
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="920920920")

    def _conversation(self, *, external_id, owner=None):
        contact = ContactIdentity.objects.create(
            organization=self.org, external_id=external_id, owner=owner,
            verification_level=(
                ContactIdentity.VERIFICATION_PHONE_MATCH if owner
                else ContactIdentity.VERIFICATION_UNKNOWN),
        )
        return Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=contact)

    def _identify(self, conversation, **args):
        from apps.agent import tools
        return tools.run_tool(
            'identify_client', args, conversation=conversation,
            executor=ToolExecutor(conversation, self.agent_user,
                                  transport=RealApiTransport()))


class IdentifyClientTests(Fase1Base):

    def test_acepta_un_solo_dato_y_guarda_lo_que_llego(self):
        """C2 · push: se guarda lo que el cliente aportó, sin habérselo pedido."""
        conversation = self._conversation(external_id="5215500001111")
        outcome = self._identify(conversation, owner_name="Ana Cruz")

        self.assertTrue(outcome.ok)
        conversation.refresh_from_db()
        self.assertEqual(conversation.flow['aportado']['owner_name'], "Ana Cruz")

    def test_nunca_devuelve_nombres_ni_conteos(self):
        """G4 / ADR p56 inv. 6 — el modelo no puede enumerar lo que no sabe.

        Se afirma sobre el PAYLOAD, no sobre el texto: si el nombre nunca llega
        al modelo, ninguna redacción puede filtrarlo.
        """
        conversation = self._conversation(external_id="5215500001111")
        outcome = self._identify(conversation, owner_name="Ana Cruz")

        blob = str(outcome.data)
        self.assertNotIn("Oliver", blob)
        self.assertNotIn("4586", blob)
        # El nombre que el propio cliente aportó tampoco vuelve: `ya_tengo` son
        # ETIQUETAS de factor, no valores.
        self.assertNotIn("Ana Cruz", blob)

    def test_comportamiento_uniforme_exista_o_no_el_registro(self):
        """ADR p56 inv. 6 — nada de oráculo de existencia.

        Pedir los 4 dígitos no puede significar «encontré a alguien con ese
        nombre»: un número desconocido podría sondear qué clientes tiene la
        clínica preguntando por nombres a ver cuál cambia la respuesta.
        """
        existe = self._identify(
            self._conversation(external_id="5215500002222"),
            owner_name="Ana Cruz")
        no_existe = self._identify(
            self._conversation(external_id="5215500003333"),
            owner_name="Zoraida Inexistente")

        self.assertEqual(existe.data['falta'], no_existe.data['falta'])
        self.assertEqual(existe.data['verificado'], no_existe.data['verificado'])

    def test_verifica_por_mascota_cuando_el_numero_ya_tiene_titular(self):
        conversation = self._conversation(external_id="5215511994586",
                                          owner=self.owner)
        outcome = self._identify(conversation, pet_name="Oliver")

        self.assertTrue(outcome.data['verificado'])
        conversation.contact.refresh_from_db()
        self.assertEqual(conversation.contact.verification_level,
                         ContactIdentity.VERIFICATION_CONFIRMED)

    def test_el_vinculo_familiar_exige_los_tres_factores(self):
        """Seguridad: con dos de tres NO se vincula nada.

        Un conocido casual sabe «Ana y Oliver»; los últimos 4 dígitos del
        teléfono registrado los sabe un familiar real.
        """
        conversation = self._conversation(external_id="5215500004444")
        parcial = self._identify(conversation, owner_name="Ana Cruz",
                                 pet_name="Oliver")

        self.assertFalse(parcial.data['verificado'])
        conversation.contact.refresh_from_db()
        self.assertIsNone(conversation.contact.owner_id)

        completo = self._identify(conversation, owner_name="Ana Cruz",
                                  pet_name="Oliver", phone_digits="4586")
        self.assertTrue(completo.data['verificado'])
        conversation.contact.refresh_from_db()
        self.assertEqual(conversation.contact.owner_id, self.owner.pk)

    def test_dos_homonimos_que_pasan_los_tres_factores_no_vinculan(self):
        """Ambigüedad = no se elige. El sistema nunca adivina un expediente."""
        gemela = Owner.objects.create(organization=self.org, name="Ana Cruz",
                                      phone="5599884586")
        Pet.objects.create(organization=self.org, owner=gemela, name="Oliver",
                           species="perro", birth_date="2020-01-01")

        conversation = self._conversation(external_id="5215500005555")
        outcome = self._identify(conversation, owner_name="Ana Cruz",
                                 pet_name="Oliver", phone_digits="4586")

        self.assertFalse(outcome.data['verificado'])
        conversation.contact.refresh_from_db()
        self.assertIsNone(conversation.contact.owner_id)


class UrgencyStillPreemptsTests(Fase1Base):

    def test_la_urgencia_gana_a_la_situacion(self):
        """ADR p56 inv. 3 — la frontera más importante de la capa de situación.

        «Estoy desesperada, mi perro no respira» trae señal emocional Y una
        urgencia. Una capa de empatía bien intencionada que retrase esto sería
        el peor resultado posible de todo el rediseño.
        """
        conversation = self._conversation(external_id="5215500006666")
        decision = policy.evaluate(
            conversation, "estoy desesperada, mi perro no respira")

        self.assertEqual(decision.kind, policy.ESCALATE)
        self.assertEqual(decision.handoff_reason,
                         HumanHandoff.REASON_EMERGENCY)


class ConversationalTurnIsValidTests(Fase1Base):

    def test_preguntar_no_acerca_al_cliente_a_una_escalada(self):
        """C11 / R10 · ADR p56 §7.

        Hasta aquí una pregunta no llenaba ningún slot, así que sumaba a
        `stall_turns`, y tres de esas mandaban al cliente con un humano
        diciéndole «creo que por aquí nos estamos enredando». El sistema
        contaba la conversación del cliente como su propio atasco.
        """
        from apps.agent import planner

        conversation = self._conversation(external_id="5215511994586",
                                          owner=self.owner)
        goal = ConversationGoal.objects.create(
            organization=self.org, conversation=conversation,
            name="schedule_appointment")

        for _ in range(3):
            estancado = planner._settle_goal(
                conversation, goal_progressed=False, goal_attempted=True,
                other_tool_used=False, client_asked=True)
            self.assertFalse(estancado)

        goal.refresh_from_db()
        self.assertEqual(goal.stall_turns, 0)

    def test_el_bucle_del_modelo_si_sigue_contando(self):
        """El detector no se desarma: lo que cuenta es que el SISTEMA no
        avanza — el modelo llamando la misma herramienta vuelta tras vuelta."""
        from apps.agent import planner

        conversation = self._conversation(external_id="5215511994586",
                                          owner=self.owner)
        ConversationGoal.objects.create(
            organization=self.org, conversation=conversation,
            name="schedule_appointment")

        resultados = [
            planner._settle_goal(conversation, goal_progressed=False,
                                 goal_attempted=True, other_tool_used=False,
                                 client_asked=False)
            for _ in range(3)
        ]
        self.assertTrue(resultados[-1], "3 turnos sin avance deben escalar")


class NudgeRespectsDeferTests(Fase1Base):

    def test_quien_pidio_tiempo_no_recibe_el_recordatorio(self):
        """C13 · un mensaje que el sistema INICIA también cumple un propósito.

        `T0_DEFER` le contesta «aquí queda pendiente — me dices», y conserva el
        `pending_action` a propósito. Hasta ahora eso significaba que TODO
        cliente que pedía tiempo recibía «¿Seguimos con tu cita?» una hora
        después. No es un caso extremo: es el flujo normal del producto.
        """
        conversation = self._conversation(external_id="5215511994586",
                                          owner=self.owner)
        conversation.flow['pending_action'] = {'tool': 'create_appointment'}
        conversation.last_inbound_at = timezone.now() - policy.NUDGE_IDLE
        conversation.save()

        decision = policy.evaluate(conversation, "déjame pensarlo")
        self.assertEqual(decision.meta.get('reason'), 'confirm_defer')

        conversation.refresh_from_db()
        self.assertIn('deferred_at', conversation.flow)

        conversation.last_inbound_at = timezone.now() - policy.NUDGE_IDLE
        conversation.save(update_fields=['last_inbound_at'])
        self.assertEqual(policy.nudge_abandoned_flows(), 0)

    def test_el_recordatorio_sigue_saliendo_para_quien_solo_se_quedo_callado(self):
        """No se desarma el nudge: el silencio sí merece un recordatorio."""
        conversation = self._conversation(external_id="5215500007777",
                                          owner=self.owner)
        conversation.flow['pending_action'] = {'tool': 'create_appointment'}
        conversation.last_inbound_at = timezone.now() - policy.NUDGE_IDLE
        conversation.save()

        self.assertEqual(policy.nudge_abandoned_flows(), 1)
        self.assertTrue(
            Message.objects.filter(conversation=conversation,
                                   direction=Message.DIRECTION_OUT).exists())
