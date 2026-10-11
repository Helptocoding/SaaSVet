"""New evaluation adapters only. Never copy receipts or alter runtime sources."""
import ast
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
OLD = OUT.parent/'e4-causal-diagnostic-2026-10-03-dded711c'
OLD_KEY = 'dded711c1ce04cfd8f01af5dc7d62da2'
KEY = 'f1239f896754491c8998d56e43356aa1'


def replace(source, old, new):
    assert old in source, old
    return source.replace(old,new)


def main():
    provenance = {}
    for name in ('infra.py','run.py','analyze.py','finalize.py','close.py','PROTOCOL.md'):
        original = (OLD/name).read_bytes()
        source = original.decode('utf-8').replace(OLD_KEY,KEY).replace('35449','35451')
        if name == 'infra.py':
            source = replace(source,"    assert not drift,drift\n    return dict", """    assert not drift,drift
    prior = ROOT/'docs/evals/e4-causal-diagnostic-2026-10-03-dded711c'
    manifest = json.loads((prior/'manifest.sha256.json').read_text(encoding='utf-8'))
    prior_hashes = {}
    for name, expected in manifest['files'].items():
        digest = hashlib.sha256()
        with (prior/name).open('rb') as source:
            for block in iter(lambda: source.read(1048576), b''):
                digest.update(block)
        assert digest.hexdigest()==expected['sha256'], name
        prior_hashes[name]=expected['sha256']
    prior_hashes['manifest.sha256.json']=hashlib.sha256((prior/'manifest.sha256.json').read_bytes()).hexdigest()
    return dict""")
            source = replace(source,'drift=drift,hashes=hashes)',
                "drift=drift,hashes=hashes,prior_diagnostic_protection=dict(root=str(prior),hashes=prior_hashes))")
        elif name == 'finalize.py':
            source = replace(source," == draft['all_sql_query_count'] == 75600", " == draft['all_sql_query_count']")
            source = replace(source,"    assert len(claims) == len(summaries) == 189 and len(over) == 122\n    assert all(row['organization_id'] == 3 and row['threshold_crossed_before_selection'] for row in over)\n    assert all(row['observable_lock_samples'] == 0 for row in summaries)\n    assert len(corrections) == 22 and len(draft['missed_attempts']) == 20", """    assert len(claims) == len(summaries)
    assert len(corrections) == sum(row['safety'] for row in summaries)
    confirmed = bool(over) and all(row['threshold_crossed_before_selection'] for row in over)
    classification = 'CAUSE_CONFIRMED' if confirmed else 'CAUSE_NOT_CONFIRMED'""")
            source = replace(source,"result_classification='CAUSE_CONFIRMED'", "result_classification=classification")
            source = replace(source,"causal_conclusion='In this new run all 122 claimed inbounds above 10 s cross 10 s before selection_start. '",
                "causal_conclusion=('In this new run all '+str(len(over))+' claimed inbounds above 10 s cross 10 s before selection_start. '")
            source = replace(source,"'the multi-second excess. This confirms the phase, not a historical cause or a uniquely identified tuning change.',",
                "'the multi-second excess. This confirms the phase, not a historical cause or a uniquely identified tuning change.' if confirmed else 'Evidence is complete but requires inspection to attribute excess; no phase is automatically confirmed.'),")
            source = replace(source,"confirmation_scope='NEW_RUN_PRESELECTION_PHASE_ONLY'", "confirmation_scope='NEW_RUN_PRESELECTION_PHASE_ONLY' if confirmed else 'NONE'")
            source = replace(source,"over_10_count=122, crossed_threshold_before_selection=122, bound_memberships=189,",
                "over_10_count=len(over), crossed_threshold_before_selection=sum(row['threshold_crossed_before_selection'] for row in over), bound_memberships=len(summaries),")
            source = replace(source,"no_lock_samples_in_bound_claim_or_selection=True", "no_lock_samples_in_bound_claim_or_selection=all(row['observable_lock_samples']==0 for row in summaries)")
            source = replace(source,"'207 unclaimed noisy inbounds are right-censored; their final latency is not fabricated.'",
                "str(len(draft['unclaimed_inbounds']))+' unclaimed inbounds are right-censored; their final latency is not fabricated.'")
            source = replace(source,"sum(inputs['sent']) == 396", "sum(inputs['sent'])")
            source = replace(source,"corrected_safety_attempts=len(corrections),phases_over_10", "corrected_safety_attempts=len(corrections),phases_over_10")
            source = replace(source,"representative_attempts=[r for r in summaries if r['turn_work_id'] in (4,100,149,189)]",
                "representative_attempts=([min(over,key=lambda row:row['persisted_to_claimed_at_s']), sorted(over,key=lambda row:row['persisted_to_claimed_at_s'])[len(over)//2], max(over,key=lambda row:row['persisted_to_claimed_at_s'])] if over else []) + ([max([r for r in summaries if r['organization_id'] in (1,2)],key=lambda row:row['persisted_to_claimed_at_s'])] if any(r['organization_id'] in (1,2) for r in summaries) else [])")
            source = replace(source,"commit_ms=claim['commit_duration_ms'], claim_result_to_commit_ack_ms_signed=",
                "persisted_to_commit_ack_ms_bounds=metric['persisted_to_commit_ack_ms_bounds'], claim_result_monotonic_ns=claim['claim_result']['monotonic_ns'], commit_start=claim['commit_start'], commit_end=claim['commit'], commit_ack_monotonic_ns=ack_ns, commit_ms=claim['commit_duration_ms'], claim_result_to_commit_ack_ms_signed=")
            source = replace(source,"'claimed_at_to_commit_ack_ms_bounds')", "'claimed_at_to_commit_ack_ms_bounds','persisted_to_commit_ack_ms_bounds')")
        elif name == 'close.py':
            source = replace(source,"    assert report['result_classification'] == 'CAUSE_CONFIRMED'", "    assert report['result_classification'] in ('CAUSE_CONFIRMED','CAUSE_NOT_CONFIRMED')")
            source = replace(source,"                assert wall_persisted_s > 10", "                if report['result_classification']=='CAUSE_CONFIRMED': assert wall_persisted_s > 10")
            source = replace(source,"                assert lower > 10", "                if report['result_classification']=='CAUSE_CONFIRMED': assert lower > 10")
            source = replace(source,"    assert len(utc_checks) == 122", "    assert len(utc_checks) == len(report['over_10_seconds'])")
            source = replace(source," == report['all_sql_query_count'] == 75600", " == report['all_sql_query_count']")
            source = replace(source,"result_classification='CAUSE_CONFIRMED'", "result_classification=report['result_classification']")
            source = replace(source,"min(x['utc_observed_persisted_to_selection_s'] for x in utc_checks)", "min((x['utc_observed_persisted_to_selection_s'] for x in utc_checks),default=None)")
            source = replace(source,"min(x['calibrated_lower_minus_observed_clock_offset_range_s'] for x in utc_checks)", "min((x['calibrated_lower_minus_observed_clock_offset_range_s'] for x in utc_checks),default=None)")
        elif name == 'PROTOCOL.md':
            source = source.replace('Preparación iniciada el 03-10;', 'Preparación iniciada el 04-10;')
            source += '\nEsta es otra ejecución completamente nueva, autorizada el 04-10. La carpeta diagnóstica anterior se protege por sus hashes y no aporta journals/recibos a esta reconstrucción. Las clasificaciones se derivan de los nuevos datos, sin exigir los conteos ni el resultado anterior.\n'
        if name.endswith('.py'):
            ast.parse(source,filename=name)
        with (OUT/name).open('x',encoding='utf-8') as target:
            target.write(source)
        provenance[name] = dict(template_sha256=hashlib.sha256(original).hexdigest(),new_sha256=hashlib.sha256((OUT/name).read_bytes()).hexdigest(),
            copied_type='EVALUATION_ADAPTER_SOURCE_ONLY')
    with (OUT/'adapter-provenance.json').open('x',encoding='utf-8') as target:
        json.dump(dict(classification='DIAGNOSTIC_ONLY',run_id='causal-'+KEY,
            receipts_copied=0,journals_copied=0,runtime_modified=False,adapters=provenance),target,indent=2)
    print(json.dumps(dict(directory=str(OUT),key=KEY,port=35451)))


if __name__=='__main__':
    main()
