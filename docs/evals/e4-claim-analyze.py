"""Derive all timelines from closed diagnostic events and durable PG rows."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path


def seconds(value):
    return datetime.fromisoformat(value).timestamp() if value else None


def distribution(values):
    values = sorted(values)
    if not values:
        return dict(count=0, p50=None, p95=None, maximum=None)
    return dict(count=len(values), p50=values[int((len(values)-1)*.5+.999999)],
                p95=values[int((len(values)-1)*.95+.999999)], maximum=values[-1])


def analyze(path):
    receipt = json.loads(path.read_text(encoding='utf-8'))
    diag = receipt['claim_diagnostic']
    orgs = receipt['fixture_organization_ids']
    conv_org = {r['id']: orgs.index(r['organization_id']) for r in diag['conversations']}
    works = {r['id']: r for r in diag['works']}
    cycles = []
    claims = {}
    selectors = []
    sqls = []
    for role in ('planner-1', 'planner-2'):
        journal = json.loads(path.with_name(path.stem+'-'+role+'.claim-timing.json').read_text())
        grouped = {}
        for event in journal['events']:
            if event.get('poll') is not None:
                grouped.setdefault(event['poll'], []).append(event)
            if event['event'] == 'selector_sql_returned':
                selectors.append(event['duration'])
            if event['event'] == 'lock_sql_returned':
                sqls.append(event)
        for number, events in grouped.items():
            begin = next(e['time'] for e in events if e['event'] == 'planner_start')
            end = next((e['time'] for e in events if e['event'] == 'planner_end'), None)
            if end is None:
                raise RuntimeError('Incomplete planner cycle')
            claimed = [e for e in events if e['event'] == 'claim_commit']
            cycle = dict(role=role, poll=number, start=begin, end=end, events=events,
                claims=[dict(work=e['work'], org=conv_org[e['conversation']], at=e['time']) for e in claimed],
                misses=sum(e['event']=='claim_miss' for e in events),
                candidates=[dict(at=e['time'], conversations=e['conversations'],
                    orgs=[conv_org[c] for c in e['conversations']]) for e in events if e['event']=='candidates_observed'])
            cycles.append(cycle)
            for claim in claimed:
                claims[claim['work']] = (cycle, claim)
    cycles.sort(key=lambda c:c['start'])
    timelines = []
    for msg in diag['healthy_messages']:
        persisted = seconds(msg['created_at'])
        eligible = max(persisted, seconds(msg['available_at']) or persisted)
        claim_time = seconds(msg['turn_work__claimed_at'])
        row = dict(message=msg['id'], org=orgs.index(msg['organization_id']), work=msg['turn_work_id'],
            semantic_type=msg['semantic_type'], T0=persisted, T1=eligible, T7=claim_time)
        if msg['turn_work_id'] not in claims:
            row.update(planner=None, route='receipt_safety' if msg['semantic_type']=='safety_signal' else 'missing',
                       T2=None, T3=None, T4=None, T5=None, T6=None, T8=None)
            timelines.append(row)
            continue
        cycle, committed = claims[msg['turn_work_id']]
        events = cycle['events']
        selected = max((e for e in events if e['event']=='candidate_selected'
            and e['conversation']==msg['conversation_id'] and e['time']<=committed['time']), key=lambda e:e['time'])
        observed = [e for c in cycles for e in c['events'] if e['event']=='candidates_observed'
                    and msg['conversation_id'] in e['conversations'] and eligible<=e['time']<=selected['time']]
        first_observed = min((e['time'] for e in observed), default=None)
        joined_after_observation = first_observed is None
        if first_observed is None:
            first_observed = max((e['time'] for e in events if e['event']=='candidates_observed'
                and msg['conversation_id'] in e['conversations'] and e['time']<=selected['time']), default=None)
        transaction = next(e['time'] for e in events if e['event']=='claim_transaction_started'
                           and selected['time']<=e['time']<=committed['time'])
        org_lock = next(e['time'] for e in events if e['event']=='lock_requested'
                        and e['table']=='organizations_organization' and selected['time']<=e['time']<=committed['time'])
        starts = [c for c in cycles if eligible<=c['start']<=selected['time']]
        first_start = min((c['start'] for c in starts), default=cycle['start'])
        in_flight = [c for c in cycles if c['start']<eligible and any(
            e['event']=='candidates_observed' and msg['conversation_id'] in e['conversations']
            and eligible<=e['time']<=selected['time'] for e in c['events'])]
        segments = []
        boundaries = sorted(set([eligible, claim_time]+[t for c in cycles for t in
            [c['start'], c['end']]+[r['at'] for r in c['claims']] if eligible<t<claim_time]))
        categories = Counter()
        for lo, hi in zip(boundaries, boundaries[1:]):
            midpoint = (lo+hi)/2
            phase = []
            for role in ('planner-1', 'planner-2'):
                active = next((c for c in cycles if c['role']==role and c['start']<=midpoint<c['end']), None)
                phase.append('service' if active and any(r['at']<=midpoint for r in active['claims'])
                             else 'selection' if active else 'external_pause')
            category = '+'.join(sorted(phase))
            categories[category] += hi-lo
            segments.append(dict(start=lo, end=hi, phases=phase))
        states = []
        for role in ('planner-1', 'planner-2'):
            previous = max((c for c in cycles if c['role']==role and c['start']<=eligible),
                           key=lambda c:c['start'], default=None)
            following = min((c for c in cycles if c['role']==role and c['start']>eligible),
                            key=lambda c:c['start'], default=None)
            in_cycle = previous is not None and previous['end']>eligible
            busy = in_cycle and any(r['at']<=eligible for r in previous['claims'])
            states.append(dict(role=role, state='busy' if busy else 'selecting' if in_cycle else 'external_pause',
                current_orgs=[r['org'] for r in previous['claims']] if busy else [],
                free_at=previous['end'] if busy else eligible,
                next_start=following['start'] if following else None,
                opportunity_delay=following['start']-eligible if following else None))
        opportunities = [dict(role=c['role'], poll=c['poll'], start=c['start'], end=c['end'],
            claims=c['claims'], candidates=c['candidates'], misses=c['misses']) for c in starts]
        row.update(route='planner', planner=cycle['role'], poll=cycle['poll'], T2=first_start,
            winning_planner_start=cycle['start'], T3=first_observed, T4=selected['time'], T5=org_lock,
            T6=transaction, T8=committed['time'], planner_states_at_T1=states, opportunities=opportunities,
            joined_after_candidate_observation=joined_after_observation,
            opportunity_already_in_flight=bool(in_flight),
            eligible_to_next_planner_start=max(0,first_start-eligible),
            eligible_to_next_opportunity=0 if in_flight else max(0,first_start-eligible),
            wait_state_seconds=dict(categories), wait_state_segments=segments,
            eligible_to_candidate=first_observed-eligible if first_observed is not None else None,
            candidate_to_claim=claim_time-first_observed if first_observed is not None else None,
            selected_to_claim=claim_time-selected['time'],
            persisted_to_eligible=eligible-persisted, eligible_to_claim=claim_time-eligible,
            persisted_to_claim=claim_time-persisted,
            both_busy=all(s['state']=='busy' for s in states),
            min_busy_remaining=max(0, min(s['free_at'] for s in states)-eligible))
        timelines.append(row)
    ordinary = [r for r in timelines if r['route']=='planner']
    planner_rows = []
    for role in ('planner-1', 'planner-2'):
        rows = sorted((c for c in cycles if c['role']==role), key=lambda c:c['start'])
        planner_rows.append(dict(role=role, cycles=len(rows), claims_by_org=dict(Counter(
            r['org'] for c in rows for r in c['claims'])), misses=sum(c['misses'] for c in rows),
            busy_seconds=sum(c['end']-c['start'] for c in rows),
            idle_seconds=sum(b['start']-a['end'] for a,b in zip(rows, rows[1:])),
            service=distribution([c['end']-c['start'] for c in rows if c['claims']]),
            start_to_start=distribution([b['start']-a['start'] for a,b in zip(rows, rows[1:])]),
            completion_to_next_start=distribution([b['start']-a['end'] for a,b in zip(rows, rows[1:])]),
            eligible_to_next_opportunity=distribution([s['opportunity_delay'] for r in ordinary
                for s in r['planner_states_at_T1'] if s['role']==role and s['opportunity_delay'] is not None])))
    duplicate_misses = []
    for c in cycles:
        for event in c['events']:
            if event['event'] != 'claim_miss':
                continue
            other = [x for x in cycles if x['role']!=c['role'] and any(
                e['event']=='candidate_selected' and e['conversation']==event['conversation']
                and abs(e['time']-event['time'])<.5 for e in x['events'])]
            duplicate_misses.append(dict(role=c['role'], poll=c['poll'], conversation=event['conversation'],
                org=conv_org[event['conversation']], at=event['time'], competing_cycle=bool(other),
                subsequent_claims=[r for r in c['claims'] if r['at']>event['time']]))
    organization_rows = []
    for index in (0,1):
        rows = [r for r in ordinary if r['org']==index]
        organization_rows.append(dict(org=index, count=len(rows), both_busy=sum(r['both_busy'] for r in rows),
            metrics={field:distribution([r[field] for r in rows if r[field] is not None]) for field in
                ('persisted_to_eligible','eligible_to_claim','persisted_to_claim',
                 'eligible_to_next_opportunity','eligible_to_candidate','candidate_to_claim','selected_to_claim',
                 'min_busy_remaining')},
            example=max(rows, key=lambda r:r['eligible_to_claim'], default=None)))
    candidate_cases = []
    for c in cycles:
        for selection in c['candidates']:
            at = selection['at']
            healthy_ready = sorted(set(r['org'] for r in ordinary if r['T1']<=at<=r['T7']))
            healthy_processing = sorted(set(orgs.index(w['organization_id']) for w in works.values()
                if w['organization_id'] in orgs[:2] and w['claimed_at'] and w['completed_at']
                and seconds(w['claimed_at'])<=at<seconds(w['completed_at'])))
            candidate_cases.append(dict(role=c['role'], poll=c['poll'], at=at,
                candidates=selection['orgs'], healthy_ready=healthy_ready,
                last_claim_by_org={index:max((seconds(w['claimed_at']) for w in works.values()
                    if w['organization_id']==org and w['claimed_at'] and seconds(w['claimed_at'])<at), default=None)
                    for index,org in enumerate(orgs)},
                healthy_processing=healthy_processing,
                selected=[conv_org[e['conversation']] for e in c['events'] if e['event']=='candidate_selected'],
                noisy_first_with_healthy_ready=bool(selection['orgs'] and selection['orgs'][0]==2 and healthy_ready)))
    near_ready_starts = []
    for c in cycles:
        for event in c['events']:
            if event['event']!='candidate_selected' or conv_org[event['conversation']]!=2:
                continue
            at = event['time']
            soon = [r for r in ordinary if r['T0']<=at<r['T1']<=at+1]
            if soon:
                query = max((e for e in c['events'] if e['event']=='selector_sql_returned'
                             and e['time']<=at), key=lambda e:e['time'])
                snapshot_bound = query['start']
                history = {index:max((seconds(w['claimed_at']) for w in works.values()
                    if w['organization_id']==org and w['claimed_at'] and seconds(w['claimed_at'])<snapshot_bound),
                    default=None) for index,org in enumerate(orgs)}
                def applicable(row):
                    busy = any(w['organization_id']==orgs[row['org']] and w['claimed_at'] and w['completed_at']
                        and seconds(w['claimed_at'])<=snapshot_bound<seconds(w['completed_at']) for w in works.values())
                    return (row['T0']<=snapshot_bound<row['T1']<=snapshot_bound+1 and not busy
                        and history[2] is not None and (history[row['org']] is None or history[row['org']]<history[2]))
                near_ready_starts.append(dict(role=c['role'], poll=c['poll'], at=at,
                    selector_request_start=snapshot_bound, selector_seconds=query['duration'],
                    claimed=any(r['org']==2 for r in c['claims']),
                    guard_applicable_by_request_time=any(applicable(r) for r in soon),
                    upcoming=[dict(message=r['message'], org=r['org'], deadline=r['T1'],
                        seconds_until_eligible=r['T1']-at, eventual_eligible_to_claim=r['eligible_to_claim']) for r in soon]))
    result = dict(classification='DIAGNOSTIC_ONLY', source=str(path),
        original_gate=receipt['healthy_claim'], margin=10-receipt['healthy_claim']['p95_seconds'],
        planners=planner_rows, organizations=organization_rows, timelines=timelines,
        duplicated_misses=duplicate_misses, selector_sql=distribution(selectors),
        locks_sql_upper_bounds={table:distribution([e['duration'] for e in sqls if e['table']==table])
            for table in sorted(set(e['table'] for e in sqls))},
        candidate_cases=candidate_cases,
        noisy_selected_with_healthy_due_within_existing_poll=near_ready_starts,
        noisy_first_with_healthy_ready=sum(c['noisy_first_with_healthy_ready'] for c in candidate_cases),
        cycles=cycles, count_ordinary=len(ordinary), count_safety=sum(r['route']=='receipt_safety' for r in timelines))
    output = path.with_suffix('.analysis.json')
    output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(source=path.name, gate=result['original_gate'], margin=result['margin'],
        planners=planner_rows, orgs=[{k:v for k,v in r.items() if k!='example'} for r in organization_rows],
        misses=len(duplicate_misses), selector=result['selector_sql'], locks=result['locks_sql_upper_bounds']), indent=2))


parser = argparse.ArgumentParser()
parser.add_argument('receipt', type=Path)
args = parser.parse_args()
analyze(args.receipt)
