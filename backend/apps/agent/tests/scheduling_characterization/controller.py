"""D29 adaptive controller. Planning/replay never opens a database or emits load.

Use --help for commands. Live execution requires an explicit sealed plan,
--execute-load and an isolated executor. Product target and E are not inferred.
"""
import argparse
import hashlib
import json
import math
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path

from .recipes import RECIPES
from .runner import BASELINE, write_json

VERSION = 'D29-controller-v2'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def source_hashes():
    root = Path(__file__).parent
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob('*.py'))}


@dataclass(frozen=True)
class Parameters:
    initial_fraction: float = .5
    multiplier: float = 1.5
    bracket_fraction: float = .25
    screen_seconds: int = 360
    confirmation_seconds: int = 900
    confirmations: int = 3
    calibration_episodes_per_org: int = 10
    conversations_per_org: int = 3
    max_levels: int = 8
    max_refinements: int = 32
    followup_seconds: int = 240
    burst_multiplier: float = 2.
    burst_seconds: int = 120
    slow_multiplier: float = 2.
    blocked_llm_hold_seconds: int = 120

    def validate(self):
        for key, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError('Positive finite test parameter required: ' + key)
        for key in ('screen_seconds', 'confirmation_seconds', 'confirmations', 'calibration_episodes_per_org',
                    'conversations_per_org', 'max_levels', 'max_refinements', 'followup_seconds', 'burst_seconds',
                    'blocked_llm_hold_seconds'):
            if not isinstance(getattr(self, key), int):
                raise ValueError('Integer parameter required: ' + key)
        if not self.initial_fraction <= 1 or not self.bracket_fraction < 1 or not self.multiplier > 1:
            raise ValueError('Invalid adaptation factors')
        if self.screen_seconds < 360 or self.confirmation_seconds < self.screen_seconds:
            raise ValueError('Three full backlog windows required; confirmation cannot be shorter than screen')
        if self.burst_seconds > self.screen_seconds:
            raise ValueError('Burst must fit within the observation window')
        return self


def seal_plan(series_id, cases=None, *, parameters=None, reason=None, evidence=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', series_id):
        raise ValueError('Technical series ID required')
    params = (parameters or Parameters()).validate()
    selected = list(cases if cases is not None else RECIPES)
    if not selected or len(set(selected)) != len(selected) or any(c not in RECIPES for c in selected):
        raise ValueError('Unique known cases required')
    if any(RECIPES[c].prerequisites for c in selected) and 'R1-02' not in selected:
        raise ValueError('R1-02 confirmed balanced base is required by selected dependent cases')
    if 'R1-02' in selected and any(selected.index(c) < selected.index('R1-02') for c in selected if RECIPES[c].prerequisites):
        raise ValueError('Confirmed base must precede dependent cases')
    if params != Parameters() and (not reason or not evidence):
        raise ValueError('Prospective parameter changes require reason and evidence')
    root = Path(__file__).resolve().parents[5]
    protocol = root / 'docs/decisions/2026-10-05-scheduling-characterization-protocol.json'
    value = dict(schema='saaslyvet-d29-series-plan-v2', series_id=series_id, controller_version=VERSION,
                 baseline=BASELINE, protocol_version='D29-v1', protocol_sha256=hashlib.sha256(protocol.read_bytes()).hexdigest(),
                 source_hashes=source_hashes(), parameters=asdict(params), cases=selected,
                 adaptations=dict(reason=reason, evidence=evidence), bound_seconds=120,
                 sustainable_envelope=None, product_contract_accepted=False, load_authorized=False,
                 operational_defaults_status='INITIAL_ADAPTIVE_TEST_PLAN_NOT_PRODUCT_TERMS')
    value['plan_sha256'] = digest(value)
    return value


def validate_plan(plan):
    copy = deepcopy(plan)
    signature = copy.pop('plan_sha256', None)
    if signature != digest(copy):
        raise ValueError('Plan changed after sealing')
    expected = seal_plan(copy['series_id'], copy['cases'], parameters=Parameters(**copy['parameters']),
                         **copy['adaptations'])
    if expected != plan:
        raise ValueError('Plan source/protocol/target does not match this conductor')
    return Parameters(**copy['parameters']).validate()


class StopSeries(Exception):
    pass


class Controller:
    """Single-use ordered controller; each job is sealed and has a new run ID."""
    def __init__(self, plan, backend, output):
        self.parameters = validate_plan(plan)
        if hasattr(backend, 'preflight'):
            backend.preflight(plan)
        self.plan, self.backend, self.output = deepcopy(plan), backend, Path(output)
        self.jobs, self.references, self.confirmed = [], {}, {}
        self.finished_cases = []
        self.seen_runs = set()
        self.output.mkdir(parents=True, exist_ok=False)
        write_json(self.output / 'sealed-series-plan.json', plan)

    def job(self, case, phase, *, rates=None, variant=None, repetition=None):
        p = self.parameters
        serial = len(self.jobs) + 1
        run_id = f'{self.plan["series_id"]}-{serial:04d}'
        job = dict(schema='saaslyvet-d29-job-v2', run_id=run_id, baseline=BASELINE,
                   controller_version=VERSION, protocol_version='D29-v1', series_plan_sha256=self.plan['plan_sha256'],
                   source_hashes=self.plan['source_hashes'], case_id=case, phase=phase,
                   variant=variant or RECIPES[case].variants[0], organization_count=1 if case == 'R1-01' else 2,
                   offered_rates_per_minute=rates, repetition=repetition,
                   offer_seconds=p.confirmation_seconds if phase == 'CONFIRM' else p.screen_seconds,
                   calibration_episodes_per_org=p.calibration_episodes_per_org,
                   conversations_per_org=p.conversations_per_org, followup_seconds=p.followup_seconds,
                   burst_multiplier=p.burst_multiplier, burst_seconds=p.burst_seconds,
                   slow_multiplier=p.slow_multiplier, blocked_llm_hold_seconds=p.blocked_llm_hold_seconds,
                   boundary_case=case == 'R1-07', bound_seconds=120, fault_contract_coverage='PENDING')
        if case == 'R1-03':
            job['comparison_global_rate'] = sum(self.confirmed['R1-02']['rates'])
        job['job_sha256'] = digest(job)
        write_json(self.output / (run_id + '-plan.json'), job)
        try:
            receipt = self.backend.execute(deepcopy(job))
        except Exception as exc:
            receipt = dict(schema='saaslyvet-d29-job-error-v2', run_id=run_id, job_sha256=job['job_sha256'],
                           source_kind='EXECUTOR_ERROR', dispositions=['INVALID_RUN'], error_class=type(exc).__name__,
                           contract_accepted=False, sustainable_envelope=None)
        self.jobs.append(dict(plan=job, receipt=receipt))
        write_json(self.output / (run_id + '-receipt.json'), receipt)
        if receipt.get('run_id') != run_id or run_id in self.seen_runs or receipt.get('job_sha256') != job['job_sha256']:
            raise StopSeries('RECEIPT_ID_OR_SEALED_JOB_MISMATCH')
        self.seen_runs.add(run_id)
        expected_kind = 'SYNTHETIC_REPLAY' if self.backend.synthetic else 'ISOLATED_LIVE'
        if receipt.get('source_kind') != expected_kind:
            raise StopSeries('RECEIPT_PROVENANCE_MISMATCH')
        if receipt.get('contract_accepted') is not False or receipt.get('sustainable_envelope') is not None:
            raise StopSeries('EXECUTOR_CANNOT_APPROVE_PRODUCT_CONTRACT_OR_E')
        labels = receipt.get('model_dispositions' if self.backend.synthetic else 'dispositions', [])
        if any(s in labels for s in ('INVARIANT_FAILURE', 'INVALID_RUN', 'INDETERMINATE')):
            raise StopSeries('+'.join(labels))
        if phase == 'CALIBRATE':
            refs = receipt.get('calibration_reference_by_org_index')
            if labels != ['CALIBRATION_REFERENCE_OBSERVED'] or not isinstance(refs, list) or len(refs) != job['organization_count']:
                raise StopSeries('CALIBRATION_NOT_ACCREDITED')
            if any(isinstance(r, bool) or not isinstance(r, (int, float)) or not math.isfinite(r) or r <= 0 for r in refs):
                raise StopSeries('INVALID_CALIBRATION_REFERENCE')
            return refs
        if not labels or any(s not in ('OBSERVED_COMPATIBLE', 'OBSERVED_INCOMPATIBLE_WITH_TARGET',
                                       'OBSERVED_BACKLOG_GROWTH', 'FAULT_OBSERVATION_COMPLETE_COVERAGE_PENDING') for s in labels):
            raise StopSeries('JOB_NOT_EVALUATED_AS_LEVEL_OR_FAULT_OBSERVATION')
        return labels

    def search(self, case):
        p = self.parameters
        refs = self.job(case, 'CALIBRATE')
        self.references[case] = refs
        rate = min(refs) * p.initial_fraction
        compatible, upper = [], None
        for _ in range(p.max_levels):
            labels = self.job(case, 'SCREEN', rates=[rate] * len(refs))
            if labels == ['OBSERVED_COMPATIBLE']:
                compatible.append(rate)
                rate *= p.multiplier
            else:
                upper = rate
                break
        if not compatible:
            raise StopSeries('NO_COMPATIBLE_INITIAL_LEVEL:' + case)
        lower = compatible[-1]
        if upper is not None:
            for _ in range(p.max_refinements):
                if (upper - lower) / lower <= p.bracket_fraction:
                    break
                middle = (lower + upper) / 2
                labels = self.job(case, 'REFINE', rates=[middle] * len(refs))
                if labels == ['OBSERVED_COMPATIBLE']:
                    lower = middle
                    compatible.append(middle)
                else:
                    upper = middle
            else:
                if (upper - lower) / lower > p.bracket_fraction:
                    raise StopSeries('REFINEMENT_BUDGET_EXHAUSTED:' + case)
        # Each rejected confirmation starts a fresh set at the next lower
        # previously observed candidate. No successful repetition is reused.
        rejected = []
        for candidate in sorted(set(compatible), reverse=True):
            for repetition in range(1, p.confirmations + 1):
                labels = self.job(case, 'CONFIRM', rates=[candidate] * len(refs), repetition=repetition)
                if labels != ['OBSERVED_COMPATIBLE']:
                    rejected.append(candidate)
                    break
            else:
                result = dict(rates=[candidate] * len(refs), located_frontier=upper is not None,
                              bracket=[candidate, min(([upper] if upper is not None else []) + rejected, default=None)],
                              screening_bracket=[lower, upper], confirmation_rejected_rates=rejected,
                              refinement_rule_applies_to='SCREENING_BRACKET_NOT_A_UNIVERSAL_CAPACITY_BOUND',
                              confirmed_repetitions=p.confirmations,
                              finding='RANGE_OBSERVED_CONFIRMED_NOT_MAXIMUM_CAPACITY')
                self.confirmed[case] = result
                return result
        raise StopSeries('NO_CANDIDATE_SURVIVED_ALL_CONFIRMATIONS:' + case)

    def run(self):
        state, reason = 'CONTROLLER_COMPLETE', None
        try:
            for case in self.plan['cases']:
                if case in ('R1-01', 'R1-02'):
                    self.search(case)
                    self.finished_cases.append(case)
                    continue
                base = self.confirmed.get('R1-02')
                if not base:
                    raise StopSeries('CONFIRMED_BASE_NOT_AVAILABLE:' + case)
                rates = base['rates']
                if case == 'R1-03':
                    total = sum(rates)
                    rates = [total * 2 / 3, total / 3]
                for variant in RECIPES[case].variants:
                    self.job(case, 'SCENARIO', rates=rates, variant=variant)
                self.finished_cases.append(case)
        except StopSeries as exc:
            state, reason = 'CONTROLLER_STOPPED', str(exc)
        result = dict(schema='saaslyvet-d29-series-result-v2', series_id=self.plan['series_id'],
                      status=state, reason=reason, plan_sha256=self.plan['plan_sha256'],
                      source_kind='SYNTHETIC_REPLAY' if self.backend.synthetic else 'ISOLATED_LIVE',
                      jobs=len(self.jobs), completed_cases=self.finished_cases,
                      attempted_cases=sorted({j['plan']['case_id'] for j in self.jobs}),
                      confirmed=self.confirmed, references=self.references,
                      benchmark_executed=not self.backend.synthetic, contract_accepted=False,
                      sustainable_envelope=None, formal_sustainability_proven=False,
                      note='Replay validates controller decisions only; live observations do not approve contract or release.')
        write_json(self.output / 'series-result.json', result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    plan = sub.add_parser('plan', help='Seal a prospective plan; no DB or load')
    plan.add_argument('--series-id', required=True)
    plan.add_argument('--output', type=Path, required=True)
    plan.add_argument('--cases', nargs='+')
    plan.add_argument('--parameters', type=Path)
    plan.add_argument('--reason')
    plan.add_argument('--evidence')
    for name in ('replay', 'series'):
        command = sub.add_parser(name)
        command.add_argument('--plan', type=Path, required=True)
        command.add_argument('--output', type=Path, required=True)
        if name == 'series':
            command.add_argument('--execute-load', action='store_true')
            command.add_argument('--database-template', required=True)
    verify = sub.add_parser('verify-plan')
    verify.add_argument('--plan', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'plan':
        params = Parameters(**json.loads(args.parameters.read_text(encoding='utf-8'))) if args.parameters else None
        result = seal_plan(args.series_id, args.cases, parameters=params, reason=args.reason, evidence=args.evidence)
        write_json(args.output, result)
        print(json.dumps({'plan_sha256': result['plan_sha256'], 'cases': result['cases'], 'load_executed': False}))
        return
    sealed = json.loads(args.plan.read_text(encoding='utf-8'))
    validate_plan(sealed)
    if args.command == 'verify-plan':
        print(json.dumps({'status': 'PLAN_VALID', 'load_executed': False}))
        return
    if args.command == 'replay':
        from .replay import ReplayBackend
        backend = ReplayBackend()
    else:
        if not args.execute_load:
            parser.error('series requires explicit --execute-load; planning/replay are the default preparation tools')
        from .execution import LiveBackend
        backend = LiveBackend(args.database_template, args.output)
    result = Controller(sealed, backend, args.output).run()
    print(json.dumps(result))
    if result['status'] != 'CONTROLLER_COMPLETE':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
