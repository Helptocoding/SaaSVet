"""Seal only this offline phase; verify preserved sources and evidence."""
import json
from pathlib import Path
import tempfile

from common import BASE, BASE_HASH, HERE, PRIOR, ROOT, check_integrity, read, save, sha, utc
from read_only_diagnostic import command, memory_and_processes, tcp_snapshot


def prior_indexes():
    checked=[]
    folders=('d29-r102-base-2026-10-07','d29-authorized-probes-2026-10-07',
             'd29-physical-2026-10-06','d29-frontiers-2026-10-07','d29-dependent-2026-10-07',
             'd29-gap-preparation-2026-10-07','d29-methodology-provider-2026-10-07')
    for folder in folders:
        directory=ROOT/'docs/evals'/folder
        candidates=list(directory.glob('artifact-index*.json'))
        if not candidates:
            checked.append({'folder':folder,'index_available':False})
            continue
        def version(p):
            tail=p.stem.removeprefix('artifact-index').removeprefix('-v')
            return int(tail) if tail.isdigit() else 1
        index=max(candidates,key=version)
        entries=read(index)
        mismatches=[];n=0
        for rel,entry in entries.items():
            if not isinstance(entry,dict) or 'sha256' not in entry:
                raise ValueError('Unsupported prior index schema: '+str(index))
            target=(directory/rel).resolve()
            if not target.is_relative_to(directory.resolve()):raise ValueError('Index path outside evidence directory')
            n+=1
            if not target.is_file() or sha(target)!=entry['sha256']:mismatches.append(rel)
        checked.append({'folder':folder,'index_available':True,'index':index.name,'index_sha256':sha(index),
                        'artifacts_checked':n,'mismatches':mismatches,'unchanged':not mismatches})
    return checked


def main():
    integrity=check_integrity()
    integrity['prior_evidence_indexes']=prior_indexes()
    proposal=ROOT/'docs/evals/d29-propuestas-cierre-2026-10-09.md'
    integrity['prior_proposal']={'sha256':sha(proposal),'expected':'acc47b690e8b49877b7ca9bee5742baa89c6924b90def3a8dff9b13c0c280e60'}
    integrity['all_available_evidence_unchanged']=all(x['unchanged'] for x in integrity['prior_evidence_indexes'] if x['index_available'])
    integrity['valid']=integrity['valid'] and integrity['all_available_evidence_unchanged'] and integrity['prior_proposal']['sha256']==integrity['prior_proposal']['expected']
    save('final-integrity.json',integrity)
    memory,processes,limits=memory_and_processes()
    service=command(['powershell','-NoProfile','-Command','Get-Service -Name W32Time | Select-Object Name,Status,StartType | ConvertTo-Json -Compress'])
    owned=[p for p in processes if any(m in p['owned_markers'] for m in ('vet-d29-authorized-20261007-','run_regression_v2.py'))]
    cleanup={'at_utc':utc(),'diagnosis_only':True,'owned_historical_workers_remaining':owned,
             'connections':tcp_snapshot(processes),'W32Time_after':service,
             'lab_paths':[{'name':n,'exists':(Path(tempfile.gettempdir())/n).exists()} for n in
                          ('vet-d29-authorized-20261007-03e5n2jy','vet-d29-authorized-20261007-l8icq_3c')],
             'private_databases_created':0,'service_mutations':0,'cleanup_operations_needed':False,
             'no_foreign_process_intervention':True}
    save('final-read-only-cleanup.json',cleanup)
    tests=read(HERE/'preparation-tests-attempt-03.json')
    checksums={p.name:sha(p) for p in HERE.glob('*.py')}
    receipt={'schema':'D29_OFFLINE_PREPARATION_FINAL_RECEIPT_V1','at_utc':utc(),
             'global_status':'CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY',
             'base_status':'CONFIRMED_BASE_ESTABLISHED','base_sha256':sha(BASE),'base_unchanged':sha(BASE)==BASE_HASH,
             'scope':'PREPARATION_AND_OFFLINE_VALIDATION_ONLY','execution_authorized':False,
             'P01':'VERIFIER_OFFLINE_VALIDATED_PROSPECTIVE_CAPTURE_INTEGRATION_PENDING',
             'P02':'READ_ONLY_DIAGNOSIS_DONE_SERVICE_CONTROL_ACCESS_DENIED_RECOVERY_NOT_INSTALLED',
             'P03':'PENDING_NO_DEMONSTRABLE_PHYSICAL_WINDOW',
             'P04':{'uncertain_meta':'OFFLINE_PREPARED_NOT_EXECUTED','slow_meta':'OFFLINE_PREPARED_NOT_EXECUTED'},
             'P05':'ROOT_CAUSE_UNDETERMINED_SEVEN_SEQUENTIAL_SUITES_PREPARED_NOT_EXECUTED',
             'validation':{'receipt':'preparation-tests-attempt-03.json','sha256':sha(HERE/'preparation-tests-attempt-03.json'),
                           'tests':tests['tests'],'passed':tests['passed'],'source_kind':tests['source_kind']},
             'evidence_separation':{'physical_frontier':'NO_NEW_PHYSICAL_ACCREDITATION',
                                    'load_condition':'NO_NEW_PHYSICAL_LOAD_EXECUTED','confirmed_base':'ESTABLISHED_UNCHANGED',
                                    'pending_prerequisites':['R106 causal capture integration','R104 phase/latency bounds',
                                                            'W32Time safe restoration access and independent recovery','R209 launch bridge and complete physical gates'],
                                    'synthetic':'ONLY_OFFLINE_NEGATIVE_CONTROLS_AND_CONDITIONAL_INTERVAL_MODELS',
                                    'physical':'READ_ONLY_HOST_DIAGNOSTICS_AND_PRESERVED_RAW_CAPTURE_AUDIT_ONLY'},
             'original_invariants_and_bounds_unchanged':True,'physical_probes_executed':0,'application_suites_executed':0,
             'matrices_executed':0,'W32Time_stop_calls':0,'provider_parameter_changes':False,'production_changes':False,
             'contract_changes':False,'commits':0,'E':None,'maximum_capacity':None,'commercial_capacity':None,
             'source_sha256':checksums,'integrity_receipt':'final-integrity.json','integrity_valid':integrity['valid'],
             'preserved_earlier_offline_receipts':True,'final_policy':'r106-prospective-policy-v2.json',
             'final_temporal_analysis':'r104-temporal-analysis-v2.json','final_r209_plan_validation':'r209-plan-validation-v2.json',
             'stop_after_review_delivery':True}
    save('final-phase-receipt.json',receipt)
    index={str(p.relative_to(HERE)).replace('\\','/'):{'sha256':sha(p),'bytes':p.stat().st_size}
           for p in sorted(HERE.rglob('*')) if p.is_file() and p.name!='artifact-index.json'}
    save('artifact-index.json',index)
    print(json.dumps({'integrity_valid':integrity['valid'],'protected_sources':integrity['protected_sources_checked'],
                      'prior_indexes':integrity['prior_evidence_indexes'],'offline_tests':tests['tests'],
                      'new_phase_artifacts':len(index),'owned_workers_remaining':owned,'service_after':service},ensure_ascii=False))
    if not integrity['valid']:raise SystemExit(1)


if __name__=='__main__':main()
