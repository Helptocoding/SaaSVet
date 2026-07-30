"""
test_w1_experience.py — É-F3 W1: experiencia y conservación vinculante.

La enmienda E2 del PO gobierna este bloque: **no se quitó ninguna regla**. Las
que se pueden verificar en código pasaron del prompt (advisorio) a
`guards.py` (vinculante), y el resto se reescribió como conducta.

W1-1  guards de salida: precio inventado, consejo médico y promesas no salen.
W1-4  debounce real: la ráfaga humana se agrupa en UN turno.
W1-5  el cliente que insiste tras un handoff recibe un acuse, una sola vez.
W1-6  el reto acepta el nombre de pila; el teléfono se re-matchea.
W1-7  audio/imagen se responden con plantilla, sin gastar una llamada al LLM.
W1-8  un 400 del dominio se traduce por lo que dice, no siempre a "se ocupó".
W1-9  el saludo institucional vuelve a existir con el agente encendido.
W1-10 la baja corta proactivos; no silencia al cliente para siempre.
"""
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.agent import guards, identity, policy, services, tier0, tools
from apps.agent.llm import LLMResult, StubLLMClient
from apps.agent.models import (
    ContactIdentity,
    Conversation,
    HumanHandoff,
    LLMCall,
)
from apps.agent.services import ingest_inbound_message
from apps.agent.tests.harness import close_all_days, run_turn
from apps.agent.tests.test_w0_hardening import AgentFixture
from apps.agent.worker import process_pending_conversations
from apps.channels.models import Message
from apps.patients.models import Owner


def _later(seconds=15):
    return timezone.now() + timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# W1-1 · Guards de salida
# ---------------------------------------------------------------------------

class OutputGuardUnitTests(TestCase):
    def test_price_not_backed_by_a_tool_is_a_hard_violation(self):
        v = guards.check_output("La consulta cuesta $850", tool_facts=[])
        self.assertTrue(guards.has_hard(v))
        self.assertEqual(v[0].kind, 'invented_price')

    def test_price_present_in_tool_results_passes(self):
        facts = [{'tool': 'get_service_catalog',
                  'resultado': [{'servicio': 'Consulta', 'precio': '$350.00'}]}]
        self.assertEqual(guards.check_output("Cuesta $350 🙂", tool_facts=facts), [])

    def test_medical_advice_is_blocked(self):
        v = guards.check_output("Dale media pastilla cada 12 horas")
        self.assertTrue(guards.has_hard(v))

    def test_mexican_affirmative_is_not_medical_advice(self):
        """'dale' es un sí en México: bloquearlo escalaría conversaciones sanas."""
        self.assertEqual(guards.check_output("¡Dale! Te agendo entonces 🐾"), [])

    def test_promise_is_blocked(self):
        self.assertTrue(guards.has_hard(
            guards.check_output("Si no te gusta te devolvemos el dinero")))

    def test_jargon_is_soft(self):
        v = guards.check_output("Te dejo el invoice en draft")
        self.assertTrue(v)
        self.assertFalse(guards.has_hard(v))

    def test_clean_text_passes(self):
        self.assertEqual(
            guards.check_output("¡Listo! Te esperamos el martes 🐾"), [])


class OutputGuardPlannerTests(AgentFixture):
    account_id = "900000101"

    def test_invented_price_is_retried_once_and_then_sent_clean(self):
        bodies, result, stub = run_turn(
            self, self.conv, self.agent_user, "¿cuánto cuesta la consulta?",
            scripted_llm=[
                LLMResult(kind="text", text="Cuesta $850"),      # inventado
                LLMResult(kind="text", text="Ese dato no lo tengo a la mano 🙈"),
            ], assert_clean=False)
        self.assertEqual(result["decision"], "planner_reply")
        self.assertEqual(len(stub.calls), 2)          # hubo reintento
        self.assertNotIn("850", bodies[-1])

    def test_hard_violation_that_persists_never_reaches_the_client(self):
        bodies, result, _ = run_turn(
            self, self.conv, self.agent_user, "¿qué le doy para el dolor?",
            scripted_llm=[
                LLMResult(kind="text", text="Dale media pastilla cada 12 horas"),
                LLMResult(kind="text", text="Dale media pastilla cada 12 horas"),
            ], assert_clean=False)
        self.assertEqual(result["decision"], "guard_blocked")
        self.assertNotIn("pastilla", " ".join(bodies).lower())
        self.assertEqual(bodies[-1], tier0.T0_GUARD_BLOCKED)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.state, Conversation.STATE_HANDOFF_PENDING)


# ---------------------------------------------------------------------------
# W1-4 · Debounce real
# ---------------------------------------------------------------------------

class QuietWindowTests(AgentFixture):
    account_id = "900000102"

    def _inbound(self, wamid, body):
        return ingest_inbound_message(
            self.channel, wamid=wamid, wa_id="5215511110000", body=body)

    def test_each_message_pushes_the_whole_burst_forward(self):
        first = self._inbound("wamid.Q1", "hola")
        first.refresh_from_db()
        original = first.available_at

        second = self._inbound("wamid.Q2", "quiero una cita")
        first.refresh_from_db()
        second.refresh_from_db()
        # El primero YA no vence antes: la ráfaga espera a que el cliente calle.
        self.assertGreater(first.available_at, original)
        self.assertEqual(first.available_at, second.available_at)

    def test_hard_cap_stops_an_endless_typist(self):
        first = self._inbound("wamid.Q3", "hola")
        # El más viejo lleva 30 s: el tope (25 s) ya venció.
        Message.objects.filter(pk=first.pk).update(
            created_at=timezone.now() - timedelta(seconds=30))
        self._inbound("wamid.Q4", "sigo escribiendo")
        first.refresh_from_db()
        self.assertLessEqual(first.available_at, timezone.now())

    def test_burst_is_answered_in_a_single_turn(self):
        self._inbound("wamid.Q5", "hola")
        self._inbound("wamid.Q6", "quiero agendar")
        self._inbound("wamid.Q7", "para mañana")
        seen = {}

        def fake_turn(conversation, **kwargs):
            seen['burst'] = kwargs.get('burst')
            from apps.agent.outbound import enqueue_outbound
            enqueue_outbound(conversation, "una sola respuesta", author='agent')
            return {'decision': 'planner_reply', 'llm_calls': 1, 'tools': 0}

        with mock.patch("apps.agent.planner.handle_inbound", fake_turn):
            process_pending_conversations(now=_later())

        self.assertEqual(seen['burst'], ["hola", "quiero agendar", "para mañana"])
        self.assertEqual(
            Message.objects.filter(conversation=self.conv,
                                   direction=Message.DIRECTION_OUT).count(), 1)


class SupersededReplyTests(AgentFixture):
    account_id = "900000103"

    def _run_with_late_message(self, decision, tools_used=0):
        ingest_inbound_message(
            self.channel, wamid="wamid.S1", wa_id="5215511110000", body="hola")

        def fake_turn(conversation, **kwargs):
            from apps.agent.outbound import enqueue_outbound
            enqueue_outbound(conversation, "respuesta ya desfasada",
                             author='agent')
            # El cliente siguió escribiendo mientras el modelo pensaba.
            Message.objects.create(
                organization=self.org, channel_account=self.channel,
                conversation=conversation, direction=Message.DIRECTION_IN,
                author_type=Message.AUTHOR_CLIENT, body="para mañana",
                status=Message.STATUS_PENDING, available_at=timezone.now())
            return {'decision': decision, 'llm_calls': 1, 'tools': tools_used}

        with mock.patch("apps.agent.planner.handle_inbound", fake_turn):
            process_pending_conversations(now=_later())
        return Message.objects.filter(
            conversation=self.conv, direction=Message.DIRECTION_OUT,
        ).order_by('-id').first()

    def test_pure_text_reply_is_discarded_and_never_sent(self):
        outbound = self._run_with_late_message('planner_reply')
        self.assertEqual(outbound.status, Message.STATUS_DISCARDED)

    def test_reply_with_side_effects_is_kept(self):
        """Descartar la confirmación de algo ya ejecutado sería mucho peor."""
        outbound = self._run_with_late_message('planner_reply', tools_used=1)
        self.assertEqual(outbound.status, Message.STATUS_PENDING)

    def test_confirmation_is_never_discarded(self):
        outbound = self._run_with_late_message('awaiting_confirmation')
        self.assertEqual(outbound.status, Message.STATUS_PENDING)


# ---------------------------------------------------------------------------
# W1-5 · Handoff: acuse único
# ---------------------------------------------------------------------------

class HandoffAckTests(AgentFixture):
    account_id = "900000104"

    def setUp(self):
        super().setUp()
        policy.escalate_to_human(
            self.conv, reason_code=HumanHandoff.REASON_EXPLICIT)
        self.conv.refresh_from_db()

    def test_first_insistence_gets_an_acknowledgement(self):
        d = policy.evaluate(self.conv, "¿hola? ¿me atienden?",
                            agent_settings=self.settings)
        self.assertEqual(d.kind, policy.REPLY)
        self.assertEqual(d.text, tier0.T0_HANDOFF_WAITING)

    def test_following_messages_are_silent(self):
        policy.evaluate(self.conv, "¿hola?", agent_settings=self.settings)
        self.conv.refresh_from_db()
        d = policy.evaluate(self.conv, "sigo esperando",
                            agent_settings=self.settings)
        self.assertEqual(d.kind, policy.SILENT)

    def test_emergency_still_wins_over_the_ack(self):
        d = policy.evaluate(self.conv, "mi perro convulsiona",
                            agent_settings=self.settings)
        self.assertEqual(d.kind, policy.ESCALATE)
        self.assertEqual(d.handoff_priority, HumanHandoff.PRIORITY_URGENT)

    def test_open_handoff_is_upgraded_to_urgent(self):
        """Ya había una escalada normal en cola y aparece una urgencia: sube
        de prioridad y avisa, en vez de quedarse enterrada como 'normal'."""
        with mock.patch("apps.agent.alerts.notify_urgent_handoff") as alert:
            policy.escalate_to_human(
                self.conv, reason_code=HumanHandoff.REASON_EMERGENCY,
                priority=HumanHandoff.PRIORITY_URGENT)
        handoff = HumanHandoff.objects.get(conversation=self.conv)
        self.assertEqual(handoff.priority, HumanHandoff.PRIORITY_URGENT)
        self.assertEqual(handoff.reason_code, HumanHandoff.REASON_EMERGENCY)
        self.assertEqual(alert.call_count, 1)
        # Sigue habiendo UNA sola escalada abierta.
        self.assertEqual(
            HumanHandoff.objects.filter(conversation=self.conv).count(), 1)

    def test_ack_is_rearmed_after_a_new_escalation(self):
        policy.evaluate(self.conv, "¿hola?", agent_settings=self.settings)
        self.conv.refresh_from_db()
        policy.escalate_to_human(
            self.conv, reason_code=HumanHandoff.REASON_EXPLICIT)
        self.conv.refresh_from_db()
        d = policy.evaluate(self.conv, "¿sigue en pie?",
                            agent_settings=self.settings)
        self.assertEqual(d.kind, policy.REPLY)


# ---------------------------------------------------------------------------
# W1-6 · Identidad tolerante y re-match
# ---------------------------------------------------------------------------

class IdentityToleranceTests(AgentFixture):
    account_id = "900000105"

    def test_first_name_matches_full_registered_name(self):
        self.assertTrue(identity._name_matches("Ana", "Ana Torres"))
        self.assertTrue(identity._name_matches("Torres", "Ana Torres"))

    def test_particles_alone_do_not_match(self):
        self.assertFalse(identity._name_matches("de", "Ana de la Cruz"))

    def test_unrelated_name_still_fails(self):
        self.assertFalse(identity._name_matches("Pedro", "Ana Torres"))

    def test_owner_challenge_accepts_first_name(self):
        self.contact.verification_level = ContactIdentity.VERIFICATION_PHONE_MATCH
        self.contact.save(update_fields=['verification_level'])
        self.assertTrue(identity.try_verify_by_owner_name(self.contact, "Ana"))
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.verification_level,
                         ContactIdentity.VERIFICATION_CONFIRMED)


class ContactRematchTests(AgentFixture):
    account_id = "900000106"

    def test_contact_registered_later_gets_linked_on_next_message(self):
        stranger = ContactIdentity.objects.create(
            organization=self.org, channel_type='whatsapp',
            external_id="5215599990000", phone_normalized="5599990000")
        self.assertIsNone(stranger.owner_id)

        # La clínica lo da de alta en mostrador DESPUÉS de que escribió.
        nuevo = Owner.objects.create(
            organization=self.org, name="Luis Rangel", phone="5599990000")

        services.resolve_contact_identity(self.channel, "5215599990000")
        stranger.refresh_from_db()
        self.assertEqual(stranger.owner_id, nuevo.id)
        self.assertEqual(stranger.verification_level,
                         ContactIdentity.VERIFICATION_PHONE_MATCH)

    def test_existing_link_is_never_reassigned(self):
        services.resolve_contact_identity(self.channel, self.contact.external_id)
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.owner_id, self.owner.id)


# ---------------------------------------------------------------------------
# W1-7 · Media entrante
# ---------------------------------------------------------------------------

class IncomingMediaTests(AgentFixture):
    account_id = "900000107"

    def test_audio_gets_a_template_without_calling_the_model(self):
        ingest_inbound_message(
            self.channel, wamid="wamid.M1", wa_id="5215511110000",
            body="", payload_type="audio")
        process_pending_conversations(now=_later())
        outbound = Message.objects.get(conversation=self.conv,
                                       direction=Message.DIRECTION_OUT)
        self.assertEqual(outbound.body, tier0.T0_MEDIA_AUDIO)
        self.assertEqual(LLMCall.objects.filter(conversation=self.conv).count(), 0)

    def test_image_gets_the_generic_template(self):
        d = policy.evaluate(self.conv, "", burst=[""],
                            payload_types=["image"],
                            agent_settings=self.settings)
        self.assertEqual(d.kind, policy.REPLY)
        self.assertEqual(d.text, tier0.T0_MEDIA_OTHER)

    def test_text_alongside_media_is_processed_normally(self):
        d = policy.evaluate(self.conv, "¿a qué hora abren?",
                            burst=["", "¿a qué hora abren?"],
                            payload_types=["audio", "text"],
                            agent_settings=self.settings)
        self.assertEqual(d.kind, policy.RUN_PLANNER)


# ---------------------------------------------------------------------------
# W1-8 · Errores del dominio traducidos con honestidad
# ---------------------------------------------------------------------------

class DomainErrorMappingTests(TestCase):
    def test_overlap_is_slot_taken(self):
        code, _ = tools.map_domain_400({
            'code': 'validation_error',
            'errors': {'error': [
                'Ya existe una cita para este veterinario en ese horario']}})
        self.assertEqual(code, 'slot_taken')

    def test_past_date_is_reported_as_past(self):
        code, _ = tools.map_domain_400({
            'code': 'validation_error',
            'errors': {'date': ['No se pueden agendar citas en el pasado.']}})
        self.assertEqual(code, 'past_date')

    def test_other_validation_errors_are_not_disguised_as_slot_taken(self):
        code, detail = tools.map_domain_400({
            'code': 'validation_error',
            'errors': {'reason': ['Este campo no puede estar en blanco.']}})
        self.assertEqual(code, 'invalid_data')
        self.assertIn('blanco', detail)


# ---------------------------------------------------------------------------
# W1-9 · Saludo institucional con el agente encendido
# ---------------------------------------------------------------------------

class GreetingTests(AgentFixture):
    account_id = "900000108"

    def test_bare_greeting_uses_the_template_without_the_model(self):
        ingest_inbound_message(
            self.channel, wamid="wamid.G1", wa_id="5215511110000", body="hola")
        process_pending_conversations(now=_later())
        outbound = Message.objects.get(conversation=self.conv,
                                       direction=Message.DIRECTION_OUT)
        # `startswith`: fuera del horario de la clínica el saludo lleva además
        # el aviso de fuera de horario (INT-03), y el horario por defecto lo
        # siembra el alta de la organización.
        self.assertTrue(outbound.body.startswith(
            tier0.T0_GREET.format(clinic=self.org.name)), outbound.body)
        self.assertEqual(LLMCall.objects.filter(conversation=self.conv).count(), 0)

    def test_greeting_with_intent_goes_to_the_planner(self):
        d = policy.evaluate(self.conv, "hola, quiero una cita",
                            agent_settings=self.settings)
        self.assertEqual(d.kind, policy.RUN_PLANNER)

    def test_greeting_is_not_repeated_later_in_the_conversation(self):
        Message.objects.create(
            organization=self.org, channel_account=self.channel,
            conversation=self.conv, direction=Message.DIRECTION_OUT,
            author_type=Message.AUTHOR_AGENT, body="ya te saludé",
            status=Message.STATUS_SENT)
        d = policy.evaluate(self.conv, "hola", agent_settings=self.settings)
        self.assertEqual(d.kind, policy.RUN_PLANNER)


class AfterHoursNoticeTests(AgentFixture):
    account_id = "900000109"

    def test_notice_is_prepended_once_when_closed(self):
        close_all_days(self.org)   # cerrada toda la semana
        first, _, _ = run_turn(
            self, self.conv, self.agent_user, "¿a qué hora abren?",
            scripted_llm=[LLMResult(kind="text", text="Abrimos a las 9 🙂")],
            assert_clean=False)
        self.assertIn("fuera de horario", first[-1])

        second, _, _ = run_turn(
            self, self.conv, self.agent_user, "¿y los sábados?",
            scripted_llm=[LLMResult(kind="text", text="También 🙂")],
            assert_clean=False)
        self.assertNotIn("fuera de horario", second[-1])

    def test_notice_is_not_prepended_over_a_complaint(self):
        """É-F4 Fase 2 §2.3 — conv 13: el aviso cayó en medio de una queja por
        pérdida de contexto y CAUSÓ el mensaje siguiente ("no te pedí ningún
        horario"). Se pospone SIN consumirse: el turno normal siguiente sí lo
        lleva (un aviso correcto en mal momento sigue siendo ruido, pero el
        cliente merece enterarse)."""
        close_all_days(self.org)
        first, _, _ = run_turn(
            self, self.conv, self.agent_user, "¿se te borró el contexto?",
            scripted_llm=[LLMResult(kind="text", text="Aquí sigo 🙂")],
            assert_clean=False)
        self.assertNotIn("fuera de horario", first[-1])

        second, _, _ = run_turn(
            self, self.conv, self.agent_user, "¿a qué hora abren?",
            scripted_llm=[LLMResult(kind="text", text="Abrimos a las 9 🙂")],
            assert_clean=False)
        self.assertIn("fuera de horario", second[-1])


# ---------------------------------------------------------------------------
# W1-10 · Opt-out no destructivo
# ---------------------------------------------------------------------------

class OptOutTests(AgentFixture):
    account_id = "900000110"

    def test_optout_does_not_silence_future_messages(self):
        policy.evaluate(self.conv, "ya no me escriban",
                        agent_settings=self.settings)
        self.contact.refresh_from_db()
        self.assertTrue(self.contact.proactive_opt_out)
        self.assertFalse(self.contact.is_blocked)

        # Escribe de nuevo: se le atiende con normalidad (spec INT-04).
        message = ingest_inbound_message(
            self.channel, wamid="wamid.O1", wa_id="5215511110000",
            body="mejor sí quiero cita")
        self.assertEqual(message.status, Message.STATUS_PENDING)
