"""Regresión audit run-1, hallazgo 8.2: clínicas desactivadas no deben dejar
sin servicio al agente de las clínicas activas.

El claim durable rechaza una organización inactiva y deja su entrante
pendiente. Antes del arreglo, el selector del worker no las excluía antes de su
LIMIT 3 y ordenaba por el claim más antiguo: una org desactivada nunca vuelve a
ser reclamada, así que sube al frente, y tres de ellas llenaban el LIMIT. El
sender tenía la misma forma con su `[:batch]` sin filtrar.

Ruta real: ingesta del webhook, claim/finalize durable y bucle real del worker.
Solo se sustituye `_run_turn`, que llamaría al LLM.
"""
from unittest.mock import patch

from django.test import TransactionTestCase

from apps.agent import durable, sender, worker
from apps.agent.outbound import enqueue_outbound
from apps.agent.services import ingest_inbound_message
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization


class InactiveOrgStarvationTests(TransactionTestCase):
    def _org(self, name):
        org = Organization.objects.create(name=name, timezone='UTC')
        ch = ChannelAccount.objects.create(organization=org, external_account_id=f'starve-{name}')
        return org, ch

    def _inbound(self, ch, key):
        m = ingest_inbound_message(ch, wamid=key, wa_id='5215512345678', body=key)
        Message.objects.filter(pk=m.pk).update(available_at=None)
        return m

    def _serve_once(self, conv_id):
        witness = durable.claim_turn(conv_id)
        self.assertIsNotNone(witness, 'fixture: la org aún estaba activa')
        durable.finalize_turn(witness)

    def _scenario(self, n_inactive):
        """Las clínicas que luego se desactivan usaron el agente ANTES que la
        activa: su último claim es más viejo, sin manipular datos."""
        inactive = []
        for i in range(n_inactive):
            org, ch = self._org(f'inactiva-{i}')
            first = self._inbound(ch, f'in-{i}-a')
            self._serve_once(first.conversation_id)
            self._inbound(ch, f'in-{i}-b')
            inactive.append(org)
        _, active_ch = self._org('activa')
        first = self._inbound(active_ch, 'act-a')
        self._serve_once(first.conversation_id)
        pending = self._inbound(active_ch, 'act-b')
        Organization.objects.filter(pk__in=[o.pk for o in inactive]).update(is_active=False)
        return inactive, pending

    def test_selector_never_offers_deactivated_orgs(self):
        inactive, pending = self._scenario(4)
        candidates = list(worker._pending_conversation_candidates())
        self.assertIn(pending.conversation_id, candidates)
        offered_orgs = set(Message.objects.filter(conversation_id__in=candidates)
                           .values_list('organization_id', flat=True))
        self.assertFalse(offered_orgs & {o.pk for o in inactive})

    def test_active_clinic_is_served_despite_more_inactive_orgs_than_the_limit(self):
        inactive, pending = self._scenario(4)
        served = []

        def fake_run(witness):
            served.append(witness.conversation_id)
            durable.finalize_turn(witness)

        with patch.object(worker, '_run_turn', side_effect=fake_run):
            for _ in range(3):
                worker.process_pending_conversations(batch=10)
        self.assertIn(pending.conversation_id, served)
        # Lo de las inactivas queda pendiente, intacto, para cuando se reactiven.
        self.assertEqual(
            Message.objects.filter(organization__in=inactive, direction='in',
                                   status='pending').count(),
            len(inactive),
        )

    def test_sender_batch_skips_deactivated_backlog(self):
        inactive, pending = self._scenario(3)
        for org in inactive:
            conv = Message.objects.filter(organization=org).first().conversation
            for n in range(2):
                enqueue_outbound(conv, f'pendiente-{n}')
        active_out = enqueue_outbound(pending.conversation, 'para la activa')
        offered = []

        def fake_claim(message_id, *, organization_id, channel_account_id):
            offered.append(organization_id)
            return None

        # batch=2 < 6 salientes de inactivas creados ANTES: sin el filtro, el
        # lote entero serían salientes que claim_message rechaza.
        with patch.object(sender, 'claim_message', side_effect=fake_claim):
            sender.send_pending_outbound(batch=2)
        self.assertIn(active_out.organization_id, offered)
        self.assertFalse(set(offered) & {o.pk for o in inactive})
