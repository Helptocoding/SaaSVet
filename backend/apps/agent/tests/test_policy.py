"""
test_policy.py — É-F1 PR-11: Policy Engine (orden del router, spec §3/§11.2).
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.agent import policy, tier0
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
        self.settings = AgentSettings.objects.create(
            organization=self.org, enabled=True,
            faq_facts={"telefono": "55-1234-5678"},
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
