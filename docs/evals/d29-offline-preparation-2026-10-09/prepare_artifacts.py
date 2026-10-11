"""Produce reviewable offline plans/receipts only. No live entry points."""
import json
from pathlib import Path

from common import BASE, BASE_HASH, BASELINE, HERE, PRIOR, ROOT, read, save, sha, utc
from r104_temporal import analysis
from r106_verifier import POLICY, verify_directory
from r209_preparation import plan, validate_plan


def main():
    # Every offline preparation attempt is preserved, including old seals.
    suffix='' if not (HERE/'r106-prospective-policy.json').exists() else '-v2'
    save('r106-prospective-policy'+suffix+'.json',{
        'policy':POLICY,'at_utc':utc(),'prospective_only':True,'execution_authorized':False,
        'verifier':{'path':'r106_verifier.py','sha256':sha(HERE/'r106_verifier.py')},
        'confirmed_base_reference':{'path':str(BASE),'sha256':BASE_HASH},
        'population':{'backlog':'2X4_ONLY','ordinary':'2X3_UNCHANGED_GLOBAL_ROTATION'},
        'unit':'CONTINUOUS_ORDINARY_READY_EPISODE','bound_seconds':120,
        'coalescing':'COMPLETE_INPUT_MEMBERSHIP_WITHOUT_ORIGIN_RESET',
        'deferral':'NATIVE_GUARD_AND_OUTER_COMMIT_PLUS_SAME_SCOPE_SUCCESSOR_WITH_PRIOR_INPUTS_ACTUALLY_CONSUMED',
        'response_acceptance':'ONE_TO_ONE_META_DISPATCH_RESULT_OUTBOX_ACCEPTED_KNOWN',
        'new_capture_events':{
            'new_input_guard':{'boundary':'native has_new_input evaluation inside locked finalize transaction',
                               'required':['work/org/conversation/epoch/fingerprint','native boolean','actual triggering input IDs with source cursor','raw transaction/session/seq','native monotonic time'],
                               'later_query_allowed':False},
            'work_terminal':{'boundary':'successful native terminal CAS inside same finalize transaction',
                             'required':['same work authority','outcome_code','CAS affected=1','outer commit raw journal'],
                             'snapshot_alone_allowed':False},
            'context_consumed':{'boundary':'actual immutable member/context + packed history consumed before successor first LLM',
                                'required':['work/org/conversation/epoch/fingerprint','actual consumed input IDs','phase BEFORE_FIRST_LLM','history/member cursor','raw session/seq/time'],
                                'available_in_history_query_alone_allowed':False}},
        'no_historical_pass':True,'production_changes':False,
        'pending_capture_integration':'No live observer installed. These passive native-boundary witnesses must be wired into a future evaluation-only worker before repeating if deferral occurs.'})
    historical=PRIOR/'r1-06/authorized-r106-2x4-20261007-0002'
    audit=verify_directory(historical)
    save('r106-historical-read-only-audit'+suffix+'.json',audit)
    save('r104-temporal-analysis'+suffix+'.json',analysis())
    validations={}
    for variant in ('uncertain_meta','slow_meta'):
        proposed=plan(variant)
        if not (HERE/('r209-'+variant+'-prepared-plan.json')).exists():save('r209-'+variant+'-prepared-plan.json',proposed)
        validations[variant]=validate_plan(proposed)
    save('r209-plan-validation'+suffix+'.json',validations)
    suite_script=ROOT/'docs/evals/d29-physical-2026-10-06/orchestration-current/app_regression.py'
    labels=['test_b4_sender','test_w1_monotonic','test_b5_safety','test_operation_execution',
            'test_b9b_budget','test_b9c_concurrency','test_b9c_processes']
    jobs=[]
    for ordinal,label in enumerate(labels,1):
        jobs.append({'ordinal':ordinal,'label':'apps.agent.tests.'+label,'status':'PENDING_EXPLICIT_EXECUTION_AUTHORIZATION',
                     'database_name_template':'test_d29_offlineprep_'+label.removeprefix('test_')+'_<unique_attempt>',
                     'database_creation':'NEW_PRIVATE_DB_FROM_UNCHANGED_BASELINE_TEMPLATE_AT_EXECUTION_ONLY',
                     'argv':['rtk','proxy','<private-lab-python>','-B','-X','utf8',str(suite_script)],
                     'working_directory':'<baseline-private-copy>/backend',
                     'environment_from':'NEW_PRIVATE_LAB_SESSION_NOT_PRODUCTION',
                     'extra_env':{'D29_REGRESSION_LABELS':json.dumps(['apps.agent.tests.'+label]),
                                  'D29_REGRESSION_OUTPUT':'<new-attempt-dir>/'+label+'.json'},
                     'before':['verify previous suite and cleanup completed','capture host resources and job limits',
                               'capture private pg_stat_activity + database configuration + pg log watermark','record process identities and ancestry'],
                     'during':['capture private process and connection resource timeline','retain unfiltered suite and PostgreSQL logs',
                               'on OOM stop sequencing and preserve private state before controlled cleanup'],
                     'after':['record suite tests/failures/errors/skips/exit even on failure','final resources/connections/pg logs',
                              'verify no owned suite child remains','archive technical evidence before removing only owned private DB',
                              'verify database absence and source integrity']})
    if not (HERE/'regression-sequential-plan.json').exists():save('regression-sequential-plan.json',{
        'schema':'D29_SEQUENTIAL_REGRESSION_OFFLINE_PLAN_V1','at_utc':utc(),'execution_authorized':False,
        'baseline':BASELINE,'suite_script':{'path':str(suite_script),'sha256':sha(suite_script)},
        'sequence':jobs,'max_simultaneous_suites':1,'new_private_database_per_suite':True,
        'no_live_probe_overlap':True,'on_oom':'STOP_PRESERVE_DIAGNOSE_NO_AUTO_RESTART',
        'on_other_failure':'STOP_AND_REPORT_NO_SILENT_OMISSION','change_tests':False,'memory_increase':False,
        'postgres_tuning':False,'retained_existing_evidence':{'D29':'78 distinct tests passed','B3':'39 tests passed'},
        'new_lab_created_now':False,'suites_executed_now':False,
        'preconditions':['separate human authorization','fresh private cluster with baseline durability settings',
                         'resource monitoring works before starting any suite','no unexpected private clients',
                         'all old receipts and failures sealed','owned-process cleanup and interruption path available'],
        'note':'The old concurrent runner is not invoked. The existing single-suite script and tests remain byte-identical; orchestration is one suite then complete cleanup.'})
    print(json.dumps({'historical_r106_status':audit['status'],'historical_r106_new_gate_errors':audit['errors'],
                      'r209_plan_validation':validations,'r104_status':analysis()['status'],'regression_suites_prepared':len(jobs)}))


if __name__=='__main__':main()
