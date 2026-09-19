"""Versioned multi-turn corpus with separate binding/invalidation safety metrics."""
import json
from pathlib import Path
from django.db import transaction
from django.test import TestCase
from apps.agent import matter_binding as binding, goals, tools
from apps.agent.models import ConversationGoal
from apps.patients.models import Pet
from . import test_b6_binding as fixtures


class B6CorpusTests(TestCase):
    inbound = fixtures.B6BindingTests.inbound
    context = fixtures.B6BindingTests.context
    turn = fixtures.B6BindingTests.turn
    derived = fixtures.B6BindingTests.derived

    def test_versioned_multi_turn_corpus(self):
        path = Path(__file__).resolve().parents[4] / 'docs/evals/b6-binding-v1.json'
        corpus = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(corpus['schema'], 1)
        metrics = {'bindings_correct': 0, 'binding_checks': 0,
                   'clarifications_correct': 0, 'clarification_checks': 0,
                   'invalidations_correct': 0, 'invalidation_checks': 0,
                   'stale_reuse_violations': 0, 'matter_mixing_violations': 0,
                   'conversations': len(corpus['cases']), 'turns': 0}
        for case in corpus['cases']:
            with self.subTest(case=case['id']), transaction.atomic():
                fixtures.B6BindingTests.setUp(self)
                for name in case.get('extra_pets', []):
                    Pet.objects.create(organization=self.org, owner=self.owner, name=name)
                old_stamp = None
                for step in case['steps']:
                    before = binding.current_goal(self.conv)
                    revision = before.binding_revision if before else None
                    reply = self.turn(step['text'])
                    metrics['turns'] += 1
                    actual = self.goal.bound_pet.name if self.goal and self.goal.bound_pet_id else None
                    metrics['binding_checks'] += 1
                    metrics['bindings_correct'] += actual == step['pet']
                    self.assertEqual(actual, step['pet'], (case['id'], step['text']))
                    if not step.get('abandoned'):
                        metrics['clarification_checks'] += 1
                        metrics['clarifications_correct'] += bool(reply) == step.get('clarify', False)
                        self.assertEqual(bool(reply), step.get('clarify', False), step['text'])
                    active = binding.values(self.goal) if self.goal else {}
                    for key in step.get('invalidated', []):
                        metrics['invalidation_checks'] += 1
                        metrics['invalidations_correct'] += key not in active
                        self.assertNotIn(key, active)
                    for key in step.get('keep', []):
                        self.assertIn(key, active)
                    for key in step.get('absent', []):
                        metrics['matter_mixing_violations'] += key in active
                        self.assertNotIn(key, active)
                    if step.get('kind'):
                        self.assertEqual(self.goal.name, step['kind'])
                    if step.get('no_goal') or step.get('abandoned'):
                        self.assertIsNone(self.goal)
                    if step.get('same_revision'):
                        self.assertEqual(self.goal.binding_revision, revision)
                    if old_stamp and self.goal and old_stamp != binding.snapshot(self.goal):
                        stale = tools.ToolOutcome(kind='READ', data=[], validated=True,
                                                  scope={'binding': old_stamp})
                        metrics['stale_reuse_violations'] += binding.outcome_current(self.conv, stale)
                        self.assertFalse(binding.outcome_current(self.conv, stale))
                    open_count = ConversationGoal.objects.filter(conversation=self.conv,
                        status__in=ConversationGoal.FOREGROUND_STATUSES).count()
                    metrics['matter_mixing_violations'] += open_count > 1
                    self.assertLessEqual(open_count, 1)
                    for key in step.get('derive', []):
                        self.derived(key)
                    old_stamp = binding.snapshot(self.goal) if self.goal else None
                transaction.set_rollback(True)
        print('B6_CORPUS_RESULT ' + json.dumps(metrics, sort_keys=True))
        self.assertEqual(metrics['stale_reuse_violations'], 0)
        self.assertEqual(metrics['matter_mixing_violations'], 0)
