"""
test_logging_config.py — El logger del agente debe emitir en producción.

Sin una entrada propia, `agent.events` cae en `root` (nivel WARNING) y TODO el
INFO del subsistema se descarta: `AGENT_WORKER_STARTED`,
`AGENT_FIRST_REPLY_QUEUED`, `AGENT_CONVERSATION_OPENED`, `AGENT_GOAL_OPENED`…
El runbook manda buscar esos eventos en los logs del worker, y durante el
piloto son la única forma de seguir un turno end-to-end.

Se detectó en el deploy del 2026-07-26: worker arriba, `RestartCount=0`, y cero
líneas de log — indistinguible a simple vista de un worker colgado.
"""
import json
import logging

from django.test import SimpleTestCase


class AgentLoggerConfigTests(SimpleTestCase):
    def test_agent_events_emits_info(self):
        logger = logging.getLogger('agent.events')
        self.assertTrue(
            logger.isEnabledFor(logging.INFO),
            "agent.events descarta INFO: el runbook y el piloto se quedan "
            "ciegos (revisar LOGGING en config/settings.py)",
        )

    def test_agent_events_does_not_leak_to_root(self):
        """Handler propio: sin `propagate=False` los eventos saldrían dos veces
        (una en JSON y otra en texto plano)."""
        logger = logging.getLogger('agent.events')
        self.assertFalse(logger.propagate)
        self.assertTrue(logger.handlers, "sin handler propio")

    def test_events_are_structured_json_with_their_extras(self):
        """El agregador ingesta una línea JSON por evento; los `extra` del
        call site (organization_id, conversation_id…) deben viajar dentro."""
        from apps.core.logging import RBACStructuredFormatter
        record = logging.LogRecord(
            name='agent.events', level=logging.INFO, pathname=__file__,
            lineno=1, msg='AGENT_GOAL_OPENED', args=(), exc_info=None,
        )
        record.organization_id = 7
        record.conversation_id = 42
        record.goal = 'schedule_appointment'

        payload = json.loads(RBACStructuredFormatter().format(record))
        self.assertEqual(payload['event'], 'AGENT_GOAL_OPENED')
        self.assertEqual(payload['level'], 'INFO')
        self.assertEqual(payload['organization_id'], 7)
        self.assertEqual(payload['goal'], 'schedule_appointment')
