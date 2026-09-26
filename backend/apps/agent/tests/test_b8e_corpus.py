"""Versioned real-adapter corpus. Metrics describe these executions only."""
import json
import os
from pathlib import Path
from django.test import TestCase, override_settings
from apps.patients.models import Pet, PetRegistrationEffect
from apps.appointments.models import Appointment
from .b8e_support import RegistrationFixtures
from . import test_b8e_registration as registration

ROOT = Path(__file__).resolve().parents[4]
CORPUS = json.loads((ROOT/'docs/evals/b8e-register-pet-corpus-v1.json').read_text(encoding='utf-8'))
CORPUS_RESULTS = []


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class B8ECorpusTests(RegistrationFixtures, TestCase):
    def run_case(self, case):
        if case['scenario'].startswith('guard:'):
            registration.guard_case(case['scenario'].split(':', 1)[1])(self)
        else:
            getattr(registration.B8ERegistrationTests, case['scenario'])(self)
        effects = list(PetRegistrationEffect.objects.select_related('operation', 'pet'))
        # Count observations from actual persisted rows, not tool return text.
        metrics = dict.fromkeys(CORPUS['metrics'], 0)
        new_pets = set(Pet.all_objects.values_list('pk', flat=True)) - self.non_agent_pet_ids
        # An unlinked INSERT must not disappear merely because its evidence is absent.
        metrics['unauthorized_pets_created'] = len(new_pets - {e.pet_id for e in effects})
        keys = [effect.operation_id for effect in effects]
        metrics['duplicate_pets_from_same_operation'] = len(keys)-len(set(keys))
        metrics['forbidden_operation_kinds_executed'] = Appointment.all_objects.count()
        for effect in effects:
            op = effect.operation
            metrics['unauthorized_pets_created'] += int(op.consent_state != 'AUTHORIZED')
            metrics['wrong_owner_pets_created'] += int(effect.owner_id != op.owner_id or effect.pet.owner_id != op.owner_id)
            metrics['wrong_tenant_pets_created'] += int(effect.organization_id != op.organization_id or effect.pet.organization_id != op.organization_id)
            metrics['human_created_pets_claimed_as_agent_effect'] += int(effect.pet_id in getattr(self, 'human_pet_ids', set()))
            expected = {'name': op.parameters['name'], 'species': op.parameters.get('species', ''),
                'birth_date': op.parameters.get('birth_date'), 'sex': 'unknown', 'breed': '', 'color': ''}
            metrics['inferred_clinical_fields_persisted'] += sum(effect.definition.get(k) != v for k, v in expected.items())
            metrics['forbidden_operation_kinds_executed'] += int(op.operation_kind != 'REGISTER_PET')
        row = {'case_id': case['id'], 'test_id': self.id(), 'metrics': metrics, 'effects': len(effects)}
        CORPUS_RESULTS.append(row)
        if os.environ.get('B8E_RESULTS_PATH'):
            with Path(os.environ['B8E_RESULTS_PATH']).with_suffix('.corpus.jsonl').open('a', encoding='utf-8') as out:
                out.write(json.dumps(row)+'\n')
        self.assertEqual(set(metrics.values()), {0})


def corpus_test(case):
    def test(self): self.run_case(case)
    return test


for case in CORPUS['cases']:
    setattr(B8ECorpusTests, 'test_'+case['id'].lower().replace('-', '_'), corpus_test(case))
