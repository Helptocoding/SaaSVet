"""One redacted verification of the exact historical allowlist, plus a negative control."""
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import time

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
RTK = shutil.which('rtk')
SCANNER = OUT / 'runtime/gitleaks/gitleaks.exe'


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def git(*args):
    return subprocess.check_output([RTK, 'proxy', 'git', *args], cwd=ROOT).decode().strip()


def history():
    return dict(head=git('rev-parse', 'HEAD'),
                refs=sorted(git('for-each-ref', '--format=%(refname) %(objectname)').splitlines()),
                shallow=git('rev-parse', '--is-shallow-repository'))


def scan(label, source, *, no_git=False):
    report = OUT / ('gitleaks-' + label + '.json')
    assert not report.exists(), 'Formal scan cannot be silently repeated'
    args = [RTK, 'proxy', str(SCANNER), 'detect', '--source', str(source),
            '--config', str(ROOT / '.gitleaks.toml'),
            '--gitleaks-ignore-path', str(ROOT / '.gitleaksignore'),
            '--redact', '--no-banner', '--no-color', '--report-format', 'json',
            '--report-path', str(report), '--exit-code', '1']
    if no_git:
        args.append('--no-git')
    started = time.monotonic()
    with (OUT / ('gitleaks-' + label + '.log')).open('wb') as log:
        result = subprocess.run(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    findings = json.loads(report.read_text(encoding='utf-8')) if report.exists() else None
    return dict(scope=label, exit_code=result.returncode, seconds=time.monotonic()-started,
                findings=None if findings is None else len(findings), redacted=True,
                report=report.name, argv=args)


def main():
    assert not (OUT / 'security-verification.json').exists()
    before = history()
    assert before['shallow'] == 'false'
    policy = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
              for p in ('.gitleaks.toml', '.gitleaksignore')}
    save('security-history-before.json', before)
    # A new synthetic value in a previously waived filename must still be caught.
    control = OUT / 'runtime/scanner-control'
    control.mkdir(parents=True, exist_ok=False)
    fixture = control / 'backend/apps/agent/tests/test_b9a_e2e.py'
    fixture.parent.mkdir(parents=True)
    fixture.write_text('api_key = "' + secrets.token_urlsafe(40) + '"\n', encoding='utf-8')
    negative = scan('negative-control', control, no_git=True)
    assert negative['exit_code'] == 1 and negative['findings'] >= 1, 'Detector negative control failed'
    formal = scan('history', ROOT)
    after = history()
    save('security-history-after.json', after)
    unchanged = before == after and all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h
                                      for p, h in policy.items())
    state = 'PENDING' if not unchanged else ('PASS' if formal['exit_code'] == 0 and formal['findings'] == 0 else 'FAIL')
    result = dict(state=state, historical_r12_fail_preserved=True,
                  scope='HEAD ancestry, identical default Gitleaks CI scope; full Git refs observed before/after',
                  policy=policy, negative_control=negative, formal=formal,
                  history_and_policy_unchanged=unchanged, current_uncommitted_tree_certified=False)
    save('security-verification.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('negative_control', 'formal')}), flush=True)
    return 0 if state == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
