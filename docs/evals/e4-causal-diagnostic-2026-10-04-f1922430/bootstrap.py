"""Prepare new evaluation adapters only; runtime and prior evidence stay frozen."""
import ast
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
OLD = OUT.parent / 'e4-causal-diagnostic-2026-10-04-f1239f89'
KEY = 'f1922430c60348e8adce24196c02bf5a'
OLD_KEY = 'f1239f896754491c8998d56e43356aa1'


def main():
    provenance = {}
    for name in ('infra.py', 'run.py', 'analyze.py', 'finalize.py', 'close.py',
                 'inventory.py', 'report.py', 'PROTOCOL.md'):
        original = (OLD / name).read_bytes()
        source = original.decode('utf-8').replace('\r\n', '\n').replace(OLD_KEY, KEY).replace('35451', '35453')
        if name == 'infra.py':
            start = source.index("    prior = ROOT/'docs/evals/e4-causal-diagnostic-2026-10-03-dded711c'")
            end = source.index('\n\ndef main():', start)
            source = source[:start] + '''    prior_hashes = {}
    prior_root = ROOT/'docs/evals'
    for directory in ('e4-causal-diagnostic-2026-10-03-dded711c',
                      'e4-causal-diagnostic-2026-10-04-f1239f89'):
        prior = prior_root/directory
        manifest = json.loads((prior/'manifest.sha256.json').read_text(encoding='utf-8'))
        for name, expected in manifest['files'].items():
            digest = hashlib.sha256()
            with (prior/name).open('rb') as source_file:
                for block in iter(lambda: source_file.read(1048576), b''):
                    digest.update(block)
            assert digest.hexdigest() == expected['sha256'], (directory, name)
            prior_hashes[directory+'/'+name] = expected['sha256']
        prior_hashes[directory+'/manifest.sha256.json'] = hashlib.sha256((prior/'manifest.sha256.json').read_bytes()).hexdigest()
    preexisting = {}
    for name in ('DEPLOY_VPS_PLAN.md', 'DEPLOY_VPS_STATUS.md', 'skills-lock.json',
                 'docs/auditoria-agente-conversacional-veterinario-2026-09-10.md',
                 'docs/discrepancia-encargo-b9-2026-09-26.md',
                 'docs/evals/e4-bounded-yield-sql-audit-2026-10-01.md'):
        path = ROOT/name
        preexisting[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    return dict(head=HEAD,classification='DIAGNOSTIC_ONLY',protected_files=len(paths),drift=drift,hashes=hashes,
                prior_diagnostic_protection=dict(root=str(prior_root),hashes=prior_hashes),
                preexisting_user_files=preexisting)
''' + source[end:]
        elif name == 'report.py':
            source = source.replace('de la primera ejecución diagnóstica', 'de las dos ejecuciones diagnósticas anteriores')
            source = source.replace('por segunda vez en dos cargas independientes', 'en esta tercera carga independiente')
            source = source.replace('Two independent diagnostic observations corroborate the phase.',
                                    'Independent diagnostic observations corroborate the current-runtime phase only.')
            source = source.replace('La investigación se detiene tras esta clasificación; no hay otra ronda automática.',
                                    'La causa histórica permanece ROOT_CAUSE_NOT_CONFIRMED. La investigación se detiene tras esta clasificación; no hay otra ronda automática.')
        elif name == 'PROTOCOL.md':
            source += '\nEsta tercera corrida tiene identidad propia. Las dos corridas anteriores se verifican y protegen por hash, sin importar sus journals a esta reconstrucción. El objetivo histórico conserva ROOT_CAUSE_NOT_CONFIRMED: el HEAD actual no es el runtime histórico. No se propone una modificación del runtime.\n'
        if name.endswith('.py'):
            ast.parse(source, filename=name)
        with (OUT / name).open('x', encoding='utf-8') as target:
            target.write(source)
        provenance[name] = dict(template_sha256=hashlib.sha256(original).hexdigest(),
                               new_sha256=hashlib.sha256((OUT/name).read_bytes()).hexdigest(),
                               copied_type='EVALUATION_ADAPTER_SOURCE_ONLY')
    with (OUT/'adapter-provenance.json').open('x', encoding='utf-8') as target:
        json.dump(dict(classification='DIAGNOSTIC_ONLY',run_id='causal-'+KEY,
                       receipts_copied=0,journals_copied=0,runtime_modified=False,
                       adapters=provenance), target, indent=2)
    print(json.dumps(dict(key=KEY,directory=str(OUT),port=35453)))


if __name__ == '__main__':
    main()
