"""
test_metrics.py — É-F2 PR-19: métricas de negocio del piloto (spec §8).
"""
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.agent.metrics import compute_business_metrics
from apps.agent.models import (
    ContactIdentity, Conversation, HumanHandoff, ToolExecution,
)
from apps.channels.models import ChannelAccount
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSIONS
from apps.organizations.models import Organization
from apps.users.models import User


def _seed_role(org, role_name):
    codes = PERMISSIONS[role_name]
    role, _ = Role.objects.get_or_create(
        name=role_name, organization=org, defaults={"is_system_role": True})
    if "*.*" in codes:
        w, _ = Permission.objects.get_or_create(code="*.*")
        role.permissions.set([w])
    else:
        role.permissions.set(
            [Permission.objects.get_or_create(code=c)[0] for c in codes])
    return role


class BusinessMetricsTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Metric Org", timezone="UTC")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="900900900")
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215511110000")
        self.conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact)

    def _tx(self, tool_name, *, decision=ToolExecution.DECISION_AUTO,
            http_status=200):
        return ToolExecution.objects.create(
            organization=self.org, conversation=self.conv, tool_name=tool_name,
            policy_decision=decision, http_status=http_status)

    def test_counts_intent_creation_cancel_and_conversion(self):
        self._tx("find_available_slots")                       # intención + oferta
        self._tx("create_appointment")                         # GET pet (propuesta)
        self._tx("create_appointment",                         # commit real
                 decision=ToolExecution.DECISION_CONFIRMED, http_status=201)
        self._tx("cancel_appointment",
                 decision=ToolExecution.DECISION_CONFIRMED, http_status=200)
        HumanHandoff.objects.create(
            organization=self.org, conversation=self.conv,
            reason_code=HumanHandoff.REASON_EMERGENCY)

        now = timezone.now()
        m = compute_business_metrics(
            self.org, now - timezone.timedelta(days=1),
            now + timezone.timedelta(days=1))

        self.assertEqual(m["conversaciones_iniciadas"], 1)
        self.assertEqual(m["con_intencion_agendar"], 1)
        self.assertEqual(m["citas_creadas"], 1)               # solo el commit
        self.assertEqual(m["cancelaciones"], 1)
        self.assertEqual(m["citas_abandonadas"], 0)
        self.assertEqual(m["tasa_conversion"], 1.0)
        self.assertEqual(m["handoffs"]["total"], 1)
        self.assertEqual(m["handoffs"]["por_motivo"]["emergency"], 1)
        self.assertEqual(m["embudo"]["slots_ofertados"], 1)

    def test_abandoned_when_intent_without_creation(self):
        self._tx("find_available_slots")   # ofertó, pero nunca se creó cita
        now = timezone.now()
        m = compute_business_metrics(
            self.org, now - timezone.timedelta(days=1),
            now + timezone.timedelta(days=1))
        self.assertEqual(m["con_intencion_agendar"], 1)
        self.assertEqual(m["citas_creadas"], 0)
        self.assertEqual(m["citas_abandonadas"], 1)
        self.assertEqual(m["tasa_conversion"], 0.0)


class MetricsEndpointTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Metric API Org", timezone="UTC")
        role = _seed_role(self.org, "ASSISTANT")
        self.user = User.objects.create_user(
            username="recep", password="p", organization=self.org, role="ASSISTANT")
        UserRole.objects.get_or_create(user=self.user, role=role)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_endpoint_returns_metrics_shape(self):
        r = self.client.get("/api/inbox/metrics/")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        for key in ("conversaciones_iniciadas", "citas_creadas",
                    "tasa_conversion", "handoffs", "embudo", "periodo"):
            self.assertIn(key, body)

    def test_endpoint_forbidden_for_agent_role(self):
        """El propio agente (rol AGENT) NO tiene agentinbox.view → 403."""
        agent_role = _seed_role(self.org, "AGENT")
        agent_user = User.objects.create_user(
            username="agent.metrics", password="p", organization=self.org,
            role="AGENT", is_service_account=True)
        UserRole.objects.get_or_create(user=agent_user, role=agent_role)
        self.client.force_authenticate(agent_user)
        r = self.client.get("/api/inbox/metrics/")
        self.assertEqual(r.status_code, 403, r.content)
