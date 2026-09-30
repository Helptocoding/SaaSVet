"""Read-only E4 evidence collector for local test DBs; no conversation data."""
import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from .b9e_profile import setup, percentile


def distribution(values):
    values = list(values)
    return dict(n=len(values), **{f'p{int(q*100)}': percentile(values, q)
        for q in (.5, .75, .9, .95, .99)}, max=max(values, default=None))


def candidate_query():
    from django.db.models import Q, Exists, OuterRef
    from django.db.models.functions import Now
    from apps.agent.models import TurnWork, Conversation
    from apps.channels.models import Message
    from apps.agent import durable
    due = (Q(turn_works__status=TurnWork.PROCESSING, turn_works__lease_expires_at__lte=Now()) |
           Q(turn_works__status=TurnWork.PENDING, turn_works__next_attempt_at__lte=Now()) |
           Q(turn_works__status=TurnWork.PENDING, turn_works__next_attempt_at__isnull=True))
    incoming = Message.objects.filter(direction='in', status='pending', turn_work__isnull=True).filter(
        Q(available_at__isnull=True) | Q(available_at__lte=Now())).values('conversation_id')
    return (Conversation.objects.filter(due | Q(pk__in=incoming))
        .alias(org_busy=Exists(durable.active_org_work(OuterRef('organization_id'))))
        .filter(org_busy=False).order_by('last_activity_at', 'pk')
        .values_list('pk', flat=True).distinct()[:1])


def collect(receipt_path, output, current_selector=False):
    setup()
    from django.db import connection
    from django.db.models import F, Count
    from apps.agent.models import TurnWork, LLMCall
    from apps.channels.models import Message
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    start, end = map(datetime.fromisoformat, receipt['window_utc'])
    orgs = receipt['fixture_organization_ids']
    healthy = set(orgs[:2])
    rows = list(Message.objects.filter(direction='in', organization_id__in=orgs,
        created_at__gte=start, created_at__lt=end).values('id', 'organization_id',
        'conversation_id', 'turn_work_id', 'created_at', 'available_at', 'status', 'semantic_type'))
    work_rows = list(TurnWork.objects.filter(organization_id__in=orgs).values('id',
        'organization_id', 'conversation_id', 'claimed_at', 'completed_at', 'status',
        'llm_calls_admitted', 'llm_output_tokens_reserved', 'outcome_code'))
    works = {w['id']: w for w in work_rows}
    journals = []
    for role in ('planner-1', 'planner-2', 'sender'):
        path = receipt_path.with_name(receipt_path.stem + '-' + role + '.timing.json')
        if path.exists():
            journals.extend(dict(e, role=role) for e in json.loads(path.read_text())['events'])
    polls = sorted((e for e in journals if e['event'] == 'poll'), key=lambda e: e['time'])
    commits = {e['work']: e for e in journals if e['event'] == 'claim_commit'}
    breakdown = defaultdict(list)
    samples = []
    for row in rows:
        w = works.get(row['turn_work_id'])
        if not w or not w['claimed_at']:
            continue
        t0 = row['created_at'].timestamp()
        # Safety uses an immediate B5 transaction, not ordinary eligibility/poll.
        ordinary = row['semantic_type'] != 'safety_signal'
        t1 = row['available_at'].timestamp() if row['available_at'] else t0
        sample = dict(id=row['id'], organization=orgs.index(row['organization_id']),
            work=w['id'], ordinary=ordinary, T0=t0, T1=t1,
            claimed_at=w['claimed_at'].timestamp(),
            persisted_to_claim=(w['claimed_at']-row['created_at']).total_seconds())
        if row['organization_id'] in healthy:
            breakdown['persisted_to_claim'].append(sample['persisted_to_claim'])
            breakdown['ordinary_claim' if ordinary else 'safety_claim'].append(sample['persisted_to_claim'])
            if ordinary:
                breakdown['eligible_delay'].append(t1-t0)
        c = commits.get(w['id'])
        if c:
            first_seen = min((e['time'] for e in polls if row['id'] in e['healthy_eligible']), default=None)
            sample['first_eligible_observation'] = first_seen
            if row['organization_id'] in healthy and ordinary and first_seen is not None:
                breakdown['first_observation_to_claim'].append(w['claimed_at'].timestamp()-first_seen)
                sample['eligibility_extended_after_observation'] = first_seen < t1
            selected = [e for e in journals if e['event'] == 'candidate_selected'
                and e['conversation'] == row['conversation_id'] and e['role'] == c['role']
                and e['time'] <= c['time']]
            t3 = max((e['time'] for e in selected), default=None)
            observed = [e for e in polls if row['id'] in e['healthy_eligible']
                and e['time'] >= t1 and (t3 is None or e['time'] <= t3)]
            t2 = min((e['time'] for e in observed), default=None)
            locks = [e for e in journals if e['event'] == 'claim_sql' and
                e['conversation'] == row['conversation_id'] and e['role'] == c['role']
                and t3 <= e['time'] <= c['time']]
            t4 = min((e['start'] for e in locks if e['table'] == 'organizations_organization'), default=None)
            t5 = max((e['time'] for e in locks), default=None)
            sample.update(T2=t2, T3=t3, T4=t4, T5=t5, T6=c['time'])
            if row['organization_id'] in healthy and ordinary:
                for key, a, b in [('eligible_to_poll', t1, t2), ('poll_to_candidate', t2, t3),
                    ('candidate_to_capacity', t3, t4), ('capacity_to_locks', t4, t5),
                    ('locks_to_commit', t5, c['time']), ('candidate_to_commit', t3, c['time']),
                    ('persisted_to_commit', t0, c['time'])]:
                    if a is not None and b is not None:
                        breakdown[key].append(b-a)
        samples.append(sample)
    calls = list(LLMCall.objects.filter(turn_work__organization_id__in=orgs)
        .values('turn_work_id', 'admitted_at', 'recorded_at', 'purpose'))
    by_work = defaultdict(list)
    for call in calls:
        by_work[call['turn_work_id']].append(call)
    service = defaultdict(list)
    for w in work_rows:
        if not w['completed_at'] or not w['claimed_at'] or w['id'] not in by_work:
            continue
        service['claim_to_completion'].append((w['completed_at']-w['claimed_at']).total_seconds())
        cw = sorted(by_work[w['id']], key=lambda c: c['admitted_at'])
        service['calls_per_work'].append(len(cw))
        service['claim_to_first_admission'].append((cw[0]['admitted_at']-w['claimed_at']).total_seconds())
        committed = commits.get(w['id'])
        if committed and cw[0]['admitted_at'].timestamp() >= committed['time']:
            service['commit_return_to_first_admission'].append(cw[0]['admitted_at'].timestamp()-committed['time'])
            service['commit_return_to_completion'].append(w['completed_at'].timestamp()-committed['time'])
        ev = [e for e in journals if e.get('work') == w['id']]
        dispatched = sorted((e['time'] for e in ev if e['event'] == 'llm_dispatch'))
        responded = sorted((e['time'] for e in ev if e['event'] == 'llm_response'))
        toolend = next((e['time'] for e in ev if e['event'] == 'tool_end'), None)
        if len(dispatched) == len(responded) == 2 and len(cw) == 2 and toolend:
            service['first_dispatch_to_response'].append(responded[0]-dispatched[0])
            service['first_response_to_tool_completed'].append(toolend-responded[0])
            service['tool_to_second_admission'].append(cw[1]['admitted_at'].timestamp()-toolend)
            service['second_dispatch_to_response'].append(responded[1]-dispatched[1])
            service['second_response_to_completion'].append(w['completed_at'].timestamp()-responded[1])
    sql = defaultdict(list)
    for e in journals:
        if e['event'] == 'claim_sql':
            sql[e['table']].append(e['duration'])
        elif e['event'] == 'candidate_query':
            sql['candidate_query'].append(e['duration'])
    gaps = []
    for role in ('planner-1', 'planner-2'):
        rp = [e for e in polls if e['role'] == role]
        gaps.extend(b['start']-a['start'] for a, b in zip(rp, rp[1:]))
    selector = receipt.get('e4_overrides', {}).get('E4_SELECTOR')
    if current_selector:
        from apps.agent.worker import _pending_conversation_candidates
        q = _pending_conversation_candidates()
    elif selector in ('fair', 'efficient'):
        from .e4_selector import candidates
        q = candidates(fair=selector == 'fair')
    else:
        q = candidate_query()
    with connection.cursor() as cursor:
        cursor.execute('SELECT version(), current_setting(%s), current_setting(%s)', ['fsync', 'synchronous_commit'])
        environment = cursor.fetchone()
        cursor.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename IN ('agent_conversation','agent_turnwork','channels_message')")
        indexes = cursor.fetchall()
        query_sql, query_params = q.query.sql_with_params()
        cursor.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + query_sql, query_params)
        plan = cursor.fetchone()[0]
    critical = dict(cross_tenant=Message.objects.filter(organization_id__in=orgs).exclude(
        organization_id=F('conversation__organization_id')).count(),
        cross_tenant_work=TurnWork.objects.filter(organization_id__in=orgs).exclude(
            organization_id=F('conversation__organization_id')).count(),
        cross_tenant_call=LLMCall.objects.filter(turn_work__organization_id__in=orgs).exclude(
            organization_id=F('turn_work__organization_id')).count(),
        budget_violations=sum(w['llm_calls_admitted'] > 30 or w['llm_output_tokens_reserved'] > 18000 for w in work_rows),
        failed=sum(w['status'] == 'FAILED' for w in work_rows),
        max_active_observed=receipt['max_active_per_org_observed'],
        unclaimed_healthy=sum(r['organization_id'] in healthy and r['turn_work_id'] is None for r in rows))
    result = dict(schema='e4-collection-v2', classification='DIAGNOSTIC_ONLY', receipt=receipt_path.name,
        environment=environment, distributions={k: distribution(v) for k, v in breakdown.items()},
        service={k: distribution(v) for k, v in service.items()}, critical=critical,
        polling=dict(start_to_start=distribution(gaps), polls=len(polls),
            empty=sum(e['event'] == 'poll_end' and e['processed'] == 0 for e in journals),
            nonempty=sum(e['event'] == 'poll_end' and e['processed'] > 0 for e in journals),
            misses=sum(e['event'] == 'claim_miss' for e in journals),
            observer_cost=distribution(e['observer_seconds'] for e in polls)),
        sql_execution_seconds={k: distribution(v) for k, v in sql.items()},
        query=str(q.query), query_plan=plan, current_runtime_selector=current_selector,
        sql_duration_is_lock_wait_upper_bound=True,
        lock_wait_samples=[dict(second=s['second'], waits=s['postgresql_wait_samples'])
            for s in receipt['queue_samples'] if 'postgresql_wait_samples' in s],
        indexes=indexes, timing_samples=samples,
        queue_timeline=[dict(time=e['time'], queue=e['queue']) for e in polls])
    output.write_text(json.dumps(result, indent=2, default=str)+'\n', encoding='utf-8')
    print(json.dumps(dict(output=str(output), distributions=result['distributions'],
        critical=critical), default=str))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--current-selector', action='store_true')
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError('Refusing to overwrite E4 evidence')
    collect(args.receipt, args.output, args.current_selector)


if __name__ == '__main__':
    main()
