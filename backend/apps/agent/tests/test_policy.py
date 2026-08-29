"""
test_policy.py — É-F1 PR-11: Policy Engine (orden del router, spec §3/§11.2).
"""
from datetime import timedelta

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.agent import confirmations, goals, matchers, policy, situation, tier0
from apps.agent.models import (
    AgentSettings,
    ContactIdentity,
    Conversation,
    HumanHandoff,
)
from apps.agent.tests.harness import identity_commitment
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet


class PolicyTestCase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Pol Org", timezone="UTC")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="800100800",
        )
        self.owner = Owner.objects.create(
            organization=self.org, name="Ana Torres", phone="5511998877",
        )
        Pet.objects.create(
            organization=self.org, owner=self.owner, name="Luna",
            species="perro", birth_date="2021-01-01",
        )
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215511998877",
            owner=self.owner,
            verification_level=ContactIdentity.VERIFICATION_PHONE_MATCH,
        )
        self.conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact,
        )
        Organization.objects.filter(pk=self.org.pk).update(
            phone="55-1234-5678")
        self.org.refresh_from_db()
        self.conv.organization = self.org
        self.settings = AgentSettings.objects.create(
            organization=self.org, enabled=True,
        )

    def _eval(self, text):
        return policy.evaluate(self.conv, text, agent_settings=self.settings)

    def _inbound(self, text):
        """Un entrante REAL del cliente.

        La evidencia de identidad exige objetos `Message`, no cuerpos (plan de
        continuidad, D24): sin PK no hay procedencia que sellar. Un test que
        solo pasa texto obtiene, correctamente, cero evidencia.
        """
        from apps.channels.models import Message
        return Message.objects.create(
            organization=self.org, channel_account=self.channel,
            conversation=self.conv, direction=Message.DIRECTION_IN,
            author_type=Message.AUTHOR_CLIENT, body=text,
            status=Message.STATUS_PENDING,
        )

    def _eval_burst(self, *texts):
        messages = [self._inbound(text) for text in texts]
        return policy.evaluate(self.conv, texts[-1],
                               agent_settings=self.settings,
                               burst_messages=messages)


class KillSwitchTests(PolicyTestCase):
    def test_disabled_returns_t0_disabled(self):
        self.settings.enabled = False
        self.settings.save()
        d = self._eval("hola")
        self.assertEqual(d.kind, policy.REPLY)
        self.assertEqual(d.meta.get("reason"), "disabled")

    def test_blocked_contact_is_silent(self):
        self.contact.is_blocked = True
        self.contact.save()
        self.assertEqual(self._eval("hola").kind, policy.SILENT)

    def test_human_active_is_silent(self):
        self.conv.state = Conversation.STATE_HUMAN_ACTIVE
        self.conv.save()
        self.assertEqual(self._eval("hola").kind, policy.SILENT)


class PriorityOrderTests(PolicyTestCase):
    def test_emergency_beats_everything(self):
        d = self._eval("mi perro convulsiona y quiero hablar con alguien")
        self.assertEqual(d.kind, policy.ESCALATE)
        self.assertEqual(d.handoff_reason, HumanHandoff.REASON_EMERGENCY)
        self.assertEqual(d.handoff_priority, HumanHandoff.PRIORITY_URGENT)
        self.assertEqual(d.meta.get('handoff_detail'), 'posibles convulsiones')
        self.assertIn("55-1234-5678", d.text)

    def test_emergency_escalates_leaving_pending_action_for_escalate_to_human(self):
        """`evaluate()` ya no toca `pending_action` por su cuenta (Fase 1
        §1.1): la urgencia SUPLANTA, no aborta (R4/R5) — quien lo suspende
        es `escalate_to_human`, el único punto de escritura, llamado por el
        dispatcher del planner tras recibir el veredicto ESCALATE."""
        self.conv.flow["pending_action"] = {"tool": "x"}
        self.conv.save()
        d = self._eval("se está muriendo")
        self.assertEqual(d.kind, policy.ESCALATE)
        self.conv.refresh_from_db()
        self.assertIn("pending_action", self.conv.flow)   # intacto todavía

    def test_emergency_suspends_pending_action_not_destroys(self):
        """Extremo a extremo (evaluate + escalate_to_human, como lo
        encadena el planner): la urgencia SUSPENDE el `pending_action`, no
        lo destruye — se ofrece de vuelta al retomar (R4/R5).

        El `state` viaja **íntegro** (TC-SEC-03: la propuesta no se reescribe
        ni se recorta al suspenderla). Desde F2 la suspensión lleva además
        `suspension_id`, `suspended_at` y `handoff_reason` (§6.1) — el primero
        es la clave de idempotencia que el release necesita para no aplicar su
        veredicto sobre una suspensión distinta de la que verificó.
        """
        self.conv.flow["pending_action"] = {"tool": "create_appointment"}
        self.conv.save()
        d = self._eval("se está muriendo")
        policy.escalate_to_human(
            self.conv, reason_code=d.handoff_reason,
            priority=d.handoff_priority)
        self.conv.refresh_from_db()
        self.assertNotIn("pending_action", self.conv.flow)

        suspended = self.conv.flow["suspended"]
        self.assertEqual(suspended["kind"], "pending_action")
        self.assertEqual(suspended["state"], {"tool": "create_appointment"})
        self.assertTrue(suspended["suspension_id"])
        self.assertTrue(suspended["suspended_at"])
        self.assertEqual(suspended["handoff_reason"], d.handoff_reason)

    def test_emergency_handoff_keeps_a_safe_symptom_summary(self):
        d = self._eval("mi perro convulsiona desde hace 30 minutos")
        policy.escalate_to_human(
            self.conv, reason_code=d.handoff_reason,
            priority=d.handoff_priority,
            detail=d.meta['handoff_detail'],
        )

        handoff = HumanHandoff.objects.get(conversation=self.conv)
        self.assertEqual(handoff.reason_detail, 'posibles convulsiones')
        self.assertNotIn('30 minutos', handoff.reason_detail)

    def test_wants_human_escalates(self):
        d = self._eval("me pasas con una persona por favor")
        self.assertEqual(d.kind, policy.ESCALATE)
        self.assertEqual(d.handoff_reason, HumanHandoff.REASON_EXPLICIT)

    def test_optout_closes_and_stops_proactive_only(self):
        """W1-10: la baja corta los proactivos, NO silencia al contacto.

        Con `is_blocked` un "ya no me escriban" dejaba al cliente inalcanzable
        para siempre; la spec (INT-04) dice que si vuelve a escribir se le
        atiende normal.
        """
        d = self._eval("ya no me escriban")
        self.assertEqual(d.kind, policy.CLOSE)
        self.contact.refresh_from_db()
        self.assertTrue(self.contact.proactive_opt_out)
        self.assertFalse(self.contact.is_blocked)

    def test_bot_question_replies_without_escalating(self):
        self.conv.flow["pending_action"] = {"tool": "x"}
        self.conv.save()
        d = self._eval("eres un robot?")
        self.assertEqual(d.kind, policy.REPLY)
        self.assertEqual(d.text, tier0.T0_BOTQ)
        self.conv.refresh_from_db()
        self.assertIn("pending_action", self.conv.flow)  # NO lo descarta


class ConfirmationFlowTests(PolicyTestCase):
    def setUp(self):
        super().setUp()
        confirmations.stage_pending(
            self.conv, tool='create_appointment', args={},
            paraphrase='Te confirmo: cita para Luna. ¿Es correcto?',
        )
        pending = confirmations.get_pending(self.conv)
        proposal = Message.objects.create(
            organization=self.org, channel_account=self.channel,
            conversation=self.conv, contact=self.contact,
            direction=Message.DIRECTION_OUT, author_type=Message.AUTHOR_SYSTEM,
            semantic_type=Message.SEMANTIC_CONFIRMATION,
            operation_key=pending['proposal_id'], body=pending['paraphrase'],
            status=Message.STATUS_SENT,
        )
        confirmations.bind_pending_message(self.conv, proposal.pk)

    def test_defer_keeps_pending(self):
        d = self._eval("ahorita")
        self.assertEqual(d.kind, policy.REPLY)
        self.assertEqual(d.text, tier0.T0_DEFER)
        self.conv.refresh_from_db()
        self.assertIn("pending_action", self.conv.flow)

    def test_affirmative_runs_planner(self):
        d = self._eval("sí, dale")
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.assertEqual(d.meta.get("confirm"), "affirmative")

    def test_affirmative_without_a_proposal_never_reaches_the_planner(self):
        confirmations.clear_pending(self.conv)

        d = self._eval('sí')

        self.assertEqual(d.kind, policy.REPLY)
        self.assertEqual(d.meta.get('reason'), 'orphan_affirmative')
        self.assertEqual(d.text, tier0.T0_CONFIRMATION_UNAVAILABLE)

    def test_acknowledgement_without_a_proposal_is_silent(self):
        confirmations.clear_pending(self.conv)

        d = self._eval('ok')

        self.assertEqual(d.kind, policy.SILENT)
        self.assertEqual(d.meta.get('reason'), 'acknowledgement')

    def test_affirmative_with_explicit_intent_reaches_the_planner(self):
        confirmations.clear_pending(self.conv)

        d = self._eval('sí, voy a asistir')

        self.assertEqual(d.kind, policy.RUN_PLANNER)

    def test_unbound_pending_is_invalidated_before_an_affirmative(self):
        pending = confirmations.get_pending(self.conv)
        pending.pop('proposal_message_id')
        self.conv.flow['pending_action'] = pending
        self.conv.save(update_fields=['flow'])

        d = self._eval('sí')

        self.assertEqual(d.kind, policy.REPLY)
        self.assertEqual(d.meta.get('reason'), 'unbound_confirmation')
        self.conv.refresh_from_db()
        self.assertNotIn('pending_action', self.conv.flow)


    def test_reaffirmation_with_words_commits_once(self):
        """Un reclamo que reafirma el sí no puede abrir otra propuesta."""
        d = self._eval("que sí te dije")
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.assertEqual(d.meta.get("confirm"), "affirmative")

    def test_emphatic_short_reaffirmation_commits_once(self):
        d = self._eval("QUE SÍ")
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.assertEqual(d.meta.get("confirm"), "affirmative")

    def test_reaffirmation_with_complaint_commits_once(self):
        d = self._eval("no entiendes que es sí?")
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.assertEqual(d.meta.get("confirm"), "affirmative")

    def test_question_keeps_pending_without_repeating_proposal(self):
        d = self._eval("¿qué día era?")
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.assertTrue(d.meta.get("pending_context"))
        self.assertNotIn("confirm", d.meta)
        self.conv.refresh_from_db()
        self.assertIn("pending_action", self.conv.flow)

    def test_unrelated_question_does_not_supersede_pending(self):
        d = self._eval("tengo otra pregunta: ¿abren los domingos?")
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.assertTrue(d.meta.get("pending_context"))
        self.conv.refresh_from_db()
        self.assertIn("pending_action", self.conv.flow)

    def test_negative_discards_and_continues(self):
        d = self._eval("no, mejor no")
        self.conv.refresh_from_db()
        self.assertNotIn("pending_action", self.conv.flow)
        self.assertEqual(d.kind, policy.RUN_PLANNER)

    def test_new_operation_supersedes_stale_pending_before_planning(self):
        """Regression: a later cancellation request cannot confirm an old booking."""
        d = self._eval("quiero cancelar la cita de Luna")

        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.assertNotIn("confirm", d.meta)
        self.conv.refresh_from_db()
        self.assertNotIn("pending_action", self.conv.flow)
        self.assertEqual(
            self.conv.flow["last_superseded_pending"]["tool"],
            "create_appointment",
        )

    def test_ambiguous_confirmation_supersedes_old_parameters(self):
        """"Sí, pero para otra mascota" needs a new proposal, never a commit."""
        d = self._eval("sí, pero para otra mascota")

        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.assertNotIn("confirm", d.meta)
        self.conv.refresh_from_db()
        self.assertNotIn("pending_action", self.conv.flow)


class NoPassiveVerificationTests(PolicyTestCase):
    """ADR p59 · `policy` ya NO verifica identidad por su cuenta.

    Aquí se probaba la ruta pasiva: `policy` escaneaba la ráfaga y promovía si
    encontraba el nombre de una mascota del expediente. Funcionaba porque una
    gramática cerrada decidía si el cliente «había querido decirlo» — y era esa
    gramática la que, en producción, rechazó a un cliente legítimo que había
    contestado bien.

    Retirada la gramática, este escaneo promovería con cualquier coincidencia de
    token («anoche vi la luna» con una mascota llamada Luna), que es exactamente
    el bug que la gramática existía para tapar. Así que la ruta pasiva cae con
    ella y queda **una sola vía**: `identify_client`, donde el modelo propone la
    lectura y el servidor la comprueba contra el texto real del cliente.
    """

    def test_naming_the_pet_no_longer_verifies_in_the_router(self):
        """El caso que ANTES verificaba. Ahora se verifica un paso más adelante:
        la tool personal rebota, el modelo llama a `identify_client` y reintenta,
        todo dentro del mismo turno."""
        self._eval_burst("hola, quiero cita para Luna")
        self.contact.refresh_from_db()
        self.assertEqual(
            self.contact.verification_level,
            ContactIdentity.VERIFICATION_PHONE_MATCH,
        )

    def test_a_bare_mention_does_not_verify_either(self):
        """Lo que la gramática protegía sigue protegido, y sin gramática: nadie
        promueve sin que el modelo lo proponga."""
        self._eval_burst("anoche vi la luna")
        self.contact.refresh_from_db()
        self.assertEqual(
            self.contact.verification_level,
            ContactIdentity.VERIFICATION_PHONE_MATCH,
        )

    def test_the_router_never_touches_the_commitment_slot(self):
        """Satisfacer el slot es parte del commit de `verify_pet_evidence`, y
        `policy` ya no lo llama."""
        commitment = goals.start_identity(
            self.conv, goals.TITULAR_CHALLENGE, first_factor='pet')
        self._eval_burst("cita para Luna")
        commitment.refresh_from_db()
        self.assertIsNone(commitment.slots.get('pet', {}).get('value'))

    def test_the_router_does_not_import_the_evidence_service(self):
        """Gate estático: una vía nueva en el router reintroduciría la promoción
        sin propuesta del modelo, que es lo que p59 cierra."""
        from pathlib import Path
        source = (Path(__file__).resolve().parent.parent
                  / 'policy.py').read_text(encoding='utf-8')
        for gone in ('resolve_pet_evidence', 'verify_pet_evidence'):
            self.assertNotIn(gone, source, f'{gone} volvió a `policy`: ver p59')


class BudgetAndScopeTests(PolicyTestCase):
    def test_budget_exhausted_escalates(self):
        from django.conf import settings as dj_settings
        # W1-5: el tope subió de 15 a 40 (15 se agotaba al 5º mensaje).
        self.conv.total_llm_calls = (
            dj_settings.AGENT_MAX_LLM_TURNS_PER_CONVERSATION)
        self.conv.save()
        d = self._eval("y otra pregunta")
        self.assertEqual(d.kind, policy.ESCALATE)
        self.assertEqual(d.handoff_reason, HumanHandoff.REASON_BUDGET)

    def test_thanks_reaches_the_model(self):
        """É-F5 Fase 5. Antes: `REPLY` con `T0_THANKS`.

        Un "gracias" es de las mejores ocasiones de sonar humano y era justo
        donde el sistema contestaba con una constante.
        """
        d = self._eval("muchas gracias")
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.assertTrue(situation.read(self.conv, "muchas gracias")["agradece"])

    def test_payment_reaches_the_model_with_the_limit_as_a_fact(self):
        """É-F5 Fase 5. Antes: `REPLY` con `T0_OUT_PAYMENT`.

        Lo que impide cobrar por WhatsApp no era esa plantilla: es que no
        existe ninguna herramienta de cobro. La frase pasa al modelo; el
        límite se queda donde siempre estuvo.
        """
        text = "te puedo pagar por aquí con transferencia?"
        d = self._eval(text)
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.assertTrue(
            situation.read(self.conv, text)
            ["quiere_pagar_por_aqui_y_aqui_no_se_cobra"])

    def test_normal_query_runs_planner(self):
        d = self._eval("cuánto cuesta la consulta")
        self.assertEqual(d.kind, policy.RUN_PLANNER)


class IdentityIsNoLongerPreemptedTests(PolicyTestCase):
    """El contrato NUEVO del router en identidad (É-F5 Fase 2, ADR p56 §4).

    Aquí vivían cuatro clases —IdentityChallengeTests, IdentityTriageTests,
    TriageMatcherTests, DeviationTests e IdentityTriageDoneNotOverwrittenTests—
    con ~430 líneas que verificaban etapa por etapa una máquina de estados
    retirada: qué plantilla tocaba, cuándo se avanzaba de factor, cuántos
    desvíos caben antes de escalar.

    Sus garantías NO se perdieron; cambiaron de capa y de dueño:

    - «datos correctos → verificado» y «datos incorrectos → sin vínculo» viven
      en `test_f5_fase1.IdentifyClientTests` y `test_family_link`, sobre la
      herramienta que ahora dictamina.
    - «no se revela nada bajo el nivel requerido» sigue siendo
      `_verification_ok` en `run_tool`, y lo cubre la suite adversarial.

    Lo que SÍ se perdió, y conviene que esté escrito en vez de desaparecer con
    los tests: la escalada tras dos datos equivocados era **estructural** —la
    conducía el router— y ahora depende de que el modelo decida pedir ayuda.
    La seguridad no cambia (nadie entra sin verificar); lo que deja de estar
    garantizado es que un cliente atascado llegue a un humano. Es el riesgo
    §11.4 del plan, y se mide con el eval real, no con esta suite.
    """

    def test_un_numero_sin_registro_llega_al_modelo(self):
        """Antes lo interceptaba el tamiz (paso 12b) antes de que el modelo
        viera el mensaje. Ese era el defecto que abrió É-F5."""
        self.contact.owner = None
        self.contact.verification_level = ContactIdentity.VERIFICATION_UNKNOWN
        self.contact.save()

        decision = self._eval("quiero una cita para mi mascota")

        self.assertEqual(decision.kind, policy.RUN_PLANNER)

    def test_el_router_no_emite_ninguna_plantilla_de_identidad(self):
        """Guarda de regresión: si alguien vuelve a meter un reto en el
        router, esto lo caza aunque los tests de arriba sigan verdes."""
        self.contact.owner = None
        self.contact.verification_level = ContactIdentity.VERIFICATION_UNKNOWN
        self.contact.save()

        for text in ("quiero una cita", "ya he ido antes", "soy nuevo",
                     "quiero cancelar mi cita", "¿qué citas tengo?"):
            with self.subTest(text=text):
                decision = self._eval(text)
                self.assertNotEqual(decision.meta.get('reason'),
                                    'identity_triage')


class IdentityStateLivesInTheModelGateTests(SimpleTestCase):
    """Gate (a) — R7: el estado de un reto de identidad NO vuelve a `flow`.

    Precedente doble y real: la conv 13 perdió el `4586` correcto porque el
    reto se destruía con un `pop` (S2/CR-5), y la auditoría encontró cinco
    implementaciones del mismo objeto, cuatro de ellas en un blob JSON que no
    se agrega, no se mide y se tira entero (§10.2). Desde É-F4 Fase 3 los
    retos son compromisos; este gate impide la recaída.

    Excepción declarada: `pending_action` (confirmación tier-2) SIGUE en
    `flow` a propósito — queda fuera del alcance de la Fase 3 (§11 del plan)
    y unificarlo es trabajo de otro sprint con su propia entrada en el ADR.
    """

    _IDENTITY_KEYS = (
        "'identity_challenge'", "'family_challenge'", "'identity_triage'",
        '"identity_challenge"', '"family_challenge"', '"identity_triage"',
    )
    _RUNTIME_MODULES = ('policy', 'tools', 'planner', 'prompts', 'views')

    def test_no_runtime_module_stores_challenge_state_in_flow(self):
        import importlib
        offenders = []
        for name in self._RUNTIME_MODULES:
            module = importlib.import_module(f'apps.agent.{name}')
            with open(module.__file__, encoding='utf-8') as fh:
                for number, line in enumerate(fh, start=1):
                    if 'flow' not in line:
                        continue
                    if any(key in line for key in self._IDENTITY_KEYS):
                        offenders.append((name, number, line.strip()))
        self.assertEqual(
            offenders, [],
            "El estado de identidad volvió a `Conversation.flow` "
            f"{offenders}. Vive en el compromiso (R7): usa "
            "`goals.start_identity` / `get_identity_commitment`.",
        )
