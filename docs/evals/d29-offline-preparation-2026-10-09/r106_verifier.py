"""Prospective R1-06 reconciliation. Offline only; never issues physical PASS.

The directory adapter recomputes population/ages/claims from raw journals and
uses the unchanged clock, bound, invariant and queue gates. New causal events
must be collected at the native guard/finalization/context boundaries, not
manufactured from a later query. Missing events fail closed.
"""
import argparse
from collections import Counter, defaultdict
import importlib.util
import json
from pathlib import Path
import sys

from common import BASE, BASE_HASH, BASELINE, HERE, PRIOR, ROOT, lines, read, sha

sys.path.insert(0, str(ROOT / 'backend'))
from apps.agent.tests.scheduling_characterization.assessment import demand_gate, invariant_gate, window_gate
from apps.agent.tests.scheduling_characterization.evidence import ClockMap, Interval, NS, classify, reconstruct, timestamp, transactions
from apps.agent.claim_diagnostic_report import _savepoint_rolled_back

POLICY = 'R106_PROSPECTIVE_OBLIGATIONS_20261009_V1'
ROLES = ('ingress', 'planner_1', 'planner_2', 'sender')


def load_clock_guard():
    spec = importlib.util.spec_from_file_location('sealed_d29_clock_guard', PRIOR / 'revision2/clock_guard.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pair_wire(wire):
    """Correlate exhaustive dispatch/results, including failures, by call ID."""
    grouped, errors, pairs = defaultdict(list), [], []
    for row in wire:
        grouped[row.get('call_id')].append(row)
    identity = ('run_id', 'role', 'os_pid', 'boundary', 'organization_id', 'turn_work_id',
                'message_id', 'epoch', 'lease_fingerprint', 'call_number', 'fault_id', 'injected_fault')
    for call_id, rows in grouped.items():
        d = [r for r in rows if r.get('event') == 'dispatch']
        r = [r for r in rows if r.get('event') == 'result']
        if call_id is None or len(rows) != 2 or len(d) != 1 or len(r) != 1:
            errors.append('DISPATCH_RESULT_NOT_ONE_TO_ONE:' + str(call_id))
            continue
        d, r = d[0], r[0]
        if any(d.get(k) != r.get(k) for k in identity):
            errors.append('CALL_IDENTITY_CHANGED:' + str(call_id))
        if r.get('monotonic_ns', -1) < d.get('monotonic_ns', 0) or r.get('elapsed_ns') != r.get('monotonic_ns', 0) - d.get('monotonic_ns', 0):
            errors.append('CALL_INTERVAL_INVALID:' + str(call_id))
        if d.get('external_destination') is not False or d.get('in_atomic') is not False or d.get('admission_verified') is not True:
            errors.append('CALL_ADMISSION_OR_CONTAINMENT_INVALID:' + str(call_id))
        pairs.append((d, r))
    return pairs, errors


def reconcile(report, census, works, wire, llm_ledger, causal, origins=None):
    """No inputs=episodes=outputs assumption; no inferred deferral discharge.

`causal` is normalized by causal_events() from raw, committed journal events.
Unit models may exercise this function but cannot accredit physical load.
"""
    errors = list(report['issues'])
    if report['uncertain_transactions']:
        errors.append('UNRESOLVED_TRANSACTION')
    rows = {m['id']: m for m in census}
    ws = {w['id']: w for w in works}
    episodes = report['episodes']
    ep_work = {e['turn_work_id']: e for e in episodes if e.get('turn_work_id') is not None}
    if len(ws) != len(works) or len(rows) != len(census) or len(ep_work) != len(episodes):
        errors.append('DUPLICATE_OR_UNCLAIMED_IDENTITY')
    if set(ep_work) != set(ws):
        errors.append('EPISODE_WORK_POPULATION_MISMATCH')
    inputs = {m['id'] for m in census if m['direction'] == 'in' and m.get('semantic_type') != 'safety_signal'}
    members = [i for e in episodes for i in e['member_ids']]
    if set(members) != inputs or len(members) != len(set(members)) or len(inputs) != report['population']['accepted_durable_inputs']:
        errors.append('INPUT_POPULATION_NOT_CONSERVED')
    cut = Interval(*report['cut_ns_bounds'])
    for e in episodes:
        eid = e['episode_id']
        ready = Interval(*e['ready_ns_bounds'])
        claim = Interval(*e['claim_commit_ns_bounds']) if e.get('claim_commit_ns_bounds') else None
        result = classify(ready, claim, cut, valid=not e.get('issues'), bound_ns=120*NS)
        if result['disposition'] != 'OBSERVED_WITHIN_TARGET':
            errors.append('BOUND_OR_ORIGIN_NOT_ACCREDITED:' + eid + ':' + result['disposition'])
        if origins and eid in origins and e['ready_ns_bounds'] != origins[eid]:
            errors.append('ORIGINAL_READY_CHANGED:' + eid)
        if not e['member_ids'] or ready.lo is None or ready.hi is None:
            errors.append('EPISODE_WITHOUT_ORIGIN:' + eid)
        w = ws.get(e.get('turn_work_id'))
        for mid in e['member_ids']:
            m = rows.get(mid)
            if not m or (m['organization_id'], m['conversation_id'], m.get('turn_work_id')) != (e['organization_id'], e['conversation_id'], e['turn_work_id']):
                errors.append('INPUT_MEMBERSHIP_OR_SCOPE_INVALID:' + str(mid))
        if not w or w['status'] != 'COMPLETED' or (w['organization_id'], w['conversation_id']) != (e['organization_id'], e['conversation_id']):
            errors.append('WORK_NOT_COMPLETED_OR_WRONG_SCOPE:' + str(e.get('turn_work_id')))
    pairs, pair_errors = pair_wire(wire)
    errors.extend(pair_errors)
    llm = defaultdict(list)
    meta = defaultdict(list)
    for d, r in pairs:
        if d['boundary'] == 'llm':
            llm[d.get('turn_work_id')].append((d, r))
        elif d['boundary'] == 'meta':
            meta[d.get('message_id')].append((d, r))
    if set(llm) != set(ws):
        errors.append('CLAIMED_WORK_WITHOUT_SERVICE_WITNESS_OR_ORPHAN_SERVICE')
    calls_by_work = defaultdict(list)
    for c in llm_ledger:
        calls_by_work[c['turn_work_id']].append(c)
    if set(calls_by_work) != set(ws):
        errors.append('LLM_LEDGER_WORK_POPULATION_MISMATCH')
    for wid, w in ws.items():
        calls = llm[wid]
        if len(calls) != 2 or {d.get('call_number') for d, _ in calls} != {1, 2} or any(r.get('result') != 'ACCEPTED' or r.get('elapsed_ns', -1) < NS//2 for _, r in calls):
            errors.append('BASE_LLM_COST_NOT_COMPLETELY_OBSERVED:' + str(wid))
        ledger = calls_by_work[wid]
        if len(ledger) != 2 or any(not c.get('admitted_at') or not c.get('recorded_at') or c.get('error') or (c['organization_id'], c['conversation_id']) != (w['organization_id'], w['conversation_id']) for c in ledger):
            errors.append('LLM_LEDGER_NOT_RECONCILED:' + str(wid))
        if w.get('llm_calls_admitted') != 2 or any(d.get('epoch') != w.get('ownership_epoch') or d.get('lease_fingerprint') != w.get('lease_fingerprint') for d, _ in calls):
            errors.append('LLM_OWNERSHIP_OR_COUNT_MISMATCH:' + str(wid))
    outs = defaultdict(list)
    accepted = set()
    for m in census:
        if m['direction'] != 'out':
            continue
        outs[m.get('turn_work_id')].append(m)
        calls = meta[m['id']]
        w = ws.get(m.get('turn_work_id'))
        good = (len(calls) == 1 and calls[0][1].get('result') == 'ACCEPTED'
                and calls[0][1].get('elapsed_ns', -1) >= NS//5
                and m.get('provider_accepted_at') is not None and m.get('send_admitted_at') is not None
                and w is not None and (m['organization_id'], m['conversation_id']) == (w['organization_id'], w['conversation_id'])
                and calls[0][0].get('organization_id') == m['organization_id'])
        if not good:
            errors.append('OUTPUT_ACCEPTANCE_NOT_PROVEN:' + str(m['id']))
        else:
            accepted.add(m['id'])
    if set(meta) != {m['id'] for values in outs.values() for m in values} or set(outs) - set(ws):
        errors.append('META_OUTBOX_POPULATION_MISMATCH')
    guards, terminals, contexts = causal
    successors = {}
    for wid, w in ws.items():
        if w.get('outcome_code') != 'deferred_to_new_input':
            if not outs[wid] or any(m['id'] not in accepted for m in outs[wid]):
                errors.append('RESPONSE_OBLIGATION_UNRESOLVED:' + str(wid))
            continue
        if outs[wid]:
            errors.append('DEFERRED_WORK_HAS_OUTPUT:' + str(wid))
        gs = [g for g in guards if g.get('turn_work_id') == wid]
        ts = [t for t in terminals if t.get('turn_work_id') == wid]
        if len(gs) != 1 or len(ts) != 1:
            errors.append('DEFERRAL_NATIVE_GUARD_OR_COMMIT_MISSING:' + str(wid))
            continue
        g, t = gs[0], ts[0]
        triggers = set(g.get('new_input_ids', []))
        ep = ep_work[wid]
        if (not g.get('has_new_input') or not triggers or g['transaction_identity'] != t['transaction_identity']
                or g['observed_ns_bounds'][1] > t['observed_ns_bounds'][0]
                or t.get('outcome_code') != 'deferred_to_new_input' or t.get('cas_affected') != 1
                or g.get('anchor_message_id') != w.get('anchor_message_id')
                or g.get('anchor_created_at') != w.get('anchor_created_at')
                or any(g.get(k) != w.get(v) or t.get(k) != w.get(v) for k, v in
                       (('epoch', 'ownership_epoch'), ('lease_fingerprint', 'lease_fingerprint'), ('organization_id', 'organization_id'), ('conversation_id', 'conversation_id')))):
            errors.append('DEFERRAL_CAUSAL_WITNESS_INVALID:' + str(wid))
            continue
        candidate = [s for s in episodes if s['turn_work_id'] != wid and triggers <= set(s['member_ids'])
                     and (s['organization_id'], s['conversation_id']) == (ep['organization_id'], ep['conversation_id'])]
        if len(candidate) != 1:
            errors.append('DEFERRAL_SUCCESSOR_NOT_DEMONSTRATED:' + str(wid))
            continue
        succ = candidate[0]
        sid = succ['turn_work_id']
        cs = [c for c in contexts if c.get('turn_work_id') == sid and c.get('phase') == 'BEFORE_FIRST_LLM']
        required = set(ep['member_ids']) | triggers
        if (t['commit_ns_bounds'][1] > succ['claim_commit_ns_bounds'][0] or not cs
                or not any(required <= set(c.get('consumed_input_ids', []))
                           and c.get('organization_id') == ep['organization_id'] and c.get('conversation_id') == ep['conversation_id']
                           and c.get('capture_boundary') == 'ACTUAL_PACKED_CONTEXT'
                           and c.get('epoch') == ws[sid]['ownership_epoch']
                           and c.get('lease_fingerprint') == ws[sid]['lease_fingerprint']
                           and all(c['observed_ns_bounds'][1] <= d['db_ns'] for d, _ in llm[sid]) for c in cs)):
            errors.append('DEFERRAL_SUCCESSOR_CONTEXT_NOT_DEMONSTRATED:' + str(wid))
            continue
        if not all(mid in inputs and mid not in ep['member_ids'] for mid in triggers):
            errors.append('DEFERRAL_TRIGGER_NOT_A_NEW_INPUT:' + str(wid))
            continue
        if any(g.get('input_commit_ns_bounds', {}).get(str(mid), [None, None])[1] is None
               or g['input_commit_ns_bounds'][str(mid)][1] > g['observed_ns_bounds'][0] for mid in triggers):
            errors.append('DEFERRAL_TRIGGER_COMMIT_NOT_PROVEN:' + str(wid))
            continue
        anchor = (timestamp(w['anchor_created_at']), w['anchor_message_id'])
        cursors = g.get('input_creation_cursors', {})
        if any(str(mid) not in cursors or tuple(cursors[str(mid)]) <= anchor for mid in triggers):
            errors.append('DEFERRAL_TRIGGER_NOT_AFTER_NATIVE_ANCHOR:' + str(wid))
            continue
        successors[wid] = sid
    obligations = []
    for ep in episodes:
        wid = ep['turn_work_id']
        chain, cursor = [], wid
        while cursor in successors and cursor not in chain:
            chain.append(cursor)
            cursor = successors[cursor]
        cycle = cursor in chain
        if cycle or (ws.get(cursor, {}).get('outcome_code') == 'deferred_to_new_input') or not outs[cursor] or any(m['id'] not in accepted for m in outs[cursor]):
            errors.append('OBLIGATION_CHAIN_UNRESOLVED:' + str(wid))
            resolved = False
        else:
            resolved = True
        obligations.append({'episode_id': ep['episode_id'], 'input_ids': ep['member_ids'], 'work_id': wid,
                            'deferral_chain': chain, 'terminal_work_id': cursor,
                            'accepted_output_ids': [m['id'] for m in outs[cursor] if m['id'] in accepted],
                            'causal_chain_verified': resolved})
    return {'errors': sorted(set(errors)), 'obligations': obligations,
            'counts': {'inputs': len(inputs), 'episodes': len(episodes), 'works': len(ws),
                       'llm_calls': sum(len(v) for v in llm.values()), 'outbound': sum(len(v) for v in outs.values()),
                       'meta_calls': sum(len(v) for v in meta.values()), 'accepted_outputs': len(accepted),
                       'deferred_works': sum(w.get('outcome_code') == 'deferred_to_new_input' for w in ws.values()),
                       'demonstrated_successor_links': len(successors)}}


def causal_events(journals, input_effects):
    """Resolve new witnesses against actual outer commits, never final rows."""
    guards, terminals, contexts = [], [], []
    input_commits = {str(e['message_id']): tx['commit'].json() for tx in input_effects for e in tx['rows'] if e['event'] == 'message_persisted'}
    input_cursors = {str(e['message_id']): [timestamp(e['created_at']), e['message_id']] for tx in input_effects for e in tx['rows'] if e['event'] == 'message_persisted'}
    for journal in journals:
        clock = ClockMap(journal)
        grouped = defaultdict(list)
        for event in journal:
            if event.get('transaction_id'):
                grouped[event['transaction_id']].append(event)
            if event['event'] == 'context_consumed':
                contexts.append(dict(event, observed_ns_bounds=clock.execution({'execute_start_ns': event['monotonic_ns'], 'execute_end_ns': event['monotonic_ns']}).json()))
        for txid, events in grouped.items():
            commits = [e for e in events if e['event'] == 'commit_end' and e.get('error_class') is None]
            if len(commits) != 1 or any(e['event'] == 'rollback_end' for e in events):
                continue
            commit = clock.execution(commits[0]).json()
            for event in events:
                if event['event'] not in ('new_input_guard', 'work_terminal') or _savepoint_rolled_back(event, events):
                    continue
                row = dict(event, transaction_identity=[event['session_id'], txid], commit_ns_bounds=commit,
                           observed_ns_bounds=clock.execution({'execute_start_ns': event['monotonic_ns'], 'execute_end_ns': event['monotonic_ns']}).json())
                if event['event'] == 'new_input_guard':
                    row['input_commit_ns_bounds'] = input_commits
                    row['input_creation_cursors'] = input_cursors
                    guards.append(row)
                else:
                    terminals.append(row)
    return guards, terminals, contexts


def population_gate(population, offers, census, pre, orgs):
    errors=[]
    omap={o['message_id']:o for o in offers if o['outcome']=='ACCEPTED_DURABLE'}
    cmap={m['id']:m for m in census}
    by_org_slot={}
    backlog=[p for p in population if p['phase']=='BACKLOG']
    if {p['message_id'] for p in backlog}!={m['id'] for m in pre['messages']}:
        errors.append('PRESTART_BACKLOG_LEDGER_MISMATCH')
    for p in backlog:
        m=cmap.get(p['message_id'])
        if m:by_org_slot[(p['organization_id'],p['slot'])]=m['conversation_id']
    if len(by_org_slot)!=8 or any(len({c for (o,s),c in by_org_slot.items() if o==org})!=4 for org in orgs):
        errors.append('FOUR_DISTINCT_BACKLOG_CONVERSATIONS_PER_ORG_REQUIRED')
    for p in population:
        o=omap.get(p['message_id']);m=cmap.get(p['message_id'])
        if (not o or not m or o.get('phase')!=p['phase'] or o.get('schedule_id')!=p['schedule_id']
                or m['organization_id']!=p['organization_id'] or o['organization_id']!=p['organization_id']
                or by_org_slot.get((p['organization_id'],p['slot']))!=m['conversation_id']):
            errors.append('POPULATION_SCOPE_SLOT_OR_PHASE_MISMATCH:'+str(p['message_id']))
        if p['phase']=='ORDINARY' and p['slot'] not in (0,1,2):
            errors.append('FOURTH_SLOT_USED_FOR_ORDINARY_OFFER')
    return {'errors':sorted(set(errors))}


def verify_directory(directory):
    """Read only. Historical data remains audit-only even if all gates pass."""
    d = Path(directory)
    participant = read(d/'participant-plan.json')
    raw = {role: lines(d/(role+'.jsonl')) for role in ROLES}
    clock_module = load_clock_guard()
    errors, continuity = [], {}
    for role, journal in raw.items():
        state = clock_module.Continuity()
        try:
            for row in journal:
                state.feed(row)
            continuity[role] = state.finish()
        except (ValueError, KeyError, clock_module.ClockInvalid) as exc:
            errors.append('CLOCK_OR_CAPTURE_INVALID:' + role + ':' + str(exc))
    common = {'policy': POLICY, 'source_kind': 'OFFLINE_RAW_CAPTURE_AUDIT', 'execution_authorized': False,
              'physical_accreditation': False, 'base_sha256': sha(BASE), 'clock': continuity}
    if errors:
        return dict(common, status='INVALID_EVIDENCE', errors=errors)
    journals = list(raw.values())
    final = read(d/'full-durable-final.json')
    offers = lines(d/'schedule-offers.jsonl')
    report = reconstruct(journals, offers, final['messages'], Interval(final['db_ns'], final['db_ns']), run_id=participant['run_id'])
    effects, unresolved = transactions(journals)
    wire = [e for r in ROLES[1:] for e in lines(d/(r+'-wire.jsonl'))]
    result = reconcile(report, final['messages'], final['works'], wire, final['calls'], causal_events(journals, effects))
    errors.extend(result['errors'])
    slots = read(d/'schedule.json')
    orgs = participant['organization_ids']
    population = lines(d/'population-slots.jsonl')
    back = [p for p in population if p['phase'] == 'BACKLOG']
    ordinary = [p for p in population if p['phase'] == 'ORDINARY']
    if [p['slot'] for p in ordinary] != [i % 3 for i in range(len(ordinary))]:
        errors.append('GLOBAL_BASE_ROTATION_CHANGED')
    if len(back) != 8 or any(sorted(p['slot'] for p in back if p['organization_id'] == o) != [0,1,2,3] for o in orgs):
        errors.append('BACKLOG_2X4_NOT_CONSERVED')
    if len(population) != len(offers) or {p['message_id'] for p in population} != {o['message_id'] for o in offers}:
        errors.append('POPULATION_SLOT_LEDGER_NOT_RECONCILED')
    cuts = lines(d/'snapshots.jsonl')
    pre = [c for c in cuts if c['stage'] == 'backlog_ready_before_workers']
    if len(pre) != 1:
        errors.append('PRESTART_CUT_MISSING')
    else:
        pre = pre[0]
        errors.extend(population_gate(population, offers, final['messages'], pre, orgs)['errors'])
        if pre['works'] or len(pre['messages']) != 8 or any(m['turn_work_id'] or not m['available_at'] or timestamp(m['available_at']) > pre['db_ns'] for m in pre['messages']):
            errors.append('EIGHT_NATURAL_READY_PRESTART_NOT_OBSERVED')
        for m in pre['messages']:
            ep = next((e for e in report['episodes'] if m['id'] in e['member_ids']), None)
            if not ep or ep['ready_ns_bounds'] != [timestamp(m['available_at'])]*2:
                errors.append('BACKLOG_ORIGINAL_AGE_NOT_PRESERVED:' + str(m['id']))
        if any(c['event'] == 'claim_bound' and c['claimed_at'] and timestamp(c['claimed_at']) <= pre['db_ns'] for j in journals for c in j):
            errors.append('CLAIM_BEFORE_PRESTART_CUT')
    from apps.agent.tests.scheduling_characterization.replay import schedule
    from apps.agent.tests.scheduling_characterization.execution import queued_samples
    start = min(s['due_monotonic_ns'] for s in slots)
    if schedule(participant, start) != slots:
        errors.append('BASE_CALENDAR_CHANGED')
    clock = ClockMap(raw['ingress'])
    offsets = [0, 120, 240, 360]
    intervals = [Interval(start+o*NS+clock.offset.lo, start+o*NS+clock.offset.hi) for o in offsets]
    queues = queued_samples(report, offsets, intervals)
    # Narrow prospective R1-06 exception only: allow coalescing; retain every
    # schedule, acceptance, tenant, origin, 120s bound and invariant check.
    dg = demand_gate(dict(participant, boundary_case=True), report, offers, slots, orgs, (intervals[0].lo, intervals[-1].hi))
    ig = invariant_gate(report, journals, final['messages'], final['works'], [r for r in wire if r['event']=='dispatch'], orgs)
    wg = window_gate(participant, report, queues, orgs)
    for name, gate in (('demand', dg), ('invariants', ig), ('windows', wg)):
        errors.extend(name+':'+str(e) for e in gate['missing']+gate['violations'])
    if any(v in ('INDETERMINATE', 'OBSERVED_BACKLOG_GROWTH') for v in wg['backlog'].values()):
        errors.append('QUEUE_BACKLOG_NOT_COMPATIBLE')
    if sha(BASE) != BASE_HASH or participant['baseline'] != BASELINE or participant['confirmed_base_reference']['sha256'] != BASE_HASH:
        errors.append('BASE_OR_BASELINE_CHANGED')
    base=read(BASE)
    if participant['offered_rates_per_minute']!=base['confirmed_base']['rates'] or participant['confirmed_base_rates']!=base['confirmed_base']['rates']:
        errors.append('BASE_RATES_CHANGED')
    for name, expected_hash in participant['source_hashes'].items():
        source=ROOT/'backend/apps/agent/tests/scheduling_characterization'/name
        if not source.is_file() or sha(source)!=expected_hash:errors.append('EVALUATION_SOURCE_INTEGRITY_CHANGED:'+name)
    if participant['bound_seconds'] != 120 or participant['offer_seconds'] != 360 or participant['followup_seconds'] != 240 or participant['ordinary_conversations_per_org'] != 3 or participant['conversations_per_org'] != 4:
        errors.append('R106_RECIPE_CHANGED')
    pids = [j[0]['os_pid'] for j in journals]
    if len(set(pids)) != 4:
        errors.append('PARTICIPANT_PROCESSES_NOT_SEPARATE')
    spans = [[r['monotonic_ns'] for r in raw[role] if r['event']=='poll_start'] for role in ROLES[1:3]]
    if any(not s for s in spans) or max(s[0] for s in spans) >= min(s[-1] for s in spans):
        errors.append('PLANNER_CONCURRENCY_NOT_OBSERVED')
    end = clock.execution({'execute_start_ns': start+600*NS, 'execute_end_ns': start+600*NS})
    if final['db_ns'] < end.hi:
        errors.append('FOLLOWUP_END_NOT_DEFINITELY_COVERED')
    errors = sorted(set(errors))
    return dict(common, status='HISTORICAL_AUDIT_ONLY' if participant.get('reconciliation_policy') != POLICY else 'OFFLINE_EVALUATED_NOT_PHYSICAL_ACCREDITATION',
                errors=errors, offline_checks_satisfied=not errors, reconciliation=result, gates={'demand':dg,'invariants':ig,'windows':wg},
                synthetic_evidence=[], input_capture_sha256={p.name:sha(p) for p in d.iterdir() if p.suffix in ('.json','.jsonl')},
                required_new_witnesses=['new_input_guard','work_terminal','context_consumed'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='Offline read-only verification; no probes or bootstrap')
    p.add_argument('directory')
    args = p.parse_args()
    print(json.dumps(verify_directory(args.directory), ensure_ascii=False, indent=2))
