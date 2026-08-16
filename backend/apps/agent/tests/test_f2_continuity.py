"""
test_f2_continuity.py — El contexto es de la PERSONA, no del episodio (F2/F3).

La queja que abrió este trabajo: «cada conversación que se cierra y el cliente
manda mensaje se crea una nueva conversación, empezando desde 0, el agente no
tiene ningún contexto». En producción un solo contacto acumuló **19
conversaciones**, y la 20 arrancó preguntando quién era.

La sesión sigue siendo por episodio —de ella cuelgan métricas, presupuesto,
claim, hand-off y compromisos— pero el transcript que ve el modelo ya no muere
con ella.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.agent import prompts, services
from apps.agent.models import ContactIdentity, Conversation
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet


class ContinuityTestCase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Cont Org", timezone="UTC")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="770100770")
        self.owner = Owner.objects.create(
            organization=self.org, name="Andrés Ruiz", phone="5511223399")
        Pet.objects.create(
            organization=self.org, owner=self.owner, name="Luna",
            species="perro", birth_date="2021-01-01")
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215511223399",
            owner=self.owner,
            verification_level=ContactIdentity.VERIFICATION_CONFIRMED,
            verified_at=timezone.now(),
        )
        self.old = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact, state=Conversation.STATE_CLOSED,
            closed_at=timezone.now() - timedelta(days=1),
        )
        self.new = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact,
        )

    def _msg(self, conversation, body, *, direction=Message.DIRECTION_IN,
             status=None, contact=None, channel=None, author=None):
        outbound = direction == Message.DIRECTION_OUT
        return Message.objects.create(
            organization=self.org,
            channel_account=channel or self.channel,
            conversation=conversation,
            contact=contact or conversation.contact,
            direction=direction,
            author_type=author or (Message.AUTHOR_AGENT if outbound
                                   else Message.AUTHOR_CLIENT),
            body=body,
            status=status or (Message.STATUS_SENT if outbound
                              else Message.STATUS_PROCESSED),
        )

    def _rendered(self, conversation=None):
        messages = prompts.assemble_messages(conversation or self.new)
        return [m['content'] for m in messages]


class CrossSessionHistoryTests(ContinuityTestCase):
    def test_a_verified_contact_sees_the_previous_session(self):
        self._msg(self.old, "mi perrita se estresa mucho en el consultorio")
        self._msg(self.new, "hola")
        self.assertTrue(
            any("se estresa mucho" in c for c in self._rendered()),
            "El hilo anterior del mismo cliente tiene que llegar al modelo",
        )

    def test_an_unverified_contact_only_sees_the_current_session(self):
        """D19 · el transcript viejo puede contener el nombre de la mascota, que
        ahora es la RESPUESTA del reto. No se entrega antes de saber quién
        escribe."""
        self.contact.verification_level = (
            ContactIdentity.VERIFICATION_PHONE_MATCH)
        self.contact.verified_at = None
        self.contact.save(update_fields=['verification_level', 'verified_at'])
        self.new.contact = self.contact

        self._msg(self.old, "mi perrita se estresa mucho")
        self._msg(self.new, "hola")
        self.assertFalse(
            any("se estresa mucho" in c for c in self._rendered()))

    def test_another_contact_never_leaks_in(self):
        other_contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215500009999")
        other_conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=other_contact)
        self._msg(other_conv, "secreto de otro cliente", contact=other_contact)
        self._msg(self.new, "hola")
        self.assertFalse(
            any("secreto de otro" in c for c in self._rendered()))

    def test_another_channel_account_of_the_same_org_is_separate(self):
        """Dos números de la misma clínica pueden ser dos flujos (agenda y
        mostrador): mezclarlos mete al modelo en una conversación que no es la
        suya."""
        other_channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="770100771")
        other_conv = Conversation.objects.create(
            organization=self.org, channel_account=other_channel,
            contact=self.contact)
        self._msg(other_conv, "esto es del otro número", channel=other_channel)
        self._msg(self.new, "hola")
        self.assertFalse(
            any("del otro número" in c for c in self._rendered()))

    def test_a_failed_outbound_is_not_part_of_the_history(self):
        """`failed` = la ventana de 24 h estaba cerrada y el proveedor no lo
        entregó. El modelo lo veía como dicho."""
        self._msg(self.old, "esto nunca salió", direction=Message.DIRECTION_OUT,
                  status=Message.STATUS_FAILED)
        self._msg(self.new, "hola")
        self.assertFalse(any("nunca salió" in c for c in self._rendered()))


class ContactFactsTests(ContinuityTestCase):
    """F3 · hechos que el sistema calcula y publica sin que nadie los pida."""

    def _context(self):
        import json
        payload = prompts.assemble_messages(self.new)[0]['content']
        return json.loads(payload.split("\n", 1)[1])

    def test_a_returning_contact_is_not_greeted_as_new(self):
        self._msg(self.old, "buenas", direction=Message.DIRECTION_OUT)
        self._msg(self.new, "hola de nuevo")
        ctx = self._context()
        self.assertTrue(ctx['ya_hablamos_antes'])
        self.assertNotIn('es_su_primer_mensaje_con_nosotros',
                         ctx.get('como_llega', {}))

    def test_a_genuinely_new_contact_still_reads_as_first_contact(self):
        fresh_contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215500001234")
        fresh_conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=fresh_contact)
        message = self._msg(fresh_conv, "hola", contact=fresh_contact)
        import json
        payload = prompts.assemble_messages(
            fresh_conv, burst_text=message.body)[0]['content']
        ctx = json.loads(payload.split("\n", 1)[1])
        self.assertTrue(
            ctx.get('como_llega', {}).get('es_su_primer_mensaje_con_nosotros'))

    def test_the_gap_excludes_the_current_burst(self):
        """El entrante YA está persistido cuando el worker arma el prompt: sin
        excluirlo, `ultimo_mensaje_hace` diría «unos minutos» siempre — lo
        contrario de lo que quiere decir."""
        old_message = self._msg(self.old, "hace un mes hablamos")
        Message.objects.filter(pk=old_message.pk).update(
            created_at=timezone.now() - timedelta(days=40))
        # La ráfaga de ESTE turno, tal como la deja el webhook.
        self._msg(self.new, "sigo aquí", status=Message.STATUS_PENDING)

        ctx = self._context()
        self.assertEqual(ctx['ultimo_mensaje_hace'], 'un mes')
        self.assertTrue(ctx['ya_hablamos_antes'])

    def test_no_facts_when_there_is_no_history(self):
        fresh_contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215500004321")
        fresh_conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=fresh_contact)
        import json
        payload = prompts.assemble_messages(fresh_conv)[0]['content']
        ctx = json.loads(payload.split("\n", 1)[1])
        self.assertNotIn('ya_hablamos_antes', ctx)


class SessionCreationTests(ContinuityTestCase):
    def test_an_open_session_is_reused(self):
        conv = services.get_or_create_open_conversation(
            self.contact, self.channel)
        self.assertEqual(conv.pk, self.new.pk)

    def test_a_closed_session_still_opens_a_new_one(self):
        """CLOSED sigue siendo terminal — lo que cambia es que el contexto ya no
        muere con el hilo."""
        self.new.state = Conversation.STATE_CLOSED
        self.new.closed_at = timezone.now()
        self.new.save(update_fields=['state', 'closed_at'])
        conv = services.get_or_create_open_conversation(
            self.contact, self.channel)
        self.assertNotEqual(conv.pk, self.new.pk)
        self.assertEqual(conv.state, Conversation.STATE_ACTIVE)

    def test_sessions_are_per_channel_account(self):
        other_channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="770100772")
        conv = services.get_or_create_open_conversation(
            self.contact, other_channel)
        self.assertNotEqual(conv.pk, self.new.pk)

    def test_duplicate_sessions_are_resolved_by_precedence(self):
        """No «la más reciente»: eso podía cerrar una que una persona está
        atendiendo y dejar viva una `active` más nueva."""
        human = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact, state=Conversation.STATE_HUMAN_ACTIVE)
        newer = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact)

        survivor = services.get_or_create_open_conversation(
            self.contact, self.channel)

        self.assertEqual(survivor.pk, human.pk)
        newer.refresh_from_db()
        self.assertEqual(newer.state, Conversation.STATE_CLOSED)
        self.assertEqual(newer.close_reason, Conversation.CLOSE_DUPLICATE)

    def test_two_human_sessions_are_never_auto_closed(self):
        """Elegir por reloj entre dos personas operando no es decisión de un
        script."""
        first = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact, state=Conversation.STATE_HUMAN_ACTIVE)
        second = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact, state=Conversation.STATE_HANDOFF_PENDING)

        services.get_or_create_open_conversation(self.contact, self.channel)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertNotEqual(first.state, Conversation.STATE_CLOSED)
        self.assertNotEqual(second.state, Conversation.STATE_CLOSED)


class CloseReasonTests(ContinuityTestCase):
    def test_idle_sweep_records_its_reason(self):
        from apps.agent import policy
        Conversation.objects.filter(pk=self.new.pk).update(
            last_activity_at=timezone.now() - timedelta(hours=48))
        policy.close_inactive_conversations()
        self.new.refresh_from_db()
        self.assertEqual(self.new.state, Conversation.STATE_CLOSED)
        self.assertEqual(self.new.close_reason, Conversation.CLOSE_IDLE)

    def test_messages_carry_their_contact(self):
        """El contrato del backfill: si hay conversación, hay contacto."""
        message = services.ingest_inbound_message(
            self.channel, wamid="wamid.F2", wa_id="5215511223399",
            body="hola",
        )
        self.assertIsNotNone(message.contact_id)
        self.assertEqual(message.contact_id, message.conversation.contact_id)
