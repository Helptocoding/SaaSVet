"""Prepared finite R2-04 prelude + immutable base-window alignment.

No entry point: this phase prepares infrastructure, not a new physical run.
The conductor must seal the proposed phase layout after user review.
"""
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

BASE_SHA = '71c3e58c34decfac1698f9517f39b4d7cbc936c0463e35a4bbfe00ee04920a56'


def base_plan(base_path):
    path = Path(base_path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != BASE_SHA:
        raise ValueError('IMMUTABLE_BASE_CHANGED')
    base = json.loads(path.read_text(encoding='utf-8'))
    p = base['configuration']['parameters']
    rates = base['confirmed_base']['rates']
    if base['base_status'] != 'CONFIRMED_BASE_ESTABLISHED' or len(rates) != 2:
        raise ValueError('ESTABLISHED_TWO_ORG_BASE_REQUIRED')
    cadence_ns = int(Decimal(60_000_000_000) / Decimal(str(rates[0])))
    return dict(case_id='R2-04', base_sha256=BASE_SHA, rates=rates,
                conversations_per_org=p['conversations_per_org'], planners=2, senders=1,
                offer_seconds=p['screen_seconds'], followup_seconds=p['followup_seconds'],
                prelude_inputs=1, prelude_conversation_slot=0,
                lead_to_natural_expiry_ns=cadence_ns,
                phase_layout='PRELUDE_CRASH_WAIT_THEN_UNCHANGED_BASE_WINDOW',
                status='PREPARED_REQUIRES_REVIEW_NOT_EXECUTED', accreditation=False)


def anchor_window(plan, lease_expires_db_ns):
    start = lease_expires_db_ns - plan['lead_to_natural_expiry_ns']
    return dict(start_db_ns=start, end_db_ns=start + plan['offer_seconds'] * 1_000_000_000,
                natural_expiry_db_ns=lease_expires_db_ns)


def prepare_prelude(session, base_path):
    """Future local fixture only. Reuses the already accredited crash primitive.

    The crash child occupies one planner slot; no base-loop workers run yet.
    Once its OS/backend exit is proved, it may be replaced, not supplemented.
    Initial input uses slot 0 within the same three-conversation population.
    """
    from apps.agent.tests.scheduling_characterization.physical_cases import crash_committed
    from apps.agent.tests.scheduling_characterization.runner import write_json
    from apps.agent.tests.scheduling_characterization.evidence import timestamp

    plan = base_plan(base_path)
    if len(session.fixtures) != 2 or session.case != 'R2-04':
        raise ValueError('R204_TWO_ORG_ISOLATED_SESSION_REQUIRED')
    row, witness, old, snapshot, snapshot_file = crash_committed(session)
    session.event('outer_commit', [snapshot_file, 'crash.jsonl'])
    exit_file = session.kill('crash')
    session.event('postcommit_crash', [exit_file], source='PROCESS_EXIT')
    expiry = timestamp(old['lease_expires_at'])
    anchor = anchor_window(plan, expiry)
    value = dict(plan=plan, window=anchor, work_id=witness.turn_work_id, message_id=row.pk,
                 committed_snapshot=snapshot_file, crash_exit=exit_file,
                 base_offer_started=False, status='PRELUDE_ONLY_NOT_ACCREDITED')
    write_json(session.directory / 'reclaim-base-preparation.json', value)
    return value, witness, old


def wait_offer_start(preparation):
    """Natural wall time only; conductor clock/host guards must surround this."""
    from apps.agent.tests.scheduling_characterization.physical import wait_db
    at = preparation['window']['start_db_ns']
    seconds, nanos = divmod(at, 1_000_000_000)
    when = datetime.fromtimestamp(seconds, tz=timezone.utc).replace(microsecond=nanos // 1000)
    wait_db(when.isoformat())


def verify_overlap(window, reclaim_commit_bounds, offers, organization_ids, prelude_message_id):
    """Additional overlap gate for actual interval witnesses, not a calendar.

    window.begin_cut/end_cut are independent DB phase snapshots. In particular,
    the output of anchor_window is NOT this input and fails the gate.
    Caller also needs the unchanged physical reclaim, clock, complete demand,
    pacing, concurrency, ownership, age, terminal and cleanup verifiers.
    A returned pass never accredits R2-04 by itself.
    """
    issues = []
    if 'begin_cut' not in window or 'end_cut' not in window:
        return dict(passed=False, issues=['OBSERVED_BASE_WINDOW_CUTS_MISSING'], accreditation=False)
    lo, hi = reclaim_commit_bounds
    start, end, expiry = window['begin_cut']['db_ns'], window['end_cut']['db_ns'], window['natural_expiry_db_ns']
    if lo is None or hi is None or not start <= expiry <= lo <= hi < end:
        issues.append('RECLAIM_NOT_NATURALLY_DUE_INSIDE_BASE_WINDOW')
    accepted = [o for o in offers if o.get('outcome') == 'ACCEPTED_DURABLE' and o.get('phase') == 'ORDINARY']
    ids = [o.get('message_id') for o in accepted]
    if not ids or None in ids or len(set(ids)) != len(ids) or prelude_message_id in ids:
        issues.append('BASE_AND_PRELUDE_NOT_RECONCILED')
    if any(o['organization_id'] not in organization_ids for o in accepted):
        issues.append('UNDECLARED_ORGANIZATION')
    if lo is not None and hi is not None:
        for org in organization_ids:
            rows = [o for o in accepted if o['organization_id'] == org]
            before = [o for o in rows if start <= o['offered_db_ns_bounds'][0] <= o['offered_db_ns_bounds'][1] < lo]
            after = [o for o in rows if hi < o['offered_db_ns_bounds'][0] <= o['offered_db_ns_bounds'][1] < end]
            if not before or not after:
                issues.append('ACTUAL_BASE_ACCEPTANCES_DO_NOT_BRACKET_RECLAIM:' + str(org))
    return dict(passed=not issues, issues=issues, accreditation=False,
                scope='ADDITIONAL_RECLAIM_BASE_OVERLAP_GATE', actual_base_acceptances=len(accepted))
