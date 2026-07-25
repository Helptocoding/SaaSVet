"""
test_w3_quality.py — É-F3 W3: medición de calidad conversacional.

Las métricas de negocio responden "¿agendó?". Estas responden la pregunta que
decide el piloto: "¿se siente como una buena recepcionista?". Sin ellas, el
piloto solo puede opinar.
"""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.agent import goals
from apps.agent.metrics import compute_quality_metrics
from apps.agent.models import ConversationGoal, HumanHandoff
from apps.agent.tests.test_w0_hardening import AgentFixture
from apps.channels.models import Message


class QualityFixture(AgentFixture):
    account_id = "900000301"

    def setUp(self):
        super().setUp()
        self.since = timezone.now() - timedelta(days=1)
        self.until = timezone.now() + timedelta(days=1)

    def _msg(self, direction, *, author, body="x", minutes_ago=0,
             payload_type="text", status=Message.STATUS_PROCESSED):
        message = Message.objects.create(
            organization=self.org, channel_account=self.channel,
            conversation=self.conv, direction=direction, author_type=author,
            body=body, payload_type=payload_type, status=status)
        if minutes_ago:
            Message.objects.filter(pk=message.pk).update(
                created_at=timezone.now() - timedelta(minutes=minutes_ago))
            message.refresh_from_db()
        return message

    def _metrics(self):
        return compute_quality_metrics(self.org, self.since, self.until)


class ResponseLatencyTests(QualityFixture):
    def test_latency_is_measured_from_the_last_inbound(self):
        inbound = self._msg(Message.DIRECTION_IN,
                            author=Message.AUTHOR_CLIENT)
        outbound = self._msg(Message.DIRECTION_OUT,
                             author=Message.AUTHOR_AGENT)
        Message.objects.filter(pk=outbound.pk).update(
            created_at=inbound.created_at + timedelta(seconds=6))

        latency = self._metrics()['latencia_respuesta_ms']
        self.assertEqual(latency['muestras'], 1)
        self.assertAlmostEqual(latency['p50'], 6000, delta=1500)

    def test_discarded_replies_do_not_count_as_answers(self):
        """Un saliente descartado (W1-4) nunca llegó al cliente."""
        self._msg(Message.DIRECTION_IN, author=Message.AUTHOR_CLIENT)
        self._msg(Message.DIRECTION_OUT, author=Message.AUTHOR_AGENT,
                  status=Message.STATUS_DISCARDED)
        metrics = self._metrics()
        self.assertEqual(metrics['latencia_respuesta_ms']['muestras'], 0)
        self.assertEqual(metrics['respuestas_descartadas'], 1)

    def test_no_traffic_no_crash(self):
        latency = self._metrics()['latencia_respuesta_ms']
        self.assertIsNone(latency['p50'])
        self.assertEqual(latency['muestras'], 0)


class MediaShareTests(QualityFixture):
    def test_audio_share_feeds_the_transcription_gate(self):
        for _ in range(3):
            self._msg(Message.DIRECTION_IN, author=Message.AUTHOR_CLIENT)
        self._msg(Message.DIRECTION_IN, author=Message.AUTHOR_CLIENT,
                  body="", payload_type="audio")
        metrics = self._metrics()
        self.assertEqual(metrics['pct_audio'], 0.25)   # > 15 % → UX-14
        self.assertEqual(metrics['entrantes_por_tipo']['audio'], 1)


class GoalQualityTests(QualityFixture):
    def test_turns_per_resolution_counts_only_completed_goals(self):
        for _ in range(4):
            self._msg(Message.DIRECTION_IN, author=Message.AUTHOR_CLIENT)
        goal = goals.open_goal(self.conv, goals.SCHEDULE)
        goals.close(goal, ConversationGoal.STATUS_COMPLETED, 'ok')

        turns = self._metrics()['turnos_por_resolucion']
        self.assertEqual(turns['muestras'], 1)
        self.assertEqual(turns['promedio'], 4)

    def test_abandoned_goals_do_not_pollute_the_average(self):
        for _ in range(9):
            self._msg(Message.DIRECTION_IN, author=Message.AUTHOR_CLIENT)
        goals.open_goal(self.conv, goals.SCHEDULE)   # queda abierto
        self.assertEqual(
            self._metrics()['turnos_por_resolucion']['muestras'], 0)

    def test_repeated_question_rate(self):
        goal = goals.open_goal(self.conv, goals.SCHEDULE)
        goals.mark_asked(goal, ['date'])
        goals.mark_asked(goal, ['date'])          # mismo dato, 2ª vez
        self.assertEqual(self._metrics()['tasa_repregunta'], 1.0)

    def test_single_ask_is_not_a_repetition(self):
        goal = goals.open_goal(self.conv, goals.SCHEDULE)
        goals.mark_asked(goal, ['date'])
        self.assertEqual(self._metrics()['tasa_repregunta'], 0.0)


class HandoffRateTests(QualityFixture):
    def test_handoff_rate_is_per_conversation(self):
        HumanHandoff.objects.create(
            organization=self.org, conversation=self.conv,
            reason_code=HumanHandoff.REASON_EXPLICIT)
        HumanHandoff.objects.create(
            organization=self.org, conversation=self.conv,
            reason_code=HumanHandoff.REASON_EMERGENCY)
        # Dos escaladas en la MISMA conversación no son dos conversaciones.
        self.assertEqual(self._metrics()['tasa_handoff'], 1.0)


class QualityCommandTests(QualityFixture):
    def test_command_reports_and_samples(self):
        self._msg(Message.DIRECTION_IN, author=Message.AUTHOR_CLIENT)
        HumanHandoff.objects.create(
            organization=self.org, conversation=self.conv,
            reason_code=HumanHandoff.REASON_EXPLICIT)
        out = StringIO()
        call_command('agent_quality', '--days', '2', stdout=out)
        text = out.getvalue()
        self.assertIn(self.org.name, text)
        self.assertIn('tasa de handoff', text)
        self.assertIn(str(self.conv.public_id), text)   # muestra para leer

    def test_command_json_is_parseable(self):
        import json
        self._msg(Message.DIRECTION_IN, author=Message.AUTHOR_CLIENT)
        out = StringIO()
        call_command('agent_quality', '--days', '2', '--json', stdout=out)
        data = json.loads(out.getvalue())
        self.assertIn('organizaciones', data)
        self.assertEqual(data['organizaciones'][0]['organizacion'], self.org.name)

    def test_command_without_traffic_says_so(self):
        from apps.organizations.models import Organization
        vacia = Organization.objects.create(name="Sin tráfico", timezone="UTC")
        out = StringIO()
        call_command('agent_quality', '--days', '2',
                     '--org', str(vacia.public_id), stdout=out)
        self.assertIn('Sin conversaciones', out.getvalue())


class QualityIsolationTests(TestCase):
    def test_metrics_are_org_scoped(self):
        from apps.organizations.models import Organization
        other = Organization.objects.create(name="Ajena", timezone="UTC")
        metrics = compute_quality_metrics(
            other, timezone.now() - timedelta(days=1), timezone.now())
        self.assertEqual(metrics['latencia_respuesta_ms']['muestras'], 0)
        self.assertEqual(metrics['tasa_handoff'], 0.0)
