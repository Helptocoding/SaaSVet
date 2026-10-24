"""Same CI scanner/configuration over full history and the two new tree paths."""
import json
import subprocess
from prepare_wsl import EVIDENCE, WORK, TREE, RTK, environment, save


def main():
    rows=[]
    for label,source,extra in [('history',WORK/'history',[]),('correction',WORK/'security-patch',['--no-git'])]:
        argv=[str(RTK),'proxy',str(WORK/'gitleaks/gitleaks'),'detect','--source',str(source),
              '--config',str(TREE/'.gitleaks.toml'),'--redact','--no-banner','--verbose',
              '--report-format','json','--report-path',str(EVIDENCE/'blocks'/('gitleaks-'+label+'.json')),
              '--exit-code','1',*extra]
        code=subprocess.run(argv,env=environment(),stdin=subprocess.DEVNULL).returncode
        rows.append({'scope':label,'source':str(source),'exit_code':code})
        if code:
            save('security-scopes.json',{'state':'NONPASS','scans':rows});raise SystemExit(code)
    save('security-scopes.json',{'state':'PASS','scans':rows,'redacted':True})


if __name__=='__main__':
    main()
