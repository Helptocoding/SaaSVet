"""Complete-population, conservative D29 reconstruction; no Django setup or IO.

All times are integer nanoseconds on the calibrated database clock. Journal
clock mapping is conditional on no unobserved clock step. Unknown evidence
never becomes a passing sample. This module does not reuse historical gates.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from apps.agent.claim_diagnostic_report import _savepoint_rolled_back

NS = 1_000_000_000
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def timestamp(value):
    delta = datetime.fromisoformat(value).astimezone(timezone.utc) - EPOCH
    return (delta.days * 86400 + delta.seconds) * NS + delta.microseconds * 1000


@dataclass(frozen=True)
class Interval:
    lo: int | None
    hi: int | None

    def __post_init__(self):
        if self.lo is not None and self.hi is not None and self.lo > self.hi:
            raise ValueError('Reversed temporal interval')

    def json(self):
        return [self.lo, self.hi]


def classify(ready, claim, cut, *, valid=True, bound_ns=120 * NS):
    if not valid:
        return {'disposition': 'INVALID_EVIDENCE', 'wait_seconds_bounds': None}
    finish = claim or cut
    low = max(0, finish.lo - ready.hi) if finish.lo is not None and ready.hi is not None else None
    high = finish.hi - ready.lo if finish.hi is not None and ready.lo is not None else None
    if high is not None and high < 0:
        return {'disposition': 'NOT_YET_READY' if claim is None else 'INVALID_EVIDENCE',
                'wait_seconds_bounds': None}
    if low is not None and high is not None and low > high:
        return {'disposition': 'INVALID_EVIDENCE', 'wait_seconds_bounds': None}
    if low is not None and low > bound_ns:
        disposition = 'OBSERVED_EXCESS'
    elif claim is not None and high is not None and high <= bound_ns and low is not None:
        disposition = 'OBSERVED_WITHIN_TARGET'
    elif claim is None and ready.lo is not None and cut.hi is not None and ready.lo > cut.hi:
        disposition = 'NOT_YET_READY'
    elif claim is None:
        disposition = 'PENDING_CENSORED'
    else:
        disposition = 'INDETERMINATE'
    return {'disposition': disposition, 'wait_seconds_bounds':
            [low / NS if low is not None else None, high / NS if high is not None else None]}


class ClockMap:
    def __init__(self, rows):
        calibrations = [r for r in rows if r['event'] == 'db_clock']
        offsets = [(timestamp(r['db_timestamp']) - r['end_ns'],
                    timestamp(r['db_timestamp']) - r['start_ns']) for r in calibrations]
        self.offset = Interval(max(x[0] for x in offsets), min(x[1] for x in offsets)) if offsets else None

    def execution(self, row):
        if self.offset is None:
            return Interval(None, None)
        return Interval(self.offset.lo + row['execute_start_ns'],
                        self.offset.hi + row['execute_end_ns'])


@dataclass
class Episode:
    organization_id: int
    conversation_id: int
    ordinal: int
    members: list = field(default_factory=list)
    ready: Interval = field(default_factory=lambda: Interval(None, None))
    claim: Interval | None = None
    work_id: int | None = None
    issues: list = field(default_factory=list)

    def receipt(self, run_id, cut, bound_ns):
        result = classify(self.ready, self.claim, cut, valid=not self.issues, bound_ns=bound_ns)
        return dict(episode_id=f'{run_id}:{self.organization_id}:{self.conversation_id}:{self.members[0]}:{self.ordinal}',
                    organization_id=self.organization_id, conversation_id=self.conversation_id,
                    member_ids=self.members, ready_ns_bounds=self.ready.json(),
                    claim_commit_ns_bounds=self.claim.json() if self.claim else None,
                    turn_work_id=self.work_id, issues=self.issues, **result)


def transactions(journals, resolutions=()):
    """Savepoint rollback removes only its effects; failed COMMIT is unresolved.

    Even a subsequent successful ROLLBACK cannot prove that a failed COMMIT
    did not commit. A separate durable witness may resolve that uncertainty.
    """
    effects, uncertainties = [], []
    for rows in journals:
        clock = ClockMap(rows)
        groups = {}
        for row in rows:
            if row.get('transaction_id'):
                groups.setdefault(row['transaction_id'], []).append(row)
        for tx, group in groups.items():
            successful = next((r for r in group if r['event'] == 'commit_end' and not r['error_class']), None)
            failed_commit = next((r for r in group if r['event'] == 'commit_end' and r['error_class']), None)
            rollback = any(r['event'] == 'rollback_end' and not r['error_class'] for r in group)
            logical = [r for r in group if r['event'] in ('message_persisted','deadline_set','claim_bound')
                       and not _savepoint_rolled_back(group, r)]
            if not logical:
                continue
            resolution = next((r for r in resolutions if r['session_id'] == rows[0]['session_id']
                               and r['transaction_id'] == tx), None)
            if failed_commit:
                if resolution and resolution['result'] == 'COMMITTED' and resolution['witness_verified']:
                    start = clock.execution(failed_commit)
                    interval = Interval(start.lo, resolution['visible_by_db_ns'])
                else:
                    uncertainties.append({'session_id': rows[0]['session_id'], 'transaction_id': tx,
                                          'reason': 'COMMIT_ACK_UNRESOLVED', 'candidate_events': logical})
                    continue
            elif rollback:
                continue
            elif successful:
                interval = clock.execution(successful)
            else:
                uncertainties.append({'session_id': rows[0]['session_id'], 'transaction_id': tx,
                                      'reason': 'TRANSACTION_OUTCOME_UNRESOLVED', 'candidate_events': logical})
                continue
            effects.append({'session_id':rows[0]['session_id'], 'transaction_id':tx,
                            'commit':interval, 'rows':logical,'context_rows':group})
    return effects, uncertainties


def queue_counts(episodes, cut):
    per_org = {}
    for episode in episodes:
        entry = per_org.setdefault(episode.organization_id, [0,0])
        # A claim after this cut does not erase a pending episode at the cut.
        if episode.claim and episode.claim.hi is not None and episode.claim.hi <= cut.lo:
            continue
        definitely_unclaimed = not episode.claim or (episode.claim.lo is not None and episode.claim.lo > cut.hi)
        definitely_ready = episode.ready.hi is not None and episode.ready.hi <= cut.lo
        possibly_ready = episode.ready.lo is None or episode.ready.lo <= cut.hi
        if definitely_ready and definitely_unclaimed:
            entry[0] += 1
        if possibly_ready:
            entry[1] += 1
    return per_org


def backlog_disposition(counts, full_windows=None):
    """Counts are lower/upper bounds at aligned cuts, including final remainder."""
    if len(counts) < 2:
        return 'INDETERMINATE'
    increasing = [b[0] > a[1] for a,b in zip(counts,counts[1:])]
    full_windows = full_windows if full_windows is not None else [True]*len(increasing)
    if any(all(increasing[i:i+3]) and all(full_windows[i:i+3]) for i in range(len(increasing)-2)):
        return 'OBSERVED_BACKLOG_GROWTH'
    if counts[-1][0] > counts[0][1]:
        return 'INDETERMINATE'
    if counts[-1][1] > counts[0][0] or any(a[0] != a[1] for a in counts):
        return 'INDETERMINATE'
    return 'NO_GROWTH_OBSERVED'


def reconstruct(journals, offers, census, cut, *, run_id, resolutions=(), bound_ns=120 * NS,
                queue_cuts=(), capture_errors=(), level_evidence=None):
    """Births come from ingress, never from claims or a completed-work query.

    This intentionally refuses to certify unobserved ownership/safety changes.
    Those require a scenario-specific transition witness, not inferred pauses.
    """
    issues = list(capture_errors)
    if any(any(r.get('run_id') != run_id for r in rows) for rows in journals):
        issues.append('CAPTURE_RUN_MISMATCH')
        journals=[rows for rows in journals if all(r.get('run_id')==run_id for r in rows)]
    sessions=[rows[0]['session_id'] for rows in journals if rows]
    if len(sessions)!=len(set(sessions)):
        issues.append('DUPLICATE_CAPTURE_SESSION')
        journals=[]
    try:
        effects, unknown = transactions(journals,resolutions)
    except ValueError:
        effects, unknown = [], []
        issues.append('INVALID_CLOCK_RELATION')
    episodes, pending, counters, assigned, recovery = [], {}, {}, {}, []
    deadlines = {}
    accepted = {o['message_id'] for o in offers if o['outcome'] == 'ACCEPTED_DURABLE' and o.get('message_id')}
    ordinary_rows = {r['id']:r for r in census if r['direction'] == 'in' and not r['semantic_type']}
    effects.sort(key=lambda t: (t['commit'].lo if t['commit'].lo is not None else -1, t['session_id'],t['transaction_id']))
    previous_by_conv = {}
    for tx in effects:
        commit = tx['commit']
        if commit.lo is not None and cut.hi is not None and commit.lo > cut.hi:
            continue
        if commit.hi is None or commit.lo is None:
            issues.append('MISSING_COMMIT_CLOCK_BOUNDARY')
        if commit.hi is not None and cut.lo is not None and commit.hi > cut.lo:
            issues.append('TRANSACTION_OVERLAPS_ANALYSIS_CUT')
            continue
        convs = {r['conversation_id'] for r in tx['rows']}
        for conv in convs:
            prev = previous_by_conv.get(conv)
            if prev and (prev.hi is None or commit.lo is None or prev.hi > commit.lo):
                issues.append(f'AMBIGUOUS_TRANSACTION_ORDER:{conv}')
            previous_by_conv[conv] = commit
        born_here=set()
        for event in tx['rows']:
            conv, org = event['conversation_id'],event['organization_id']
            if event['event'] == 'message_persisted':
                mid = event['message_id']
                if mid not in ordinary_rows:
                    issues.append(f'UNACCREDITED_MESSAGE_CLASS_OR_CENSUS:{mid}')
                    continue
                if (ordinary_rows[mid]['organization_id'],ordinary_rows[mid]['conversation_id']) != (org,conv):
                    issues.append(f'INGRESS_SCOPE_MISMATCH:{mid}')
                if mid not in accepted:
                    issues.append(f'INGRESS_NOT_IN_ACCEPTANCE_LEDGER:{mid}')
                if conv not in pending:
                    counters[conv] = counters.get(conv,0)+1
                    ep = Episode(org,conv,counters[conv])
                    episodes.append(ep)
                    pending[conv] = ep
                    born_here.add(conv)
                ep = pending[conv]
                ep.members.append(mid)
                deadline = timestamp(event['available_at']) if event['available_at'] else None
                deadlines[mid] = deadline
                if len(ep.members) == 1:
                    ep.ready = Interval(max(commit.lo,deadline) if commit.lo is not None and deadline is not None else commit.lo,
                                        max(commit.hi,deadline) if commit.hi is not None and deadline is not None else commit.hi)
            elif event['event'] == 'deadline_set':
                ep = pending.get(conv)
                if not ep:
                    issues.append(f'DEADLINE_WITHOUT_POPULATION:{conv}')
                    continue
                deadline = timestamp(event['available_at']) if event['available_at'] else None
                for mid in ep.members:
                    deadlines[mid] = deadline
                if conv in born_here:
                    ep.ready = Interval(max(commit.lo,deadline) if deadline is not None and commit.lo is not None else commit.lo,
                                        max(commit.hi,deadline) if deadline is not None and commit.hi is not None else commit.hi)
                elif ep.ready.hi is not None and commit.lo is not None and ep.ready.hi <= commit.lo:
                    # C4/W1 monotonicity: later input must preserve the old origin.
                    if deadline is not None and deadline > ep.ready.hi:
                        ep.issues.append('READY_RETRACTED_BY_DEADLINE')
                elif ep.ready.lo is not None and commit.hi is not None and commit.hi < ep.ready.lo:
                    ep.ready = Interval(max(commit.lo,deadline) if deadline is not None and commit.lo is not None else commit.lo,
                                        max(commit.hi,deadline) if deadline is not None and commit.hi is not None else commit.hi)
                else:
                    ep.issues.append('READY_TRANSITION_OVERLAPS_COMMIT')
            elif event['event'] == 'claim_bound':
                if event['member_ids'] is None or event['turn_work_id'] in assigned:
                    existing=next((r for r in tx['context_rows'] if r['event']=='existing_work'),None)
                    due=(existing.get('lease_expires_at') if existing['status']=='PROCESSING'
                         else existing.get('next_attempt_at')) if existing else None
                    recovery.append({'turn_work_id':event['turn_work_id'],'attempts':event['attempts'],
                                     'organization_id':org,'commit_ns_bounds':commit.json(),
                                     'eligibility_source':'LEASE_EXPIRY' if existing and existing['status']=='PROCESSING'
                                         else 'RETRY_DUE' if existing else 'NOT_OBSERVED',
                                     'eligibility_db_ns':timestamp(due) if due else None,
                                     'recovery_bound_seconds':None})
                    continue
                ep = pending.get(conv)
                if not ep or ep.organization_id!=org or set(ep.members) != set(event['member_ids']):
                    issues.append(f'MEMBERSHIP_NOT_RECONCILED:{event["turn_work_id"]}')
                    continue
                ep.claim,ep.work_id = commit,event['turn_work_id']
                assigned[ep.work_id] = ep
                del pending[conv]
    represented = {mid for ep in episodes for mid in ep.members}
    all_member_ids=[mid for ep in episodes for mid in ep.members]
    if len(all_member_ids)!=len(represented):
        issues.append('INPUT_COUNTED_MORE_THAN_ONCE')
    missing = accepted-represented
    # A missing ingress origin remains an obligation. It cannot disappear.
    for mid in sorted(missing):
        row = ordinary_rows.get(mid)
        if row:
            counters[row['conversation_id']] = counters.get(row['conversation_id'],0)+1
            ep=Episode(row['organization_id'],row['conversation_id'],counters[row['conversation_id']],
                       members=[mid],issues=['ORIGIN_NOT_RECONSTRUCTED'])
            episodes.append(ep)
        issues.append(f'ACCEPTED_INPUT_ORIGIN_NOT_RECONSTRUCTED:{mid}')
    census_ids = set(ordinary_rows)
    if census_ids != accepted:
        issues.append('CENSUS_ACCEPTANCE_LEDGER_MISMATCH')
    if unknown:
        issues.append('UNRESOLVED_TRANSACTION_OUTCOMES')
    if any(o['outcome'] == 'UNCERTAIN' for o in offers):
        issues.append('UNRESOLVED_OFFER_OUTCOME')
    results = [ep.receipt(run_id,cut,bound_ns) for ep in episodes]
    backlog = {}
    organizations = sorted({ep.organization_id for ep in episodes}|{o['organization_id'] for o in offers if o.get('organization_id') is not None})
    if queue_cuts:
        counts = [queue_counts(episodes,Interval(*c)) for c in queue_cuts]
        full = [b[0]-a[1] >= bound_ns for a,b in zip(queue_cuts,queue_cuts[1:])]
        for org in organizations:
            backlog[str(org)] = backlog_disposition([c.get(org,[0,0]) for c in counts],full)
        backlog['global'] = backlog_disposition([[sum(c.get(o,[0,0])[i] for o in organizations) for i in (0,1)] for c in counts],full)
    summary = {kind:sum(r['disposition']==kind for r in results) for kind in
               ('OBSERVED_WITHIN_TARGET','OBSERVED_EXCESS','PENDING_CENSORED','NOT_YET_READY','INDETERMINATE','INVALID_EVIDENCE')}
    dispositions = []
    if issues or summary['INVALID_EVIDENCE']:
        dispositions.append('INDETERMINATE')
    if summary['OBSERVED_EXCESS']:
        dispositions.append('OBSERVED_INCOMPATIBLE_WITH_TARGET')
    if 'OBSERVED_BACKLOG_GROWTH' in backlog.values():
        dispositions.append('OBSERVED_BACKLOG_GROWTH')
    if any(summary[k] for k in ('PENDING_CENSORED','NOT_YET_READY','INDETERMINATE')) or 'INDETERMINATE' in backlog.values():
        dispositions.append('INDETERMINATE')
    # A cohort observation is not a level acceptance without workload, invariant,
    # cut-completeness and preparation evidence from the executing conductor.
    if not dispositions:
        level_complete = level_evidence and all(level_evidence.get(k) is True for k in
            ('plan_conformance','invariants_accredited','population_complete','queue_windows_complete'))
        if results and backlog and level_complete:
            dispositions.append('OBSERVED_COMPATIBLE')
        else:
            dispositions.append('COHORT_ONLY_NOT_LEVEL_ACCEPTANCE')
    return {'schema':'saaslyvet-d29-cohort-v1','run_id':run_id,'bound_seconds':bound_ns/NS,
            'clock_assumption':'SAME_HOST_CALIBRATION_AND_NO_UNOBSERVED_CLOCK_STEP',
            'cut_ns_bounds':cut.json(),'episodes':results,'summary':summary,
            'organization_counts':{str(o):sum(e.organization_id==o for e in episodes) for o in organizations},
            'population':{'offered_attempts':len(offers),'accepted_durable_inputs':len(accepted),
                          'represented_inputs':len(represented),'technical_duplicates':sum(o['outcome']=='DUPLICATE_CONFIRMED' for o in offers),
                          'unresolved_offers':sum(o['outcome']=='UNCERTAIN' for o in offers)},
            'recovery':recovery,'backlog':backlog,'issues':sorted(set(issues)),
            'uncertain_transactions':[dict(session_id=u['session_id'],transaction_id=u['transaction_id'],reason=u['reason']) for u in unknown],
            'dispositions':sorted(set(dispositions)),'contract_accepted':False,'sustainable_envelope':None}
