"""DIAGNOSTIC_ONLY: original PROFILE v1 conditions, readiness decomposition.

Reuses the E4 test harness without modifying its selector or historical receipts.
Never changes production code, gates, rates, clocks or provider latencies.
"""
import json
from pathlib import Path
from unittest.mock import patch

from . import e4_profile


def distribution(values):
    return dict(count=len(values), p50_seconds=e4_profile.percentile(values, .5),
                p95_seconds=e4_profile.percentile(values, .95), max_seconds=max(values, default=None))


def observe(*args):
    receipt = e4_profile.observe(*args)
    from apps.channels.models import Message
    from apps.agent.models import TurnWork
    from django.db.models import Count, Sum
    from django.utils.dateparse import parse_datetime
    start, end = map(parse_datetime, receipt['window_utc'])
    orgs = args[3]
    rows = []
    for index, org in enumerate(orgs):
        messages = Message.objects.filter(direction='in', organization_id=org,
            created_at__gte=start, created_at__lt=end).exclude(
            semantic_type=Message.SEMANTIC_SAFETY_SIGNAL).select_related('turn_work')
        pe, ec, pc, missing, joined = [], [], [], 0, 0
        for message in messages:
            eligible = max(message.created_at, message.available_at or message.created_at)
            pe.append((eligible-message.created_at).total_seconds())
            joined += int(message.available_at is not None and message.available_at < message.created_at)
            if message.turn_work_id and message.turn_work.claimed_at:
                claim = message.turn_work.claimed_at
                ec.append((claim-eligible).total_seconds())
                pc.append((claim-message.created_at).total_seconds())
            else:
                missing += 1
        works = TurnWork.objects.filter(organization_id=org, context_at__gte=start, context_at__lt=end)
        work_count = works.count()
        calls = works.aggregate(calls=Sum('llm_calls_admitted'))['calls'] or 0
        dialogues = works.values('conversation_id').distinct().count()
        rows.append(dict(organization=index, healthy=index < 2,
            persisted_to_eligible=distribution(pe), eligible_to_claim=distribution(ec),
            persisted_to_claim=distribution(pc), missing_claim=missing,
            joined_ready_inbounds=joined, works=work_count, calls=calls,
            calls_per_work=calls/work_count if work_count else None,
            calls_per_dialogue=calls/dialogues if dialogues else None,
            calls_per_work_distribution=list(works.values('llm_calls_admitted').annotate(count=Count('pk'))),
            deferrals=works.filter(outcome_code='deferred_to_new_input').count()))
    receipt['monotonic_diagnostic'] = dict(classification='DIAGNOSTIC_ONLY', organizations=rows,
        eligibility='max(created_at, available_at); NULL => created_at',
        acceptance_run=False, profile_conditions='PROFILE-BETA-1 v1 unchanged')
    return receipt


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenario', required=True, choices=('base', 'blocked_llm'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--role')
    parser.add_argument('--stop', type=Path)
    args = parser.parse_args()
    # Reuse the identical workers with their existing test-only timing wrapper.
    if args.role:
        e4_profile.worker(args.role, args.scenario, args.stop)
    else:
        original_observe = e4_profile.observe
        # Avoid recursion while keeping the original receipt's gates/denominators.
        def extended(*a):
            with patch.object(e4_profile, 'observe', original_observe):
                return observe(*a)
        with patch.object(e4_profile, 'observe', extended):
            e4_profile.orchestrate(args.scenario, args.output)


if __name__ == '__main__':
    main()
