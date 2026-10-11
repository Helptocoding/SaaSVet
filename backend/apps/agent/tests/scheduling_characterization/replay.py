"""Finite virtual-clock accreditation fixtures. Never opens Django or PostgreSQL.

These are invented test histories, explicitly labelled SYNTHETIC_REPLAY.
They exercise the conductor's rules, not runtime capacity or fault handling.
"""
from collections import defaultdict
import math
from datetime import datetime, timezone
from fractions import Fraction

from .assessment import assess
from .evidence import NS, Episode, Interval, queue_counts, reconstruct
from .recipes import RECIPES, required_transitions, verify_recipe

ORIGIN = 1_800_000_000 * NS


def iso(ns):
    return datetime.fromtimestamp(ns / NS, tz=timezone.utc).isoformat()


def schedule(job, start=0):
    """Half-open pacing slots, with prospective burst changes and no catch-up."""
    slots = []
    end = start + job['offer_seconds'] * NS
    for org, rate in enumerate(job['offered_rates_per_minute']):
        due, serial = Fraction(start), 0
        burst_org = job['case_id'] == 'R1-05' and (job['variant'] == 'simultaneous' or org == 0)
        burst_end = start + job['burst_seconds'] * NS
        while due < end:
            multiplier = job['burst_multiplier'] if burst_org and due < burst_end else 1
            following = due + max(Fraction(1), Fraction(60 * NS) / (Fraction(str(rate)) * Fraction(str(multiplier))))
            if burst_org and due < burst_end < following:
                following = burst_end
            rounded_due = math.ceil(due)
            if rounded_due >= end:
                break
            slots.append(dict(id=f'{org}:{serial}', organization_index=org,
                              due_monotonic_ns=rounded_due, end_monotonic_ns=min(math.ceil(following), end)))
            due, serial = following, serial + 1
            if serial > 1_000_000:
                raise ValueError('Fixture schedule exceeds bounded test population')
    return sorted(slots, key=lambda s: (s['due_monotonic_ns'], s['organization_index']))


def recipe_fixture(job):
    events = []
    now = ORIGIN
    for event in required_transitions(job['case_id'], job['variant']):
        if event == 'block_release':
            now += job['blocked_llm_hold_seconds'] * NS
        elif event == 'burst_end':
            now += job['burst_seconds'] * NS
        else:
            now += NS
        row = dict(event=event, run_id=job['run_id'], organization_index=0,
                   db_ns=now, observed=True, source='REPLAY')
        if event in ('natural_expiry', 'natural_retry_due'):
            row.update(due_db_ns=now, runtime_clock_or_deadline_changed=False)
        if event in ('same_work_reclaimed', 'same_work_retry', 'history_preserved'):
            row.update(same_work_and_membership=True, budget_reset=False)
        if event == 'old_witness_fenced':
            row['effect_published'] = False
        if event == 'retry_terminal':
            row['attempts_exhausted'] = job['variant'] == 'exhaustion'
        if event == 'meta_result':
            row['result'] = 'UNCERTAIN' if job['variant'] == 'uncertain_meta' else 'ACCEPTED'
        events.append(row)
    return events


def level_fixture(job, *, excess=False, pending=False, coalesced=False, clock_error=False):
    slots = schedule(job)
    journals, offers, census, works, wire = [], [], [], [], []
    organizations = list(range(1, job['organization_count'] + 1))
    serial = 0
    for org in organizations:
        rows = [dict(event='db_clock', run_id=job['run_id'], session_id=f's{org}', transaction_id=None,
                     monotonic_ns=0, start_ns=0, end_ns=0, db_timestamp=iso(ORIGIN), savepoint_ids=[])]
        for slot in [s for s in slots if s['organization_index'] == org - 1]:
            serial += 1
            mid, conv, work = serial, serial, serial
            at = slot['due_monotonic_ns'] + 1_000_000
            ready = ORIGIN + at
            common = dict(run_id=job['run_id'], session_id=f's{org}', savepoint_ids=[],
                          organization_id=org, conversation_id=conv)
            rows.extend([
                dict(event='message_persisted', monotonic_ns=at, transaction_id=f'i{mid}', message_id=mid,
                     available_at=iso(ready), **common),
                dict(event='commit_end', monotonic_ns=at, transaction_id=f'i{mid}', execute_start_ns=at,
                     execute_end_ns=at, error_class=None, **common)])
            offer = dict(schedule_id=slot['id'], organization_id=org, outcome='ACCEPTED_DURABLE', message_id=mid,
                         started_monotonic_ns=at, phase='ORDINARY')
            offers.append(offer)
            item = dict(id=mid, organization_id=org, conversation_id=conv, semantic_type='', direction='in', turn_work_id=work)
            census.append(item)
            if pending and serial == 1:
                item['turn_work_id'] = None
                continue
            claim = at + (121 if excess and serial == 1 else 1) * NS
            rows.extend([
                dict(event='claim_bound', monotonic_ns=claim, transaction_id=f'c{mid}', turn_work_id=work,
                     member_ids=[mid], epoch=0, lease_fingerprint=f'fp{work}', attempts=1, **common),
                dict(event='commit_end', monotonic_ns=claim, transaction_id=f'c{mid}', execute_start_ns=claim,
                     execute_end_ns=claim, error_class=None, **common)])
            works.append(dict(id=work, organization_id=org, conversation_id=conv))
            wire.append(dict(boundary='llm', organization_id=org, turn_work_id=work, epoch=0,
                             lease_fingerprint=f'fp{work}', db_ns=ORIGIN + claim + NS, external_destination=False,
                             in_atomic=False, admission_verified=True, active_org_work=1, matching_active_work=True))
        journals.append(rows)
    end = ORIGIN + (job['offer_seconds'] + job['followup_seconds']) * NS
    report = reconstruct(journals, offers, census, Interval(end, end), run_id=job['run_id'])
    if coalesced and len(report['episodes']) > 1:
        first, second = report['episodes'][:2]
        first['member_ids'] += second['member_ids']
        report['episodes'].remove(second)
    if clock_error:
        report['issues'].append('INVALID_CLOCK_RELATION')
    eps = [Episode(e['organization_id'], e['conversation_id'], 1, members=e['member_ids'],
                   ready=Interval(*e['ready_ns_bounds']),
                   claim=Interval(*e['claim_commit_ns_bounds']) if e['claim_commit_ns_bounds'] else None)
           for e in report['episodes']]
    offsets = list(range(0, job['offer_seconds'] + 1, 120))
    if offsets[-1] != job['offer_seconds']:
        offsets.append(job['offer_seconds'])
    queues = []
    for offset in offsets:
        cut = ORIGIN + offset * NS
        counts = queue_counts(eps, Interval(cut, cut))
        scopes = {str(o): counts.get(o, [0, 0]) for o in organizations}
        scopes['global'] = [sum(scopes[str(o)][i] for o in organizations) for i in (0, 1)]
        queues.append(dict(offset_seconds=offset, counts=scopes, correlated_clock=True))
    preparation = {k: True for k in ('fresh_database', 'participants_ready_before_offer', 'source_integrity',
                                      'capture_all_participants', 'durable_database', 'contained_provider')}
    events = recipe_fixture(job)
    result = assess(job, report, offers=offers, scheduled=slots, organizations=organizations,
                    offer_span=(ORIGIN, ORIGIN + job['offer_seconds'] * NS), queue_samples=queues,
                    journals=journals, census=census, works=works, wire=wire, preparation=preparation,
                    recipe=verify_recipe(job, events), synthetic=True)
    result.update(job_sha256=job['job_sha256'], scenario_events=events)
    return result


class ReplayBackend:
    synthetic = True

    def __init__(self, *, threshold=6.4, confirmation_failures=None, indeterminate_at=None):
        self.threshold = threshold
        self.confirmation_failures = confirmation_failures or set()
        self.indeterminate_at = indeterminate_at
        self.calls = []

    def execute(self, job):
        self.calls.append(job)
        if job['phase'] == 'CALIBRATE':
            return dict(run_id=job['run_id'], job_sha256=job['job_sha256'], source_kind='SYNTHETIC_REPLAY',
                        dispositions=['SYNTHETIC_REPLAY_NOT_LOAD_ACCEPTANCE'],
                        model_dispositions=['CALIBRATION_REFERENCE_OBSERVED'],
                        calibration_reference_by_org_index=[12.] * job['organization_count'],
                        contract_accepted=False, sustainable_envelope=None)
        excess = (job['case_id'] in ('R1-01', 'R1-02') and max(job['offered_rates_per_minute']) > self.threshold)
        key = (job['case_id'], job['offered_rates_per_minute'][0], job['repetition'])
        if key in self.confirmation_failures:
            excess = True
        return level_fixture(job, excess=excess, clock_error=len(self.calls) == self.indeterminate_at)
