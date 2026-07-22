"""
test_prompts.py — Ensamblado de contexto del LLM.

Bug real de piloto: el modelo alucinaba la fecha ("este viernes 21 de marzo"
en julio) porque el contexto no incluía la fecha de hoy. Estos tests anclan
que la fecha actual (en la zona de la org) SIEMPRE viaja al LLM.
"""
import json

from django.test import TestCase
from django.utils import timezone

from apps.agent import prompts
from apps.agent.models import ContactIdentity, Conversation
from apps.channels.models import ChannelAccount
from apps.organizations.models import Organization


class AssembleMessagesDateTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            name="Fecha Org", timezone="America/Mexico_City")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="990990990")
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215500000000")
        self.conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact)

    def _context_block(self):
        messages = prompts.assemble_messages(self.conv)
        self.assertEqual(messages[0]["role"], "system")
        # El primer bloque de sistema es el JSON de contexto.
        payload = messages[0]["content"].split("\n", 1)[1]
        return json.loads(payload)

    def test_context_includes_today(self):
        ctx = self._context_block()
        for key in ("fecha_hoy", "dia_semana", "hoy_legible", "hora_actual"):
            self.assertIn(key, ctx)

    def test_today_matches_org_timezone(self):
        from zoneinfo import ZoneInfo
        expected = timezone.now().astimezone(
            ZoneInfo(self.org.timezone)).date().isoformat()
        self.assertEqual(self._context_block()["fecha_hoy"], expected)

    def test_bad_timezone_does_not_crash(self):
        # Zona inválida → cae a localtime, nunca lanza (defensivo).
        Organization.objects.filter(pk=self.org.pk).update(timezone="Marte/Nada")
        self.conv.refresh_from_db()
        ctx = self._context_block()
        self.assertIn("fecha_hoy", ctx)
