"""
test_policy.py — É-F1 PR-11: Policy Engine (orden del router, spec §3/§11.2).
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.agent import matchers, policy, tier0
from apps.agent.models import (
    AgentSettings,
    ContactIdentity,
    Conversation,
    HumanHandoff,
)
from apps.channels.models import ChannelAccount
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
        self.assertIn("55-1234-5678", d.text)

    def test_emergency_discards_pending_action(self):
        self.conv.flow["pending_action"] = {"tool": "x"}
        self.conv.save()
        self._eval("se está muriendo")
        self.conv.refresh_from_db()
        self.assertNotIn("pending_action", self.conv.flow)

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
        self.conv.flow["pending_action"] = {"tool": "create_appointment"}
        self.conv.save()

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

    def test_negative_discards_and_continues(self):
        d = self._eval("no, mejor no")
        self.conv.refresh_from_db()
        self.assertNotIn("pending_action", self.conv.flow)
        self.assertEqual(d.kind, policy.RUN_PLANNER)


class IdentityChallengeTests(PolicyTestCase):
    def test_challenge_flow_success(self):
        policy.start_identity_challenge(self.conv)
        d = self._eval("Luna")
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.contact.refresh_from_db()
        self.assertEqual(
            self.contact.verification_level,
            ContactIdentity.VERIFICATION_CONFIRMED,
        )

    def test_challenge_retry_then_owner_then_fail(self):
        policy.start_identity_challenge(self.conv)
        # 1er no-match → repetición (no cuenta).
        d1 = self._eval("Firulais")
        self.assertEqual(d1.text, tier0.T0_CHALLENGE_RETRY)
        # 2º no-match → 2º factor (titular).
        d2 = self._eval("Solovino")
        self.assertEqual(d2.text, tier0.T0_CHALLENGE_OWNER)
        # titular incorrecto → E-06.
        d3 = self._eval("Pedro Gómez")
        self.assertEqual(d3.kind, policy.ESCALATE)
        self.assertEqual(d3.handoff_reason, HumanHandoff.REASON_IDENTITY)

    def test_challenge_owner_second_factor_success(self):
        policy.start_identity_challenge(self.conv)
        self._eval("Firulais")   # retry
        self._eval("Rex")        # → owner stage
        d = self._eval("Ana Torres")
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.contact.refresh_from_db()
        self.assertEqual(
            self.contact.verification_level,
            ContactIdentity.VERIFICATION_CONFIRMED,
        )


class ImplicitVerificationTests(PolicyTestCase):
    def test_naming_pet_verifies_passively(self):
        self._eval("hola, quiero cita para Luna")
        self.contact.refresh_from_db()
        self.assertEqual(
            self.contact.verification_level,
            ContactIdentity.VERIFICATION_CONFIRMED,
        )


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

    def test_thanks_closes_cordially(self):
        d = self._eval("muchas gracias")
        self.assertEqual(d.kind, policy.REPLY)
        self.assertEqual(d.text, tier0.T0_THANKS)

    def test_payment_out_of_scope(self):
        d = self._eval("te puedo pagar por aquí con transferencia?")
        self.assertEqual(d.kind, policy.REPLY)
        self.assertEqual(d.meta.get("reason"), "out_payment")

    def test_normal_query_runs_planner(self):
        d = self._eval("cuánto cuesta la consulta")
        self.assertEqual(d.kind, policy.RUN_PLANNER)


class IdentityTriageTests(PolicyTestCase):
    """Tamiz UX-05: un número sin registro NUNCA se asume cliente nuevo.

    Y decir "ya soy cliente" no manda a nadie con un humano: arranca el reto
    que lo busca en `Owner` y lo verifica, para que el agente siga atendiendo.
    Solo una verificación FALLIDA escala (eso ya lo cubre `_family_fail`).
    """

    def setUp(self):
        super().setUp()
        self.unknown_contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215500001111",
            phone_normalized="5500001111",
        )
        self.unknown_conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.unknown_contact,
        )

    def _eval_unknown(self, text):
        return policy.evaluate(self.unknown_conv, text,
                               agent_settings=self.settings)

    def test_personal_action_from_unregistered_number_asks_triage(self):
        d = self._eval_unknown("quiero agendar una cita")
        self.assertEqual(d.kind, policy.REPLY)
        self.assertEqual(d.meta.get("triage"), "asked")
        self.assertIn("primera vez", d.text.lower())
        self.unknown_conv.refresh_from_db()
        self.assertIn("identity_triage", self.unknown_conv.flow)

    def test_price_question_does_not_trigger_triage(self):
        """Precio/horario se atienden en anónimo: el tamiz sería fricción."""
        d = self._eval_unknown("cuánto cuesta una cita?")
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.unknown_conv.refresh_from_db()
        self.assertNotIn("identity_triage", self.unknown_conv.flow)

    def test_registered_number_skips_triage(self):
        d = self._eval("quiero agendar una cita")
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.conv.refresh_from_db()
        self.assertNotIn("identity_triage", self.conv.flow)

    def test_new_client_answer_yields_to_planner(self):
        self._eval_unknown("quiero agendar una cita")
        d = self._eval_unknown("es mi primera vez")
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.assertEqual(d.meta.get("triage"), "new")
        self.unknown_conv.refresh_from_db()
        self.assertNotIn("identity_triage", self.unknown_conv.flow)

    def test_returning_client_is_found_and_verified_without_handoff(self):
        """El caso que el PO corrigió: "ya soy cliente" NO escala. Se busca en
        la tabla, se verifica (mascota + 4 dígitos) y el agente continúa."""
        self._eval_unknown("quiero agendar una cita")

        d = self._eval_unknown("ya soy cliente, cambié de número")
        self.assertEqual(d.kind, policy.REPLY)
        self.assertEqual(d.meta.get("triage"), "returning")

        d = self._eval_unknown("Ana Torres")
        self.assertEqual(d.kind, policy.REPLY)
        self.unknown_conv.refresh_from_db()
        family = self.unknown_conv.flow["family_challenge"]
        self.assertEqual(family["stage"], "pet")
        self.assertIn(self.owner.pk, family["candidate_ids"])

        self._eval_unknown("Luna")
        self.unknown_conv.refresh_from_db()
        self.assertEqual(
            self.unknown_conv.flow["family_challenge"]["stage"], "digits")

        d = self._eval_unknown("8877")  # últimos 4 de 5511998877
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.assertTrue(d.meta.get("verified"))
        self.unknown_contact.refresh_from_db()
        self.assertEqual(self.unknown_contact.owner_id, self.owner.pk)
        self.assertEqual(
            self.unknown_contact.verification_level,
            ContactIdentity.VERIFICATION_CONFIRMED,
        )
        self.assertEqual(
            HumanHandoff.objects.filter(conversation=self.unknown_conv).count(),
            0,
        )

    def test_already_answered_in_the_same_message_is_not_re_asked(self):
        """"soy nuevo, quiero cita" ya contesta el tamiz: preguntarlo sería la
        repregunta robótica que la métrica `tasa_repregunta` persigue."""
        d = self._eval_unknown("soy nuevo, quiero cita")
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.assertEqual(d.meta.get("triage"), "new")
        self.unknown_conv.refresh_from_db()
        self.assertNotIn("identity_triage", self.unknown_conv.flow)

    def test_already_says_returning_goes_straight_to_lookup(self):
        d = self._eval_unknown("ya soy cliente, quiero agendar una cita")
        self.assertEqual(d.kind, policy.REPLY)
        self.assertEqual(d.meta.get("triage"), "returning")
        self.unknown_conv.refresh_from_db()
        self.assertEqual(
            self.unknown_conv.flow["identity_triage"]["stage"], "titular")

    def test_unclear_answer_re_asks_once_then_yields(self):
        self._eval_unknown("quiero agendar una cita")
        d = self._eval_unknown("mmm pues no sé")
        self.assertEqual(d.kind, policy.REPLY)
        self.assertEqual(d.meta.get("triage"), "retry")
        d = self._eval_unknown("pues eso")
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.assertEqual(d.meta.get("triage"), "unclear")

    def test_first_contact_opens_with_the_clinic_welcome(self):
        """Sin salientes previos el tamiz es lo PRIMERO que lee el cliente:
        abre con bienvenida, no hablándole de la base de datos (§2.1)."""
        d = self._eval_unknown("quiero agendar una cita")
        self.assertIn(self.org.name, d.text)
        self.assertNotIn("registrado", d.text.lower())

    def test_triage_replies_carry_the_privacy_notice_flag(self):
        """UX-01: el aviso just-in-time va antes de pedir datos personales."""
        d = self._eval_unknown("quiero agendar una cita")
        self.assertTrue(d.meta.get("privacy_notice"))
        d = self._eval_unknown("ya soy cliente")
        self.assertTrue(d.meta.get("privacy_notice"))

    def test_pet_already_named_skips_that_factor(self):
        """Nombró a Luna en el primer mensaje: pedírsela otra vez sería la
        repregunta más torpe. Se salta al último factor."""
        from apps.channels.models import Message
        Message.objects.create(
            organization=self.org, channel_account=self.channel,
            conversation=self.unknown_conv,
            direction=Message.DIRECTION_IN,
            author_type=Message.AUTHOR_CLIENT,
            body="quiero agendar cita para Luna",
            status=Message.STATUS_PROCESSED,
        )
        self._eval_unknown("quiero agendar cita para Luna")
        self._eval_unknown("ya soy cliente")
        d = self._eval_unknown("Ana Torres")

        self.unknown_conv.refresh_from_db()
        family = self.unknown_conv.flow["family_challenge"]
        self.assertEqual(family["stage"], "digits")
        self.assertEqual(family["candidate_ids"], [self.owner.pk])
        self.assertIn("4 dígitos", d.text)

        d = self._eval_unknown("8877")
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.unknown_contact.refresh_from_db()
        self.assertEqual(self.unknown_contact.owner_id, self.owner.pk)

    def test_triage_is_asked_once_per_conversation(self):
        self._eval_unknown("quiero agendar una cita")
        self._eval_unknown("es mi primera vez")
        d = self._eval_unknown("quiero agendar una cita")
        self.assertEqual(d.kind, policy.RUN_PLANNER)

    def test_emergency_still_beats_triage(self):
        """El tamiz vive DESPUÉS de urgencia: nunca la retrasa."""
        d = self._eval_unknown("quiero una cita, mi perro convulsiona")
        self.assertEqual(d.kind, policy.ESCALATE)
        self.assertEqual(d.handoff_reason, HumanHandoff.REASON_EMERGENCY)


class TriageMatcherTests(PolicyTestCase):
    """D4/D5: recall del clasificador y falsos positivos de la puerta.

    Cada frase es es-MX que un cliente escribe de verdad; el diccionario se
    amplió porque muchas caían en 'unclear' y disparaban un reintento que se
    lee como "no te entendí".
    """

    def test_returning_phrasings(self):
        for phrase in [
            "ya vine antes", "sí, ya había venido", "ya fui el año pasado",
            "ya llevé a mi perro con ustedes", "ya me atendieron ahí",
            "ya soy cliente", "soy paciente de ahí", "ya tengo expediente",
            "ya me conocen", "no es la primera vez", "no soy nuevo",
            "cambié de número", "es que tengo otro número",
        ]:
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    matchers.classify_client_triage(phrase), "returning")

    def test_new_phrasings(self):
        for phrase in [
            "primera vez", "es mi primera vez", "sí, primera visita",
            "soy nuevo", "somos nuevos", "nunca he ido",
            "nunca lo he llevado", "apenas voy a llevarlo",
            "no soy cliente", "no tengo expediente", "no estoy registrado",
        ]:
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    matchers.classify_client_triage(phrase), "new")

    def test_negations_are_not_read_backwards(self):
        """"no soy cliente" contiene "soy cliente"; "no es la primera" contiene
        "primera". Sin evaluar las negaciones primero, ambas salían al revés."""
        self.assertEqual(
            matchers.classify_client_triage("no soy cliente"), "new")
        self.assertEqual(
            matchers.classify_client_triage("no es la primera vez"), "returning")

    def test_bare_yes_no_stays_unclear(self):
        """Adivinar aquí abre expedientes duplicados: mejor re-preguntar."""
        for phrase in ["sí", "no", "ajá", "pues no sé"]:
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    matchers.classify_client_triage(phrase), "unclear")

    def test_info_questions_do_not_need_identity(self):
        for phrase in [
            "¿cuánto tarda una cita?", "¿qué incluye la cita?",
            "¿necesito cita o puedo llegar así?", "¿atienden sin cita?",
            "¿cuánto cuesta una cita?", "¿qué horario tienen?",
            "¿dónde están?", "¿qué necesito para la primera consulta?",
        ]:
            with self.subTest(phrase=phrase):
                self.assertFalse(matchers.wants_personal_action(phrase))

    def test_real_requests_still_need_identity(self):
        for phrase in [
            "quiero agendar una cita", "me das una cita para mañana",
            "¿qué citas tengo?", "quiero cancelar mi cita",
            "necesito una cita para mi perro", "¿cuándo le toca la vacuna?",
        ]:
            with self.subTest(phrase=phrase):
                self.assertTrue(matchers.wants_personal_action(phrase))


class DeviationTests(IdentityTriageTests):
    """Fase 0 §0.2 — R1/R9: una pregunta durante un reto nunca es un fallo.

    Reproduce el caso concreto de la conv 13 (`85a2a691`): el cliente dio los
    4 factores correctos y preguntó "¿para qué necesitas eso?" antes de dar
    los últimos 4 dígitos. Con el sistema viejo eso sumaba `fails` dos veces
    y tiraba el reto que estaba a punto de pasar.
    """

    def _reach_digits_stage(self):
        # `_seed_family_challenge` salta el factor de mascota si YA se nombró
        # antes en la conversación (mismo patrón que
        # `test_pet_already_named_skips_that_factor`): necesita el `Message`
        # persistido, no solo el texto pasado a `policy.evaluate`.
        from apps.channels.models import Message
        Message.objects.create(
            organization=self.org, channel_account=self.channel,
            conversation=self.unknown_conv,
            direction=Message.DIRECTION_IN,
            author_type=Message.AUTHOR_CLIENT,
            body="quiero agendar cita para Luna",
            status=Message.STATUS_PROCESSED,
        )
        self._eval_unknown("quiero agendar cita para Luna")
        self._eval_unknown("ya soy cliente")
        self._eval_unknown("Ana Torres")
        self.unknown_conv.refresh_from_db()
        self.assertEqual(
            self.unknown_conv.flow["family_challenge"]["stage"], "digits")

    def test_conv13_question_at_digits_gets_reason_not_fail(self):
        self._reach_digits_stage()
        d = self._eval_unknown("para que necesitas eso")
        self.assertEqual(d.kind, policy.REPLY)
        self.assertIn(tier0.FACTOR_WHY['digits'], d.text)
        self.unknown_conv.refresh_from_db()
        family = self.unknown_conv.flow["family_challenge"]
        self.assertEqual(family.get("fails", 0), 0)

        # el dato correcto, llegado después, verifica con normalidad.
        d = self._eval_unknown("8877")   # últimos 4 de 5511998877
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.assertTrue(d.meta.get("verified"))

    def test_digits_shaped_question_advances_no_deviation(self):
        """"¿es 8877?" TRAE la respuesta: no es un desvío."""
        self._reach_digits_stage()
        d = self._eval_unknown("¿es 8877?")
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.assertTrue(d.meta.get("verified"))

    def test_three_deviations_escalate_with_deviation_cap(self):
        self._reach_digits_stage()
        self._eval_unknown("para que necesitas eso")
        self._eval_unknown("por que me pides eso")
        d = self._eval_unknown("no entiendo para que")
        self.assertEqual(d.kind, policy.ESCALATE)
        self.assertEqual(d.meta.get("handoff_detail"), "deviation_cap")
        self.unknown_conv.refresh_from_db()
        self.assertNotIn("family_challenge", self.unknown_conv.flow)
        self.assertNotIn("deviations", self.unknown_conv.flow)


class IdentityTriageDoneNotOverwrittenTests(IdentityTriageTests):
    """Fase 0 §0.4 — conv 13 S6: dos 'unclear' del tamiz no deben pisar un
    'returning' ya decidido (setdefault, no asignación directa)."""

    def test_returning_survives_a_stray_unclear_resolution(self):
        self.unknown_conv.flow['identity_triage_done'] = 'returning'
        self.unknown_conv.flow['identity_triage'] = {'stage': 'ask', 'asks': 2}
        self.unknown_conv.save(update_fields=['flow'])
        d = policy._advance_identity_triage(
            self.unknown_conv, self.unknown_contact, "que dijiste",
            self.unknown_conv.flow['identity_triage'])
        self.assertEqual(d.kind, policy.RUN_PLANNER)
        self.unknown_conv.refresh_from_db()
        self.assertEqual(
            self.unknown_conv.flow.get('identity_triage_done'), 'returning')


class FsmTests(PolicyTestCase):
    def test_escalate_to_human_is_idempotent(self):
        policy.escalate_to_human(self.conv, reason_code=HumanHandoff.REASON_EXPLICIT)
        policy.escalate_to_human(self.conv, reason_code=HumanHandoff.REASON_EXPLICIT)
        self.assertEqual(
            HumanHandoff.objects.filter(conversation=self.conv).count(), 1,
        )
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.state, Conversation.STATE_HANDOFF_PENDING)

    def test_close_inactive(self):
        self.conv.last_activity_at = timezone.now() - timedelta(hours=25)
        self.conv.save()
        closed = policy.close_inactive_conversations()
        self.assertEqual(closed, 1)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.state, Conversation.STATE_CLOSED)


class NudgeTests(PolicyTestCase):
    """UX-08 (PR-18): recordatorio único de flujo abandonado."""

    def _arm(self, minutes_ago=90):
        self.conv.last_inbound_at = timezone.now() - timedelta(minutes=minutes_ago)
        self.conv.flow = {'pending_action': {
            'tool': 'create_appointment', 'args': {}, 'paraphrase': 'x'}}
        self.conv.save(update_fields=['last_inbound_at', 'flow'])

    def test_nudges_abandoned_pending_once(self):
        self._arm()
        self.assertEqual(policy.nudge_abandoned_flows(), 1)
        self.conv.refresh_from_db()
        self.assertTrue(self.conv.flow.get('nudge_sent'))
        self.assertEqual(policy.nudge_abandoned_flows(), 0)   # no repite

    def test_no_nudge_without_pending(self):
        self.conv.last_inbound_at = timezone.now() - timedelta(minutes=90)
        self.conv.save(update_fields=['last_inbound_at'])
        self.assertEqual(policy.nudge_abandoned_flows(), 0)

    def test_no_nudge_after_optout(self):
        self._arm()
        self.contact.proactive_opt_out = True
        self.contact.save(update_fields=['proactive_opt_out'])
        self.assertEqual(policy.nudge_abandoned_flows(), 0)

    def test_no_nudge_when_blocked(self):
        self._arm()
        self.contact.is_blocked = True
        self.contact.save(update_fields=['is_blocked'])
        self.assertEqual(policy.nudge_abandoned_flows(), 0)

    def test_no_nudge_when_disabled(self):
        self._arm()
        self.settings.nudge_enabled = False
        self.settings.save(update_fields=['nudge_enabled'])
        self.assertEqual(policy.nudge_abandoned_flows(), 0)

    def test_no_nudge_when_too_recent(self):
        self._arm(minutes_ago=5)   # dentro de los 60 min → aún no
        self.assertEqual(policy.nudge_abandoned_flows(), 0)
