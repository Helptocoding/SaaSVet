"""Seal physical attempts, exact missing requirements and final integrity."""
import hashlib
import json
import re
import runpy
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
lab = runpy.run_path(str(HERE/'orchestration/lab.py'))
read, write, sha = lab['read'], lab['write'], lab['sha']
ROOT = lab['ROOT']
EXPECTED = {
    'R1-01': ['ordinary'], 'R1-02': ['balanced'], 'R1-03': ['unequal'],
    'R1-04': ['forecasts'], 'R1-05': ['simultaneous', 'concentrated'],
    'R1-06': ['backlog'],
    'R1-07': ['w1_w2', 'deadline_before', 'deadline_at', 'deadline_after', 'no_poll', 'legacy_null'],
    'R2-01': ['slow'], 'R2-02': ['blocked'], 'R2-03': ['precommit'],
    'R2-04': ['postcommit'], 'R2-05': ['retry', 'exhaustion'], 'R2-06': ['restart'],
    'R2-07': ['org_lock', 'message_lock', 'outer_rollback', 'savepoint_rollback', 'lost_ack'],
    'R2-08': ['safety_before', 'safety_after', 'takeover_before', 'takeover_after', 'w1_w2'],
    'R2-09': ['slow_meta', 'uncertain_meta'],
    'R2-10': ['expired_consent', 'expired_authority', 'cross_tenant', 'closed_gate'],
}
# Explicit conditions of D29 section 6; finite cases retain their accepted scope.
REQUIRES_BASE_LOAD = {'R1-03','R1-04','R1-05','R1-06','R2-01','R2-02','R2-04','R2-09'}


def ref(path):
    return dict(path=str(path.relative_to(HERE)) if path.is_relative_to(HERE) else str(path), sha256=sha(path))


def unit_summary(log):
    value = log.read_text(encoding='utf-8')
    count = re.search(r'Ran (\d+) tests', value)
    skipped = re.search(r'OK \(skipped=(\d+)\)', value)
    return dict(tests=int(count[1]) if count else None,
                skipped=int(skipped[1]) if skipped else 0, receipt=ref(log))


def main():
    regression = runpy.run_path(str(HERE/'final_regression.py'))
    regression['main']()
    audit = runpy.run_path(str(HERE/'audit_attempts.py'))
    audit['main']()
    runpy.run_path(str(HERE/'clock_capture_audit.py'))['main']()
    sender_queue=runpy.run_path(str(HERE/'audit_sender_queue.py'))['main']()
    groups = [read(HERE/name)['results'] for name in
              ('individual-result.json','matrix-physical-result.json','matrix-existing-result.json')]
    individual, physical, existing = groups
    original_matrix = physical+existing
    matrix=[]
    for original_row in original_matrix:
        row=dict(original_row)
        if row['case_id']=='R2-09':
            extra=next(v for v in sender_queue if v['run_id']==row['run_id'])
            row['supplemental_physical_requirement']=extra
            row['original_verifier_status']=row['status']
            if extra['status']!='PHYSICALLY_ACCREDITED':
                row['status']='NOT_ACCREDITED'
                row['errors']=row.get('errors',[])+extra['errors']
                row['load_condition']=dict(row.get('load_condition',{}),status='NOT_ACCREDITED',
                    supplemental_requirement='ORDINARY_READY_QUEUE_DURING_AFFECTED_META')
        matrix.append(row)
    by_case = defaultdict(list)
    for row in matrix:
        by_case[row['case_id']].append(row)
    cases = {}
    for case, variants in EXPECTED.items():
        rows = by_case[case]
        seen = [r['variant'] for r in rows]
        complete = sorted(seen)==sorted(variants)
        finite = complete and all(r['status']=='PHYSICALLY_ACCREDITED' for r in rows)
        frontier = complete and all(r.get('physical_frontier',{}).get('status')=='PHYSICALLY_ACCREDITED'
                                    for r in rows)
        load = (all(r.get('load_condition',{}).get('status')=='PHYSICALLY_ACCREDITED' for r in rows)
                if case in REQUIRES_BASE_LOAD else None)
        full = finite and (load if case in REQUIRES_BASE_LOAD else True)
        cases[case] = dict(required_variants=variants, observed_variants=seen,
                          all_variants_attempted=complete, fresh_physical_checks_passed=finite,
                          physical_frontier_accredited=frontier,
                          requires_base_load=case in REQUIRES_BASE_LOAD,
                          complete_load_accredited=load, full_requirement_accredited=full,
                          results=rows)
    unit = read(HERE/'unit-regression.json')
    negative = read(HERE/'receipt-negative-regression.json')
    final_d29 = read(HERE/'final-d29-regression.json')
    application = read(HERE/'application-regression.json')
    cleanup = read(HERE/'lab-cleanup.json')
    attempt_cleanup_paths=sorted(HERE.glob('*/*-database-cleanup.json'))
    attempt_cleanup=dict(expected_attempts=len(individual)+len(matrix),
                         receipts=len(attempt_cleanup_paths),
                         all_removed=all(read(p).get('removed') is True and
                                         read(p).get('created_by_this_run') is True
                                         for p in attempt_cleanup_paths),
                         evidence=[ref(p) for p in attempt_cleanup_paths])
    attempt_cleanup['complete']=(attempt_cleanup['receipts']==attempt_cleanup['expected_attempts']
                                 and attempt_cleanup['all_removed'])
    integrity = read(HERE/'final-integrity.json')
    full = (len(cases)==17 and len(matrix)==36 and all(c['full_requirement_accredited'] for c in cases.values())
            and unit['exit_code']==negative['exit_code']==final_d29['exit_code']==0 and application['status']=='PASS'
            and all(cleanup.values()) and attempt_cleanup['complete'] and integrity['intact'])
    # No prediction/model status participates in this decision.
    state = 'FULL_CONTROLLER_ACCREDITED' if full else 'FULL_LIVE_MATRIX_NOT_READY'
    pending = {c:v for c,v in cases.items() if not v['full_requirement_accredited']}
    frozen = read(HERE/'frozen-sources.json')
    source_errors = [p for p,h in frozen.items() if sha(ROOT/p)!=h or sha(HERE/'frozen-sources'/p)!=h]
    orchestration = read(HERE/'orchestration-seal.json')
    source_errors += [n for n,h in orchestration.items() if sha(HERE/'orchestration'/n)!=h]
    revision = read(HERE/'orchestration-v2-seal.json')
    source_errors += ['v2/'+n for n,h in revision.items() if sha(HERE/'orchestration-v2'/n)!=h]
    causal_revision = read(HERE/'orchestration-v3-seal.json')
    source_errors += ['v3/'+n for n,h in causal_revision.items() if sha(HERE/'orchestration-v3'/n)!=h]
    sender_revision = read(HERE/'orchestration-v4-seal.json')
    source_errors += ['v4/'+n for n,h in sender_revision.items() if sha(HERE/'orchestration-v4'/n)!=h]
    if source_errors:
        raise RuntimeError('Evaluation sources changed: '+str(source_errors))
    result = dict(schema='d29-dependent-final-physical-matrix-v1',
        baseline=lab['BASE'], global_status='CONTROLLER_CORE_VALIDATED / '+state,
        confirmed_base_status='CONFIRMED_BASE_ESTABLISHED',
        confirmed_base_reference=ref(lab['BASE_DIR']/'confirmed-base-receipt.json'),
        accepted_base_configuration=read(lab['BASE_DIR']/'confirmed-base-receipt.json')['configuration'],
        base_recalibrated=False,new_base_generated=False, characterization=False,
        maximum_capacity=None,sustainable_envelope=None,commercial_capacity=None,
        synthetic_evidence=[],individual_results=individual, cases=cases,
        scenario_count=len(cases),required_variant_count=36,attempted_variant_count=len(matrix),
        fresh_physical_variants_passed=sum(r['status']=='PHYSICALLY_ACCREDITED' for r in matrix),
        original_verifiers_passed=sum(r['status']=='PHYSICALLY_ACCREDITED' for r in original_matrix),
        full_scenarios_accredited=sum(c['full_requirement_accredited'] for c in cases.values()),
        full_controller_accredited=full, pending_scenarios=list(pending),
        regression=dict(unit=dict(unit,**unit_summary(HERE/'unit-regression.log')),
                        negative=dict(negative,**unit_summary(HERE/'receipt-negative-regression.log')),
                        final_d29=final_d29,
                        application=application),
        cleanup=cleanup, attempt_cleanup=attempt_cleanup,
        integrity=dict(intact=integrity['intact'],protected_source_count=len(integrity['protected_sources']),
                                        accepted_evidence=integrity['previous_evidence'],receipt=ref(HERE/'final-integrity.json')),
        sources=dict(frozen=ref(HERE/'frozen-sources.json'),orchestration=ref(HERE/'orchestration-seal.json'),
                     observer_revision=ref(HERE/'observer-revision.json'),
                     burst_orchestration=ref(HERE/'orchestration-v2-seal.json'),
                     causal_observer_revision=ref(HERE/'causal-observer-revision.json'),
                     causal_orchestration=ref(HERE/'orchestration-v3-seal.json'),
                     sender_verifier_revision=ref(HERE/'sender-verifier-revision.json'),
                     final_orchestration=ref(HERE/'orchestration-v4-seal.json'),errors=source_errors),
        interruption_recovery=ref(HERE/'interruption-recovery.json'),
        actual_attempt_audit=ref(HERE/'actual-attempt-audit.json'),
        clock_capture_audit=ref(HERE/'clock-capture-audit.json'),
        host_clock_events=ref(HERE/'host-clock-events.json'),
        causal_observer_negative_preflight=ref(HERE/'causal-observer-preflight.json'),
        sender_verifier_preflight=ref(HERE/'sender-verifier-preflight.json'),
        sender_queue_verification=ref(HERE/'sender-queue-overlap-verification.json'),
        failed_attempts_preserved=True,runtime_b8_b9_e4_changed=False,contracts_changed=False,commits_created=0,
        modified_scope=dict(directory=str(HERE),production_source_files=[],contract_files=[],
                            description='ONLY_NEW_EVALUATION_INFRASTRUCTURE_REPORTS_AND_CAPTURE_ARTIFACTS'),
        stop_after_this_phase=True)
    write(HERE/'final-receipt.json',result)
    summary = ['# D29: resultado del consumo de CONFIRMED_BASE','',
               '**'+result['global_status']+'**. Base aceptada íntegra; no se generó ni recalibró otra base.',
               '', '| Primeros intentos individuales | Resultado | Causa / evidencia |',
               '| --- | --- | --- |']
    for r in individual:
        summary.append('| '+r['case_id']+' '+r['variant']+' | '+r['status']+' | '+
                       '; '.join(r.get('errors',[]))+'; `'+r.get('receipt','')+'` |')
    summary += ['', 'El primer burst simultáneo conserva su fallo de captura. El observador v2 '+
                'registra la activación antes del inicio monotónico real de la ventana; las tasas, '+
                'duración, oferta y procesos permanecen intactos. Los resultados de cierre proceden '+
                'de la matriz con las fuentes finales, sin sobrescribir el intento anterior.',
                '', 'La revisión v3 añade testigos previos/posteriores de R1-04. La revisión v4 '+
                'corrige exclusivamente la inicialización de Django en el verificador de R2-09 '+
                'antes de su ejecución; no cambia la ejecución física de los demás casos. '+
                'Cada intento conserva los hashes de la revisión que realmente ejecutó.',
                '', 'La matriz intentó '+str(len(matrix))+' variantes requeridas de 17 escenarios. '+
                str(result['fresh_physical_variants_passed'])+' verificaciones físicas recientes pasaron. '+
                str(result['full_scenarios_accredited'])+' escenarios satisfacen sus requisitos completos en estas fuentes. '+
                'No se confunde la frontera finita con la condición completa de carga.', '',
                '| Escenario | Variantes intentadas | Frontera física reciente | Condición completa |',
                '| --- | --- | --- | --- |']
    for c,v in cases.items():
        summary.append('| '+c+' | '+str(len(v['results']))+'/'+str(len(v['required_variants']))+' | '+
                       ('PASÓ' if v['physical_frontier_accredited'] else 'NOT_ACCREDITED')+' | '+
                       ('ACREDITADA' if v['full_requirement_accredited'] else 'NOT_ACCREDITED')+' |')
    summary += ['', 'Requisitos que siguen pendientes:', '',
                '| Escenario / variante | Motivo observado | Receipt |',
                '| --- | --- | --- |']
    for c,v in pending.items():
        for row in v['results']:
            if row['status']=='PHYSICALLY_ACCREDITED' and (
                    c not in REQUIRES_BASE_LOAD or row.get('load_condition',{}).get('status')=='PHYSICALLY_ACCREDITED'):
                continue
            reasons=list(row.get('errors',[]))
            if row.get('cause'):
                reasons.append(str(row['cause']))
            load_reason=row.get('load_condition',{}).get('reason')
            if load_reason:
                reasons.append(load_reason)
            for gate_name,gate in row.get('load_condition',{}).get('gates',{}).items():
                for detail in gate.get('missing',[])+gate.get('violations',[]):
                    reasons.append(gate_name+': '+detail)
            summary.append('| '+c+' '+row['variant']+' | '+('; '.join(reasons) or 'Requisito físico completo sin acreditar')+
                           ' | `'+row.get('receipt','')+'` |')
    summary += ['', 'Regresión D29 final: '+str(final_d29['tests'])+' tests, '+str(final_d29['skipped'])+
                ' omitidos; exit '+str(final_d29['exit_code'])+'. Se conserva también la regresión inicial: '+
                str(result['regression']['unit']['tests'])+' tests, '+
                str(result['regression']['unit']['skipped'])+' omitidos inicialmente; los '+
                str(result['regression']['negative']['tests'])+' checks físicos omitidos se ejecutaron después contra receipts preservados. '+
                'Exit codes: '+str(unit['exit_code'])+'/'+str(negative['exit_code'])+'.',
                '', 'Regresión de aplicación: `'+application['status']+'`; resultado completo en `application-regression.json`.',
                '', 'Cleanup privado e integridad verificados. Baseline, '+str(len(integrity['protected_sources']))+
                ' fuentes protegidas y todos los artefactos históricos sellados permanecen íntegros. Cero commits.',
                '', 'Todos los intentos, incluidos fallos y rechazos de preparación, se conservan. '+
                'Los detalles causales y decisiones propuestas están en [blockers-and-decisions.md](blockers-and-decisions.md). '+
                'No se inicia una fase posterior ni se calcula E.',
                '', 'Receipt completo: [final-receipt.json](final-receipt.json). '+
                'Índice de hashes: [artifact-index.json](artifact-index.json).']
    (HERE/'report.md').write_text('\n'.join(summary)+'\n',encoding='utf-8')
    index = {p.relative_to(HERE).as_posix():dict(bytes=p.stat().st_size,sha256=sha(p))
             for p in sorted(HERE.rglob('*')) if p.is_file() and p.name!='artifact-index.json'}
    write(HERE/'artifact-index.json',index)
    print(json.dumps(dict(global_status=result['global_status'],variants=len(matrix),pending=list(pending),
                          artifacts=len(index),commits=0)),flush=True)


if __name__=='__main__':
    main()
