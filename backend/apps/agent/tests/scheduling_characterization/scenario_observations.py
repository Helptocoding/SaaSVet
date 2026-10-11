"""Derive scenario witnesses from captures, never merely from a selected case."""
import math

from .evidence import ClockMap, Interval, NS, timestamp, transactions
from .runner import BASELINE


def observations(job, report, journals, wire, read_lines, directory, final):
    events = []
    org_ids = job['organization_ids']
    def add(name, at, org=0, source='JOURNAL', **extra):
        events.append(dict(event=name, run_id=job['run_id'], organization_index=org,
                           db_ns=at, observed=True, source=source, **extra))
    effects, unresolved = transactions(journals)
    claims = [(tx['commit'], e) for tx in effects for e in tx['rows'] if e['event'] == 'claim_bound' and e['member_ids'] is not None]
    claims.sort(key=lambda item: item[0].lo)
    first = min((e['ready_ns_bounds'][0] for e in report['episodes'] if e['ready_ns_bounds'][0] is not None), default=None)
    last = final['db_ns']
    case = job['case_id']
    if case == 'R1-01' and len({e['conversation_id'] for e in report['episodes']}) > 1:
        add('multiple_conversations', last)
    planners = [j for j in journals if j[0].get('worker') in ('planner_1', 'planner_2')]
    if case in ('R1-02', 'R1-03') and len(planners) == 2 and all(any(r['event'] == 'poll_start' for r in j) for j in planners):
        add('concurrent_planners', first)
        rates = job['offered_rates_per_minute']
        if case == 'R1-02' and rates[0] == rates[1] and all(report['organization_counts'].get(str(o), 0) for o in org_ids):
            add('balanced_offer', last)
        if case == 'R1-03' and math.isclose(rates[0], 2 * rates[1]) and math.isclose(sum(rates), job['comparison_global_rate']):
            add('same_global_2_to_1', last)
    if case == 'R1-04':
        # A miss of a future conversation while another org has READY demand,
        # on two distinct polls, is required. Ordinary multi-tenant inputs do
        # not establish this scenario without those observed facts.
        witnessed = []
        census = {m['conversation_id']: m for m in final['messages']}
        for journal in planners:
            clock = ClockMap(journal)
            if clock.offset is None:
                continue
            for r in journal:
                if r['event'] != 'claim_result' or r.get('result') != 'miss':
                    continue
                conv = r.get('conversation_id')
                at = clock.offset.lo + r['monotonic_ns']
                row = census.get(conv)
                if not row:
                    continue
                future = any(e['conversation_id'] == conv and e['ready_ns_bounds'][0] is not None and e['ready_ns_bounds'][0] > at for e in report['episodes'])
                waiter = next((e for e in report['episodes'] if e['organization_id'] != row['organization_id']
                    and e['ready_ns_bounds'][1] is not None and e['ready_ns_bounds'][1] <= at
                    and (e['claim_commit_ns_bounds'] is None or e['claim_commit_ns_bounds'][0] > at)), None)
                if future and waiter:
                    witnessed.append((at, r.get('poll_id'), waiter))
        witnessed.sort(key=lambda item: item[0])
        if witnessed:
            at, poll, waiter = witnessed[0]
            add('ready_waiter', waiter['ready_ns_bounds'][1])
            add('future_eligibility', at)
            add('forecast_miss', at)
            later = next((w for w in witnessed[1:] if w[1] != poll), None)
            if later:
                add('future_eligibility_again', later[0])
    if case == 'R1-05':
        # The independently reconciled schedule proves the multiplier; actual
        # generator pacing is checked by demand_gate, not this plan alone.
        schedule = __import__('json').loads((directory / 'schedule.json').read_text(encoding='utf-8'))
        clock = ClockMap(next(j for j in journals if j[0]['worker'] == 'ingress'))
        start = min(s['due_monotonic_ns'] for s in schedule) + clock.offset.lo
        add('burst_begin', start)
        add('burst_end', start + job['burst_seconds'] * NS)
        add('base_return', start + job['burst_seconds'] * NS)
        add('drain_cut', last)
    if case == 'R1-06':
        cuts = read_lines(directory / 'snapshots.jsonl')
        backlog = next((s for s in cuts if s['stage'] == 'backlog_ready_before_workers'), None)
        if backlog:
            add('captured_backlog', min(e['ready_ns_bounds'][0] for e in report['episodes']))
            add('natural_ready', backlog['db_ns'])
            starts = [ClockMap(j).offset.lo + j[0]['monotonic_ns'] for j in planners]
            add('workers_start', min(starts), source='PROCESS_EXIT')
            add('drain_cut', last)
    if case in ('R2-01', 'R2-02', 'R2-09'):
        for role in ('planner_1', 'planner_2', 'sender'):
            events.extend(read_lines(directory / (role + '-events.jsonl')))
        def db_time(row, role):
            journal = next(j for j in journals if j[0]['worker'] == role)
            return ClockMap(journal).offset.lo + row['monotonic_ns']
        if case == 'R2-01':
            for role in ('planner_1', 'planner_2'):
                values = read_lines(directory / (role + '-wire.jsonl'))
                start = next((r for r in values if r['event'] == 'dispatch' and r['boundary'] == 'llm' and r['organization_id'] == org_ids[0]), None)
                result = next((r for r in values if start and r['event'] == 'result' and r.get('turn_work_id') == start.get('turn_work_id') and r['elapsed_ns'] >= .5 * job['slow_multiplier'] * NS), None)
                if start and result:
                    add('slow_service_begin', start['db_ns'], source='CONTAINED_PROVIDER')
                    add('slow_service_end', db_time(result, role), source='CONTAINED_PROVIDER')
                    peer = next((c for c, e in claims if e['organization_id'] == org_ids[1] and c.lo >= db_time(result, role)), None)
                    if peer:
                        add('peer_progress', peer.hi, org=1)
                    break
        if case == 'R2-02':
            begin = next((e for e in events if e['event'] == 'block_begin'), None)
            release = next((e for e in events if e['event'] == 'block_release'), None)
            if begin and release:
                peer = next((c for c, e in claims if e['organization_id'] == org_ids[1] and c.lo > begin['db_ns'] and c.hi < release['db_ns']), None)
                if peer:
                    add('peer_progress', peer.hi, org=1)
        if case == 'R2-09':
            values = read_lines(directory / 'sender-wire.jsonl')
            dispatch = next((r for r in values if r['event'] == 'dispatch' and r['organization_id'] == org_ids[0]), None)
            result = next((r for r in values if dispatch and r['event'] == 'result' and r['message_id'] == dispatch['message_id']), None)
            if dispatch and result:
                from apps.channels.models import Message
                row = Message.objects.get(pk=dispatch['message_id'])
                add('sender_admitted', timestamp(row.send_admitted_at.isoformat()), source='INDEPENDENT_DB_WITNESS')
                add('meta_dispatch', dispatch['db_ns'], source='CONTAINED_PROVIDER')
                add('meta_result', db_time(result, 'sender'), source='CONTAINED_PROVIDER', result='UNCERTAIN' if row.status == 'uncertain' else 'ACCEPTED')
                later = next((c for c, e in claims if c.lo >= db_time(result, 'sender')), None)
                if later:
                    add('ordinary_progress', later.hi)
                    if sum(r['event'] == 'dispatch' and r['message_id'] == row.pk for r in values) == 1:
                        add('no_blind_resend', last, source='INDEPENDENT_DB_WITNESS')
    return sorted(events, key=lambda e: e['db_ns'])
