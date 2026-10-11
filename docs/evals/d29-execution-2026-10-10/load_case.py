"""Fixed physical accreditation jobs consuming an immutable accepted base.

No adaptive search or base producer. Calendar helpers only plan real offers;
independent verification uses the actual ingress ledger and raw journals.
"""
import argparse
import hashlib
import json
import math
import time
from pathlib import Path
from unittest.mock import patch

from apps.agent.tests.scheduling_characterization import execution
from apps.agent.tests.scheduling_characterization.controller import digest
from apps.agent.tests.scheduling_characterization.evidence import NS, timestamp
from apps.agent.tests.scheduling_characterization.runner import bootstrap, write_json
from apps.agent.tests.scheduling_characterization.replay import schedule as plan_calendar
from apps.agent.tests.scheduling_characterization.scenario_observations import observations as prior_observations


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_base(reference):
    path = Path(reference['path'])
    if sha(path) != reference['sha256']:
        raise ValueError('Accepted base receipt hash changed')
    value = read(path)
    if value['base_status'] != 'CONFIRMED_BASE_ESTABLISHED' or value['baseline'] != execution.BASELINE:
        raise ValueError('Accepted established base required')
    if value['confirmed_base']['confirmed_repetitions'] != 3:
        raise ValueError('Accepted physical confirmations required')
    verification = value['physical_verification']
    if sha(path.parent / verification['path']) != verification['sha256'] or not read(path.parent / verification['path'])['established']:
        raise ValueError('Physical base verification changed')
    for rel, entry in read(path.parent / 'artifact-index.json').items():
        if sha(path.parent / rel) != entry['sha256']:
            raise ValueError('Accepted base artifact changed: ' + rel)
    return value


def common_calendar(job, start=0):
    """Exact balanced-base global instants, reassigned in a 2:1 cycle."""
    balanced = dict(job, case_id='R1-02', offered_rates_per_minute=job['confirmed_base_rates'])
    slots = plan_calendar(balanced, start)
    counts = [0, 0]
    for index, slot in enumerate(slots):
        org = (0, 0, 1)[index % 3]
        slot['organization_index'] = org
        slot['id'] = str(org) + ':' + str(counts[org])
        counts[org] += 1
    return slots


def run(job_path, output):
    job = read(job_path)
    unsigned = dict(job)
    seal = unsigned.pop('job_sha256')
    if seal != digest(unsigned) or job['phase'] != 'ACCREDITATION_SCENARIO':
        raise ValueError('Sealed fixed accreditation job required')
    base = validate_base(job['confirmed_base_reference'])
    p = base['configuration']['parameters']
    for key in ('conversations_per_org', 'followup_seconds', 'burst_multiplier', 'burst_seconds', 'slow_multiplier', 'blocked_llm_hold_seconds'):
        if job[key] != p[key] and not (job['case_id'] == 'R1-06' and key == 'conversations_per_org' and job.get('scenario_population') == 'R1-06_OPTION_B_2X4'):
            raise ValueError('Accepted base parameter changed: ' + key)
    if job['offer_seconds'] != p['screen_seconds'] or job['confirmed_base_rates'] != base['confirmed_base']['rates']:
        raise ValueError('Base rates/scenario window changed')
    expected = base['confirmed_base']['rates']
    if job['case_id'] == 'R1-03':
        expected = [sum(expected) * 2 / 3, sum(expected) / 3]
    if job['offered_rates_per_minute'] != expected:
        raise ValueError('Unauthorized rate change')
    directory = Path(output)
    original_offer = execution.offer
    observed_phases = []
    rotation = {}

    def observe_offer(recorder, fixture, slot, schedule_slot=None, phase='ORDINARY'):
        if job['case_id'] == 'R1-03':
            org = schedule_slot['organization_index']
            ordinal = rotation.get(org, 0)
            rotation[org] = ordinal + 1
            # Preserve the base's three-slot per-organization rotation even
            # after global slots are reassigned to the unequal organizations.
            slot = (ordinal * 2 + org) % job['conversations_per_org']
        # Natural snapshots are taken before the first offer of each actual
        # burst/return phase. The actual ledger remains the pacing authority.
        if job['case_id'] == 'R1-05' and schedule_slot is not None:
            start = read(directory / 'schedule.json')[0]['due_monotonic_ns']
            kind = 'burst' if schedule_slot['due_monotonic_ns'] < start + job['burst_seconds'] * NS and (
                job['variant'] == 'simultaneous' or schedule_slot['organization_index'] == 0) else 'base-return'
            if kind not in observed_phases and (kind == 'burst' or time.perf_counter_ns() >= start + job['burst_seconds'] * NS):
                cut = recorder.snapshot('physical-' + kind)
                observed_phases.append(kind)
                execution.append(directory / 'physical-phases.jsonl', dict(phase=kind,
                    db_ns=cut['db_ns'], monotonic_ns=time.perf_counter_ns(), snapshot_stage=cut['stage']))
        return original_offer(recorder, fixture, slot, schedule_slot, phase)

    def truthful_observations(augmented, report, journals, wire, read_lines, folder, final):
        if job['case_id'] == 'R1-04':
            # A later census + claim miss is never evidence of selector yield
            # or a forecast which was later superseded. Retain missing causal
            # witnesses rather than promoting that old observer to accreditation.
            return []
        events = prior_observations(augmented, report, journals, wire, read_lines, folder, final)
        if job['case_id'] == 'R1-05':
            phases = read_lines(folder / 'physical-phases.jsonl')
            first = next((r for r in phases if r['phase'] == 'burst'), None)
            returned = next((r for r in phases if r['phase'] == 'base-return'), None)
            events = []
            for name, row in [('burst_begin', first), ('burst_end', returned), ('base_return', returned), ('drain_cut', final)]:
                if row:
                    events.append(dict(event=name, run_id=job['run_id'], organization_index=0,
                        db_ns=row['db_ns'], observed=True, source='INDEPENDENT_DB_WITNESS',
                        evidence='snapshots.jsonl', actual_boundary=True))
        return events

    error = None
    result = None
    try:
        from apps.agent.tests.scheduling_characterization import scenario_observations
        with patch.object(execution, 'schedule', common_calendar if job['case_id'] == 'R1-03' else plan_calendar), \
                patch.object(execution, 'offer', observe_offer), \
                patch.object(scenario_observations, 'observations', truthful_observations):
            result = execution.execute_job(directory, job)
    except Exception as exc:
        error = dict(exception_class=type(exc).__name__, message=str(exc), kind='PHYSICAL_SCENARIO_NOT_ACCREDITED')
        directory.mkdir(parents=True, exist_ok=True)
    receipt = dict(schema='d29-fixed-base-executor-v1', run_id=job['run_id'], case_id=job['case_id'], variant=job['variant'],
        job_sha256=seal, confirmed_base_reference=job['confirmed_base_reference'],
        error=error, executor_dispositions=result.get('dispositions') if result else None,
        synthetic_evidence=[], physical_evidence='RAW_INGRESS_JOURNALS_SNAPSHOTS_WIRE',
        base_recalibrated=False, new_base_generated=False, characterization=False,
        maximum_capacity=None, sustainable_envelope=None, commercial_capacity=None,
        status='OBSERVED_PENDING_INDEPENDENT_VERIFICATION' if result else 'NOT_ACCREDITED')
    if job['case_id'] == 'R1-06' and error:
        receipt['population_conflict'] = dict(required_distinct_conversations_by_org=[math.ceil(r * 2) for r in job['confirmed_base_rates']],
            accepted_conversations_per_org=job['conversations_per_org'], base_population_changed=False)
    write_json(directory / 'dependent-executor-receipt.json', receipt)
    print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    run(args.job, args.output)
