"""Versioned technical corpus, deliberately separate from clinical validation."""
import json
from pathlib import Path
from django.test import SimpleTestCase

CORPUS = Path(__file__).resolve().parents[4] / 'docs/evals/b5-safety-v1.json'


class B5CorpusTests(SimpleTestCase):
    def test_safe_02_versioned_adversarial_corpus(self):
        from apps.agent.safety import assess_texts
        corpus = json.loads(CORPUS.read_text(encoding='utf-8'))
        self.assertEqual(corpus['review_status'], 'VETERINARY_REVIEW_REQUIRED')
        counts = dict(TP=0, FN=0, TN=0, FP=0)
        families = {}
        critical_detected = critical_total = 0
        for case in corpus['cases']:
            with self.subTest(case=case['id'], family=case['family']):
                result = assess_texts(case['texts'])
                positive = result.classification != 'NO_SIGNAL'
                expected = case['expected'] != 'NO_SIGNAL'
                key = ('TP' if positive else 'FN') if expected else ('FP' if positive else 'TN')
                counts[key] += 1
                family = families.setdefault(case['family'], dict(TP=0, FN=0, TN=0, FP=0))
                family[key] += 1
                if case['expected'] == 'URGENT':
                    critical_total += 1
                    critical_detected += int(positive)
                self.assertEqual(result.classification, case['expected'])
        print('B5_CORPUS ' + json.dumps({'counts': counts, 'families': families,
            'critical_detected': critical_detected, 'critical_total': critical_total,
            'critical_recall': critical_detected / critical_total,
            'review_status': corpus['review_status']}, sort_keys=True))
