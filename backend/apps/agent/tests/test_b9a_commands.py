"""Command boundary tests; application scripts run separately on PostgreSQL."""
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase


class B9ACommandTests(SimpleTestCase):
    def test_explicit_database_and_artifact_required(self):
        for command in ('agent_eval', 'agent_eval_conversations'):
            with self.subTest(command=command), self.assertRaises(CommandError):
                call_command(command, application_e2e=True, stdout=io.StringIO())

    def test_production_name_rejected_before_launch(self):
        with patch('apps.agent.management.e2e_evaluation.subprocess.run') as launch:
            with self.assertRaises(CommandError):
                call_command('agent_eval', application_e2e=True, e2e_database='production',
                    e2e_output=Path('unused'), stdout=io.StringIO())
            launch.assert_not_called()

    def test_commands_select_application_scripts_and_reject_incomplete_receipt(self):
        for command in ('agent_eval', 'agent_eval_conversations'):
            for skip in (0, 1):
                with self.subTest(command=command, skip=skip), TemporaryDirectory() as tmp:
                    prefix = Path(tmp) / 'result'
                    def launch(args, **kwargs):
                        selected = json.loads(prefix.with_suffix('.command-selection.json').read_text())
                        self.assertTrue(all('test_b9a_e2e' in label for label in selected))
                        self.assertEqual(kwargs['env']['DISABLE_SENTRY'], 'True')
                        prefix.with_suffix('.results.json').write_text(json.dumps({
                            'exit_code': 0, 'tests': 3, 'skips': skip, 'errors': 0, 'failures': 0, 'xfail': 0}))
                        return SimpleNamespace(returncode=0)
                    with patch.dict(os.environ, DATABASE_URL='postgresql://unused@127.0.0.1/test_only'), patch(
                            'apps.agent.management.e2e_evaluation.subprocess.run', side_effect=launch):
                        output = io.StringIO()
                        kwargs = dict(application_e2e=True, e2e_database='test_b8b_b9a_command',
                            e2e_output=prefix, stdout=output)
                        if skip:
                            with self.assertRaises(CommandError): call_command(command, **kwargs)
                        else:
                            call_command(command, **kwargs)
                            report = json.loads(output.getvalue())
                            self.assertEqual(report['scope'], 'application_e2e')
                            self.assertEqual(report['beta_acceptance'], 'PENDING')

    def test_prior_evidence_rejected_before_launch(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, DATABASE_URL='postgresql://unused@127.0.0.1/test_only'):
            prefix = Path(tmp) / 'old'
            prefix.with_suffix('.results.json').write_text(json.dumps({'exit_code': 0}))
            with patch('apps.agent.management.e2e_evaluation.subprocess.run') as launch:
                with self.assertRaises(CommandError):
                    call_command('agent_eval', application_e2e=True, e2e_database='test_b8b_b9a_command',
                        e2e_output=prefix, stdout=io.StringIO())
                launch.assert_not_called()

    def test_interrupted_child_cannot_accept_a_receipt(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, DATABASE_URL='postgresql://unused@127.0.0.1/test_only'):
            prefix = Path(tmp) / 'interrupted'
            def launch(*args, **kwargs):
                prefix.with_suffix('.results.json').write_text(json.dumps({'exit_code': 0}))
                return SimpleNamespace(returncode=1)
            with patch('apps.agent.management.e2e_evaluation.subprocess.run', side_effect=launch):
                with self.assertRaisesMessage(CommandError, 'failed or interrupted'):
                    call_command('agent_eval', application_e2e=True, e2e_database='test_b8b_b9a_command',
                        e2e_output=prefix, stdout=io.StringIO())

    def test_successful_process_without_receipt_is_not_acceptance(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, DATABASE_URL='postgresql://unused@127.0.0.1/test_only'):
            with patch('apps.agent.management.e2e_evaluation.subprocess.run', return_value=SimpleNamespace(returncode=0)):
                with self.assertRaisesMessage(CommandError, 'failed or interrupted'):
                    call_command('agent_eval', application_e2e=True, e2e_database='test_b8b_b9a_command',
                        e2e_output=Path(tmp) / 'missing', stdout=io.StringIO())
