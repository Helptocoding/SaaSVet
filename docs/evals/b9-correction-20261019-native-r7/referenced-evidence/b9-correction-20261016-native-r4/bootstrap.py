"""Prepare a new fixed native campaign from the closed r3, without tests."""
import ast
import hashlib
import json
from pathlib import Path
import socket
import subprocess

HERE = Path(__file__).resolve().parent
PRIOR = HERE.with_name('b9-correction-20261016-native-r3')
USER = 'rocede con lo que falte'


def main():
    assert not (HERE / 'native_support.py').exists()
    previous = json.loads((PRIOR / 'final-classification.json').read_text(encoding='utf-8'))
    assert previous['decision'] == 'PENDING'
    assert previous['classification'] == 'ENVIRONMENT_MEMORY_RESERVE_EXHAUSTED'
    assert previous['formal_invocations'] == 1 and previous['formal_reruns'] == 0
    assert json.loads((PRIOR / 'delivery-verification.json').read_text())['state'] == 'PASS'
    assert json.loads((PRIOR / 'native-closure.json').read_text())['state'] == 'PASS'
    assert not Path('C:/Users/LAP/AppData/Local/Temp/b9-native-20261016-r4').exists()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 35488))
    head = subprocess.check_output(['rtk', 'proxy', 'git', 'rev-parse', 'HEAD'], cwd=HERE.parents[2]).decode().strip()
    assert head == '194772677ca4e9fe1a1dec7f4dafa48396a6c583'
    copied = []
    helpers = [p for p in sorted(PRIOR.glob('*.py')) if p.name != 'bootstrap.py']
    helpers.append(PRIOR / 'diagnostics/close_acceptance.py')
    for source in helpers:
        relative = source.relative_to(PRIOR)
        target = HERE / relative
        assert not target.exists()
        text = source.read_text(encoding='utf-8')
        for old, new in [
            ('20261016-native-r3', '20261016-native-r4'),
            ('b9-native-20261016-r3', 'b9-native-20261016-r4'),
            ('native-20261016-r3', 'native-20261016-r4'),
            ('35487', '35488'),
            ('nativo r3', 'nativo r4'), ('nativa r3', 'nativa r4')]:
            text = text.replace(old, new)
        if source.name == 'prepare_native.py':
            text = text.replace("NATIVE_PRIOR = EVIDENCE.with_name('b9-correction-20261016-native-r2')",
                                "NATIVE_PRIOR = EVIDENCE.with_name('b9-correction-20261016-native-r3')")
            text = text.replace("'user': 'continua ya hay mas espacio, necesito ya cerrar el plan de inbox/agente wsp'",
                                "'user': " + repr(USER))
            text = text.replace("'prior_decision': 'PENDING_ENVIRONMENT_DISK_RESERVE_EXHAUSTED'",
                                "'prior_decision': 'PENDING_ENVIRONMENT_MEMORY_RESERVE_EXHAUSTED'")
        elif source.name == 'finalize_preflight.py':
            text = text.replace("prior = EVIDENCE.with_name('b9-correction-20261016-native-r2')",
                                "prior = EVIDENCE.with_name('b9-correction-20261016-native-r3')")
            text = text.replace("fromfile='native-r2/'", "fromfile='native-r3/'")
            text = text.replace('../b9-correction-20261016-native-r2/native-preflight.json',
                                '../b9-correction-20261016-native-r3/native-preflight.json')
        ast.parse(text, filename=str(target))
        compile(text, str(target), 'exec')
        assert not any(line.rstrip() != line for line in text.splitlines()), relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8', newline='\n')
        copied.append({'path': relative.as_posix(),
            'prior_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    record = {'state': 'NEW_NATIVE_CAMPAIGN_PREPARATION', 'user': USER,
        'date_local': '2026-10-16', 'previous_campaign': PRIOR.name,
        'previous_decision': previous, 'prior_formal_results_transferred': False,
        'candidate_tree': '196aceb4f5f234c086b96d8e8af93787613f3c25',
        'tests_or_product_changes_authorized': False, 'wsl_invoked': False,
        'new_workspace': 'C:/Users/LAP/AppData/Local/Temp/b9-native-20261016-r4',
        'private_postgresql_port': 35488, 'copied_helpers': copied,
        'adaptations': ['New campaign identity, own workspace and private PostgreSQL port',
            'Final native helpers from closed r3; original fixed contract templates from r4',
            'No prior results, invocations, stops, incident receipts or control files copied',
            'Same candidate, inventory, partitions, assertions, workloads and resource guards',
            'Same bounded auxiliary lifetimes as the immediately preceding native campaign']}
    (HERE / 'resumption.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('NATIVE_RESUMPTION_PREPARED', len(copied), flush=True)


if __name__ == '__main__':
    main()
