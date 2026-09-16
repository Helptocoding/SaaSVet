from io import StringIO
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase


class B4CommandTests(SimpleTestCase):
    def test_sender_mode_never_waits_for_planner(self):
        path = 'apps.agent.management.commands.run_agent_worker.'
        with patch(path + 'process_pending_conversations', side_effect=AssertionError('planner')) as planner, \
             patch(path + 'send_pending_outbound', return_value=1) as sender:
            call_command('run_agent_worker', mode='sender', once=True, stdout=StringIO())
        planner.assert_not_called()
        sender.assert_called_once_with(batch=20)

    def test_planner_mode_never_runs_sender(self):
        path = 'apps.agent.management.commands.run_agent_worker.'
        with patch(path + 'process_pending_conversations', return_value=1) as planner, \
             patch(path + 'send_pending_outbound', side_effect=AssertionError('sender')) as sender:
            call_command('run_agent_worker', mode='planner', once=True, stdout=StringIO())
        planner.assert_called_once_with(batch=10)
        sender.assert_not_called()

    def test_compatibility_mode_runs_both(self):
        path = 'apps.agent.management.commands.run_agent_worker.'
        with patch(path + 'process_pending_conversations', return_value=1) as planner, \
             patch(path + 'send_pending_outbound', return_value=1) as sender:
            call_command('run_agent_worker', once=True, stdout=StringIO())
        planner.assert_called_once()
        sender.assert_called_once()

    def test_invalid_bounds_fail_before_polling(self):
        for kwargs in ({'batch': 0}, {'batch': 51}, {'poll': 0}, {'poll': 61}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CommandError):
                call_command('run_agent_worker', once=True, **kwargs)
