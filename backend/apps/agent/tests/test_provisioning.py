"""
test_provisioning.py — É-F0 PR-3: comando provision_channel.

Idempotencia + guard R1 (un phone_number_id jamás se reasigna entre orgs).
"""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.agent.models import AgentSettings
from apps.channels.models import ChannelAccount
from apps.core.models import Permission, Role
from apps.core.permissions_codes import PERMISSIONS
from apps.organizations.models import Organization

User = get_user_model()


def _seed_agent_role(org):
    role, _ = Role.objects.get_or_create(
        name="AGENT", organization=org, defaults={"is_system_role": True}
    )
    perms = [Permission.objects.get_or_create(code=c)[0] for c in PERMISSIONS["AGENT"]]
    role.permissions.set(perms)
    return role


def _provision(org, phone_number_id, **extra):
    out = StringIO()
    call_command(
        "provision_channel",
        org=str(org.public_id),
        phone_number_id=phone_number_id,
        stdout=out,
        **extra,
    )
    return out.getvalue()


class ProvisionChannelTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Prov Org", timezone="UTC")
        _seed_agent_role(self.org)

    def test_provisions_all_three_pieces(self):
        _provision(self.org, "444000444", display_number="+5215588887777")

        agent = User.objects.get(
            organization=self.org, role="AGENT", is_service_account=True,
        )
        self.assertFalse(agent.has_usable_password())

        settings_obj = AgentSettings.objects.get(organization=self.org)
        self.assertFalse(settings_obj.enabled)  # kill switch arranca apagado
        self.assertEqual(settings_obj.agent_user, agent)

        channel = ChannelAccount.objects.get(external_account_id="444000444")
        self.assertEqual(channel.organization, self.org)
        self.assertEqual(channel.display_number, "+5215588887777")

    def test_is_idempotent(self):
        _provision(self.org, "555000555")
        _provision(self.org, "555000555")
        self.assertEqual(
            ChannelAccount.objects.filter(external_account_id="555000555").count(), 1
        )
        self.assertEqual(AgentSettings.objects.filter(organization=self.org).count(), 1)
        self.assertEqual(
            User.objects.filter(organization=self.org, role="AGENT").count(), 1
        )

    def test_rejects_phone_number_id_of_another_org(self):
        """Guard R1: reasignar un número re-enrutaría conversaciones de una
        clínica a otra — el comando aborta, sin escrituras parciales."""
        _provision(self.org, "666000666")
        org_b = Organization.objects.create(name="Prov Org B", timezone="UTC")
        _seed_agent_role(org_b)
        with self.assertRaises(CommandError):
            _provision(org_b, "666000666")
        channel = ChannelAccount.objects.get(external_account_id="666000666")
        self.assertEqual(channel.organization, self.org)  # intacto

    def test_unknown_org_fails(self):
        with self.assertRaises(CommandError):
            call_command(
                "provision_channel",
                org="00000000-0000-0000-0000-000000000000",
                phone_number_id="777000777",
            )

    def test_does_not_reenable_kill_switch(self):
        """Re-provisionar NO enciende el agente: enabled es decisión de la
        clínica (bandeja), no del comando."""
        _provision(self.org, "888000888")
        settings_obj = AgentSettings.objects.get(organization=self.org)
        settings_obj.enabled = True
        settings_obj.save(update_fields=["enabled"])

        _provision(self.org, "888000888")
        settings_obj.refresh_from_db()
        self.assertTrue(settings_obj.enabled)  # no lo tocó
