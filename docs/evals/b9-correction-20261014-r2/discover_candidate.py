"""Resolve the frozen CI corpus without running tests or setting up a DB."""
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest

EVIDENCE = Path(__file__).resolve().parent
assembly = json.loads((EVIDENCE / 'assembly.json').read_text())
assert assembly['phase'] in ('PREPARING', 'ASSEMBLED_NOT_EXECUTED')
assert json.loads((EVIDENCE / 'candidate-sources.json').read_text())['mismatches'] == []
TREE = Path(assembly['tree'])
os.chdir(TREE / 'backend')
sys.path.insert(0, str(TREE / 'backend'))
os.environ.update(DJANGO_SETTINGS_MODULE='config.settings', SECRET_KEY='b9i-disposable-test-only',
    ENVIRONMENT='dev', DEBUG='False', DATABASE_URL='postgresql://b9e@127.0.0.1:35482/test_b9i_control',
    DISABLE_SENTRY='True', SENTRY_DSN='', REDIS_URL='', DISCORD_WEBHOOK_URL='',
    HEALTHCHECK_AGENT_WORKER_URL='', HEALTHCHECK_AGENT_SENDER_URL='',
    AGENT_LLM_API_KEY='', AGENT_LLM_BASE_URL='', WHATSAPP_ACCESS_TOKEN='',
    WHATSAPP_APP_SECRET='', WHATSAPP_VERIFY_TOKEN='')
import django
django.setup()
from django.test.runner import DiscoverRunner
from django.conf import settings


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


def save(name, value):
    (EVIDENCE / name).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + '\n', encoding='utf-8')


scope = json.loads((EVIDENCE / 'scope-manifest.json').read_text())
selections = {'directed': scope['directed_test_ids'], 'full': []}
critical = {
    'b0': ['apps.agent.tests.test_b0_containment'],
    'b3': ['apps.agent.tests.test_b3_durable', 'apps.agent.tests.test_b3_processes'],
    'b4': ['apps.agent.tests.test_b4_sender', 'apps.agent.tests.test_b4_processes',
           'apps.agent.tests.test_b4_command', 'apps.channels.tests.test_b4_transport',
           'apps.channels.tests.test_b4_webhook', 'apps.channels.tests.test_b4_migration'],
    'b5': ['apps.agent.tests.test_b5_corpus', 'apps.agent.tests.test_b5_safety',
           'apps.agent.tests.test_b5_processes', 'apps.agent.tests.test_b5_migration'],
}
selections.update(critical)
resolved = {}
errors = {}
for label, labels in selections.items():
    runner = DiscoverRunner(verbosity=0, parallel=1)
    tests = list(flatten(runner.build_suite(labels)))
    ids = sorted(t.id() for t in tests)
    resolved[label] = ids
    errors[label] = runner.test_loader.errors[:]
    save(label + '-selected.json', ids)
    if label == 'full':
        save('discovery-skip-annotations.json', [{'id': t.id(), 'reason':
            getattr(t, '__unittest_skip_why__', '') or getattr(type(t), '__unittest_skip_why__', '')}
            for t in tests if getattr(t, '__unittest_skip__', False) or
            getattr(type(t), '__unittest_skip__', False) or
            getattr(getattr(t, t._testMethodName), '__unittest_skip__', False)])
summary = {'candidate_sha': assembly['candidate_sha'], 'tests_executed': False,
    'counts': {k: len(v) for k, v in resolved.items()}, 'loader_errors': errors,
    'missing_directed': sorted(set(scope['directed_test_ids']) - set(resolved['directed'])),
    'unexpected_directed': sorted(set(resolved['directed']) - set(scope['directed_test_ids'])),
    'duplicates': {k: len(v) - len(set(v)) for k, v in resolved.items()},
    'directed_full_overlap': len(set(resolved['directed']) & set(resolved['full'])),
    'critical_full_overlap': {k: len(set(resolved[k]) & set(resolved['full'])) for k in critical},
    'full_discovered_count_is_not_historical_total': True,
    'ci_sha256': hashlib.sha256((TREE / '.github/workflows/ci.yml').read_bytes()).hexdigest()}
save('discovery.json', summary)
effective = {k: getattr(settings, k) for k in dir(settings) if k.startswith('AGENT_') and 'KEY' not in k}
effective.update(ENVIRONMENT=settings.ENVIRONMENT, DEBUG=settings.DEBUG, DATABASES=settings.DATABASES,
                 CACHES=settings.CACHES, ALLOWED_HOSTS=settings.ALLOWED_HOSTS,
                 DISABLE_SENTRY=True, REDIS_URL='', DISCORD_WEBHOOK_URL='',
                 PASSWORD_HASHERS=settings.PASSWORD_HASHERS)
save('effective-configuration.json', effective)
print(json.dumps(summary, ensure_ascii=False))
if any(errors.values()) or summary['missing_directed'] or summary['unexpected_directed'] or any(summary['duplicates'].values()):
    raise SystemExit(1)
