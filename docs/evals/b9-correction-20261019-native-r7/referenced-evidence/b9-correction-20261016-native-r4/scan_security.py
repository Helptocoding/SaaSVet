"""Run the fixed redacted Windows scanner over sealed history and correction paths."""
import json
import re
import subprocess
from native_support import EVIDENCE, REPO, WORK, TREE, RTK, environment, save, run


def history_state():
    head=run('git','rev-parse','HEAD').decode('utf-8').strip()
    assert re.fullmatch(r'[0-9a-f]{40}',head), 'Unexpected Git HEAD output'
    refs=sorted(run('git','for-each-ref','--format=%(refname) %(objectname)').decode('utf-8').splitlines())
    assert all(re.fullmatch(r'\S+ [0-9a-f]{40}',row) for row in refs), 'Unexpected Git refs output'
    shallow=run('git','rev-parse','--is-shallow-repository').decode('utf-8').strip()
    assert shallow in ('true','false'), 'Unexpected Git shallow output'
    return {'head':head,'refs':refs,'is_shallow':shallow=='true'}


def check_history(label,expected,scans):
    try:
        current=history_state()
        mismatches=[key for key in ('head','refs','is_shallow') if current[key]!=expected[key]]
        if current['is_shallow'] and 'is_shallow' not in mismatches:
            mismatches.append('is_shallow')
        receipt={'state':'PENDING' if mismatches else 'PASS','current':current,
            'mismatches':mismatches,'product_finding_attributed':False}
    except Exception as exc:
        receipt={'state':'PENDING','mismatches':['history_observation_unavailable'],
            'error_type':type(exc).__name__,'error':str(exc),'product_finding_attributed':False}
    save('security-history-'+label+'.json',receipt)
    if receipt['state']!='PASS':
        save('security-scopes.json',{'state':'PENDING','cause':'Sealed Git history changed or could not be verified',
            'history_receipt':'security-history-'+label+'.json','scans':scans,
            'product_finding_attributed':False})
        raise SystemExit(2)


def main():
    expected=json.loads((EVIDENCE/'security-history.json').read_text(encoding='utf-8'))
    assert re.fullmatch(r'[0-9a-f]{40}',expected['head'])
    assert expected['is_shallow'] is False
    assert isinstance(expected['refs'],list) and expected['refs']==sorted(expected['refs'])
    assert all(re.fullmatch(r'\S+ [0-9a-f]{40}',row) for row in expected['refs'])
    rows=[]
    check_history('before',expected,rows)
    for label,source,extra in [('history',REPO,[]),('correction',WORK/'security-patch',['--no-git'])]:
        argv=[str(RTK),'proxy',str(WORK/'gitleaks/gitleaks.exe'),'detect','--source',str(source),
            '--config',str(TREE/'.gitleaks.toml'),'--redact','--no-banner','--verbose',
            '--report-format','json','--report-path',str(EVIDENCE/'blocks'/('gitleaks-'+label+'.json')),
            '--exit-code','1',*extra]
        code=subprocess.run(argv,cwd=REPO,env=environment(),stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW).returncode
        rows.append({'scope':label,'source':str(source),'exit_code':code})
        if label=='history':
            check_history('after',expected,rows)
        if code:
            save('security-scopes.json',{'state':'NONPASS','scans':rows,'redacted':True,
                'classification_required':True,'history_before_after_verified':True})
            raise SystemExit(code)
    save('security-scopes.json',{'state':'PASS','scans':rows,'redacted':True,
        'history_before_after_verified':True,'full_history_verified':True})


if __name__=='__main__':
    main()
